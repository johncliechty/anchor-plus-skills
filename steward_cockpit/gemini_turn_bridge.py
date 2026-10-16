"""Subscription Gemini transport (the agy / Antigravity CLI) using the bounded, owned Steward broker.

agy 1.3.x (2026-10-07) runs one headless turn per process: ``agy --input-format stream-json --output-format
stream-json -p=`` reads ONE NDJSON message on stdin - ``{"event": "user", "message": {"role": "user", "content":
"..."}}`` (an 80 KB prompt proven) - and streams ``init`` / ``step_update`` / ``result`` events. A later turn resumes
the same conversation with ``--conversation <id>`` (proven: it remembers across processes). The prompt goes over
stdin, so no prompt file exists. agy signs in from the Windows keyring (the Antigravity login), never an API key.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import uuid
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit.codex_turn_bridge import (
    Broker, BridgeError, DEFAULT_TURN_TIMEOUT_SECONDS, DEFAULT_IDLE_TIMEOUT_SECONDS, EventNormalizer,
    MAX_INPUT_BYTES, _bounded_string, _identifier, emit_json,
)
from steward_cockpit.grok_turn_bridge import _skill_token


PERMISSION_MODES = ("plan", "acceptEdits", "bypassPermissions", "dontAsk", "default")
_AUTH_FAILURE = re.compile(r"(?i)(not logged in|log in to antigravity|unauthori[sz]ed|unauthenticated|\b401\b|\b403\b)")


def canonical_conversation_id(value: Any) -> str:
    if not isinstance(value, str):
        raise BridgeError("Gemini conversation ID must be a UUID")
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise BridgeError("Gemini conversation ID must be a UUID") from exc
    if parsed != value.lower():
        raise BridgeError("Gemini conversation ID must be a canonical UUID")
    return parsed


def agy_model(model: str, effort: str) -> str:
    """agy encodes the effort in the model id (gemini-3.8-flash-high); the policy names the base and the effort."""
    try:
        import model_policy
        return model_policy.agy_model_id(model, effort)
    except ImportError:          # the bridge also runs from its own folder in tests
        return f"{model}-{effort}" if effort and not re.search(r"-(minimal|low|medium|high|xhigh|max)$", model) else model


def build_argv(executable: str, *, model: str, effort: str, permission_mode: str, conversation_id: str | None) -> list[str]:
    _identifier(model, "model")
    _identifier(effort, "effort")
    if permission_mode not in PERMISSION_MODES:
        raise BridgeError("Unsupported Gemini permission mode")
    argv = [executable, "--input-format", "stream-json", "--output-format", "stream-json",
            "--model", agy_model(model, effort)]
    if permission_mode == "plan":
        argv += ["--mode", "plan"]
    elif permission_mode == "acceptEdits":
        argv += ["--mode", "accept-edits"]
    elif permission_mode in ("bypassPermissions", "dontAsk"):
        argv.append("--dangerously-skip-permissions")
    if conversation_id is not None:
        argv += ["--conversation", canonical_conversation_id(conversation_id)]
    # The empty attached prompt selects print mode; the turn's prompt arrives on stdin.
    argv.append("-p=")
    return argv


def stdin_message(encoded_prompt: bytes) -> bytes:
    text = encoded_prompt.decode("utf-8").rstrip("\n")
    return (json.dumps({"event": "user", "message": {"role": "user", "content": text}}) + "\n").encode("utf-8")


_WRITE_TOOLS = ("write_to_file", "replace_file_content", "multi_replace_file_content", "Write", "Edit", "NotebookEdit")


class GeminiNormalizer(EventNormalizer):
    provider_label = "Gemini"

    def __init__(self, model: str, effort: str, *, resume: str | None = None):
        super().__init__(model, effort, resume)
        self.expected_id = canonical_conversation_id(resume) if resume else None
        self._tool_steps: set[int] = set()
        self._write_steps: set[int] = set()
        self._completed_write_steps: set[int] = set()
        self._streamed = ""

    def _receipt(self):
        receipt = super()._receipt()
        receipt["provider"] = "gemini"
        # agy echoes the model it was asked to run in its init event; it does not report a served model.
        receipt["model_source"] = None if self.model_served is None else "cli-recorded"
        return receipt

    def _text_delta(self, text: str):
        if not text:
            return []
        self.text.append(text)
        self._streamed += text
        return [{"type": "stream_event", "session_id": self.thread_id, "event": {
            "type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text},
        }}]

    def _tool(self, step: dict[str, Any]):
        index = step.get("step_index")
        if not isinstance(index, int) or isinstance(index, bool):
            return []
        state = step.get("state")
        if index in self._tool_steps:
            if index in self._write_steps and index not in self._completed_write_steps and state in ("DONE", "ERROR"):
                self._completed_write_steps.add(index)
                return [{"type": "user", "session_id": self.thread_id, "message": {
                    "role": "user", "content": [{"type": "tool_result", "tool_use_id": f"{self.thread_id}:{index}",
                        "is_error": state != "DONE"}],
                }}]
            return []
        self._tool_steps.add(index)
        info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
        name = _bounded_string(step.get("tool_name") or info.get("name"), 120) or "gemini_tool"
        params = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}
        payload = {"provider_tool": name}
        if name in _WRITE_TOOLS:
            fp = _bounded_string(
                params.get("TargetFile") or params.get("file_path") or params.get("AbsolutePath") or params.get("path"),
                500,
            )
            if fp:
                payload["file_path"] = fp
                self._write_steps.add(index)
        skill = _skill_token(name, *[v for v in params.values() if isinstance(v, str)])
        if skill:
            payload["skill"] = skill   # the cockpit marks the skill in use; the folder's name only
        events = [{"type": "assistant", "session_id": self.thread_id, "message": {
            "role": "assistant", "content": [{"type": "tool_use", "id": f"{self.thread_id}:{index}",
                "name": name, "input": payload}],
        }}]
        if index in self._write_steps and state in ("DONE", "ERROR"):
            self._completed_write_steps.add(index)
            events.append({"type": "user", "session_id": self.thread_id, "message": {
                "role": "user", "content": [{"type": "tool_result", "tool_use_id": f"{self.thread_id}:{index}",
                    "is_error": state != "DONE"}],
            }})
        return events

    def accept(self, event: dict[str, Any]):
        if self._finished:
            raise BridgeError("Gemini event received after its result was finalized")
        if not isinstance(event, dict):
            raise BridgeError("Gemini event must be an object")
        kind = event.get("event")
        if kind == "init":
            conversation = canonical_conversation_id(event.get("conversation_id"))
            if self.expected_id is not None and conversation != self.expected_id:
                raise BridgeError("Gemini resumed an unexpected conversation")
            init = event.get("init") if isinstance(event.get("init"), dict) else {}
            model = init.get("model")
            if isinstance(model, str) and model and len(model) <= 256:
                self.model_served = model
            self.thread_id = conversation
            if self._initialized:
                return []
            self._initialized = True
            return [{"type": "system", "subtype": "init", "session_id": self.thread_id, **self._receipt()}]
        if not self._initialized:
            if kind == "result":     # agy refused before starting a conversation (bad flag, no login)
                return self._result(event)
            raise BridgeError("Gemini emitted turn data before its conversation was confirmed")
        if kind == "step_update":
            step = event.get("step_update")
            if not isinstance(step, dict):
                raise BridgeError("Malformed Gemini step update")
            if step.get("conversation_id") not in (None, self.thread_id):
                raise BridgeError("Gemini emitted an unexpected conversation identity")
            if step.get("step_type") == "agent_response":
                delta = step.get("text_delta")
                if delta is not None and not isinstance(delta, str):
                    raise BridgeError("Malformed Gemini text delta")
                return self._text_delta(delta or "")
            if step.get("step_type") == "tool":
                return self._tool(step)
            return []      # user echo, thinking and planning steps are never conversation text
        if kind == "result":
            return self._result(event)
        return []

    def _result(self, event: dict[str, Any]):
        if self.terminal == "failed":
            return []
        result = event.get("result")
        if not isinstance(result, dict):
            raise BridgeError("Malformed Gemini result")
        conversation = result.get("conversation_id")
        if self.thread_id is None and isinstance(conversation, str):
            try:
                self.thread_id = canonical_conversation_id(conversation)
            except BridgeError:
                pass
        status = result.get("status")
        if not isinstance(status, str):
            raise BridgeError("Gemini result omitted its status")
        self.terminal = "completed" if status == "SUCCESS" else "failed"
        usage = result.get("usage")
        if isinstance(usage, dict):
            mapped = {"input_tokens": usage.get("input_tokens"),
                      "output_tokens": (usage.get("output_tokens") or 0) + (usage.get("thinking_tokens") or 0),
                      "cache_read_input_tokens": usage.get("cache_read_tokens")}
            self.usage = {k: v for k, v in mapped.items() if isinstance(v, int) and not isinstance(v, bool) and v >= 0}
        if self.terminal == "failed":
            message = _bounded_string(result.get("error")) or f"Gemini reported status {status}"
            self.error_message = message[:2000]
            self.error_code = "auth_required" if _AUTH_FAILURE.search(message) else "provider_error"
            return []
        response = result.get("response")
        if isinstance(response, str) and response.startswith(self._streamed):
            return self._text_delta(response[len(self._streamed):]) if not self._streamed else []
        return []

    def finish(self, *args, **kwargs):
        result = super().finish(*args, **kwargs)
        if result is not None and result.get("error", {}).get("code") == "unconfirmed_turn":
            message = "Gemini exited before a successful turn was confirmed"
            result["error"]["message"], result["errors"] = message, [message]
        return result


class GeminiBroker(Broker):
    provider_label = "Gemini"

    def __init__(self, **kwargs):
        if not kwargs.get("executable"):
            kwargs["executable"] = shutil.which("agy.exe" if os.name == "nt" else "agy") or shutil.which("agy")
            if not kwargs["executable"]:
                raise BridgeError("Subscription Gemini CLI (agy) is not installed")
        super().__init__(**kwargs)

    def _validate_launch(self, executable, model, effort, permission_mode, resume):
        build_argv(executable, model=model, effort=effort, permission_mode=permission_mode, conversation_id=resume)

    def _make_normalizer(self):
        return GeminiNormalizer(self.model, self.effort, resume=self.thread_id)

    def _prepare_prompt(self, encoded_prompt):
        return build_argv(self.executable, model=self.model, effort=self.effort,
                          permission_mode=self.permission_mode, conversation_id=self.thread_id), stdin_message(encoded_prompt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--permission-mode", required=True, choices=PERMISSION_MODES)
    parser.add_argument("--resume")
    parser.add_argument("--turn-timeout-seconds", type=float, default=DEFAULT_TURN_TIMEOUT_SECONDS)
    parser.add_argument("--idle-timeout-seconds", type=float, default=DEFAULT_IDLE_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        broker = GeminiBroker(target=args.target, model=args.model, effort=args.effort,
                              permission_mode=args.permission_mode, resume=args.resume,
                              turn_timeout_seconds=args.turn_timeout_seconds,
                              idle_timeout_seconds=args.idle_timeout_seconds)
    except BridgeError as exc:
        emit_json({"type": "result", "is_error": True, "replay_safe": True, "provider": "gemini",
                   "model_attested": False, "error": {"code": "setup_error", "message": str(exc)}})
        return 2

    def on_signal(_signum, _frame):
        broker.stop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, on_signal)
    try:
        while not broker._stop.is_set():
            raw = sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1)
            if not raw:
                break
            if len(raw) > MAX_INPUT_BYTES:
                emit_json({"type": "result", "is_error": True, "replay_safe": True,
                           "model_attested": False, "error": {"code": "input_too_large",
                           "message": "Input envelope exceeds the byte limit"}})
                return 2
            try:
                envelope = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                emit_json({"type": "result", "is_error": True, "replay_safe": True,
                           "model_attested": False, "error": {"code": "invalid_input",
                           "message": "Input envelope must be UTF-8 JSON"}})
                continue
            broker.turn(envelope)
    finally:
        broker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

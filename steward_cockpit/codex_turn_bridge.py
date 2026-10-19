"""Subscription Codex exec/resume transport for the persistent Steward protocol.

The broker accepts user JSONL on stdin and emits the small Claude-compatible
event subset consumed by Engine. Prompts travel through stdin only. Model and
permission decisions are frozen by the parent; this module never chooses a
different provider, model, effort, session, or permission level.

Native Windows children start suspended, enter an owned kill-on-close job, and
only then resume. POSIX children use a new process group; that cannot prove
containment of descendants that deliberately create another session. Tests and
embedding hosts may inject a compatible ``process_guard_factory``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from model_policy import launch_args, policy_environment


# Codex events are parsed incrementally. Unused tool payloads are validated and
# discarded; full assistant text is preserved. Neither frames nor productive
# turns have a default output quota. The reader queue holds four projections.
MAX_EVENT_BYTES = None
MAX_GROK_EVENT_BYTES = 16 * 1024 * 1024
MAX_TURN_BYTES = None
MAX_INPUT_BYTES = 8 * 1024 * 1024
DEFAULT_TURN_TIMEOUT_SECONDS = 7200
DEFAULT_IDLE_TIMEOUT_SECONDS = 900
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
PERMISSIONS = {
    "plan": "read-only",
    "acceptEdits": "workspace-write",
    "bypassPermissions": "danger-full-access",
    # two-lane step 3 (2026-10-06): writes only inside the steward's folder, localhost reachable for the hand-off tools
    "fenced": "workspace-write",
}
FENCE_CONFIG = (
    "-c", "sandbox_workspace_write.network_access=true",
    "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
    "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
    "-c", 'windows.sandbox="unelevated"',
)


_SKILL_FOLDER_RE = re.compile(r"(?:^|[\\/\s\"'])skills[\\/]([A-Za-z0-9_.-]{1,40})[\\/]", re.I)


def _skill_token(*values):
    """The skill folder's NAME from a command or path (a derived token, never the command itself)."""
    for value in values:
        if isinstance(value, str) and value:
            m = _SKILL_FOLDER_RE.search(value)
            if m:
                return m.group(1)
    return ""

class BridgeError(ValueError):
    """Invalid input or an unsafe/malformed provider protocol response."""


class OutputLimitError(BridgeError):
    """Provider output exceeded an Anchor transport size bound."""


class TurnTimeout(BridgeError):
    """The bounded native turn deadline expired."""


class TurnWatchdog:
    """Bound a turn by both elapsed time and time since meaningful progress.

    The caller decides which native events count as progress. Observed expiry
    is permanent: neither subsequent events nor a clock rollback can revive it.
    """

    def __init__(self, wall_seconds, idle_seconds, *, clock=time.monotonic, provider_label="Codex"):
        for name, value in (("wall_seconds", wall_seconds), ("idle_seconds", idle_seconds)):
            # The upper bound also rejects infinities; NaN fails this ordered
            # comparison. Check before float conversion to handle huge ints.
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 43200:
                raise ValueError(f"{name} must be a finite number greater than 0 and at most 43200")
        self.wall_seconds = float(wall_seconds)
        self.idle_seconds = float(idle_seconds)
        self._clock = clock
        self.provider_label = str(provider_label)
        self._started = clock()
        self._last_progress = self._started
        self._expired = None

    def _remaining_at(self, now):
        if self._expired is not None:
            raise self._expired
        elapsed = max(0.0, now - self._started)
        idle = max(0.0, now - self._last_progress)
        if elapsed >= self.wall_seconds:
            kind = "wall_limit"
            explanation = f"reached its {self.wall_seconds:g}s wall-clock limit"
        elif idle >= self.idle_seconds:
            kind = "inactivity"
            explanation = f"had no meaningful native progress for its {self.idle_seconds:g}s inactivity limit"
        else:
            return min(self.wall_seconds - elapsed, self.idle_seconds - idle)
        error = TurnTimeout(
            f"{self.provider_label} turn {explanation} "
            f"(elapsed {elapsed:.1f}s; idle {idle:.1f}s)."
        )
        error.kind = kind
        error.elapsed = elapsed
        error.idle = idle
        self._expired = error
        raise error

    def remaining(self):
        """Return positive seconds until the next deadline, or raise."""
        return self._remaining_at(self._clock())

    def progress(self):
        """Record meaningful progress only if neither deadline has expired."""
        now = self._clock()
        self._remaining_at(now)
        self._last_progress = now


class WindowsJobGuard:
    """Adapter for Anchor's verified owned-process Windows job helper."""

    requires_suspended = True
    containment = {"mode": "windows_job", "descendants_verified": True, "degraded": False}

    def __init__(self, process: Any, *, job_factory: Callable[[], Any] | None = None):
        if job_factory is None:
            from codex_adapter import _WindowsJob
            job_factory = _WindowsJob
        self.process = process
        self.job = job_factory()
        self._closed = False
        try:
            if self.job.assign_and_resume(process) is not True:
                raise BridgeError("Windows containment did not confirm assignment")
        except Exception as exc:
            failures = []
            try:
                if self.job.abort_suspended(process) is False:
                    failures.append("suspended child cleanup failed")
            except Exception:
                failures.append("suspended child cleanup failed")
            try:
                if self.job.close() is not True:
                    failures.append("job handle cleanup failed")
            except Exception:
                failures.append("job handle cleanup failed")
            self._closed = True
            detail = "; " + "; ".join(failures) if failures else ""
            raise BridgeError("Could not establish Windows process containment" + detail) from exc

    def terminate(self) -> None:
        if not self._closed and self.job.terminate_verified(self.process, timeout_seconds=5) is not True:
            raise BridgeError("Windows job termination was not verified")

    def close(self) -> None:
        if self._closed:
            return
        failures = []
        try:
            if self.job.verify_empty(timeout_seconds=2) is not True:
                if self.job.terminate_verified(self.process, timeout_seconds=5) is not True:
                    failures.append("Windows job descendant termination was not verified")
                if self.job.verify_empty(timeout_seconds=2) is not True:
                    failures.append("Windows job descendants remain unverified")
        except Exception:
            failures.append("Windows job cleanup verification failed")
        finally:
            try:
                if self.job.close() is not True:
                    failures.append("Windows job handle cleanup failed")
            except Exception:
                failures.append("Windows job handle cleanup failed")
            self._closed = True
        if failures:
            raise BridgeError("; ".join(failures))


class PosixProcessGroupGuard:
    """Own a new process group without claiming escape-proof containment."""

    start_new_session = True
    containment = {
        "mode": "posix_process_group", "descendants_verified": False, "degraded": True,
        "warning": "Process-group cleanup cannot prove containment of descendants that create another session.",
    }

    def __init__(self, process: Any):
        self.process = process
        self.group_id = process.pid
        self._closed = False

    def _alive(self) -> bool:
        try:
            os.killpg(self.group_id, 0)
            return True
        except ProcessLookupError:
            return False

    def terminate(self) -> None:
        if self._closed:
            return
        for signum, seconds in ((signal.SIGTERM, 2), (signal.SIGKILL, 3)):
            try:
                os.killpg(self.group_id, signum)
            except ProcessLookupError:
                return
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                # Reap the immediate child so its zombie cannot keep the group
                # visible after all owned processes have actually exited.
                self.process.poll()
                if not self._alive():
                    return
                time.sleep(0.05)
        raise BridgeError("Owned POSIX process group cleanup was not verified")

    def close(self) -> None:
        if not self._closed:
            if self._alive():
                self.terminate()
            self._closed = True


def containment_spawn_options(factory: Any, *, windows: bool) -> dict[str, Any]:
    """Pure launch-options seam for testing suspended/owned-session creation."""
    if windows:
        extra = getattr(factory, "creationflags", 0) if factory is not None else 0
        if not isinstance(extra, int):
            raise BridgeError("Containment creationflags must be an integer")
        flags = CREATE_NO_WINDOW | extra
        if getattr(factory, "requires_suspended", False):
            flags |= CREATE_SUSPENDED
        return {"creationflags": flags}
    return {"start_new_session": True} if getattr(factory, "start_new_session", False) else {}


def _identifier(value: Any, label: str) -> str:
    # These values become argv/TOML literals, never executable shell strings.
    if not isinstance(value, str) or not value or len(value) > 256:
        raise BridgeError(f"Invalid {label}")
    if value.startswith("-") or any(char.isspace() or ord(char) < 32 or char in '\"\\' for char in value):
        raise BridgeError(f"Invalid {label}")
    return value


def build_argv(
    executable: str,
    *,
    model: str,
    effort: str,
    permission_mode: str,
    thread_id: str | None = None,
) -> list[str]:
    """Build first-turn or exact-session resume argv without prompt text."""
    _identifier(model, "model")
    _identifier(effort, "effort")
    if permission_mode not in PERMISSIONS:
        raise BridgeError("Unsupported permission mode")
    if thread_id is not None:
        _identifier(thread_id, "thread ID")
    result = [executable, "exec"]
    if thread_id is not None:
        result.append("resume")
    result.extend(["--json", "--skip-git-repo-check"])
    # Sub-agents stay ON and inherit the steward's model/effort policy (John,
    # 2026-09-15: every family may spawn sub-agents; the requirement is that
    # each one is attributed back to its project and effort, not switched off).
    result.extend(launch_args({"family": "chatgpt", "model": model, "effort": effort}))
    # Both exec and exec resume accept -c; resume does not accept --sandbox.
    result.extend([
        "-c", 'forced_login_method="chatgpt"',
        "-c", 'approval_policy="never"',
        "-c", f'sandbox_mode="{PERMISSIONS[permission_mode]}"',
    ])
    if permission_mode == "fenced":
        result.extend(FENCE_CONFIG)
    if thread_id is not None:
        result.append(thread_id)
    result.append("-")
    return result


def _bounded_string(value: Any, limit: int = 2000) -> str:
    return value[:limit] if isinstance(value, str) else ""


_STDERR_KINDS = (
    ("auth", re.compile(r"(?i)\b(login|auth|unauthori[sz]ed|forbidden|401|403)\b")),
    ("rate_limit", re.compile(r"(?i)\b(rate.?limit|quota|429|too many requests|usage limit)\b")),
    ("network", re.compile(r"(?i)\b(timed? ?out|timeout|network|dns|econn\w*|unreachable|502|503|504)\b")),
    ("sandbox", re.compile(r"(?i)\b(sandbox|permission|denied|blocked by policy|rejected)\b")),
    ("panic", re.compile(r"(?i)\b(panic|traceback|unhandled|fatal)\b")),
)


def classify_stderr(lines: list[str]) -> dict[str, Any]:
    """codex-discipline-2026-09-15 Wave 1.3: what KIND of diagnostics the
    native process wrote, never their content. The pipe can carry login
    links and credentials, and the transport contract (tests) forbids
    forwarding it raw; John still learns whether a failed turn died on auth,
    a rate limit, the network, the sandbox, or a crash."""
    kinds: list[str] = []
    for kind, pattern in _STDERR_KINDS:
        if any(pattern.search(line) for line in lines):
            kinds.append(kind)
    return {"kinds": kinds or ["other"], "lines": len(lines)}


def _error_message(event: dict[str, Any]) -> tuple[str, str]:
    error = event.get("error", event)
    if isinstance(error, str):
        return _bounded_string(error), "provider_error"
    if isinstance(error, dict):
        return (
            _bounded_string(error.get("message")) or "Codex reported a failed turn",
            _bounded_string(error.get("code"), 120) or "provider_error",
        )
    return "Codex reported a failed turn", "provider_error"


class EventNormalizer:
    """Accumulate one native turn, stream public events, produce one result."""

    def __init__(self, model: str, effort: str, thread_id: str | None = None):
        self.requested_model = model
        self.requested_effort = effort
        self.thread_id = thread_id
        self.model_served: str | None = None
        self.effort_served: str | None = None
        self.text: list[str] = []
        self._completed_files: set[str] = set()
        self.usage: dict[str, int] = {}
        self.terminal: str | None = None
        self.error_message = ""
        self.error_code = ""
        self._text_items: set[str] = set()
        self._tool_items: set[str] = set()
        self._initialized = False
        self._finished = False
        self._progress_items: dict[str, bytes] = {}
        self._progress_terminal: str | None = None

    def made_progress(self, event, translated):
        """Called only after protocol validation; never expose reasoning text.

        Public deltas/tools are already deduplicated by accept(). Native item
        changes additionally cover tool completion/output and reasoning which
        intentionally do not appear in the dialogue. Heartbeats and repeated
        identical snapshots cannot refresh the inactivity deadline.
        """
        if self.terminal != self._progress_terminal:
            self._progress_terminal = self.terminal
            return True
        item = event.get("item")
        kind = event.get("type")
        if kind in ("item.started", "item.updated", "item.completed") and isinstance(item, dict):
            item_type = item.get("type")
            if item_type not in ("agent_message", "reasoning", "command_execution", "file_change", "mcp_tool_call", "web_search"):
                return False
            if item_type in ("agent_message", "reasoning") and not (isinstance(item.get("text"), str) and item["text"].strip()):
                return False
            fields = {"stage": kind, **{key: item[key] for key in ("type", "status", "exit_code", "text", "aggregated_output", "changes", "_change_count", "_paths_incomplete") if key in item}}
            signature = hashlib.sha256(json.dumps(fields, sort_keys=True).encode("utf-8")).digest()
            key = str(item_type) + ":" + str(item.get("id") or "")
            if self._progress_items.get(key) == signature:
                return False
            self._progress_items[key] = signature
            return True
        for output in translated:
            delta = (output.get("event") or {}).get("delta") or {}
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str) and delta["text"].strip():
                return True
            if output.get("type") == "assistant" and any(
                    block.get("type") == "tool_use" for block in (output.get("message") or {}).get("content", [])):
                return True
        # Grok's session identity has already been validated by its adapter.
        # Its reasoning deltas are private progress, never conversation text.
        data = event.get("event")
        if kind == "stream_event" and isinstance(data, dict) and data.get("type") == "content_block_delta":
            delta = data.get("delta")
            return bool(isinstance(delta, dict) and delta.get("type") == "thinking_delta"
                        and isinstance(delta.get("thinking"), str) and delta["thinking"].strip())
        return False

    def _receipt(self) -> dict[str, Any]:
        return {
            "provider": "chatgpt",
            "requested_model": self.requested_model,
            "requested_effort": self.requested_effort,
            "model_served": self.model_served,
            "effort_served": self.effort_served,
            "model_attested": self.model_served is not None,
            "model_source": (None if self.model_served is None      # who attests it
                             else "provider-confirmed" if getattr(self, "provider_label", "Codex") == "Grok"
                             else "cli-recorded"),
        }

    def accept(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(event, dict):
            raise BridgeError("Provider event must be an object")
        if self._finished:
            raise BridgeError("Event received after result was finalized")
        if event.get("thread_id") is not None and self.thread_id is not None and event["thread_id"] != self.thread_id:
            raise BridgeError("Codex emitted an unexpected thread")
        item = event.get("item")
        # Only fields explicitly emitted by the provider can attest a model.
        for source in (event, item if isinstance(item, dict) else {}):
            served = source.get("model_served") or source.get("model")
            if isinstance(served, str) and served and len(served) <= 256:
                self.model_served = served
            effort = source.get("effort_served")
            if isinstance(effort, str) and effort and len(effort) <= 64:
                self.effort_served = effort

        kind = event.get("type")
        if kind == "thread.started":
            new_id = _identifier(event.get("thread_id"), "provider thread ID")
            if self.thread_id is not None and self.thread_id != new_id:
                raise BridgeError("Codex resumed an unexpected thread")
            self.thread_id = new_id
            if self._initialized:
                return []
            self._initialized = True
            return [{
                "type": "system", "subtype": "init", "session_id": new_id,
                **self._receipt(),
            }]

        if kind in ("item.started", "item.updated", "item.completed") and isinstance(item, dict):
            item_type = item.get("type")
            item_id = _bounded_string(item.get("id"), 256)
            if item_type == "agent_message" and kind == "item.completed":
                text = item.get("text")
                if not isinstance(text, str):
                    raise BridgeError("Agent message is missing text")
                if item_id and item_id in self._text_items:
                    return []
                if item_id:
                    self._text_items.add(item_id)
                self.text.append(text)
                return [{
                    "type": "stream_event", "session_id": self.thread_id,
                    "event": {
                        "type": "content_block_delta", "index": len(self.text) - 1,
                        "delta": {"type": "text_delta", "text": text},
                    },
                }]
            if item_type in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                tool_id = item_id or f"tool-{len(self._tool_items)}"
                refresh = (item_type == "file_change" and kind == "item.completed"
                           and tool_id not in self._completed_files)
                if tool_id in self._tool_items and not refresh:
                    return []
                if item_type == "file_change" and kind == "item.completed":
                    self._completed_files.add(tool_id)   # one completed refresh per file change
                self._tool_items.add(tool_id)
                # Never forward aggregated command output, credentials, raw
                # arguments, file contents, reasoning, or arbitrary tool data.
                metadata: dict[str, Any] = {"item_id": tool_id}
                status = _bounded_string(item.get("status"), 80)
                if status:
                    metadata["status"] = status
                if isinstance(item.get("exit_code"), int):
                    metadata["exit_code"] = item["exit_code"]
                changes = item.get("changes")
                if isinstance(changes, list):
                    metadata["change_count"] = (item["_change_count"] if type(item.get("_change_count")) is int
                                                else len(changes))
                    paths = []                                  # bounded paths, never contents
                    for change in changes[:20]:
                        path = _bounded_string((change or {}).get("path") if isinstance(change, dict) else None, 240)
                        if path and path not in paths:
                            paths.append(path)
                    if paths:
                        metadata["paths"] = paths
                    if item.get("_paths_incomplete") or len(changes) > 20 or len(paths) < metadata["change_count"]:
                        metadata["paths_incomplete"] = True   # the audit treats an incomplete list as a possible write
                elif type(item.get("_change_count")) is int and item["_change_count"] >= 0:
                    metadata["change_count"] = item["_change_count"]
                if item_type == "command_execution":
                    # 2026-10-08: never the command itself - only whether it names Anchor's served folder (or could:
                    # an unreadable command counts), so the end-of-turn audit speaks to the steward that could have written
                    from steward_cockpit.codex_event_stream import names_served
                    metadata["names_served"] = (item["_names_served"] if "_names_served" in item
                                                else names_served(item.get("command")))
                skill = _skill_token(item.get("command"), item.get("tool"), *(metadata.get("paths") or []))
                if skill:
                    metadata["skill"] = skill   # the cockpit marks the skill in use; the folder's name only
                return [{
                    "type": "assistant", "session_id": self.thread_id,
                    "message": {"role": "assistant", "content": [{
                        "type": "tool_use", "id": tool_id,
                        "name": item_type, "input": metadata,
                    }]},
                }]
            return []

        if kind == "turn.completed":
            if self.terminal == "failed":
                return []
            self.terminal = "completed"
            usage = event.get("usage")
            if isinstance(usage, dict):
                self.usage = {
                    key: value for key, value in usage.items()
                    if key in ("input_tokens", "cached_input_tokens", "output_tokens")
                    and isinstance(value, int) and not isinstance(value, bool) and value >= 0
                }
        elif kind in ("turn.failed", "error"):
            self.terminal = "failed"
            self.error_message, self.error_code = _error_message(event)
        return []

    def finish(
        self,
        returncode: int | None,
        *,
        failure: str | None = None,
        failure_code: str = "transport_error",
        submitted: bool = True,
    ) -> dict[str, Any] | None:
        if self._finished:
            return None
        self._finished = True
        failed = bool(failure) or returncode != 0 or self.terminal != "completed"
        message = failure or self.error_message
        code = failure_code if failure else self.error_code
        if failed and not message:
            message = "Codex exited before a successful turn was confirmed"
            code = "unconfirmed_turn"
        result = {
            "type": "result",
            "subtype": "error_during_execution" if failed else "success",
            "is_error": failed,
            "session_id": self.thread_id,
            "result": "".join(self.text),
            "usage": self.usage,
            "replay_safe": not submitted if failed else False,
            **self._receipt(),
        }
        if failure or self.terminal not in ("completed", "failed"):
            # Partial events do not establish a completed serving receipt.
            result["model_attested"] = False
            result["model_served"] = None
        if failed:
            result.update({"error": {"code": code, "message": message}, "errors": [message]})
        return result


def user_text(envelope: Any) -> tuple[str, str | None]:
    if not isinstance(envelope, dict) or envelope.get("type") != "user":
        raise BridgeError("Expected a user message envelope")
    message = envelope.get("message")
    if not isinstance(message, dict):
        raise BridgeError("User message is missing content")
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list) and all(
        isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        for block in content
    ):
        text = "\n".join(block["text"] for block in content)
    else:
        raise BridgeError("Only text input is supported by this Codex bridge")
    system = envelope.get("system_prompt")
    if system is not None and not isinstance(system, str):
        raise BridgeError("system_prompt must be text")
    standing = envelope.get("standing_rules")
    if standing is not None and not isinstance(standing, str):
        raise BridgeError("standing_rules must be text")
    if not text.strip():
        raise BridgeError("User message must not be empty")
    return text, system, standing


def turn_prompt(system_prompt, standing_rules, text, fresh_thread):
    """The full contract opens a thread; every later turn (a new process) carries the standing rules."""
    if fresh_thread and system_prompt:
        return f"{system_prompt}\n\n{text}"
    if not fresh_thread and standing_rules:
        return f"{standing_rules}\n\n{text}"
    return text


class Broker:
    provider_label = "Codex"
    prompt_available_on_launch = False

    def _validate_launch(self, executable, model, effort, permission_mode, resume):
        build_argv(executable, model=model, effort=effort,
                   permission_mode=permission_mode, thread_id=resume)

    def _make_normalizer(self):
        normalizer = EventNormalizer(self.model, self.effort, self.thread_id)
        normalizer.provider_label = self.provider_label     # names who attests the served model
        return normalizer

    def _prepare_prompt(self, encoded_prompt: bytes):
        """Provider hook: return argv and optional stdin bytes."""
        return build_argv(
            self.executable, model=self.model, effort=self.effort,
            permission_mode=self.permission_mode, thread_id=self.thread_id,
        ), encoded_prompt

    def _cleanup_prompt(self):
        """Provider hook: verify cleanup of any owned prompt resource."""

    def __init__(
        self,
        *,
        target: str,
        model: str,
        effort: str,
        permission_mode: str,
        resume: str | None = None,
        executable: str | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        process_guard_factory: Callable[[Any], Any] | None = None,
        max_event_bytes: int | None = MAX_EVENT_BYTES,
        max_turn_bytes: int | None = MAX_TURN_BYTES,
        turn_timeout_seconds: float = DEFAULT_TURN_TIMEOUT_SECONDS,
        idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
        monotonic_clock: Callable[[], float] = time.monotonic,
        usage_tracker_factory=None,
    ):
        self.executable = executable or shutil.which("codex.exe" if os.name == "nt" else "codex")
        if not self.executable:
            raise BridgeError("Subscription Codex CLI is not installed")
        self._validate_launch(self.executable, model, effort, permission_mode, resume)
        self.target = str(Path(target).resolve())
        self.model, self.effort, self.permission_mode = model, effort, permission_mode
        self.thread_id = resume
        self.emit = emit or emit_json
        self.popen_factory = popen_factory
        if process_guard_factory is None and popen_factory is subprocess.Popen:
            process_guard_factory = WindowsJobGuard if os.name == "nt" else PosixProcessGroupGuard
        self.process_guard_factory = process_guard_factory
        self._spawn_containment = containment_spawn_options(process_guard_factory, windows=os.name == "nt")
        if popen_factory is subprocess.Popen and os.name == "nt":
            if process_guard_factory is None or not self._spawn_containment["creationflags"] & CREATE_SUSPENDED:
                raise BridgeError("Native Windows containment requires a suspended child")
        if (not isinstance(turn_timeout_seconds, (int, float)) or isinstance(turn_timeout_seconds, bool)
                or not 0 < turn_timeout_seconds <= 43200):
            raise BridgeError("Turn timeout must be finite and between zero and 43200 seconds")
        self.turn_timeout_seconds = float(turn_timeout_seconds)
        try:
            TurnWatchdog(turn_timeout_seconds, idle_timeout_seconds, clock=monotonic_clock)
        except ValueError as exc:
            raise BridgeError(str(exc)) from exc
        self.idle_timeout_seconds = float(idle_timeout_seconds)
        self._clock = monotonic_clock
        if max_event_bytes is not None and (isinstance(max_event_bytes, bool) or not isinstance(max_event_bytes, int) or max_event_bytes <= 0):
            raise BridgeError("max_event_bytes must be a positive integer")
        if max_turn_bytes is not None and (
            isinstance(max_turn_bytes, bool) or not isinstance(max_turn_bytes, int) or max_turn_bytes <= 0
        ):
            raise BridgeError("max_turn_bytes must be a positive integer or None")
        self.max_event_bytes = (MAX_GROK_EVENT_BYTES if self.provider_label != "Codex" and max_event_bytes is None else max_event_bytes)
        self.max_turn_bytes = (8 * 1024 * 1024 if self.provider_label != "Codex" and max_turn_bytes is None else max_turn_bytes)
        self._stop = threading.Event()
        self._active: Any = None
        self._guard: Any = None
        self._system_prompt: str | None = None
        self._input_seen = False
        self._cleanup_errors: list[str] = []
        self._stderr_tail: list[str] = []  # Wave 1.3: redacted, bounded, failed turns only
        self._usage_tracker_factory = usage_tracker_factory
        if usage_tracker_factory is None and popen_factory is subprocess.Popen and self.provider_label == "Codex":
            from steward_cockpit.codex_usage import CodexUsageTracker
            self._usage_tracker_factory = CodexUsageTracker


    def _spawn_env(self):
        """The model policy plus the ids the steward's children inherit."""
        env = policy_environment()
        try:
            import usage_capture as _uc
            env.update(_uc.attribution_env(effort_dir=self.target))
        except Exception:
            pass
        return env

    def _terminate_owned(self) -> None:
        guard = self._guard
        if guard is not None:
            try:
                if guard.terminate() is False:
                    self._cleanup_errors.append("Owned process guard did not confirm termination")
            except Exception:
                self._cleanup_errors.append("Owned process guard termination failed")
        child = self._active
        if child is not None:
            try:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                self._cleanup_errors.append("Immediate owned child termination failed")

    def stop(self) -> None:
        self._stop.set()
        self._terminate_owned()

    def turn(self, envelope: Any) -> dict[str, Any]:
        normalized = self._make_normalizer()
        invocation_id = str(uuid.uuid4())
        tracker = None
        checkpoint = None
        capture_error = None
        if self._usage_tracker_factory is not None:
            try:
                # Existing resumed file EOF is latched before the child starts.
                tracker = self._usage_tracker_factory(target=self.target, thread_id=self.thread_id)
            except Exception:
                capture_error = "usage-tracker-unavailable"

        def poll_usage(force=False):
            nonlocal checkpoint, capture_error
            if tracker is None or not self.thread_id:
                return
            try:
                tracker.bind(self.thread_id)
                update = tracker.poll(force=force)
            except Exception:
                update = {"usage": None, "token_status": "unavailable", "error": "usage-read-failed"}
            if update is None or update == checkpoint:
                return
            if update.get("error"):
                capture_error = update["error"]
            checkpoint = update
            self.emit({"type": "usage_checkpoint", "session_id": self.thread_id,
                       "invocation_id": invocation_id, "usage": update.get("usage"),
                       "token_status": update.get("token_status", "partial"),
                       "usage_source": "codex-rollout", "usage_error": update.get("error"),
                       "at": datetime.now(timezone.utc).isoformat()})
        submitted = False
        reader_stop = threading.Event()
        readers: list[threading.Thread] = []
        writer: threading.Thread | None = None
        writer_done = threading.Event()
        writer_failed = threading.Event()
        returncode: int | None = None
        failure: str | None = None
        failure_code = "transport_error"
        self._cleanup_errors = []
        self._stderr_tail = []
        watchdog = TurnWatchdog(self.turn_timeout_seconds, self.idle_timeout_seconds,
                                clock=self._clock, provider_label=self.provider_label)
        started = self._clock()
        containment = {
            "mode": "injected_process", "descendants_verified": False, "degraded": True,
        }
        try:
            text, system, standing = user_text(envelope)
            if self._input_seen and system is not None and system != self._system_prompt:
                raise BridgeError("Cannot change the system contract inside an existing broker")
            if not self._input_seen:
                self._system_prompt = system
            self._input_seen = True
            prompt = turn_prompt(self._system_prompt, standing, text, self.thread_id is None)
            encoded_prompt = (prompt + "\n").encode("utf-8")
            if self.provider_label != "Codex" and len(encoded_prompt) > MAX_INPUT_BYTES:
                raise BridgeError("User prompt exceeds the input byte limit")
            if self._stop.is_set():
                raise BridgeError(f"{self.provider_label} broker has been cancelled")
            argv, stdin_prompt = self._prepare_prompt(encoded_prompt)
            options: dict[str, Any] = {
                "cwd": self.target, "env": self._spawn_env(), "shell": False,
                "stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            }
            options.update(self._spawn_containment)
            if self.prompt_available_on_launch:
                # File-based providers can consume their prompt immediately
                # upon resume, before stdin/output worker setup has completed.
                submitted = True
            child = self.popen_factory(argv, **options)
            self._active = child
            if self.process_guard_factory is not None:
                self._guard = self.process_guard_factory(child)
                containment = dict(getattr(self._guard, "containment", {
                    "mode": "custom_guard", "descendants_verified": False, "degraded": True,
                }))
            events: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=4)

            def enqueue(event: tuple[str, Any]) -> bool:
                while not reader_stop.is_set():
                    try:
                        events.put(event, timeout=0.1)
                        return True
                    except queue.Full:
                        continue
                return False

            def read_pipe(name: str, pipe: Any) -> None:
                try:
                    if name == "stdout" and self.provider_label == "Codex":
                        from steward_cockpit.codex_event_stream import (
                            iter_codex_events, EventStreamError, EventSizeError)
                        try:
                            for event, size in iter_codex_events(pipe,
                                    cancelled=lambda: self._stop.is_set() or reader_stop.is_set(),
                                    max_event_bytes=self.max_event_bytes):
                                if not enqueue(("native_event", (event, size))):
                                    break
                        except EventSizeError as exc:
                            enqueue(("protocol_error", OutputLimitError(str(exc))))
                        except EventStreamError as exc:
                            if not self._stop.is_set() and not reader_stop.is_set():
                                enqueue(("protocol_error", BridgeError(str(exc))))
                        return
                    while not self._stop.is_set() and not reader_stop.is_set():
                        data = (pipe.readline(self.max_event_bytes + 1) if name == "stdout"
                                else pipe.read(65536))
                        if not data:
                            break
                        if not enqueue((name, data)):
                            break
                except (OSError, ValueError):
                    enqueue(("reader_error", name))
                finally:
                    enqueue(("eof", name))

            readers = [
                threading.Thread(target=read_pipe, args=(name, pipe), daemon=True)
                for name, pipe in (("stdout", child.stdout), ("stderr", child.stderr))
            ]
            for reader in readers:
                reader.start()
            submitted = True  # A partial write is already ambiguous; never auto-replay it.

            def write_prompt() -> None:
                try:
                    if stdin_prompt is not None:
                        child.stdin.write(stdin_prompt)
                        child.stdin.flush()
                except (OSError, ValueError):
                    writer_failed.set()
                finally:
                    try:
                        child.stdin.close()
                    except (OSError, ValueError):
                        writer_failed.set()
                    writer_done.set()
                    enqueue(("writer_done", None))

            writer = threading.Thread(target=write_prompt, daemon=True)
            writer.start()
            total_bytes = 0
            eof: set[str] = set()
            while len(eof) < 2 or not writer_done.is_set():
                poll_usage()
                if self._stop.is_set():
                    raise BridgeError(f"{self.provider_label} turn was cancelled")
                remaining = watchdog.remaining()
                try:
                    name, data = events.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue
                if name == "writer_done":
                    continue
                if name == "eof":
                    eof.add(data)
                    continue
                if name == "reader_error":
                    raise BridgeError(f"Could not read the {self.provider_label} event stream")
                if name == "protocol_error":
                    raise data
                event = None
                if name == "native_event":
                    event, size = data
                else:
                    size = len(data)
                total_bytes += size
                if self.max_turn_bytes is not None and total_bytes > self.max_turn_bytes:
                    raise OutputLimitError(f"Anchor transport: {self.provider_label} turn output of {total_bytes} bytes exceeds the local size bound of {self.max_turn_bytes} bytes")
                if name == "stderr":
                    # Counted; never forwarded raw. Wave 1.3 keeps the last
                    # lines in memory only to CLASSIFY a failed turn's cause.
                    try:
                        for line in data.decode("utf-8", errors="replace").splitlines():
                            if line.strip():
                                self._stderr_tail.append(line[:400])
                                del self._stderr_tail[:-40]
                    except Exception:
                        pass
                    continue
                if event is None:
                    if self.max_event_bytes is not None and size > self.max_event_bytes:
                        raise OutputLimitError(f"Anchor transport: {self.provider_label} event output of at least {size} bytes exceeds the local size bound of {self.max_event_bytes} bytes")
                    try:
                        event = json.loads(data.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError) as exc:
                        raise BridgeError(f"{self.provider_label} emitted an invalid JSON event") from exc
                translated_events = normalized.accept(event)
                if normalized.made_progress(event, translated_events):
                    watchdog.progress()
                for translated in translated_events:
                    self.emit(translated)
                self.thread_id = normalized.thread_id
                poll_usage()
            if self._stop.is_set():
                raise BridgeError(f"{self.provider_label} turn was cancelled")
            remaining = watchdog.remaining()
            try:
                returncode = child.wait(timeout=min(10, remaining))
            except subprocess.TimeoutExpired as exc:
                raise TurnTimeout(f"{self.provider_label} did not exit within the bounded turn deadline") from exc
            if self._stop.is_set():
                raise BridgeError(f"{self.provider_label} turn was cancelled")
            if writer_failed.is_set() and normalized.terminal != "failed":
                raise BridgeError(f"Could not finish sending the {self.provider_label} prompt")
        except Exception as exc:
            self._terminate_owned()
            # Exception strings from OS/provider plumbing can contain secrets.
            failure = str(exc) if isinstance(exc, BridgeError) else f"Could not complete the {self.provider_label} transport"
            failure_code = ("cancelled" if self._stop.is_set() else
                            "turn_timeout" if isinstance(exc, TurnTimeout) else
                            "transport_output_limit" if isinstance(exc, OutputLimitError) else "transport_error")
        finally:
            reader_stop.set()
            if self._guard is not None:
                try:
                    if self._guard.close() is False:
                        self._cleanup_errors.append("Owned process guard cleanup was not confirmed")
                except Exception:
                    self._cleanup_errors.append("Owned process guard cleanup verification failed")
                self._guard = None
            child = self._active
            if child is not None:
                # Join before closing buffered pipes: closing a pipe whose
                # worker still holds its I/O lock can itself block forever.
                if writer is not None and writer.ident is not None:
                    writer.join(timeout=0.5)
                for reader in readers:
                    if reader.ident is not None:
                        reader.join(timeout=0.5)
                workers = [(writer, child.stdin)] + list(zip(readers, (child.stdout, child.stderr)))
                if not readers:
                    workers.extend([(None, child.stdout), (None, child.stderr)])
                for worker, pipe in workers:
                    if worker is not None and worker.is_alive():
                        self._cleanup_errors.append("Owned Codex I/O worker did not stop")
                        continue
                    try:
                        pipe.close()
                    except (OSError, ValueError):
                        self._cleanup_errors.append("Owned Codex pipe cleanup failed")
            self._active = None
            try:
                if self._cleanup_prompt() is False:
                    self._cleanup_errors.append("Owned prompt resource cleanup was not confirmed")
            except Exception:
                self._cleanup_errors.append("Owned prompt resource cleanup verification failed")
        if self._cleanup_errors:
            # Never publish success before descendant and handle cleanup gates.
            cleanup = "; ".join(dict.fromkeys(self._cleanup_errors))
            failure = f"{failure}; {cleanup}" if failure else cleanup
            failure_code = "containment_cleanup_failed"
            containment["descendants_verified"] = False
            self._stop.set()  # Do not run another turn beside uncertain leftovers.
        result = normalized.finish(
            returncode, failure=failure, failure_code=failure_code, submitted=submitted,
        )
        assert result is not None
        if result.get("is_error") and self._stderr_tail:
            result["stderr_hint"] = classify_stderr(self._stderr_tail)
        poll_usage(force=True)
        if tracker is not None:
            result["usage_invocation_id"] = invocation_id
            result["token_status"] = "reported" if result.get("usage") else "partial"
            result["usage_source"] = "codex-cli-final" if result.get("usage") else "codex-rollout"
            if not result.get("usage") and checkpoint and checkpoint.get("usage"):
                result["usage"] = checkpoint["usage"]
        if capture_error:
            result["usage_capture_error"] = capture_error
        result["containment"] = containment
        result["duration_ms"] = round(max(0, self._clock() - started) * 1000)
        result["transport_output_bytes"] = total_bytes if "total_bytes" in locals() else 0
        result["turn_limits"] = {"wall_seconds": self.turn_timeout_seconds,
                                 "idle_seconds": self.idle_timeout_seconds}
        self.thread_id = normalized.thread_id
        self.emit(result)
        return result


def emit_json(event: dict[str, Any]) -> None:
    # Windows service stdout may use a legacy code page. ASCII JSON escapes
    # preserve every Unicode character across that pipe; the receiver decodes
    # JSON back to the original text without locale-dependent replacement.
    sys.stdout.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--permission-mode", required=True, choices=tuple(PERMISSIONS))
    parser.add_argument("--resume")
    parser.add_argument("--turn-timeout-seconds", type=float, default=DEFAULT_TURN_TIMEOUT_SECONDS)
    parser.add_argument("--idle-timeout-seconds", type=float, default=DEFAULT_IDLE_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        broker = Broker(target=args.target, model=args.model, effort=args.effort,
                        permission_mode=args.permission_mode, resume=args.resume,
                        turn_timeout_seconds=args.turn_timeout_seconds,
                        idle_timeout_seconds=args.idle_timeout_seconds)
    except BridgeError as exc:
        emit_json({"type": "result", "is_error": True, "replay_safe": True,
                   "model_attested": False, "error": {"code": "setup_error", "message": str(exc)}})
        return 2

    def on_signal(_signum: int, _frame: Any) -> None:
        broker.stop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, on_signal)
    try:
        while not broker._stop.is_set():
            # Internal parent-to-broker pipe: forward the complete accepted
            # prompt. The native provider owns its model context constraints.
            raw = sys.stdin.buffer.readline()
            if not raw:
                break
            try:
                envelope = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                emit_json({"type": "result", "is_error": True, "replay_safe": True,
                           "model_attested": False, "error": {
                               "code": "invalid_input", "message": "Input envelope must be UTF-8 JSON"}})
                continue
            broker.turn(envelope)
    finally:
        broker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

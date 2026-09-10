"""Grok broker canaries: fake native processes and fake filesystem APIs only."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from steward_cockpit import grok_turn_bridge as bridge
from steward_cockpit.codex_turn_bridge import BridgeError


SESSION = "12345678-1234-4234-8234-123456789abc"
OTHER_SESSION = "12345678-1234-4234-8234-123456789abd"


def envelope(text="hello", **extra):
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}, **extra}


def init(session=SESSION, **extra):
    return {"type": "system", "subtype": "init", "session_id": session,
            "apiKeySource": "oauth", "model": "configured-alias", **extra}


def stream(event, session=SESSION):
    return {"type": "stream_event", "session_id": session, "event": event}


def assistant(text="answer", session=SESSION, message_id="m1", **extra):
    return {"type": "assistant", "session_id": session, "message": {
        "id": message_id, "model": "configured-alias", "content": [{"type": "text", "text": text}], **extra,
    }}


def result(session=SESSION, **extra):
    return {"type": "result", "session_id": session, "is_error": False, "subtype": "success",
            "usage": {"input_tokens": 3, "output_tokens": 2}, "modelUsage": {}, **extra}


def native(*events):
    return b"".join((json.dumps(event) + "\n").encode() for event in events)


class CapturedInput(io.BytesIO):
    def close(self):
        if not self.closed:
            self.captured = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self, output, code=0):
        self.stdin = CapturedInput()
        self.stdout = io.BytesIO(output)
        self.stderr = io.BytesIO()
        self.returncode = code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.returncode = -1

    def kill(self):
        self.terminate()


def fake_broker(*, responses=None, prompt_failure=False, cleanup_failure=False, **kwargs):
    calls, emitted, prompts, processes = [], [], [], []
    responses = iter(responses) if responses is not None else None

    class Prompt:
        def __init__(self, payload):
            self.payload = payload
            self.path = Path("private-test-boundary") / f"owned-{len(prompts)}.txt"
            self.closed = False
            prompts.append(self)

        def close(self):
            if cleanup_failure:
                raise BridgeError("private cleanup failed")
            self.closed = True

    def prompt_factory(payload):
        if prompt_failure:
            raise BridgeError("Could not verify a private boundary")
        return Prompt(payload)

    def spawn(argv, **options):
        calls.append((argv, options))
        flag = "--resume" if "--resume" in argv else "--session-id"
        session = argv[argv.index(flag) + 1]
        output = next(responses)(session) if responses is not None else native(
            init(session), assistant(session=session), result(session),
        )
        process = FakeProcess(output)
        processes.append(process)
        return process

    broker = bridge.GrokBroker(
        target=".", model="future-grok", effort="highest-current", permission_mode="plan",
        executable="grok-stub", emit=emitted.append, popen_factory=spawn,
        prompt_factory=prompt_factory, **kwargs,
    )
    return broker, calls, emitted, prompts, processes


@pytest.mark.parametrize("mode", bridge.PERMISSION_MODES)
def test_native_argv_preserves_permission_and_uses_private_file_not_literal_prompt(mode):
    argv = bridge.build_argv("grok", model="future-model", effort="future-effort",
                             permission_mode=mode, prompt_file="private location/prompt.txt",
                             session_id=SESSION, resume=False)
    assert argv[argv.index("--permission-mode") + 1] == mode
    assert argv[argv.index("--output-format") + 1] == "streaming-messages-json"
    assert "--include-partial-messages" in argv
    assert argv[-2:] == ["--session-id", SESSION]
    assert "-p" not in argv and "--single" not in argv and "--prompt" not in argv
    assert argv[argv.index("--prompt-file") + 1] != "-"


def test_exact_resume_never_reuses_new_session_flag():
    argv = bridge.build_argv("grok", model="future-model", effort="high", permission_mode="plan",
                             prompt_file="private.txt", session_id=SESSION, resume=True)
    assert argv[-2:] == ["--resume", SESSION]
    assert "--session-id" not in argv


@pytest.mark.parametrize("changes", [
    {"permission_mode": "unknown"}, {"session_id": "--latest"},
    {"session_id": SESSION.upper()}, {"model": "--injected-flag"},
    {"effort": "high\noption"}, {"prompt_file": ""},
])
def test_unsafe_or_unsupported_launch_fields_are_rejected(changes):
    arguments = dict(model="future", effort="high", permission_mode="plan",
                     prompt_file="private.txt", session_id=SESSION, resume=False)
    arguments.update(changes)
    with pytest.raises(BridgeError):
        bridge.build_argv("grok", **arguments)


def test_stream_and_completed_message_reconcile_without_duplicate_text_or_thinking():
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    output = normalizer.accept(init())
    output += normalizer.accept(stream({"type": "message_start", "message": {"id": "m1"}}))
    output += normalizer.accept(stream({"type": "content_block_delta", "index": 0,
                                       "delta": {"type": "text_delta", "text": "Hel"}}))
    output += normalizer.accept(stream({"type": "content_block_delta", "index": 0,
                                       "delta": {"type": "thinking_delta", "thinking": "private thought"}}))
    output += normalizer.accept(assistant("Hello"))
    output += normalizer.accept(assistant("Hello"))
    output += normalizer.accept(result(result="Hello"))
    final = normalizer.finish(0)
    texts = [event["event"]["delta"]["text"] for event in output if event["type"] == "stream_event"]
    assert texts == ["Hel", "lo"]
    assert final["result"] == "Hello"
    assert "private thought" not in json.dumps(output)
    assert final["model_attested"] is False
    assert final["model_served"] is None
    assert final["provider"] == "grok"


def test_partial_without_message_start_reconciles_once():
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    normalizer.accept(init())
    normalizer.accept(stream({"type": "content_block_delta", "index": 0,
                              "delta": {"type": "text_delta", "text": "answer"}}))
    assert normalizer.accept(assistant()) == []
    normalizer.accept(result())
    assert normalizer.finish(0)["result"] == "answer"


def test_conflicting_completed_text_fails_instead_of_silently_overwriting_partial():
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    normalizer.accept(init())
    normalizer.accept(stream({"type": "content_block_delta", "index": 0,
                              "delta": {"type": "text_delta", "text": "partial"}}))
    with pytest.raises(BridgeError, match="disagreed"):
        normalizer.accept(assistant("different"))


def test_tool_metadata_is_deduplicated_without_forwarding_arguments_or_tool_output():
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    normalizer.accept(init())
    block = {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"secret": "private"}}
    events = normalizer.accept(stream({"type": "content_block_start", "index": 0, "content_block": block}))
    events += normalizer.accept(stream({"type": "content_block_delta", "index": 0,
                                       "delta": {"type": "input_json_delta", "partial_json": "private"}}))
    events += normalizer.accept(assistant(content=[block]))
    assert len(events) == 1
    assert "private" not in json.dumps(events)
    assert events[0]["message"]["content"][0]["input"] == {"provider_tool": "Read"}


def test_only_single_contributing_model_usage_id_attests_actual_model():
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    normalizer.accept(init(model="not-attestation"))
    normalizer.accept(assistant(model="also-not-attestation"))
    normalizer.accept(result(modelUsage={"future-served-build": {"inputTokens": 3, "outputTokens": 1}}))
    final = normalizer.finish(0)
    assert final["model_attested"] is True
    assert final["model_served"] == "future-served-build"
    assert final["models_served"] == ["future-served-build"]
    assert final["requested_model"] == "configured"


def test_multiple_contributors_are_preserved_without_guessing_main_model():
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    normalizer.accept(init())
    normalizer.accept(result(modelUsage={
        "served-a": {"inputTokens": 3}, "served-b": {"outputTokens": 2},
        "unsafe\nidentity": {"inputTokens": 3}, "no-evidence": {},
        "zero-only": {"inputTokens": 0},
    }))
    final = normalizer.finish(0)
    assert final["models_served"] == ["served-a", "served-b"]
    assert final["model_served"] is None and final["model_attested"] is False


@pytest.mark.parametrize("bad", [
    init(apiKeySource="user"), init(apiKeySource=None), init(session=OTHER_SESSION),
    result(),
])
def test_subscription_and_session_confirmation_fail_closed(bad):
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    with pytest.raises(BridgeError):
        normalizer.accept(bad)


def test_every_turn_event_requires_its_expected_identity():
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    normalizer.accept(init())
    with pytest.raises(BridgeError, match="identity"):
        normalizer.accept({"type": "result", "is_error": False})
    with pytest.raises(BridgeError, match="identity"):
        normalizer.accept(result(session=OTHER_SESSION))


def test_quota_error_keeps_partial_text_and_structured_reason_without_safe_replay():
    normalizer = bridge.GrokNormalizer("configured", "high", expected_id=SESSION)
    normalizer.accept(init())
    normalizer.accept(assistant("partial text"))
    normalizer.accept(result(is_error=True, subtype="error_during_execution", errors=["Usage limit reached"]))
    final = normalizer.finish(1)
    assert final["is_error"] is True and final["replay_safe"] is False
    assert final["result"] == "partial text"
    assert final["error"]["message"] == "Usage limit reached"
    assert normalizer.finish(1) is None


def test_two_turns_use_private_files_empty_stdin_and_exact_native_resume():
    broker, calls, events, prompts, processes = fake_broker()
    first = broker.turn(envelope("private first message", system_prompt="private contract"))
    second = broker.turn(envelope("private second message"))
    assert not first["is_error"] and not second["is_error"]
    first_id = calls[0][0][calls[0][0].index("--session-id") + 1]
    assert str(uuid.UUID(first_id)) == first_id
    assert calls[1][0][-2:] == ["--resume", first_id]
    assert first["session_id"] == second["session_id"] == first_id
    assert prompts[0].payload == b"private contract\n\nprivate first message\n"
    assert prompts[1].payload == b"private second message\n"
    assert all(prompt.closed for prompt in prompts)
    assert all(process.stdin.captured == b"" for process in processes)
    assert all("private first message" not in " ".join(argv) for argv, _ in calls)
    assert all(options["shell"] is False for _, options in calls)
    assert len([event for event in events if event["type"] == "result"]) == 2


def test_missing_private_boundary_blocks_before_native_spawn():
    broker, calls, _, prompts, _ = fake_broker(prompt_failure=True)
    final = broker.turn(envelope())
    assert final["is_error"] is True and final["replay_safe"] is True
    assert calls == [] and prompts == []


def test_prompt_cleanup_failure_blocks_success_and_subsequent_turns():
    broker, calls, events, _, _ = fake_broker(cleanup_failure=True)
    final = broker.turn(envelope())
    assert final["is_error"] is True
    assert final["error"]["code"] == "containment_cleanup_failed"
    assert final["model_attested"] is False
    assert len([event for event in events if event["type"] == "result"]) == 1
    broker.turn(envelope("next"))
    assert len(calls) == 1


def test_failed_first_init_does_not_reuse_fresh_session_id():
    broker, calls, _, _, _ = fake_broker(responses=[
        lambda session: b"", lambda session: native(init(session), result(session)),
    ])
    assert broker.turn(envelope())["is_error"] is True
    assert broker.turn(envelope())["is_error"] is False
    first_id = calls[0][0][calls[0][0].index("--session-id") + 1]
    second_id = calls[1][0][calls[1][0].index("--session-id") + 1]
    assert first_id != second_id


def test_file_based_provider_is_ambiguous_as_soon_as_launch_can_consume_prompt():
    broker, _, _, prompts, _ = fake_broker()

    def failed_spawn(argv, **kwargs):
        raise OSError("private platform error")

    broker.popen_factory = failed_spawn
    final = broker.turn(envelope())
    assert final["is_error"] is True and final["replay_safe"] is False
    assert prompts[0].closed
    assert "private platform error" not in json.dumps(final)


def test_constructor_cleanup_failure_is_not_hidden_as_an_ordinary_setup_error():
    broker, calls, _, _, _ = fake_broker()

    def failed_prompt(payload):
        raise bridge.PromptCleanupError("Owned cleanup failed")

    broker._prompt_factory = failed_prompt
    final = broker.turn(envelope())
    assert final["error"]["code"] == "containment_cleanup_failed"
    assert broker._stop.is_set() and calls == []


def test_owner_acl_is_protected_and_grants_only_current_sid():
    sid = "S-1-5-21-100-200-300-400"
    assert bridge.owner_only_sddl(sid) == f"O:{sid}D:P(A;OICI;FA;;;{sid})"
    assert "WD" not in bridge.owner_only_sddl(sid)  # No Everyone/Users grant.
    with pytest.raises(BridgeError):
        bridge.owner_only_sddl("S-1-5-21-1)D:(A;;FA;;;WD")


def fake_windows_api(monkeypatch, *, reject_acl=False):
    events, paths, handles = [], set(), {}

    class FakeAPI:
        def __init__(self):
            self.kernel = SimpleNamespace(
                CreateDirectoryW=self.create_directory, CreateFileW=self.create_file,
                GetFileInformationByHandleEx=self.attributes, WriteFile=self.write,
                FlushFileBuffers=lambda handle: True, CloseHandle=self.close_handle,
                RemoveDirectoryW=self.remove_directory, LocalFree=lambda pointer: None,
            )
            self.advapi = SimpleNamespace(ConvertStringSecurityDescriptorToSecurityDescriptorW=self.descriptor)

        def current_sid(self):
            return "S-1-5-21-100-200-300-400"

        def private_root(self):
            events.append("current_account_local_root")
            return Path("current-account-local-app-data")

        def descriptor(self, sddl, revision, output, length):
            events.append(("protected_acl", sddl))
            output._obj.value = 123
            return True

        def create_directory(self, path, attributes):
            paths.add(path)
            events.append("create_directory")
            return True

        def create_file(self, path, access, share, attributes, disposition, flags, template):
            handle = len(handles) + 11
            handles[handle] = {"path": path, "flags": flags, "delete": False}
            paths.add(path)
            events.append(("open_owned", handle, access, share, flags))
            return handle

        def assert_private(self, handle, sid):
            events.append(("verify_acl", handle))
            if reject_acl:
                raise BridgeError("ACL validation failed")

        def attributes(self, handle, kind, output, size):
            output[0], output[1] = 0, 0
            return True

        def write(self, handle, payload, size, written, overlapped):
            events.append(("write", handle, size))
            written._obj.value = size
            return True

        def mark_delete(self, handle):
            events.append(("delete_owned_handle", handle))
            handles[handle]["delete"] = True
            return True

        def close_handle(self, handle):
            events.append(("close_handle", handle))
            entry = handles[handle]
            if entry["delete"] or entry["flags"] & 0x04000000:
                paths.discard(entry["path"])
            return True

        def remove_directory(self, path):
            paths.discard(path)
            return True

    monkeypatch.setattr(bridge, "_WindowsAPI", FakeAPI)
    monkeypatch.setattr(bridge.os.path, "lexists", lambda path: str(path) in paths)
    return events, paths, handles


def test_windows_prompt_verifies_acl_before_any_bytes_and_cleans_owned_handles(monkeypatch):
    events, paths, handles = fake_windows_api(monkeypatch)
    prompt = bridge.WindowsPrivatePrompt(b"private classroom prompt")
    assert len(paths) == 2
    assert prompt.path.parent == prompt.directory
    writes = [index for index, event in enumerate(events) if isinstance(event, tuple) and event[0] == "write"]
    acl_checks = [index for index, event in enumerate(events) if isinstance(event, tuple) and event[0] == "verify_acl"]
    assert len(acl_checks) == 2 and max(acl_checks) < min(writes)
    file_entries = [entry for entry in handles.values() if entry["path"].endswith("prompt.txt")]
    assert file_entries[0]["flags"] & 0x04000000  # Crash-safe delete-on-close.
    assert all(event[3] == 1 for event in events if isinstance(event, tuple) and event[0] == "open_owned")
    prompt.close()
    assert paths == set()
    assert len([event for event in events if isinstance(event, tuple) and event[0] == "delete_owned_handle"]) == 2


def test_windows_acl_failure_writes_no_secret_bytes_and_cleans_owned_directory(monkeypatch):
    events, paths, _ = fake_windows_api(monkeypatch, reject_acl=True)
    with pytest.raises(BridgeError, match="ACL validation"):
        bridge.WindowsPrivatePrompt(b"must never be written")
    assert not any(isinstance(event, tuple) and event[0] == "write" for event in events)
    assert paths == set()

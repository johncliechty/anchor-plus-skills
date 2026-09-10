"""Broker canaries. Every child here is fake; no CLI or provider is invoked."""

import io
import json
import threading
import time

import pytest

from steward_cockpit.codex_turn_bridge import (
    BridgeError, Broker, CREATE_NO_WINDOW, CREATE_SUSPENDED,
    PosixProcessGroupGuard, WindowsJobGuard, EventNormalizer,
    build_argv, containment_spawn_options, user_text,
)


def envelope(text="hello", **extra):
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}, **extra}


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
def test_service_pipe_preserves_unicode_on_legacy_stdout(monkeypatch, encoding):
    from steward_cockpit import codex_turn_bridge as bridge
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding=encoding, errors="strict")
    event = {"text": "John—I'll explain ∫ f dμ, 日本語, and 🧭 without replacement."}
    with monkeypatch.context() as patch:
        patch.setattr(bridge.sys, "stdout", stream)
        bridge.emit_json(event)
    assert json.loads(raw.getvalue().decode("utf-8")) == event
    stream.detach()


def native(*events):
    return b"".join((json.dumps(event) + "\n").encode() for event in events)


def successful(text="answer", thread="thread-1"):
    return native(
        {"type": "thread.started", "thread_id": thread},
        {"type": "item.completed", "item": {"id": "a", "type": "agent_message", "text": text}},
        {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 3}},
    )


class CapturedInput(io.BytesIO):
    def close(self):
        if not self.closed:
            self.captured = self.getvalue()
        super().close()


class FakeProcess:
    def __init__(self, stdout, stderr=b"", code=0):
        self.stdin = CapturedInput()
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = code
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -1

    def kill(self):
        self.terminate()


def broker_with_processes(*processes, **kwargs):
    calls = []
    emitted = []
    remaining = iter(processes)

    def spawn(argv, **options):
        calls.append((argv, options))
        return next(remaining)

    broker = Broker(target=".", model="future-frontier", effort="ultra",
                    permission_mode="acceptEdits", executable="codex-stub",
                    emit=emitted.append, popen_factory=spawn, **kwargs)
    return broker, calls, emitted


def test_recognized_progress_not_heartbeat_or_duplicate_snapshots():
    n = EventNormalizer("future-frontier", "ultra", "thread-1")
    def progress(event):
        return n.made_progress(event, n.accept(event))
    assert not progress({"type": "heartbeat"})
    started = {"type": "item.started", "item": {"id": "tool-1", "type": "command_execution", "status": "in_progress"}}
    assert progress(started)
    assert not progress(started)
    completed = {"type": "item.completed", "item": {**started["item"], "status": "completed", "exit_code": 0}}
    assert progress(completed)
    assert not progress(completed)
    reasoning = {"type": "item.updated", "item": {"id": "r", "type": "reasoning", "text": "Private progress"}}
    output = n.accept(reasoning)
    assert output == []
    assert n.made_progress(reasoning, output)
    assert not progress(reasoning)
    with pytest.raises(BridgeError, match="unexpected thread"):
        progress({**started, "thread_id": "wrong-thread"})


def test_broker_survives_active_work_past_old_fifteen_minute_wall():
    class Clock:
        now = 0.0
        def __call__(self):
            return self.now
    clock = Clock()
    events = [{"type": "thread.started", "thread_id": "thread-1"}]
    events += [{"type": "item.completed", "item": {"id": str(i), "type": "agent_message", "text": "progress"}} for i in range(3)]
    events += [{"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}]
    process = FakeProcess(native(*events))
    broker, _, _ = broker_with_processes(process, monotonic_clock=clock)
    class TimedNormalizer(EventNormalizer):
        def accept(self, event):
            if event["type"] == "item.completed":
                clock.now += 600
            return super().accept(event)
    broker._make_normalizer = lambda: TimedNormalizer("future-frontier", "ultra")
    result = broker.turn(envelope())
    assert not result["is_error"]
    assert result["duration_ms"] == 1800000
    assert result["turn_limits"] == {"wall_seconds": 7200, "idle_seconds": 900}
    assert not process.terminated


def test_broker_silent_idle_timeout_is_nonreplayable_and_keeps_wall_bound():
    class Clock:
        now = 0.0
        def __call__(self):
            return self.now
    clock = Clock()
    process = FakeProcess(native({"type": "heartbeat"}))
    broker, _, _ = broker_with_processes(process, monotonic_clock=clock)
    class SilentNormalizer(EventNormalizer):
        def accept(self, event):
            clock.now = 901
            return super().accept(event)
    broker._make_normalizer = lambda: SilentNormalizer("future-frontier", "ultra")
    result = broker.turn(envelope())
    assert result["is_error"] and result["error"]["code"] == "turn_timeout"
    assert "inactivity" in result["error"]["message"]
    assert result["replay_safe"] is False


@pytest.mark.parametrize("mode,sandbox", [
    ("plan", "read-only"), ("acceptEdits", "workspace-write"),
    ("bypassPermissions", "danger-full-access"),
])
def test_permission_mapping_and_explicit_main_and_subagent_policy(mode, sandbox):
    argv = build_argv("codex", model="future-frontier", effort="ultra", permission_mode=mode)
    assert argv[:2] == ["codex", "exec"]
    assert argv[-1] == "-"
    assert f'sandbox_mode="{sandbox}"' in argv
    assert 'forced_login_method="chatgpt"' in argv
    assert 'approval_policy="never"' in argv
    assert 'model_reasoning_effort="ultra"' in argv
    assert 'agents.default_subagent_model="future-frontier"' in argv
    assert 'agents.default_subagent_reasoning_effort="ultra"' in argv
    assert "--ephemeral" not in argv and "--last" not in argv


def test_resume_uses_exact_id_and_supported_config_flags_only():
    argv = build_argv("codex", model="moving-model", effort="high",
                      permission_mode="plan", thread_id="exact-thread")
    assert argv[:3] == ["codex", "exec", "resume"]
    assert argv[-2:] == ["exact-thread", "-"]
    assert not {"--sandbox", "--cd", "--color", "--last", "--ephemeral"}.intersection(argv)


@pytest.mark.parametrize("changes", [
    {"permission_mode": "default"}, {"model": 'bad"model'},
    {"effort": "high\nextra"}, {"thread_id": 'bad\\thread'},
    {"thread_id": "--last"}, {"model": "--other-option"},
])
def test_invalid_launch_values_fail_before_spawn(changes):
    args = {"model": "moving", "effort": "high", "permission_mode": "plan", **changes}
    with pytest.raises(BridgeError):
        build_argv("codex", **args)


def test_normalizer_preserves_partial_text_deduplicates_and_does_not_invent_model():
    normalizer = EventNormalizer("requested", "ultra")
    init = normalizer.accept({"type": "thread.started", "thread_id": "t"})
    event = {"type": "item.completed", "item": {"id": "a", "type": "agent_message", "text": "partial"}}
    assert normalizer.accept(event)[0]["event"]["delta"]["text"] == "partial"
    assert normalizer.accept(event) == []
    result = normalizer.finish(1)
    assert init[0]["model_attested"] is False
    assert result["result"] == "partial"
    assert result["is_error"] is True and result["replay_safe"] is False
    assert result["model_served"] is None and result["model_attested"] is False
    assert normalizer.finish(1) is None


def test_only_explicit_native_model_can_attest_and_usage_is_whitelisted():
    normalizer = EventNormalizer("requested", "ultra")
    normalizer.accept({"type": "turn.completed", "model": "actually-served", "usage": {
        "input_tokens": 12, "output_tokens": 4, "cached_input_tokens": 2,
        "private": "secret", "cost": 100,
    }})
    result = normalizer.finish(0)
    assert result["model_served"] == "actually-served" and result["model_attested"] is True
    assert result["requested_model"] == "requested"
    assert result["effort_served"] is None
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 4, "cached_input_tokens": 2}


def test_provider_failure_is_one_error_result_even_if_completed_event_follows():
    normalizer = EventNormalizer("requested", "high")
    normalizer.accept({"type": "turn.failed", "error": {"code": "quota", "message": "Limit reached"}})
    normalizer.accept({"type": "turn.completed"})
    result = normalizer.finish(0)
    assert result["is_error"] is True
    assert result["error"] == {"code": "quota", "message": "Limit reached"}
    assert normalizer.finish(0) is None


def test_tool_event_excludes_raw_arguments_outputs_and_reasoning():
    normalizer = EventNormalizer("requested", "high")
    event = {"type": "item.started", "item": {"type": "command_execution", "id": "tool",
             "command": "secret command", "aggregated_output": "private output", "status": "in_progress"}}
    translated = normalizer.accept(event)
    tool = translated[0]["message"]["content"][0]
    assert tool["input"] == {"item_id": "tool", "status": "in_progress"}
    assert "secret" not in json.dumps(translated) and "private" not in json.dumps(translated)
    assert normalizer.accept({**event, "type": "item.completed"}) == []
    assert normalizer.accept({"type": "item.completed", "item": {"type": "reasoning", "text": "private"}}) == []


def test_resume_thread_mismatch_fails_closed():
    normalizer = EventNormalizer("requested", "high", "owned-thread")
    with pytest.raises(BridgeError, match="unexpected thread"):
        normalizer.accept({"type": "thread.started", "thread_id": "other-thread"})


def test_two_turns_use_stdin_then_exact_resume_and_frozen_policy():
    first, second = FakeProcess(successful()), FakeProcess(successful("second"))
    broker, calls, events = broker_with_processes(first, second)
    assert broker.turn(envelope("user-one", system_prompt="private system contract"))["is_error"] is False
    assert broker.turn(envelope("user-two"))["is_error"] is False
    assert first.stdin.captured == b"private system contract\n\nuser-one\n"
    assert second.stdin.captured == b"user-two\n"
    assert calls[0][0][:2] == ["codex-stub", "exec"]
    assert calls[1][0][:3] == ["codex-stub", "exec", "resume"]
    assert calls[1][0][-2:] == ["thread-1", "-"]
    assert all(options["shell"] is False for _, options in calls)
    assert all("private system contract" not in " ".join(argv) for argv, _ in calls)
    assert len([event for event in events if event["type"] == "result"]) == 2
    assert calls[0][0][calls[0][0].index("--model") + 1] == "future-frontier"
    assert calls[1][0][calls[1][0].index("--model") + 1] == "future-frontier"


def test_invalid_input_does_not_spawn_or_mutate_permissions():
    broker, calls, _ = broker_with_processes()
    result = broker.turn({"type": "user", "message": {"content": [{"type": "image", "data": "x"}]}})
    assert result["is_error"] is True and result["replay_safe"] is True
    assert calls == []


def test_changed_system_contract_is_rejected_without_spawning_another_turn():
    broker, calls, _ = broker_with_processes(FakeProcess(successful()))
    broker.turn(envelope(system_prompt="one"))
    result = broker.turn(envelope(system_prompt="two"))
    assert result["is_error"] is True and result["replay_safe"] is True
    assert len(calls) == 1


def test_unexpected_exit_keeps_partial_answer_and_never_replays():
    process = FakeProcess(native(
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.completed", "item": {"type": "agent_message", "id": "a", "text": "partial"}},
    ), stderr=b"private error details", code=1)
    broker, calls, emitted = broker_with_processes(process)
    result = broker.turn(envelope())
    assert result["result"] == "partial" and result["replay_safe"] is False
    assert result["model_attested"] is False and result["is_error"] is True
    assert "private error details" not in json.dumps(emitted)
    assert len(calls) == 1


@pytest.mark.parametrize("stdout,stderr,limits", [
    (b"x" * 101 + b"\n", b"", {"max_event_bytes": 100}),
    (successful(), b"x" * 100, {"max_turn_bytes": 50}),
    (b"not json\n", b"", {}),
])
def test_protocol_and_byte_budget_failures_return_one_ambiguous_error(stdout, stderr, limits):
    broker, _, emitted = broker_with_processes(FakeProcess(stdout, stderr), **limits)
    result = broker.turn(envelope())
    assert result["is_error"] is True and result["replay_safe"] is False
    assert len([event for event in emitted if event["type"] == "result"]) == 1


def test_owned_containment_hook_runs_before_prompt_and_closes_after_turn():
    process = FakeProcess(successful())
    lifecycle = []

    class Guard:
        def terminate(self):
            lifecycle.append("terminate")

        def close(self):
            lifecycle.append("close")

    def contain(child):
        assert child is process
        assert child.stdin.getvalue() == b""
        lifecycle.append("attach")
        return Guard()

    broker, _, _ = broker_with_processes(process, process_guard_factory=contain)
    assert broker.turn(envelope())["is_error"] is False
    assert lifecycle == ["attach", "close"]


def test_pre_cancelled_broker_never_spawns_and_reports_safe_failure():
    broker, calls, _ = broker_with_processes()
    broker.stop()
    result = broker.turn(envelope())
    assert result["is_error"] is True and result["replay_safe"] is True
    assert result["error"]["code"] == "cancelled"
    assert calls == []


def test_content_blocks_preserve_text_order():
    assert user_text({"type": "user", "message": {"content": [
        {"type": "text", "text": "one"}, {"type": "text", "text": "two"},
    ]}}) == ("one\ntwo", None)


def test_windows_default_guard_requires_suspended_and_hidden_creation():
    options = containment_spawn_options(WindowsJobGuard, windows=True)
    assert options["creationflags"] & CREATE_SUSPENDED
    assert options["creationflags"] & CREATE_NO_WINDOW


def test_custom_guard_can_supply_creation_flags_without_real_processes():
    class GuardFactory:
        creationflags = CREATE_SUSPENDED | 0x200

    assert containment_spawn_options(GuardFactory, windows=True)["creationflags"] == (
        CREATE_NO_WINDOW | CREATE_SUSPENDED | 0x200
    )


def test_posix_group_is_new_session_and_honestly_degraded():
    assert containment_spawn_options(PosixProcessGroupGuard, windows=False) == {"start_new_session": True}
    assert PosixProcessGroupGuard.containment["degraded"] is True
    assert PosixProcessGroupGuard.containment["descendants_verified"] is False


def test_windows_guard_verifies_or_terminates_descendants_before_close():
    calls = []
    process = object()

    class Job:
        def assign_and_resume(self, child):
            assert child is process
            calls.append("assign_resume")
            return True

        def verify_empty(self, timeout_seconds):
            assert timeout_seconds == 2
            calls.append("verify")
            return calls.count("verify") > 1

        def terminate_verified(self, child, timeout_seconds):
            assert child is process and timeout_seconds == 5
            calls.append("terminate")
            return True

        def close(self):
            calls.append("close")
            return True

    guard = WindowsJobGuard(process, job_factory=Job)
    guard.close()
    assert calls == ["assign_resume", "verify", "terminate", "verify", "close"]


def test_windows_assignment_failure_aborts_suspended_child_and_closes_handle():
    calls = []

    class Job:
        def assign_and_resume(self, child):
            raise RuntimeError("private operating-system details")

        def abort_suspended(self, child):
            calls.append("abort")

        def close(self):
            calls.append("close")
            return True

    with pytest.raises(BridgeError, match="Could not establish Windows process containment") as error:
        WindowsJobGuard(object(), job_factory=Job)
    assert "private" not in str(error.value)
    assert calls == ["abort", "close"]


def test_windows_cleanup_failure_is_not_suppressed():
    class Job:
        def assign_and_resume(self, child):
            return True

        def verify_empty(self, timeout_seconds):
            return False

        def terminate_verified(self, child, timeout_seconds):
            return False

        def close(self):
            return True

    guard = WindowsJobGuard(object(), job_factory=Job)
    with pytest.raises(BridgeError, match="not verified"):
        guard.close()


def test_cleanup_failure_turns_native_success_into_one_error_result():
    class Guard:
        containment = {"mode": "fake_job", "descendants_verified": True, "degraded": False}

        def terminate(self):
            return True

        def close(self):
            return False

    broker, _, emitted = broker_with_processes(FakeProcess(successful()), process_guard_factory=lambda child: Guard())
    result = broker.turn(envelope())
    assert result["is_error"] is True
    assert result["result"] == "answer"
    assert result["error"]["code"] == "containment_cleanup_failed"
    assert result["containment"]["descendants_verified"] is False
    assert result["model_attested"] is False
    assert len([event for event in emitted if event["type"] == "result"]) == 1


class BlockedPromptProcess(FakeProcess):
    """A fake provider that emits text but never consumes prompt bytes."""

    def __init__(self):
        super().__init__(successful("partial"))
        self.returncode = None
        self.released = threading.Event()
        self.write_started = threading.Event()
        process = self

        class BlockedInput:
            def write(self, data):
                process.write_started.set()
                if not process.released.wait(timeout=3):
                    raise OSError("fake writer remained blocked")
                raise BrokenPipeError("private write failure")

            def flush(self):
                pass

            def close(self):
                pass

        self.stdin = BlockedInput()

    def terminate(self):
        super().terminate()
        self.released.set()


def test_blocked_prompt_write_is_bounded_and_keeps_partial_output():
    process = BlockedPromptProcess()
    broker, calls, emitted = broker_with_processes(process, turn_timeout_seconds=0.1)
    start = time.monotonic()
    result = broker.turn(envelope())
    assert time.monotonic() - start < 1.5
    assert process.write_started.is_set() and process.terminated
    assert result["error"]["code"] == "turn_timeout"
    assert result["result"] == "partial" and result["replay_safe"] is False
    assert result["model_attested"] is False
    assert len(calls) == 1
    assert len([event for event in emitted if event["type"] == "result"]) == 1


def test_cancellation_interrupts_blocked_prompt_write():
    process = BlockedPromptProcess()
    broker, _, _ = broker_with_processes(process, turn_timeout_seconds=5)

    def cancel_after_write_starts():
        assert process.write_started.wait(timeout=1)
        broker.stop()

    canceller = threading.Thread(target=cancel_after_write_starts, daemon=True)
    canceller.start()
    result = broker.turn(envelope())
    canceller.join(timeout=1)
    assert result["is_error"] is True and result["error"]["code"] == "cancelled"
    assert result["replay_safe"] is False and process.terminated


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), 43201, True])
def test_turn_timeout_must_be_positive_finite_and_bounded(timeout):
    with pytest.raises(BridgeError, match="Turn timeout"):
        broker_with_processes(turn_timeout_seconds=timeout)


def test_closed_job_cannot_emit_success_before_close_verification():
    order = []

    class Guard:
        def terminate(self):
            order.append("terminate")

        def close(self):
            order.append("close_verified")

    broker, _, _ = broker_with_processes(FakeProcess(successful()), process_guard_factory=lambda child: Guard())
    broker.emit = lambda event: order.append("result" if event["type"] == "result" else "event")
    broker.turn(envelope())
    assert order[-2:] == ["close_verified", "result"]

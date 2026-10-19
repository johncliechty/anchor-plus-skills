"""Broker contracts for large native events, identity, errors, and progress."""

import io
import json

from steward_cockpit.codex_event_stream import iter_codex_events
from steward_cockpit.codex_turn_bridge import EventNormalizer
from tests.test_codex_turn_bridge_2026_09_08 import (
    FakeProcess,
    broker_with_processes,
    envelope,
    native,
    successful,
)


THREAD = "5835bc4e-dd63-4bb6-beb9-839f8aed86de"
OTHER_THREAD = "9620992f-86c6-4e83-b52c-5bf0b73e4a52"
USAGE = {"input_tokens": 5, "output_tokens": 3}


def command_event(output, *, status="completed", thread=THREAD):
    return {
        "type": "item.completed" if status == "completed" else "item.updated",
        "thread_id": thread,
        "item": {
            "id": "synthetic-command", "type": "command_execution",
            "command": "synthetic fixture only", "status": status,
            "exit_code": 0 if status == "completed" else None,
            "aggregated_output": output,
        },
    }


def completed_turn(answer, *middle):
    return native(
        {"type": "thread.started", "thread_id": THREAD},
        *middle,
        {"type": "item.completed", "thread_id": THREAD,
         "item": {"id": "answer", "type": "agent_message", "text": answer}},
        {"type": "turn.completed", "thread_id": THREAD, "usage": USAGE},
    )


def assert_success(result, emitted, answer):
    assert result["is_error"] is False
    assert result["result"] == answer
    assert result["session_id"] == THREAD
    assert not result.get("error")
    assert result["usage"]["input_tokens"] == USAGE["input_tokens"]
    assert result["usage"]["output_tokens"] == USAGE["output_tokens"]
    assert emitted[-1]["is_error"] is False
    assert emitted[-1]["result"] == answer


def assert_single_stdin_message(process, message):
    expected = message.encode("utf-8")
    # A single terminal newline is transport framing, not another user request.
    assert process.stdin.captured in (expected, expected + b"\n")


def test_native_command_over_16_mib_preserves_answer_and_usage_without_emitting_body():
    marker = "SYNTHETIC_COMMAND_BODY_MUST_NOT_REACH_CLIENT"
    payload = marker + "\n" + ("x" * (18 * 1024 * 1024))
    answer = "Complete final answer: Unicode π and all final text remain intact."
    process = FakeProcess(completed_turn(answer, command_event(payload)))
    broker, calls, emitted = broker_with_processes(process)

    result = broker.turn(envelope("Summarize the synthetic command result."))

    assert_success(result, emitted, answer)
    assert len(calls) == 1
    emitted_text = json.dumps(emitted, ensure_ascii=False)
    assert marker not in emitted_text
    assert "x" * 4096 not in emitted_text
    assert len(emitted_text.encode("utf-8")) < 64 * 1024


def test_explicit_event_cap_does_not_replay_original_or_break_next_turn():
    original_message = "Original synthetic request; execute it only once."
    followup_message = "A distinct synthetic follow-up request."
    first_process = FakeProcess(native(
        {"type": "thread.started", "thread_id": THREAD},
        command_event("x" * 8192),
    ))
    answer = "Follow-up completed."
    next_process = FakeProcess(successful(answer, thread=THREAD))
    broker, calls, emitted = broker_with_processes(
        first_process, next_process, max_event_bytes=2048,
    )

    failed = broker.turn(envelope(original_message))

    assert failed["is_error"] is True
    assert failed["error"]["code"] == "transport_output_limit"
    assert failed["session_id"] == THREAD
    assert failed["replay_safe"] is False
    assert emitted[-1]["is_error"] is True
    assert len(calls) == 1
    assert_single_stdin_message(first_process, original_message)

    recovered = broker.turn(envelope(followup_message, session_id=THREAD))

    assert_success(recovered, emitted, answer)
    assert len(calls) == 2
    assert "resume" in calls[1][0]
    assert THREAD in calls[1][0]
    assert_single_stdin_message(next_process, followup_message)
    assert_single_stdin_message(first_process, original_message)


def test_projection_cannot_hide_a_wrong_thread_identity():
    wrong_answer = "This answer belongs to another thread."
    process = FakeProcess(native(
        {"type": "thread.started", "thread_id": THREAD},
        {"type": "item.completed", "thread_id": OTHER_THREAD,
         "item": {"id": "wrong-answer", "type": "agent_message", "text": wrong_answer}},
        {"type": "turn.completed", "thread_id": THREAD, "usage": USAGE},
    ))
    broker, calls, emitted = broker_with_processes(process)

    result = broker.turn(envelope())

    assert result["is_error"] is True
    assert result["error"]["code"] == "transport_error"
    assert "unexpected thread" in result["error"]["message"].lower()
    assert wrong_answer not in json.dumps(emitted)
    assert emitted[-1]["is_error"] is True
    assert len(calls) == 1


def test_actual_provider_error_retains_its_code_and_message():
    code = "rate_limit_exceeded"
    message = "Synthetic provider request limit; retry after the stated reset."
    process = FakeProcess(native(
        {"type": "thread.started", "thread_id": THREAD},
        {"type": "turn.failed", "thread_id": THREAD,
         "error": {"code": code, "message": message}},
    ))
    broker, calls, emitted = broker_with_processes(process)

    result = broker.turn(envelope())

    assert result["is_error"] is True
    assert result["error"]["code"] == code
    assert result["error"]["message"] == message
    assert emitted[-1]["error"]["code"] == code
    assert emitted[-1]["error"]["message"] == message
    assert len(calls) == 1


def test_successful_answer_with_quota_terms_is_still_success():
    answer = "Usage limit, rate limit, quota, capacity, overloaded, and 429 are example terms."
    broker, calls, emitted = broker_with_processes(
        FakeProcess(successful(answer, thread=THREAD)),
    )

    result = broker.turn(envelope("Explain these example terms."))

    assert_success(result, emitted, answer)
    assert len(calls) == 1


def test_changed_aggregate_output_counts_as_progress_without_retaining_raw_output():
    outputs = ["first synthetic progress", "second synthetic progress", "second synthetic progress"]
    projected = list(iter_codex_events(io.BytesIO(native(
        *(command_event(output, status="in_progress") for output in outputs),
    ))))
    normalizer = EventNormalizer("future-frontier", "ultra", THREAD)
    progress = []
    fingerprints = []
    for event, _raw_bytes in projected:
        fingerprint = event["item"]["aggregated_output"]
        assert isinstance(fingerprint, str)
        assert fingerprint not in outputs
        fingerprints.append(fingerprint)
        translated = normalizer.accept(event)
        progress.append(normalizer.made_progress(event, translated))

    assert len(projected) == 3
    assert fingerprints[0] != fingerprints[1]
    assert fingerprints[1] == fingerprints[2]
    assert progress == [True, True, False]

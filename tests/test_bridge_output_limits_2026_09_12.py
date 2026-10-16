"""Native output size handling, independently of subscription/model failures."""

import re

import pytest

from tests.test_codex_turn_bridge_2026_09_08 import (
    FakeProcess,
    broker_with_processes,
    envelope,
    native,
)


THREAD_ID = "56e2fceb-1ea5-4c3d-a2e5-a0a67f578c8e"


def command_event(item_id, output_bytes):
    return {
        "type": "item.completed",
        "item": {
            "id": item_id,
            "type": "command_execution",
            "command": "synthetic output fixture",
            "aggregated_output": "x" * output_bytes,
            "status": "completed",
            "exit_code": 0,
        },
    }


def completed_stream(*events):
    return native(
        {"type": "thread.started", "thread_id": THREAD_ID},
        *events,
        {"type": "item.completed", "item": {
            "id": "reply", "type": "agent_message", "text": "complete",
        }},
        {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 3}},
    )


def test_single_native_command_event_over_two_mib_completes():
    event = command_event("large-command", 2 * 1024 * 1024 + 1024)
    assert len(native(event)) > 2 * 1024 * 1024
    broker, _, emitted = broker_with_processes(FakeProcess(completed_stream(event)))

    result = broker.turn(envelope())

    assert not result["is_error"]
    assert result["usage"] == {"input_tokens": 5, "output_tokens": 3}
    assert emitted[-1] == result


def test_cumulative_native_command_output_over_eight_mib_completes():
    stream = completed_stream(*(command_event(f"command-{index}", 2 * 1024 * 1024)
                                for index in range(5)))
    assert len(stream) > 8 * 1024 * 1024
    broker, _, emitted = broker_with_processes(FakeProcess(stream))
    assert broker.max_turn_bytes is None

    result = broker.turn(envelope())

    assert not result["is_error"]
    assert result["usage"] == {"input_tokens": 5, "output_tokens": 3}
    assert emitted[-1] == result


@pytest.mark.parametrize("limits, bound", [
    ({"max_event_bytes": 1024}, "event"),
    ({"max_event_bytes": 2048, "max_turn_bytes": 2048}, "turn"),
])
def test_explicit_output_bounds_fail_locally_and_preserve_thread_identity(limits, bound):
    broker, _, emitted = broker_with_processes(
        FakeProcess(completed_stream(
            command_event("bounded-command-1", 1024),
            command_event("bounded-command-2", 1024),
        )),
        **limits,
    )

    result = broker.turn(envelope())

    assert result["is_error"]
    assert result["error"]["code"] == "transport_output_limit"
    message = result["error"]["message"]
    assert "Anchor transport" in message
    assert "local size bound" in message
    assert bound in message
    measured = re.search(r"(?:at least |of )([0-9]+) bytes", message)
    assert measured is not None
    assert int(measured.group(1)) > limits[f"max_{bound}_bytes"]
    assert f"{limits[f'max_{bound}_bytes']} bytes" in message
    if bound == "event":
        assert "at least" in message
    assert "synthetic output fixture" not in message
    assert len(message) < 300
    assert result["replay_safe"] is False
    assert result["session_id"] == THREAD_ID
    assert emitted[-1] == result


def test_malformed_json_remains_a_transport_error():
    stream = native({"type": "thread.started", "thread_id": THREAD_ID}) + b'{"type":\n'
    broker, _, emitted = broker_with_processes(FakeProcess(stream))

    result = broker.turn(envelope())

    assert result["is_error"]
    assert result["error"]["code"] == "transport_error"
    assert result["replay_safe"] is False
    assert result["session_id"] == THREAD_ID
    assert emitted[-1] == result


@pytest.mark.parametrize("option", ["max_event_bytes", "max_turn_bytes"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "1024"])
def test_output_bounds_reject_nonpositive_or_noninteger_configuration(option, value):
    with pytest.raises(ValueError, match=option):
        broker_with_processes(FakeProcess(completed_stream()), **{option: value})


def test_native_provider_receives_complete_large_prompt_without_anchor_quota():
    process = FakeProcess(completed_stream())
    broker, _, _ = broker_with_processes(process)
    text = "x" * (8 * 1024 * 1024 + 1)
    result = broker.turn(envelope(text))
    assert not result["is_error"]
    assert process.stdin.captured == (text + "\n").encode()
    assert broker.max_event_bytes is None

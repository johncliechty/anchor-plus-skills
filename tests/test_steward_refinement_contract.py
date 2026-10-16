"""Transport contracts only; the Node lifecycle is exercised by integration tests."""

import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from steward_cockpit import refinement_client as client


CAPABILITIES = {"ok": True, "capabilities": {"schema": "ecgberht-refinement-v1", "version": 1}}
OPERATION = {"action": "request_refinement", "operation_id": "feedback-1", "expected_seq": 3, "slice_id": "foundation"}


def response(value, code=0):
    return subprocess.CompletedProcess([], code, json.dumps(value), "")


def state_response(*, managed=True, consistent=True, sequence=3, **extra):
    return {
        "ok": True,
        "state": {"managed": managed},
        "sequence": sequence,
        "projection_status": {"consistent": consistent},
        **extra,
    }


@pytest.fixture
def cli(tmp_path):
    target = tmp_path / "path with spaces" / "ecgberht.mjs"
    target.parent.mkdir()
    target.write_text("// A path seam; mocked subprocess never executes this file.\n", encoding="utf-8")
    return target


def test_explicit_missing_cli_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.setenv(client.CLI_ENV, str(tmp_path / "missing.mjs"))
    with patch.object(client.subprocess, "run") as run:
        result = client.read_state(tmp_path)
    assert result["error"] == "dependency-missing"
    assert result["component"] == "cli"
    assert result["configured"] is True
    run.assert_not_called()


def test_missing_node_is_a_dependency_failure(cli, tmp_path):
    with patch.object(client.shutil, "which", return_value=None), patch.object(client.subprocess, "run") as run:
        result = client.read_state(tmp_path, cli_path=cli)
    assert result["error"] == "dependency-missing"
    assert result["component"] == "node"
    run.assert_not_called()


def test_read_capability_checks_and_uses_argument_array_without_shell(cli, tmp_path):
    project = tmp_path / "campaign spaces & literals"
    with patch.object(client.shutil, "which", return_value="node-resolved"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(state_response())]
    ) as run:
        result = client.read_state(project, cli_path=cli)
    assert result["ok"] is True
    assert len(run.call_args_list) == 2
    for call in run.call_args_list:
        assert call.args[0] == ["node-resolved", str(cli.resolve()), "refinement-update", "--project", str(project)]
        assert call.kwargs["shell"] is False
        assert call.kwargs["timeout"] == 20
        assert call.kwargs["encoding"] == "utf-8"
        assert call.kwargs["creationflags"] == (getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    assert [json.loads(call.kwargs["input"])["action"] for call in run.call_args_list] == ["capabilities", "read"]


def test_capability_request_runs_once(cli, tmp_path):
    with patch.object(client.shutil, "which", return_value="node"), patch.object(client.subprocess, "run", return_value=response(CAPABILITIES)) as run:
        result = client.invoke(tmp_path, {"action": "capabilities"}, cli_path=cli)
    assert result == CAPABILITIES
    assert run.call_count == 1


def test_incompatible_capabilities_stop_before_mutation(cli, tmp_path):
    incompatible = {"ok": True, "capabilities": {"schema": "older-protocol", "version": 1}}
    with patch.object(client.shutil, "which", return_value="node"), patch.object(client.subprocess, "run", return_value=response(incompatible)) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["error"] == "dependency-incompatible"
    assert run.call_count == 1


@pytest.mark.parametrize("invalid", [None, [], {}, {"ok": 1}, {"ok": True}, {"ok": False}, {"ok": False, "error": ""}, {"ok": True, "state": {}}, state_response(sequence=True)])
def test_invalid_envelopes_never_become_success(cli, tmp_path, invalid):
    with patch.object(client.shutil, "which", return_value="node"), patch.object(client.subprocess, "run", side_effect=[response(CAPABILITIES), response(invalid)]):
        result = client.read_state(tmp_path, cli_path=cli)
    assert result["ok"] is False
    assert result["error"] == "dependency-returns-garbage"


@pytest.mark.parametrize("raw", ["", "   ", "model chatter\n{}", "{broken"])
def test_empty_or_malformed_output_is_not_empty_state(cli, tmp_path, raw):
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), subprocess.CompletedProcess([], 0, raw, "private diagnostic")]
    ):
        result = client.read_state(tmp_path, cli_path=cli)
    assert result["error"] == "dependency-returns-garbage"
    assert "private diagnostic" not in json.dumps(result)


@pytest.mark.parametrize("error", ["backing-store-unreadable", {"code": "projection-conflict", "region": "plan"}])
def test_meaningful_nonzero_failure_identity_is_preserved(cli, tmp_path, error):
    failure = {"ok": False, "error": error, "sequence": 3, "repair_required": True}
    with patch.object(client.shutil, "which", return_value="node"), patch.object(client.subprocess, "run", side_effect=[response(CAPABILITIES), response(failure, 2)]):
        result = client.read_state(tmp_path, cli_path=cli)
    assert result == failure


def test_nonzero_success_envelope_is_invalid(cli, tmp_path):
    with patch.object(client.shutil, "which", return_value="node"), patch.object(client.subprocess, "run", side_effect=[response(CAPABILITIES), response(state_response(), 1)]):
        result = client.read_state(tmp_path, cli_path=cli)
    assert result["error"] == "dependency-returns-garbage"


@pytest.mark.parametrize("expected", [state_response(managed=False), state_response(consistent=False)])
def test_unmanaged_empty_state_and_projection_lag_remain_distinct_valid_reads(cli, tmp_path, expected):
    with patch.object(client.shutil, "which", return_value="node"), patch.object(client.subprocess, "run", side_effect=[response(CAPABILITIES), response(expected)]):
        result = client.read_state(tmp_path, cli_path=cli)
    assert result == expected


def test_normal_mutation_submitted_once_after_capability_check(cli, tmp_path):
    expected = state_response(sequence=4, committed=True, consistent=True, operation_id=OPERATION["operation_id"])
    expected["consistent"] = True
    with patch.object(client.shutil, "which", return_value="node"), patch.object(client.subprocess, "run", side_effect=[response(CAPABILITIES), response(expected)]) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result == expected
    assert [json.loads(call.kwargs["input"])["action"] for call in run.call_args_list] == ["capabilities", OPERATION["action"]]


def test_timed_out_mutation_reconciles_commit_without_resubmission(cli, tmp_path):
    status = state_response(sequence=4, consistent=True, committed=True, operation_id=OPERATION["operation_id"])
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), subprocess.TimeoutExpired("node", 20), response(status)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    requests = [json.loads(call.kwargs["input"]) for call in run.call_args_list]
    assert requests == [{"action": "capabilities"}, OPERATION, {"action": "operation_status", "operation_id": "feedback-1"}]
    assert all(call.kwargs["timeout"] == 20 for call in run.call_args_list)
    assert result["committed"] is True
    assert result["consistent"] is True
    assert result["state"] == status["state"]
    assert result["ok"] is True
    assert result["reconciled_after_interruption"] is True


def test_timeout_with_no_observed_commit_remains_interrupted(cli, tmp_path):
    status = state_response(committed=False, operation_id=OPERATION["operation_id"])
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), subprocess.TimeoutExpired("node", 20), response(status)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["error"] == "dependency-slow-or-killed"
    assert result["commit_status"] == "not-observed"
    assert run.call_count == 3


def test_second_timeout_is_bounded_and_leaves_commit_unknown(cli, tmp_path):
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), subprocess.TimeoutExpired("node", 20), subprocess.TimeoutExpired("node", 20)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["error"] == "dependency-slow-or-killed"
    assert result["commit_status"] == "unknown"
    assert result["reconciliation"]["reason"] == "timeout"
    assert run.call_count == 3


def test_reconciliation_for_different_operation_cannot_confirm_commit(cli, tmp_path):
    status = state_response(committed=True, operation_id="someone-elses-operation")
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), subprocess.TimeoutExpired("node", 20), response(status)]
    ):
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["ok"] is False
    assert result["commit_status"] == "unknown"
    assert result["reconciliation"]["error"] == "dependency-returns-garbage"


def test_killed_mutation_also_reconciles_instead_of_replaying(cli, tmp_path):
    status = state_response(committed=False, operation_id=OPERATION["operation_id"])
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), subprocess.CompletedProcess([], -9, "", ""), response(status)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["reason"] == "exit-without-response"
    assert result["commit_status"] == "not-observed"
    assert run.call_count == 3


@pytest.mark.parametrize("operation", [{"action": "read"}, {"action": "request_refinement", "expected_seq": 0}, {"action": "request_refinement", "operation_id": "one", "expected_seq": True}])
def test_invalid_mutations_do_not_start_a_child(tmp_path, operation):
    with patch.object(client.subprocess, "run") as run:
        result = client.update(tmp_path, operation)
    assert result["error"] == "invalid-request"
    run.assert_not_called()


def _requests(run):
    return [json.loads(call.kwargs["input"]) for call in run.call_args_list]


def _mutation_success():
    result = state_response(sequence=4, committed=True, operation_id=OPERATION["operation_id"])
    result["consistent"] = True
    return result


@pytest.mark.parametrize("code", ["projection-lag", "committed-needs-repair"])
def test_committed_projection_failure_repairs_once_without_second_mutation(cli, tmp_path, code):
    original = {"ok": False, "error": code, "committed": True, "consistent": False}
    status = state_response(sequence=4, committed=True, operation_id=OPERATION["operation_id"])
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(original, 1), response(state_response(sequence=4)), response(status)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["ok"] is True
    assert result["committed"] is True
    assert result["sequence"] == 4
    assert result["recovered_after_projection_repair"] is True
    assert _requests(run) == [
        {"action": "capabilities"}, OPERATION, {"action": "repair"},
        {"action": "operation_status", "operation_id": OPERATION["operation_id"]},
    ]


def test_interrupted_committed_operation_with_lag_uses_same_bounded_repair(cli, tmp_path):
    lagging = state_response(sequence=4, consistent=False, committed=True, operation_id=OPERATION["operation_id"])
    repaired = state_response(sequence=4)
    confirmed = state_response(sequence=4, committed=True, operation_id=OPERATION["operation_id"])
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), subprocess.TimeoutExpired("node", 20), response(lagging), response(repaired), response(confirmed)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["ok"] is True
    requests = _requests(run)
    assert requests.count(OPERATION) == 1
    assert requests.count({"action": "repair"}) == 1
    assert [request["action"] for request in requests] == ["capabilities", OPERATION["action"], "operation_status", "repair", "operation_status"]
    assert all(call.kwargs["timeout"] == 20 for call in run.call_args_list)


def test_prior_projection_lag_retries_only_confirmed_absent_same_operation(cli, tmp_path):
    prior_lag = {"ok": False, "error": "projection-lag", "committed": False, "consistent": False}
    absent = state_response(committed=False, operation_id=OPERATION["operation_id"])
    expected = _mutation_success()
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(prior_lag, 1), response(state_response()), response(absent), response(expected)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result == expected
    assert _requests(run) == [
        {"action": "capabilities"}, OPERATION, {"action": "repair"},
        {"action": "operation_status", "operation_id": OPERATION["operation_id"]}, OPERATION,
    ]


def test_external_content_conflict_does_not_attempt_repair(cli, tmp_path):
    failure = {"ok": False, "error": "managed-content-conflict", "committed": True, "consistent": False, "region": "plan"}
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(failure, 1)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result == failure
    assert len(_requests(run)) == 2


def test_refused_repair_preserves_external_conflict_and_confirmed_commit(cli, tmp_path):
    original = {"ok": False, "error": "projection-lag", "committed": True, "consistent": False}
    refused = {"ok": False, "error": "managed-content-conflict", "consistent": False, "region": "deliverables", "reason": "missing-marker"}
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(original, 1), response(refused, 1)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["error"] == refused["error"]
    assert result["region"] == refused["region"]
    assert result["reason"] == refused["reason"]
    assert result["committed"] is True
    assert result["recovery"]["stage"] == "repair"
    assert len(_requests(run)) == 3


@pytest.mark.parametrize("repair_response, expected_error", [
    (subprocess.CompletedProcess([], 0, "{garbage", ""), "dependency-returns-garbage"),
    (FileNotFoundError(), "dependency-missing"),
    (subprocess.TimeoutExpired("node", 20), "dependency-slow-or-killed"),
])
def test_unavailable_repair_never_replays_committed_mutation(cli, tmp_path, repair_response, expected_error):
    original = {"ok": False, "error": "projection-lag", "committed": True, "consistent": False}
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(original, 1), repair_response]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["ok"] is False
    assert result["error"] == expected_error
    assert result["committed"] is True
    assert _requests(run).count(OPERATION) == 1
    assert len(_requests(run)) == 3


def test_old_sequence_conflict_after_repair_is_not_rebased_or_hidden(cli, tmp_path):
    prior_lag = {"ok": False, "error": "projection-lag", "consistent": False}
    absent = state_response(sequence=8, committed=False, operation_id=OPERATION["operation_id"])
    conflict = {"ok": False, "error": "sequence-conflict", "expected_seq": 3, "sequence": 8}
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(prior_lag, 1), response(state_response(sequence=8)), response(absent), response(conflict, 1)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result == conflict
    assert _requests(run)[-1] == OPERATION
    assert _requests(run)[-1]["expected_seq"] == 3


def test_second_projection_lag_stops_without_repair_loop(cli, tmp_path):
    lag = {"ok": False, "error": "projection-lag", "consistent": False}
    absent = state_response(committed=False, operation_id=OPERATION["operation_id"])
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(lag, 1), response(state_response()), response(absent), response(lag, 1)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result == lag
    assert _requests(run).count({"action": "repair"}) == 1
    assert _requests(run).count(OPERATION) == 2


def test_failed_reconciliation_after_repair_does_not_guess_or_replay(cli, tmp_path):
    lag = {"ok": False, "error": "projection-lag", "consistent": False}
    unreadable = {"ok": False, "error": "backing-store-unreadable"}
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(lag, 1), response(state_response()), response(unreadable, 1)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["error"] == "backing-store-unreadable"
    assert result["recovery"]["stage"] == "operation_status"
    assert _requests(run).count(OPERATION) == 1


def test_read_with_projection_lag_has_no_repair_side_effect(cli, tmp_path):
    lag = {"ok": False, "error": "projection-lag", "consistent": False}
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(lag, 1)]
    ) as run:
        result = client.read_state(tmp_path, cli_path=cli)
    assert result == lag
    assert _requests(run) == [{"action": "capabilities"}, {"action": "read"}]


def test_contradictory_status_never_replays_an_already_confirmed_commit(cli, tmp_path):
    committed_lag = {"ok": False, "error": "projection-lag", "committed": True, "consistent": False}
    absent = state_response(sequence=4, committed=False, operation_id=OPERATION["operation_id"])
    with patch.object(client.shutil, "which", return_value="node"), patch.object(
        client.subprocess, "run", side_effect=[response(CAPABILITIES), response(committed_lag, 1), response(state_response(sequence=4)), response(absent)]
    ) as run:
        result = client.update(tmp_path, OPERATION, cli_path=cli)
    assert result["error"] == "dependency-returns-garbage"
    assert result["committed"] is True
    assert _requests(run).count(OPERATION) == 1

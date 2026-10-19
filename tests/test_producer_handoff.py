"""Producer handoff transport preserves dispatch context and user review."""

from copy import deepcopy
import hashlib
import json
from unittest.mock import patch

import pytest

from steward_cockpit import producer_handoff as handoff


def slice_state(*, phase="awaiting_review", round=1):
    return {"phase": phase, "work_phase": "idle", "round": round,
            "requirements": {"keep": ["clear notation"], "retired": ["old figure"]},
            "candidate": {"guide": "presentation-1"}, "depends_on": ["definitions"]}


def read_result(*, managed=True, sequence=7, slices=None, existing=None):
    return {"ok": True, "sequence": sequence,
            "state": {"managed": managed,
                      "slices": {"foundation": slice_state()} if slices is None else slices,
                      "producer_handoffs": {} if existing is None else existing}}


def captured(*, round=1):
    state = slice_state(round=round)
    return {"step_id": "foundation", **{key: deepcopy(state[key]) for key in ("round", "requirements", "candidate", "depends_on")}}


def expected_id(kind="job", producer_id="job-17"):
    raw = json.dumps([kind, producer_id], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "producer-handoff-" + hashlib.sha256(raw).hexdigest()


def test_unmanaged_capture_and_handoff_are_explicitly_skipped_without_mutation():
    with patch.object(handoff.refinement_client, "read_state", return_value=read_result(managed=False)), patch.object(handoff.refinement_client, "update") as update:
        assert handoff.capture_context("campaign") is None
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17")
    assert result == {"ok": True, "skipped": True, "reason": "unmanaged"}
    update.assert_not_called()


def test_capture_uses_exact_step_and_keeps_an_independent_dispatch_snapshot():
    state = read_result(slices={"foundation": slice_state(), "later": slice_state(round=2)})
    with patch.object(handoff.refinement_client, "read_state", return_value=state):
        context = handoff.capture_context("campaign", step_id="foundation")
    assert context == captured()
    state["state"]["slices"]["foundation"]["requirements"]["keep"].append("a later change")
    state["state"]["slices"]["foundation"]["candidate"]["guide"] = "presentation-2"
    assert context == captured()


def test_capture_does_not_guess_among_multiple_unfinished_slices():
    state = read_result(slices={"foundation": slice_state(), "later": slice_state()})
    with patch.object(handoff.refinement_client, "read_state", return_value=state):
        assert handoff.capture_context("campaign") is None
        assert handoff.capture_context("campaign", step_id="unknown") is None


def test_capture_can_select_the_sole_unfinished_slice_or_an_explicit_done_slice():
    state = read_result(slices={"finished": slice_state(phase="done", round=0), "foundation": slice_state()})
    with patch.object(handoff.refinement_client, "read_state", return_value=state):
        assert handoff.capture_context("campaign") == captured()
        done = handoff.capture_context("campaign", step_id="finished")
    assert done["step_id"] == "finished"
    assert done["round"] == 0


@pytest.mark.parametrize("slices", [{}, {"foundation": slice_state(phase="done")}])
def test_no_unfinished_slice_has_no_implicit_context(slices):
    with patch.object(handoff.refinement_client, "read_state", return_value=read_result(slices=slices)):
        assert handoff.capture_context("campaign") is None


def test_read_failure_is_propagated_by_capture_and_record():
    failure = {"ok": False, "error": "backing-store-unreadable"}
    with patch.object(handoff.refinement_client, "read_state", return_value=failure), patch.object(handoff.refinement_client, "update") as update:
        assert handoff.capture_context("campaign") == failure
        assert handoff.record_handoff("campaign", "job", "job-17", "job:17") == failure
    update.assert_not_called()


def test_failed_capture_does_not_suppress_later_completion_handoff():
    failure = {"ok": False, "error": "dependency-missing"}
    completed = {"ok": True, "handoff": {"status": "pending", "freshness": "unknown"}}
    outputs = [{"path": "outputs/foundation.html", "label": "Completed foundation"}]
    with patch.object(handoff.refinement_client, "read_state", return_value=read_result()) as read, patch.object(handoff.refinement_client, "update", return_value=completed) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17", context=failure,
                                        outputs=outputs, inventory_complete=True)
    assert result == {**completed, "context_warning": {"error": "dependency-missing"}}
    operation = update.call_args.args[1]
    assert operation["step_id"] is None
    assert operation["dispatch_context"] is None
    assert operation["dispatch_error"] == "dependency-missing"
    assert operation["source_ref"] == "job:17"
    assert operation["outputs"] == outputs
    assert operation["inventory_complete"] is True
    assert read.call_count == update.call_count == 1


def test_failed_capture_preserves_only_safe_diagnostic_code():
    failure = {"ok": False, "error": {"code": "backing-store-unreadable", "message": "private path and transcript"}}
    with patch.object(handoff.refinement_client, "read_state", return_value=read_result()), patch.object(handoff.refinement_client, "update", return_value={"ok": True}) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17", context=failure)
    assert result["context_warning"] == {"error": "backing-store-unreadable"}
    assert "private path and transcript" not in json.dumps(update.call_args.args[1])
    assert "private path and transcript" not in json.dumps(result)


def test_handoff_records_explicit_inventory_for_review_without_closing_or_publishing():
    state = read_result()
    expected = {"ok": True, "handoff": {"status": "pending", "freshness": "current"}}
    inventory = [{"path": "outputs/foundation.html", "label": "Foundation draft"}]
    context = captured()
    with patch.object(handoff.refinement_client, "read_state", return_value=state), patch.object(handoff.refinement_client, "update", return_value=expected) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17",
                                        context=context, outputs=inventory, inventory_complete=True)
    assert result == expected
    assert update.call_count == 1
    operation = update.call_args.args[1]
    assert operation == {
        "action": "producer_handoff", "version": 1,
        "operation_id": expected_id(), "handoff_id": expected_id(), "expected_seq": 7,
        "step_id": "foundation", "producer_kind": "job", "source_ref": "job:17",
        "dispatch_context": context, "outputs": inventory,
        "inventory_complete": True, "terminal": "done",
    }
    assert operation["dispatch_context"] is not context
    assert operation["outputs"] is not inventory
    assert state["state"]["slices"]["foundation"]["phase"] == "awaiting_review"


def test_missing_context_or_inventory_is_not_inferred_at_completion():
    with patch.object(handoff.refinement_client, "read_state", return_value=read_result()), patch.object(handoff.refinement_client, "update", return_value={"ok": True}) as update:
        handoff.record_handoff("campaign", "terminal", "command-1", "terminal:1")
    operation = update.call_args.args[1]
    assert operation["step_id"] is None
    assert operation["dispatch_context"] is None
    assert operation["outputs"] == []
    assert operation["inventory_complete"] is False


def test_existing_handoff_is_returned_idempotently_without_new_mutation():
    existing = {"status": "pending", "freshness": "stale", "source_ref": "job:17"}
    with patch.object(handoff.refinement_client, "read_state", return_value=read_result(existing={expected_id(): existing})), patch.object(handoff.refinement_client, "update") as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "different-reference", context=captured(round=2))
    assert result == {"ok": True, "idempotent": True, "handoff_id": expected_id(), "handoff": existing, "sequence": 7}
    update.assert_not_called()


def test_same_producer_id_in_different_kinds_has_a_different_identity():
    with patch.object(handoff.refinement_client, "read_state", return_value=read_result()), patch.object(handoff.refinement_client, "update", return_value={"ok": True}) as update:
        for kind in ("job", "conversation", "terminal"):
            handoff.record_handoff("campaign", kind, "same-id", "explicit-reference")
    identifiers = [call.args[1]["handoff_id"] for call in update.call_args_list]
    assert len(set(identifiers)) == 3


@pytest.mark.parametrize("failure", [
    {"ok": False, "error": "managed-content-conflict"},
    {"ok": False, "error": "dependency-slow-or-killed", "committed": True},
    {"ok": False, "error": "invalid-producer-handoff"},
])
def test_real_failures_are_not_converted_to_success_or_retried(failure):
    with patch.object(handoff.refinement_client, "read_state", return_value=read_result()) as read, patch.object(handoff.refinement_client, "update", return_value=failure) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17", context=captured())
    assert result == failure
    assert read.call_count == update.call_count == 1


def test_one_cas_retry_refreshes_only_sequence_and_retains_stale_dispatch_context():
    context = captured(round=1)
    current = read_result(sequence=7, slices={"foundation": slice_state(round=2)})
    newer = read_result(sequence=8, slices={"foundation": slice_state(round=3)})
    conflict = {"ok": False, "error": "sequence-conflict"}
    expected = {"ok": True, "handoff": {"freshness": "stale"}}
    with patch.object(handoff.refinement_client, "read_state", side_effect=[current, newer]), patch.object(handoff.refinement_client, "update", side_effect=[conflict, expected]) as update:
        result = handoff.record_handoff("campaign", "conversation", "turn-1", "conversation:1", context=context)
    assert result == expected
    first, second = [call.args[1] for call in update.call_args_list]
    assert first["expected_seq"] == 7
    assert second["expected_seq"] == 8
    assert {key: value for key, value in first.items() if key != "expected_seq"} == {key: value for key, value in second.items() if key != "expected_seq"}
    assert second["dispatch_context"] == context
    assert second["dispatch_context"]["round"] == 1


def test_cas_recheck_finding_existing_handoff_does_not_resubmit():
    existing = {"status": "pending", "freshness": "current"}
    with patch.object(handoff.refinement_client, "read_state", side_effect=[read_result(), read_result(sequence=8, existing={expected_id(): existing})]), patch.object(handoff.refinement_client, "update", return_value={"ok": False, "error": "sequence-conflict"}) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17")
    assert result["idempotent"] is True
    assert result["handoff"] == existing
    assert update.call_count == 1


def test_second_cas_conflict_is_returned_without_a_loop():
    conflict = {"ok": False, "error": "sequence-conflict", "sequence": 9}
    with patch.object(handoff.refinement_client, "read_state", side_effect=[read_result(), read_result(sequence=8)]) as read, patch.object(handoff.refinement_client, "update", return_value=conflict) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17")
    assert result == conflict
    assert read.call_count == update.call_count == 2


def test_failed_cas_recheck_is_not_treated_as_absence():
    failure = {"ok": False, "error": "backing-store-unreadable"}
    with patch.object(handoff.refinement_client, "read_state", side_effect=[read_result(), failure]), patch.object(handoff.refinement_client, "update", return_value={"ok": False, "error": "sequence-conflict"}) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17")
    assert result == failure
    assert update.call_count == 1


def test_losing_managed_scope_during_cas_recheck_does_not_turn_failure_into_skip_success():
    conflict = {"ok": False, "error": "sequence-conflict"}
    with patch.object(handoff.refinement_client, "read_state", side_effect=[read_result(), read_result(managed=False)]), patch.object(handoff.refinement_client, "update", return_value=conflict) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17")
    assert result == conflict
    assert update.call_count == 1


def test_two_completion_callbacks_for_one_owned_job_share_the_js_handoff_identity():
    state = read_result()
    identifier = "producer-handoff-" + hashlib.sha256(b'["job","owned-job"]').hexdigest()
    recorded = {"producer_kind": "job", "source_ref": "job:owned-job", "status": "pending"}

    def commit(campaign_dir, operation):
        assert campaign_dir == "campaign"
        assert operation["handoff_id"] == identifier
        assert operation["operation_id"] == identifier
        state["state"]["producer_handoffs"][identifier] = deepcopy(recorded)
        state["sequence"] += 1
        return {"ok": True, "state": deepcopy(state["state"]), "sequence": state["sequence"]}

    with patch.object(handoff.refinement_client, "read_state", return_value=state) as read, patch.object(handoff.refinement_client, "update", side_effect=commit) as update:
        first = handoff.record_handoff("campaign", "job", "owned-job", "job:owned-job", context=captured())
        second = handoff.record_handoff("campaign", "job", "owned-job", "job:owned-job", context=captured())

    assert first["ok"] is True
    assert second == {"ok": True, "idempotent": True, "handoff_id": identifier,
                      "handoff": recorded, "sequence": 8}
    assert read.call_count == 2
    assert update.call_count == 1
    assert list(state["state"]["producer_handoffs"]) == [identifier]


def test_handoff_exists_reconciles_the_exact_existing_id_without_resubmission():
    existing = {"status": "resolved", "disposition": "no_deliverable", "source_ref": "job:17"}
    conflict = {"ok": False, "error": "HANDOFF_EXISTS"}
    with patch.object(handoff.refinement_client, "read_state", side_effect=[read_result(), read_result(sequence=8, existing={expected_id(): existing})]) as read, patch.object(handoff.refinement_client, "update", return_value=conflict) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17")
    assert result == {"ok": True, "idempotent": True, "handoff_id": expected_id(), "handoff": existing, "sequence": 8}
    assert read.call_count == 2
    assert update.call_count == 1


def test_handoff_exists_without_its_exact_id_stays_a_failure_and_is_not_retried():
    conflict = {"ok": False, "error": "HANDOFF_EXISTS"}
    other = {expected_id("job", "another-job"): {"status": "pending"}}
    with patch.object(handoff.refinement_client, "read_state", side_effect=[read_result(), read_result(sequence=8, existing=other)]) as read, patch.object(handoff.refinement_client, "update", return_value=conflict) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17")
    assert result == conflict
    assert read.call_count == 2
    assert update.call_count == 1


def test_handoff_exists_with_failed_reconciliation_never_claims_success():
    conflict = {"ok": False, "error": "HANDOFF_EXISTS"}
    unreadable = {"ok": False, "error": "backing-store-unreadable"}
    with patch.object(handoff.refinement_client, "read_state", side_effect=[read_result(), unreadable]), patch.object(handoff.refinement_client, "update", return_value=conflict) as update:
        result = handoff.record_handoff("campaign", "job", "job-17", "job:17")
    assert result == unreadable
    assert update.call_count == 1

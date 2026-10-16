"""Existing Engine accounting: invocation checkpoints and final reconciliation."""

import copy
import io
from types import SimpleNamespace

import pytest

import anchor_settings
from steward_cockpit import steward_engine as engine_mod


SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
FOREIGN_SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab9"
INVOCATION = "956f7cb6-404f-4cdb-8820-9d6ed2c7d189"
SECOND_INVOCATION = "956f7cb6-404f-4cdb-8820-9d6ed2c7d190"


@pytest.fixture
def cockpit(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": "chatgpt", "settings_revision": 1})
    engine = engine_mod.Engine(str(tmp_path), fake=True)
    engine.cli = "chatgpt"
    engine.session_id = SESSION
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(engine, "_status_update", lambda **kwargs: None)
    return engine


def checkpoint(input_tokens=100, output_tokens=20, cached=60, **extra):
    return {"type": "usage_checkpoint", "session_id": SESSION, "invocation_id": INVOCATION,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cached_input_tokens": cached},
            "token_status": "reported", "usage_source": "codex-rollout", **extra}


def result(input_tokens=150, output_tokens=30, cached=90, **extra):
    return {"type": "result", "subtype": "success", "session_id": SESSION,
            "usage_invocation_id": INVOCATION,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cached_input_tokens": cached},
            "token_status": "reported", "usage_source": "codex-turn-completed",
            "total_cost_usd": 0.25, "duration_ms": 2000, **extra}


def finish(engine, event):
    engine.turn_text = "Completed response."
    engine._handle(event, engine.proc)


def test_progress_adds_only_delta_and_excludes_cached_subset(cockpit):
    cockpit._handle(checkpoint(), cockpit.proc)
    assert cockpit.tokens == 120
    assert cockpit.turns == 0
    assert cockpit.secs == 0
    cockpit._handle(checkpoint(), cockpit.proc)
    assert cockpit.tokens == 120
    cockpit._handle(checkpoint(150, 30, 90), cockpit.proc)
    assert cockpit.tokens == 180
    visible = cockpit._usage_payload()
    assert visible["checkpoint_coverage"]["reported_invocations"] == 1
    assert visible["usage_updated_at"]
    assert visible["usage_basis"] == "recorded-turn-results-and-invocation-checkpoints"


def test_final_reconciles_progress_and_duplicate_final_changes_nothing(cockpit):
    cockpit._handle(checkpoint(), cockpit.proc)
    finish(cockpit, result())
    assert (cockpit.tokens, cockpit.turns, cockpit.spend, cockpit.secs) == (180, 1, 0.25, 2)
    turns = [event for event in cockpit.events if event["t"] == "turn_end"]
    assert turns[-1]["tokens"] == 180  # Entire invocation, not its final 60-token delta.
    assert turns[-1]["cost_usd"] == 0.25
    before = copy.deepcopy(cockpit._usage_payload())
    finish(cockpit, result())
    assert cockpit._usage_payload() == before
    assert len([event for event in cockpit.events if event["t"] == "turn_end"]) == len(turns)


def test_late_progress_after_final_cannot_increase_tokens(cockpit):
    cockpit._record_usage_result(result())
    assert cockpit._record_usage_checkpoint(checkpoint(1000, 500, 100)) is False
    assert cockpit.tokens == 180


def test_each_invocation_has_its_own_counter_origin(cockpit):
    cockpit._record_usage_result(result())
    cockpit._record_usage_checkpoint(checkpoint(10, 2, 1, invocation_id=SECOND_INVOCATION))
    assert cockpit.tokens == 192
    cockpit._record_usage_result(result(15, 3, 2, usage_invocation_id=SECOND_INVOCATION, total_cost_usd=None))
    assert cockpit.tokens == 198
    assert cockpit.turns == 2
    assert cockpit.unpriced_turns == 1
    assert cockpit._usage_payload()["spend"] is None
    assert cockpit._usage_payload()["reported_spend"] == 0.25


@pytest.mark.parametrize("extra", [{"session_id": FOREIGN_SESSION}, {"session_id": "not-a-uuid"}, {"invocation_id": "not-a-uuid"}])
def test_foreign_or_invalid_checkpoint_cannot_charge_project(cockpit, extra):
    assert cockpit._record_usage_checkpoint(checkpoint(**extra)) is False
    assert cockpit.tokens == 0
    assert cockpit._usage_payload()["checkpoint_coverage"]["tracked_invocations"] == 0


@pytest.mark.parametrize("extra", [{"session_id": FOREIGN_SESSION}, {"session_id": "not-a-uuid"}, {"usage_invocation_id": "not-a-uuid"}])
def test_foreign_or_invalid_final_refuses_credit_but_completes_owned_turn(cockpit, extra):
    cockpit.busy = True
    finish(cockpit, result(is_error=True, subtype="error_during_execution", errors=["Owned process stopped before initialization."], **extra))
    assert cockpit.tokens == cockpit.turns == cockpit.spend == 0
    assert cockpit.busy is False
    turns = [event for event in cockpit.events if event["t"] == "turn_end"]
    assert len(turns) == 1
    assert turns[0]["tokens"] is None
    assert turns[0]["cost_usd"] is None
    assert cockpit._usage_payload()["usage_attribution_error"] == "usage-session-unmatched"
    assert cockpit._usage_payload()["token_status"] == "unavailable"


def test_missing_usage_is_unavailable_not_a_reported_zero(cockpit):
    cockpit._record_usage_checkpoint(checkpoint(usage=None, token_status="unavailable"))
    visible = cockpit._usage_payload()
    assert visible["tokens"] == 0
    assert visible["token_status"] == "unavailable"
    assert visible["checkpoint_coverage"]["reported_invocations"] == 0
    assert visible["unpriced_inflight"] == 1
    assert visible["spend"] is None


def test_valid_reported_zero_is_distinguishable_from_missing_usage(cockpit):
    cockpit._record_usage_checkpoint(checkpoint(0, 0, 0))
    visible = cockpit._usage_payload()
    assert visible["tokens"] == 0
    assert visible["token_status"] == "partial"  # The invocation is unfinished.
    assert visible["checkpoint_coverage"]["reported_invocations"] == 1


def test_decrease_preserves_credit_and_stays_partial(cockpit):
    cockpit._record_usage_checkpoint(checkpoint())
    cockpit._record_usage_checkpoint(checkpoint(10, 2, 1))
    assert cockpit.tokens == 120
    assert cockpit._usage_payload()["token_status"] == "partial"
    cockpit._record_usage_checkpoint(checkpoint(1000, 200, 100))
    assert cockpit.tokens == 120
    assert cockpit._usage_payload()["token_status"] == "partial"


def test_capture_error_preserves_partial_credit_and_valid_final_can_complete_it(cockpit):
    cockpit._record_usage_checkpoint(checkpoint())
    cockpit._record_usage_checkpoint(checkpoint(usage=None, token_status="unavailable"))
    assert cockpit.tokens == 120
    assert cockpit._usage_payload()["token_status"] == "partial"
    cockpit._record_usage_result(result())
    assert cockpit.tokens == 180
    assert cockpit._usage_payload()["token_status"] == "reported"


def test_new_unpriced_running_work_makes_previous_complete_dollars_partial(cockpit):
    cockpit._record_usage_result(result())
    assert cockpit._usage_payload()["cost_complete"] is True
    cockpit._record_usage_checkpoint(checkpoint(10, 2, 1, invocation_id=SECOND_INVOCATION))
    payload = cockpit._usage_payload()
    assert payload["cost_complete"] is False
    assert payload["completed_cost_complete"] is True
    assert payload["unpriced_turns"] == 0
    assert payload["unpriced_inflight"] == 1
    assert payload["cost_status"] == "partial"
    assert payload["reported_spend"] == 0.25
    normalized = engine_mod._usage_snapshot(payload)
    assert normalized["cost_complete"] is False
    assert normalized["unpriced_turns"] == 0
    assert normalized["checkpoint_coverage"] == payload["checkpoint_coverage"]
    assert normalized["usage_updated_at"] == payload["usage_updated_at"]


def test_checkpoint_credit_restores_and_final_replay_remains_idempotent(cockpit, monkeypatch, tmp_path):
    cockpit._record_usage_checkpoint(checkpoint())
    restored = engine_mod.Engine(str(tmp_path), fake=True)
    restored.cli = "chatgpt"
    restored.session_id = SESSION
    assert restored.tokens == 120
    restored._record_usage_checkpoint(checkpoint())
    assert restored.tokens == 120
    restored._record_usage_result(result())
    assert restored.tokens == 180
    assert restored.turns == 1
    restarted_again = engine_mod.Engine(str(tmp_path), fake=True)
    restarted_again.cli = "chatgpt"
    restarted_again.session_id = SESSION
    assert restarted_again._record_usage_result(result()) is False
    assert restarted_again.tokens == 180
    assert restarted_again.spend == 0.25
    assert restarted_again.turns == 1


def test_restart_does_not_convert_inflight_cost_to_an_unpriced_completed_turn(cockpit, tmp_path):
    cockpit._record_usage_result(result())
    cockpit._record_usage_checkpoint(checkpoint(10, 2, 1, invocation_id=SECOND_INVOCATION))
    restored = engine_mod.Engine(str(tmp_path), fake=True)
    restored.cli = "chatgpt"
    restored.session_id = SESSION
    assert restored.unpriced_turns == 0
    restored._record_usage_result(result(15, 3, 2, usage_invocation_id=SECOND_INVOCATION))
    assert restored._usage_payload()["cost_complete"] is True
    assert restored.unpriced_turns == 0
    assert restored.spend == 0.5


def test_final_credit_and_money_are_in_the_same_persisted_snapshot(cockpit, monkeypatch):
    writes = []
    real_update = engine_mod._update_state

    def record_write(key, update):
        if "usage" in update:
            writes.append(copy.deepcopy(update["usage"]))
        return real_update(key, update)

    monkeypatch.setattr(engine_mod, "_update_state", record_write)
    cockpit._record_usage_checkpoint(checkpoint())
    cockpit._record_usage_result(result())
    finals = [usage for usage in writes if usage["usage_checkpoints"][INVOCATION]["finalized"]]
    assert len(finals) == 1
    assert finals[0]["tokens"] == 180
    assert finals[0]["reported_spend"] == 0.25
    assert finals[0]["turns"] == 1


def test_legacy_additive_provider_accounting_is_preserved(cockpit):
    legacy = {"type": "result", "usage": {"input_tokens": 100, "output_tokens": 20,
              "cached_input_tokens": 60, "cache_read_input_tokens": 30, "cache_creation_input_tokens": 5},
              "total_cost_usd": 0.5, "duration_ms": 1000}
    accounting = cockpit._record_usage_result(legacy)
    assert accounting["turn_tokens"] == 155
    assert cockpit.tokens == 155
    assert cockpit.spend == 0.5
    assert cockpit.turns == 1
    assert cockpit._usage_payload()["checkpoint_coverage"]["tracked_invocations"] == 0


def test_existing_aggregate_is_preserved_without_historical_backfill(cockpit):
    cockpit.tokens = 69004247
    cockpit.turns = 35
    cockpit._restore_usage_checkpoints({"tokens": 69004247, "turns": 35})
    cockpit._record_usage_checkpoint(checkpoint())
    assert cockpit.tokens == 69004367
    assert cockpit._usage_payload()["token_status"] == "partial"
    assert cockpit._usage_payload()["checkpoint_coverage"]["tracked_invocations"] == 1


def _persistence_warnings(engine):
    return [event for event in engine.events if event.get("t") == "sys"
            and event.get("text") == "Usage totals could not be saved. The displayed counts are in memory and may be lost on restart."]


def test_failed_checkpoint_save_keeps_memory_and_warns_once_until_confirmed_save(cockpit, monkeypatch):
    real_update = engine_mod._update_state
    monkeypatch.setattr(engine_mod, "_update_state", lambda *args, **kwargs: False)
    assert cockpit._record_usage_checkpoint(checkpoint()) is False
    assert cockpit.tokens == 120
    visible = cockpit._usage_payload()
    assert visible["usage_persistence_error"] == "usage-persistence-failed"
    assert visible["token_status"] == "partial"
    assert engine_mod._usage_snapshot(visible)["usage_persistence_error"] == "usage-persistence-failed"
    assert len(_persistence_warnings(cockpit)) == 1

    assert cockpit._record_usage_checkpoint(checkpoint(150, 30, 90)) is False
    assert cockpit.tokens == 180
    assert len(_persistence_warnings(cockpit)) == 1
    monkeypatch.setattr(engine_mod, "_update_state", real_update)
    assert cockpit._record_usage_checkpoint(checkpoint(150, 30, 90)) is True
    assert cockpit.tokens == 180
    assert cockpit._usage_payload()["usage_persistence_error"] is None
    assert len(_persistence_warnings(cockpit)) == 1


def test_failed_final_persistence_can_be_retried_without_repeating_money_or_turns(cockpit, monkeypatch, tmp_path):
    cockpit._record_usage_checkpoint(checkpoint())
    real_update = engine_mod._update_state
    monkeypatch.setattr(engine_mod, "_update_state", lambda *args, **kwargs: False)
    finish(cockpit, result())
    assert (cockpit.tokens, cockpit.spend, cockpit.turns) == (180, 0.25, 1)
    assert cockpit._usage_payload()["usage_persistence_error"] == "usage-persistence-failed"
    assert len([event for event in cockpit.events if event["t"] == "turn_end"]) == 1

    # A restarted Engine sees only the last confirmed saved aggregate.
    restored_before_retry = engine_mod.Engine(str(tmp_path), fake=True)
    assert restored_before_retry.tokens == 120
    assert restored_before_retry.turns == 0
    assert restored_before_retry.spend == 0

    monkeypatch.setattr(engine_mod, "_update_state", real_update)
    finish(cockpit, result())  # Duplicate final: persistence only, no new turn.
    assert (cockpit.tokens, cockpit.spend, cockpit.turns) == (180, 0.25, 1)
    assert cockpit._usage_payload()["usage_persistence_error"] is None
    assert len([event for event in cockpit.events if event["t"] == "turn_end"]) == 1
    assert len(_persistence_warnings(cockpit)) == 1
    restored_after_retry = engine_mod.Engine(str(tmp_path), fake=True)
    assert (restored_after_retry.tokens, restored_after_retry.spend, restored_after_retry.turns) == (180, 0.25, 1)


def test_direct_duplicate_final_retries_only_failed_durability(cockpit, monkeypatch):
    real_update = engine_mod._update_state
    monkeypatch.setattr(engine_mod, "_update_state", lambda *args, **kwargs: False)
    accounting = cockpit._record_usage_result(result())
    assert accounting["usage_persisted"] is False
    monkeypatch.setattr(engine_mod, "_update_state", real_update)
    assert cockpit._record_usage_result(result()) is False
    assert (cockpit.tokens, cockpit.spend, cockpit.turns) == (180, 0.25, 1)
    assert cockpit._usage_payload()["usage_persistence_error"] is None


def test_storage_exception_is_a_visible_accounting_warning_not_a_work_failure(cockpit, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("private storage details")

    monkeypatch.setattr(engine_mod, "_update_state", unavailable)
    accounting = cockpit._record_usage_result(result())
    assert accounting["usage_persisted"] is False
    assert cockpit.tokens == 180
    assert len(_persistence_warnings(cockpit)) == 1
    assert "private storage details" not in repr(_persistence_warnings(cockpit))


def test_warning_resets_only_after_a_successful_write(cockpit, monkeypatch):
    real_update = engine_mod._update_state
    monkeypatch.setattr(engine_mod, "_update_state", lambda *args, **kwargs: False)
    cockpit._record_usage_checkpoint(checkpoint())
    monkeypatch.setattr(engine_mod, "_update_state", real_update)
    cockpit._record_usage_checkpoint(checkpoint())
    monkeypatch.setattr(engine_mod, "_update_state", lambda *args, **kwargs: False)
    cockpit._record_usage_checkpoint(checkpoint(150, 30, 90))
    assert len(_persistence_warnings(cockpit)) == 2


def test_unfinished_record_stays_partial_after_restart_without_claiming_a_running_process(cockpit, tmp_path):
    cockpit._record_usage_checkpoint(checkpoint())
    assert cockpit._usage_payload()["token_status"] == "partial"
    restored = engine_mod.Engine(str(tmp_path), fake=True)
    visible = restored._usage_payload()
    assert visible["tokens"] == 120
    assert visible["token_status"] == "partial"
    assert visible["checkpoint_coverage"]["reported_invocations"] == 1
    assert visible["checkpoint_coverage"]["finalized_invocations"] == 0
    assert visible["unpriced_inflight"] == 1  # An unfinished record, not liveness evidence.


def test_reconstructed_engine_credits_selected_resume_before_init_and_keeps_early_error(cockpit, monkeypatch, tmp_path):
    # Persist the actual selected provider/session, then reconstruct rather
    # than assigning session_id on the new Engine as earlier fixtures did.
    assert engine_mod._update_state(cockpit.skey(), {"cli": "chatgpt", "session_id": SESSION}) is True
    restored = engine_mod.Engine(str(tmp_path), fake=True)
    assert restored.session_id == SESSION
    restored.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(restored, "_status_update", lambda **kwargs: None)
    restored.busy = True
    restored._handle(checkpoint(), restored.proc)  # No init event has arrived.
    assert restored.tokens == 120
    finish(restored, result(usage=None, token_status="unavailable", total_cost_usd=None,
                           is_error=True, subtype="error_during_execution",
                           errors=["Owned process exited before its init event."]))
    assert restored.busy is False
    assert restored.tokens == 120
    assert restored.turns == 1
    assert restored.unpriced_turns == 1
    terminal = [event for event in restored.events if event["t"] == "turn_end"]
    assert len(terminal) == 1
    assert terminal[0]["cost_usd"] is None
    assert restored._usage_payload()["token_status"] == "partial"


def test_fresh_engine_refuses_foreign_usage_without_suppressing_early_terminal_error(cockpit, monkeypatch, tmp_path):
    fresh_root = tmp_path / "fresh-project"
    fresh_root.mkdir()
    fresh = engine_mod.Engine(str(fresh_root), fake=True)
    assert fresh.session_id is None
    fresh.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(fresh, "_status_update", lambda **kwargs: None)
    fresh.busy = True
    fresh._handle(checkpoint(), fresh.proc)
    assert fresh.tokens == 0
    finish(fresh, result(is_error=True, subtype="error_during_execution",
                         errors=["Fresh child stopped before its session was initialized."]))
    assert fresh.busy is False
    assert (fresh.tokens, fresh.spend, fresh.turns) == (0, 0, 0)
    terminal = [event for event in fresh.events if event["t"] == "turn_end"]
    assert len(terminal) == 1
    assert terminal[0]["tokens"] is None
    assert terminal[0]["cost_usd"] is None
    assert fresh._usage_payload()["cost_status"] == "unavailable"


def test_other_provider_saved_uuid_is_not_seeded_as_a_codex_resume(cockpit, tmp_path):
    assert engine_mod._update_state(cockpit.skey(), {"cli": "claude", "session_id": SESSION}) is True
    restored = engine_mod.Engine(str(tmp_path), fake=True)
    assert restored.session_id is None
    assert restored._record_usage_checkpoint(checkpoint()) is False
    assert restored.tokens == 0


def test_quarantined_checkpoint_blocks_replay_without_inventing_pending_cost(cockpit):
    cockpit._record_usage_result(result())
    stored = cockpit._usage_payload()
    stored["usage_checkpoints"][SECOND_INVOCATION] = {
        "session_id": SESSION, "credited_tokens": "unreadable", "counts": None,
        "token_status": "unavailable",  # Missing finalized is not active work.
    }
    cockpit._restore_usage_checkpoints(stored)
    visible = cockpit._usage_payload()
    assert visible["unpriced_inflight"] == 0
    assert visible["checkpoint_coverage"]["tracked_invocations"] == 1
    assert visible["checkpoint_coverage"]["finalized_invocations"] == 1
    assert visible["cost_complete"] is True
    assert visible["cost_status"] == "reported"
    assert visible["spend"] == 0.25
    assert visible["token_status"] == "partial"
    assert cockpit._record_usage_checkpoint(checkpoint(invocation_id=SECOND_INVOCATION)) is False
    assert cockpit.tokens == 180
    assert cockpit._usage_payload()["unpriced_inflight"] == 0

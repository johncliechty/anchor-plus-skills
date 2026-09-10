"""Behavior canaries for durable cockpit policy; no provider/process launches."""

import io
import subprocess
from types import SimpleNamespace

import pytest

import anchor_settings
import model_policy
from steward_cockpit import steward_campaign, steward_engine


POLICY = {"mode": "latest_supported", "effort": "highest_supported"}


def settings(*, default="chatgpt", coding="chatgpt", review="grok", revision=1):
    return {
        "default_cli": default, "coding_family": coding, "review_family": review,
        "model_policy": dict(POLICY), "settings_revision": revision,
    }


def selection(family, revision=1):
    return {
        "family": family, "model": f"{family}-current-discovered", "effort": "high",
        "requested_policy": dict(POLICY), "settings_revision": revision,
        "model_attested": False,
    }


@pytest.fixture
def cockpit(monkeypatch, tmp_path):
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    engine = steward_engine.Engine(str(tmp_path), fake=True)
    engine.fake = False
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    engine.cli = "chatgpt"
    engine.model_selection = selection("chatgpt")
    engine.session_id = "owned-existing-session"
    engine.queue = []
    engine.policy_override = None
    engine._last_submitted = ""
    engine._turn_had_tools = False
    current = settings()
    monkeypatch.setattr(anchor_settings, "get_launch_settings", lambda: dict(current))

    def resolve(family, config=None, **kwargs):
        config = kwargs.get("settings", config) or current
        return selection(family, config.get("settings_revision", 1))

    monkeypatch.setattr(model_policy, "resolve", resolve)

    def no_processes(*args, **kwargs):
        raise AssertionError("Policy canaries must not launch processes")

    monkeypatch.setattr(subprocess, "Popen", no_processes)
    return engine, current


@pytest.mark.parametrize("event,expected", [
    ({"is_error": True, "result": "partial answer", "error": {"code": "quota", "message": "Structured usage limit"},
      "errors": ["Secondary error"]}, "Structured usage limit"),
    ({"is_error": True, "result": "partial answer", "errors": ["Usage limit reached"]}, "Usage limit reached"),
    ({"is_error": True, "result": "Only available failure text"}, "Only available failure text"),
])
def test_structured_error_reason_has_priority_over_partial_assistant_text(event, expected):
    assert expected in steward_engine.result_error_text(event)


def test_clean_success_result_is_not_treated_as_an_error():
    assert steward_engine.result_error_text({
        "is_error": False, "subtype": "success", "result": "A successful assistant answer",
    }) == ""


def test_invalid_durable_settings_block_before_old_stdin_receives_text(cockpit, monkeypatch):
    engine, _ = cockpit
    calls = []

    def invalid_settings():
        raise anchor_settings.SettingsInvalid("Synthetic invalid primary preferences")

    monkeypatch.setattr(anchor_settings, "get_launch_settings", invalid_settings)
    monkeypatch.setattr(engine, "_rollover_locked", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert engine._send_locked("must not reach the old provider") is False
    assert engine.proc.stdin.getvalue() == ""
    assert calls == []


def test_configured_ladder_does_not_invent_an_unselected_claude_fallback(cockpit, monkeypatch):
    engine, current = cockpit
    attempted = []

    def unavailable(family, *args, **kwargs):
        attempted.append(family)
        raise model_policy.PolicyUnavailable(family, "Synthetic unavailable capability")

    monkeypatch.setattr(model_policy, "resolve", unavailable)
    with pytest.raises(RuntimeError):
        engine._select_available_policy(current, "chatgpt")
    assert attempted == ["chatgpt", "grok"]
    assert "claude" not in attempted


def test_explicitly_excluded_provider_is_not_retried(cockpit, monkeypatch):
    engine, current = cockpit
    attempted = []

    def resolved(family, *args, **kwargs):
        attempted.append(family)
        return selection(family)

    monkeypatch.setattr(model_policy, "resolve", resolved)
    engine._select_available_policy(current, "chatgpt", excluded=("chatgpt",))
    assert attempted == ["grok"]


def test_pending_family_change_rolls_over_before_writing_old_provider(cockpit, monkeypatch):
    engine, current = cockpit
    old_stdin = engine.proc.stdin
    current.update(default_cli="grok", settings_revision=2)
    captured = []

    def rollover(target, config, text):
        assert old_stdin.getvalue() == ""
        captured.append((target, dict(config), text))
        return True

    monkeypatch.setattr(engine, "_rollover_locked", rollover)
    assert engine._send_locked("Send this once to the newly selected family") is True
    assert len(captured) == 1
    assert captured[0][0] == "grok" and captured[0][1]["settings_revision"] == 2
    assert captured[0][2] == "Send this once to the newly selected family"
    assert old_stdin.getvalue() == ""


def test_pending_change_preserves_queued_messages_when_rollover_is_not_ready(cockpit, monkeypatch):
    engine, current = cockpit
    current.update(default_cli="grok", settings_revision=2)
    engine.queue = ["queued first", "queued second"]
    before = list(engine.queue)
    monkeypatch.setattr(engine, "_rollover_locked", lambda *args, **kwargs: False)
    assert engine._send_locked("current user message") is False
    assert engine.queue == before
    assert engine.proc.stdin.getvalue() == ""


def test_same_live_provider_keeps_frozen_model_selection(cockpit, monkeypatch):
    engine, current = cockpit
    engine.model_selection = {**selection("chatgpt"), "model": "earlier-discovered-session-model"}
    frozen = dict(engine.model_selection)
    current["settings_revision"] = 2

    def no_rediscovery(*args, **kwargs):
        raise AssertionError("An active same-provider turn must keep its frozen policy")

    monkeypatch.setattr(model_policy, "resolve", no_rediscovery)
    monkeypatch.setattr(engine, "_rollover_locked", no_rediscovery)
    assert engine._send_locked("same-session message") is True
    assert "same-session message" in engine.proc.stdin.getvalue()
    assert engine.model_selection == frozen


def test_ladder_preserves_configured_order_and_deduplicates(cockpit, monkeypatch):
    engine, _ = cockpit
    current = settings(default="chatgpt", coding="chatgpt", review="claude")
    attempted = []

    def resolved(family, *args, **kwargs):
        attempted.append(family)
        if family != "claude":
            raise model_policy.PolicyUnavailable(family, "Synthetic capability unavailable")
        return selection(family)

    monkeypatch.setattr(model_policy, "resolve", resolved)
    family, chosen = engine._select_available_policy(current, "grok")
    assert attempted == ["grok", "chatgpt", "claude"]
    assert family == "claude"
    assert chosen["family"] == "claude"


def test_unavailability_is_durably_journaled_before_fallback_resolution(cockpit, monkeypatch):
    engine, current = cockpit
    attempts = []

    def resolved(family, *args, **kwargs):
        attempts.append(family)
        if family == "chatgpt":
            raise model_policy.PolicyUnavailable(family, "Synthetic unavailable capability")
        entry = steward_engine._read_state_entry(engine.skey())
        assert any(event.get("action") == "unavailable" for event in entry.get("routing_events", []))
        return selection(family)

    monkeypatch.setattr(model_policy, "resolve", resolved)
    family, chosen = engine._select_available_policy(current, "chatgpt")
    assert attempts == ["chatgpt", "grok"]
    assert family == "grok"
    assert chosen["family"] == "grok"
    entry = steward_engine._read_state_entry(engine.skey())
    failover = [event for event in entry["routing_events"] if event.get("action") == "failover"][-1]
    assert failover["requested"] == "chatgpt" and failover["actual_family"] == "grok"
    assert failover["model_served"] is None and failover["cross_model"] is False
    assert engine.policy_override["family"] == "grok"


def test_failed_journal_persistence_prevents_fallback_or_launch(cockpit, monkeypatch):
    engine, current = cockpit
    attempts = []

    def unavailable(family, *args, **kwargs):
        attempts.append(family)
        raise model_policy.PolicyUnavailable(family, "Synthetic unavailable capability")

    monkeypatch.setattr(model_policy, "resolve", unavailable)
    monkeypatch.setattr(steward_engine, "_update_state", lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError):
        engine._select_available_policy(current, "chatgpt")
    assert attempts == ["chatgpt"]
    assert engine.proc.stdin.getvalue() == ""


def test_init_model_alias_does_not_attest_actual_service(cockpit):
    engine, _ = cockpit
    engine._handle({"type": "system", "subtype": "init", "session_id": "owned-existing-session",
                    "model": "configured-alias-is-not-evidence", "provider": "chatgpt"}, engine.proc)
    assert engine.model_selection.get("model_attested") is not True
    assert engine.model_selection.get("model_served") != "configured-alias-is-not-evidence"
    persisted = steward_engine._read_state_entry(engine.skey()).get("model_policy", {})
    assert persisted.get("model_attested") is not True
    assert persisted.get("model_served") != "configured-alias-is-not-evidence"


def quiet_result_side_effects(engine, monkeypatch):
    monkeypatch.setattr(engine, "_status_update", lambda *args, **kwargs: None)
    monkeypatch.setattr(steward_campaign, "write_attention", lambda *args, **kwargs: None)


def test_explicit_actual_model_receipt_updates_persisted_policy(cockpit, monkeypatch):
    engine, _ = cockpit
    quiet_result_side_effects(engine, monkeypatch)
    engine._handle({"type": "result", "subtype": "success", "is_error": False, "result": "done",
                    "session_id": engine.session_id, "model_served": "actually-served-model",
                    "model_attested": True, "usage": {"input_tokens": 1, "output_tokens": 1}}, engine.proc)
    persisted = steward_engine._read_state_entry(engine.skey()).get("model_policy", {})
    assert persisted.get("model_served") == "actually-served-model"
    assert persisted.get("model_attested") is True


def test_unattested_result_does_not_upgrade_requested_model_into_actual_evidence(cockpit, monkeypatch):
    engine, _ = cockpit
    quiet_result_side_effects(engine, monkeypatch)
    engine._handle({"type": "result", "subtype": "success", "is_error": False, "result": "done",
                    "session_id": engine.session_id, "model_served": "requested-not-confirmed",
                    "model_attested": False, "usage": {}}, engine.proc)
    persisted = steward_engine._read_state_entry(engine.skey()).get("model_policy", {})
    assert persisted.get("model_attested") is not True
    assert persisted.get("model_served") != "requested-not-confirmed"


@pytest.mark.parametrize("replay_safe,had_tools,should_replay", [
    (True, False, True), (False, False, False), (True, True, False),
])
def test_quota_boundary_preserves_queue_and_never_answer_nudges(
    cockpit, monkeypatch, replay_safe, had_tools, should_replay,
):
    engine, _ = cockpit
    quiet_result_side_effects(engine, monkeypatch)
    monkeypatch.setattr(steward_engine, "_campaign_limit", lambda text: "usage_limit")
    engine._last_submitted = "original submitted request"
    engine._turn_had_tools = had_tools
    engine.queue = ["queued user first", "queued user second"]
    engine.busy = True
    queue_before = list(engine.queue)
    handoffs, nudges = [], []

    def rollover(target, config, text):
        handoffs.append((target, text, list(engine.queue)))
        return True

    monkeypatch.setattr(engine, "_rollover_locked", rollover)
    monkeypatch.setattr(engine, "_send_locked", lambda text: nudges.append(text) or True)
    engine._handle({"type": "result", "subtype": "error_during_execution", "is_error": True,
                    "result": "partial assistant text", "error": {"code": "quota", "message": "Usage limit reached"},
                    "errors": ["Usage limit reached"], "replay_safe": replay_safe,
                    "model_attested": False, "session_id": engine.session_id, "usage": {}}, engine.proc)
    assert len(handoffs) == 1 and handoffs[0][0] == "grok"
    assert handoffs[0][2] == queue_before and engine.queue == queue_before
    assert nudges == []
    if should_replay:
        assert handoffs[0][1] == "original submitted request"
    else:
        assert "Do not run tools or repeat prior actions" in handoffs[0][1]
        assert "original submitted request" not in handoffs[0][1]
        assert "needs confirmation" in handoffs[0][1]
        events = steward_engine._read_state_entry(engine.skey()).get("routing_events", [])
        assert any(event.get("action") == "replay_blocked" for event in events)

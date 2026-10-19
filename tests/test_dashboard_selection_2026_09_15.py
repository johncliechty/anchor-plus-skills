"""codex-discipline-2026-09-15 — the dashboard selection drives every steward
(John, 2026-09-15: "switching the dashboard model should switch the control").

What stays from Wave 1.1: a transient catalog failure keeps the running
family and its last selection (journaled), discovery runs off the request
thread, and only a missing CLI or a dead login walks the family ladder.
"""
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from steward_cockpit import steward_engine as eng  # noqa: E402
import model_policy  # noqa: E402

CODEX_SELECTION = {"family": "chatgpt", "model": "gpt-6-astra", "effort": "ultra",
                   "requested_policy": dict(model_policy.DEFAULT_POLICY)}


def _settings(default="chatgpt", revision=10):
    return {"default_cli": default, "coding_family": default, "review_family": "grok",
            "settings_revision": revision, "model_policy": dict(model_policy.DEFAULT_POLICY)}


@pytest.fixture
def campaign(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="steward-dash-")
    monkeypatch.setattr(eng, "STATE_FILE", Path(tmp) / "state.json")
    return tmp


def _codex_engine(campaign, monkeypatch, default="chatgpt"):
    monkeypatch.setattr("anchor_settings.load_settings", lambda: _settings(default))
    monkeypatch.setattr("anchor_settings.get_launch_settings", lambda: _settings(default))
    eng._update_state(str(campaign), {"cli": "chatgpt", "model_policy": dict(CODEX_SELECTION),
                                      "session_id": "01a09813-6605-7e13-b5ed-701477dd3d5e"})
    return eng.Engine(campaign, fake=True)


def test_dashboard_change_becomes_the_next_target_and_a_pending_switch(campaign, monkeypatch):
    e = _codex_engine(campaign, monkeypatch, default="claude")
    assert e.cli == "chatgpt"
    _settings_, target = e._desired_policy()
    assert target == "claude"          # the new model takes over on the next message
    st = e.state()
    assert st["selected_cli"] == "claude" and st["pending_switch"] == "claude"
    assert "family_pinned" not in st


def test_same_selection_means_no_switch(campaign, monkeypatch):
    e = _codex_engine(campaign, monkeypatch, default="chatgpt")
    _settings_, target = e._desired_policy()
    assert target == "chatgpt"
    assert e.state()["pending_switch"] is None


def test_explicit_switch_override_is_honoured_for_its_revision(campaign, monkeypatch):
    e = _codex_engine(campaign, monkeypatch, default="chatgpt")
    e.policy_override = {"family": "claude", "reason": "explicit_session_choice", "revision": 10}
    assert e._desired_policy()[1] == "claude"
    e.policy_override = {"family": "claude", "reason": "explicit_session_choice", "revision": 3}
    assert e._desired_policy()[1] == "chatgpt"  # a stale override yields to the dashboard


def test_transient_catalog_failure_keeps_family_and_last_selection(campaign, monkeypatch):
    e = _codex_engine(campaign, monkeypatch)
    journaled = []
    monkeypatch.setattr(e, "_journal_routing", lambda **event: journaled.append(event))
    monkeypatch.setattr(e, "_select_available_policy",
                        lambda *a, **k: pytest.fail("ladder must not be walked on a transient failure"))
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: None)

    def timed_out(family, **_kw):
        raise model_policy.PolicyUnavailable(family, "CLI discovery TimeoutExpired")
    monkeypatch.setattr(model_policy, "resolve", timed_out)
    target, selection = e._current_selection(_settings(), "chatgpt")
    assert (target, selection["model"]) == ("chatgpt", "gpt-6-astra")
    e._catalog_refresh_thread.join(5)
    assert journaled and journaled[0]["action"] == "stale_catalog"
    assert e._unavailable_family is None


def test_missing_cli_found_off_thread_walks_the_ladder_next_send(campaign, monkeypatch):
    e = _codex_engine(campaign, monkeypatch)
    seen = {}
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: None)
    monkeypatch.setattr(e, "_journal_routing", lambda **event: None)

    def missing(family, **_kw):
        raise model_policy.PolicyUnavailable(family, "subscription CLI is not installed", code="cli_missing")
    monkeypatch.setattr(model_policy, "resolve", missing)

    def ladder(settings, target, excluded=()):
        seen["excluded"] = tuple(excluded)
        return "claude", {"family": "claude", "model": "best", "effort": "max"}
    monkeypatch.setattr(e, "_select_available_policy", ladder)
    target, _sel = e._current_selection(_settings(), "chatgpt")
    assert target == "chatgpt"  # answered now from the last selection
    e._catalog_refresh_thread.join(5)
    assert e._unavailable_family == "chatgpt"
    target, _sel = e._current_selection(_settings(), "chatgpt")
    assert target == "claude" and seen["excluded"] == ("chatgpt",)
    # after the failover the finding is spent; the new family is never walked off by it
    e.cli, e.model_selection = "claude", {"family": "claude", "model": "best", "effort": "max"}
    seen.clear()
    monkeypatch.setattr(model_policy, "cached_selection",
                        lambda family, settings=None, env=None: dict(e.model_selection, stale=False))
    assert e._current_selection(_settings("claude"), "claude")[0] == "claude" and seen == {}


def test_a_different_dashboard_family_goes_to_the_ladder_not_the_cache(campaign, monkeypatch):
    e = _codex_engine(campaign, monkeypatch, default="claude")
    seen = {}
    monkeypatch.setattr(e, "_select_available_policy",
                        lambda settings, target, excluded=(): seen.update(target=target) or ("claude", {"family": "claude", "model": "best", "effort": "max"}))
    target, _sel = e._current_selection(_settings("claude"), "claude")
    assert target == "claude" and seen == {"target": "claude"}


def test_fresh_cache_answers_without_a_probe(campaign, monkeypatch):
    e = _codex_engine(campaign, monkeypatch)
    newer = dict(CODEX_SELECTION, model="gpt-7-nova", stale=False)
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: dict(newer))
    monkeypatch.setattr(model_policy, "resolve", lambda *a, **k: pytest.fail("fresh cache needs no probe"))
    target, selection = e._current_selection(_settings(), "chatgpt")
    assert (target, selection["model"]) == ("chatgpt", "gpt-7-nova") and "stale" not in selection


def test_busy_turn_never_probes(campaign, monkeypatch):
    e = _codex_engine(campaign, monkeypatch)
    e.busy = True
    monkeypatch.setattr(model_policy, "resolve", lambda *a, **k: pytest.fail("no discovery while a turn is running"))
    assert e._current_selection(_settings(), "chatgpt") == ("chatgpt", CODEX_SELECTION)

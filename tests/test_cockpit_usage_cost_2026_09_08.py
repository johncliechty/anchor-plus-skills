"""Unknown provider charges are not free usage. No live models or service writes."""
import io
from types import SimpleNamespace

import pytest

import anchor_settings
from steward_cockpit import steward_engine as engine_mod, steward_routes


@pytest.fixture
def cockpit(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {
        "default_cli": "chatgpt", "settings_revision": 1})
    eng = engine_mod.Engine(str(tmp_path), fake=True)
    eng.cli = "chatgpt"
    eng.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(eng, "_status_update", lambda **kw: None)
    return eng


def finish(eng, **fields):
    eng.turn_text = "Completed response."
    eng._handle({"type": "result", "subtype": "success", **fields}, eng.proc)
    return [e for e in eng.events if e["t"] == "turn_end"][-1]


def test_chatgpt_tokens_without_cost_remain_unpriced(cockpit):
    ev = finish(cockpit, usage={"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 20})
    assert ev["cost_usd"] is None
    assert ev["cost_status"] == "unavailable"
    assert ev["tokens"] == 120  # cached input is not counted twice
    state = cockpit.state()
    assert state["spend_usd"] is None
    assert state["tokens"] == 120
    assert state["unpriced_turns"] == 1


def test_explicit_zero_is_reported_zero(cockpit):
    ev = finish(cockpit, total_cost_usd=0, usage={"output_tokens": 2})
    assert ev["cost_usd"] == 0
    assert ev["cost_status"] == "reported"
    assert cockpit.state()["spend_usd"] == 0


@pytest.mark.parametrize("bad", [None, True, "1.20", -1, float("nan"), float("inf")])
def test_invalid_cost_is_not_converted_to_zero(cockpit, bad):
    assert finish(cockpit, total_cost_usd=bad)["cost_usd"] is None


def test_partial_cost_and_tokens_survive_new_engine(cockpit):
    finish(cockpit, total_cost_usd=1.25, usage={"input_tokens": 10})
    finish(cockpit, usage={"input_tokens": 100, "output_tokens": 20})
    fresh = engine_mod.Engine(cockpit.dir, fake=True)
    state = fresh.state()
    assert state["spend_usd"] is None
    assert state["reported_spend_usd"] == 1.25
    assert state["cost_status"] == "partial"
    assert state["unpriced_turns"] == 1
    assert state["tokens"] == 130
    assert fresh.turns == 2


def test_legacy_zero_cost_cannot_be_certified_complete():
    u = engine_mod._usage_snapshot({"spend": 0, "tokens": 200, "turns": 3})
    assert u["spend"] is None and u["unpriced_turns"] == 3
    assert u["tokens"] == 200


def test_legacy_positive_subtotal_is_preserved_but_coverage_unknown():
    u = engine_mod._usage_snapshot({"spend": 2.75, "tokens": 200, "turns": 3})
    assert u["spend"] is None and not u["cost_complete"]
    assert u["reported_spend"] == 2.75


@pytest.mark.parametrize("usage", [
    {"secs": 20, "spend": 0},
    {"spend": 1.5},
    {"cost_complete": False, "unpriced_turns": 0, "spend": 0},
    {"cost_complete": False, "unpriced_turns": "bad", "spend": 0},
])
def test_unknown_coverage_never_becomes_zero_from_sparse_or_malformed_counts(usage):
    assert engine_mod._usage_snapshot(usage)["spend"] is None


def test_rollup_keeps_partial_cost_and_exact_project_boundary(monkeypatch, tmp_path):
    root = str(tmp_path / "project")
    entries = {
        root: {"usage": {"spend": 2.5, "cost_complete": True, "unpriced_turns": 0,
                          "tokens": 10, "turns": 1}},
        root + "||general||1": {"usage": {"spend": 0, "tokens": 100, "turns": 2}},
        root + "-different": {"usage": {"spend": 999, "tokens": 999, "turns": 1}},
    }
    monkeypatch.setattr(engine_mod, "_read_all_state", lambda: entries)
    roll = steward_routes._usage_rollup(root)
    assert roll["steward"]["spend"] == 2.5
    assert roll["terms"]["spend"] is None
    assert roll["total"]["spend"] is None
    assert roll["total"]["reported_spend"] == 2.5
    assert roll["total"]["tokens"] == 110
    assert roll["total"]["unpriced_turns"] == 2


def test_cache_read_tokens_counted_and_invalid_token_values_ignored(cockpit):
    ev = finish(cockpit, usage={"input_tokens": 5, "cache_creation_input_tokens": 7,
                               "cache_read_input_tokens": 13, "output_tokens": True})
    assert ev["tokens"] == 25

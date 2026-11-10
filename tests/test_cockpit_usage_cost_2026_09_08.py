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
    assert state["billing_mode"] == "subscription"
    assert "ChatGPT subscription" in state["cost_text"]
    assert "incomplete" not in state["cost_text"]
    assert engine_mod.fmt_usage_cost_text(
        {"reported_spend": 11.6975, "unpriced_turns": 45,
         "billing_mode": "subscription"}, cli="chatgpt") == (
        "$11.70 previously reported · ChatGPT subscription (45 turns)")


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


# ---- Wave L (John, 2026-09-25): a labeled estimate at API list price ----

def test_price_table_is_dated_sourced_and_holds_the_two_models_john_runs():
    table = engine_mod.api_list_prices()
    assert table["as_of"] == "2026-10-13" and table["source"].startswith("https://developers.openai.com/")
    assert table["usd_per_million"]["gpt-6-astra"] == {"input": 10.0, "cached_input": 1.0, "output": 50.0}
    assert table["usd_per_million"]["gpt-5.6-sol"] == {"input": 4.0, "cached_input": 0.4, "output": 20.0}
    assert "claude-opus-5-5" in table["usd_per_million"]
    assert "gemini-4-argon" in table["usd_per_million"]
    assert "grok-4.20" in table["usd_per_million"]


def test_estimate_prices_uncached_input_cached_input_and_output_separately():
    usage = {"input_tokens": 1_000_000, "cached_input_tokens": 800_000, "output_tokens": 100_000}
    assert engine_mod.estimate_list_price_usd("gpt-6-astra", usage) == 7.8      # 0.2M x $10 + 0.8M x $1 + 0.1M x $50
    assert engine_mod.estimate_list_price_usd("GPT-6-Astra", usage) == 7.8      # the name, any case
    assert engine_mod.estimate_list_price_usd("best", usage) is None           # not in the table: no guess
    assert engine_mod.estimate_list_price_usd("gpt-6-astra", {}) is None       # no token counts: no guess
    assert engine_mod.estimate_list_price_usd("gpt-6-astra", None) is None


def test_chatgpt_turn_carries_a_labeled_estimate_beside_the_unpriced_count(cockpit):
    cockpit.model_selection = {"family": "chatgpt", "model": "gpt-6-astra"}
    finish(cockpit, usage={"input_tokens": 1_000_000, "cached_input_tokens": 800_000, "output_tokens": 100_000})
    state = cockpit.state()
    assert state["unpriced_turns"] == 1                     # still no reported price
    assert state["estimated_turns"] == 1
    assert state["estimated_spend_usd"] == 7.8
    assert state["reported_spend_usd"] == 0                 # never folded into "reported"
    assert state["estimate_basis"].startswith("API list price as of 20")
    assert "ChatGPT subscription" in state["cost_text"]


def test_a_model_outside_the_table_stays_unpriced_without_an_estimate(cockpit):
    cockpit.model_selection = {"family": "chatgpt", "model": "best"}
    finish(cockpit, usage={"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 20})
    state = cockpit.state()
    assert state["unpriced_turns"] == 1 and state["estimated_turns"] == 0 and state["estimated_spend_usd"] == 0


def test_estimate_survives_a_new_engine_and_sums_in_the_rollup(cockpit, monkeypatch, tmp_path):
    cockpit.model_selection = {"family": "chatgpt", "model": "gpt-6-astra"}
    finish(cockpit, usage={"input_tokens": 1_000_000, "cached_input_tokens": 800_000, "output_tokens": 100_000})
    finish(cockpit, usage={"input_tokens": 1_000_000, "cached_input_tokens": 800_000, "output_tokens": 100_000})
    again = engine_mod.Engine(str(tmp_path), fake=True)
    assert again.estimated_turns == 2 and round(again.estimated_spend, 4) == 15.6
    total = steward_routes._usage_rollup(str(tmp_path))["total"]
    assert total["estimated_turns"] == 2 and total["estimated_spend"] == 15.6
    assert total["unpriced_turns"] == 2 and total["reported_spend"] == 0


def test_tracked_codex_turn_estimates_from_its_checkpoint_counts(cockpit):
    cockpit.model_selection = {"family": "chatgpt", "model": "gpt-5.6-sol"}
    cockpit.session_id = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
    invocation = "01a08260-068d-76a1-99f6-5a7bdf3aaab9"
    cockpit._handle({"type": "usage_checkpoint", "session_id": cockpit.session_id, "invocation_id": invocation,
                     "usage": {"input_tokens": 1_000_000, "cached_input_tokens": 500_000, "output_tokens": 100_000},
                     "token_status": "reported", "usage_source": "codex-rollout"}, cockpit.proc)
    finish(cockpit, session_id=cockpit.session_id, usage_invocation_id=invocation,
           usage={"input_tokens": 1_000_000, "cached_input_tokens": 500_000, "output_tokens": 100_000})
    state = cockpit.state()
    assert state["estimated_turns"] == 1
    assert state["estimated_spend_usd"] == 4.2                 # 0.5M x $4 + 0.5M x $0.40 + 0.1M x $20


def test_dismiss_deliverable_hides_until_file_is_modified_on_disk(tmp_path):
    from steward_cockpit import steward_campaign
    doc = tmp_path / "PLAN.md"
    doc.write_text("# Initial Plan\n", encoding="utf-8")
    items = steward_campaign.read_deliverables(str(tmp_path))["items"]
    assert any(d["path"] == "PLAN.md" for d in items)

    res = steward_campaign.dismiss_deliverable(str(tmp_path), "PLAN.md")
    assert res["ok"] and res["dismissed"]["path"] == "PLAN.md"
    after_dismiss = steward_campaign.read_deliverables(str(tmp_path))["items"]
    assert not any(d["path"] == "PLAN.md" and d.get("is_current") for d in after_dismiss)
    assert any(d["path"] == "PLAN.md" and d.get("reviewed_done") for d in after_dismiss)

    # Modifying the file on disk automatically un-dismisses it so updated deliverables reappear in For Review.
    doc.write_text("# Updated Plan v2\n", encoding="utf-8")
    after_edit = steward_campaign.read_deliverables(str(tmp_path))["items"]
    assert any(d["path"] == "PLAN.md" and not d.get("reviewed_done") for d in after_edit)


def test_global_usage_summary_decumulates_resumed_session_turns_and_prices_active_models(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    import paths
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    steward_routes._GLOBAL_USAGE_CACHE["ts"] = 0.0
    steward_routes._GLOBAL_USAGE_CACHE["data"] = None
    ledger = paths.data_dir() / ".anchor" / "usage_ledger"
    ledger.mkdir(parents=True)
    now_iso = datetime.now(timezone.utc).isoformat()
    (ledger / "proj.json").write_text(json.dumps({"entries": {
        "t1": {
            "cli": "chatgpt", "model": "gpt-6.1-sol", "session_id": "sess-1",
            "recorded_at": now_iso, "tokens": 1_100_000,
            "input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 100_000,
        },
        "t2": {
            "cli": "chatgpt", "model": "gpt-6.1-sol", "session_id": "sess-1",
            "recorded_at": now_iso, "tokens": 2_200_000,
            "input_tokens": 2_000_000, "cached_input_tokens": 0, "output_tokens": 200_000,
        },
        "t3": {
            "cli": "claude", "model": "claude-fable-5-1", "session_id": "sess-2",
            "recorded_at": now_iso, "tokens": 1_100_000,
            "input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 100_000,
            "cost_usd": 7.5,
        },
    }}), encoding="utf-8")
    summary, code = steward_routes.global_usage_summary({"refresh": ["1"]})
    assert code == 200 and summary["ok"] is True
    w7 = summary["windows"]["7d"]
    # sess-1 turn 2 was cumulative (2.0M in / 0.2M out total across t1+t2), not 3.0M!
    assert w7["by_family"]["chatgpt"]["total_tokens"] == 2_200_000
    assert w7["by_family"]["claude"]["total_tokens"] == 1_100_000
    assert w7["by_family"]["claude"]["hypothetical_usd"] == 7.5

def test_update_state_preserves_higher_persisted_usage_against_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    skey = str(tmp_path)
    engine_mod._update_state(skey, {"usage": {
        "turns": 265, "unpriced_turns": 240, "estimated_turns": 240,
        "reported_spend": 277.30, "estimated_spend": 838.60,
        "tokens": 956_583_369, "cumulative_tokens": 20_389_522_476,
        "cumulative_estimated_spend": 11241.28, "secs": 156238,
    }})
    # Simulate an Engine that booted during a transient read failure (turns=1 in memory)
    engine_mod._update_state(skey, {"usage": {
        "turns": 1, "unpriced_turns": 1, "estimated_turns": 1,
        "reported_spend": 0.0, "estimated_spend": 12.50,
        "tokens": 400_000, "cumulative_tokens": 400_000,
        "cumulative_estimated_spend": 12.50, "secs": 30,
    }})
    saved = engine_mod._read_all_state()[skey]["usage"]
    assert saved["turns"] == 265
    assert saved["reported_spend"] == 277.30
    assert saved["estimated_spend"] == 838.60
    assert saved["tokens"] == 956_583_369
    assert saved["cumulative_tokens"] == 20_389_522_476


def test_engine_decumulates_resumed_session_turns_and_tracks_cumulative_context(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    cockpit = engine_mod.Engine(str(tmp_path))
    cockpit.cli = "chatgpt"
    cockpit.session_id = "01a0c682-4864-7e11-a1f4-4148ac7b0b48"
    cockpit.model_selection = {"cli": "chatgpt", "model": "gpt-6-astra", "model_served": "gpt-6-astra"}
    # Turn 1: 1.0M input (800k cached), 100k output -> 1.1M new tokens
    cockpit._record_usage_result({
        "total_cost_usd": None, "duration_ms": 1000,
        "usage": {"input_tokens": 1_000_000, "cached_input_tokens": 800_000, "output_tokens": 100_000},
    })
    # Turn 2 (resumed same session): cumulative 2.0M input (1.6M cached), 200k output -> delta is 1.1M, cumulative is 3.3M
    cockpit._record_usage_result({
        "total_cost_usd": None, "duration_ms": 1000,
        "usage": {"input_tokens": 2_000_000, "cached_input_tokens": 1_600_000, "output_tokens": 200_000},
    })
    assert cockpit.tokens == 2_200_000
    assert cockpit.cumulative_tokens == 3_300_000
    assert round(cockpit.estimated_spend, 2) == 15.60
    assert round(cockpit.cumulative_estimated_spend, 2) == 23.40



def test_live_mid_turn_usage_checkpoint_and_claude_assistant_update_estimated_spend(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    cockpit = engine_mod.Engine(str(tmp_path))
    cockpit.cli = "gemini"
    cockpit.session_id = "96622deb-e07f-4ef3-abe2-0819b0f7efe3"
    cockpit.model_selection = {"cli": "gemini", "model": "gemini-4-argon", "model_served": "gemini-4-argon"}
    cockpit._record_usage_checkpoint({
        "type": "usage_checkpoint",
        "invocation_id": "11111111-2222-4333-8444-555555555555",
        "session_id": cockpit.session_id,
        "cli": "gemini",
        "model": "gemini-4-argon",
        "usage": {"input_tokens": 100_000, "cached_input_tokens": 50_000, "output_tokens": 10_000},
    })
    st = cockpit.state()
    assert st["tokens"] == 110_000
    assert st["estimated_spend_usd"] > 0.0
    assert st["billing_mode"] in ("subscription", "estimated")
    rollup = steward_routes._usage_rollup_fresh(str(tmp_path))
    assert rollup["total"]["tokens"] == 110_000
    assert rollup["total"]["estimated_spend"] > 0.0

    # Also test Claude mid-turn assistant event with message.usage before result arrives
    claude_dir = tmp_path / "claude_proj"
    claude_dir.mkdir()
    c_eng = engine_mod.Engine(str(claude_dir))
    c_eng.cli = "claude"
    c_eng.busy = True
    c_eng.model_selection = {"cli": "claude", "model": "claude-opus-5-5", "model_served": "claude-opus-5-5"}
    c_eng._handle({
        "type": "assistant",
        "message": {
            "id": "msg-live-1",
            "model": "claude-opus-5-5",
            "usage": {"input_tokens": 50_000, "cache_read_input_tokens": 0, "output_tokens": 5_000},
            "content": [{"type": "text", "text": "Working on it..."}],
        },
    }, c_eng.proc)
    c_st = c_eng.state()
    assert c_st["tokens"] == 55_000
    assert c_st["estimated_spend_usd"] > 0.0


def test_gemini_usage_tracker_tails_transcript_and_nightly_sync_reconciles(tmp_path, monkeypatch):
    import json
    from steward_cockpit.gemini_turn_bridge import GeminiUsageTracker
    import usage_nightly_sync as uns
    import paths

    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGY_BRAIN_DIR", str(tmp_path / "brain"))
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "steward-cockpit-state.json")

    conv_id = "96622deb-e07f-4ef3-abe2-0819b0f7efe3"
    log_dir = tmp_path / "brain" / conv_id / ".system_generated" / "logs"
    log_dir.mkdir(parents=True)
    transcript = log_dir / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"step_index": 0, "type": "USER_INPUT", "content": "Hello"}) + "\n",
        encoding="utf-8",
    )

    tracker = GeminiUsageTracker(target="gemini", thread_id=conv_id, sessions_root=tmp_path / "brain", min_poll_interval=0.0)
    # Append a PLANNER_RESPONSE step mid-turn
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "created_at": "2026-11-03T20:00:00Z",
            "input_tokens": 40_000,
            "cache_read_tokens": 10_000,
            "output_tokens": 2_000,
        }) + "\n")

    upd = tracker.poll()
    assert upd is not None
    assert upd["usage_source"] == "gemini-transcript"
    assert upd["usage"]["input_tokens"] == 50_000
    assert upd["usage"]["cached_input_tokens"] == 10_000
    assert upd["usage"]["output_tokens"] == 2_000

    # Test nightly sync reconciling a second un-ledgered turn from transcript.jsonl
    skey = str(tmp_path / "mba_proj")
    engine_mod._update_state(skey, {
        "cli": "gemini",
        "session_id": conv_id,
        "model_policy": {"cli": "gemini", "model": "gemini-4-argon", "model_served": "gemini-4-argon"},
        "usage": {"turns": 0, "unpriced_turns": 0, "tokens": 0, "estimated_spend": 0.0},
    })
    res = uns.sync_all_usage(write_snapshot=True)
    assert res["ok"] is True
    assert res["ledger_entries_added"] >= 1
    st_after = engine_mod._read_all_state()[skey]["usage"]
    assert st_after["tokens"] == 52_000
    assert st_after["estimated_spend"] > 0.0
    assert (paths.data_dir() / ".anchor" / "usage_snapshots" / "latest.json").is_file()


def test_subscription_turn_end_emits_estimated_cost_and_no_inflight_compounding(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    cockpit = engine_mod.Engine(str(tmp_path))
    cockpit.cli = "gemini"
    cockpit.session_id = "8f9d7898-c49c-4cbd-b7a0-a511bb3d2294"
    cockpit.model_selection = {"cli": "gemini", "model": "gemini-4-argon", "model_served": "gemini-4-argon-high"}

    inv_id = "f3552e75-1169-4e3c-8434-3a16b8f0f9a4"
    cockpit._record_usage_checkpoint({
        "type": "usage_checkpoint",
        "invocation_id": inv_id,
        "session_id": cockpit.session_id,
        "cli": "gemini",
        "model": "gemini-4-argon-high",
        "usage_source": "gemini-transcript",
        "usage": {"input_tokens": 828_923, "cached_input_tokens": 808_254, "output_tokens": 7_234},
    })
    # While unfinalized, self.estimated_spend is 0.0 and inflight is added only in state()
    assert cockpit.estimated_spend == 0.0
    mid_state = cockpit.state()
    assert mid_state["estimated_spend_usd"] > 0.30

    # Reloading a second Engine from persisted state must NOT bake unfinalized inflight_spend into self.estimated_spend
    reloaded = engine_mod.Engine(str(tmp_path))
    assert reloaded.estimated_spend == 0.0

    # Finalize the turn via _handle("result") and verify turn_end carries estimated_cost_usd
    cockpit.busy = True
    cockpit._handle({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "Done.",
        "session_id": cockpit.session_id,
        "usage_invocation_id": inv_id,
        "usage_source": "gemini-transcript",
        "token_status": "reported",
        "total_cost_usd": None,
        "duration_ms": 153200,
        "usage": {"input_tokens": 828_923, "cached_input_tokens": 808_254, "output_tokens": 7_234},
    }, cockpit.proc)

    turn_ends = [ev for ev in cockpit.events if ev.get("t") == "turn_end"]
    assert len(turn_ends) == 1
    assert turn_ends[0]["cost_usd"] is None
    assert turn_ends[0]["estimated_cost_usd"] is not None
    assert turn_ends[0]["estimated_cost_usd"] > 0.30
    assert round(cockpit.estimated_spend, 4) == turn_ends[0]["estimated_cost_usd"]


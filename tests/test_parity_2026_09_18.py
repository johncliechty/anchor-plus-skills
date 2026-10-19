"""codex-discipline parity wave (2026-09-18) — the last plan items, built at once.

STUB GATE. Behaviours only:

- rules on every turn: a bridge family's every native turn carries the compact
  standing rules (the full contract still opens the thread); the engine sends
  them to bridge families only.
- Codex file paths: a file_change names its paths; both engine inventories
  (files touched, the turn's output refs) and the tool line carry them.
- per-turn model badge: the served model, its source (recorded by the CLI /
  provider-confirmed) and a mismatch against the request are on the policy.
- "Current work and review" keeps everything explicitly awaiting review
  whatever the focus; a missing current_step_id falls back to the one pin.
- honest auto-commit: only the campaign's own paths; other staging preserved;
  announced only when git said so.
- journal receipts at detection and at turn end; the reader keeps a journal
  receipt recorded before a step existed or before a rollover.
- the North Star re-read is tied to the goal revision it read.
"""
import io
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(tmp_path / "sidecars"))
    (tmp_path / "sidecars").mkdir()
    import importlib
    for mod in ("paths", "journal", "usage_ledger", "usage_index", "usage_capture", "rnd_registry"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    project = tmp_path / "proj"
    effort = project / "planning" / "eff-1"
    effort.mkdir(parents=True)
    pid = rnd_registry.add_project("Parity", str(project), scaffold=False)["id"]
    return {"pid": pid, "project": str(project), "effort": str(effort), "data": data}


def _engine(env, monkeypatch, tmp_path, cli="chatgpt"):
    import anchor_settings
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": cli, "settings_revision": 1})
    engine = engine_mod.Engine(env["effort"], fake=True)
    engine.cli = cli
    engine.session_id = SESSION
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(engine, "_status_update", lambda **kwargs: None)
    emitted = []
    monkeypatch.setattr(engine, "_emit", lambda ev: emitted.append(ev))
    engine._emitted = emitted
    return engine


# ── rules on every turn ───────────────────────────────────────────────────────

def test_the_bridge_prompt_carries_the_rules_on_every_turn():
    from steward_cockpit.codex_turn_bridge import turn_prompt, user_text, BridgeError
    assert turn_prompt("SYSTEM", "RULES", "hi", fresh_thread=True) == "SYSTEM\n\nhi"
    assert turn_prompt("SYSTEM", "RULES", "hi", fresh_thread=False) == "RULES\n\nhi"
    assert turn_prompt("SYSTEM", None, "hi", fresh_thread=False) == "hi"           # the old shape, unchanged
    assert turn_prompt(None, "RULES", "hi", fresh_thread=True) == "hi"
    env = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
           "system_prompt": "S", "standing_rules": "R"}
    assert user_text(env) == ("hi", "S", "R")
    with pytest.raises(BridgeError):
        user_text(dict(env, standing_rules=7))


def test_the_engine_sends_standing_rules_to_bridge_families_only(env, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine as engine_mod
    for cli, expected in (("chatgpt", True), ("grok", True), ("claude", False)):
        engine = _engine(env, monkeypatch, tmp_path, cli=cli)
        engine.busy = False
        assert engine._send("hello there") is not False
        sent = json.loads(engine.proc.stdin.getvalue().strip().splitlines()[-1])
        assert ("standing_rules" in sent) is expected, cli
        if expected:
            assert sent["standing_rules"] == engine._contract()          # the one contract, every turn (small duty first, 2026-10-04)
            assert sent["standing_rules"].startswith(engine_mod.SMALL_DUTY) and engine_mod.CONTRACT in sent["standing_rules"]


# ── Codex file paths ──────────────────────────────────────────────────────────

def test_codex_file_change_paths_reach_both_inventories_and_the_tool_line(env, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine as engine_mod
    from steward_cockpit.codex_turn_bridge import EventNormalizer
    broker = EventNormalizer("gpt-6-astra", "high", "01a0b0c6-2222-7b50-a38b-b91aad842222")
    out = broker.accept({"type": "item.completed", "thread_id": broker.thread_id,
                         "item": {"id": "fc-1", "type": "file_change", "status": "completed",
                                  "changes": [{"path": "src/a.py", "kind": "update"}, {"path": "docs/b.md", "kind": "add"},
                                              {"path": "src/a.py", "kind": "update"}]}})
    block = out[0]["message"]["content"][0]
    assert block["name"] == "file_change" and block["input"]["paths"] == ["src/a.py", "docs/b.md"]
    # Codex starts a file_change with no changes, then completes it with them: the completed event still carries the paths
    started = broker.accept({"type": "item.started", "thread_id": broker.thread_id,
                             "item": {"id": "fc-2", "type": "file_change", "status": "in_progress"}})
    assert "paths" not in started[0]["message"]["content"][0]["input"]
    done = broker.accept({"type": "item.completed", "thread_id": broker.thread_id,
                          "item": {"id": "fc-2", "type": "file_change", "status": "completed", "changes": [{"path": "src/c.py", "kind": "add"}]}})
    assert done[0]["message"]["content"][0]["input"]["paths"] == ["src/c.py"]
    again = broker.accept({"type": "item.completed", "thread_id": broker.thread_id,
                           "item": {"id": "fc-2", "type": "file_change", "status": "completed", "changes": [{"path": "src/c.py", "kind": "add"}]}})
    assert again == []                                                        # one completed refresh, no second line
    assert block["input"]["change_count"] == 3 and "changes" not in block["input"]     # never contents
    engine = _engine(env, monkeypatch, tmp_path)
    engine._handle(out[0], engine.proc)
    assert engine.files[-2:] == ["src/a.py", "docs/b.md"] and engine._turn_output_refs == ["src/a.py", "docs/b.md"]
    assert engine._turn_wrote_files is True
    assert engine_mod._tool_detail(block) == "src/a.py, docs/b.md"
    tool_line = [e for e in engine._emitted if e.get("t") == "tool"][-1]
    assert tool_line["detail"] == "src/a.py, docs/b.md"


# ── the per-turn model badge ──────────────────────────────────────────────────

def test_the_served_model_carries_its_source_and_a_mismatch_is_said(env, monkeypatch, tmp_path):
    engine = _engine(env, monkeypatch, tmp_path)
    engine.model_selection = {"model": "gpt-6-astra", "effort": "high"}
    engine.turn_text = "Reviewed."
    engine._handle({"type": "result", "subtype": "success", "session_id": SESSION,
                    "usage": {"input_tokens": 10, "output_tokens": 2}, "total_cost_usd": None, "duration_ms": 900,
                    "model_served": "gpt-6-mini", "model_attested": True, "model_source": "cli-recorded"}, engine.proc)
    p = engine.model_selection
    assert p["model_served"] == "gpt-6-mini" and p["model_source"] == "cli-recorded"
    assert any("model served gpt-6-mini (requested gpt-6-astra)" in (e.get("text") or "") for e in engine._emitted)
    engine._emitted.clear()
    engine.turn_text = "Again."
    engine._handle({"type": "result", "subtype": "success", "session_id": SESSION,
                    "usage": {"input_tokens": 10, "output_tokens": 2}, "total_cost_usd": None, "duration_ms": 900,
                    "model_served": "gpt-6-astra", "model_attested": True, "model_source": "cli-recorded"}, engine.proc)
    assert not any("model served" in (e.get("text") or "") for e in engine._emitted)
    from steward_cockpit.codex_turn_bridge import EventNormalizer
    from steward_cockpit.grok_turn_bridge import GrokNormalizer
    grok = GrokNormalizer("grok-4.6", "high", expected_id="7c9e6679-7425-40de-944b-e07fc1f90ae7")
    grok.model_served = "grok-4.6-build"
    assert grok._receipt()["model_source"] == "provider-confirmed"
    # a dated or build id of the requested model is not a mismatch; a sibling is
    from steward_cockpit.steward_engine import _same_model
    assert _same_model("gpt-6-astra", "gpt-6-astra-2026-09-01") and _same_model("grok-4.6", "grok-4.6-build")
    assert _same_model("gpt-6-astra", "gpt-6-astra") and _same_model(None, "anything")
    assert not _same_model("gpt-6-astra", "gpt-6-astra-mini") and not _same_model("gpt-5", "gpt-5.4")
    engine._emitted.clear()
    engine.turn_text = "Once more."
    engine._handle({"type": "result", "subtype": "success", "session_id": SESSION,
                    "usage": {"input_tokens": 10, "output_tokens": 2}, "total_cost_usd": None, "duration_ms": 900,
                    "model_served": "gpt-6-astra-2026-09-01", "model_attested": True, "model_source": "cli-recorded"}, engine.proc)
    assert not any("model served" in (e.get("text") or "") for e in engine._emitted)
    codex = EventNormalizer("gpt-6-astra", "high")
    assert codex._receipt()["model_source"] is None
    codex.model_served = "gpt-6-astra"
    assert codex._receipt()["model_source"] == "cli-recorded"


# ── Current work and review ───────────────────────────────────────────────────

def test_the_review_tile_keeps_requested_reviews_whatever_the_focus():
    from steward_cockpit.steward_campaign import current_review_items
    steps = [{"id": "chapters", "name": "Chapters", "status": "active",
              "navigation": {"current": False, "role": "primary", "featured_paths": ["docs/featured.md"]}},
             {"id": "spine", "name": "Spine", "status": "active", "navigation": {"current": True, "pin": True}}]
    items = [
        {"what": "Chapter 1 v1", "path": "chapters/ch1.html", "step": "chapters", "managed": True, "phase": "awaiting_review", "date": "2026-09-15"},
        {"what": "Chapter 2 draft", "path": "chapters/ch2.html", "step": "chapters", "managed": True, "phase": "preparing", "date": "2026-09-15"},
        {"what": "Old draft", "path": "chapters/ch0.html", "step": "chapters", "managed": True, "phase": "done", "date": "2026-09-01"},
        {"what": "Notes", "path": "docs/featured.md", "step": "chapters", "managed": False, "date": "2026-09-10"},
        {"what": "Spine note", "path": "docs/spine.md", "step": "spine", "managed": True, "phase": "preparing", "date": "2026-09-14"},
        {"what": "Accepted thing", "path": "docs/ok.md", "step": "spine", "managed": True, "phase": "awaiting_review", "accepted": True, "date": "2026-09-16"},
    ]
    current = [it["path"] for it in current_review_items({"steps": steps}, items)]
    assert "chapters/ch1.html" in current                  # asked for review, focus elsewhere: stays (journal 0132)
    assert "chapters/ch2.html" not in current              # not yet asked: follows the focus
    assert "docs/featured.md" not in current               # merely featured under an out-of-focus step: follows the focus
    assert "docs/spine.md" in current                      # the focused step's own work in progress
    assert "chapters/ch0.html" not in current and "docs/ok.md" not in current


def test_a_missing_current_step_id_falls_back_to_the_one_pinned_step():
    from steward_cockpit.steward_campaign import _focused_step
    steps = [{"id": "a", "status": "active", "navigation": {"pin": True, "current": True}},
             {"id": "b", "status": "active", "navigation": {}}]
    step, warning = _focused_step({"heartbeat": {}, "steps": steps})
    assert step["id"] == "a" and warning == ""
    step, warning = _focused_step({"heartbeat": {"current_step_id": "b"}, "steps": steps})
    assert step["id"] == "b"
    step, warning = _focused_step({"heartbeat": {}, "steps": [dict(s, navigation={}) for s in steps]})
    assert step is None and "steps are active" in warning


# ── honest auto-commit ────────────────────────────────────────────────────────

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def test_the_auto_commit_touches_only_the_campaigns_paths(env, monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    campaign = repo / "campaign"
    (repo / "outside").mkdir(parents=True)
    campaign.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (campaign / "a.md").write_text("one\n", encoding="utf-8")
    (repo / "outside" / "shared.md").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    (campaign / "a.md").write_text("two\n", encoding="utf-8")                  # the campaign's own change
    (repo / "outside" / "shared.md").write_text("two\n", encoding="utf-8")     # another session's dirty file
    (repo / "outside" / "staged.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "outside/staged.md")                                     # another session's staging
    engine = _engine(env, monkeypatch, tmp_path)
    engine.dir = str(campaign)
    engine.fake = False
    engine._commit_if_dirty("steward cadence checkpoint")
    assert any("committed work-in-progress" in (e.get("text") or "") for e in engine._emitted)
    assert _git(repo, "log", "-1", "--name-only", "--format=").split() == ["campaign/a.md"]
    status = _git(repo, "status", "--porcelain")
    assert "A  outside/staged.md" in status and " M outside/shared.md" in status
    # git says no: nothing is announced as committed
    engine._emitted.clear()
    (campaign / "b.md").write_text("b\n", encoding="utf-8")
    from steward_cockpit import steward_engine as engine_mod
    real_run = engine_mod.subprocess.run

    def failing_commit(argv, **kw):
        if argv[:2] == ["git", "commit"]:
            return subprocess.CompletedProcess(argv, 128, "", "fatal: refused by hook")
        return real_run(argv, **kw)
    monkeypatch.setattr(engine_mod.subprocess, "run", failing_commit)
    engine._commit_if_dirty("steward cadence checkpoint")
    texts = [e.get("text") or "" for e in engine._emitted]
    assert any(t.startswith("commit failed: fatal: refused by hook") for t in texts)
    assert not any("committed work-in-progress" in t for t in texts)


# ── journal receipts ──────────────────────────────────────────────────────────

def test_journal_receipts_at_detection_and_at_turn_end_and_the_reader_keeps_them(env, monkeypatch, tmp_path):
    from steward_cockpit.steward_campaign import _local_status_evidence
    engine = _engine(env, monkeypatch, tmp_path)
    base = Path(env["effort"])
    engine._journal_receipt("turn_error", "no strip yet")
    assert not (base / "strip.json").exists()                                    # never minted by the engine
    (base / "strip.json").write_text(json.dumps({"schema": "strip", "current_step_id": None, "pending_request": {"purpose": "John's wait"},
                                                 "grasscatch": ["idea"], "receipts": []}), encoding="utf-8")
    engine._journal_receipt("turn_error", "rate limit: try later")
    strip = json.loads((base / "strip.json").read_text(encoding="utf-8"))
    r = strip["receipts"][-1]
    assert r["kind"] == "journal_update" and r["source"] == "engine" and r["step_id"] is None
    assert "path" not in r and r["summary"].startswith("turn_error: rate limit")     # the receipt is the record
    assert strip["pending_request"] == {"purpose": "John's wait"} and strip["grasscatch"] == ["idea"]   # the steward's fields untouched
    # the reader: a different session id and no step id still count (before a rollover / before a step existed)
    out = _local_status_evidence(str(base), {"heartbeat": strip}, {"session_id": "another-session"}, {"id": "s1"})
    assert out["journal"].startswith(r["entry_id"] + ": turn_error") and out["journal_source"]["state"] == "available"
    # at turn end: the steward's own newest journal entry becomes a receipt once
    (base / "journal").mkdir()
    (base / "journal" / "0007-what-changed.md").write_text("# 0007 — What changed\n\nBody.\n", encoding="utf-8")
    engine._journal_changed_receipt()
    engine._journal_receipt("turn_error", "an engine receipt in between")
    _engine(env, monkeypatch, tmp_path)._journal_changed_receipt()      # a fresh engine (a restart) adds nothing
    strip = json.loads((base / "strip.json").read_text(encoding="utf-8"))
    entries = [x for x in strip["receipts"] if x.get("entry_id") == "0007-what-changed"]
    assert len(entries) == 1 and entries[0]["summary"] == "0007 — What changed" and entries[0]["path"] == "journal/0007-what-changed.md"
    # an interrupt and a turn error reach the journal through the engine paths
    engine.turn_text = "x"
    engine._handle({"type": "result", "subtype": "error", "is_error": True, "session_id": SESSION,
                    "error": "boom", "result": "boom", "duration_ms": 10}, engine.proc)
    strip = json.loads((base / "strip.json").read_text(encoding="utf-8"))
    assert any(x.get("kind") == "journal_update" and x.get("summary", "").startswith("turn_error") for x in strip["receipts"][-2:])
    # an interrupt with no turn running journals nothing
    before = len(strip["receipts"])
    engine.busy = False
    engine.interrupt_turn("stopped by John")
    assert len(json.loads((base / "strip.json").read_text(encoding="utf-8"))["receipts"]) == before


# ── the North Star re-read is tied to its revision ────────────────────────────

def test_the_goal_reread_is_tied_to_the_north_star_revision(tmp_path):
    from steward_cockpit import steward_campaign as campaign
    d = tmp_path / "camp"
    d.mkdir()
    (d / "ECGBERHT.md").write_text("## North star\n\nBuild the model-space prior.\n", encoding="utf-8")

    def roadmap(flip):
        (d / "roadmap.json").write_text(json.dumps({
            "schema": "ecgberht-roadmap-v0",
            "roadmap_events": [{"kind": "status_flip", "step_id": "m1", "to": "done", "receipt": {"who": "steward", "why": "landed"}}] + ([flip] if flip else []),
            "roadmap_projection": [{"id": "m1", "name": "Audit", "status": "done", "part": "research"}],
        }), encoding="utf-8")
    roadmap(None)
    m = campaign.read_map(str(d))
    assert m["goal_reread"] is False and m["goal_revision"]
    rev = m["goal_revision"]
    roadmap({"kind": "goal_flip", "step_id": "m1", "verdict": "kept", "goal_revision": rev, "at": "2026-09-18T10:00:00Z",
             "receipt": {"who": "steward", "why": "re-read"}})
    assert campaign.read_map(str(d))["goal_reread"] is True
    (d / "ECGBERHT.md").write_text("## North star\n\nBuild the model-space prior, then ship it.\n", encoding="utf-8")
    m = campaign.read_map(str(d))
    assert m["goal_reread"] is False and any("North Star changed since its last re-read" in g for g in m["gaps"])
    roadmap({"kind": "goal_flip", "step_id": "m1", "verdict": "kept", "receipt": {"who": "steward", "why": "legacy"}})
    assert campaign.read_map(str(d))["goal_reread"] is True                    # a legacy flip is trusted on the step alone

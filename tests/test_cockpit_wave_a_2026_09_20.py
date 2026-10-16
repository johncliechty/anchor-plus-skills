"""Cockpit workflow Wave A (2026-09-20) — paint what the strip already holds.

STUB GATE for PLAN.md v3 rows A1–A3 (Skill Foundry/planning/cockpit-workflow-2026-09-19):

- A1 the lead: compose_status returns `lead_line` — ONE template over the strip's
  own next_recommended, why_next and the wait, honest when no next is stated —
  and the dashboard tile and a record written before the lead paint the same line.
- A2 the honest current item: several active steps are named, never guessed.
- A3 acts before files: the deliverables reader returns `acts` — review each
  product awaiting John, open the current step's featured files, then the
  steward's next — in that order.
"""
import json
import tempfile
from pathlib import Path

import pytest


def _campaign(tmp, *, next_text="Read Refinement 2 and say what to change", why="It gates the build path",
              wait="John: read Refinement 2", steps=None, current="s2", featured=("docs/guide.md",)):
    d = Path(tmp) / "camp"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ECGBERHT.md").write_text("## North star\n\nShip the guide.\n", encoding="utf-8")
    steps = steps or [
        {"id": "s1", "name": "Survey", "status": "done", "part": "research"},
        {"id": "s2", "name": "Guide draft", "status": "active", "part": "slice",
         "navigation": {"current": True, "pin": True, "featured_paths": list(featured)}},
        {"id": "s3", "name": "Puter trial", "status": "planned", "part": "slice"},
    ]
    (d / "roadmap.json").write_text(json.dumps({
        "schema": "ecgberht-roadmap-v0",
        "roadmap_events": [{"kind": "status_flip", "step_id": "s1", "to": "done", "receipt": {"who": "steward", "why": "landed"}},
                           {"kind": "goal_flip", "step_id": "s1", "verdict": "reaffirmed", "receipt": {"who": "steward", "why": "re-read"}}],
        "roadmap_projection": steps,
    }), encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({
        "schema": "ecgberht-strip-v0", "phase": "slice", "active_effort": "Guide",
        "current_step_id": current, "next_recommended": next_text, "why_next": why, "human_wait": wait,
        "receipts": []}), encoding="utf-8")
    return d


# ── A1 ────────────────────────────────────────────────────────────────────────

def test_the_status_leads_with_next_why_and_the_wait(tmp_path):
    from steward_cockpit import steward_campaign as sc
    d = _campaign(tmp_path)
    st = sc.compose_status(str(d), {"busy": False})
    assert st["lead_line"] == "Next: Read Refinement 2 and say what to change \u2014 It gates the build path \u00b7 waiting on you: John: read Refinement 2"
    assert st["plan"]["why"] == "It gates the build path"
    d2 = _campaign(tmp_path / "b", next_text="", why="", wait="")
    st2 = sc.compose_status(str(d2), {"busy": False})
    assert st2["lead_line"] == "Next not stated by the steward"                # never an invented step
    assert sc.lead_line({"next": "", "waiting_on_you": "John"}) == "Next not stated by the steward \u00b7 waiting on you: John"


def test_the_dashboard_tile_leads_with_the_same_line(tmp_path, monkeypatch):
    import anchor_gui
    d = _campaign(tmp_path)
    (d / ".ecgberht").mkdir()
    summary = {"at": "2026-09-20 13:05", "now": ["nothing running - waiting on you"],
               "plan": {"steps_done": 1, "steps_total": 3, "next": "Read Refinement 2", "why": "it gates the build", "waiting_on_you": "John: read it"},
               "compact": {"facts": [{"label": "Doing", "value": "Idle"}]}}
    (d / ".ecgberht" / "status-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    line = anchor_gui._steward_status_tile_line({"folder_path": str(d)})
    assert line == "⏱ 13:05 · Next: Read Refinement 2 — it gates the build · waiting on you: John: read it"
    summary["plan"] = {"steps_done": 1, "steps_total": 3}
    (d / ".ecgberht" / "status-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    assert anchor_gui._steward_status_tile_line({"folder_path": str(d)}).startswith("⏱ 13:05 · Idle")   # the old facts, honestly
    # a record the previous build wrote (no lead_line) reads with the same template
    from steward_cockpit import steward_campaign as sc
    summary["plan"] = {"steps_done": 1, "steps_total": 3, "next": "Read it", "waiting_on_you": "John"}
    (d / ".ecgberht" / "status-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    last = sc.read_last_status(str(d))
    assert last["stale"] is True and last["lead_line"] == "Next: Read it \u00b7 waiting on you: John"


# ── A2 ────────────────────────────────────────────────────────────────────────

def test_several_active_steps_are_named_never_guessed():
    from steward_cockpit.steward_campaign import _focused_step
    steps = [{"id": "a", "name": "Audit", "status": "active"}, {"id": "b", "name": "Board", "status": "active"},
             {"id": "c", "name": "Close", "status": "active"}, {"id": "d", "name": "Done", "status": "done"}]
    step, warning = _focused_step({"heartbeat": {}, "steps": steps})
    assert step is None
    assert "3 steps are active" in warning and "the steward must pin one: Audit, Board, Close" in warning
    many = [{"id": "s%d" % i, "name": "Step %d" % i, "status": "active"} for i in range(8)]
    assert "Step 5 and 2 more" in _focused_step({"heartbeat": {}, "steps": many})[1]
    step, _ = _focused_step({"heartbeat": {"current_step_id": "b"}, "steps": steps})
    assert step["id"] == "b"
    planned = [{"id": "a", "name": "Audit", "status": "done"}, {"id": "b", "name": "Board", "status": "planned"}]
    step, warning = _focused_step({"heartbeat": {}, "steps": planned})
    assert step is None and "no step is active" in warning and "pin one of the 1 open steps" in warning
    step, warning = _focused_step({"heartbeat": {}, "steps": [{"id": "a", "status": "done"}]})
    assert step is None and warning == ""                                   # a finished campaign has nothing to pin


# ── A3 ────────────────────────────────────────────────────────────────────────

def test_acts_come_in_order_review_open_next(tmp_path):
    from steward_cockpit import steward_campaign as sc
    d = _campaign(tmp_path)
    map_ = sc.read_map(str(d))
    items = [
        {"what": "decision-guide", "path": "research/guide-r2.md", "step": "s2", "managed": True, "phase": "awaiting_review", "date": "2026-09-19"},
        {"what": "draft-notes", "path": "research/notes.md", "step": "s2", "managed": True, "phase": "preparing", "date": "2026-09-18"},
        {"what": "Guide v1", "path": "docs/guide.md", "step": "s2", "managed": False, "date": "2026-09-17"},
        {"what": "Old survey", "path": "research/survey.md", "step": "s1", "managed": False, "date": "2026-09-10"},
    ]
    acts = sc.review_acts(map_, sc.current_review_items(map_, items))
    assert [(a["act"], a["label"]) for a in acts] == [
        ("Review", "decision guide"),
        ("Open", "Guide v1"),                                             # the current step's own file: one act, the register's row
        ("Next", "Read Refinement 2 and say what to change"),
    ]
    assert acts[0]["item"]["path"] == "research/guide-r2.md" and acts[1]["item"]["path"] == "docs/guide.md"
    assert "draft-notes" not in [a["label"] for a in acts]                # a product the steward is still preparing is not John's act
    empty = _campaign(tmp_path / "e", next_text="", featured=())
    assert sc.review_acts(sc.read_map(str(empty)), []) == []


def test_the_deliverables_reader_serves_the_acts(tmp_path):
    from steward_cockpit import steward_campaign as sc
    d = _campaign(tmp_path)
    (d / "DELIVERABLES.md").write_text("| What | Where | Date | Step |\n|---|---|---|---|\n| Guide v1 | `docs/guide.md` | 2026-09-19 | 2 |\n", encoding="utf-8")
    (d / "docs").mkdir()
    (d / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    view = sc.read_deliverables(str(d))
    assert [a["act"] for a in view["acts"]] == ["Open", "Next"]           # the featured file, then the steward's next
    assert view["acts"][0]["label"] == "Guide v1" and view["acts"][0]["item"]["path"] == "docs/guide.md"   # the register's own row
    assert view["acts"][1]["label"] == "Read Refinement 2 and say what to change"
    assert view["current_warning"] == ""                                  # s2 is pinned
    (d / "strip.json").write_text(json.dumps({"schema": "ecgberht-strip-v0", "phase": "slice", "active_effort": "Guide",
                                              "current_step_id": "", "next_recommended": "", "why_next": "", "human_wait": "", "receipts": []}), encoding="utf-8")
    assert "the steward must pin one" not in sc.read_deliverables(str(d))["current_warning"]   # one pin still names the item

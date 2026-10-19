"""Cockpit workflow Wave B (2026-09-20) — the Anchor side of "the steward states its next act".

STUB GATE for PLAN.md v3 rows B3 and B4 (Skill Foundry/planning/cockpit-workflow-2026-09-19):

- B3 off-path steps fold by default: the plan tree keeps the sequence open and folds done, parked and
  supporting steps; a group with several active steps and no pin says so in its title.
- B4 the goal re-read note: the engine now appends the goal_flip at close, so the reader flags a missing
  re-read only for a close older than a day.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path


def _campaign(tmp, close_at, with_flip=False):
    d = Path(tmp) / "camp"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ECGBERHT.md").write_text("## North star\n\nShip the guide.\n", encoding="utf-8")
    events = [{"kind": "status_flip", "step_id": "s1", "to": "done", "at": close_at, "receipt": {"who": "steward", "why": "landed"}}]
    if with_flip:
        events.append({"kind": "goal_flip", "step_id": "s1", "verdict": "reaffirmed", "scope": "s1", "receipt": {"who": "engine", "why": "close"}})
    (d / "roadmap.json").write_text(json.dumps({
        "schema": "ecgberht-roadmap-v0", "roadmap_events": events,
        "roadmap_projection": [{"id": "s1", "name": "Survey", "status": "done"}, {"id": "s2", "name": "Guide", "status": "active"}],
    }), encoding="utf-8")
    (d / "strip.json").write_text(json.dumps({"schema": "ecgberht-strip-v0", "phase": "slice", "active_effort": "Guide",
                                              "current_step_id": "s2", "next_recommended": "Draft the guide", "why_next": "it gates the trial",
                                              "human_wait": "", "receipts": []}), encoding="utf-8")
    return d


def test_a_close_made_today_with_no_flip_yet_is_not_a_missed_re_read(tmp_path):
    from steward_cockpit import steward_campaign as sc
    today = datetime.now().replace(hour=0, minute=5).isoformat(timespec="seconds")
    m = sc.read_map(str(_campaign(tmp_path / "fresh", today)))
    assert m["goal_reread"] is True
    st = sc.compose_status(str(tmp_path / "fresh" / "camp"), {"busy": False})
    assert "goal not re-read" not in " ".join(st["now"])
    old = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
    assert sc.read_map(str(_campaign(tmp_path / "old", old)))["goal_reread"] is False           # an older close without a flip: the note stands
    assert sc.read_map(str(_campaign(tmp_path / "flipped", old, with_flip=True)))["goal_reread"] is True
    assert sc.read_map(str(_campaign(tmp_path / "dated", (datetime.now() - timedelta(days=3)).date().isoformat())))["goal_reread"] is False
    assert sc.read_map(str(_campaign(tmp_path / "today", datetime.now().date().isoformat())))["goal_reread"] is True   # the CLI's date-only stamp
    # a flip at an older North Star revision is never excused by the date
    d = _campaign(tmp_path / "stale", datetime.now().date().isoformat(), with_flip=True)
    events = json.loads((d / "roadmap.json").read_text(encoding="utf-8"))
    events["roadmap_events"][-1]["goal_revision"] = "000000000000"
    (d / "roadmap.json").write_text(json.dumps(events), encoding="utf-8")
    assert sc.read_map(str(d))["goal_reread"] is False


def test_lint_the_plan_tree_keeps_the_sequence_open_and_folds_the_rest():
    """A source lint, not a behaviour test: the fold rule and its one title."""
    js = Path(__file__).resolve().parents[1].joinpath("steward_cockpit", "static", "shared.js").read_text(encoding="utf-8")
    body = js.split("function renderGroup(g,parent)")[1].split("if(stepRows)model.roots.forEach")[0]
    assert "s.step.navigation.role==='primary'&&!offPath(s.step)" in body              # the open sequence
    assert "s.step.navigation.role!=='primary'||offPath(s.step)" in body                # the fold
    assert "'Done, parked and supporting steps · '" in body and "pin one" not in body   # one sentence for that fact lives in Current work

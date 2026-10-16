"""The plan John sees is roadmap.json (John, 2026-09-05: "It does not look like the plan gets updated
when there are clear instructions to add elements, or if a new north star is created and plan to go
with it"). Two mechanisms: the outline is never blank while a plan document exists (derived steps),
and every human turn carries a PLAN DRIFT line to the model until the roadmap catches up.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402

PLAN = """# PLAN — Econ 588 Student Summaries (PROPOSED)

## Goal (proposal — edit freely)
Produce a study pack per week.

## Observable success
- A student can state the formulas.

## Week map (proposal)
| Wk | Topic |

## Build order
1. Week 1 pack.
"""


def _effort(tmp, plan=True, roadmap=None, roadmap_older=False):
    d = Path(tmp)
    (d / "ECGBERHT.md").write_text("# Face\n\n## North Star\nA plan.\n", encoding="utf-8")
    if roadmap is not None:
        (d / "roadmap.json").write_text(json.dumps(roadmap), encoding="utf-8")
        if roadmap_older:
            old = time.time() - 600
            os.utime(d / "roadmap.json", (old, old))
    if plan:
        (d / "PLAN.md").write_text(PLAN, encoding="utf-8")
    return str(d)


def test_no_plan_doc_no_drift():
    with tempfile.TemporaryDirectory() as tmp:
        d = _effort(tmp, plan=False, roadmap={"roadmap_projection": [{"id": "s1", "name": "x", "status": "proposed"}]})
        assert campaign.plan_drift(d) == {"drift": False, "reason": "", "docs": []}
        assert campaign.plan_drift_suffix(d) == ""


def test_plan_doc_without_roadmap_drifts_and_the_outline_derives_steps():
    with tempfile.TemporaryDirectory() as tmp:
        d = _effort(tmp, plan=True, roadmap=None)
        drift = campaign.plan_drift(d)
        assert drift["drift"] is True and "not been written" in drift["reason"]
        m = campaign.read_map(d)
        names = [s["name"] for s in m["steps"]]
        assert names == ["Week map", "Build order"], names           # Goal / Observable success skipped
        assert all(s["status"] == "proposed" and s["derived_from"] == "PLAN.md" for s in m["steps"])
        assert any("derived from PLAN.md" in g for g in m["gaps"])
        suffix = campaign.plan_drift_suffix(d)
        assert suffix.startswith("\n\n[cockpit, not John] PLAN DRIFT:") and "roadmap.json" in suffix


def test_roadmap_with_steps_newer_than_the_plan_has_no_drift():
    with tempfile.TemporaryDirectory() as tmp:
        d = _effort(tmp, plan=True, roadmap={"roadmap_projection": [{"id": "s1", "name": "Real step", "status": "active"}]})
        # roadmap written after the plan doc
        now = time.time() + 5
        os.utime(Path(d) / "roadmap.json", (now, now))
        assert campaign.plan_drift(d)["drift"] is False
        m = campaign.read_map(d)
        assert [s["name"] for s in m["steps"]] == ["Real step"]     # real steps win; nothing derived


def test_plan_doc_newer_than_the_roadmap_drifts():
    with tempfile.TemporaryDirectory() as tmp:
        d = _effort(tmp, plan=True, roadmap={"roadmap_projection": [{"id": "s1", "name": "Real step", "status": "active"}]}, roadmap_older=True)
        drift = campaign.plan_drift(d)
        assert drift["drift"] is True and "after roadmap.json" in drift["reason"]


def test_engine_appends_the_drift_line_to_a_human_turn_only():
    from steward_cockpit import steward_engine as eng
    src = Path(eng.__file__).read_text(encoding="utf-8")
    assert "(16) PLAN DRIFT" in src
    # (2026-09-07) the drift line is computed at DELIVERY, never at queue time (journal 0111)
    assert "text = text + self._plan_drift_suffix()" not in src
    assert 'self._send_locked(text + (self._plan_drift_suffix() if (human and not self.general) else ""))' in src
    assert 'suffix = "" if self.general else self._plan_drift_suffix()' in src

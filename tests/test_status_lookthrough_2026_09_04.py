"""Status window rework — John, 2026-09-04.

"I am not super impressed with the content of the status updates in the
status window. The what's next is way too long, just bullet points and much
shorter. It does not help that what is running is always the steward, I want
that more look through, if a skill is being run by steward that is interesting
and should be shown and the ETA is the length of the current slice (an estimate
of that length of time). Then the summary should be shorter and should focus on
the summary of the current slice (or slices) that are being worked on."

And: "when you have a plan for going forward (like for researchPrime) have it
both available with a clickable link in the overall work flow as well as have
a short summary presented by the steward in the dialogue (bullet point style)."
"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402
from steward_cockpit import steward_engine as engine  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "steward_cockpit" / "static"

FOREMAN_LOG = """[17:54:08] contract: 5 wave(s)
[17:54:08] [17:54] Foreman build · literature-review · t=0
---------------------------------
Effort   IMPLEMENTATION-PLAN.md (5 waves)
Doing    wave 1 · starting (iter 0)
Status   0/5 waves · elapsed 0m
Tests    last verdict -
Blocker  none
Procs    agent_calls 0 · est $0.00 (subscription equiv)
---------------------------------
ETA      estimating (no completed wave yet)
To do    waves 1..5
[18:04:08] [18:04] Foreman build · literature-review · t+10m
---------------------------------
Effort   IMPLEMENTATION-PLAN.md (5 waves)
Doing    wave 2 · gate (iter 1)
Status   1/5 waves · elapsed 10m
Tests    last verdict GO
Blocker  none
Procs    agent_calls 4 · est $0.00 (subscription equiv)
---------------------------------
ETA      ~35m to run end (pace estimate)
To do    waves 2..5
[18:04:09] waiting on agent:gate 0m
"""

NEXT_LONG = ("Run the hermetic acceptance fixture and confirm all twelve seeds are "
             "retained through rank truncation with their text_source stamps. Then "
             "wire the corpus_relevance stamp into the run record and the ledger "
             "header; verify the console prints it too. After that, re-run the full "
             "suite and commit. Finally ask John whether the floor default of 0.15 "
             "is the one he wants before the release note is written.")


def _campaign(td, active_started_min_ago=20, with_log=True, log_age_s=0):
    root = Path(td)
    (root / "ECGBERHT.md").write_text(
        "# Effort\n\n## North Star\nAn on-topic corpus by construction for the "
        "literature-review skill. Every seed in, every candidate ranked by relevance.\n",
        encoding="utf-8")
    started = (datetime.now() - timedelta(minutes=active_started_min_ago)).isoformat(
        timespec="seconds")
    roadmap = {
        "roadmap_projection": [
            {"id": "s1", "name": "Baseline read", "status": "done", "part": "research",
             "done_when": "The journal evidence is on disk."},
            {"id": "s2", "name": "Relevance term + floor", "status": "active",
             "part": "slice", "commissioned_as": "Foreman",
             "gate": "node --test test/index.mjs",
             "done_when": "Fiji, U-Net, NumPy and ResNet are excluded as off-topic on "
                          "the fixture corpus while the seeds stay in. The suite is green."},
            {"id": "s3", "name": "Corpus stamp", "status": "proposed", "part": "harden",
             "done_when": "corpus_relevance in the run record."},
        ],
        "roadmap_events": [
            {"kind": "step_status", "step_id": "s1", "status": "done",
             "at": (datetime.now() - timedelta(minutes=60)).isoformat(timespec="seconds")},
            {"kind": "step_status", "step_id": "s2", "status": "active", "at": started},
        ],
    }
    (root / "roadmap.json").write_text(json.dumps(roadmap), encoding="utf-8")
    (root / "strip.json").write_text(json.dumps({
        "phase": "build", "human_wait": "", "next_recommended": NEXT_LONG}),
        encoding="utf-8")
    if with_log:
        f = root / "planning" / "effort" / "_foreman-status.log"
        f.parent.mkdir(parents=True)
        f.write_text(FOREMAN_LOG, encoding="utf-8")
        if log_age_s:
            t = time.time() - log_age_s
            os.utime(f, (t, t))
    return root


class LookThroughTest(unittest.TestCase):
    def test_parse_status_table_reads_the_last_table(self):
        got = campaign.parse_status_table(FOREMAN_LOG)
        self.assertEqual(got["rows"]["doing"], "wave 2 · gate (iter 1)")
        self.assertEqual(got["rows"]["eta"], "~35m to run end (pace estimate)")
        self.assertEqual(got["rows"]["tests"], "last verdict GO")
        self.assertEqual(got["head"]["title"], "Foreman build · literature-review")
        self.assertEqual(got["head"]["tick"], "t+10m")
        self.assertIsNone(campaign.parse_status_table("no table here"))

    def test_the_commissioned_skill_is_what_is_running(self):
        td = tempfile.mkdtemp(prefix="stw-look-")
        _campaign(td)
        st = campaign.compose_status(td, {"busy": True, "queued": 1})
        self.assertEqual(st["running"]["kind"], "skill")
        self.assertTrue(st["running"]["label"].startswith("Foreman build"))
        self.assertIn("wave 2 · gate (iter 1)", st["running"]["label"])
        # the skill leads the NOW lines; the steward's own turn follows, never leads
        self.assertEqual(st["now"][0], st["running"]["label"])
        self.assertIn("steward working · 1 queued", st["now"])
        self.assertEqual(st["tests"], "last verdict GO")
        self.assertTrue(st["eta"].startswith("~35m to run end"))
        self.assertIn("Foreman build", st["eta"])
        self.assertEqual(st["lookthrough"]["source"], "planning/effort/_foreman-status.log")

    def test_summary_is_the_current_slice_and_next_is_three_short_bullets(self):
        td = tempfile.mkdtemp(prefix="stw-slice-")
        _campaign(td)
        st = campaign.compose_status(td, {"busy": False})
        sl = st["slice"]
        self.assertEqual((sl["n"], sl["total"]), (2, 3))
        self.assertEqual(sl["name"], "Relevance term + floor")
        self.assertEqual(sl["part"], "slice")
        self.assertTrue(sl["summary"].startswith("Fiji, U-Net, NumPy and ResNet"))
        self.assertLessEqual(len(sl["summary"]), 140)
        nb = st["next_bullets"]
        self.assertEqual(len(nb), 3)
        for b in nb:
            self.assertLessEqual(len(b), 90, b)
        self.assertTrue(nb[0].startswith("Run the hermetic acceptance fixture"))
        # the whole text is still on record for the map — the pane just does not read it
        self.assertEqual(st["plan"]["next"], NEXT_LONG)
        self.assertIn("research ✓", st["project"]["parts"])
        self.assertIn("slice ▶", st["project"]["parts"])
        self.assertTrue(st["project"]["brief"].startswith("An on-topic corpus"))

    def test_eta_is_the_length_of_the_current_slice_when_no_run_carries_one(self):
        td = tempfile.mkdtemp(prefix="stw-eta-")
        _campaign(td, active_started_min_ago=20, with_log=False)
        st = campaign.compose_status(td, {"busy": True})
        self.assertEqual(st["running"]["kind"], "steward")
        self.assertEqual(st["now"][0], "steward working")
        self.assertEqual(st["tests"], "")
        self.assertIn("min left of a ~45 min slice", st["eta"])
        self.assertIn("estimate", st["eta"])
        # past the typical length the ETA says so instead of "0 min left"
        td3 = tempfile.mkdtemp(prefix="stw-over-")
        _campaign(td3, active_started_min_ago=70, with_log=False)
        st3 = campaign.compose_status(td3, {"busy": True})
        self.assertTrue(st3["eta"].startswith("over the ~45 min typical for a slice"), st3["eta"])
        # a stale log is not a running skill
        td2 = tempfile.mkdtemp(prefix="stw-stale-")
        _campaign(td2, with_log=True, log_age_s=2000)
        st2 = campaign.compose_status(td2, {"busy": False})
        self.assertNotEqual(st2["running"]["kind"], "skill")
        self.assertIsNone(st2["lookthrough"])

    def test_a_finished_run_is_said_as_finished_not_running(self):
        td = tempfile.mkdtemp(prefix="stw-final-")
        root = _campaign(td, with_log=False)
        f = root / "_foreman-status.log"
        f.write_text(FOREMAN_LOG.replace("· t+10m", "· final"), encoding="utf-8")
        st = campaign.compose_status(td, {"busy": False})
        self.assertEqual(st["running"]["kind"], "finished")
        self.assertEqual(campaign._real_wait("none"), "")
        self.assertEqual(campaign._real_wait("None."), "")
        self.assertEqual(campaign._real_wait("your look at the draft"), "your look at the draft")
        self.assertIn("Foreman build finished", st["now"][0])
        self.assertEqual(st["tests"], "")
        self.assertIn("~45 min slice", st["eta"])    # the slice estimate, not the run's

    def test_the_pane_and_the_top_bar_read_the_new_shape(self):
        js = (STATIC / "shared.js").read_text(encoding="utf-8")
        body = js.split("function renderStatus(stat)")[1].split("function stepDeliverables")[0]
        self.assertIn("const sl = stat.slice || null;", body)
        self.assertIn("const run = stat.running || null;", body)
        self.assertIn('["Summary", sliceLine || goal ||', body)
        self.assertIn('["Doing", doingLine ||', body)
        self.assertIn("bullets.slice(0, 3)", body)
        self.assertIn('["To do", todo ||', body)
        self.assertNotIn('"map: "', body)          # the map is not the to-do list
        self.assertIn('line += " · ETA " + stat.eta', body)
        self.assertIn('line += " · slice " + sl.n', body)
        css = (STATIC / "shared.css").read_text(encoding="utf-8")
        self.assertIn(".stab .stodo", css)

    def test_the_dashboard_row_says_running_slice_and_eta(self):
        src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        blk = src.split("def _steward_status_tile_line(entry: dict) -> str:")[1] \
                 .split("def render_project_tile_html")[0]
        self.assertIn('run = data.get("running") or {}', blk)
        self.assertIn('sl = data.get("slice") or {}', blk)
        self.assertIn('bits.append("ETA " + eta)', blk)


class PlansForwardTest(unittest.TestCase):
    def test_plan_documents_are_clickable_rows_without_registration(self):
        td = tempfile.mkdtemp(prefix="stw-plan-")
        root = Path(td)
        (root / "planning" / "rp").mkdir(parents=True)
        (root / "planning" / "rp" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        (root / "MASTER-PLAN.md").write_text("# mp\n", encoding="utf-8")
        (root / "notes.md").write_text("not a plan\n", encoding="utf-8")
        got = campaign.read_deliverables(td)
        self.assertFalse(got["exists"])
        paths = sorted(it["path"] for it in got["items"])
        self.assertEqual(paths, ["MASTER-PLAN.md", "planning/rp/PLAN.md"])
        self.assertTrue(all(it["openable"] and it["auto"] for it in got["items"]))
        # a plan the register already lists is not doubled
        (root / "DELIVERABLES.md").write_text(
            "| What | Where | Date |\n|---|---|---|\n"
            "| the plan | `MASTER-PLAN.md` | 2026-09-04 |\n", encoding="utf-8")
        got = campaign.read_deliverables(td)
        self.assertTrue(got["exists"])
        self.assertEqual([it["path"] for it in got["items"]],
                         ["MASTER-PLAN.md", "planning/rp/PLAN.md"])
        self.assertNotIn("auto", got["items"][0])

    def test_the_law_asks_for_the_link_and_the_bullet_summary(self):
        law = engine.LAWS if hasattr(engine, "LAWS") else ""
        src = (REPO / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
        self.assertIn("(14) PLANS FORWARD", src)
        self.assertIn("row in DELIVERABLES.md", src)
        self.assertIn("short bullet summary said by ", src)


class EnterSendsTest(unittest.TestCase):
    """(John, 2026-09-04) in the project steward's box, Enter is the Send button;
    Shift+Enter is a newline; dictated text is still sent with the button."""

    def test_enter_sends_and_shift_enter_stays_a_newline(self):
        js = (STATIC / "shared.js").read_text(encoding="utf-8")
        blk = js.split("function wireComposer()")[1].split("function wireChrome()")[0]
        self.assertIn('if (e.key !== "Enter" || e.isComposing) return;', blk)
        self.assertIn("if (e.shiftKey) return;", blk)
        self.assertIn("e.preventDefault(); submit();", blk)
        self.assertNotIn("(e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); }", blk)
        self.assertIn('if (send) send.onclick = submit;', blk)   # the button stays


if __name__ == "__main__":
    unittest.main()

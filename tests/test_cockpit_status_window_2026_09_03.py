"""Cockpit effort view — John's 2026-09-03 revisions.

1. Deliverables in the status tab are ONE line each; click → the long
   description; click its link → the deliverable opens in a new window (the
   same two-stage line the plan's steps already used).
2. The status is its OWN window (bordered box between the deliverables tile
   and the files tile) that shrinks when the tile opens; nothing slides under.
3. The 10-minute update renders in John's locked table format (Summary ·
   Effort · Doing · Status · Tests · Blocker · Procs · Journal · ETA · To do)
   — every row present, honest dashes for facts the engine does not have —
   and an idle effort shows its LAST recorded update, stamped.
4. The Goal bar's line is the one-line status of record for this steward run;
   the goal itself is one click away inside the bar.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402
from steward_cockpit import steward_routes as routes  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "steward_cockpit" / "static"


class StatusWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (STATIC / "shared.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "shared.css").read_text(encoding="utf-8")
        cls.v1 = (STATIC / "v1.html").read_text(encoding="utf-8")

    def test_deliverables_are_one_line_then_two_stage_in_tile_and_goal(self):
        self.assertIn("items.forEach((it) => body.appendChild(stepDelivLine(it)))", self.js)
        self.assertIn("items.forEach((it) => slot.appendChild(stepDelivLine(it)))", self.js)
        self.assertNotIn("items.forEach((it) => body.appendChild(delivRow(it)))", self.js)
        # the line stays one line; the detail carries the open link
        self.assertIn(".sdrow .sdone { color: var(--steward); cursor: pointer;", self.css)
        self.assertIn("white-space: nowrap;", self.css.split(".sdrow .sdone {")[1].split("}")[0])
        self.assertIn(".sdrow.open .sddetail { display: block; }", self.css)
        self.assertIn("detail.appendChild(delivRow(it))", self.js)   # click 2 → opens

    def test_status_is_its_own_window_below_the_deliverables_tile(self):
        v1 = self.v1
        i_deliv, i_stat, i_files = (v1.index("data-delivmount"), v1.index("data-pstatus"),
                                    v1.index("data-filesect"))
        self.assertLess(i_deliv, i_stat)
        self.assertLess(i_stat, i_files)
        # the scrollport, latest and held messages live INSIDE the window
        block = v1[i_stat: i_files]
        for slot in ('class="pscroll"', "data-latest", "data-msgs", "data-statusstamp"):
            self.assertIn(slot, block, slot)
        self.assertIn(".pstatus { flex: 1 1 auto; min-height: 0;", self.css)
        self.assertIn("overflow: hidden;", self.css.split(".pstatus {")[1].split("}")[0])
        # the pinned dominance rule still holds
        self.assertIn(".rightcol .pscroll { flex: 1 1 auto; min-height: 0;", self.css)
        self.assertIn(".pdeliv { flex: none;", self.css)

    def test_status_block_is_johns_locked_table(self):
        js = self.js
        body = js.split("function renderStatus(stat)")[1].split("function stepDeliverables")[0]
        for row in ('["Summary"', '["Effort"', '["Doing"', '["Status"', '["Tests"',
                    '["Blocker"', '["Procs"', '["Journal"', '["ETA"', '["To do"'):
            self.assertIn(row, body, row)
        self.assertIn('el("table", "stab")', body)
        self.assertIn('compact.appendChild(tab)', body)  # categories stay visible
        self.assertIn('stat.tests || "—"', body)     # honest dash, never a guess
        self.assertIn('stat.journal || "—"', body)
        self.assertIn('stat.eta || "—"', body)
        self.assertIn('glyph: "⚑"', self.js)     # two marks: done, waiting on you (John, 2026-09-21); no arrow
        self.assertNotIn('▷', self.js)
        self.assertIn('Action needed', self.js)
        self.assertIn('"last update " + hhmm', body)
        self.assertIn("last update on record", body)  # the stale marker
        # the replay guard is untouched
        self.assertIn("statusId <= latestStatusId", body)

    def test_top_line_is_the_run_status_and_the_goal_line_keeps_the_goal(self):
        js = self.js
        self.assertIn('data-goallabel', self.v1)
        self.assertIn('data-barlead', self.v1)
        self.assertIn("barlead.textContent = line", js)                # the status sits on the top line (John, 2026-09-25)
        self.assertNotIn("_statusLine", js)                             # and nowhere else: no shared variable
        self.assertNotIn('lab.textContent = "Status"', js)
        self.assertIn('gb.textContent = map.goal_brief || ""', js)      # the goal line keeps the goal, blank when none
        self.assertIn("line.length > 120", js)                          # short, per the elegance rule

    def test_a_group_row_with_a_mark_has_no_arrow(self):
        # the mark leads and the title is the toggle, as on the step rows (John, 2026-09-25: "arrows and then dots")
        self.assertIn(".navgroup>summary:has(.plan-mark){list-style:none}", self.js)
        self.assertIn(".navgroup>summary:has(.plan-mark)::-webkit-details-marker{display:none}", self.js)

    def test_idle_effort_answers_with_its_last_recorded_update(self):
        td = tempfile.mkdtemp(prefix="steward-status-")
        # no record → None
        self.assertIsNone(campaign.read_last_status(td))
        rec = {"at": "2026-09-02 17:40", "status_id": "1", "effort": "x",
               "now": ["nothing running - waiting on you"],
               "plan": {"step": "s", "steps_done": 3, "steps_total": 9,
                        "waiting_on_you": "your look", "next": "look", "attention": "needs_you"},
               "map": [], "swarm": []}
        d = Path(td, ".ecgberht"); d.mkdir()
        Path(d, "status-summary.json").write_text(json.dumps(rec), encoding="utf-8")
        got = campaign.read_last_status(td)
        self.assertTrue(got["stale"])
        self.assertEqual(got["at"], "2026-09-02 17:40")
        # a junk record is honest-None, never a crash
        Path(d, "status-summary.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(campaign.read_last_status(td))

    def test_status_verb_prefers_the_record_when_no_engine_is_live(self):
        src = (REPO / "steward_cockpit" / "steward_routes.py").read_text(encoding="utf-8")
        blk = src.split('if verb == "status":')[1].split('if verb == "grass":')[0]
        # W3c (2026-10-01, his word: the tile's Status read old): ONE rule - the record NOW with the last run's receipts and
        # stamp carried (status_for_pane); a live engine still composes fresh inside it
        self.assertIn("campaign.status_for_pane(cdir, eng.state() if eng else None, live=eng is not None)", blk)
        self.assertIn("eng = ENGINES.get(cdir)", blk)
        self.assertNotIn("read_last_status", blk)


def test_status_facts_keep_every_category_in_one_line():
    facts = campaign.status_facts(
        effort="MBA Teaching AI",
        summary="Lecture 4 is in review while Lecture 3 stays approved.",
        doing="Working on the Lecture 4 refinement and checking the visual companion.",
        status="8/12 done · needs_you",
        tests="pass",
        blocker="waiting on you: Keep the current Lecture 4 structure, or try the experimental flow?",
        procs="none",
        journal="none",
        eta="—",
        todo="Review Lecture 4 Refinement 2",
    )
    assert [row["label"] for row in facts] == [
        "Summary", "Effort", "Doing", "Status", "Tests",
        "Blocker", "Procs", "Journal", "ETA", "To do"]
    assert all(len(row["value"]) <= 110 for row in facts)
    clipped = campaign.one_line("First sentence stays. " + ("later detail " * 40), 110)
    assert clipped.startswith("First sentence stays.")
    assert len(clipped) <= 110
    assert campaign.one_line("1. Fix the chart 2. Ship the deck") == "1. Fix the chart 2. Ship the deck"
    assert "v1.2.15" in campaign.one_line("Lecture v1.2.15 shipped to review")


def test_status_table_is_visible_and_plan_uses_attention_flags():
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    css = (STATIC / "shared.css").read_text(encoding="utf-8")
    body = js.split("function renderStatus(stat)")[1].split("function stepDeliverables")[0]
    assert 'compact.appendChild(tab)' in body
    assert 'el("table", "stab")' in body
    assert 'status-details' not in body
    assert 'No extra diagnostics' not in body
    assert 'glyph: "⚑"' in js and '▷' not in js      # two marks on the plan; the Not done list carries the rest
    assert 'Action needed' in js
    assert 'Accept recommendation' in js
    assert '.action-needed.open .action-more' in css
    assert '.action-needed.open .action-close' in css
    assert 'plan-mark.todo' in css


if __name__ == "__main__":
    unittest.main()


class EffortTileGravestoneTest(unittest.TestCase):
    """(2026-09-03, John) every effort tile ends in a gravestone that retires the
    effort to the boneyard; the boneyard's way back is 'resurrect'."""

    def test_gravestone_on_every_effort_tile_and_resurrect(self):
        s = (STATIC / "cockpit.html").read_text(encoding="utf-8")
        blk = s.split("j.efforts.forEach(e => {")[1].split("r.onclick = () => openEffort(e.rel);")[0]
        self.assertIn('el("span", "ebone", "🪦")', blk)
        self.assertIn('fetch("/api/boneyard_move"', blk)
        self.assertIn("JSON.stringify({ dir: e.rel })", blk)
        self.assertIn("confirm(", blk)                      # one honest confirm, nothing deleted
        self.assertIn("if (e.rel) {", blk)                  # the project root cannot be retired
        yard = s.split("/* ---------- seal tile: effort boneyard ---------- */")[1]
        self.assertIn('el("button", "mini", "resurrect")', yard)
        self.assertIn('fetch("/api/boneyard_restore"', yard)
        self.assertIn(".efrow .ebone {", s)


class RetireInPlaceTest(unittest.TestCase):
    """(2026-09-03, John: "there was an error archiving") Windows refuses to
    rename a folder with an open file inside; the effort then retires IN PLACE
    (marker) and rests in the boneyard all the same; resurrect removes it."""

    def _project(self):
        root = tempfile.mkdtemp(prefix="steward-yard-")
        eff = Path(root, "deck effort")
        eff.mkdir()
        (eff / "ECGBERHT.md").write_text("# deck effort\n\nGoal: a deck.\n", encoding="utf-8")
        return root, eff

    def test_move_falls_back_to_the_marker_and_the_lists_agree(self):
        root, eff = self._project()
        from unittest import mock
        live_before = [e["rel"] for e in campaign.discover_efforts(root)]
        self.assertIn("deck effort", live_before)
        with mock.patch.object(Path, "rename", side_effect=OSError(5, "Access is denied")), \
             mock.patch.object(routes.time, "sleep", lambda s: None), \
             mock.patch.object(routes, "_effort_dir", lambda proot, rel: str(eff)), \
             mock.patch.object(routes, "ENGINES", {}):
            out, code = routes.api_post(root, "boneyard_move", {"dir": "deck effort"})
        self.assertEqual(code, 200, out)
        self.assertTrue(out["ok"] and out["in_place"])
        self.assertTrue(campaign.is_retired_in_place(str(eff)))
        self.assertNotIn("deck effort", [e["rel"] for e in campaign.discover_efforts(root)])
        yard = campaign.list_boneyard(root)
        self.assertEqual([(b["name"], b["in_place"]) for b in yard], [("deck effort", True)])
        # resurrect: the marker goes, the effort is live again
        out, code = routes.api_post(root, "boneyard_restore", {"name": "deck effort"})
        self.assertEqual(code, 200, out)
        self.assertTrue(out["in_place"])
        self.assertFalse(campaign.is_retired_in_place(str(eff)))
        self.assertIn("deck effort", [e["rel"] for e in campaign.discover_efforts(root)])
        self.assertEqual(campaign.list_boneyard(root), [])

    def test_a_free_folder_still_moves(self):
        root, eff = self._project()
        from unittest import mock
        with mock.patch.object(routes, "_effort_dir", lambda proot, rel: str(eff)), \
             mock.patch.object(routes, "ENGINES", {}):
            out, code = routes.api_post(root, "boneyard_move", {"dir": "deck effort"})
        self.assertEqual((code, out["ok"], out["in_place"]), (200, True, False))
        self.assertTrue(Path(root, campaign.BONEYARD_DIRNAME, "deck effort", "ECGBERHT.md").is_file())
        self.assertEqual([b["in_place"] for b in campaign.list_boneyard(root)], [False])

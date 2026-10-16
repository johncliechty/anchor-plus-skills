"""r3 home (2026-09-03) — the main dashboard follows the dashboard-v2 prototype.

Design contract: _mockups/dashboard-v2 (r3) + SCORECARD.md cuts, as read by the
2026-08-29 best-in-class addendum. Pins:
- the steward owns the rail: the move today · due today · coming up · project
  counts · workbench; the old Views / Domains / Domain-balance nav is gone
- the steward tile opens with ranked "Needs attention" rows, each naming its rule
- tiles in r3 order: Steward · Tasks · Projects · Workbench · Calendar · Email · Grass
- Calendar and Email are HOME tiles in an honest not-connected state: no sample
  data, no personal account labels, the only action says it is not yet available
- the cuts: stats row, Completed/Cancelled/Saved header buttons, "Click to expand"
- nothing is lost: Inbox, domain filters and the R&D archive stay one click away
"""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO = Path(__file__).resolve().parent.parent


def _render_home():
    prev = os.environ.get("ANCHOR_DATA_DIR")
    td = tempfile.mkdtemp(prefix="anchor-home-r3-")
    os.environ["ANCHOR_DATA_DIR"] = td
    try:
        import paths
        importlib.reload(paths)
        paths.ensure_data_dirs()
        import rnd_registry
        importlib.reload(rnd_registry)
        import effort_history
        importlib.reload(effort_history)
        import sessions
        importlib.reload(sessions)
        import anchor_gui
        importlib.reload(anchor_gui)
        return anchor_gui.generate_html(*anchor_gui.gather_all())
    finally:
        if prev is None:
            os.environ.pop("ANCHOR_DATA_DIR", None)
        else:
            os.environ["ANCHOR_DATA_DIR"] = prev


class HomeR3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _render_home()

    def test_rail_is_the_stewards(self):
        h = self.html
        self.assertIn('data-rail', h)
        for lab in ("The move today", ">Due today<", ">Coming up<", ">Projects<", ">Workbench<"):
            self.assertIn(lab, h, lab)
        self.assertIn("Calendar not connected", h)
        self.assertIn('data-needyou=', h)
        # the old nav is gone from the rail
        self.assertNotIn('<h3>Views</h3>', h)
        self.assertNotIn('<h3>Domains</h3>', h)
        self.assertNotIn('Domain Balance', h)

    def test_steward_tile_carries_ranked_attention(self):
        h = self.html
        self.assertIn('data-attention', h)
        i = h.index('id="tile-highseat"')
        self.assertLess(i, h.index('data-attention'))
        self.assertIn("need attention &middot; talk below", h) if 'class="att ' in h else \
            self.assertIn("nothing waiting &middot; talk below", h)
        if 'class="att ' in h:
            self.assertIn('data-rule="', h)
            self.assertIn("raised by: ", h)
        self.assertIn("function r3RaiseRows(", h)   # the steward's raise queue joins client-side
        self.assertIn("window.r3RaiseRows", (REPO / "static" / "high-seat.js").read_text(encoding="utf-8"))

    def test_tiles_in_r3_order_with_calendar_and_email_on_the_home(self):
        h = self.html
        order = ['id="tile-highseat"', 'id="tile-tasks"', 'id="tile-projects"',
                 'id="dashboard-workbench-details"', 'id="tile-cal"', 'id="tile-mail"', 'id="tile-grass"']
        idx = [h.index(k) for k in order]
        self.assertEqual(idx, sorted(idx), "tile order must be Steward · Tasks · Projects · Workbench · Calendar · Email · Grass")

    def test_calendar_and_email_are_honest_zero_state(self):
        h = self.html
        for tid in ('id="tile-cal"', 'id="tile-mail"'):
            seg = h[h.index(tid): h.index("</details>", h.index(tid))]
            self.assertIn("not connected", seg)
            self.assertIn("nothing here is sample data", seg)
            self.assertIn("Set up &mdash; not yet available", seg)
            self.assertIn("disabled", seg)
            for personal in ("PSU", "Axmra", "@gmail", "jcl12"):
                self.assertNotIn(personal, seg, personal)

    def test_the_cuts(self):
        h = self.html
        self.assertNotIn('class="stats-row"', h)
        self.assertNotIn('id="completedBtn"', h)
        self.assertNotIn("Click to expand", h)
        self.assertNotIn("Click to collapse", h)

    def test_chrome_per_johns_look(self):
        h = self.html
        # the Doctor chip sits with Update / Zombie Hunter / Skill Foundry
        i_upd, i_doc, i_zh = h.index("&#8635; Update"), h.index('id="doctorChip"'), h.index("Zombie Hunter")
        self.assertLess(i_upd, i_doc)
        self.assertLess(i_doc, i_zh)
        # the Steward pick rides the Terminal / Coder / Reviewer / Judge line
        prefs = h[h.index("id='modelPrefs'"): h.index("id='mpStatus'")]
        self.assertIn("id='stewardPick'", prefs)
        self.assertEqual(h.count("id='stewardPick'"), 1)
        # tiles remember being open across the reload a task action triggers
        self.assertIn("anchor_tiles_open", h)
        self.assertIn("function _wireTileMemory()", h)

    def test_gravestone_at_the_end_of_every_project_row(self):
        # (2026-09-03, John) each project row under the steward's seal ends in
        # a gravestone → the Archive view (kept); a resting row offers resurrect
        import anchor_gui
        row = anchor_gui.render_project_tile_html({"id": "p1", "name": "Alpha", "state": "active",
                                                   "folder_path": "C:/x", "group": ""})
        self.assertIn('class="rnd-mini rnd-grave"', row)
        self.assertIn("rndArchive('p1')", row)
        self.assertLess(row.index("rnd-grave"), row.index("rnd-kebab-btn"))   # at the END, before the kebab
        rest = anchor_gui.render_project_tile_html({"id": "p2", "name": "Beta", "state": "archived",
                                                    "folder_path": "C:/y", "group": ""})
        self.assertIn(">resurrect</button>", rest)
        self.assertIn("rndReactivate('p2')", rest)

    def test_nothing_is_lost(self):
        h = self.html
        self.assertIn("showView('inbox')", h)
        self.assertIn("showView('rnd-archive')", h)
        self.assertIn("showView('completed')", h)
        self.assertIn("showView('cancelled')", h)
        self.assertIn("showView('saved')", h)
        self.assertIn('data-railback', h)  # off the dashboard the rail offers the way back
        self.assertIn('id="view-inbox"', h)


if __name__ == "__main__":
    unittest.main()

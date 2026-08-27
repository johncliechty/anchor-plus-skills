"""The setup message must reach the tile John actually looks at (2026-08-27).

An adversarial review caught this: the server emitted "Setting up the
project…", a test asserted the JSON payload, and the browser dropped it on the
floor — the R&D project tile (`.rnd-row`) carries `data-project-id` but is not
`.card` and had no `.gandalf-card-status` span, and the poller both SELECTED
and GATED on `.card[data-project-id]`. The tile stayed blank, which is the
exact failure the feature exists to prevent, with a green test above it.

So these tests pin the RENDER PATH, not the payload.
"""

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import anchor_gui as g  # noqa: E402


class TileCarriesTheStatusSlotTest(unittest.TestCase):
    def setUp(self):
        self.src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")

    def test_rnd_tile_has_a_status_slot(self):
        tile = self.src[self.src.index('<div class="rnd-row" data-project-id'):]
        tile = tile[:2000]
        self.assertIn("gandalf-card-status", tile,
                      "the R&D tile must carry the badge the poll writes to")
        self.assertIn("gcs-text", tile)

    def test_poller_selects_both_tile_kinds(self):
        self.assertNotIn("querySelectorAll('.card[data-project-id]')", self.src,
                         "selecting only .card skips every R&D project tile")
        self.assertIn("querySelectorAll('[data-project-id]')", self.src)

    def test_poller_is_not_gated_on_card_only_pages(self):
        self.assertNotIn("querySelector('.card[data-project-id]')", self.src,
                         "the poll must not stop itself on an R&D-only page")

    def test_setup_message_is_not_labelled_gandalf(self):
        self.assertIn("indexOf('Setting up') === 0", self.src,
                      "a setup sentence must not be prefixed 'Gandalf:'")


class DeferredReadStillSpeaksTest(unittest.TestCase):
    """Projects 2 and 3 of a rapid triple-create have their read DEFERRED. If
    the setup message clears with nothing behind it, those tiles go blank —
    the original failure, reproduced for exactly the case that caused it."""

    def setUp(self):
        self._saved = dict(g._GANDALF_INFLIGHT)
        g._GANDALF_INFLIGHT.clear()
        self._enabled = g._PROACTIVE_SUMMARY_ENABLED
        g._PROACTIVE_SUMMARY_ENABLED = True

    def tearDown(self):
        g._GANDALF_INFLIGHT.clear()
        g._GANDALF_INFLIGHT.update(self._saved)
        g._PROACTIVE_SUMMARY_ENABLED = self._enabled
        g.set_project_setup_status("deferred-one", None)

    def test_a_deferred_read_leaves_an_honest_message(self):
        import tempfile
        g._GANDALF_INFLIGHT["busy-project"] = {"status": "running",
                                               "ts": __import__("time").time()}
        g._trigger_gandalf_first_scan(tempfile.mkdtemp(), "deferred-one")
        msg = g.project_setup_statuses().get("deferred-one", "")
        self.assertTrue(msg.startswith("Read deferred"), msg)
        self.assertIn("Gandalf button", msg,
                      "tell him how to run it himself")

    def test_setup_clear_does_not_wipe_a_deferral_notice(self):
        src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        self.assertIn('.startswith(\n                            "Setting up")',
                      src.replace("\r\n", "\n"))


class MoveGuardCoversTheReadTest(unittest.TestCase):
    def test_move_is_refused_while_a_read_walks_the_tree(self):
        """A Gandalf read is not a managed session, so has_live_sessions does
        not see it — nothing else would stop a shutil.move mid-read."""
        src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        self.assertIn("_gandalf_inflight_ids()", src)
        self.assertIn("pid in project_setup_statuses() or "
                      "pid in _gandalf_inflight_ids()", src)


class NewestIsActuallyNewestTest(unittest.TestCase):
    def test_summary_picks_by_date_not_file_order(self):
        js = (REPO / "steward_cockpit" / "static" / "shared.js").read_text(
            encoding="utf-8")
        self.assertIn("const byDate = items.slice().sort", js,
                      "'newest' must be chosen by date, not by file position")


class FilesSectionHasOneScrollerTest(unittest.TestCase):
    def test_no_nested_scrollbars(self):
        css = (REPO / "steward_cockpit" / "static" / "shared.css").read_text(
            encoding="utf-8")
        self.assertIn(".pfiles.psect { flex: none; max-height: none; "
                      "overflow: visible; }", css)


if __name__ == "__main__":
    unittest.main()

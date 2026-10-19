"""A newly created project must SAY what it is doing (John, 2026-08-27).

"If there's some big run happening when projects are being created then it
should give me some indication ... it shows up in the unfiled folder, then I
can move it to the right folder, and that's all done while things are going in
the background setting up the project."

What went wrong before: creating a project fired a whole-tree read with no
visible sign, so a blank tile sat there and he clicked Create again. The read
is back ON (it produces a real verdict) — what changed is that it announces
itself, lands in Ungrouped immediately, and can only run one at a time.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import anchor_gui as g          # noqa: E402
import rnd_registry as _rnd     # noqa: E402


class _Handler:
    def __init__(self):
        self.sent = None
        self.code = None
        self._tok = True

    def _send_json(self, obj, code=200):
        self.sent, self.code = obj, code

    def _term_token_ok(self):
        return self._tok


class SetupStatusTest(unittest.TestCase):
    def tearDown(self):
        g.set_project_setup_status("p-test", None)

    def test_set_and_clear(self):
        g.set_project_setup_status("p-test", "Setting up…")
        self.assertEqual(g.project_setup_statuses().get("p-test"), "Setting up…")
        g.set_project_setup_status("p-test", None)
        self.assertNotIn("p-test", g.project_setup_statuses())

    def test_a_stale_setup_message_expires(self):
        """A crashed setup must not pin 'setting up…' on a card forever."""
        with g._PROJECT_SETUP_GUARD:
            g._PROJECT_SETUP["p-test"] = {"status": "Setting up…", "ts": 0}
        self.assertNotIn("p-test", g.project_setup_statuses())

    def test_bulk_badge_poll_reports_setup(self):
        """It rides the SAME poll the Gandalf badge already uses, so the card
        needs no new wiring."""
        g.set_project_setup_status("p-test", "Setting up the project…")
        h = _Handler()
        g.handle_gandalf_status_all(h, "/api/rnd/gandalf_status_all", {})
        self.assertTrue(h.sent["ok"])
        self.assertEqual(h.sent["statuses"].get("p-test"),
                         "Setting up the project…")

    def test_bulk_poll_still_token_gated(self):
        h = _Handler()
        h._tok = False
        g.handle_gandalf_status_all(h, "/api/rnd/gandalf_status_all", {})
        self.assertEqual(h.code, 401)


class RegistrationAnnouncesItselfTest(unittest.TestCase):
    def setUp(self):
        self._real = g._trigger_gandalf_first_scan
        self.seen = []
        # capture the setup message as it is at read-scheduling time
        def _fake(folder, pid):
            self.seen.append(g.project_setup_statuses().get(pid))
            return True
        g._trigger_gandalf_first_scan = _fake

    def tearDown(self):
        g._trigger_gandalf_first_scan = self._real

    def test_new_project_lands_ungrouped_and_announces_setup(self):
        tmp = tempfile.mkdtemp(prefix="anchor-setup-")
        res = g.select_existing_project("Setup Announce", tmp, priority=3)
        pid = res["entry"]["id"]
        try:
            # unfiled: no group, so it sorts into Ungrouped on the dashboard
            self.assertEqual(res["entry"].get("group", ""), "")
            # the read WAS scheduled, and a setup message was live when it was
            self.assertEqual(len(self.seen), 1,
                             "registration must still schedule the read")
            self.assertTrue(self.seen[0],
                            "the card must say it is setting up while it runs")
            # ...and it is cleared once setup finishes
            self.assertNotIn(pid, g.project_setup_statuses())
        finally:
            _rnd.remove_project(pid)


class MoveIsRefusedDuringSetupTest(unittest.TestCase):
    def tearDown(self):
        g.set_project_setup_status("p-move", None)

    def test_disk_move_refused_while_setup_writes_into_the_folder(self):
        g.set_project_setup_status("p-move", "Setting up…")
        h = _Handler()
        g.handle_move_project(h, "/api/rnd/move_project",
                              {"project_id": "p-move", "group": "Research",
                               "confirm": True})
        self.assertEqual(h.code, 409)
        self.assertEqual(h.sent["reason"], "setup-in-flight")


if __name__ == "__main__":
    unittest.main()

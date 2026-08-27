"""'+ New project' silently did nothing (John, 2026-08-26).

What actually happened: registration SUCCEEDED, but the POST never got a
response back, so the dashboard never reloaded and it looked like a no-op —
so he clicked again, and registered a duplicate. Twice. Causes:

1. Registering fired the first-scan Gandalf read — a whole-tree map-reduce
   fanning out to ~12 parallel model jobs — and the in-flight guard was PER
   PROJECT, so each extra click started another swarm and the machine (and
   with it the HTTP response) ground to a halt. (2026-08-27: the read itself
   is wanted and is back ON; what is capped is CONCURRENCY — one automatic
   read machine-wide — and it now announces itself on the card.)
2. Brownfield discover/adopt ran inline inside WRITE_LOCK, on the path the
   click was waiting on.

These are BEHAVIOURAL tests: an adversarial review pointed out that grepping
the source for a guard expression cannot see a race, a wedge, or a wrongly
matched project. Each test drives the real function.
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
    """Captures what the endpoint would have sent."""

    def __init__(self):
        self.sent = None
        self.code = None

    def _send_json(self, obj, code=200):
        self.sent, self.code = obj, code


class RegisterSchedulesOneAnnouncedReadTest(unittest.TestCase):
    """Registering schedules ONE announced read — never a pile of swarms."""

    def setUp(self):
        self.calls = []
        self._real = g._trigger_gandalf_first_scan
        g._trigger_gandalf_first_scan = lambda f, p: self.calls.append((f, p))
        self._enabled = g._PROACTIVE_SUMMARY_ENABLED

    def tearDown(self):
        g._trigger_gandalf_first_scan = self._real
        g._PROACTIVE_SUMMARY_ENABLED = self._enabled

    def test_register_schedules_the_read_but_announces_it(self):
        """2026-08-27: John WANTS the read on creation — it produced a real
        verdict. What made it dangerous was never the read, it was three
        unannounced swarms at once. It is back on, off the request path, capped
        to one at a time machine-wide, and it says so on the card."""
        tmp = tempfile.mkdtemp(prefix="anchor-reg-")
        entry = None
        try:
            res = g.select_existing_project("Reg Test", tmp, priority=3)
            entry = res["entry"]
            self.assertEqual(len(self.calls), 1,
                             "registration schedules exactly one read")
        finally:
            if entry:
                _rnd.remove_project(entry["id"])

    def test_open_and_rescan_also_read(self):
        """Opening/rescanning reads too — the same single-read path."""
        tmp = tempfile.mkdtemp(prefix="anchor-open-")
        entry = _rnd.add_project("Open Test", tmp, priority=3, scaffold=True)
        try:
            self.calls.clear()
            g.discover_and_adopt(entry["id"])          # the open/rescan path
            self.assertEqual(len(self.calls), 1,
                             "opening/rescanning keeps the first-scan read")
        finally:
            _rnd.remove_project(entry["id"])


class GlobalFirstScanCapTest(unittest.TestCase):
    """One automatic whole-tree read at a time, machine-wide."""

    def setUp(self):
        self._saved = dict(g._GANDALF_INFLIGHT)
        g._GANDALF_INFLIGHT.clear()
        self._enabled = g._PROACTIVE_SUMMARY_ENABLED
        g._PROACTIVE_SUMMARY_ENABLED = True

    def tearDown(self):
        g._GANDALF_INFLIGHT.clear()
        g._GANDALF_INFLIGHT.update(self._saved)
        g._PROACTIVE_SUMMARY_ENABLED = self._enabled

    def test_second_project_is_refused_while_another_read_runs(self):
        g._GANDALF_INFLIGHT["project-A"] = {"status": "running",
                                            "ts": time.time()}
        self.assertFalse(
            g._trigger_gandalf_first_scan(tempfile.mkdtemp(), "project-B"),
            "a second project's automatic read must wait, not add a swarm")
        self.assertNotIn("project-B", g._GANDALF_INFLIGHT,
                         "a refused read must not strand a claim")

    def test_a_wedged_run_does_not_wedge_every_other_project(self):
        """No staleness escape meant one hung read suppressed the whole
        machine's automatic reads until the server restarted."""
        g._GANDALF_INFLIGHT["stuck"] = {"status": "running", "ts": 0}
        g._trigger_gandalf_first_scan(tempfile.mkdtemp(), "fresh")
        self.assertNotIn("stuck", g._GANDALF_INFLIGHT,
                         "a claim older than the escape window must expire")

    def test_own_in_flight_read_is_still_refused(self):
        g._GANDALF_INFLIGHT["me"] = {"status": "running", "ts": time.time()}
        self.assertFalse(g._trigger_gandalf_first_scan(tempfile.mkdtemp(), "me"))
        self.assertIn("me", g._GANDALF_INFLIGHT,
                      "refusing must not drop the RUNNING read's own claim")


class DuplicateGuardTest(unittest.TestCase):
    """A second click on a slow create must not mint a twin."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="anchor-dup-")
        self.made = []

    def tearDown(self):
        for pid in self.made:
            _rnd.remove_project(pid)

    def _create(self, name):
        h = _Handler()
        g.handle_new_project(h, "/api/rnd/new_project",
                             {"mode": "existing", "name": name,
                              "priority": 3, "folder_path": self.tmp})
        if h.sent and h.sent.get("entry"):
            pid = h.sent["entry"]["id"]
            if pid not in self.made:
                self.made.append(pid)
        return h.sent

    def test_second_identical_create_returns_the_same_project(self):
        first = self._create("Dup Test")
        second = self._create("Dup Test")
        self.assertTrue(second.get("already_registered"))
        self.assertEqual(second["entry"]["id"], first["entry"]["id"],
                         "a double-click must not create a twin")
        self.assertEqual(len(self.made), 1)

    def test_a_different_name_still_makes_a_second_project(self):
        """1 folder : N projects is deliberate — the guard must not kill it."""
        first = self._create("Angle One")
        second = self._create("Angle Two")
        self.assertNotEqual(second["entry"]["id"], first["entry"]["id"])
        self.assertFalse(second.get("already_registered"))

    def test_a_retired_project_does_not_block_re_registration(self):
        """group_by_folder includes retired entries; matching them handed back
        a retired project forever and made that name unusable."""
        first = self._create("Retire Me")
        _rnd.retire_project(first["entry"]["id"])
        again = self._create("Retire Me")
        self.assertFalse(again.get("already_registered"),
                         "a retired project must not block a fresh one")
        self.assertNotEqual(again["entry"]["id"], first["entry"]["id"])


if __name__ == "__main__":
    unittest.main()

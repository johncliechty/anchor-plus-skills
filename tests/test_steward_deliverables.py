"""Deliverables surface (2026-08-25, John's ask — campaign journal 0010).

Pins: (1) DELIVERABLES.md parsing (the steward's own register convention — table
rows, backticked path, bold title); (2) HARD containment of the file route —
entries outside the effort dir are text-only and ../ or absolute escapes 404;
(3) the status shape carries deliverables_count.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402
from steward_cockpit import steward_routes as routes      # noqa: E402


REGISTER = """# Deliverables — the things worth opening

| What | Where | Date |
|---|---|---|
| **The report** — final PDF for the collaborator | `deliverables/report.pdf` (copy) | 2026-08-25 |
| **Working notes** — journal entry | `journal/0001-notes.md` | 2026-08-25 |
| **Outside file** — lives above the effort | `../outside.csv` (repo root) | 2026-07 |
| **Missing file** — listed but not on disk | `reports/ghost.md` | 2026-08 |
| **Stepped notes** — carries the optional Step column | `journal/0001-notes.md` | 2026-08-26 | 2 |
"""


class DeliverablesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-deliv-")
        self.cdir = os.path.join(self.tmp, "effort")
        os.makedirs(os.path.join(self.cdir, "deliverables"))
        os.makedirs(os.path.join(self.cdir, "journal"))
        Path(self.cdir, "DELIVERABLES.md").write_text(REGISTER, encoding="utf-8")
        Path(self.cdir, "deliverables", "report.pdf").write_bytes(b"%PDF-1.4 fake")
        Path(self.cdir, "journal", "0001-notes.md").write_text("notes", encoding="utf-8")
        Path(self.tmp, "outside.csv").write_text("a,b", encoding="utf-8")
        # the effort must be DISCOVERABLE for the api_get dispatch tests —
        # discovery keys on ECGBERHT.md (one-level rule)
        Path(self.cdir, "ECGBERHT.md").write_text("# effort face", encoding="utf-8")

    def test_parse_register(self):
        d = campaign.read_deliverables(self.cdir)
        self.assertTrue(d["exists"])
        self.assertEqual(len(d["items"]), 5)
        by_step = {i["what"].split(" — ")[0]: i["step"] for i in d["items"]}
        self.assertEqual(by_step["Stepped notes"], "2")
        self.assertEqual(by_step["The report"], "")
        by = {i["what"].split(" — ")[0]: i for i in d["items"]}
        self.assertTrue(by["The report"]["openable"])
        self.assertTrue(by["Working notes"]["openable"])
        # outside the effort: parsed, NEVER openable (containment is the law)
        self.assertFalse(by["Outside file"]["openable"])
        # listed-but-missing: text-only, not a dead link
        self.assertFalse(by["Missing file"]["openable"])

    def test_no_register_is_honest(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        d = campaign.read_deliverables(empty)
        self.assertFalse(d["exists"])
        self.assertEqual(d["items"], [])

    def test_file_route_containment(self):
        ok, code = routes.handle_get(
            self.cdir, "deliverable-file", {"path": "deliverables/report.pdf"})
        self.assertEqual(code, 200)
        self.assertIn("__file__", ok)
        self.assertEqual(ok["__ctype__"], "application/pdf")
        for escape in ("../outside.csv", "..\\..\\anything.py",
                       os.path.join(self.tmp, "outside.csv"), "reports/ghost.md"):
            _bad, c = routes.handle_get(self.cdir, "deliverable-file", {"path": escape})
            self.assertEqual(c, 404, f"escape must 404: {escape}")

    def test_active_content_served_inert(self):
        Path(self.cdir, "deliverables", "page.html").write_text("<script>x</script>", encoding="utf-8")
        ok, code = routes.handle_get(
            self.cdir, "deliverable-file", {"path": "deliverables/page.html"})
        self.assertEqual(code, 200)
        self.assertTrue(ok["__ctype__"].startswith("text/plain"),
                        "html/svg must be served inert, never renderable")

    def test_status_carries_count(self):
        s = campaign.compose_status(self.cdir)
        self.assertEqual(s.get("deliverables_count"), 5)

    # ── DISPATCH-layer pins (2026-08-25) ─────────────────────────────────────
    # The original bug: every test above pinned handle_get, but api_get routed
    # "deliverables" as a PROJECT verb — the register read the project root and
    # returned exists:false on John's screen while this whole file stayed
    # green. These tests call the layer the page actually hits.

    def test_api_get_register_is_effort_level(self):
        d, code = routes.api_get(self.tmp, "deliverables", {"dir": "effort"})
        self.assertEqual(code, 200)
        self.assertTrue(d["exists"], "register must resolve the EFFORT dir, "
                        "never the project root")
        self.assertEqual(len(d["items"]), 5)

    def test_api_get_register_unknown_effort_404(self):
        _d, code = routes.api_get(self.tmp, "deliverables", {"dir": "nope"})
        self.assertEqual(code, 404)

    def test_api_get_session_files_is_project_level(self):
        from steward_cockpit import steward_engine as eng
        old = eng.STATE_FILE
        eng.STATE_FILE = Path(self.tmp) / "state.json"
        try:
            d, code = routes.api_get(self.tmp, "session-files", {})
        finally:
            eng.STATE_FILE = old
        self.assertEqual(code, 200)
        # the legacy cockpit-tab shape: files work sessions wrote
        self.assertIn("deliverables", d)
        self.assertIsInstance(d["deliverables"], list)

    def test_api_get_deliverable_file_dispatch(self):
        d, code = routes.api_get(
            self.tmp, "deliverable-file",
            {"dir": "effort", "path": "deliverables/report.pdf"})
        self.assertEqual(code, 200)
        self.assertIn("__file__", d)

    def test_api_get_register_all_unions_effort_registers(self):
        # 2026-08-26 (John): the project-wide list is the UNION of the
        # per-effort curated registers — never raw session files. Items carry
        # effort name + dir rel so the client can build contained open links.
        second = os.path.join(self.tmp, "second")
        os.makedirs(second)
        Path(second, "ECGBERHT.md").write_text("# face", encoding="utf-8")
        Path(second, "DELIVERABLES.md").write_text(
            "| What | Where | Date |\n|---|---|---|\n"
            "| **Second report** | `notes.md` | 2026-08-26 |\n",
            encoding="utf-8")
        Path(second, "notes.md").write_text("hi", encoding="utf-8")
        d, code = routes.api_get(self.tmp, "register-all", {"dir": ""})
        self.assertEqual(code, 200)
        self.assertEqual(len(d["items"]), 6)  # 5 from effort + 1 from second
        by_dir = {i["dir"] for i in d["items"]}
        self.assertEqual(by_dir, {"effort", "second"})
        for i in d["items"]:
            self.assertIn("effort", i)
            self.assertIn("what", i)


class SoftStartTest(unittest.TestCase):
    """SOFT START (John, 2026-08-26): opening a parked effort page must wake
    the steward and land the pickup — after a service restart the dialog was
    EMPTY because nothing called wake() on open. Fake-engine seam."""

    def setUp(self):
        from steward_cockpit import steward_engine as eng_mod
        self.tmp = tempfile.mkdtemp(prefix="steward-soft-")
        self.cdir = os.path.join(self.tmp, "effort")
        os.makedirs(self.cdir)
        Path(self.cdir, "ECGBERHT.md").write_text("# face", encoding="utf-8")
        self._old_state = eng_mod.STATE_FILE
        eng_mod.STATE_FILE = Path(self.tmp) / "state.json"
        self._old_fake = routes.CONFIG.get("fake")
        routes.CONFIG["fake"] = True

    def tearDown(self):
        from steward_cockpit import steward_engine as eng_mod
        for key in [k for k in routes.ENGINES if k.startswith(self.cdir)]:
            try:
                routes.ENGINES[key].stop()
            except Exception:
                pass
            routes.ENGINES.pop(key, None)
        eng_mod.STATE_FILE = self._old_state
        routes.CONFIG["fake"] = self._old_fake

    def test_open_poll_wakes_parked_session_with_pickup(self):
        from steward_cockpit import steward_engine as eng_mod
        cdir = routes._effort_dir(self.tmp, "effort")
        eng_mod._update_state(cdir, {"session_id": "fake-parked-1"})
        d, code = routes.api_get(
            self.tmp, "events", {"dir": "effort", "since": "0"})
        self.assertEqual(code, 200)
        texts = " | ".join(e.get("text", "") for e in d["events"])
        self.assertIn("resuming the last session", texts,
                      "open poll must auto-wake a PARKED steward session")

    def test_open_poll_never_spawns_for_fresh_effort(self):
        # no stored session -> a mere page view must not start a model session
        cdir = routes._effort_dir(self.tmp, "effort")
        routes.api_get(self.tmp, "events", {"dir": "effort", "since": "0"})
        eng = routes.ENGINES.get(cdir)
        self.assertTrue(eng is None or not eng.alive(),
                        "fresh effort must stay asleep on open")


if __name__ == "__main__":
    unittest.main()

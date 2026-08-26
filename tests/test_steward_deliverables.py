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

    def test_parse_register(self):
        d = campaign.read_deliverables(self.cdir)
        self.assertTrue(d["exists"])
        self.assertEqual(len(d["items"]), 4)
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
        self.assertEqual(s.get("deliverables_count"), 4)


if __name__ == "__main__":
    unittest.main()

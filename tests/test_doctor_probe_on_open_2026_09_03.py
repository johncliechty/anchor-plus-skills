"""The r3 Doctor rule, built (2026-09-03).

SCORECARD.md, "Doctor rule (v0)": a health issue is already a diagnosis on
disk. Opening Doctor with a red banner (1) reads the latest report, (2) probes
the failing checks NOW, (3) if the 5 AM failure is gone re-runs so the banner
clears, (4-5) otherwise says what is still wrong and stops. "Never start a chat
session named 'Diagnose this' as the path to a fix." The cut it makes on the
live home: the required Diagnose click when a health issue already exists.

What this pins:
  * ``GET /api/doctor/probe`` — token-authed, registered, READ-ONLY (never
    starts the re-run, never a session, never a seed);
  * the page calls it on open whenever an issue exists, re-runs the check
    itself ONLY on ``rerun`` (the deterministic health check — no model), and
    a model session still needs a click;
  * the home banner says what a click does, in plain words.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anchor_gui  # noqa: E402
import route_table  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RAW_HTTP = ("0/7 passed; failures: GET /: timed out (20.0s); GET /api/status: timed out; "
            "POST /api/done: <urlopen error [WinError 10061] No connection could be made "
            "because the target machine actively refused it>")
AUTOFIX = ["test port 8778 busy; ran on free port 59984 instead"]


class _FakeHandler:
    def __init__(self):
        self.sent = []

    def _send_json(self, data, code=200):
        self.sent.append((code, data))


def _answering(p, timeout=4.0):
    return {"path": p, "ok": True, "code": 200, "ms": 3}


class ProbeRouteTest(unittest.TestCase):
    def test_route_row_registry_and_inventory(self):
        rows = [r for r in route_table.ROUTES if r.pattern == "/api/doctor/probe"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].method, rows[0].auth, rows[0].handler, rows[0].migrated),
                         ("GET", route_table.AUTH_TOKEN, "handle_doctor_probe", True))
        self.assertIn("handle_doctor_probe", anchor_gui._MIGRATED_HANDLERS)
        inv = (REPO / "chamber" / "routes-inventory.json").read_text(encoding="utf-8")
        self.assertIn('"pattern": "/api/doctor/probe"', inv)

    def test_probe_is_read_only_and_decides(self):
        h = _FakeHandler()
        stats = {"issues": [{"component": "HTTP endpoints", "detail": RAW_HTTP}],
                 "autofixes": AUTOFIX, "last_run": "2026-09-03", "status": "red"}
        with mock.patch.object(anchor_gui, "_doctor_stats", return_value=stats), \
             mock.patch.object(anchor_gui, "_doctor_live_probe", side_effect=_answering), \
             mock.patch.object(anchor_gui, "_doctor_start_healthcheck_run") as run, \
             mock.patch.object(anchor_gui, "handle_doctor_session_start") as start:
            anchor_gui.handle_doctor_probe(h, "/api/doctor/probe", {})
        code, out = h.sent[0]
        self.assertEqual(code, 200)
        self.assertEqual(out["decision"], "rerun")
        self.assertEqual([p["path"] for p in out["probe"]], ["/", "/api/status"])
        self.assertIn("could not reach its throwaway test copy", out["issues"][0]["title"])
        self.assertEqual(out["last_run"], "2026-09-03")
        run.assert_not_called()      # the PAGE decides to re-run; the probe never does
        start.assert_not_called()
        self.assertNotIn("seed_issue", out)
        self.assertNotIn("rerun", out)

    def test_probe_says_session_when_something_is_really_wrong(self):
        h = _FakeHandler()
        stats = {"issues": [{"component": "journal", "detail": "5/6 passed; failures: journal corrupt"}],
                 "autofixes": []}
        with mock.patch.object(anchor_gui, "_doctor_stats", return_value=stats), \
             mock.patch.object(anchor_gui, "_doctor_live_probe", side_effect=_answering):
            anchor_gui.handle_doctor_probe(h, "/api/doctor/probe", {})
        out = h.sent[0][1]
        self.assertEqual(out["decision"], "session")
        self.assertEqual(out["issues"][0]["title"], "journal: 1 of 6 checks failed")

    def test_probe_with_a_clean_report_is_nothing(self):
        h = _FakeHandler()
        with mock.patch.object(anchor_gui, "_doctor_stats", return_value={"issues": [], "autofixes": []}), \
             mock.patch.object(anchor_gui, "_doctor_live_probe") as probe:
            anchor_gui.handle_doctor_probe(h, "/api/doctor/probe", {})
        self.assertEqual(h.sent[0][1]["decision"], "nothing")
        probe.assert_not_called()

    def test_resolve_all_shares_the_probe(self):
        # One truth: the button's decision is the open-time decision.
        src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        body = src[src.index("def handle_doctor_resolve_all("):src.index("def _doctor_start_healthcheck_run(")]
        self.assertIn("_doctor_probe_state()", body)


class PageProbesOnOpenTest(unittest.TestCase):
    def setUp(self):
        self.src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        self.tpl = self.src[self.src.index("_DOCTOR_PAGE_TEMPLATE = r"):self.src.index("def render_doctor_page_html(")]

    def test_page_probes_on_open_whenever_an_issue_exists(self):
        self.assertIn("function probeOnOpen()", self.tpl)
        self.assertIn("fetch(tq('/api/doctor/probe')", self.tpl)
        self.assertIn("if (BANNER_ISSUE || DOCTOR_ISSUES.length) probeOnOpen();", self.tpl)
        # It runs after the engine-health status fetch (shell-first), once.
        self.assertLess(self.tpl.index("fetch(tq('/api/doctor/status')"),
                        self.tpl.index("if (BANNER_ISSUE || DOCTOR_ISSUES.length) probeOnOpen();"))
        self.assertIn("if (PROBED_ON_OPEN) return;", self.tpl)

    def test_rerun_is_automatic_and_a_model_session_never_is(self):
        fn = self.tpl[self.tpl.index("function probeOnOpen()"):self.tpl.index("// Shell-first:")]
        rerun = fn[fn.index("p.decision === 'rerun'"):fn.index("p.decision === 'session'")]
        self.assertIn("window.runDiagnostics();", rerun)      # the deterministic check
        self.assertNotIn("runDiagnose(", fn)                   # never a model session
        self.assertNotIn("session_start", fn)
        self.assertNotIn("resolve_all", fn)
        self.assertIn("your click", fn)                        # the session case waits

    def test_the_old_click_to_diagnose_prompt_is_gone(self):
        self.assertNotIn("Click Diagnose to start a model session", self.tpl)
        self.assertNotIn('Click Diagnose, or use "Resolve this" above', self.tpl)

    def test_home_banner_says_what_a_click_does(self):
        self.assertIn("Click: Doctor reads it, probes the live server, and", self.src)
        self.assertNotIn("seeded context — not a static markdown path", self.src)

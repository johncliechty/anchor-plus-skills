"""Doctor, per John's 2026-09-03 look.

1. Issues in plain words (doctor_plain): a title, one sentence of meaning, the
   raw report line behind a disclosure — never lost, never a guess.
2. "Resolve all": re-probe the live server; every issue was the self-test
   failing to reach its own target AND live answers → re-run the check so the
   banner clears; else ONE doctor session seeded with all issues.
3. "Resolve this" / "Resolve all" RUN the seeded brief: a settled Enter follows
   the paste (Diagnose stays hands-off).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anchor_gui  # noqa: E402
import doctor_plain as dp  # noqa: E402
import route_table  # noqa: E402
import terminal_session as ts  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RAW_HTTP = ("0/7 passed; failures: GET /: timed out (20.0s); GET /api/status: timed out; "
            "POST /api/done: <urlopen error [WinError 10061] No connection could be made "
            "because the target machine actively refused it>")
RAW_WALK = ("38 rows walked; 3 failed: GET /: transport error <urlopen error [WinError 10061] "
            "No connection could be made>; GET /dashboard: transport error <urlopen error>")
AUTOFIX = ["test port 8778 busy; ran on free port 59984 instead"]


class PlainWordsTest(unittest.TestCase):
    def test_self_test_unreachable_reads_as_such_and_keeps_the_raw(self):
        ex = dp.explain({"component": "HTTP endpoints", "detail": RAW_HTTP}, AUTOFIX)
        self.assertEqual(ex["kind"], dp.KIND_SELF_TEST_UNREACHABLE)
        self.assertIn("could not reach its throwaway test copy", ex["title"])
        self.assertIn("7 of 7", ex["meaning"])
        self.assertIn("live Anchor was not the one", ex["meaning"])
        self.assertTrue(ex["raw"].startswith("[HTTP endpoints] 0/7 passed"))
        self.assertIn("/api/status", ex["paths"])

    def test_generic_failures_and_junk_never_raise(self):
        ex = dp.explain({"component": "journal", "detail": "5/6 passed; failures: journal corrupt at line 3"})
        self.assertEqual(ex["kind"], dp.KIND_CHECKS_FAILED)
        self.assertEqual(ex["title"], "journal: 1 of 6 checks failed")
        self.assertIn("journal corrupt", ex["meaning"])
        ex = dp.explain({"component": "x", "detail": ""})
        self.assertEqual(ex["kind"], dp.KIND_OTHER)
        self.assertEqual(dp.explain_all([None, "junk", {}])[0]["kind"], dp.KIND_OTHER)

    def test_probe_targets_are_get_only_and_safe(self):
        ex = dp.explain_all([{"component": "HTTP endpoints", "detail": RAW_HTTP},
                             {"component": "declared-route auth walk (W8)", "detail": RAW_WALK}], AUTOFIX)
        t = dp.probe_targets(ex)
        self.assertEqual(t, ["/", "/api/status", "/dashboard"])
        self.assertNotIn("/api/done", t)   # a write endpoint is never re-probed
        self.assertEqual(dp.probe_targets([]), ["/api/version", "/api/status"])

    def test_decision(self):
        ex = dp.explain_all([{"component": "HTTP endpoints", "detail": RAW_HTTP}], AUTOFIX)
        ok = [{"path": "/", "ok": True}, {"path": "/api/status", "ok": True}]
        self.assertEqual(dp.decide(ex, ok), "rerun")
        self.assertEqual(dp.decide(ex, [{"path": "/", "ok": False}]), "session")
        self.assertEqual(dp.decide(ex + [dp.explain({"component": "journal", "detail": "5/6 passed; failures: x"})], ok), "session")
        self.assertEqual(dp.decide([], ok), "nothing")
        seed = dp.resolve_all_seed(ex, ok, "session")
        self.assertTrue(seed.startswith("ANCHOR DOCTOR - RESOLVE ALL 1 OPEN ISSUES NOW"))
        self.assertIn("live re-probe just now: / answers; /api/status answers", seed)


class _FakeHandler:
    def __init__(self):
        self.sent = []

    def _send_json(self, data, code=200):
        self.sent.append((code, data))


class ResolveAllRouteTest(unittest.TestCase):
    def test_route_row_and_registry(self):
        rows = [r for r in route_table.ROUTES if r.pattern == "/api/doctor/resolve_all"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].method, rows[0].auth, rows[0].handler),
                         ("POST", route_table.AUTH_TOKEN, "handle_doctor_resolve_all"))
        self.assertIn("handle_doctor_resolve_all", anchor_gui._MIGRATED_HANDLERS)

    def test_rerun_when_only_the_self_test_was_unreachable_and_live_answers(self):
        h = _FakeHandler()
        stats = {"issues": [{"component": "HTTP endpoints", "detail": RAW_HTTP}], "autofixes": AUTOFIX}
        with mock.patch.object(anchor_gui, "_doctor_stats", return_value=stats), \
             mock.patch.object(anchor_gui, "_doctor_live_probe",
                               side_effect=lambda p, timeout=4.0: {"path": p, "ok": True, "code": 200, "ms": 3}), \
             mock.patch.object(anchor_gui, "_doctor_start_healthcheck_run", return_value={"ok": True, "pid": 1}) as run:
            anchor_gui.handle_doctor_resolve_all(h, "/api/doctor/resolve_all", {})
        code, out = h.sent[0]
        self.assertEqual(code, 200)
        self.assertEqual(out["decision"], "rerun")
        self.assertEqual([p["path"] for p in out["probe"]], ["/", "/api/status"])
        run.assert_called_once()
        self.assertNotIn("seed_issue", out)

    def test_session_seed_when_something_is_really_wrong(self):
        h = _FakeHandler()
        stats = {"issues": [{"component": "journal", "detail": "5/6 passed; failures: journal corrupt"}],
                 "autofixes": []}
        with mock.patch.object(anchor_gui, "_doctor_stats", return_value=stats), \
             mock.patch.object(anchor_gui, "_doctor_live_probe",
                               side_effect=lambda p, timeout=4.0: {"path": p, "ok": True, "code": 200, "ms": 3}), \
             mock.patch.object(anchor_gui, "_doctor_start_healthcheck_run") as run:
            anchor_gui.handle_doctor_resolve_all(h, "/api/doctor/resolve_all", {})
        out = h.sent[0][1]
        self.assertEqual(out["decision"], "session")
        run.assert_not_called()
        self.assertTrue(out["seed_issue"]["all"])
        self.assertIn("RESOLVE ALL 1 OPEN ISSUES", out["seed_issue"]["message"])

    def test_page_card_is_plain_words_with_resolve_all(self):
        s = {"issues": [{"component": "HTTP endpoints", "detail": RAW_HTTP}], "autofixes": AUTOFIX}
        html = anchor_gui._doctor_issues_block_html(s)
        self.assertIn("could not reach its throwaway test copy", html)
        self.assertIn("what the check said", html)          # raw behind a disclosure
        self.assertIn("0/7 passed", html)
        self.assertIn('id="resolveAllBtn"', html)
        self.assertIn("onclick=\"resolveAll()\"", html)
        self.assertIn("onclick=\"resolveIssue(0)\"", html)
        src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        self.assertIn("window.resolveAll = function", src)
        self.assertIn("fetch('/api/doctor/resolve_all'", src)
        self.assertIn("window.runDiagnose({ fromBanner: true, resolve: true })", src)


class AutoSubmitTest(unittest.TestCase):
    def _pty(self, texts, writes):
        it = iter(texts)
        last = {"t": ""}

        def read_since(sid, cur):
            try:
                last["t"] = next(it)
            except StopIteration:
                pass
            return {"text": last["t"]}

        def write(sid, data):
            writes.append(data)
        return read_since, write

    def test_presses_enter_once_the_tui_settled_and_stops_when_the_model_answers(self):
        writes = []
        frame = "x" * 200
        read_since, write = self._pty([frame, frame + "y" * 100], writes)
        with mock.patch.object(ts._pty, "read_since", read_since), mock.patch.object(ts._pty, "write", write), \
             mock.patch.object(ts.time, "sleep", lambda s: None):
            n = ts._auto_submit_seed("sid", settle=0, min_output=120, timeout=5, _sync=True)
        self.assertEqual(n, 1)
        self.assertEqual(writes, ["\r"])

    def test_second_press_when_the_first_was_swallowed(self):
        writes = []
        frame = "x" * 200
        read_since, write = self._pty([frame, frame, frame], writes)
        with mock.patch.object(ts._pty, "read_since", read_since), mock.patch.object(ts._pty, "write", write), \
             mock.patch.object(ts.time, "sleep", lambda s: None):
            n = ts._auto_submit_seed("sid", settle=0, min_output=120, timeout=5, _sync=True)
        self.assertEqual(n, 2)
        self.assertEqual(writes, ["\r", "\r"])

    def test_no_press_without_a_live_pty_or_before_the_frame(self):
        writes = []
        with mock.patch.object(ts._pty, "read_since", side_effect=RuntimeError("dead")), \
             mock.patch.object(ts._pty, "write", lambda s, d: writes.append(d)), \
             mock.patch.object(ts.time, "sleep", lambda s: None):
            self.assertEqual(ts._auto_submit_seed("sid", settle=0, timeout=1, _sync=True), 0)
        self.assertEqual(writes, [])

    def test_only_resolve_sessions_auto_submit(self):
        src = (REPO / "terminal_session.py").read_text(encoding="utf-8")
        blk = src.split("def start_doctor_session(")[1].split("def _auto_submit_seed(")[0]
        self.assertIn('if resolve and seed_context and rec and rec.get("session_id"):', blk)
        self.assertIn('_auto_submit_seed(rec["session_id"])', blk)


if __name__ == "__main__":
    unittest.main()

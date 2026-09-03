"""POST /api/restart — supervised self-restart (2026-09-03).

Contract: token-authed row; refuses (409, no exit) unless the parent process
is nssm (AppExit=Restart) or the caller forces it; when honored it answers
first, drains warm (fail-open), then exits 0 so nssm brings a fresh server up.
The removed /api/shutdown stays removed — this can never leave Anchor down.
"""
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anchor_gui  # noqa: E402
import route_table  # noqa: E402


class _FakeHandler:
    def __init__(self):
        self.sent = []

    def _send_json(self, data, code=200):
        self.sent.append((code, data))


class RestartRouteTest(unittest.TestCase):
    def test_route_row_is_token_authed_post(self):
        rows = [r for r in route_table.ROUTES if r.pattern == "/api/restart"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r.method, "POST")
        self.assertEqual(r.auth, route_table.AUTH_TOKEN)
        self.assertEqual(r.handler, "handle_restart")
        self.assertTrue(hasattr(anchor_gui, "handle_restart"))

    def test_unsupervised_refuses_and_never_exits(self):
        h = _FakeHandler()
        with mock.patch.object(anchor_gui, "_supervisor_parent_name", return_value="python.exe"), \
             mock.patch.object(anchor_gui.os, "_exit") as ex:
            anchor_gui.handle_restart(h, "/api/restart", {})
        self.assertEqual(h.sent[0][0], 409)
        self.assertEqual(h.sent[0][1]["error"], "not_supervised")
        self.assertEqual(h.sent[0][1]["parent"], "python.exe")
        ex.assert_not_called()

    def test_supervised_answers_then_drains_then_exits(self):
        h = _FakeHandler()
        done = threading.Event()
        calls = []

        def _fake_exit(code):
            calls.append(("exit", code))
            done.set()

        def _fake_drain(**kw):
            calls.append(("drain", kw))
            return {"ok": True}

        from tools import pre_restart_drain
        with mock.patch.object(anchor_gui, "_supervisor_parent_name", return_value="nssm.exe"), \
             mock.patch.object(anchor_gui.os, "_exit", _fake_exit), \
             mock.patch.object(pre_restart_drain, "drain", _fake_drain), \
             mock.patch.object(anchor_gui.time, "sleep", lambda s: None):
            anchor_gui.handle_restart(h, "/api/restart", {})
            self.assertTrue(done.wait(5), "restart thread never exited")
        self.assertEqual(h.sent[0][0], 200)
        self.assertTrue(h.sent[0][1]["restarting"])
        self.assertEqual(h.sent[0][1]["leaving_build"], anchor_gui.BUILD_ID)
        self.assertEqual([c[0] for c in calls], ["drain", "exit"])  # answer → drain → exit
        self.assertEqual(calls[1][1], 0)

    def test_drain_failure_is_fail_open(self):
        h = _FakeHandler()
        done = threading.Event()
        from tools import pre_restart_drain

        def _boom(**kw):
            raise RuntimeError("drain broke")

        with mock.patch.object(anchor_gui, "_supervisor_parent_name", return_value="nssm.exe"), \
             mock.patch.object(anchor_gui.os, "_exit", lambda c: done.set()), \
             mock.patch.object(pre_restart_drain, "drain", _boom), \
             mock.patch.object(anchor_gui.time, "sleep", lambda s: None):
            anchor_gui.handle_restart(h, "/api/restart", {"force": True})
            self.assertTrue(done.wait(5))
        self.assertEqual(h.sent[0][0], 200)

    def test_force_overrides_unsupervised(self):
        h = _FakeHandler()
        done = threading.Event()
        from tools import pre_restart_drain
        with mock.patch.object(anchor_gui, "_supervisor_parent_name", return_value=""), \
             mock.patch.object(anchor_gui.os, "_exit", lambda c: done.set()), \
             mock.patch.object(pre_restart_drain, "drain", lambda **kw: {}), \
             mock.patch.object(anchor_gui.time, "sleep", lambda s: None):
            anchor_gui.handle_restart(h, "/api/restart", {"force": True})
            self.assertTrue(done.wait(5))
        self.assertEqual(h.sent[0][1]["parent"], "unknown")


if __name__ == "__main__":
    unittest.main()

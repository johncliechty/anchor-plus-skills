"""Adjustments from what John saw on 2026-09-04.

1. "the total spend tokens, time and $ resets every time I reconnect with Anchor" — the
   steward engine's counters started at zero on every (re)creation and the turn-end write
   replaced the durable usage with the smaller in-memory total. Now they are seeded from
   the durable record, so an effort's totals carry its entire history.
2. "the cockpit refreshed on its own ... and cleared the dialogue while I was typing" — the
   redeploy watcher reloaded every open page the moment a new build was served. It now
   waits while a text field has focus or holds unsent text, and stashes every draft
   across the reload it eventually does.
3. The hunter GUI process outlives service restarts with the code and environment it was
   born with; Anchor now recycles a hunter whose server.js on disk is newer than the one
   it reports (a hunter reporting none is an old build).
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anchor_gui  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class UsageSurvivesReconnectTest(unittest.TestCase):
    def test_engine_seeds_its_counters_from_the_durable_record(self):
        src = (REPO / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
        i = src.index('_u = stored_entry.get("usage") or {}')
        block = src[i:i + 500]
        for line in ('self.spend = float(_u.get("spend") or 0.0)',
                     'self.tokens = int(_u.get("tokens") or 0)',
                     'self.secs = float(_u.get("secs") or 0.0)',
                     'self.turns = int(_u.get("turns") or 0)'):
            self.assertIn(line, block)
        # the zero-start that caused the reset is gone from the constructor
        ctor = src[src.index("class Engine:"):src.index('_u = stored_entry.get("usage")')]
        self.assertNotIn("self.spend = 0.0", ctor)


class RedeployKeepsDraftsTest(unittest.TestCase):
    def test_watcher_waits_while_typing_and_stashes_drafts(self):
        js = anchor_gui.cache_bust_script()
        self.assertIn("function typing()", js)
        self.assertIn("if (typing()) return;", js)
        self.assertIn("function stashDrafts()", js)
        self.assertIn("function restoreDrafts()", js)
        self.assertIn("stashDrafts();", js[js.index("function checkVersion()"):])
        self.assertIn("anchor_drafts:", js)
        self.assertIn("restoreDrafts()", js[js.index("if (document.readyState"):])
        # still exactly one reload per served version
        self.assertIn("anchor_reloaded_for", js)


class HunterSelfRelaunchTest(unittest.TestCase):
    def _state(self, payload):
        class _R:
            def __init__(self, b): self._b = b
            def read(self): return self._b
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _R(json.dumps(payload).encode("utf-8"))

    def test_a_hunter_reporting_no_build_is_stale_and_a_current_one_is_not(self):
        with mock.patch("urllib.request.urlopen", return_value=self._state({"zombies": []})), \
             mock.patch("os.path.getmtime", return_value=1_700_000_000.0):
            self.assertTrue(anchor_gui._zh_node_is_stale())
        with mock.patch("urllib.request.urlopen", return_value=self._state({"server_mtime": 1_700_000_000_000.0})), \
             mock.patch("os.path.getmtime", return_value=1_700_000_000.0):
            self.assertFalse(anchor_gui._zh_node_is_stale())
        with mock.patch("urllib.request.urlopen", return_value=self._state({"server_mtime": 1_699_999_000_000.0})), \
             mock.patch("os.path.getmtime", return_value=1_700_000_000.0):
            self.assertTrue(anchor_gui._zh_node_is_stale())   # disk is newer by 1000 s
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertFalse(anchor_gui._zh_node_is_stale())  # not up is not "stale"

    def test_ensure_recycles_a_live_but_stale_hunter(self):
        src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        i = src.index("def _ensure_zh_node_server(")
        body = src[i:i + 2600]
        self.assertIn("if _zh_node_is_up(timeout=0.8) and not _zh_node_is_stale(timeout=0.8):", body)
        self.assertIn("older server.js than on disk — recycling", body)
        self.assertLess(body.index("older server.js than on disk"), body.index("_zh_node_kill_listener()"))


if __name__ == "__main__":
    unittest.main()

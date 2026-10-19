"""The dashboard's selected families are the universal source of seats (John, 2026-09-04):
"the seats for different skills should be what is set in the Anchor main dashboard (go and
get that and use that ... universal throughout all of the skills)".

Anchor's own surfaces still keyed on WHICH CLIS ARE INSTALLED: the no-preference engine plan
offered a "Gemini swarm" whenever agy was on PATH, the model-flex badge said so, and the
Doctor / hunter engine pickers offered Gemini as a live choice — after the Gemini
subscription was dropped. Now every one of them reads the dashboard.

Also pinned: the session reconcile / auto-advance runs on a SERVER ticker, not only under a
browser's poll — "we should not be tied to whether a particular device is up and has an
Anchor webpage active".
"""
import importlib
import inspect
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anchor_gui  # noqa: E402
import lanes  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BOTH = {"claude": True, "gemini": True, "grok": True, "chatgpt": True}
JOHNS = {"default_cli": "claude", "coding": "chatgpt", "review": "claude", "selected": {"claude", "chatgpt"}}
WITH_GEMINI = {"default_cli": "claude", "coding": "claude", "review": "gemini", "selected": {"claude", "gemini"}}


class SelectedFamiliesTest(unittest.TestCase):
    def test_reads_the_dashboard_settings_never_the_installed_clis(self):
        import anchor_settings
        with mock.patch.object(anchor_settings, "load_settings",
                               return_value={"default_cli": "grok", "coding_family": "chatgpt", "review_family": "claude"}):
            f = lanes.selected_families()
        self.assertEqual((f["default_cli"], f["coding"], f["review"]), ("grok", "chatgpt", "claude"))
        self.assertEqual(f["selected"], {"grok", "chatgpt", "claude"})
        with mock.patch.object(anchor_settings, "load_settings", side_effect=RuntimeError("boom")):
            f = lanes.selected_families()
        self.assertEqual(f["selected"], {"claude"})          # total: defaults, never raises


class EnginePlanTest(unittest.TestCase):
    def test_both_installed_but_gemini_unselected_spawns_no_gemini(self):
        plan = lanes.select_engine_plan("research", profile=BOTH, families=JOHNS)
        self.assertEqual(plan["driver"], "claude")
        self.assertIsNone(plan["swarm"])
        self.assertFalse(plan["spawns_gemini"])
        self.assertIn("not a selected family", plan["reason"])
        self.assertEqual(plan["families"]["coding"], "chatgpt")

    def test_both_installed_and_gemini_selected_keeps_the_swarm(self):
        plan = lanes.select_engine_plan("research", profile=BOTH, families=WITH_GEMINI)
        self.assertEqual(plan["swarm"], "gemini")
        self.assertTrue(plan["spawns_gemini"])

    def test_no_families_argument_reads_the_dashboard(self):
        with mock.patch.object(lanes, "selected_families", return_value=JOHNS) as sf:
            plan = lanes.select_engine_plan("research", profile=BOTH)
        sf.assert_called_once()
        self.assertFalse(plan["spawns_gemini"])


class EngineToggleTest(unittest.TestCase):
    def test_installed_but_unselected_engine_is_offered_disabled_with_the_reason(self):
        with mock.patch.object(anchor_gui._lanes, "selected_families", return_value=JOHNS):
            toggle = anchor_gui._w8_engine_toggle(profile=BOTH)
        by = {e["id"]: e for e in toggle["engines"]}
        self.assertTrue(by["claude"]["enabled"] and by["chatgpt"]["enabled"])
        self.assertFalse(by["gemini"]["enabled"])
        self.assertFalse(by["gemini"]["selected"])
        self.assertIn("not selected on the dashboard", by["gemini"]["health"])
        self.assertFalse(by["grok"]["enabled"])
        self.assertNotIn("gemini", toggle["available"])
        self.assertEqual(toggle["defaultEngine"], "claude")   # default_cli wins the picker

    def test_an_explicit_selection_seam_is_honored(self):
        toggle = anchor_gui._w8_engine_toggle(profile=BOTH, prefs={"_selected": {"grok"}, "default_cli": "grok"})
        by = {e["id"]: e for e in toggle["engines"]}
        self.assertTrue(by["grok"]["enabled"])
        self.assertFalse(by["claude"]["enabled"])
        self.assertEqual(toggle["defaultEngine"], "grok")

    def test_uninstalled_stays_unavailable_even_if_selected(self):
        toggle = anchor_gui._w8_engine_toggle(profile={"claude": True, "gemini": False}, prefs={"_selected": {"gemini", "claude"}})
        gem = next(e for e in toggle["engines"] if e["id"] == "gemini")
        self.assertFalse(gem["enabled"])
        self.assertIn("not detected", gem["health"])


class HunterSpawnTest(unittest.TestCase):
    def test_the_hunter_gui_is_spawned_with_the_dashboard_prefs_env(self):
        src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        i = src.index('["node", _ZH_NODE_SERVER_PATH]')
        block = src[i - 600:i + 400]
        self.assertIn("_aset.export_env_overrides()", block)
        self.assertIn("env=_zh_env", block)
        import anchor_settings
        keys = set(anchor_settings.export_env_overrides())
        self.assertTrue({"ANCHOR_DEFAULT_CLI", "CODING_FAMILY", "REVIEW_FAMILY"} <= keys)


class BadgeTest(unittest.TestCase):
    def test_badge_says_what_the_dashboard_selected(self):
        html = anchor_gui.render_model_flex_badge(
            env={"ANCHOR_CLAUDE_AVAILABLE": "1", "ANCHOR_GEMINI_AVAILABLE": "1"}, families=JOHNS)
        self.assertIn("Coder Chatgpt", html)
        self.assertIn("Reviewer Claude", html)
        self.assertNotIn("Gemini swarm", html)
        html = anchor_gui.render_model_flex_badge(
            env={"ANCHOR_CLAUDE_AVAILABLE": "1", "ANCHOR_GEMINI_AVAILABLE": "1"}, families=WITH_GEMINI)
        self.assertIn("Gemini swarm", html)


class ReconcileTickerTest(unittest.TestCase):
    def test_the_poll_handler_calls_the_shared_tick(self):
        src = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        self.assertIn("    _reconcile_sessions_tick(pid)\n", src)
        self.assertIn("def _reconcile_sessions_tick(pid=None):", src)
        self.assertIn("with _RECONCILE_TICK_LOCK:", inspect.getsource(anchor_gui._reconcile_sessions_tick))

    def test_main_starts_the_ticker_and_it_is_a_daemon(self):
        src = inspect.getsource(anchor_gui.main)
        self.assertIn("_start_reconcile_ticker()", src)
        with mock.patch.dict("os.environ", {"ANCHOR_RECONCILE_TICK_S": "0"}):
            self.assertIsNone(anchor_gui._start_reconcile_ticker())      # 0 disables
        with mock.patch.dict("os.environ", {"ANCHOR_RECONCILE_TICK_S": "3600"}):
            t = anchor_gui._start_reconcile_ticker()
        self.assertIsInstance(t, threading.Thread)
        self.assertTrue(t.daemon)
        self.assertEqual(t.name, "anchor-reconcile-tick")

    def test_the_tick_is_total_when_nothing_is_registered(self):
        # runs the real function against an empty live set; must never raise
        with mock.patch.object(anchor_gui._termsess, "list_sessions", return_value=[]), \
             mock.patch.object(anchor_gui._termsess._pty, "live_sessions", return_value=[]), \
             mock.patch.object(anchor_gui._termsess, "reconcile_and_advance", return_value={"reconcile": {"marked": []}}) as ra, \
             mock.patch.object(anchor_gui._termsess, "recover_interrupted_efforts", return_value=None):
            anchor_gui._reconcile_sessions_tick(None)
        ra.assert_called_once()


if __name__ == "__main__":
    unittest.main()

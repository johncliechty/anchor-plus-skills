"""ZH-node recycle-storm circuit-breaker tests (2026-07-26 hardening, P0.6).

logs/errors.log showed 74 cycles of
    "ensure_zh_node: port 48484 listening but /api/state dead — recycling"
    "ensure_zh_node: killed wedged listener pid=..."
    "ensure_zh_node: launched server.js on port 48484"
at 6-8 second intervals, forking a Node process on every cycle, with no backoff
and no give-up. It was the loudest error in the log — in the very subsystem the
product most wants to look trustworthy.

The breaker is exercised through the module's own state helpers rather than by
booting the server (importing anchor_gui starts one).
"""
import re
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = (REPO / "anchor_gui.py").read_text(encoding="utf-8", errors="replace")


def _breaker_ns():
    """Exec just the breaker block in isolation (anchor_gui boots a server)."""
    start = SRC.index("#: Consecutive failed (re)starts")
    end = SRC.index("def _ensure_zh_node_server", start)
    block = SRC[start:end]
    # The block logs the server path when it opens; supply it (the real module
    # defines it above this block).
    ns = {"time": time, "_logger": _NullLogger(),
          "_ZH_NODE_SERVER_PATH": "<server.js>"}
    exec(compile(block, "<breaker>", "exec"), ns)  # noqa: S102 - test harness
    return ns


class _NullLogger:
    def info(self, *a, **k):
        pass
    warning = error = debug = info


def test_backoff_grows_and_is_capped():
    ns = _breaker_ns()
    fail, state = ns["_zh_node_breaker_fail"], ns["zh_node_breaker_state"]
    fail()
    first = state()["next_attempt_in_s"]
    assert 1 < first <= ns["_ZH_NODE_BACKOFF_BASE_S"] + 1
    fail()
    second = state()["next_attempt_in_s"]
    assert second > first, "backoff must grow, not repeat at a fixed 6-8s"
    for _ in range(8):
        fail()
    assert state()["next_attempt_in_s"] <= ns["_ZH_NODE_BACKOFF_CAP_S"] + 1


def test_breaker_opens_after_the_retry_limit_and_stops_respawning():
    ns = _breaker_ns()
    fail, state = ns["_zh_node_breaker_fail"], ns["zh_node_breaker_state"]
    for _ in range(ns["_ZH_NODE_MAX_RETRIES"]):
        fail()
    st = state()
    assert st["open"] is True, "the breaker must OPEN — 74 cycles is not a strategy"
    assert st["open_for_s"] > 60, "an open breaker needs a real cooldown"


def test_success_resets_everything():
    ns = _breaker_ns()
    for _ in range(ns["_ZH_NODE_MAX_RETRIES"]):
        ns["_zh_node_breaker_fail"]()
    ns["_zh_node_breaker_reset"]()
    st = ns["zh_node_breaker_state"]()
    assert st == {"fails": 0, "open": False, "open_for_s": 0.0,
                  "next_attempt_in_s": 0.0}


def test_the_supervisor_actually_consults_the_breaker():
    """A breaker nothing checks is the 'documented but not wired' defect class."""
    fn = SRC.split("def _ensure_zh_node_server", 1)[1].split("\ndef ", 1)[0]
    assert "_zh_node_breaker[\"open_until\"]" in fn, (
        "the supervisor must refuse to respawn while the breaker is open")
    assert "next_attempt_at" in fn, "the supervisor must honor the backoff window"
    assert "_zh_node_breaker_fail()" in fn, "a failed start must record a failure"
    assert "_zh_node_breaker_reset()" in fn, "a healthy radar must reset the breaker"


def test_the_open_breaker_says_the_radar_is_down_honestly():
    """Silence would be worse than the storm: the operator must be told."""
    block = SRC[SRC.index("def _zh_node_breaker_fail"):
                SRC.index("def zh_node_breaker_state")]
    assert re.search(r"radar is DOWN", block), (
        "opening the breaker must state plainly that the radar is not running")

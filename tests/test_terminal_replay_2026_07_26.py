"""Terminal double-print regression tests (2026-07-26 hardening, P0.1 + P0.2).

The reported symptom (John's laptop): the terminal renders everything twice and
loses its place after sleep. Evidence in logs/nssm-stdout.log: two
``term_stream2`` subscriptions for ONE session in the same second following a
92-minute sleep gap.

Three defects, each pinned here:
  1. the client never sent a cursor, so every (re)connect replayed the whole
     retained 200KB buffer on top of the screen — and the WS path had no
     ``since`` knob at all (server hard-coded ``cursor = 0``);
  2. the SSE fallback fired even when the WebSocket HAD been working, opening a
     second consumer on one PTY;
  3. ``_mountTerminal`` tore nothing down, so a re-entrant mount left a second
     xterm + a live orphaned transport (also the iPad dual-input amplifier).

These are contract tests over the shipped client/server source: they assert the
wiring exists and cannot silently regress. The live behavioural proof is the
Playwright/CDP offline-online cycle noted in the hardening REVIEW.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
JS = (REPO / "static" / "project-window.js").read_text(encoding="utf-8",
                                                       errors="replace")
GUI = (REPO / "anchor_gui.py").read_text(encoding="utf-8", errors="replace")


def test_client_sends_a_cursor_on_both_transports():
    """Both SSE and WS URLs must carry &since= — no more replay-from-zero."""
    assert "'&since=' + cursor" in JS, "no cursor on an outbound transport URL"
    # Specifically both builders.
    assert "term_ws?session=" in JS and "term_stream2?session=" in JS
    ws_block = JS.split("function _wsUrl()", 1)[1][:400]
    assert "&since=" in ws_block, "the WebSocket URL must resume from the cursor"
    sse_block = JS.split("var sseUrl =", 1)[1][:400]
    assert "&since=" in sse_block, "the SSE URL must resume from the cursor"


def test_client_advances_the_cursor_from_server_payloads():
    """The server already returned `next`; it used to be discarded."""
    assert "_bumpCursor" in JS
    assert "p.next" in JS or "typeof p.next" in JS


def test_dropped_scrollback_is_surfaced_not_silent():
    """read_since clamps a stale cursor; the loss must be visible to the user."""
    assert "_noteDropped" in JS
    assert "scrollback dropped" in JS


def test_websocket_server_honors_since_instead_of_hardcoding_zero():
    """The WS handler had NO since knob — every attach replayed everything."""
    assert 'cursor = int(_q.get("since", ["0"])[0] or 0)' in GUI, (
        "the term_ws handler must parse ?since= like the SSE handler does")
    # The old UNCONDITIONAL reset must be gone: `inbuf = b""` used to be
    # followed immediately by `cursor = 0`. (A `cursor = 0` inside the parse's
    # except-fallback is correct and must NOT trip this.)
    ws_fn = GUI.split("def _serve_term_ws", 1)[1].split("\n    def ", 1)[0]
    assert 'inbuf = b""\n        cursor = 0' not in ws_fn, (
        "term_ws still hard-codes cursor = 0 instead of honoring ?since=")


def test_sse_fallback_only_when_the_websocket_never_delivered():
    """A WS that worked then closed must NOT open a second transport."""
    assert "var gotData = false;" in JS
    assert "if (!sseStarted && !gotData) startSSE();" in JS, (
        "ws.onclose must not fall back after the WS had carried data")


def test_eventsource_autoretry_is_disarmed():
    """EventSource auto-reconnects to cursor 0 without an id: field — close it."""
    assert "es.onerror = function () { try { es.close(); } catch (e) {} };" in JS


def test_mount_is_idempotent_and_disposes_the_previous_mount():
    """The shared root cause of double-print AND the iPad dual-input target."""
    assert "_disposeMount" in JS
    mount = JS.split("function _mountTerminal(", 1)[1][:2500]
    assert "_disposeMount(w);" in mount, "the re-entrant mount must dispose first"
    assert "DOCK.sessionId === sessionId" in mount, (
        "both homes (panel record + dock) must be disposed for one session")


def test_openpanel_closes_the_outgoing_transport_before_replacing_the_record():
    assert "_prevPanel" in JS
    idx = JS.find("PANELS[sessionId] = {el: panel")
    assert idx > 0
    before = JS[max(0, idx - 700):idx]
    assert "_prevPanel.transport.close()" in before, (
        "replacing PANELS[sessionId] must not orphan a live transport")


def test_sleep_resume_handlers_exist_and_are_guarded():
    """No visibilitychange/online/pageshow handling existed at all before."""
    for ev in ("visibilitychange", "online", "pageshow"):
        assert ev in JS, f"missing a {ev} resume handler"
    assert "_ensureTransport" in JS
    assert "_reconnecting" in JS, (
        "a wake-up burst must not be able to open two streams")


@pytest.mark.parametrize("marker", [
    "CURSOR RESUME", "IDEMPOTENT MOUNT", "LAPTOP SLEEP",
])
def test_the_fixes_explain_themselves_for_the_next_reader(marker):
    assert marker in JS

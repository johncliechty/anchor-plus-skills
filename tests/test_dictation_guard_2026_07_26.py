"""iPad dictation blow-up regression tests (2026-07-26 hardening, P0.3).

Symptom (docs/friction/2026-07-25-terminal-dictation.md:9): "each new dictated
sentence re-includes all prior dictated text -> exponential/cumulative blow-up",
which polluted real transcripts with hundreds of repeated loops.

Root cause is in vendored xterm 6.0.0: the hidden helper textarea is never
cleared after a composition commit, and its only anti-duplication guard
(_dataAlreadySent) is fed exclusively from a keyCode===229 keydown that iOS
dictation never sends. Every compositionend therefore re-emitted
value.substring(start) of an ever-growing buffer, and Anchor forwarded it
verbatim with no cap.

Fixed at Anchor's boundary (no vendor fork) + a server-side backstop.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JS = (REPO / "static" / "project-window.js").read_text(encoding="utf-8",
                                                       errors="replace")
CSS = (REPO / "static" / "project-window.css").read_text(encoding="utf-8",
                                                          errors="replace")
GUI = (REPO / "anchor_gui.py").read_text(encoding="utf-8", errors="replace")


def test_composition_is_tracked_on_the_helper_textarea():
    """Anchor had ZERO composition awareness before this fix."""
    assert ".xterm-helper-textarea" in JS, (
        "the guard must attach to xterm's real editable element")
    for ev in ("compositionstart", "compositionend", "beforeinput"):
        assert ev in JS, f"missing a {ev} listener"


def test_sends_are_suppressed_while_composing():
    """xterm's in-flight emissions ARE the cumulative buffer — drop them."""
    assert "_composing" in JS
    assert "if (_composing) {" in JS, (
        "term.onData must not forward while a composition is in flight")


def test_the_textarea_is_cleared_after_a_commit():
    """The load-bearing half: an uncleared textarea regrows the substring."""
    assert "_ta.value = ''" in JS, (
        "compositionend must clear the helper textarea or the blow-up returns")


def test_only_the_delta_is_sent_not_the_whole_buffer():
    """The defining bug: 'a', 'a b', 'a b c'. Only the tail may go."""
    assert "_sentPrefix" in JS
    assert "full.slice(_sentPrefix.length)" in JS, (
        "the commit must strip the already-sent prefix")


def test_insert_replacement_text_is_accounted_for():
    """iOS re-recognition commits with insertReplacementText; xterm drops it."""
    assert "insertReplacementText" in JS


def test_server_caps_the_conpty_input_turn():
    """The legacy REPL capped turns; this ConPTY path had NO guard at all."""
    assert "_term.MAX_TURN_CHARS" in GUI
    handler = GUI.split("def handle_term_input2", 1)[1].split("\ndef ", 1)[0]
    assert "MAX_TURN_CHARS" in handler, (
        "term_input2 must refuse an oversized turn before it reaches the PTY")
    assert "turn-too-large" in handler
    assert "413" in handler, "an oversized turn should answer 413"


def test_coarse_pointer_clients_get_a_real_caret_rect():
    """A 0x0 off-screen field pushes iOS into whole-field replacement."""
    assert "@media (pointer: coarse)" in CSS
    block = CSS.split("@media (pointer: coarse)", 1)[1]
    assert ".xterm-helper-textarea" in block
    assert "width: 1px" in block and "height: 1em" in block
    # Desktop must be untouched: the vendor rule still hides it by default.
    vendor = (REPO / "vendor" / "xterm" / "xterm.css").read_text(
        encoding="utf-8", errors="replace")
    assert "opacity: 0" in vendor


def test_the_fix_explains_itself_for_the_next_reader():
    assert "DICTATION GUARD" in JS
    assert "keyCode===229" in JS or "keyCode === 229" in JS, (
        "the comment must name the vendor mechanism so this is not 'fixed' away")

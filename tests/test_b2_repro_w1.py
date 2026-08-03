"""diag-B2 tile/resume inconsistencies — NON-SKIPPING reproductions (telemetry W1).

Repro-FIRST discipline: this suite REPRODUCES the three diag-B2 symptoms and
asserts the BUGGY behavior is PRESENT — no fixes land in W1 (they land in W6,
where the Playwright screenshot sign-off already runs). Root-cause chains are
recorded in ``planning/telemetry-resume-2026-07/intake/gap-closures-b2.md``.

W1-AMENDMENT MANDATE (John, 2026-07-11, "rework repros to not skip"): every test
here is PURE-PYTHON, DETERMINISTIC, and GREEN in the standard ``pytest tests/ -v``
gate. There is **NO** ``pytest.importorskip`` / ``pytest.skip`` / ``xfail`` /
``skipif`` anywhere in this module — the suite's skip/xfail marker count does NOT
rise and nothing is actually skipped. Any assertion that GENUINELY requires a
live browser / ConPTY (e.g. the visual blank pane, the WS attach race) is
DEFERRED to W6 and is NOT authored here as a skip-gated test.

Each symptom is classified state-bug (fixture-testable now) vs attach-race
(deferred to the W6 WS attach-ack change):

- S1 blank large-tile window   → STATE-BUG (two facets, both reproduced here):
  (a) the stale client liveness cache misfires on a server-dead session, and
  (b) the transport's ``unknown-session`` close writes ZERO bytes to the pane.
- S2 context-free blue restart → STATE-BUG: the blue "Continue" button POSTs
  ``continue_session`` immediately with no pre-click seed/context preview, and
  the dock title falls back to bare ``lane · skill`` because ``label`` defaults "".
- S3 dual undistinguished resume → STATE-BUG FACET (two structurally different
  resume mechanisms coexist: ``continue_session`` AUTO-SUBMITS its seed vs the
  v10 pending-paste path which does NOT) + ATTACH-RACE FACET (the pending-paste
  flush is gated on observing the greet marker and only evaluated on
  attach/read_since — an unmounted follow-on never checks; the fix rides the W6
  attach-ack change and is DEFERRED there, not authored here).
"""
import json
import os
import re
from pathlib import Path

import pytest  # noqa: F401  (imported for parity with the suite; NO skip/xfail used)

REPO = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "registry_state"

# Shipped sources the reproductions inspect (the byte-identical static mirror of
# the embedded project-window JS, plus the two backend modules).
JS = (REPO / "static" / "project-window.js").read_text(encoding="utf-8")
GUI = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
TS = (REPO / "terminal_session.py").read_text(encoding="utf-8")

SESSIONS = json.loads((FIXTURE_DIR / "sessions.json").read_text(encoding="utf-8"))


# ── Pure mirror of the shipped client liveness decision ─────────────────────
# static/project-window.js openEffortDock():
#     var live = !!MANAGED[sessionId] && status === 'running';
# `status` is read from the CLIENT cache (MANAGED[sid]), never re-verified
# server-side. This mirror is used to demonstrate the misfire over the captured
# fixture; the test below ALSO asserts the exact predicate is present in the
# SHIPPED JS, so the mirror can't drift from (or fabricate) the real decision.
def _client_live_decision(managed_cache, session_id):
    rec = managed_cache.get(session_id)
    if not rec:
        return False
    status = rec.get("status")
    return bool(rec) and status == "running"


# ──────────────────────────────────────────────────────────────────────────────
# S1 — blank large-tile window  (STATE-BUG)
# ──────────────────────────────────────────────────────────────────────────────
def test_s1_liveness_decision_is_client_cache_only():
    """The shipped liveness decision reads the client cache alone (bug present)."""
    assert "var live = !!MANAGED[sessionId] && status === 'running';" in JS


def test_s1_stale_cache_cannot_self_heal_no_periodic_or_visibility_repoll():
    """`repopulate()` never fires periodically or on tab refocus, so a session
    that dies server-side stays cached 'running' for as long as the tab sits open."""
    # No visibility-triggered re-poll at all.
    assert "visibilitychange" not in JS
    # `repopulate` is only ever scheduled one-shot (setTimeout after load/actions),
    # never on a repeating interval.
    assert re.search(r"setInterval\([^)]*repopulate", JS) is None
    assert "setTimeout(repopulate" in JS  # the one-shot, action-driven refresh only


def test_s1_stale_cache_misfires_on_server_dead_session():
    """Over the captured fixture: a session dead server-side but cached 'running'
    client-side makes the liveness decision return live=True (the misfire)."""
    sid = "sess-0006"  # server truth: reaped-orphan (reconciled dead)
    server_truth = SESSIONS[sid]
    assert server_truth["status"] != "running"  # the server knows it is dead
    # The tab was open when it died → the client MANAGED cache still says running.
    stale_client_cache = {sid: {"session_id": sid, "status": "running"}}
    assert _client_live_decision(stale_client_cache, sid) is True  # misfire reproduced


def test_s1_unknown_session_transport_writes_zero_bytes(tmp_path, monkeypatch):
    """The silent close: reading a dead/unknown session yields ok=False and NO
    output text (zero bytes to the pane) — reproduced against the real backend.

    Hermetic: ANCHOR_DATA_DIR → a tmp dir (never the build repo's real .anchor/
    store) and the stub PTY backend; the unknown id resolves to no record, so the
    result is deterministic regardless.
    """
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    import terminal_session
    out = terminal_session.read_since("sess-0006-no-live-pty", 0)
    assert out.get("ok") is False
    assert out.get("reason") == "unknown-session"
    assert "text" not in out  # zero bytes are ever produced for the pane


def test_s1_transport_handlers_close_silently_on_unknown_session():
    """Both PTY transports terminate WITHOUT sending an output frame on
    unknown-session (SSE emits a done/error event; WS just breaks) → blank pane."""
    # SSE fallback: on `not out.get("ok")` it emits a done/error event and returns,
    # never an "output" event carrying bytes.
    assert 'if not out.get("ok", True):  # unknown session' in GUI
    assert 'self._sse_event("done", {"status": "error",' in GUI
    # WS: on `not out.get("ok")` it breaks the pump with no sendall of a text frame.
    assert "break  # unknown session" in GUI


# ──────────────────────────────────────────────────────────────────────────────
# S2 — context-free blue restart button  (STATE-BUG)
# ──────────────────────────────────────────────────────────────────────────────
def test_s2_blue_continue_button_posts_immediately_with_no_preview():
    """`_mountReadOnlyBody` renders the blue Continue button whose click calls
    `continueSession` immediately — no pre-click preview of the resume seed."""
    # ASCII-safe substrings of the button (avoids the ▶ glyph byte-match fragility).
    assert 'class="ro-continue" type="button"' in JS
    assert "Continue in a live session</button>" in JS
    assert "continueSession(sessionId, s.lane);" in JS
    # continueSession POSTs continue_session IMMEDIATELY with an id-only payload —
    # no confirm/preview step and no seed text ever shown to the user first. The
    # actual resume context (`_build_continue_seed`'s doc list / phase) is
    # synthesized SERVER-SIDE, AFTER the click mints the session.
    assert "await _postJson('/api/rnd/continue_session', payload);" in JS
    assert "source_session: sessionId" in JS


def test_s2_dock_title_falls_back_to_bare_lane_skill():
    """The dock title falls back to `lane · skill` because `label` defaults ""
    in start_session and callers don't pass one → context-free title."""
    # ASCII-safe substring of the title fallback (avoids the · middot glyph).
    assert "(lane || 'effort')" in JS
    assert 'def start_session(project_id, lane, backend=_UNSET, label="",' in TS


# ──────────────────────────────────────────────────────────────────────────────
# S3 — dual undistinguished resume mechanisms  (STATE-BUG facet)
# ──────────────────────────────────────────────────────────────────────────────
def test_s3_continue_session_seed_is_auto_submitted(monkeypatch):
    """MECHANISM 1: `continue_session` folds the resume context into the lane seed,
    which is written to the PTY at start and ends with a newline → AUTO-SUBMITTED."""
    # Clear seed env overrides so we exercise the built-in fold path deterministically.
    for key in list(os.environ):
        if key.startswith("ANCHOR_SEED_PROMPT_") or key == "ANCHOR_TERMINAL_SEED":
            monkeypatch.delenv(key, raising=False)
    import terminal_session
    seed = terminal_session.seed_for_lane("research", seed_context="RESUME-CONTEXT-XYZ")
    assert seed is not None
    assert "RESUME-CONTEXT-XYZ" in seed
    assert seed.endswith("\n")  # trailing newline == one submitted turn (auto-submit)


def test_s3_pending_paste_mechanism_coexists_and_does_not_auto_submit():
    """MECHANISM 2 (structurally different): a v10 `paste_prompt` is recorded as
    `pending_paste` with paste_flushed=False and is NOT written at start — it is
    held UNSENT. Two undistinguished mechanisms coexist → the reported inconsistency."""
    assert 'pending = (paste_prompt or "")' in TS
    assert "sid, pending_paste=pending, paste_flushed=False)" in TS
    # It is delivered later, not at start, by _flush_pending_paste.
    assert "def _flush_pending_paste(session_id):" in TS


def test_s3_pending_paste_flush_gated_on_greet_marker_attach_race_facet():
    """The ATTACH-RACE facet (compounding bug), reproduced by source inspection:
    the pending-paste flush is gated on observing the greet marker and only runs on
    attach/read_since — a paraphrased/omitted greet leaves the paste pending forever
    and an unmounted follow-on never checks. The FIX rides the W6 attach-ack change
    and is DEFERRED there (not authored here as a skip)."""
    assert 'GREET_MARKER = "what would you like to do?"' in TS
    assert "marker = GREET_MARKER.lower()" in TS
    # The flush is wired into read_since (evaluated only when the pane reads).
    assert "_flush_pending_paste(session_id)" in TS

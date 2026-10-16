"""v11.1 Wave 1 FIX — keystone background summary dedup on a TERMINAL source.

THE REDUNDANCY (proven by ``tests/test_summary_on_finish_v7.py`` once the prod env
gate ``ANCHOR_PROACTIVE_SUMMARY=1`` is live): killing a planning session triggers
TWO summaries of the SAME session —

  (1) ``anchor_gui._trigger_session_summary_on_finish`` — the canonical
      "this session is done → summarize it" hook (the v7 finish hook); and
  (2) ``term_kill`` → ``auto_advance_planning_to_build`` →
      ``terminal_session.prepare_stage_handoff`` →
      ``_trigger_background_source_summary`` — the keystone's background summary of
      the SOURCE session being advanced FROM, which is the SAME (now DONE) session.

THE FIX (dedup at the root): ``_trigger_background_source_summary`` SKIPS when the
source session is already TERMINAL (DONE / FAILED). A terminal source is summarized
by its finish hook; the keystone summary's value is for a LIVE source being advanced
from (the normal research→plan advance + the v11.1 conversation-transcript case,
where the research source stays RUNNING). Best-effort: a status read failure falls
through to the prior behavior (fire).

These tests prove the dedup directly + hermetically: the gate FIRES for a RUNNING
source, SKIPS for a DONE / FAILED source, and falls THROUGH (fires) when the source
record cannot be resolved. The summarizer is fully stubbed — no PTY, no git, no
claude. ``ANCHOR_PROACTIVE_SUMMARY=1`` is set per-test via monkeypatch (auto-
restored), so the suite default stays OFF.
"""
import threading

import terminal_session as ts
import session_registry as reg


class _Imm:
    """Run the daemon body inline so the assertions are deterministic + hermetic."""

    def __init__(self, target=None, daemon=None):
        self._t = target

    def start(self):
        if self._t is not None:
            self._t()


def _wire(monkeypatch, source_status):
    """Stub the env-gate ON, the registry status of ``sid``, and the summarizer.

    Returns the ``captured`` dict; ``"session"`` is present iff the summarizer ran.
    """
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "1")
    monkeypatch.setattr(threading, "Thread", _Imm)

    # The source session's registry status drives the dedup gate.
    if source_status is None:
        monkeypatch.setattr(reg, "get_session", lambda sid: None, raising=True)
    else:
        monkeypatch.setattr(
            reg, "get_session",
            lambda sid: {"session_id": sid, "status": source_status},
            raising=True)

    import summarizer as _sm
    import effort_history as _eh
    monkeypatch.setattr(_eh, "_resolve_subdir", lambda lane: lane, raising=True)
    monkeypatch.setattr(
        _eh, "efforts_for_session_id",
        lambda *a, **k: [{"artifact_path": "research/sid-transcript.md"}],
        raising=True)
    monkeypatch.setattr(_sm, "load_cached", lambda *a, **k: None, raising=True)

    captured = {}

    def _fake_summarize(folder, project_id, lane, session):
        captured["session"] = session
        return {"ok": True}

    monkeypatch.setattr(_sm, "summarize_session", _fake_summarize, raising=True)
    return captured


def test_keystone_fires_for_running_source(monkeypatch):
    """The normal research→plan advance: the SOURCE is RUNNING, so the keystone
    background summary FIRES (it is the only trigger there — not regressed)."""
    captured = _wire(monkeypatch, reg.STATUS_RUNNING)
    ts._trigger_background_source_summary("/tmp/x", "pid", "research", "sid")
    assert "session" in captured, \
        "the keystone summary must fire for a RUNNING source (the live advance)"
    efforts = captured["session"]["efforts"]
    assert efforts and efforts[0]["artifact_path"] == "research/sid-transcript.md"


def test_keystone_skips_for_done_source(monkeypatch):
    """A killed/finished planning session that auto-advances: the SOURCE is DONE, so
    the keystone background summary is DEDUPED (the finish hook owns it)."""
    captured = _wire(monkeypatch, reg.STATUS_DONE)
    ts._trigger_background_source_summary("/tmp/x", "pid", "planning", "sid")
    assert "session" not in captured, \
        "the keystone summary must SKIP a terminal (DONE) source (finish hook owns it)"


def test_keystone_skips_for_failed_source(monkeypatch):
    """A FAILED source is terminal too → the keystone summary is deduped."""
    captured = _wire(monkeypatch, reg.STATUS_FAILED)
    ts._trigger_background_source_summary("/tmp/x", "pid", "planning", "sid")
    assert "session" not in captured, \
        "the keystone summary must SKIP a terminal (FAILED) source"


def test_keystone_fires_when_source_unresolvable(monkeypatch):
    """Best-effort: when the source record can't be resolved (get_session → None),
    the gate falls THROUGH to the prior behavior (fire) — it never blocks/raises."""
    captured = _wire(monkeypatch, None)
    ts._trigger_background_source_summary("/tmp/x", "pid", "research", "sid")
    assert "session" in captured, \
        "an unresolvable source must fall through to the prior behavior (fire)"


def test_keystone_fires_when_status_read_raises(monkeypatch):
    """A status-read FAILURE must not break the advance — fall through to fire."""
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "1")
    monkeypatch.setattr(threading, "Thread", _Imm)

    def _boom(sid):
        raise RuntimeError("registry read blew up")

    monkeypatch.setattr(reg, "get_session", _boom, raising=True)

    import summarizer as _sm
    import effort_history as _eh
    monkeypatch.setattr(_eh, "_resolve_subdir", lambda lane: lane, raising=True)
    monkeypatch.setattr(
        _eh, "efforts_for_session_id",
        lambda *a, **k: [{"artifact_path": "research/sid-transcript.md"}],
        raising=True)
    monkeypatch.setattr(_sm, "load_cached", lambda *a, **k: None, raising=True)
    captured = {}
    monkeypatch.setattr(
        _sm, "summarize_session",
        lambda f, p, l, s: captured.__setitem__("session", s) or {"ok": True},
        raising=True)

    ts._trigger_background_source_summary("/tmp/x", "pid", "research", "sid")
    assert "session" in captured, \
        "a status-read failure must fall through (fire), never break the advance"

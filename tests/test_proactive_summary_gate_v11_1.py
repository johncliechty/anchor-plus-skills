"""v11.1 Wave 1 FIX-3 — the background transcript-refine gate is wired in prod.

THE BUG Reviewer B found: ``terminal_session._trigger_background_source_summary``
(the keystone's background refine of the snapshotted transcript) gates on the ENV
var ``ANCHOR_PROACTIVE_SUMMARY`` — but ``anchor_gui.main()`` only set the module
FLAG ``_PROACTIVE_SUMMARY_ENABLED=True`` and NEVER exported the env var, so in the
live ``anchor`` service the refine NEVER ran. FIX: ``main()`` now also sets
``os.environ["ANCHOR_PROACTIVE_SUMMARY"] = "1"``.

These tests prove (a) the gate is a hard NO-OP when the env is OFF (the default in
tests/healthcheck — NO daemon thread, NO live claude) and (b) when the env is ON
(the prod state), the gate is NOT a no-op and refines the persisted transcript —
WITHOUT spawning a real model (the summarizer is stubbed). Plus a static check
that ``main()`` exports the env var.

Hermetic: the only "model" is a stubbed summarizer; no PTY, no git, no claude.
"""
import inspect
import threading
import types

import terminal_session as ts


def test_gate_is_noop_when_env_off(monkeypatch):
    """With ANCHOR_PROACTIVE_SUMMARY unset, the trigger spawns no thread and the
    summarizer is never touched (tests/healthcheck stay off-claude)."""
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)

    started = []
    real_thread = threading.Thread

    def _spy_thread(*a, **k):
        started.append((a, k))
        return real_thread(*a, **k)

    monkeypatch.setattr(threading, "Thread", _spy_thread)
    ts._trigger_background_source_summary("/tmp/x", "pid", "research", "sid")
    assert started == [], "a background thread was spawned while the gate is OFF"


def test_gate_fires_and_refines_when_env_on(monkeypatch):
    """With ANCHOR_PROACTIVE_SUMMARY=1 (the prod state), the trigger DOES run the
    summarize path — and it picks up the session's persisted efforts. The model is
    fully stubbed (no live claude); we run the daemon body synchronously."""
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "1")

    # Run the daemon body inline so the assertions are deterministic + hermetic.
    captured = {}

    class _Imm:
        def __init__(self, target=None, daemon=None):
            self._t = target

        def start(self):
            self._t()

    monkeypatch.setattr(threading, "Thread", _Imm)

    # Stub the summarizer + effort_history modules the lazy import resolves to.
    import summarizer as _sm
    import effort_history as _eh

    monkeypatch.setattr(_eh, "_resolve_subdir", lambda lane: lane, raising=True)
    monkeypatch.setattr(
        _eh, "efforts_for_session_id",
        lambda *a, **k: [{"artifact_path": "research/sid-transcript.md"}],
        raising=True)
    # No existing cache → not skipped.
    monkeypatch.setattr(_sm, "load_cached", lambda *a, **k: None, raising=True)

    def _fake_summarize(folder, project_id, lane, session):
        captured["session"] = session
        return {"ok": True}

    monkeypatch.setattr(_sm, "summarize_session", _fake_summarize, raising=True)

    ts._trigger_background_source_summary("/tmp/x", "pid", "research", "sid")

    assert "session" in captured, "the gate did NOT fire when the env is ON"
    # It tied the summary to the session's persisted transcript effort.
    efforts = captured["session"]["efforts"]
    assert efforts and efforts[0]["artifact_path"] == "research/sid-transcript.md"


def test_main_exports_the_proactive_env_var():
    """Static check: anchor_gui.main() sets ANCHOR_PROACTIVE_SUMMARY in the env
    (so the prod server actually enables the keystone's background refine).
    This is the SERVER path only — never imported/run in tests, so the suite
    keeps the env OFF."""
    import anchor_gui
    src = inspect.getsource(anchor_gui.main)
    assert 'os.environ["ANCHOR_PROACTIVE_SUMMARY"]' in src \
        or "os.environ['ANCHOR_PROACTIVE_SUMMARY']" in src, \
        "main() does not export ANCHOR_PROACTIVE_SUMMARY"

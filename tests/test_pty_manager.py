"""Wave 1 — PTY session manager (stub backend) acceptance.

Locks the v3 terminal substrate (MASTER-PLAN §D / Implementation-Plan Wave 1):
``pty_manager`` exposes start/write/read_since/resize/kill over a backend seam
with a deterministic in-memory **stub** backend. These tests run ONLY against
the stub (``ANCHOR_PTY_BACKEND=stub``) — NO real process, NO pywinpty, NO live
claude — so they are hermetic and fast.

The real pywinpty backend is exercised separately by ``spike_conpty_service.py``
(a runnable empirical spike), never by pytest.

Mirrors the fixture/reload/monkeypatch pattern of ``test_terminal_repl.py``.
"""
import importlib

import pytest


@pytest.fixture
def mgr(monkeypatch):
    """Reload pty_manager with the stub backend selected, hermetic per-test."""
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    import pty_manager
    importlib.reload(pty_manager)
    yield pty_manager
    pty_manager._reset_live_table_for_tests()


# ── backend selection honors the env override ────────────────────────────────

def test_backend_selection_honors_stub_env(mgr):
    backend = mgr.select_backend()
    assert backend.name == mgr.STUB_BACKEND
    assert isinstance(backend, mgr.StubBackend)


# ── start → write → read_since round-trips echoed bytes ──────────────────────

def test_start_write_read_round_trips_echoed_bytes(mgr):
    sid = mgr.start("cmd.exe")
    assert isinstance(sid, str) and sid
    # Nothing produced yet.
    out0 = mgr.read_since(sid, 0)
    assert out0["text"] == ""
    assert out0["status"] == "running"
    # The stub child echoes written bytes into its readable output.
    mgr.write(sid, "hello world")
    out1 = mgr.read_since(sid, out0["next"])
    assert out1["text"] == "hello world"


def test_write_accepts_bytes(mgr):
    sid = mgr.start("cmd.exe")
    mgr.write(sid, b"bytes-in")
    out = mgr.read_since(sid, 0)
    assert out["text"] == "bytes-in"


# ── cursor advances: a second read returns nothing new ───────────────────────

def test_cursor_advances_second_read_is_empty(mgr):
    sid = mgr.start("cmd.exe")
    mgr.write(sid, "abc")
    out1 = mgr.read_since(sid, 0)
    assert out1["text"] == "abc"
    out2 = mgr.read_since(sid, out1["next"])
    assert out2["text"] == ""
    assert out2["next"] == out1["next"]
    # A further write is picked up from the advanced cursor only.
    mgr.write(sid, "def")
    out3 = mgr.read_since(sid, out2["next"])
    assert out3["text"] == "def"


# ── resize updates dimensions ────────────────────────────────────────────────

def test_resize_updates_dimensions(mgr):
    sid = mgr.start("cmd.exe")
    mgr.resize(sid, 120, 40)
    child = mgr._get(sid)
    assert child.cols == 120
    assert child.rows == 40


# ── kill reaps: a killed session is dead / not in the live table ─────────────

def test_kill_reaps_and_removes_from_live_table(mgr):
    sid = mgr.start("cmd.exe")
    assert sid in mgr.live_sessions()
    mgr.kill(sid)
    assert sid not in mgr.live_sessions()
    # Subsequent manager calls on the killed id raise UnknownSession.
    with pytest.raises(mgr.UnknownSession):
        mgr.read_since(sid, 0)


def test_session_stays_alive_until_kill(mgr):
    sid = mgr.start("cmd.exe")
    child = mgr._get(sid)
    assert child.is_alive() is True
    mgr.write(sid, "still here")
    assert child.is_alive() is True
    mgr.kill(sid)
    assert child.is_alive() is False
    assert child.reaped is True


# ── unknown-session calls raise ──────────────────────────────────────────────

def test_unknown_session_calls_raise(mgr):
    with pytest.raises(mgr.UnknownSession):
        mgr.write("no-such-session", "x")
    with pytest.raises(mgr.UnknownSession):
        mgr.read_since("no-such-session", 0)
    with pytest.raises(mgr.UnknownSession):
        mgr.resize("no-such-session", 80, 24)
    with pytest.raises(mgr.UnknownSession):
        mgr.kill("no-such-session")
    # UnknownSession is a KeyError subclass (clear error contract).
    assert issubclass(mgr.UnknownSession, KeyError)


# ── multiple independent sessions don't cross-contaminate ────────────────────

def test_multiple_sessions_are_independent(mgr):
    a = mgr.start("cmd.exe")
    b = mgr.start("cmd.exe")
    assert a != b
    mgr.write(a, "AAA")
    mgr.write(b, "BBB")
    assert mgr.read_since(a, 0)["text"] == "AAA"
    assert mgr.read_since(b, 0)["text"] == "BBB"
    mgr.kill(a)
    # b is unaffected by killing a.
    assert b in mgr.live_sessions()
    assert mgr.read_since(b, 0)["text"] == "BBB"


# ── output buffer is bounded; cursor stays absolute across the drop boundary ──

def test_output_buffer_is_bounded_preserving_absolute_cursor(mgr, monkeypatch):
    # Shrink the cap so the test is fast and the drop path is exercised.
    monkeypatch.setattr(mgr, "MAX_BUFFER_CHARS", 1000)
    sid = mgr.start("cmd.exe")
    # Write well past the cap (8000 > 1000).
    for _ in range(8):
        mgr.write(sid, "x" * 1000)

    child = mgr._get(sid)
    # Retained tail window stays bounded by the cap.
    assert len(child._buf) <= mgr.MAX_BUFFER_CHARS
    # The cumulative total reflects everything ever produced.
    assert child._total == 8000

    # read_since(0) serves only the retained tail (not all 8000 chars), and
    # advances the cursor to the TRUE absolute total.
    out = mgr.read_since(sid, 0)
    assert 0 < len(out["text"]) <= mgr.MAX_BUFFER_CHARS
    assert len(out["text"]) < child._total
    assert out["next"] == 8000

    # A follow-up read from the returned absolute cursor is empty.
    out2 = mgr.read_since(sid, out["next"])
    assert out2["text"] == ""
    assert out2["next"] == 8000

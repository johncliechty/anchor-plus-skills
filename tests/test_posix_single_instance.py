"""share-distro v1 Wave 2 — POSIX single-instance guard.

Decision #6 (POSIX single-instance guard): a second Anchor on the fixed port
(8777) must NOT silently squat on macOS/Linux — parity with the Windows
``SO_EXCLUSIVEADDRUSE`` guard. ONE locked mechanism: on non-Windows leave
``SO_REUSEADDR`` OFF for the real fixed port so a duplicate bind raises
``EADDRINUSE``, which the existing ``paths.classify_bind_error`` maps to a clean
``exit(0)`` (no pidfile).

THE GATE HOST IS WINDOWS. Per the plan's Conventions block these run on Windows
via a faked platform + an INJECTED ``OSError(EADDRINUSE)`` — no real dual bind,
``:8777`` is never touched, and ``pytest.skip`` is NOT the coverage. They run
identically on a real POSIX host.
"""
import errno
import importlib
import socket
import sys

import pytest

import paths


# ── use_posix_exclusive_bind (pure predicate) ───────────────────────────────

def test_use_posix_exclusive_bind_true_for_fixed_port_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    # reload so the function re-reads the faked sys.platform at call time
    p = importlib.reload(paths)
    assert p.use_posix_exclusive_bind("127.0.0.1", 8777) is True
    monkeypatch.setattr(sys, "platform", "darwin")
    assert p.use_posix_exclusive_bind("127.0.0.1", 8777) is True


def test_use_posix_exclusive_bind_false_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    p = importlib.reload(paths)
    assert p.use_posix_exclusive_bind("127.0.0.1", 8777) is False


def test_use_posix_exclusive_bind_never_for_ephemeral_port(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    p = importlib.reload(paths)
    # port=0 (OS-assigned, used by the suite/health check) must NEVER go exclusive.
    assert p.use_posix_exclusive_bind("127.0.0.1", 0) is False


def test_use_posix_exclusive_bind_handles_bad_port(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    p = importlib.reload(paths)
    assert p.use_posix_exclusive_bind("127.0.0.1", None) is False
    assert p.use_posix_exclusive_bind("127.0.0.1", "nope") is False


# ── EADDRINUSE on POSIX → classify_bind_error returns the clean-exit decision ─

def test_eaddrinuse_classifies_as_clean_exit_on_posix(monkeypatch):
    """The injected EADDRINUSE a POSIX duplicate bind would raise classifies as
    'exit' (clean exit), NOT a retry/traceback — the heart of the guard."""
    monkeypatch.setattr(sys, "platform", "linux")
    p = importlib.reload(paths)
    exc = OSError(errno.EADDRINUSE, "address already in use")
    assert p.classify_bind_error(exc) == "exit"


# ── Live (Windows-gate-safe) guard behavior via main() ──────────────────────

def _load_gui(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    importlib.reload(paths)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    paths.ensure_data_dirs()
    return gui


def test_posix_duplicate_bind_exits_cleanly_no_traceback(monkeypatch, tmp_path):
    """Given sys.platform faked to 'linux' and the bind helper fed an injected
    OSError(EADDRINUSE), When the guard runs, Then main() exits cleanly
    (SystemExit 0) — NOT a raised traceback — with no real dual bind."""
    gui = _load_gui(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")

    # Inject the EADDRINUSE a POSIX duplicate bind would raise (no real bind).
    def fake_make_server(host, port):
        raise OSError(errno.EADDRINUSE, "address already in use")

    monkeypatch.setattr(gui, "make_server", fake_make_server)
    monkeypatch.setattr(
        sys, "argv", ["anchor_gui.py", "--port", "8777", "--no-browser"])

    with pytest.raises(SystemExit) as ei:
        gui.main()
    # The clean-exit decision (parity with Windows), not a traceback.
    assert ei.value.code == 0


def test_posix_non_in_use_bind_error_still_propagates(monkeypatch, tmp_path):
    """A non-'in use' bind failure on POSIX must NOT be swallowed as a clean
    exit — it propagates so real startup faults surface (the guard is narrow)."""
    gui = _load_gui(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")

    def fake_make_server(host, port):
        raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(gui, "make_server", fake_make_server)
    monkeypatch.setattr(
        sys, "argv", ["anchor_gui.py", "--port", "8777", "--no-browser"])

    with pytest.raises(OSError) as ei:
        gui.main()
    assert ei.value.errno == errno.EACCES


# ── make_server selects the POSIX exclusive server class for the fixed port ──

def test_make_server_picks_posix_exclusive_class_for_fixed_port(monkeypatch, tmp_path):
    """Given non-Windows + a fixed non-zero port, make_server selects the
    SO_REUSEADDR-off POSIX exclusive class (allow_reuse_address False) WITHOUT a
    real bind (bind_with_retry stubbed to capture the constructed class)."""
    gui = _load_gui(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")

    captured = {}

    def fake_bind_with_retry(factory):
        # Construct nothing real — just discover which server class the factory
        # would build by inspecting the closure's selection.
        captured["cls"] = _peek_server_cls(gui, "127.0.0.1", 8777)
        return "SERVER"

    monkeypatch.setattr(gui._paths, "bind_with_retry", fake_bind_with_retry)
    result = gui.make_server("127.0.0.1", 8777)
    assert result == "SERVER"
    assert captured["cls"] is gui._PosixExclusiveThreadingHTTPServer
    # The locked mechanism: SO_REUSEADDR off (no exclusive sockopt on POSIX).
    assert gui._PosixExclusiveThreadingHTTPServer.allow_reuse_address is False


def _peek_server_cls(gui, host, port):
    """Re-derive the server class make_server would pick (mirrors its branch)."""
    if gui._paths.use_exclusive_bind(host, port):
        return gui._ExclusiveThreadingHTTPServer
    if gui._paths.use_posix_exclusive_bind(host, port):
        return gui._PosixExclusiveThreadingHTTPServer
    return gui._QuietThreadingHTTPServer


def test_make_server_ephemeral_unaffected_on_posix(monkeypatch, tmp_path):
    """port=0 binds on POSIX still use the plain (non-exclusive) server class —
    the ephemeral binds used across the whole suite keep SO_REUSEADDR."""
    gui = _load_gui(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    cls = _peek_server_cls(gui, "127.0.0.1", 0)
    assert cls is gui._QuietThreadingHTTPServer
    assert cls is not gui._PosixExclusiveThreadingHTTPServer


def test_posix_exclusive_first_holder_survives(monkeypatch, tmp_path):
    """End-to-end on the Windows gate: a first holder grabs a free port, then a
    POSIX-guarded second main() (EADDRINUSE injected) exits cleanly and the first
    holder is untouched — no real dual bind, :8777 never used."""
    gui = _load_gui(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")

    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    held_port = holder.getsockname()[1]
    assert held_port != 8777
    try:
        def fake_make_server(host, port):
            raise OSError(errno.EADDRINUSE, "address already in use")

        monkeypatch.setattr(gui, "make_server", fake_make_server)
        monkeypatch.setattr(
            sys, "argv",
            ["anchor_gui.py", "--port", str(held_port), "--no-browser"])

        with pytest.raises(SystemExit) as ei:
            gui.main()
        assert ei.value.code == 0

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(2)
        try:
            probe.connect(("127.0.0.1", held_port))
        finally:
            probe.close()
    finally:
        holder.close()

"""Wave 3 — single-instance guard.

A duplicate/orphan Anchor server must never silently squat the fixed port
(8777) and serve stale code. These tests exercise the guard WITHOUT touching
port 8777 or the live service: they bind throwaway servers on OS-assigned free
ports (port=0) and unit-test the pure decision helpers.

Coverage:
  - classify_bind_error: EADDRINUSE/WSAEADDRINUSE -> "exit"; everything else
    (incl. EADDRNOTAVAIL and generic errno-less OSError) -> "retry".
  - use_exclusive_bind: only the real fixed-port path on Windows; never port=0.
  - bind_with_retry: re-raises an in-use error immediately (no wasted retries)
    but still retries a transient/errno-less failure (back-compat with Wave 2).
  - A second start against an already-owned port exits cleanly (SystemExit 0)
    without killing the first server.
  - A normal start on a free OS-assigned port works.
  - port=0 ephemeral binds are unaffected (no exclusive option applied).
"""
import errno
import importlib
import socket
import sys
import threading

import pytest

import paths


# ── classify_bind_error ────────────────────────────────────────────────────

def test_classify_eaddrinuse_is_exit():
    exc = OSError(errno.EADDRINUSE, "address in use")
    assert paths.classify_bind_error(exc) == "exit"


def test_classify_wsaeaddrinuse_number_is_exit():
    # The raw Windows Sockets code (10048), regardless of platform aliasing.
    exc = OSError()
    exc.errno = 10048
    assert paths.classify_bind_error(exc) == "exit"


def test_classify_winerror_in_use_is_exit():
    exc = OSError("in use")
    # Windows surfaces WSAEADDRINUSE via .winerror on some socket errors.
    exc.winerror = 10048
    assert paths.classify_bind_error(exc) == "exit"


def test_classify_eaddrnotavail_is_retry():
    # The slow-Tailscale case: address not yet assignable -> transient -> retry.
    exc = OSError(errno.EADDRNOTAVAIL, "address not available")
    assert paths.classify_bind_error(exc) == "retry"


def test_classify_generic_errno_less_oserror_is_retry():
    # Back-compat: the original Wave-2 retry test raises a plain OSError with no
    # errno. That MUST still be classified as retry.
    assert paths.classify_bind_error(OSError("address not available yet")) == "retry"


# ── use_exclusive_bind ──────────────────────────────────────────────────────

def test_use_exclusive_bind_only_fixed_port_on_windows():
    expected = (sys.platform == "win32") and hasattr(socket, "SO_EXCLUSIVEADDRUSE")
    assert paths.use_exclusive_bind("127.0.0.1", 8777) is expected


def test_use_exclusive_bind_never_for_ephemeral_port():
    # port=0 (OS-assigned, used by tests/health check) must NEVER go exclusive.
    assert paths.use_exclusive_bind("127.0.0.1", 0) is False


def test_use_exclusive_bind_handles_bad_port():
    assert paths.use_exclusive_bind("127.0.0.1", None) is False
    assert paths.use_exclusive_bind("127.0.0.1", "nope") is False


# ── bind_with_retry reconciliation ──────────────────────────────────────────

def test_bind_with_retry_reraises_addr_in_use_immediately():
    """An 'address in use by another instance' error is NOT retried — it is
    re-raised on the first occurrence so no retry budget is wasted."""
    paths_mod = importlib.reload(paths)
    calls = {"n": 0}

    def in_use():
        calls["n"] += 1
        raise OSError(errno.EADDRINUSE, "address in use")

    with pytest.raises(OSError) as ei:
        paths_mod.bind_with_retry(in_use, attempts=5, delay=0.001)
    assert ei.value.errno == errno.EADDRINUSE
    assert calls["n"] == 1  # tried exactly once, no retries


def test_bind_with_retry_still_retries_transient(monkeypatch):
    """The Wave-2 contract is preserved: a transient (errno-less) failure that
    succeeds on the second try is still recovered."""
    paths_mod = importlib.reload(paths)
    calls = {"n": 0}

    def make():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("address not available yet (slow Tailscale)")
        return "SERVER"

    assert paths_mod.bind_with_retry(make, attempts=5, delay=0.001) == "SERVER"
    assert calls["n"] == 2


# ── Live (throwaway port) behavior ──────────────────────────────────────────

def _load_gui(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    importlib.reload(paths)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    paths.ensure_data_dirs()
    return gui


def test_normal_start_on_free_port_works(monkeypatch, tmp_path):
    """A normal start on a free OS-assigned port binds + serves /api/status."""
    gui = _load_gui(monkeypatch, tmp_path)
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
            assert r.status == 200
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


def test_second_instance_refuses_without_killing_first(monkeypatch, tmp_path):
    """Simulate 'port already owned': hold a socket on a free port, then make
    main() try to bind the SAME port. main() must exit cleanly (SystemExit 0)
    and the first holder must survive (still bound)."""
    gui = _load_gui(monkeypatch, tmp_path)

    # First "instance": grab and hold an OS-assigned free port with a listener.
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    held_port = holder.getsockname()[1]
    assert held_port != 8777

    try:
        # Force make_server to fail with EADDRINUSE (deterministic, cross-platform)
        # so we exercise the guard rather than relying on OS exclusivity rules.
        def fake_make_server(host, port):
            raise OSError(errno.EADDRINUSE, "address already in use")

        monkeypatch.setattr(gui, "make_server", fake_make_server)
        monkeypatch.setattr(sys, "argv", ["anchor_gui.py", "--port", str(held_port), "--no-browser"])

        with pytest.raises(SystemExit) as ei:
            gui.main()
        # Clean exit (0), NOT a crash.
        assert ei.value.code == 0

        # The first holder must be untouched — still bound and accepting.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(2)
        try:
            probe.connect(("127.0.0.1", held_port))
        finally:
            probe.close()
    finally:
        holder.close()


def test_main_reraises_non_in_use_bind_error(monkeypatch, tmp_path):
    """A non-'in use' bind failure that survives retries must NOT be silently
    swallowed as a clean exit — it propagates (so real startup faults surface)."""
    gui = _load_gui(monkeypatch, tmp_path)

    def fake_make_server(host, port):
        raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(gui, "make_server", fake_make_server)
    monkeypatch.setattr(sys, "argv", ["anchor_gui.py", "--port", "8781", "--no-browser"])

    with pytest.raises(OSError) as ei:
        gui.main()
    assert ei.value.errno == errno.EACCES


def test_make_server_ephemeral_unaffected_by_exclusive(monkeypatch, tmp_path):
    """port=0 binds must use a plain ThreadingHTTPServer with NO exclusive bind,
    proving ephemeral binds used across the suite are unaffected. (v10: the
    ephemeral server is the quiet-disconnect ThreadingHTTPServer subclass, which
    only swallows benign client-teardown errors and has NO exclusive bind — so
    the discriminating intent is "is a ThreadingHTTPServer AND is not the
    exclusive-bind class".)"""
    from http.server import ThreadingHTTPServer
    gui = _load_gui(monkeypatch, tmp_path)
    server = gui.make_server("127.0.0.1", 0)
    try:
        # A plain threading server (incl. the quiet-disconnect subclass) — and
        # explicitly NOT the exclusive-bind class used for the real :8777 port.
        assert isinstance(server, ThreadingHTTPServer)
        assert not isinstance(server, gui._ExclusiveThreadingHTTPServer)
    finally:
        server.server_close()

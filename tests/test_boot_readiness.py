"""STUB GATE — boot readiness (Anchor Doctor fix, 2026-09-03).

The 5 AM health check reported ``[HTTP endpoints] 0/7 passed; GET /: timed
out (20.0s); … WinError 10061 actively refused`` on 13 of the 18 nights before
this fix. Root cause (reproduced): ``anchor_gui.main()`` bound AND listened its
port ~0.5s into boot, then ran the boot reconcile (registry PID probes,
worktree reap, daemons — 80s+ under 5 AM load) BEFORE ``serve_forever``. Every
connect in that window queued into socketserver's 5-slot backlog that nobody
drained; the health check's probes hung 20s each until the backlog was full,
after which Windows RST'd every further connect (10061) until serving began.

The fix: bind early (the single-instance guard must still fire before any
boot work touches shared state) but ``listen()`` only when ready — a connect
during boot is refused (POSIX) or dropped (Windows), never queued — with the
backlog raised to 64,
and the health check waiting for a REAL HTTP answer with a realistic deadline.
"""
import inspect
import socket
import threading
import urllib.request

import pytest

import anchor_gui as gui
import paths as _paths


def _connect(port, timeout=0.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return "ok"
    except ConnectionRefusedError:
        return "refused"
    except socket.timeout:
        return "timeout"
    except OSError as e:
        return "refused" if getattr(e, "winerror", None) == 10061 else f"err:{e}"
    finally:
        s.close()


def _free_fixed_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def test_bind_only_refuses_until_activated_then_serves():
    srv = gui.make_server("127.0.0.1", 0, activate=False)
    try:
        port = srv.server_address[1]
        assert port > 0, "activate=False must still BIND (claim the port)"
        # Not listening yet → the connect is NEVER accepted/queued. POSIX
        # refuses it (RST); Windows silently drops the SYN to a bound-but-
        # unlistened port, so the client sees a connect timeout instead.
        assert _connect(port) in ("refused", "timeout")
        srv.server_activate()
        assert _connect(port) == "ok"
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/version", timeout=5) as r:
                assert r.status == 200
        finally:
            srv.shutdown()
    finally:
        srv.server_close()


def test_default_make_server_still_binds_and_listens():
    # Tests / the health check keep the historical bind+listen construction.
    srv = gui.make_server("127.0.0.1", 0)
    try:
        assert _connect(srv.server_address[1]) == "ok"
    finally:
        srv.server_close()


def test_single_instance_guard_fires_while_still_unactivated():
    # A duplicate's bind must fail even though the owner has not listen()ed
    # yet — the guard is a BIND-time property, so deferring listen keeps it.
    port = _free_fixed_port()
    first = gui.make_server("127.0.0.1", port, activate=False)
    try:
        with pytest.raises(OSError) as ei:
            gui.make_server("127.0.0.1", port, activate=False)
        assert _paths.classify_bind_error(ei.value) == "exit"
    finally:
        first.server_close()


def test_backlog_raised_on_every_server_class():
    for cls in (gui._ExclusiveThreadingHTTPServer,
                gui._PosixExclusiveThreadingHTTPServer,
                gui._QuietThreadingHTTPServer):
        assert cls.request_queue_size >= 64, cls.__name__


def test_main_binds_early_and_listens_only_when_ready():
    src = inspect.getsource(gui.main)
    assert "make_server(bind_host, port, activate=False)" in src
    # Match the CALLS (line-start), not the prose that mentions them.
    i_activate = src.index("\n    server.server_activate()\n")
    i_serve = src.index("\n        server.serve_forever()\n")
    assert i_activate < i_serve
    # Every boot-reconcile step must run BEFORE the listen.
    for marker in ("reconcile_on_startup", "worktrees.reap_orphans",
                   "start_autosave_daemon", "zombie_hunter.start_hunter"):
        assert src.index(marker) < i_activate, marker


def test_healthcheck_waits_for_real_http_readiness():
    import anchor_healthcheck as hc
    assert hc.SERVER_READY_TIMEOUT >= 120
    assert hc.SERVER_READY_WARN < hc.SERVER_READY_TIMEOUT
    src = inspect.getsource(hc.check_server_and_endpoints)
    assert "_http_ready(TEST_PORT)" in src
    assert "_port_in_use(TEST_PORT):\n            booted" not in src
    # Timing is a WARN, never red (locked severity rule).
    assert 'report.warn("server boot speed"' in src


def test_http_ready_probe_tracks_real_readiness():
    import anchor_healthcheck as hc
    srv = gui.make_server("127.0.0.1", 0, activate=False)
    port = srv.server_address[1]
    try:
        assert hc._http_ready(port, timeout=1.0) is False
        srv.server_activate()
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            assert hc._http_ready(port, timeout=5.0) is True
        finally:
            srv.shutdown()
    finally:
        srv.server_close()

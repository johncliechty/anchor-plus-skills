"""Wave 4 — job_runner launch + durable log + long-poll tail.

AC1: mock runner emits N lines then exits → durable log captures N lines and the
     job record holds {job_id, lane, pid, status, log_path}.
AC2: a running job long-polled with ?since=K returns lines after K within the
     (injected, small) ceiling, and a client disconnect does NOT crash the
     handler thread.

NO live ``claude`` is ever invoked — everything goes through ANCHOR_RUNNER_CMD →
tests/fake_claude.py.
"""
import importlib
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # Point the indirection at the deterministic mock — never live claude.
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    yield job_runner
    job_runner._reset_live_table_for_tests()


def test_ac1_launch_captures_n_lines_and_record(runner):
    rec = runner.launch("research", extra_args=["--lines", "5", "--exit-code", "0"])
    # Record shape (AC1 mandated fields).
    for field in ("job_id", "lane", "pid", "status", "log_path"):
        assert field in rec, f"missing record field {field}"
    assert rec["lane"] == "research"
    assert isinstance(rec["pid"], int)

    final = runner.wait(rec["job_id"], timeout=30)
    assert final["status"] == runner.STATUS_DONE
    assert final["exit_code"] == 0

    # Durable log captured exactly N lines.
    lines = runner._lines_from_log(rec["job_id"])
    assert lines == [f"fake-line {i}" for i in range(5)]
    # And the persisted log file actually exists on disk under ANCHOR_DATA_DIR.
    assert Path(final["log_path"]).exists()


def test_ac1_nonzero_exit_marks_failed(runner):
    rec = runner.launch("plan", extra_args=["--lines", "2", "--exit-code", "3"])
    final = runner.wait(rec["job_id"], timeout=30)
    assert final["status"] == runner.STATUS_FAILED
    assert final["exit_code"] == 3
    assert runner._lines_from_log(rec["job_id"]) == ["fake-line 0", "fake-line 1"]


def test_ac2_longpoll_returns_lines_after_since(runner):
    # Emit a few lines then sleep so the job stays "running" while we poll.
    rec = runner.launch("build", extra_args=["--lines", "4", "--sleep", "1.0"])
    jid = rec["job_id"]

    # Wait until at least 2 lines are present, then long-poll from since=2.
    deadline = time.monotonic() + 10
    while len(runner.all_lines(jid)) < 4 and time.monotonic() < deadline:
        time.sleep(0.02)

    # Long-poll from K=2 with a SMALL injected ceiling (not 25s).
    out = runner.long_poll(jid, since=2, ceiling=2.0, poll_interval=0.02)
    assert out["lines"] == ["fake-line 2", "fake-line 3"]
    assert out["next"] == 4
    runner.wait(jid, timeout=30)


def test_ac2_longpoll_blocks_then_delivers(runner):
    # Slow drip: a brief sleep so a poll starting at the tail must wait for more.
    rec = runner.launch("research", extra_args=["--lines", "3", "--sleep", "0.4"])
    jid = rec["job_id"]
    # Poll from the very start; should get the 3 lines within the small ceiling.
    out = runner.long_poll(jid, since=0, ceiling=3.0, poll_interval=0.02)
    assert "fake-line 0" in out["lines"]
    runner.wait(jid, timeout=30)


def test_ac2_client_disconnect_does_not_crash_handler(runner):
    """Wire long_poll behind a minimal ThreadingHTTPServer handler and abort the
    client mid-request. The handler thread must swallow the broken-pipe and not
    crash (no leaked exception escaping the thread)."""
    rec = runner.launch("build", extra_args=["--lines", "2", "--sleep", "2.0"])
    jid = rec["job_id"]

    crashes = []

    jr = runner

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            since = int(q.get("since", ["0"])[0])
            try:
                out = jr.long_poll(jid, since=since, ceiling=3.0,
                                   poll_interval=0.02)
                payload = ("\n".join(out["lines"])).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                # Simulate slow write; client may have already gone away.
                self.wfile.write(payload)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # EXPECTED on client disconnect — swallow, do NOT crash thread.
                pass
            except Exception as e:  # pragma: no cover - guard for the test
                crashes.append(repr(e))

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        # Open a raw socket, send a request, then close immediately to force a
        # client-side disconnect while the handler is mid long-poll.
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(b"GET /?since=0 HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        time.sleep(0.1)
        s.close()  # abrupt disconnect

        # A normal client should still be served fine afterwards (server alive).
        with urlopen(f"http://127.0.0.1:{port}/?since=0", timeout=5) as r:
            body = r.read().decode("utf-8")
        assert "fake-line 0" in body or body == ""  # lines may still be arriving
    finally:
        srv.shutdown()
        srv.server_close()
        runner.wait(jid, timeout=30)

    assert crashes == [], f"handler thread crashed: {crashes}"

"""W5 of the night of 2026-10-09: the restart drain fails closed. Every case runs against a stub server on a free
port, never :8777. The first install runs THIS helper against the OLD service, which answers drain-all only inside a
valid project and effort (it rejected {} with "unknown project") - so the helper sends one, and the old handler parks
every engine of the service."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import pre_restart_drain as drain  # noqa: E402

TOKEN = "t0k"
TARGET = {"pid": "p1", "dir": "Effort One"}


def _serve(mode):
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            seen.append({"path": self.path, "body": body, "token": self.headers.get("X-Anchor-Token")})
            if self.headers.get("X-Anchor-Token") != TOKEN:
                return self._send(401, {"ok": False, "error": "unauthorized"})
            if mode == "old":            # the service before W5: a project and an effort, or "unknown project"
                if body.get("pid") != "p1":
                    return self._send(404, {"ok": False, "error": "unknown project"})
                if body.get("dir") != "Effort One":
                    return self._send(404, {"ok": False, "error": "unknown effort"})
                return self._send(200, {"parked": ["a", "b"], "idle": ["c"], "errors": [], "ok": True})
            if mode == "new":
                return self._send(200, {"parked": ["a"], "idle": [], "errors": [], "ok": True})
            if mode == "malformed":
                return self._send(200, {"ok": True})
            if mode == "partial":
                return self._send(200, {"parked": ["a"], "idle": [], "errors": ["b: RuntimeError: stuck"], "ok": False})
            if mode == "html":
                self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
                self.wfile.write(b"<html>login</html>")

        def _send(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    assert srv.server_address[1] != 8777
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1], seen


def _run(mode, token=TOKEN, target=TARGET):
    srv, url, seen = _serve(mode)
    try:
        return drain.service_drain(url=url, token=token, target=target, timeout=5), seen
    finally:
        srv.shutdown()


def test_the_old_service_parks_every_engine_through_the_legacy_request():
    out, seen = _run("old")
    assert out["note"] is None and out["parked"] == ["a", "b"] and out["idle"] == ["c"]
    assert seen[0]["body"] == TARGET and "pid=p1" in seen[0]["path"]


def test_the_old_service_rejects_an_empty_body_and_that_fails_closed():
    out, _ = _run("old", target={})
    assert out["note"] and "404" in out["note"]


def test_the_new_service_answers_the_same_request():
    out, _ = _run("new")
    assert out["note"] is None and out["parked"] == ["a"]


def test_a_401_fails_closed_and_says_so():
    out, _ = _run("new", token="wrong")
    assert out["note"] and "401" in out["note"]


def test_a_malformed_answer_fails_closed():
    for mode in ("malformed", "html"):
        out, _ = _run(mode)
        assert out["note"] and "not" in out["note"], mode


def test_a_partial_park_fails_closed():
    out, _ = _run("partial")
    assert out["note"] and "failed to park" in out["note"]


def test_an_unreachable_service_fails_closed():
    out = drain.service_drain(url="http://127.0.0.1:9", token=TOKEN, target=TARGET, timeout=2)
    assert out["note"] and "unreachable" in out["note"]


def test_the_drain_report_and_exit_code_follow_the_service(monkeypatch):
    monkeypatch.setattr(drain, "_live_pty_records", lambda project_id=None: [])
    monkeypatch.setattr(drain, "service_drain", lambda: {"mode": "http", "parked": [], "idle": [], "errors": [],
                                                         "note": "cockpit drain HTTP 404: engines NOT parked"})
    rep = drain.drain()
    assert rep["ok"] is False
    assert drain.main([]) == 1
    monkeypatch.setattr(drain, "service_drain", lambda: {"mode": "http", "parked": ["a"], "idle": [], "errors": [], "note": None})
    assert drain.drain()["ok"] is True and drain.main([]) == 0


def test_drain_all_is_dispatched_with_no_project_and_no_effort():
    src = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert 'if verb == "drain-all":         # W5 (2026-10-09)' in src and "obj, code = _scr.drain_all()" in src
    from steward_cockpit import steward_routes
    rep, code = steward_routes.drain_all()
    assert code == 200 and set(rep) >= {"parked", "idle", "errors", "ok"}


def test_the_restart_script_fails_closed_and_reads_the_service_token():
    ps = (ROOT / "restart_anchor.ps1").read_text(encoding="utf-8")
    assert "fail-open" not in ps.split("# Idempotent")[1]
    assert "AppEnvironmentExtra" in ps and "ANCHOR_TOKEN=" in ps
    assert "RESULT: RESTART STOPPED BEFORE ANY CHANGE" in ps and "param([switch]$Cold)" in ps
    i_drain, i_stop = ps.index("pre_restart_drain.py"), ps.index("& $Nssm stop anchor")
    assert i_drain < i_stop


def test_a_terminal_the_service_owns_is_never_reported_parked(monkeypatch):
    """final r1: close_session in this separate process cannot stop a service-owned PTY (pty_killed False)."""
    import terminal_session as ts
    monkeypatch.setattr(drain, "_live_pty_records", lambda project_id=None: [{"session_id": "s1", "project_id": "p", "lane": "plan"}])
    monkeypatch.setattr(ts, "close_session", lambda sid, project_id=None: {"ok": True, "pty_killed": False, "status": "idle"})
    monkeypatch.setattr(drain, "ensure_warm_seed", lambda *a, **k: "cached")
    monkeypatch.setattr(drain, "service_drain", lambda: {"mode": "http", "parked": [], "idle": [], "errors": [], "note": None})
    rep = drain.drain()
    e = rep["drained"][0]
    assert e["parked"] is False and e["recorded"] is True and rep["terminals_end_with_stop"] == ["s1"]
    monkeypatch.setattr(ts, "close_session", lambda sid, project_id=None: {"ok": False})
    assert drain.drain()["ok"] is False

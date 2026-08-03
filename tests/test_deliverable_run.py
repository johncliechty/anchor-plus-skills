"""Wave 8 — runnable Anchor deliverable as an EPHEMERAL preview.

The Anchor deliverable (``anchor_gui.py``) is a long-running server, so its
"run" is a preview instance on an OS-assigned free port in an isolated TEMP
data dir — it must NEVER bind/disturb the live :8777 service (frozen design —
MASTER-PLAN §H + IMPLEMENTATION-PLAN Wave 8).

Coverage:
  - start_preview launches a REAL anchor_gui.py subprocess on an ephemeral port
    with a temp data dir, health-checks 200, returns a URL; stop_preview reaps
    it (the pid is dead afterward). Bounded — never hangs.
  - NEVER-8777: the chosen preview port != 8777, and pick_free_port refuses
    8777. The test never binds 8777.
  - reap_orphans / list_previews reconcile a dead preview → stopped.
  - Auth: /api/rnd/preview_start + preview_stop are 401 without the token when
    ANCHOR_TOKEN is set, succeed with it.

Hermetic: temp data dir, ephemeral ports, NO live claude. Every spawned process
is reaped (no leaks).
"""
import importlib
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

CODE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def preview(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_BIND", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import job_runner
    importlib.reload(job_runner)
    import preview_server
    importlib.reload(preview_server)
    return preview_server


def _pid_alive(pid):
    if pid is None:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                             capture_output=True, text=True)
        return str(int(pid)) in (out.stdout or "")
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


# ── pick_free_port: OS-assigned, never 8777 ─────────────────────────────────

def test_pick_free_port_is_free_and_not_8777(preview):
    port = preview.pick_free_port()
    assert port != preview.LIVE_PORT == 8777
    assert 1 <= port <= 65535


def test_pick_free_port_refuses_only_8777(preview, monkeypatch):
    """If the OS only ever offered 8777, pick_free_port REFUSES rather than ever
    returning the live port."""
    calls = {"n": 0}

    class _FakeSock:
        def bind(self, addr):
            pass

        def getsockname(self):
            calls["n"] += 1
            return ("127.0.0.1", 8777)

        def close(self):
            pass

    monkeypatch.setattr(preview.socket, "socket",
                        lambda *a, **k: _FakeSock())
    with pytest.raises(RuntimeError):
        preview.pick_free_port(attempts=3)
    assert calls["n"] == 3  # exhausted, never returned 8777


# ── start / health-check / stop / reap a REAL preview ───────────────────────

def test_start_preview_then_stop_reaps(preview):
    res = preview.start_preview(str(CODE_DIR), "pid-xyz",
                                target="anchor_gui.py", health_timeout=20.0)
    assert res["ok"] is True, res
    pid = res["pid"]
    port = res["port"]
    try:
        # NEVER 8777.
        assert port != 8777
        assert res["url"] == f"http://127.0.0.1:{port}/"
        # Reachable: it answers 200 on /.
        with urllib.request.urlopen(res["url"], timeout=5) as r:
            assert r.status == 200
        # Registered + survives a reload of the module (durable).
        importlib.reload(preview)
        recs = preview.list_previews("pid-xyz")
        assert any(x["preview_id"] == res["preview_id"]
                   and x["status"] == preview.STATUS_RUNNING for x in recs)
        # The preview uses an isolated TEMP data dir (NOT the code dir / live).
        rec = next(x for x in recs if x["preview_id"] == res["preview_id"])
        assert Path(rec["data_dir"]).resolve() != CODE_DIR
    finally:
        stop = preview.stop_preview(res["preview_id"])
        assert stop["ok"] is True
    # Bounded wait for the process to actually be gone.
    deadline = time.time() + 15
    while _pid_alive(pid) and time.time() < deadline:
        time.sleep(0.2)
    assert not _pid_alive(pid), "preview process must be reaped"
    # Record now reads stopped.
    rec = preview.load_previews().get(res["preview_id"])
    assert rec and rec["status"] == preview.STATUS_STOPPED


def test_stop_preview_idempotent_and_unknown(preview):
    # Unknown id → clean refusal, not a crash.
    assert preview.stop_preview("nope")["ok"] is False
    # Start, stop twice — second stop is a no-op success.
    res = preview.start_preview(str(CODE_DIR), "pid-2",
                                target="anchor_gui.py", health_timeout=20.0)
    assert res["ok"] is True
    pid = res["pid"]
    try:
        assert preview.stop_preview(res["preview_id"])["ok"] is True
        assert preview.stop_preview(res["preview_id"])["ok"] is True
    finally:
        # Ensure no leak even if an assert above failed.
        preview.stop_preview(res["preview_id"])
    deadline = time.time() + 15
    while _pid_alive(pid) and time.time() < deadline:
        time.sleep(0.2)
    assert not _pid_alive(pid)


def test_start_preview_missing_target_is_clean_failure(preview, tmp_path):
    res = preview.start_preview(str(tmp_path), "pid-3",
                                target="does_not_exist.py", health_timeout=2.0)
    assert res["ok"] is False
    assert "not found" in res["reason"].lower()


def test_reap_orphans_marks_dead_preview_stopped(preview):
    """A 'running' record whose process is gone is reconciled → stopped without
    killing anything live (simulated-restart recovery)."""
    # Inject a fake running record whose pid is certainly dead.
    rec = {
        "preview_id": "ghost",
        "project_id": "pid-4",
        "target": "anchor_gui.py",
        "port": 65000,
        "url": "http://127.0.0.1:65000/",
        "pid": 999999998,  # not a live process
        "data_dir": "",
        "status": preview.STATUS_RUNNING,
        "started_at": time.time(),
        "stopped_at": None,
    }
    preview._put_record(rec)
    out = preview.reap_orphans()
    assert "ghost" in out["reaped"]
    assert preview.load_previews()["ghost"]["status"] == preview.STATUS_STOPPED


# ── never-8777: starting/stopping does not bind or disturb 8777 ─────────────

def test_preview_never_binds_8777(preview):
    """Two previews both get ephemeral ports != 8777; the live port is untouched
    (the test never binds 8777; it asserts the guard holds)."""
    a = preview.start_preview(str(CODE_DIR), "p", target="anchor_gui.py",
                              health_timeout=20.0)
    assert a["ok"] is True
    try:
        assert a["port"] != 8777
        b = preview.start_preview(str(CODE_DIR), "p", target="anchor_gui.py",
                                  health_timeout=20.0)
        assert b["ok"] is True
        try:
            assert b["port"] != 8777
            assert a["port"] != b["port"]
        finally:
            preview.stop_preview(b["preview_id"])
    finally:
        preview.stop_preview(a["preview_id"])


# ── Auth: preview endpoints are token-gated ─────────────────────────────────

def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _get(url, token=None):
    req = urllib.request.Request(url, method="GET")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_previews_endpoint_omits_absolute_paths(monkeypatch, tmp_path):
    """GET /api/rnd/previews returns a SAFE projection — it must NOT leak the
    absolute on-disk fields (data_dir / folder_path) that the persisted record
    keeps for reaping. Mirrors the term_sessions worktree_path stripping."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_BIND", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import preview_server
    importlib.reload(preview_server)
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    # Inject a STOPPED record carrying absolute paths (no live process).
    secret_data_dir = str(tmp_path / "secret-preview-data")
    secret_folder = str(CODE_DIR)
    preview_server._put_record({
        "preview_id": "proj-abc",
        "project_id": "pid-secret",
        "target": "anchor_gui.py",
        "port": 65111,
        "url": "http://127.0.0.1:65111/",
        "pid": None,
        "data_dir": secret_data_dir,
        "status": preview_server.STATUS_STOPPED,
        "started_at": time.time(),
        "stopped_at": time.time(),
        "folder_path": secret_folder,
    })

    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        code, raw = _get(
            f"http://127.0.0.1:{port}/api/rnd/previews?project_id=pid-secret")
        assert code == 200
        text = raw.decode("utf-8")
        body = json.loads(text)
        assert body.get("ok") is True
        prevs = body.get("previews") or []
        assert any(p.get("preview_id") == "proj-abc" for p in prevs), prevs
        for p in prevs:
            # The safe projection must NOT carry the absolute fields...
            assert "data_dir" not in p, p
            assert "folder_path" not in p, p
            # ...but must keep the fields the UI actually needs.
            assert "url" in p and "status" in p and "port" in p
        # And the absolute path strings must not appear anywhere in the body.
        assert secret_data_dir not in text
        assert secret_folder not in text
        # The persisted record STILL keeps the full fields (for reaping).
        rec = preview_server.load_previews().get("proj-abc")
        assert rec and rec.get("data_dir") == secret_data_dir
        assert rec.get("folder_path") == secret_folder
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


def test_preview_endpoints_require_token(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # Placeholder token on the distro-scan allowlist (so the no-secrets scan
    # never flags this test as a leaked auth-token-value).
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    monkeypatch.delenv("ANCHOR_BIND", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    assert port != 8777
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # No token → 401 (BEFORE any preview subprocess is ever spawned).
        for ep, payload in (
            ("/api/rnd/preview_start", {"project_id": "x"}),
            ("/api/rnd/preview_stop", {"preview_id": "x"}),
        ):
            code, _ = _post(base + ep, payload)
            assert code == 401, ep + " must require the token"
        # Right token → reaches the handler; unknown project is a clean refusal
        # (404) — proving auth passed without spawning a real preview.
        code, raw = _post(base + "/api/rnd/preview_start",
                          {"project_id": "no-such"}, token="tok-123")
        assert code == 404
        # Stop of an unknown preview with a valid token → clean 404.
        code, raw = _post(base + "/api/rnd/preview_stop",
                          {"preview_id": "no-such"}, token="tok-123")
        assert code == 404
        body = json.loads(raw)
        assert body.get("ok") is False
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)

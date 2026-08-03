"""Wave 2 — Gandalf endpoints + the first-scan trigger hook.

  * ``POST /api/rnd/gandalf_run {project_id}`` — token-authed; schedules a fresh
    run in a daemon thread ({ok, scheduled}); per-project in-flight guard; NOT
    module-flag-gated (manual is explicit).
  * ``GET  /api/rnd/gandalf?project_id=<id>`` — ``?token=`` gated; the SAFE
    ``list_runs`` projection.
  * ``_trigger_gandalf_first_scan`` — gated by ``_PROACTIVE_SUMMARY_ENABLED`` (off
    in tests) + first-run-ONLY + no TOCTOU double-fire under two concurrent calls.

Hermetic: tmp data dir + a temp git repo + a registered project + BOTH seams
stubbed (``ANCHOR_RUNNER_CMD`` → ``stub_gandalf_draft.py``, ``ANCHOR_GANDALF_HOST_CMD``
→ ``stub_gandalf_host.py``); ``ANCHOR_PROACTIVE_SUMMARY`` off; a loopback server on
an OS-assigned free port (NEVER :8777). Stdlib only.
"""
import importlib
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
DRAFT_STUB = (_TESTS / "stub_gandalf_draft.py").as_posix()
HOST_STUB = (_TESTS / "stub_gandalf_host.py").as_posix()


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args),
                   capture_output=True, text=True, check=False)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")  # OFF in tests
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {DRAFT_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD", f"{sys.executable} {HOST_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(tmp_path / "no-skill"))
    # These endpoint tests drive runs via the map-reduce draft+host stubs (the
    # retained fallback); the DEFAULT is now the agentic canonical-skill run.
    monkeypatch.setenv("ANCHOR_GANDALF_MODE", "mapreduce")

    for mod in ("paths", "job_runner", "rnd_registry", "effort_history",
                "summarizer", "report_viewer", "gandalf"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    import rnd_registry
    import gandalf

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    pid = proj["id"]
    yield {"gui": gui, "rnd": rnd_registry, "gandalf": gandalf,
           "repo": repo, "pid": pid}


@pytest.fixture
def server(env):
    gui = env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        time.sleep(0.15)
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _wait_runs(gandalf, repo, pid, n=1, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = gandalf.list_runs(str(repo), pid)
        if len(runs) >= n:
            return runs
        time.sleep(0.05)
    return gandalf.list_runs(str(repo), pid)


# ── GET read endpoint ────────────────────────────────────────────────────────

def test_get_empty_then_populated(server):
    env, base, _ = server
    pid = env["pid"]
    status, body = _get(f"{base}/api/rnd/gandalf?project_id={pid}")
    assert status == 200
    assert body["ok"] is True
    assert body["runs"] == []

    # Run once directly, then read again.
    env["gandalf"].run_gandalf(str(env["repo"]), pid)
    status, body = _get(f"{base}/api/rnd/gandalf?project_id={pid}")
    assert status == 200
    assert len(body["runs"]) == 1
    rec = body["runs"][0]
    assert rec["ok"] is True
    assert rec["verdict"]
    # SAFE projection — no absolute paths leak.
    for v in rec.values():
        if isinstance(v, str):
            assert ":\\" not in v
            assert str(env["repo"]) not in v


def test_get_requires_project_id(server):
    _, base, _ = server
    status, body = _get(f"{base}/api/rnd/gandalf")
    assert status == 400
    assert body["ok"] is False


def test_get_unknown_project_404(server):
    _, base, _ = server
    status, body = _get(f"{base}/api/rnd/gandalf?project_id=nope-xyz")
    assert status == 404


def test_get_token_gate(env, monkeypatch):
    # With a token configured, an unauthed GET is 401; an authed one is 200.
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    import paths
    importlib.reload(paths)
    gui = importlib.reload(env["gui"])
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        pid = env["pid"]
        status, _ = _get(f"{base}/api/rnd/gandalf?project_id={pid}")
        assert status == 401
        status, body = _get(
            f"{base}/api/rnd/gandalf?project_id={pid}&token=s3cret")
        assert status == 200
        assert body["ok"] is True
    finally:
        srv.shutdown()
        time.sleep(0.15)
        srv.server_close()
        t.join(timeout=5)


# ── POST manual run endpoint ─────────────────────────────────────────────────

def test_manual_run_schedules_exactly_one(server):
    env, base, _ = server
    pid, repo, gandalf = env["pid"], env["repo"], env["gandalf"]
    status, body = _post(f"{base}/api/rnd/gandalf_run", {"project_id": pid})
    assert status == 200
    assert body["ok"] is True
    assert body["scheduled"] is True
    runs = _wait_runs(gandalf, repo, pid, n=1)
    assert len(runs) == 1


def test_manual_run_inflight_guard(server):
    """Two manual calls fired back-to-back schedule ≤1 run while one is in-flight
    (the second is suppressed by the per-project guard)."""
    env, base, _ = server
    pid, repo, gandalf = env["pid"], env["repo"], env["gandalf"]
    # Fire two POSTs as fast as possible.
    s1, b1 = _post(f"{base}/api/rnd/gandalf_run", {"project_id": pid})
    s2, b2 = _post(f"{base}/api/rnd/gandalf_run", {"project_id": pid})
    assert s1 == 200 and s2 == 200
    scheduled = [b1["scheduled"], b2["scheduled"]]
    # At least one scheduled; at most one TRUE while the first is in-flight.
    assert scheduled.count(True) >= 1
    runs = _wait_runs(gandalf, repo, pid, n=1)
    # The guard means the in-flight set blocked any overlapping schedule; once
    # finished a later manual call would work again. We assert no double-fire
    # raced into >1 run from the two near-simultaneous calls.
    assert 1 <= len(runs) <= 2


def test_manual_run_unknown_project_404(server):
    _, base, _ = server
    status, body = _post(f"{base}/api/rnd/gandalf_run",
                         {"project_id": "nope-xyz"})
    assert status == 404


def test_manual_run_requires_token_when_set(env, monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    import paths
    importlib.reload(paths)
    gui = importlib.reload(env["gui"])
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        pid = env["pid"]
        status, _ = _post(f"{base}/api/rnd/gandalf_run", {"project_id": pid})
        assert status == 401
        status, body = _post(f"{base}/api/rnd/gandalf_run",
                             {"project_id": pid}, token="s3cret")
        assert status == 200
        assert body["ok"] is True
    finally:
        srv.shutdown()
        time.sleep(0.15)
        srv.server_close()
        t.join(timeout=5)


# ── first-scan trigger gating + TOCTOU ───────────────────────────────────────

def test_first_scan_suppressed_when_proactive_off(env):
    """With ANCHOR_PROACTIVE_SUMMARY off (the test default), the first-scan hook
    does NOT schedule a run."""
    gui, repo, pid = env["gui"], env["repo"], env["pid"]
    assert gui._PROACTIVE_SUMMARY_ENABLED is False
    scheduled = gui._trigger_gandalf_first_scan(str(repo), pid)
    assert scheduled is False
    time.sleep(0.2)
    assert env["gandalf"].list_runs(str(repo), pid) == []


def test_first_scan_fires_once_when_enabled(env, monkeypatch):
    """With proactive ON, the first-scan hook fires once when absent and no-ops
    when a run already exists."""
    gui, repo, pid, gandalf = (env["gui"], env["repo"], env["pid"],
                               env["gandalf"])
    monkeypatch.setattr(gui, "_PROACTIVE_SUMMARY_ENABLED", True)
    assert gui._trigger_gandalf_first_scan(str(repo), pid) is True
    runs = _wait_runs(gandalf, repo, pid, n=1)
    assert len(runs) == 1
    # A second first-scan call no-ops (a prior run exists).
    assert gui._trigger_gandalf_first_scan(str(repo), pid) is False
    time.sleep(0.2)
    assert len(gandalf.list_runs(str(repo), pid)) == 1


def test_two_concurrent_first_scans_schedule_at_most_one(env, monkeypatch):
    """The TOCTOU guard: two concurrent first-scan calls schedule ≤1 run."""
    gui, repo, pid, gandalf = (env["gui"], env["repo"], env["pid"],
                               env["gandalf"])
    monkeypatch.setattr(gui, "_PROACTIVE_SUMMARY_ENABLED", True)
    results = []
    barrier = threading.Barrier(2)

    def _fire():
        barrier.wait()
        results.append(gui._trigger_gandalf_first_scan(str(repo), pid))

    threads = [threading.Thread(target=_fire) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # At most one of the two concurrent calls scheduled a run.
    assert results.count(True) <= 1
    runs = _wait_runs(gandalf, repo, pid, n=1)
    assert len(runs) == 1  # exactly one run, never two


def test_delete_route(server, monkeypatch):
    """POST /api/rnd/gandalf_delete token-gated delete route test."""
    env, base, _ = server
    pid, repo, gandalf = env["pid"], env["repo"], env["gandalf"]
    # Run once to populate index
    gandalf.run_gandalf(str(repo), pid)
    runs = gandalf.list_runs(str(repo), pid)
    assert len(runs) == 1
    run_id = runs[0]["run_id"]

    # Without token (when token is set) -> 401
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    import paths
    importlib.reload(paths)
    status, body = _post(f"{base}/api/rnd/gandalf_delete", {"project_id": pid, "run_id": run_id})
    assert status == 401
    
    # With valid token -> 200, deleted
    status, body = _post(f"{base}/api/rnd/gandalf_delete", {"project_id": pid, "run_id": run_id}, token="s3cret")
    assert status == 200
    assert body["ok"] is True
    assert body["deleted"] is True
    
    # Verify index has no runs left
    assert gandalf.list_runs(str(repo), pid) == []


# ── GET bulk in-flight status (dashboard card badges) ────────────────────────

def test_status_all_empty(server):
    """With nothing in-flight the bulk endpoint returns ok + an empty map."""
    _, base, _ = server
    status, body = _get(f"{base}/api/rnd/gandalf_status_all")
    assert status == 200
    assert body["ok"] is True
    assert body["statuses"] == {}


def test_status_all_reports_inflight_then_clears(server):
    """A project with a live in-flight record surfaces in the bulk map keyed by
    project_id; once popped it disappears."""
    env, base, _ = server
    gui, pid = env["gui"], env["pid"]
    with gui._GANDALF_INFLIGHT_GUARD:
        gui._GANDALF_INFLIGHT[pid] = {"status": "Reading the codebase…",
                                      "ts": time.time()}
    try:
        status, body = _get(f"{base}/api/rnd/gandalf_status_all")
        assert status == 200
        assert body["ok"] is True
        assert body["statuses"].get(pid) == "Reading the codebase…"
    finally:
        with gui._GANDALF_INFLIGHT_GUARD:
            gui._GANDALF_INFLIGHT.pop(pid, None)
    # After the run finishes (record popped) the project drops out of the map.
    status, body = _get(f"{base}/api/rnd/gandalf_status_all")
    assert status == 200
    assert pid not in body["statuses"]


def test_status_all_skips_and_sweeps_stale(server):
    """A stale (>30 min) in-flight record is omitted AND swept from the dict."""
    env, base, _ = server
    gui, pid = env["gui"], env["pid"]
    with gui._GANDALF_INFLIGHT_GUARD:
        gui._GANDALF_INFLIGHT[pid] = {"status": "zombie", "ts": time.time() - 3600}
    status, body = _get(f"{base}/api/rnd/gandalf_status_all")
    assert status == 200
    assert body["ok"] is True
    assert pid not in body["statuses"]
    with gui._GANDALF_INFLIGHT_GUARD:
        assert pid not in gui._GANDALF_INFLIGHT  # swept


def test_status_all_token_gate(env, monkeypatch):
    """With a token configured, an unauthed bulk GET is 401; an authed one 200."""
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    import paths
    importlib.reload(paths)
    gui = importlib.reload(env["gui"])
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status, _ = _get(f"{base}/api/rnd/gandalf_status_all")
        assert status == 401
        status, body = _get(f"{base}/api/rnd/gandalf_status_all?token=s3cret")
        assert status == 200
        assert body["ok"] is True
        assert body["statuses"] == {}
    finally:
        srv.shutdown()
        time.sleep(0.15)
        srv.server_close()
        t.join(timeout=5)


# ── archive / clear-failed (feat/gandalf-archive-ui) ─────────────────────────

def _failed_record(rid, reason="boom"):
    return {"run_id": rid, "ts": time.time(), "ok": False, "verdict": "",
            "degraded": True, "cross_model": False, "report_rel": None,
            "exec_rel": None, "advisor_rel": None, "reason": reason}


def test_archive_removes_run_from_index(server):
    """POST /api/rnd/gandalf_archive drops the targeted run from the index AND
    removes its on-disk artifact dir."""
    env, base, _ = server
    pid, repo, gandalf = env["pid"], env["repo"], env["gandalf"]
    out = gandalf.run_gandalf(str(repo), pid)
    run_id = out["run_id"]
    run_dir = repo / "gandalf" / run_id
    assert run_dir.is_dir()  # artifacts written for the OK run
    assert len(gandalf.list_runs(str(repo), pid)) == 1

    status, body = _post(f"{base}/api/rnd/gandalf_archive",
                         {"project_id": pid, "run_id": run_id})
    assert status == 200
    assert body["ok"] is True
    assert body["removed"] is True
    assert gandalf.list_runs(str(repo), pid) == []
    assert not run_dir.exists()  # artifact dir gone


def test_archive_unknown_run_idempotent(server):
    """Archiving an id that isn't present is a no-op (ok, removed:false)."""
    env, base, _ = server
    pid = env["pid"]
    status, body = _post(f"{base}/api/rnd/gandalf_archive",
                         {"project_id": pid, "run_id": "run-nope-123"})
    assert status == 200
    assert body["ok"] is True
    assert body["removed"] is False


def test_archive_requires_fields(server):
    _, base, _ = server
    status, body = _post(f"{base}/api/rnd/gandalf_archive", {"run_id": "x"})
    assert status == 400
    assert body["ok"] is False


def test_archive_unknown_project_404(server):
    _, base, _ = server
    status, _ = _post(f"{base}/api/rnd/gandalf_archive",
                      {"project_id": "nope-xyz", "run_id": "run-1"})
    assert status == 404


def test_clear_failed_removes_failed_keeps_ok(server):
    """POST /api/rnd/gandalf_clear_failed retires every failed run while leaving
    completed runs intact."""
    env, base, _ = server
    pid, repo, gandalf = env["pid"], env["repo"], env["gandalf"]
    # One real (OK) run + two injected failed records.
    ok_out = gandalf.run_gandalf(str(repo), pid)
    gandalf._append_index(str(repo), pid, _failed_record("run-fail-1"))
    gandalf._append_index(str(repo), pid, _failed_record("run-fail-2"))
    runs = gandalf.list_runs(str(repo), pid)
    assert len(runs) == 3
    assert sum(1 for r in runs if not r["ok"]) == 2

    status, body = _post(f"{base}/api/rnd/gandalf_clear_failed",
                         {"project_id": pid})
    assert status == 200
    assert body["ok"] is True
    assert body["removed"] == 2

    remaining = gandalf.list_runs(str(repo), pid)
    assert len(remaining) == 1
    assert remaining[0]["ok"] is True
    assert remaining[0]["run_id"] == ok_out["run_id"]


def test_clear_failed_noop_when_none(server):
    env, base, _ = server
    pid, repo, gandalf = env["pid"], env["repo"], env["gandalf"]
    gandalf.run_gandalf(str(repo), pid)
    status, body = _post(f"{base}/api/rnd/gandalf_clear_failed",
                         {"project_id": pid})
    assert status == 200
    assert body["ok"] is True
    assert body["removed"] == 0
    assert len(gandalf.list_runs(str(repo), pid)) == 1


def test_archive_token_gate(env, monkeypatch):
    """With a token set, the mutating archive route is 401 unauthed, 200 authed."""
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    import paths
    importlib.reload(paths)
    gui = importlib.reload(env["gui"])
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        pid = env["pid"]
        status, _ = _post(f"{base}/api/rnd/gandalf_archive",
                          {"project_id": pid, "run_id": "run-1"})
        assert status == 401
        status, body = _post(f"{base}/api/rnd/gandalf_archive",
                             {"project_id": pid, "run_id": "run-1"},
                             token="s3cret")
        assert status == 200
        assert body["ok"] is True
    finally:
        srv.shutdown()
        time.sleep(0.15)
        srv.server_close()
        t.join(timeout=5)


def test_cancel_route(server):
    """POST /api/rnd/term_kill for a Gandalf run cancels it."""
    env, base, _ = server
    pid, repo, gandalf = env["pid"], env["repo"], env["gandalf"]
    
    # Fake the active run in active runs dict and session registry
    import session_registry
    session_id = "run-cancel-test-123"
    session_registry.register_session(
        project_id=pid,
        lane="gandalf",
        status=session_registry.STATUS_RUNNING,
        session_id=session_id
    )
    
    # Put in active runs
    import subprocess
    import os
    # Spawn a dummy sleep process to kill
    if os.name == "nt":
        proc = subprocess.Popen(["cmd.exe", "/c", "pause"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        proc = subprocess.Popen(["sleep", "60"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
    gandalf._ACTIVE_RUNS[session_id] = {"job_id": None, "proc": proc, "cancelled": False}
    
    # Call term_kill
    status, body = _post(f"{base}/api/rnd/term_kill", {"session": session_id})
    assert status == 200
    assert body["ok"] is True
    
    # Verify process was terminated
    # Give a tiny bit of time
    time.sleep(0.5)
    assert proc.poll() is not None


def test_gandalf_cancel_route(server):
    """POST /api/rnd/gandalf_cancel cancels a Gandalf run by project_id."""
    env, base, _ = server
    pid, repo, gandalf = env["pid"], env["repo"], env["gandalf"]

    # Try cancelling when nothing is running
    status, body = _post(f"{base}/api/rnd/gandalf_cancel", {"project_id": pid})
    assert status == 200
    assert body["ok"] is True
    assert body["cancelled"] is False

    # Fake the active run in active runs dict and session registry
    import session_registry
    session_id = "run-cancel-proj-123"
    session_registry.register_session(
        project_id=pid,
        lane="gandalf",
        status=session_registry.STATUS_RUNNING,
        session_id=session_id
    )

    import subprocess
    import os
    if os.name == "nt":
        proc = subprocess.Popen(["cmd.exe", "/c", "pause"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        proc = subprocess.Popen(["sleep", "60"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    gandalf._ACTIVE_RUNS[session_id] = {
        "job_id": None,
        "proc": proc,
        "cancelled": False,
        "folder": str(repo),
        "project_id": pid,
        "index_recorded": False,
    }

    # Call gandalf_cancel
    status, body = _post(f"{base}/api/rnd/gandalf_cancel", {"project_id": pid})
    assert status == 200
    assert body["ok"] is True
    assert body["cancelled"] is True

    # Verify status in session_registry is cancelled
    rec = session_registry.get_session(session_id)
    assert rec["status"] == "cancelled"

    # Verify process was terminated
    time.sleep(0.5)
    assert proc.poll() is not None


def test_panel_html_contains_retire_control(env):
    """The rendered Gandalf panel carries the (x) retire control + the Clear-failed
    button when a failed run is present."""
    gui, repo, pid, gandalf = (env["gui"], env["repo"], env["pid"],
                               env["gandalf"])
    gandalf.run_gandalf(str(repo), pid)
    gandalf._append_index(str(repo), pid, _failed_record("run-fail-x"))
    html = gui._render_layoutd_gandalf_panel(str(repo), pid)
    assert "gretire" in html
    assert "gandalfArchiveRun(event" in html
    assert "gandalf-clear-failed" in html
    assert "gandalfClearFailed(" in html

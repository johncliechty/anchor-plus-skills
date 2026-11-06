"""Wave 4 — the daily healthcheck exercises the v11 "Reliable Trio Handoff" surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 4 — ... healthcheck v11 surface": the
self-test walks the v11 surface FULLY STUBBED — ``ANCHOR_PTY_BACKEND=stub`` + the
runner seam swapped to the STREAM-JSON stub (``ANCHOR_RUNNER_CMD`` →
tests/stub_streamjson.py) + a temp worktree base + a throwaway temp git project +
a temp data dir — never live claude / real PTY / :8777 / real data / network, with
proactive summary OFF (so the keystone's background summary hard no-ops).

THE v11 LESSON made permanent: the walk exercises the REAL WORKTREE-ONLY live flow.
It starts a LIVE research/planning session, writes produced docs into the session's
WORKTREE ONLY (NO ``record_effort``, NO kill), advances through the shared keystone
``terminal_session.prepare_stage_handoff``, and asserts the docs were PERSISTED +
committed into the MAIN project AND named in the prompt AND referenced in a
HANDOFF.md. (Pre-fix the docs never left the worktree — this is the walk that would
have caught the original bug.)

The test asserts the check PASSES + is hermetic: it RESTORES the forced env vars
(incl. ANCHOR_PROACTIVE_SUMMARY), never binds :8777, leaves no orphan synthetic
project / managed session / live stub PTY, and tears down its temp dirs. If any of
these FAIL it is a REAL bug in ``check_rnd_v11_surface`` (fix the product code, not
the test).
"""
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _have_stream_stub():
    return (Path(__file__).resolve().parent / "stub_streamjson.py").is_file()


@pytest.fixture
def hc(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PTY_BACKEND", raising=False)
    monkeypatch.delenv("ANCHOR_WORKTREE_BASE", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "gate_adapter", "rnd_registry", "effort_history",
                 "sessions", "lanes", "brownfield_scan", "report_viewer",
                 "summarizer", "deliverables", "pty_manager", "session_registry",
                 "worktrees", "terminal_session", "handoff", "preview_server",
                 "project_bootstrap", "project_remote", "project_move",
                 "boneyard", "anchor_marker", "anchor_gui", "anchor_healthcheck"):
        importlib.import_module(name)
        importlib.reload(importlib.import_module(name))
    hc_mod = importlib.import_module("anchor_healthcheck")
    yield hc_mod, tmp_path
    import job_runner
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()
    import pty_manager
    pty_manager._reset_live_table_for_tests()


def _rnd_env(hc_mod, tmp_path, suffix=""):
    env = {
        "runner_cmd": hc_mod._fake_runner_cmd(),
        "folder": tmp_path / f"hc-rnd-folder{suffix}",
        "created_ids": [],
        "prev_runner_cmd": None,
        "v3_temp_dirs": [],
    }
    env["folder"].mkdir(parents=True, exist_ok=True)
    return env


pytestmark = pytest.mark.skipif(
    not (_have_git() and _have_stream_stub()),
    reason="git not on PATH or stream-json stub absent")


def test_check_rnd_v11_surface_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v11_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    v11 = [c for c in report.checks if c[0] == "R&D v11 surface"]
    assert v11, "v11 check did not record a result"
    name, ok, detail = v11[0]
    assert ok, f"v11 surface check failed: {detail}"


def test_v11_walk_survives_live_registry_writer(hc, monkeypatch):
    """A dashboard writer saving an earlier ambient registry snapshot right after
    the v11 planning session starts must not erase plan_sid before update_session
    (reproduces 'plan→build keystone: KeyError: <plan_sid>').
    """
    import json
    import session_registry as reg
    import terminal_session as ts

    hc_mod, tmp_path = hc
    live = reg.register_session("live-project", "general", label="Before")
    snapshot = reg.load_sessions()
    snapshot[live["session_id"]]["label"] = "Dashboard update"
    writer_env = dict(os.environ, ANCHOR_DATA_DIR=str(tmp_path))
    original_start = ts.start_session
    writes = []

    def start_with_live_writer(project_id, lane, *args, **kwargs):
        result = original_start(project_id, lane, *args, **kwargs)
        if lane == "planning" and not writes:
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import json,sys,session_registry as r; "
                 "r._save_sessions(json.loads(sys.stdin.read()))"],
                input=json.dumps(snapshot), text=True, capture_output=True,
                env=writer_env, cwd=str(Path(__file__).resolve().parent.parent),
                timeout=15)
            assert proc.returncode == 0, proc.stderr
            writes.append(result["session_id"])
        return result

    monkeypatch.setattr(ts, "start_session", start_with_live_writer)
    rnd_env = _rnd_env(hc_mod, tmp_path, "writer")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v11_surface(report, object(), rnd_env)
        assert writes, "the interleaved registry writer never ran"
        result = next(c for c in report.checks if c[0] == "R&D v11 surface")
        assert result[1], result[2]
        assert os.environ.get("ANCHOR_DATA_DIR") == str(tmp_path)
        assert reg.load_sessions() == snapshot
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert reg.load_sessions() == snapshot


def test_v11_walk_preserves_existing_session_and_pty(hc, monkeypatch):
    import pty_manager as pty
    import session_registry as reg

    hc_mod, tmp_path = hc
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    sid = pty.start(["stub"])
    live = reg.register_session(
        "live-project", "research", session_id=sid,
        status=reg.STATUS_RUNNING)
    rnd_env = _rnd_env(hc_mod, tmp_path, "live")
    rnd_env["created_ids"].append(live["project_id"])
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v11_surface(report, object(), rnd_env)
        assert pty.live_sessions() == [sid]
        assert reg.get_session(sid) == live
    finally:
        rnd_env["created_ids"].remove(live["project_id"])
        if sid in pty.live_sessions():
            pty.kill(sid)
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)


def test_v11_walk_restores_env(hc, monkeypatch):
    """The walk restores ANCHOR_PTY_BACKEND / WORKTREE_BASE / TERMINAL_SEED /
    ANCHOR_RUNNER_CMD / ANCHOR_PROACTIVE_SUMMARY to their prior values."""
    hc_mod, tmp_path = hc
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "sentinel-prev")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    # WORKTREE_BASE / TERMINAL_SEED / PROACTIVE were deleted by the fixture.
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    assert "ANCHOR_PROACTIVE_SUMMARY" not in os.environ
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v11_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_PTY_BACKEND") == "sentinel-prev"
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    assert "ANCHOR_PROACTIVE_SUMMARY" not in os.environ
    assert os.environ.get("ANCHOR_RUNNER_CMD") == prev_runner


@pytest.mark.parametrize("previous_data", [None, "", "configured"])
def test_v11_data_scope_restored_after_failure(hc, monkeypatch, previous_data):
    import paths
    import session_registry as reg

    hc_mod, tmp_path = hc
    monkeypatch.setattr(paths, "CODE_DIR", tmp_path)
    if previous_data is None:
        monkeypatch.delenv("ANCHOR_DATA_DIR")
    else:
        if previous_data:
            previous_data = str(tmp_path)
        monkeypatch.setenv("ANCHOR_DATA_DIR", previous_data)
    live = reg.register_session("live-project", "general")
    observed = []

    def fail_after_entering_scope(folder):
        observed.append(paths.data_dir())
        raise RuntimeError("injected v11 setup failure")

    monkeypatch.setattr(hc_mod, "_git_init_repo", fail_after_entering_scope)
    rnd_env = _rnd_env(hc_mod, tmp_path, "early-error")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v11_surface(report, object(), rnd_env)
        assert observed and observed[0] != tmp_path
        assert os.environ.get("ANCHOR_DATA_DIR") == previous_data
        assert reg.get_session(live["session_id"]) == live
        result = next(c for c in report.checks if c[0] == "R&D v11 surface")
        assert not result[1] and "injected v11 setup failure" in result[2]
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)


def test_v11_walk_never_8777_no_orphans(hc, monkeypatch):
    """No preview bound to :8777, no orphan synthetic project, no live PTY /
    managed session after teardown."""
    import preview_server
    import session_registry
    import pty_manager
    import rnd_registry
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "3")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v11_surface(report, object(), rnd_env)
        private_roots = [d for d in rnd_env["v3_temp_dirs"]
                         if Path(d).name.startswith("anchor-hc-v11-data-")]
        assert len(private_roots) == 1
        with monkeypatch.context() as private:
            private.setenv("ANCHOR_DATA_DIR", str(private_roots[0]))
            assert session_registry.list_sessions() == []
            assert rnd_registry.list_projects(with_effective_state=False) == []
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    for rec in preview_server.load_previews().values():
        assert rec.get("port") != preview_server.LIVE_PORT
    for pid in rnd_env["created_ids"]:
        assert session_registry.list_sessions(project_id=pid) == []
    assert pty_manager.live_sessions() == []


def test_v11_walk_torn_down_temp_dirs(hc):
    """The walk's throwaway worktree base + project dirs are recorded + removed."""
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "4")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v11_surface(report, object(), rnd_env)
        created = list(rnd_env.get("v3_temp_dirs", []))
        assert created, "the v11 walk should have recorded temp dirs"
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    for d in created:
        if Path(d).name.startswith(("anchor-hc-v11-data-", "anchor-hc-v11-wt-")):
            assert not Path(d).exists(), f"temp dir not cleaned: {d}"


def test_v11_walk_skips_without_stream_stub(hc, monkeypatch):
    """If the stream-json stub is absent the walk SKIPS green (never live claude)."""
    hc_mod, tmp_path = hc
    monkeypatch.setattr(hc_mod, "_streamjson_runner_cmd", lambda: None)
    rnd_env = _rnd_env(hc_mod, tmp_path, "5")
    report = hc_mod.Report()
    hc_mod.check_rnd_v11_surface(report, object(), rnd_env)
    v11 = [c for c in report.checks if c[0] == "R&D v11 surface"]
    assert v11 and v11[0][1] is True
    assert "skipped" in v11[0][2]


def test_v11_check_registered_in_main_dispatch():
    """check_rnd_v11_surface is wired into the healthcheck run (after v10)."""
    src = (Path(__file__).resolve().parent.parent
           / "anchor_healthcheck.py").read_text(encoding="utf-8")
    assert "check_rnd_v11_surface(report, server_proc, rnd_env)" in src, \
        "v11 surface check not called in main()"

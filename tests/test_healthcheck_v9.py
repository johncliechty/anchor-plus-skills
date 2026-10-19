"""Wave 5 — the daily healthcheck exercises the v9 "Tidy" surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 5 — ... healthcheck v9 surface": the
self-test walks the v9 surface FULLY STUBBED — `ANCHOR_PTY_BACKEND=stub` + the
runner seam swapped to the STREAM-JSON stub (`ANCHOR_RUNNER_CMD` →
tests/stub_streamjson.py) + a temp worktree base + throwaway temp git projects +
a TEMP projects_root — never live claude / real PTY / :8777 / the REAL Anchor repo
/ the live registry / real network.

Walk: (a) session delete (Option A — record+efforts+summary gone after a reload,
produced docs KEPT); (b) ghost cleanup (an empty DONE record swept, one with
efforts kept); (c) grass idea delete (pointer+index+refinements gone, sibling
kept); (d) set_group/group_by_group (no disk move); (e) the guarded on-disk MOVE
on a TEMP project (+ Anchor-repo refusal with CODE_DIR pointed at a temp dir +
live-session refusal + rollback on an injected failure).
"""
import importlib
import os
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture
def hc(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PTY_BACKEND", raising=False)
    monkeypatch.delenv("ANCHOR_WORKTREE_BASE", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "gate_adapter", "rnd_registry", "effort_history",
                 "sessions", "lanes", "brownfield_scan", "report_viewer",
                 "summarizer", "deliverables", "pty_manager", "session_registry",
                 "worktrees", "terminal_session", "handoff", "preview_server",
                 "project_bootstrap", "project_remote", "project_move",
                 "anchor_marker", "anchor_gui", "anchor_healthcheck"):
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


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


def test_check_rnd_v9_surface_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v9_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    v9 = [c for c in report.checks if c[0] == "R&D v9 surface"]
    assert v9, "v9 check did not record a result"
    name, ok, detail = v9[0]
    assert ok, f"v9 surface check failed: {detail}"


def test_v9_walk_restores_env_and_code_dir(hc, monkeypatch):
    """The walk restores ANCHOR_PTY_BACKEND / WORKTREE_BASE / TERMINAL_SEED /
    ANCHOR_RUNNER_CMD AND — critically — paths.CODE_DIR (which the anchor-repo
    refusal probe temporarily points at a temp dir)."""
    hc_mod, tmp_path = hc
    import paths
    code_dir_before = paths.CODE_DIR
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "sentinel-prev")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v9_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_PTY_BACKEND") == "sentinel-prev"
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    assert os.environ.get("ANCHOR_RUNNER_CMD") == prev_runner
    # CODE_DIR is restored — never left pointed off the real repo.
    assert paths.CODE_DIR == code_dir_before


def test_v9_walk_never_8777_no_orphans_no_real_move(hc):
    """No preview bound to :8777, no orphan synthetic project, no live PTY /
    managed session after teardown — and the REAL Anchor repo / live registry was
    never moved (the walk's move ran on TEMP dirs + a TEMP projects_root only)."""
    import preview_server
    import session_registry
    import pty_manager
    import rnd_registry
    import paths
    hc_mod, tmp_path = hc
    real_code_dir = paths.CODE_DIR
    rnd_env = _rnd_env(hc_mod, tmp_path, "3")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v9_surface(report, object(), rnd_env)
        for pid in rnd_env["created_ids"]:
            proj = rnd_registry.get_project(pid)
            assert proj is None or "__healthcheck__" in proj.get("name", "")
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    # Never the live port.
    for rec in preview_server.load_previews().values():
        assert rec.get("port") != preview_server.LIVE_PORT
    # No managed session rows survive for synthetic pids (no orphan worktree).
    for pid in rnd_env["created_ids"]:
        assert session_registry.list_sessions(project_id=pid) == []
    # No live stub PTY left behind.
    assert pty_manager.live_sessions() == []
    # The REAL Anchor repo directory still exists and was never relocated.
    assert Path(real_code_dir).is_dir()
    assert paths.CODE_DIR == real_code_dir


def test_v9_walk_torn_down_temp_dirs(hc):
    """The walk's throwaway worktree base + project/root dirs are removed."""
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "4")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v9_surface(report, object(), rnd_env)
        created = list(rnd_env.get("v3_temp_dirs", []))
        assert created, "the v9 walk should have recorded temp dirs"
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    for d in created:
        if Path(d).name.startswith("anchor-hc-v9-wt-"):
            assert not Path(d).exists(), f"temp dir not cleaned: {d}"


def test_v9_walk_skips_without_stream_stub(hc, monkeypatch):
    """If the stream-json stub is absent the walk SKIPS green (never live claude)."""
    hc_mod, tmp_path = hc
    monkeypatch.setattr(hc_mod, "_streamjson_runner_cmd", lambda: None)
    rnd_env = _rnd_env(hc_mod, tmp_path, "5")
    report = hc_mod.Report()
    hc_mod.check_rnd_v9_surface(report, object(), rnd_env)
    v9 = [c for c in report.checks if c[0] == "R&D v9 surface"]
    assert v9 and v9[0][1] is True
    assert "skipped" in v9[0][2]


def test_v9_check_registered_in_main_dispatch():
    """check_rnd_v9_surface is wired into the healthcheck run (after v8)."""
    src = (Path(__file__).resolve().parent.parent
           / "anchor_healthcheck.py").read_text(encoding="utf-8")
    assert "check_rnd_v9_surface(report, server_proc, rnd_env)" in src, \
        "v9 surface check not called in main()"

"""Wave 9 — the daily healthcheck exercises the v4 "Project Cockpit" surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 9 — ... healthcheck v4 surface": the
self-test walks the v4 surface FULLY STUBBED — `ANCHOR_PTY_BACKEND=stub` + the
runner seam (`ANCHOR_RUNNER_CMD` → tests/fake_claude.py), in a throwaway temp
project + temp git repo, with a temp worktree base + temp skills dir (never the
build repo / live skills dir), never live claude / real PTY / real preview spawn
/ :8777.

Walk: seed-once (stub session, seeded flag + no re-emit); engine switch (no
orphan PTY); doc-roles dict; rollup lifetime+30d; grass promote (seeded, idea
stays); type-aware deliverable launch — skill verify (no spawn) + service on a
free injected port != 8777 (stubbed preview).
"""
import importlib
import os
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def hc(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PTY_BACKEND", raising=False)
    monkeypatch.delenv("ANCHOR_WORKTREE_BASE", raising=False)
    monkeypatch.delenv("ANCHOR_SKILLS_DIR", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "gate_adapter", "rnd_registry", "effort_history",
                 "sessions", "lanes", "brownfield_scan", "report_viewer",
                 "summarizer", "deliverables", "pty_manager", "session_registry",
                 "worktrees", "terminal_session", "handoff", "preview_server",
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


def test_check_rnd_v4_surface_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v4_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    v4 = [c for c in report.checks if c[0] == "R&D v4 surface"]
    assert v4, "v4 check did not record a result"
    name, ok, detail = v4[0]
    assert ok, f"v4 surface check failed: {detail}"


def test_v4_walk_restores_env(hc, monkeypatch):
    """The walk must restore ANCHOR_PTY_BACKEND / WORKTREE_BASE / SKILLS_DIR /
    TERMINAL_SEED to their prior values (or absence)."""
    hc_mod, tmp_path = hc
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "sentinel-prev")
    # WORKTREE_BASE / SKILLS_DIR / TERMINAL_SEED were delenv'd in the fixture.
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v4_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_PTY_BACKEND") == "sentinel-prev"
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_SKILLS_DIR" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ


def test_v4_walk_never_8777_and_no_orphans(hc):
    """No preview record bound to :8777, no leftover synthetic project, and no
    live PTY / managed session left running after teardown."""
    import preview_server
    import session_registry
    import pty_manager
    import rnd_registry
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "3")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v4_surface(report, object(), rnd_env)
        for pid in rnd_env["created_ids"]:
            proj = rnd_registry.get_project(pid)
            assert proj is None or "__healthcheck__" in proj.get("name", "")
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    # Never the live port.
    for rec in preview_server.load_previews().values():
        assert rec.get("port") != preview_server.LIVE_PORT
    # No managed session rows survive for synthetic pids.
    for pid in rnd_env["created_ids"]:
        assert session_registry.list_sessions(project_id=pid) == []
    # No live stub PTY left behind.
    assert pty_manager.live_sessions() == []


def test_v4_walk_torn_down_temp_dirs(hc):
    """The walk's throwaway temp dirs are best-effort removed by teardown.

    The worktree base + skills dir (plain dirs) MUST be gone. The temp git
    project repo is best-effort: on Windows git's read-only packed objects can
    survive ``shutil.rmtree(ignore_errors=True)``; since it is an OS temp dir
    (never real data) we only require teardown to not raise. The no-orphan
    registry/PTY contract is asserted in test_v4_walk_never_8777_and_no_orphans.
    """
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "4")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v4_surface(report, object(), rnd_env)
        created = list(rnd_env.get("v3_temp_dirs", []))
        assert created, "the v4 walk should have recorded temp dirs"
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    # The plain (non-git) temp dirs — worktree base + skills dir — must be gone.
    for d in created:
        name = Path(d).name
        if name.startswith("anchor-hc-v4-wt-") or \
                name.startswith("anchor-hc-v4-skills-"):
            assert not Path(d).exists(), f"temp dir not cleaned: {d}"

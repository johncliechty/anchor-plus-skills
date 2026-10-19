"""Wave 10 — the daily healthcheck exercises the v3 "Mission Control" surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 10 — ... healthcheck": the self-test
walks the v3 surface FULLY STUBBED — `ANCHOR_PTY_BACKEND=stub` + the runner seam
(`ANCHOR_RUNNER_CMD` → tests/fake_claude.py), in a throwaway temp project/folder,
with a temp worktree base (never the build repo), never live claude / real PTY /
real preview spawn / real worktree off the build repo.

Walk: session registry register→reconcile(dead)→remove; stub-PTY round-trip +
terminal_session start→attach(replay)→input→kill; proactive project summary
(stubbed) → cached; preview pick_free_port (!=8777) + reap_orphans with an
injected dead pid (no spawn); handoff discover + record (survives a rescan).
"""
import importlib
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
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "gate_adapter", "rnd_registry", "effort_history",
                 "sessions", "lanes", "brownfield_scan", "report_viewer",
                 "summarizer", "deliverables", "rnd_terminal", "pty_manager",
                 "session_registry", "worktrees", "terminal_session", "handoff",
                 "preview_server", "anchor_marker", "anchor_gui",
                 "anchor_healthcheck"):
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


def test_check_rnd_v3_surface_is_green(hc):
    hc_mod, tmp_path = hc

    rnd_env = {
        "runner_cmd": hc_mod._fake_runner_cmd(),
        "folder": tmp_path / "hc-rnd-folder",
        "created_ids": [],
        "prev_runner_cmd": None,
    }
    rnd_env["folder"].mkdir(parents=True, exist_ok=True)

    report = hc_mod.Report()
    try:
        # server_proc is unused by the v3 walk (all in-process module ops); a
        # truthy placeholder matches the v2 walk's calling convention.
        hc_mod.check_rnd_v3_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    v3 = [c for c in report.checks if c[0] == "R&D v3 surface"]
    assert v3, "v3 check did not record a result"
    name, ok, detail = v3[0]
    assert ok, f"v3 surface check failed: {detail}"


def test_v3_walk_restores_pty_backend_env(hc, monkeypatch):
    """The walk must restore ANCHOR_PTY_BACKEND / ANCHOR_WORKTREE_BASE."""
    import os
    hc_mod, tmp_path = hc
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "sentinel-prev")
    rnd_env = {
        "runner_cmd": hc_mod._fake_runner_cmd(),
        "folder": tmp_path / "hc-rnd-folder2",
        "created_ids": [],
        "prev_runner_cmd": None,
    }
    rnd_env["folder"].mkdir(parents=True, exist_ok=True)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v3_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_PTY_BACKEND") == "sentinel-prev"
    assert "ANCHOR_WORKTREE_BASE" not in os.environ


def test_v3_walk_creates_no_real_data(hc):
    """The walk must not register any non-synthetic project nor touch 8777."""
    import preview_server
    hc_mod, tmp_path = hc
    rnd_env = {
        "runner_cmd": hc_mod._fake_runner_cmd(),
        "folder": tmp_path / "hc-rnd-folder3",
        "created_ids": [],
        "prev_runner_cmd": None,
    }
    rnd_env["folder"].mkdir(parents=True, exist_ok=True)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v3_surface(report, object(), rnd_env)
        # Every created id is synthetic and is cleaned up.
        import rnd_registry
        for pid in rnd_env["created_ids"]:
            proj = rnd_registry.get_project(pid)
            assert proj is None or "__healthcheck__" in proj.get("name", "")
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    # No leftover preview record bound to the live port.
    for rec in preview_server.load_previews().values():
        assert rec.get("port") != preview_server.LIVE_PORT


def test_v3_teardown_sweeps_session_rows_on_mid_walk_failure(hc, monkeypatch):
    """Reviewer B (MINOR): a mid-walk failure between register/remove must NOT
    orphan a synthetic session_registry row (or preview record) in real data.

    Simulate a step AFTER `session_registry.register_session` raising, and assert
    that after `_cleanup_synthetic_rnd` NO session row (and no preview record)
    remains keyed to any synthetic project id. Hermetic via the `hc` fixture's
    temp ANCHOR_DATA_DIR — real `.anchor` is never touched.
    """
    import session_registry
    import preview_server
    hc_mod, tmp_path = hc

    # Make the FIRST step after register (reconcile) blow up, so the freshly
    # registered "running" session leaks unless teardown sweeps it.
    boom = {"hit": False}
    real_reconcile = session_registry.reconcile

    def _boom_reconcile(*a, **k):
        boom["hit"] = True
        raise RuntimeError("synthetic mid-walk failure")

    monkeypatch.setattr(session_registry, "reconcile", _boom_reconcile)

    rnd_env = {
        "runner_cmd": hc_mod._fake_runner_cmd(),
        "folder": tmp_path / "hc-rnd-folder4",
        "created_ids": [],
        "prev_runner_cmd": None,
    }
    rnd_env["folder"].mkdir(parents=True, exist_ok=True)
    report = hc_mod.Report()
    try:
        # The walk catches the exception internally; it must NOT propagate, and
        # the pid must already be in created_ids by the time it fails.
        hc_mod.check_rnd_v3_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    assert boom["hit"], "the injected mid-walk failure did not fire"
    assert rnd_env["created_ids"], "no synthetic pid recorded to clean up"

    # After teardown: NO session row and NO preview record for any synthetic pid.
    real_reconcile  # keep a ref so we don't accidentally rely on the patched one
    for pid in rnd_env["created_ids"]:
        assert session_registry.list_sessions(project_id=pid) == [], \
            f"orphaned session_registry row(s) for synthetic pid {pid}"
        for rec in preview_server.load_previews().values():
            assert rec.get("project_id") != pid, \
                f"orphaned preview record for synthetic pid {pid}"

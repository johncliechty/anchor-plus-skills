"""Wave 8 — the daily healthcheck exercises the v10 "Live Handoff & Boneyard" surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 8 — ... healthcheck v10 surface": the
self-test walks the v10 surface FULLY STUBBED — `ANCHOR_PTY_BACKEND=stub` + the
runner seam swapped to the STREAM-JSON stub (`ANCHOR_RUNNER_CMD` →
tests/stub_streamjson.py) + a temp worktree base + a throwaway temp git project +
a temp data dir — never live claude / real PTY / :8777 / real data / network.

Walk: (a) PASTE substrate (W1 — pending → flush UNSENT once after greet);
(b) ADVANCE both-artifacts (W2 — plan→build writes HANDOFF.md + NEXT-PROMPT.md,
links, paste pending, idempotent); (c) GRASS (W3-W5 — two dev sessions + archive
+ grass_origin lineage + research→plan advance); (d) BONEYARD (W6 — capture on
kill / v9-delete [D10 ordering] / live-delete / grass-delete + search).

The test asserts the check PASSES + is hermetic: it RESTORES the forced env vars,
never binds :8777, leaves no orphan synthetic project / managed session / live
stub PTY, and tears down its temp dirs. If any of these FAIL it is a REAL bug in
`check_rnd_v10_surface` (fix the product code, not the test).
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


def test_check_rnd_v10_surface_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v10_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    v10 = [c for c in report.checks if c[0] == "R&D v10 surface"]
    assert v10, "v10 check did not record a result"
    name, ok, detail = v10[0]
    assert ok, f"v10 surface check failed: {detail}"


def test_v10_walk_restores_env(hc, monkeypatch):
    """The walk restores ANCHOR_PTY_BACKEND / WORKTREE_BASE / TERMINAL_SEED /
    ANCHOR_RUNNER_CMD to their prior values (snapshot → call → assert)."""
    hc_mod, tmp_path = hc
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "sentinel-prev")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    # WORKTREE_BASE / TERMINAL_SEED were deleted by the fixture → must stay absent.
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v10_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_PTY_BACKEND") == "sentinel-prev"
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    assert os.environ.get("ANCHOR_RUNNER_CMD") == prev_runner


def test_v10_walk_never_8777_no_orphans(hc):
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
        hc_mod.check_rnd_v10_surface(report, object(), rnd_env)
        # The only registry projects are the synthetic probe(s).
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


def test_v10_walk_torn_down_temp_dirs(hc):
    """The walk's throwaway worktree base + project dirs are recorded + removed."""
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "4")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v10_surface(report, object(), rnd_env)
        created = list(rnd_env.get("v3_temp_dirs", []))
        assert created, "the v10 walk should have recorded temp dirs"
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    for d in created:
        if Path(d).name.startswith("anchor-hc-v10-wt-"):
            assert not Path(d).exists(), f"temp dir not cleaned: {d}"


def test_v10_walk_skips_without_stream_stub(hc, monkeypatch):
    """If the stream-json stub is absent the walk SKIPS green (never live claude)."""
    hc_mod, tmp_path = hc
    monkeypatch.setattr(hc_mod, "_streamjson_runner_cmd", lambda: None)
    rnd_env = _rnd_env(hc_mod, tmp_path, "5")
    report = hc_mod.Report()
    hc_mod.check_rnd_v10_surface(report, object(), rnd_env)
    v10 = [c for c in report.checks if c[0] == "R&D v10 surface"]
    assert v10 and v10[0][1] is True
    assert "skipped" in v10[0][2]


def test_v10_check_registered_in_main_dispatch():
    """check_rnd_v10_surface is wired into the healthcheck run (after v9)."""
    src = (Path(__file__).resolve().parent.parent
           / "anchor_healthcheck.py").read_text(encoding="utf-8")
    assert "check_rnd_v10_surface(report, server_proc, rnd_env)" in src, \
        "v10 surface check not called in main()"

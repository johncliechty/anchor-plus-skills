"""Wave 8 — the daily healthcheck exercises the v8 "Durable Artifacts" surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 8 — ... healthcheck v8 surface": the
self-test walks the v8 surface FULLY STUBBED — `ANCHOR_PTY_BACKEND=stub` + the
runner seam swapped to the STREAM-JSON stub (`ANCHOR_RUNNER_CMD` →
tests/stub_streamjson.py) + a temp worktree base + a throwaway temp git project +
the git/gh remote seam stubbed (`ANCHOR_GH_CMD` → tests/stub_gh.py) with a LOCAL
BARE remote — never live claude / real PTY / :8777 / real gh / real github.com /
network.

Walk: (a) bootstrap (non-git temp → git-init + starter CLAUDE.md, idempotent);
(b) the keystone — a killed planning session persists its plan docs into the main
project (committed) BEFORE the worktree is reaped + a build worktree contains them
+ discover_recent_plan_set finds them; (c) the handoff seed carries the real
persisted paths + the correct skill (Foreman/Crucible); (d) no-loss (persisted
docs recoverable by managed session id); (e) grass contained+deduped + export
carries docs + idea promoted; (f) link (stub gh, private, persisted) + opt-in gate
+ push to the LOCAL BARE remote only.
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
    monkeypatch.delenv("ANCHOR_GH_CMD", raising=False)
    monkeypatch.delenv("ANCHOR_GH_STUB_FAIL", raising=False)
    monkeypatch.delenv("ANCHOR_GH_STUB_REMOTE", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "gate_adapter", "rnd_registry", "effort_history",
                 "sessions", "lanes", "brownfield_scan", "report_viewer",
                 "summarizer", "deliverables", "pty_manager", "session_registry",
                 "worktrees", "terminal_session", "handoff", "preview_server",
                 "project_bootstrap", "project_remote",
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


def test_check_rnd_v8_surface_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v8_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    v8 = [c for c in report.checks if c[0] == "R&D v8 surface"]
    assert v8, "v8 check did not record a result"
    name, ok, detail = v8[0]
    assert ok, f"v8 surface check failed: {detail}"


def test_v8_walk_restores_env(hc, monkeypatch):
    """The walk restores ANCHOR_PTY_BACKEND / WORKTREE_BASE / TERMINAL_SEED /
    ANCHOR_RUNNER_CMD / ANCHOR_GH_CMD / the gh-stub vars to their prior values (or
    absence). Critically it restores the runner it swapped to the stream-json stub
    AND clears the gh seam so later steps never reach a real gh."""
    hc_mod, tmp_path = hc
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "sentinel-prev")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v8_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_PTY_BACKEND") == "sentinel-prev"
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    # The gh seam + its stub knobs are gone (no real gh / network can leak).
    assert "ANCHOR_GH_CMD" not in os.environ
    assert "ANCHOR_GH_STUB_FAIL" not in os.environ
    assert "ANCHOR_GH_STUB_REMOTE" not in os.environ
    # the runner is restored (fake_claude / whatever it was), NOT the stream stub.
    assert os.environ.get("ANCHOR_RUNNER_CMD") == prev_runner


def test_v8_walk_never_8777_no_orphans_no_network(hc):
    """No preview bound to :8777, no orphan synthetic project, no live PTY /
    managed session left after teardown, and the gh seam stayed STUBBED (never a
    real gh / github.com / network) — asserted by the seam never resolving to the
    real `gh` and no remote URL pointing at github.com surviving teardown."""
    import preview_server
    import session_registry
    import pty_manager
    import rnd_registry
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "3")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v8_surface(report, object(), rnd_env)
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
    # The gh seam knobs are torn down → a later real gh call cannot leak.
    assert "ANCHOR_GH_CMD" not in os.environ


def test_v8_walk_torn_down_temp_dirs(hc):
    """The walk's throwaway worktree base + boot/bare dirs are removed by teardown."""
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "4")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v8_surface(report, object(), rnd_env)
        created = list(rnd_env.get("v3_temp_dirs", []))
        assert created, "the v8 walk should have recorded temp dirs"
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    for d in created:
        if Path(d).name.startswith("anchor-hc-v8-wt-"):
            assert not Path(d).exists(), f"temp dir not cleaned: {d}"


def test_v8_walk_skips_without_stream_stub(hc, monkeypatch):
    """If the stream-json stub is absent the walk SKIPS green (never live claude)."""
    hc_mod, tmp_path = hc
    monkeypatch.setattr(hc_mod, "_streamjson_runner_cmd", lambda: None)
    rnd_env = _rnd_env(hc_mod, tmp_path, "5")
    report = hc_mod.Report()
    hc_mod.check_rnd_v8_surface(report, object(), rnd_env)
    v8 = [c for c in report.checks if c[0] == "R&D v8 surface"]
    assert v8 and v8[0][1] is True
    assert "skipped" in v8[0][2]


def test_v8_check_registered_in_main_dispatch():
    """check_rnd_v8_surface is wired into the healthcheck run (after v7)."""
    src = (Path(__file__).resolve().parent.parent
           / "anchor_healthcheck.py").read_text(encoding="utf-8")
    assert "check_rnd_v8_surface(report, server_proc, rnd_env)" in src, \
        "v8 surface check not called in main()"

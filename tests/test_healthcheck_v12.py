"""Wave 12 — the daily healthcheck exercises the v12 "Efforts" surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 12 — ... check_rnd_v12_surface": the
self-test walks the v12 surface FULLY STUBBED — ``ANCHOR_PTY_BACKEND=stub`` + the
runner seam swapped to the STREAM-JSON stub (``ANCHOR_RUNNER_CMD`` →
tests/stub_streamjson.py) + a temp worktree base + a throwaway temp git project +
a temp data dir — never live claude / real PTY / :8777 / real data / network, with
proactive summary OFF (so the background stage summary hard no-ops).

THE v11 LESSON applied to v12: the walk advances a real effort WORKTREE-ONLY (a
committed plan-set) and CONVERSATION-ONLY (the stub PTY buffer seeded, no file →
transcript snapshot), asserting session-id SET equality (zero mint) after EACH
advance, plus the retirement map (an effort gated off the legacy auto-advance; a
legacy record still mints), handoff_to_fresh (new session / SAME effort_id /
pending paste UNSENT), restart recovery ('interrupted', no auto-spawn), the effort
view, and grass one-session + ✕→Boneyard capture.

The test asserts the check PASSES + is hermetic: it RESTORES the forced env vars
(incl. ANCHOR_PROACTIVE_SUMMARY), never binds :8777, leaves no orphan synthetic
project / managed session / live stub PTY, and tears down its temp dirs. If any of
these FAIL it is a REAL bug in ``check_rnd_v12_surface`` (fix the product code, not
the test).
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
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "gate_adapter", "rnd_registry", "effort_history",
                 "sessions", "lanes", "brownfield_scan", "report_viewer",
                 "summarizer", "deliverables", "pty_manager", "session_registry",
                 "worktrees", "terminal_session", "handoff", "preview_server",
                 "project_bootstrap", "project_remote", "project_move",
                 "boneyard", "effort_view", "anchor_marker", "anchor_gui",
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


def test_check_rnd_v12_surface_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v12_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    v12 = [c for c in report.checks if c[0] == "R&D v12 surface"]
    assert v12, "v12 check did not record a result"
    name, ok, detail = v12[0]
    assert ok, f"v12 surface check failed: {detail}"


def test_v12_walk_restores_env(hc, monkeypatch):
    """The walk restores ANCHOR_PTY_BACKEND / WORKTREE_BASE / TERMINAL_SEED /
    ANCHOR_RUNNER_CMD / ANCHOR_PROACTIVE_SUMMARY to their prior values."""
    hc_mod, tmp_path = hc
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "sentinel-prev")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    assert "ANCHOR_PROACTIVE_SUMMARY" not in os.environ
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v12_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_PTY_BACKEND") == "sentinel-prev"
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    assert "ANCHOR_PROACTIVE_SUMMARY" not in os.environ
    assert os.environ.get("ANCHOR_RUNNER_CMD") == prev_runner


def test_v12_walk_never_8777_no_orphans(hc):
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
        hc_mod.check_rnd_v12_surface(report, object(), rnd_env)
        for pid in rnd_env["created_ids"]:
            proj = rnd_registry.get_project(pid)
            assert proj is None or "__healthcheck__" in proj.get("name", "")
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    for rec in preview_server.load_previews().values():
        assert rec.get("port") != preview_server.LIVE_PORT
    for pid in rnd_env["created_ids"]:
        assert session_registry.list_sessions(project_id=pid) == []
    assert pty_manager.live_sessions() == []


def test_v12_walk_torn_down_temp_dirs(hc):
    """The walk's throwaway worktree base + project dirs are recorded AND actually
    REMOVED by cleanup — including a temp git repo's read-only .git/objects, which a
    plain rmtree(ignore_errors=True) would leak on Windows (V12R1-01)."""
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "4")
    report = hc_mod.Report()
    hc_mod.check_rnd_v12_surface(report, object(), rnd_env)
    created = list(rnd_env.get("v3_temp_dirs", []))
    assert created, "the v12 walk should have recorded temp dirs"
    names = [Path(d).name for d in created]
    assert any(n.startswith("anchor-hc-v12-wt-") for n in names)
    assert any(n.startswith("anchor-hc-v12-proj-") for n in names)
    folder = rnd_env.get("folder")

    # Cleanup must actually REMOVE every recorded temp dir (no leak into %TEMP%).
    hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    leaked = [d for d in created if Path(d).exists()]
    if folder is not None and Path(folder).exists():
        leaked.append(folder)
    assert not leaked, f"cleanup leaked temp dirs (read-only files?): {leaked}"


def test_v12_walk_skips_without_stream_stub(hc, monkeypatch):
    """If the stream-json stub is absent the walk SKIPS green (never live claude)."""
    hc_mod, tmp_path = hc
    monkeypatch.setattr(hc_mod, "_streamjson_runner_cmd", lambda: None)
    rnd_env = _rnd_env(hc_mod, tmp_path, "5")
    report = hc_mod.Report()
    hc_mod.check_rnd_v12_surface(report, object(), rnd_env)
    v12 = [c for c in report.checks if c[0] == "R&D v12 surface"]
    assert v12 and v12[0][1] is True
    assert "skipped" in v12[0][2]


def test_v12_check_registered_in_main_dispatch():
    """check_rnd_v12_surface is wired into the healthcheck run (after v11.1)."""
    src = (Path(__file__).resolve().parent.parent
           / "anchor_healthcheck.py").read_text(encoding="utf-8")
    assert "check_rnd_v12_surface(report, server_proc, rnd_env)" in src, \
        "v12 surface check not called in main()"

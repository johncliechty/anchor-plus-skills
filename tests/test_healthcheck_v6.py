"""Wave 8 — the daily healthcheck exercises the v6 "Linked Pipeline" surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 8 — ... healthcheck v6 surface": the
self-test walks the v6 surface FULLY STUBBED — `ANCHOR_PTY_BACKEND=stub` + the
runner seam swapped to the STREAM-JSON stub (`ANCHOR_RUNNER_CMD` →
tests/stub_streamjson.py) for the summarizer round-trip, in a throwaway temp
project + temp git repo, with a temp worktree base (never the build repo), never
live claude / real PTY / :8777.

Walk: (1) summaries through the PRODUCTION stream-json envelope stub yield grounded
non-empty session (skill/prompts/actions) + project (objective) summaries, and a
SCHEMA_VERSION-stale empty cache heals on regenerate; (2) the linked chain —
research → linked planning → finish-with-plan → exactly-one auto build (idempotent),
asserting ordered chain_members [research, planning, build]; (3) the term_sessions
projection includes terminal-status sessions and stays SAFE.
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
    monkeypatch.delenv("STUB_STREAMJSON_CLAIMS", raising=False)
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


def test_check_rnd_v6_surface_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v6_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    v6 = [c for c in report.checks if c[0] == "R&D v6 surface"]
    assert v6, "v6 check did not record a result"
    name, ok, detail = v6[0]
    assert ok, f"v6 surface check failed: {detail}"


def test_v6_walk_restores_env(hc, monkeypatch):
    """The walk restores ANCHOR_PTY_BACKEND / WORKTREE_BASE / TERMINAL_SEED /
    ANCHOR_RUNNER_CMD / STUB_STREAMJSON_CLAIMS to their prior values (or absence).
    Critically it restores the runner it swapped to the stream-json stub so later
    healthcheck steps see fake_claude again."""
    hc_mod, tmp_path = hc
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "sentinel-prev")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v6_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_PTY_BACKEND") == "sentinel-prev"
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    assert "ANCHOR_TERMINAL_SEED" not in os.environ
    assert "STUB_STREAMJSON_CLAIMS" not in os.environ
    # the runner is restored (fake_claude / whatever it was), NOT the stream stub.
    assert os.environ.get("ANCHOR_RUNNER_CMD") == prev_runner


def test_v6_walk_never_8777_and_no_orphans(hc):
    """No preview bound to :8777, no leftover synthetic project, and no live PTY /
    managed session left running after teardown."""
    import preview_server
    import session_registry
    import pty_manager
    import rnd_registry
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "3")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v6_surface(report, object(), rnd_env)
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


def test_v6_walk_torn_down_temp_dirs(hc):
    """The walk's throwaway worktree base (a plain dir) is removed by teardown."""
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "4")
    report = hc_mod.Report()
    try:
        hc_mod.check_rnd_v6_surface(report, object(), rnd_env)
        created = list(rnd_env.get("v3_temp_dirs", []))
        assert created, "the v6 walk should have recorded temp dirs"
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    for d in created:
        if Path(d).name.startswith("anchor-hc-v6-wt-"):
            assert not Path(d).exists(), f"temp dir not cleaned: {d}"


def test_v6_walk_skips_without_stream_stub(hc, monkeypatch):
    """If the stream-json stub is absent the walk SKIPS green (never live claude)."""
    hc_mod, tmp_path = hc
    monkeypatch.setattr(hc_mod, "_streamjson_runner_cmd", lambda: None)
    rnd_env = _rnd_env(hc_mod, tmp_path, "5")
    report = hc_mod.Report()
    hc_mod.check_rnd_v6_surface(report, object(), rnd_env)
    v6 = [c for c in report.checks if c[0] == "R&D v6 surface"]
    assert v6 and v6[0][1] is True
    assert "skipped" in v6[0][2]

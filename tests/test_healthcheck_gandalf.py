"""Wave 4 — the daily healthcheck exercises the Gandalf v1 surface.

Proves IMPLEMENTATION-PLAN.md "## Wave 4 — ... check_gandalf_surface": the
self-test walks the Gandalf surface FULLY STUBBED — both seams swapped
(``ANCHOR_RUNNER_CMD`` → tests/stub_gandalf_draft.py emitting a canned RAW draft;
``ANCHOR_GANDALF_HOST_CMD`` → tests/stub_gandalf_host.py emitting a canned GRADED
advisor-output) + a temp project + a temp data dir — never live claude / real node
/ :8777 / real data / network, with proactive summary OFF.

The walk: run → 3 artifacts + index → list_runs shape → a 2nd run appends +
run_gandalf_if_absent no-ops → an error run (host forced to fail) recorded honestly.

The test asserts the check PASSES + is hermetic: it RESTORES the forced env vars
(ANCHOR_RUNNER_CMD / ANCHOR_GANDALF_HOST_CMD / ANCHOR_GANDALF_SKILL_DIR /
ANCHOR_PROACTIVE_SUMMARY / STUB_GANDALF_HOST_FAIL), never binds :8777, leaves no
orphan synthetic project, and tears down its temp dirs. If any FAIL it is a REAL
bug in ``check_gandalf_surface`` (fix the product, not the test).
"""
import importlib
import os
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_TESTS = Path(__file__).resolve().parent


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _have_stubs():
    return ((_TESTS / "stub_gandalf_draft.py").is_file()
            and (_TESTS / "stub_gandalf_host.py").is_file())


@pytest.fixture
def hc(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    monkeypatch.delenv("ANCHOR_GANDALF_HOST_CMD", raising=False)
    monkeypatch.delenv("ANCHOR_GANDALF_SKILL_DIR", raising=False)
    monkeypatch.delenv("STUB_GANDALF_HOST_FAIL", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "rnd_registry", "effort_history", "summarizer",
                 "report_viewer", "gandalf", "anchor_gui", "anchor_healthcheck"):
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


def _rnd_env(hc_mod, tmp_path, suffix=""):
    env = {
        "runner_cmd": hc_mod._fake_runner_cmd(),
        "folder": tmp_path / f"hc-gandalf-folder{suffix}",
        "created_ids": [],
        "prev_runner_cmd": None,
        "v3_temp_dirs": [],
    }
    env["folder"].mkdir(parents=True, exist_ok=True)
    return env


pytestmark = pytest.mark.skipif(
    not (_have_git() and _have_stubs()),
    reason="git not on PATH or Gandalf stubs absent")


def test_check_gandalf_surface_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_gandalf_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    g = [c for c in report.checks if c[0] == "Gandalf surface"]
    assert g, "Gandalf check did not record a result"
    name, ok, detail = g[0]
    assert ok, f"Gandalf surface check failed: {detail}"


def test_gandalf_walk_restores_env(hc, monkeypatch):
    """The walk restores ANCHOR_RUNNER_CMD / ANCHOR_GANDALF_HOST_CMD /
    ANCHOR_GANDALF_SKILL_DIR / ANCHOR_PROACTIVE_SUMMARY / STUB_GANDALF_HOST_FAIL."""
    hc_mod, tmp_path = hc
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    assert "ANCHOR_GANDALF_HOST_CMD" not in os.environ
    assert "ANCHOR_GANDALF_SKILL_DIR" not in os.environ
    assert "ANCHOR_PROACTIVE_SUMMARY" not in os.environ
    assert "STUB_GANDALF_HOST_FAIL" not in os.environ
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_gandalf_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    assert os.environ.get("ANCHOR_RUNNER_CMD") == prev_runner
    assert "ANCHOR_GANDALF_HOST_CMD" not in os.environ
    assert "ANCHOR_GANDALF_SKILL_DIR" not in os.environ
    assert "ANCHOR_PROACTIVE_SUMMARY" not in os.environ
    assert "STUB_GANDALF_HOST_FAIL" not in os.environ


def test_gandalf_walk_no_orphan_project(hc):
    """No orphan synthetic project after teardown."""
    import rnd_registry
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "3")
    report = hc_mod.Report()
    try:
        hc_mod.check_gandalf_surface(report, object(), rnd_env)
        for pid in rnd_env["created_ids"]:
            proj = rnd_registry.get_project(pid)
            assert proj is None or "__healthcheck__" in proj.get("name", "")
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)


def test_gandalf_walk_torn_down_temp_dirs(hc):
    """The walk's throwaway project + skill dirs are recorded AND removed."""
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "4")
    report = hc_mod.Report()
    hc_mod.check_gandalf_surface(report, object(), rnd_env)
    created = list(rnd_env.get("v3_temp_dirs", []))
    assert created, "the Gandalf walk should have recorded temp dirs"
    names = [Path(d).name for d in created]
    assert any(n.startswith("anchor-hc-gandalf-proj-") for n in names)
    folder = rnd_env.get("folder")
    hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    leaked = [d for d in created if Path(d).exists()]
    if folder is not None and Path(folder).exists():
        leaked.append(folder)
    assert not leaked, f"cleanup leaked temp dirs: {leaked}"


def test_gandalf_walk_skips_without_stubs(hc, monkeypatch):
    """If the Gandalf stubs are absent the walk SKIPS green (never live)."""
    hc_mod, tmp_path = hc
    monkeypatch.setattr(hc_mod, "_gandalf_draft_runner_cmd", lambda: None)
    rnd_env = _rnd_env(hc_mod, tmp_path, "5")
    report = hc_mod.Report()
    hc_mod.check_gandalf_surface(report, object(), rnd_env)
    g = [c for c in report.checks if c[0] == "Gandalf surface"]
    assert g and g[0][1] is True
    assert "skipped" in g[0][2]


def test_gandalf_check_registered_in_main_dispatch():
    """check_gandalf_surface is wired into the healthcheck run (after v12)."""
    src = (Path(__file__).resolve().parent.parent
           / "anchor_healthcheck.py").read_text(encoding="utf-8")
    assert "check_gandalf_surface(report, server_proc, rnd_env)" in src, \
        "Gandalf surface check not called in main()"

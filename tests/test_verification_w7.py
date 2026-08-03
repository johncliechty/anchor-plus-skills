"""W7 — Verification: the daily healthcheck walks capture+finalize + the live
drift tripwire (Honest Telemetry).

Proves IMPLEMENTATION-PLAN.md "## Wave 7 — W7 — Verification, Deploy, and the
Measured Undercount" — the SOURCE deliverables an EXECUTE agent can pin under the
standard ``pytest tests/ -v`` gate (the live deploy smoke-run + the real-project
undercount numbers are deploy-time, recorded in the execution log):

  * ``check_telemetry_capture_surface`` — FULLY STUBBED (temp ANCHOR_SIDECAR_DIR
    with the PINNED fixtures + stub PTY + fake runner + temp git repo): the CLEAN
    leg finalizes ONE ``measured`` RUN cost record with EXACT fixture totals; the
    CORRUPTED leg finalizes ONE RED-classified ``capture-failed`` record with the
    lifecycle intact; the new telemetry routes are auth-enumerated. Never :8777,
    never a real ``~/.claude`` home path (the W2 fail-closed seam holds).
  * ``check_sidecar_drift_tripwire`` — split severity, deterministic + load
    independent: zero sidecars → ``report.warn`` (never red); a PRESENT but
    unparseable / zero-usage sidecar → ``report.check(False)`` RED; clean recent
    sidecars → green.
  * Both are wired into ``main()``; every new telemetry route is token-gated
    (the auth-enumeration BLOCKER contract).

Hermetic: temp data dir, temp ANCHOR_SIDECAR_DIR (fixture/temp only), stub PTY,
the fake runner, a temp git repo — NEVER ``:8777`` / real data / a live model /
the real home store. If a check FAILS it is a REAL bug in the product code (fix
the source, not the test).
"""
import importlib
import json
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sidecar"
EXPECTED = json.loads((FIXTURES / "EXPECTED.json").read_text(encoding="utf-8"))
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
    monkeypatch.delenv("ANCHOR_SIDECAR_DIR", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SESSION_ID_FLAG", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("paths", "usage_ledger", "job_runner", "gate_adapter",
                 "rnd_registry", "effort_history", "sessions", "lanes",
                 "brownfield_scan", "report_viewer", "summarizer", "deliverables",
                 "pty_manager", "session_registry", "worktrees",
                 "terminal_session", "usage_capture", "handoff", "preview_server",
                 "project_bootstrap", "boneyard", "effort_view", "route_table",
                 "anchor_gui", "anchor_healthcheck"):
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


# ══════════════════════════════════════════════════════════════════════════════
# 1) The stubbed capture+finalize walk — clean MEASURED leg + corrupted RED leg
# ══════════════════════════════════════════════════════════════════════════════

def test_capture_surface_walk_is_green(hc):
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path)
    report = hc_mod.Report()
    try:
        hc_mod.check_telemetry_capture_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)

    got = [c for c in report.checks
           if c[0] == "telemetry capture+finalize walk (W7)"]
    assert got, "capture surface check did not record a result"
    name, ok, detail = got[0]
    assert ok, f"capture surface walk failed: {detail}"
    assert "skipped" not in detail, f"walk should not have skipped: {detail}"


def test_capture_surface_walk_leaves_no_ledger_or_sidecar_env(hc):
    """The walk cleans its throwaway ledger docs and RESTORES the sidecar env so
    the later drift tripwire (and real data) are untouched."""
    import os
    hc_mod, tmp_path = hc
    assert "ANCHOR_SIDECAR_DIR" not in os.environ
    assert "ANCHOR_PTY_BACKEND" not in os.environ
    rnd_env = _rnd_env(hc_mod, tmp_path, "2")
    report = hc_mod.Report()
    try:
        hc_mod.check_telemetry_capture_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    # Forced env restored (popped, since they were unset before).
    assert "ANCHOR_SIDECAR_DIR" not in os.environ
    assert "ANCHOR_PTY_BACKEND" not in os.environ
    assert "ANCHOR_WORKTREE_BASE" not in os.environ
    # The ledger dir under the temp data dir holds no leaked throwaway docs.
    import usage_ledger
    led = usage_ledger.ledger_dir()
    leaked = list(led.glob("*.json")) if led.exists() else []
    assert not leaked, f"walk leaked ledger docs: {leaked}"


def test_capture_surface_walk_never_binds_8777_no_orphans(hc):
    import pty_manager
    import session_registry
    hc_mod, tmp_path = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "3")
    report = hc_mod.Report()
    try:
        hc_mod.check_telemetry_capture_surface(report, object(), rnd_env)
    finally:
        hc_mod._cleanup_synthetic_rnd(rnd_env, report)
    for pid in rnd_env["created_ids"]:
        assert session_registry.list_sessions(project_id=pid) == []
    assert pty_manager.live_sessions() == []


# ══════════════════════════════════════════════════════════════════════════════
# 2) The split-severity live drift tripwire
# ══════════════════════════════════════════════════════════════════════════════

def _fx(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_drift_tripwire_zero_sidecars_is_warn_not_red(hc, tmp_path, monkeypatch):
    """Zero sidecars found → report.warn (environmental) — NEVER reddens."""
    hc_mod, _ = hc
    empty = tmp_path / "sc-empty"
    empty.mkdir()
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(empty))
    report = hc_mod.Report()
    hc_mod.check_sidecar_drift_tripwire(report)
    assert not report.has_issues, "zero-sidecars must not redden the banner"
    warned = [w for w in report.warnings if "sidecar drift tripwire" in w]
    assert warned, f"expected a warn note; warnings={report.warnings}"


def test_drift_tripwire_clean_recent_sidecar_is_green(hc, tmp_path, monkeypatch):
    hc_mod, _ = hc
    sc = tmp_path / "sc-clean"
    sc.mkdir()
    (sc / "1a2b3c4d-0001-4a00-8a00-000000000001.jsonl").write_text(
        _fx("canonical_3turn.jsonl"), encoding="utf-8")
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(sc))
    report = hc_mod.Report()
    hc_mod.check_sidecar_drift_tripwire(report)
    assert not report.has_issues, f"clean sidecar reddened: {report.issues}"
    got = [c for c in report.checks if c[0] == "sidecar drift tripwire (W7)"]
    assert got and got[0][1] is True


@pytest.mark.parametrize("fixture", ["corrupted_zero_usage.jsonl",
                                     "corrupted_malformed.jsonl"])
def test_drift_tripwire_present_but_unparseable_is_red(hc, tmp_path, monkeypatch,
                                                       fixture):
    """A PRESENT-but-unparseable / zero-usage sidecar → report.check(False) RED,
    deterministic (no timing) and load-independent."""
    hc_mod, _ = hc
    sc = tmp_path / f"sc-{fixture}"
    sc.mkdir()
    (sc / "drifted.jsonl").write_text(_fx(fixture), encoding="utf-8")
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(sc))
    report = hc_mod.Report()
    hc_mod.check_sidecar_drift_tripwire(report)
    assert report.has_issues, "present-but-unparseable sidecar must go RED"
    red = [i for i in report.issues if "sidecar drift tripwire" in i]
    assert red, f"expected the drift check RED; issues={report.issues}"
    # The red path documents its meaning (capture never halts, nothing zeroed).
    assert "nothing zeroed" in red[0]


def test_drift_tripwire_skips_hermetic_without_explicit_dir(hc, monkeypatch):
    """Under pytest with NO explicit ANCHOR_SIDECAR_DIR the tripwire never reads a
    real home path — it warns-skip instead (the fail-closed diagnostic seam)."""
    hc_mod, _ = hc
    monkeypatch.delenv("ANCHOR_SIDECAR_DIR", raising=False)
    assert hc_mod._drift_scan_root() is None
    report = hc_mod.Report()
    hc_mod.check_sidecar_drift_tripwire(report)
    assert not report.has_issues
    warned = [w for w in report.warnings if "sidecar drift tripwire" in w]
    assert warned


# ══════════════════════════════════════════════════════════════════════════════
# 3) Auth-enumeration of the new telemetry routes + main() wiring
# ══════════════════════════════════════════════════════════════════════════════

def test_new_telemetry_routes_are_token_gated(hc):
    hc_mod, _ = hc
    ok, detail = hc_mod._telemetry_routes_auth_enumeration()
    assert ok, f"a new telemetry route escaped the auth net: {detail}"


def test_auth_enumeration_flags_a_missing_route(hc, monkeypatch):
    """The enumeration is a real BLOCKER — dropping a route makes it fail."""
    hc_mod, _ = hc
    import route_table
    pruned = [r for r in route_table.ROUTES
              if r.pattern != "/api/rnd/usage_ledger"]
    monkeypatch.setattr(route_table, "ROUTES", pruned)
    ok, detail = hc_mod._telemetry_routes_auth_enumeration()
    assert not ok
    assert "usage_ledger" in detail


def test_both_w7_checks_registered_in_main():
    src = (Path(__file__).resolve().parent.parent
           / "anchor_healthcheck.py").read_text(encoding="utf-8")
    assert "check_telemetry_capture_surface(report, server_proc, rnd_env)" in src
    assert "check_sidecar_drift_tripwire(report)" in src


def test_capture_surface_skips_green_without_runner(hc, tmp_path):
    """No stub runner → the walk SKIPS green (never live claude)."""
    hc_mod, _ = hc
    rnd_env = _rnd_env(hc_mod, tmp_path, "9")
    rnd_env["runner_cmd"] = None
    report = hc_mod.Report()
    hc_mod.check_telemetry_capture_surface(report, object(), rnd_env)
    got = [c for c in report.checks
           if c[0] == "telemetry capture+finalize walk (W7)"]
    assert got and got[0][1] is True and "skipped" in got[0][2]

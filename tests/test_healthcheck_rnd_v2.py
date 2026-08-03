"""Wave 8 — the daily healthcheck exercises the v2 R&D surface (stubbed).

Proves IMPLEMENTATION-PLAN.md "## Wave 8 — ... healthcheck": the self-test walks
the v2 endpoints (status_line shape, /summary, regenerate_summary, term_*,
pin_deliverable, add_idea, promote_inbox, reconcile preview) and a synthetic
terminal session through start -> input -> discover -> adopt — ALL stubbed via
ANCHOR_RUNNER_CMD -> tests/fake_claude.py (NEVER live claude).

Runs `check_rnd_v2_surface` directly against a throwaway anchor_gui server on an
OS-assigned free port with a tmp ANCHOR_DATA_DIR, so real data is never touched
and the existing synthetic __healthcheck__ filtering is unaffected.
"""
import importlib
import threading
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def hc(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    # Reload the v2 modules against the tmp data dir.
    for name in ("job_runner", "gate_adapter", "rnd_registry", "effort_history",
                 "sessions", "lanes", "brownfield_scan", "report_viewer",
                 "summarizer", "deliverables", "rnd_terminal", "anchor_gui",
                 "anchor_healthcheck"):
        importlib.import_module(name)
        importlib.reload(importlib.import_module(name))
    import anchor_gui
    gui = importlib.import_module("anchor_gui")
    hc_mod = importlib.import_module("anchor_healthcheck")
    yield gui, hc_mod, tmp_path
    import job_runner
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


def test_check_rnd_v2_surface_is_green(hc, monkeypatch):
    gui, hc_mod, tmp_path = hc

    # Boot a throwaway server on an OS-assigned free port; point the healthcheck
    # globals at that port (check_rnd_v2_surface reads TEST_PORT).
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    monkeypatch.setattr(hc_mod, "TEST_PORT", port, raising=False)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    rnd_folder = tmp_path / "hc-rnd-folder"
    rnd_folder.mkdir(parents=True, exist_ok=True)
    rnd_env = {
        "runner_cmd": hc_mod._fake_runner_cmd(),
        "folder": rnd_folder,
        "created_ids": [],
        "prev_runner_cmd": None,
    }

    report = hc_mod.Report()
    try:
        # server_proc is only used as a "did the server boot" sentinel; a truthy
        # placeholder is enough since we drive HTTP against the live thread-server.
        hc_mod.check_rnd_v2_surface(report, object(), rnd_env)
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)

    # The v2 check must be GREEN.
    rnd_checks = [c for c in report.checks if c[0] == "R&D v2 surface"]
    assert rnd_checks, "v2 check did not record a result"
    name, ok, detail = rnd_checks[0]
    assert ok, f"v2 surface check failed: {detail}"


def test_fake_runner_resolves(hc):
    _gui, hc_mod, _tmp = hc
    cmd = hc_mod._fake_runner_cmd()
    assert cmd and "fake_claude.py" in cmd

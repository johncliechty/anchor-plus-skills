"""Synthetic health probes choose their fixture protocol, preserving user prefs."""
import importlib
import json
import os
import threading

import pytest


@pytest.fixture
def chatgpt_healthcheck(tmp_path, monkeypatch):
    import anchor_settings
    import job_runner
    import model_policy
    import paths
    import pty_manager

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_HEALTHCHECK", "1")
    monkeypatch.setenv("ANCHOR_DEFAULT_CLI", "chatgpt")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    preferences = {
        "default_cli": "chatgpt", "coding_family": "chatgpt",
        "review_family": "claude", "settings_revision": 17,
    }
    mirror = tmp_path / "model_prefs.json"
    primary = data / "settings.json"
    for target in (mirror, primary):
        target.write_text(json.dumps(preferences), encoding="utf-8")
    monkeypatch.setattr(anchor_settings, "mirror_path", lambda: mirror)
    before = {target: target.read_bytes() for target in (mirror, primary)}

    def no_live_policy(*args, **kwargs):
        pytest.fail("Synthetic health probe attempted live model discovery")

    monkeypatch.setattr(model_policy, "resolve", no_live_policy)
    paths.ensure_data_dirs()
    import anchor_healthcheck
    hc = importlib.reload(anchor_healthcheck)
    yield hc, tmp_path
    assert anchor_settings.get_launch_settings()["coding_family"] == "chatgpt"
    assert {target: target.read_bytes() for target in before} == before
    assert os.environ["ANCHOR_DEFAULT_CLI"] == "chatgpt"
    job_runner._reset_live_table_for_tests()
    pty_manager._reset_live_table_for_tests()


@pytest.mark.parametrize("check_name", [
    "check_rnd_v2_surface", "check_rnd_v3_surface", "check_rnd_v4_surface",
    "check_rnd_v5_surface", "check_rnd_v6_surface", "check_rnd_v7_surface",
    "check_supervisor_seam",
    "check_supervisor_live_probes",
])
def test_fixture_probes_ignore_saved_chatgpt_protocol(chatgpt_healthcheck, monkeypatch,
                                                    check_name):
    hc, tmp_path = chatgpt_healthcheck
    report = hc.Report()
    if check_name.startswith("check_rnd_"):
        folder = tmp_path / "probe-project"
        folder.mkdir()
        rnd_env = {"runner_cmd": hc._fake_runner_cmd(), "folder": folder,
                   "created_ids": []}
        server = thread = None
        try:
            monkeypatch.setenv("ANCHOR_RUNNER_CMD", rnd_env["runner_cmd"])
            if check_name == "check_rnd_v2_surface":
                import anchor_gui
                # This synthetic server shares cached modules with earlier tests;
                # a standalone server would import the current data-directory path.
                monkeypatch.setattr(anchor_gui, "INBOX_MD", hc.DATA_DIR / "INBOX.md")
                server = anchor_gui.make_server("127.0.0.1", 0)
                monkeypatch.setattr(hc, "TEST_PORT", server.server_address[1])
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
            getattr(hc, check_name)(report, object(), rnd_env)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            hc._cleanup_synthetic_rnd(rnd_env, report)
    else:
        getattr(hc, check_name)(report)
    assert report.checks
    assert all(ok for _, ok, _ in report.checks), report.checks
    assert not any("skipped" in detail for _, _, detail in report.checks)


def test_supervisor_probe_reports_rejected_launch(chatgpt_healthcheck, monkeypatch):
    import supervisor

    hc, _ = chatgpt_healthcheck
    monkeypatch.setattr(supervisor.ExternalSupervisor, "launch",
                        lambda *args, **kwargs: {"ok": False,
                                                 "error": "fixture launch rejected"})
    report = hc.Report()
    hc.check_supervisor_live_probes(report)
    assert len(report.checks) == 1
    _, ok, detail = report.checks[0]
    assert not ok
    assert "fixture launch rejected" in detail
    assert "KeyError" not in detail

"""Regression tests for Merrill's Windows 11 installation log (2026-10-19).

Covers:
1. Automatic Mark-of-the-Web (:Zone.Identifier) unblocking in anchor_shell.py before .NET / WebView2 loads.
2. JS promise rejection handling in connect.py _SCRIPT so errors never hang silently on "Connecting…".
3. Resilient onboard_bootstrap resolution + automatic local service startup / GitHub pull in select_mother_ship.
4. PyInstaller build_exe.ps1 bundling of root modules (onboard_bootstrap) + Unblock-File pass.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "shell") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "shell"))

from shell import anchor_shell, connect


@pytest.mark.skipif(os.name != "nt", reason="NTFS Alternate Data Streams are Windows-only")
def test_unblock_extracted_files_strips_zone_identifier_streams(tmp_path):
    pkg = tmp_path / "Anchor-Merrill-Share"
    internal = pkg / "Anchor" / "_internal" / "webview" / "lib"
    internal.mkdir(parents=True)
    dll = internal / "Microsoft.Web.WebView2.Core.dll"
    dll.write_bytes(b"MZ-fake-dll")
    launcher = pkg / "launch_anchor_dashboard.py"
    launcher.write_text("# launcher\n", encoding="utf-8")

    ads_dll = str(dll) + ":Zone.Identifier"
    ads_launcher = str(launcher) + ":Zone.Identifier"
    Path(ads_dll).write_text("[ZoneTransfer]\nZoneId=3\n", encoding="utf-8")
    Path(ads_launcher).write_text("[ZoneTransfer]\nZoneId=3\n", encoding="utf-8")
    assert Path(ads_dll).exists()
    assert Path(ads_launcher).exists()

    removed = anchor_shell.unblock_extracted_files([pkg / "Anchor", pkg])
    assert removed >= 2
    assert not Path(ads_dll).exists()
    assert not Path(ads_launcher).exists()
    assert dll.read_bytes() == b"MZ-fake-dll"


def test_connect_script_catches_promise_rejections():
    page = connect.first_launch_page()
    assert ".catch(" in page
    assert "Connecting" in page


def test_select_mother_ship_auto_starts_local_package_when_present(tmp_path, monkeypatch):
    data_dir = tmp_path / "shell-data"
    pkg_dir = tmp_path / "Anchor-Merrill-Share"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "launch_anchor_dashboard.py").write_text("# launcher\n", encoding="utf-8")
    (pkg_dir / "anchor_gui.py").write_text("# gui\n", encoding="utf-8")

    state = {"running": False, "spawned": []}

    def fake_reachable(address, timeout=5.0):
        return address == connect.LOCAL and state["running"]

    def fake_run(cmd, **kwargs):
        state["spawned"].append(cmd)
        state["running"] = True
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(connect, "reachable", fake_reachable)
    monkeypatch.setattr(connect.subprocess, "run", fake_run)

    res = connect.select_mother_ship(data_dir, pkg_dir, auto_bootstrap=False)
    assert res["ok"] is True
    assert res["address"] == connect.LOCAL
    assert res["path"] == "/setup"
    assert state["spawned"], "Expected launch_anchor_dashboard.py to be invoked automatically"
    assert any("launch_anchor_dashboard.py" in str(part) for part in state["spawned"][0])
    assert connect.load_address(data_dir) == connect.LOCAL


def test_select_mother_ship_auto_pulls_when_frozen_and_no_local_package(tmp_path, monkeypatch):
    data_dir = tmp_path / "shell-data"
    empty_exe_dir = tmp_path / "standalone-exe"
    empty_exe_dir.mkdir(parents=True)

    state = {"running": False, "pulled": False}

    def fake_reachable(address, timeout=5.0):
        return address == connect.LOCAL and state["running"]

    def fake_ensure_local(package_root=None, check_system_dirs=False, probe_fn=None):
        if state["pulled"]:
            state["running"] = True
            return {"ok": True, "started": True, "root": str(tmp_path / "pulled")}
        return {"ok": False, "started": False, "root": ""}

    def fake_pull(target_dir=None, repo_url=connect.DEFAULT_GITHUB_REPO, run_onboard=True, runner_fn=None, workspace_dir=None):
        state["pulled"] = True
        state["running"] = True
        return {"ok": True, "target_dir": str(tmp_path / "pulled"), "onboard_ready": True}

    monkeypatch.setattr(connect, "reachable", fake_reachable)
    monkeypatch.setattr(connect, "ensure_local_service_running", fake_ensure_local)
    monkeypatch.setattr(connect, "pull_and_install_mothership", fake_pull)

    res = connect.select_mother_ship(data_dir, empty_exe_dir, auto_bootstrap=True)
    assert res["ok"] is True
    assert res["installed"] is True
    assert res["address"] == connect.LOCAL
    assert res["path"] == "/setup"
    assert state["pulled"] is True
    assert connect.load_address(data_dir) == connect.LOCAL


def test_build_exe_ps1_includes_root_path_and_unblock():
    ps1 = (REPO_ROOT / "shell" / "build_exe.ps1").read_text(encoding="utf-8")
    assert "--paths $root" in ps1
    assert "--hidden-import onboard_bootstrap" in ps1
    assert "Unblock-File" in ps1

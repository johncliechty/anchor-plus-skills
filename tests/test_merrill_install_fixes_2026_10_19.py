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
    assert "arg===undefined?pywebview.api[name]():pywebview.api[name](arg)" in page


def test_host_api_accepts_zero_or_undefined_arg_from_pywebview(tmp_path, monkeypatch):
    data_dir = tmp_path / "shell-data"
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir(parents=True)
    monkeypatch.setattr(anchor_shell, "DATA", data_dir)
    monkeypatch.setattr(anchor_shell, "ROOT", pkg_dir)
    monkeypatch.setattr(connect, "reachable", lambda addr, timeout=5.0: True)

    host = anchor_shell.HostApi()
    urls, pages = [], []
    host.bind(SimpleNamespace(load_url=urls.append, load_html=pages.append))

    # Must succeed both with 0 args and when pywebview passes (None,) for undefined arg
    assert host.select_mother_ship() == ""
    assert host.select_mother_ship(None) == ""
    assert urls[-1] == connect.LOCAL + "/setup"
    assert host.change_address(None) == ""
    assert host.retry(None) == ""


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
    assert any("launch_anchor_dashboard.py" in str(part) for cmd in state["spawned"] for part in cmd)
    assert connect.load_address(data_dir) == connect.LOCAL


def test_select_mother_ship_auto_pulls_when_frozen_and_no_local_package(tmp_path, monkeypatch):
    data_dir = tmp_path / "shell-data"
    empty_exe_dir = tmp_path / "standalone-exe"
    empty_exe_dir.mkdir(parents=True)

    state = {"running": False, "pulled": False}

    def fake_reachable(address, timeout=5.0):
        return address == connect.LOCAL and state["running"]

    def fake_inspect(package_root=None, check_system_dirs=True, target_version=None, **kwargs):
        return {
            "target_version": connect.BUNDLED_VERSION,
            "root": str(tmp_path / "pulled") if state["pulled"] else "",
            "disk_root": str(tmp_path / "pulled") if state["pulled"] else "",
            "disk_version": connect.BUNDLED_VERSION if state["pulled"] else "0.0.0",
            "running": state["running"],
            "running_version": connect.BUNDLED_VERSION if state["running"] else "0.0.0",
            "needs_install": not state["pulled"],
            "needs_upgrade": False,
            "needs_install_or_upgrade": not state["pulled"],
            "reason": "" if state["pulled"] else "not_installed",
        }

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
    monkeypatch.setattr(connect, "inspect_local_anchor_version", fake_inspect)
    monkeypatch.setattr(connect, "ensure_local_service_running", fake_ensure_local)
    monkeypatch.setattr(connect, "pull_and_install_mothership", fake_pull)

    res = connect.select_mother_ship(data_dir, empty_exe_dir, auto_bootstrap=True)
    assert res["ok"] is True
    assert res["installed"] is True
    assert res["upgraded"] is True
    assert res["address"] == connect.LOCAL
    assert res["path"] == "/setup"
    assert state["pulled"] is True
    assert connect.load_address(data_dir) == connect.LOCAL


def test_select_mother_ship_detects_older_running_version_upgrades_and_opens_setup(tmp_path, monkeypatch):
    data_dir = tmp_path / "shell-data"
    old_pkg = tmp_path / "old-anchor"
    old_pkg.mkdir(parents=True)
    (old_pkg / "anchor_gui.py").write_text("# old gui\n", encoding="utf-8")
    (old_pkg / "launch_anchor_dashboard.py").write_text("# old launcher\n", encoding="utf-8")
    (old_pkg / "VERSION").write_text("1.3.2\n", encoding="utf-8")

    state = {"stopped": 0, "pulled": False, "running_ver": "1.3.2"}

    def fake_running_ver(address=connect.LOCAL, timeout=2.0):
        return {"reachable": True, "version": state["running_ver"]}

    def fake_stop(port=8777):
        state["stopped"] += 1
        return 1

    def fake_pull(target_dir=None, repo_url=connect.DEFAULT_GITHUB_REPO, run_onboard=True, runner_fn=None, workspace_dir=None):
        state["pulled"] = True
        (old_pkg / "VERSION").write_text(connect.BUNDLED_VERSION + "\n", encoding="utf-8")
        state["running_ver"] = connect.BUNDLED_VERSION
        return {"ok": True, "target_dir": str(old_pkg), "onboard_ready": True}

    monkeypatch.setattr(connect, "read_running_version", fake_running_ver)
    monkeypatch.setattr(connect, "stop_local_service_on_port", fake_stop)
    monkeypatch.setattr(connect, "pull_and_install_mothership", fake_pull)
    monkeypatch.setattr(connect, "reachable", lambda addr, timeout=5.0: True)

    vinfo = connect.inspect_local_anchor_version(old_pkg, check_system_dirs=False, target_version="1.4.0")
    assert vinfo["needs_upgrade"] is True
    assert vinfo["disk_version"] == "1.3.2"
    assert vinfo["running_version"] == "1.3.2"

    res = connect.select_mother_ship(data_dir, old_pkg, auto_bootstrap=True)
    assert res["ok"] is True
    assert res["upgraded"] is True
    assert res["path"] == "/setup"
    assert state["stopped"] >= 1
    assert state["pulled"] is True


def test_build_exe_ps1_includes_root_path_and_unblock():
    ps1 = (REPO_ROOT / "shell" / "build_exe.ps1").read_text(encoding="utf-8")
    assert "--paths $root" in ps1
    assert "--hidden-import onboard_bootstrap" in ps1
    assert "$versionFile" in ps1
    assert "Unblock-File" in ps1


def test_pre_132_server_on_8777_without_app_html_is_detected_and_stopped(tmp_path, monkeypatch):
    old_pkg = tmp_path / "old-120"
    old_pkg.mkdir(parents=True)
    (old_pkg / "anchor_gui.py").write_text("# 1.2.0\n", encoding="utf-8")
    (old_pkg / "launch_anchor_dashboard.py").write_text("# 1.2.0\n", encoding="utf-8")
    (old_pkg / "VERSION").write_text("1.2.0\n", encoding="utf-8")

    # Simulate 1.2.0 server: /static/app.html returns False (404), but port 8777 is listening
    monkeypatch.setattr(connect, "reachable", lambda addr, timeout=5.0: False)
    monkeypatch.setattr(connect, "any_service_on_port", lambda addr=connect.LOCAL, port=8777, timeout=1.0: True)
    monkeypatch.setattr(connect, "read_running_version", lambda addr=connect.LOCAL, timeout=1.5: "")

    vinfo = connect.inspect_local_anchor_version(old_pkg, check_system_dirs=False, target_version="1.4.2")
    assert vinfo["running"] is True
    assert vinfo["running_is_older"] is True
    assert vinfo["needs_upgrade"] is True


def test_user_data_migrated_when_upgrading_from_older_folder(tmp_path):
    old_dir = tmp_path / "Anchor-Merrill-Share"
    new_dir = tmp_path / "Anchor"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "projects.json").write_text('{"projects":["merrill-1"]}', encoding="utf-8")
    (old_dir / "DASHBOARD.md").write_text("# Merrill Dashboard\n", encoding="utf-8")

    connect._migrate_user_data_if_needed(old_dir, new_dir)
    assert (new_dir / "projects.json").read_text(encoding="utf-8") == '{"projects":["merrill-1"]}'
    assert (new_dir / "DASHBOARD.md").read_text(encoding="utf-8") == "# Merrill Dashboard\n"


def test_windows_store_python_stub_rejected():
    import onboard_bootstrap as ob
    assert ob._probe_real_python_argv([r"C:\Users\merrill\AppData\Local\Microsoft\WindowsApps\python.exe"]) is False
    assert connect._probe_real_python_argv([r"C:\Users\merrill\AppData\Local\Microsoft\WindowsApps\python3.exe"]) is False


def test_normalize_accepts_bare_localhost_as_http():
    addr, err = connect.normalize("127.0.0.1:8777")
    assert err is None
    assert addr == "http://127.0.0.1:8777"
    addr2, err2 = connect.normalize("localhost:8777")
    assert err2 is None
    assert addr2 == "http://localhost:8777"


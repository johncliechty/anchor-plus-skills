"""Hermetic bootstrap decision tests (no winget, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import onboard_bootstrap as boot  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def test_python_version_ok():
    assert boot.python_version_ok((3, 8, 0)) is True
    assert boot.python_version_ok((3, 13, 0)) is True
    assert boot.python_version_ok((3, 7, 9)) is False


def test_resolve_python_prefers_py_launcher():
    def which(name):
        return {"py": "C:\\Windows\\py.exe", "python": None}.get(name)

    r = boot.resolve_python_command(which_fn=which, version_check_fn=lambda _e: True)
    assert r["ok"] is True
    assert r["argv_prefix"] == ["py", "-3"]


def test_bootstrap_plan_run_when_python_present():
    plan = boot.bootstrap_plan(
        which_fn=lambda n: "C:\\Python\\python.exe" if n == "python" else None,
        winget_present=False,
        version_check_fn=lambda _e: True,
    )
    assert plan["action"] == "run_onboard"
    assert plan["module"] == "share_onboard"


def test_bootstrap_plan_winget_when_python_missing():
    plan = boot.bootstrap_plan(
        which_fn=lambda n: "winget" if n == "winget" else None,
        winget_present=True,
        version_check_fn=lambda _e: False,
    )
    # which_fn returns nothing for python — resolve fails
    def which(n):
        if n == "winget":
            return "winget"
        return None

    plan = boot.bootstrap_plan(which_fn=which, winget_present=True)
    assert plan["action"] == "install_python_then_run"
    assert plan["winget_id"] == "Python.Python.3.12"


def test_bootstrap_plan_fail_manual_without_winget():
    plan = boot.bootstrap_plan(
        which_fn=lambda _n: None,
        winget_present=False,
    )
    assert plan["action"] == "fail_manual"
    assert "python.org" in plan["fix_link"]


def test_repo_cold_start_files_present():
    r = boot.package_root_has_cold_start(REPO)
    assert r["ok"] is True, r
    assert r["has_launcher"] is True

"""Hermetic-friendly bootstrap decisions for Windows cold-start (onboard.ps1).

The .ps1 script remains the user-facing entry; this module holds the decision
logic so we can unit-test without winget/network thrash.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def python_version_ok(version_info=None) -> bool:
    v = version_info if version_info is not None else sys.version_info
    return (v[0], v[1]) >= (3, 8)


def resolve_python_command(
    *,
    which_fn=None,
    version_check_fn=None,
    prefer_py_launcher: bool = True,
) -> dict:
    """Decide which Python command to run for ``-m share_onboard``.

    Returns ``{ok, command, argv_prefix, note}`` where ``argv_prefix`` is a list
    suitable for subprocess (e.g. ``['py', '-3']`` or ``['C:\\\\…\\\\python.exe']``).
    """
    which = which_fn or shutil.which
    check = version_check_fn or (lambda _exe: python_version_ok())

    if prefer_py_launcher and which("py"):
        # py -3 is preferred on Windows when present and healthy.
        return {
            "ok": True,
            "command": "py -3",
            "argv_prefix": ["py", "-3"],
            "note": "py_launcher",
        }

    for name in ("python", "python3"):
        path = which(name)
        if not path:
            continue
        if check(path):
            return {
                "ok": True,
                "command": path,
                "argv_prefix": [path],
                "note": "path_" + name,
            }

    return {
        "ok": False,
        "command": None,
        "argv_prefix": [],
        "note": "python_missing",
    }


def bootstrap_plan(
    *,
    which_fn=None,
    winget_present: bool | None = None,
    version_check_fn=None,
) -> dict:
    """Return the bootstrap action plan (no side effects).

    ``action`` is one of: ``run_onboard``, ``install_python_then_run``, ``fail_manual``.
    """
    which = which_fn or shutil.which
    if winget_present is None:
        winget_present = bool(which("winget"))

    resolved = resolve_python_command(
        which_fn=which,
        version_check_fn=version_check_fn,
    )
    if resolved["ok"]:
        return {
            "action": "run_onboard",
            "python": resolved,
            "winget": winget_present,
            "module": "share_onboard",
        }

    if winget_present:
        return {
            "action": "install_python_then_run",
            "python": resolved,
            "winget": True,
            "winget_id": "Python.Python.3.12",
            "module": "share_onboard",
            "fix_link": "https://www.python.org/downloads/",
        }

    return {
        "action": "fail_manual",
        "python": resolved,
        "winget": False,
        "module": "share_onboard",
        "fix_link": "https://www.python.org/downloads/",
        "note": "Install Python 3.8+ then re-run onboard.cmd",
    }


def package_root_has_cold_start(root) -> dict:
    """Assert cold-start files exist under a package root (A or B tree)."""
    root = Path(root)
    needed = (
        "onboard.cmd",
        "onboard.ps1",
        "share_onboard.py",
        "USER-ONBOARD.md",
    )
    missing = [n for n in needed if not (root / n).is_file()]
    return {
        "ok": not missing,
        "root": str(root),
        "missing": missing,
        "has_launcher": (root / "launch_anchor_dashboard.py").is_file(),
    }

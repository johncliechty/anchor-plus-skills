"""Hermetic-friendly bootstrap decisions for Windows cold-start (onboard.ps1).

The .ps1 script remains the user-facing entry; this module holds the decision
logic so we can unit-test without winget/network thrash.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def python_version_ok(version_info=None) -> bool:
    v = version_info if version_info is not None else sys.version_info
    return (v[0], v[1]) >= (3, 8)


def _probe_real_python_argv(argv_prefix: list[str]) -> bool:
    """Verify candidate Python actually executes and is >= 3.8 (rejects Windows Store 9009 stub)."""
    if not argv_prefix:
        return False
    first = str(argv_prefix[0]).lower()
    if "windowsapps" in first:
        return False
    kwargs = {"capture_output": True, "text": True, "timeout": 8}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        res = subprocess.run(
            list(argv_prefix) + ["-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)"],
            **kwargs,
        )
        return res.returncode == 0
    except Exception:
        return False


def _discover_windows_python_installs() -> list[str]:
    """Scan standard Windows Python installation directories (for fresh winget installs before PATH refresh)."""
    if os.name != "nt":
        return []
    found = []
    roots = [
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Programs" / "Python",
        Path(r"C:\Program Files"),
        Path(r"C:\\"),
    ]
    for r in roots:
        try:
            if not r.is_dir():
                continue
            for sub in sorted(r.glob("Python3*"), reverse=True):
                exe = sub / "python.exe"
                if exe.is_file() and "windowsapps" not in str(exe).lower():
                    found.append(str(exe))
        except OSError:
            pass
    return found


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
    live_mode = (which_fn is None) and (version_check_fn is None)
    which = which_fn or shutil.which
    check = version_check_fn or (
        (lambda exe: _probe_real_python_argv([exe])) if live_mode else (lambda _exe: python_version_ok())
    )

    if prefer_py_launcher and which("py"):
        if not live_mode or _probe_real_python_argv(["py", "-3"]):
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
        if live_mode and "windowsapps" in str(path).lower():
            continue
        if check(path):
            return {
                "ok": True,
                "command": path,
                "argv_prefix": [path],
                "note": "path_" + name,
            }

    if live_mode:
        for cand_exe in _discover_windows_python_installs():
            if _probe_real_python_argv([cand_exe]):
                return {
                    "ok": True,
                    "command": cand_exe,
                    "argv_prefix": [cand_exe],
                    "note": "discovered_install",
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
        "note": "Install Python 3.8+ from python.org then re-run onboard.cmd",
    }


def package_root_has_cold_start(root: Path | str) -> dict:
    r = Path(root)
    needed = ("onboard.cmd", "onboard.ps1", "share_onboard.py", "USER-ONBOARD.md")
    missing = [n for n in needed if not (r / n).is_file()]
    return {
        "ok": not missing,
        "root": str(r),
        "missing": missing,
        "has_launcher": (r / "launch_anchor_dashboard.py").is_file(),
    }

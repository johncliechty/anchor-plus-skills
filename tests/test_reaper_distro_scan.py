"""reaper Wave 9 — the stdlib-vs-psutil HARD GATE.

The zombie-hunter's process enumeration/liveness is ctypes-only
(``proc_probe.enum_pids`` / ``proc_probe.probe_status``); ``psutil`` (and WMI)
appear ONLY as a dev/test-only ground-truth dependency (see
``test_reaper_real_process.py``'s parity check). This module mechanically FAILS
the build if any PRODUCT module imports ``psutil`` / ``wmi`` — the hard gate the
plan's Wave-9 done-when names (criterion 15 / 11).

The reaper subsystem modules are product code (imported at runtime by
``anchor_gui.py``) but are not (yet) enumerated in ``dist_manifest.txt``, so we
scan them EXPLICITLY by name in addition to the manifest-selected shippable set —
the psutil-absence guarantee must not depend on the manifest.

Documented bounded, assent-gated escape hatch (never open-ended): if a future
host genuinely needs a richer enumerator than ctypes Toolhelp can provide, the
ONLY sanctioned path is to add ``psutil`` to ``distro._THIRD_PARTY_IMPORT_ALLOWLIST``
with an explicit per-file scope AND a human sign-off recorded in the plan — the
same deny-by-default mechanism that governs the lone ``winpty`` exception. Until
then this gate keeps the product ctypes-only.

Stdlib + pytest only. Never touches the live ``.anchor`` store or any process.
"""
from pathlib import Path

import distro

REPO_ROOT = distro.REPO_ROOT

# The reaper subsystem's product modules — scanned explicitly so the psutil/WMI
# absence guarantee holds regardless of dist_manifest.txt membership.
REAPER_PRODUCT_MODULES = [
    "proc_probe.py",
    "reaper.py",
    "reaper_arming.py",
    "freeze_state.py",
    "session_registry.py",
    "zombie_hunter.py",
    "worktrees.py",
    "job_runner.py",
    "pty_manager.py",
    "paths.py",
    "anchor_gui.py",
]

# The banned ground-truth-only / native process libraries.
_BANNED_TOPLEVELS = {"psutil", "wmi", "win32api", "win32process", "win32con", "pywin32"}


def _product_py_files():
    """Every top-level product ``*.py`` in the repo root (excludes tests/vendor/
    archives/prototypes/mockups/planning docs)."""
    skip_prefixes = ("tests", "vendor", "_archive", "_prototypes", "_mockups",
                     "planning", "docs", "starter", "static", "health_reports",
                     "logs", "domains", "__pycache__")
    out = []
    for p in sorted(REPO_ROOT.glob("*.py")):
        rel = p.name
        if any(rel.startswith(pref) for pref in skip_prefixes):
            continue
        out.append(rel)
    return out


def test_psutil_not_in_third_party_allowlist():
    """The sole declared native-dep exception is winpty — psutil/WMI are NOT
    sanctioned product imports (the deny-by-default control plane)."""
    allow = distro._THIRD_PARTY_IMPORT_ALLOWLIST
    assert set(allow.keys()) == {"winpty"}, (
        "Wave 9 must not add a third-party-import exception; psutil is "
        "dev/test-only ground truth, never a product dependency")
    assert "psutil" not in allow
    assert "wmi" not in allow


def test_reaper_subsystem_modules_scan_clean():
    """Every reaper subsystem product module passes distro.py's stdlib-only
    import scan (no undeclared third-party import — and so no psutil/WMI)."""
    for mod in REAPER_PRODUCT_MODULES:
        path = REPO_ROOT / mod
        assert path.exists(), f"expected reaper product module {mod} to exist"
        hits = distro.scan_third_party_imports([(mod, path)], root=REPO_ROOT)
        assert hits == [], f"{mod} leaks an undeclared third-party import: {hits}"


def test_no_psutil_or_wmi_anywhere_in_product():
    """No product ``*.py`` (root modules ∪ manifest-shippable) imports psutil/WMI
    or a pywin32 process module — the enumeration is ctypes-only."""
    files = set(_product_py_files())
    for rel in distro.select_shippable():
        if rel.endswith(".py") and not rel.startswith(("tests/", "vendor/")):
            files.add(rel)
    offenders = []
    for rel in sorted(files):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for module, lineno in distro._import_top_levels(text):
            top = (module or "").split(".")[0]
            if top in _BANNED_TOPLEVELS:
                offenders.append((rel, top, lineno))
    assert offenders == [], (
        f"product code imports a banned native/ground-truth lib: {offenders}")


def test_proc_probe_enumerator_is_ctypes_only():
    """The enumerator lives in proc_probe.py and is ctypes-based (imports ctypes,
    never psutil) — the product substrate the psutil parity test validates."""
    src = (REPO_ROOT / "proc_probe.py").read_text(encoding="utf-8")
    assert "def enum_pids(" in src, "the Toolhelp enumerator must ship in proc_probe.py"
    assert "CreateToolhelp32Snapshot" in src
    assert "import psutil" not in src
    tops = {(m or "").split(".")[0] for m, _ in distro._import_top_levels(src)}
    assert "ctypes" in tops
    assert not (tops & _BANNED_TOPLEVELS)


def test_psutil_available_as_dev_ground_truth():
    """psutil IS importable in the TEST environment (dev/test-only) so the
    parity ground-truth check can run — it is just never a product import."""
    import importlib.util
    assert importlib.util.find_spec("psutil") is not None, (
        "psutil must be installed as a dev/test dependency for the Wave-9 "
        "enumerator parity ground truth")

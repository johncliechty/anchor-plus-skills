"""The distro STARTUP GATE (2026-07-26 hardening).

`dist_manifest.txt` is deny-by-default and every scan in distro.py reads file
CONTENT. None of them ever loaded the built result, so a REQUIRED file that was
never added to the manifest shipped as a silent hole: the public v1.1.0 tag
omitted `foundry_map_v2.schema.json`, and because `foundry_map` resolves its
schema at MODULE SCOPE, `import anchor_gui` raised FileNotFoundError. The
released bundle could not start at all, and every build check was green.

A content scan structurally cannot detect an ABSENT file. Only loading it can.
"""
import subprocess
import sys
from pathlib import Path

import pytest

import distro


def _write(root: Path, rel: str, body: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_a_bundle_missing_a_required_data_file_fails_the_gate(tmp_path,
                                                              monkeypatch):
    """The exact v1.1.0 shape: module-scope read of a file that never shipped."""
    staging = tmp_path / "staged"
    staging.mkdir()
    _write(staging, "needy.py",
           "from pathlib import Path\n"
           "SCHEMA = Path(__file__).resolve().parent / 'schema.json'\n"
           "_S = SCHEMA.read_text(encoding='utf-8')\n")
    # schema.json deliberately NOT staged — the manifest hole.
    monkeypatch.setattr(distro, "STARTUP_IMPORTS", ("needy",))

    hits = distro.scan_startup_imports(staging)
    assert hits, "a bundle that cannot import was reported as clean"
    mod, kind, detail = hits[0]
    assert mod == "needy" and kind == "startup-import"
    assert "FileNotFoundError" in detail or "schema.json" in detail, detail


def test_a_complete_bundle_passes(tmp_path, monkeypatch):
    staging = tmp_path / "staged"
    staging.mkdir()
    _write(staging, "needy.py",
           "from pathlib import Path\n"
           "SCHEMA = Path(__file__).resolve().parent / 'schema.json'\n"
           "_S = SCHEMA.read_text(encoding='utf-8')\n")
    _write(staging, "schema.json", "{}")
    monkeypatch.setattr(distro, "STARTUP_IMPORTS", ("needy",))

    assert distro.scan_startup_imports(staging) == []


def test_the_gate_imports_in_a_child_process_not_this_one(tmp_path,
                                                          monkeypatch):
    """Importing the staged tree in-process would pollute the test runner and
    could bind ports / touch real data. It must be a subprocess."""
    staging = tmp_path / "staged"
    staging.mkdir()
    _write(staging, "sideeffect.py",
           "import sys\nsys.modules['GATE_LEAKED'] = True\n")
    monkeypatch.setattr(distro, "STARTUP_IMPORTS", ("sideeffect",))

    assert distro.scan_startup_imports(staging) == []
    assert "GATE_LEAKED" not in sys.modules, \
        "the gate imported the bundle into the test process"


def test_the_gate_runs_with_a_throwaway_data_dir(tmp_path, monkeypatch):
    """It must never point the bundle at the real ANCHOR_DATA_DIR."""
    staging = tmp_path / "staged"
    staging.mkdir()
    _write(staging, "probe.py",
           "import os, pathlib\n"
           "d = os.environ['ANCHOR_DATA_DIR']\n"
           "assert os.environ['ANCHOR_PTY_BACKEND'] == 'stub'\n"
           "pathlib.Path(d, 'touched').write_text('x')\n")
    real = tmp_path / "REAL-DATA"
    real.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(real))
    monkeypatch.setattr(distro, "STARTUP_IMPORTS", ("probe",))

    assert distro.scan_startup_imports(staging) == []
    assert not (real / "touched").exists(), \
        "the gate ran the bundle against the REAL data dir"


def test_build_distro_refuses_a_bundle_that_cannot_start():
    """The gate is wired into the build, not merely defined."""
    src = Path(distro.__file__).read_text(encoding="utf-8", errors="replace")
    body = src.split("def build_distro", 1)[1].split("\ndef ", 1)[0]
    assert "scan_startup_imports(" in body, \
        "build_distro does not run the startup gate"
    assert "StartupImportError" in body, \
        "build_distro does not fail the build on an unimportable bundle"


def test_the_real_manifest_ships_the_foundry_map_schema():
    """Regression pin for the actual v1.1.0 defect."""
    manifest = Path(distro.__file__).resolve().parent / "dist_manifest.txt"
    listed = {ln.strip() for ln in
              manifest.read_text(encoding="utf-8", errors="replace").splitlines()
              if ln.strip() and not ln.strip().startswith("#")}
    assert "foundry_map_v2.schema.json" in listed, \
        "the schema foundry_map reads at import time is not in the manifest"


def test_the_real_manifest_ships_friction_journal():
    """anchor_gui imports it at module scope for the journaling handlers."""
    manifest = Path(distro.__file__).resolve().parent / "dist_manifest.txt"
    listed = {ln.strip() for ln in
              manifest.read_text(encoding="utf-8", errors="replace").splitlines()
              if ln.strip() and not ln.strip().startswith("#")}
    assert "friction_journal.py" in listed

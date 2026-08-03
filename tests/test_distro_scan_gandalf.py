"""Gandalf v1 Wave 4 — the Gandalf integration added NO new native/third-party
import, and its module + SVG asset ship in the manifest.

Proves IMPLEMENTATION-PLAN.md "## Wave 4 — ... distro": `gandalf.py` (the
two-stage engine) is STDLIB-ONLY (json / os / subprocess / time / pathlib + the
in-repo paths / job_runner / summarizer seams — `node` is an EXTERNAL CLI through
a seam, never a Python dep), it is declared in `dist_manifest.txt`, the new
white-wizard SVG (`vendor/brand/gandalf-white-icon.svg`) is declared + ships, and
the whole shipped product set still scans clean modulo the lone declared
`pywinpty` exception. Playwright never appears in product code.
"""
import distro

REPO_ROOT = distro.REPO_ROOT


def test_gandalf_module_in_manifest_and_ships():
    manifest = (REPO_ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    assert "gandalf.py" in manifest, "gandalf.py must be declared in dist_manifest.txt"
    assert "gandalf.py" in set(distro.select_shippable()), "gandalf.py should ship"


def test_gandalf_svg_in_manifest_and_ships():
    manifest = (REPO_ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    assert "vendor/brand/gandalf-white-icon.svg" in manifest, (
        "the Gandalf white-wizard SVG must be declared in dist_manifest.txt")
    assert "vendor/brand/gandalf-white-icon.svg" in set(distro.select_shippable()), \
        "the Gandalf white-wizard SVG should ship"


def test_gandalf_module_scans_clean():
    pairs = [("gandalf.py", REPO_ROOT / "gandalf.py")]
    hits = distro.scan_third_party_imports(pairs, root=REPO_ROOT)
    assert hits == [], f"gandalf.py leaks a third-party import: {hits}"


def test_full_product_scan_still_clean_with_gandalf():
    selected = distro.select_shippable()
    pairs = [(rel, REPO_ROOT / rel) for rel in selected]
    hits = distro.scan_third_party_imports(pairs, root=REPO_ROOT)
    assert hits == [], f"undeclared third-party import(s) after Gandalf: {hits}"
    assert distro.scan_paths(pairs) == []


def test_only_declared_pywinpty_exception_after_gandalf():
    allow = distro._THIRD_PARTY_IMPORT_ALLOWLIST
    assert set(allow.keys()) == {"winpty"}, (
        "the Gandalf integration may not add a third-party-import exception")

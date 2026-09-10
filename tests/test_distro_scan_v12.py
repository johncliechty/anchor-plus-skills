"""Distribution import guards, including the original Wave 12 checks.

The whole shipped product must pass the stdlib-only import scan except for
explicit, file-scoped optional dependencies: `winpty` in `pty_manager.py`, and
`jupyter_server`, `jupyter_client`, and `traitlets` in `notebook_service.py`.
Each exception is restricted to its owning file.

The Wave 12 module `effort_view.py` remains stdlib-only and listed in
`dist_manifest.txt`. Playwright remains a development-only test dependency
and must never appear in product code.
"""
from pathlib import Path

import distro

REPO_ROOT = distro.REPO_ROOT


def test_v12_real_product_import_scan_is_clean():
    """The full shipped product set passes the stdlib-only import scan."""
    selected = distro.select_shippable()
    pairs = [(rel, REPO_ROOT / rel) for rel in selected]
    hits = distro.scan_third_party_imports(pairs, root=REPO_ROOT)
    assert hits == [], f"undeclared third-party import(s) after v12: {hits}"


def test_v12_full_scan_clean():
    """Belt-and-suspenders: the whole scan (PII + secrets + imports) is clean."""
    selected = distro.select_shippable()
    pairs = [(rel, REPO_ROOT / rel) for rel in selected]
    assert distro.scan_paths(pairs) == []


def test_only_declared_file_scoped_import_exceptions():
    """Only declared optional dependencies may import from their owning file."""
    expected_owners = {
        "winpty": "pty_manager.py",
        "jupyter_server": "notebook_service.py",
        "jupyter_client": "notebook_service.py",
        "traitlets": "notebook_service.py",
    }
    allow = distro._THIRD_PARTY_IMPORT_ALLOWLIST
    assert set(allow) == set(expected_owners), (
        "third-party-import exceptions must match the declared optional dependencies")
    for module, owner in expected_owners.items():
        assert allow[module]["files"] == frozenset({owner})
        assert distro._import_allowed(module, owner)
        for other_file in {"anchor_gui.py", "pty_manager.py", "notebook_service.py"} - {owner}:
            assert not distro._import_allowed(module, other_file)


def test_v12_new_module_ships_in_manifest_and_scans_clean():
    """The lone NEW v12 module (effort_view.py) is in the manifest, ships, and
    scans clean (stdlib only)."""
    # In the manifest (added at Wave 9 when effort_view.py landed).
    manifest = (REPO_ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    assert "effort_view.py" in manifest, (
        "effort_view.py must be declared in dist_manifest.txt")
    selected = set(distro.select_shippable())
    assert "effort_view.py" in selected, "effort_view.py should ship"
    pairs = [("effort_view.py", REPO_ROOT / "effort_view.py")]
    hits = distro.scan_third_party_imports(pairs, root=REPO_ROOT)
    assert hits == [], f"effort_view.py leaks a third-party import: {hits}"


def test_v12_touched_modules_scan_clean_individually():
    """Each v12-touched product module scans clean (no native import leak)."""
    v12_modules = [
        "effort_view.py", "session_registry.py", "terminal_session.py",
        "effort_history.py", "summarizer.py", "deliverables.py",
        "anchor_gui.py", "anchor.py", "anchor_healthcheck.py",
    ]
    selected = set(distro.select_shippable())
    for mod in v12_modules:
        assert mod in selected, f"{mod} should ship"
        pairs = [(mod, REPO_ROOT / mod)]
        hits = distro.scan_third_party_imports(pairs, root=REPO_ROOT)
        assert hits == [], f"{mod} leaks a third-party import: {hits}"


def test_no_playwright_in_product_code():
    """Playwright is a DEV-ONLY test dep — it must NEVER be imported by any
    shipped product module. (In tests it is gated by pytest.importorskip.)"""
    selected = distro.select_shippable()
    offenders = []
    for rel in selected:
        if not rel.endswith(".py") or rel.startswith("vendor/") \
                or rel.startswith("tests/"):
            continue
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for module, lineno in distro._import_top_levels(text):
            top = (module or "").split(".")[0]
            if top == "playwright":
                offenders.append((rel, lineno))
    assert offenders == [], f"playwright imported in product code: {offenders}"


def test_winpty_only_lazily_in_pty_manager():
    """`import winpty` appears ONLY inside pty_manager.py across the product."""
    selected = distro.select_shippable()
    offenders = []
    for rel in selected:
        if not rel.endswith(".py") or rel.startswith("vendor/") \
                or rel.startswith("tests/"):
            continue
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for module, lineno in distro._import_top_levels(text):
            if module == "winpty" and rel != "pty_manager.py":
                offenders.append((rel, lineno))
    assert offenders == [], f"winpty imported outside pty_manager.py: {offenders}"

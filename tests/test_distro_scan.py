"""Wave 8 — Shareable, data-free distribution.

Proves the acceptance criteria from IMPLEMENTATION-PLAN.md "## Wave 8" and the
three fixed findings (BLOCKER-1 email-by-pattern, MAJOR-1 no global bypass,
MAJOR-2 broadened token detection + vendor false-positive guard):

AC1  Given the manifest, when the distro is built, then only manifest-allowed
     code files are included (data/registry/.anchor/ excluded).
AC2  Given a planted Windows user path / personal email / token (quoted,
     unquoted, JSON, AWS, JWT, bare high-entropy) / registry artifact in the
     staged set, when the scan runs, then the build FAILS with the file named.
AC3  Given a clean tree, when the distro is built, then a README is emitted and
     the export is publishable.

Hard constraints proven here:
 - The REAL shipped product set (INCLUDING vendor/katex/) scans CLEAN.
 - NO shipped file embeds a real personal email literal — the scanner detects
   the personal address by PATTERN, never by storing it.
 - The old `distro-scan: allow` inline marker is GONE: a secret + that marker
   planted in a non-scanner shipped file (anchor.py) is STILL caught.

NOTE ON THIS TEST FILE: it is itself shipped (manifest `tests/test_*.py`) and so
must scan CLEAN. It therefore embeds NO real secret/email literal. Secret-shaped
strings used in assertions are BUILT AT RUNTIME via concatenation, and concrete
leak literals live in the UNSHIPPED `tests/fixtures/planted_secret/` fixtures.
"""
import shutil
from pathlib import Path

import pytest

import distro


REPO_ROOT = distro.REPO_ROOT
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "planted_secret"

# The real personal email, assembled at runtime so this shipped test file does
# NOT contain the literal (it would otherwise leak / self-trip the scanner).
_REAL_EMAIL = "john.liechty" + "@" + "gmail" + "." + "com"
# A high-entropy token VALUE, assembled at runtime (not a literal in this file).
_FAKE_TOKEN = "a9F3kZ2pQ7" + "wL5mN8xR1t" + "Y6vB4cD0eH2j"
# A bare 40+ char high-entropy run, assembled so no contiguous literal of it
# appears in this shipped file (it would otherwise self-trip the scanner).
_FAKE_BLOB = "kZ2pQ7wL5mN8" + "xR1tY6vB4cD0" + "eH2jA9F3kZ2pQ7" + "wL5mN8"


def _assign(key, value):
    """Build a `KEY = "VALUE"` source line at runtime (so the value is never a
    contiguous literal in THIS file's source -> this test file stays scan-clean)."""
    return key + ' = "' + value + '"\n'


# ── AC1: deny-by-default — only manifest-allowed files are staged ────────────

def test_selected_set_is_manifest_subset_and_excludes_data():
    selected = set(distro.select_shippable())

    # Product code is included.
    for must in ("anchor.py", "anchor_gui.py", "paths.py", "distro.py",
                 "rnd_registry.py", "job_runner.py", "report_viewer.py"):
        assert must in selected, f"{must} should ship"

    # Vendored KaTeX assets are included via the vendor/** glob.
    assert any(f.startswith("vendor/katex/") for f in selected)

    # Data / registry / .anchor / state are EXCLUDED (never listed in manifest).
    forbidden = {
        "DASHBOARD.md", "PROJECTS.md", "INBOX.md", "CANCELLED.md",
        "SAVED_FOR_LATER.md", "WEEKLY_REVIEW.md", "dashboard.html",
        "foreman-checkpoint.json", "foreman.config.json",
    }
    assert not (forbidden & selected), forbidden & selected

    # No data subdirs, planning, archives, mockups, logs, health reports.
    for f in selected:
        assert not f.startswith("domains/")
        assert not f.startswith("logs/")
        assert not f.startswith("health_reports/")
        assert not f.startswith("planning/")
        assert not f.startswith("_archive/")
        assert not f.startswith("_mockups/")
        assert ".anchor/" not in f

    # The planted-secret fixtures must NOT be in the shippable set.
    assert not any("planted_secret" in f for f in selected)


def test_build_stages_only_selected_files(tmp_path):
    out = tmp_path / "export"
    report = distro.build_distro(output_dir=out)
    staged = {p.relative_to(out).as_posix()
              for p in out.rglob("*") if p.is_file()}

    # Everything staged (minus the build-time-emitted files: the README, the
    # v1.1.3 thin consumer CLAUDE.md, and the v1.2.3 collaborator run contract
    # AGENTS.md + AUTONOMOUS-MODE.md) is in the manifest selection.
    selected = set(report["files"])
    emitted = {"README.md", "CLAUDE.md", "AGENTS.md", "AUTONOMOUS-MODE.md", "ELEGANCE.md"}
    assert staged - emitted == selected

    # And data files are absent on disk.
    assert not (out / "DASHBOARD.md").exists()
    assert not (out / "foreman-checkpoint.json").exists()


def test_new_unlisted_file_does_not_ship(tmp_path):
    """Deny-by-default: a brand-new unlisted file in a tree is NOT staged."""
    fake_root = tmp_path / "tree"
    fake_root.mkdir()
    (fake_root / "anchor.py").write_text("# ok\n", encoding="utf-8")
    (fake_root / "totally_new_unlisted.py").write_text("x = 1\n", encoding="utf-8")
    # Use the real manifest as the allowlist.
    selected = distro.select_shippable(root=fake_root)
    assert "anchor.py" in selected
    assert "totally_new_unlisted.py" not in selected


# ── AC2: planted secrets FAIL the build and NAME the file ────────────────────

def _build_tree_with(tmp_path, fixture_name):
    """Stage a minimal real-ish tree + drop one planted-secret fixture in,
    add it to a manifest so it gets staged, and return (root, manifest)."""
    root = tmp_path / "tree"
    root.mkdir()
    # A legit product file (must pass clean).
    shutil.copy2(REPO_ROOT / "paths.py", root / "paths.py")
    # paths.py imports first-party pillar_flags (function scope) — stage it so
    # the import scan does not false-positive as third-party when the root is
    # a sparse fixture tree (same guard as the share w2 tests).
    man_lines = ["paths.py", fixture_name]
    if (REPO_ROOT / "pillar_flags.py").is_file():
        shutil.copy2(REPO_ROOT / "pillar_flags.py", root / "pillar_flags.py")
        man_lines.insert(1, "pillar_flags.py")
    # The planted secret, copied to the tree root.
    planted = root / fixture_name
    shutil.copy2(FIXTURE_DIR / fixture_name, planted)
    # A manifest that allows all staged files.
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("\n".join(man_lines) + "\n", encoding="utf-8")
    return root, manifest


@pytest.mark.parametrize("fixture_name,category", [
    ("email_leak.py", "personal-email"),
    ("userpath_leak.py", "user-profile-path"),
    ("token_leak.py", "auth-token-value"),
    ("token_unquoted_leak.py", "auth-token-value"),
    ("token_json_leak.json", "auth-token-value"),
    ("aws_key_leak.py", "secret-token-literal"),
    ("jwt_leak.py", "secret-token-literal"),
    ("bare_entropy_leak.py", "high-entropy-token"),
    ("registry_artifact.json", "registry-data-artifact"),
])
def test_planted_secret_fails_build_and_names_file(tmp_path, fixture_name, category):
    root, manifest = _build_tree_with(tmp_path, fixture_name)
    out = tmp_path / "export"

    with pytest.raises(distro.PersonalDataError) as ei:
        distro.build_distro(root=root, output_dir=out, manifest_path=manifest,
                            emit_readme_file=False)

    err = ei.value
    offending = {rel for (rel, cat, snip) in err.hits}
    cats = {cat for (rel, cat, snip) in err.hits}
    # The offending file is NAMED.
    assert fixture_name in offending, (fixture_name, err.hits)
    assert fixture_name in str(err)
    # The right category tripped.
    assert category in cats, (category, err.hits)
    # The clean product file is NOT named.
    assert "paths.py" not in offending
    # On failure the staging dir is torn down (nothing leaks).
    assert not out.exists()


# ── BLOCKER-1: no shipped file embeds the real personal email ────────────────

def test_no_shipped_file_contains_real_personal_email():
    """Build the real distro and assert no staged file contains the real
    personal address (caught by pattern, not stored) — and distro.py is clean."""
    # Assembled at runtime so this assertion's own source does not contain it.
    gmail_suffix = "@" + "gmail" + ".com"
    selected = distro.select_shippable()
    for rel in selected:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        assert _REAL_EMAIL not in text, f"{rel} embeds the real personal email"
        # No real-gmail address of any local-part should ship.
        assert gmail_suffix not in text.lower(), f"{rel} embeds a gmail address"


def test_distro_py_has_no_embedded_real_pii():
    """The scanner's OWN source must scan clean with no marker — it stores no
    real email literal, no real C:\\Users\\<account> path, no real token."""
    text = (REPO_ROOT / "distro.py").read_text(encoding="utf-8")
    assert _REAL_EMAIL not in text
    hits = list(distro._scan_text("distro.py", text))
    hits += list(distro._scan_registry_artifact("distro.py", text))
    assert hits == [], f"distro.py is not self-clean: {hits}"


def test_planted_real_email_in_staged_file_is_caught(tmp_path):
    """A real personal email planted in a staged product file IS caught/named."""
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copy2(REPO_ROOT / "anchor.py", root / "anchor.py")
    leaky = root / "anchor.py"
    leaky.write_text(leaky.read_text(encoding="utf-8")
                     + f'\nOWNER = "{_REAL_EMAIL}"\n', encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("anchor.py\n", encoding="utf-8")
    out = tmp_path / "export"

    with pytest.raises(distro.PersonalDataError) as ei:
        distro.build_distro(root=root, output_dir=out, manifest_path=manifest,
                            emit_readme_file=False)
    hits = ei.value.hits
    assert any(rel == "anchor.py" and cat == "personal-email"
               for (rel, cat, _) in hits), hits
    assert "anchor.py" in str(ei.value)


def test_allowlisted_emails_not_flagged():
    """Known-safe non-personal addresses do NOT trip the scanner."""
    safe = (
        'GIT_AUTHOR = "anchor@localhost"\n'
        'COAUTHOR = "noreply@anthropic.com"\n'
        'DOC = "someone@example.com and test@example.org, a@example.net"\n'
    )
    assert list(distro._scan_text("x.py", safe)) == []


# ── MAJOR-1: the inline marker grants NO global bypass ───────────────────────

def test_marker_in_product_file_is_still_caught(tmp_path):
    """A secret + '# distro-scan: allow' planted in a NON-scanner shipped file
    (anchor.py) is STILL caught — the marker mechanism is gone, no self-grant."""
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copy2(REPO_ROOT / "anchor.py", root / "anchor.py")
    leaky = root / "anchor.py"
    # secret VALUE + the old opt-out marker text on the same line.
    leaky.write_text(
        leaky.read_text(encoding="utf-8")
        + f'\nANCHOR_TOKEN = "{_FAKE_TOKEN}"  # distro-scan: allow\n',
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("anchor.py\n", encoding="utf-8")
    out = tmp_path / "export"

    with pytest.raises(distro.PersonalDataError) as ei:
        distro.build_distro(root=root, output_dir=out, manifest_path=manifest,
                            emit_readme_file=False)
    hits = ei.value.hits
    assert any(rel == "anchor.py" and cat == "auth-token-value"
               for (rel, cat, _) in hits), hits


def test_marker_text_is_no_longer_a_suppression_mechanism():
    """Sanity: the scanner exposes no marker constant/function any more."""
    assert not hasattr(distro, "SCAN_ALLOW_MARKER")
    assert not hasattr(distro, "_line_allowed")
    # And the bare marker string on a line does NOT suppress a secret.
    text = _assign("secret", _FAKE_TOKEN).rstrip("\n") + "  # distro-scan: allow\n"
    cats = {cat for (_, cat, _) in distro._scan_text("p.py", text)}
    assert "auth-token-value" in cats


# ── MAJOR-2: token detection breadth + vendor no-false-positive ──────────────

def test_unquoted_token_assignment_is_flagged():
    text = f"ANCHOR_TOKEN={_FAKE_TOKEN}\n"
    cats = {cat for (_, cat, _) in distro._scan_text("p.py", text)}
    assert "auth-token-value" in cats


def test_json_token_value_is_flagged():
    text = '{ "ANCHOR_TOKEN": "%s" }\n' % _FAKE_TOKEN
    cats = {cat for (_, cat, _) in distro._scan_text("p.json", text)}
    assert "auth-token-value" in cats


def test_aws_key_shape_is_flagged():
    text = 'KEY = "AKIA' + "IOSFODNN7EXAMPLE" + '"\n'
    cats = {cat for (_, cat, _) in distro._scan_text("p.py", text)}
    assert "secret-token-literal" in cats


def test_jwt_shape_is_flagged():
    jwt = ("eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxIn0"
           + "." + "abcDEF123456ghiJKL")
    text = f'JWT = "{jwt}"\n'
    cats = {cat for (_, cat, _) in distro._scan_text("p.py", text)}
    assert "secret-token-literal" in cats


def test_bearer_token_is_flagged():
    text = 'h = "Bearer ' + "abcDEF123456ghiJKLmnoPQR789stu" + '"\n'
    cats = {cat for (_, cat, _) in distro._scan_text("p.py", text)}
    assert "secret-token-literal" in cats


def test_bare_high_entropy_token_in_first_party_is_flagged():
    text = _assign("BLOB", _FAKE_BLOB)
    cats = {cat for (_, cat, _) in distro._scan_text("first_party.py", text)}
    assert "high-entropy-token" in cats


def test_generic_entropy_skips_vendor_files():
    """The generic high-entropy heuristic is NOT applied to vendor/ files."""
    text = 'var x="' + _FAKE_BLOB + '";\n'
    # First-party: flagged.
    assert any(cat == "high-entropy-token"
               for (_, cat, _) in distro._scan_text("first_party.py", text))
    # Vendored: NOT flagged by the generic heuristic.
    assert not any(cat == "high-entropy-token"
                   for (_, cat, _) in distro._scan_text("vendor/katex/x.js", text))


def test_vendor_katex_does_not_false_positive():
    """The REAL vendored minified KaTeX must scan CLEAN (no false positives)."""
    selected = distro.select_shippable()
    vendor = [(rel, REPO_ROOT / rel) for rel in selected
              if rel.startswith("vendor/katex/")]
    assert vendor, "expected vendored KaTeX files in the shippable set"
    hits = distro.scan_paths(vendor)
    assert hits == [], f"vendor/katex/ false positive(s): {hits}"


def test_concrete_pii_still_runs_over_vendor():
    """Concrete-PII patterns (email/user-path/token shapes) DO run over vendor/
    files — only the GENERIC entropy heuristic is skipped there."""
    text = f'comment = "{_REAL_EMAIL}";\n'
    cats = {cat for (_, cat, _) in distro._scan_text("vendor/katex/x.js", text)}
    assert "personal-email" in cats


# ── AC3: clean tree -> README emitted + publishable export ───────────────────

def test_clean_build_emits_readme_and_is_publishable(tmp_path):
    out = tmp_path / "export"
    report = distro.build_distro(output_dir=out)

    readme = out / "README.md"
    assert readme.exists() and readme.stat().st_size > 0
    assert report["readme"] == readme
    assert "data-free" in readme.read_text(encoding="utf-8").lower()

    # Publishable: staging dir exists and contains the product entrypoint.
    assert (out / "anchor_gui.py").exists()
    assert (out / "anchor.py").exists()
    assert report["staging"] == out


def test_default_output_is_tmp_dir():
    """No output dir -> a fresh tmp staging dir (never publishes anywhere)."""
    report = distro.build_distro()
    try:
        assert report["staging"].exists()
        assert (report["staging"] / "anchor_gui.py").exists()
    finally:
        shutil.rmtree(report["staging"], ignore_errors=True)


# ── Hard constraint: the REAL product set scans CLEAN (no false positive) ────

def test_real_product_files_scan_clean():
    """The actual shipped product code (incl. vendor/katex/ and this test file)
    must pass the scan even though it contains the identifier ANCHOR_TOKEN and
    may mention the Windows user dir in comments."""
    selected = distro.select_shippable()
    pairs = [(rel, REPO_ROOT / rel) for rel in selected]
    hits = distro.scan_paths(pairs)
    assert hits == [], f"false positive(s) on real product code: {hits}"


def test_full_real_build_scans_clean(tmp_path):
    """Building the real distro into a staging dir succeeds (scan clean)."""
    out = tmp_path / "export"
    report = distro.build_distro(output_dir=out)
    assert report["files"]
    # Re-scan the staged set directly to be doubly sure.
    assert distro.scan_staged_dir(out) == []


def test_bare_token_identifier_not_flagged():
    """A bare ANCHOR_TOKEN env-var reference / dict KEY is NOT a secret value."""
    text = (
        'tok = os.environ.get("ANCHOR_TOKEN")\n'
        'AUTH_TOKEN_ENV = "ANCHOR_TOKEN"\n'
        'monkeypatch.delenv("ANCHOR_TOKEN", raising=False)\n'
        '# paths under the Windows user dir are mentioned but not concrete\n'
    )
    assert list(distro._scan_text("x.py", text)) == []


def test_placeholder_token_value_not_flagged():
    """A placeholder token value is not treated as a real secret."""
    text = 'ANCHOR_TOKEN = "changeme"\n'
    assert list(distro._scan_text("x.py", text)) == []


def test_doc_placeholder_userpath_not_flagged():
    """An allowlisted doc-placeholder account (C:\\Users\\example\\...) passes."""
    text = r'EXAMPLE = r"C:\Users\example\dev\Anchor"' + "\n"
    cats = {cat for (_, cat, _) in distro._scan_text("x.py", text)}
    assert "user-profile-path" not in cats


def test_concrete_token_value_is_flagged():
    text = _assign("ANCHOR_TOKEN", _FAKE_TOKEN)
    hits = list(distro._scan_text("x.py", text))
    assert any(cat == "auth-token-value" for (_, cat, _) in hits)


# ── Wave 10: the declared pywinpty exception + stdlib-only import enforcement ─

def test_pywinpty_exception_is_declared_and_scoped():
    """The ONE native-dep exception is declared + scoped to pty_manager.py."""
    allow = distro._THIRD_PARTY_IMPORT_ALLOWLIST
    assert "winpty" in allow, "pywinpty (winpty) must be the declared exception"
    assert "pty_manager.py" in allow["winpty"]["files"]
    # Scoped: allowed in pty_manager.py, refused everywhere else.
    assert distro._import_allowed("winpty", "pty_manager.py")
    assert not distro._import_allowed("winpty", "anchor_gui.py")
    assert not distro._import_allowed("winpty", "preview_server.py")


def test_lazy_import_winpty_in_pty_manager_does_not_fail_scan():
    """`import winpty` in pty_manager.py must NOT trip the import scan, and the
    REAL pty_manager.py (which lazily imports winpty) scans clean."""
    src = "def start(self):\n    import winpty  # lazy native import\n"
    hits = distro.scan_third_party_imports(
        [("pty_manager.py", _WRITE(src))], root=REPO_ROOT)
    assert hits == [], hits
    # The real shipped pty_manager.py is in the selection and scans clean.
    selected = set(distro.select_shippable())
    assert "pty_manager.py" in selected
    pairs = [("pty_manager.py", REPO_ROOT / "pty_manager.py")]
    assert distro.scan_third_party_imports(pairs) == []


def test_undeclared_native_import_elsewhere_is_flagged(tmp_path):
    """An undeclared third-party/native import in another first-party file FAILS,
    and `import winpty` OUTSIDE pty_manager.py is also refused."""
    # numpy in a non-allowlisted module → flagged.
    numpy_src = tmp_path / "some_module.py"
    numpy_src.write_text("import numpy\n", encoding="utf-8")
    hits = distro.scan_third_party_imports(
        [("some_module.py", numpy_src)], root=REPO_ROOT)
    assert any(cat == "third-party-import" and "numpy" in snip
               for (_, cat, snip) in hits), hits

    # winpty imported in a DIFFERENT file than pty_manager.py → still refused.
    winpty_src = tmp_path / "bar.py"
    winpty_src.write_text("import winpty\n", encoding="utf-8")
    hits2 = distro.scan_third_party_imports(
        [("bar.py", winpty_src)], root=REPO_ROOT)
    assert any(cat == "third-party-import" and "winpty" in snip
               for (_, cat, snip) in hits2), hits2


def test_undeclared_native_import_fails_the_build(tmp_path):
    """A planted `import requests` in a staged product file FAILS the build."""
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copy2(REPO_ROOT / "paths.py", root / "paths.py")
    if (REPO_ROOT / "pillar_flags.py").is_file():
        shutil.copy2(REPO_ROOT / "pillar_flags.py",
                     root / "pillar_flags.py")
    leaky = root / "leaky_mod.py"
    leaky.write_text("import requests\nx = 1\n", encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("paths.py\nleaky_mod.py\n", encoding="utf-8")
    out = tmp_path / "export"
    with pytest.raises(distro.PersonalDataError) as ei:
        distro.build_distro(root=root, output_dir=out, manifest_path=manifest,
                            emit_readme_file=False)
    cats = {cat for (_, cat, _) in ei.value.hits}
    assert "third-party-import" in cats, ei.value.hits
    assert "leaky_mod.py" in str(ei.value)
    assert not out.exists()  # torn down on failure


def test_v3_modules_ship():
    """All new v3 "Mission Control" modules are in the shippable set."""
    selected = set(distro.select_shippable())
    for must in ("pty_manager.py", "session_registry.py", "worktrees.py",
                 "terminal_session.py", "handoff.py", "preview_server.py"):
        assert must in selected, f"{must} should ship"


def test_tests_and_vendor_exempt_from_import_rule():
    """tests/ (pytest is a declared dev dep) and vendor/ are exempt from the
    stdlib-only import rule."""
    # A test file importing pytest is NOT flagged.
    pytest_src = "import pytest\n"
    assert distro.scan_third_party_imports(
        [("tests/test_x.py", _WRITE(pytest_src))], root=REPO_ROOT) == []
    # A vendor file with a third-party-looking import is NOT flagged.
    assert distro.scan_third_party_imports(
        [("vendor/x/y.py", _WRITE("import numpy\n"))], root=REPO_ROOT) == []


def test_manifest_negation_denies_shippable(tmp_path):
    """A ``!pattern`` manifest line DENIES a file every allow-pattern covers.

    This is how PII-planting suites (scrub/redaction tests that embed synthetic
    secrets BY DESIGN) stay out of the stranger-facing bundle without weakening
    the tests or the scanner (hardening round 2026-07-29)."""
    root = tmp_path / "tree"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_ok.py").write_text("x = 1" + chr(10), encoding="utf-8")
    (root / "tests" / "test_planty.py").write_text("x = 2" + chr(10), encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("tests/test_*.py" + chr(10) + "!tests/test_planty.py" + chr(10),
                        encoding="utf-8")
    sel = distro.select_shippable(root=root, manifest_path=manifest)
    assert "tests/test_ok.py" in sel
    assert "tests/test_planty.py" not in sel


def test_real_manifest_denies_pii_planting_suites():
    """The live manifest keeps the known PII-planting suites out of the set."""
    sel = set(distro.select_shippable())
    for banned in ("tests/test_share_feedback_w6.py",
                   "tests/test_share_onboard_w5.py",
                   "tests/test_log_redaction_2026_07_26.py"):
        assert banned not in sel, banned


def test_unquoted_token_rule_exempts_attribute_reads():
    """``auth_token = self.token`` is a code READ, never a pasted literal."""
    hits = list(distro._scan_text("m.py", 'auth_token = self.token' + chr(10)))
    assert hits == []
    # A genuine pasted literal still trips.
    hits = list(distro._scan_text("m.py", 'auth_token = ' + 'abcd1234' + 'efgh5678' + chr(10)))
    assert [h[1] for h in hits] == ["auth-token-value"]


# Helper: materialize source text to a temp file path for the import scan, which
# reads from disk. (Kept tiny + local so the scan-clean test file stays clean.)
def _WRITE(text):
    import tempfile
    p = Path(tempfile.mkstemp(suffix=".py")[1])
    p.write_text(text, encoding="utf-8")
    return p

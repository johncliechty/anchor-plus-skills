"""Share-distro Wave 4 — distro.py build-host-path detector + clean-scan over
the REAL vendored output.

Proves the Wave 4 done-when (IMPLEMENTATION-PLAN.md "## Wave 4"):

 1. Given ``vendor_skills.vendor_all`` run into a temp tree (a temp git source
    repo built via the env, like Wave 3), When ``build_distro`` stages + scans
    it, Then it returns CLEAN — no ``PersonalDataError``, no
    ``third-party-import`` on the vendored skills, no high-entropy false-fail on
    a vendored git SHA (the SOURCES.md commit sha).
 2. Given a seeded ``C:\\dev\\secret\\x`` in a NON-vendored staged file, When
    scanned, Then it RAISES ``PersonalDataError`` (the new build-host-path
    detector fires); the SAME path inside ``vendor/bundled-skills/`` does NOT
    appear / does not fail.

HARD CONSTRAINT — this test file is itself SHIPPED (manifest ``tests/test_*.py``)
and so must scan CLEAN. It therefore embeds NO literal host path / PII: every
host-path / email literal is ASSEMBLED AT RUNTIME via concatenation (the
tests/test_distro_scan.py convention), so the repo-wide distro scan stays clean.
Hermetic: source repos are TEMP git repos via the env — never the real
C:\\dev\\trio / Skill Foundry, never network.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import distro  # noqa: E402
import vendor_skills  # noqa: E402


# ── Runtime-assembled literals (so THIS shipped file stays scan-clean) ────────
# A Windows dev-tree leak path whose LEAF ("secret") is NOT allowlisted.
_SECRET_WIN = "C:" + "\\" + "dev" + "\\" + "secret" + "\\" + "x"
# A POSIX home leak path.
_SECRET_POSIX = "/" + "home" + "/" + "someuser" + "/" + "proj"
# A nested dev-tree leak (drive then any path then dev\<leaf>).
_SECRET_NESTED = "D:" + "\\" + "work" + "\\" + "dev" + "\\" + "private" + "\\" + "y"
# The project's OWN root — must NOT trip (allowlisted leaf "Anchor").
_OWN_ROOT = "C:" + "\\" + "dev" + "\\" + "Anchor" + "\\" + "sub"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args),
                   check=True, capture_output=True)


def _init_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")


def _have_git():
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


requires_git = pytest.mark.skipif(not _have_git(), reason="git not available")


@pytest.fixture
def trio_repo(tmp_path):
    """A temp git repo holding a 'foreman' skill subdir with a normal SKILL.md
    + a committed file carrying a host path + email that the vendor scrub
    genericizes. (Assembled at runtime — see top of file.)"""
    repo = tmp_path / "trio"
    _init_repo(repo)
    skill = repo / "foreman"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "# Foreman\nA normal skill file.\n", encoding="utf-8")
    # A committed file with a host path + email — the residual scrub must
    # genericize these so the VENDORED output scans clean.
    leak_email = "dev" + "@" + "host" + ".example"
    (skill / "notes.md").write_text(
        "Built at %s by %s\n" % (_SECRET_WIN, leak_email), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    return repo


# ── Unit-level: the new build-host-path detector ─────────────────────────────

def test_build_host_path_detector_fires_on_non_vendored_windows():
    text = 'P = "' + _SECRET_WIN + '"\n'
    hits = list(distro._scan_text("first_party.py", text))
    cats = {cat for (_, cat, _) in hits}
    assert "build-host-path" in cats, hits


def test_build_host_path_detector_fires_on_posix_home():
    text = 'P = "' + _SECRET_POSIX + '"\n'
    cats = {cat for (_, cat, _) in distro._scan_text("first_party.py", text)}
    assert "build-host-path" in cats


def test_build_host_path_detector_fires_on_nested_dev_tree():
    text = 'P = "' + _SECRET_NESTED + '"\n'
    cats = {cat for (_, cat, _) in distro._scan_text("first_party.py", text)}
    assert "build-host-path" in cats


def test_own_root_leaf_is_allowlisted_not_flagged():
    """The project's OWN root (C:\\dev\\Anchor\\...) is the documented example
    path used throughout the code; the allowlisted leaf does NOT trip."""
    text = 'REPO = r"' + _OWN_ROOT + '"\n'
    cats = {cat for (_, cat, _) in distro._scan_text("first_party.py", text)}
    assert "build-host-path" not in cats


def test_build_host_path_skipped_for_vendored_files():
    """The build-host-path detector (like the generic-entropy heuristic) is NOT
    applied to vendored files (they are scrubbed by vendor_skills)."""
    text = 'P = "' + _SECRET_WIN + '"\n'
    cats = {cat for (_, cat, _)
            in distro._scan_text("vendor/bundled-skills/foreman/x.md", text)}
    assert "build-host-path" not in cats


def test_user_profile_gap_caught_by_new_detector():
    """The OLD _USERPATH_RE only catches <drive>\\Users\\<acct>\\<seg>; a plain
    dev-tree path (no Users segment) slipped through and is now caught."""
    text = 'P = "' + _SECRET_WIN + '"\n'
    # The old user-profile detector does NOT fire (no Users segment)...
    up = {cat for (_, cat, _) in distro._scan_text("x.py", text)
          if cat == "user-profile-path"}
    assert up == set()
    # ...but the new build-host-path detector does.
    bh = {cat for (_, cat, _) in distro._scan_text("x.py", text)
          if cat == "build-host-path"}
    assert bh == {"build-host-path"}


# ── Scanner self-clean + real product set stays clean ────────────────────────

def test_distro_py_self_clean_for_host_paths():
    """The scanner's OWN source must not embed a flaggable host path literal."""
    text = (distro.REPO_ROOT / "distro.py").read_text(encoding="utf-8")
    hits = [h for h in distro._scan_text("distro.py", text)
            if h[1] == "build-host-path"]
    assert hits == [], hits


def test_real_shippable_set_no_host_path_false_fail():
    """The REAL shipped product set scans clean for the new detector (legit
    own-root / placeholder references are allowlisted, not false-failed)."""
    selected = distro.select_shippable()
    pairs = [(rel, distro.REPO_ROOT / rel) for rel in selected]
    hits = [h for h in distro.scan_paths(pairs) if h[1] == "build-host-path"]
    assert hits == [], hits


# ── Done-when #1: build over the REAL vendored output is CLEAN ───────────────

@requires_git
def test_build_distro_over_vendored_output_is_clean(trio_repo, tmp_path, monkeypatch):
    """vendor_all run into the export, then build_distro stages + scans it ->
    CLEAN: no PersonalDataError, no third-party-import on the vendored skill, no
    high-entropy false-fail on the SOURCES.md git SHA."""
    monkeypatch.setenv("ANCHOR_TRIO_DIR", str(trio_repo))
    monkeypatch.delenv("ANCHOR_GANDALF_DIR", raising=False)
    out = tmp_path / "export"

    report = distro.build_distro(
        output_dir=out,
        vendor_sources=[("foreman", "ANCHOR_TRIO_DIR", "foreman")],
    )

    # The vendored skill landed in the export AND is in the report's file set.
    skill_md = out / "vendor" / "bundled-skills" / "foreman" / "SKILL.md"
    assert skill_md.exists()
    assert "vendor/bundled-skills/foreman/SKILL.md" in report["files"]

    # vendor_all report carried through.
    assert report["vendored_skills"] is not None
    assert any(v["name"] == "foreman"
               for v in report["vendored_skills"]["vendored"])

    # SOURCES.md exists and carries the 40-hex git SHA — which must NOT
    # high-entropy false-fail (it is under vendor/, skipped by the heuristic).
    sources_md = out / "vendor" / "bundled-skills" / "SOURCES.md"
    assert sources_md.exists()
    head = subprocess.run(
        ["git", "-C", str(trio_repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    assert head in sources_md.read_text(encoding="utf-8")

    # The host path / email committed in the source were scrubbed in vendoring,
    # so the vendored notes.md does not leak them.
    notes = (out / "vendor" / "bundled-skills" / "foreman" / "notes.md")
    if notes.exists():
        body = notes.read_text(encoding="utf-8")
        assert _SECRET_WIN not in body

    # Doubly sure: a direct re-scan of the staged dir is clean.
    assert distro.scan_staged_dir(out) == []


@requires_git
def test_vendored_sources_md_sha_not_high_entropy_failed(trio_repo, tmp_path, monkeypatch):
    """Focused: the vendored SOURCES.md (with its git SHA) scans clean — the
    generic high-entropy heuristic is NOT applied under vendor/."""
    monkeypatch.setenv("ANCHOR_TRIO_DIR", str(trio_repo))
    dest = tmp_path / "dest"
    vendor_skills.vendor_all(
        dest, sources=[("foreman", "ANCHOR_TRIO_DIR", "foreman")])
    sources_md = dest / "vendor" / "bundled-skills" / "SOURCES.md"
    rel = sources_md.relative_to(dest).as_posix()
    hits = list(distro._scan_text(rel, sources_md.read_text(encoding="utf-8")))
    assert hits == [], hits


# ── Done-when #2: a seeded host path in a NON-vendored staged file FAILS ──────

@requires_git
def test_seeded_host_path_in_nonvendored_file_raises(trio_repo, tmp_path, monkeypatch):
    """A C:\\dev\\secret\\x seeded into a NON-vendored staged product file
    raises PersonalDataError (the new detector fires); a build with that path
    only inside vendor/bundled-skills/ would NOT fail."""
    monkeypatch.setenv("ANCHOR_TRIO_DIR", str(trio_repo))
    root = tmp_path / "tree"
    root.mkdir()
    # A clean product file...
    import shutil
    shutil.copy2(distro.REPO_ROOT / "paths.py", root / "paths.py")
    if (distro.REPO_ROOT / "pillar_flags.py").is_file():
        shutil.copy2(distro.REPO_ROOT / "pillar_flags.py",
                     root / "pillar_flags.py")
    # ...and a leaky non-vendored one (host path assembled at runtime).
    leaky = root / "leaky_mod.py"
    leaky.write_text('BUILD = r"' + _SECRET_WIN + '"\nx = 1\n', encoding="utf-8")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("paths.py\nleaky_mod.py\n", encoding="utf-8")
    out = tmp_path / "export"

    with pytest.raises(distro.PersonalDataError) as ei:
        distro.build_distro(root=root, output_dir=out, manifest_path=manifest,
                            emit_readme_file=False, vendor_skills_=False)

    hits = ei.value.hits
    assert any(rel == "leaky_mod.py" and cat == "build-host-path"
               for (rel, cat, _) in hits), hits
    assert "leaky_mod.py" in str(ei.value)
    # The clean product file is not named.
    assert all(rel != "paths.py" for (rel, _, _) in hits
               if hits and hits[0])
    # Torn down on failure (nothing leaks).
    assert not out.exists()


def test_same_path_inside_vendored_does_not_fail():
    """The SAME secret host path, but inside a vendor/bundled-skills/ file,
    does NOT produce a build-host-path hit (vendored files are scrubbed/skipped
    for this heuristic)."""
    text = 'note = "' + _SECRET_WIN + '"\n'
    rel = "vendor/bundled-skills/foreman/notes.md"
    hits = [h for h in distro._scan_text(rel, text) if h[1] == "build-host-path"]
    assert hits == []


# ── Manifest allow-list wiring ───────────────────────────────────────────────

def test_manifest_allows_vendored_skills_and_generator():
    pats = distro.load_manifest()
    assert "vendor/bundled-skills/**" in pats
    assert "vendor_skills.py" in pats
    # vendor_skills.py is in the real shippable selection.
    assert "vendor_skills.py" in set(distro.select_shippable())

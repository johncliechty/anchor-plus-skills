"""Share-distro Wave 6 — onboard.py CORE (skills-install + scaffold + token).

Proves the Wave 6 Given/When/Then (IMPLEMENTATION-PLAN.md "## Wave 6" +
MASTER-PLAN decisions #7/#8/R3):

  1. FRESH RUN: installs all 4 skills (COPY) + scaffolds the starter files +
     writes a token file OUTSIDE the repo tree.
  2. IDEMPOTENT: a second run is a no-op — no duplicate skill, no overwritten
     scaffold, the SAME token (never re-minted).
  3. REFUSE-DON'T-CLOBBER: a pre-existing, differently-sourced
     ``<skills_home>/foreman`` is left UNTOUCHED and reported as refused.
  4. PARTIAL-INSTALL ROLLBACK + RESUME: an injected mid-install failure for
     skill 3-of-4 leaves NO partial skill-3 dir; a resume completes all 4.
  5. TOKEN OUT-OF-TREE: after onboard runs, a ``distro`` scan over the REPO is
     still CLEAN and the token file is NOT inside the repo / not staged.

HERMETIC: a temp ``ANCHOR_SKILLS_HOME`` + temp data dir + a temp
``ANCHOR_BUNDLED_SKILLS_DIR`` holding 4 FAKE skill dirs. NEVER touches the real
``~/.claude/skills`` or real Anchor data; never binds :8777; never network.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import onboard  # noqa: E402
import distro  # noqa: E402

FAKE_SKILLS = ["researchPrime", "crucible", "foreman", "gandalf"]


# --------------------------------------------------------------------------- #
# Fixtures — a fully hermetic temp environment.
# --------------------------------------------------------------------------- #
def _make_fake_bundle(root: Path) -> Path:
    """Create 4 fake skill dirs, each with a SKILL.md + a nested file."""
    src = root / "bundled-skills"
    src.mkdir(parents=True)
    # A non-skill provenance file that install_skills must IGNORE.
    (src / "SOURCES.md").write_text("# provenance\n", encoding="utf-8")
    for name in FAKE_SKILLS:
        d = src / name
        (d / "sub").mkdir(parents=True)
        (d / "SKILL.md").write_text("# %s\nfake skill body\n" % name, encoding="utf-8")
        (d / "sub" / "helper.py").write_text("# helper for %s\n" % name, encoding="utf-8")
    return src


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp skills-home + data-dir + bundled-skills source, all via env."""
    src = _make_fake_bundle(tmp_path / "vendor")
    home = tmp_path / "skills_home"
    data = tmp_path / "data"
    monkeypatch.setenv("ANCHOR_BUNDLED_SKILLS_DIR", str(src))
    monkeypatch.setenv("ANCHOR_SKILLS_HOME", str(home))
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    return {"src": src, "home": home, "data": data, "tmp": tmp_path}


# --------------------------------------------------------------------------- #
# 1. Fresh run.
# --------------------------------------------------------------------------- #
def test_fresh_run_installs_all_skills(env):
    rep = onboard.install_skills()
    assert {s["name"] for s in rep["installed"]} == set(FAKE_SKILLS)
    assert rep["refused"] == []
    assert rep["failed"] == []
    for name in FAKE_SKILLS:
        sk = env["home"] / name
        assert (sk / "SKILL.md").is_file()
        assert (sk / "sub" / "helper.py").is_file()
        # Marked as ours (so a re-run is idempotent).
        assert (sk / onboard._OURS_MARKER).is_file()
    # SOURCES.md is NOT a skill — it was not installed.
    assert not (env["home"] / "SOURCES.md").exists()


def test_fresh_run_scaffolds_starter(env):
    rep = onboard.scaffold_anchor()
    # The real starter/ tree is copied into the temp data dir.
    assert (env["data"] / "DASHBOARD.md").is_file()
    assert (env["data"] / "INBOX.md").is_file()
    assert (env["data"] / "domains" / "academic.md").is_file()
    assert len(rep["created"]) > 0
    assert rep["skipped"] == []


def test_fresh_run_token_outside_repo(env):
    rep = onboard.generate_token()
    tok_path = Path(rep["path"])
    assert rep["created"] is True
    assert tok_path.is_file()
    assert tok_path.read_text(encoding="utf-8").strip()  # non-empty
    # The token file is NOT inside the repo tree.
    assert rep["in_repo"] is False
    assert not onboard._is_inside_repo(tok_path)
    with pytest.raises(ValueError):
        tok_path.resolve().relative_to(REPO_ROOT)


# --------------------------------------------------------------------------- #
# 2. Idempotent re-run.
# --------------------------------------------------------------------------- #
def test_second_run_is_noop(env):
    onboard.install_skills()
    onboard.scaffold_anchor()
    tok1 = onboard.generate_token()
    token_value_1 = Path(tok1["path"]).read_text(encoding="utf-8")

    # Re-run.
    rep2 = onboard.install_skills()
    assert rep2["installed"] == []            # nothing re-installed
    assert {s["name"] for s in rep2["skipped"]} == set(FAKE_SKILLS)
    assert rep2["refused"] == []

    scaf2 = onboard.scaffold_anchor()
    assert scaf2["created"] == []             # nothing re-created
    assert len(scaf2["skipped"]) > 0

    tok2 = onboard.generate_token()
    assert tok2["created"] is False           # token NOT re-minted
    assert tok2["path"] == tok1["path"]
    assert Path(tok2["path"]).read_text(encoding="utf-8") == token_value_1

    # No duplicate skill dirs.
    installed = sorted(p.name for p in env["home"].iterdir() if p.is_dir())
    assert installed == sorted(FAKE_SKILLS)


# --------------------------------------------------------------------------- #
# 3. Refuse-don't-clobber a differently-sourced target.
# --------------------------------------------------------------------------- #
def test_refuse_dont_clobber_existing_foreman(env):
    # A pre-made, differently-sourced foreman dir (NOT ours — no marker).
    pre = env["home"] / "foreman"
    pre.mkdir(parents=True)
    sentinel = pre / "MINE.md"
    sentinel.write_text("do not clobber me\n", encoding="utf-8")

    rep = onboard.install_skills()

    # foreman was refused, not installed; the others went in.
    refused_names = {r["name"] for r in rep["refused"]}
    assert "foreman" in refused_names
    assert {s["name"] for s in rep["installed"]} == set(FAKE_SKILLS) - {"foreman"}

    # The pre-existing dir is UNTOUCHED — sentinel intact, no marker added.
    assert sentinel.read_text(encoding="utf-8") == "do not clobber me\n"
    assert not (pre / onboard._OURS_MARKER).exists()
    assert not (pre / "SKILL.md").exists()


# --------------------------------------------------------------------------- #
# 4. Partial-install rollback + resume.
# --------------------------------------------------------------------------- #
def test_partial_failure_rolls_back_then_resumes(env):
    # Inject a mid-copy failure for the 3rd skill (sorted order).
    fail_name = sorted(FAKE_SKILLS)[2]
    rep = onboard.install_skills(_fail_on=fail_name)

    failed_names = {f["name"] for f in rep["failed"]}
    assert fail_name in failed_names
    # NO partial skill-3 dir remains (rolled back cleanly).
    assert not (env["home"] / fail_name).exists()
    # The non-failing skills DID install.
    installed_now = {s["name"] for s in rep["installed"]}
    assert installed_now == set(FAKE_SKILLS) - {fail_name}

    # RESUME: a clean re-run completes all 4 (idempotent on the ones done).
    rep2 = onboard.install_skills()
    assert {s["name"] for s in rep2["installed"]} == {fail_name}
    for name in FAKE_SKILLS:
        assert (env["home"] / name / "SKILL.md").is_file()
        assert (env["home"] / name / onboard._OURS_MARKER).is_file()
    assert rep2["failed"] == []


# --------------------------------------------------------------------------- #
# 5. Token out-of-tree: the repo scan stays clean after onboard.
# --------------------------------------------------------------------------- #
def test_repo_scan_clean_after_onboard(env):
    # Run the full core orchestration against the temp env.
    rc = onboard.main(argv=[])
    assert rc == 0

    tok_path = onboard._default_token_path()
    assert tok_path.is_file()
    # The token landed in the temp data dir, OUTSIDE the repo.
    assert not onboard._is_inside_repo(tok_path)

    # No onboard artifact leaked into the repo tree: the only repo-resident files
    # are the source (onboard.py, starter/, etc.) — the token + skills + scaffold
    # all live under temp dirs. A scan over the *repo's manifest-selected* files
    # stays clean (the token is not among them).
    selected = distro.select_shippable(root=REPO_ROOT)
    pairs = [(rel, REPO_ROOT / rel) for rel in selected]
    hits = distro.scan_paths(pairs, root=REPO_ROOT)
    assert hits == [], "repo scan must stay clean after onboard: %r" % (hits,)

    # And explicitly: the token file is NOT among the manifest-selected files.
    tok_rel = None
    try:
        tok_rel = tok_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        tok_rel = None
    assert tok_rel is None or tok_rel not in selected


def test_detect_prereqs_never_hard_fails(env):
    rep = onboard.detect_prereqs()
    assert rep["python"]["present"] is True
    assert rep["python"]["ok"] is True
    # node / claude are OPTIONAL — present-or-not, but always reported, never raised.
    assert "present" in rep["node"]
    assert "present" in rep["claude"]
    assert rep["node"]["optional"] is True
    assert rep["claude"]["optional"] is True

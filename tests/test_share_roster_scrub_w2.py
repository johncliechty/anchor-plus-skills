"""Shareable Anchor + Skills — Wave 2 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 2): roster expansion (config-only), early canary (one Foundry + one
Trio) through git-archive → denylist → residual scrub → SOURCES, dual scrub
fixtures (planted-leak fails clean-scan / planted-legit passes), bundle
allowlist / stranger-tree no author credentials, money-safe mock archives.

Hermetic: TEMP git repos only via env injection; no real C:\\dev\\trio /
Skill Foundry, no network, no paid CLI, no :8777.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import distro  # noqa: E402
import share_capability_matrix as cap  # noqa: E402
import vendor_skills  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "share_scrub"
LEAK_FIXTURE = FIXTURE_ROOT / "planted_leak"
LEGIT_FIXTURE = FIXTURE_ROOT / "planted_legit"

# Assembled at runtime so this shipped test file embeds no contiguous secret.
_PII_EMAIL = "jane" + "@" + "uni" + ".edu"
_PII_HOSTPATH = "C:\\" + "Users\\jane\\private\\skill-data"
_PII_DEVPATH = "C:\\" + "dev\\secret-work\\notes"
_FAKE_TOKEN = "a9F3kZ2pQ7" + "wL5mN8xR1t" + "Y6vB4cD0eH2j"
_FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLX"  # 16 chars after AKIA


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        check=True, capture_output=True,
    )


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


def _write_skill_tree(skill_dir: Path, *, with_leak: bool = False,
                      with_author_junk: bool = True):
    """Populate a mock skill directory with shippable + denylisted content."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "# Skill\nSee `./src/run.mjs` and `test/smoke.md`.\n",
        encoding="utf-8",
    )
    src = skill_dir / "src"
    src.mkdir(exist_ok=True)
    (src / "run.mjs").write_text("export const ok = true;\n", encoding="utf-8")

    if with_author_junk:
        (skill_dir / "EXECUTION-LOG.md").write_text("personal log\n", encoding="utf-8")
        (skill_dir / "DECISION-LOG.md").write_text("decisions\n", encoding="utf-8")
        jdir = skill_dir / "journal"
        jdir.mkdir(exist_ok=True)
        (jdir / "day1.md").write_text("journal entry\n", encoding="utf-8")
        plan = skill_dir / "planning"
        plan.mkdir(exist_ok=True)
        (plan / "notes.md").write_text("author plan notes\n", encoding="utf-8")
        (skill_dir / "wave2-checkpoint.json").write_text("{}\n", encoding="utf-8")
        (skill_dir / ".env").write_text("TOKEN=hunter2\n", encoding="utf-8")
        (skill_dir / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
        (skill_dir / "_foreman-status.log").write_text("status\n", encoding="utf-8")

    if with_leak:
        (skill_dir / "notes.md").write_text(
            "Host %s contact %s token %s aws %s\n"
            % (_PII_HOSTPATH, _PII_EMAIL, _FAKE_TOKEN, _FAKE_AWS),
            encoding="utf-8",
        )
        (skill_dir / "devpath.md").write_text(
            "Build at %s\n" % _PII_DEVPATH, encoding="utf-8"
        )


@pytest.fixture
def trio_repo(tmp_path):
    """Mock trio monorepo with a foreman skill (canary Trio half)."""
    repo = tmp_path / "trio"
    _init_repo(repo)
    skill = repo / "foreman"
    _write_skill_tree(skill, with_leak=True, with_author_junk=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial trio")
    return repo


@pytest.fixture
def foundry_repo(tmp_path):
    """Mock Skill Foundry monorepo with literature-review under skills/."""
    repo = tmp_path / "foundry"
    _init_repo(repo)
    skill = repo / "skills" / "literature-review"
    _write_skill_tree(skill, with_leak=True, with_author_junk=True)
    # Extra Foundry-ish run residue that denylist must drop.
    out = skill / "litreview-out"
    out.mkdir()
    (out / "prisma-exclusions.json").write_text("{}\n", encoding="utf-8")
    scratch = skill / "scratch"
    scratch.mkdir()
    (scratch / "tmp.txt").write_text("tmp\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial foundry")
    return repo


# ── Roster config covers declared suite expansion path ───────────────────────

def test_roster_config_covers_declared_suite_and_baseline():
    names = vendor_skills.declared_skill_names()
    # 4-skill baseline preserved.
    for baseline in ("researchPrime", "crucible", "foreman", "gandalf"):
        assert baseline in names, baseline
    # Expansion toward full declared suite (capability matrix vendorable set).
    for expanded in (
        "jumper", "ramanujan", "legal-beagle", "literature-review",
        "financial-analyst", "tidy-idy", "zombie-hunter",
    ):
        assert expanded in names, expanded
    # Config-only: every entry is a 3-tuple with env var name.
    for name, env_var, subdir in vendor_skills.SKILL_SOURCES:
        assert isinstance(name, str) and name
        assert env_var.startswith("ANCHOR_") and env_var.endswith("_DIR")
        assert isinstance(subdir, str)


def test_canary_sources_are_one_trio_and_one_foundry():
    canary = vendor_skills.CANARY_SKILL_SOURCES
    assert len(canary) == 2
    names = vendor_skills.canary_skill_names()
    assert "foreman" in names
    assert "literature-review" in names
    envs = {env for _n, env, _s in canary}
    assert "ANCHOR_TRIO_DIR" in envs
    assert "ANCHOR_FOUNDRY_DIR" in envs


def test_roster_names_align_with_capability_matrix_vendorable():
    """Every non-Anchor-feature capability skill has a roster expansion path."""
    matrix = cap.load_matrix()
    vendorable = []
    for skill in matrix["skills"]:
        if skill.get("suite") == "anchor-feature":
            continue  # Anchor Doctor — not a vendored skill
        vendorable.append(skill["skill_id"])
    roster_lower = {n.lower() for n in vendor_skills.declared_skill_names()}
    for sid in vendorable:
        # skill_id is kebab/lowercase; roster uses display-ish names
        assert sid.lower() in roster_lower or any(
            sid.replace("-", "") in n.lower().replace("-", "")
            for n in vendor_skills.declared_skill_names()
        ), "capability skill %s missing from SKILL_SOURCES" % sid


def test_archive_scrub_public_api_still_frozen():
    """W2 freezes archive/scrub APIs — symbols remain callable as before."""
    assert callable(vendor_skills.vendor_all)
    assert callable(vendor_skills.vendor_canary)
    assert callable(vendor_skills._archive_subdir)
    assert callable(vendor_skills._apply_denylist)
    assert callable(vendor_skills._scrub_tree)
    assert callable(vendor_skills._scrub_text)
    assert callable(vendor_skills._is_denied)


# ── Dual CI fixtures: planted-leak fail / planted-legit pass ─────────────────

def test_dual_fixtures_exist_on_disk():
    assert (LEAK_FIXTURE / "leak_skill_notes.md").is_file()
    assert (LEGIT_FIXTURE / "SKILL.md").is_file()


def test_planted_leak_fails_clean_scan(tmp_path):
    """GWT: absolute author host path + secret-shaped token → clean-scan fails."""
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copy2(distro.REPO_ROOT / "paths.py", root / "paths.py")
    planted = root / "leak_skill_notes.md"
    shutil.copy2(LEAK_FIXTURE / "leak_skill_notes.md", planted)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("paths.py\nleak_skill_notes.md\n", encoding="utf-8")
    out = tmp_path / "export"

    with pytest.raises(distro.PersonalDataError) as ei:
        distro.build_distro(
            root=root, output_dir=out, manifest_path=manifest,
            emit_readme_file=False, vendor_skills_=False,
        )
    hits = ei.value.hits
    assert hits, "expected clean-scan hits for planted leak"
    cats = {cat for (_rel, cat, _snip) in hits}
    # At least one of path / token / secret categories must fire.
    assert cats & {
        "user-profile-path", "auth-token-value", "secret-token-literal",
        "build-host-path", "personal-email",
    }, hits
    assert not out.exists()  # torn down — publish blocked


def test_planted_legit_passes_clean_scan(tmp_path):
    """GWT: legitimate relative path prose → clean-scan passes (no false +)."""
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copy2(distro.REPO_ROOT / "paths.py", root / "paths.py")
    # paths.py imports first-party pillar_flags — stage it so import scan
    # does not false-positive as third-party when root is a sparse fixture tree.
    if (distro.REPO_ROOT / "pillar_flags.py").is_file():
        shutil.copy2(distro.REPO_ROOT / "pillar_flags.py", root / "pillar_flags.py")
    skill_dir = root / "skill_doc"
    skill_dir.mkdir()
    shutil.copy2(LEGIT_FIXTURE / "SKILL.md", skill_dir / "SKILL.md")
    manifest = tmp_path / "manifest.txt"
    man_lines = ["paths.py", "skill_doc/SKILL.md"]
    if (root / "pillar_flags.py").is_file():
        man_lines.insert(1, "pillar_flags.py")
    manifest.write_text("\n".join(man_lines) + "\n", encoding="utf-8")
    out = tmp_path / "export"

    report = distro.build_distro(
        root=root, output_dir=out, manifest_path=manifest,
        emit_readme_file=False, vendor_skills_=False,
    )
    assert report["files"]
    assert (out / "skill_doc" / "SKILL.md").is_file()
    body = (out / "skill_doc" / "SKILL.md").read_text(encoding="utf-8")
    assert "./src/cli.mjs" in body
    assert "skills/jumper/" in body
    assert distro.scan_staged_dir(out) == []


def test_planted_leak_fixture_not_in_shippable_manifest():
    """Bundle allowlist: planted-leak fixtures never ship."""
    selected = set(distro.select_shippable())
    assert not any("planted_leak" in f for f in selected)
    assert not any("planted_secret" in f for f in selected)


def test_bundle_allowlist_excludes_author_data_dirs():
    """Stranger-facing selection never includes author data dirs/secrets."""
    selected = set(distro.select_shippable())
    for prefix_or_name in vendor_skills.BUNDLE_AUTHOR_EXCLUDES:
        if prefix_or_name.endswith("/"):
            assert not any(f.startswith(prefix_or_name) for f in selected), (
                prefix_or_name
            )
        else:
            assert prefix_or_name not in selected, prefix_or_name
            assert not any(prefix_or_name in f for f in selected if
                           "planted" in prefix_or_name), prefix_or_name


# ── Canary path: mock archive + scrub-green + stranger-tree ──────────────────

@requires_git
def test_canary_vendors_trio_and_foundry_scrub_green(
    trio_repo, foundry_repo, tmp_path, monkeypatch
):
    """GWT: canary with mock archives + network denied completes scrub-green."""
    monkeypatch.setenv("ANCHOR_TRIO_DIR", str(trio_repo))
    monkeypatch.setenv("ANCHOR_FOUNDRY_DIR", str(foundry_repo))
    monkeypatch.delenv("ANCHOR_GANDALF_DIR", raising=False)

    dest = tmp_path / "dest"

    # Money-safe: refuse any non-local network socket during packaging.
    real_create = socket.socket
    def _no_network(*a, **kw):
        raise AssertionError("network socket forbidden during money-safe canary")
    monkeypatch.setattr(socket, "socket", _no_network)

    report = vendor_skills.vendor_canary(dest)

    assert {v["name"] for v in report["vendored"]} == {
        "foreman", "literature-review",
    }
    assert report["skipped"] == []

    for name in ("foreman", "literature-review"):
        skill_dir = dest / "vendor" / "bundled-skills" / name
        assert (skill_dir / "SKILL.md").is_file()
        assert (skill_dir / "src" / "run.mjs").is_file()
        # Denylist drops author junk.
        assert not (skill_dir / "EXECUTION-LOG.md").exists()
        assert not (skill_dir / "DECISION-LOG.md").exists()
        assert not (skill_dir / "journal").exists()
        assert not (skill_dir / "planning").exists()
        assert not (skill_dir / "wave2-checkpoint.json").exists()
        assert not (skill_dir / ".env").exists()
        assert (skill_dir / ".env.example").exists()
        assert not (skill_dir / "_foreman-status.log").exists()

    # Foundry-specific denylist expansions.
    lit = dest / "vendor" / "bundled-skills" / "literature-review"
    assert not (lit / "litreview-out").exists()
    assert not (lit / "scratch").exists()

    # Residual scrub removed host paths / emails / secrets.
    for notes_name in ("notes.md", "devpath.md"):
        for name in ("foreman", "literature-review"):
            p = dest / "vendor" / "bundled-skills" / name / notes_name
            if not p.exists():
                continue
            body = p.read_text(encoding="utf-8")
            assert _PII_HOSTPATH not in body
            assert _PII_DEVPATH not in body
            assert _PII_EMAIL not in body
            assert _FAKE_AWS not in body
            assert "<path>" in body or "<email>" in body or "<secret>" in body

    # SOURCES.md stub records both skills + commits.
    sources_md = (
        dest / "vendor" / "bundled-skills" / "SOURCES.md"
    ).read_text(encoding="utf-8")
    assert "foreman" in sources_md
    assert "literature-review" in sources_md
    for v in report["vendored"]:
        assert v["commit"] in sources_md

    # Stranger-tree: author credentials / raw host paths absent after scrub.
    bundle = dest / "vendor" / "bundled-skills"
    for p in bundle.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in vendor_skills._BINARY_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert "C:\\Users\\" not in text and "C:/Users/" not in text, p
        assert _PII_EMAIL not in text, p
        assert _FAKE_AWS not in text, p
        assert "ANCHOR_TOKEN = " not in text or _FAKE_TOKEN not in text, p

    # Clean-scan over the scrubbed canary tree is green.
    hits = distro.scan_staged_dir(dest)
    assert hits == [], hits

    # Restore socket (monkeypatch tears down, but be explicit for clarity).
    monkeypatch.setattr(socket, "socket", real_create)


@requires_git
def test_canary_money_safe_no_paid_cli_and_local_git_only(
    trio_repo, foundry_repo, tmp_path, monkeypatch
):
    """Packaging tests: mock archive fixtures only; no paid CLI invocations."""
    monkeypatch.setenv("ANCHOR_TRIO_DIR", str(trio_repo))
    monkeypatch.setenv("ANCHOR_FOUNDRY_DIR", str(foundry_repo))

    forbidden_bins = {
        "claude", "claude.exe", "agy", "agy.exe", "gemini", "gemini.exe",
        "grok", "grok.exe", "curl", "curl.exe", "wget", "wget.exe",
        "gh", "gh.exe", "npm", "npm.cmd", "npx", "npx.cmd",
    }
    calls = []
    real_run = subprocess.run

    def _guarded_run(cmd, *a, **kw):
        calls.append(list(cmd) if not isinstance(cmd, str) else [cmd])
        head = str(cmd[0]).lower().replace("\\", "/")
        base = Path(head).name
        if base in forbidden_bins:
            raise AssertionError("paid/network CLI forbidden in canary: %s" % cmd)
        # Only local git -C is expected from vendor_skills.
        if base in ("git", "git.exe"):
            return real_run(cmd, *a, **kw)
        raise AssertionError("unexpected subprocess in money-safe canary: %s" % cmd)

    monkeypatch.setattr(subprocess, "run", _guarded_run)
    dest = tmp_path / "dest"
    report = vendor_skills.vendor_canary(dest)
    assert report["vendored"]
    assert all(
        Path(c[0]).name.lower().startswith("git") for c in calls
    ), calls


@requires_git
def test_expanded_denylist_drops_planning_and_foreman_logs(tmp_path, monkeypatch):
    repo = tmp_path / "trio"
    _init_repo(repo)
    skill = repo / "foreman"
    _write_skill_tree(skill, with_leak=False, with_author_junk=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "denylist probe")

    monkeypatch.setenv("ANCHOR_TRIO_DIR", str(repo))
    dest = tmp_path / "dest"
    vendor_skills.vendor_all(
        dest, sources=[("foreman", "ANCHOR_TRIO_DIR", "foreman")]
    )
    skill_dir = dest / "vendor" / "bundled-skills" / "foreman"
    assert not (skill_dir / "planning").exists()
    assert not (skill_dir / "_foreman-status.log").exists()
    assert (skill_dir / "SKILL.md").exists()


@requires_git
def test_residual_secret_scrub_removes_aws_and_sk_shapes(tmp_path, monkeypatch):
    repo = tmp_path / "trio"
    _init_repo(repo)
    skill = repo / "foreman"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# ok\n", encoding="utf-8")
    (skill / "secrets.md").write_text(
        "key=%s sk=%s\n" % (_FAKE_AWS, "sk-" + "x" * 20),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "secrets")

    monkeypatch.setenv("ANCHOR_TRIO_DIR", str(repo))
    dest = tmp_path / "dest"
    vendor_skills.vendor_all(
        dest, sources=[("foreman", "ANCHOR_TRIO_DIR", "foreman")]
    )
    body = (
        dest / "vendor" / "bundled-skills" / "foreman" / "secrets.md"
    ).read_text(encoding="utf-8")
    assert _FAKE_AWS not in body
    assert "sk-" + "x" * 20 not in body
    assert "<secret>" in body


@requires_git
def test_unset_foundry_env_is_honest_skip_on_canary(tmp_path, monkeypatch):
    monkeypatch.delenv("ANCHOR_TRIO_DIR", raising=False)
    monkeypatch.delenv("ANCHOR_FOUNDRY_DIR", raising=False)
    dest = tmp_path / "dest"
    report = vendor_skills.vendor_canary(dest)
    assert report["vendored"] == []
    assert len(report["skipped"]) == 2
    reasons = " ".join(s["reason"] for s in report["skipped"])
    assert "ANCHOR_TRIO_DIR" in reasons
    assert "ANCHOR_FOUNDRY_DIR" in reasons


def test_full_roster_honest_skips_without_hardcoded_paths(tmp_path, monkeypatch):
    """Expanding SKILL_SOURCES never falls back to a real author path."""
    for env in (
        "ANCHOR_TRIO_DIR", "ANCHOR_GANDALF_DIR", "ANCHOR_FOUNDRY_DIR",
    ):
        monkeypatch.delenv(env, raising=False)
    dest = tmp_path / "dest"
    report = vendor_skills.vendor_all(dest)
    assert report["vendored"] == []
    assert len(report["skipped"]) == len(vendor_skills.SKILL_SOURCES)
    for skip in report["skipped"]:
        assert "no fallback" in skip["reason"] or "unset" in skip["reason"]
        assert "C:\\Users" not in skip["reason"]
        assert "C:\\dev" not in skip["reason"]

"""Hermetic tests for vendor_skills.vendor_all (share-distro Wave 3).

Every source repo is a TEMP git repo built here with ``git init`` + commit;
sources are configured exclusively via the env (ANCHOR_TRIO_DIR /
ANCHOR_GANDALF_DIR) — NEVER the real C:\\dev\\trio / Skill Foundry, never
network. The key assertion is that a COMMITTED EXECUTION-LOG.md is DROPPED by
the denylist (git archive alone would ship it).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vendor_skills  # noqa: E402

# PII strings are assembled at runtime so this SHIPPED test file embeds NO
# literal personal email / host path that the distro scanner would flag
# (the rnd-distro convention — see tests/test_distro_scan.py). They are written
# INTO the temp source repo to genuinely exercise the residual scrub.
_PII_EMAIL = "jane" + "@" + "uni" + ".edu"
_PII_HOSTPATH = "C:\\" + "dev\\foreman-targets\\x"


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


@pytest.fixture
def trio_repo(tmp_path):
    """A temp git repo holding a 'foreman' skill subdir with the full mix of
    (a) normal file, (b) gitignored+untracked runs/x.log, (c) committed
    EXECUTION-LOG.md, (d) dirty uncommitted file, (e) committed host-path/PII.
    """
    repo = tmp_path / "trio"
    _init_repo(repo)
    skill = repo / "foreman"
    skill.mkdir()

    # (a) committed normal file
    (skill / "SKILL.md").write_text("# Foreman\nA normal skill file.\n", encoding="utf-8")
    # gitignore that ignores runs/
    (repo / ".gitignore").write_text("runs/\n", encoding="utf-8")
    # (c) committed personal log — git archive WOULD keep this
    (skill / "EXECUTION-LOG.md").write_text("secret personal log\n", encoding="utf-8")
    # also a committed DECISION-LOG.md + a journal dir + a checkpoint + .env
    (skill / "DECISION-LOG.md").write_text("decisions\n", encoding="utf-8")
    jdir = skill / "journal"
    jdir.mkdir()
    (jdir / "day1.md").write_text("journal entry\n", encoding="utf-8")
    (skill / "wave3-checkpoint.json").write_text("{}\n", encoding="utf-8")
    (skill / ".env").write_text("TOKEN=hunter2\n", encoding="utf-8")
    (skill / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
    # (e) committed host-path + email (assembled at runtime — see top of file)
    (skill / "notes.md").write_text(
        "Build target at %s - contact %s\n" % (_PII_HOSTPATH, _PII_EMAIL),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    # (b) gitignored + UNTRACKED file (created AFTER commit, never tracked)
    (skill / "runs").mkdir()
    (skill / "runs" / "x.log").write_text("untracked run log\n", encoding="utf-8")
    # (d) dirty uncommitted change to a tracked file
    (skill / "SKILL.md").write_text(
        "# Foreman\nA normal skill file.\nDIRTY UNCOMMITTED LINE\n", encoding="utf-8"
    )

    return repo


@requires_git
def test_vendor_all_denylist_and_scrub(trio_repo, tmp_path, monkeypatch):
    dest = tmp_path / "dest"
    monkeypatch.setenv("ANCHOR_TRIO_DIR", str(trio_repo))
    monkeypatch.delenv("ANCHOR_GANDALF_DIR", raising=False)

    # Only vendor the 'foreman' skill from the trio repo for this test.
    report = vendor_skills.vendor_all(
        dest, sources=[("foreman", "ANCHOR_TRIO_DIR", "foreman")]
    )

    skill_dir = dest / "vendor" / "bundled-skills" / "foreman"
    assert skill_dir.is_dir()

    # (a) normal file present
    skillmd = skill_dir / "SKILL.md"
    assert skillmd.exists()
    # (d) dirty uncommitted line NOT shipped (archive is of the commit)
    assert "DIRTY UNCOMMITTED LINE" not in skillmd.read_text(encoding="utf-8")

    # NO .git/
    assert not (skill_dir / ".git").exists()
    # (b) NO gitignored+untracked runs/x.log
    assert not (skill_dir / "runs").exists()
    assert not (skill_dir / "runs" / "x.log").exists()

    # (c) THE KEY ASSERTION — committed EXECUTION-LOG.md dropped by the denylist
    assert not (skill_dir / "EXECUTION-LOG.md").exists()
    # other denylisted items dropped
    assert not (skill_dir / "DECISION-LOG.md").exists()
    assert not (skill_dir / "journal").exists()
    assert not (skill_dir / "wave3-checkpoint.json").exists()
    assert not (skill_dir / ".env").exists()
    # .env.example kept
    assert (skill_dir / ".env.example").exists()

    # (e) host-path + email scrubbed
    notes = (skill_dir / "notes.md").read_text(encoding="utf-8")
    assert _PII_HOSTPATH not in notes
    assert _PII_EMAIL not in notes
    assert "<path>" in notes
    assert "<email>" in notes

    # SOURCES.md records the archived commit sha
    sources_md = (dest / "vendor" / "bundled-skills" / "SOURCES.md").read_text(encoding="utf-8")
    head = subprocess.run(
        ["git", "-C", str(trio_repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert head in sources_md
    assert "foreman" in sources_md

    # report reflects the vendored skill
    assert report["vendored"]
    assert report["vendored"][0]["name"] == "foreman"
    assert report["vendored"][0]["commit"] == head


@requires_git
def test_unset_source_env_is_honest_skip_no_fallback(tmp_path, monkeypatch):
    """An UNSET source env causes an honest skip/refusal — never a real-path
    fallback."""
    dest = tmp_path / "dest"
    monkeypatch.delenv("ANCHOR_TRIO_DIR", raising=False)
    monkeypatch.delenv("ANCHOR_GANDALF_DIR", raising=False)

    report = vendor_skills.vendor_all(
        dest, sources=[("foreman", "ANCHOR_TRIO_DIR", "foreman")]
    )

    assert report["vendored"] == []
    assert len(report["skipped"]) == 1
    skip = report["skipped"][0]
    assert skip["name"] == "foreman"
    assert "ANCHOR_TRIO_DIR" in skip["reason"]
    # nothing was vendored — no skill dir created
    assert not (dest / "vendor" / "bundled-skills" / "foreman").exists()


@requires_git
def test_gandalf_from_repo_root(tmp_path, monkeypatch):
    """A skill whose subdir is '' is vendored from the repo root."""
    repo = tmp_path / "gandalf-src"
    _init_repo(repo)
    (repo / "SKILL.md").write_text("# Gandalf\n", encoding="utf-8")
    (repo / "EXECUTION-LOG.md").write_text("personal\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")

    dest = tmp_path / "dest"
    monkeypatch.setenv("ANCHOR_GANDALF_DIR", str(repo))
    report = vendor_skills.vendor_all(
        dest, sources=[("gandalf", "ANCHOR_GANDALF_DIR", "")]
    )

    skill_dir = dest / "vendor" / "bundled-skills" / "gandalf"
    assert (skill_dir / "SKILL.md").exists()
    assert not (skill_dir / "EXECUTION-LOG.md").exists()
    assert not (skill_dir / ".git").exists()
    assert report["vendored"][0]["name"] == "gandalf"

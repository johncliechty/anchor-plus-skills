"""Wave 1 (v8 "Durable Artifacts") — project bootstrap acceptance.

Locks the keystone prerequisite: registering / opening / rescanning a non-git
R&D folder must leave it a git repo (with an initial commit) + a starter
``CLAUDE.md``, idempotently, so a later ``worktrees.create_worktree`` / research
session start no longer dead-ends with ``not-a-git-repo``. Git must be reused
through ``worktrees._git`` (never forked), and a genuinely-absent git must
degrade to a clean reason WITHOUT raising.

Hermetic: real ``git init`` runs in TEMP dirs only (allowed — the existing
worktree/healthcheck tests do the same). NEVER any real push / gh / network /
``:8777`` / real data. The git-absent case is simulated by monkeypatching
``worktrees._git`` to fail (git is never actually uninstalled).
"""
import importlib
import subprocess
from pathlib import Path

import pytest


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A tmp data dir + tmp managed worktree base + freshly-reloaded modules."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))

    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import worktrees
    importlib.reload(worktrees)
    import project_bootstrap
    importlib.reload(project_bootstrap)

    return {"rnd": rnd_registry, "wt": worktrees, "pb": project_bootstrap,
            "tmp": tmp_path, "wbase": wbase}


def _is_repo(folder) -> bool:
    return (Path(folder) / ".git").exists()


def _committed_files(folder):
    out = subprocess.run(["git", "-C", str(folder), "ls-files"],
                         capture_output=True, text=True)
    return set(p for p in out.stdout.splitlines() if p.strip())


# ── ensure_git_repo ─────────────────────────────────────────────────────────

def test_ensure_git_repo_inits_and_commits(env):
    pb = env["pb"]
    folder = env["tmp"] / "proj"
    folder.mkdir()
    (folder / "a.txt").write_text("alpha\n", encoding="utf-8")
    (folder / "b.txt").write_text("bravo\n", encoding="utf-8")
    assert not _is_repo(folder)

    res = pb.ensure_git_repo(folder)
    assert res["ok"] is True
    assert res["initialized"] is True
    assert _is_repo(folder)
    # The existing files are captured in the initial commit.
    files = _committed_files(folder)
    assert {"a.txt", "b.txt"} <= files


def test_ensure_git_repo_idempotent(env):
    """A second call on an existing repo is a no-op (initialized:False)."""
    pb = env["pb"]
    folder = env["tmp"] / "idem"
    folder.mkdir()
    (folder / "f.txt").write_text("x\n", encoding="utf-8")

    first = pb.ensure_git_repo(folder)
    assert first["ok"] and first["initialized"] is True

    second = pb.ensure_git_repo(folder)
    assert second["ok"] is True
    assert second["initialized"] is False  # no-op, nothing re-initialized


def test_ensure_git_repo_honors_gitignore(env):
    """An ignored file is NOT committed by the bootstrap initial commit."""
    pb = env["pb"]
    folder = env["tmp"] / "ignored"
    folder.mkdir()
    (folder / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    (folder / "keep.txt").write_text("keep\n", encoding="utf-8")
    (folder / "secret.txt").write_text("nope\n", encoding="utf-8")

    res = pb.ensure_git_repo(folder)
    assert res["ok"] and res["initialized"] is True
    files = _committed_files(folder)
    assert "keep.txt" in files
    assert ".gitignore" in files
    assert "secret.txt" not in files  # honored .gitignore


def test_ensure_git_repo_git_absent_is_clean(env, monkeypatch):
    """git unavailable → clean reason WITHOUT raising (simulate via the seam)."""
    pb, wt = env["pb"], env["wt"]
    folder = env["tmp"] / "nogit"
    folder.mkdir()
    (folder / "x.txt").write_text("x\n", encoding="utf-8")

    # Simulate a missing git binary by pointing the shared _git wrapper at a
    # failure that looks like an absent binary — exactly what the real wrapper
    # returns when subprocess raises OSError. We do NOT uninstall git.
    def _fail(repo, args, timeout=None):
        return (False, None, "", "git invocation failed: [Errno 2] not found")
    monkeypatch.setattr(wt, "_git", _fail)

    res = pb.ensure_git_repo(folder)  # must not raise
    assert res["ok"] is False
    assert res["reason"] == "git-unavailable"
    assert not _is_repo(folder)


# ── ensure_claude_md ────────────────────────────────────────────────────────

def test_ensure_claude_md_creates_when_absent(env):
    pb = env["pb"]
    folder = env["tmp"] / "cm"
    folder.mkdir()
    assert not (folder / "CLAUDE.md").exists()

    res = pb.ensure_claude_md(folder, "My Project")
    assert res["created"] is True
    text = (folder / "CLAUDE.md").read_text(encoding="utf-8")
    assert "My Project" in text
    assert "R&D project managed by Anchor" in text


def test_ensure_claude_md_never_overwrites(env):
    pb = env["pb"]
    folder = env["tmp"] / "cm2"
    folder.mkdir()
    original = "# Hand-written\n\nDo not clobber.\n"
    (folder / "CLAUDE.md").write_text(original, encoding="utf-8")

    res = pb.ensure_claude_md(folder, "Whatever")
    assert res["created"] is False
    # The existing content is preserved verbatim.
    assert (folder / "CLAUDE.md").read_text(encoding="utf-8") == original


# ── register / open / rescan paths invoke bootstrap ─────────────────────────

def test_select_existing_project_bootstraps(env, monkeypatch):
    """Registering a non-git folder makes it a git repo + writes a CLAUDE.md."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(env["tmp"] / "data"))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(env["wbase"]))
    import anchor_gui
    importlib.reload(anchor_gui)

    folder = env["tmp"] / "registered"
    folder.mkdir()
    (folder / "readme.txt").write_text("hi\n", encoding="utf-8")
    assert not _is_repo(folder)

    res = anchor_gui.select_existing_project("Registered", str(folder))
    assert res["path_exists"] is True
    assert _is_repo(folder)
    assert (folder / "CLAUDE.md").exists()


def test_rescan_path_bootstraps(env, monkeypatch):
    """discover_and_adopt (the rescan + open path) bootstraps a non-git repo."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(env["tmp"] / "data"))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(env["wbase"]))
    import anchor_gui
    importlib.reload(anchor_gui)
    rnd = anchor_gui._rnd

    folder = env["tmp"] / "rescanme"
    folder.mkdir()
    (folder / "note.txt").write_text("note\n", encoding="utf-8")
    # Register WITHOUT going through the gui bootstrap helper, then rescan.
    proj = rnd.add_project("Rescan", str(folder), scaffold=False)
    assert not _is_repo(folder)

    anchor_gui.discover_and_adopt(proj["id"])
    assert _is_repo(folder)
    assert (folder / "CLAUDE.md").exists()


# ── the user's error is fixed: worktree-after-bootstrap succeeds ────────────

def test_worktree_after_bootstrap_succeeds(env):
    """After bootstrap, create_worktree no longer returns not-a-git-repo."""
    pb, wt, rnd = env["pb"], env["wt"], env["rnd"]
    folder = env["tmp"] / "fixed"
    folder.mkdir()
    (folder / "src.txt").write_text("code\n", encoding="utf-8")

    # Before bootstrap: a project on this folder fails with not-a-git-repo.
    proj = rnd.add_project("Fixed", str(folder), scaffold=False)
    before = wt.create_worktree(proj["id"], "sess-before")
    assert before["ok"] is False
    assert before["reason"] == "not-a-git-repo"

    # Bootstrap, then a worktree must succeed.
    boot = pb.ensure_git_repo(folder)
    assert boot["ok"] and boot["initialized"] is True

    after = wt.create_worktree(proj["id"], "sess-after")
    assert after["ok"] is True, after
    assert after.get("reason") != "not-a-git-repo"
    assert Path(after["path"]).exists()

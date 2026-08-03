"""Wave 2 — git-worktree isolation acceptance (hermetic, stdlib + real git).

Locks the v3 worktree isolation (MASTER-PLAN §F): each session gets its OWN git
worktree + branch under a MANAGED base outside the tracked tree; a dirty file in
one worktree is invisible to the other and to the main tree; remove takes one
down and leaves the other; ``reap_orphans`` cleans a worktree whose session is
gone.

Hermetic: a TEMP git repo is built per test (init + one commit), a project is
registered in ``rnd_registry`` (rooted at a tmp ``ANCHOR_DATA_DIR``) pointing at
it, and the managed worktree base is a tmp dir (``ANCHOR_WORKTREE_BASE``). NO
worktree is ever created off the real ``C:\\dev\\Anchor`` build repo. Uses the
real ``git`` on PATH (Windows host).
"""
import importlib
import subprocess

import pytest


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A tmp data dir, a tmp managed worktree base, and a tmp git repo."""
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

    # Build a hermetic temp git repo with one commit.
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    return {
        "wt": worktrees, "rnd": rnd_registry, "repo": repo,
        "pid": proj["id"], "wbase": wbase,
    }


# ── create: distinct path + branch per session ────────────────────────────

def test_create_two_sessions_distinct_worktrees(env):
    wt, pid, wbase = env["wt"], env["pid"], env["wbase"]
    a = wt.create_worktree(pid, "sess-a")
    b = wt.create_worktree(pid, "sess-b")
    assert a["ok"] and b["ok"], (a, b)
    assert a["path"] != b["path"]
    assert a["branch"] != b["branch"]
    # Both live under the managed base, outside the repo tree.
    assert str(wbase) in a["path"] and str(wbase) in b["path"]
    assert str(env["repo"]) not in a["path"]
    # Branches are deterministic from the session id.
    assert a["branch"] == wt.branch_for("sess-a")


def test_shared_prefix_ids_get_distinct_branches_and_isolated_worktrees(env):
    """Two ids sharing a 12-char prefix must NOT collide onto one branch/tree."""
    wt, pid = env["wt"], env["pid"]
    from pathlib import Path
    id_a = "abcdefghijkl-AAA"
    id_b = "abcdefghijkl-BBB"
    # The old truncate-to-12 scheme would map both to the same branch.
    assert wt.branch_for(id_a) != wt.branch_for(id_b)

    a = wt.create_worktree(pid, id_a)
    b = wt.create_worktree(pid, id_b)
    assert a["ok"] and b["ok"], (a, b)
    assert a["branch"] != b["branch"]
    assert a["path"] != b["path"]

    # Isolation: a file written in A is invisible in B.
    secret = Path(a["path"]) / "only_in_a.txt"
    secret.write_text("dirty\n", encoding="utf-8")
    assert secret.exists()
    assert not (Path(b["path"]) / "only_in_a.txt").exists()


def test_unknown_project_and_non_git_repo(env, tmp_path):
    wt, rnd = env["wt"], env["rnd"]
    assert wt.create_worktree("no-such-pid", "s")["reason"] == "unknown-project"
    # A project pointing at a non-git folder: Open terminal still works in-place
    # (no worktree isolation), named clearly so we never pretend isolation ran.
    plain = tmp_path / "plain"
    plain.mkdir()
    p2 = rnd.add_project("Plain", str(plain), scaffold=False)
    res = wt.create_worktree(p2["id"], "s2")
    assert res["ok"] is True
    assert res["isolation"] == "none"
    assert res["reason"] == "not-a-git-repo-in-place"
    assert res["path"] == str(plain)
    assert res["branch"] == "project-root"


def test_empty_unborn_repo_seeds_and_opens_worktree(env, tmp_path):
    """``git init`` with no commits used to refuse Open terminal with
    ``fatal: invalid reference: HEAD``. Auto-seed an empty commit and open.
    """
    wt, rnd = env["wt"], env["rnd"]
    empty = tmp_path / "empty-repo"
    empty.mkdir()
    assert _git(empty, "init", "-b", "master").returncode == 0
    # Unborn: rev-parse HEAD must fail before create.
    assert _git(empty, "rev-parse", "HEAD").returncode != 0
    p = rnd.add_project("Empty", str(empty), scaffold=False)
    res = wt.create_worktree(p["id"], "empty-sess")
    assert res["ok"] is True, res
    assert res.get("seeded_empty_commit") is True
    assert res.get("isolation") == "worktree"
    from pathlib import Path
    assert Path(res["path"]).is_dir()
    # HEAD is now a real commit; a second session also works without re-seed noise.
    res2 = wt.create_worktree(p["id"], "empty-sess-2")
    assert res2["ok"] is True, res2
    assert res2.get("seeded_empty_commit") in (None, False)


# ── isolation: a dirty file in A is invisible in B and the main tree ──────

def test_worktrees_are_isolated(env):
    wt, pid, repo = env["wt"], env["pid"], env["repo"]
    a = wt.create_worktree(pid, "iso-a")
    b = wt.create_worktree(pid, "iso-b")
    from pathlib import Path
    secret = Path(a["path"]) / "only_in_a.txt"
    secret.write_text("dirty\n", encoding="utf-8")

    assert secret.exists()
    assert not (Path(b["path"]) / "only_in_a.txt").exists()
    assert not (repo / "only_in_a.txt").exists()
    # The main tree's working dir is clean of A's dirty file.
    status = _git(repo, "status", "--porcelain").stdout
    assert "only_in_a.txt" not in status


# ── remove: takes one down, leaves the other ─────────────────────────────

def test_remove_one_leaves_other(env):
    wt, pid, repo = env["wt"], env["pid"], env["repo"]
    from pathlib import Path
    a = wt.create_worktree(pid, "rm-a")
    b = wt.create_worktree(pid, "rm-b")
    assert Path(a["path"]).exists() and Path(b["path"]).exists()
    # A's branch exists before removal.
    branches_before = _git(repo, "branch", "--list", a["branch"]).stdout
    assert a["branch"] in branches_before

    res = wt.remove_worktree("rm-a", project_id=pid)
    assert res["ok"] and res["removed"]
    assert not Path(a["path"]).exists()
    assert Path(b["path"]).exists()  # untouched

    # FIX 2: the per-session branch is deleted, not left to accumulate; B's
    # branch survives.
    branches_after = _git(repo, "branch", "--list", a["branch"]).stdout
    assert a["branch"] not in branches_after
    assert b["branch"] in _git(repo, "branch", "--list", b["branch"]).stdout


def test_remove_already_gone_is_tolerated(env):
    wt, pid = env["wt"], env["pid"]
    res = wt.remove_worktree("never-created", project_id=pid)
    assert res["ok"] is True
    assert res["removed"] is False
    assert res["reason"] == "already-gone"


def test_remove_refuses_unsafe_path(env, tmp_path):
    wt, pid = env["wt"], env["pid"]
    from pathlib import Path
    # A sentinel placed OUTSIDE the managed base — it must survive any traversal.
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("do not delete\n", encoding="utf-8")
    assert sentinel.exists()

    # A traversal session id resolves OUTSIDE the managed base, so the guard must
    # refuse it with reason "unsafe-path" and delete nothing.
    res = wt.remove_worktree("../escape", project_id=pid)
    assert res["ok"] is False
    assert res["reason"] == "unsafe-path"

    # An absolute-path session id is likewise refused.
    res2 = wt.remove_worktree(str(sentinel.parent), project_id=pid)
    assert res2["ok"] is False
    assert res2["reason"] == "unsafe-path"

    # Nothing outside the managed base was touched.
    assert sentinel.exists()


# ── reap_orphans: cleans worktrees whose session is gone ─────────────────

def test_reap_orphans(env):
    wt, pid = env["wt"], env["pid"]
    from pathlib import Path
    keep = wt.create_worktree(pid, "keep")
    drop = wt.create_worktree(pid, "drop")
    assert Path(keep["path"]).exists() and Path(drop["path"]).exists()

    report = wt.reap_orphans(active_session_ids={"keep"}, project_id=pid)
    assert "drop" in report["reaped"]
    assert "keep" in report["kept"]
    assert not Path(drop["path"]).exists()
    assert Path(keep["path"]).exists()


def test_list_managed_worktrees(env):
    wt, pid = env["wt"], env["pid"]
    wt.create_worktree(pid, "lm-a")
    wt.create_worktree(pid, "lm-b")
    ids = set(wt.list_managed_worktrees())
    assert {"lm-a", "lm-b"} <= ids

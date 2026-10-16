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


def test_empty_repo_seed_preserves_staged_files(env, tmp_path):
    """Opening a session must not commit the owner's staged first draft."""
    from pathlib import Path
    wt, rnd = env["wt"], env["rnd"]
    repo = tmp_path / "staged-unborn"
    repo.mkdir()
    assert _git(repo, "init", "-b", "main").returncode == 0
    draft = repo / "draft.txt"
    draft.write_text("Owner's uncommitted draft\n", encoding="utf-8")
    assert _git(repo, "add", "draft.txt").returncode == 0
    index = repo / ".git" / "index"
    original_index = index.read_bytes()
    project = rnd.add_project("Staged unborn", str(repo), scaffold=False)

    result = wt.create_worktree(project["id"], "staged-unborn-session")

    assert result["ok"], result
    assert index.read_bytes() == original_index
    assert _git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout == ""
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == "draft.txt"
    assert draft.read_text(encoding="utf-8") == "Owner's uncommitted draft\n"
    assert not (Path(result["path"]) / "draft.txt").exists()


def test_empty_repo_seed_opens_worktree_with_locked_source_index(env, tmp_path):
    """Real Windows sharing denial reproduces Doctor's .git/index failure."""
    import ctypes
    import os
    from ctypes import wintypes
    from pathlib import Path
    if os.name != "nt":
        pytest.skip("Windows index sharing semantics")
    wt, rnd = env["wt"], env["rnd"]
    repo = tmp_path / "locked-unborn"
    repo.mkdir()
    assert _git(repo, "init", "-b", "main").returncode == 0
    (repo / "draft.txt").write_text("Keep this staged\n", encoding="utf-8")
    assert _git(repo, "add", "draft.txt").returncode == 0
    index = repo / ".git" / "index"
    original_index = index.read_bytes()
    project = rnd.add_project("Locked unborn", str(repo), scaffold=False)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(index), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    try:
        result = wt.create_worktree(project["id"], "locked-unborn-session")
        assert result["ok"], result
        assert Path(result["path"]).is_dir()
    finally:
        kernel.CloseHandle(handle)
    assert index.read_bytes() == original_index
    assert _git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout == ""


def test_empty_repo_seed_preserves_concurrent_first_commit(env, tmp_path, monkeypatch):
    from pathlib import Path
    wt, rnd = env["wt"], env["rnd"]
    repo = tmp_path / "concurrent-unborn"
    repo.mkdir()
    assert _git(repo, "init", "-b", "main").returncode == 0
    (repo / "draft.txt").write_text("Owner's first commit\n", encoding="utf-8")
    assert _git(repo, "add", "draft.txt").returncode == 0
    tree = _git(repo, "write-tree").stdout.strip()
    owner_commit = _git(repo, "-c", "user.name=Owner", "-c",
                        "user.email=owner@localhost", "commit-tree", tree,
                        "--no-gpg-sign", "-m", "Owner's first commit").stdout.strip()
    assert owner_commit
    project = rnd.add_project("Concurrent unborn", str(repo), scaffold=False)
    original_git = wt._git

    def competing_git(folder, args, **kwargs):
        if args[0] == "update-ref":
            publication = original_git(folder, ["update-ref", "refs/heads/main",
                                                 owner_commit, ""])
            assert publication[0], publication
        return original_git(folder, args, **kwargs)

    monkeypatch.setattr(wt, "_git", competing_git)
    result = wt.create_worktree(project["id"], "concurrent-unborn-session")
    assert result["ok"], result
    assert result.get("resolved_via") == "concurrent-head"
    assert not result.get("seeded_empty_commit")
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == owner_commit
    assert (Path(result["path"]) / "draft.txt").read_text() == "Owner's first commit\n"


@pytest.mark.parametrize("command", ["mktree", "commit-tree", "update-ref"])
def test_empty_repo_seed_reports_real_publication_failure(env, tmp_path, monkeypatch,
                                                         command):
    wt, rnd = env["wt"], env["rnd"]
    repo = tmp_path / "failed-unborn"
    repo.mkdir()
    assert _git(repo, "init", "-b", "main").returncode == 0
    project = rnd.add_project("Failed unborn", str(repo), scaffold=False)
    original_git, original_git_env = wt._git, wt._git_env

    def failed_git(folder, args, **kwargs):
        if args[0] == command:
            return False, 128, "", "test: object or ref storage permission denied"
        return original_git(folder, args, **kwargs)

    def failed_git_env(folder, args, **kwargs):
        if args[0] == command:
            return False, 128, "", "test: object or ref storage permission denied"
        return original_git_env(folder, args, **kwargs)

    monkeypatch.setattr(wt, "_git", failed_git)
    monkeypatch.setattr(wt, "_git_env", failed_git_env)
    result = wt.create_worktree(project["id"], "failed-unborn-session")
    assert not result["ok"]
    assert result["reason"] == "empty-repo-seed-failed"
    assert result["returncode"] == 128
    assert "storage permission denied" in result["detail"]
    assert _git(repo, "rev-parse", "--verify", "HEAD").returncode != 0
    assert not wt.worktree_path_for("failed-unborn-session").exists()


def test_unreadable_existing_repository_is_not_seeded(env, monkeypatch):
    wt, repo = env["wt"], env["repo"]
    original_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    original_git = wt._git

    def unreadable_git(folder, args, **kwargs):
        if args[0] in ("rev-parse", "rev-list"):
            return False, 128, "", "test: repository read permission denied"
        return original_git(folder, args, **kwargs)

    def unexpected_seed(*args, **kwargs):
        pytest.fail("Failed reads must not trigger creation of a seed commit")

    monkeypatch.setattr(wt, "_git", unreadable_git)
    monkeypatch.setattr(wt, "_git_env", unexpected_seed)
    result = wt.create_worktree(env["pid"], "unreadable-session")
    assert not result["ok"]
    assert result["reason"] == "start-point-unavailable"
    assert "read permission denied" in result["detail"]
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == original_head
    assert not wt.worktree_path_for("unreadable-session").exists()


def test_empty_sha256_repository_seeds_worktree(env, tmp_path):
    wt, rnd = env["wt"], env["rnd"]
    repo = tmp_path / "sha256-unborn"
    repo.mkdir()
    initialized = _git(repo, "init", "--object-format=sha256", "-b", "main")
    if initialized.returncode != 0:
        pytest.skip("Git does not support SHA-256 repositories")
    project = rnd.add_project("SHA-256 unborn", str(repo), scaffold=False)
    result = wt.create_worktree(project["id"], "sha256-unborn-session")
    assert result["ok"], result
    assert result.get("seeded_empty_commit")
    assert len(_git(repo, "rev-parse", "HEAD").stdout.strip()) == 64
    assert _git(repo, "ls-tree", "-r", "--name-only", "HEAD").stdout == ""


@pytest.mark.parametrize("release_after_failure", [True, False])
def test_branch_ref_read_denial_is_retried_without_seeding(env, monkeypatch,
                                                         release_after_failure):
    """A Windows sharing denial produces Doctor's exact bad-object error."""
    import ctypes
    import os
    from ctypes import wintypes
    from pathlib import Path
    if os.name != "nt":
        pytest.skip("Windows ref sharing semantics")
    wt, repo = env["wt"], env["repo"]
    ref = repo / ".git" / "refs" / "heads" / "main"
    original_ref = ref.read_bytes()
    original_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(ref), 0x80000000, 0, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    original_git = wt._git
    failures = []

    def observed_git(folder, args, **kwargs):
        nonlocal handle
        result = original_git(folder, args, **kwargs)
        if args[0] == "rev-list" and not result[0]:
            failures.append(result)
            if release_after_failure and handle is not None:
                kernel.CloseHandle(handle)
                handle = None
        return result

    def unexpected_seed(*args, **kwargs):
        pytest.fail("An unreadable existing branch must not be seeded")

    monkeypatch.setattr(wt, "_git", observed_git)
    monkeypatch.setattr(wt, "_git_env", unexpected_seed)
    try:
        result = wt.create_worktree(env["pid"], "ref-denial-session")
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
    assert failures and "fatal: bad object refs/heads/main" in failures[0][3]
    assert ref.read_bytes() == original_ref
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == original_head
    assert not result.get("seeded_empty_commit")
    if release_after_failure:
        assert result["ok"], result
        assert result["start_point"] == original_head
        assert Path(result["path"]).is_dir()
    else:
        assert not result["ok"]
        assert result["reason"] == "start-point-unavailable"
        assert "bad object refs/heads/main" in result["detail"]
        assert not wt.worktree_path_for("ref-denial-session").exists()


def test_missing_commit_object_is_rejected_without_changing_ref(env, monkeypatch):
    """Resolving a ref's OID is insufficient if its commit does not exist."""
    wt, repo = env["wt"], env["repo"]
    ref = repo / ".git" / "refs" / "heads" / "main"
    missing_oid = "0" * 39 + "1"
    ref.write_text(missing_oid + "\n", encoding="ascii")
    original_ref = ref.read_bytes()

    def unexpected_seed(*args, **kwargs):
        pytest.fail("A missing commit object must not authorize a seed")

    monkeypatch.setattr(wt, "_git_env", unexpected_seed)
    result = wt.create_worktree(env["pid"], "missing-object-session")
    assert not result["ok"]
    assert result["reason"] == "start-point-unavailable"
    assert "bad object refs/heads/main" in result["detail"]
    assert ref.read_bytes() == original_ref
    assert not wt.worktree_path_for("missing-object-session").exists()


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

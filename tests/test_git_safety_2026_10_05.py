"""Part A of the delegated-work proposal v0.3 (approved by John 2026-10-05; incident 2026-10-04 18:59): nothing
automated rewrites a shared working tree. Hermetic: temp git repos only."""
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

import git_safety as gs
from steward_cockpit import steward_engine


def g(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    r = tmp_path / "shared"
    r.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"], ["config", "core.autocrlf", "false"]):
        g(r, *a)
    (r / "a.txt").write_bytes(b"one\n")          # exact bytes (Python text mode on Windows would write CRLF)
    (r / "b.txt").write_bytes(b"bee\n")
    g(r, "add", "-A"); g(r, "commit", "-qm", "start")
    return r


def _job_commit(repo, changes):
    """A job's change as a commit on a side branch (what a code job's worktree would hold)."""
    g(repo, "checkout", "-q", "-b", "job")
    for f, t in changes.items():
        if t is None:
            (repo / f).unlink()
        else:
            (repo / f).write_bytes(t.encode("utf-8"))
    g(repo, "add", "-A"); g(repo, "commit", "-qm", "job")
    sha = g(repo, "rev-parse", "HEAD").stdout.strip()
    g(repo, "checkout", "-q", "master" if g(repo, "rev-parse", "--verify", "master", check=False).returncode == 0 else "main")
    return sha


def test_a_clean_land_writes_only_its_files_and_leaves_others_staging_alone(repo):
    src = _job_commit(repo, {"a.txt": "two\n", "new.txt": "fresh\n"})
    (repo / "b.txt").write_text("someone else's staged edit\n", encoding="utf-8")
    g(repo, "add", "b.txt")
    (repo / "c.txt").write_text("someone else's untracked file\n", encoding="utf-8")
    ok, note = gs.land(repo, src, ["a.txt", "new.txt"], "job lands")
    assert ok, note
    assert g(repo, "show", "HEAD:a.txt").stdout == "two\n" and g(repo, "show", "HEAD:new.txt").stdout == "fresh\n"
    assert "b.txt" not in g(repo, "show", "--name-only", "--format=", "HEAD").stdout, "the other session's staging is not committed"
    assert g(repo, "diff", "--cached", "--name-only").stdout.strip() == "b.txt", "and it is still staged"
    assert (repo / "b.txt").read_text(encoding="utf-8") == "someone else's staged edit\n" and (repo / "c.txt").exists()


@pytest.mark.parametrize("make_dirty, why", [
    (lambda r: (r / "a.txt").write_text("his unsaved edit\n", encoding="utf-8"), "uncommitted edits"),
    (lambda r: ((r / "a.txt").write_text("staged then reverted\n", encoding="utf-8"), g(r, "add", "a.txt"),
                (r / "a.txt").write_text("one\n", encoding="utf-8")), "staged by someone else"),
])
def test_a_file_someone_else_changed_or_staged_never_lands(repo, make_dirty, why):
    src = _job_commit(repo, {"a.txt": "two\n"})
    make_dirty(repo)
    before = (repo / "a.txt").read_bytes()
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    assert not ok and why in note
    assert (repo / "a.txt").read_bytes() == before, "his work is untouched"


def test_a_new_file_that_exists_untracked_is_his(repo):
    src = _job_commit(repo, {"n.txt": "job's\n"})
    (repo / "n.txt").write_text("his own new file\n", encoding="utf-8")
    ok, note = gs.land(repo, src, ["n.txt"], "job")
    assert not ok and "someone else's new file" in note and (repo / "n.txt").read_text(encoding="utf-8") == "his own new file\n"


def test_runtime_and_steward_state_never_land(repo):
    for f in ("settings.json", "rnd_registry.json", "Setup and Mother Ship/.ecgberht/conversation-log.json", "x/strip.json"):
        ok, note = gs.land(repo, "HEAD", [f], "job")
        assert not ok and "never land" in note, f


def test_a_crlf_only_difference_is_clean_under_autocrlf_and_lf_bytes_are_kept(repo):
    g(repo, "config", "core.autocrlf", "true")
    src = _job_commit(repo, {"a.txt": "two\n"})
    (repo / "a.txt").write_bytes(b"one\r\n")          # the checkout convention, same content
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    assert ok, note
    assert (repo / "a.txt").read_bytes() == b"two\n", "bytes copied from the blob, no text-mode rewrite"


def test_the_snapshot_keeps_staged_unstaged_untracked_and_runtime_work(repo):
    (repo / "a.txt").write_text("unstaged edit\n", encoding="utf-8")
    (repo / "b.txt").write_text("staged edit\n", encoding="utf-8"); g(repo, "add", "b.txt")
    (repo / "b.txt").write_text("staged then edited again\n", encoding="utf-8")
    (repo / "u.txt").write_text("untracked\n", encoding="utf-8")
    (repo / ".gitignore").write_text("settings.json\n", encoding="utf-8")
    (repo / "settings.json").write_text('{"steward_type": "aladdin"}', encoding="utf-8")
    ref = gs.snapshot(repo, "test")
    assert ref.startswith(gs.SNAP_PREFIX)
    g(repo, "reset", "-q", "--hard")                       # the incident's kind of wipe, in the TEST repo
    (repo / "settings.json").write_text('{"steward_type": "jarvis"}', encoding="utf-8")
    for f in ("a.txt", "u.txt", "settings.json", "b.txt"):
        assert gs.restore_path(repo, ref, f)
    assert (repo / "a.txt").read_text(encoding="utf-8") == "unstaged edit\n" and (repo / "u.txt").exists()
    assert "aladdin" in (repo / "settings.json").read_text(encoding="utf-8")
    assert (repo / "b.txt").read_text(encoding="utf-8") == "staged then edited again\n"
    assert gs.restore_path(repo, ref, "b.txt", from_index=True) and (repo / "b.txt").read_text(encoding="utf-8") == "staged edit\n"
    assert any(r == ref for r, _, _ in gs.list_snapshots(repo))


def test_the_lock_admits_one_holder(repo):
    order = []

    def hold():
        with gs.repo_lock(repo, wait_s=5) as h:
            order.append(("a", h)); time.sleep(0.6)
    t = threading.Thread(target=hold); t.start(); time.sleep(0.2)
    with gs.repo_lock(repo, wait_s=0.1) as h2:
        order.append(("b-fast", h2))
    with gs.repo_lock(repo, wait_s=5) as h3:
        order.append(("b-wait", h3))
    t.join()
    assert order == [("a", True), ("b-fast", False), ("b-wait", True)]


def test_destructive_git_is_found_with_its_target(repo, tmp_path):
    hits = gs.destructive_git('git -C "C:/dev/Anchor" merge --no-ff x; git status 2>&1; git stash push -m t; git commit -m ok', "C:/here")
    assert hits == [("merge", "C:/dev/Anchor"), ("stash", "C:/here")], "commit and status are never destructive"
    own = tmp_path / "own"; own.mkdir(); g(own, "init", "-q")
    inside = repo / "cockpit"; inside.mkdir()
    assert not gs.shared_product_tree(str(own), str(own)), "a cockpit that is its own repo may use git freely"
    assert gs.shared_product_tree(str(inside), str(inside)), "a cockpit inside a product repo is in the shared tree"
    assert not gs.shared_product_tree(str(repo), str(repo / "x"), jobs_base_dir=str(tmp_path)), "a job's worktree is exempt"


def test_the_campaign_state_commit_is_by_pathspec(tmp_path, monkeypatch):
    import commission_session as cs
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    r = tmp_path / "proj"; r.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        g(r, *a)
    (r / "other.txt").write_text("x\n", encoding="utf-8"); g(r, "add", "-A"); g(r, "commit", "-qm", "s")
    (r / "other.txt").write_text("staged by another session\n", encoding="utf-8"); g(r, "add", "other.txt")
    p = cs.CAMPAIGN_STATE_PATHS[0]
    (r / p).parent.mkdir(parents=True, exist_ok=True)
    (r / p).write_text("campaign state\n", encoding="utf-8")
    out = cs.commit_campaign_state(str(r), "test")
    assert out["committed"], out
    assert "other.txt" not in g(r, "show", "--name-only", "--format=", "HEAD").stdout and \
        g(r, "diff", "--cached", "--name-only").stdout.strip() == "other.txt"


# ---------- gitguard: the git every agent runs (Grok code R1 F1-F3, F6) ----------
import os
import shutil
import sys

GUARD = Path(__file__).resolve().parent.parent / "tools" / "gitguard"
REAL_GIT = shutil.which("git")


def guarded(args, cwd, allow=""):
    env = dict(os.environ, GITGUARD_REAL_GIT=REAL_GIT, GITGUARD_PYTHON=sys.executable, GITGUARD_ALLOW_UNDER=allow,
               PATH=str(GUARD) + os.pathsep + os.environ.get("PATH", ""))
    return subprocess.run(["cmd", "/c", "git", *args] if os.name == "nt" else ["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True)


def test_the_guard_refuses_tree_rewriting_verbs_in_a_shared_tree(repo):
    (repo / "a.txt").write_bytes(b"his unsaved edit\n")
    for args in (["reset", "--hard"], ["checkout", "--", "a.txt"], ["stash"], ["restore", "a.txt"], ["merge", "x"],
                 ["-C", str(repo), "clean", "-fd"], ["--work-tree=" + str(repo), "--git-dir=" + str(repo / ".git"), "reset", "--hard"]):
        r = guarded(args, repo)
        assert r.returncode != 0 and "gitguard: refused" in r.stderr, args
    assert (repo / "a.txt").read_bytes() == b"his unsaved edit\n", "nothing ran"


def test_the_guard_passes_everything_else_through(repo):
    r = guarded(["status", "--porcelain"], repo)
    assert r.returncode == 0 and "gitguard" not in r.stderr
    (repo / "a.txt").write_bytes(b"edit\n")
    assert guarded(["add", "a.txt"], repo).returncode == 0
    assert guarded(["commit", "-qm", "ok"], repo).returncode == 0, "commit is never blocked"
    assert guarded(["rev-parse", "--verify", "nope"], repo).returncode != 0, "git's own exit code comes back"


def test_the_guard_allows_a_job_worktree(repo, tmp_path):
    jobs = tmp_path / "jobs"
    wt = jobs / "j1"
    g(repo, "worktree", "add", "-q", "-b", "j1", str(wt))
    r = guarded(["reset", "--hard"], wt, allow=str(jobs))
    assert r.returncode == 0, r.stderr
    r = guarded(["-C", str(repo), "reset", "--hard"], wt, allow=str(jobs))
    assert r.returncode != 0 and "refused" in r.stderr, "-C into the shared tree from a worktree is still refused"


def test_the_guard_fails_closed_without_the_real_git(repo):
    env = dict(os.environ, GITGUARD_REAL_GIT="", GITGUARD_PYTHON=sys.executable)
    r = subprocess.run([sys.executable, str(GUARD / "gitguard.py"), "status"], cwd=str(repo), env=env, capture_output=True, text=True)
    assert r.returncode != 0


def test_the_engine_puts_the_guard_first_on_every_agent_path(tmp_path, monkeypatch):
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    eng = steward_engine.Engine(str(tmp_path), fake=True)
    monkeypatch.setenv("ANCHOR_GITGUARD_DIR", str(tmp_path / "gg"))
    env = eng._spawn_env()
    first = env["PATH"].split(os.pathsep)[0]
    assert first == str(tmp_path / "gg" / "bin") and os.path.isfile(os.path.join(first, "git.exe")), first
    assert os.path.isfile(env["GITGUARD_REAL_GIT"]) and "gitguard" not in env["GITGUARD_REAL_GIT"] and "gg" not in env["GITGUARD_REAL_GIT"]
    assert env.get("BASH_ENV", "").endswith("bash_env.sh")
    eng.general = True
    assert eng._spawn_env()["PATH"].split(os.pathsep)[0] == first, "workbench terminals get the guard too (Grok code R2 N1)"
    assert not hasattr(eng, "_guard_destructive_git"), "no turn-killing git guard (Grok code R1 F6)"


def test_a_land_refuses_when_head_moved(repo):
    src = _job_commit(repo, {"a.txt": "two\n"})
    head = g(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "b.txt").write_bytes(b"someone committed\n"); g(repo, "commit", "-qam", "other")
    ok, note = gs.land(repo, src, ["a.txt"], "job", expect_head=head)
    assert not ok and "moved" in note


def test_a_land_refuses_while_runtime_state_is_tracked(repo):
    (repo / "settings.json").write_bytes(b"{}\n"); g(repo, "add", "settings.json"); g(repo, "commit", "-qm", "tracked")
    src = _job_commit(repo, {"a.txt": "two\n"})
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    assert not ok and "still tracks runtime state" in note



def test_the_built_git_exe_refuses_and_passes_arguments_exactly(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_GITGUARD_DIR", str(tmp_path / "gg"))
    sys.path.insert(0, str(GUARD.parent))
    from gitguard import install
    bin_dir, _ = install.ensure()
    exe = os.path.join(bin_dir, "git.exe")
    env = dict(os.environ, GITGUARD_REAL_GIT=REAL_GIT, GITGUARD_PYTHON=sys.executable, GITGUARD_ALLOW_UNDER=str(tmp_path / "nowhere"))
    (repo / "a.txt").write_bytes(b"his unsaved edit\n")
    r = subprocess.run([exe, "reset", "--hard"], cwd=str(repo), env=env, capture_output=True, text=True)
    assert r.returncode != 0 and "refused" in r.stderr and (repo / "a.txt").read_bytes() == b"his unsaved edit\n"
    msg = 'line1\nline2 a^b say "hi" & 100%'
    r = subprocess.run([exe, "commit", "-qam", msg], cwd=str(repo), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert g(repo, "log", "-1", "--format=%B").stdout.strip() == msg, "the message arrives byte for byte (Grok code R2 N2)"


def test_a_failed_byte_check_restores_the_file(repo, monkeypatch):
    src = _job_commit(repo, {"a.txt": "two\n"})
    real_read = Path.read_bytes

    def flaky(self):
        if self.name == "a.txt" and getattr(flaky, "armed", True):
            flaky.armed = False
            return b"someone else's bytes\n"
        return real_read(self)
    monkeypatch.setattr(Path, "read_bytes", flaky)
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    monkeypatch.setattr(Path, "read_bytes", real_read)
    assert not ok and "changed on disk" in note
    assert (repo / "a.txt").read_bytes() == b"one\n", "the file is put back as HEAD had it (Grok code R2 N3)"
    assert g(repo, "status", "--porcelain").stdout.strip() == "", "and nothing is staged"


def test_a_save_racing_the_commit_neither_enters_it_nor_is_lost(repo, monkeypatch):
    src = _job_commit(repo, {"a.txt": "two\n"})
    real = gs._git

    def racing(r, *args, **kw):
        if args[:1] == ("write-tree",) and "anchor-land" in ((kw.get("env") or {}).get("GIT_INDEX_FILE") or ""):
            (Path(r) / "a.txt").write_bytes(b"his fresh edit\n")    # he saves while the lander builds the commit
        return real(r, *args, **kw)
    monkeypatch.setattr(gs, "_git", racing)
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    monkeypatch.setattr(gs, "_git", real)
    assert ok, note
    assert g(repo, "show", "HEAD:a.txt").stdout == "two\n", "the commit holds the job's bytes, not his"
    assert (repo / "a.txt").read_bytes() == b"his fresh edit\n", "and his edit is still on disk, as a local change"


def test_a_failed_land_never_overwrites_a_concurrent_writers_bytes(repo, monkeypatch):
    src = _job_commit(repo, {"a.txt": "two\n"})
    real = gs._git

    def racing(r, *args, **kw):
        if args[:1] == ("write-tree",) and "anchor-land" in ((kw.get("env") or {}).get("GIT_INDEX_FILE") or ""):
            (Path(r) / "a.txt").write_bytes(b"his fresh edit\n")
            raise RuntimeError("boom")
        return real(r, *args, **kw)
    monkeypatch.setattr(gs, "_git", racing)
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    monkeypatch.setattr(gs, "_git", real)
    assert not ok
    assert (repo / "a.txt").read_bytes() == b"his fresh edit\n", "the rollback leaves his bytes alone"
    assert g(repo, "log", "-1", "--format=%s").stdout.strip() != "job"


def test_a_land_moves_head_only_by_compare_and_swap(repo, monkeypatch):
    src = _job_commit(repo, {"a.txt": "two\n"})
    real = gs._git

    def racing(r, *args, **kw):
        if args[:1] == ("write-tree",) and "anchor-land" in ((kw.get("env") or {}).get("GIT_INDEX_FILE") or ""):
            (Path(r) / "b.txt").write_bytes(b"x\n")
            real(r, "add", "b.txt"); real(r, "commit", "-qm", "someone else")
        return real(r, *args, **kw)
    monkeypatch.setattr(gs, "_git", racing)
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    monkeypatch.setattr(gs, "_git", real)
    assert not ok and "compare-and-swap" in note
    assert g(repo, "log", "-1", "--format=%s").stdout.strip() == "someone else", "his commit is never orphaned"


def test_paths_are_literal_never_patterns(repo):
    (repo / "a1.txt").write_bytes(b"sibling\n"); g(repo, "add", "a1.txt"); g(repo, "commit", "-qm", "sibling")
    src = _job_commit(repo, {"a[1].txt": "bracket\n"})
    (repo / "a1.txt").write_bytes(b"his staged edit\n"); g(repo, "add", "a1.txt")
    ok, note = gs.land(repo, src, ["a[1].txt"], "job")
    assert ok, note
    assert g(repo, "diff", "--cached", "--name-only").stdout.strip() == "a1.txt", "his staged sibling is untouched (Grok R4 #3)"


def test_a_held_index_lock_is_waited_out_before_success(repo, monkeypatch):
    src = _job_commit(repo, {"a.txt": "two\n"})
    lock = repo / ".git" / "index.lock"
    real = gs._git
    state = {"n": 0}

    def busy(r, *args, **kw):
        if args[:1] == ("reset",) and state["n"] < 2:
            state["n"] += 1
            lock.write_bytes(b"")
            out = real(r, *args, **kw)
            lock.unlink()
            return out
        return real(r, *args, **kw)
    monkeypatch.setattr(gs, "_git", busy)
    monkeypatch.setattr(gs.time, "sleep", lambda s: None)
    ok, note = gs.land(repo, src, ["a.txt"], "job")
    monkeypatch.setattr(gs, "_git", real)
    assert ok and "BUT" not in note, note
    assert state["n"] == 2
    assert g(repo, "diff", "--cached", "--name-only").stdout.strip() == "", "the shared index matches the new HEAD (Grok R4 #2)"

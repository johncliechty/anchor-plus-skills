"""v8 Wave 2 (THE KEYSTONE) — trio document persistence.

A trio session runs in a throwaway git WORKTREE and historically Anchor committed
only the tiny ``.pointer.json`` metadata — the DOCUMENTS a session produced
(MASTER-PLAN.md, the research report, EXECUTION-LOG, …) were deleted when the
worktree was reaped on kill. This wave makes those documents DURABLE: on session
finish/kill, BEFORE the worktree is reaped, the produced docs are copied into the
MAIN project folder and committed (scoped to just those docs + the effort
pointer/index — never ``git add -A``), recorded as discoverable efforts in the
main folder, so they survive the kill, ride into later (off-main-HEAD) worktrees,
and are found by ``handoff.discover_recent_plan_set``.

Locked acceptance (IMPLEMENTATION-PLAN Wave 2):
  - persisted into the project + committed (scoped to produced docs);
  - capture-before-reap (docs survive a kill; worktree gone);
  - a subsequently-created build worktree CONTAINS them;
  - ``discover_recent_plan_set`` finds them from the main folder;
  - idempotent (a re-persist of unchanged docs commits nothing) + scoped (the
    user's unrelated file in the main folder is never staged/committed).

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, a tmp data dir + tmp worktree base. NEVER binds
``:8777``; NEVER a worktree off the real ``C:\\dev\\Anchor`` repo; NEVER real
push / gh / network.
"""
import importlib
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


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


# ── env / fixtures (stub PTY + temp git repo + project) ──────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY + the fake runner + a temp git
    repo + a registered project. Reloads the full stack against the isolated env
    so start_session creates a real worktree off the TEMP repo (never C:\\dev)."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()

    import effort_history
    import handoff
    import terminal_session
    import session_registry
    import sessions
    import worktrees
    import rnd_registry

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {
        "ts": terminal_session, "reg": session_registry, "handoff": handoff,
        "eh": effort_history, "sessions": sessions, "wt": worktrees,
        "rnd": rnd_registry, "repo": repo, "pid": proj["id"],
        "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_plan_docs_in_worktree(worktree_path, plan_dir="planning/rnd-x"):
    """Stand in for what Crucible would write: a MASTER + IMPL plan set in the
    session's worktree (uncommitted, as a live session leaves them)."""
    wt = Path(worktree_path)
    master = f"{plan_dir}/MASTER-PLAN.md"
    impl = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    log = f"{plan_dir}/EXECUTION-LOG.md"
    for rel, body in [(master, "# Master Plan\nThe locked north star.\n"),
                      (impl, "# Implementation Plan\nWave-by-wave.\n"),
                      (log, "# Execution Log\n")]:
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return {"master": master, "impl": impl, "log": log}


# ════════════════════════════════════════════════════════════════════════════
# (1) persisted into the project + committed (scoped to produced docs)
# ════════════════════════════════════════════════════════════════════════════

def test_persist_copies_and_commits_scoped(env):
    """A planning session that wrote a plan set in its worktree → the docs exist
    in the MAIN folder AND are committed (a scoped commit; only those docs +
    pointer/index staged)."""
    ts, eh, repo, pid = env["ts"], env["eh"], env["repo"], env["pid"]

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    wt = plan_sess["worktree_path"]
    docs = _write_plan_docs_in_worktree(wt)

    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    res = eh.persist_session_docs(repo, pid, "planning", psid, wt)
    assert res["ok"] is True
    assert docs["master"] in res["persisted"]
    assert docs["impl"] in res["persisted"]
    assert res["committed"] is True

    # The docs now exist in the MAIN folder.
    assert (repo / docs["master"]).is_file()
    assert (repo / docs["impl"]).is_file()
    assert (repo / docs["log"]).is_file()

    # A new commit landed and is scoped: only the plan docs + the lane's
    # pointer-records/index were touched — NOTHING else (no README, no git add -A).
    head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head_after != head_before
    changed = set(_git(repo, "diff", "--name-only", head_before, head_after)
                  .stdout.split())
    assert docs["master"] in changed
    assert docs["impl"] in changed
    assert "README.md" not in changed
    # Every changed path is a plan doc or an .anchor pointer/index — nothing else.
    for c in changed:
        assert (c.startswith("planning/")
                or c.startswith(".anchor/")), f"unexpected staged path: {c}"

    ts.kill(psid)


def test_persist_scoped_leaves_user_unrelated_file_untouched(env):
    """A user's unrelated, dirty file in the MAIN folder is NEVER staged or
    committed by persistence (no ``git add -A``)."""
    ts, eh, repo, pid = env["ts"], env["eh"], env["repo"], env["pid"]

    # User edits an unrelated file in the main working tree (uncommitted).
    (repo / "NOTES.txt").write_text("my private scratch\n", encoding="utf-8")

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    _write_plan_docs_in_worktree(plan_sess["worktree_path"])
    eh.persist_session_docs(repo, pid, "planning", psid,
                            plan_sess["worktree_path"])

    # NOTES.txt is still untracked (never staged/committed by the scoped commit).
    status = _git(repo, "status", "--porcelain", "NOTES.txt").stdout
    assert "?? NOTES.txt" in status, "user's unrelated file must stay untracked"
    tracked = set(_git(repo, "ls-files").stdout.split())
    assert "NOTES.txt" not in tracked

    ts.kill(psid)


# ════════════════════════════════════════════════════════════════════════════
# (2) capture-before-reap: docs SURVIVE a kill (worktree gone)
# ════════════════════════════════════════════════════════════════════════════

def test_docs_survive_kill_worktree_gone(env):
    """Killing the session persists the docs to the MAIN folder BEFORE the
    worktree is reaped — the worktree is gone afterwards but the docs remain."""
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    wt = Path(plan_sess["worktree_path"])
    docs = _write_plan_docs_in_worktree(wt)
    assert wt.is_dir()

    out = ts.kill(psid)
    # kill() ran persistence (docs result present + persisted the plan docs).
    assert out["docs"]["ok"] is True
    assert docs["master"] in out["docs"]["persisted"]

    # The worktree is reaped …
    assert not wt.is_dir(), "worktree should be removed after kill"
    # … but the docs survive in the MAIN folder (and are committed).
    assert (repo / docs["master"]).is_file()
    assert (repo / docs["impl"]).is_file()
    tracked = set(_git(repo, "ls-files").stdout.split())
    assert docs["master"] in tracked and docs["impl"] in tracked


# ════════════════════════════════════════════════════════════════════════════
# (3) a NEW (build) worktree created afterward CONTAINS the docs
# ════════════════════════════════════════════════════════════════════════════

def test_build_worktree_contains_persisted_docs(env):
    """After persistence (commit to main HEAD), a freshly-created build worktree
    (checked out off main HEAD) physically CONTAINS the plan docs."""
    ts, repo, pid = env["ts"], env["repo"], env["pid"]

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    docs = _write_plan_docs_in_worktree(plan_sess["worktree_path"])
    ts.kill(psid)  # persists + commits to main HEAD, then reaps the worktree

    build_sess = ts.start_session(pid, "build", backend="claude")
    bsid = build_sess["session_id"]
    bwt = Path(build_sess["worktree_path"])
    # The build worktree is off the TEMP repo (never C:\dev), and HAS the docs.
    assert str(env["wbase"]) in str(bwt) and str(repo) not in str(bwt)
    assert (bwt / docs["master"]).is_file(), "build worktree missing the plan"
    assert (bwt / docs["impl"]).is_file()

    ts.kill(bsid)


# ════════════════════════════════════════════════════════════════════════════
# (4) discover_recent_plan_set finds them from the MAIN folder
# ════════════════════════════════════════════════════════════════════════════

def test_discover_finds_persisted_plan_set(env):
    """After a planning session's docs are persisted, ``discover_recent_plan_set``
    resolves the plan set to the MAIN-folder-relative paths."""
    ts, ho, repo, pid = env["ts"], env["handoff"], env["repo"], env["pid"]

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    docs = _write_plan_docs_in_worktree(plan_sess["worktree_path"])
    ts.kill(psid)

    plan_set = ho.discover_recent_plan_set(repo, pid, source_session_id=psid)
    assert plan_set is not None, "discover must find the persisted plan set"
    assert plan_set["master_plan_rel"] == docs["master"]
    assert plan_set["impl_plan_rel"] == docs["impl"]
    assert plan_set["plan_dir"] == "planning/rnd-x"
    # The resolved paths genuinely exist in the main folder.
    assert (repo / plan_set["master_plan_rel"]).is_file()


# ════════════════════════════════════════════════════════════════════════════
# (5) idempotent: a re-persist of UNCHANGED docs commits nothing
# ════════════════════════════════════════════════════════════════════════════

def test_persist_idempotent_no_duplicate_commit(env):
    """Re-persisting unchanged docs stages nothing → no second commit (idempotent
    on content-addressed effort ids + git's empty-commit guard)."""
    ts, eh, repo, pid = env["ts"], env["eh"], env["repo"], env["pid"]

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    wt = plan_sess["worktree_path"]
    _write_plan_docs_in_worktree(wt)

    first = eh.persist_session_docs(repo, pid, "planning", psid, wt)
    assert first["committed"] is True
    head1 = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # Re-persist the SAME, unchanged docs → nothing to commit.
    second = eh.persist_session_docs(repo, pid, "planning", psid, wt)
    assert second["ok"] is True
    assert second["committed"] is False
    head2 = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head2 == head1, "a re-persist must not create a duplicate commit"

    ts.kill(psid)


# ════════════════════════════════════════════════════════════════════════════
# (6) honesty: a session that produced NO docs persists nothing (no commit)
# ════════════════════════════════════════════════════════════════════════════

def test_no_docs_no_commit(env):
    """A session whose worktree has no produced docs persists nothing and creates
    no commit (best-effort, honest no-op)."""
    ts, eh, repo, pid = env["ts"], env["eh"], env["repo"], env["pid"]

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    res = eh.persist_session_docs(repo, pid, "planning", psid,
                                  plan_sess["worktree_path"])
    assert res["ok"] is True
    assert res["persisted"] == []
    assert res["committed"] is False
    head_after = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head_after == head_before

    ts.kill(psid)

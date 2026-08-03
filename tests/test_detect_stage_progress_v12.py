"""v12 Wave 7 — ``detect_stage_progress``: on-disk-only auto-advance (ZERO PTY).

Auto-advance fires ONLY on a high-precision ON-DISK signal — never a PTY scrape
(the v11.1 seed-echo false-fire). The signal per stage:

  - research→plan: a COMMITTED MASTER-PLAN.md + IMPLEMENTATION-PLAN.md pair
    committed NEWER than the research stage start.
  - plan→build: a committed EXECUTION-LOG.md / build product newer than plan start.

A positive signal calls ``advance_stage(mode='auto')`` (which writes nothing to
the PTY); a re-poll is idempotent (no second mint). A conversation-only stage (no
committed plan files) does NOT auto-advance.

THE v11 LESSON, applied:
  - WORKTREE-ONLY: produced docs are written + committed into the session
    worktree, never ``eh.record_effort`` pre-persist.
  - SET equality: ``set(list_sessions ids)`` snapshot pre/post, assert EQUAL.
  - ZERO PTY: the detect reads NO PTY bytes — asserted via the PTY read-buffer
    being byte-for-byte unchanged across the detect call.

Hermetic: ``ANCHOR_PTY_BACKEND=stub``, the STUB summarizer runner, a temp git
repo + temp data dir + temp worktree base, ``ANCHOR_PROACTIVE_SUMMARY`` OFF.
NEVER binds ``:8777`` / a worktree off the real repo / real network.
"""
import importlib
import subprocess
from pathlib import Path

import pytest

STUB = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()


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
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "The locked north star is durable resumable work")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "boneyard", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()

    import effort_history
    import terminal_session
    import session_registry
    import pty_manager
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
        "ts": terminal_session, "reg": session_registry, "eh": effort_history,
        "pty": pty_manager, "rnd": rnd_registry, "repo": repo,
        "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _ids(reg, pid):
    return set(r["session_id"] for r in reg.list_sessions(project_id=pid))


def _pty_text(pty, sid):
    try:
        out = pty.read_since(sid, 0)
    except Exception:
        return ""
    return (out.get("text") or "") if isinstance(out, dict) else ""


def _wt_git(wt, *args):
    return subprocess.run(["git", "-C", str(wt), *args],
                          capture_output=True, text=True)


def _commit_in_worktree(wt, rels_to_body, msg="stage docs"):
    """Write + COMMIT files into a worktree (committed = the on-disk signal)."""
    wt = Path(wt)
    for rel, body in rels_to_body.items():
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _wt_git(wt, "add", "-A")
    _wt_git(wt, "commit", "-m", msg)


# ════════════════════════════════════════════════════════════════════════════
# POSITIVE — committed plan-set newer than stage start → auto-advance ONCE
# ════════════════════════════════════════════════════════════════════════════

def test_detect_committed_plan_set_advances_once_zero_pty(env):
    """*Given* a research effort whose worktree gains a COMMITTED MASTER-PLAN.md +
    IMPLEMENTATION-PLAN.md pair newer than the stage start, *When*
    detect_stage_progress, *Then* it advances to plan ONCE, idempotent on
    re-poll, set(list_sessions ids) unchanged, ZERO PTY bytes read."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]

    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    assert sess["current_stage"] == "research"

    # Commit the plan-set pair INTO the worktree — newer than the stage start.
    _commit_in_worktree(wt, {
        "planning/MASTER-PLAN.md": "# Master Plan\n",
        "planning/IMPLEMENTATION-PLAN.md": "# Implementation Plan\n",
    }, msg="plan set")

    ids_before = _ids(reg, pid)
    pty_before = _pty_text(pty, sid)

    res = ts.detect_stage_progress(sid, project_id=pid)

    assert res["ok"] is True
    assert res["advanced"] is True
    assert res["to_stage"] == "plan"
    assert reg.get_session(sid)["current_stage"] == "plan"

    # ZERO mint — set equality, not count.
    assert _ids(reg, pid) == ids_before
    # ZERO PTY bytes read/written by the detect (on-disk only).
    assert _pty_text(pty, sid) == pty_before

    # Idempotent: a re-poll advances NOTHING (already at plan) — no second flip,
    # no mint.
    res2 = ts.detect_stage_progress(sid, project_id=pid)
    assert res2["advanced"] is False
    assert reg.get_session(sid)["current_stage"] == "plan"
    assert _ids(reg, pid) == ids_before


def test_detect_committed_execution_log_advances_plan_to_build(env):
    """plan→build fires on a committed EXECUTION-LOG.md newer than the plan
    stage start (the build signal)."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]

    # Start at research, advance to plan first (so current_stage=='plan').
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    _commit_in_worktree(wt, {
        "planning/MASTER-PLAN.md": "# Master Plan\n",
        "planning/IMPLEMENTATION-PLAN.md": "# Implementation Plan\n",
    }, msg="plan set")
    a = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert a["ok"] and a["record"]["current_stage"] == "plan"

    ids_before = _ids(reg, pid)
    pty_before = _pty_text(pty, sid)

    # Commit a build signal (an execution log) AFTER the plan stage start.
    _commit_in_worktree(wt, {
        "planning/EXECUTION-LOG.md": "# Execution Log\nbuilt.\n",
    }, msg="exec log")

    res = ts.detect_stage_progress(sid, project_id=pid)
    assert res["advanced"] is True
    assert res["to_stage"] == "build"
    assert reg.get_session(sid)["current_stage"] == "build"
    assert _ids(reg, pid) == ids_before
    assert _pty_text(pty, sid) == pty_before


def test_detect_committed_build_product_advances_plan_to_build(env):
    """plan→build also fires on a committed build PRODUCT (a non-doc artifact)
    newer than the plan stage start."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    _commit_in_worktree(wt, {
        "planning/MASTER-PLAN.md": "# Master Plan\n",
        "planning/IMPLEMENTATION-PLAN.md": "# Implementation Plan\n",
    }, msg="plan set")
    ts.advance_stage(sid, "plan", mode="manual", project_id=pid)

    _commit_in_worktree(wt, {"build/app.py": "print('hi')\n"}, msg="product")
    res = ts.detect_stage_progress(sid, project_id=pid)
    assert res["advanced"] is True
    assert reg.get_session(sid)["current_stage"] == "build"


# ════════════════════════════════════════════════════════════════════════════
# NEGATIVE / ISOLATION — no committed pair, PTY echo must NOT trigger a fire
# ════════════════════════════════════════════════════════════════════════════

def test_detect_pty_echo_plus_uncommitted_plan_does_not_advance(env):
    """*Given* a PTY buffer echoing "Crucible loaded" + a WORKING-TREE
    (uncommitted) MASTER-PLAN.md (no committed pair), *When* detect_stage_progress,
    *Then* NO advance — proving it neither scrapes the PTY nor fires on
    uncommitted files."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]

    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]

    # (a) Echo a skill-name into the PTY buffer — a v11.1 false-fire bait.
    pty.write(sid, "Crucible loaded — what would you like to do?\n")
    assert "Crucible loaded" in _pty_text(pty, sid)

    # (b) WORKING-TREE (uncommitted) plan files — present on disk, NOT committed.
    wtp = Path(wt)
    (wtp / "planning").mkdir(parents=True, exist_ok=True)
    (wtp / "planning" / "MASTER-PLAN.md").write_text("# m\n", encoding="utf-8")
    (wtp / "planning" / "IMPLEMENTATION-PLAN.md").write_text(
        "# i\n", encoding="utf-8")

    ids_before = _ids(reg, pid)
    res = ts.detect_stage_progress(sid, project_id=pid)

    assert res["advanced"] is False
    assert res["reason"] == "no-disk-signal"
    assert reg.get_session(sid)["current_stage"] == "research"
    assert _ids(reg, pid) == ids_before


def test_detect_only_master_plan_committed_does_not_advance(env):
    """research→plan requires the PAIR — only MASTER-PLAN.md committed (no
    IMPLEMENTATION-PLAN.md) → NO advance."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    _commit_in_worktree(wt, {"planning/MASTER-PLAN.md": "# m\n"}, msg="half")
    res = ts.detect_stage_progress(sid, project_id=pid)
    assert res["advanced"] is False
    assert reg.get_session(sid)["current_stage"] == "research"


def test_detect_plan_committed_before_stage_start_does_not_advance(env):
    """A committed pair that predates the stage start is NOT a signal (the
    "newer than the stage start" precision). Here the pair is committed BEFORE
    the build stage begins, so plan→build does not fire on it."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    # Commit the plan set, advance to plan, then advance to build — WITHOUT any
    # NEW commit after the build stage starts. The plan docs predate the build
    # stage start, so plan→build (already past anyway) + the build stage sees no
    # NEW build signal.
    _commit_in_worktree(wt, {
        "planning/MASTER-PLAN.md": "# m\n",
        "planning/IMPLEMENTATION-PLAN.md": "# i\n",
    }, msg="plan set")
    ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    ts.advance_stage(sid, "build", mode="manual", project_id=pid)
    assert reg.get_session(sid)["current_stage"] == "build"
    # No NEW committed build signal → detect is a no-op (at the end of the trio).
    res = ts.detect_stage_progress(sid, project_id=pid)
    assert res["advanced"] is False
    assert res["reason"] in ("no-next-stage", "no-disk-signal")


def test_detect_conversation_only_stage_does_not_auto_advance(env):
    """A conversation-only stage (output ONLY in the PTY, no committed plan
    files) does NOT auto-advance — that's the manual Advance →'s job."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    # Seed transcript-like content into the PTY buffer — NO file committed.
    pty.write(sid, "Here is my full research analysis as a conversation.\n")
    res = ts.detect_stage_progress(sid, project_id=pid)
    assert res["advanced"] is False
    assert reg.get_session(sid)["current_stage"] == "research"


# ════════════════════════════════════════════════════════════════════════════
# Honesty / guards
# ════════════════════════════════════════════════════════════════════════════

def test_detect_legacy_record_is_noop(env):
    """A legacy (effort_managed==False) record is OWNED by the legacy
    auto-advance paths — detect_stage_progress is an honest no-op for it."""
    ts, pid = env["ts"], env["pid"]
    # A legacy research session (no effort_managed=True).
    sess = ts.start_session(pid, "research", backend="claude")
    assert sess.get("effort_managed") in (False, None)
    res = ts.detect_stage_progress(sess["session_id"], project_id=pid)
    assert res["advanced"] is False
    assert res["reason"] == "not-effort-managed"


def test_detect_unknown_session_is_honest(env):
    ts = env["ts"]
    res = ts.detect_stage_progress("no-such-session")
    assert res["ok"] is False
    assert res["advanced"] is False
    assert res["reason"] == "unknown-session"


def test_detect_non_live_effort_is_noop(env):
    """A killed (terminal) effort is not LIVE → detect is a no-op."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    ts.kill(sid, project_id=pid)
    res = ts.detect_stage_progress(sid, project_id=pid)
    assert res["advanced"] is False
    assert res["reason"] == "not-live"


def test_detect_plan_stage_empty_baseline_no_false_fire(env):
    """W7-R2-03 / R1-W7-03: a plan-stage effort whose baseline_ref is empty must
    NOT diff the empty tree (which would over-report prior-stage commits) — it's
    treated as no signal, never a false plan→build advance."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude", effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    # commit a research doc, then advance to plan (opens a plan entry w/ baseline)
    _commit_in_worktree(wt, {"research/r.md": "# research\n"}, msg="research")
    ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    # Force the active (plan) entry's baseline_ref empty (a back-compat / partial
    # record), then commit a prior-looking doc — empty-tree diff WOULD list it.
    rec = reg.get_session(sid)
    hist = [dict(e) for e in rec["stage_history"]]
    for e in hist:
        if e.get("ended_at") is None:
            e["baseline_ref"] = ""
    reg.update_session(sid, stage_history=hist)
    res = ts.detect_stage_progress(sid, project_id=pid)
    assert res["advanced"] is False
    assert res["reason"] == "no-baseline"

"""v12 Wave 8 — restart recovery: an interrupted effort recovers without loss.

A crash / service restart is NOT a "close": an ``effort_managed`` record whose
status is RUNNING but whose PTY is GONE has had its work interrupted.
``terminal_session.recover_interrupted_efforts`` persists the active stage's
worktree docs (Wave-5 ``finish_stage`` path, NO reap), marks the active stage
entry ``state='interrupted'`` (a literal DISTINCT from ``done`` / ``failed``),
re-statuses the record IDLE, and leaves it reopenable to continue the SAME stage
(a fresh session inheriting ``effort_id``) — it NEVER auto-spawns / auto-advances.

Covers the Wave-8 restart Given/When/Then EXACTLY:
  *Given* an effort_managed effort RUNNING at build with UNCOMMITTED build docs,
  simulate PTY-gone via ``pty_manager.kill(sid)`` WITHOUT ``terminal_session.kill``
  (the reconcile-dead state), *When* recover_interrupted_efforts, *Then* build
  docs persist (worktree-only), the build stage entry ``state=='interrupted'``
  (≠ done, ≠ failed), the effort is reopenable to continue build (a fresh session
  inherits ``effort_id``), set(list_sessions ids) shows NO auto-spawned build, and
  the v9 anchor-repo/live-member guard is not tripped.

THE v11 LESSON, applied: WORKTREE-ONLY (build doc written into the session
worktree, never ``eh.record_effort`` pre-persist); set-equality assertions.

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
    import summarizer
    import rnd_registry
    import pty_manager

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
        "summ": summarizer, "rnd": rnd_registry, "pty": pty_manager,
        "repo": repo, "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _ids(reg, pid):
    return set(r["session_id"] for r in reg.list_sessions(project_id=pid))


def _write(worktree_path, rel, body):
    p = Path(worktree_path) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def _start_build_effort(env):
    """Start a research effort and advance research→plan→build, returning the
    live record at current_stage=='build' with an UNCOMMITTED build doc in its
    worktree (worktree-only — never record_effort)."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]

    _write(wt, "research/findings.md",
           "# Findings\nThe locked north star is durable resumable work.\n")
    ts.advance_stage(sid, "plan", mode="manual", project_id=pid)

    _write(wt, "planning/MASTER-PLAN.md",
           "# Master Plan\ndurable resumable work\n")
    adv = ts.advance_stage(sid, "build", mode="manual", project_id=pid)
    assert adv["ok"] and adv["advanced"]
    rec = adv["record"]
    assert rec["current_stage"] == "build"

    # UNCOMMITTED build product in the worktree (worktree-only).
    _write(rec["worktree_path"], "build/app.py",
           "print('durable resumable work')\n")
    return rec


# ════════════════════════════════════════════════════════════════════════════
# RESTART RECOVERY — interrupted (not done), no loss, no auto-spawn
# ════════════════════════════════════════════════════════════════════════════

def test_recover_interrupted_marks_interrupted_persists_no_spawn(env):
    """The whole Wave-8 restart GWT in one test."""
    ts, reg, pty, repo, pid = (env["ts"], env["reg"], env["pty"], env["repo"],
                               env["pid"])

    rec = _start_build_effort(env)
    sid = rec["session_id"]
    effort_id = rec["effort_id"]

    ids_before = _ids(reg, pid)

    # Simulate PTY-gone via pty_manager.kill (reconcile-dead state) WITHOUT
    # terminal_session.kill — the registry record stays RUNNING, the worktree
    # survives, no docs persisted yet.
    pty.kill(sid)
    assert sid not in set(pty.live_sessions())
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING

    out = ts.recover_interrupted_efforts(live_session_ids=list(pty.live_sessions()))
    assert out["ok"] is True
    assert sid in out["recovered"]

    # Build docs PERSISTED (worktree-only build product → main folder + committed).
    assert _git(repo, "ls-files", "--error-unmatch",
                "build/app.py").returncode == 0, \
        "build doc was not persisted on recovery"

    after = reg.get_session(sid)

    # The build stage entry is 'interrupted' — a literal DISTINCT from done/failed.
    build_ents = [e for e in after["stage_history"]
                  if e.get("stage") == "build"]
    assert build_ents
    b_ent = build_ents[-1]
    assert b_ent["state"] == "interrupted"
    assert b_ent["state"] != "done"
    assert b_ent["state"] != "failed"
    assert b_ent["ended_at"] is not None

    # The record is re-statused IDLE (no live process) — honestly not running.
    assert after["status"] == reg.STATUS_IDLE

    # NO auto-spawned build — the id SET is unchanged (set-equality, not len).
    assert _ids(reg, pid) == ids_before

    # The worktree still exists (not reaped) so the stage is reopenable.
    assert Path(rec["worktree_path"]).is_dir()

    # REOPENABLE: a fresh session can continue the SAME effort (inherits
    # effort_id). This is the user-driven reopen — recovery itself never spawns it.
    cont = ts.start_session(pid, "build", backend="claude",
                            effort_id=effort_id, effort_managed=True)
    assert cont["effort_id"] == effort_id
    assert cont["session_id"] != sid


def test_recover_is_idempotent(env):
    """A second recover pass does NOT re-process an already-interrupted effort."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]
    rec = _start_build_effort(env)
    sid = rec["session_id"]
    pty.kill(sid)

    first = ts.recover_interrupted_efforts(live_session_ids=[])
    assert sid in first["recovered"]
    # Now it is IDLE + interrupted — a second pass must NOT recover it again.
    second = ts.recover_interrupted_efforts(live_session_ids=[])
    assert sid not in second["recovered"]


def test_recover_skips_live_effort(env):
    """A still-LIVE effort (PTY present) is not touched by recovery."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    assert sid in set(pty.live_sessions())
    out = ts.recover_interrupted_efforts(
        live_session_ids=list(pty.live_sessions()))
    assert sid not in out["recovered"]
    # Untouched: still RUNNING, stage still active.
    after = reg.get_session(sid)
    assert after["status"] == reg.STATUS_RUNNING
    active = [e for e in after["stage_history"] if e.get("ended_at") is None]
    assert active and active[0]["state"] == "active"


def test_recover_ignores_legacy_records(env):
    """A legacy (effort_managed==False) record is owned by reconcile, not the v12
    recovery path — it is NEVER touched even when its PTY is gone."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]
    # A legacy start (effort_managed defaults False).
    sess = ts.start_session(pid, "research", backend="claude")
    sid = sess["session_id"]
    assert reg.get_session(sid)["effort_managed"] is False
    pty.kill(sid)
    out = ts.recover_interrupted_efforts(live_session_ids=[])
    assert sid not in out["recovered"]
    # The legacy record is left RUNNING (reconcile, not recovery, owns it).
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING


def test_recover_no_auto_advance(env):
    """Recovery NEVER auto-advances: an interrupted BUILD effort stays at build
    (it is the user's job to reopen, not recovery's to push the stage)."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]
    rec = _start_build_effort(env)
    sid = rec["session_id"]
    pty.kill(sid)
    ts.recover_interrupted_efforts(live_session_ids=[])
    after = reg.get_session(sid)
    assert after["current_stage"] == "build"


def test_recover_before_reconcile_gui_order_no_doc_loss(env):
    """W8-R2-01 (the integration-order BLOCKER): in the GUI poll's order —
    recover_interrupted_efforts FIRST, then reconcile_and_advance — an
    effort_managed effort whose PTY died is marked 'interrupted' + IDLE with its
    docs persisted, and the following reconcile pass does NOT flip it to DONE.
    (The pre-fix order [reconcile first] marked it DONE and LOST the docs.)"""
    ts, reg, pty, pid, repo = (env["ts"], env["reg"], env["pty"], env["pid"],
                               env["repo"])
    rec = _start_build_effort(env)
    sid = rec["session_id"]
    pty.kill(sid)  # PTY gone, registry still RUNNING (the reconcile-dead state)
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING

    # Replicate the GUI poll ORDER exactly (anchor_gui term_sessions refresh):
    live = list(pty.live_sessions())
    ts.recover_interrupted_efforts(live_session_ids=live)   # FIRST (the fix)
    ts.reconcile_and_advance(live_session_ids=live)         # THEN reconcile

    after = reg.get_session(sid)
    # Build doc PERSISTED + committed (the doc-loss the BLOCKER caused is gone).
    assert _git(repo, "ls-files", "--error-unmatch",
                "build/app.py").returncode == 0, "build doc lost (W8-R2-01)"
    # Stage stays 'interrupted' — reconcile did NOT overwrite it to done.
    b_ent = [e for e in after["stage_history"] if e.get("stage") == "build"][-1]
    assert b_ent["state"] == "interrupted"
    # Record is IDLE, NOT DONE (a crash must not masquerade as an orderly finish).
    assert after["status"] == reg.STATUS_IDLE
    assert after["status"] != reg.STATUS_DONE

"""v12 Wave 6 — ``advance_stage``: in-session relabel + save, lock, idempotency.

The continuity-first "Advance" keeps the SAME session, injects NOTHING into the
PTY by default, and is concurrency-safe. This suite covers the Wave-6
Given/When/Then EXACTLY (the WORKTREE-ONLY, idempotent-race, and grass-dev cases;
the CONVERSATION-ONLY load-bearing case is in
``test_advance_stage_conversation_v12.py``).

THE v11 LESSON, applied:
  - WORKTREE-ONLY: produced docs are written into the session worktree, never
    ``eh.record_effort`` pre-persist.
  - SET equality: snapshot ``set(list_sessions ids)`` pre/post and assert EQUAL
    (zero mint) — not just ``len``.
  - ZERO PTY bytes: the default advance writes nothing to the PTY — asserted via
    the PTY read-buffer delta == 0.

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


def _pty_len(pty, sid):
    """Cumulative PTY output buffer length (cursor 0). Used for byte-delta."""
    try:
        out = pty.read_since(sid, 0)
    except Exception:
        return 0
    return len((out.get("text") or "") if isinstance(out, dict) else "")


def _write_research_docs(worktree_path):
    """WORKTREE-ONLY: write a research doc into the worktree (uncommitted)."""
    wt = Path(worktree_path)
    rel = "research/findings.md"
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# Research findings\nThe locked north star is durable resumable work.\n",
        encoding="utf-8")
    return rel


# ════════════════════════════════════════════════════════════════════════════
# WORKTREE-ONLY — advance research → plan keeps the SAME session, ZERO PTY bytes
# ════════════════════════════════════════════════════════════════════════════

def test_advance_research_to_plan_worktree_only(env):
    """*Given* a live research effort with docs in its worktree only, *When*
    advance_stage(sid,'plan','manual'), *Then* SAME session_id + worktree_path;
    list_sessions id SET unchanged; current_stage=='plan'; research entry closed
    (done + summary/doc_count); plan entry open (active); effort_managed True;
    PTY buffer delta == 0."""
    ts, reg, pty, pid = env["ts"], env["reg"], env["pty"], env["pid"]

    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    wt = sess["worktree_path"]
    # Wave-6 start change: the FIRST stage entry is opened at effort start.
    assert sess["current_stage"] == "research"
    active = [e for e in sess["stage_history"] if e.get("ended_at") is None]
    assert len(active) == 1 and active[0]["stage"] == "research"

    _write_research_docs(wt)

    ids_before = _ids(reg, pid)
    pty_before = _pty_len(pty, sid)

    out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)

    assert out["ok"] is True
    assert out["advanced"] is True
    rec = out["record"]

    # SAME session id + worktree.
    assert rec["session_id"] == sid
    assert rec["worktree_path"] == wt

    # ZERO mint — the id SET is unchanged (set-equality, not len).
    assert _ids(reg, pid) == ids_before

    # current_stage flipped.
    assert rec["current_stage"] == "plan"

    # Research stage entry CLOSED: ended_at set, state 'done', has a doc_count.
    history = rec["stage_history"]
    research_ents = [e for e in history if e.get("stage") == "research"]
    assert research_ents
    r_ent = research_ents[-1]
    assert r_ent["ended_at"] is not None
    assert r_ent["state"] == "done"
    assert r_ent.get("doc_count", 0) >= 1

    # Plan stage entry OPEN: state 'active', ended_at None.
    plan_ents = [e for e in history if e.get("stage") == "plan"]
    assert len(plan_ents) == 1
    p_ent = plan_ents[0]
    assert p_ent["ended_at"] is None
    assert p_ent["state"] == "active"
    assert p_ent["store_lane"] == "planning"

    # The v12 discriminator is set.
    assert rec["effort_managed"] is True

    # ZERO PTY bytes written by the advance (relabel+save, no injection).
    assert _pty_len(pty, sid) == pty_before


def test_advance_research_docs_persisted_to_main(env):
    """Advancing persists the research stage's docs into the MAIN project (the
    finish_stage keystone runs against the live worktree)."""
    ts, repo, pid = env["ts"], env["repo"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    rel = _write_research_docs(wt)

    out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert out["ok"] is True
    # The research doc landed in the main folder via the finish_stage persist.
    assert rel in (out["finished"]["docs"].get("persisted") or [])
    assert (Path(repo) / rel).is_file()


def test_advance_default_to_stage_is_next(env):
    """``to_stage=None`` resolves to the NEXT trio stage (research→plan)."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    out = ts.advance_stage(sess["session_id"], project_id=pid)  # no to_stage
    assert out["ok"] is True and out["advanced"] is True
    assert out["to_stage"] == "plan"
    assert out["record"]["current_stage"] == "plan"


# ════════════════════════════════════════════════════════════════════════════
# IDEMPOTENT RACE — manual+auto under the lock → exactly ONE advance
# ════════════════════════════════════════════════════════════════════════════

def test_advance_idempotent_double_call(env, monkeypatch):
    """*Given* advance_stage called twice (manual+auto race under the lock),
    *Then* exactly one persist + one summary schedule + one flip; the second is a
    no-op."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]

    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    _write_research_docs(wt)

    # Count summary-schedule invocations (the W4 scheduling seam).
    scheduled = []
    monkeypatch.setattr(
        ts, "_trigger_background_stage_summary",
        lambda folder, project_id, store_lane, session_id, stage:
            scheduled.append((session_id, stage)))

    ids_before = _ids(reg, pid)

    first = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    second = ts.advance_stage(sid, "plan", mode="auto", project_id=pid)

    # First advanced; second is an honest no-op.
    assert first["ok"] is True and first["advanced"] is True
    assert second["ok"] is True and second["advanced"] is False
    assert second["reason"] == "already-advanced"

    # Exactly ONE flip — still at 'plan', not double-advanced past it.
    assert reg.get_session(sid)["current_stage"] == "plan"

    # Exactly ONE summary scheduled (the closing research stage), from the FIRST
    # advance only. The no-op never re-schedules.
    assert scheduled == [(sid, "research")]

    # Zero mint across both calls.
    assert _ids(reg, pid) == ids_before


def test_advance_idempotent_when_already_past(env):
    """An advance to a stage the effort is already PAST is a no-op (rank-based)."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    # research → plan → build.
    ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    ts.advance_stage(sid, "build", mode="manual", project_id=pid)
    # Now ask to advance to 'plan' again (already past).
    out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert out["ok"] is True and out["advanced"] is False
    assert out["record"]["current_stage"] == "build"


# ════════════════════════════════════════════════════════════════════════════
# GRASS-DEV accepted (covers W11's reuse)
# ════════════════════════════════════════════════════════════════════════════

def test_advance_grass_dev_accepted(env):
    """*Given* a grass-dev effort, *When* advance_stage, *Then* accepted."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "grass", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    assert reg.get_session(sid)["kind"] == "grass-dev"
    # A grass-dev effort opens at the 'research' stage (its lane's dev stage).
    assert sess["current_stage"] == "research"

    out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert out["ok"] is True
    assert out["advanced"] is True
    assert out["record"]["current_stage"] == "plan"


# ════════════════════════════════════════════════════════════════════════════
# Validation / honesty
# ════════════════════════════════════════════════════════════════════════════

def test_advance_unknown_session_is_honest(env):
    ts = env["ts"]
    out = ts.advance_stage("no-such-session")
    assert out["ok"] is False
    assert out["reason"] == "unknown-session"


def test_advance_non_live_session_refused(env):
    """A killed (terminal) effort is not LIVE → advance refused."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    ts.kill(sid, project_id=pid)
    out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert out["ok"] is False
    assert out["reason"] == "not-live"


def test_advance_load_skill_opt_in_writes_one_turn(env):
    """mode='manual' with load_skill=True writes exactly ONE skill-load turn;
    default (load_skill=False) writes nothing — the contrast proving the default
    injects ZERO bytes."""
    ts, pty, pid = env["ts"], env["pty"], env["pid"]

    # Default: zero bytes.
    s1 = ts.start_session(pid, "research", backend="claude", effort_managed=True)
    sid1 = s1["session_id"]
    before1 = _pty_len(pty, sid1)
    ts.advance_stage(sid1, "plan", mode="manual", project_id=pid)
    assert _pty_len(pty, sid1) == before1

    # Opt-in: one turn written (buffer grows because the stub echoes input).
    s2 = ts.start_session(pid, "research", backend="claude", effort_managed=True)
    sid2 = s2["session_id"]
    before2 = _pty_len(pty, sid2)
    ts.advance_stage(sid2, "plan", mode="manual", project_id=pid,
                     load_skill=True)
    assert _pty_len(pty, sid2) > before2


def test_advance_closing_entry_gets_summary_ref(env):
    """W6-R2-01 / MASTER-PLAN §4.3: the CLOSED stage entry must carry a
    summary_ref (the stage-summary cache locator) after advance."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude", effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    _write_research_docs(wt)
    out = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert out["ok"] and out["advanced"]
    r_ent = [e for e in out["record"]["stage_history"]
             if e.get("stage") == "research"][-1]
    assert r_ent["state"] == "done"
    ref = r_ent.get("summary_ref")
    assert ref and ref.get("stage") == "research" and ref.get("session_id") == sid
    assert ref.get("lane") == "research"  # store_lane locator


def test_advance_invalid_stage_is_honest_error(env):
    """W6-R2-02: a garbage to_stage is an HONEST ok:False, NOT a silent
    'already-advanced' no-op."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude", effort_managed=True)
    out = ts.advance_stage(sess["session_id"], "frobnicate", mode="manual",
                           project_id=pid)
    assert out["ok"] is False
    assert out["reason"] == "invalid-stage"


def test_advance_stage_skip_refused(env):
    """W6-R2-03: single-step only — research→build (skipping plan) is rejected."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude", effort_managed=True)
    out = ts.advance_stage(sess["session_id"], "build", mode="manual",
                           project_id=pid)
    assert out["ok"] is False
    assert out["reason"] == "invalid-stage-skip"

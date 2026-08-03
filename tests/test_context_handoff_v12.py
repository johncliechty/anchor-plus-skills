"""v12 Wave 8 — context-relief handoff (warn + one-click) + context_fullness.

The context-relief valve (SC2): when context fills (or the user clicks the warn
banner), ``terminal_session.handoff_to_fresh`` continues the effort in a FRESH
session that JOINS the same effort (same ``effort_id`` / tile / lineage), carrying
the prior stage's docs + the real next prompt forward via the v11.1 machinery —
held as a PENDING PASTE (UNSENT; NOTHING auto-submitted). ``context_fullness`` is
the stdlib heuristic behind the warn banner.

Covers the Wave-8 Given/When/Then for handoff + context_status EXACTLY:
  - handoff: ``new.session_id != old.session_id`` AND
    ``new.effort_id == old.effort_id``; plan docs persisted+committed;
    ``new.pending_paste == <prompt>`` and ``paste_flushed == False``;
    ``pty.read_since(new_sid,0)`` contains the greet marker but NOT the prompt
    body (held unsent — the v11.1 base-count guard); ``old.worktree_path`` still
    exists (not reaped); old plan stage entry ``state=='done'``.
  - context_fullness over threshold → ``over_threshold`` True; a not-full session
    → False.

THE v11 LESSON, applied: WORKTREE-ONLY (docs written into the session worktree,
never ``eh.record_effort`` pre-persist).

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
    monkeypatch.delenv("ANCHOR_CONTEXT_FULL_RATIO", raising=False)
    monkeypatch.delenv("ANCHOR_CONTEXT_FULL_BUDGET", raising=False)

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


def _write_plan_docs(worktree_path):
    """WORKTREE-ONLY: write the plan-stage docs into the worktree (uncommitted)."""
    wt = Path(worktree_path)
    rels = []
    for rel, body in (
        ("planning/MASTER-PLAN.md",
         "# Master Plan\nThe locked north star is durable resumable work.\n"),
        ("planning/IMPLEMENTATION-PLAN.md",
         "# Implementation Plan\nWave 1: durable resumable work.\n"),
    ):
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        rels.append(rel)
    return rels


def _committed_in_repo(repo, rel):
    return _git(repo, "ls-files", "--error-unmatch", rel).returncode == 0


def _start_plan_effort(env):
    """Start a research effort, write+advance to plan, write plan docs. Returns
    the live record at current_stage=='plan' with plan docs in its worktree."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid, wt = sess["session_id"], sess["worktree_path"]
    _write_research_docs(wt)
    adv = ts.advance_stage(sid, "plan", mode="manual", project_id=pid)
    assert adv["ok"] and adv["advanced"]
    rec = adv["record"]
    assert rec["current_stage"] == "plan"
    _write_plan_docs(rec["worktree_path"])
    return rec


# ════════════════════════════════════════════════════════════════════════════
# HANDOFF — fresh session JOINS the same effort, prompt held UNSENT
# ════════════════════════════════════════════════════════════════════════════

def test_handoff_to_fresh_joins_same_effort(env):
    """*Given* a running effort at current_stage=='plan' with plan docs in its
    worktree, *When* handoff_to_fresh(effort_id), *Then* new.session_id !=
    old.session_id AND new.effort_id == old.effort_id; plan docs persisted+
    committed; new.pending_paste == <prompt> + paste_flushed False;
    read_since(new_sid,0) has the greet marker but NOT the prompt body; old
    worktree still exists (not reaped); old plan stage state=='done'."""
    ts, reg, pty, repo, pid = (env["ts"], env["reg"], env["pty"], env["repo"],
                               env["pid"])

    old = _start_plan_effort(env)
    old_sid = old["session_id"]
    old_wt = old["worktree_path"]
    effort_id = old["effort_id"]

    out = ts.handoff_to_fresh(effort_id, project_id=pid)
    assert out["ok"] is True

    new_rec = out["new_session"]
    new_sid = new_rec["session_id"]

    # A DISTINCT new session that JOINS the SAME effort.
    assert new_sid != old_sid
    assert new_rec["effort_id"] == effort_id
    assert old["effort_id"] == effort_id

    # CONTINUE, not ADVANCE (R1 F1): context-relief keeps the SAME stage — the
    # new session stays at 'plan' (a regression that advanced to 'build' fails here).
    assert new_rec["current_stage"] == "plan"

    # Plan docs persisted + committed into MAIN.
    assert _committed_in_repo(repo, "planning/MASTER-PLAN.md")
    assert _committed_in_repo(repo, "planning/IMPLEMENTATION-PLAN.md")

    # The next prompt is held as a PENDING PASTE — UNSENT (paste_flushed False).
    prompt = out["prompt"]
    assert prompt, "handoff produced no next prompt"
    assert new_rec["pending_paste"] == prompt
    assert new_rec["paste_flushed"] is False

    # The new session's PTY buffer (read directly — NOT via terminal_session, so
    # no flush is triggered) contains the GREET MARKER (echoed in the start seed)
    # but NOT the prompt body (held unsent per the v11.1 base-count guard).
    buf = pty.read_since(new_sid, 0)
    text = (buf.get("text") or "") if isinstance(buf, dict) else ""
    assert ts.GREET_MARKER.lower() in text.lower(), \
        "greet marker (echoed seed) missing from the new session buffer"
    # The prompt body must NOT be in the buffer — it sits pending, unsent. Probe
    # with a distinctive doc-path token that is in the prompt but NOT the seed (a
    # context-relief handoff continues the SAME stage, so the plan-stage prompt
    # references the upstream research doc paths it must read first).
    assert "research/findings.md" in prompt
    assert "research/findings.md" not in text, \
        "the prompt body leaked into the PTY (it must be held UNSENT)"

    # The OLD session's worktree is NOT reaped (close-keeps-record).
    assert Path(old_wt).is_dir(), "old worktree was reaped — handoff must not reap"

    # The OLD session's plan stage entry is CLOSED (state 'done').
    old_after = reg.get_session(old_sid)
    plan_ents = [e for e in old_after["stage_history"]
                 if e.get("stage") == "plan"]
    assert plan_ents
    assert plan_ents[-1]["state"] == "done"
    assert plan_ents[-1]["ended_at"] is not None


def test_handoff_to_fresh_accepts_session_id(env):
    """handoff_to_fresh also accepts the session_id directly (the common case
    where effort_id == own sid)."""
    ts, pid = env["ts"], env["pid"]
    old = _start_plan_effort(env)
    out = ts.handoff_to_fresh(old["session_id"], project_id=pid)
    assert out["ok"] is True
    assert out["new_session"]["session_id"] != old["session_id"]
    assert out["new_session"]["effort_id"] == old["effort_id"]


def test_handoff_unknown_session_is_honest(env):
    ts = env["ts"]
    out = ts.handoff_to_fresh("no-such-session")
    assert out["ok"] is False
    assert out["reason"] == "unknown-session"


def test_handoff_new_session_is_distinct_tile(env):
    """The handoff MINTS a new session — the id set grows by exactly one."""
    ts, reg, pid = env["ts"], env["reg"], env["pid"]
    old = _start_plan_effort(env)
    ids_before = _ids(reg, pid)
    out = ts.handoff_to_fresh(old["effort_id"], project_id=pid)
    assert out["ok"]
    ids_after = _ids(reg, pid)
    assert out["new_session"]["session_id"] in ids_after
    assert ids_after - ids_before == {out["new_session"]["session_id"]}


# ════════════════════════════════════════════════════════════════════════════
# CONTEXT FULLNESS — over threshold True; a not-full session False
# ════════════════════════════════════════════════════════════════════════════

def test_context_fullness_over_threshold(env, monkeypatch):
    """*Given* context_fullness over threshold, *Then* over_threshold True."""
    ts, pty, pid = env["ts"], env["pty"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]

    # Make the budget small enough that a modest seeded buffer crosses it.
    monkeypatch.setenv("ANCHOR_CONTEXT_FULL_BUDGET", "100")
    monkeypatch.setenv("ANCHOR_CONTEXT_FULL_RATIO", "0.8")
    # Seed >100 bytes of "conversation" into the PTY buffer (the stub echoes it).
    pty.write(sid, "X" * 500)

    cf = ts.context_fullness(sid)
    assert cf["over_threshold"] is True
    assert cf["ratio"] >= 0.8
    assert cf["observed_bytes"] >= 500


def test_context_fullness_not_full_is_false(env, monkeypatch):
    """A session with little output is NOT over the threshold."""
    ts, pid = env["ts"], env["pid"]
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    # A large budget + the tiny start-seed echo → well under threshold.
    monkeypatch.setenv("ANCHOR_CONTEXT_FULL_BUDGET", "200000")
    monkeypatch.setenv("ANCHOR_CONTEXT_FULL_RATIO", "0.8")
    cf = ts.context_fullness(sid)
    assert cf["over_threshold"] is False
    assert 0.0 <= cf["ratio"] < 0.8


def test_context_fullness_unknown_session_is_zero(env):
    """A dead/unknown session honestly reports ratio 0.0 / not over threshold."""
    ts = env["ts"]
    cf = ts.context_fullness("no-such-session")
    assert cf["ratio"] == 0.0
    assert cf["over_threshold"] is False


def test_fresh_seeded_session_not_over_threshold_default_budget(env, monkeypatch):
    """v13 Wave 1 (#7): a freshly-seeded stub session is NOT over threshold under
    the DEFAULT (~1 MB) budget. The one-time skill seed is the first thing a new
    session prints; it is discounted by the fixed seed allowance, so a brand-new
    session no longer fires a FALSE context-full warning (the bug: the old 200 KB
    budget measured the seed itself)."""
    ts = env["ts"]
    # Defaults ONLY — no budget / ratio / seed-allowance overrides.
    monkeypatch.delenv("ANCHOR_CONTEXT_FULL_BUDGET", raising=False)
    monkeypatch.delenv("ANCHOR_CONTEXT_FULL_RATIO", raising=False)
    monkeypatch.delenv("ANCHOR_CONTEXT_SEED_ALLOWANCE", raising=False)
    sess = ts.start_session(env["pid"], "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    cf = ts.context_fullness(sid)
    assert cf["over_threshold"] is False
    assert cf["ratio"] < 0.8
    # The budget reflects the raised ~1 MB default (not the old 200 KB).
    assert cf["budget"] >= 1_000_000
    # The seed is discounted: growth BEYOND the seed is ~0 on a fresh session.
    assert cf["growth_bytes"] == 0
    # observed_bytes is still the RAW buffer length (honest about what we saw).
    assert cf["observed_bytes"] >= 0

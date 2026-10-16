"""v12 Wave 5 — ``finish_stage``: the non-reaping durability refactor.

Wave 5 factors the persist+summarize keystone OUT of ``terminal_session.kill``
into a shared path so a STAGE BOUNDARY can persist+summarize a stage WITHOUT
reaping the worktree or marking the registry record terminal — with ``kill``'s
observable behavior provably UNCHANGED (it remains the single most load-bearing
durable path: v8 no-loss, v10 Boneyard).

This suite covers the Wave-5 Given/When/Then EXACTLY:

  (1) ``finish_stage`` on a LIVE effort → the current stage's docs persist
      (Wave-3 stage-scoped) + a summary is scheduled, the worktree is STILL on
      disk, the record is STILL RUNNING (not terminal), and NO Boneyard entry is
      recorded (a stage boundary is not a discard).

  (2) ``kill`` is identical to pre-refactor: docs persisted, a Boneyard
      ``killed`` entry recorded (when the session produced material), the
      worktree removed, the record marked terminal.

Hermetic + WORKTREE-ONLY (the v11 lesson): produced docs are written into the
session worktree (never ``eh.record_effort`` pre-persist). ``ANCHOR_PTY_BACKEND
=stub``, a temp git repo for the worktree, a temp data dir + temp worktree base,
the STUB summarizer runner, ``ANCHOR_PROACTIVE_SUMMARY`` left OFF (the
default) so no live ``claude`` is ever spawned. NEVER binds ``:8777``; NEVER a
worktree off the real ``C:\\dev\\Anchor`` repo; NEVER real push/gh/network.
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


# ── env / fixtures (stub PTY + temp git repo + project + STUB summarizer) ─────

@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    # Proactive summary stays OFF (the unit-test default): finish_stage SCHEDULES
    # a summary only when proactive is enabled, so we assert the scheduling SEAM
    # is invoked (monkeypatched), never spawn a real model.
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "The locked north star is durable resumable work")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

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
    import boneyard

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
        "summ": summarizer, "rnd": rnd_registry, "bone": boneyard,
        "repo": repo, "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_research_docs(worktree_path):
    """Write a research doc into the worktree (uncommitted, as a live session
    leaves it). WORKTREE-ONLY: no eh.record_effort pre-persist."""
    wt = Path(worktree_path)
    rel = "research/findings.md"
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# Research findings\nThe locked north star is durable resumable work.\n",
        encoding="utf-8")
    return rel


def _write_build_docs(worktree_path, plan_dir="build/rnd-x"):
    wt = Path(worktree_path)
    rels = {
        "north": f"{plan_dir}/NORTH-STAR.md",
        "deliv": f"{plan_dir}/DELIVERABLE.md",
        "log": f"{plan_dir}/EXECUTION-LOG.md",
    }
    bodies = {
        "north": "# North Star\nThe locked north star is durable resumable work.\n",
        "deliv": "# Deliverable\nThe widget cache service ships.\n",
        "log": "# Execution Log\nWave 1 GREEN.\n",
    }
    for key, rel in rels.items():
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(bodies[key], encoding="utf-8")
    return rels


def _start_v12_effort_with_stage(env, stage="research", store_lane="research"):
    """Start a v12 effort (effort_managed=True) and open an active stage entry.

    Wave 5 does NOT wire advance, so the active stage_history entry is set up the
    same way the Wave-6 advance path will: record_stage_baseline (Wave-3) +
    set_current_stage (Wave-1). After this the session carries an OPEN stage
    entry with a real baseline_ref so finish_stage/kill take the stage-scoped
    persist path."""
    ts, reg, eh, pid = env["ts"], env["reg"], env["eh"], env["pid"]
    sess = ts.start_session(pid, store_lane, backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    wt = sess["worktree_path"]
    baseline = eh.record_stage_baseline(wt)
    reg.set_current_stage(sid, stage, store_lane, baseline)
    return sid, wt


# ════════════════════════════════════════════════════════════════════════════
# (1) finish_stage — persists + summarizes the current stage WITHOUT reaping
# ════════════════════════════════════════════════════════════════════════════

def test_finish_stage_persists_no_reap_no_terminal_no_boneyard(env, monkeypatch):
    """*Given* a live effort, *When* finish_stage, *Then* docs persist (W3) +
    summary scheduled, worktree still on disk, record still RUNNING, NO Boneyard
    entry."""
    ts, reg, bone, repo, pid = (env["ts"], env["reg"], env["bone"],
                                env["repo"], env["pid"])

    sid, wt = _start_v12_effort_with_stage(env, "research", "research")
    rel = _write_research_docs(wt)

    # Capture the summary-scheduling seam so we can assert it fired with the
    # stage threaded through (without enabling a real model run).
    scheduled = []
    monkeypatch.setattr(
        ts, "_trigger_background_stage_summary",
        lambda folder, project_id, store_lane, session_id, stage:
            scheduled.append((session_id, store_lane, stage)))

    # Boneyard must NOT be touched by a stage boundary.
    bone_calls = []
    monkeypatch.setattr(bone, "record_entry",
                        lambda *a, **k: bone_calls.append(a))

    out = ts.finish_stage(sid, "research", "research", project_id=pid)

    # Docs persisted (the W3 stage-scoped path returned ok with the research doc).
    assert out["ok"] is True
    assert out["docs"]["ok"] is True
    assert rel in out["docs"]["persisted"]
    # ...and the doc actually landed in the MAIN project folder.
    assert (Path(repo) / rel).is_file()

    # Summary scheduled, with the stage threaded through (Wave-4 stage-keyed).
    assert scheduled == [(sid, "research", "research")]

    # Worktree STILL on disk (NOT reaped).
    assert Path(wt).is_dir()

    # Record STILL RUNNING (NOT marked terminal).
    rec = reg.get_session(sid)
    assert rec is not None
    assert rec["status"] == reg.STATUS_RUNNING

    # NO Boneyard entry (a stage boundary is not a discard).
    assert bone_calls == []
    assert bone.list_entries(str(repo), pid) == []


def test_finish_stage_is_stage_scoped_not_whole_tree(env):
    """finish_stage attributes ONLY the active stage's docs.

    Research persists r.md; then a NEW plan baseline + MASTER-PLAN.md; finishing
    the PLAN stage yields ONLY the plan doc — r.md (the closed research stage) is
    subtracted. Proves finish_stage rides the Wave-3 keystone, not the legacy
    whole-tree diff."""
    ts, reg, eh, pid = env["ts"], env["reg"], env["eh"], env["pid"]

    sid, wt = _start_v12_effort_with_stage(env, "research", "research")
    r_rel = _write_research_docs(wt)
    res = ts.finish_stage(sid, "research", "research", project_id=pid)
    assert res["docs"]["persisted"] == [r_rel]

    # Advance the stage record to plan (new baseline) — as Wave-6 advance will.
    b1 = eh.record_stage_baseline(wt)
    reg.set_current_stage(sid, "plan", "planning", b1)
    plan_rel = "planning/MASTER-PLAN.md"
    p = Path(wt) / plan_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# master plan\n", encoding="utf-8")

    out = ts.finish_stage(sid, "plan", "planning", project_id=pid)
    assert out["docs"]["ok"] is True
    # ONLY the plan doc — research's r.md is excluded (closed prior stage).
    assert out["docs"]["persisted"] == [plan_rel]
    assert r_rel not in out["docs"]["persisted"]

    # Still no reap / still running after a second stage boundary.
    assert Path(wt).is_dir()
    assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING


def test_finish_stage_unknown_session_is_honest(env):
    """finish_stage never raises on an unknown id — honest not-ok result."""
    ts = env["ts"]
    out = ts.finish_stage("no-such-session")
    assert out["ok"] is False
    assert out["reason"] == "unknown-session"


# ════════════════════════════════════════════════════════════════════════════
# (2) kill — IDENTICAL to pre-refactor (persist + boneyard + reap + terminal)
# ════════════════════════════════════════════════════════════════════════════

def test_kill_legacy_session_unchanged_persists_boneyard_reaps_terminal(env):
    """The kill regression assertion over a LEGACY (non-effort) session — the
    exact case every existing v8/v10 kill test exercises.

    *Given* a live session, *When* kill, *Then* identical to pre-refactor: docs
    persisted, Boneyard 'killed' entry recorded (material present), worktree
    removed, record terminal."""
    ts, reg, bone, repo, pid = (env["ts"], env["reg"], env["bone"],
                                env["repo"], env["pid"])

    sess = ts.start_session(pid, "build", backend="claude")  # legacy: managed=False
    sid = sess["session_id"]
    assert reg.get_session(sid)["effort_managed"] is False
    wt = sess["worktree_path"]
    docs = _write_build_docs(wt)

    out = ts.kill(sid)

    # Docs persisted (the legacy whole-tree capture path — unchanged).
    assert out["docs"]["ok"] is True
    persisted = out["docs"]["persisted"]
    for rel in docs.values():
        assert rel in persisted

    # Boneyard 'killed' entry recorded (the session produced material).
    entries = bone.list_entries(str(repo), pid)
    assert len(entries) == 1
    assert entries[0]["source"] == bone.SOURCE_KILLED
    assert entries[0]["doc_rels"]

    # Worktree removed.
    assert not Path(wt).is_dir()

    # Record terminal (DONE).
    assert reg.get_session(sid)["status"] == reg.STATUS_DONE


def test_kill_v12_effort_still_reaps_and_terminates(env):
    """Even on a v12 EFFORT (the new stage-scoped persist path), kill STILL
    reaps the worktree, marks the record terminal, and records a Boneyard
    'killed' entry — only the doc-attribution narrowed (the observable kill
    contract is unchanged)."""
    ts, reg, bone, repo, pid = (env["ts"], env["reg"], env["bone"],
                                env["repo"], env["pid"])

    sid, wt = _start_v12_effort_with_stage(env, "build", "build")
    docs = _write_build_docs(wt)

    out = ts.kill(sid, project_id=pid)

    assert out["docs"]["ok"] is True
    # The build stage attributes its build docs.
    persisted = out["docs"]["persisted"]
    assert any(rel in persisted for rel in docs.values())

    # Boneyard 'killed' entry recorded.
    entries = bone.list_entries(str(repo), pid)
    assert len(entries) == 1
    assert entries[0]["source"] == bone.SOURCE_KILLED

    # Worktree removed + record terminal — the kill contract holds.
    assert not Path(wt).is_dir()
    assert reg.get_session(sid)["status"] == reg.STATUS_DONE


def test_kill_no_material_records_no_boneyard_entry(env):
    """kill of a session that produced NOTHING records no Boneyard entry but
    still reaps + terminates — pre-refactor behavior, unchanged."""
    ts, reg, bone, repo, pid = (env["ts"], env["reg"], env["bone"],
                                env["repo"], env["pid"])

    sess = ts.start_session(pid, "build", backend="claude")
    sid = sess["session_id"]
    wt = sess["worktree_path"]
    # No docs written.

    out = ts.kill(sid)
    assert out["ok"] is True

    assert bone.list_entries(str(repo), pid) == []
    assert not Path(wt).is_dir()
    assert reg.get_session(sid)["status"] == reg.STATUS_DONE

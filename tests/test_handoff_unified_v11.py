"""v11 Wave 3 — Unify the other advance paths through the keystone.

THE GOAL: ONE handoff path. After v11 W1 (the shared
``terminal_session.prepare_stage_handoff`` keystone) + W2 (research→plan routed
through it), this wave routes the REMAINING advance paths through the SAME
keystone so all are consistent and equally verified:

  1. plan→build BUTTON  (anchor_gui ``finish_to_build``);
  2. plan→build AUTO-ON-KILL  (``terminal_session.auto_advance_planning_to_build``
     fired from a hard-kill / reconcile-dead);
  3. grass research→plan  (``effort_history.advance_grass_research_to_plan``,
     SAFE/PARTIAL unification — the persist + prompt builder are shared, the
     contained-grass session wiring is preserved).

THE v11 LESSON (non-negotiable, see IMPLEMENTATION-PLAN.md Conventions): these
tests are WORKTREE-ONLY. We start a LIVE session, write produced docs into the
session's WORKTREE ONLY (NO ``eh.record_effort`` pre-persist), then advance, then
assert the docs were PERSISTED into the project AND referenced in the prompt AND
physically present in the BUILD worktree on disk (the v8 standard). A test that
pre-persists the effort is prompt-building coverage, NOT live-flow coverage.

NON-VACUITY (reasoned, per path): if the unified path did NOT persist the
worktree-only docs, then (1) for plan→build the plan docs would never reach main
HEAD → ``discover_recent_plan_set`` (reads persisted planning efforts) would find
NO plan set → no build would open (the test asserting a build with the real plan
paths would FAIL); (2) for grass the prompt builder would resolve no research
doc → the prompt would NOT name the real research doc path (the test asserting the
prompt names ``rel`` would FAIL). So each test would fail were persistence absent —
the masking pattern cannot make them pass. (v11.1 Wave 2 removed the
``no-research-material`` hard-refusal; the advance now always opens the plan session,
so the asserted material is the prompt's NAMED doc path, not the refusal.)

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, a tmp data dir + tmp worktree base,
``ANCHOR_PROACTIVE_SUMMARY`` left OFF. NEVER binds ``:8777``; NEVER a worktree off
the real repo; NEVER real push/gh/network.
"""
import importlib
import json as _json
import re
import subprocess
import threading
import urllib.request as _req
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


# ── env / fixtures (stub PTY + temp git repo + project + gui) ─────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import handoff
    import terminal_session
    import session_registry
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
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "handoff": handoff, "eh": effort_history, "rnd": rnd_registry,
        "repo": repo, "pid": proj["id"], "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _write_in_worktree(worktree_path, rel, body):
    """Write a produced doc into a session's WORKTREE ONLY (no record_effort)."""
    wt = Path(worktree_path)
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def _write_plan_set_in_worktree(worktree_path, plan_dir="planning/rnd-y"):
    """Author a REAL MASTER+IMPL plan set LIVE in the planning session's worktree
    ONLY (uncommitted to main, NO record_effort) — the v11 worktree-only flow."""
    master_rel = f"{plan_dir}/MASTER-PLAN.md"
    impl_rel = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    _write_in_worktree(worktree_path, master_rel, "# Master Plan\n## Scope\nX.\n")
    _write_in_worktree(worktree_path, impl_rel,
                       "# Implementation Plan\n## Wave 1\nDo X.\n")
    return master_rel, impl_rel


def _committed_in_repo(repo, rel):
    r = _git(repo, "ls-files", "--error-unmatch", rel)
    return r.returncode == 0


def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def _post(port, path, payload):
    req = _req.Request(f"http://127.0.0.1:{port}{path}",
                       data=_json.dumps(payload).encode("utf-8"),
                       headers={"Content-Type": "application/json"},
                       method="POST")
    with _req.urlopen(req, timeout=20) as r:
        return _json.loads(r.read().decode("utf-8"))


# ════════════════════════════════════════════════════════════════════════════
# (1) plan→build BUTTON — finish_to_build, WORKTREE-ONLY live flow
# ════════════════════════════════════════════════════════════════════════════

def test_finish_to_build_button_worktree_only_persists_and_opens_build(env):
    """Given a LIVE planning session whose MASTER+IMPL plan docs are in its
    WORKTREE ONLY (no record_effort), When POST /api/rnd/finish_to_build runs,
    Then through the SHARED keystone: the plan docs are persisted + committed to
    MAIN, exactly ONE linked build session opens whose pending paste names the
    real plan paths, the build worktree HANDOFF.md references them, and the plan
    docs EXIST in the build worktree on disk (the v8 standard)."""
    ts, reg, repo, pid, gui = (env["ts"], env["reg"], env["repo"], env["pid"],
                               env["gui"])
    ho = env["handoff"]

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    master_rel, impl_rel = _write_plan_set_in_worktree(plan_sess["worktree_path"])

    # Pre-condition (proves the live flow): the plan docs live ONLY in the
    # planning worktree — NOT in main, NOT discoverable as a plan set yet.
    assert not (repo / master_rel).is_file()
    assert ho.discover_recent_plan_set(repo, pid,
                                       source_session_id=psid) is None

    srv, port, t = _free_server(gui)
    bsid = None
    try:
        data = _post(port, "/api/rnd/finish_to_build",
                     {"project_id": pid, "session": psid})
        assert data["ok"] is True, data
        ab = data.get("auto_build")
        assert ab, f"finish_to_build did not open a build: {data}"
        bsid = ab["session_id"]

        # (i) plan docs persisted + committed into MAIN (via the keystone).
        assert (repo / master_rel).is_file(), "MASTER-PLAN not persisted to main"
        assert (repo / impl_rel).is_file(), "IMPL-PLAN not persisted to main"
        assert _committed_in_repo(repo, master_rel)
        assert _committed_in_repo(repo, impl_rel)

        # (ii) exactly ONE linked build, parented to the planning session.
        builds = [s for s in reg.list_sessions(project_id=pid)
                  if s.get("lane") == "build"]
        assert len(builds) == 1
        assert ab["parent_session_id"] == psid
        assert ab["chain_id"] == plan_sess["chain_id"]

        # (iii) the pending paste names the real plan paths + Foreman.
        full = reg.get_session(bsid)
        paste = full["pending_paste"]
        assert master_rel in paste or impl_rel in paste, \
            f"build paste missing the real plan paths: {paste!r}"
        assert "Foreman" in paste
        assert full["paste_flushed"] is False

        # (iv) HANDOFF.md in the build worktree references the plan docs AND the
        #      plan docs EXIST in the build worktree on disk (the v8 standard).
        wt = Path(ab["worktree_path"])
        assert str(env["wbase"]) in str(wt) and str(repo) not in str(wt)
        hf = wt / ho.HANDOFF_FILENAME
        assert hf.exists()
        htext = hf.read_text(encoding="utf-8")
        assert master_rel in htext and impl_rel in htext
        assert (wt / master_rel).is_file(), \
            "plan docs are not in the build worktree on disk (v8 standard)"
        assert (wt / impl_rel).is_file()

        # (v) idempotent: a second finish_to_build does not duplicate the build.
        data2 = _post(port, "/api/rnd/finish_to_build",
                      {"project_id": pid, "session": psid})
        assert data2["ok"] is True
        builds2 = [s for s in reg.list_sessions(project_id=pid)
                   if s.get("lane") == "build"]
        assert len(builds2) == 1, "finish_to_build duplicated the build"
    finally:
        if bsid:
            try:
                ts.kill(bsid)
            except Exception:
                pass
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_finish_to_build_button_no_plan_set_is_honest(env):
    """A planning session with NO produced plan docs → honest no-build (no
    fabricated plan set), no crash."""
    ts, reg, pid, gui = env["ts"], env["reg"], env["pid"], env["gui"]
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    # Write NOTHING into the worktree.
    srv, port, t = _free_server(gui)
    try:
        data = _post(port, "/api/rnd/finish_to_build",
                     {"project_id": pid, "session": psid})
        assert data["ok"] is True
        assert data.get("auto_build") is None
        assert "reason" in data
        assert [s for s in reg.list_sessions(project_id=pid)
                if s.get("lane") == "build"] == []
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


# ════════════════════════════════════════════════════════════════════════════
# (2) plan→build AUTO-ON-KILL — auto_advance_planning_to_build, worktree-only
# ════════════════════════════════════════════════════════════════════════════

def test_auto_advance_on_kill_worktree_only_persists_and_opens_build(env):
    """Given a LIVE planning session whose plan docs are in its worktree ONLY,
    When it is hard-KILLED (kill persists + reaps) and auto_advance runs through
    the SHARED keystone, Then the auto-opened build's pending paste names the real
    plan paths, the plan docs are in the build worktree on disk, the build is
    linked, and there is EXACTLY ONE build (idempotent)."""
    ts, reg, repo, pid = env["ts"], env["reg"], env["repo"], env["pid"]
    ho = env["handoff"]

    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    master_rel, impl_rel = _write_plan_set_in_worktree(plan_sess["worktree_path"])

    # Pre-condition: plan docs only in the planning worktree (live flow).
    assert not (repo / master_rel).is_file()

    # Mirror the term_kill handler ordering: kill() persists the docs into MAIN
    # (capture_session_docs, before reap) + sets DONE, THEN capture the now-
    # discoverable plan set, THEN auto-advance through the keystone.
    ts.kill(psid)
    assert reg.get_session(psid)["status"] in reg.TERMINAL_STATUSES
    # The kill persisted the plan docs to main (now discoverable).
    assert (repo / master_rel).is_file(), "kill did not persist the plan docs"
    assert _committed_in_repo(repo, master_rel)

    post_plan_set = ts.capture_plan_set(pid, psid)
    assert post_plan_set is not None
    build = ts.auto_advance_planning_to_build(pid, psid, plan_set=post_plan_set)
    assert build is not None, "a plan set was present — a build must auto-open"
    bsid = build["session_id"]

    # Exactly ONE build, linked.
    builds = [s for s in reg.list_sessions(project_id=pid)
              if s.get("lane") == "build"]
    assert len(builds) == 1
    assert build["parent_session_id"] == psid
    assert build["chain_id"] == plan_sess["chain_id"]

    # The build prompt (pending paste, via the keystone) names the real plan paths.
    full = reg.get_session(bsid)
    paste = full["pending_paste"]
    assert master_rel in paste or impl_rel in paste, \
        f"auto-build paste missing the real plan paths: {paste!r}"
    assert "Foreman" in paste

    # The plan docs are physically present in the build worktree (v8 standard) and
    # HANDOFF.md references them.
    wt = Path(build["worktree_path"])
    assert (wt / master_rel).is_file() and (wt / impl_rel).is_file()
    htext = (wt / ho.HANDOFF_FILENAME).read_text(encoding="utf-8")
    assert master_rel in htext and impl_rel in htext

    # Idempotent: a second advance does not duplicate.
    again = ts.auto_advance_planning_to_build(pid, psid, plan_set=post_plan_set)
    assert again is None
    builds2 = [s for s in reg.list_sessions(project_id=pid)
               if s.get("lane") == "build"]
    assert len(builds2) == 1
    ts.kill(bsid)


def test_auto_advance_reconcile_dead_worktree_only(env):
    """The reconcile-dead transition for a worktree-only-docs planning session
    advances to ONE primed build through the keystone (idempotent)."""
    ts, reg, repo, pid = env["ts"], env["reg"], env["repo"], env["pid"]
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    master_rel, _ = _write_plan_set_in_worktree(plan_sess["worktree_path"])

    # reconcile_and_advance marks the (no-live-id) planning session DONE — but the
    # kill-style persist only runs inside kill(); reconcile marks DONE WITHOUT
    # persisting. The keystone (called by auto_advance) re-persists from the still-
    # present worktree, so the plan docs reach main here too.
    out = ts.reconcile_and_advance(live_session_ids=[])
    assert psid in out["reconcile"]["marked"]
    assert (repo / master_rel).is_file(), \
        "keystone did not persist the worktree plan docs on reconcile-advance"
    assert len(out["auto_builds"]) == 1
    build = out["auto_builds"][0]
    full = reg.get_session(build["session_id"])
    assert master_rel in full["pending_paste"]
    ts.kill(build["session_id"])


# ════════════════════════════════════════════════════════════════════════════
# (3) grass research→plan — SAFE partial unification, v10 W5 preserved
# ════════════════════════════════════════════════════════════════════════════

def _add_grass_idea(eh, repo, pid):
    idea = eh.add_idea(str(repo), pid, "Passive autonomous cooling loop",
                       notes="A natural-circulation decay-heat loop.")
    return idea.get("job_id") or idea.get("id")


def test_grass_advance_through_keystone_preserves_v10_w5(env):
    """Given a grass RESEARCH dev session with a report doc in its worktree ONLY,
    When advance_grass_research_to_plan runs (now sharing the keystone persist +
    prompt builder), Then v10 W5 behavior is preserved exactly: a CONTAINED,
    LINKED, paste-pending grass PLAN dev session opens, carrying grass_origin, with
    the real research doc path in the prompt; the idea stays in grass."""
    ts, eh, reg, repo, pid = (env["ts"], env["eh"], env["reg"], env["repo"],
                              env["pid"])
    idea_id = _add_grass_idea(eh, repo, pid)

    # Contained (idea, 'research') dev session + a report doc in its WORKTREE ONLY.
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    rel = _write_in_worktree(reg.get_session(rsid)["worktree_path"],
                             "research/run-1/REPORT.md",
                             "# Cooling report\n## Findings\nAdequate.\n")
    # Pre-condition (live flow): the doc is only in the worktree.
    assert not (repo / rel).is_file()

    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is True, out
    assert out["research_session_id"] == rsid
    prec = out["session"]
    psid = prec["session_id"]
    full = reg.get_session(psid)

    # The keystone persisted the research doc into MAIN (shared persist).
    assert (repo / rel).is_file(), "keystone did not persist the grass research doc"

    # v10 W5 invariants preserved exactly:
    assert prec["lane"] == "plan" and psid != rsid
    assert full["parent_session_id"] == rsid
    assert full["chain_id"] == reg.chain_for(rsid)
    assert full["grass_origin"] == idea_id
    paste = full["pending_paste"]
    assert paste and "Crucible" in paste
    assert rel in paste, "the prompt must name the REAL research doc path"
    assert full["paste_flushed"] is False
    # CONTAINED: GRASS_DEV_LABEL_PREFIX → excluded from the board + top strip.
    assert full["label"].startswith(eh.GRASS_DEV_LABEL_PREFIX)
    assert eh.is_grass_dev_label(full["label"]) is True
    # The idea stays in grass (copy, never destroy).
    assert eh.get_grass_idea(repo, pid, idea_id) is not None
    # The (idea, 'plan') dedupe map is persisted.
    idea_rec = eh.get_grass_idea(repo, pid, idea_id)
    assert eh._grass_dev_sessions(idea_rec).get("plan") == psid


def test_grass_advance_empty_research_still_opens_honest_minimal(env):
    """v11.1 Wave 2 (D1): a grass research dev session with NO produced docs AND no
    conversation in its buffer NO LONGER refuses — the advance ALWAYS opens the
    contained plan dev session with the honest-minimal 'create the materials'
    prompt (the v10/v11 'no-research-material' hard-refusal was removed; it diverged
    from the non-grass path and refused the conversation-only case)."""
    ts, eh, reg, repo, pid = (env["ts"], env["eh"], env["reg"], env["repo"],
                              env["pid"])
    idea_id = _add_grass_idea(eh, repo, pid)
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    # Produce NOTHING in the worktree AND no conversation.
    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is True, out
    assert out["reason"] != "no-research-material"
    prec = out["session"]
    assert prec is not None and prec["lane"] == "plan"
    psid = prec["session_id"]
    full = reg.get_session(psid)
    assert full["parent_session_id"] == rsid
    assert full["grass_origin"] == idea_id
    assert full["label"].startswith(eh.GRASS_DEV_LABEL_PREFIX)
    paste = full["pending_paste"]
    assert paste and "Crucible" in paste
    assert re.search(r"create the", paste, re.I), paste
    # The (idea, 'plan') dedupe map is persisted.
    idea_rec = eh.get_grass_idea(repo, pid, idea_id)
    assert eh._grass_dev_sessions(idea_rec).get("plan") == psid
    ts.kill(psid)
    ts.kill(rsid)


def test_grass_advance_re_advance_focuses_same_plan(env):
    """A second advance FOCUSES the same contained plan dev session (dedupe) — no
    second minted (v10 W5 preserved through the unification)."""
    ts, eh, reg, repo, pid = (env["ts"], env["eh"], env["reg"], env["repo"],
                              env["pid"])
    idea_id = _add_grass_idea(eh, repo, pid)
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    _write_in_worktree(reg.get_session(rsid)["worktree_path"],
                       "research/run-1/REPORT.md", "# R\n## Findings\nOK.\n")
    out1 = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out1["ok"] is True
    psid1 = out1["session"]["session_id"]
    out2 = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out2["ok"] is True
    assert out2["session"]["session_id"] == psid1, "re-advance minted a 2nd plan"
    plans = [s for s in reg.list_sessions(project_id=pid)
             if s.get("lane") == "plan"]
    assert len(plans) == 1

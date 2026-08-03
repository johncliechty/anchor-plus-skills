"""v12 Wave 7 — the COMPLETE retirement map (no two advance models).

EVERY legacy session-minting path is gated on the ``effort_managed`` discriminator
(NEVER on ``kind``/``current_stage`` — Shark C3): for a v12 effort each path
EARLY-RETURNS (mints nothing); for a LEGACY record (effort_managed==False — as the
v6/v8/v10/v11 healthcheck walks build) each path stays FULLY LIVE.

The gated minting sites (Shark C1/C2/C4):
  1. terminal_session.auto_advance_planning_to_build
  2. the term_kill handler branch  (POST /api/rnd/term_kill, planning kill)
  3. the finish_to_build handler   (POST /api/rnd/finish_to_build)
  4. terminal_session.reconcile_and_advance
  5. POST /api/rnd/advance_session
  6. POST /api/rnd/finish_to_build  (== #3 over HTTP; covered explicitly)
  + the grass second-advance: effort_history.advance_grass_research_to_plan

Each retirement assertion is SET equality on ``set(list_sessions ids)`` (not a
count) so a churned reconcile can't mask a stray mint.

Hermetic: ``ANCHOR_PTY_BACKEND=stub``, the fake runner, a temp git repo + temp
data dir + temp worktree base. NEVER binds ``:8777`` / a worktree off the real
repo / real network.
"""
import importlib
import json as _json
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


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "boneyard", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import terminal_session
    import session_registry
    import handoff
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
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "eh": effort_history, "handoff": handoff, "rnd": rnd_registry,
        "pty": pty_manager, "repo": repo, "pid": proj["id"],
        "wbase": wbase, "data": data,
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _ids(reg, pid):
    return set(r["session_id"] for r in reg.list_sessions(project_id=pid))


def _add_plan_set(eh, repo, pid, plan_dir="planning/rnd-x", created_at=2000.0):
    """Record a discovered planning session with a REAL committed MASTER+IMPL
    pair so discover_recent_plan_set finds it (a legacy record WOULD mint)."""
    master_rel = f"{plan_dir}/MASTER-PLAN.md"
    impl_rel = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    for rel, body in [(master_rel, "# Master Plan\n"),
                      (impl_rel, "# Implementation Plan\n")]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "plan set")
    specs = [(master_rel, "Master Plan"), (impl_rel, "Implementation Plan")]
    for i, (rel, title) in enumerate(specs):
        jid = eh.discovered_job_id("planning", rel)
        eh.record_effort(
            repo, pid, "planning", jid, skill="Crucible",
            extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan-doc",
                   "title": title, "artifact_path": rel, "status": "imported",
                   "created_at": created_at + i * 0.001})
    return {"master_rel": master_rel, "impl_rel": impl_rel}


def _free_server(gui):
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port, t


def _post(port, path, body):
    payload = _json.dumps(body).encode("utf-8")
    req = _req.Request(f"http://127.0.0.1:{port}{path}", data=payload,
                       headers={"Content-Type": "application/json"},
                       method="POST")
    try:
        with _req.urlopen(req, timeout=20) as r:
            return r.status, _json.loads(r.read().decode("utf-8"))
    except _req.HTTPError as e:
        return e.code, _json.loads(e.read().decode("utf-8"))


def _make_planning_effort(ts, reg, pid):
    """A v12 PLANNING effort (effort_managed=True), at the plan stage."""
    sess = ts.start_session(pid, "planning", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    assert reg.get_session(sid)["effort_managed"] is True
    return sid


def _make_research_effort(ts, reg, pid):
    """A v12 RESEARCH effort (effort_managed=True), at the research stage."""
    sess = ts.start_session(pid, "research", backend="claude",
                            effort_managed=True)
    sid = sess["session_id"]
    assert reg.get_session(sid)["effort_managed"] is True
    return sid


# ════════════════════════════════════════════════════════════════════════════
# RETIREMENT — parametrized over ALL the direct/module minting paths
# ════════════════════════════════════════════════════════════════════════════

def test_retire_auto_advance_planning_to_build(env):
    """#1 auto_advance_planning_to_build early-returns for an EFFORT (None),
    minting nothing — set equality."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_set(eh, repo, pid)
    sid = _make_planning_effort(ts, reg, pid)
    # Mark the effort DONE (the auto-advance precondition for a legacy record),
    # but it must STILL early-return because it is effort_managed.
    reg.update_session(sid, status=reg.STATUS_DONE)
    before = _ids(reg, pid)
    out = ts.auto_advance_planning_to_build(pid, sid)
    assert out is None, "effort must not auto-advance to a new build"
    assert _ids(reg, pid) == before


def test_retire_reconcile_and_advance(env):
    """#4 reconcile_and_advance: a dead EFFORT planning session is reconciled
    DONE but mints NO build (auto_builds empty) — set equality."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_set(eh, repo, pid)
    sid = _make_planning_effort(ts, reg, pid)
    before = _ids(reg, pid)
    # No live ids → the running planning effort is stale → reconciled DONE; but
    # the auto-advance MUST be gated off (effort_managed).
    out = ts.reconcile_and_advance(live_session_ids=[])
    assert sid in out["reconcile"]["marked"]
    assert out["auto_builds"] == [], "effort must not reconcile-advance"
    assert _ids(reg, pid) == before


def test_retire_http_term_kill_planning_branch(env):
    """#2 POST /api/rnd/term_kill on a PLANNING EFFORT: no auto_build, set
    equality (kill removes the killed session record — so compare on the set
    MINUS the killed id, asserting NO NEW id appeared)."""
    ts, reg, eh, repo, pid, gui = (env["ts"], env["reg"], env["eh"],
                                   env["repo"], env["pid"], env["gui"])
    _add_plan_set(eh, repo, pid)
    sid = _make_planning_effort(ts, reg, pid)
    before = _ids(reg, pid)
    srv, port, t = _free_server(gui)
    try:
        status, data = _post(port, "/api/rnd/term_kill", {"session": sid})
        assert status == 200 and data["ok"] is True
        assert data.get("auto_build") is None, "effort kill must not auto-build"
        after = _ids(reg, pid)
        # The killed session record stays (kill marks it terminal, doesn't
        # remove it) — and NO NEW session id was minted.
        assert after == before
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_retire_http_finish_to_build(env):
    """#3/#6 POST /api/rnd/finish_to_build on a PLANNING EFFORT early-returns
    (409, effort-managed reason); set equality."""
    ts, reg, eh, repo, pid, gui = (env["ts"], env["reg"], env["eh"],
                                   env["repo"], env["pid"], env["gui"])
    _add_plan_set(eh, repo, pid)
    sid = _make_planning_effort(ts, reg, pid)
    before = _ids(reg, pid)
    srv, port, t = _free_server(gui)
    try:
        status, data = _post(port, "/api/rnd/finish_to_build",
                             {"project_id": pid, "session": sid})
        assert data.get("auto_build") is None
        assert data.get("reason") == "effort-managed-use-advance-stage"
        assert _ids(reg, pid) == before
        # The effort is NOT marked DONE by the retired path (early-return before
        # the update_session mark).
        assert reg.get_session(sid)["status"] == reg.STATUS_RUNNING
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_retire_http_advance_session(env):
    """#5 POST /api/rnd/advance_session on a RESEARCH EFFORT early-returns
    (409, effort-managed reason); set equality (no planning session minted)."""
    ts, reg, eh, repo, pid, gui = (env["ts"], env["reg"], env["eh"],
                                   env["repo"], env["pid"], env["gui"])
    _add_plan_set(eh, repo, pid)
    sid = _make_research_effort(ts, reg, pid)
    before = _ids(reg, pid)
    srv, port, t = _free_server(gui)
    try:
        status, data = _post(port, "/api/rnd/advance_session",
                             {"project_id": pid, "source_session": sid})
        assert data.get("session") is None
        assert data.get("reason") == "effort-managed-use-advance-stage"
        assert _ids(reg, pid) == before
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_retire_grass_advance_research_to_plan(env):
    """The grass SECOND-ADVANCE: advance_grass_research_to_plan early-returns for
    a grass-dev EFFORT (the research dev session is effort_managed); set
    equality (no second grass plan session minted)."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "An idea worth developing")
    iid = idea.get("job_id")
    # Develop a research dev session, then mark it a v12 effort.
    dev = eh.develop_grass_idea(pid, iid, "research", folder_path=repo,
                                backend="claude")
    rsid = dev["session_id"]
    reg.update_session(rsid, effort_managed=True)
    assert reg.get_session(rsid)["effort_managed"] is True

    before = _ids(reg, pid)
    out = eh.advance_grass_research_to_plan(pid, iid, folder_path=repo)
    assert out["ok"] is False
    assert out["reason"] == "effort-managed-use-advance-stage"
    assert out["session"] is None
    assert _ids(reg, pid) == before


# ════════════════════════════════════════════════════════════════════════════
# LEGACY INTACT — a legacy record (effort_managed==False) STILL mints
# ════════════════════════════════════════════════════════════════════════════

def test_legacy_planning_record_still_auto_advances(env):
    """*Given* a synthetic LEGACY planning record (effort_managed==False, as the
    v10/v11 walks build), *When* the kill/auto-advance path runs, *Then* a build
    session IS minted (legacy behavior preserved, Shark C3)."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_set(eh, repo, pid)
    # A LEGACY planning session — no effort_managed kwarg.
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    assert reg.get_session(psid).get("effort_managed") in (False, None)
    ts.kill(psid)
    build = ts.auto_advance_planning_to_build(pid, psid)
    assert build is not None, "legacy planning kill MUST still auto-advance"
    assert build["lane"] == "build"
    assert build["parent_session_id"] == psid
    builds = [s for s in reg.list_sessions(project_id=pid)
              if s.get("lane") == "build"]
    assert len(builds) == 1
    ts.kill(build["session_id"])


def test_legacy_reconcile_dead_planning_still_advances(env):
    """The legacy reconcile-dead path STILL mints a build for a legacy record."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_set(eh, repo, pid)
    plan_sess = ts.start_session(pid, "planning", backend="claude")
    psid = plan_sess["session_id"]
    out = ts.reconcile_and_advance(live_session_ids=[])
    assert psid in out["reconcile"]["marked"]
    assert len(out["auto_builds"]) == 1, "legacy reconcile MUST still advance"
    ts.kill(out["auto_builds"][0]["session_id"])


def test_legacy_grass_advance_still_mints(env):
    """The legacy grass research→plan advance STILL mints a plan session for a
    LEGACY (effort_managed==False) grass-dev research session."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    idea = eh.add_idea(repo, pid, "A legacy grass idea")
    iid = idea.get("job_id")
    dev = eh.develop_grass_idea(pid, iid, "research", folder_path=repo,
                                backend="claude")
    rsid = dev["session_id"]
    assert reg.get_session(rsid).get("effort_managed") in (False, None)
    before = _ids(reg, pid)
    out = eh.advance_grass_research_to_plan(pid, iid, folder_path=repo)
    # Legacy path opens the plan dev session (v11.1: always opens, transcript- or
    # honest-minimal-backed) — a NEW session id appears.
    assert out["ok"] is True, "legacy grass advance MUST still open a plan session"
    assert out["session"] is not None
    after = _ids(reg, pid)
    assert after != before and len(after) == len(before) + 1

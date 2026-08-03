"""v12 Wave 3 — stage-scoped build deliverable resolution.

``deliverables.resolve_build_deliverable``: when the subject is a trio EFFORT
(carries ``stage_history``/``current_stage`` + a ``session_id``), feed it ONLY
the build-stage doc set (``efforts_for_session_stage(..., 'build')``) — so a
plan-stage MASTER-PLAN.md can NEVER be resolved as the build product (Shark C6).
Honest unresolved when ``current_stage != build`` or no build-stage signal.

``deliverables.backfill_build_deliverables``: with the stage-scoped persist
routing MASTER-PLAN.md into the ``planning`` store-lane (never ``build``), a
rescan pins the build product (app.py) only, never a plan-stage MASTER-PLAN.md.

Legacy (non-effort) build sessions are untouched — their existing behavior is
covered by ``test_build_deliverable.py`` and asserted preserved here.

Hermetic + WORKTREE-ONLY: a temp git repo, a temp data dir; build docs are
written into the worktree and persisted via the Wave-3 keystone (NOT
record_effort'd by hand). Never binds ``:8777``.
"""
import importlib
import subprocess
from pathlib import Path

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
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "rnd_registry", "effort_history", "sessions",
                "report_viewer", "summarizer", "deliverables"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry, effort_history, sessions, deliverables

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Deliv", str(repo), scaffold=False)
    return {
        "eh": effort_history, "rnd": rnd_registry, "sessions": sessions,
        "deliv": deliverables, "repo": repo, "pid": proj["id"],
    }


def _commit(repo, rel, body, msg):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "-m", msg)


def _drive_effort_to_build(eh, repo, pid, sid):
    """Run plan (commit MASTER-PLAN.md) then build (write app.py) for one effort,
    persisting each stage via the Wave-3 keystone. Returns the effort subject
    dict the resolver consumes (current_stage='build')."""
    # Plan stage: baseline then commit MASTER-PLAN.md, persist to planning lane.
    b_plan = eh.record_stage_baseline(repo)
    _commit(repo, "planning/MASTER-PLAN.md", "# master plan\n", "mp")
    eh.persist_session_stage_docs(repo, pid, sid, "plan", "planning", repo, b_plan)
    # Build stage: baseline then write app.py (uncommitted), persist to build lane.
    b_build = eh.record_stage_baseline(repo)
    (repo / "build").mkdir(parents=True, exist_ok=True)
    (repo / "build" / "app.py").write_text("print('app')\n", encoding="utf-8")
    eh.persist_session_stage_docs(repo, pid, sid, "build", "build", repo, b_build)
    # The effort subject the resolver sees: stage fields + session id.
    return {
        "session_id": sid,
        "effort_id": sid,
        "current_stage": "build",
        "stage_history": [
            {"stage": "plan", "store_lane": "planning", "state": "done"},
            {"stage": "build", "store_lane": "build", "state": "active"},
        ],
    }


# ── (1) effort build deliverable resolves the build product, never MASTER-PLAN ─

def test_effort_resolves_build_product_not_master_plan(env):
    eh, deliv, repo, pid = env["eh"], env["deliv"], env["repo"], env["pid"]
    sid = "EFFORT-D1"
    subject = _drive_effort_to_build(eh, repo, pid, sid)

    res = deliv.resolve_build_deliverable(repo, pid, subject)
    assert res["resolved"] is True, res
    path = res["deliverable"]["path"].replace("\\", "/")
    assert path.endswith("build/app.py")
    # The plan-stage MASTER-PLAN.md is NEVER the resolved deliverable.
    assert "MASTER-PLAN" not in path


# ── (2) current_stage != build → honest unresolved ───────────────────────────

def test_effort_at_plan_stage_unresolved(env):
    eh, deliv, repo, pid = env["eh"], env["deliv"], env["repo"], env["pid"]
    sid = "EFFORT-D2"
    # only plan persisted; effort still at plan.
    b_plan = eh.record_stage_baseline(repo)
    _commit(repo, "planning/MASTER-PLAN.md", "# mp\n", "mp")
    eh.persist_session_stage_docs(repo, pid, sid, "plan", "planning", repo, b_plan)
    subject = {
        "session_id": sid, "effort_id": sid, "current_stage": "plan",
        "stage_history": [{"stage": "plan", "store_lane": "planning",
                           "state": "active"}],
    }
    res = deliv.resolve_build_deliverable(repo, pid, subject)
    assert res["resolved"] is False
    assert res["deliverable"] is None
    assert "build" in res["reason"].lower()


# ── (3) effort at build but NO build-stage doc → honest unresolved ───────────

def test_effort_build_no_signal_unresolved(env):
    eh, deliv, repo, pid = env["eh"], env["deliv"], env["repo"], env["pid"]
    sid = "EFFORT-D3"
    # plan persisted, build stage opened but produced nothing.
    b_plan = eh.record_stage_baseline(repo)
    _commit(repo, "planning/MASTER-PLAN.md", "# mp\n", "mp")
    eh.persist_session_stage_docs(repo, pid, sid, "plan", "planning", repo, b_plan)
    subject = {
        "session_id": sid, "effort_id": sid, "current_stage": "build",
        "stage_history": [
            {"stage": "plan", "store_lane": "planning", "state": "done"},
            {"stage": "build", "store_lane": "build", "state": "active"},
        ],
    }
    res = deliv.resolve_build_deliverable(repo, pid, subject)
    assert res["resolved"] is False
    assert res["deliverable"] is None
    # never falls through to a project-level MASTER-PLAN marker.
    assert res["deliverable"] is None


# ── (4) backfill pins app.py only, never MASTER-PLAN.md ───────────────────────

def test_backfill_pins_build_product_only(env):
    eh, deliv, repo, pid = env["eh"], env["deliv"], env["repo"], env["pid"]
    sid = "EFFORT-D4"
    _drive_effort_to_build(eh, repo, pid, sid)
    # backfill scans the BUILD lane sessions (MASTER-PLAN.md lives in planning,
    # so it can never be scanned/pinned as a build product).
    out = deliv.backfill_build_deliverables(repo, pid)
    pinned_rels = {(r.get("artifact_path") or "").replace("\\", "/")
                   for r in deliv.list_pinned_deliverables(repo, pid)}
    assert "build/app.py" in pinned_rels
    assert "planning/MASTER-PLAN.md" not in pinned_rels


# ── (5) legacy (non-effort) build session behavior preserved ─────────────────

def test_legacy_non_effort_build_session_unchanged(env):
    """A legacy discovered build session (no stage fields) resolves exactly as
    before — _is_effort_subject is False so the v12 branch is skipped."""
    eh, deliv, sessions, repo, pid = (env["eh"], env["deliv"], env["sessions"],
                                      env["repo"], env["pid"])
    # A legacy build session: a north-star doc + a product member, recorded the
    # old way (this mirrors test_build_deliverable.py's fixture).
    (repo / "build" / "run-A").mkdir(parents=True, exist_ok=True)
    (repo / "build" / "run-A" / "NORTH-STAR.md").write_text("ns\n", "utf-8")
    (repo / "build" / "run-A" / "widget.py").write_text("# w\n", "utf-8")
    for fn, kind in (("NORTH-STAR.md", "northstar"), ("widget.py", "build")):
        eh.record_effort(repo, pid, "build",
                         eh.discovered_job_id("build", f"build/run-A/{fn}"),
                         skill="foreman",
                         extra={"source": eh.SOURCE_DISCOVERED,
                                "artifact_path": f"build/run-A/{fn}",
                                "title": fn, "kind": kind})
    bs = None
    for s in sessions.list_sessions(repo, pid, "build"):
        rels = {(m.get("artifact_path") or "") for m in s.get("member_files", [])}
        if "build/run-A/widget.py" in rels:
            bs = s
            break
    assert bs is not None
    # NOT an effort subject (no stage_history / current_stage).
    assert deliv._is_effort_subject(bs) is False
    res = deliv.resolve_build_deliverable(repo, pid, bs)
    assert res["resolved"] is True
    assert res["deliverable"]["path"].replace("\\", "/").endswith(
        "build/run-A/widget.py")

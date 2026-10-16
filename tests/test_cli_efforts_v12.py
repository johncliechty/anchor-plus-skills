"""Wave 12 — CLI mirror of the v12 "Efforts" read seams.

Proves IMPLEMENTATION-PLAN.md "## Wave 12 — CLI mirror": the new read subcommands
DELEGATE to the shared v12 seams (no forked logic):

  - rnd efforts <pid>                       → effort_view.build_effort_view
                                              (id · current_stage · status · stages)
  - rnd effort <pid> --session <id>         → effort_view.effort_for_session
                                              (ordered stage_history, SAFE projection)
  - rnd effort-deliverable <pid> --session <id>
                                            → deliverables.resolve_build_deliverable
                                              (build-stage product; honest unresolved)

All three are READ-ONLY (never start a PTY / advance / run a model / hit the
network) and HONEST when absent (no efforts → "No efforts"; unknown session → "No
effort"; not-at-build / no signal → UNRESOLVED). The SAFE projection NEVER carries
``worktree_path`` / ``branch`` / ``baseline_ref`` / ``store_lane``.

Hermetic: tmp ANCHOR_DATA_DIR, stub PTY backend, ANCHOR_RUNNER_CMD →
tests/fake_claude.py (NEVER live claude / real PTY / :8777). The effort records +
stage-tagged docs are seeded DIRECTLY via the shared modules so the test needs no
live session — it exercises the read mirror only.
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt"))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "rnd_registry", "effort_history", "sessions",
                 "session_registry", "worktrees", "pty_manager",
                 "terminal_session", "summarizer", "report_viewer",
                 "deliverables", "anchor_marker", "handoff", "boneyard",
                 "effort_view", "anchor"):
        importlib.reload(importlib.import_module(name))
    import anchor
    import rnd_registry
    import effort_history
    import session_registry
    import effort_view
    yield {"tmp": tmp_path, "anchor": anchor, "rnd": rnd_registry,
           "eh": effort_history, "sreg": session_registry, "ev": effort_view}
    try:
        import pty_manager
        for sid in list(pty_manager.live_sessions()):
            try:
                pty_manager.kill(sid)
            except Exception:
                pass
    except Exception:
        pass


def _mkproject(env, name="Anchor"):
    folder = env["tmp"] / f"proj-{name.lower().replace(' ', '-')}"
    folder.mkdir(parents=True, exist_ok=True)
    return env["rnd"].add_project(name, str(folder), scaffold=False), folder


def _seed_effort_record(env, pid, sid, current_stage="build",
                        stages=("research", "plan", "build")):
    """Register a v12 single-session effort record carrying a stage_history."""
    sreg = env["sreg"]
    history = []
    for st in stages:
        store = {"research": "research", "plan": "planning",
                 "build": "build"}.get(st, st)
        history.append({
            "stage": st, "store_lane": store,
            "started_at": 1000.0, "ended_at": None,
            "baseline_ref": "deadbeef" + st,  # MUST NOT leak through the mirror
            "seeded": False, "summary_ref": None, "doc_count": 0,
            "state": "active" if st == current_stage else "done",
        })
    lane = {"research": "research", "plan": "planning",
            "build": "build"}.get(current_stage, current_stage)
    rec = sreg.register_session(pid, lane, session_id=sid,
                                status=sreg.STATUS_RUNNING, label="eff",
                                effort_id=sid, effort_managed=True)
    sreg.update_session(sid, current_stage=current_stage,
                        stage_history=history, kind="trio")
    return sreg.get_session(sid)


# ── usage string lists the new subcommands ─────────────────────────────────

def test_cli_rnd_usage_lists_effort_subcommands(env, capsys):
    """`anchor.py rnd` (no subcommand) prints a usage line naming the v12 seams."""
    anchor = env["anchor"]
    anchor._rnd_cli([])
    out = capsys.readouterr().out
    assert "efforts" in out
    assert "effort-deliverable" in out


# ── rnd efforts ─────────────────────────────────────────────────────────────

def test_rnd_efforts_honest_empty(env):
    """A project with no efforts → empty list (never fabricated)."""
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "Empty")
    assert anchor.rnd_efforts(proj["id"]) == []


def test_cli_efforts_honest_empty_message(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "EmptyP")
    anchor._rnd_cli(["efforts", proj["id"]])
    out = capsys.readouterr().out
    assert "No efforts" in out


def test_rnd_efforts_lists_seeded_effort(env):
    """A seeded single-session effort surfaces as a SAFE projection."""
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "Efforts")
    pid = proj["id"]
    _seed_effort_record(env, pid, "EFF-1", current_stage="build")
    efforts = anchor.rnd_efforts(pid)
    assert len(efforts) == 1
    e = efforts[0]
    assert e["effort_id"] == "EFF-1"
    assert e["current_stage"] == "build"
    assert e["status"] == "running"
    assert e["stage_count"] == 3
    # SAFE: NEVER a worktree_path / branch / baseline_ref / stage_history.
    assert set(e.keys()) == {"effort_id", "current_stage", "status",
                             "stage_count"}


def test_cli_efforts_prints_rows(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "EffCLI")
    pid = proj["id"]
    _seed_effort_record(env, pid, "EFF-CLI-1", current_stage="plan",
                        stages=("research", "plan"))
    anchor._rnd_cli(["efforts", pid])
    out = capsys.readouterr().out
    assert "effort(s)" in out
    assert "EFF-CLI-1" in out
    assert "plan" in out
    # No baseline / worktree leak.
    assert "deadbeef" not in out


def test_cli_efforts_usage_when_missing_args(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["efforts"])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd efforts" in out


def test_rnd_efforts_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_efforts("deadbeef-not-real")


def test_cli_efforts_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["efforts", "deadbeef-not-real"])
    out = capsys.readouterr().out
    assert "Unknown project" in out


# ── rnd effort --session ────────────────────────────────────────────────────

def test_rnd_effort_honest_absent_unknown_session(env):
    """An unknown session → honest empty effort (no fabrication)."""
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "NoEffort")
    out = anchor.rnd_effort(proj["id"], "no-such-session")
    assert out["effort_id"] is None
    assert out["stage_history"] == []


def test_cli_effort_honest_absent_message(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "NoEffortP")
    anchor._rnd_cli(["effort", proj["id"], "--session", "no-such-session"])
    out = capsys.readouterr().out
    assert "No effort" in out


def test_rnd_effort_returns_safe_stage_history(env):
    """The effort's ordered stage_history is a SAFE projection."""
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "EffortHist")
    pid = proj["id"]
    _seed_effort_record(env, pid, "EFF-H1", current_stage="build")
    out = anchor.rnd_effort(pid, "EFF-H1")
    assert out["effort_id"] == "EFF-H1"
    assert out["current_stage"] == "build"
    stages = out["stage_history"]
    assert [s["stage"] for s in stages] == ["research", "plan", "build"]
    # SAFE keys ONLY — never baseline_ref / store_lane / worktree / branch.
    for s in stages:
        assert set(s.keys()) == {"stage", "state", "doc_count", "summary_ref"}


def test_cli_effort_prints_stage_track(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "EffortCLI")
    pid = proj["id"]
    _seed_effort_record(env, pid, "EFF-T1", current_stage="plan",
                        stages=("research", "plan"))
    anchor._rnd_cli(["effort", pid, "--session", "EFF-T1"])
    out = capsys.readouterr().out
    assert "Effort EFF-T1" in out
    assert "[research]" in out
    assert "[plan]" in out
    assert "deadbeef" not in out  # no baseline leak


def test_cli_effort_usage_when_missing_session(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "EffortUsage")
    anchor._rnd_cli(["effort", proj["id"]])  # no --session
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd effort" in out


def test_rnd_effort_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_effort("deadbeef-not-real", "any")


# ── rnd effort-deliverable --session ───────────────────────────────────────

def test_rnd_effort_deliverable_unresolved_off_build(env):
    """An effort at the PLAN stage → honest UNRESOLVED (not at build)."""
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "PlanStage")
    pid = proj["id"]
    _seed_effort_record(env, pid, "EFF-P1", current_stage="plan",
                        stages=("research", "plan"))
    res = anchor.rnd_effort_deliverable(pid, "EFF-P1")
    assert res["resolved"] is False
    assert res["deliverable"] is None


def test_rnd_effort_deliverable_resolves_build_product(env):
    """An effort at BUILD with a build-stage product resolves it, NOT a plan-stage
    MASTER-PLAN.md decoy."""
    anchor, eh = env["anchor"], env["eh"]
    proj, folder = _mkproject(env, "BuildProd")
    pid = proj["id"]
    sid = "EFF-B1"
    _seed_effort_record(env, pid, sid, current_stage="build")
    # A plan-stage MASTER-PLAN.md DECOY (must NOT be resolved as the build product).
    (folder / "planning").mkdir(parents=True, exist_ok=True)
    (folder / "planning" / "MASTER-PLAN.md").write_text("# mp\n", encoding="utf-8")
    eh.record_effort(str(folder), pid, "planning",
                     eh.discovered_job_id("planning", "planning/MASTER-PLAN.md"),
                     skill="Crucible",
                     extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan-doc",
                            "title": "Master Plan",
                            "artifact_path": "planning/MASTER-PLAN.md",
                            "session_id": sid, "stage": "plan"})
    # A real BUILD-stage product (a non-doc) tagged (sid, 'build').
    (folder / "app.py").write_text("print('app')\n", encoding="utf-8")
    eh.record_effort(str(folder), pid, "build",
                     eh.discovered_job_id("build", "app.py"),
                     skill="foreman",
                     extra={"source": eh.SOURCE_DISCOVERED, "kind": "build",
                            "title": "app.py", "artifact_path": "app.py",
                            "session_id": sid, "stage": "build"})
    res = anchor.rnd_effort_deliverable(pid, sid)
    assert res["resolved"] is True, res
    path = (res["deliverable"]["path"] or "").replace("\\", "/")
    assert path.endswith("app.py")
    assert "MASTER-PLAN" not in path


def test_cli_effort_deliverable_unresolved_message(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "DelivCLI")
    pid = proj["id"]
    _seed_effort_record(env, pid, "EFF-D1", current_stage="plan",
                        stages=("research", "plan"))
    anchor._rnd_cli(["effort-deliverable", pid, "--session", "EFF-D1"])
    out = capsys.readouterr().out
    assert "UNRESOLVED" in out


def test_cli_effort_deliverable_usage_when_missing_session(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "DelivUsage")
    anchor._rnd_cli(["effort-deliverable", proj["id"]])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd effort-deliverable" in out


def test_rnd_effort_deliverable_unknown_session_raises_valueerror(env):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "UnkSess")
    with pytest.raises(ValueError):
        anchor.rnd_effort_deliverable(proj["id"], "no-such-session")


def test_rnd_effort_deliverable_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_effort_deliverable("deadbeef-not-real", "any")


# ── read-only invariant ─────────────────────────────────────────────────────

def test_effort_mirrors_are_read_only(env):
    """Reading efforts / effort / effort-deliverable never mutates the registry."""
    anchor, sreg = env["anchor"], env["sreg"]
    proj, folder = _mkproject(env, "ReadOnly")
    pid = proj["id"]
    _seed_effort_record(env, pid, "EFF-RO", current_stage="build")
    before = sreg.get_session("EFF-RO")
    anchor.rnd_efforts(pid)
    anchor.rnd_effort(pid, "EFF-RO")
    try:
        anchor.rnd_effort_deliverable(pid, "EFF-RO")
    except Exception:
        pass
    after = sreg.get_session("EFF-RO")
    assert after is not None
    assert after.get("current_stage") == before.get("current_stage")
    assert after.get("stage_history") == before.get("stage_history")

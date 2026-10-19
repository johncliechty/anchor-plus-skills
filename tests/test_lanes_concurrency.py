"""Wave 6 — lane wiring + within-project / cross-folder concurrency.

AC1: a lane launch uses the correct skill + prompt seed AND gives the engine the
     project-scoped output path so the effort is recorded under
     ``.anchor/projects/<id>/<lane>/`` — NEVER the folder root.
AC2: a build running for a project serializes/refuses a second build for the
     SAME project, while a research job for that project runs concurrently.
AC4: two projects in DIFFERENT folders both launch builds → they run
     concurrently.
AC5: reattach — after a simulated browser close/reopen, a job's log re-tails
     history → live.

NO live ``claude`` is ever invoked — everything goes through ANCHOR_RUNNER_CMD →
tests/fake_claude.py. All spawned procs are reaped (no leaks).
"""
import importlib
import json
import threading
import time
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import lanes
    importlib.reload(lanes)
    yield lanes
    # Cancel any still-running jobs, then reset policy tables (no leaks).
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            job_runner.cancel(rec["job_id"])
    job_runner._reset_live_table_for_tests()


def _mkproject(tmp_subdir, name="P"):
    """Register a project rooted at a fresh real folder; returns the entry."""
    import rnd_registry
    tmp_subdir.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(tmp_subdir))


# ── AC1 ──────────────────────────────────────────────────────────────────────

def test_ac1_lane_uses_skill_seed_and_project_scoped_output(env, tmp_path):
    lanes = env
    import job_runner
    proj = _mkproject(tmp_path / "folderA", "Alpha")
    pid = proj["id"]
    folder = Path(proj["folder_path"])

    rec = lanes.launch_lane(pid, "plan",
                            extra_args=["--lines", "2", "--exit-code", "0"])
    jid = rec["job_id"]

    # Correct skill identifier recorded.
    assert rec["skill"] == lanes.SKILL_PLAN == "crucible"
    # The engine was given the project-scoped output path.
    expected_out = folder / ".anchor" / "projects" / pid / "planning"
    assert Path(rec["output_dir"]) == expected_out

    # The launch pointer-record landed UNDER the project namespace (not root).
    pointer = expected_out / lanes.LAUNCH_RECORD_NAME
    assert pointer.exists(), "effort not recorded under project namespace"
    data = json.loads(pointer.read_text(encoding="utf-8"))
    assert data["skill"] == "crucible"
    assert data["lane"] == "plan"
    # Git-trackable pointer metadata binds the prompt without leaking project
    # names, prompt text, or absolute user paths into the repository.
    import hashlib
    assert data["prompt_sha256"] == hashlib.sha256(
        rec["relaunch_spec"]["prompt"].encode("utf-8")
    ).hexdigest()
    assert "prompt_seed" not in data
    assert "output_dir" not in data
    assert "project_id" not in data
    assert str(folder) not in json.dumps(data)

    # NEVER the folder root: no launch pointer-record at the folder root itself.
    assert not (folder / lanes.LAUNCH_RECORD_NAME).exists()

    job_runner.wait(jid, timeout=30)


def test_brownfield_prompt_seeds_render_with_placeholders(env):
    """Enriched brownfield seeds still substitute name/folder/output_dir and now
    carry take-over-ready / brownfield language — for all three trio lanes."""
    lanes = env
    project = {"name": "Acme", "folder_path": "C:/dev/Acme"}
    out = "C:/dev/Acme/.anchor/p/plan"

    # All three lanes render without KeyError and substitute every placeholder.
    for lane in ("research", "plan", "build"):
        seed = lanes.build_prompt_seed(lane, project, out)
        assert "Acme" in seed                 # {name!r}
        assert "C:/dev/Acme" in seed          # {folder}
        assert out in seed                    # {output_dir}
        assert "{name" not in seed and "{folder" not in seed
        assert "{output_dir" not in seed

    research = lanes.build_prompt_seed("research", project, out)
    plan = lanes.build_prompt_seed("plan", project, out)
    build = lanes.build_prompt_seed("build", project, out)

    # Research: keeps no-gate/no-mutate posture + adds brownfield inventory/orient.
    assert "researchPrime" in research
    assert "no interactive gate" in research
    assert "do not mutate" in research.lower() or "not mutate" in research.lower()
    assert "brownfield" in research.lower()
    assert "inventory" in research.lower()

    # Plan: keeps crucible + no-mutate; adds brownfield assess + Foreman-ready.
    assert "crucible" in plan
    assert "not mutate" in plan.lower()
    assert "brownfield" in plan.lower()
    assert "foreman-ready" in plan.lower()
    assert "assess" in plan.lower()

    # Build: keeps foreman + mutate posture; adds continue-from-existing note.
    assert "foreman" in build
    assert "mutate the shared working tree" in build.lower()
    assert "brownfield" in build.lower()
    assert "scratch" in build.lower()


def test_ac1_each_lane_maps_to_its_skill_and_subdir(env, tmp_path):
    lanes = env
    import job_runner
    cases = [
        ("research", "researchPrime", "research", False),
        ("plan", "crucible", "planning", True),
        ("build", "foreman", "build", True),
    ]
    for i, (lane, skill, subdir, gates) in enumerate(cases):
        proj = _mkproject(tmp_path / f"f{i}", lane)
        pid = proj["id"]
        rec = lanes.launch_lane(pid, lane, extra_args=["--lines", "1"])
        assert rec["skill"] == skill
        assert rec["gates"] is gates
        out = Path(rec["output_dir"])
        assert out.name == subdir
        assert out.parent.name == pid  # under .anchor/projects/<id>/
        job_runner.wait(rec["job_id"], timeout=30)


def test_ac1_research_runs_to_completion_no_gate(env, tmp_path):
    lanes = env
    import job_runner
    proj = _mkproject(tmp_path / "rf", "R")
    rec = lanes.launch_lane(proj["id"], "research",
                            extra_args=["--lines", "3", "--exit-code", "0"])
    final = job_runner.wait(rec["job_id"], timeout=30)
    assert final["status"] == job_runner.STATUS_DONE
    assert rec["gates"] is False


# ── AC2 ──────────────────────────────────────────────────────────────────────

def test_ac2_same_project_second_build_refused_research_concurrent(env, tmp_path):
    lanes = env
    import job_runner
    proj = _mkproject(tmp_path / "proj", "Beta")
    pid = proj["id"]

    # First build — kept alive via --sleep so it holds the lane slot.
    b1 = lanes.launch_lane(pid, "build", extra_args=["--lines", "1", "--sleep", "2.0"])

    # A SECOND build for the SAME project is serialized/refused.
    with pytest.raises(job_runner.LaneBusyError) as ei:
        lanes.launch_lane(pid, "build", extra_args=["--lines", "1"])
    assert ei.value.reason == job_runner.REFUSED_SAME_LANE
    assert ei.value.holder == b1["job_id"]

    # A research job for the SAME project may run CONCURRENTLY (different lane).
    r1 = lanes.launch_lane(pid, "research", extra_args=["--lines", "1"])
    assert r1["job_id"] != b1["job_id"]
    job_runner.wait(r1["job_id"], timeout=30)
    # The build is still running (it held its slot the whole time).
    assert job_runner.load_record(b1["job_id"])["status"] == job_runner.STATUS_RUNNING

    # Once the build finishes, its lane slot frees and a new build is allowed.
    job_runner.wait(b1["job_id"], timeout=30)
    b2 = lanes.launch_lane(pid, "build", extra_args=["--lines", "1"])
    assert b2["job_id"] != b1["job_id"]
    job_runner.wait(b2["job_id"], timeout=30)


# ── AC4 ──────────────────────────────────────────────────────────────────────

def test_ac4_builds_in_different_folders_run_concurrently(env, tmp_path):
    lanes = env
    import job_runner
    p1 = _mkproject(tmp_path / "folder1", "One")
    p2 = _mkproject(tmp_path / "folder2", "Two")
    assert p1["folder_path"] != p2["folder_path"]

    b1 = lanes.launch_lane(p1["id"], "build", extra_args=["--lines", "1", "--sleep", "1.5"])
    # Different folder → NOT folder-build-locked → concurrent launch succeeds.
    b2 = lanes.launch_lane(p2["id"], "build", extra_args=["--lines", "1", "--sleep", "1.5"])

    # Both are genuinely running at the same time.
    assert job_runner.load_record(b1["job_id"])["status"] == job_runner.STATUS_RUNNING
    assert job_runner.load_record(b2["job_id"])["status"] == job_runner.STATUS_RUNNING
    assert b1["job_id"] != b2["job_id"]

    job_runner.wait(b1["job_id"], timeout=30)
    job_runner.wait(b2["job_id"], timeout=30)


# ── AC5 ──────────────────────────────────────────────────────────────────────

def test_ac5_reattach_retails_history_then_live(env, tmp_path):
    lanes = env
    import job_runner
    proj = _mkproject(tmp_path / "reattach", "Re")
    # A job that emits a couple lines, sleeps (browser "closes" here), then more.
    rec = lanes.launch_lane(proj["id"], "research",
                            extra_args=["--lines", "2", "--sleep", "0.8"])
    jid = rec["job_id"]

    # Wait until the first 2 lines are captured (history exists).
    deadline = time.monotonic() + 10
    while len(job_runner.all_lines(jid)) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(job_runner.all_lines(jid)) >= 2

    # Simulate "closed browser": drop the in-memory live table. The durable log
    # on disk is the source of truth and persists across the close.
    job_runner._reset_live_table_for_tests()
    assert jid not in job_runner._LIVE

    # Reopen: a fresh client re-tails HISTORY from index 0 off the durable log.
    hist = job_runner.tail(jid, since=0)
    assert hist["lines"][:2] == ["fake-line 0", "fake-line 1"]
    cursor = hist["next"]

    # Then it long-polls for LIVE continuation (the job is still finishing /
    # finalizing). It must receive subsequent activity or a terminal status,
    # never crash.
    out = job_runner.long_poll(jid, since=cursor, ceiling=5.0, poll_interval=0.02)
    assert out["status"] in (job_runner.STATUS_RUNNING,) + tuple(
        job_runner.TERMINAL_STATUSES)

    final = job_runner.wait(jid, timeout=30)
    assert final["status"] == job_runner.STATUS_DONE
    # Full history is intact on disk after reattach.
    assert job_runner._lines_from_log(jid)[:2] == ["fake-line 0", "fake-line 1"]

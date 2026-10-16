"""Wave 6 — folder-level build lock (AC3).

AC3: a build running in folder F blocks ANOTHER project's build in F with a
     folder-build-lock indicator; research/plan jobs in F still run concurrently;
     releasing the first build frees the lock.

The lock is at the FOLDER level (two projects sharing one folder), enforcing the
trio's "no parallel coders in one tree" rule. Build (foreman) mutates the shared
working tree; research/plan are non-mutating and project-scoped, so they are NOT
folder-locked.

NO live ``claude`` — everything goes through ANCHOR_RUNNER_CMD → fake_claude.py.
All spawned procs are reaped (no leaks).
"""
import importlib
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
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            job_runner.cancel(rec["job_id"])
    job_runner._reset_live_table_for_tests()


def _two_projects_one_folder(folder, n1="A", n2="B"):
    """Register TWO projects sharing ONE folder (1 folder : N projects, D5)."""
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    a = rnd_registry.add_project(n1, str(folder))
    b = rnd_registry.add_project(n2, str(folder))
    assert a["id"] != b["id"]
    assert a["folder_path"] == b["folder_path"]
    return a, b


def test_ac3_build_blocks_other_project_build_in_same_folder(env, tmp_path):
    lanes = env
    import job_runner
    folder = tmp_path / "shared"
    a, b = _two_projects_one_folder(folder)
    fp = a["folder_path"]

    # Project A starts a build (held alive via --sleep) → it holds the folder lock.
    ba = lanes.launch_lane(a["id"], "build", extra_args=["--lines", "1", "--sleep", "2.0"])

    # The folder-build-lock indicator is observable (badge data).
    assert job_runner.folder_build_holder(fp) == ba["job_id"]

    # Project B (DIFFERENT project, SAME folder) requesting a build is refused
    # with the folder-build-lock indicator.
    with pytest.raises(job_runner.LaneBusyError) as ei:
        lanes.launch_lane(b["id"], "build", extra_args=["--lines", "1"])
    assert ei.value.reason == job_runner.REFUSED_FOLDER_BUILD
    assert ei.value.holder == ba["job_id"]

    # Releasing the first build frees the lock → B's build now succeeds.
    job_runner.wait(ba["job_id"], timeout=30)
    assert job_runner.folder_build_holder(fp) is None
    bb = lanes.launch_lane(b["id"], "build", extra_args=["--lines", "1"])
    assert bb["job_id"] != ba["job_id"]
    job_runner.wait(bb["job_id"], timeout=30)


def test_ac3_research_and_plan_not_folder_locked(env, tmp_path):
    lanes = env
    import job_runner
    folder = tmp_path / "shared2"
    a, b = _two_projects_one_folder(folder)

    # A build in the folder holds the build lock.
    ba = lanes.launch_lane(a["id"], "build", extra_args=["--lines", "1", "--sleep", "2.0"])
    assert job_runner.folder_build_holder(a["folder_path"]) == ba["job_id"]

    # Research + plan for the OTHER project in the SAME folder still run
    # concurrently — they are NOT folder-locked (non-mutating, project-scoped).
    r = lanes.launch_lane(b["id"], "research", extra_args=["--lines", "1"])
    p = lanes.launch_lane(b["id"], "plan", extra_args=["--lines", "1"])
    assert r["job_id"] != ba["job_id"]
    assert p["job_id"] != ba["job_id"]
    # The build is still holding its lock while they ran.
    assert job_runner.load_record(ba["job_id"])["status"] == job_runner.STATUS_RUNNING

    job_runner.wait(r["job_id"], timeout=30)
    job_runner.wait(p["job_id"], timeout=30)
    job_runner.wait(ba["job_id"], timeout=30)


def test_ac3_same_project_research_during_build_in_folder(env, tmp_path):
    """Even the build-holding project may run research concurrently (cross-lane),
    confirming the folder lock targets only the build lane."""
    lanes = env
    import job_runner
    folder = tmp_path / "shared3"
    a, _b = _two_projects_one_folder(folder)

    ba = lanes.launch_lane(a["id"], "build", extra_args=["--lines", "1", "--sleep", "1.5"])
    ra = lanes.launch_lane(a["id"], "research", extra_args=["--lines", "1"])
    assert ra["job_id"] != ba["job_id"]
    job_runner.wait(ra["job_id"], timeout=30)
    job_runner.wait(ba["job_id"], timeout=30)


def test_ac3_folder_lock_released_on_cancel(env, tmp_path):
    """Cancelling (not just completing) a build also frees the folder lock."""
    lanes = env
    import job_runner
    folder = tmp_path / "shared4"
    a, b = _two_projects_one_folder(folder)

    ba = lanes.launch_lane(a["id"], "build", extra_args=["--lines", "1", "--sleep", "5.0"])
    assert job_runner.folder_build_holder(a["folder_path"]) == ba["job_id"]

    job_runner.cancel(ba["job_id"])
    # After cancel the holder is terminal → lock self-heals to free.
    assert job_runner.folder_build_holder(a["folder_path"]) is None
    bb = lanes.launch_lane(b["id"], "build", extra_args=["--lines", "1"])
    assert bb["job_id"] != ba["job_id"]
    job_runner.wait(bb["job_id"], timeout=30)

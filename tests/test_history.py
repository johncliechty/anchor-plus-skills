"""Wave 7 — versioned effort history (AC1).

AC1: Given multiple efforts, when history is read, then records are sorted
     NEWEST-FIRST (index 0 = most recent) and nothing is deleted on re-run (D5).

Pure on-disk pointer-records; no subprocess, no live claude.
"""
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    return effort_history, rnd_registry


def _project(rnd, tmp_path, name="P"):
    folder = tmp_path / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project(name, str(folder))


def test_history_newest_first_index0_is_most_recent(mods, tmp_path):
    eh, rnd = mods
    proj = _project(rnd, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]

    # Append three efforts in order j1 → j2 → j3.
    for jid in ("j1", "j2", "j3"):
        eh.record_effort(folder, pid, "research", jid, skill="researchPrime")

    efforts = eh.list_efforts(folder, pid, "research")
    assert [e["job_id"] for e in efforts] == ["j3", "j2", "j1"]
    # index 0 == most recent.
    assert efforts[0]["job_id"] == "j3"
    assert eh.latest_effort(folder, pid, "research")["job_id"] == "j3"


def test_rerun_never_deletes_prior_efforts(mods, tmp_path):
    eh, rnd = mods
    proj = _project(rnd, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]

    eh.record_effort(folder, pid, "build", "old", skill="foreman")
    eh.record_effort(folder, pid, "build", "new", skill="foreman")

    # "Re-run" the lane again (another new effort) — prior efforts survive.
    eh.record_effort(folder, pid, "build", "newest", skill="foreman")

    efforts = eh.list_efforts(folder, pid, "build")
    assert [e["job_id"] for e in efforts] == ["newest", "new", "old"]
    # All three pointer-records are present on disk (nothing deleted).
    ed = eh.efforts_dir(folder, pid, "build")
    files = sorted(p.name for p in ed.glob("*.pointer.json"))
    assert files == ["new.pointer.json", "newest.pointer.json", "old.pointer.json"]


def test_update_same_jobid_is_in_place_not_a_new_effort(mods, tmp_path):
    eh, rnd = mods
    proj = _project(rnd, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]

    eh.record_effort(folder, pid, "research", "j1", skill="researchPrime")
    # Update the SAME effort (e.g. to stamp cost) — must not duplicate.
    eh.record_effort(folder, pid, "research", "j1",
                     extra={"cost": {"total_cost_usd": 1.0}})
    efforts = eh.list_efforts(folder, pid, "research")
    assert len(efforts) == 1
    assert efforts[0]["cost"]["total_cost_usd"] == 1.0


def test_lane_name_aliases_map_to_same_subdir(mods, tmp_path):
    eh, rnd = mods
    proj = _project(rnd, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]
    # "plan" (trio name) and "planning" (store subdir) are the same lane.
    eh.record_effort(folder, pid, "plan", "p1", skill="crucible")
    efforts = eh.list_efforts(folder, pid, "planning")
    assert [e["job_id"] for e in efforts] == ["p1"]

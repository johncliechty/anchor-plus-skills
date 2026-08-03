"""Wave 3 — id-keyed R&D registry tests.

Covers: id-keyed CRUD; folder_path non-unique (N projects per folder, no
collision); priority/archive/future retained-not-deleted; legacy id assignment
idempotent; path-missing state; JSON persistence round-trip under a tmp
ANCHOR_DATA_DIR; concurrent writes lock-serialized (no lost update).
"""
import importlib
import json
import threading

import pytest


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """Fresh registry rooted at a tmp ANCHOR_DATA_DIR."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    return rnd_registry


def test_add_and_get_id_keyed(reg, tmp_path):
    e = reg.add_project("Anchor", str(tmp_path / "Anchor"))
    assert e["id"]
    assert e["name"] == "Anchor"
    assert e["priority"] == 2
    assert e["state"] == reg.STATE_ACTIVE
    got = reg.get_project(e["id"])
    assert got["id"] == e["id"]


def test_fresh_id_per_project(reg, tmp_path):
    a = reg.add_project("A", str(tmp_path / "A"))
    b = reg.add_project("B", str(tmp_path / "B"))
    assert a["id"] != b["id"]


def test_folder_path_non_unique(reg, tmp_path):
    folder = str(tmp_path / "shared")
    a = reg.add_project("Proj-A", folder)
    b = reg.add_project("Proj-B", folder)
    assert a["id"] != b["id"]
    assert a["folder_path"] == b["folder_path"]
    # Both grouped under the one folder.
    groups = reg.group_by_folder()
    key = next(k for k in groups if k.endswith("shared"))
    ids = {e["id"] for e in groups[key]}
    assert {a["id"], b["id"]} <= ids
    # Stores do not collide — distinct dirs.
    sa = reg.project_store_dir(folder, a["id"])
    sb = reg.project_store_dir(folder, b["id"])
    assert sa != sb
    assert sa.exists() and sb.exists()
    for lane in reg.LANE_DIRS:
        assert (sa / lane).is_dir()
        assert (sb / lane).is_dir()


def test_scaffold_creates_lane_dirs(reg, tmp_path):
    folder = str(tmp_path / "P")
    e = reg.add_project("P", folder)
    store = reg.project_store_dir(folder, e["id"])
    for lane in ("research", "planning", "build", "deliverables", "jobs"):
        assert (store / lane).is_dir()
    # Tracking policy present.
    anchor_dir = tmp_path / "P" / ".anchor"
    assert (anchor_dir / ".gitignore").exists()
    assert (anchor_dir / "README").exists()


def test_priority_change_persists(reg, tmp_path):
    e = reg.add_project("P", str(tmp_path / "P"))
    reg.set_priority(e["id"], 1)
    assert reg.get_project(e["id"])["priority"] == 1


def test_archive_retained_not_deleted(reg, tmp_path):
    e = reg.add_project("P", str(tmp_path / "P"))
    reg.archive_project(e["id"])
    # Still in the registry.
    assert reg.get_project(e["id"]) is not None
    assert reg.get_project(e["id"])["state"] == reg.STATE_ARCHIVED
    # Listed when archived included.
    ids = {x["id"] for x in reg.list_projects(include_archived=True)}
    assert e["id"] in ids
    # Filtered out of the active-only view but NOT deleted.
    ids_active = {x["id"] for x in reg.list_projects(include_archived=False)}
    assert e["id"] not in ids_active
    assert reg.get_project(e["id"]) is not None


def test_future_retained_not_deleted(reg, tmp_path):
    e = reg.add_project("P", str(tmp_path / "P"))
    reg.mark_future(e["id"])
    assert reg.get_project(e["id"])["state"] == reg.STATE_FUTURE
    ids_no_future = {x["id"] for x in reg.list_projects(include_future=False)}
    assert e["id"] not in ids_no_future
    assert reg.get_project(e["id"]) is not None


def test_path_missing_state(reg, tmp_path):
    # Register a folder, then remove it.
    folder = tmp_path / "gone"
    folder.mkdir()
    e = reg.add_project("Gone", str(folder))
    import shutil
    shutil.rmtree(folder)
    listed = {x["id"]: x for x in reg.list_projects()}
    assert listed[e["id"]]["state"] == reg.STATE_PATH_MISSING
    # The stored state is untouched (still active) — no crash, no deletion.
    raw = reg.load_registry()[e["id"]]
    assert raw["state"] == reg.STATE_ACTIVE


def test_persistence_round_trip(reg, tmp_path):
    e = reg.add_project("Persisted", str(tmp_path / "Persisted"), priority=1)
    # Read the raw JSON file.
    p = reg.registry_path()
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert any(x["id"] == e["id"] and x["priority"] == 1 for x in data)
    # Reload fresh from disk.
    reloaded = reg.load_registry()
    assert reloaded[e["id"]]["name"] == "Persisted"


def test_legacy_id_assignment_idempotent(reg, tmp_path):
    legacy = [
        {"name": "Old1", "folder_path": str(tmp_path / "o1")},
        {"name": "Old2", "folder_path": str(tmp_path / "o2")},
    ]
    first = reg.assign_legacy_ids(legacy)
    ids1 = sorted(e["id"] for e in first)
    assert all(e["id"] for e in first)
    # Re-run with the now-id'd entries → same ids (idempotent).
    second = reg.assign_legacy_ids(first)
    ids2 = sorted(e["id"] for e in second)
    assert ids1 == ids2
    # Registry not duplicated.
    assert len(reg.load_registry()) == 2


def test_status_line_shape_per_lane_counts(reg, tmp_path):
    """Wave 3 contract: status_line returns {lane: {count, imported, running}}."""
    import effort_history as eh
    importlib.reload(eh)
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = reg.add_project("P", str(folder))["id"]

    # Empty project: every lane is a zeroed counts dict (never "none-yet").
    line = reg.status_line(pid)
    for lane in reg.STATUS_LANES:
        assert line[lane] == {"count": 0, "imported": 0, "running": 0}

    # One real run + two discovered planning files in two dirs (=2 sessions).
    eh.record_effort(folder, pid, "research", "r1", skill="researchPrime")
    eh.record_effort(folder, pid, "planning", "d1", skill="crucible",
                     extra={"source": "discovered",
                            "artifact_path": "planning/a/x.md"})
    eh.record_effort(folder, pid, "planning", "d2", skill="crucible",
                     extra={"source": "discovered",
                            "artifact_path": "planning/b/y.md"})
    line = reg.status_line(pid)
    assert line["research"] == {"count": 1, "imported": 0, "running": 0}
    assert line["planning"]["count"] == 2
    assert line["planning"]["imported"] == 2


def test_blurb_field_round_trips(reg, tmp_path):
    pid = reg.add_project("P", str(tmp_path / "P"), blurb="seed blurb")["id"]
    assert reg.get_project(pid)["blurb"] == "seed blurb"
    reg.set_blurb(pid, "edited")
    assert reg.get_project(pid)["blurb"] == "edited"
    # Persisted to disk.
    assert reg.load_registry()[pid]["blurb"] == "edited"


def test_concurrent_writes_no_lost_update(reg, tmp_path):
    n = 25
    errors = []

    def worker(i):
        try:
            reg.add_project(f"P{i}", str(tmp_path / f"P{i}"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # All N writes survived (lock serialized them — no lost update).
    assert len(reg.load_registry()) == n

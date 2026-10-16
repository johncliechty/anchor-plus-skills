"""Wave 2 — honest discovery model + reconciliation in effort_history.

Proves IMPLEMENTATION-PLAN.md "## Wave 2":

GIVEN 2 real + 3 discovered efforts, WHEN project_rollup runs, THEN
  effort_count == 2, discovered_count == 3, cost unchanged; AND adopting twice
  yields no duplicates; AND after a discovered artifact is deleted + rescan, its
  record is gone.

Honesty contract:
  - discovered records carry source="discovered", real metadata only, NO cost.
  - list_efforts STILL returns discovered records (render needs them).
  - lane_rollup/project_rollup EXCLUDE discovered from effort_count + cost and
    add a parallel discovered_count.
  - real efforts are NEVER mutated/pruned by reconciliation.
"""
import importlib

import pytest

import brownfield_scan as bscan


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


def _seed_brownfield(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "foreman-checkpoint.json").write_text("{}", encoding="utf-8")
    p = root / "planning"
    p.mkdir()
    (p / "MASTER-PLAN.md").write_text("# Master\n", encoding="utf-8")
    r = root / "research" / "s"
    r.mkdir(parents=True)
    (r / "report.md").write_text("# R\n", encoding="utf-8")
    return root


def test_adopt_then_rollup_excludes_discovered(mods, tmp_path):
    eh, rnd = mods
    folder = tmp_path / "proj"
    _seed_brownfield(folder)
    proj = rnd.add_project("P", str(folder))
    pid = proj["id"]

    # Two REAL efforts (with cost) in research.
    for jid, cost in (("e1", 0.01), ("e2", 0.02)):
        eh.record_effort(folder, pid, "research", jid, skill="researchPrime")
        eh.finalize_effort(folder, pid, "research", jid,
                           {"status": "done",
                            "cost": {"total_cost_usd": cost,
                                     "total_tokens": 100}},
                           auto_commit=False)

    # Adopt the brownfield scan (3 discovered: build/planning/research).
    scan = bscan.scan(str(folder))
    rep = eh.adopt_discovered(folder, pid, scan)
    assert rep["adopted"] == 3
    assert rep["pruned"] == 0

    # list_efforts STILL returns discovered records.
    research = eh.list_efforts(folder, pid, "research")
    assert any(eh.is_discovered(r) for r in research)
    assert sum(1 for r in research if eh.is_discovered(r)) == 1
    assert sum(1 for r in research if not eh.is_discovered(r)) == 2

    # Discovered record honesty: source flag, real metadata, NO cost.
    disc = [r for r in research if eh.is_discovered(r)][0]
    assert disc["source"] == "discovered"
    assert disc["artifact_path"] == "research/s/report.md"
    assert disc["created_at"] > 0
    assert "cost" not in disc or not disc.get("cost")
    assert "session_id" not in disc
    assert "total_cost_usd" not in disc

    # Rollup: 2 real efforts, 3 discovered, cost unchanged (only real).
    pr = eh.project_rollup(pid, folder)
    assert pr["total"]["effort_count"] == 2
    assert pr["total"]["discovered_count"] == 3
    assert pr["total"]["total_cost_usd"] == pytest.approx(0.03)
    assert pr["lanes"]["research"]["effort_count"] == 2
    assert pr["lanes"]["research"]["discovered_count"] == 1
    assert pr["lanes"]["planning"]["discovered_count"] == 1
    assert pr["lanes"]["build"]["discovered_count"] == 1


def test_adopt_twice_is_idempotent(mods, tmp_path):
    eh, rnd = mods
    folder = tmp_path / "proj"
    _seed_brownfield(folder)
    proj = rnd.add_project("P", str(folder))
    pid = proj["id"]
    scan = bscan.scan(str(folder))
    eh.adopt_discovered(folder, pid, scan)
    n1 = {lane: len(eh.list_efforts(folder, pid, lane))
          for lane in ("research", "planning", "build", "deliverables")}
    # Adopt again with a fresh scan — must NOT duplicate.
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    n2 = {lane: len(eh.list_efforts(folder, pid, lane))
          for lane in ("research", "planning", "build", "deliverables")}
    assert n1 == n2


def test_rescan_prunes_deleted_artifact(mods, tmp_path):
    eh, rnd = mods
    folder = tmp_path / "proj"
    _seed_brownfield(folder)
    proj = rnd.add_project("P", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    assert len(eh.list_efforts(folder, pid, "planning")) == 1

    # Delete the planning artifact on disk, rescan + adopt.
    (folder / "planning" / "MASTER-PLAN.md").unlink()
    rep = eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    assert rep["pruned"] == 1
    assert eh.list_efforts(folder, pid, "planning") == []


def test_reconcile_prunes_without_rescan(mods, tmp_path):
    eh, rnd = mods
    folder = tmp_path / "proj"
    _seed_brownfield(folder)
    proj = rnd.add_project("P", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    (folder / "research" / "s" / "report.md").unlink()
    rep = eh.reconcile_discovered(folder, pid)
    assert rep["pruned"] == 1
    assert all(not eh.is_discovered(r)
               for r in eh.list_efforts(folder, pid, "research"))


def test_reconcile_never_prunes_real_efforts(mods, tmp_path):
    eh, rnd = mods
    folder = tmp_path / "proj"
    folder.mkdir(parents=True)
    proj = rnd.add_project("P", str(folder))
    pid = proj["id"]
    # A real effort with no on-disk artifact_path — must survive reconcile.
    eh.record_effort(folder, pid, "research", "real1", skill="researchPrime")
    eh.reconcile_discovered(folder, pid)
    survivors = eh.list_efforts(folder, pid, "research")
    assert len(survivors) == 1
    assert survivors[0]["job_id"] == "real1"


def test_discovered_job_id_is_stable(mods):
    eh, _ = mods
    a = eh.discovered_job_id("research", "research/s/report.md")
    b = eh.discovered_job_id("research", "research/s/report.md")
    c = eh.discovered_job_id("research", "research/s/other.md")
    assert a == b
    assert a != c
    assert a.startswith("disc-")


def test_sibling_store_adoption_pulls_other_id_same_folder(mods, tmp_path):
    """Wave 2 sibling adoption: a real effort recorded under a SIBLING project-id
    for the same folder is pulled into the target id as an imported effort."""
    eh, rnd = mods
    folder = tmp_path / "proj"
    folder.mkdir()
    target = rnd.add_project("Anchor", str(folder))["id"]
    sib = rnd.add_project("Anchor", str(folder))["id"]

    # A real research run lives ONLY under the sibling's store.
    eh.record_effort(folder, sib, "research", "sib1", skill="researchPrime",
                     extra={"title": "sibling report"})
    eh.finalize_effort(folder, sib, "research", "sib1",
                       {"status": "done", "cost": {"total_cost_usd": 0.05}},
                       auto_commit=False)
    assert eh.list_efforts(folder, target, "research") == []

    rep = eh.adopt_sibling_sessions(folder, target)
    assert rep["imported"] == 1
    got = eh.list_efforts(folder, target, "research")
    assert len(got) == 1
    assert got[0]["title"] == "sibling report"
    # Folded-in history is imported (not double-counted as a real run-cost).
    assert eh.is_discovered(got[0])
    # Honest rollup: the target's real effort_count stays 0 (imported only).
    assert eh.lane_rollup(folder, target, "research")["effort_count"] == 0
    assert eh.lane_rollup(folder, target, "research")["discovered_count"] == 1

"""Wave 2 — folder-history unification: sibling adoption + reconcile_folder.

Proves IMPLEMENTATION-PLAN.md "## Wave 2":

- SIBLING-STORE ADOPTION: a trio run recorded under one project-id's store for a
  folder is pulled into a sibling project-id for the SAME folder as an imported
  effort (``effort_history.adopt_sibling_sessions`` / wired into rescan).
- ``reconcile_folder(active_id)`` is EXPLICIT + REVIEWABLE:
    * preview (apply=False) reports the plan WITHOUT mutating,
    * apply (apply=True) folds retired siblings' REAL sessions into the active id
      then HARD-DELETES the folded sibling ids.
- G/W/T: Given 3 retired + 1 active same-folder ids, When reconcile_folder is
  applied, Then the retired ids' real sessions are present under the active id
  AND the retired ids are absent from the registry; the registry contains
  exactly ONE project for that folder.
- A DIFFERENT-folder id (the "BF Test" temp-folder case) is NEVER folded/deleted
  by reconcile_folder for the Anchor folder.

Hermetic: temp ANCHOR_DATA_DIR + temp folders (conftest pattern). NEVER touches
the live .anchor or live registry.
"""
import importlib

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
    return rnd_registry, effort_history


@pytest.fixture
def mods_full(tmp_path, monkeypatch):
    """Like ``mods`` but also reloads sessions + deliverables for the headline
    end-to-end acceptance (sibling adoption → research session + pinned
    deliverable + exactly-one-id)."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import job_runner
    importlib.reload(job_runner)
    import report_viewer
    importlib.reload(report_viewer)
    import deliverables
    importlib.reload(deliverables)
    return rnd_registry, effort_history, sessions, deliverables


def _seed_real_effort(eh, folder, pid, lane, jid, *, skill="researchPrime",
                      cost=0.01, **extra):
    """Record a REAL (run) effort in ``lane`` and stamp cost on it."""
    eh.record_effort(folder, pid, lane, jid, skill=skill, extra=extra)
    eh.finalize_effort(folder, pid, lane, jid,
                       {"status": "done",
                        "cost": {"total_cost_usd": cost, "total_tokens": 100}},
                       auto_commit=False)


def _mirror_3_retired_plus_active(rnd, eh, folder, other_folder):
    """Build the live-shaped fixture: 3 retired same-folder siblings + 1 active,
    plus 1 unrelated different-folder id. Returns the registry ids by role."""
    folder.mkdir(parents=True, exist_ok=True)
    other_folder.mkdir(parents=True, exist_ok=True)

    # active id (the live "Anchor")
    active = rnd.add_project("Anchor", str(folder), priority=1)
    aid = active["id"]

    # Retired sibling holding the REAL researchPrime report (227eb08… analog).
    sib_research = rnd.add_project("Anchor", str(folder), priority=1)
    rid = sib_research["id"]
    rnd.retire_project(rid)
    _seed_real_effort(eh, str(folder), rid, "research", "researchPrime-real",
                      skill="researchPrime", title="researchPrime report",
                      artifact_path="research/report.md")

    # Retired sibling holding a real planning run (bfe0e75… analog).
    sib_plan = rnd.add_project("Anchor", str(folder), priority=2)
    pid2 = sib_plan["id"]
    rnd.retire_project(pid2)
    _seed_real_effort(eh, str(folder), pid2, "planning", "plan-real",
                      skill="crucible", title="Master Plan")

    # Third retired same-folder sibling, holding nothing (empty duplicate).
    sib_empty = rnd.add_project("Anchor", str(folder), priority=2)
    eid = sib_empty["id"]
    rnd.retire_project(eid)

    # UNRELATED id on a DIFFERENT folder (the "BF Test" temp-folder case).
    bf = rnd.add_project("BF Test", str(other_folder), priority=2)
    bf_id = bf["id"]
    rnd.retire_project(bf_id)
    _seed_real_effort(eh, str(other_folder), bf_id, "research", "bf-real",
                      title="BF report")

    return {"active": aid, "research": rid, "plan": pid2, "empty": eid,
            "bf": bf_id}


# ── sibling adoption ─────────────────────────────────────────────────────────

def test_adopt_sibling_sessions_pulls_same_folder_efforts(mods, tmp_path):
    rnd, eh = mods
    folder = tmp_path / "proj"
    folder.mkdir()
    active = rnd.add_project("Anchor", str(folder))
    sib = rnd.add_project("Anchor", str(folder))
    aid, sid = active["id"], sib["id"]

    # A real research effort lives ONLY under the sibling id's store.
    _seed_real_effort(eh, str(folder), sid, "research", "r1",
                      title="sibling report", artifact_path="research/r.md")
    # The active id sees nothing yet.
    assert eh.list_efforts(str(folder), aid, "research") == []

    rep = eh.adopt_sibling_sessions(str(folder), aid)
    assert rep["imported"] == 1
    assert sid in rep["from"]

    # Now the active id SEES the sibling's research effort (as imported).
    got = eh.list_efforts(str(folder), aid, "research")
    assert len(got) == 1
    assert got[0]["title"] == "sibling report"
    assert eh.is_discovered(got[0])  # imported → excluded from real-cost rollup


def test_sibling_store_ids_finds_same_folder_stores(mods, tmp_path):
    rnd, eh = mods
    folder = tmp_path / "proj"
    folder.mkdir()
    a = rnd.add_project("A", str(folder))["id"]
    b = rnd.add_project("B", str(folder))["id"]
    c = rnd.add_project("C", str(folder))["id"]
    ids = eh.sibling_store_ids(str(folder), exclude_id=a)
    assert set(ids) == {b, c}
    assert a not in ids


def test_adopt_sibling_sessions_is_idempotent(mods, tmp_path):
    rnd, eh = mods
    folder = tmp_path / "proj"
    folder.mkdir()
    aid = rnd.add_project("Anchor", str(folder))["id"]
    sid = rnd.add_project("Anchor", str(folder))["id"]
    _seed_real_effort(eh, str(folder), sid, "build", "b1", title="build")
    eh.adopt_sibling_sessions(str(folder), aid)
    n1 = len(eh.list_efforts(str(folder), aid, "build"))
    eh.adopt_sibling_sessions(str(folder), aid)
    n2 = len(eh.list_efforts(str(folder), aid, "build"))
    assert n1 == n2 == 1


def test_adopt_sibling_blank_job_id_fallback_is_idempotent(mods, tmp_path):
    """Exercise the fallback-job_id import path: a sibling REAL effort whose
    on-disk job_id is blank must still import (via the stable identity-hash
    fallback in ``_import_record_into``) and importing it a SECOND time must NOT
    create a duplicate — idempotent on the hash fallback, not just on job_id."""
    rnd, eh = mods
    folder = tmp_path / "proj"
    folder.mkdir()
    aid = rnd.add_project("Anchor", str(folder))["id"]
    sid = rnd.add_project("Anchor", str(folder))["id"]

    # A real research effort under the sibling id.
    _seed_real_effort(eh, str(folder), sid, "research", "r1",
                      title="blanked report", artifact_path="research/r.md")

    # Blank the recorded job_id ON DISK (simulates a legacy/corrupt pointer
    # whose id field is empty) so adoption must use the identity-hash fallback.
    ppath = eh._pointer_path(str(folder), sid, "research", "r1")
    import json as _json
    rec = _json.loads(ppath.read_text(encoding="utf-8"))
    rec["job_id"] = ""
    ppath.write_text(_json.dumps(rec), encoding="utf-8")

    # First adoption: the blank-id sibling effort folds into the active id.
    eh.adopt_sibling_sessions(str(folder), aid)
    got1 = eh.list_efforts(str(folder), aid, "research")
    assert len(got1) == 1
    assert got1[0]["title"] == "blanked report"
    # It landed under a stable hash-fallback id (disc-sib-…), not the empty id.
    assert got1[0]["job_id"].startswith(eh.DISCOVERED_PREFIX + "sib-")

    # SECOND adoption: must be idempotent — no duplicate via the stable hash.
    eh.adopt_sibling_sessions(str(folder), aid)
    got2 = eh.list_efforts(str(folder), aid, "research")
    assert len(got2) == 1


# ── reconcile_folder: preview then apply ──────────────────────────────────────

def test_reconcile_preview_does_not_mutate(mods, tmp_path):
    rnd, eh = mods
    ids = _mirror_3_retired_plus_active(rnd, eh,
                                        tmp_path / "Anchor", tmp_path / "bf")
    aid = ids["active"]

    before = set(rnd.load_registry().keys())
    plan = rnd.reconcile_folder(aid, apply=False)
    after = set(rnd.load_registry().keys())

    assert plan["ok"] is True
    assert plan["applied"] is False
    # Registry untouched by the preview.
    assert before == after
    # The plan folds exactly the 3 SAME-folder retired siblings (not the BF id).
    fold_ids = {f["id"] for f in plan["fold"]}
    assert fold_ids == {ids["research"], ids["plan"], ids["empty"]}
    assert ids["bf"] not in fold_ids
    assert set(plan["to_delete"]) == fold_ids
    # Effort counts are reported per sibling in the preview.
    by_id = {f["id"]: f for f in plan["fold"]}
    assert by_id[ids["research"]]["efforts"].get("research") == 1
    assert by_id[ids["plan"]]["efforts"].get("planning") == 1
    assert by_id[ids["empty"]]["total_efforts"] == 0
    # No sibling adoption happened during preview.
    assert eh.list_efforts(str(tmp_path / "Anchor"), aid, "research") == []


def test_reconcile_apply_folds_then_hard_deletes(mods, tmp_path):
    rnd, eh = mods
    folder = tmp_path / "Anchor"
    ids = _mirror_3_retired_plus_active(rnd, eh, folder, tmp_path / "bf")
    aid = ids["active"]

    res = rnd.reconcile_folder(aid, apply=True)
    assert res["ok"] is True and res["applied"] is True

    # G/W/T: retired ids' real sessions are now present under the active id.
    research = eh.list_efforts(str(folder), aid, "research")
    planning = eh.list_efforts(str(folder), aid, "planning")
    assert any(r.get("title") == "researchPrime report" for r in research)
    assert any(p.get("title") == "Master Plan" for p in planning)

    # G/W/T: the retired ids are ABSENT from the registry (hard-deleted).
    reg = rnd.load_registry()
    for sid in (ids["research"], ids["plan"], ids["empty"]):
        assert sid not in reg
    assert set(res["deleted"]) == {ids["research"], ids["plan"], ids["empty"]}

    # Exactly ONE project remains for the Anchor folder.
    anchor_ids = [e["id"] for e in reg.values()
                  if e["folder_path"] == str(folder)]
    assert anchor_ids == [aid]


def test_reconcile_apply_folds_grass_ideas_not_lost(mods, tmp_path):
    """Wave 5 fix: the destructive fold-then-hard-delete must FOLD grass-lane
    ideas too — otherwise a sibling's manually-added / adopted grass ideas are
    silently destroyed when the sibling id is hard-deleted.

    G/W/T: a retired same-folder sibling holds a grass idea (and a real research
    effort). When reconcile_folder(active, apply=True), Then the grass idea is
    PRESENT under the active id (folded) AND the sibling id is gone. The cost
    rollup for the active id must NOT have gained any cost from the grass idea
    (grass is excluded from the cost rollup by design)."""
    rnd, eh = mods
    folder = tmp_path / "Anchor"
    folder.mkdir()

    active = rnd.add_project("Anchor", str(folder), priority=1)
    aid = active["id"]

    # Retired same-folder sibling: a manually-added grass IDEA + a real (cost-
    # bearing) research effort, so we can prove grass folds AND cost stays honest.
    sib = rnd.add_project("Anchor", str(folder), priority=1)
    sid = sib["id"]
    rnd.retire_project(sid)
    idea = eh.add_idea(str(folder), sid, "explore tritium recovery",
                       notes="from brainstorm")
    idea_jid = idea["job_id"]
    _seed_real_effort(eh, str(folder), sid, "research", "r-real",
                      title="sibling research", cost=0.05)

    # Sanity: active sees no grass yet.
    assert eh.list_efforts(str(folder), aid, "grass") == []

    # Preview must already account for the grass lane in the fold plan.
    plan = rnd.reconcile_folder(aid, apply=False)
    by_id = {f["id"]: f for f in plan["fold"]}
    assert by_id[sid]["efforts"].get("grass") == 1

    res = rnd.reconcile_folder(aid, apply=True)
    assert res["ok"] is True and res["applied"] is True

    # The grass idea is now PRESENT under the active id (folded, never lost).
    grass = eh.list_efforts(str(folder), aid, "grass")
    assert len(grass) == 1
    assert grass[0]["title"] == "explore tritium recovery"
    # Imported grass keeps its provenance honest (folded → source=discovered).
    assert eh.is_discovered(grass[0])
    assert grass[0].get("imported_from") == sid
    # The grass fold is reflected in the apply report's by-lane counts.
    assert res["imported_by_lane"].get("grass") == 1

    # The sibling id is hard-deleted; exactly one Anchor id remains.
    reg = rnd.load_registry()
    assert sid not in reg
    anchor_ids = [e["id"] for e in reg.values()
                  if e["folder_path"] == str(folder)]
    assert anchor_ids == [aid]

    # COST HONESTY: the cost rollup never includes the grass lane, and the
    # folded grass idea fabricates NO cost. (Folded efforts become
    # source=discovered, so they're excluded from the real-cost rollup — see the
    # honesty contract; the rollup therefore stays $0.00 and grass contributes
    # nothing.)
    rollup = eh.project_rollup(aid, folder_path=str(folder))
    assert "grass" not in rollup["lanes"]            # rollup never includes grass
    assert set(rollup["lanes"]) == set(eh.ROLLUP_LANES)
    assert rollup["total"]["total_cost_usd"] == pytest.approx(0.0)


def test_reconcile_never_touches_different_folder_id(mods, tmp_path):
    rnd, eh = mods
    folder = tmp_path / "Anchor"
    other = tmp_path / "bf"
    ids = _mirror_3_retired_plus_active(rnd, eh, folder, other)
    aid = ids["active"]

    rnd.reconcile_folder(aid, apply=True)

    reg = rnd.load_registry()
    # The unrelated BF Test id (different folder) survives untouched.
    assert ids["bf"] in reg
    assert reg[ids["bf"]]["folder_path"] == str(other)
    # Its real effort is still under ITS OWN store, NOT folded into active.
    assert len(eh.list_efforts(str(other), ids["bf"], "research")) == 1
    active_research = eh.list_efforts(str(folder), aid, "research")
    assert all(r.get("title") != "BF report" for r in active_research)


def test_reconcile_unknown_active_is_clean(mods, tmp_path):
    rnd, _ = mods
    res = rnd.reconcile_folder("nope-not-an-id", apply=False)
    assert res["ok"] is False
    assert res["reason"] == "unknown-active"


def test_reconcile_apply_then_registry_has_exactly_one(mods, tmp_path):
    """The headline acceptance: 3 retired + 1 active same-folder → 1 id after."""
    rnd, eh = mods
    folder = tmp_path / "Anchor"
    ids = _mirror_3_retired_plus_active(rnd, eh, folder, tmp_path / "bf")
    rnd.reconcile_folder(ids["active"], apply=True)
    reg = rnd.load_registry()
    same_folder = [e for e in reg.values() if e["folder_path"] == str(folder)]
    assert len(same_folder) == 1
    assert same_folder[0]["id"] == ids["active"]


def test_headline_acceptance_research_session_plus_pinned_deliverable(
        mods_full, tmp_path):
    """Done-when (IMPLEMENTATION-PLAN Wave 2): after reconcile + a pin, the
    active Anchor project shows the researchPrime report as a RESEARCH session,
    anchor_gui.py (pinned) appears as a DELIVERABLE, and the registry contains
    exactly ONE project for that folder."""
    rnd, eh, sessions, deliv = mods_full
    folder = tmp_path / "Anchor"
    ids = _mirror_3_retired_plus_active(rnd, eh, folder, tmp_path / "bf")
    aid = ids["active"]
    (folder / "anchor_gui.py").write_text("print('app')\n", encoding="utf-8")

    # Reconcile folds the retired siblings' real sessions into the active id and
    # hard-deletes them.
    rnd.reconcile_folder(aid, apply=True)
    # Pin the running web app as a deliverable (declare/pin path).
    deliv.pin_deliverable(str(folder), aid, "anchor_gui.py")

    # researchPrime report shows up as a RESEARCH session under the active id.
    research_sessions = sessions.list_sessions(str(folder), aid, "research")
    assert any("researchPrime report" == s["title"]
               or any(m.get("title") == "researchPrime report"
                      for m in s["member_files"])
               for s in research_sessions)

    # anchor_gui.py appears as a pinned DELIVERABLE.
    pinned = deliv.list_pinned_deliverables(str(folder), aid)
    assert any(p["artifact_path"] == "anchor_gui.py" for p in pinned)

    # The registry contains exactly ONE Anchor id for that folder.
    reg = rnd.load_registry()
    anchor_ids = [e["id"] for e in reg.values()
                  if e["folder_path"] == str(folder)]
    assert anchor_ids == [aid]

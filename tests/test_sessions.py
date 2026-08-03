"""Wave 1 (R&D v2) — session model + grouping (sessions.py).

Proves IMPLEMENTATION-PLAN.md "## Wave 1":

G/W/T: Given 7 discovered planning files across 2 parent dirs, when
  list_sessions(folder, active_id, "plan"), then 2 session records are returned
  newest-first and every source file appears in exactly one session's
  member_files.

All tests are HERMETIC: a temp store is built via effort_history's own API under
a tmp ANCHOR_DATA_DIR — never the live .anchor store. Mirrors the established
fixture pattern in tests/test_history.py / tests/test_brownfield_adopt.py.
"""
import importlib

import pytest

#: The active project id from the frozen Conventions block.
ACTIVE_ID = "2fe37f39157f4c7aa3e2523baa41f40f"


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    return effort_history, rnd_registry, sessions


def _project(rnd, tmp_path, name="Anchor"):
    folder = tmp_path / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    return rnd.add_project(name, str(folder))


def _record_discovered(eh, folder, pid, lane, rel, *, kind="plan",
                       title="", created_at=None, skill="crucible"):
    """Record one DISCOVERED effort pointer-record (hermetic fixture builder)."""
    jid = eh.discovered_job_id(lane, rel)
    extra = {
        "source": eh.SOURCE_DISCOVERED,
        "kind": kind,
        "title": title or rel.rsplit("/", 1)[-1],
        "artifact_path": rel,
        "status": "imported",
        "skill": skill,
    }
    eh.record_effort(folder, pid, lane, jid, extra=extra)
    if created_at is not None:
        eh._set_created_at(folder, pid, lane, jid, float(created_at))
    return jid


# ── Acceptance: 7 discovered planning files / 2 parent dirs → 2 sessions ─────

def test_discovered_planning_groups_into_two_sessions(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID

    # brownfield-discovery: 3 files (older). rnd-v1: 4 files (newer).
    bd_files = [
        "planning/brownfield-discovery/MASTER-PLAN.md",
        "planning/brownfield-discovery/IMPLEMENTATION-PLAN.md",
        "planning/brownfield-discovery/EXECUTION-LOG.md",
    ]
    v1_files = [
        "planning/rnd-v1/MASTER-PLAN.md",
        "planning/rnd-v1/IMPLEMENTATION-PLAN.md",
        "planning/rnd-v1/EXECUTION-LOG.md",
        "planning/rnd-v1/NOTES.md",
    ]
    base = 1_700_000_000.0
    for i, rel in enumerate(bd_files):
        _record_discovered(eh, folder, pid, "plan", rel,
                            kind=("master" if "MASTER" in rel else "plan"),
                            created_at=base + i)
    for i, rel in enumerate(v1_files):
        _record_discovered(eh, folder, pid, "plan", rel,
                            kind=("master" if "MASTER" in rel else "plan"),
                            created_at=base + 1000 + i)

    sessions = sx.list_sessions(folder, pid, "plan")

    # Exactly 2 sessions.
    assert len(sessions) == 2

    # Newest-first: rnd-v1 (newer) sorts strictly before brownfield-discovery.
    assert sessions[0]["timestamp"] > sessions[1]["timestamp"]

    # Every source file appears in exactly one session's member_files.
    all_rels = []
    for s in sessions:
        for m in s["member_files"]:
            all_rels.append(m["artifact_path"])
    assert sorted(all_rels) == sorted(bd_files + v1_files)
    assert len(all_rels) == len(set(all_rels))  # no duplicates

    # Each session carries its full membership.
    by_count = sorted(len(s["member_files"]) for s in sessions)
    assert by_count == [3, 4]

    # Both are imported provenance.
    assert all(s["provenance"] == "imported" for s in sessions)

    # Title prefers a master-plan-like member.
    for s in sessions:
        assert s["title"] == "MASTER-PLAN.md"


def test_session_lane_aliases_plan_and_planning(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID
    _record_discovered(eh, folder, pid, "plan",
                       "planning/x/MASTER-PLAN.md", kind="master",
                       created_at=1_700_000_000.0)
    # Either lane name resolves to the same store subdir / sessions.
    assert len(sx.list_sessions(folder, pid, "plan")) == 1
    assert len(sx.list_sessions(folder, pid, "planning")) == 1
    assert sx.list_sessions(folder, pid, "planning")[0]["lane"] == "planning"


# ── Run efforts: one session per job_id ──────────────────────────────────────

def test_run_efforts_one_session_per_job_id(mods, tmp_path):
    eh, rnd, sx = mods
    proj = _project(rnd, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]

    for jid in ("j1", "j2", "j3"):
        eh.record_effort(folder, pid, "build", jid, skill="foreman")

    sessions = sx.list_sessions(folder, pid, "build")
    assert len(sessions) == 3
    # newest-first (j3 recorded last).
    assert [m["job_id"] for s in sessions for m in s["member_files"]][0] == "j3"
    # each session = one effort, run provenance.
    for s in sessions:
        assert len(s["member_files"]) == 1
        assert s["provenance"] == "run"
    # session_ids are job_id-derived and unique.
    sids = {s["session_id"] for s in sessions}
    assert len(sids) == 3


def test_run_efforts_with_empty_job_id_each_get_own_session(mods, tmp_path):
    """FIX 2: two distinct RUN efforts with a missing/empty job_id must NOT
    collapse into a single ("run", "") session — one run effort = one session.
    Session ids must be STABLE across repeated list_sessions calls."""
    import json
    eh, rnd, sx = mods
    proj = _project(rnd, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]

    # Record two real run efforts under distinct pointer files...
    eh.record_effort(folder, pid, "build", "rj1", skill="foreman")
    eh.record_effort(folder, pid, "build", "rj2", skill="foreman")
    eh._set_created_at(folder, pid, "build", "rj1", 1_700_000_000.0)
    eh._set_created_at(folder, pid, "build", "rj2", 1_700_000_010.0)
    # ...then blank out the job_id *field* on each on-disk record (the index
    # still tracks them by filename, but the records themselves carry "" job_id).
    for jid in ("rj1", "rj2"):
        p = eh._pointer_path(folder, pid, "build", jid)
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["job_id"] = ""
        p.write_text(json.dumps(rec), encoding="utf-8")

    sessions = sx.list_sessions(folder, pid, "build")
    # Two distinct empty-job_id run efforts → two sessions (not one collapsed).
    assert len(sessions) == 2
    for s in sessions:
        assert len(s["member_files"]) == 1
        assert s["provenance"] == "run"
    ids1 = sorted(s["session_id"] for s in sessions)
    assert len(set(ids1)) == 2

    # Session ids are STABLE across a second call (Wave 6 cache-keying needs this).
    sessions2 = sx.list_sessions(folder, pid, "build")
    ids2 = sorted(s["session_id"] for s in sessions2)
    assert ids1 == ids2


# ── Fallback: flat discovered files cluster by skill + timestamp window ──────

def test_fallback_cluster_by_skill_and_timestamp(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID

    # Top-level (no parent dir) discovered files, same skill.
    # Two close in time (one cluster) + one far away (separate cluster).
    base = 1_700_000_000.0
    _record_discovered(eh, folder, pid, "research", "a.md",
                       created_at=base, skill="researchPrime")
    _record_discovered(eh, folder, pid, "research", "b.md",
                       created_at=base + 60, skill="researchPrime")
    _record_discovered(eh, folder, pid, "research", "c.md",
                       created_at=base + 100000, skill="researchPrime")

    sessions = sx.list_sessions(folder, pid, "research", cluster_window_s=3600)
    # Two clusters: {a,b} together, {c} alone.
    assert len(sessions) == 2
    sizes = sorted(len(s["member_files"]) for s in sessions)
    assert sizes == [1, 2]
    # Newest-first: the lone 'c' (latest ts) comes first.
    assert sessions[0]["member_files"][0]["artifact_path"] == "c.md"


def test_fallback_separates_distinct_skills(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID
    base = 1_700_000_000.0
    _record_discovered(eh, folder, pid, "research", "a.md",
                       created_at=base, skill="researchPrime")
    _record_discovered(eh, folder, pid, "research", "b.md",
                       created_at=base + 10, skill="other-skill")
    sessions = sx.list_sessions(folder, pid, "research")
    # Different skills never cluster together even within the window.
    assert len(sessions) == 2


# ── Empty lane ───────────────────────────────────────────────────────────────

def test_empty_lane_returns_empty(mods, tmp_path):
    eh, rnd, sx = mods
    proj = _project(rnd, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]
    assert sx.list_sessions(folder, pid, "research") == []
    assert sx.list_sessions(folder, pid, "plan") == []


# ── merge_sessions escape hatch ──────────────────────────────────────────────

def test_merge_sessions_folds_two_into_one(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID
    base = 1_700_000_000.0
    _record_discovered(eh, folder, pid, "plan", "planning/aa/MASTER-PLAN.md",
                       kind="master", created_at=base)
    _record_discovered(eh, folder, pid, "plan", "planning/bb/MASTER-PLAN.md",
                       kind="master", created_at=base + 5)

    sessions = sx.list_sessions(folder, pid, "plan")
    assert len(sessions) == 2
    ids = [s["session_id"] for s in sessions]

    merged = sx.merge_sessions(folder, pid, "plan", ids)
    assert merged is not None
    after = sx.list_sessions(folder, pid, "plan")
    assert len(after) == 1
    assert len(after[0]["member_files"]) == 2
    # Override persisted to the sidecar.
    assert sx._overrides_path(folder, pid, "plan").exists()

    # Re-reading is stable (still one merged session).
    assert len(sx.list_sessions(folder, pid, "plan")) == 1


def test_merge_sessions_needs_two_ids(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID
    assert sx.merge_sessions(folder, pid, "plan", ["only-one"]) is None
    assert sx.merge_sessions(folder, pid, "plan", []) is None


# ── split_session escape hatch ───────────────────────────────────────────────

def test_split_session_separates_members(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID
    base = 1_700_000_000.0
    # Two files under one parent dir → one computed session.
    j1 = _record_discovered(eh, folder, pid, "plan",
                            "planning/mix/MASTER-PLAN.md",
                            kind="master", created_at=base)
    j2 = _record_discovered(eh, folder, pid, "plan",
                            "planning/mix/STRAY.md",
                            kind="note", created_at=base + 5)

    sessions = sx.list_sessions(folder, pid, "plan")
    assert len(sessions) == 1
    src_sid = sessions[0]["session_id"]
    assert len(sessions[0]["member_files"]) == 2

    # Split j2 out into its own session.
    after = sx.split_session(folder, pid, "plan", src_sid,
                             {j2: "split-stray"})
    assert len(after) == 2
    sizes = sorted(len(s["member_files"]) for s in after)
    assert sizes == [1, 1]
    # The split member landed under the requested new session id.
    new_sess = [s for s in after if s["session_id"] == "split-stray"]
    assert len(new_sess) == 1
    assert new_sess[0]["member_files"][0]["job_id"] == j2
    # And j1 remains in the original.
    orig = [s for s in after if s["session_id"] == src_sid]
    assert orig and orig[0]["member_files"][0]["job_id"] == j1


def test_split_session_noop_without_grouping(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID
    _record_discovered(eh, folder, pid, "plan", "planning/z/MASTER-PLAN.md",
                       kind="master", created_at=1_700_000_000.0)
    before = sx.list_sessions(folder, pid, "plan")
    after = sx.split_session(folder, pid, "plan", "whatever", {})
    assert len(after) == len(before) == 1


# ── Mixed run + discovered in one lane ───────────────────────────────────────

def test_mixed_run_and_discovered_sessions(mods, tmp_path):
    eh, rnd, sx = mods
    folder = (tmp_path / "proj")
    folder.mkdir(parents=True, exist_ok=True)
    pid = ACTIVE_ID
    base = 1_700_000_000.0
    # 3 discovered files in one dir + one real run effort.
    for i, rel in enumerate(["planning/old/MASTER-PLAN.md",
                             "planning/old/IMPLEMENTATION-PLAN.md",
                             "planning/old/EXECUTION-LOG.md"]):
        _record_discovered(eh, folder, pid, "plan", rel,
                           kind=("master" if "MASTER" in rel else "plan"),
                           created_at=base + i)
    eh.record_effort(folder, pid, "plan", "runjob", skill="crucible")
    eh._set_created_at(folder, pid, "plan", "runjob", base + 9999)

    sessions = sx.list_sessions(folder, pid, "plan")
    # One imported session (3 files) + one run session (1 file).
    assert len(sessions) == 2
    run = [s for s in sessions if s["provenance"] == "run"]
    imp = [s for s in sessions if s["provenance"] == "imported"]
    assert len(run) == 1 and len(imp) == 1
    assert len(imp[0]["member_files"]) == 3
    # The run session is newest.
    assert sessions[0]["provenance"] == "run"

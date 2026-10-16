"""v12 Wave 4 — Keystone B: stage-keyed summaries + schema heal + closed-stage
read via ``store_lane``.

Each stage of ONE effort/session gets its OWN cached summary, keyed
``(session, stage)`` and stored under ``<store_lane>/summaries/<sid>/<stage>/``.
After the effort's ``lane`` flips to a later stage, a CLOSED stage's summary must
still resolve via the stage's recorded ``store_lane`` (Wave 1
``stage_history``) — NOT the record's current ``lane``. A pre-bump
(``SCHEMA_VERSION<3``) single-key cache at the OLD path is a MISS (heals). And
the ``stage=None`` path must be byte-identical to the legacy behavior so every
existing summarizer caller stays green.

Frozen plan: ``planning/rnd-v12/IMPLEMENTATION-PLAN.md`` "## Wave 4";
``MASTER-PLAN.md`` §4.2.

Hermetic: temp ANCHOR_DATA_DIR, the stream-json STUB runner (NO live claude),
never :8777, ``ANCHOR_PROACTIVE_SUMMARY`` off. Stdlib only.
"""
import importlib
import json
from pathlib import Path

import pytest

STREAMJSON = (Path(__file__).resolve().parent / "stub_streamjson.py").as_posix()


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STREAMJSON}")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "0")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "effort_history",
                "session_registry", "sessions", "report_viewer", "summarizer"):
        importlib.reload(importlib.import_module(mod))
    import job_runner, effort_history, rnd_registry, session_registry, summarizer
    yield (job_runner, effort_history, rnd_registry, session_registry,
           summarizer)
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


def _project(rnd, folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "CLAUDE.md").write_text("# Proj\n", encoding="utf-8")
    return rnd.add_project("Proj", str(folder))["id"]


def _write_doc(folder, rel, text):
    p = Path(folder) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return rel


def _session(sid, lane, members):
    """A session dict shaped exactly like ``sessions.list_sessions`` output for
    the summarizer's extraction seed (it only reads session_id + member_files)."""
    return {"session_id": sid, "lane": lane, "title": f"{lane} session",
            "provenance": "run", "member_files": members}


def _member(rel, title):
    return {"job_id": "", "title": title, "artifact_path": rel}


# ── GWT 1 — two stages cache under distinct store_lane/<sid>/<stage> dirs ─────

def test_two_stages_distinct_dirs_no_collision(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sr, summ = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)
    sid = "EFFORT-1"

    # Research stage produced a research doc; plan stage a planning doc — both in
    # the SAME effort/session id, different store lanes.
    rrel = _write_doc(folder, "research/r.md",
                      "# Research\n\n## Findings\n"
                      "Investigated the calendar sync question thoroughly.\n")
    prel = _write_doc(folder, "planning/MASTER-PLAN.md",
                      "# Master Plan\n\n## North Star\n"
                      "Deliver the durable efforts dashboard for the trio.\n")

    research_sess = _session(sid, "research", [_member(rrel, "research report")])
    plan_sess = _session(sid, "planning", [_member(prel, "master plan")])

    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       "Investigated the calendar sync question thoroughly.")
    r_out = summ.summarize_session(str(folder), pid, "research", research_sess,
                                   stage="research")
    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       "Deliver the durable efforts dashboard for the trio.")
    p_out = summ.summarize_session(str(folder), pid, "planning", plan_sess,
                                   stage="plan")

    # Distinct on-disk cache dirs: <store_lane>/summaries/<sid>/<stage>/
    r_dir = summ.summary_dir(str(folder), pid, "research", sid, stage="research")
    p_dir = summ.summary_dir(str(folder), pid, "planning", sid, stage="plan")
    assert r_dir != p_dir
    assert r_dir.name == "research" and r_dir.parent.name == "EFFORT-1"
    assert p_dir.name == "plan" and p_dir.parent.name == "EFFORT-1"
    assert "research" in r_dir.parts and "summaries" in r_dir.parts
    assert "planning" in p_dir.parts and "summaries" in p_dir.parts
    assert (r_dir / summ.SUMMARY_JSON).is_file()
    assert (p_dir / summ.SUMMARY_JSON).is_file()

    # load_cached(stage=...) resolves BOTH, and they do NOT collide.
    r_cached = summ.load_cached(str(folder), pid, "research", sid,
                                stage="research")
    p_cached = summ.load_cached(str(folder), pid, "planning", sid, stage="plan")
    assert r_cached is not None and p_cached is not None
    assert r_cached != p_cached
    assert r_cached["claims"] and p_cached["claims"]
    assert "calendar sync" in " ".join(r_cached["claims"]).lower()
    assert "efforts dashboard" in " ".join(p_cached["claims"]).lower()
    assert r_cached.get("stage") == "research"
    assert p_cached.get("stage") == "plan"


# ── GWT 2 — closed stage resolves via store_lane AFTER lane flipped ──────────

def test_closed_stage_resolves_via_store_lane_after_lane_flip(
        mods, tmp_path, monkeypatch):
    jr, eh, rnd, sr, summ = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)
    sid = "EFFORT-2"

    rrel = _write_doc(folder, "research/r.md",
                      "# Research\n\n## Findings\n"
                      "Discovered the worktree isolation approach works well.\n")
    research_sess = _session(sid, "research",
                             [_member(rrel, "research report")])

    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       "Discovered the worktree isolation approach works well.")
    summ.summarize_session(str(folder), pid, "research", research_sess,
                           stage="research")

    # Now register the effort and walk it through the stages via the Wave-1
    # machinery so its CURRENT lane FLIPS to build, while the research stage's
    # entry retains store_lane='research'.
    sr.register_session(pid, "research", session_id=sid, effort_id=sid,
                        effort_managed=True, status="running")
    sr.set_current_stage(sid, "research", "research", "b0")
    sr.set_current_stage(sid, "plan", "planning", "b1")
    sr.set_current_stage(sid, "build", "build", "b2")
    record = sr.load_sessions()[sid]
    assert record["lane"] == "build" and record["current_stage"] == "build"

    # The closed-stage read MUST resolve via store_lane, not the current lane.
    research_store_lane = summ.stage_store_lane(record, "research")
    assert research_store_lane == "research"

    resolved = summ.load_cached(str(folder), pid, research_store_lane, sid,
                                stage="research")
    assert resolved is not None
    assert "worktree isolation" in " ".join(resolved["claims"]).lower()

    # Using the CURRENT lane ('build') would NOT find the research summary — this
    # is exactly the bug Wave 4 fixes (the cache lives under research, not build).
    via_current_lane = summ.load_cached(str(folder), pid, record["lane"], sid,
                                        stage="research")
    assert via_current_lane is None

    # And the plan stage (no summary written) is honestly a MISS, distinct from
    # research (no collision across stages).
    plan_store_lane = summ.stage_store_lane(record, "plan")
    assert plan_store_lane == "planning"
    assert summ.load_cached(str(folder), pid, plan_store_lane, sid,
                            stage="plan") is None
    assert (summ.load_cached(str(folder), pid, research_store_lane, sid,
                             stage="research")
            != summ.load_cached(str(folder), pid, plan_store_lane, sid,
                                stage="plan"))


# ── GWT 3 — a pre-bump (SCHEMA_VERSION<3) single-key cache is a MISS ─────────

def test_pre_bump_single_key_cache_is_a_miss(mods, tmp_path):
    jr, eh, rnd, sr, summ = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)
    sid = "EFFORT-3"

    # Bump landed at 3; the version under test must be exactly the post-bump int.
    assert summ.SUMMARY_SCHEMA_VERSION == 3

    # Hand-write a legacy single-key cache at the OLD path with schema_version 2.
    legacy_dir = summ.summary_dir(str(folder), pid, "research", sid)  # no stage
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / summ.SUMMARY_JSON).write_text(json.dumps({
        "session_id": sid, "lane": "research", "title": "old",
        "claims": ["stale claim"], "schema_version": 2,
    }), encoding="utf-8")

    # The legacy (stage=None) read is a MISS — the version is older than 3.
    assert summ.load_cached(str(folder), pid, "research", sid) is None
    # And it is certainly not served as a stage-keyed cache either.
    assert summ.load_cached(str(folder), pid, "research", sid,
                            stage="research") is None


# ── GWT 4 — stage=None path is byte-identical to legacy behavior ─────────────

def test_stage_none_path_is_legacy_unchanged(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sr, summ = mods
    folder = tmp_path / "proj"
    pid = _project(rnd, folder)
    sid = "LEGACY-1"

    rel = _write_doc(folder, "planning/MASTER-PLAN.md",
                     "# Master Plan\n\n## North Star\n"
                     "Build a validated cached summary surface for sessions.\n")
    sess = _session(sid, "planning", [_member(rel, "master plan")])

    monkeypatch.setenv("STUB_STREAMJSON_CLAIMS",
                       "Build a validated cached summary surface for sessions.")
    out = summ.summarize_session(str(folder), pid, "planning", sess)  # no stage

    # The cache lands at the legacy single-key path (NOT under a <stage>/ subdir).
    legacy_dir = summ.summary_dir(str(folder), pid, "planning", sid)
    assert legacy_dir.name != "plan"  # not a stage subdir
    assert legacy_dir.name == "LEGACY-1"
    assert (legacy_dir / summ.SUMMARY_JSON).is_file()
    # No stage-keyed dir was created.
    assert not summ.summary_dir(str(folder), pid, "planning", sid,
                                stage="plan").exists()

    # The legacy record carries NO 'stage' key (byte-identical legacy shape).
    assert "stage" not in out
    # Round-trip: load_cached() (no stage) serves the identical cached dict, and
    # a SECOND summarize serves the cache (run-once, model not re-run).
    cached = summ.load_cached(str(folder), pid, "planning", sid)
    assert cached is not None and "stage" not in cached
    assert cached["claims"] == out["claims"]
    again = summ.summarize_session(str(folder), pid, "planning", sess)
    assert again["generated_at"] == out["generated_at"]  # served from cache
    assert "stage" not in again

    # session_blurb (stage=None) still resolves the legacy cache unchanged.
    blurb = summ.session_blurb(str(folder), pid, "planning", sid)
    assert blurb  # non-empty, from the cached claim

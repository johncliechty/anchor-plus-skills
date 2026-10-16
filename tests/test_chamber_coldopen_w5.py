# W5 completion gate — brownfield derivation over the REAL ledgers, the
# one-time cold-open rebuild command, the died-after-last-reflection E9
# fixture, the fixture-size record, and the reflection-landing subscription.
#
# AUTH-ON: not-a-surface
#
# The wave's own words drive these tests:
#   * "fixture-tested against copies of every real live-campaign ledger"
#     (NOT synthetic shapes) — the real-ledgers sweep below parametrizes over
#     every committed campaign copy, asserts derive-or-drawn-degraded, and
#     proves ZERO writes anywhere by hashing the whole tree before/after.
#   * "One-time cold-open rebuild command deriving full projections from the
#     ledger" — chamber_coldopen.cold_open_rebuild (+ its CLI form) rebuilds
#     manifest + projection store + brief; deterministic (run twice ->
#     byte-identical sidecar files); every write under .anchor/chamber/.
#   * "died-after-last-reflection fixture" — the committed synthetic fixture:
#     the precomputed brief cites the reconciled run record and says the run
#     died; reflection text survives ONLY as labeled narrative color (E9).
#     The real mba-teaching-ai ledger is itself a died-after case and is
#     asserted too — real data, not just the synthetic shape.
#   * "Fixture-size record ... committed to a fixture manifest" — the record
#     is consistency-checked (largest = per-metric max; W6 minimums = 2x
#     each) and every copied fixture file is scrub-verified (no host home
#     paths ride the repo).
#   * "Brief precompute projector subscribed to existing reflection output"
#     — commission_session.finish_run lands a run + reflection and the brief
#     appears in the chamber sidecar with no further call.
#
# Pure module/fixture tests — no server is ever booted here.
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import chamber_brownfield as cb  # noqa: E402
import chamber_coldopen as co  # noqa: E402
import chamber_manifest as cm  # noqa: E402
import chamber_projections as _cp  # noqa: E402
import chamber_reconcile as cr  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "chamber"
REAL_LEDGERS = FIXTURES / "real-ledgers"
DIED_FIXTURE = FIXTURES / "synthetic" / "died-after-last-reflection"

REAL_CAMPAIGNS = sorted(
    p.name for p in REAL_LEDGERS.iterdir() if p.is_dir())

SIDECAR_PREFIX = ".anchor/chamber/"

ROADMAP = {
    "project_id": "proj-w5",
    "roadmap_projection": [
        {"id": "s1", "name": "Draft memo", "status": "done",
         "commissioned_as": "gandalf:job-1"},
        {"id": "s2", "name": "Verify memo", "status": None},
    ],
    "roadmap_events": [
        {"kind": "scaffold_proposal", "proposal_id": "prop-1",
         "goal": "A verified memo."},
    ],
}


def _write_roadmap(folder, doc):
    (Path(folder) / "roadmap.json").write_text(
        json.dumps(doc), encoding="utf-8")


def _tree_hashes(root, exclude_prefix=None):
    """{rel_posix: sha256} over every file under root, optionally excluding a
    rel-path prefix (the chamber sidecar, for zero-spine-write proofs)."""
    out = {}
    root = Path(root)
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if exclude_prefix and rel.startswith(exclude_prefix):
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ── The real-ledgers sweep (copies of every real live campaign, W5's words) ──

def test_real_campaign_fixtures_are_committed():
    # The wave is meaningless without the real copies: at least the six
    # campaigns captured 2026-08-09 must be present beside their manifest.
    assert len(REAL_CAMPAIGNS) >= 6
    assert (REAL_LEDGERS / "fixture-manifest.json").is_file()


@pytest.mark.parametrize("slug", REAL_CAMPAIGNS)
def test_real_campaign_derives_or_maps_degraded_with_zero_writes(slug):
    folder = REAL_LEDGERS / slug
    before = _tree_hashes(folder)

    out = cb.derive_brownfield_manifest(folder)
    assert out["route"] in (cb.ROUTE_DERIVED, cb.ROUTE_DEGRADED)
    if out["route"] == cb.ROUTE_DERIVED:
        assert cm.validate_manifest(out["manifest"]) == []
        again = cb.derive_brownfield_manifest(folder)
        assert cm.compute_manifest_hash(out["manifest"]) == \
            cm.compute_manifest_hash(again["manifest"])
    else:
        # degraded is DRAWN and NAMED, never a shrug
        assert out["reason"] in (cb.REASON_ROADMAP_MISSING,
                                 cb.REASON_ROADMAP_UNREADABLE,
                                 cb.REASON_NO_STEPS,
                                 cb.REASON_DERIVED_INVALID)
        assert out["amendment_ref"] == cb.DEGRADED_AMENDMENT_REF

    # chamber-side READS only: not one byte of the real ledger copy moved
    assert _tree_hashes(folder) == before


@pytest.mark.parametrize("slug", REAL_CAMPAIGNS)
def test_real_campaign_with_projection_steps_actually_derives(slug):
    # The dual path must not be satisfied vacuously: any real campaign whose
    # roadmap carries valid projection steps must take the DERIVED route.
    folder = REAL_LEDGERS / slug
    try:
        doc = json.loads((folder / "roadmap.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pytest.skip("campaign has no readable roadmap — degraded by design")
    steps = [s for s in (doc.get("roadmap_projection") or [])
             if isinstance(s, dict)
             and isinstance(s.get("id"), str) and s["id"].strip()
             and isinstance(s.get("name"), str) and s["name"].strip()]
    out = cb.derive_brownfield_manifest(folder)
    if steps:
        assert out["route"] == cb.ROUTE_DERIVED
    else:
        assert out["route"] == cb.ROUTE_DEGRADED


@pytest.mark.parametrize("slug", REAL_CAMPAIGNS)
def test_cold_open_rebuild_on_real_campaign(tmp_path, slug):
    camp = tmp_path / slug
    shutil.copytree(REAL_LEDGERS / slug, camp)
    spine_before = _tree_hashes(camp, exclude_prefix=SIDECAR_PREFIX)

    out = co.cold_open_rebuild(camp)
    assert out["ok"], out
    assert out["refused_parts"] == []
    assert out["writes_under"] == _cp.CHAMBER_SIDECAR_REL

    # the FULL chamber projection landed in the sidecar
    assert (camp / cr.BRIEF_REL).is_file()
    assert (camp / _cp.PROJECTIONS_REL).is_file()
    assert out["parts"]["manifest"]["route"] in (
        cb.ROUTE_DERIVED, cb.ROUTE_DEGRADED, co.ROUTE_KEPT_MANIFEST)

    # E8 / zero spine writes: every byte outside .anchor/chamber/ untouched
    assert _tree_hashes(camp, exclude_prefix=SIDECAR_PREFIX) == spine_before

    # pre-emission honesty: each brief field either derives deterministically
    # or carries the DRAWN degraded reference — never a blank guess
    brief = cr.load_brief(camp)
    assert brief["schema"] == cr.SCHEMA
    for key in ("stand", "running", "next_move"):
        f = brief["fields"][key]
        assert f["text"] is not None or f.get("degraded"), (slug, key, f)
    gg = brief["fields"]["goal_guard"]
    assert gg["text"] is not None or gg.get("degraded"), (slug, gg)

    # deterministic + re-runnable: a second rebuild is byte-identical
    sidecar_files = [camp / cr.BRIEF_REL, camp / _cp.PROJECTIONS_REL]
    if (camp / cm.MANIFEST_REL).is_file():
        sidecar_files.append(camp / cm.MANIFEST_REL)
    first = {p.name: _sha(p) for p in sidecar_files}
    again = co.cold_open_rebuild(camp)
    assert again["ok"]
    assert {p.name: _sha(p) for p in sidecar_files} == first


# ── The died-after-last-reflection fixture (E9's acceptance case) ────────────

def test_died_after_last_reflection_brief_cites_record_not_reflection(tmp_path):
    camp = tmp_path / "died"
    shutil.copytree(DIED_FIXTURE, camp)

    rec = cr.reconcile(camp)
    died = rec["died_after_last_reflection"]
    assert died is not None
    assert died["cites"] == "run-record:runB"
    assert died["run"]["outcome"] == "died"
    assert died["reflection_source"] == "run-record:runA"
    assert rec["overrides"] and rec["overrides"][0]["winner"] == "run-record"

    brief = cr.precompute_brief(camp, persist=True)
    running = brief["fields"]["running"]
    # the brief CITES the reconciled record and SAYS the run died
    assert running["cites"] == "run-record:runB"
    assert "died" in running["text"]
    assert "last-writer" in running["rule"]
    # the reflection's optimistic claim never becomes grounded brief text …
    assert "will land cleanly" not in (running["text"] or "")
    # … it survives ONLY as labeled narrative color (E9)
    color = brief["fields"]["stand"].get("color")
    assert color and "narrative color" in color["role"]
    assert "will land cleanly" in color["text"]
    assert color["source"] == "run-record:runA"


def test_real_mba_ledger_is_a_died_after_last_reflection_case():
    # Real data, not a synthetic shape: the mba-teaching-ai capture ends with
    # a timeout run carrying the last reflection — the record must win (E9).
    folder = REAL_LEDGERS / "mba-teaching-ai"
    rec = cr.reconcile(folder)
    died = rec["died_after_last_reflection"]
    assert died is not None
    assert died["run"]["outcome"] in cr.DEATH_OUTCOMES
    assert rec["overrides"] and rec["overrides"][0]["winner"] == "run-record"

    brief = cr.precompute_brief(folder, persist=False)  # read-only fixture
    running = brief["fields"]["running"]
    assert running["cites"] == died["cites"]
    assert died["run"]["outcome"] in running["text"]
    assert "no run is live" in running["text"]


def test_died_fixture_cold_open_rebuild_derives_event_time_store(tmp_path):
    camp = tmp_path / "died"
    shutil.copytree(DIED_FIXTURE, camp)
    out = co.cold_open_rebuild(camp)
    assert out["ok"]
    events = _cp.read_events(camp)
    # runA: derivable start + produced yield; runB: derivable start + death —
    # in deterministic event-time order, every event carrying its cite
    assert [e["kind"] for e in events] == [
        _cp.KIND_COMMISSION_START, _cp.KIND_STEP_YIELD,
        _cp.KIND_COMMISSION_START, _cp.KIND_RUN_DEATH]
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert all(e["derived"] and "run-record:" in e["derived_from"]
               for e in events)
    death = events[-1]
    assert death["outcome"] == "died" and death["session_id"] == "runB"
    y = events[1]
    assert y["report_link"] == "run-record:runA" and y["step_id"] == "s1"


# ── Rebuild refusal + cure laws ─────────────────────────────────────────────

def test_rebuild_refuses_to_clobber_live_observed_store(tmp_path):
    _write_roadmap(tmp_path, ROADMAP)
    _cp.record_commission_start(tmp_path, "c-obs", session_id="live-1",
                                step_id="s1", skill="gandalf", lane="general")
    out = co.cold_open_rebuild(tmp_path)
    assert not out["ok"]
    assert out["refused_parts"] == ["projections"]
    part = out["parts"]["projections"]
    assert part["reason"] == co.REFUSAL_LIVE_STORE
    # the observed event survives untouched
    events = _cp.read_events(tmp_path)
    assert len(events) == 1 and events[0]["commission_id"] == "c-obs"
    # the independent legs still landed honestly
    assert (Path(tmp_path) / cr.BRIEF_REL).is_file()


def test_rebuild_is_the_cure_for_a_corrupt_store(tmp_path):
    _write_roadmap(tmp_path, ROADMAP)
    store = Path(tmp_path) / _cp.PROJECTIONS_REL
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(_cp.ProjectionStoreError):
        _cp.load_store(tmp_path)
    out = co.cold_open_rebuild(tmp_path)
    assert out["ok"]
    assert out["parts"]["projections"]["was_corrupt"] is True
    assert isinstance(_cp.read_events(tmp_path), list)  # readable again


def test_rebuild_keeps_a_declared_manifest(tmp_path):
    _write_roadmap(tmp_path, ROADMAP)
    declared = cb.derive_brownfield_manifest(tmp_path)["manifest"]
    del declared["brownfield"]  # a scaffold-time manifest has no such key
    assert cm.write_manifest(tmp_path, declared)["ok"]
    before = _sha(Path(tmp_path) / cm.MANIFEST_REL)
    out = co.cold_open_rebuild(tmp_path)
    assert out["ok"]
    assert out["parts"]["manifest"]["route"] == co.ROUTE_KEPT_MANIFEST
    assert _sha(Path(tmp_path) / cm.MANIFEST_REL) == before


def test_underivable_campaign_rebuild_is_drawn_degraded_not_refused(tmp_path):
    # no roadmap at all: manifest leg maps to the DRAWN degraded-rail state,
    # yet the command still WORKS (degraded is honest, not a failure)
    out = co.cold_open_rebuild(tmp_path)
    assert out["ok"]
    assert "manifest" in out["degraded_parts"]
    part = out["parts"]["manifest"]
    assert part["state"] == cb.DEGRADED_RAIL_STATE
    assert part["reason"] == cb.REASON_ROADMAP_MISSING


def test_cold_open_rebuild_cli_command(tmp_path, capsys):
    _write_roadmap(tmp_path, ROADMAP)
    assert co._cli(["rebuild", str(tmp_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["ok"] and printed["writes_under"] == _cp.CHAMBER_SIDECAR_REL
    assert (Path(tmp_path) / cr.BRIEF_REL).is_file()
    assert co._cli([]) == 2  # usage, never a stack trace


# ── The fixture-size record (W6's >=2x budget numbers key off it) ────────────

def test_fixture_size_record_is_committed_and_consistent():
    man = json.loads(
        (REAL_LEDGERS / "fixture-manifest.json").read_text(encoding="utf-8"))
    rows = man["campaigns"]
    assert rows and man["schema_version"] == 1
    # every recorded campaign copy exists, file for file
    for r in rows:
        d = REAL_LEDGERS / r["slug"]
        assert d.is_dir(), r["slug"]
        for rel in r["copied_files"]:
            assert (d / rel).is_file(), (r["slug"], rel)
    # no unlisted campaign dir rides along
    assert {p.name for p in REAL_LEDGERS.iterdir() if p.is_dir()} == \
        {r["slug"] for r in rows}
    # the largest-real-ledger record is the per-metric max, honestly
    largest = man["largest_real_ledger"]
    assert largest["event_count"] == max(r["event_count"] for r in rows)
    assert largest["run_record_count"] == \
        max(r["run_record_count"] for r in rows)
    assert largest["bytes_full_ledger"] == \
        max(r["bytes_full_ledger"] for r in rows)
    # W6's budget floor: >= 2x EACH measured number
    rule = man["w6_budget_rule"]
    assert rule["min_event_count"] == 2 * largest["event_count"]
    assert rule["min_run_record_count"] == 2 * largest["run_record_count"]
    assert rule["min_bytes"] == 2 * largest["bytes_full_ledger"]


_HOME_PATH = re.compile(
    r"[A-Za-z]:[\\/]+Users[\\/]|/Users/[A-Za-z0-9_]|/home/[A-Za-z0-9_]")


def test_no_host_home_path_rides_the_committed_fixtures_or_w5_sources():
    files = [p for p in FIXTURES.rglob("*") if p.is_file()]
    files += [Path(m.__file__) for m in (cb, co, cr)]
    assert files
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        m = _HOME_PATH.search(text)
        assert m is None, (str(p.name), m.group(0))


# ── The reflection-landing subscription (E8, wired into finish_run) ─────────

def test_finish_run_precomputes_brief_at_reflection_landing(tmp_path,
                                                            monkeypatch):
    import commission_session as cs
    monkeypatch.setattr(cs, "run_bridge", lambda mode, payload, timeout=0: {
        "ok": True,
        "report": {"say": "clean landing"},
        "reflection": {"impact": "The memo landed.", "next": None},
        "raised": None, "handback": None})
    monkeypatch.setattr(cs, "commit_campaign_state",
                        lambda *a, **k: {"ok": True, "committed": False})
    _write_roadmap(tmp_path, ROADMAP)

    record = {"session_id": "sessA", "commission_id": "c-9", "step_id": "s1",
              "skill": "gandalf", "lane": "general"}
    result = {"outcome": "produced", "transcript": "hello", "ran": True,
              "elapsed_s": 3, "transcript_chars": 5}
    out = cs.finish_run(str(tmp_path), "proj-w5", record, result)
    assert out["ok"]

    # the brief precomputed into the chamber sidecar with NO further call
    brief = cr.load_brief(tmp_path)
    assert brief and brief["schema"] == cr.SCHEMA
    assert "Last landed: gandalf on s1" in brief["fields"]["stand"]["text"]
    color = brief["fields"]["stand"].get("color")
    assert color and color["text"] == "The memo landed."
    assert "narrative color" in color["role"]

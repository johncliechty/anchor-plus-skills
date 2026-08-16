# W6 gate — the bounded Seal-open read path + verbatim M1 slice render
# (chamber_open), proven against the wave's own words.
#
# AUTH-ON: not-a-surface
#
# The wave's C1 laws drive these tests:
#   * "Structural read-path fixes ... before any cache" — the ledger is
#     tail-read from the last snapshot line (never a full-history replay)
#     and run-record reads are capped to active scaffold steps under the
#     hard 200-read backstop, with a REFUSAL path into the drawn
#     degraded-rail state when the cap is exceeded.
#   * "First-open-after-deploy" (drawn-degraded-until-rebuilt, signed
#     AG-DEGRADED-RAIL): sidecar absent or schema-stale paints the drawn
#     degraded state and SURFACES the W5 cold-open rebuild affordance — an
#     inline rebuild on the open path is a test failure, proven here by
#     whole-tree hashing (the open writes NOTHING, repairs NOTHING).
#   * "<2s ... at the committed >=2x-real fixture sizes" — the budget test
#     below generates its synthetic campaign AT OR ABOVE every number in
#     the committed fixture manifest's w6_budget_rule (events, MB on disk,
#     run records) and asserts the open meets the bound via the structural
#     fixes alone (the read_stats prove the tail-read, not a cache).
#   * "Zero model calls, zero spawns, zero writes" — the module's import
#     closure is pinned (no subprocess/socket/model client can even be
#     named), and both open paths are hash-proven write-free.
#   * The render is the thin VERBATIM-markup shell: every slot value is
#     escaped (hostile step names/goals never reach the DOM raw).
#
# Pure module/fixture tests — no server is ever booted here.
import ast
import hashlib
import json
import sys
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

import chamber_coldopen as co  # noqa: E402
import chamber_open as copen  # noqa: E402
import chamber_projections as _cp  # noqa: E402
import chamber_reconcile as cr  # noqa: E402

FIXTURE_MANIFEST = (Path(__file__).resolve().parent / "fixtures" / "chamber"
                    / "real-ledgers" / "fixture-manifest.json")


# ── helpers ─────────────────────────────────────────────────────────────────

def _tree_hashes(root):
    """{rel_posix: sha256} over every file under root — the zero-write
    proof: equal before/after means the open touched NOTHING."""
    out = {}
    root = Path(root)
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def _at(i):
    """Monotonic synthetic instants (lexicographically ordered ISO)."""
    return "2026-08-09T%02d:%02d:%02dZ" % (i // 3600, (i // 60) % 60, i % 60)


def _roadmap(steps, events, as_of):
    return {"project_id": "proj-w6", "as_of": as_of,
            "roadmap_projection": steps, "roadmap_events": events}


def _write_roadmap(folder, doc):
    (Path(folder) / "roadmap.json").write_text(
        json.dumps(doc), encoding="utf-8")


def _write_run_record(folder, sid, *, step_id, outcome, at, skill="gandalf",
                      say="did the thing", reflection=True):
    root = Path(folder) / cr.RUN_RECORDS_REL
    root.mkdir(parents=True, exist_ok=True)
    rec = {"session_id": sid, "commission_id": "c-" + sid, "step_id": step_id,
           "skill": skill, "lane": "research", "outcome": outcome, "at": at,
           "elapsed_s": 12.5, "report": {"say": say}}
    if reflection:
        rec["reflection"] = {"say": say, "at": at}
    (root / (sid + ".json")).write_text(json.dumps(rec), encoding="utf-8")


def _campaign(tmp_path, name="camp"):
    """A minimal real-shaped campaign: 2-step roadmap (one done, one active),
    one finished + one live run record, sidecar built by the REAL W5
    cold-open rebuild (never a hand-forged sidecar)."""
    folder = tmp_path / name
    folder.mkdir()
    steps = [
        {"id": "s1", "name": "Draft memo", "status": "done",
         "skill": "gandalf", "commissioned_as": "gandalf:job-1"},
        {"id": "s2", "name": "Verify memo", "status": None,
         "skill": "researchPrime"},
    ]
    events = [
        {"kind": "scaffold_proposal", "proposal_id": "prop-1",
         "goal": "A verified memo.", "at": _at(10)},
        {"kind": "step_done", "step_id": "s1", "at": _at(20)},
    ]
    _write_roadmap(folder, _roadmap(steps, events, as_of=_at(20)))
    _write_run_record(folder, "sess-done", step_id="s1", outcome="done",
                      at=_at(15))
    _write_run_record(folder, "sess-live", step_id="s2",
                      outcome=cr.OUTCOME_LIVE, at=_at(25), reflection=False)
    co.cold_open_rebuild(folder)
    return folder


# ── structural fix 1: ledger tail-read from the last snapshot line ──────────

def test_ledger_tail_reads_the_tail_never_the_full_history(tmp_path):
    folder = tmp_path / "tail"
    folder.mkdir()
    events = [{"kind": "note", "n": i, "at": _at(i)} for i in range(500)]
    # Snapshot current to the last event: the reverse scan must stop on its
    # FIRST hit — 500 events of history, ONE scanned line.
    _write_roadmap(folder, _roadmap([], list(events), as_of=_at(499)))
    r = copen.read_ledger_tail(folder)
    assert r["present"] and not r["unreadable"]
    assert r["read_stats"]["ledger_events_total"] == 500
    assert r["read_stats"]["ledger_events_scanned"] == 1
    assert r["read_stats"]["ledger_tail_count"] == 0
    assert r["tail_events"] == []

    # Three events landed after the snapshot instant: tail = exactly those
    # three, scanned = tail + the one snapshot-line hit that stops the scan.
    _write_roadmap(folder, _roadmap([], list(events), as_of=_at(496)))
    r = copen.read_ledger_tail(folder)
    assert r["read_stats"]["ledger_events_scanned"] == 4
    assert r["read_stats"]["ledger_tail_count"] == 3
    assert [e["n"] for e in r["tail_events"]] == [497, 498, 499]


def test_ledger_tail_missing_and_corrupt_are_honest(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    r = copen.read_ledger_tail(folder)
    assert r == {"present": False, "unreadable": False, "steps": [],
                 "as_of": None, "tail_events": [], "read_stats":
                 {"ledger_events_total": 0, "ledger_events_scanned": 0,
                  "ledger_tail_count": 0}}
    (folder / "roadmap.json").write_text("{not json", encoding="utf-8")
    r = copen.read_ledger_tail(folder)
    assert r["present"] and r["unreadable"]
    assert r["steps"] == [] and r["tail_events"] == []


# ── structural fix 2: run-record reads capped to active scaffold steps ──────

def test_run_record_reads_capped_to_active_steps(tmp_path):
    folder = tmp_path / "cap"
    folder.mkdir()
    for sid in ("a-done", "b-active", "c-unbonded"):
        _write_run_record(folder, sid, step_id=None, outcome="done",
                          at=_at(5))
    steps = [{"id": "s1", "name": "one", "status": "done"},
             {"id": "s2", "name": "two", "status": None}]
    events = [
        {"kind": _cp.KIND_COMMISSION_START, "session_id": "a-done",
         "step_id": "s1"},   # bonded to a DONE step — not a candidate
        {"kind": _cp.KIND_COMMISSION_START, "session_id": "b-active",
         "step_id": "s2"},   # bonded to the ACTIVE step — a candidate
        {"kind": _cp.KIND_RUN_DEATH, "session_id": "c-unbonded"},
        # cited with NO step bond — cannot be proven inactive, stays in
    ]
    plan = copen.plan_run_record_reads(folder, steps, events)
    assert not plan["refused"]
    assert sorted(f.stem for f in plan["candidates"]) == \
        ["b-active", "c-unbonded"]
    assert plan["stats"]["run_records_present"] == 3
    assert plan["stats"]["run_record_reads"] == 2

    # No citations at all: every present record is a candidate (honest
    # fallback), still under the backstop.
    plan = copen.plan_run_record_reads(folder, steps, [])
    assert not plan["refused"]
    assert plan["stats"]["run_record_candidates"] == 3

    # Over the cap: REFUSED — zero reads, never a silent truncation.
    plan = copen.plan_run_record_reads(folder, steps, [], cap=2)
    assert plan["refused"] and plan["candidates"] == []
    assert plan["stats"]["run_record_reads"] == 0
    assert plan["stats"]["run_record_read_cap"] == 2


def test_read_run_records_capped_skips_unreadable_and_sorts(tmp_path):
    folder = tmp_path / "reads"
    folder.mkdir()
    _write_run_record(folder, "later", step_id="s1", outcome="done",
                      at=_at(50))
    _write_run_record(folder, "earlier", step_id="s1", outcome="done",
                      at=_at(10))
    root = Path(folder) / cr.RUN_RECORDS_REL
    (root / "broken.json").write_text("{nope", encoding="utf-8")
    rows = copen.read_run_records_capped(sorted(root.glob("*.json")))
    assert [r["session_id"] for r in rows] == ["earlier", "later"]
    assert all(r["terminal"] for r in rows)


# ── first-open-after-deploy: drawn-degraded-until-rebuilt (AG-DEGRADED-RAIL) ─

def test_first_open_after_deploy_paints_drawn_degraded_and_never_rebuilds(
        tmp_path):
    folder = tmp_path / "fresh"
    folder.mkdir()
    _write_roadmap(folder, _roadmap(
        [{"id": "s1", "name": "Draft memo", "status": None}],
        [{"kind": "note", "at": _at(1)}], as_of=_at(1)))
    before = _tree_hashes(folder)

    view = copen.seal_open_view(folder)
    html = copen.render_seal_slice_html(view)

    deg = view["degraded"]
    assert deg["state"] == copen.DEGRADED_RAIL_STATE
    assert deg["amendment_ref"] == copen.DEGRADED_AMENDMENT_REF
    assert sorted(deg["reasons"]) == sorted([
        copen.REASON_PROJECTIONS_MISSING, copen.REASON_BRIEF_MISSING,
        copen.REASON_MANIFEST_MISSING])
    # The explicit W5 rebuild affordance is SURFACED, never run.
    assert deg["rebuild"]["command"] == copen.REBUILD_COMMAND
    assert copen.REBUILD_AFFORDANCE_LABEL in html
    assert 'data-rebuild-command' in html and 'class="degrail"' in html
    # The degraded open reads NO run records and stays inside the bound.
    assert view["read_stats"]["run_record_reads"] == 0
    assert view["open_ms"] < 2000
    # An inline rebuild on the open path is a test failure: the tree is
    # byte-identical — no sidecar appeared, nothing was "repaired".
    assert _tree_hashes(folder) == before


def test_schema_stale_sidecar_paints_degraded_not_a_guess(tmp_path):
    folder = _campaign(tmp_path, "stale")
    store_p = _cp.store_path(folder)
    doc = json.loads(store_p.read_text(encoding="utf-8"))
    doc["schema"] = "anchor-chamber-projections-v0-ancient"
    store_p.write_text(json.dumps(doc), encoding="utf-8")
    view = copen.seal_open_view(folder)
    assert copen.REASON_PROJECTIONS_SCHEMA_STALE in view["degraded"]["reasons"]

    folder2 = _campaign(tmp_path, "stalebrief")
    cr.brief_path(folder2).write_text(
        json.dumps({"schema": "anchor-chamber-brief-v0"}), encoding="utf-8")
    view = copen.seal_open_view(folder2)
    assert copen.REASON_BRIEF_SCHEMA_STALE in view["degraded"]["reasons"]

    folder3 = _campaign(tmp_path, "corrupt")
    _cp.store_path(folder3).write_text("{corrupt", encoding="utf-8")
    view = copen.seal_open_view(folder3)
    assert copen.REASON_PROJECTIONS_UNREADABLE in view["degraded"]["reasons"]


def test_read_cap_exceeded_refuses_into_the_drawn_degraded_state(tmp_path):
    folder = _campaign(tmp_path, "flood")
    # Rebuild happened over 2 records; now 201 UNCITED records appear (no
    # projection event names them) — the fallback candidate set exceeds the
    # 200-read backstop and the open REFUSES into the drawn state.
    store_p = _cp.store_path(folder)
    doc = json.loads(store_p.read_text(encoding="utf-8"))
    doc["events"] = []          # no citations at all → fallback = every file
    store_p.write_text(json.dumps(doc), encoding="utf-8")
    for i in range(copen.RUN_RECORD_READ_CAP + 1):
        _write_run_record(folder, "flood-%03d" % i, step_id=None,
                          outcome="done", at=_at(i))
    before = _tree_hashes(folder)
    view = copen.seal_open_view(folder)
    assert view["degraded"]["reasons"] == [copen.REASON_READ_CAP_EXCEEDED]
    assert view["read_stats"]["run_record_reads"] == 0
    assert view["read_stats"]["run_record_candidates"] > \
        copen.RUN_RECORD_READ_CAP
    assert _tree_hashes(folder) == before


# ── the healthy open: one bounded, deterministic, write-free pass ───────────

def test_seal_open_healthy_view_from_the_real_rebuilt_sidecar(tmp_path):
    folder = _campaign(tmp_path)
    before = _tree_hashes(folder)
    view = copen.seal_open_view(folder)
    assert view["ok"] and view["degraded"] is None
    assert view["schema"] == copen.SCHEMA
    assert view["progress"] == {"done": 1, "total": 2}
    assert [s["id"] for s in view["steps"]] == ["s1", "s2"]
    # The live record surfaces as the running step.
    assert view["live_run"] and view["live_run"]["session_id"] == "sess-live"
    running = [s for s in view["steps"] if s.get("running")]
    assert [s["id"] for s in running] == ["s2"]
    # Bounded: snapshot-first (one scanned line), both records read, brief
    # served from the W5 precompute — no unbounded anything.
    assert view["read_stats"]["ledger_events_scanned"] == 1
    assert view["read_stats"]["run_record_reads"] <= 2
    assert view["brief"] is not None
    assert view["open_ms"] < 2000
    # Zero writes on the open path — byte-identical tree.
    assert _tree_hashes(folder) == before
    # Deterministic: two opens agree on everything but the stopwatch.
    v1, v2 = copen.seal_open_view(folder), copen.seal_open_view(folder)
    v1.pop("open_ms"), v2.pop("open_ms")
    assert v1 == v2


# ── the W6 budget: <2s at the committed >=2x-real fixture sizes ─────────────

def test_open_budget_under_2s_at_the_committed_2x_fixture_sizes(tmp_path):
    rule = json.loads(FIXTURE_MANIFEST.read_text(
        encoding="utf-8"))["w6_budget_rule"]
    folder = tmp_path / "months"
    folder.mkdir()

    n_events = max(200, rule["min_event_count"])
    n_records = max(24, rule["min_run_record_count"])
    pad = "x" * 8192  # drives the ledger past the committed byte floor
    steps = [{"id": "s%d" % i, "name": "Step %d" % i,
              "status": "done" if i < 8 else None, "skill": "gandalf"}
             for i in range(10)]
    events = [{"kind": "note", "n": i, "note": pad, "at": _at(i)}
              for i in range(n_events)]
    _write_roadmap(folder, _roadmap(steps, events, as_of=_at(n_events - 1)))
    for i in range(n_records):
        _write_run_record(folder, "sess-%03d" % i,
                          step_id="s%d" % (8 + (i % 2)), outcome="done",
                          at=_at(i))

    # The synthetic campaign genuinely meets EVERY committed minimum — the
    # committed numbers are the oracle, not a copy pasted into this test.
    ledger_bytes = (folder / "roadmap.json").stat().st_size
    assert n_events >= rule["min_event_count"]
    assert n_records >= rule["min_run_record_count"]
    assert ledger_bytes >= rule["min_bytes"]

    co.cold_open_rebuild(folder)
    view = copen.seal_open_view(folder)
    assert view["degraded"] is None
    # The bound, met by STRUCTURE (tail-read + capped reads), not a cache:
    # months of history, ONE scanned ledger line.
    assert view["open_ms"] < 2000
    assert view["read_stats"]["ledger_events_total"] == n_events
    assert view["read_stats"]["ledger_events_scanned"] == 1
    assert view["read_stats"]["run_record_reads"] <= \
        copen.RUN_RECORD_READ_CAP
    html = copen.render_seal_slice_html(view)
    assert html.startswith('<div class="dock">')


# ── the verbatim slice render: escaped slots, drawn states, no invention ────

def test_render_escapes_hostile_slot_values(tmp_path):
    folder = tmp_path / "hostile"
    folder.mkdir()
    evil = '<script>alert(1)</script>"&'
    _write_roadmap(folder, _roadmap(
        [{"id": "s1", "name": evil, "status": None}],
        [{"kind": "note", "at": _at(1)}], as_of=_at(1)))
    html = copen.render_seal_slice_html(copen.seal_open_view(folder))
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    hostile_view = {
        "degraded": None, "progress": {"done": 0, "total": 1},
        "steps": [{"id": "s1", "name": evil, "status": None, "skill": evil}],
        "goal": {"text": evil}, "brief": {"stand": {"text": evil}},
        "live_run": None, "deliverable": None,
    }
    html = copen.render_seal_slice_html(hostile_view)
    assert "<script>" not in html
    for cls in ('class="dbar"', 'class="progress"', 'class="goalbar"',
                'class="chamber"', 'class="convo"'):
        assert cls in html


def test_render_carries_the_signed_drawn_states(tmp_path):
    # AG-STEP-NO-SKILL / AG-YIELD-MISSING / AG-NO-RUNNING-STEP: the drawn
    # honest states, never a guessed skill / fabricated yield / fake pulse.
    view = {
        "degraded": None, "progress": {"done": 1, "total": 2},
        "steps": [
            {"id": "s1", "name": "Done bare", "status": "done"},
            {"id": "s2", "name": "Next up", "status": None},
        ],
        "goal": {}, "brief": {}, "live_run": None, "deliverable": None,
    }
    html = copen.render_seal_slice_html(view)
    assert "no skill bound" in html
    assert "yield missing" in html
    assert "goal unreadable" in html
    assert "no step running" in html


# ── zero model calls, zero spawns: the import closure is pinned ─────────────

def test_module_import_closure_admits_no_spawn_no_network_no_model():
    src = (ANCHOR / "chamber_open.py").read_text(encoding="utf-8")
    allowed = {"__future__", "html", "json", "time", "pathlib",
               "chamber_brownfield", "chamber_manifest",
               "chamber_projections", "chamber_reconcile"}
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= allowed, imported - allowed
    for forbidden in ("subprocess", "socket", "urllib", "requests",
                      "http", "asyncio"):
        assert forbidden not in imported

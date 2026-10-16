# W11 — E3: the correction-recording contract, the one-time triage with the
# published predicate-coverage threshold, the handback-blocking regression
# guard on the W2-proven seam, and the findings-ledger wire-homing row
# resolved against the committed ledger fixture (steward-chamber W11, C6).
#
# AUTH-ON: not-a-surface
#
# The wave's own words drive these tests:
#   * "Given a resumed/re-briefed rewrite that regresses a predicate-bearing
#     correction, when handback is attempted, then the mechanical diff blocks
#     the handback with the named finding, and the coverage report shows the
#     unassertable remainder demoted, never silently blessed (E3)."
#   * "Correction-recording contract: machine predicate (grep/length/
#     structural) or explicit 'unassertable — manual review' mark"
#   * "wire-homing row findings-ledger (engine/step-findings.mjs) resolved
#     against committed ledger fixtures"
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_corrections as ccx  # noqa: E402
import chamber_enforcement as ce  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]
LEDGER_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "chamber" \
    / "step-findings-ledger.json"


def _project(tmp_path):
    folder = tmp_path / "proj"
    (folder / ".anchor" / "chamber").mkdir(parents=True)
    return folder


GREP_CORRECTION = {
    "id": "c-no-legacy-weights",
    "text": "The syllabus must use the new 40/40/20 weights.",
    "artifact_rel": "docs/syllabus.md",
    "predicate": {"kind": "grep", "pattern": r"40/40/20",
                  "must_match": True},
}


# ── the recording contract: predicate REQUIRED or the explicit mark ─────────

def test_recording_refuses_a_correction_with_no_predicate_and_no_mark(tmp_path):
    folder = _project(tmp_path)
    out = ccx.record_correction(folder, {"id": "c1", "text": "be better"})
    assert not out["ok"]
    assert out["error"] == ccx.ERROR_PREDICATE_REQUIRED
    assert ccx.list_corrections(folder) == []


def test_recording_accepts_predicate_bearing_and_marked_unassertable(tmp_path):
    folder = _project(tmp_path)
    assert ccx.record_correction(folder, GREP_CORRECTION)["ok"]
    assert ccx.record_correction(folder, {
        "id": "c-tone", "text": "keep the steward's tone warm",
        "unassertable": True, "mark": ccx.UNASSERTABLE_MARK})["ok"]
    # A dishonest mark string is refused — the demotion is explicit or not
    # at all.
    out = ccx.record_correction(folder, {
        "id": "c-bad", "text": "x", "unassertable": True,
        "mark": "we'll eyeball it"})
    assert not out["ok"]


def test_all_three_predicate_kinds_evaluate_deterministically():
    assert ccx.evaluate_predicate(
        {"kind": "grep", "pattern": "x+", "must_match": True}, "xxx")["holds"]
    assert not ccx.evaluate_predicate(
        {"kind": "grep", "pattern": "x", "must_match": False}, "x")["holds"]
    assert ccx.evaluate_predicate(
        {"kind": "length", "min": 2, "max": 5}, "abc")["holds"]
    assert not ccx.evaluate_predicate({"kind": "length", "max": 2},
                                      "abc")["holds"]
    assert ccx.evaluate_predicate(
        {"kind": "structural", "required_lines": ["## Plan"]},
        "intro\n## Plan\nbody")["holds"]
    assert not ccx.evaluate_predicate(
        {"kind": "structural", "required_keys": ["steps"]},
        json.dumps({"goal": 1}))["holds"]
    # Malformed never holds — named, never a silent pass.
    v = ccx.evaluate_predicate({"kind": "vibes"}, "x")
    assert not v["holds"] and ccx.ERROR_BAD_PREDICATE in v["detail"]


# ── the one-time triage + the published threshold ───────────────────────────

def test_triage_keeps_derives_and_demotes_with_named_rows():
    triage = ccx.triage_entries([
        {"id": "keep-1", "text": "t", "predicate": {
            "kind": "length", "min": 1}},
        {"id": "derive-1", "text": "t", "must_contain": "SIGN-OFF"},
        {"id": "derive-2", "text": "t", "must_not_contain": "TODO"},
        {"id": "demote-1", "text": "prose only"},
    ])
    assert triage["kept"] == ["keep-1"]
    assert triage["derived"] == ["derive-1", "derive-2"]
    assert triage["demoted_unassertable"] == ["demote-1"]
    assert triage["coverage"] == 0.75
    assert triage["threshold"] == ccx.PREDICATE_COVERAGE_THRESHOLD
    assert triage["meets_threshold"] is True
    demoted = [e for e in triage["entries"] if e["id"] == "demote-1"][0]
    assert demoted["mark"] == ccx.UNASSERTABLE_MARK


def test_committed_triage_record_matches_the_code_owned_threshold():
    doc = ccx.load_triage_record()
    assert doc["schema_version"] == ccx.TRIAGE_SCHEMA_VERSION
    assert doc["owner_file"] == "chamber_corrections.py"
    assert doc["published_threshold"] == ccx.PREDICATE_COVERAGE_THRESHOLD
    # The record triages the REAL existing ledger honestly: all three legacy
    # fix-item entries demoted, coverage 0.0 — demoted, never blessed.
    legacy = doc["triaged_sources"][0]
    assert legacy["entries_found"] == 3
    assert legacy["demoted"] == 3 and legacy["coverage"] == 0.0
    for row in legacy["outcomes"]:
        assert row["outcome"] == "demoted"
        assert row["mark"] == ccx.UNASSERTABLE_MARK
    assert "C:\\\\" not in json.dumps(doc)  # no absolute host paths


def test_triage_of_the_real_fix_item_ledger_demotes_all_three_when_present():
    ledger = ce.ecgberht_root() / "artifacts" / "fix-item-ledger.json"
    if not ledger.is_file():
        # The two-repo contract makes the sibling required in the gate; a
        # missing ledger elsewhere still leaves the committed record tested.
        return
    items = json.loads(ledger.read_text(encoding="utf-8"))["items"]
    triage = ccx.triage_entries(
        [{"id": i["id"], "text": i.get("title")} for i in items])
    assert triage["total"] == 3
    assert triage["demoted_unassertable"] == [i["id"] for i in items]
    assert triage["coverage"] == 0.0


# ── E3: the handback guard blocks a regression with the named finding ───────

def test_regressed_predicate_blocks_handback_with_named_finding(tmp_path):
    folder = _project(tmp_path)
    (folder / "docs").mkdir()
    doc = folder / "docs" / "syllabus.md"
    doc.write_text("weights: 40/40/20", encoding="utf-8")
    assert ccx.record_correction(folder, GREP_CORRECTION)["ok"]
    assert ccx.record_correction(folder, {
        "id": "c-tone", "text": "warm tone", "unassertable": True,
        "mark": ccx.UNASSERTABLE_MARK})["ok"]

    ok = ccx.handback_guard(folder)
    assert ok["ok"] and not ok["blocked"]

    # The resumed/re-briefed rewrite REGRESSES the correction.
    doc.write_text("weights: 50/40/10 (reverted)", encoding="utf-8")
    out = ccx.handback_guard(folder)
    assert out["blocked"]
    assert out["finding"] == ccx.FINDING_E3_REGRESSION
    assert [r["id"] for r in out["regressions"]] == ["c-no-legacy-weights"]
    # The report DEMOTES the unassertable remainder by name — never blessed.
    rep = out["report"]
    assert [d["id"] for d in rep["demoted_unassertable"]] == ["c-tone"]
    assert rep["demoted_unassertable"][0]["mark"] == ccx.UNASSERTABLE_MARK
    assert all(a["id"] != "c-tone" for a in rep["assertions"])


def test_vanished_artifact_is_a_regression_not_a_pass(tmp_path):
    folder = _project(tmp_path)
    assert ccx.record_correction(folder, GREP_CORRECTION)["ok"]
    out = ccx.handback_guard(folder)
    assert out["blocked"]
    assert "absent" in out["regressions"][0]["detail"]


def test_guard_fails_closed_on_unreadable_store_and_open_on_zero(tmp_path):
    folder = _project(tmp_path)
    assert ccx.handback_guard(folder)["ok"]  # zero corrections → honest ok
    ccx.store_path(folder).write_text("{broken", encoding="utf-8")
    out = ccx.handback_guard(folder)
    assert out["blocked"] and out["finding"] == ccx.FINDING_E3_REGRESSION


def test_every_report_carries_the_demoted_remainder(tmp_path):
    folder = _project(tmp_path)
    assert ccx.record_correction(folder, {
        "id": "u1", "text": "prose", "unassertable": True,
        "mark": ccx.UNASSERTABLE_MARK})["ok"]
    rep = ccx.coverage_report(folder)
    assert rep["demoted_unassertable"] == [
        {"id": "u1", "mark": ccx.UNASSERTABLE_MARK}]
    assert rep["coverage"] == 0.0
    assert rep["meets_threshold"] is False  # honest, not flattered


# ── the seam wiring: finish_run intercepts BEFORE the ingest bridge ─────────

def test_finish_run_calls_the_guard_before_the_ingest_bridge():
    src = (ANCHOR / "commission_session.py").read_text(encoding="utf-8")
    assert "chamber_corrections" in src and "handback_guard" in src, (
        "the E3 guard is not wired into commission_session at all")
    guard_at = src.index("handback_guard")
    ingest_at = src.index('run_bridge("ingest-run"')
    assert guard_at < ingest_at, (
        "the E3 interception must sit BEFORE the ingest bridge reaches the "
        "W2-proven ingestHandback seam")


def test_w2_seam_symbols_still_exist_in_the_engine_owner():
    """The interception point is the W2-proven handback seam — its named
    symbols must still exist in engine/handback-ingest.mjs (wire-homing
    law: a moved symbol fails by name, and the sibling is REQUIRED by the
    two-repo execution contract)."""
    owner = ce.ecgberht_root() / "engine" / "handback-ingest.mjs"
    assert owner.is_file(), "sibling engine/handback-ingest.mjs missing"
    src = owner.read_text(encoding="utf-8")
    assert "ingestHandback" in src
    assert "ingestValidatedHandbackBody" in src


# ── the findings-ledger wire-homing row (W11 wave of record) ────────────────

def test_findings_ledger_row_symbols_resolve_in_the_owner():
    owner = ce.ecgberht_root() / "engine" / "step-findings.mjs"
    assert owner.is_file(), "sibling engine/step-findings.mjs missing"
    src = owner.read_text(encoding="utf-8")
    assert "export function appendStepFindings" in src
    assert "export function findingsForStep" in src
    # The reader here mirrors the OWNER's constants, never forks them.
    assert ccx.STEP_FINDINGS_REL.replace("\\", "/") \
        == ".ecgberht/step-findings.json"
    assert ("'%s'" % ccx.STEP_FINDINGS_SCHEMA) in src


def test_reader_characterizes_against_the_committed_ledger_fixture(tmp_path):
    """The row's oracle: the COMMITTED ledger fixture (real store shape).
    The chamber reader must serve exactly the owner's read contract over
    it — findings surfaces + E3 triage input."""
    folder = _project(tmp_path)
    dest = ccx.step_findings_path(folder)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LEDGER_FIXTURE, dest)

    read = ccx.read_step_findings_ledger(folder)
    assert read["ok"] and read["exists"]
    assert read["schema"] == ccx.STEP_FINDINGS_SCHEMA
    rows = ccx.findings_for_step(folder, "step-syllabus")
    assert [r["finding"] for r in rows] == [
        "old weights Quizzes 50/40/10",
        "only 4 of 13 decks exist",
        "rubric facts ride into the syllabus step"]
    assert ccx.findings_for_step(folder, "no-such-step") == []

    triage_input = ccx.findings_triage_input(folder)
    assert len(triage_input) == 4
    assert triage_input[0]["step_id"] == "step-external-scan"
    # The flattened entries feed the SAME one-time triage mechanically.
    triage = ccx.triage_entries(triage_input)
    assert triage["total"] == 4
    assert triage["demoted_unassertable"] == [e["id"] for e in triage_input]


def test_reader_missing_and_corrupt_stores_answer_the_owner_contract(tmp_path):
    folder = _project(tmp_path)
    read = ccx.read_step_findings_ledger(folder)
    assert read == {"ok": True, "exists": False, "steps": {}}
    dest = ccx.step_findings_path(folder)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("{broken", encoding="utf-8")
    bad = ccx.read_step_findings_ledger(folder)
    assert bad["ok"] is False and bad["error"] == "step_findings_unreadable"

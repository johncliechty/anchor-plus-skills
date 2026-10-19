# W12 — the honestly-bounded close reports: E1 enforcement, E3 enforcement,
# and the C8 campaign-close ease report (steward-chamber W12, Phase-4 Close).
#
# AUTH-ON: not-a-surface
#
# The law under test: every number derives from a COMMITTED input; a fact
# the tree cannot ground is reported ABSENT by name, never invented; the
# builders are deterministic so the committed artifacts must equal a fresh
# regeneration; the ease verdict is JOHN'S one-pass audit, never the
# report's own number.
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chamber_close_report as ccr  # noqa: E402
import chamber_corrections as cc  # noqa: E402

ANCHOR = Path(__file__).resolve().parents[1]


def test_committed_reports_equal_a_fresh_regeneration():
    assert ccr.committed_matches_regenerated() == []


def test_reports_carry_no_absolute_host_paths():
    for _, path, _b in ccr.REPORTS:
        text = path.read_text(encoding="utf-8")
        assert "C:\\Users" not in text and "/Users/" not in text, path.name


# ── E1: honestly vacuous while the stack is absent ──────────────────────────

def test_e1_report_agrees_with_the_mechanical_instrument_scan():
    scan = ccr.e1_instrument_scan()
    text = ccr.E1_REPORT_PATH.read_text(encoding="utf-8")
    if scan["stack_complete"]:
        assert "Enforcement bound" in text
    else:
        # The report says VACUOUS and names the consequence plainly: E1 is
        # NOT engine-enforced in the assembled system.
        assert "HONESTLY VACUOUS" in text
        assert "NOT engine-enforced" in text
        assert "plan defect" in text
        # Every absent leg is marked NO in the scan table.
        assert text.count("| NO |") >= 3


def test_e1_scan_detects_a_landed_parser(tmp_path):
    # The probe is mechanical: a chamber module carrying the E1 vocabulary
    # flips the scan (and therefore the regenerated report, which would
    # then fail the committed-equality gate until regenerated).
    root = tmp_path / "anchor"
    (root / "tests").mkdir(parents=True)
    (root / "chamber_e1_bound.py").write_text(
        "def parse_direct_questions(text):\n    return []\n",
        encoding="utf-8")
    scan = ccr.e1_instrument_scan(root=root, ecg_root=tmp_path / "ecg")
    assert scan["bound_parser_landed"] is True
    assert scan["stack_complete"] is False  # hook + test + F7 still absent


# ── E3: real numbers from the committed triage record ───────────────────────

def test_e3_report_names_every_demoted_entry_and_the_threshold():
    record = ccr.load_triage_record()
    text = ccr.E3_REPORT_PATH.read_text(encoding="utf-8")
    assert ("PREDICATE_COVERAGE_THRESHOLD = %g"
            % cc.PREDICATE_COVERAGE_THRESHOLD) in text
    assert record["published_threshold"] == cc.PREDICATE_COVERAGE_THRESHOLD
    demoted = [o["id"] for src in record["triaged_sources"]
               for o in (src.get("outcomes") or [])
               if o.get("outcome") == "demoted"]
    assert demoted, "the committed triage record carries the demoted legacy"
    for eid in demoted:
        assert eid in text, ("every unassertable is NAMED in the report "
                             "(E3) — missing %s" % eid)
    assert cc.UNASSERTABLE_MARK.split(" ")[0] in text


# ── C8: the ease report ships the plan's own honest fallback ────────────────

def test_ease_report_is_honest_about_the_missing_instruments():
    scan = ccr.ease_instrument_scan()
    text = ccr.EASE_REPORT_PATH.read_text(encoding="utf-8")
    assert ccr.STAGE2_BASELINE in text, "the 5->0 baseline is the ruler"
    if not scan["frozen_classifier_landed"]:
        # No classifier of record -> no count; the report refuses to mint
        # a number and takes the plan's own C8 fallback.
        assert "UNAVAILABLE" in text
        assert "DESCRIPTIVE ONLY" in text
        assert "fabrication" in text
    # V6: the latency number (or its absence) is ON THE TABLE by name.
    assert "spoken-turn latency" in text
    # The verdict is JOHN'S one-pass audit — an explicit HALT marker.
    assert "HALT for John's one-pass audit" in text
    assert "no number above is the verdict" in text.replace("\n", " ")


def test_ease_scan_probes_are_specific_not_substring_noise():
    # 'release'/'lease' in the projections module must NOT read as an ease
    # ledger — the probe demands the specific tokens.
    scan = ccr.ease_instrument_scan()
    proj_text = (ANCHOR / "chamber_projections.py").read_text(
        encoding="utf-8", errors="replace")
    if not any(tok in proj_text for tok in
               ("ease_event", "ease_ledger", "record_ease", '"ease"')):
        assert scan["live_ease_ledger_landed"] is False


def test_write_reports_regenerates_into_a_target_dir(tmp_path):
    out = ccr.write_reports(chamber_dir=tmp_path)
    assert sorted(out) == ["e1", "e3", "ease"]
    for name, path in out.items():
        assert path.is_file() and path.parent == tmp_path
        assert path.read_text(encoding="utf-8").startswith("#"), name


def test_triage_record_is_versioned_owned_and_json_valid():
    record = json.loads(
        (ANCHOR / "chamber" / "correction-triage.json").read_text(
            encoding="utf-8"))
    assert record["schema_version"] == cc.TRIAGE_SCHEMA_VERSION
    assert record["owner_file"] == "chamber_corrections.py"

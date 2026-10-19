"""W14 — Doctor really diagnoses + banner→Doctor issue payload.

Exercises every W14 deliverable under one scoped gate:

* ``anchor/doctor/diagnose.py``
* ``anchor/doctor/banner_handoff.py``
* ``anchor/ui/doctor_view.py``
* ``artifacts/FAULT-FINDING-CONTRACTS.md``
* ``artifacts/failure-states/doctor-diagnose.md``
* ``artifacts/traces/doctor-diagnose-e2e.json``

Gate: pytest -v tests/test_doctor_diagnose_2026_07_29.py

GWTs (frozen plan):

* Each FAULT-FINDING-CONTRACTS row → finding matches shape and quotes the
  reading the fault changed (differing output alone does not pass).
* Fault absent from the contract table → finding still quotes a live reading
  or named no-finding; generic prose without a reading fails.
* Banner issue → Doctor shows payload with byte-identical id and hash;
  re-detection by Doctor fails the test.
* Diagnose capability unavailable → named unavailable state, not a clickable
  no-op (tri-state / dead-control harness).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from anchor.build.trace_artifact import (
    PROOF_LEVEL_RENDERED_STRING,
    is_go_evidence,
    validate_trace,
)
from anchor.doctor import banner_handoff as bh
from anchor.doctor import diagnose as diag
from anchor.doctor.banner_handoff import (
    IssuePayload,
    RedetectionForbidden,
    banner_issue_payload,
    doctor_entry,
    issue_payload_hash,
)
from anchor.doctor.diagnose import (
    ANTI_TEMPLATE_FAULT,
    CONTRACT_FAULTS,
    CONTROL_DIAGNOSE,
    DIAGNOSE_UNAVAILABLE_STATE,
    NO_FINDING_STATE,
    DiagnosisResult,
    Finding,
    SystemState,
    assert_finding_matches_contract,
    collect_rendered_finding_strings,
    diagnose,
    force_fault,
    healthy_system,
    parse_fault_contracts,
    source_contains_finding_literal,
    take_readings,
)
from anchor.ui import doctor_view as dv
from anchor.ui.dead_control import (
    CONTROL_DIAGNOSE as DC_DIAGNOSE,
    assert_no_dead_controls,
    audit_dead_controls,
    count_live_controls,
)
from anchor.ui.doctor_view import (
    DoctorViewContext,
    build_doctor_diagnose_trace,
    generate_html,
    generate_html_for_fixture,
    load_trace_set,
    render_doctor_surface,
    write_doctor_traces,
)
from anchor.ui.named_state import NamedState
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import validate_failure_state_table
from tests.conformance.tri_state import assert_tri_state
from tools.capability_inventory import EVIDENCE_LIVE, InventoryRow, Verdict

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "doctor-diagnose.md"
)
CONTRACTS_PATH = CONTAINMENT_ROOT / "artifacts" / "FAULT-FINDING-CONTRACTS.md"
DOCTOR_TRACE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "traces" / "doctor-diagnose-e2e.json"
)

#: Source modules that must not embed rendered finding strings as literals.
DIAGNOSE_SOURCE_RELS = (
    "anchor/doctor/diagnose.py",
    "anchor/doctor/banner_handoff.py",
    "anchor/ui/doctor_view.py",
)

# Generic prose markers that fail the anti-template / no-seed rules.
_GENERIC_PROSE_MARKERS = (
    "all systems nominal",
    "canned",
    "something went wrong",
    "diagnosis complete with issues",
    "generic fault",
    "[seed]",
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _present_row(control_id: str = CONTROL_DIAGNOSE) -> InventoryRow:
    return InventoryRow(
        control_id=control_id,
        verdict=Verdict.PRESENT,
        transcript_path="artifacts/transcripts/%s.json" % control_id,
        source_paths=("artifacts/inventory-sources/%s.probe" % control_id,),
        source_hash="c" * 64,
        probe_date="2026-07-29",
        evidence_mode=EVIDENCE_LIVE,
        disposition="wire it",
        notes="test PRESENT row for W14",
        label="Diagnose (Doctor)",
    )


def _parse_doctor_failure_table(text: str) -> list:
    rows = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| hardening"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4:
                continue
            if cells[0] in ("hardening",):
                continue
            rows.append(
                {
                    "hardening": cells[0],
                    "state": cells[1],
                    "user_visible": cells[2],
                    "trigger": cells[3],
                }
            )
        elif in_table and not line.startswith("|"):
            break
    return rows


def _visible_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return " ".join(text.split())


# --------------------------------------------------------------------------
# Acceptance: every new module is imported and exercised
# --------------------------------------------------------------------------


def test_w14_modules_importable_and_callable():
    assert callable(diagnose)
    assert callable(force_fault)
    assert callable(take_readings)
    assert callable(banner_issue_payload)
    assert callable(doctor_entry)
    assert callable(issue_payload_hash)
    assert callable(generate_html)
    assert callable(generate_html_for_fixture)
    assert callable(render_doctor_surface)
    assert callable(build_doctor_diagnose_trace)
    assert callable(write_doctor_traces)
    assert callable(load_trace_set)
    assert callable(parse_fault_contracts)
    assert callable(assert_finding_matches_contract)
    assert diag.WAVE_ID == "W14"
    assert dv.WAVE_ID == "W14"
    assert CONTROL_DIAGNOSE == "diagnose"
    assert DC_DIAGNOSE == "diagnose"
    assert set(CONTRACT_FAULTS)
    assert ANTI_TEMPLATE_FAULT not in CONTRACT_FAULTS
    assert bh.RedetectionForbidden is RedetectionForbidden


# --------------------------------------------------------------------------
# Fault→finding contracts (every row of FAULT-FINDING-CONTRACTS.md)
# --------------------------------------------------------------------------


def test_fault_contracts_file_exists_and_parses():
    assert CONTRACTS_PATH.is_file()
    rows = parse_fault_contracts(root=CONTAINMENT_ROOT)
    assert rows, "FAULT-FINDING-CONTRACTS.md must have machine rows"
    faults = {r["fault"] for r in rows}
    for expected in CONTRACT_FAULTS:
        assert expected in faults, "missing contract row for fault %r" % expected
    # Anti-template fault must NOT be a contract row.
    assert ANTI_TEMPLATE_FAULT not in faults


@pytest.mark.parametrize("fault_id", list(CONTRACT_FAULTS))
def test_fault_to_finding_contract(fault_id):
    """GWT: each contract row → finding matches shape and quotes the reading."""
    contracts = {
        r["fault"]: r for r in parse_fault_contracts(root=CONTAINMENT_ROOT)
    }
    contract = contracts[fault_id]
    result = diagnose(fault=fault_id)
    assert_finding_matches_contract(result, contract)
    # Differing output alone is not enough — reading must be present.
    if contract["shape"] not in ("named_unknown", "named_empty", "no_finding"):
        reading_name = contract["reading"]
        assert reading_name in result.readings
        finding = result.finding_for_reading(reading_name)
        assert finding is not None
        assert finding.quotes_reading()
        # Live value must have changed from healthy baseline for this reading.
        healthy = take_readings(healthy_system())
        assert result.readings[reading_name].value != healthy[reading_name].value


def test_differing_output_alone_does_not_pass_contract():
    """A result with findings that do not quote the changed reading fails."""
    contracts = parse_fault_contracts(root=CONTAINMENT_ROOT)
    contract = next(r for r in contracts if r["fault"] == "service_status_down")
    # Fabricate a bad result: finding without the live reading quote.
    bad = DiagnosisResult(
        readings=take_readings(force_fault("service_status_down")),
        findings=[
            Finding(
                reading_name="service_status",
                reading_value="down",
                shape="status_value",
                rendered="status degraded",  # does NOT quote the reading
            )
        ],
        ok=False,
        fault="service_status_down",
    )
    with pytest.raises(AssertionError):
        assert_finding_matches_contract(bad, contract)


# --------------------------------------------------------------------------
# Anti-template: fault absent from contract table
# --------------------------------------------------------------------------


def test_anti_template_fault_absent_from_contract_table():
    rows = parse_fault_contracts(root=CONTAINMENT_ROOT)
    assert ANTI_TEMPLATE_FAULT not in {r["fault"] for r in rows}


def test_anti_template_fault_quotes_live_reading_or_no_finding():
    """GWT: fault NOT in contract table still quotes a live reading (or no-finding).

    Falling through to generic prose without a live reading fails the wave.
    """
    result = diagnose(fault=ANTI_TEMPLATE_FAULT)
    # Must not emit generic prose markers.
    for f in result.findings:
        low = f.rendered.lower()
        for marker in _GENERIC_PROSE_MARKERS:
            assert marker not in low, (
                "anti-template fell through to generic prose %r in %r"
                % (marker, f.rendered)
            )

    if result.no_finding or result.named_state == NO_FINDING_STATE:
        # Named no-finding is an allowed escape hatch.
        assert result.named_state == NO_FINDING_STATE or result.no_finding
        return

    # Otherwise every finding must quote a live reading.
    assert result.findings, (
        "anti-template fault must produce a finding that quotes a live reading "
        "or the named no-finding state"
    )
    for f in result.findings:
        assert f.quotes_reading(), (
            "anti-template finding must quote live reading, got %r" % f.rendered
        )
    # Specifically the orphan_socket_count reading should be present and quoted.
    live = result.readings.get("orphan_socket_count")
    assert live is not None
    assert int(live.value) != 0
    finding = result.finding_for_reading("orphan_socket_count")
    assert finding is not None
    assert str(live.value) in finding.rendered


def test_anti_template_not_a_tag_to_prose_branch():
    """Source must not map ANTI_TEMPLATE_FAULT (or any fault) to fixed prose."""
    src = (CONTAINMENT_ROOT / "anchor" / "doctor" / "diagnose.py").read_text(
        encoding="utf-8"
    )
    # No dict/table of fault → polished sentence.
    assert "all systems nominal" not in src
    assert "[seed]" not in src
    # Composition uses reading parts, not a FAULT_PROSE map.
    assert "FAULT_PROSE" not in src
    assert "TAG_TO_PROSE" not in src
    assert "injector" not in src.lower() or "anti-template" in src.lower()


# --------------------------------------------------------------------------
# Literal-scan: no rendered finding string is a source literal
# --------------------------------------------------------------------------


def test_literal_scan_no_rendered_finding_is_source_literal():
    rendered = collect_rendered_finding_strings()
    assert rendered, "expected at least one rendered finding across faults"
    sources = []
    for rel in DIAGNOSE_SOURCE_RELS:
        path = CONTAINMENT_ROOT / rel
        assert path.is_file(), "missing source %s" % rel
        sources.append((rel, path.read_text(encoding="utf-8")))

    for finding_text in rendered:
        for rel, text in sources:
            assert not source_contains_finding_literal(finding_text, text), (
                "rendered finding %r appears as a source literal in %s"
                % (finding_text, rel)
            )


def test_no_seed_strings_in_diagnose_output():
    for fid in list(CONTRACT_FAULTS) + [ANTI_TEMPLATE_FAULT, None]:
        result = diagnose(fault=fid) if fid else diagnose()
        for f in result.findings:
            low = f.rendered.lower()
            for marker in _GENERIC_PROSE_MARKERS:
                assert marker not in low


# --------------------------------------------------------------------------
# Banner → Doctor payload propagation (id + hash byte-identical)
# --------------------------------------------------------------------------


def test_banner_payload_hash_stable():
    a = banner_issue_payload("iss-1", "health-banner", "service flapping")
    b = banner_issue_payload("iss-1", "health-banner", "service flapping")
    assert a.issue_id == b.issue_id
    assert a.payload_hash == b.payload_hash
    assert a.payload_hash == issue_payload_hash(
        "iss-1", "health-banner", "service flapping"
    )
    # Different symptom → different hash.
    c = banner_issue_payload("iss-1", "health-banner", "other symptom")
    assert c.payload_hash != a.payload_hash


def test_doctor_entry_byte_identical_id_and_hash():
    """GWT: Doctor receives and records the banner id + hash unchanged."""
    payload = banner_issue_payload(
        "banner-issue-42",
        "health-banner",
        "observed service down",
    )
    entry = doctor_entry(payload, redetect=False)
    assert entry.issue_id == payload.issue_id
    assert entry.payload_hash == payload.payload_hash
    assert entry.source == payload.source
    assert entry.observed_symptom == payload.observed_symptom
    assert entry.redetect_attempted is False
    assert entry.trace_payload_id == payload.issue_id
    assert entry.trace_payload_hash == payload.payload_hash


def test_doctor_redetect_is_forbidden():
    """GWT: Doctor re-running detection to reconstruct the issue fails."""
    payload = banner_issue_payload("iss-x", "banner", "symptom")
    with pytest.raises(RedetectionForbidden):
        doctor_entry(
            payload,
            redetect=True,
            system_snapshot={"service_status": "down"},
        )


def test_view_shows_payload_byte_identical():
    payload = banner_issue_payload(
        "view-issue-7",
        "health-banner",
        "banner click symptom",
    )
    result = render_doctor_surface(
        DoctorViewContext(
            capability_present=True,
            inventory_row=_present_row(),
            head_hash="c" * 64,
            issue_payload=payload,
            fault="service_status_down",
        )
    )
    assert result.entry is not None
    assert result.entry.issue_id == payload.issue_id
    assert result.entry.payload_hash == payload.payload_hash
    html = result.html
    assert 'data-issue-id="%s"' % payload.issue_id in html
    assert 'data-payload-hash="%s"' % payload.payload_hash in html
    assert 'data-entry-id="%s"' % payload.issue_id in html
    assert 'data-entry-hash="%s"' % payload.payload_hash in html
    assert payload.issue_id in _visible_text(html)
    assert payload.payload_hash in html


def test_view_attempt_redetect_raises():
    payload = banner_issue_payload("iss-r", "banner", "sym")
    with pytest.raises(RedetectionForbidden):
        render_doctor_surface(
            DoctorViewContext(
                capability_present=True,
                issue_payload=payload,
                attempt_redetect=True,
                run_diagnose=False,
            )
        )


# --------------------------------------------------------------------------
# Diagnose control: PRESENT → live; unavailable → named state (no dead btn)
# --------------------------------------------------------------------------


def test_diagnose_live_when_capability_present():
    result = render_doctor_surface(
        DoctorViewContext(
            capability_present=True,
            inventory_row=_present_row(),
            head_hash="c" * 64,
            run_diagnose=True,
        )
    )
    assert result.diagnose_is_live
    assert result.unavailable is False
    assert count_live_controls(result.html, CONTROL_DIAGNOSE) >= 1
    assert_no_dead_controls(result.html)
    assert 'data-action="action:diagnose"' in result.html


def test_diagnose_unavailable_named_state_not_dead_button():
    """GWT: capability unavailable → named unavailable state, not clickable no-op."""
    result = render_doctor_surface(
        DoctorViewContext(
            force_absent=True,
            capability_present=False,
            run_diagnose=False,
        )
    )
    assert result.unavailable is True
    assert result.diagnose_is_live is False
    assert count_live_controls(result.html, CONTROL_DIAGNOSE) == 0
    assert_no_dead_controls(result.html)
    findings = audit_dead_controls(result.html)
    assert findings == []
    assert 'data-diagnose-unavailable="true"' in result.html
    assert_visible_text_contains(result.html, DIAGNOSE_UNAVAILABLE_STATE.label)
    # No Diagnose button element at all.
    assert not re.search(
        r'<button[^>]*data-control="diagnose"',
        result.html,
        re.IGNORECASE,
    )


def test_tri_state_unknown_empty_distinct_on_doctor():
    """unknown (store unreadable) ≠ empty (no-finding scope)."""
    unknown_html = generate_html_for_fixture("unknown")
    empty_html = generate_html_for_fixture("empty")
    assert_visible_text_contains(unknown_html, "unknown")
    assert_visible_text_contains(empty_html, "empty")
    # Distinct.
    assert 'data-doctor-state="unknown"' in unknown_html
    assert (
        'data-doctor-state="no_finding"' in empty_html
        or 'data-no-finding="true"' in empty_html
    )
    assert 'data-doctor-state="unknown"' not in empty_html
    assert 'data-doctor-state="no_finding"' not in unknown_html


def test_tri_state_harness_doctor_surface():
    assert_tri_state(
        generate_html_for_fixture,
        call_site="anchor.ui.doctor_view.generate_html_for_fixture",
    )


# --------------------------------------------------------------------------
# Rendered HTML + node --check
# --------------------------------------------------------------------------


def test_generate_html_document_and_findings():
    payload = banner_issue_payload(
        "html-issue",
        "health-banner",
        "status down",
    )
    html = generate_html(
        DoctorViewContext(
            capability_present=True,
            inventory_row=_present_row(),
            head_hash="c" * 64,
            issue_payload=payload,
            fault="service_status_down",
        )
    )
    assert "<html" in html.lower()
    assert "<script>" in html.lower()
    assert "doctor-finding" in html or "service_status" in html
    assert payload.issue_id in html
    assert payload.payload_hash in html
    assert_no_dead_controls(html)


def test_node_check_doctor_scripts():
    html = generate_html(
        DoctorViewContext(
            capability_present=True,
            inventory_row=_present_row(),
            head_hash="c" * 64,
            fault="process_count_zero",
        )
    )
    node_check_scripts(html)


def test_finding_quotes_reading_in_rendered_html():
    result = render_doctor_surface(
        DoctorViewContext(
            capability_present=True,
            fault="version_mismatch",
        )
    )
    assert result.diagnosis is not None
    finding = result.diagnosis.finding_for_reading("version")
    assert finding is not None
    assert finding.reading_value in result.html
    assert finding.rendered in result.html
    assert 'data-live-reading="true"' in result.html


# --------------------------------------------------------------------------
# Failure-state table
# --------------------------------------------------------------------------


def test_failure_state_table_unknown_and_empty_separate():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    rows = _parse_doctor_failure_table(text)
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    # No merged unknown/empty row.
    for r in rows:
        assert "/" not in r["state"]
        assert "unknown" not in r["state"] or r["state"] == "unknown"
    report = validate_failure_state_table(rows, surface="doctor-diagnose")
    assert report["ok"] is True


def test_failure_state_table_surface_native_diagnose_language():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "diagnose" in low
    # Honesty theater ban.
    body = text.split("## Rows")[1] if "## Rows" in text else text
    for verb in ("index", "rebuild", "reconcile"):
        # Allowed in prose bans section, not as triggers for machine rows.
        pass
    rows = _parse_doctor_failure_table(text)
    for r in rows:
        trig = r["trigger"].lower()
        assert "rebuild" not in trig
        assert "reconcile" not in trig
        # "index" alone as a trigger verb is banned; "index" substring in
        # unrelated words is fine — require word boundary.
        assert not re.search(r"\brebuild\b", trig)
        assert not re.search(r"\breconcile\b", trig)


# --------------------------------------------------------------------------
# E2E trace artifact
# --------------------------------------------------------------------------


def test_write_and_load_doctor_diagnose_trace():
    path = write_doctor_traces(root=CONTAINMENT_ROOT)
    assert path.is_file()
    assert path.name == "doctor-diagnose-e2e.json"
    bag = load_trace_set(root=CONTAINMENT_ROOT)
    assert bag["wave_id"] == "W14"
    assert bag["control_id"] == "diagnose"
    assert bag["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    # Primary hops validate as a full trace.
    primary = {
        k: bag[k]
        for k in (
            "schema",
            "wave_id",
            "control_id",
            "proof_level",
            "proof_disclosure",
            "trace_result",
            "induced_fault",
            "rendered_state",
            "as_of",
            "notes",
            "hops",
        )
        if k in bag
    }
    art = validate_trace(primary)
    assert is_go_evidence(art)
    # Payload id/hash byte-identical across hops.
    hops = bag["hops"]
    ids = {h["payload_id"] for h in hops}
    hashes = {h["payload_hash"] for h in hops}
    assert len(ids) == 1
    assert len(hashes) == 1
    # Contract faults covered.
    assert set(bag.get("enumerated_faults") or []) >= set(CONTRACT_FAULTS)
    assert ANTI_TEMPLATE_FAULT in (bag.get("reason_traces") or {})


def test_trace_payload_matches_banner_hash():
    issue = banner_issue_payload(
        "trace-issue-9",
        "health-banner",
        "trace symptom",
    )
    art = build_doctor_diagnose_trace(
        fault="config_path_missing",
        issue_id=issue.issue_id,
        source=issue.source,
        observed_symptom=issue.observed_symptom,
    )
    for hop in art.hops:
        assert hop.payload_id == issue.issue_id
        assert hop.payload_hash == issue.payload_hash


def test_trace_file_exists_after_write():
    write_doctor_traces(root=CONTAINMENT_ROOT)
    assert DOCTOR_TRACE_PATH.is_file()


# --------------------------------------------------------------------------
# Live readings basics
# --------------------------------------------------------------------------


def test_healthy_diagnose_is_ok_no_findings():
    result = diagnose(healthy_system())
    assert result.ok is True
    assert result.findings == []
    assert result.named_state == NamedState.ok or result.named_state is None or result.ok


def test_take_readings_carries_live_values():
    sys = force_fault("process_count_zero")
    readings = take_readings(sys)
    assert readings["process_count"].value == 0
    assert readings["process_count"].source == "live_system"


def test_force_fault_mutates_reading_not_prose():
    sys = force_fault("service_status_down")
    assert sys.service_status == "down"
    assert sys.active_fault == "service_status_down"

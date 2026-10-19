"""W9 — End-to-end trace schema, fault injection, EXECUTION-LOG schema.

Exercises every W9 deliverable under one scoped gate:

* ``anchor/build/trace_artifact.py``
* ``tools/fault_inject.py``
* ``anchor/build/execution_log.py``
* ``tools/attestation.py``

Gate: pytest -v tests/test_trace_and_faults_2026_07_29.py

GWTs (frozen plan):

* Surface GREEN with no trace → execution_log.append rejects citing
  ``no end-to-end trace`` and the wave is not GO.
* Sub-agent-authored attestation → attestation.count_attestations counts
  zero and reports the claim as non-evidence.
* Trace missing proof_level, or claiming a human-driven user path →
  schema validator rejects (only S1 may claim the user path).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from anchor.build import execution_log as elog
from anchor.build import trace_artifact as ta
from anchor.build.execution_log import (
    GO,
    NO_E2E_TRACE_MESSAGE,
    NOT_GO,
    AppendResult,
    ExecutionLogError,
    IllegalAttestationSource,
    MissingCommitSha,
    NoEndToEndTrace,
    append,
    is_surface_wave,
    make_row,
    validate_row,
)
from anchor.build.trace_artifact import (
    HOP_CAPABILITY_CALL,
    HOP_CONTROL_INVOCATION,
    HOP_HANDLER,
    HOP_RENDERED_STATE,
    PROOF_LEVEL_HUMAN_PATH,
    PROOF_LEVEL_RENDERED_STRING,
    REQUIRED_HOP_KINDS,
    TRACE_RESULT_COMPLETED,
    TRACE_RESULT_DEAD,
    TraceHop,
    TraceValidationError,
    build_trace,
    emit_trace,
    is_go_evidence,
    make_hop,
    payload_hash,
    validate_trace,
)
from tools import attestation as att
from tools import fault_inject as fi
from tools.attestation import (
    SOURCE_HOST,
    SOURCE_ORCHESTRATOR,
    SOURCE_SUB_AGENT,
    SUB_AGENT_NON_EVIDENCE_MESSAGE,
    AttestationClaim,
    classify_attestation,
    compute_host_attestation,
    count_attestations,
    reject_sub_agent_attestation,
)
from tools.fault_inject import (
    NAMED_FAILURE_REASONS,
    ProductionFaultRefuse,
    UnknownFaultReason,
    clear_faults,
    coverage_report,
    induce_fault,
    induce_one_per_reason,
    named_failure_reasons,
    require_one_per_reason,
)

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_faults_between_tests():
    clear_faults()
    yield
    clear_faults()


def _four_hops(payload_id: str = "pay-1", payload: object = None) -> list:
    if payload is None:
        payload = {"id": payload_id, "v": 1}
    ph = payload_hash(payload)
    return [
        make_hop(HOP_CONTROL_INVOCATION, "click-open", payload_id=payload_id, payload=payload),
        make_hop(HOP_HANDLER, "open_work.handle", payload_id=payload_id, payload_hash_value=ph),
        make_hop(
            HOP_CAPABILITY_CALL,
            "capability.open",
            payload_id=payload_id,
            payload_hash_value=ph,
        ),
        make_hop(
            HOP_RENDERED_STATE,
            "render_state.ok",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="ok",
        ),
    ]


def _valid_trace(
    wave_id: str = "W10",
    control_id: str = "open",
    **kwargs,
):
    return build_trace(
        wave_id,
        control_id,
        _four_hops(),
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_COMPLETED,
        rendered_state="ok",
        **kwargs,
    )


# --------------------------------------------------------------------------
# Acceptance: every new module is imported and exercised by this gate
# --------------------------------------------------------------------------


def test_w9_modules_importable_and_callable():
    assert callable(build_trace)
    assert callable(validate_trace)
    assert callable(emit_trace)
    assert callable(induce_fault)
    assert callable(induce_one_per_reason)
    assert callable(append)
    assert callable(validate_row)
    assert callable(compute_host_attestation)
    assert callable(count_attestations)
    assert ta.TRACE_SCHEMA.startswith("end-to-end-trace")
    assert elog.EXECUTION_LOG_SCHEMA.startswith("execution-log-row")
    assert att.HOST_ATTESTATION_SCHEMA.startswith("host-attestation")
    assert set(named_failure_reasons()) == set(NAMED_FAILURE_REASONS)


# --------------------------------------------------------------------------
# Trace schema — hops, payload id/hash, proof_level
# --------------------------------------------------------------------------


def test_build_trace_stamps_rendered_string_proof_level():
    art = _valid_trace()
    assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
    assert art.wave_id == "W10"
    assert len(art.hops) == 4
    assert [h.kind for h in art.hops] == list(REQUIRED_HOP_KINDS)
    for h in art.hops:
        assert h.payload_id
        assert len(h.payload_hash) == 64


def test_each_hop_records_payload_id_and_hash():
    payload = {"session": "s-9", "n": 2}
    pid = "payload-abc"
    hops = _four_hops(payload_id=pid, payload=payload)
    art = build_trace("W11", "attach", hops)
    expected = payload_hash(payload)
    for hop in art.hops:
        assert hop.payload_id == pid
        assert hop.payload_hash == expected


def test_gwt_missing_proof_level_is_rejected():
    """Given a trace artifact with no proof_level stamp, when the schema
    validator runs, then it rejects the artifact."""
    hops = [h.as_dict() for h in _four_hops()]
    raw = {
        "wave_id": "W10",
        "control_id": "open",
        "hops": hops,
        "trace_result": TRACE_RESULT_COMPLETED,
        # proof_level deliberately omitted
    }
    with pytest.raises(TraceValidationError) as ei:
        validate_trace(raw)
    msg = str(ei.value).lower()
    assert "proof_level" in msg
    assert "rendered-string" in msg


def test_gwt_empty_proof_level_is_rejected():
    hops = [h.as_dict() for h in _four_hops()]
    raw = {
        "wave_id": "W10",
        "control_id": "open",
        "hops": hops,
        "proof_level": "",
        "trace_result": TRACE_RESULT_COMPLETED,
    }
    with pytest.raises(TraceValidationError) as ei:
        validate_trace(raw)
    assert "proof_level" in str(ei.value).lower()


def test_gwt_human_driven_user_path_claim_is_rejected():
    """Given a trace claiming a human-driven user path, when the schema
    validator runs, then it rejects — only S1 may claim the user path."""
    with pytest.raises(TraceValidationError) as ei:
        build_trace(
            "W10",
            "open",
            _four_hops(),
            proof_level=PROOF_LEVEL_HUMAN_PATH,
        )
    msg = str(ei.value).lower()
    assert "user path" in msg or "human" in msg
    assert "s1" in msg


def test_gwt_human_path_claim_in_notes_is_rejected():
    with pytest.raises(TraceValidationError) as ei:
        build_trace(
            "W10",
            "open",
            _four_hops(),
            proof_level=PROOF_LEVEL_RENDERED_STRING,
            notes="human-driven user path proven live",
        )
    assert "user path" in str(ei.value).lower() or "human" in str(ei.value).lower()


def test_s1_allow_human_path_flag_accepts_only_when_explicit():
    art = validate_trace(
        {
            "wave_id": "W22",
            "control_id": "s1-open",
            "hops": [h.as_dict() for h in _four_hops()],
            "proof_level": PROOF_LEVEL_HUMAN_PATH,
            "trace_result": TRACE_RESULT_COMPLETED,
            "proof_disclosure": "S1 live session",
        },
        allow_human_path=True,
    )
    assert art.proof_level == PROOF_LEVEL_HUMAN_PATH


def test_missing_capability_hop_fails_schema():
    hops = [
        make_hop(HOP_CONTROL_INVOCATION, "click", payload_id="p", payload="x"),
        make_hop(HOP_HANDLER, "handler", payload_id="p", payload="x"),
        # capability_call missing
        make_hop(HOP_RENDERED_STATE, "state", payload_id="p", payload="x"),
    ]
    with pytest.raises(TraceValidationError) as ei:
        build_trace("W10", "open", hops)
    assert "capability_call" in str(ei.value)


def test_null_capability_call_is_dead_control_signature():
    ph = payload_hash("x")
    hops = [
        TraceHop(HOP_CONTROL_INVOCATION, "click", "p", ph),
        TraceHop(HOP_HANDLER, "handler", "p", ph),
        TraceHop(HOP_CAPABILITY_CALL, "null", "p", ph),
        TraceHop(HOP_RENDERED_STATE, "state", "p", ph),
    ]
    with pytest.raises(TraceValidationError) as ei:
        build_trace("W10", "open", hops)
    assert "dead control" in str(ei.value).lower() or "capability" in str(ei.value).lower()


def test_hop_order_must_be_control_handler_capability_state():
    ph = payload_hash("x")
    hops = [
        TraceHop(HOP_HANDLER, "handler", "p", ph),
        TraceHop(HOP_CONTROL_INVOCATION, "click", "p", ph),
        TraceHop(HOP_CAPABILITY_CALL, "cap", "p", ph),
        TraceHop(HOP_RENDERED_STATE, "state", "p", ph),
    ]
    with pytest.raises(TraceValidationError) as ei:
        build_trace("W10", "open", hops)
    assert "order" in str(ei.value).lower()


def test_is_go_evidence_rejects_dead_result():
    art = build_trace(
        "W10",
        "open",
        _four_hops(),
        trace_result=TRACE_RESULT_DEAD,
    )
    # Schema accepts dead as a document, but it is never GO evidence.
    assert not is_go_evidence(art)


def test_emit_and_load_trace_roundtrip(tmp_path: Path):
    art = _valid_trace("W12", "usage")
    path = emit_trace(art, root=tmp_path)
    assert path.is_file()
    # Containment: written under tmp_path/artifacts/traces/
    assert "traces" in path.parts
    loaded = ta.load_trace(path, root=tmp_path)
    assert loaded.wave_id == "W12"
    assert loaded.control_id == "usage"
    assert loaded.proof_level == PROOF_LEVEL_RENDERED_STRING
    assert "human-driven user path deferred to s1" in loaded.proof_disclosure.lower()


def test_proof_disclosure_on_face_defers_user_path_to_s1():
    art = _valid_trace()
    d = art.as_dict()
    assert d["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    assert "s1" in d["proof_disclosure"].lower()
    assert "not a north star" in d["proof_disclosure"].lower()


# --------------------------------------------------------------------------
# Fault injection — one per named failure reason (E4 reduced form)
# --------------------------------------------------------------------------


def test_named_failure_reasons_are_exactly_five():
    assert named_failure_reasons() == (
        "timeout",
        "missing_capability",
        "empty_result_set",
        "unmeasured_cost",
        "stale_telemetry",
    )


def test_induce_one_per_reason_covers_all_named_reasons():
    induced = induce_one_per_reason(force_production=False)
    assert set(induced.keys()) == set(NAMED_FAILURE_REASONS)
    report = coverage_report(induced)
    assert report["one_per_reason_complete"] is True
    assert report["e4_reduced_form"] == "one-per-reason"
    require_one_per_reason(induced)  # does not raise


def test_induce_each_named_reason_individually():
    for reason in NAMED_FAILURE_REASONS:
        clear_faults()
        fault = induce_fault(reason, force_production=False)
        assert fault.reason == reason
        assert fault.active is True
        assert fault.label
        assert fault.default_state
        assert fi.is_induced(reason)


def test_unknown_fault_reason_raises():
    with pytest.raises(UnknownFaultReason):
        induce_fault("network-partition-xyz", force_production=False)


def test_production_context_refuses_fault_injection():
    with pytest.raises(ProductionFaultRefuse) as ei:
        induce_fault("timeout", force_production=True)
    assert "production" in str(ei.value).lower()


def test_require_one_per_reason_fails_when_incomplete():
    induce_fault("timeout", force_production=False)
    with pytest.raises(fi.FaultInjectionError) as ei:
        require_one_per_reason()
    assert "missing" in str(ei.value).lower()


def test_trace_can_record_induced_fault():
    fault = induce_fault("timeout", force_production=False)
    art = build_trace(
        "W11",
        "attach",
        _four_hops(),
        induced_fault=fault.reason,
        trace_result="failed_with_named_state",
        rendered_state="timeout",
    )
    assert art.induced_fault == "timeout"
    assert is_go_evidence(art)


# --------------------------------------------------------------------------
# Attestation — host-computed counts; sub-agent does not
# --------------------------------------------------------------------------


def test_compute_host_attestation_is_evidence():
    a = compute_host_attestation(
        wave_id="W9",
        gate_command="pytest -v tests/test_trace_and_faults_2026_07_29.py",
        pass_count=12,
        fail_count=0,
        test_names=("test_a", "test_b"),
        commit_sha="abc1234",
        source=SOURCE_HOST,
    )
    assert a.source == SOURCE_HOST
    assert a.kind == att.KIND_EVIDENCE
    assert a.content_hash
    assert len(a.content_hash) == 64
    cls = classify_attestation(a)
    assert cls.counts is True
    assert cls.is_evidence is True


def test_orchestrator_source_counts_as_evidence():
    a = compute_host_attestation(
        wave_id="W9",
        gate_command="pytest -v tests/test_trace_and_faults_2026_07_29.py",
        pass_count=3,
        source=SOURCE_ORCHESTRATOR,
    )
    result = count_attestations([a])
    assert result.evidence_count == 1
    assert result.non_evidence_count == 0


def test_gwt_sub_agent_attestation_counts_zero_as_non_evidence():
    """Given an attestation string written by a sub-agent into its report,
    when attestation.py counts attestations, then it counts zero and reports
    the sub-agent-authored claim as non-evidence."""
    claim_text = (
        "sub-agent report: all 47 tests passed; wave GREEN; "
        "attestation authored by execute agent"
    )
    result = count_attestations([claim_text])
    assert result.evidence_count == 0
    assert result.non_evidence_count >= 1
    assert any(
        SUB_AGENT_NON_EVIDENCE_MESSAGE in m or "non-evidence" in m
        for m in result.non_evidence_messages
    )


def test_gwt_sub_agent_claim_object_counts_zero():
    claim = AttestationClaim(
        source=SOURCE_SUB_AGENT,
        text="I (sub-agent) attest 20/20 passed",
        pass_count=20,
        origin="sub-agent report",
    )
    result = count_attestations([claim])
    assert result.evidence_count == 0
    assert result.non_evidence_count == 1
    assert SUB_AGENT_NON_EVIDENCE_MESSAGE in result.non_evidence_messages


def test_reject_sub_agent_attestation_explicit_path():
    cls = reject_sub_agent_attestation("agent says green")
    assert cls.counts is False
    assert cls.kind == att.KIND_NON_EVIDENCE
    assert SUB_AGENT_NON_EVIDENCE_MESSAGE in cls.message


def test_mixed_claims_only_host_counts():
    host = compute_host_attestation(
        wave_id="W9",
        gate_command="pytest -v tests/test_trace_and_faults_2026_07_29.py",
        pass_count=5,
        source=SOURCE_HOST,
    )
    sub = AttestationClaim(source=SOURCE_SUB_AGENT, text="sub-agent: 5 passed")
    result = count_attestations([host, sub, "sub-agent authored: still green"])
    assert result.evidence_count == 1
    assert result.non_evidence_count == 2


def test_compute_host_attestation_rejects_sub_agent_source():
    with pytest.raises(att.AttestationError):
        compute_host_attestation(
            wave_id="W9",
            gate_command="pytest -v tests/test_trace_and_faults_2026_07_29.py",
            pass_count=1,
            source=SOURCE_SUB_AGENT,
        )


# --------------------------------------------------------------------------
# EXECUTION-LOG append schema
# --------------------------------------------------------------------------


def test_make_row_requires_wave_commit_gate_attestation_delta():
    row = make_row(
        "W9",
        commit_sha="deadbee",
        gate_command="pytest -v tests/test_trace_and_faults_2026_07_29.py",
        attestation_source=SOURCE_ORCHESTRATOR,
        exit_register_delta={"signed_exits": 0},
    )
    validated = validate_row(row)  # W9 is not a surface wave — no trace needed
    assert validated.wave_id == "W9"
    assert validated.commit_sha == "deadbee"
    assert validated.attestation_source == SOURCE_ORCHESTRATOR
    assert validated.exit_register_delta == {"signed_exits": 0}


def test_missing_commit_sha_rejects():
    row = make_row(
        "W9",
        commit_sha="",
        gate_command="pytest -v tests/test_trace_and_faults_2026_07_29.py",
        attestation_source=SOURCE_ORCHESTRATOR,
        exit_register_delta={},
    )
    with pytest.raises(MissingCommitSha):
        validate_row(row)


def test_sub_agent_attestation_source_rejected_on_append():
    row = make_row(
        "W9",
        commit_sha="abc1234",
        gate_command="pytest -v tests/test_trace_and_faults_2026_07_29.py",
        attestation_source=SOURCE_SUB_AGENT,
        exit_register_delta={},
    )
    with pytest.raises(IllegalAttestationSource) as ei:
        validate_row(row)
    assert "orchestrator" in str(ei.value).lower() or "sub-agent" in str(ei.value).lower()


def test_gwt_surface_green_without_trace_rejected(tmp_path: Path):
    """Given a surface wave reporting GREEN with no trace artifact, when
    execution_log.append runs, then it rejects the row citing
    'no end-to-end trace' and the wave is not GO."""
    assert is_surface_wave("W10")
    # Isolated root so a real artifacts/traces/ tree cannot satisfy the check.
    row = make_row(
        "W10",
        commit_sha="abc1234",
        gate_command="pytest -v tests/test_open_run_2026_07_29.py",
        attestation_source=SOURCE_ORCHESTRATOR,
        exit_register_delta={},
        status=GO,
        # no trace_relpath, no trace_artifact
    )
    with pytest.raises(NoEndToEndTrace) as ei:
        append(row, root=tmp_path, dry_run=True)
    msg = str(ei.value).lower()
    assert NO_E2E_TRACE_MESSAGE in msg
    assert not elog.is_go(row, root=tmp_path)


def test_gwt_surface_green_with_valid_trace_is_go(tmp_path: Path):
    art = _valid_trace("W10", "open")
    emit_trace(art, root=tmp_path)
    row = make_row(
        "W10",
        commit_sha="abc1234f",
        gate_command="pytest -v tests/test_open_run_2026_07_29.py",
        attestation_source=SOURCE_ORCHESTRATOR,
        exit_register_delta={"signed_exits": 0},
        status=GO,
    )
    result = append(row, root=tmp_path, dry_run=False)
    assert isinstance(result, AppendResult)
    assert result.ok is True
    assert result.go is True
    assert result.row is not None
    assert result.row.commit_sha == "abc1234f"
    # Log file written under containment root.
    log_path = tmp_path / elog.EXECUTION_LOG_RELPATH
    assert log_path.is_file()
    text = log_path.read_text(encoding="utf-8")
    assert "W10" in text
    assert "abc1234f" in text
    assert "orchestrator" in text


def test_surface_green_with_in_memory_trace_artifact_is_go(tmp_path: Path):
    art = _valid_trace("W15", "preview")
    row = make_row(
        "W15",
        commit_sha="fedcba9",
        gate_command="pytest -v tests/test_preview_2026_07_29.py",
        attestation_source=SOURCE_HOST,
        exit_register_delta={},
        status="GREEN",
    )
    validated = validate_row(row, root=tmp_path, trace_artifact=art)
    assert validated.status == GO
    # Without a trace artifact or on-disk trace, the same GREEN row is not GO.
    bare = make_row(
        "W15",
        commit_sha="fedcba9",
        gate_command="pytest -v tests/test_preview_2026_07_29.py",
        attestation_source=SOURCE_HOST,
        exit_register_delta={},
        status=GO,
    )
    assert elog.is_go(bare, root=tmp_path) is False
    result = append(row, root=tmp_path, dry_run=True, trace_artifact=art)
    assert result.go is True


def test_phase2_primitive_wave_green_without_trace_is_allowed():
    """W9 itself is not a surface wave — GREEN needs no e2e trace."""
    assert not is_surface_wave("W9")
    row = make_row(
        "W9",
        commit_sha="1234567",
        gate_command="pytest -v tests/test_trace_and_faults_2026_07_29.py",
        attestation_source=SOURCE_ORCHESTRATOR,
        exit_register_delta={"signed_exits": 0},
        status=GO,
    )
    validated = validate_row(row)
    assert validated.status == GO


def test_not_go_surface_row_does_not_require_trace():
    row = make_row(
        "W10",
        commit_sha="abc1234",
        gate_command="pytest -v tests/test_open_run_2026_07_29.py",
        attestation_source=SOURCE_ORCHESTRATOR,
        exit_register_delta={},
        status=NOT_GO,
    )
    validated = validate_row(row)
    assert validated.status == NOT_GO
    assert not elog.is_go(validated)


def test_append_writes_required_fields_in_markdown(tmp_path: Path):
    row = make_row(
        "W8",
        commit_sha="aabbccd",
        gate_command="pytest -v tests/test_conformance_harness_2026_07_29.py",
        attestation_source=SOURCE_ORCHESTRATOR,
        exit_register_delta={"delta": "none"},
        status=GO,
        note="phase-2 primitive",
        pass_count=10,
        fail_count=0,
    )
    result = append(row, root=tmp_path)
    text = (tmp_path / "EXECUTION-LOG.md").read_text(encoding="utf-8")
    assert "wave_id" in text or "W8" in text
    assert "aabbccd" in text
    assert "gate" in text.lower()
    assert "attestation_source" in text
    assert "exit_register_delta" in text
    assert result.written_path == "EXECUTION-LOG.md"


def test_is_surface_wave_bounds():
    assert not is_surface_wave("W1")
    assert not is_surface_wave("W9")
    assert is_surface_wave("W10")
    assert is_surface_wave("W21")
    assert not is_surface_wave("W22")
    assert not is_surface_wave("not-a-wave")


# --------------------------------------------------------------------------
# Integration: surface wave GREEN path under induced fault + host attestation
# --------------------------------------------------------------------------


def test_surface_wave_end_to_end_under_induced_fault(tmp_path: Path):
    """done-when: emit schema-valid e2e trace, inject one fault per reason,
    append EXECUTION-LOG row with host attestation + commit SHA."""
    induced = induce_one_per_reason(force_production=False)
    require_one_per_reason(induced)

    # One representative fault recorded on the trace (timeout).
    art = build_trace(
        "W10",
        "open",
        _four_hops(payload_id="e2e-1", payload={"control": "open", "fault": "timeout"}),
        induced_fault="timeout",
        trace_result="failed_with_named_state",
        rendered_state="timeout",
        proof_level=PROOF_LEVEL_RENDERED_STRING,
    )
    assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
    path = emit_trace(art, root=tmp_path)
    assert path.is_file()

    host_att = compute_host_attestation(
        wave_id="W10",
        gate_command="pytest -v tests/test_open_run_2026_07_29.py",
        pass_count=8,
        fail_count=0,
        commit_sha="c0ffee1",
        source=SOURCE_HOST,
        files_touched=("anchor/session/open_work.py",),
    )
    counted = count_attestations([host_att])
    assert counted.evidence_count == 1

    row = make_row(
        "W10",
        commit_sha="c0ffee1",
        gate_command="pytest -v tests/test_open_run_2026_07_29.py",
        attestation_source=SOURCE_ORCHESTRATOR,
        exit_register_delta={"signed_exits_before": 0, "signed_exits_after": 0},
        status=GO,
        pass_count=8,
        fail_count=0,
        note="e2e under induced timeout; host attestation counted",
    )
    result = append(row, root=tmp_path, trace_artifact=art)
    assert result.go is True
    assert result.row is not None
    assert result.row.commit_sha == "c0ffee1"
    assert result.row.attestation_source in {SOURCE_ORCHESTRATOR, SOURCE_HOST}

    # Sub-agent claim still counts zero even when a host attestation exists.
    sub_result = count_attestations(
        [
            host_att,
            "sub-agent report: I also attest GREEN",
        ]
    )
    assert sub_result.evidence_count == 1
    assert sub_result.non_evidence_count == 1


def test_no_absolute_host_paths_in_w9_module_source():
    """Acceptance checklist (2): no absolute host paths in shipped strings."""
    modules = [
        CONTAINMENT_ROOT / "anchor" / "build" / "trace_artifact.py",
        CONTAINMENT_ROOT / "anchor" / "build" / "execution_log.py",
        CONTAINMENT_ROOT / "tools" / "fault_inject.py",
        CONTAINMENT_ROOT / "tools" / "attestation.py",
    ]
    banned = ("C:\\Users\\", "C:/Users/", "/Users/", "C:\\dev\\")
    for mod in modules:
        text = mod.read_text(encoding="utf-8")
        for b in banned:
            assert b not in text, "%s contains banned path fragment %r" % (mod.name, b)


def test_trace_json_serializable_without_host_paths():
    art = _valid_trace()
    raw = json.dumps(art.as_dict())
    assert "C:\\" not in raw
    assert "/Users/" not in raw
    data = json.loads(raw)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING

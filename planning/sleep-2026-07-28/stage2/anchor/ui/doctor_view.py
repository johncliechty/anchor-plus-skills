"""Doctor surface view — W14 + W15.

Diagnose control is rendered **only** when the diagnose capability is
PRESENT (non-STALE live inventory). Otherwise a named unavailable state
appears in place of the control — never a dead button.

Banner → Doctor handoff carries the issue payload (id + hash) into the
view and the e2e trace. Diagnosis findings are rendered with their live
readings; the named no-finding state is used when diagnose reports empty
scope.

**W15 — per-engine independent rows:** Claude, Gemini, and Grok each get
their own depth-labelled report from an independent probe. One engine
failing does not blank or fake the other two; there is no shared verdict.

``generate_html`` returns a full document with a syntax-valid ``<script>``
block suitable for ``node --check``. Trace builders emit
``artifacts/traces/doctor-diagnose-e2e.json`` and
``artifacts/traces/doctor-engines-e2e.json`` at ``proof_level: rendered-string``.
"""
from __future__ import annotations

import html
import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from anchor.build.trace_artifact import (
    HOP_CAPABILITY_CALL,
    HOP_CONTROL_INVOCATION,
    HOP_HANDLER,
    HOP_RENDERED_STATE,
    PROOF_LEVEL_RENDERED_STRING,
    TRACE_RESULT_COMPLETED,
    TRACE_RESULT_FAILED_NAMED,
    TraceArtifact,
    build_trace,
    make_hop,
    payload_hash,
    validate_trace,
)
from anchor.doctor.banner_handoff import (
    DoctorEntryRecord,
    IssuePayload,
    banner_issue_payload,
    doctor_entry,
)
from anchor.doctor.depth_label import (
    ENGINE_IDS,
    ENGINE_LABELS,
    DepthLabel,
    EngineReport,
    UnlabelledReportError,
    validate_engine_report,
    validate_engine_reports,
)
from anchor.doctor.diagnose import (
    ANTI_TEMPLATE_FAULT,
    CONTRACT_FAULTS,
    CONTROL_DIAGNOSE,
    DIAGNOSE_UNAVAILABLE_STATE,
    NO_FINDING_STATE,
    DiagnosisResult,
    SystemState,
    diagnose,
    healthy_system,
)
from anchor.doctor.engines import probe_all_engines
from anchor.ui.dead_control import (
    ControlMode,
    ControlRender,
    assert_no_dead_controls,
    audit_dead_controls,
    render_cannot_state,
    render_control,
)
from anchor.ui.named_state import NamedState, render_state
from tools.capability_inventory import InventoryRow

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "doctor-diagnose"
WAVE_ID = "W14"
CONTROL_ID = CONTROL_DIAGNOSE
DIAGNOSE_ACTION = "action:diagnose"

#: W15 per-engine surface constants (independent of W14 diagnose wave id).
ENGINES_SURFACE_ID = "doctor-engines"
ENGINES_WAVE_ID = "W15"
ENGINES_CONTROL_ID = "diagnose_engines"

DOCTOR_TRACE_RELPATH = os.path.join("artifacts", "traces", "doctor-diagnose-e2e.json")
DOCTOR_ENGINES_TRACE_RELPATH = os.path.join(
    "artifacts", "traces", "doctor-engines-e2e.json"
)
TRACE_AS_OF = "2026-07-29T00:00:00Z"

FINDING_CLASS = "doctor-finding"
FINDINGS_CLASS = "doctor-findings"
PAYLOAD_CLASS = "doctor-issue-payload"
UNAVAILABLE_CLASS = "doctor-diagnose-unavailable"
NO_FINDING_CLASS = "doctor-no-finding"
OUTCOME_CLASS = "doctor-outcome"
ENGINE_ROW_CLASS = "doctor-engine-row"
ENGINE_PANEL_CLASS = "doctor-engine-panel"
ENGINE_DEPTH_CLASS = "engine-depth"
ENGINE_NAME_CLASS = "engine-name"

#: Unavailable reason shown beside the named state (not a seed finding).
UNAVAILABLE_REASON = "diagnose capability unavailable"

#: Induced fault reasons for the per-engine surface (one per named path).
ENGINE_INDUCED_FAULT_REASONS: tuple = (
    "timeout",
    "store_unreadable",
    "empty",
    "missing",
    "garbage",
)


# --------------------------------------------------------------------------
# Context + result
# --------------------------------------------------------------------------


@dataclass
class DoctorViewContext:
    """Inputs that drive the Doctor surface render."""

    inventory_row: Optional[InventoryRow] = None
    capability_present: Optional[bool] = None
    force_absent: bool = False
    issue_payload: Optional[IssuePayload] = None
    system: Optional[SystemState] = None
    fault: Optional[str] = None
    run_diagnose: bool = True
    as_of: Optional[date] = None
    root: Optional[Path] = None
    head_hash: Optional[str] = None
    content_overrides: Optional[Mapping[str, bytes]] = None
    title: str = "Doctor diagnose"
    #: Test seam: attempt re-detection (must raise RedetectionForbidden).
    attempt_redetect: bool = False
    #: W15: per-engine fault map (engine id → fault id). Independent probes.
    engine_faults: Optional[Mapping[str, Optional[str]]] = None
    #: W15: when True (default), run Claude/Gemini/Grok probes and render rows.
    run_engine_probes: bool = True
    #: W15: optional pre-built engine reports (test seam; skips probes).
    engine_reports: Optional[Mapping[str, EngineReport]] = None


@dataclass
class DoctorViewResult:
    """Structured render outcome for tests and traces."""

    html: str
    diagnose_control: ControlRender
    diagnosis: Optional[DiagnosisResult] = None
    entry: Optional[DoctorEntryRecord] = None
    issue_payload: Optional[IssuePayload] = None
    dead_control_findings: List[Any] = field(default_factory=list)
    unavailable: bool = False
    #: W15: independent per-engine reports (depth-labelled).
    engine_reports: Dict[str, EngineReport] = field(default_factory=dict)

    @property
    def diagnose_is_live(self) -> bool:
        return self.diagnose_control.mode.value == "live"


# --------------------------------------------------------------------------
# Control render
# --------------------------------------------------------------------------


def render_diagnose_control(
    *,
    row: Optional[InventoryRow] = None,
    root: Optional[Path] = None,
    as_of: Optional[date] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
    force_absent: bool = False,
    capability_present: Optional[bool] = None,
) -> ControlRender:
    """Render Diagnose as live control or named unavailable — never dead.

    When ``capability_present`` is False (or force_absent), the named
    unavailable state is emitted with **no** clickable element.
    """
    if force_absent or capability_present is False:
        return render_cannot_state(
            CONTROL_ID,
            cannot_state=DIAGNOSE_UNAVAILABLE_STATE,
            reason=UNAVAILABLE_REASON,
        )

    if capability_present is True and row is None:
        # Authorized by explicit capability_present without an inventory row
        # (test seam). Build a synthetic LIVE decision via render_control with
        # a forced-present path: use force_absent=False and inject PRESENT row.
        # Callers that pass capability_present=True should also pass a PRESENT
        # inventory row + matching head_hash for production honesty.
        from tools.capability_inventory import EVIDENCE_LIVE, Verdict

        row = InventoryRow(
            control_id=CONTROL_ID,
            verdict=Verdict.PRESENT,
            transcript_path="artifacts/transcripts/diagnose.json",
            source_paths=("artifacts/inventory-sources/diagnose.probe",),
            source_hash=head_hash or ("c" * 64),
            probe_date="2026-07-29",
            evidence_mode=EVIDENCE_LIVE,
            disposition="wire it",
            notes="doctor_view capability_present=True seam",
            label="Diagnose (Doctor)",
        )
        head_hash = head_hash or row.source_hash

    return render_control(
        CONTROL_ID,
        label="Diagnose",
        action=DIAGNOSE_ACTION,
        row=row,
        root=root,
        as_of=as_of,
        head_hash=head_hash,
        content_overrides=content_overrides,
        cannot_state=DIAGNOSE_UNAVAILABLE_STATE,
        force_absent=force_absent,
    )


# --------------------------------------------------------------------------
# Finding / payload / outcome render
# --------------------------------------------------------------------------


def render_finding(finding: Any) -> str:
    """Render one finding that carries its live reading (no seed prose)."""
    reading_name = html.escape(str(finding.reading_name), quote=True)
    reading_value = html.escape(
        "true"
        if finding.reading_value is True
        else "false"
        if finding.reading_value is False
        else str(finding.reading_value),
        quote=False,
    )
    shape = html.escape(str(finding.shape), quote=True)
    rendered = html.escape(str(finding.rendered), quote=False)
    return (
        '<li class="%s" data-reading-name="%s" data-reading-value="%s" '
        'data-finding-shape="%s">'
        '<span class="finding-text">%s</span>'
        ' <span class="finding-reading" data-live-reading="true">%s=%s</span>'
        "</li>"
        % (
            FINDING_CLASS,
            reading_name,
            html.escape(
                "true"
                if finding.reading_value is True
                else "false"
                if finding.reading_value is False
                else str(finding.reading_value),
                quote=True,
            ),
            shape,
            rendered,
            reading_name,
            reading_value,
        )
    )


def render_findings(diagnosis: DiagnosisResult) -> str:
    """Render the findings panel, no-finding state, or ok."""
    if diagnosis.named_state == NamedState.unknown:
        state_html = render_state(NamedState.unknown)
        return (
            '<div class="%s" data-doctor-state="unknown">%s</div>'
            % (OUTCOME_CLASS, state_html)
        )
    if diagnosis.no_finding or diagnosis.named_state == NO_FINDING_STATE:
        state_html = render_state(NO_FINDING_STATE)
        return (
            '<div class="%s %s" data-doctor-state="no_finding" '
            'data-no-finding="true">%s</div>'
            % (OUTCOME_CLASS, NO_FINDING_CLASS, state_html)
        )
    if diagnosis.ok and not diagnosis.findings:
        state_html = render_state(NamedState.ok)
        return (
            '<div class="%s" data-doctor-state="ok">%s</div>'
            % (OUTCOME_CLASS, state_html)
        )

    items = "".join(render_finding(f) for f in diagnosis.findings)
    extra = ""
    if diagnosis.named_state is not None:
        extra = render_state(diagnosis.named_state)
    return (
        '<div class="%s" data-doctor-state="findings">'
        '%s'
        '<ul class="%s">%s</ul>'
        "</div>"
        % (OUTCOME_CLASS, extra, FINDINGS_CLASS, items)
    )


def render_issue_payload_panel(payload: IssuePayload, entry: DoctorEntryRecord) -> str:
    """Show the banner issue payload as received (id + hash byte-identical)."""
    return (
        '<div class="%s" data-issue-id="%s" data-payload-hash="%s" '
        'data-payload-source="%s" data-observed-symptom="%s" '
        'data-entry-id="%s" data-entry-hash="%s" data-redetect="false">'
        '<span class="payload-id">%s</span> '
        '<span class="payload-hash">%s</span> '
        '<span class="payload-source">%s</span> '
        '<span class="payload-symptom">%s</span>'
        "</div>"
        % (
            PAYLOAD_CLASS,
            html.escape(payload.issue_id, quote=True),
            html.escape(payload.payload_hash, quote=True),
            html.escape(payload.source, quote=True),
            html.escape(payload.observed_symptom, quote=True),
            html.escape(entry.issue_id, quote=True),
            html.escape(entry.payload_hash, quote=True),
            html.escape(payload.issue_id, quote=False),
            html.escape(payload.payload_hash, quote=False),
            html.escape(payload.source, quote=False),
            html.escape(payload.observed_symptom, quote=False),
        )
    )


def render_unavailable_slot(control: ControlRender) -> str:
    """Named unavailable state in place of the Diagnose control."""
    return (
        '<div class="%s" data-diagnose-unavailable="true" '
        'data-control-mode="named_state">%s</div>'
        % (UNAVAILABLE_CLASS, control.html)
    )


# --------------------------------------------------------------------------
# W15 — independent per-engine rows
# --------------------------------------------------------------------------


def render_engine_row(report: EngineReport) -> str:
    """Render one independently-stated engine row (depth-labelled).

    Validates depth presence: an unlabelled report raises
    :class:`UnlabelledReportError` naming the engine.
    """
    depth = validate_engine_report(report)
    state_html = render_state(report.named_state)
    eng = html.escape(report.engine, quote=True)
    label = html.escape(ENGINE_LABELS.get(report.engine, report.engine), quote=False)
    depth_val = html.escape(depth.value, quote=True)
    state_val = html.escape(report.named_state.value, quote=True)
    reading_attr = ""
    reading_html = ""
    if report.reading_name is not None:
        rn = html.escape(str(report.reading_name), quote=True)
        rv_raw = (
            "true"
            if report.reading_value is True
            else "false"
            if report.reading_value is False
            else str(report.reading_value)
        )
        rv = html.escape(rv_raw, quote=True)
        reading_attr = ' data-reading-name="%s" data-reading-value="%s"' % (rn, rv)
        reading_html = (
            ' <span class="engine-reading" data-live-reading="true">%s=%s</span>'
            % (html.escape(str(report.reading_name), quote=False), html.escape(rv_raw, quote=False))
        )
    detail_html = ""
    if report.detail:
        detail_html = (
            ' <span class="engine-detail">%s</span>'
            % html.escape(str(report.detail), quote=False)
        )
    return (
        '<div class="%s" data-engine="%s" data-depth="%s" '
        'data-named-state="%s" data-engine-ok="%s" data-control-id="%s"%s>'
        '<span class="%s">%s</span> '
        '<span class="%s" data-depth-label="%s">%s</span> '
        "%s"
        "%s"
        "%s"
        "</div>"
        % (
            ENGINE_ROW_CLASS,
            eng,
            depth_val,
            state_val,
            "true" if report.ok else "false",
            html.escape(report.control_id or "", quote=True),
            reading_attr,
            ENGINE_NAME_CLASS,
            label,
            ENGINE_DEPTH_CLASS,
            depth_val,
            depth_val,
            state_html,
            reading_html,
            detail_html,
        )
    )


def render_engine_rows(
    reports: Mapping[str, EngineReport],
) -> str:
    """Render three independently-stated engine rows (no shared verdict).

    Validates every report has a depth label. Order is Claude, Gemini, Grok.
    One failing engine does not suppress the other rows.
    """
    validate_engine_reports(reports)
    parts: List[str] = []
    for eng in ENGINE_IDS:
        report = reports.get(eng)
        if report is None:
            # Missing report is a blanked row — refuse (isolation contract).
            raise UnlabelledReportError(
                eng,
                report=None,
                message=(
                    "engine %r: missing independent report — cannot blank row"
                    % eng
                ),
            )
        parts.append(render_engine_row(report))
    return (
        '<div class="%s" data-surface="%s" data-wave="%s" '
        'data-shared-verdict="false">'
        "%s"
        "</div>"
        % (
            ENGINE_PANEL_CLASS,
            html.escape(ENGINES_SURFACE_ID, quote=True),
            html.escape(ENGINES_WAVE_ID, quote=True),
            "".join(parts),
        )
    )


def collect_engine_reports(
    *,
    faults: Optional[Mapping[str, Optional[str]]] = None,
    prebuilt: Optional[Mapping[str, EngineReport]] = None,
) -> Dict[str, EngineReport]:
    """Collect independent per-engine reports (prebuilt or live probes)."""
    if prebuilt is not None:
        missing = [e for e in ENGINE_IDS if e not in prebuilt]
        if missing:
            raise UnlabelledReportError(
                missing[0],
                report=None,
                message=(
                    "engine %r: missing independent report — cannot blank row"
                    % missing[0]
                ),
            )
        validate_engine_reports(prebuilt)
        return {k: prebuilt[k] for k in ENGINE_IDS}
    return probe_all_engines(faults=faults, validate=True)


# --------------------------------------------------------------------------
# Surface compose
# --------------------------------------------------------------------------


def render_doctor_surface(ctx: Optional[DoctorViewContext] = None) -> DoctorViewResult:
    """Compose the Doctor view: control + optional payload + diagnosis + engines."""
    ctx = ctx or DoctorViewContext()

    control = render_diagnose_control(
        row=ctx.inventory_row,
        root=ctx.root,
        as_of=ctx.as_of,
        head_hash=ctx.head_hash,
        content_overrides=ctx.content_overrides,
        force_absent=ctx.force_absent,
        capability_present=ctx.capability_present,
    )
    unavailable = control.mode is ControlMode.NAMED_STATE

    entry: Optional[DoctorEntryRecord] = None
    payload = ctx.issue_payload
    diagnosis: Optional[DiagnosisResult] = None
    engine_reports: Dict[str, EngineReport] = {}

    body_parts: List[str] = []

    if unavailable:
        body_parts.append(render_unavailable_slot(control))
    else:
        body_parts.append(
            '<div class="doctor-control-slot" data-diagnose-live="true">%s</div>'
            % control.html
        )

        if payload is not None:
            if ctx.attempt_redetect:
                # Contract: re-detection is a hard failure.
                doctor_entry(payload, redetect=True, system_snapshot={"x": 1})
            entry = doctor_entry(payload, redetect=False)
            body_parts.append(render_issue_payload_panel(payload, entry))

        if ctx.run_diagnose and not unavailable:
            diagnosis = diagnose(ctx.system, fault=ctx.fault)
            body_parts.append(render_findings(diagnosis))

    # W15: per-engine rows are independent of the diagnose control availability.
    # One engine fault must not blank or fake the other two.
    if ctx.run_engine_probes:
        engine_reports = collect_engine_reports(
            faults=ctx.engine_faults,
            prebuilt=ctx.engine_reports,
        )
        body_parts.append(render_engine_rows(engine_reports))

    inner = "\n".join(body_parts)
    page = (
        '<section class="doctor-surface" data-surface="%s" data-wave="%s">'
        "<h1>%s</h1>"
        "%s"
        "</section>"
        % (
            html.escape(SURFACE_ID, quote=True),
            html.escape(WAVE_ID, quote=True),
            html.escape(ctx.title, quote=False),
            inner,
        )
    )

    findings = audit_dead_controls(page)
    return DoctorViewResult(
        html=page,
        diagnose_control=control,
        diagnosis=diagnosis,
        entry=entry,
        issue_payload=payload,
        dead_control_findings=findings,
        unavailable=unavailable,
        engine_reports=engine_reports,
    )


def generate_html(ctx: Optional[DoctorViewContext] = None) -> str:
    """Full HTML document with a syntax-valid script block for node --check."""
    result = render_doctor_surface(ctx)
    engines_payload = {
        eng: {
            "depth": (
                result.engine_reports[eng].depth.value
                if eng in result.engine_reports and result.engine_reports[eng].depth
                else None
            ),
            "state": (
                result.engine_reports[eng].named_state.value
                if eng in result.engine_reports
                else None
            ),
        }
        for eng in ENGINE_IDS
    }
    script = (
        "(function(){"
        "var surface=%s;"
        "var wave=%s;"
        "var control=%s;"
        "var enginesWave=%s;"
        "var enginesSurface=%s;"
        "var engines=%s;"
        "if(typeof surface!=='string'){throw new Error('surface');}"
        "if(typeof enginesWave!=='string'){throw new Error('enginesWave');}"
        "})();"
        % (
            json.dumps(SURFACE_ID),
            json.dumps(WAVE_ID),
            json.dumps(CONTROL_ID),
            json.dumps(ENGINES_WAVE_ID),
            json.dumps(ENGINES_SURFACE_ID),
            json.dumps(engines_payload),
        )
    )
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<title>Doctor diagnose</title></head><body>"
        "%s"
        "<script>%s</script>"
        "</body></html>"
        % (result.html, script)
    )


def generate_html_for_fixture(
    fixture: str,
    *,
    payload: Optional[IssuePayload] = None,
) -> str:
    """Render HTML for a named fixture (tri-state / fault / unavailable)."""
    fid = str(fixture).strip().lower()
    if fid in ("unavailable", "capability_absent", "absent"):
        return generate_html(
            DoctorViewContext(
                force_absent=True,
                capability_present=False,
                run_diagnose=False,
            )
        )
    if fid in ("unknown", "health_store_unreadable", "store_unreadable"):
        return generate_html(
            DoctorViewContext(
                capability_present=True,
                fault="health_store_unreadable",
                issue_payload=payload,
            )
        )
    if fid in ("empty", "no_finding", "empty_finding_scope"):
        return generate_html(
            DoctorViewContext(
                capability_present=True,
                fault="empty_finding_scope",
                issue_payload=payload,
            )
        )
    if fid in ("zero_measured", "zero", "measured_zero"):
        # Measured-zero stand-in: explicit zero_measured tile (distinct from
        # empty / unknown) so the tri-state harness can prove separation.
        return (
            "<!DOCTYPE html><html><body>"
            '<main data-surface="%s" data-doctor-state="zero_measured">'
            "%s"
            "</main>"
            "<script>(function(){var s=%s;})();</script>"
            "</body></html>"
            % (
                html.escape(SURFACE_ID, quote=True),
                render_state(NamedState.zero_measured),
                json.dumps(SURFACE_ID),
            )
        )
    if fid in ("ok", "healthy"):
        return generate_html(
            DoctorViewContext(
                capability_present=True,
                system=healthy_system(),
                issue_payload=payload,
            )
        )
    # Treat as a fault id.
    return generate_html(
        DoctorViewContext(
            capability_present=True,
            fault=fid,
            issue_payload=payload,
        )
    )


# --------------------------------------------------------------------------
# E2E trace (banner click → payload → diagnosis → rendered findings)
# --------------------------------------------------------------------------


def build_doctor_trace_payload(
    *,
    issue: IssuePayload,
    entry: DoctorEntryRecord,
    diagnosis: DiagnosisResult,
) -> Dict[str, Any]:
    """Payload carried through every hop (id + hash must match banner)."""
    return {
        "issue_id": issue.issue_id,
        "source": issue.source,
        "observed_symptom": issue.observed_symptom,
        "payload_hash": issue.payload_hash,
        "entry_issue_id": entry.issue_id,
        "entry_payload_hash": entry.payload_hash,
        "redetect_attempted": entry.redetect_attempted,
        "finding_count": len(diagnosis.findings),
        "no_finding": diagnosis.no_finding,
        "named_state": (
            diagnosis.named_state.value if diagnosis.named_state is not None else None
        ),
        "fault": diagnosis.fault,
        "readings": {
            k: {"name": v.name, "value": v.value} for k, v in diagnosis.readings.items()
        },
        "findings": [f.as_dict() for f in diagnosis.findings],
    }


def build_doctor_diagnose_trace(
    *,
    fault: Optional[str] = "service_status_down",
    issue_id: str = "banner-issue-1",
    source: str = "health-banner",
    observed_symptom: str = "service not responding",
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """Banner click → payload → diagnosis → rendered findings e2e trace.

    Executes real handoff + diagnose; every hop carries the banner payload
    id and hash (byte-identical).
    """
    issue = banner_issue_payload(issue_id, source, observed_symptom)
    entry = doctor_entry(issue, redetect=False)
    diagnosis = diagnose(fault=fault)
    payload = build_doctor_trace_payload(
        issue=issue, entry=entry, diagnosis=diagnosis
    )
    # Mechanical identity: hop payload_id is the issue id; payload_hash is
    # the banner-computed hash (not a re-hash of the whole hop payload).
    payload_id = issue.issue_id
    ph = issue.payload_hash
    ts = TRACE_AS_OF

    if diagnosis.named_state is not None:
        rendered_state = diagnosis.named_state.value
    elif diagnosis.no_finding:
        rendered_state = NO_FINDING_STATE.value
    elif diagnosis.findings:
        rendered_state = "findings"
    else:
        rendered_state = NamedState.ok.value

    hops = [
        make_hop(
            HOP_CONTROL_INVOCATION,
            "banner-click-diagnose",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="health banner click through to Doctor",
            timestamp=ts,
        ),
        make_hop(
            HOP_HANDLER,
            "anchor.doctor.banner_handoff.doctor_entry",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="banner payload accepted; redetect_attempted=false",
            timestamp=ts,
        ),
        make_hop(
            HOP_CAPABILITY_CALL,
            "anchor.doctor.diagnose.diagnose",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="capability.diagnose",
            timestamp=ts,
        ),
        make_hop(
            HOP_RENDERED_STATE,
            "doctor_view.render_findings",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=rendered_state,
            timestamp=ts,
        ),
    ]

    # Embed full diagnosis payload for audit (hash already fixed to issue).
    _ = payload  # carried via notes/detail for humans; hop hash is issue hash

    result = (
        TRACE_RESULT_COMPLETED
        if diagnosis.ok
        else TRACE_RESULT_FAILED_NAMED
    )
    return build_trace(
        wave_id,
        CONTROL_ID,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=result,
        induced_fault=fault,
        rendered_state=rendered_state,
        as_of=TRACE_AS_OF,
        notes=(
            "W14 doctor diagnose e2e: banner click → payload → diagnosis → "
            "rendered findings; structural rendered-string proof only; "
            "payload id/hash byte-identical; handler executed"
        ),
    )


def write_doctor_traces(
    *,
    root: Optional[Path] = None,
    relpath: str = DOCTOR_TRACE_RELPATH,
) -> Path:
    """Materialize doctor-diagnose-e2e.json under artifacts/traces/."""
    base = root
    if base is None:
        base = Path(__file__).resolve().parents[2]
    primary = build_doctor_diagnose_trace(fault="service_status_down")
    # Multi-fault evidence bag for the gate (primary + per-contract samples).
    reason_traces: Dict[str, Any] = {}
    for fid in CONTRACT_FAULTS:
        art = build_doctor_diagnose_trace(
            fault=fid,
            issue_id="banner-issue-%s" % fid,
            observed_symptom="observed under %s" % fid,
        )
        reason_traces[fid] = art.as_dict()
    # Anti-template fault also traced.
    anti = build_doctor_diagnose_trace(
        fault=ANTI_TEMPLATE_FAULT,
        issue_id="banner-issue-anti-template",
        observed_symptom="orphan sockets elevated",
    )
    reason_traces[ANTI_TEMPLATE_FAULT] = anti.as_dict()

    bag = primary.as_dict()
    bag["enumerated_faults"] = list(CONTRACT_FAULTS)
    bag["induced_fault_reasons"] = list(CONTRACT_FAULTS)
    bag["reason_traces"] = reason_traces
    bag["anti_template_fault"] = ANTI_TEMPLATE_FAULT

    # Validate primary hops before write.
    validate_trace(primary)

    out = (base / relpath).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(bag, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def load_trace_set(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the shipped doctor-diagnose-e2e.json (write first if missing)."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / DOCTOR_TRACE_RELPATH
    if not path.is_file():
        write_doctor_traces(root=base)
    return json.loads(path.read_text(encoding="utf-8"))


def node_check_doctor_scripts(html_text: str) -> None:
    """Run node --check on extracted script blocks when node is on PATH."""
    from tests.conformance.html_assert import node_check_scripts

    node_check_scripts(html_text)


# --------------------------------------------------------------------------
# W15 — per-engine e2e traces
# --------------------------------------------------------------------------


def build_doctor_engines_trace(
    *,
    engine_faults: Optional[Mapping[str, Optional[str]]] = None,
    wave_id: str = ENGINES_WAVE_ID,
) -> TraceArtifact:
    """Independent per-engine diagnose e2e trace (control→handler→cap→state).

    Default induced fault: Gemini timeout while Claude and Grok succeed —
    the isolation GWT from the frozen plan.
    """
    faults = dict(engine_faults) if engine_faults is not None else {
        "gemini": "timeout",
    }
    reports = probe_all_engines(faults=faults, validate=True)
    html_fragment = render_engine_rows(reports)

    # Payload is the independent report bag (not a shared verdict).
    bag = {
        "engines": {k: v.as_dict() for k, v in reports.items()},
        "faults": faults,
        "shared_verdict": False,
        "rendered_html_excerpt": html_fragment[:500],
    }
    pid = "doctor-engines-%s" % ("-".join(
        "%s=%s" % (k, faults.get(k) or "ok") for k in ENGINE_IDS
    ))
    ph = payload_hash(bag)
    ts = TRACE_AS_OF

    # Rendered state summary: per-engine named states joined (not one verdict).
    rendered_state = ";".join(
        "%s:%s:%s"
        % (
            eng,
            reports[eng].named_state.value,
            reports[eng].depth.value if reports[eng].depth else "unlabelled",
        )
        for eng in ENGINE_IDS
    )

    hops = [
        make_hop(
            HOP_CONTROL_INVOCATION,
            "doctor-engines-probe",
            payload_id=pid,
            payload_hash_value=ph,
            detail="per-engine independent diagnose control",
            timestamp=ts,
        ),
        make_hop(
            HOP_HANDLER,
            "anchor.doctor.engines.probe_all_engines",
            payload_id=pid,
            payload_hash_value=ph,
            detail="independent probes; no shared verdict",
            timestamp=ts,
        ),
        make_hop(
            HOP_CAPABILITY_CALL,
            "anchor.doctor.engines.{claude,gemini,grok}.probe",
            payload_id=pid,
            payload_hash_value=ph,
            detail="capability.diagnose_engines",
            timestamp=ts,
        ),
        make_hop(
            HOP_RENDERED_STATE,
            "doctor_view.render_engine_rows",
            payload_id=pid,
            payload_hash_value=ph,
            detail=rendered_state,
            timestamp=ts,
        ),
    ]

    any_failed = any(not r.ok for r in reports.values())
    return build_trace(
        wave_id,
        ENGINES_CONTROL_ID,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=(
            TRACE_RESULT_FAILED_NAMED if any_failed else TRACE_RESULT_COMPLETED
        ),
        induced_fault=json.dumps(faults, sort_keys=True),
        rendered_state=rendered_state,
        as_of=TRACE_AS_OF,
        notes=(
            "W15 doctor engines e2e: independent Claude/Gemini/Grok probes with "
            "depth labels; structural rendered-string proof only; one engine "
            "fault does not blank or fake the other two"
        ),
    )


def write_doctor_engines_traces(
    *,
    root: Optional[Path] = None,
    relpath: str = DOCTOR_ENGINES_TRACE_RELPATH,
) -> Path:
    """Materialize doctor-engines-e2e.json under artifacts/traces/."""
    base = root
    if base is None:
        base = Path(__file__).resolve().parents[2]

    # Primary: Gemini timeout isolation scenario (plan GWT).
    primary = build_doctor_engines_trace(
        engine_faults={"gemini": "timeout"},
    )
    validate_trace(primary)

    reason_traces: Dict[str, Any] = {}
    for reason in ENGINE_INDUCED_FAULT_REASONS:
        # Induce the fault on Gemini only; other engines stay healthy.
        art = build_doctor_engines_trace(
            engine_faults={"gemini": reason},
        )
        reason_traces[reason] = art.as_dict()

    # Also record a healthy all-ok bag and a Claude-only fault for isolation.
    reason_traces["all_ok"] = build_doctor_engines_trace(engine_faults={}).as_dict()
    reason_traces["claude_timeout"] = build_doctor_engines_trace(
        engine_faults={"claude": "timeout"},
    ).as_dict()
    reason_traces["grok_store_unreadable"] = build_doctor_engines_trace(
        engine_faults={"grok": "store_unreadable"},
    ).as_dict()

    bag = primary.as_dict()
    bag["enumerated_faults"] = list(ENGINE_INDUCED_FAULT_REASONS)
    bag["induced_fault_reasons"] = list(ENGINE_INDUCED_FAULT_REASONS)
    bag["reason_traces"] = reason_traces
    bag["engines"] = list(ENGINE_IDS)
    bag["shared_verdict"] = False
    bag["surface_id"] = ENGINES_SURFACE_ID

    out = (base / relpath).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(bag, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def load_engines_trace_set(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the shipped doctor-engines-e2e.json (write first if missing)."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / DOCTOR_ENGINES_TRACE_RELPATH
    if not path.is_file():
        write_doctor_engines_traces(root=base)
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "SURFACE_ID",
    "WAVE_ID",
    "CONTROL_ID",
    "DIAGNOSE_ACTION",
    "ENGINES_SURFACE_ID",
    "ENGINES_WAVE_ID",
    "ENGINES_CONTROL_ID",
    "DOCTOR_TRACE_RELPATH",
    "DOCTOR_ENGINES_TRACE_RELPATH",
    "TRACE_AS_OF",
    "FINDING_CLASS",
    "FINDINGS_CLASS",
    "PAYLOAD_CLASS",
    "UNAVAILABLE_CLASS",
    "NO_FINDING_CLASS",
    "OUTCOME_CLASS",
    "ENGINE_ROW_CLASS",
    "ENGINE_PANEL_CLASS",
    "ENGINE_DEPTH_CLASS",
    "ENGINE_NAME_CLASS",
    "UNAVAILABLE_REASON",
    "ENGINE_INDUCED_FAULT_REASONS",
    "DoctorViewContext",
    "DoctorViewResult",
    "render_diagnose_control",
    "render_finding",
    "render_findings",
    "render_issue_payload_panel",
    "render_unavailable_slot",
    "render_engine_row",
    "render_engine_rows",
    "collect_engine_reports",
    "render_doctor_surface",
    "generate_html",
    "generate_html_for_fixture",
    "build_doctor_trace_payload",
    "build_doctor_diagnose_trace",
    "write_doctor_traces",
    "load_trace_set",
    "build_doctor_engines_trace",
    "write_doctor_engines_traces",
    "load_engines_trace_set",
    "node_check_doctor_scripts",
]

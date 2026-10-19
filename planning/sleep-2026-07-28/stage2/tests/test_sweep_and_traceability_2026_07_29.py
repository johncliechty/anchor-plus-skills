"""W21 — Unnamed-control sweep + dead-control audit + traceability matrix.

Exercises every W21 deliverable under one scoped gate:

* ``tools/dead_control_audit.py``
* ``tools/ambiguous_zero_audit.py``
* ``artifacts/TRACEABILITY-MATRIX.md``
* ``artifacts/OUT-OF-CRITERIA-SURFACES.md``
* surface-wave join gate (W10–W20 GREEN + commit SHA)
* exit-register conjunction reconciliation

Gate: pytest -v tests/test_sweep_and_traceability_2026_07_29.py

GWTs (frozen plan):

* Out-of-criteria control bound to missing capability → dead-control finding;
  E3 rejected until fixed or removed from view.
* Criterion row with test file but no commit SHA or trace → matrix validator
  fails naming the incomplete row (never silent met).
* MET stamp before S1 fails the validator.
* Join gate HALTs when any of W10–W20 is not GREEN or lacks commit SHA.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools import ambiguous_zero_audit as aza
from tools import dead_control_audit as dca
from tools.ambiguous_zero_audit import (
    AMBIGUOUS_ZERO_MESSAGE,
    AmbiguousZeroAuditError,
    assert_no_ambiguous_zeros,
    audit_html as audit_ambiguous,
    is_zero_from_render_cost,
    is_zero_from_render_state,
)
from tools.dead_control_audit import (
    GO,
    HALT,
    INCOMPLETE_ROW_MESSAGE,
    JOIN_MISSING_GREEN_MESSAGE,
    JOIN_MISSING_SHA_MESSAGE,
    MET_BEFORE_S1_MESSAGE,
    STATUS_CANDIDATE_MET,
    STATUS_MET,
    STATUS_OPEN,
    E3_REJECTED_FOR_DEAD_MESSAGE,
    ControlRecord,
    TraceabilityRow,
    assert_no_dead_controls_across_surfaces,
    audit_html,
    audit_html_out_of_criteria_dead,
    bootstrap_wave21,
    build_traceability_matrix,
    classify_expected_control,
    e3_allowed_for_control,
    enumerate_controls,
    parse_green_waves,
    parse_out_of_criteria_closures,
    parse_traceability_markdown,
    phase4_go_decision,
    reconcile_exit_register,
    resolve_wave_status,
    surface_wave_join_gate,
    validate_traceability_matrix,
    write_out_of_criteria_surfaces,
    write_traceability_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Dead-control enumeration + audit
# --------------------------------------------------------------------------


def test_enumerate_wired_named_and_dead():
    html = (
        '<button type="button" class="live-control" data-control="open" '
        'data-action="action:open" data-control-mode="live">Open</button>'
        '<div class="cannot-state" data-control="run" data-control-mode="named_state">'
        '<span class="named-state" data-named-state="cannot_run">cannot_run</span>'
        "</div>"
        '<button type="button" data-control="retry" data-action="#">Retry</button>'
    )
    recs = enumerate_controls(html, surface="test")
    by_id = {r.control_id: r.disposition for r in recs}
    assert by_id["open"] == "wired"
    assert by_id["run"] == "named_state"
    assert by_id["retry"] == "dead"


def test_audit_html_flags_dead_noop():
    html = '<button data-control="diagnose" data-action="noop">Diagnose</button>'
    result = audit_html(html, surface_id="doctor")
    assert result.dead_findings
    assert any(r.disposition == "dead" for r in result.controls)


def test_hidden_when_expected_control_absent():
    html = '<div class="tile"><span class="named-state" data-named-state="empty">empty</span></div>'
    recs = enumerate_controls(html)
    assert classify_expected_control("restart", recs) == "hidden"


def test_out_of_criteria_dead_control_is_finding_and_e3_rejected():
    """GWT: control outside ten criteria bound to missing capability → finding;
    E3 rejected until fixed or removed.
    """
    dead_html = (
        '<button type="button" data-control="legacy_export" '
        'data-action="javascript:void(0)">Export</button>'
    )
    findings = audit_html_out_of_criteria_dead(
        dead_html, control_id="legacy_export", capability_present=False
    )
    assert findings, "expected finding for dead out-of-criteria control"

    allowed, reason = e3_allowed_for_control(
        dead_html, control_id="legacy_export", capability_present=False
    )
    assert allowed is False
    assert "E3 rejected" in reason or E3_REJECTED_FOR_DEAD_MESSAGE[:20] in reason


def test_out_of_criteria_honest_named_state_allows_e3_documentation():
    honest = (
        '<div class="cannot-state" data-control="legacy_export" '
        'data-control-mode="named_state">'
        '<span class="named-state" data-named-state="cannot_run">cannot_run</span>'
        "</div>"
    )
    findings = audit_html_out_of_criteria_dead(
        honest, control_id="legacy_export", capability_present=False
    )
    assert findings == []
    allowed, _ = e3_allowed_for_control(
        honest, control_id="legacy_export", capability_present=False
    )
    assert allowed is True


def test_out_of_criteria_removed_from_view_is_clean():
    html = "<div>no controls here</div>"
    findings = audit_html_out_of_criteria_dead(
        html, control_id="legacy_export", capability_present=False
    )
    assert findings == []
    assert classify_expected_control("legacy_export", enumerate_controls(html)) == "hidden"


# --------------------------------------------------------------------------
# Ambiguous-zero audit
# --------------------------------------------------------------------------


def test_bare_zero_is_finding():
    html = '<div class="usage">sessions: 0</div>'
    findings = audit_ambiguous(html)
    assert any(f.kind == "bare_zero" for f in findings)


def test_zero_measured_render_state_is_clean():
    html = (
        '<div data-named-state="zero_measured" class="usage-tile">'
        '<span class="named-state" data-named-state="zero_measured">zero_measured</span>'
        '<span class="numeral" data-numeral="0" data-measured="true">0</span>'
        "</div>"
    )
    assert is_zero_from_render_state(html)
    assert_no_ambiguous_zeros(html)


def test_measured_cost_zero_is_clean():
    html = (
        '<span class="cost-state" data-cost-state="measured">$0.00</span>'
    )
    assert is_zero_from_render_cost(html)
    assert_no_ambiguous_zeros(html)


def test_dollar_outside_measured_is_finding():
    html = '<div class="cost-tile">Total: $0.00</div>'
    findings = audit_ambiguous(html)
    assert any(f.kind == "dollar_outside_measured" for f in findings)
    with pytest.raises(AmbiguousZeroAuditError, match="ambiguous-zero"):
        assert_no_ambiguous_zeros(html)


def test_placeholder_metric_blank_is_finding():
    html = '<span class="metric" data-metric="usage">—</span>'
    findings = audit_ambiguous(html)
    assert any(f.kind == "placeholder_blank" for f in findings)


# --------------------------------------------------------------------------
# Surface-wave join gate
# --------------------------------------------------------------------------


def test_parse_green_waves_from_execution_log():
    log = (ROOT / "EXECUTION-LOG.md").read_text(encoding="utf-8")
    greens = parse_green_waves(log)
    for n in range(10, 21):
        assert greens.get(n) is True, "expected Wave %d/22 GREEN" % n


def test_surface_wave_join_gate_go_on_shipped_log():
    result = surface_wave_join_gate(root=ROOT)
    assert result.status == GO, result.message
    assert not result.missing_green
    assert not result.missing_sha
    for n in range(10, 21):
        st = result.waves["W%d" % n]
        assert st.green
        assert st.commit_sha
        assert len(st.commit_sha) >= 7


def test_join_gate_halts_when_green_missing(tmp_path: Path):
    log = tmp_path / "EXECUTION-LOG.md"
    # Only W10 GREEN — others missing.
    log.write_text(
        "## Wave 10\n- **commit:** abcdef1\n"
        "- 2026-07-29T00:00:00Z — Wave 10/22 GREEN — W10\n",
        encoding="utf-8",
    )
    # Point root so join reads this log; no checkpoint.
    (tmp_path / "artifacts").mkdir()
    result = surface_wave_join_gate(root=tmp_path)
    assert result.status == HALT
    assert "GREEN" in result.message or JOIN_MISSING_GREEN_MESSAGE[:20] in result.message
    assert "W11" in result.missing_green


def test_join_gate_halts_when_sha_missing(tmp_path: Path):
    lines = ["# log\n"]
    for n in range(10, 21):
        lines.append("## Wave %d\n" % n)
        lines.append("- **commit:** (orchestrator records SHA on GO)\n")
        lines.append(
            "- 2026-07-29T00:00:00Z — Wave %d/22 GREEN — W%d\n" % (n, n)
        )
    (tmp_path / "EXECUTION-LOG.md").write_text("".join(lines), encoding="utf-8")
    result = surface_wave_join_gate(root=tmp_path)
    assert result.status == HALT
    assert result.missing_sha
    assert JOIN_MISSING_SHA_MESSAGE.split("—")[0].strip() in result.message or "commit SHA" in result.message


def test_commit_from_proven_json_fallback(tmp_path: Path):
    lines = ["# log\n"]
    for n in range(10, 21):
        lines.append("## Wave %d\n" % n)
        lines.append("- **commit:** pending\n")
        lines.append(
            "- 2026-07-29T00:00:00Z — Wave %d/22 GREEN — W%d\n" % (n, n)
        )
    (tmp_path / "EXECUTION-LOG.md").write_text("".join(lines), encoding="utf-8")
    foreman = tmp_path / ".foreman"
    foreman.mkdir()
    for n in range(10, 21):
        sha = ("a" * 7) + ("%02d" % n)  # 9-char hex
        (foreman / ("wave-%d-proven.json" % n)).write_text(
            '{"commit_sha": "%s"}\n' % sha,
            encoding="utf-8",
        )
    result = surface_wave_join_gate(root=tmp_path)
    assert result.status == GO, result.message
    assert result.waves["W10"].commit_source == "proven.json"


# --------------------------------------------------------------------------
# Traceability matrix
# --------------------------------------------------------------------------


def test_build_and_validate_shipped_matrix():
    matrix = build_traceability_matrix(root=ROOT)
    assert len(matrix.rows) == 10
    validated = validate_traceability_matrix(matrix, allow_open=False, s1_pass=False)
    assert not validated.errors, validated.errors
    for row in matrix.rows:
        assert row.status == STATUS_CANDIDATE_MET
        assert STATUS_MET != row.status or False  # never MET
        assert "MET" not in row.status or row.status == STATUS_CANDIDATE_MET


def test_met_before_s1_fails_validator():
    rows = [
        TraceabilityRow(
            criterion=i,
            name="c%d" % i,
            waves="W10",
            test_file="tests/t.py",
            commit_sha="abcdef1",
            trace_artifact="artifacts/traces/x.json",
            status=STATUS_MET if i == 1 else STATUS_CANDIDATE_MET,
        )
        for i in range(1, 11)
    ]
    validated = validate_traceability_matrix(rows, allow_open=True, s1_pass=False)
    assert validated.errors
    assert any("MET before S1" in e or MET_BEFORE_S1_MESSAGE[:15] in e for e in validated.errors)


def test_incomplete_row_fails_naming_criterion():
    """GWT: test file but no commit SHA or trace → fail naming incomplete row."""
    rows = [
        TraceabilityRow(
            criterion=i,
            name="c%d" % i,
            waves="W10",
            test_file="tests/t.py" if i == 3 else "tests/t.py",
            commit_sha="" if i == 3 else "abcdef1",
            trace_artifact="" if i == 3 else "artifacts/traces/x.json",
            status=STATUS_CANDIDATE_MET,
        )
        for i in range(1, 11)
    ]
    # Make only criterion 3 incomplete; others complete so the error names 3.
    rows = []
    for i in range(1, 11):
        if i == 3:
            rows.append(
                TraceabilityRow(
                    criterion=3,
                    name="usage",
                    waves="W12",
                    test_file="tests/test_usage_time_surfacing_2026_07_29.py",
                    commit_sha="",
                    trace_artifact="",
                    status=STATUS_CANDIDATE_MET,
                )
            )
        else:
            rows.append(
                TraceabilityRow(
                    criterion=i,
                    name="c%d" % i,
                    waves="W10",
                    test_file="tests/t.py",
                    commit_sha="abcdef1",
                    trace_artifact="artifacts/t.json",
                    status=STATUS_CANDIDATE_MET,
                )
            )
    validated = validate_traceability_matrix(rows, allow_open=True, s1_pass=False)
    assert validated.errors
    assert any("criterion 3" in e for e in validated.errors)
    assert any(
        "incomplete" in e.lower() or INCOMPLETE_ROW_MESSAGE[:12] in e
        for e in validated.errors
    )


def test_bootstrap_writes_matrix_and_out_of_criteria():
    paths = bootstrap_wave21(root=ROOT, skip_surface_render=True)
    assert paths[dca.TRACEABILITY_RELPATH].is_file()
    assert paths[dca.OUT_OF_CRITERIA_RELPATH].is_file()
    text = paths[dca.TRACEABILITY_RELPATH].read_text(encoding="utf-8")
    assert "CANDIDATE-MET" in text
    assert "| MET |" not in text and not re_search_bare_met(text)
    parsed = parse_traceability_markdown(text)
    assert len(parsed.rows) == 10
    ooc = paths[dca.OUT_OF_CRITERIA_RELPATH].read_text(encoding="utf-8")
    closures = parse_out_of_criteria_closures(ooc)
    assert closures
    for row in closures:
        c = row["closure"].lower()
        assert c in {"fixed", "disabled"} or "e3" in c or "signed" in c


def re_search_bare_met(text: str) -> bool:
    """True if a table status cell is exactly MET (not CANDIDATE-MET)."""
    import re

    return bool(re.search(r"\|\s*MET\s*\|", text))


# --------------------------------------------------------------------------
# Exit-register reconciliation
# --------------------------------------------------------------------------


def test_exit_register_recon_zero_signed_ok():
    recon = reconcile_exit_register(root=ROOT)
    assert recon["signed_count"] == 0
    assert recon["score"] == "OK"
    assert recon["halt_rebaseline"] is False
    assert "CANDIDATE-MET" in recon["terminal_status"]


# --------------------------------------------------------------------------
# Composite GO + clean fixtures
# --------------------------------------------------------------------------


def test_phase4_go_with_injected_clean_surfaces():
    clean = {
        "open-run": (
            '<div class="cannot-state" data-control="open" data-control-mode="named_state">'
            '<span class="named-state" data-named-state="cannot_open">cannot_open</span>'
            "</div>"
        ),
        "attach": (
            '<div class="cannot-state" data-control="retry" data-control-mode="named_state">'
            '<span class="named-state" data-named-state="cannot_retry">cannot_retry</span>'
            "</div>"
        ),
        "usage": (
            '<div data-named-state="pending" class="usage-tile">'
            '<span class="named-state" data-named-state="pending">pending</span>'
            "</div>"
        ),
        "cost": (
            '<span class="cost-state" data-cost-state="unmeasured">'
            '<span class="named-state" data-named-state="unmeasured">unmeasured</span>'
            "</span>"
        ),
        "doctor": (
            '<div class="cannot-state" data-control="diagnose" data-control-mode="named_state">'
            '<span class="named-state" data-named-state="cannot_run">cannot_run</span>'
            "</div>"
        ),
        "stop-summary": (
            '<div data-named-state="empty">'
            '<span class="named-state" data-named-state="empty">empty</span>'
            "</div>"
        ),
        "restart": (
            '<div class="cannot-state" data-control="restart_run" data-control-mode="named_state">'
            '<span class="named-state" data-named-state="cannot_restart">cannot_restart</span>'
            "</div>"
        ),
        "preview": (
            '<div data-named-state="ok">'
            '<span class="named-state" data-named-state="ok">ok</span>'
            "</div>"
        ),
        "projects": (
            '<div data-named-state="empty">'
            '<span class="named-state" data-named-state="empty">empty</span>'
            "</div>"
        ),
        "cadence": (
            '<div data-named-state="ok" data-as-of="2026-07-29T00:00:00Z">'
            '<span class="named-state" data-named-state="ok">ok</span>'
            "</div>"
        ),
    }
    # Ensure artifacts exist for matrix CANDIDATE-MET.
    bootstrap_wave21(root=ROOT, skip_surface_render=True)
    result = phase4_go_decision(root=ROOT, html_by_surface=clean)
    assert result.status == GO, result.message
    assert result.matrix_ok
    assert result.ambiguous_findings == 0
    assert result.join is not None and result.join.ok


def test_phase4_halts_on_dead_control_in_surface():
    dirty = {
        "open-run": '<button data-control="open" data-action="#">Open</button>',
    }
    result = phase4_go_decision(root=ROOT, html_by_surface=dirty)
    assert result.status == HALT
    assert result.dead_audit is not None
    assert not result.dead_audit.ok


def test_assert_no_dead_controls_across_clean_surfaces():
    clean = {
        "s1": (
            '<button class="live-control" data-control="open" '
            'data-action="action:open" data-control-mode="live">Open</button>'
        ),
        "s2": (
            '<div class="cannot-state" data-control="run">'
            '<span class="named-state" data-named-state="cannot_run">cannot_run</span>'
            "</div>"
        ),
    }
    report = assert_no_dead_controls_across_surfaces(
        dca.audit_all_surfaces(html_by_surface=clean)
    )
    assert report.ok
    assert report.findings_count == 0


def test_control_record_as_dict_shape():
    rec = ControlRecord(
        control_id="open",
        disposition="wired",
        tag="button",
        action="action:open",
        label="Open",
        surface="open-run",
    )
    d = rec.as_dict()
    assert d["control_id"] == "open"
    assert d["disposition"] == "wired"


def test_resolve_wave_status_w10_shipped():
    st = resolve_wave_status(10, root=ROOT)
    assert st.green is True
    assert st.commit_sha
    assert st.wave_id == "W10"

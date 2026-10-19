"""W12 — Usage + time surfacing gated on the Rollup Evidence Gate.

Exercises every W12 deliverable under one scoped gate:

* ``anchor/usage/rollup_read.py``
* ``anchor/ui/usage_tiles.py``
* ``artifacts/failure-states/usage-time.md``
* ``artifacts/traces/usage-e2e.json``

Gate: pytest -v tests/test_usage_time_surfacing_2026_07_29.py

GWTs (frozen plan):

* NO_AGGREGATOR rollup → dashboard pending naming the aggregation wave; no numeral
* PROVEN / zero_measured → workbench shows measured 0 + zero_measured label
  (distinct from empty, pending, unknown)
* READ_FAILED → session chrome unknown; no numeral; no pending wording on the tile
* E2 provisional usage count → visible as_of stamp + reconciliation entry
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from anchor.build.rollup_registry import (
    NumeralFromEmpty,
    NumeralFromNoAggregator,
    NumeralFromReadFailed,
    RollupRegistry,
    entry_from_evidence,
)
from anchor.build.trace_artifact import (
    PROOF_LEVEL_RENDERED_STRING,
    is_go_evidence,
    validate_trace,
)
from anchor.ui import usage_tiles as ut
from anchor.ui.named_state import NamedState, render_state
from anchor.ui.usage_tiles import (
    UsageTileContext,
    generate_html,
    generate_html_for_fixture,
    generate_html_for_surface_fault,
    load_trace_set,
    node_check_usage_scripts,
    render_dashboard_tile,
    render_session_chrome_tile,
    render_usage_surface,
    render_usage_tile,
    render_workbench_tile,
    write_usage_traces,
)
from anchor.usage import rollup_read as rr
from anchor.usage.rollup_read import (
    INDUCED_FAULT_REASONS,
    METRIC_TIME,
    METRIC_USAGE,
    RECONCILIATION_MARKER,
    SURFACE_DASHBOARD,
    SURFACE_SESSION_CHROME,
    SURFACE_WORKBENCH,
    USAGE_METRICS,
    USAGE_SURFACES,
    UsageReadError,
    UsageReadResult,
    force_read_for_fault,
    has_reconciliation_entry,
    read_usage_rollup,
    record_e2_reconciliation,
    rollup_id_for,
)
from tools.rollup_evidence_gate import (
    SubVerdict,
    Verdict,
    fixture_no_aggregator,
    fixture_proven_empty,
    fixture_proven_nonzero,
    fixture_proven_zero_measured,
    fixture_read_failed,
)
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import validate_failure_state_table
from tests.conformance.tri_state import assert_tri_state

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "usage-time.md"
)
USAGE_TRACE_PATH = CONTAINMENT_ROOT / "artifacts" / "traces" / "usage-e2e.json"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _parse_usage_failure_table(text: str) -> list:
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


def _extract_tile_section(html: str, surface: str) -> str:
    """Pull the surface chrome section so legend text cannot pollute GWT checks."""
    pattern = (
        r'<section class="[^"]*" data-surface-chrome="%s">(.*?)</section>'
        % re.escape(surface)
    )
    m = re.search(pattern, html, re.DOTALL)
    if m:
        return m.group(0)
    # Fallback: first usage-tile div.
    m2 = re.search(
        r'<div class="usage-tile"[^>]*>.*?</div>',
        html,
        re.DOTALL,
    )
    return m2.group(0) if m2 else html


def _tile_has_measured_numeral(html: str) -> bool:
    return 'class="measured-numeral"' in html or "measured-numeral" in html


# --------------------------------------------------------------------------
# Acceptance: every new module is imported and exercised
# --------------------------------------------------------------------------


def test_w12_modules_importable_and_callable():
    assert callable(read_usage_rollup)
    assert callable(force_read_for_fault)
    assert callable(record_e2_reconciliation)
    assert callable(generate_html)
    assert callable(generate_html_for_fixture)
    assert callable(render_usage_tile)
    assert callable(write_usage_traces)
    assert callable(load_trace_set)
    assert rr.WAVE_ID == "W12"
    assert ut.WAVE_ID == "W12"
    assert set(INDUCED_FAULT_REASONS) == {
        "empty_scope",
        "zero_measured",
        "query_failure",
        "absent_aggregator",
    }
    assert set(USAGE_SURFACES) == {
        SURFACE_DASHBOARD,
        SURFACE_WORKBENCH,
        SURFACE_SESSION_CHROME,
    }
    assert set(USAGE_METRICS) == {METRIC_USAGE, METRIC_TIME}


# --------------------------------------------------------------------------
# rollup_read — PROVEN only numerals; NO_AGGREGATOR raises; READ_FAILED unknown
# --------------------------------------------------------------------------


def test_no_aggregator_read_is_pending_not_numeral():
    ev = fixture_no_aggregator(
        "dashboard_usage", aggregation_wave="W12-usage-aggregation"
    )
    result = read_usage_rollup(
        SURFACE_DASHBOARD, METRIC_USAGE, evidence=ev
    )
    assert result.verdict is Verdict.NO_AGGREGATOR
    assert result.named_state is NamedState.pending
    assert result.numeral is None
    assert result.allows_numeral is False
    assert result.aggregation_wave == "W12-usage-aggregation"
    assert result.pending_message is not None
    assert "W12-usage-aggregation" in result.pending_message
    with pytest.raises(NumeralFromNoAggregator):
        result.require_numeral()


def test_no_aggregator_raise_on_numeral_flag():
    ev = fixture_no_aggregator("dashboard_usage")
    with pytest.raises(NumeralFromNoAggregator):
        read_usage_rollup(
            SURFACE_DASHBOARD,
            METRIC_USAGE,
            evidence=ev,
            raise_on_no_aggregator_numeral=True,
        )


def test_read_failed_is_unknown_never_zero_never_pending():
    ev = fixture_read_failed("session_chrome_usage")
    result = read_usage_rollup(
        SURFACE_SESSION_CHROME, METRIC_USAGE, evidence=ev
    )
    assert result.verdict is Verdict.READ_FAILED
    assert result.named_state is NamedState.unknown
    assert result.numeral is None
    assert result.pending_message is None
    assert result.named_state is not NamedState.pending
    with pytest.raises(NumeralFromReadFailed):
        result.require_numeral()


def test_proven_zero_measured_returns_measured_zero():
    ev = fixture_proven_zero_measured(
        "workbench_usage", scope_size=12
    )
    result = read_usage_rollup(
        SURFACE_WORKBENCH, METRIC_USAGE, evidence=ev
    )
    assert result.verdict is Verdict.PROVEN
    assert result.sub_verdict is SubVerdict.ZERO_MEASURED
    assert result.named_state is NamedState.zero_measured
    assert result.numeral == 0
    assert result.allows_numeral is True
    assert result.require_numeral() == 0


def test_proven_empty_has_no_numeral():
    ev = fixture_proven_empty("dashboard_usage")
    result = read_usage_rollup(
        SURFACE_DASHBOARD, METRIC_USAGE, evidence=ev
    )
    assert result.named_state is NamedState.empty
    assert result.numeral is None
    with pytest.raises(NumeralFromEmpty):
        result.require_numeral()


def test_proven_nonzero_allows_numeral():
    ev = fixture_proven_nonzero("dashboard_usage")
    result = read_usage_rollup(
        SURFACE_DASHBOARD, METRIC_USAGE, evidence=ev
    )
    assert result.named_state is NamedState.ok
    assert result.numeral == 2000
    assert result.require_numeral() == 2000


def test_registry_path_for_proven_and_no_aggregator():
    reg = RollupRegistry(
        [
            entry_from_evidence(
                fixture_proven_zero_measured("workbench_time")
            ),
            entry_from_evidence(
                fixture_no_aggregator(
                    "dashboard_time",
                    aggregation_wave="W12-usage-aggregation",
                )
            ),
        ]
    )
    zm = read_usage_rollup(
        SURFACE_WORKBENCH, METRIC_TIME, registry=reg
    )
    assert zm.named_state is NamedState.zero_measured
    pend = read_usage_rollup(
        SURFACE_DASHBOARD, METRIC_TIME, registry=reg
    )
    assert pend.named_state is NamedState.pending
    with pytest.raises(NumeralFromNoAggregator):
        reg.render_numeral("dashboard_time")


def test_rollup_id_for_surfaces_and_metrics():
    assert rollup_id_for(SURFACE_DASHBOARD, METRIC_USAGE) == "dashboard_usage"
    assert rollup_id_for(SURFACE_SESSION_CHROME, METRIC_TIME) == (
        "session_chrome_time"
    )
    with pytest.raises(UsageReadError):
        rollup_id_for("not_a_surface", METRIC_USAGE)


# --------------------------------------------------------------------------
# GWT 1: NO_AGGREGATOR → dashboard pending, no numeral
# --------------------------------------------------------------------------


def test_gwt_dashboard_no_aggregator_pending_no_numeral():
    """Given NO_AGGREGATOR, when dashboard renders, pending + wave; no numeral."""
    wave = "W12-usage-aggregation"
    result = force_read_for_fault(
        "absent_aggregator",
        surface=SURFACE_DASHBOARD,
        metric=METRIC_USAGE,
        aggregation_wave=wave,
    )
    tile = render_dashboard_tile(result)
    assert_visible_text_contains(tile, "pending")
    assert 'data-named-state="pending"' in tile
    assert wave in tile
    assert 'data-aggregation-wave="%s"' % wave in tile
    assert not _tile_has_measured_numeral(tile)
    assert 'data-allows-numeral="false"' in tile
    # No bare measured 0 inventing a value that was never aggregated.
    assert 'data-numeral=' not in tile
    assert 'data-measured="true"' not in tile


def test_gwt_dashboard_full_surface_pending():
    html = generate_html_for_surface_fault(
        SURFACE_DASHBOARD,
        "absent_aggregator",
        aggregation_wave="W12-usage-aggregation",
    )
    section = _extract_tile_section(html, SURFACE_DASHBOARD)
    assert_visible_text_contains(section, "pending")
    assert "W12-usage-aggregation" in section
    assert not _tile_has_measured_numeral(section)


# --------------------------------------------------------------------------
# GWT 2: PROVEN zero_measured → workbench measured zero, distinct labels
# --------------------------------------------------------------------------


def test_gwt_workbench_zero_measured_distinct():
    """Given PROVEN/zero_measured, workbench shows measured 0 + zero_measured."""
    result = force_read_for_fault(
        "zero_measured",
        surface=SURFACE_WORKBENCH,
        metric=METRIC_USAGE,
    )
    tile = render_workbench_tile(result)
    assert_visible_text_contains(tile, "zero_measured")
    assert 'data-named-state="zero_measured"' in tile
    assert _tile_has_measured_numeral(tile)
    assert 'data-numeral="0"' in tile
    assert 'data-measured="true"' in tile
    # Visibly distinct from empty / pending / unknown.
    assert 'data-named-state="empty"' not in tile
    assert 'data-named-state="pending"' not in tile
    assert 'data-named-state="unknown"' not in tile
    nodes = visible_text_nodes(tile)
    assert "zero_measured" in nodes or "zero_measured" in tile
    assert "0" in nodes or 'data-numeral="0"' in tile


def test_four_trichotomy_labels_are_pairwise_distinct_on_tiles():
    """pending / unknown / empty / zero_measured are four distinct visible labels."""
    labels = {}
    for fault, surface, key in (
        ("absent_aggregator", SURFACE_DASHBOARD, "pending"),
        ("query_failure", SURFACE_SESSION_CHROME, "unknown"),
        ("empty_scope", SURFACE_DASHBOARD, "empty"),
        ("zero_measured", SURFACE_WORKBENCH, "zero_measured"),
    ):
        r = force_read_for_fault(fault, surface=surface, metric=METRIC_USAGE)
        frag = render_usage_tile(r)
        assert 'data-named-state="%s"' % key in frag
        labels[key] = NamedState(key).label
    assert len(set(labels.values())) == 4
    # Binding definitions ride on the NamedState members (W6).
    for key in labels:
        assert NamedState(key).definition
        # Distinct render_state strings.
        rendered = render_state(NamedState(key))
        assert key in rendered


# --------------------------------------------------------------------------
# GWT 3: READ_FAILED → session chrome unknown; no numeral; no pending wording
# --------------------------------------------------------------------------


def test_gwt_session_chrome_read_failed_unknown():
    """Given READ_FAILED, session chrome shows unknown — no numeral, no pending."""
    result = force_read_for_fault(
        "query_failure",
        surface=SURFACE_SESSION_CHROME,
        metric=METRIC_USAGE,
    )
    tile = render_session_chrome_tile(result)
    assert_visible_text_contains(tile, "unknown")
    assert 'data-named-state="unknown"' in tile
    assert not _tile_has_measured_numeral(tile)
    assert 'data-allows-numeral="false"' in tile
    assert 'data-numeral=' not in tile
    # No pending wording on the tile itself (legend is out of scope).
    assert "pending" not in tile.lower()
    assert "awaits" not in tile.lower()
    assert result.named_state is NamedState.unknown
    assert result.numeral is None


# --------------------------------------------------------------------------
# GWT 4: E2 provisional → as_of stamp + reconciliation entry
# --------------------------------------------------------------------------


def test_gwt_e2_provisional_as_of_and_reconciliation(tmp_path):
    """Given signed-E2 provisional usage count, as_of visible + log entry."""
    as_of = "2026-07-29T15:30:00Z"
    ev = fixture_proven_nonzero("dashboard_usage")
    result = read_usage_rollup(
        SURFACE_DASHBOARD,
        METRIC_USAGE,
        evidence=ev,
        provisional=True,
        as_of=as_of,
    )
    assert result.is_provisional is True
    assert result.as_of == as_of
    assert result.numeral == 2000

    tile = render_usage_tile(result)
    assert "as_of" in tile
    assert as_of in tile
    assert 'data-as-of="%s"' % as_of in tile
    assert 'data-provisional="true"' in tile
    assert _tile_has_measured_numeral(tile)

    log_path = tmp_path / "EXECUTION-LOG.md"
    log_path.write_text("# Execution Log\n\n", encoding="utf-8")
    line = record_e2_reconciliation(result, log_path=log_path)
    assert RECONCILIATION_MARKER in line
    assert "rollup=dashboard_usage" in line
    assert as_of in line
    text = log_path.read_text(encoding="utf-8")
    assert RECONCILIATION_MARKER in text
    assert has_reconciliation_entry(
        log_path=log_path, rollup_id="dashboard_usage"
    )

    # Surface path that records reconciliation into the same log.
    surf = render_usage_surface(
        UsageTileContext(
            surface=SURFACE_DASHBOARD,
            result=result,
            provisional=True,
            as_of=as_of,
        ),
        record_reconciliation=True,
        reconciliation_log=log_path,
    )
    assert surf.reconciliation_line is not None
    assert as_of in surf.html
    assert "as_of" in surf.html


def test_e2_reconciliation_refuses_non_provisional():
    result = force_read_for_fault(
        "query_failure", surface=SURFACE_SESSION_CHROME
    )
    with pytest.raises(UsageReadError):
        record_e2_reconciliation(result, log_path=Path("nope.md"))


# --------------------------------------------------------------------------
# Induced faults (one per named failure reason)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fault", list(INDUCED_FAULT_REASONS))
def test_induced_fault_per_gate_reason(fault):
    result = force_read_for_fault(fault, surface=SURFACE_DASHBOARD)
    assert isinstance(result, UsageReadResult)
    tile = render_usage_tile(result)
    assert 'data-named-state="%s"' % result.named_state.value in tile
    assert_visible_text_contains(tile, result.named_state.label)
    if fault == "absent_aggregator":
        assert result.named_state is NamedState.pending
        assert not result.allows_numeral
    elif fault == "zero_measured":
        assert result.named_state is NamedState.zero_measured
        assert result.numeral == 0
    elif fault == "query_failure":
        assert result.named_state is NamedState.unknown
        assert result.numeral is None
    elif fault == "empty_scope":
        assert result.named_state is NamedState.empty
        assert result.numeral is None


def test_force_read_unknown_fault_raises():
    with pytest.raises(UsageReadError):
        force_read_for_fault("not_a_real_fault")


# --------------------------------------------------------------------------
# Tri-state conformance across surfaces
# --------------------------------------------------------------------------


def test_usage_tri_state_conformance():
    assert_tri_state(
        generate_html_for_fixture,
        call_site="anchor.ui.usage_tiles.generate_html_for_fixture",
    )


@pytest.mark.parametrize("surface", list(USAGE_SURFACES))
def test_each_surface_renders_four_named_states(surface):
    """Every surface can render pending/unknown/empty/zero_measured distinctly."""
    fault_for = {
        NamedState.pending: "absent_aggregator",
        NamedState.unknown: "query_failure",
        NamedState.empty: "empty_scope",
        NamedState.zero_measured: "zero_measured",
    }
    rendered_states = []
    for ns, fault in fault_for.items():
        r = force_read_for_fault(fault, surface=surface, metric=METRIC_USAGE)
        frag = render_usage_tile(r)
        assert 'data-named-state="%s"' % ns.value in frag
        rendered_states.append(ns.value)
    assert len(set(rendered_states)) == 4


# --------------------------------------------------------------------------
# Failure-state table
# --------------------------------------------------------------------------


def test_failure_state_table_exists_and_maps_vocabulary():
    assert FAILURE_TABLE_PATH.is_file()
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in text
    assert "/Users/" not in text
    rows = _parse_usage_failure_table(text)
    assert rows, "usage-time.md machine table produced no rows"
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    assert "zero_measured" in states
    assert "pending" in states
    # Separate rows — not merged.
    assert "unknown/empty" not in text.lower().replace(" ", "")
    report = validate_failure_state_table(rows, surface="usage-time")
    assert report["ok"] is True


def test_failure_state_table_surface_native_usage_language():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "usage" in low or "tile render" in low
    # Machine table body must not use honesty-theater verbs as triggers.
    rows = _parse_usage_failure_table(text)
    for row in rows:
        blob = " ".join(row.values()).lower()
        for verb in ("index", "rebuild", "reconcile"):
            assert not re.search(r"\b%s\b" % verb, blob), row


# --------------------------------------------------------------------------
# End-to-end traces
# --------------------------------------------------------------------------


def test_usage_e2e_trace_artifact_schema_valid():
    """Materialize + validate artifacts/traces/usage-e2e.json."""
    written = write_usage_traces(root=CONTAINMENT_ROOT)
    assert any("usage-e2e.json" in k for k in written)
    assert USAGE_TRACE_PATH.is_file()

    data = load_trace_set(ut.USAGE_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    assert data["control_id"] == "usage-time"
    assert data["wave_id"] == "W12"
    assert is_go_evidence(data)

    nested = data.get("fault_traces") or data.get("reason_traces") or {}
    for fault in INDUCED_FAULT_REASONS:
        assert fault in nested, "missing usage fault trace for %s" % fault
        art = validate_trace(nested[fault])
        assert art.induced_fault == fault
        assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
        assert is_go_evidence(art)
        kinds = [h.kind for h in art.hops]
        assert kinds == [
            "control_invocation",
            "handler",
            "capability_call",
            "rendered_state",
        ]

    # GWT-pinned surface traces.
    for pin in (
        "dashboard_pending",
        "workbench_zero_measured",
        "session_chrome_unknown",
    ):
        assert pin in nested
        validate_trace(nested[pin])


@pytest.mark.parametrize("fault", list(INDUCED_FAULT_REASONS))
def test_build_usage_fault_trace_live(fault):
    art = ut.build_usage_fault_trace(fault)
    assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
    assert art.induced_fault == fault
    assert is_go_evidence(art)


def test_trace_rendered_states_match_fault_semantics():
    assert (
        ut.build_usage_fault_trace(
            "absent_aggregator", surface=SURFACE_DASHBOARD
        ).rendered_state
        == "pending"
    )
    assert (
        ut.build_usage_fault_trace(
            "zero_measured", surface=SURFACE_WORKBENCH
        ).rendered_state
        == "zero_measured"
    )
    assert (
        ut.build_usage_fault_trace(
            "query_failure", surface=SURFACE_SESSION_CHROME
        ).rendered_state
        == "unknown"
    )
    assert (
        ut.build_usage_fault_trace(
            "empty_scope", surface=SURFACE_DASHBOARD
        ).rendered_state
        == "empty"
    )


# --------------------------------------------------------------------------
# Visible text + node --check
# --------------------------------------------------------------------------


def test_usage_generate_html_visible_nodes_and_node_check():
    html = generate_html(
        UsageTileContext(
            force_fault="absent_aggregator",
            surface=SURFACE_DASHBOARD,
            aggregation_wave="W12-usage-aggregation",
        )
    )
    assert "<html" in html.lower()
    assert_visible_text_contains(html, "pending")
    assert 'data-surface="usage-time"' in html
    # node --check when available; soft when absent (orchestrator host has node).
    node_check_scripts(html, require_node=False)
    node_check_usage_scripts(html, require_node=False)


def test_generate_html_for_fixture_matrix():
    for fixture in ("unknown", "empty", "zero_measured"):
        html = generate_html_for_fixture(fixture)
        assert_visible_text_contains(html, fixture if fixture != "zero" else "zero_measured")
        assert 'data-named-state="%s"' % (
            "zero_measured" if fixture == "zero_measured" else fixture
        ) in html


# --------------------------------------------------------------------------
# No silent bare zero / no absolute host paths
# --------------------------------------------------------------------------


def test_no_silent_bare_zero_for_unaggregated():
    """A value that was never aggregated must not render a bare measured 0."""
    for fault in ("absent_aggregator", "query_failure", "empty_scope"):
        r = force_read_for_fault(fault, surface=SURFACE_DASHBOARD)
        tile = render_usage_tile(r)
        assert not _tile_has_measured_numeral(tile), fault
        assert r.numeral is None or r.named_state is NamedState.zero_measured


def test_no_absolute_host_paths_in_shipped_sources():
    rels = [
        "anchor/usage/rollup_read.py",
        "anchor/usage/__init__.py",
        "anchor/ui/usage_tiles.py",
        "artifacts/failure-states/usage-time.md",
    ]
    for rel in rels:
        path = CONTAINMENT_ROOT / rel
        assert path.is_file(), rel
        text = path.read_text(encoding="utf-8")
        assert "C:\\Users" not in text, rel
        assert "C:/Users" not in text, rel
        assert "/Users/" not in text, rel


def test_binding_definitions_on_four_labels():
    """Four trichotomy labels carry the binding definitions (via NamedState)."""
    from anchor.ui.named_state import (
        BINDING_EMPTY,
        BINDING_PENDING,
        BINDING_UNKNOWN,
        BINDING_ZERO_MEASURED,
    )

    assert NamedState.empty.definition == BINDING_EMPTY
    assert NamedState.zero_measured.definition == BINDING_ZERO_MEASURED
    assert NamedState.unknown.definition == BINDING_UNKNOWN
    assert NamedState.pending.definition == BINDING_PENDING

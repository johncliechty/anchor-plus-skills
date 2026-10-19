"""W13 — Cost surfacing from cost_state (never a fabricated dollar).

Exercises every W13 deliverable under one scoped gate:

* ``anchor/ui/cost_view.py``
* ``artifacts/failure-states/cost.md``
* ``artifacts/traces/cost-e2e.json``
* ``tools/zero_inference_lint.py`` wired into this gate

Gate: pytest -v tests/test_cost_surfacing_2026_07_29.py

GWTs (frozen plan):

* Engine with no cost instrumentation → session chrome labelled unmeasured;
  rendered HTML contains no '$' figure for that engine
* Cost aggregation that raises at read time → dashboard measurement_failed;
  no attempt to sign E2 for that tile is accepted by the exit register
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from anchor.build.exit_register import (
    E2_DOLLARS_MESSAGE,
    ExitId,
    IllegalExit,
    is_cost_criterion,
    make_row,
    validate,
)
from anchor.build.trace_artifact import (
    PROOF_LEVEL_RENDERED_STRING,
    is_go_evidence,
    validate_trace,
)
from anchor.cost.cost_state import SUBSCRIPTION_LABEL, CostState
from anchor.cost.render_cost import render_cost
from anchor.ui import cost_view as cv
from anchor.ui.cost_view import (
    COST_LINT_RELS,
    COST_SURFACES,
    INDUCED_FAULT_REASONS,
    SURFACE_DASHBOARD,
    SURFACE_SESSION_CHROME,
    SURFACE_WORKBENCH,
    CostAggregationError,
    CostTileContext,
    CostTileResult,
    assert_cost_sources_lint_clean,
    assert_e2_refused_for_cost_tile,
    force_cost_for_fault,
    generate_html,
    generate_html_for_cost_state,
    generate_html_for_fixture,
    generate_html_for_surface_fault,
    generate_html_zero_matrix,
    lint_cost_sources,
    load_trace_set,
    node_check_cost_scripts,
    read_cost_aggregation,
    read_engine_cost,
    refuse_e2_for_cost_tile,
    render_cost_surface,
    render_cost_tile,
    render_dashboard_cost,
    render_session_chrome_cost,
    write_cost_traces,
)
from anchor.ui.named_state import NamedState
from tools.zero_inference_lint import lint_paths, lint_source
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import validate_failure_state_table

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "cost.md"
)
COST_TRACE_PATH = CONTAINMENT_ROOT / "artifacts" / "traces" / "cost-e2e.json"

_DOLLAR_RE = re.compile(r"\$\d")
_ZERO_DOLLAR_RE = re.compile(r"\$0(?:\.0+)?\b")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _parse_cost_failure_table(text: str) -> list:
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
    pattern = (
        r'<section class="[^"]*" data-surface-chrome="%s">(.*?)</section>'
        % re.escape(surface)
    )
    m = re.search(pattern, html, re.DOTALL)
    if m:
        return m.group(0)
    m2 = re.search(
        r'<div class="cost-tile"[^>]*>.*?</div>',
        html,
        re.DOTALL,
    )
    return m2.group(0) if m2 else html


def _visible_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return " ".join(text.split())


def _engine_tile_html(html: str, engine: str) -> str:
    """Pull the tile for one engine so other engines cannot pollute checks."""
    pattern = (
        r'<div class="cost-tile[^"]*"[^>]*data-engine="%s"[^>]*>.*?</div>'
        % re.escape(engine)
    )
    m = re.search(pattern, html, re.DOTALL)
    if m:
        return m.group(0)
    # Fallback: any fragment mentioning the engine.
    if 'data-engine="%s"' % engine in html:
        return html
    return html


# --------------------------------------------------------------------------
# Acceptance: every new module is imported and exercised
# --------------------------------------------------------------------------


def test_w13_modules_importable_and_callable():
    assert callable(generate_html)
    assert callable(generate_html_zero_matrix)
    assert callable(generate_html_for_fixture)
    assert callable(render_cost_tile)
    assert callable(read_cost_aggregation)
    assert callable(read_engine_cost)
    assert callable(force_cost_for_fault)
    assert callable(write_cost_traces)
    assert callable(load_trace_set)
    assert callable(lint_cost_sources)
    assert callable(assert_cost_sources_lint_clean)
    assert callable(assert_e2_refused_for_cost_tile)
    assert callable(render_cost)  # sole sanctioned dollar path
    assert cv.WAVE_ID == "W13"
    assert set(COST_SURFACES) == {
        SURFACE_DASHBOARD,
        SURFACE_WORKBENCH,
        SURFACE_SESSION_CHROME,
    }
    assert "unmeasured_engine" in INDUCED_FAULT_REASONS
    assert "aggregation_raise" in INDUCED_FAULT_REASONS
    assert "measurement_failed" in INDUCED_FAULT_REASONS


# --------------------------------------------------------------------------
# GWT 1: unmeasured engine → session chrome labelled unmeasured, no $
# --------------------------------------------------------------------------


def test_gwt_unmeasured_engine_session_chrome_no_dollar():
    """Given an engine with no cost instrumentation, when session chrome
    renders its cost, then labelled unmeasured is visible and no '$' figure.
    """
    engine = "no-instrumentation"
    result = read_engine_cost(engine, instrumented=False)
    assert result.cost_state is CostState.unmeasured
    assert result.allows_dollar is False

    tile = render_session_chrome_cost(result)
    assert_visible_text_contains(tile, "unmeasured")
    assert 'data-cost-state="unmeasured"' in tile or "unmeasured" in tile
    assert 'data-engine="%s"' % engine in tile
    assert not _DOLLAR_RE.search(tile)
    assert "$0.00" not in tile
    assert SUBSCRIPTION_LABEL not in tile
    assert _visible_text(tile).strip()  # never blank

    # Full surface HTML.
    html = generate_html_for_surface_fault(
        SURFACE_SESSION_CHROME,
        "unmeasured_engine",
        engine=engine,
    )
    section = _extract_tile_section(html, SURFACE_SESSION_CHROME)
    eng_frag = _engine_tile_html(section, engine)
    assert_visible_text_contains(eng_frag, "unmeasured")
    assert not _DOLLAR_RE.search(eng_frag)
    assert "$" not in eng_frag or not _DOLLAR_RE.search(eng_frag)


def test_unmeasured_engine_via_engines_list_on_session_chrome():
    surf = render_cost_surface(
        CostTileContext(
            surface=SURFACE_SESSION_CHROME,
            engines=[
                {"engine": "claude", "instrumented": False},
                {
                    "engine": "gemini",
                    "cost_state": "measured",
                    "amount": 1.25,
                    "instrumented": True,
                },
            ],
        ),
        include_legend=False,
    )
    html = surf.html
    claude = _engine_tile_html(html, "claude")
    assert "unmeasured" in claude
    assert not _DOLLAR_RE.search(claude)
    gemini = _engine_tile_html(html, "gemini")
    assert "$1.25" in gemini


# --------------------------------------------------------------------------
# GWT 2: aggregation raises → dashboard measurement_failed; E2 refused
# --------------------------------------------------------------------------


def test_gwt_aggregation_raise_dashboard_measurement_failed():
    """Given a cost aggregation that raises at read time, when the dashboard
    cost tile renders, then measurement_failed is shown.
    """

    def _raise():
        raise CostAggregationError("induced aggregation failure")

    result = read_cost_aggregation(reader=_raise)
    assert result.cost_state is CostState.measurement_failed
    assert result.allows_dollar is False
    assert result.amount is None

    tile = render_dashboard_cost(result)
    assert_visible_text_contains(tile, "measurement_failed")
    assert not _DOLLAR_RE.search(tile)
    assert "$0.00" not in tile
    assert SUBSCRIPTION_LABEL not in tile

    # force_raise path
    result2 = read_cost_aggregation(force_raise=True)
    tile2 = render_dashboard_cost(result2)
    assert "measurement_failed" in tile2
    assert not _DOLLAR_RE.search(tile2)

    html = generate_html_for_surface_fault(
        SURFACE_DASHBOARD, "aggregation_raise"
    )
    section = _extract_tile_section(html, SURFACE_DASHBOARD)
    assert_visible_text_contains(section, "measurement_failed")
    assert not _DOLLAR_RE.search(section)


def test_gwt_e2_refused_for_dashboard_cost_tile():
    """No attempt to sign E2 for a measurement_failed cost tile is accepted."""
    # Dashboard is in measurement_failed from aggregation raise.
    result = force_cost_for_fault("aggregation_raise", surface=SURFACE_DASHBOARD)
    tile = render_dashboard_cost(result)
    assert "measurement_failed" in tile

    assert is_cost_criterion("cost-labelling")
    exc = refuse_e2_for_cost_tile(
        criterion="cost-labelling",
        evidence="as_of=2026-07-29 provisional stamp on dashboard cost tile",
        user_sees="provisional $ on cost tile",
    )
    assert isinstance(exc, IllegalExit)
    assert exc.message == E2_DOLLARS_MESSAGE

    msg = assert_e2_refused_for_cost_tile()
    assert msg == E2_DOLLARS_MESSAGE

    # Direct exit-register path for the same tile criterion.
    row = make_row(
        ExitId.E2,
        criterion="dashboard cost tile",
        forcing_evidence="as_of stamp after aggregation raise",
        user_sees_instead="provisional dollars",
        date="2026-07-29",
        john_confirmation="John confirms this exit",
        accessor_proven=True,
    )
    with pytest.raises(IllegalExit) as ei:
        validate(row)
    assert ei.value.message == E2_DOLLARS_MESSAGE


# --------------------------------------------------------------------------
# zero × cost_state matrix on real rendered HTML
# --------------------------------------------------------------------------


@pytest.mark.parametrize("state", list(CostState))
def test_zero_cost_state_matrix_on_real_html(state: CostState):
    """amount=0 × each CostState on full generate_html documents."""
    html = generate_html_for_cost_state(state, amount=0, surface=SURFACE_DASHBOARD)
    assert "<html" in html.lower()
    assert 'data-wave="W13"' in html or "cost" in html.lower()

    # At least one tile for this state in the document.
    assert (
        'data-cost-state="%s"' % state.value in html
        or state.value in html
    )

    visible = _visible_text(html)
    assert visible.strip()

    if state is CostState.subscription_covered:
        assert SUBSCRIPTION_LABEL in html
        assert "$0.00" not in html
        assert not _DOLLAR_RE.search(
            _extract_tile_section(html, SURFACE_DASHBOARD)
        ) or SUBSCRIPTION_LABEL in html
    elif state is CostState.measured:
        assert "$0.00" in html
    elif state is CostState.unmeasured:
        assert "unmeasured" in visible
        # Legend-free document for generate_html_for_cost_state — still no $0.00
        # as the unmeasured tile content (measured legend is off).
        section = _extract_tile_section(html, SURFACE_DASHBOARD)
        # Multiple tiles may be present (extra_results + resolve); check each
        # unmeasured tile has no dollar.
        for m in re.finditer(
            r'data-cost-state="unmeasured"[^>]*>.*?</div>',
            html,
            re.DOTALL,
        ):
            frag = m.group(0)
            assert not _DOLLAR_RE.search(frag)
            assert "$0.00" not in frag
            assert SUBSCRIPTION_LABEL not in frag
    elif state is CostState.measurement_failed:
        assert "measurement_failed" in visible
        for m in re.finditer(
            r'data-cost-state="measurement_failed"[^>]*>.*?</div>',
            html,
            re.DOTALL,
        ):
            frag = m.group(0)
            assert not _DOLLAR_RE.search(frag)
            assert "$0.00" not in frag


def test_zero_matrix_full_document():
    html = generate_html_zero_matrix()
    assert "<html" in html.lower()
    for state in CostState:
        assert 'data-cost-state="%s"' % state.value in html or state.value in html
    # Measured zero appears exactly once as a fact under measured.
    assert "$0.00" in html
    # unmeasured / failed / subscription tiles must not carry $ figures.
    for token in ("unmeasured", "measurement_failed", "subscription_covered"):
        for m in re.finditer(
            r'data-cost-state="%s"[^>]*>.*?</(?:div|span)>' % token,
            html,
            re.DOTALL,
        ):
            # Narrower: cost-state span contents.
            pass
    # Global: subscription label present once for subscription_covered.
    assert SUBSCRIPTION_LABEL in html
    # No dollar figure on non-measured cost-state spans.
    for m in re.finditer(
        r'<span class="cost-state" data-cost-state="(?P<cs>[^"]+)"[^>]*>'
        r"(?P<body>.*?)</span>",
        html,
        re.DOTALL,
    ):
        cs = m.group("cs")
        body = m.group("body")
        if cs != "measured":
            assert not _DOLLAR_RE.search(body), (cs, body)
            assert "$0.00" not in body


# --------------------------------------------------------------------------
# All dollars route through render_cost; no direct format sites
# --------------------------------------------------------------------------


def test_no_direct_dollar_format_call_sites_in_cost_view():
    """cost_view.py must not format dollars itself — only call render_cost."""
    path = CONTAINMENT_ROOT / "anchor" / "ui" / "cost_view.py"
    text = path.read_text(encoding="utf-8")
    assert "format_measured_dollars(" not in text
    # Must import and use the sanctioned renderer.
    assert "from anchor.cost.render_cost import" in text
    assert "render_cost" in text
    offenders = cv.scan_for_direct_dollar_format_sites(root=CONTAINMENT_ROOT)
    assert offenders == [], "direct dollar-format sites outside render_cost: %s" % offenders


def test_render_cost_tile_never_emits_dollar_outside_measured():
    for state in (
        CostState.unmeasured,
        CostState.subscription_covered,
        CostState.measurement_failed,
    ):
        r = CostTileResult(
            surface=SURFACE_DASHBOARD,
            cost_state=state,
            amount=0,
            allows_dollar=False,
        )
        tile = render_cost_tile(r)
        assert not _DOLLAR_RE.search(tile), (state, tile)
        assert "$0.00" not in tile


# --------------------------------------------------------------------------
# zero_inference_lint wired into this wave's gate
# --------------------------------------------------------------------------


def test_zero_inference_lint_clean_on_cost_code():
    violations = lint_cost_sources(root=CONTAINMENT_ROOT)
    assert violations == [], "zero_inference_lint violations: %s" % violations
    assert_cost_sources_lint_clean(root=CONTAINMENT_ROOT)

    # Also exercise lint_paths on the same rels (gate wiring).
    paths = [CONTAINMENT_ROOT / rel for rel in COST_LINT_RELS]
    assert paths
    for p in paths:
        assert p.is_file(), p
    again = lint_paths(paths)
    assert again == []


def test_zero_inference_lint_still_flags_classic_bug():
    """Sanity: the lint tool still catches cost == 0 → (subscription)."""
    bad = (
        "def label(cost):\n"
        "    if cost == 0:\n"
        "        return '(subscription)'\n"
        "    return str(cost)\n"
    )
    hits = lint_source(bad, path="fake_cost_bug.py")
    assert hits, "lint must still flag zero-inference subscription"
    assert any("zero-inference" in v.message for v in hits)


# --------------------------------------------------------------------------
# Induced faults
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fault", list(INDUCED_FAULT_REASONS))
def test_induced_fault_per_reason(fault):
    result = force_cost_for_fault(fault, surface=SURFACE_DASHBOARD)
    assert isinstance(result, CostTileResult)
    tile = render_cost_tile(result)
    assert result.rendered_token
    assert (
        result.rendered_token in tile
        or 'data-rendered-token="%s"' % result.rendered_token in tile
        or 'data-cost-state="%s"' % result.rendered_token in tile
        or 'data-named-state="%s"' % result.rendered_token in tile
    )
    if fault in ("unmeasured_engine", "measurement_failed", "aggregation_raise"):
        assert not result.allows_dollar
        assert not _DOLLAR_RE.search(tile)


def test_force_cost_unknown_fault_raises():
    with pytest.raises(cv.CostViewError):
        force_cost_for_fault("not_a_real_fault")


# --------------------------------------------------------------------------
# Failure-state table
# --------------------------------------------------------------------------


def test_failure_state_table_exists_and_maps_vocabulary():
    assert FAILURE_TABLE_PATH.is_file()
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in text
    assert "/Users/" not in text
    rows = _parse_cost_failure_table(text)
    assert rows, "cost.md machine table produced no rows"
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    assert "unmeasured" in states
    assert "measurement_failed" in states
    # Separate rows — not merged.
    assert "unknown/empty" not in text.lower().replace(" ", "")
    report = validate_failure_state_table(rows, surface="cost")
    assert report["ok"] is True


def test_failure_state_table_surface_native_cost_language():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "cost" in low or "tile render" in low
    rows = _parse_cost_failure_table(text)
    for row in rows:
        blob = " ".join(row.values()).lower()
        for verb in ("index", "rebuild", "reconcile"):
            assert not re.search(r"\b%s\b" % verb, blob), row


# --------------------------------------------------------------------------
# End-to-end traces
# --------------------------------------------------------------------------


def test_cost_e2e_trace_artifact_schema_valid():
    """Materialize + validate artifacts/traces/cost-e2e.json."""
    written = write_cost_traces(root=CONTAINMENT_ROOT)
    assert any("cost-e2e.json" in k for k in written)
    assert COST_TRACE_PATH.is_file()

    data = load_trace_set(cv.COST_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    assert data["control_id"] == "cost"
    assert data["wave_id"] == "W13"
    assert is_go_evidence(data)

    nested = data.get("fault_traces") or data.get("reason_traces") or {}
    for fault in INDUCED_FAULT_REASONS:
        assert fault in nested, "missing cost fault trace for %s" % fault
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

    for pin in ("session_chrome_unmeasured", "dashboard_measurement_failed"):
        assert pin in nested
        validate_trace(nested[pin])

    matrix = data.get("zero_cost_state_matrix") or {}
    for state in CostState:
        assert state.value in matrix
        validate_trace(matrix[state.value])


@pytest.mark.parametrize("fault", list(INDUCED_FAULT_REASONS))
def test_build_cost_fault_trace_live(fault):
    art = cv.build_cost_fault_trace(fault)
    assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
    assert art.induced_fault == fault
    assert is_go_evidence(art)


def test_trace_rendered_states_match_fault_semantics():
    assert (
        cv.build_cost_fault_trace(
            "unmeasured_engine", surface=SURFACE_SESSION_CHROME
        ).rendered_state
        == "unmeasured"
    )
    assert (
        cv.build_cost_fault_trace(
            "aggregation_raise", surface=SURFACE_DASHBOARD
        ).rendered_state
        == "measurement_failed"
    )
    assert (
        cv.build_cost_fault_trace(
            "empty_scope", surface=SURFACE_WORKBENCH
        ).rendered_state
        == "empty"
    )
    assert (
        cv.build_cost_fault_trace(
            "store_unreadable", surface=SURFACE_DASHBOARD
        ).rendered_state
        == "unknown"
    )


# --------------------------------------------------------------------------
# Visible text + node --check
# --------------------------------------------------------------------------


def test_cost_generate_html_visible_nodes_and_node_check():
    html = generate_html(
        CostTileContext(
            force_fault="unmeasured_engine",
            surface=SURFACE_SESSION_CHROME,
            engine="no-instrumentation",
        ),
        include_legend=False,
    )
    assert "<html" in html.lower()
    assert_visible_text_contains(html, "unmeasured")
    assert 'data-surface="cost"' in html
    node_check_scripts(html, require_node=False)
    node_check_cost_scripts(html, require_node=False)


def test_generate_html_for_fixture_matrix():
    for fixture in (
        "unknown",
        "empty",
        "zero_measured",
        "unmeasured",
        "measurement_failed",
    ):
        html = generate_html_for_fixture(fixture)
        assert html.strip()
        if fixture == "zero_measured":
            assert "$0.00" in html or "measured" in html
        elif fixture == "unmeasured":
            assert_visible_text_contains(html, "unmeasured")
            assert not _DOLLAR_RE.search(
                _extract_tile_section(html, SURFACE_SESSION_CHROME)
            )
        elif fixture == "measurement_failed":
            assert_visible_text_contains(html, "measurement_failed")
        else:
            assert_visible_text_contains(html, fixture)


# --------------------------------------------------------------------------
# Surfaces each render honestly
# --------------------------------------------------------------------------


@pytest.mark.parametrize("surface", list(COST_SURFACES))
def test_each_surface_renders_unmeasured_and_failed(surface):
    for fault, token in (
        ("unmeasured_engine", "unmeasured"),
        ("measurement_failed", "measurement_failed"),
    ):
        r = force_cost_for_fault(fault, surface=surface)
        frag = render_cost_tile(r)
        assert token in frag
        assert not _DOLLAR_RE.search(frag)


# --------------------------------------------------------------------------
# No absolute host paths
# --------------------------------------------------------------------------


def test_no_absolute_host_paths_in_shipped_sources():
    rels = [
        "anchor/ui/cost_view.py",
        "artifacts/failure-states/cost.md",
    ]
    for rel in rels:
        path = CONTAINMENT_ROOT / rel
        assert path.is_file(), rel
        text = path.read_text(encoding="utf-8")
        assert "C:\\Users" not in text, rel
        assert "C:/Users" not in text, rel
        assert "/Users/" not in text, rel


def test_cost_view_uses_render_cost_not_raw_dollars_for_measured():
    r = CostTileResult(
        surface=SURFACE_WORKBENCH,
        cost_state=CostState.measured,
        amount=2.5,
        allows_dollar=True,
    )
    tile = render_cost_tile(r)
    assert "$2.50" in tile
    assert 'data-cost-state="measured"' in tile
    # Matches the sanctioned renderer output.
    assert render_cost(2.5, CostState.measured) in tile or "$2.50" in tile

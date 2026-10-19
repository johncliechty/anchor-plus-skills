"""W7 — cost_state enum + migration + dollar-fabrication ban.

Exercises:

* ``anchor.cost.cost_state`` — CostState ×4
* ``anchor.cost.read_cost_state`` — fail-closed partial migration
* ``anchor.cost.render_cost`` — sole sanctioned renderer (imports render_state)
* ``migrations/2026_07_29_add_cost_state.sql`` — backfill to unmeasured

Four-way matrix (zero × each state) + regression: no path emits ``$0.00``
as fact outside ``cost_state == measured``.

Gate: pytest -v tests/test_cost_state_2026_07_29.py
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from anchor.cost import cost_state as cs_mod
from anchor.cost import read_cost_state as read_mod
from anchor.cost import render_cost as render_mod
from anchor.cost.cost_state import (
    COST_STATE_COUNT,
    COST_STATE_TOKENS,
    SUBSCRIPTION_LABEL,
    CostState,
    InvalidCostState,
    coerce_cost_state,
)
from anchor.cost.read_cost_state import (
    COLUMN_ABSENT,
    COST_STATE_COLUMN,
    cost_state_for_spot_check_engine,
    read_cost_state,
    read_cost_state_from_schema,
)
from anchor.cost.render_cost import (
    DollarFabricationError,
    format_measured_dollars,
    generate_cost_html,
    render_cost,
    render_cost_for_engine,
    render_cost_row,
)
from anchor.ui.named_state import NamedState, render_state
from tools.rollup_evidence_gate import (
    fixture_spot_check_disagreement,
    measurement_failed_engines,
    validate_spot_check,
)

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = CONTAINMENT_ROOT / "migrations" / "2026_07_29_add_cost_state.sql"

EXPECTED_STATES = (
    "subscription_covered",
    "measured",
    "unmeasured",
    "measurement_failed",
)

_DOLLAR_RE = re.compile(r"\$\d")
_ZERO_DOLLAR_RE = re.compile(r"\$0(?:\.0+)?\b")


def _visible_text(html: str) -> str:
    """Strip tags to approximate visible text nodes."""
    text = re.sub(r"<[^>]+>", " ", html)
    return " ".join(text.split())


# --------------------------------------------------------------------------
# CostState enum shape
# --------------------------------------------------------------------------


def test_cost_state_has_exactly_four_members():
    assert len(CostState) == COST_STATE_COUNT == 4
    assert {s.value for s in CostState} == set(EXPECTED_STATES)
    assert COST_STATE_TOKENS == set(EXPECTED_STATES)


def test_subscription_label_comes_from_enum_not_from_zero():
    """The subscription string is an enum property, not a zero-inference."""
    assert CostState.subscription_covered.label == SUBSCRIPTION_LABEL
    assert SUBSCRIPTION_LABEL == "(subscription)"
    # Value token is not the label.
    assert CostState.subscription_covered.value == "subscription_covered"
    assert CostState.subscription_covered.value != SUBSCRIPTION_LABEL


def test_only_measured_allows_dollar_figure():
    assert CostState.measured.allows_dollar_figure is True
    for s in CostState:
        if s is not CostState.measured:
            assert s.allows_dollar_figure is False


def test_coerce_cost_state_accepts_tokens_and_members():
    assert coerce_cost_state("unmeasured") is CostState.unmeasured
    assert coerce_cost_state(CostState.measured) is CostState.measured
    assert coerce_cost_state("SUBSCRIPTION_COVERED") is CostState.subscription_covered


def test_coerce_cost_state_rejects_unknown():
    with pytest.raises(InvalidCostState):
        coerce_cost_state("free_tier")
    with pytest.raises(InvalidCostState):
        coerce_cost_state(None)


def test_module_exports_importable_by_gate():
    # Acceptance: every new module is imported by at least one gate test.
    assert cs_mod.CostState is CostState
    assert read_mod.read_cost_state is read_cost_state
    assert render_mod.render_cost is render_cost
    assert callable(render_state)  # W6 dependency exercised
    assert MIGRATION_PATH.is_file()


# --------------------------------------------------------------------------
# Migration SQL — backfill to unmeasured, not measured-zero
# --------------------------------------------------------------------------


def test_migration_file_exists_and_backfills_unmeasured():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "cost_state" in sql
    assert "ADD COLUMN cost_state" in sql
    assert "unmeasured" in sql
    # Backfill maps existing rows to unmeasured rather than measured-zero.
    assert re.search(
        r"SET\s+cost_state\s*=\s*'unmeasured'",
        sql,
        flags=re.IGNORECASE,
    )
    assert "WHERE cost_state IS NULL" in sql
    # Must not backfill to measured.
    assert not re.search(
        r"SET\s+cost_state\s*=\s*'measured'",
        sql,
        flags=re.IGNORECASE,
    )
    # No absolute host paths.
    assert "C:\\Users" not in sql
    assert "/Users/" not in sql


# --------------------------------------------------------------------------
# read_cost_state — fail-closed partial migration
# --------------------------------------------------------------------------


def test_read_cost_state_absent_column_is_measurement_failed():
    row = {"cost": 0, "id": "s1"}  # no cost_state key
    assert read_cost_state(row) is CostState.measurement_failed


def test_read_cost_state_null_is_measurement_failed():
    row = {"cost": 0, "cost_state": None}
    assert read_cost_state(row) is CostState.measurement_failed


def test_read_cost_state_unreadable_token_is_measurement_failed():
    row = {"cost": 0, "cost_state": "not_a_real_state"}
    assert read_cost_state(row) is CostState.measurement_failed
    row2 = {"cost": 0, "cost_state": "   "}
    assert read_cost_state(row2) is CostState.measurement_failed


def test_read_cost_state_none_row_is_measurement_failed():
    assert read_cost_state(None) is CostState.measurement_failed


def test_read_cost_state_known_tokens():
    for token in EXPECTED_STATES:
        row = {"cost_state": token}
        assert read_cost_state(row) is CostState(token)


def test_read_cost_state_never_invents_measured_or_subscription_on_partial():
    """Absent / NULL / unreadable never become measured or subscription_covered."""
    partials = [
        None,
        {},
        {"cost": 0},
        {"cost": 0, "cost_state": None},
        {"cost": 0, "cost_state": ""},
        {"cost": 0, "cost_state": "garbage"},
    ]
    for row in partials:
        got = read_cost_state(row)
        assert got is CostState.measurement_failed
        assert got is not CostState.measured
        assert got is not CostState.subscription_covered


def test_read_cost_state_from_schema_column_absent():
    assert (
        read_cost_state_from_schema(COLUMN_ABSENT)
        is CostState.measurement_failed
    )
    assert (
        read_cost_state_from_schema("measured", column_present=False)
        is CostState.measurement_failed
    )


def test_read_cost_state_from_schema_present_null():
    assert (
        read_cost_state_from_schema(None, column_present=True)
        is CostState.measurement_failed
    )


def test_read_cost_state_from_schema_present_token():
    assert (
        read_cost_state_from_schema("unmeasured", column_present=True)
        is CostState.unmeasured
    )


# --------------------------------------------------------------------------
# Four-way matrix: cost 0 × each CostState
# --------------------------------------------------------------------------


def test_matrix_zero_unmeasured_labelled_never_subscription_or_dollar_or_blank():
    """GWT: cost 0 + unmeasured → labelled unmeasured, never (subscription)/$0.00/blank."""
    html = render_cost(0, CostState.unmeasured)
    visible = _visible_text(html)
    assert visible.strip()
    assert "unmeasured" in visible
    assert SUBSCRIPTION_LABEL not in html
    assert "(subscription)" not in html
    assert "$0.00" not in html
    assert not _ZERO_DOLLAR_RE.search(html)
    assert not _DOLLAR_RE.search(html)
    assert 'data-cost-state="unmeasured"' in html
    # Uses W6 render_state for the NamedState node.
    assert 'data-named-state="unmeasured"' in html
    assert not re.search(r"<span[^>]*>\s*</span>", html)


def test_matrix_zero_subscription_covered_shows_subscription_from_enum():
    """GWT: cost 0 + subscription_covered → (subscription) from enum, not value."""
    html = render_cost(0, CostState.subscription_covered)
    assert SUBSCRIPTION_LABEL in html
    assert CostState.subscription_covered.label in html
    # Label identity: enum property, not a hard-coded zero branch.
    assert CostState.subscription_covered.label == SUBSCRIPTION_LABEL
    assert 'data-cost-state="subscription_covered"' in html
    # Must not also fabricate a dollar figure.
    assert "$0.00" not in html
    assert not _DOLLAR_RE.search(html)
    # Changing amount must not change the subscription label (state-driven).
    html_nonzero = render_cost(12.34, CostState.subscription_covered)
    assert SUBSCRIPTION_LABEL in html_nonzero
    assert "$12.34" not in html_nonzero


def test_matrix_zero_measured_emits_zero_dollars():
    """Measured zero is a real, trustworthy $0.00 — only legal under measured."""
    html = render_cost(0, CostState.measured)
    assert "$0.00" in html
    assert 'data-cost-state="measured"' in html
    assert SUBSCRIPTION_LABEL not in html
    assert "unmeasured" not in _visible_text(html)


def test_matrix_zero_measurement_failed_no_dollar_no_subscription():
    html = render_cost(0, CostState.measurement_failed)
    visible = _visible_text(html)
    assert "measurement_failed" in visible
    assert SUBSCRIPTION_LABEL not in html
    assert "$0.00" not in html
    assert not _DOLLAR_RE.search(html)
    assert 'data-named-state="measurement_failed"' in html


@pytest.mark.parametrize("state", list(CostState))
def test_matrix_zero_times_each_state_parametrized(state: CostState):
    """Full zero × each-state matrix (parametrized coverage)."""
    html = render_cost(0, state)
    assert html.strip()
    assert 'data-cost-state="%s"' % state.value in html
    visible = _visible_text(html)
    assert visible.strip(), "never blank for state %s" % state.value

    if state is CostState.subscription_covered:
        assert SUBSCRIPTION_LABEL in html
        assert "$0.00" not in html
    elif state is CostState.measured:
        assert "$0.00" in html
        assert SUBSCRIPTION_LABEL not in html
    elif state is CostState.unmeasured:
        assert "unmeasured" in visible
        assert SUBSCRIPTION_LABEL not in html
        assert "$0.00" not in html
    elif state is CostState.measurement_failed:
        assert "measurement_failed" in visible
        assert SUBSCRIPTION_LABEL not in html
        assert "$0.00" not in html


# --------------------------------------------------------------------------
# Dollar-fabrication ban
# --------------------------------------------------------------------------


def test_format_measured_dollars_raises_without_measured():
    """Raises if asked to emit $0.00 without cost_state == measured."""
    for state in (
        CostState.unmeasured,
        CostState.subscription_covered,
        CostState.measurement_failed,
    ):
        with pytest.raises(DollarFabricationError) as ei:
            format_measured_dollars(0, cost_state=state)
        msg = str(ei.value).lower()
        assert "measured" in msg
        assert "$0.00" in str(ei.value) or "dollar" in msg


def test_format_measured_dollars_allows_zero_under_measured():
    assert format_measured_dollars(0, cost_state=CostState.measured) == "$0.00"
    assert format_measured_dollars(0.0, cost_state="measured") == "$0.00"
    assert format_measured_dollars(Decimal("0"), cost_state=CostState.measured) == "$0.00"


def test_format_measured_dollars_nonzero():
    assert format_measured_dollars(1.5, cost_state=CostState.measured) == "$1.50"
    assert format_measured_dollars(12, cost_state=CostState.measured) == "$12.00"


def test_regression_no_path_emits_zero_dollars_as_fact_outside_measured():
    """Regression: no render path emits '$0.00' as fact outside measured."""
    dishonest_states = (
        CostState.unmeasured,
        CostState.subscription_covered,
        CostState.measurement_failed,
    )
    amounts = (0, 0.0, Decimal("0"), "0", None, 99.99)
    for state in dishonest_states:
        for amount in amounts:
            html = render_cost(amount, state)
            assert "$0.00" not in html, (state, amount, html)
            assert not _ZERO_DOLLAR_RE.search(html), (state, amount, html)
            if state is not CostState.measured:
                # No dollar figures at all outside measured.
                assert not _DOLLAR_RE.search(html), (state, amount, html)


def test_render_cost_missing_state_fail_closed_no_dollars():
    html = render_cost(0, None)
    assert "measurement_failed" in _visible_text(html)
    assert "$0.00" not in html
    assert SUBSCRIPTION_LABEL not in html


# --------------------------------------------------------------------------
# GWT: mid-deploy database (column does not exist)
# --------------------------------------------------------------------------


def test_gwt_mid_deploy_missing_column_renders_measurement_failed_no_dollar():
    """Given mid-deploy DB without cost_state column, when any cost surface
    renders, then every affected row shows measurement_failed, no '$' figure,
    no '(subscription)'.
    """
    mid_deploy_rows = [
        {"id": "s1", "cost": 0},
        {"id": "s2", "cost": 1.25},
        {"id": "s3", "cost": 0, "engine": "claude"},
        {"id": "s4"},  # no cost either
    ]
    rendered = [render_cost_row(r) for r in mid_deploy_rows]
    doc = generate_cost_html(mid_deploy_rows)

    for html in rendered:
        visible = _visible_text(html)
        assert "measurement_failed" in visible
        assert SUBSCRIPTION_LABEL not in html
        assert "(subscription)" not in html
        assert not _DOLLAR_RE.search(html)
        assert "$" not in html or "$" not in visible  # no dollar figure
        assert 'data-cost-state="measurement_failed"' in html
        # Failure is visible (not blank, not a plausible dollar).
        assert visible.strip()

    # Whole surface document.
    assert "measurement_failed" in doc
    assert SUBSCRIPTION_LABEL not in doc
    # No $digit figures in the document for these mid-deploy rows.
    assert not _DOLLAR_RE.search(doc)


def test_gwt_mid_deploy_schema_flag_column_present_false():
    cs = read_cost_state_from_schema("subscription_covered", column_present=False)
    html = render_cost(0, cs)
    assert "measurement_failed" in _visible_text(html)
    assert SUBSCRIPTION_LABEL not in html
    assert not _DOLLAR_RE.search(html)


# --------------------------------------------------------------------------
# GWT: W4 spot-check wrong figure → measurement_failed, no numeric dollar
# --------------------------------------------------------------------------


def test_gwt_spot_check_wrong_figure_engine_renders_measurement_failed():
    """Given the cost spot-check from W4 recorded a wrong figure, when
    render_cost is asked for that engine, then it renders measurement_failed
    and no numeric dollar value appears anywhere in the rendered HTML.
    """
    record = fixture_spot_check_disagreement()
    # Finalize so status is MEASUREMENT_FAILED where disagreed.
    _gate, _reason, finalized = validate_spot_check(record)
    failed = measurement_failed_engines(finalized)
    assert failed, "disagreement fixture must mark at least one engine failed"
    # claude disagrees in the fixture.
    assert "claude" in failed

    # Aggregated figure from the fixture (wrong vs source rows).
    wrong_amount_cents = 9999  # any dollar figure must not appear
    wrong_dollars = wrong_amount_cents / 100.0

    html = render_cost_for_engine(
        wrong_dollars,
        engine="claude",
        cost_state=CostState.measured,  # even if caller claims measured…
        spot_check_record=finalized,
    )
    visible = _visible_text(html)
    assert "measurement_failed" in visible
    assert not _DOLLAR_RE.search(html)
    assert "$" not in visible
    assert "99.99" not in html
    assert "$99.99" not in html
    assert SUBSCRIPTION_LABEL not in html

    # Direct path via measurement_failed_engines set.
    html2 = render_cost(
        wrong_dollars,
        CostState.measured,
        engine="claude",
        measurement_failed_engines=failed,
    )
    assert "measurement_failed" in _visible_text(html2)
    assert not _DOLLAR_RE.search(html2)

    # Agreed engines are not forced failed by the spot-check alone.
    html_ok = render_cost_for_engine(
        9.80,
        engine="gemini",
        cost_state=CostState.measured,
        spot_check_record=finalized,
    )
    assert "$9.80" in html_ok
    assert "measurement_failed" not in _visible_text(html_ok)


def test_cost_state_for_spot_check_engine_helper():
    assert (
        cost_state_for_spot_check_engine("claude", {"claude"})
        is CostState.measurement_failed
    )
    assert (
        cost_state_for_spot_check_engine("gemini", {"claude"})
        is CostState.unmeasured
    )


# --------------------------------------------------------------------------
# render_cost_row + generate_cost_html
# --------------------------------------------------------------------------


def test_render_cost_row_reads_state_and_amount():
    html = render_cost_row({"cost": 2.5, "cost_state": "measured"})
    assert "$2.50" in html
    html_u = render_cost_row({"cost": 0, "cost_state": "unmeasured"})
    assert "unmeasured" in _visible_text(html_u)
    assert "$0.00" not in html_u


def test_generate_cost_html_four_way_matrix_surface():
    doc = generate_cost_html()
    assert 'data-surface="cost-state"' in doc
    assert "unmeasured" in doc
    assert SUBSCRIPTION_LABEL in doc
    assert "$0.00" in doc  # measured zero cell only
    assert "measurement_failed" in doc
    # subscription and unmeasured tiles must not carry fabricated zeros.
    # Count of $0.00 should be exactly one (the measured cell).
    assert doc.count("$0.00") == 1


def test_render_cost_uses_render_state_from_w6():
    """render_cost imports and uses render_state for unmeasured / failed."""
    u = render_cost(0, CostState.unmeasured)
    f = render_cost(0, CostState.measurement_failed)
    # Same visible vocabulary as W6 NamedState labels.
    assert NamedState.unmeasured.label in _visible_text(u)
    assert NamedState.measurement_failed.label in _visible_text(f)
    assert 'class="named-state"' in u
    assert 'class="named-state"' in f


def test_no_absolute_host_paths_in_shipped_cost_sources():
    roots = [
        CONTAINMENT_ROOT / "anchor" / "cost",
        CONTAINMENT_ROOT / "migrations",
    ]
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".sql", ".md"}:
                continue
            text = path.read_text(encoding="utf-8")
            assert "C:\\Users" not in text, path
            assert "C:/Users" not in text, path
            assert "/Users/" not in text, path

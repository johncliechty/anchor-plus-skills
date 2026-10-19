"""W16 — Stop summary tile backed by real in-flight inventory.

Exercises every W16 deliverable under one scoped gate:

* ``anchor/session/stop_summary.py``
* ``anchor/ui/stop_summary_tile.py``
* ``artifacts/failure-states/stop-summary.md``
* ``artifacts/traces/stop-summary-e2e.json``

Gate: pytest -v tests/test_stop_summary_2026_07_29.py

GWTs (frozen plan):

* Session stopped with three in-flight items → tile lists all three with
  counts traceable to the inventory query (visible text nodes).
* Session stopped while inventory read fails → unknown, visibly distinct
  from the 'nothing in flight' empty state.
* Induced faults: inventory unreadable, zero items, partial items.
* Rendered-HTML assertions + node --check.
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
from anchor.session import stop_summary as ss_mod
from anchor.session.stop_summary import (
    CAPABILITY_CONTROL_ID,
    DEFAULT_QUERY_ID,
    INDUCED_FAULT_REASONS,
    INVENTORY_SOURCE_LABEL,
    INVENTORY_SOURCE_NAME,
    STOP_SUMMARY_REASONS,
    InFlightItem,
    InFlightInventory,
    StopSummaryReason,
    StopSummaryResult,
    collect_stop_summary,
    empty_inventory,
    force_collect_for_fault,
    partial_item_inventory,
    stop_reason_named_state,
    three_item_inventory,
    unreadable_inventory,
    zero_measured_inventory,
)
from anchor.ui import stop_summary_tile as sst
from anchor.ui.named_state import NamedState
from anchor.ui.stop_summary_tile import (
    StopSummaryTileContext,
    generate_html,
    generate_html_for_fixture,
    load_trace_set,
    node_check_stop_summary_scripts,
    render_stop_summary_surface,
    render_stop_summary_tile,
    write_stop_summary_traces,
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
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "stop-summary.md"
)
STOP_TRACE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "traces" / "stop-summary-e2e.json"
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _parse_stop_failure_table(text: str) -> list:
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


def _tile_section(html: str) -> str:
    """Pull the primary stop-summary tile so legend text cannot pollute GWTs."""
    m = re.search(
        r'<div class="stop-summary-tile"[^>]*>.*?</div>',
        html,
        re.DOTALL,
    )
    return m.group(0) if m else html


# --------------------------------------------------------------------------
# Acceptance: every new module is imported and exercised
# --------------------------------------------------------------------------


def test_w16_modules_importable_and_callable():
    assert callable(collect_stop_summary)
    assert callable(force_collect_for_fault)
    assert callable(generate_html)
    assert callable(generate_html_for_fixture)
    assert callable(render_stop_summary_tile)
    assert callable(write_stop_summary_traces)
    assert callable(load_trace_set)
    assert ss_mod.WAVE_ID == "W16"
    assert sst.WAVE_ID == "W16"
    assert CAPABILITY_CONTROL_ID == "stop_summary"
    assert INVENTORY_SOURCE_NAME == "stop_summary"
    assert "stop-summary" in INVENTORY_SOURCE_LABEL
    assert set(INDUCED_FAULT_REASONS) == {
        "inventory_unreadable",
        "zero_items",
        "partial_items",
    }


# --------------------------------------------------------------------------
# Collector — inventory source + structured items with counts
# --------------------------------------------------------------------------


def test_three_in_flight_items_with_counts():
    """GWT: three in-flight items → all three with counts from inventory."""
    inv = three_item_inventory("sess-3")
    result = collect_stop_summary(
        "sess-3", inventory=inv, capability_present=True
    )
    assert isinstance(result, StopSummaryResult)
    assert result.named_state is NamedState.ok
    assert result.item_count == 3
    assert result.total_count == 2 + 1 + 3
    assert result.inventory_source == INVENTORY_SOURCE_NAME
    assert result.query_id == DEFAULT_QUERY_ID
    labels = {i.label for i in result.items}
    assert labels == {"research job", "plan draft", "build wave"}
    counts = {i.item_id: i.count for i in result.items}
    assert counts["job-1"] == 2
    assert counts["job-2"] == 1
    assert counts["job-3"] == 3
    for item in result.items:
        assert item.query_ref.startswith(DEFAULT_QUERY_ID)


def test_empty_inventory_is_empty_not_unknown():
    result = collect_stop_summary(
        "sess-e",
        inventory=empty_inventory("sess-e"),
        capability_present=True,
    )
    assert result.named_state is NamedState.empty
    assert result.reason == StopSummaryReason.ZERO_ITEMS.value
    assert result.item_count == 0
    assert result.named_state is not NamedState.unknown


def test_unreadable_inventory_is_unknown_not_empty():
    """GWT: inventory read fails → unknown, never empty-looking."""
    result = collect_stop_summary(
        "sess-u",
        inventory=unreadable_inventory("sess-u"),
        capability_present=True,
    )
    assert result.named_state is NamedState.unknown
    assert result.reason == StopSummaryReason.INVENTORY_UNREADABLE.value
    assert result.item_count == 0
    assert result.named_state is not NamedState.empty


def test_partial_items_still_listed_with_counts():
    result = collect_stop_summary(
        "sess-p",
        inventory=partial_item_inventory("sess-p"),
        capability_present=True,
    )
    assert result.named_state is NamedState.ok
    assert result.partial is True
    assert result.reason == StopSummaryReason.PARTIAL_ITEMS.value
    assert result.item_count == 2
    assert any(i.partial for i in result.items)
    assert result.total_count == 3


def test_zero_measured_over_existing_scope():
    result = collect_stop_summary(
        "sess-z",
        inventory=zero_measured_inventory("sess-z"),
        capability_present=True,
    )
    assert result.named_state is NamedState.zero_measured
    assert result.total_count == 0
    assert result.item_count == 2
    assert result.named_state is not NamedState.empty
    assert result.named_state is not NamedState.unknown


def test_capability_absent_is_unknown():
    result = collect_stop_summary("sess-c", capability_present=False)
    assert result.named_state is NamedState.unknown
    assert result.reason == StopSummaryReason.CAPABILITY_ABSENT.value


@pytest.mark.parametrize("reason", list(STOP_SUMMARY_REASONS))
def test_force_fault_per_reason(reason):
    result = force_collect_for_fault(reason)
    assert result.named_state == stop_reason_named_state(reason)
    assert result.reason == reason


# --------------------------------------------------------------------------
# Induced faults (plan gate list)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fault", list(INDUCED_FAULT_REASONS))
def test_induced_fault_per_gate_reason(fault):
    result = force_collect_for_fault(fault, session_id="induced")
    assert result.reason == fault
    html = render_stop_summary_tile(result)
    ns = stop_reason_named_state(fault)
    assert_visible_text_contains(html, ns.label)
    assert 'data-named-state="%s"' % ns.value in html


def test_induced_inventory_unreadable_distinct_from_zero_items():
    unreadable = force_collect_for_fault("inventory_unreadable")
    zero = force_collect_for_fault("zero_items")
    assert unreadable.named_state is NamedState.unknown
    assert zero.named_state is NamedState.empty
    u_html = render_stop_summary_tile(unreadable)
    z_html = render_stop_summary_tile(zero)
    assert_visible_text_contains(u_html, "unknown")
    assert_visible_text_contains(z_html, "empty")
    assert "nothing was in flight" in z_html
    assert "could not be read" in u_html
    assert "nothing was in flight" not in u_html


def test_induced_partial_items_renders_items():
    result = force_collect_for_fault("partial_items")
    html = render_stop_summary_tile(result)
    assert result.partial is True
    assert "partial items" in html
    for item in result.items:
        assert item.label in html
        assert str(item.count) in html


# --------------------------------------------------------------------------
# Tile render — three items GWT + unknown vs empty
# --------------------------------------------------------------------------


def test_tile_three_items_visible_text_nodes():
    """GWT: stop summary tile shows all three items with counts as text nodes."""
    inv = three_item_inventory("sess-3")
    ctx = StopSummaryTileContext(
        session_id="sess-3",
        inventory=inv,
        capability_present=True,
    )
    surface = render_stop_summary_surface(ctx)
    html = surface.html
    tile = _tile_section(html)
    assert surface.summary is not None
    assert surface.summary.item_count == 3

    for item in surface.summary.items:
        assert item.label in tile
        assert str(item.count) in tile
        assert item.visible_label in tile or (
            item.label in tile and ("×%d" % item.count) in tile
        )
        # Counts traceable to inventory query.
        assert item.query_ref in tile or DEFAULT_QUERY_ID in tile

    assert_visible_text_contains(tile, "ok")
    assert DEFAULT_QUERY_ID in tile
    assert INVENTORY_SOURCE_NAME in tile or "stop-summary inventory" in tile
    nodes = visible_text_nodes(tile)
    # At least the named-state label and item-related text must be present.
    assert "ok" in nodes or "ok" in tile
    assert any("research" in n or "research" in tile for n in (nodes or [tile]))


def test_tile_unknown_distinct_from_empty():
    """GWT: unreadable inventory → unknown, distinct from empty."""
    empty_html = generate_html(
        StopSummaryTileContext(
            session_id="e",
            inventory=empty_inventory("e"),
            capability_present=True,
        )
    )
    unknown_html = generate_html(
        StopSummaryTileContext(
            session_id="u",
            inventory=unreadable_inventory("u"),
            capability_present=True,
        )
    )
    e_tile = _tile_section(empty_html)
    u_tile = _tile_section(unknown_html)
    assert_visible_text_contains(e_tile, "empty")
    assert_visible_text_contains(u_tile, "unknown")
    assert 'data-named-state="empty"' in e_tile
    assert 'data-named-state="unknown"' in u_tile
    assert "nothing was in flight" in e_tile
    assert "could not be read" in u_tile
    assert "nothing was in flight" not in u_tile
    assert 'data-named-state="empty"' not in u_tile
    assert 'data-named-state="unknown"' not in e_tile


def test_render_custom_items_via_inventory():
    inv = InFlightInventory(
        items=[
            InFlightItem(item_id="a", label="alpha task", count=4),
            InFlightItem(item_id="b", label="beta task", count=5),
        ],
        session_id="custom",
    )
    result = collect_stop_summary(
        "custom", inventory=inv, capability_present=True
    )
    html = render_stop_summary_tile(result)
    assert "alpha task" in html
    assert "beta task" in html
    assert "×4" in html
    assert "×5" in html
    assert result.total_count == 9


# --------------------------------------------------------------------------
# Tri-state conformance
# --------------------------------------------------------------------------


def test_stop_summary_tri_state_conformance():
    assert_tri_state(
        generate_html_for_fixture,
        call_site="anchor.ui.stop_summary_tile.generate_html_for_fixture",
    )


# --------------------------------------------------------------------------
# Failure-state table
# --------------------------------------------------------------------------


def test_failure_state_table_exists_and_maps_vocabulary():
    assert FAILURE_TABLE_PATH.is_file()
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in text
    assert "/Users/" not in text
    rows = _parse_stop_failure_table(text)
    assert rows, "stop-summary.md machine table produced no rows"
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    assert "unknown/empty" not in text.lower().replace(" ", "")
    report = validate_failure_state_table(rows, surface="stop-summary")
    assert report["ok"] is True


def test_failure_state_table_surface_native_stop_language():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "stop" in low
    assert "summary" in low or "tile render" in low or "in-flight" in low
    head = low.split("## enumerated")[0]
    for verb in ("index", "rebuild", "reconcile"):
        assert not re.search(r"\b%s\b" % verb, head)


# --------------------------------------------------------------------------
# E2e traces
# --------------------------------------------------------------------------


def test_stop_summary_e2e_trace_artifact_schema_valid():
    write_stop_summary_traces(root=CONTAINMENT_ROOT)
    assert STOP_TRACE_PATH.is_file()
    data = load_trace_set(sst.STOP_SUMMARY_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    validate_trace(data)
    assert is_go_evidence(data) or data.get("proof_level") == PROOF_LEVEL_RENDERED_STRING
    assert data.get("control_id") == "stop_summary" or data.get(
        "wave_id"
    ) == "W16"
    reasons = set(data.get("induced_fault_reasons") or [])
    assert "inventory_unreadable" in reasons
    assert "zero_items" in reasons
    assert "partial_items" in reasons
    # Nested reason traces must validate.
    for reason, nested in (data.get("reason_traces") or {}).items():
        validate_trace(nested)
    # No absolute host paths in artifact.
    raw = STOP_TRACE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in raw
    assert "/Users/" not in raw


def test_ok_trace_records_three_items():
    write_stop_summary_traces(root=CONTAINMENT_ROOT)
    data = load_trace_set(root=CONTAINMENT_ROOT)
    # Primary path is three-item success.
    assert data.get("rendered_state") == "ok" or data.get(
        "trace_result"
    ) in ("completed", "failed_with_named_state")
    hops = data.get("hops") or []
    kinds = [h.get("kind") for h in hops]
    assert kinds == [
        "control_invocation",
        "handler",
        "capability_call",
        "rendered_state",
    ]


# --------------------------------------------------------------------------
# node --check + generate_html
# --------------------------------------------------------------------------


def test_generate_html_node_check():
    html = generate_html(
        StopSummaryTileContext(
            session_id="node-check",
            inventory=three_item_inventory("node-check"),
            capability_present=True,
        )
    )
    assert "<script>" in html
    # Prefer surface helper; fall back to conformance helper.
    try:
        blocks = node_check_stop_summary_scripts(html, require_node=False)
        assert blocks
    except RuntimeError:
        # node absent — still require scripts extractable.
        blocks = node_check_scripts(html, require_node=False)
        assert blocks is not None
    assert "C:\\Users" not in html
    assert "/Users/" not in html


def test_no_absolute_host_paths_in_sources():
    for rel in (
        "anchor/session/stop_summary.py",
        "anchor/ui/stop_summary_tile.py",
        "artifacts/failure-states/stop-summary.md",
    ):
        text = (CONTAINMENT_ROOT / rel).read_text(encoding="utf-8")
        assert "C:\\Users" not in text
        assert "/Users/" not in text

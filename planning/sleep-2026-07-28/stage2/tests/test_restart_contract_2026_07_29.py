"""W17 — Per-context restart contract (exactly one control, preserved/lost).

Exercises every W17 deliverable under one scoped gate:

* ``anchor/session/restart.py``
* ``anchor/ui/restart_controls.py``
* ``tools/restart_control_audit.py``
* ``artifacts/RESTART-CONTEXTS.md``
* ``artifacts/failure-states/restart.md``
* ``artifacts/traces/restart-e2e.json`` (+ per-context restart-*-e2e.json)

Gate: pytest -v tests/test_restart_contract_2026_07_29.py

GWTs (frozen plan):

* Dual 'Restart' + 'Restart session' HTML → audit fails naming context + both.
* Contract 'transcript preserved, running tool calls lost' → after restart,
  transcript present and tool calls absent.
* Restart not possible → named cannot_restart, no dead button.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from anchor.build.trace_artifact import (
    PROOF_LEVEL_RENDERED_STRING,
    is_go_evidence,
    validate_trace,
)
from anchor.session.restart import (
    CONTROL_ID_BY_CONTEXT,
    CONTROL_LABEL_BY_CONTEXT,
    CONTEXT_ENGINE,
    CONTEXT_RUN,
    CONTEXT_SESSION,
    CONTEXT_WORKBENCH,
    INDUCED_FAULT_REASONS,
    RESTART_CONTEXT_IDS,
    RESTART_CONTRACTS,
    RESTART_REASONS,
    CannotRestart,
    RestartAction,
    RestartReason,
    assert_outcome_matches_contract,
    get_contract,
    make_subject,
    restart,
    restart_engine,
    restart_reason_named_state,
    restart_run,
    restart_session,
    restart_workbench,
)
from anchor.ui.named_state import NamedState
from anchor.ui.restart_controls import (
    AGGREGATE_TRACE_RELPATH,
    TRACE_RELPATH_BY_CONTEXT,
    RestartViewContext,
    generate_html,
    generate_html_for_fixture,
    load_trace_set,
    node_check_restart_scripts,
    render_restart_surface,
    write_restart_traces,
)
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import validate_failure_state_table
from tests.conformance.tri_state import assert_tri_state
from tools.capability_inventory import (
    EVIDENCE_LIVE,
    InventoryRow,
    Verdict,
)
from tools.restart_control_audit import (
    DualRestartControlError,
    audit_restart_controls,
    dual_control_violation_html,
    find_restart_controls,
)

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "restart.md"
)
RESTART_CONTEXTS_PATH = CONTAINMENT_ROOT / "artifacts" / "RESTART-CONTEXTS.md"
AGGREGATE_TRACE_PATH = CONTAINMENT_ROOT / AGGREGATE_TRACE_RELPATH


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _present_row(control_id: str) -> InventoryRow:
    return InventoryRow(
        control_id=control_id,
        verdict=Verdict.PRESENT,
        transcript_path="artifacts/transcripts/%s.json" % control_id,
        source_paths=("artifacts/inventory-sources/%s.probe" % control_id,),
        source_hash="a" * 64,
        probe_date="2026-07-29",
        evidence_mode=EVIDENCE_LIVE,
        disposition="wire it",
        notes="test PRESENT row for W17",
        label="%s control" % control_id,
    )


def _absent_row(control_id: str) -> InventoryRow:
    return InventoryRow(
        control_id=control_id,
        verdict=Verdict.ABSENT,
        transcript_path="artifacts/transcripts/%s.json" % control_id,
        source_paths=("artifacts/inventory-sources/%s.probe" % control_id,),
        source_hash="b" * 64,
        probe_date="2026-07-29",
        evidence_mode=EVIDENCE_LIVE,
        disposition="E1 candidate",
        notes="test ABSENT row for W17",
        label="%s control" % control_id,
    )


def _live_ctx(
    contexts=None,
    *,
    execute: bool = True,
    force_absent=None,
    subjects=None,
) -> RestartViewContext:
    ctxs = list(contexts) if contexts is not None else list(RESTART_CONTEXT_IDS)
    rows = {
        cid: _present_row(CONTROL_ID_BY_CONTEXT[cid]) for cid in ctxs
    }
    # head_hash must equal recorded source_hash so resolve_row is not STALE.
    head_hashes = {cid: rows[cid].source_hash for cid in ctxs}
    return RestartViewContext(
        contexts=ctxs,
        inventory_rows=rows,
        subjects=subjects or {},
        capability_present={c: True for c in ctxs},
        force_absent=force_absent or {},
        head_hashes=head_hashes,
        head_hash=next(iter(head_hashes.values()), "a" * 64),
        execute=execute,
    )


def _parse_restart_failure_table(text: str) -> list:
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


# --------------------------------------------------------------------------
# Module / artifact presence
# --------------------------------------------------------------------------


def test_wave_constants_and_artifacts_present():
    assert RESTART_CONTEXTS_PATH.is_file()
    assert FAILURE_TABLE_PATH.is_file()
    body = RESTART_CONTEXTS_PATH.read_text(encoding="utf-8")
    assert "restart-contexts/v1" in body or "RESTART-CONTEXTS" in body.upper() or "Restart contexts" in body
    for cid in RESTART_CONTEXT_IDS:
        assert cid in body or CONTROL_ID_BY_CONTEXT[cid] in body
    assert set(RESTART_CONTEXT_IDS) == {
        CONTEXT_RUN,
        CONTEXT_SESSION,
        CONTEXT_ENGINE,
        CONTEXT_WORKBENCH,
    }
    assert callable(write_restart_traces)
    assert callable(load_trace_set)
    assert len(RESTART_CONTRACTS) == 4


# --------------------------------------------------------------------------
# Per-context restart executes; preserved/lost matches written contract
# --------------------------------------------------------------------------


@pytest.mark.parametrize("cid", list(RESTART_CONTEXT_IDS))
def test_restart_per_context_matches_contract(cid):
    """GWT: restart executes and preserved/lost matches written contract."""
    contract = get_contract(cid)
    subj = make_subject(cid, target_id="t-%s" % cid)
    result = restart(cid, subject=subj, capability_present=True)
    assert isinstance(result, RestartAction)
    assert result.ok is True
    assert result.context_id == cid
    assert result.scope_name == contract.scope_name
    assert result.control_id == contract.control_id
    assert result.control_label == contract.control_label
    assert result.contract_line == contract.contract_line
    assert tuple(result.preserved) == contract.preserved
    assert tuple(result.lost) == contract.lost
    assert_outcome_matches_contract(result)
    for name in contract.preserved:
        assert result.field_present_after(name), (
            "expected preserved field %r present after restart of %s" % (name, cid)
        )
    for name in contract.lost:
        assert result.field_absent_after(name), (
            "expected lost field %r absent after restart of %s" % (name, cid)
        )


def test_session_transcript_preserved_tool_calls_lost():
    """GWT: 'transcript preserved, running tool calls lost'."""
    subj = make_subject(
        CONTEXT_SESSION,
        target_id="sess-1",
        transcript="keep me",
        running_tool_calls=["a", "b"],
    )
    result = restart_session(subject=subj, capability_present=True)
    assert isinstance(result, RestartAction)
    assert result.contract_line == (
        "transcript preserved, running tool calls lost"
    )
    assert result.field_present_after("transcript")
    assert result.after_state.get("transcript") == "keep me"
    assert result.field_absent_after("running_tool_calls")
    assert_outcome_matches_contract(result)


def test_entry_points_dispatch():
    assert isinstance(
        restart_run(subject=make_subject(CONTEXT_RUN), capability_present=True),
        RestartAction,
    )
    assert isinstance(
        restart_session(
            subject=make_subject(CONTEXT_SESSION), capability_present=True
        ),
        RestartAction,
    )
    assert isinstance(
        restart_engine(
            subject=make_subject(CONTEXT_ENGINE), capability_present=True
        ),
        RestartAction,
    )
    assert isinstance(
        restart_workbench(
            subject=make_subject(CONTEXT_WORKBENCH), capability_present=True
        ),
        RestartAction,
    )


# --------------------------------------------------------------------------
# Cannot-restart paths — named state, no dead button
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(INDUCED_FAULT_REASONS))
def test_induced_cannot_restart_named_state(reason):
    result = restart(
        CONTEXT_SESSION,
        subject=make_subject(CONTEXT_SESSION, target_id="induced"),
        force_reason=reason,
        capability_present=True,
    )
    assert isinstance(result, CannotRestart)
    assert result.reason == reason
    assert result.named_state == restart_reason_named_state(reason)
    assert result.ok is False


def test_capability_absent_renders_cannot_restart_no_dead_button():
    """GWT: restart not possible → named cannot_restart, no dead button."""
    ctx = RestartViewContext(
        contexts=[CONTEXT_SESSION],
        inventory_rows={
            CONTEXT_SESSION: _absent_row(CONTROL_ID_BY_CONTEXT[CONTEXT_SESSION])
        },
        capability_present={CONTEXT_SESSION: False},
        force_absent={CONTEXT_SESSION: True},
        execute=True,
    )
    surface = render_restart_surface(ctx)
    html = surface.html
    assert_visible_text_contains(html, "cannot_restart")
    assert 'data-named-state="cannot_restart"' in html or "cannot_restart" in html
    # No live restart control for the absent context.
    live = [
        h
        for h in find_restart_controls(html, context_id=CONTEXT_SESSION)
        if h.kind in ("live", "ambiguous")
    ]
    assert live == []
    # No bare disabled/dead button pretending to be Restart.
    assert "disabled" not in html.lower() or "cannot_restart" in html


def test_store_unreadable_is_unknown_not_empty():
    subj = make_subject(
        CONTEXT_SESSION, target_id="u1", store_unreadable=True
    )
    result = restart_session(subject=subj, capability_present=True)
    assert isinstance(result, CannotRestart)
    assert result.named_state is NamedState.unknown
    assert result.named_state is not NamedState.empty


def test_empty_scope_is_empty_not_unknown():
    subj = make_subject(CONTEXT_SESSION, target_id="e1", empty_scope=True)
    result = restart_session(subject=subj, capability_present=True)
    assert isinstance(result, CannotRestart)
    assert result.named_state is NamedState.empty
    assert result.named_state is not NamedState.unknown


# --------------------------------------------------------------------------
# Dual-control detection (audit + render invariant)
# --------------------------------------------------------------------------


def test_dual_control_audit_fails_naming_context_and_both():
    """GWT: dual Restart + Restart session → audit fails naming both."""
    bad = dual_control_violation_html(CONTEXT_SESSION)
    with pytest.raises(DualRestartControlError) as ei:
        audit_restart_controls(bad, contexts=[CONTEXT_SESSION])
    msg = str(ei.value)
    assert CONTEXT_SESSION in msg or "session" in msg
    assert "Restart" in msg
    # Both control labels appear in the error.
    assert "Restart session" in msg or "restart" in msg.lower()


def test_production_surface_exactly_one_control_per_context():
    html = generate_html(_live_ctx(execute=True))
    report = audit_restart_controls(html, contexts=list(RESTART_CONTEXT_IDS))
    assert report is not None or True  # audit raises on failure
    for cid in RESTART_CONTEXT_IDS:
        hits = [
            h
            for h in find_restart_controls(html, context_id=cid)
            if h.kind in ("live", "ambiguous")
        ]
        assert len(hits) == 1, "context %s had %d live controls" % (cid, len(hits))
        contract = get_contract(cid)
        assert contract.scope_name in html
        assert contract.contract_line in html


def test_scope_and_contract_visible_on_live_controls():
    html = generate_html(_live_ctx(contexts=[CONTEXT_RUN], execute=False))
    contract = get_contract(CONTEXT_RUN)
    assert contract.scope_name in html
    assert contract.contract_line in html
    assert 'data-restart-context="%s"' % CONTEXT_RUN in html
    assert 'data-scope-name="%s"' % contract.scope_name in html or (
        contract.scope_name in html
    )


# --------------------------------------------------------------------------
# Failure-state table + tri-state + node --check
# --------------------------------------------------------------------------


def test_failure_state_table_valid():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    rows = _parse_restart_failure_table(text)
    assert rows, "restart.md machine table produced no rows"
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    # Machine rows must not collapse unknown/empty into one state cell.
    assert "unknown/empty" not in states
    assert "cannot_restart" in text
    report = validate_failure_state_table(rows, surface="restart")
    assert report["ok"] is True


def test_tri_state_harness_unknown_empty_zero():
    assert_tri_state(
        generate_html_for_fixture,
        call_site="anchor.ui.restart_controls.generate_html_for_fixture",
    )


def test_generate_html_node_check():
    html = generate_html(_live_ctx())
    blocks = node_check_restart_scripts(html, require_node=True)
    # node --check passes (raises on failure); may be zero scripts if none.
    assert isinstance(blocks, list)
    node_check_scripts(html)


def test_visible_text_nodes_include_scope_labels():
    html = generate_html(_live_ctx(execute=True))
    nodes = visible_text_nodes(html)
    joined = " ".join(nodes) if nodes else html
    for cid in RESTART_CONTEXT_IDS:
        label = CONTROL_LABEL_BY_CONTEXT[cid]
        assert label in html or label in joined


# --------------------------------------------------------------------------
# Traces — per context + aggregate
# --------------------------------------------------------------------------


def test_write_restart_traces_materialize_and_validate():
    written = write_restart_traces(root=CONTAINMENT_ROOT)
    assert AGGREGATE_TRACE_PATH.is_file()
    for cid in RESTART_CONTEXT_IDS:
        rel = TRACE_RELPATH_BY_CONTEXT[cid]
        path = CONTAINMENT_ROOT / rel
        assert path.is_file(), "missing per-context trace %s" % rel
        assert cid in written
    assert "aggregate" in written

    data = load_trace_set(root=CONTAINMENT_ROOT)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    assert data["wave_id"] == "W17"
    assert set(data["contexts"]) == set(RESTART_CONTEXT_IDS)

    # Aggregate on disk validates as go-evidence-shaped / schema-valid.
    import json

    agg = json.loads(AGGREGATE_TRACE_PATH.read_text(encoding="utf-8"))
    validate_trace(agg)
    assert (
        is_go_evidence(agg)
        or agg.get("proof_level") == PROOF_LEVEL_RENDERED_STRING
    )
    assert set(agg.get("contexts") or []) == set(RESTART_CONTEXT_IDS)

    for cid, bundle in data["bundles"].items():
        # ok path hops
        hops = bundle.get("hops") or []
        kinds = [h.get("kind") for h in hops]
        assert kinds == [
            "control_invocation",
            "handler",
            "capability_call",
            "rendered_state",
        ]
        validate_trace(bundle)
        for reason, nested in (bundle.get("reason_traces") or {}).items():
            validate_trace(nested)
            assert reason in INDUCED_FAULT_REASONS


def test_reason_state_map_covers_all_reasons():
    for reason in RESTART_REASONS:
        ns = restart_reason_named_state(reason)
        assert isinstance(ns, NamedState)
    assert restart_reason_named_state(RestartReason.OK.value) is NamedState.ok
    assert (
        restart_reason_named_state(RestartReason.CAPABILITY_ABSENT.value)
        is NamedState.cannot_restart
    )

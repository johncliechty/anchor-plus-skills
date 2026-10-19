"""W10 — Open + Run control honesty (dead-control, cannot-*, e2e traces).

Exercises every W10 deliverable under one scoped gate:

* ``anchor/ui/dead_control.py``
* ``anchor/session/open_work.py``
* ``anchor/session/run_work.py``
* ``anchor/ui/open_run_view.py``
* ``anchor/ui/open_run_traces.py``
* ``artifacts/failure-states/open-run.md``
* ``artifacts/traces/open-e2e.json`` / ``run-e2e.json``
* ``artifacts/EARLY-SLICE-PARTIAL.md``

Gate: pytest -v tests/test_open_run_2026_07_29.py

GWTs (frozen plan):

* Run capability ABSENT → no Run button; named cannot-run visible;
  dead-control audit finds zero clickable no-ops.
* Open with unreadable project store → **unknown**, not empty;
  empty list is visibly distinct.
* PRESENT + W5 signed-exit still emits e2e traces + failure-state table
  (PRESENT removes build work, never evidence).
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from anchor.build.trace_artifact import (
    PROOF_LEVEL_RENDERED_STRING,
    is_go_evidence,
    validate_trace,
)
from anchor.session import open_work as open_mod
from anchor.session import run_work as run_mod
from anchor.session.open_work import (
    OPEN_REASONS,
    CannotOpen,
    OpenReason,
    OpenedWork,
    ProjectRecord,
    ProjectStore,
    empty_store,
    list_projects_state,
    open_reason_named_state,
    open_work,
    unreadable_store,
)
from anchor.session.run_work import (
    RUN_REASONS,
    CannotRun,
    LiveRunHandle,
    RunReason,
    empty_run_env,
    list_targets_state,
    make_run_env,
    run_reason_named_state,
    run_work,
)
from anchor.ui import dead_control as dc
from anchor.ui import open_run_traces as ort
from anchor.ui import open_run_view as orv
from anchor.ui.dead_control import (
    CONTROL_OPEN,
    CONTROL_RUN,
    ControlMode,
    DeadControlAuditError,
    DeadControlError,
    assert_no_dead_controls,
    audit_dead_controls,
    count_cannot_states,
    count_live_controls,
    decide_control,
    render_cannot_state,
    render_control,
    render_live_control,
)
from anchor.ui.named_state import NamedState, render_state
from anchor.ui.open_run_view import (
    OpenRunViewContext,
    generate_html,
    generate_html_for_fixture,
    render_open_control,
    render_run_control,
    render_workbench,
)
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import (
    TableValidationError,
    validate_failure_state_table,
)
from tests.conformance.tri_state import assert_tri_state
from tools.capability_inventory import (
    EVIDENCE_LIVE,
    EVIDENCE_REPLAY,
    InventoryRow,
    Verdict,
    may_authorize_live_control,
)

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "open-run.md"
)
EARLY_SLICE_PATH = CONTAINMENT_ROOT / "artifacts" / "EARLY-SLICE-PARTIAL.md"
OPEN_TRACE_PATH = CONTAINMENT_ROOT / "artifacts" / "traces" / "open-e2e.json"
RUN_TRACE_PATH = CONTAINMENT_ROOT / "artifacts" / "traces" / "run-e2e.json"

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _present_row(control_id: str) -> InventoryRow:
    """Synthetic live PRESENT row that authorizes a live control."""
    return InventoryRow(
        control_id=control_id,
        verdict=Verdict.PRESENT,
        transcript_path="artifacts/transcripts/%s.json" % control_id,
        source_paths=("artifacts/inventory-sources/%s.probe" % control_id,),
        source_hash="a" * 64,
        probe_date="2026-07-29",
        evidence_mode=EVIDENCE_LIVE,
        disposition="wire it",
        notes="test PRESENT row for W10",
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
        notes="test ABSENT row for W10",
        label="%s control" % control_id,
    )


def _parse_open_run_failure_table(text: str) -> list:
    """Parse the machine-readable rows table from open-run.md."""
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
            # End of first machine-readable table.
            break
    return rows


# --------------------------------------------------------------------------
# Acceptance: every new module is imported and exercised
# --------------------------------------------------------------------------


def test_w10_modules_importable_and_callable():
    assert callable(decide_control)
    assert callable(render_control)
    assert callable(open_work)
    assert callable(run_work)
    assert callable(generate_html)
    assert callable(ort.build_open_reason_trace)
    assert callable(ort.build_run_reason_trace)
    assert open_mod.OPEN_REASONS
    assert run_mod.RUN_REASONS
    assert dc.CONTROL_OPEN == "open"
    assert orv.WAVE_ID == "W10"


# --------------------------------------------------------------------------
# Dead-control contract
# --------------------------------------------------------------------------


def test_absent_run_emits_no_button_and_named_cannot_run():
    """GWT: run ABSENT → no Run button; cannot-run visible; zero no-ops."""
    ctx = OpenRunViewContext(
        run_row=_absent_row("run"),
        open_row=_absent_row("open"),
        force_run_absent=False,
        force_open_absent=False,
        run_capability_present=False,
        open_capability_present=False,
    )
    result = render_workbench(ctx)
    html = result.html

    assert count_live_controls(html, CONTROL_RUN) == 0
    assert "cannot_run" in html
    assert 'data-named-state="cannot_run"' in html
    assert_visible_text_contains(html, "cannot_run")
    assert_no_dead_controls(html)
    assert result.dead_control_findings == []
    assert not result.run_is_live


def test_absent_open_emits_no_button_and_named_cannot_open():
    ctx = OpenRunViewContext(
        open_row=_absent_row("open"),
        run_row=_absent_row("run"),
        open_capability_present=False,
        run_capability_present=False,
    )
    result = render_workbench(ctx)
    html = result.html
    assert count_live_controls(html, CONTROL_OPEN) == 0
    assert_visible_text_contains(html, "cannot_open")
    assert_no_dead_controls(html)


def test_present_row_emits_live_open_and_run_buttons():
    """Live PRESENT authorizes clickable controls with real actions."""
    from anchor.ui.dead_control import ControlDecision

    open_ctrl = render_live_control(
        CONTROL_OPEN,
        label="Open",
        action=orv.OPEN_ACTION,
        decision=ControlDecision(
            control_id=CONTROL_OPEN,
            mode=ControlMode.LIVE,
            authorized=True,
            reason="live PRESENT",
            inventory_verdict="PRESENT",
        ),
    )
    run_ctrl = render_live_control(
        CONTROL_RUN,
        label="Run",
        action=orv.RUN_ACTION,
        decision=ControlDecision(
            control_id=CONTROL_RUN,
            mode=ControlMode.LIVE,
            authorized=True,
            reason="live PRESENT",
            inventory_verdict="PRESENT",
        ),
    )
    combined = open_ctrl.html + run_ctrl.html
    assert count_live_controls(combined, CONTROL_OPEN) == 1
    assert count_live_controls(combined, CONTROL_RUN) == 1
    assert_no_dead_controls(combined)
    assert 'data-action="action:open"' in open_ctrl.html
    assert 'data-action="action:run"' in run_ctrl.html


def test_decide_control_live_present_with_matching_hash():
    """Non-STALE live PRESENT row authorizes the LIVE control mode."""
    row = _present_row("open")
    # Pass head_hash == recorded source_hash so resolve_row is not STALE.
    dec = decide_control(
        CONTROL_OPEN,
        row=row,
        root=CONTAINMENT_ROOT,
        as_of=date(2026, 7, 29),
        head_hash=row.source_hash,
    )
    assert dec.authorized is True
    assert dec.mode is ControlMode.LIVE
    ctrl = render_control(
        CONTROL_OPEN,
        label="Open",
        action=orv.OPEN_ACTION,
        row=row,
        root=CONTAINMENT_ROOT,
        as_of=date(2026, 7, 29),
        head_hash=row.source_hash,
    )
    assert ctrl.mode is ControlMode.LIVE
    assert count_live_controls(ctrl.html, CONTROL_OPEN) == 1
    assert_no_dead_controls(ctrl.html)


def test_live_control_with_noop_action_raises():
    from anchor.ui.dead_control import ControlDecision

    dec = ControlDecision(
        control_id=CONTROL_OPEN,
        mode=ControlMode.LIVE,
        authorized=True,
        reason="live",
        inventory_verdict="PRESENT",
    )
    with pytest.raises(DeadControlError):
        render_live_control(CONTROL_OPEN, label="Open", action="#", decision=dec)
    with pytest.raises(DeadControlError):
        render_live_control(
            CONTROL_OPEN, label="Open", action="javascript:void(0)", decision=dec
        )


def test_dead_control_audit_flags_disabled_button():
    bad = '<button type="button" class="dead-control" data-control="run" disabled>Run</button>'
    findings = audit_dead_controls(bad)
    assert findings
    with pytest.raises(DeadControlAuditError):
        assert_no_dead_controls(bad)


def test_decide_control_absent_is_named_state():
    dec = decide_control(CONTROL_RUN, row=_absent_row("run"))
    assert dec.mode is ControlMode.NAMED_STATE
    assert dec.authorized is False
    assert dec.cannot_state == NamedState.cannot_run


def test_decide_control_force_absent():
    dec = decide_control(CONTROL_OPEN, force_absent=True)
    assert dec.mode is ControlMode.NAMED_STATE
    assert dec.cannot_state == NamedState.cannot_open


def test_named_state_path_contains_no_button():
    frag = render_cannot_state(
        CONTROL_RUN, cannot_state=NamedState.cannot_run, reason="capability absent"
    ).html
    assert "<button" not in frag.lower()
    assert "cannot_run" in frag


# --------------------------------------------------------------------------
# open_work reasons
# --------------------------------------------------------------------------


def test_open_reasons_enumerated():
    assert set(OPEN_REASONS) == {
        "no_such_project",
        "project_store_unreadable",
        "workspace_locked",
        "capability_absent",
    }


@pytest.mark.parametrize("reason", list(OPEN_REASONS))
def test_open_work_force_reason(reason):
    result = open_work("any", capability_present=True, force_reason=reason)
    assert isinstance(result, CannotOpen)
    assert result.reason == reason
    assert result.named_state == open_reason_named_state(reason)


def test_open_store_unreadable_is_unknown_not_empty():
    """GWT: project store unreadable → unknown, not 'no projects'."""
    store = unreadable_store()
    result = open_work("p1", store=store, capability_present=True)
    assert isinstance(result, CannotOpen)
    assert result.reason == OpenReason.PROJECT_STORE_UNREADABLE.value
    assert result.named_state == NamedState.unknown
    assert result.named_state != NamedState.empty

    list_state = list_projects_state(store)
    assert list_state == NamedState.unknown

    empty_state = list_projects_state(empty_store())
    assert empty_state == NamedState.empty
    assert empty_state != list_state


def test_open_unknown_visibly_distinct_from_empty_in_html():
    """GWT: unknown and empty produce distinct visible labels."""
    unknown_html = generate_html(
        OpenRunViewContext(
            project_store=unreadable_store(),
            force_open_absent=True,
            force_run_absent=True,
            open_capability_present=False,
            run_capability_present=False,
        )
    )
    empty_html = generate_html(
        OpenRunViewContext(
            project_store=empty_store(),
            force_open_absent=True,
            force_run_absent=True,
            open_capability_present=False,
            run_capability_present=False,
        )
    )
    assert_visible_text_contains(unknown_html, "unknown")
    assert_visible_text_contains(empty_html, "empty")
    # Primary list-state tiles must not collapse.
    assert 'data-list-state="unknown"' in unknown_html
    assert 'data-list-state="empty"' in empty_html
    u_nodes = set(visible_text_nodes(unknown_html))
    e_nodes = set(visible_text_nodes(empty_html))
    assert "unknown" in u_nodes or "unknown" in unknown_html
    assert "empty" in e_nodes or "empty" in empty_html


def test_open_no_such_project():
    store = ProjectStore(projects=[ProjectRecord(project_id="exists")])
    result = open_work("missing", store=store, capability_present=True)
    assert isinstance(result, CannotOpen)
    assert result.reason == OpenReason.NO_SUCH_PROJECT.value


def test_open_workspace_locked():
    store = ProjectStore(
        projects=[ProjectRecord(project_id="p1", locked=True)],
    )
    result = open_work("p1", store=store, capability_present=True)
    assert isinstance(result, CannotOpen)
    assert result.reason == OpenReason.WORKSPACE_LOCKED.value


def test_open_success():
    store = ProjectStore(
        projects=[ProjectRecord(project_id="p1", label="Demo", path="proj/p1")],
    )
    result = open_work("p1", store=store, capability_present=True)
    assert isinstance(result, OpenedWork)
    assert result.project_id == "p1"
    assert result.ok


def test_open_capability_absent_without_inventory():
    result = open_work("p1", store=empty_store())
    assert isinstance(result, CannotOpen)
    assert result.reason == OpenReason.CAPABILITY_ABSENT.value


# --------------------------------------------------------------------------
# run_work reasons
# --------------------------------------------------------------------------


def test_run_reasons_enumerated():
    assert set(RUN_REASONS) == {
        "no_runnable_target",
        "engine_unavailable",
        "prior_run_in_flight",
        "capability_absent",
    }


@pytest.mark.parametrize("reason", list(RUN_REASONS))
def test_run_work_force_reason(reason):
    result = run_work("t1", capability_present=True, force_reason=reason)
    assert isinstance(result, CannotRun)
    assert result.reason == reason
    assert result.named_state == NamedState.cannot_run


def test_run_no_runnable_target():
    result = run_work("missing", env=empty_run_env(), capability_present=True)
    assert isinstance(result, CannotRun)
    assert result.reason == RunReason.NO_RUNNABLE_TARGET.value


def test_run_engine_unavailable():
    env = make_run_env(
        targets=[{"target_id": "t1", "engine": "claude"}],
        engines=[],  # no engines available
    )
    # Clear engines that make_run_env auto-added from target.
    env.available_engines.clear()
    result = run_work("t1", engine="claude", env=env, capability_present=True)
    assert isinstance(result, CannotRun)
    assert result.reason == RunReason.ENGINE_UNAVAILABLE.value


def test_run_prior_in_flight():
    env = make_run_env(
        targets=[{"target_id": "t1", "engine": "claude"}],
        engines=["claude"],
        in_flight=["t1"],
    )
    result = run_work("t1", engine="claude", env=env, capability_present=True)
    assert isinstance(result, CannotRun)
    assert result.reason == RunReason.PRIOR_RUN_IN_FLIGHT.value


def test_run_success():
    env = make_run_env(
        targets=[{"target_id": "t1", "engine": "claude"}],
        engines=["claude"],
    )
    result = run_work("t1", engine="claude", env=env, capability_present=True)
    assert isinstance(result, LiveRunHandle)
    assert result.target_id == "t1"
    assert result.ok


def test_run_capability_absent():
    result = run_work("t1", capability_present=False)
    assert isinstance(result, CannotRun)
    assert result.reason == RunReason.CAPABILITY_ABSENT.value


def test_list_targets_unknown_vs_empty():
    assert list_targets_state(make_run_env(unreadable=True)) == NamedState.unknown
    assert list_targets_state(empty_run_env()) == NamedState.empty


# --------------------------------------------------------------------------
# cannot-* rendering per enumerated reason
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(OPEN_REASONS))
def test_open_cannot_reason_renders_named_state(reason):
    frag = orv.render_cannot_reason_html(CONTROL_OPEN, reason)
    ns = open_reason_named_state(reason)
    assert_visible_text_contains(frag, ns.label)
    assert "<button" not in frag.lower()
    assert_no_dead_controls(frag)


@pytest.mark.parametrize("reason", list(RUN_REASONS))
def test_run_cannot_reason_renders_named_state(reason):
    frag = orv.render_cannot_reason_html(CONTROL_RUN, reason)
    assert_visible_text_contains(frag, "cannot_run")
    assert "<button" not in frag.lower()
    assert_no_dead_controls(frag)


def test_store_unreadable_open_outcome_shows_unknown():
    result = open_work(
        "p1", store=unreadable_store(), capability_present=True
    )
    html = orv.render_open_outcome(result)
    assert_visible_text_contains(html, "unknown")
    assert "empty" not in visible_text_nodes(html) or "unknown" in html
    # Must carry unknown token as named-state, not empty.
    assert 'data-named-state="unknown"' in html
    assert 'data-named-state="empty"' not in html


# --------------------------------------------------------------------------
# Tri-state conformance
# --------------------------------------------------------------------------


def test_open_run_tri_state_conformance():
    assert_tri_state(
        generate_html_for_fixture,
        call_site="anchor.ui.open_run_view.generate_html_for_fixture",
    )


# --------------------------------------------------------------------------
# Failure-state table
# --------------------------------------------------------------------------


def test_failure_state_table_exists_and_maps_vocabulary():
    assert FAILURE_TABLE_PATH.is_file()
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    # No absolute host paths.
    assert "C:\\Users" not in text
    assert "/Users/" not in text
    rows = _parse_open_run_failure_table(text)
    assert rows, "open-run.md machine table produced no rows"
    # unknown and empty as SEPARATE rows.
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    report = validate_failure_state_table(rows, surface="open-run")
    assert report["ok"] is True


def test_failure_state_table_surface_native_open_run_language():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "open" in low and "run" in low
    # Honesty theater ban on this surface.
    for verb in ("index", "rebuild", "reconcile"):
        # Word-boundary-ish: table must not use these as triggers.
        assert not re.search(r"\b%s\b" % verb, low.split("## enumerated")[0])


# --------------------------------------------------------------------------
# EARLY-SLICE-PARTIAL
# --------------------------------------------------------------------------


def test_early_slice_partial_declares_partial():
    assert EARLY_SLICE_PATH.is_file()
    text = EARLY_SLICE_PATH.read_text(encoding="utf-8")
    assert "PARTIAL" in text
    assert "partial" in text.lower()
    assert "North Star" in text or "north star" in text.lower()
    # Still unbuilt list must name major remaining surfaces.
    low = text.lower()
    for needle in ("doctor", "cost", "usage", "restart", "preview", "cadence"):
        assert needle in low, "EARLY-SLICE-PARTIAL must name unbuilt %r" % needle
    assert "C:\\Users" not in text
    assert "/Users/" not in text


# --------------------------------------------------------------------------
# E2E traces — one induced fault per enumerated reason
# --------------------------------------------------------------------------


def test_open_e2e_trace_artifact_schema_valid():
    assert OPEN_TRACE_PATH.is_file()
    data = ort.load_trace_set(ort.OPEN_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    assert data["control_id"] == "open"
    assert data["wave_id"] == "W10"
    assert is_go_evidence(data)
    reasons = set(data.get("enumerated_reasons") or [])
    assert reasons == set(OPEN_REASONS)
    nested = data.get("reason_traces") or {}
    for reason in OPEN_REASONS:
        assert reason in nested, "missing open reason trace for %s" % reason
        art = validate_trace(nested[reason])
        assert art.induced_fault == reason
        assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
        assert is_go_evidence(art)


def test_run_e2e_trace_artifact_schema_valid():
    assert RUN_TRACE_PATH.is_file()
    data = ort.load_trace_set(ort.RUN_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    assert data["control_id"] == "run"
    assert is_go_evidence(data)
    nested = data.get("reason_traces") or {}
    for reason in RUN_REASONS:
        assert reason in nested
        art = validate_trace(nested[reason])
        assert art.induced_fault == reason
        assert is_go_evidence(art)


@pytest.mark.parametrize("reason", list(OPEN_REASONS))
def test_build_open_reason_trace_live(reason):
    art = ort.build_open_reason_trace(reason)
    assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
    assert art.induced_fault == reason
    assert is_go_evidence(art)


@pytest.mark.parametrize("reason", list(RUN_REASONS))
def test_build_run_reason_trace_live(reason):
    art = ort.build_run_reason_trace(reason)
    assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
    assert art.induced_fault == reason
    assert is_go_evidence(art)


def test_present_still_emits_traces_and_failure_table():
    """GWT: PRESENT removes build work, never evidence.

    Even when a control is authorized PRESENT, the wave still ships
    schema-valid e2e traces and a failure-state table.
    """
    # Traces exist and validate regardless of inventory PRESENT/ABSENT.
    open_data = ort.load_trace_set(ort.OPEN_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    run_data = ort.load_trace_set(ort.RUN_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    assert is_go_evidence(open_data)
    assert is_go_evidence(run_data)
    # Failure table still present.
    rows = _parse_open_run_failure_table(
        FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    )
    validate_failure_state_table(rows, surface="open-run")
    # Synthetic PRESENT authorization does not suppress evidence artifacts.
    row = _present_row("open")
    assert row.verdict is Verdict.PRESENT
    assert OPEN_TRACE_PATH.is_file() and RUN_TRACE_PATH.is_file()


# --------------------------------------------------------------------------
# Visible text + node --check
# --------------------------------------------------------------------------


def test_workbench_generate_html_visible_nodes_and_node_check():
    html = generate_html(
        OpenRunViewContext(
            force_open_absent=True,
            force_run_absent=True,
            open_capability_present=False,
            run_capability_present=False,
        )
    )
    assert "<html" in html.lower()
    assert_visible_text_contains(html, ["cannot_open", "cannot_run"])
    assert_no_dead_controls(html)
    # node --check on script blocks (skip if node absent).
    node_check_scripts(html, require_node=False)


def test_reason_matrix_lists_all_enumerated_reasons():
    html = generate_html(
        OpenRunViewContext(force_open_absent=True, force_run_absent=True)
    )
    for reason in OPEN_REASONS:
        assert 'data-reason="%s"' % reason in html
    for reason in RUN_REASONS:
        assert 'data-reason="%s"' % reason in html


def test_no_absolute_host_paths_in_shipped_sources():
    rels = [
        "anchor/ui/dead_control.py",
        "anchor/session/open_work.py",
        "anchor/session/run_work.py",
        "anchor/ui/open_run_view.py",
        "anchor/ui/open_run_traces.py",
        "artifacts/failure-states/open-run.md",
        "artifacts/EARLY-SLICE-PARTIAL.md",
        "artifacts/traces/open-e2e.json",
        "artifacts/traces/run-e2e.json",
    ]
    for rel in rels:
        text = (CONTAINMENT_ROOT / rel).read_text(encoding="utf-8")
        assert "C:\\Users" not in text, rel
        assert "C:/Users" not in text, rel
        assert "/Users/" not in text, rel


# --------------------------------------------------------------------------
# may_authorize integration (PRESENT requires live + non-stale)
# --------------------------------------------------------------------------


def test_replay_present_does_not_authorize_live_button():
    row = InventoryRow(
        control_id="run",
        verdict=Verdict.PRESENT,
        transcript_path="artifacts/transcripts/run.json",
        source_paths=("artifacts/inventory-sources/run.probe",),
        source_hash="c" * 64,
        probe_date="2026-07-29",
        evidence_mode=EVIDENCE_REPLAY,
        disposition="wire it",
    )
    assert may_authorize_live_control(row, head_hash=row.source_hash) is False
    dec = decide_control(CONTROL_RUN, row=row, head_hash=row.source_hash)
    assert dec.mode is ControlMode.NAMED_STATE
    ctrl = render_control(
        CONTROL_RUN,
        label="Run",
        action=orv.RUN_ACTION,
        row=row,
        head_hash=row.source_hash,
    )
    assert ctrl.mode is ControlMode.NAMED_STATE
    assert count_live_controls(ctrl.html) == 0
    assert_no_dead_controls(ctrl.html)

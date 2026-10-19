"""W11 — Session attach honesty (timeout, no double-print, Retry viable or named).

Exercises every W11 deliverable under one scoped gate:

* ``anchor/session/attach.py``
* ``anchor/ui/attach_view.py``
* ``anchor/ui/attach_traces.py``
* ``artifacts/failure-states/attach.md``
* ``artifacts/traces/attach-e2e.json``

Gate: pytest -v tests/test_session_attach_2026_07_29.py

GWTs (frozen plan):

* Attach timeout → timeout state (not unknown session); error text exactly once;
  trace records control→handler→capability→state.
* Process gone → no Retry control; named cannot-retry with reason.
* Empty session list vs unqueried/unreadable list → distinct empty vs unknown;
  tri-state harness passes.
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
from anchor.session import attach as attach_mod
from anchor.session.attach import (
    ATTACH_REASONS,
    INDUCED_FAULT_REASONS,
    AttachReason,
    AttachedSession,
    CannotAttach,
    CannotRetry,
    RetryAction,
    SessionRecord,
    SessionStore,
    attach_reason_named_state,
    attach_session,
    empty_session_store,
    list_sessions_state,
    retry_contract,
    unreadable_session_store,
)
from anchor.ui import attach_traces as atr
from anchor.ui import attach_view as av
from anchor.ui.attach_view import (
    AttachViewContext,
    count_error_text_emissions,
    generate_html,
    generate_html_for_fixture,
    render_attach_outcome,
    render_attach_surface,
    render_live_retry_for_action,
)
from anchor.ui.dead_control import (
    CONTROL_RETRY,
    assert_no_dead_controls,
    count_live_controls,
)
from anchor.ui.named_state import NamedState
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import validate_failure_state_table
from tests.conformance.tri_state import assert_tri_state

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "attach.md"
)
ATTACH_TRACE_PATH = CONTAINMENT_ROOT / "artifacts" / "traces" / "attach-e2e.json"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _parse_attach_failure_table(text: str) -> list:
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
# Acceptance: every new module is imported and exercised
# --------------------------------------------------------------------------


def test_w11_modules_importable_and_callable():
    assert callable(attach_session)
    assert callable(retry_contract)
    assert callable(generate_html)
    assert callable(atr.build_attach_reason_trace)
    assert callable(atr.load_trace_set)
    assert attach_mod.ATTACH_REASONS
    assert av.WAVE_ID == "W11"
    assert set(INDUCED_FAULT_REASONS) == {
        "timeout",
        "unknown_session",
        "empty_session_list",
    }


# --------------------------------------------------------------------------
# Attach reasons + timeout classification
# --------------------------------------------------------------------------


def test_attach_reasons_enumerated():
    assert "timeout" in ATTACH_REASONS
    assert "unknown_session" in ATTACH_REASONS
    assert "empty_session_list" in ATTACH_REASONS
    assert "process_gone" in ATTACH_REASONS


@pytest.mark.parametrize("reason", list(ATTACH_REASONS))
def test_attach_force_reason(reason):
    result = attach_session(
        "any", capability_present=True, force_reason=reason
    )
    assert isinstance(result, CannotAttach)
    assert result.reason == reason
    assert result.named_state == attach_reason_named_state(reason)


def test_timeout_is_timeout_not_unknown_session():
    """GWT: attach timeout → timeout state, not 'unknown session'."""
    store = SessionStore(
        sessions=[SessionRecord(session_id="s1", label="Live")],
        timeout_ids=["s1"],
    )
    result = attach_session("s1", store=store, capability_present=True)
    assert isinstance(result, CannotAttach)
    assert result.reason == AttachReason.TIMEOUT.value
    assert result.named_state == NamedState.timeout
    assert result.named_state != NamedState.unknown
    assert result.error_text == NamedState.timeout.label


def test_unknown_session_distinct_from_timeout():
    store = SessionStore(sessions=[SessionRecord(session_id="exists")])
    result = attach_session("missing", store=store, capability_present=True)
    assert isinstance(result, CannotAttach)
    assert result.reason == AttachReason.UNKNOWN_SESSION.value
    assert result.named_state == NamedState.unknown
    assert result.named_state != NamedState.timeout


def test_empty_session_list_is_empty_not_unknown():
    store = empty_session_store()
    result = attach_session(None, store=store, capability_present=True)
    assert isinstance(result, CannotAttach)
    assert result.reason == AttachReason.EMPTY_SESSION_LIST.value
    assert result.named_state == NamedState.empty

    list_state = list_sessions_state(store)
    assert list_state == NamedState.empty
    assert list_sessions_state(unreadable_session_store()) == NamedState.unknown


def test_process_gone():
    store = SessionStore(
        sessions=[SessionRecord(session_id="s1", process_alive=False)],
        gone_ids=["s1"],
    )
    result = attach_session("s1", store=store, capability_present=True)
    assert isinstance(result, CannotAttach)
    assert result.reason == AttachReason.PROCESS_GONE.value
    assert result.named_state == NamedState.cannot_retry
    assert result.process_alive is False


def test_attach_success():
    store = SessionStore(
        sessions=[SessionRecord(session_id="s1", label="Demo")],
    )
    result = attach_session("s1", store=store, capability_present=True)
    assert isinstance(result, AttachedSession)
    assert result.session_id == "s1"
    assert result.ok


def test_attach_capability_absent_without_inventory():
    result = attach_session("s1", store=empty_session_store())
    assert isinstance(result, CannotAttach)
    assert result.reason == AttachReason.CAPABILITY_ABSENT.value


# --------------------------------------------------------------------------
# Single error emission (double-print killed)
# --------------------------------------------------------------------------


def test_timeout_error_text_appears_exactly_once():
    """GWT: timeout state shows once in the error channel (not unknown session)."""
    ctx = AttachViewContext(
        force_attach_reason=AttachReason.TIMEOUT.value,
        capability_present=True,
        session_id="s1",
    )
    result = render_attach_surface(ctx)
    html = result.html
    assert_visible_text_contains(html, "timeout")
    # Primary outcome must be timeout, not unknown session.
    assert 'data-attach-reason="timeout"' in html
    assert 'data-attach-reason="unknown_session"' not in html
    outcome = re.search(
        r'<div class="[^"]*attach-error-once[^"]*"[^>]*>.*?</div>',
        html,
        re.DOTALL,
    )
    assert outcome, "single error channel missing"
    assert 'data-named-state="timeout"' in outcome.group(0)
    assert 'data-named-state="unknown"' not in outcome.group(0)
    emissions = count_error_text_emissions(html, "timeout")
    assert emissions == 1, (
        "timeout label must appear exactly once in the error channel, got %d"
        % emissions
    )
    assert result.error_emissions == 1


def test_render_attach_outcome_single_channel():
    cannot = CannotAttach(
        reason=AttachReason.TIMEOUT.value,
        detail="attach timed out",
        session_id="s1",
        process_alive=True,
    )
    frag = render_attach_outcome(cannot)
    assert count_error_text_emissions(frag, cannot.error_text) == 1
    # Detail must not re-print the NamedState label.
    assert frag.count(cannot.error_text) == 1


# --------------------------------------------------------------------------
# Retry contract
# --------------------------------------------------------------------------


def test_retry_contract_timeout_returns_viable_action():
    cannot = CannotAttach(
        reason=AttachReason.TIMEOUT.value,
        session_id="s1",
        process_alive=True,
    )
    rc = retry_contract(cannot)
    assert isinstance(rc, RetryAction)
    assert rc.viable is True
    assert "attach" in rc.action
    assert rc.session_id == "s1"


def test_retry_contract_process_gone_returns_cannot_retry():
    """GWT: process gone → no Retry control; named cannot-retry."""
    cannot = CannotAttach(
        reason=AttachReason.PROCESS_GONE.value,
        session_id="s1",
        process_alive=False,
    )
    rc = retry_contract(cannot)
    assert isinstance(rc, CannotRetry)
    assert rc.viable is False
    assert rc.named_state == NamedState.cannot_retry
    assert rc.reason == AttachReason.PROCESS_GONE.value


def test_process_gone_view_has_no_retry_button():
    """GWT: process gone attach error view — no Retry, cannot_retry visible."""
    ctx = AttachViewContext(
        force_attach_reason=AttachReason.PROCESS_GONE.value,
        force_process_gone=True,
        capability_present=True,
        session_id="s1",
    )
    result = render_attach_surface(ctx)
    html = result.html
    assert count_live_controls(html, CONTROL_RETRY) == 0
    assert_visible_text_contains(html, "cannot_retry")
    assert 'data-named-state="cannot_retry"' in html
    assert_no_dead_controls(html)
    assert result.dead_control_findings == []
    assert not result.retry_is_live
    assert isinstance(result.retry_result, CannotRetry)


def test_timeout_retry_is_live_reissue():
    ctx = AttachViewContext(
        force_attach_reason=AttachReason.TIMEOUT.value,
        capability_present=True,
        session_id="s1",
    )
    result = render_attach_surface(ctx)
    assert isinstance(result.retry_result, RetryAction)
    assert result.retry_is_live
    html = result.html
    assert count_live_controls(html, CONTROL_RETRY) == 1
    assert 'data-action=' in html
    assert_no_dead_controls(html)


def test_live_retry_for_action_has_real_target():
    action = RetryAction(action="action:attach:s1", session_id="s1", reason="timeout")
    ctrl = render_live_retry_for_action(action)
    assert count_live_controls(ctrl.html, CONTROL_RETRY) == 1
    assert 'data-action="action:attach:s1"' in ctrl.html
    assert_no_dead_controls(ctrl.html)


def test_retry_contract_unknown_and_empty_are_cannot_retry():
    for reason in (
        AttachReason.UNKNOWN_SESSION.value,
        AttachReason.EMPTY_SESSION_LIST.value,
    ):
        rc = retry_contract(reason=reason)
        assert isinstance(rc, CannotRetry), reason
        assert rc.named_state == NamedState.cannot_retry


# --------------------------------------------------------------------------
# Empty vs unknown (session list)
# --------------------------------------------------------------------------


def test_empty_vs_unknown_session_list_distinct_labels():
    """GWT: empty list vs unqueried list → two distinct visible labels."""
    empty_html = generate_html(
        AttachViewContext(
            session_store=empty_session_store(),
            capability_present=False,
            force_retry_absent=True,
        )
    )
    unknown_html = generate_html(
        AttachViewContext(
            session_store=unreadable_session_store(),
            capability_present=False,
            force_retry_absent=True,
        )
    )
    assert_visible_text_contains(empty_html, "empty")
    assert_visible_text_contains(unknown_html, "unknown")
    assert 'data-list-state="empty"' in empty_html
    assert 'data-list-state="unknown"' in unknown_html
    e_nodes = set(visible_text_nodes(empty_html))
    u_nodes = set(visible_text_nodes(unknown_html))
    assert "empty" in e_nodes or "empty" in empty_html
    assert "unknown" in u_nodes or "unknown" in unknown_html


# --------------------------------------------------------------------------
# Tri-state conformance
# --------------------------------------------------------------------------


def test_attach_tri_state_conformance():
    assert_tri_state(
        generate_html_for_fixture,
        call_site="anchor.ui.attach_view.generate_html_for_fixture",
    )


# --------------------------------------------------------------------------
# Failure-state table
# --------------------------------------------------------------------------


def test_failure_state_table_exists_and_maps_vocabulary():
    assert FAILURE_TABLE_PATH.is_file()
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in text
    assert "/Users/" not in text
    rows = _parse_attach_failure_table(text)
    assert rows, "attach.md machine table produced no rows"
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    # Separate rows — not merged.
    assert "unknown/empty" not in text.lower().replace(" ", "")
    report = validate_failure_state_table(rows, surface="attach")
    assert report["ok"] is True


def test_failure_state_table_surface_native_attach_language():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "attach" in low
    assert "retry" in low or "timeout" in low
    head = low.split("## enumerated")[0]
    for verb in ("index", "rebuild", "reconcile"):
        assert not re.search(r"\b%s\b" % verb, head)


# --------------------------------------------------------------------------
# Induced faults + e2e traces
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(INDUCED_FAULT_REASONS))
def test_induced_fault_per_gate_reason(reason):
    """One induced fault per reason named by the W11 gate."""
    result = attach_session(
        "induced", capability_present=True, force_reason=reason
    )
    assert isinstance(result, CannotAttach)
    assert result.reason == reason
    html = render_attach_outcome(result)
    ns = attach_reason_named_state(reason)
    assert_visible_text_contains(html, ns.label)
    assert count_error_text_emissions(html, result.error_text) == 1


def test_attach_e2e_trace_artifact_schema_valid():
    assert ATTACH_TRACE_PATH.is_file()
    data = atr.load_trace_set(atr.ATTACH_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    assert data["control_id"] == "attach"
    assert data["wave_id"] == "W11"
    assert is_go_evidence(data)
    # Induced-fault reasons from the gate must be covered.
    nested = data.get("reason_traces") or {}
    for reason in INDUCED_FAULT_REASONS:
        assert reason in nested, "missing attach reason trace for %s" % reason
        art = validate_trace(nested[reason])
        assert art.induced_fault == reason
        assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
        assert is_go_evidence(art)
        # Hop chain: control → handler → capability → state
        kinds = [h.kind for h in art.hops]
        assert kinds == [
            "control_invocation",
            "handler",
            "capability_call",
            "rendered_state",
        ]


@pytest.mark.parametrize("reason", list(ATTACH_REASONS))
def test_build_attach_reason_trace_live(reason):
    art = atr.build_attach_reason_trace(reason)
    assert art.proof_level == PROOF_LEVEL_RENDERED_STRING
    assert art.induced_fault == reason
    assert is_go_evidence(art)


def test_timeout_trace_renders_timeout_not_unknown():
    art = atr.build_attach_reason_trace("timeout")
    assert art.rendered_state == "timeout"
    assert art.rendered_state != "unknown"


# --------------------------------------------------------------------------
# Visible text + node --check
# --------------------------------------------------------------------------


def test_attach_generate_html_visible_nodes_and_node_check():
    html = generate_html(
        AttachViewContext(
            force_attach_reason=AttachReason.TIMEOUT.value,
            capability_present=True,
            session_id="s1",
        )
    )
    assert "<html" in html.lower()
    assert_visible_text_contains(html, "timeout")
    assert_no_dead_controls(html)
    node_check_scripts(html, require_node=False)


def test_reason_matrix_lists_all_enumerated_reasons():
    html = generate_html(
        AttachViewContext(
            force_attach_reason=AttachReason.CAPABILITY_ABSENT.value,
            capability_present=False,
        )
    )
    for reason in ATTACH_REASONS:
        assert 'data-reason="%s"' % reason in html


def test_no_absolute_host_paths_in_shipped_sources():
    rels = [
        "anchor/session/attach.py",
        "anchor/ui/attach_view.py",
        "anchor/ui/attach_traces.py",
        "artifacts/failure-states/attach.md",
        "artifacts/traces/attach-e2e.json",
    ]
    for rel in rels:
        text = (CONTAINMENT_ROOT / rel).read_text(encoding="utf-8")
        assert "C:\\Users" not in text, rel
        assert "C:/Users" not in text, rel
        assert "/Users/" not in text, rel

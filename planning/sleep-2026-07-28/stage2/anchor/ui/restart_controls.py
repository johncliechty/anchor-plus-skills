"""Per-context restart controls — W17, Phase 3.

Render-time invariant: a context offering **two** restart controls fails
the build. Each live control names its **scope** and **preserved/lost**
contract. When restart is not possible, a named ``cannot_restart`` state
appears and no dead button is present.

Renders exclusively through ``dead_control`` + ``render_state``.
``generate_html`` returns a full document with a syntax-valid ``<script>``
block suitable for ``node --check``.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

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
    RestartSubject,
    assert_outcome_matches_contract,
    get_contract,
    make_subject,
    normalize_context_id,
    restart,
    restart_engine,
    restart_reason_named_state,
    restart_run,
    restart_session,
    restart_workbench,
)
from anchor.ui.dead_control import (
    CANNOT_STATE_CLASS,
    ControlMode,
    ControlRender,
    DeadControlError,
    assert_no_dead_controls,
    audit_dead_controls,
    count_cannot_states,
    count_live_controls,
    decide_control,
    render_cannot_state,
    render_control,
)
from anchor.ui.named_state import NamedState, render_state
from tools.capability_inventory import InventoryRow
from tools.restart_control_audit import (
    DualRestartControlError,
    audit_restart_controls,
    find_restart_controls,
)

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "restart"
WAVE_ID = "W17"

TRACE_AS_OF = "2026-07-29T00:00:00Z"
TRACES_RELDIR = os.path.join("artifacts", "traces")

#: Per-context trace relative paths (plan: restart-e2e.json per context).
TRACE_RELPATH_BY_CONTEXT: Dict[str, str] = {
    CONTEXT_RUN: os.path.join(TRACES_RELDIR, "restart-run-e2e.json"),
    CONTEXT_SESSION: os.path.join(TRACES_RELDIR, "restart-session-e2e.json"),
    CONTEXT_ENGINE: os.path.join(TRACES_RELDIR, "restart-engine-e2e.json"),
    CONTEXT_WORKBENCH: os.path.join(TRACES_RELDIR, "restart-workbench-e2e.json"),
}

#: Aggregate multi-context artifact.
AGGREGATE_TRACE_RELPATH = os.path.join(TRACES_RELDIR, "restart-e2e.json")


class DualRestartRenderError(DeadControlError, DualRestartControlError):
    """Render-time invariant: two restart controls in one context."""

    def __init__(self, message: str, *, context_id: str = "", controls: Optional[Sequence[str]] = None):
        DeadControlError.__init__(self, message)
        DualRestartControlError.__init__(
            self, message, context_id=context_id, controls=controls
        )


# --------------------------------------------------------------------------
# View context / result
# --------------------------------------------------------------------------


@dataclass
class RestartViewContext:
    """Inputs that drive the restart surface render."""

    contexts: Sequence[str] = field(default_factory=lambda: list(RESTART_CONTEXT_IDS))
    inventory_rows: Dict[str, InventoryRow] = field(default_factory=dict)
    subjects: Dict[str, RestartSubject] = field(default_factory=dict)
    capability_present: Dict[str, bool] = field(default_factory=dict)
    force_absent: Dict[str, bool] = field(default_factory=dict)
    force_reason: Dict[str, str] = field(default_factory=dict)
    target_ids: Dict[str, str] = field(default_factory=dict)
    as_of: Optional[date] = None
    root: Optional[Path] = None
    head_hash: Optional[str] = None
    head_hashes: Dict[str, str] = field(default_factory=dict)
    content_overrides: Optional[Mapping[str, bytes]] = None
    title: str = "Restart controls"
    #: When True, execute handlers and show outcome panels.
    execute: bool = True


@dataclass
class RestartViewResult:
    """Structured render outcome for tests and traces."""

    html: str
    controls: Dict[str, ControlRender] = field(default_factory=dict)
    outcomes: Dict[str, Union[RestartAction, CannotRestart]] = field(
        default_factory=dict
    )
    dead_control_findings: List[Any] = field(default_factory=list)

    def live_contexts(self) -> List[str]:
        return [
            c
            for c, ctrl in self.controls.items()
            if ctrl.mode is ControlMode.LIVE
        ]


# --------------------------------------------------------------------------
# Control rendering (exactly one per context)
# --------------------------------------------------------------------------


def restart_action_for(context_id: str) -> str:
    return "action:restart_%s" % normalize_context_id(context_id)


def render_restart_control(
    context_id: str,
    *,
    row: Optional[InventoryRow] = None,
    inventory: Optional[Any] = None,
    root: Optional[Path] = None,
    as_of: Optional[date] = None,
    force_absent: bool = False,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> ControlRender:
    """Render exactly one restart control (or cannot_restart) for *context_id*.

    The live label is the scope name; contract line is stamped on data attributes
    by the caller (``render_context_slot``) so the preserved/lost text is visible.
    """
    cid = normalize_context_id(context_id)
    contract = get_contract(cid)
    control_id = contract.control_id
    return render_control(
        control_id,
        label=contract.control_label,
        action=restart_action_for(cid),
        row=row,
        inventory=inventory,
        root=root,
        as_of=as_of,
        head_hash=head_hash,
        content_overrides=content_overrides,
        cannot_state=NamedState.cannot_restart,
        force_absent=force_absent,
    )


def _annotate_control_html(
    control: ControlRender,
    context_id: str,
) -> str:
    """Stamp scope + contract onto the control HTML (visible + data attrs)."""
    cid = normalize_context_id(context_id)
    contract = get_contract(cid)
    frag = control.html
    # Inject data-restart-context / data-scope-name / data-contract-line.
    extra = (
        ' data-restart-context="%s" data-scope-name="%s" data-contract-line="%s"'
        % (
            html.escape(cid, quote=True),
            html.escape(contract.scope_name, quote=True),
            html.escape(contract.contract_line, quote=True),
        )
    )
    # Insert attributes after the opening tag name.
    frag = re.sub(
        r"^(<\s*(?:button|div)\b)",
        r"\1" + extra,
        frag,
        count=1,
        flags=re.IGNORECASE,
    )
    if control.mode is ControlMode.LIVE:
        # Visible contract line next to the button (assertable text node).
        contract_span = (
            ' <span class="restart-contract" data-restart-context="%s">'
            "%s</span>"
            % (
                html.escape(cid, quote=True),
                html.escape(contract.contract_line, quote=False),
            )
        )
        scope_span = (
            ' <span class="restart-scope" data-restart-context="%s">'
            "scope: %s</span>"
            % (
                html.escape(cid, quote=True),
                html.escape(contract.scope_name, quote=False),
            )
        )
        return frag + scope_span + contract_span
    return frag


def render_context_slot(
    context_id: str,
    *,
    row: Optional[InventoryRow] = None,
    root: Optional[Path] = None,
    as_of: Optional[date] = None,
    force_absent: bool = False,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> ControlRender:
    """Render one context slot and enforce the single-control invariant."""
    cid = normalize_context_id(context_id)
    ctrl = render_restart_control(
        cid,
        row=row,
        root=root,
        as_of=as_of,
        force_absent=force_absent,
        head_hash=head_hash,
        content_overrides=content_overrides,
    )
    annotated = _annotate_control_html(ctrl, cid)
    # Rebuild ControlRender with annotated html (frozen dataclass → new).
    annotated_ctrl = ControlRender(
        control_id=ctrl.control_id,
        mode=ctrl.mode,
        html=annotated,
        decision=ctrl.decision,
        action=ctrl.action,
        label=ctrl.label,
    )
    # Render-time dual-control invariant on this slot alone.
    _assert_single_control_in_fragment(annotated, cid)
    return annotated_ctrl


def _assert_single_control_in_fragment(html_frag: str, context_id: str) -> None:
    """Fail the build if this fragment alone has two restart controls."""
    hits = find_restart_controls(html_frag, context_id=context_id)
    live = [h for h in hits if h.kind in ("live", "ambiguous")]
    if len(live) > 1:
        labels = [h.label for h in live]
        raise DualRestartRenderError(
            "render-time invariant failed for context %r — two restart "
            "controls: %s" % (context_id, labels),
            context_id=context_id,
            controls=labels,
        )


def render_outcome(result: Union[RestartAction, CannotRestart]) -> str:
    """Visible panel for a restart handler result."""
    if isinstance(result, RestartAction):
        state_html = render_state(NamedState.ok)
        detail = html.escape(
            "%s — %s" % (result.scope_name, result.contract_line),
            quote=False,
        )
        preserved = html.escape(
            "preserved: %s" % ", ".join(result.preserved), quote=False
        )
        lost = html.escape(
            "lost: %s" % ", ".join(result.lost), quote=False
        )
        return (
            '<div class="restart-outcome" data-restart-ok="true" '
            'data-restart-context="%s" data-contract-line="%s">'
            "%s <span class=\"restart-detail\">%s</span>"
            ' <span class="restart-preserved">%s</span>'
            ' <span class="restart-lost">%s</span></div>'
            % (
                html.escape(result.context_id, quote=True),
                html.escape(result.contract_line, quote=True),
                state_html,
                detail,
                preserved,
                lost,
            )
        )
    state_html = render_state(result.named_state)
    reason = html.escape(result.reason, quote=True)
    label = html.escape(result.label or result.reason, quote=False)
    return (
        '<div class="restart-outcome" data-restart-ok="false" '
        'data-restart-context="%s" data-restart-reason="%s">'
        "%s <span class=\"restart-reason-label\">%s</span></div>"
        % (
            html.escape(result.context_id, quote=True),
            reason,
            state_html,
            label,
        )
    )


def render_contract_matrix() -> str:
    """Document every context's single control + contract as visible rows."""
    rows: List[str] = []
    for cid in RESTART_CONTEXT_IDS:
        c = get_contract(cid)
        rows.append(
            '<div class="contract-row" data-restart-context="%s" '
            'data-control="%s" data-scope-name="%s" data-contract-line="%s">'
            '<span class="scope-token">%s</span> '
            '<span class="contract-token">%s</span> '
            '<span class="preserved-token">preserved: %s</span> '
            '<span class="lost-token">lost: %s</span></div>'
            % (
                html.escape(cid, quote=True),
                html.escape(c.control_id, quote=True),
                html.escape(c.scope_name, quote=True),
                html.escape(c.contract_line, quote=True),
                html.escape(c.scope_name, quote=False),
                html.escape(c.contract_line, quote=False),
                html.escape(", ".join(c.preserved), quote=False),
                html.escape(", ".join(c.lost), quote=False),
            )
        )
    return (
        '<section class="contract-matrix" data-surface="restart-contracts">\n'
        "%s\n</section>" % "\n".join(rows)
    )


def render_reason_matrix() -> str:
    rows: List[str] = []
    for reason in RESTART_REASONS:
        ns = restart_reason_named_state(reason)
        rows.append(
            '<div class="reason-row" data-control="restart" data-reason="%s">'
            '<span class="reason-token">%s</span> %s</div>'
            % (
                html.escape(reason, quote=True),
                html.escape(reason, quote=False),
                render_state(ns),
            )
        )
    return (
        '<section class="reason-matrix" data-surface="restart-reasons">\n'
        "%s\n</section>" % "\n".join(rows)
    )


# --------------------------------------------------------------------------
# Full surface
# --------------------------------------------------------------------------


def render_restart_surface(
    ctx: Optional[RestartViewContext] = None,
) -> RestartViewResult:
    """Render all enumerated restart contexts (exactly one control each)."""
    c = ctx or RestartViewContext()
    contexts = [normalize_context_id(x) for x in c.contexts]
    controls: Dict[str, ControlRender] = {}
    outcomes: Dict[str, Union[RestartAction, CannotRestart]] = {}

    slot_parts: List[str] = []
    outcome_parts: List[str] = []

    for cid in contexts:
        row = c.inventory_rows.get(cid) or c.inventory_rows.get(
            CONTROL_ID_BY_CONTEXT[cid]
        )
        force_abs = bool(c.force_absent.get(cid, False))
        hh = c.head_hashes.get(cid, c.head_hash)
        ctrl = render_context_slot(
            cid,
            row=row,
            root=c.root,
            as_of=c.as_of,
            force_absent=force_abs,
            head_hash=hh,
            content_overrides=c.content_overrides,
        )
        controls[cid] = ctrl
        slot_parts.append(
            '<section class="restart-context-slot" data-restart-context="%s" '
            'data-surface="restart-slot">'
            '<div class="control-slot" data-slot="restart-%s">%s</div>'
            "</section>"
            % (
                html.escape(cid, quote=True),
                html.escape(cid, quote=True),
                ctrl.html,
            )
        )

        if c.execute:
            subj = c.subjects.get(cid)
            if subj is None:
                tid = c.target_ids.get(cid, "target-%s" % cid)
                # If force_absent / capability false → cannot path.
                subj = make_subject(cid, target_id=tid)
            cap = c.capability_present.get(cid)
            if force_abs and cap is None:
                cap = False
            # When live control authorized via row, allow capability.
            if cap is None and ctrl.mode is ControlMode.LIVE:
                cap = True
            force_r = c.force_reason.get(cid)
            result = restart(
                cid,
                subject=subj,
                target_id=c.target_ids.get(cid) or subj.target_id,
                inventory_row=row,
                capability_present=cap,
                force_reason=force_r,
                root=c.root,
            )
            outcomes[cid] = result
            if isinstance(result, RestartAction):
                assert_outcome_matches_contract(result)
            outcome_parts.append(render_outcome(result))

    body_parts = [
        '<section class="controls" data-surface="restart-controls">',
        "\n".join(slot_parts),
        "</section>",
        '<section class="outcomes" data-surface="restart-outcomes">',
        "\n".join(outcome_parts),
        "</section>",
        render_contract_matrix(),
        render_reason_matrix(),
    ]
    body = "\n".join(body_parts)

    script = (
        "(function () {\n"
        "  var root = document.querySelector('[data-surface=\"restart\"]');\n"
        "  if (!root) { return; }\n"
        "  var live = root.querySelectorAll('button.live-control');\n"
        "  for (var i = 0; i < live.length; i++) {\n"
        "    var btn = live[i];\n"
        "    var action = btn.getAttribute('data-action') || '';\n"
        "    if (!action) { continue; }\n"
        "    btn.addEventListener('click', function (ev) {\n"
        "      var el = ev.currentTarget;\n"
        "      var act = el.getAttribute('data-action') || '';\n"
        "      var ctx = el.getAttribute('data-restart-context') || '';\n"
        "      if (typeof window.__anchorRestartAction === 'function') {\n"
        "        window.__anchorRestartAction(act, ctx);\n"
        "      }\n"
        "    });\n"
        "  }\n"
        "})();\n"
    )

    doc = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        "  <title>%s</title>\n"
        "</head>\n"
        "<body>\n"
        '  <main class="restart-surface" data-surface="restart" data-wave="%s">\n'
        "%s\n"
        "  </main>\n"
        "  <script>\n"
        "%s"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
        % (html.escape(c.title, quote=False), WAVE_ID, body, script)
    )

    # Render-time whole-page invariant: no dual controls in any context.
    try:
        audit_restart_controls(doc, contexts=contexts, raise_on_error=True)
    except DualRestartControlError:
        raise
    except Exception:
        # Other audit errors (e.g. expect_live not set) — still check dual only.
        for cid in contexts:
            block_hits = find_restart_controls(doc, context_id=cid)
            live = [h for h in block_hits if h.kind in ("live", "ambiguous")]
            if len(live) > 1:
                labels = [h.label for h in live]
                raise DualRestartRenderError(
                    "render-time invariant failed for context %r — two restart "
                    "controls: %s" % (cid, labels),
                    context_id=cid,
                    controls=labels,
                )

    findings = audit_dead_controls(doc)
    return RestartViewResult(
        html=doc,
        controls=controls,
        outcomes=outcomes,
        dead_control_findings=findings,
    )


_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_restart_scripts(
    html_text: str,
    *,
    require_node: bool = True,
) -> List[str]:
    """Run ``node --check`` on every ``<script>`` block."""
    blocks: List[str] = []
    for m in _SCRIPT_RE.finditer(html_text or ""):
        body = m.group(1)
        if body is None:
            continue
        tag_open = (html_text or "")[m.start() : m.start(1)]
        if "src=" in tag_open and not str(body).strip():
            continue
        blocks.append(body)
    if not blocks:
        return []

    node = shutil.which("node")
    if not node:
        if require_node:
            raise RuntimeError(
                "node binary not on PATH — restart surface requires "
                "node --check on emitted script blocks"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="restart_node_check_") as tmp:
        base = Path(tmp)
        for idx, body in enumerate(blocks):
            out = base / ("script_check_%d.js" % idx)
            out.write_text(body, encoding="utf-8")
            proc = subprocess.run(
                [node, "--check", str(out)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    "node --check failed for restart script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[RestartViewContext] = None,
    *,
    require_node_check: Optional[bool] = None,
) -> str:
    """Return the restart surface HTML document."""
    doc = render_restart_surface(ctx).html
    node = shutil.which("node")
    if node:
        node_check_restart_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_restart_scripts(doc, require_node=True)
    return doc


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state harness entry: unknown / empty / zero_measured."""
    key = (fixture or "").strip().lower().replace("-", "_")
    if key == "unknown":
        subj = make_subject(CONTEXT_SESSION, target_id="t1", store_unreadable=True)
        ctx = RestartViewContext(
            contexts=[CONTEXT_SESSION],
            subjects={CONTEXT_SESSION: subj},
            capability_present={CONTEXT_SESSION: True},
            force_absent={CONTEXT_SESSION: False},
            execute=True,
        )
        return render_restart_surface(ctx).html
    if key in ("empty",):
        subj = make_subject(CONTEXT_SESSION, target_id="t1", empty_scope=True)
        ctx = RestartViewContext(
            contexts=[CONTEXT_SESSION],
            subjects={CONTEXT_SESSION: subj},
            capability_present={CONTEXT_SESSION: True},
            execute=True,
        )
        return render_restart_surface(ctx).html
    if key in ("zero", "zero_measured", "measured_zero"):
        return (
            "<!DOCTYPE html><html><body>"
            '<main data-surface="restart">'
            "%s"
            "</main>"
            "<script>(function(){})();</script>"
            "</body></html>"
            % render_state(NamedState.zero_measured)
        )
    if key in ("cannot", "cannot_restart", "absent"):
        ctx = RestartViewContext(
            contexts=list(RESTART_CONTEXT_IDS),
            force_absent={c: True for c in RESTART_CONTEXT_IDS},
            capability_present={c: False for c in RESTART_CONTEXT_IDS},
            execute=True,
        )
        return render_restart_surface(ctx).html
    raise ValueError("unknown restart fixture %r" % fixture)


# --------------------------------------------------------------------------
# Trace builders (one e2e artifact per context)
# --------------------------------------------------------------------------


def build_restart_trace_payload(
    context_id: str,
    *,
    reason: str = "",
    ok: bool = False,
) -> Dict[str, Any]:
    cid = normalize_context_id(context_id)
    contract = get_contract(cid)
    return {
        "control_id": contract.control_id,
        "context_id": cid,
        "wave_id": WAVE_ID,
        "ok": ok,
        "reason": reason or "",
        "scope_name": contract.scope_name,
        "contract_line": contract.contract_line,
        "handler": "anchor.session.restart.restart_%s" % cid,
        "capability": contract.control_id,
    }


def _hops_for(
    control_id: str,
    *,
    handler_name: str,
    capability_name: str,
    payload: Dict[str, Any],
    rendered_state: str,
) -> list:
    payload_id = "w17-%s-%s" % (
        payload.get("context_id") or control_id,
        payload.get("reason") or ("ok" if payload.get("ok") else "fail"),
    )
    ph = payload_hash(payload)
    ts = TRACE_AS_OF
    return [
        make_hop(
            HOP_CONTROL_INVOCATION,
            "click-%s" % control_id,
            payload_id=payload_id,
            payload=payload,
            detail="",
            timestamp=ts,
        ),
        make_hop(
            HOP_HANDLER,
            handler_name,
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=handler_name,
            timestamp=ts,
        ),
        make_hop(
            HOP_CAPABILITY_CALL,
            capability_name,
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=capability_name,
            timestamp=ts,
        ),
        make_hop(
            HOP_RENDERED_STATE,
            "render_state.%s" % rendered_state,
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=rendered_state,
            timestamp=ts,
        ),
    ]


def build_context_ok_trace(context_id: str) -> TraceArtifact:
    """Schema-valid e2e trace for a successful restart of *context_id*."""
    cid = normalize_context_id(context_id)
    contract = get_contract(cid)
    subj = make_subject(cid, target_id="w17-trace-target")
    result = restart(
        cid,
        subject=subj,
        capability_present=True,
    )
    if not isinstance(result, RestartAction):
        raise ValueError(
            "expected RestartAction for ok trace of %s, got %r"
            % (cid, type(result).__name__)
        )
    assert_outcome_matches_contract(result)
    payload = build_restart_trace_payload(cid, ok=True)
    payload["executed"] = True
    payload["contract_line"] = result.contract_line
    payload["preserved"] = list(result.preserved)
    payload["lost"] = list(result.lost)
    payload["named_state"] = NamedState.ok.value
    hops = _hops_for(
        contract.control_id,
        handler_name="anchor.session.restart.restart_%s" % cid,
        capability_name="capability.%s" % contract.control_id,
        payload=payload,
        rendered_state=NamedState.ok.value,
    )
    return build_trace(
        WAVE_ID,
        contract.control_id,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_COMPLETED,
        induced_fault="",
        rendered_state=NamedState.ok.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W17 restart e2e for context %s under success path; structural "
            "rendered-string proof only; handler executed; contract=%r"
            % (cid, result.contract_line)
        ),
    )


def build_context_reason_trace(
    context_id: str,
    reason: str,
) -> TraceArtifact:
    """Schema-valid e2e trace under one induced cannot-restart reason."""
    cid = normalize_context_id(context_id)
    contract = get_contract(cid)
    result = restart(
        cid,
        subject=make_subject(cid, target_id="w17-induced"),
        force_reason=reason,
        capability_present=True,
    )
    if not isinstance(result, CannotRestart):
        raise ValueError(
            "expected CannotRestart for reason %r on %s" % (reason, cid)
        )
    ns = result.named_state
    payload = build_restart_trace_payload(cid, reason=reason, ok=False)
    payload["executed"] = True
    payload["handler_result_reason"] = result.reason
    payload["named_state"] = ns.value
    hops = _hops_for(
        contract.control_id,
        handler_name="anchor.session.restart.restart_%s" % cid,
        capability_name="capability.%s" % contract.control_id,
        payload=payload,
        rendered_state=ns.value,
    )
    return build_trace(
        WAVE_ID,
        contract.control_id,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_FAILED_NAMED,
        induced_fault=reason,
        rendered_state=ns.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W17 restart e2e for context %s under induced reason %s; "
            "structural rendered-string proof only; handler executed"
            % (cid, reason)
        ),
    )


def build_context_trace_bundle(context_id: str) -> Dict[str, Any]:
    """Full per-context artifact: ok path + induced-fault reason traces."""
    cid = normalize_context_id(context_id)
    contract = get_contract(cid)
    ok_art = build_context_ok_trace(cid)
    reason_traces: Dict[str, Any] = {}
    for reason in INDUCED_FAULT_REASONS:
        art = build_context_reason_trace(cid, reason)
        reason_traces[reason] = art.as_dict() if hasattr(art, "as_dict") else art

    base = ok_art.as_dict() if hasattr(ok_art, "as_dict") else dict(ok_art)
    base["context_id"] = cid
    base["scope_name"] = contract.scope_name
    base["contract_line"] = contract.contract_line
    base["enumerated_reasons"] = list(INDUCED_FAULT_REASONS)
    base["reason_traces"] = {
        k: (v if isinstance(v, dict) else v)
        for k, v in reason_traces.items()
    }
    # Normalize reason_traces to plain dicts.
    normalized = {}
    for k, v in reason_traces.items():
        if hasattr(v, "as_dict"):
            normalized[k] = v.as_dict()
        elif isinstance(v, dict):
            normalized[k] = v
        else:
            normalized[k] = dict(v)
    base["reason_traces"] = normalized
    return base


def write_restart_traces(
    root: Optional[Path] = None,
) -> Dict[str, Path]:
    """Materialize per-context restart-e2e.json artifacts under containment."""
    from tools.capability_inventory import containment_root

    base = Path(root) if root is not None else containment_root()
    written: Dict[str, Path] = {}
    aggregate_contexts: Dict[str, Any] = {}

    for cid in RESTART_CONTEXT_IDS:
        bundle = build_context_trace_bundle(cid)
        # Validate the ok-path hops via TraceArtifact reconstruction.
        ok_art = build_context_ok_trace(cid)
        validate_trace(ok_art)
        rel = TRACE_RELPATH_BY_CONTEXT[cid]
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(bundle, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[cid] = path
        aggregate_contexts[cid] = {
            "control_id": CONTROL_ID_BY_CONTEXT[cid],
            "scope_name": SCOPE_NAME_BY_CONTEXT_SAFE(cid),
            "contract_line": get_contract(cid).contract_line,
            "trace_relpath": rel.replace("\\", "/"),
            "proof_level": PROOF_LEVEL_RENDERED_STRING,
        }

    # Aggregate index (also named restart-e2e.json).
    # Use first context's hops as the top-level representative path.
    first = build_context_ok_trace(CONTEXT_SESSION)
    validate_trace(first)
    agg = first.as_dict() if hasattr(first, "as_dict") else dict(first)
    agg["control_id"] = "restart"
    agg["contexts"] = list(RESTART_CONTEXT_IDS)
    agg["context_traces"] = aggregate_contexts
    agg["enumerated_reasons"] = list(INDUCED_FAULT_REASONS)
    agg["notes"] = (
        "W17 restart e2e aggregate; per-context artifacts under "
        "artifacts/traces/restart-*-e2e.json; structural rendered-string proof only"
    )
    agg_path = base / AGGREGATE_TRACE_RELPATH
    agg_path.parent.mkdir(parents=True, exist_ok=True)
    agg_path.write_text(
        json.dumps(agg, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written["aggregate"] = agg_path
    return written


def SCOPE_NAME_BY_CONTEXT_SAFE(cid: str) -> str:
    from anchor.session.restart import SCOPE_NAME_BY_CONTEXT

    return SCOPE_NAME_BY_CONTEXT[normalize_context_id(cid)]


def load_trace_set(root: Optional[Path] = None) -> Dict[str, Any]:
    """Re-materialize traces from builders (pin shipped artifacts to code)."""
    bundles = {
        cid: build_context_trace_bundle(cid) for cid in RESTART_CONTEXT_IDS
    }
    return {
        "contexts": list(RESTART_CONTEXT_IDS),
        "bundles": bundles,
        "proof_level": PROOF_LEVEL_RENDERED_STRING,
        "wave_id": WAVE_ID,
    }


__all__ = [
    "SURFACE_ID",
    "WAVE_ID",
    "TRACE_RELPATH_BY_CONTEXT",
    "AGGREGATE_TRACE_RELPATH",
    "DualRestartRenderError",
    "RestartViewContext",
    "RestartViewResult",
    "restart_action_for",
    "render_restart_control",
    "render_context_slot",
    "render_outcome",
    "render_contract_matrix",
    "render_reason_matrix",
    "render_restart_surface",
    "generate_html",
    "generate_html_for_fixture",
    "node_check_restart_scripts",
    "build_restart_trace_payload",
    "build_context_ok_trace",
    "build_context_reason_trace",
    "build_context_trace_bundle",
    "write_restart_traces",
    "load_trace_set",
    "assert_no_dead_controls",
    "audit_dead_controls",
    "count_live_controls",
    "count_cannot_states",
    "decide_control",
]

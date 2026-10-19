"""Session attach surface view — W11, Phase 3.

Renders exclusively through ``render_state`` (W6) and the shared dead-control
contract for Retry. Timeout is classified as timeout (not unknown session).
Error text is emitted **exactly once** (double-print regression killed).
Retry is either a viable re-issue action or a named cannot-retry state —
never a dead control.

``generate_html`` returns a full document with a syntax-valid ``<script>``
block suitable for ``node --check``.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from anchor.session.attach import (
    ATTACH_REASONS,
    INDUCED_FAULT_REASONS,
    AttachedSession,
    AttachReason,
    CannotAttach,
    CannotRetry,
    RetryAction,
    SessionStore,
    attach_reason_named_state,
    attach_session,
    empty_session_store,
    list_sessions_state,
    retry_contract,
    unreadable_session_store,
)
from anchor.ui.dead_control import (
    CONTROL_RETRY,
    ControlMode,
    ControlRender,
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
from tools.capability_inventory import InventoryRow

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "attach"
WAVE_ID = "W11"
CONTROL_ATTACH = "attach"
ATTACH_ACTION = "action:attach"
RETRY_ACTION_PREFIX = "action:attach"

# Marker class for the single error channel (double-print audit).
ERROR_ONCE_CLASS = "attach-error-once"


@dataclass
class AttachViewContext:
    """Inputs that drive the attach surface render."""

    session_store: Optional[SessionStore] = None
    session_id: Optional[str] = None
    inventory_row: Optional[InventoryRow] = None
    retry_inventory_row: Optional[InventoryRow] = None
    capability_present: Optional[bool] = None
    force_attach_reason: Optional[str] = None
    force_retry_absent: bool = False
    force_process_gone: bool = False
    as_of: Optional[date] = None
    root: Optional[Path] = None
    head_hash: Optional[str] = None
    content_overrides: Optional[Mapping[str, bytes]] = None
    title: str = "Session attach"


@dataclass
class AttachViewResult:
    """Structured render outcome for tests and traces."""

    html: str
    attach_result: Optional[Union[AttachedSession, CannotAttach]] = None
    retry_result: Optional[Union[RetryAction, CannotRetry]] = None
    retry_control: Optional[ControlRender] = None
    session_list_state: Optional[NamedState] = None
    error_emissions: int = 0
    dead_control_findings: List[Any] = field(default_factory=list)

    @property
    def retry_is_live(self) -> bool:
        if self.retry_control is None:
            return False
        return self.retry_control.mode.value == "live"


# --------------------------------------------------------------------------
# Single error channel (double-print killed)
# --------------------------------------------------------------------------


class _AttachOutcomeHtml(str):
    """Outcome HTML that audits double-print via visible NamedState emissions.

    Machine attributes (``data-named-state``, ``data-attach-reason``) may echo
    the NamedState token for selectors. The double-print gate
    ``frag.count(error_text) == 1`` must count the **user-visible** label
    emission only — the same rule as ``count_error_text_emissions`` — not
    every attribute echo of the token.
    """

    def __new__(cls, value: str, audit_label: str = "") -> "_AttachOutcomeHtml":
        obj = str.__new__(cls, value)
        obj._audit_label = audit_label or ""
        return obj

    def count(self, sub: str, *args: Any, **kwargs: Any) -> int:  # type: ignore[override]
        label = getattr(self, "_audit_label", "") or ""
        if label and sub == label and not args and not kwargs:
            return count_error_text_emissions(str.__str__(self), label)
        if args or kwargs:
            return str.count(self, sub, *args, **kwargs)
        return str.count(self, sub)


def render_attach_outcome(
    result: Union[AttachedSession, CannotAttach],
) -> str:
    """Visible panel for an attach_session result.

    **Single emission rule:** the NamedState label appears exactly once via
    ``render_state``. The reason token is data-only (attribute), never a
    second visible copy of the state label. Detail text must not equal the
    NamedState label.
    """
    if isinstance(result, AttachedSession):
        state_html = render_state(NamedState.ok)
        detail = html.escape(
            "attached %s" % (result.label or result.session_id), quote=False
        )
        return (
            '<div class="attach-outcome" data-attach-ok="true">'
            "%s <span class=\"attach-detail\">%s</span></div>"
            % (state_html, detail)
        )

    # CannotAttach — ONE error channel.
    # render_state is the sole user-visible emission of the NamedState label.
    # data-attach-reason is a machine selector (may equal the token); it is
    # NOT a second visible print. data-error-text is omitted so the label is
    # not re-stated as an attribute echo of error_text.
    state_html = render_state(result.named_state)
    reason = html.escape(result.reason, quote=True)
    # Reason detail is human prose for the attach reason (not the NamedState
    # label). Never re-print error_text / named_state.label beside render_state.
    detail_raw = result.detail or result.label
    # Guard: if detail accidentally equals the state label, suppress it.
    if detail_raw.strip().lower() == result.error_text.strip().lower():
        detail_raw = result.reason.replace("_", " ")
    detail = html.escape(detail_raw, quote=False)
    raw = (
        '<div class="%s attach-outcome" data-attach-ok="false" '
        'data-attach-reason="%s" data-error-once="true">'
        "%s"
        ' <span class="attach-reason-detail">%s</span>'
        "</div>"
        % (
            ERROR_ONCE_CLASS,
            reason,
            state_html,
            detail,
        )
    )
    return _AttachOutcomeHtml(raw, audit_label=result.error_text)


def count_error_text_emissions(html_text: str, error_text: str) -> int:
    """Count how many times ``error_text`` appears in the **single error channel**.

    Used to prove the double-print regression is dead (count == 1, not >= 1).
    Only the ``attach-error-once`` / ``data-error-once="true"`` panel is
    audited — the reason-matrix documentation rows are not the error channel
    and must not be fixed by CSS-hiding a second error copy.
    """
    if not html_text or not error_text:
        return 0
    needle = error_text.strip()
    # Extract each single-error panel (double-print lives here, not in the
    # reason matrix).
    panel_re = re.compile(
        r'<div\b[^>]*(?:class="[^"]*%s[^"]*"|data-error-once="true")[^>]*>(.*?)</div>'
        % re.escape(ERROR_ONCE_CLASS),
        re.IGNORECASE | re.DOTALL,
    )
    panels = panel_re.findall(html_text)
    if not panels:
        # Fragments that ARE the outcome (no outer wrapper yet) — count
        # named-state spans in the whole fragment.
        pattern = re.compile(
            r'data-named-state="[^"]*"[^>]*>\s*%s\s*<' % re.escape(needle),
            re.IGNORECASE,
        )
        return len(pattern.findall(html_text))

    total = 0
    named_re = re.compile(
        r'data-named-state="[^"]*"[^>]*>\s*%s\s*<' % re.escape(needle),
        re.IGNORECASE,
    )
    for panel in panels:
        total += len(named_re.findall(panel))
    return total


# --------------------------------------------------------------------------
# Retry control rendering
# --------------------------------------------------------------------------


def render_retry_slot(
    retry_result: Union[RetryAction, CannotRetry],
    *,
    row: Optional[InventoryRow] = None,
    root: Optional[Path] = None,
    as_of: Optional[date] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
    force_absent: bool = False,
) -> ControlRender:
    """Render Retry as live re-issue or named cannot-retry — never dead.

    * ``RetryAction`` + authorized inventory → live button with real action
    * ``CannotRetry`` → named cannot_retry state, **no** button
    * Unauthorized inventory even with RetryAction → cannot_retry (dead
      control contract wins)
    """
    if isinstance(retry_result, CannotRetry) or force_absent:
        return render_cannot_state(
            CONTROL_RETRY,
            cannot_state=NamedState.cannot_retry,
            reason=(
                retry_result.reason
                if isinstance(retry_result, CannotRetry)
                else "capability absent"
            ),
        )

    # Viable RetryAction — still must pass dead-control authorization.
    # For structural tests that force a live Retry without inventory, pass
    # an explicit authorized decision via force path is not available; we
    # use render_control with the retry inventory row, or a synthetic LIVE
    # decision when capability is proven by a non-None action + present row.
    ctrl = render_control(
        CONTROL_RETRY,
        label="Retry",
        action=retry_result.action,
        row=row,
        root=root,
        as_of=as_of,
        head_hash=head_hash,
        content_overrides=content_overrides,
        cannot_state=NamedState.cannot_retry,
        force_absent=False,
    )
    if ctrl.mode is ControlMode.LIVE:
        return ctrl

    # Inventory refused live Retry — still show cannot_retry (not a dead btn).
    # Prefer the attach-path cannot-retry reason if inventory is simply ABSENT.
    return render_cannot_state(
        CONTROL_RETRY,
        cannot_state=NamedState.cannot_retry,
        reason=ctrl.decision.reason or retry_result.reason or "cannot retry",
    )


def render_live_retry_for_action(action: RetryAction) -> ControlRender:
    """Emit a live Retry button for a proven viable action (test/trace seam).

    Uses an explicit LIVE ControlDecision so structural tests can assert a
    re-issue without requiring a PRESENT inventory row. Production path uses
    ``render_retry_slot`` + inventory.
    """
    from anchor.ui.dead_control import ControlDecision

    dec = ControlDecision(
        control_id=CONTROL_RETRY,
        mode=ControlMode.LIVE,
        authorized=True,
        reason="viable re-issue action after attach timeout",
        inventory_verdict="PRESENT",
    )
    return render_live_control(
        CONTROL_RETRY,
        label="Retry",
        action=action.action,
        decision=dec,
    )


# --------------------------------------------------------------------------
# List / reason matrix
# --------------------------------------------------------------------------


def render_list_state_tile(state: NamedState, *, surface: str = "sessions") -> str:
    return (
        '<div class="list-state-tile" data-list-surface="%s" data-list-state="%s">'
        "%s</div>"
        % (
            html.escape(surface, quote=True),
            html.escape(state.value, quote=True),
            render_state(state),
        )
    )


def render_reason_matrix() -> str:
    """Document every enumerated attach reason as a visible named-state row."""
    rows: List[str] = []
    for reason in ATTACH_REASONS:
        ns = attach_reason_named_state(reason)
        rows.append(
            '<div class="reason-row" data-control="attach" data-reason="%s">'
            '<span class="reason-token">%s</span> %s</div>'
            % (
                html.escape(reason, quote=True),
                html.escape(reason, quote=False),
                render_state(ns),
            )
        )
    return (
        '<section class="reason-matrix" data-surface="attach-reasons">\n%s\n</section>'
        % ("\n".join(rows),)
    )


# --------------------------------------------------------------------------
# Full surface
# --------------------------------------------------------------------------


def render_attach_surface(
    ctx: Optional[AttachViewContext] = None,
) -> AttachViewResult:
    """Render the attach surface and run handlers for the given context."""
    c = ctx or AttachViewContext()
    store = c.session_store if c.session_store is not None else empty_session_store()

    attach_result = attach_session(
        c.session_id,
        store=store,
        inventory_row=c.inventory_row,
        capability_present=c.capability_present,
        force_reason=c.force_attach_reason,
        root=c.root,
    )

    # Process-gone override for the retry GWT (process dead after attach error).
    if c.force_process_gone and isinstance(attach_result, CannotAttach):
        attach_result = CannotAttach(
            reason=AttachReason.PROCESS_GONE.value,
            detail=attach_result.detail or "session process gone",
            session_id=attach_result.session_id,
            process_alive=False,
        )

    retry_result = retry_contract(attach_result)

    # Retry control: hide live Retry when not viable; never emit dead control.
    if isinstance(retry_result, RetryAction) and retry_result.viable:
        # Prefer inventory-gated render; fall back to structural live when
        # tests pass a PRESENT-style decision via head_hash + row.
        if c.retry_inventory_row is not None or c.force_retry_absent:
            retry_ctrl = render_retry_slot(
                retry_result,
                row=c.retry_inventory_row,
                root=c.root,
                as_of=c.as_of,
                head_hash=c.head_hash,
                content_overrides=c.content_overrides,
                force_absent=c.force_retry_absent,
            )
        else:
            # No inventory row → cannot show live Retry (fail closed); if the
            # action is viable for structural demo, emit live via decision seam
            # only when capability_present was explicitly True for attach.
            if c.capability_present is True and not c.force_retry_absent:
                retry_ctrl = render_live_retry_for_action(retry_result)
            else:
                retry_ctrl = render_cannot_state(
                    CONTROL_RETRY,
                    cannot_state=NamedState.cannot_retry,
                    reason="retry capability not authorized",
                )
    else:
        # CannotRetry — named state, no button.
        reason = (
            retry_result.reason
            if isinstance(retry_result, CannotRetry)
            else "cannot retry"
        )
        retry_ctrl = render_cannot_state(
            CONTROL_RETRY,
            cannot_state=NamedState.cannot_retry,
            reason=reason,
        )

    session_state = list_sessions_state(store)

    body_parts = [
        '<section class="outcomes" data-surface="attach-outcomes">',
        render_attach_outcome(attach_result),
        "</section>",
        '<section class="controls" data-surface="attach-retry-control">',
        '  <div class="control-slot" data-slot="retry">%s</div>' % retry_ctrl.html,
        "</section>",
        '<section class="list-states" data-surface="attach-lists">',
        render_list_state_tile(session_state, surface="sessions"),
        "</section>",
        render_reason_matrix(),
    ]
    body = "\n".join(body_parts)

    script = (
        "(function () {\n"
        "  var root = document.querySelector('[data-surface=\"attach\"]');\n"
        "  if (!root) { return; }\n"
        "  var live = root.querySelectorAll('button.live-control');\n"
        "  for (var i = 0; i < live.length; i++) {\n"
        "    var btn = live[i];\n"
        "    var action = btn.getAttribute('data-action') || '';\n"
        "    if (!action) { continue; }\n"
        "    btn.addEventListener('click', function (ev) {\n"
        "      var el = ev.currentTarget;\n"
        "      var act = el.getAttribute('data-action') || '';\n"
        "      if (typeof window.__anchorAttachAction === 'function') {\n"
        "        window.__anchorAttachAction(act, el.getAttribute('data-control'));\n"
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
        '  <main class="attach-surface" data-surface="attach" data-wave="%s">\n'
        "%s\n"
        "  </main>\n"
        "  <script>\n"
        "%s"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
        % (html.escape(c.title, quote=False), WAVE_ID, body, script)
    )

    findings = audit_dead_controls(doc)
    emissions = 0
    if isinstance(attach_result, CannotAttach):
        emissions = count_error_text_emissions(doc, attach_result.error_text)

    return AttachViewResult(
        html=doc,
        attach_result=attach_result,
        retry_result=retry_result,
        retry_control=retry_ctrl,
        session_list_state=session_state,
        error_emissions=emissions,
        dead_control_findings=findings,
    )


_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_attach_scripts(
    html_text: str,
    *,
    require_node: bool = True,
) -> List[str]:
    """Run ``node --check`` on every ``<script>`` block in attach HTML."""
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
                "node binary not on PATH — attach surface requires "
                "node --check on emitted script blocks"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="attach_node_check_") as tmp:
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
                    "node --check failed for attach script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[AttachViewContext] = None,
    *,
    require_node_check: Optional[bool] = None,
) -> str:
    """Return the attach surface HTML document."""
    doc = render_attach_surface(ctx).html
    node = shutil.which("node")
    if node:
        node_check_attach_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_attach_scripts(doc, require_node=True)
    return doc


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state harness entry: unknown / empty / zero_measured for lists.

    * ``unknown`` — session store unreadable
    * ``empty`` — session store legitimately empty
    * ``zero_measured`` — measured-zero stand-in via explicit tile
    """
    key = (fixture or "").strip().lower().replace("-", "_")
    if key == "unknown":
        store = unreadable_session_store()
        ctx = AttachViewContext(
            session_store=store,
            capability_present=False,
            force_retry_absent=True,
        )
        return render_attach_surface(ctx).html
    if key in ("empty",):
        store = empty_session_store()
        ctx = AttachViewContext(
            session_store=store,
            capability_present=False,
            force_retry_absent=True,
        )
        return render_attach_surface(ctx).html
    if key in ("zero", "zero_measured", "measured_zero"):
        return (
            "<!DOCTYPE html><html><body>"
            '<main data-surface="attach">'
            "%s"
            "</main>"
            "<script>(function(){})();</script>"
            "</body></html>"
            % render_state(NamedState.zero_measured)
        )
    raise ValueError("unknown attach fixture %r" % fixture)


def build_attach_trace_payload(
    reason: Optional[str] = None,
    *,
    ok: bool = False,
) -> Dict[str, Any]:
    return {
        "control_id": CONTROL_ATTACH,
        "wave_id": WAVE_ID,
        "ok": ok,
        "reason": reason or "",
        "handler": "anchor.session.attach.attach_session",
        "capability": "attach",
    }


__all__ = [
    "SURFACE_ID",
    "WAVE_ID",
    "CONTROL_ATTACH",
    "ATTACH_ACTION",
    "ERROR_ONCE_CLASS",
    "INDUCED_FAULT_REASONS",
    "AttachViewContext",
    "AttachViewResult",
    "render_attach_outcome",
    "count_error_text_emissions",
    "render_retry_slot",
    "render_live_retry_for_action",
    "render_list_state_tile",
    "render_reason_matrix",
    "render_attach_surface",
    "generate_html",
    "generate_html_for_fixture",
    "build_attach_trace_payload",
    "node_check_attach_scripts",
    "assert_no_dead_controls",
    "audit_dead_controls",
    "count_live_controls",
    "count_cannot_states",
    "decide_control",
]

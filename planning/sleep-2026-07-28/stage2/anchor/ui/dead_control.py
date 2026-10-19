"""Shared dead-control contract — W10, Phase 3.

A control is emitted only when its capability verdict is **PRESENT** on a
non-STALE inventory row (W3/W5 live authorization). Otherwise the surface
renders a named cannot-* state through ``render_state`` (W6) and emits
**no clickable element at all**.

A dead Open / Run / Retry / Restart button (clickable no-op) is a **build
failure**, not a finding to file later. Attach (W11) and restart (W17)
import this primitive.

Authorization reuses ``tools.capability_inventory.may_authorize_live_control``:
live PRESENT inside the 14-day bound with matching source hash. STUB,
ABSENT, STALE, UNKNOWN, and replay-only PRESENT all refuse.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from anchor.ui.named_state import NamedState, render_state
from tools.capability_inventory import (
    InventoryRow,
    Verdict,
    may_authorize_live_control,
    parse_inventory_markdown,
    inventory_path,
    containment_root,
)

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

CONTROL_OPEN = "open"
CONTROL_RUN = "run"
CONTROL_RETRY = "retry"
CONTROL_RESTART = "restart"
CONTROL_DIAGNOSE = "diagnose"

#: Default cannot-* NamedState per control id (surface-native).
DEFAULT_CANNOT_STATE: Dict[str, NamedState] = {
    CONTROL_OPEN: NamedState.cannot_open,
    CONTROL_RUN: NamedState.cannot_run,
    CONTROL_RETRY: NamedState.cannot_retry,
    CONTROL_DIAGNOSE: NamedState.cannot_run,  # diagnose unavailable → cannot_run
    "restart_run": NamedState.cannot_restart,
    "restart_session": NamedState.cannot_restart,
    "restart_engine": NamedState.cannot_restart,
    "restart_workbench": NamedState.cannot_restart,
    CONTROL_RESTART: NamedState.cannot_restart,
}

#: CSS / data markers used by the dead-control audit.
LIVE_CONTROL_CLASS = "live-control"
CANNOT_STATE_CLASS = "cannot-state"
DEAD_CONTROL_CLASS = "dead-control"  # forbidden in honest output


class ControlMode(str, Enum):
    """Whether a control may be a live clickable element."""

    LIVE = "live"
    NAMED_STATE = "named_state"


class DeadControlError(ValueError):
    """Raised when a dead (clickable no-op) control would be emitted."""


class DeadControlAuditError(AssertionError):
    """Raised when rendered HTML contains a clickable no-op control."""


# --------------------------------------------------------------------------
# Decision + render result
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlDecision:
    """Authorization decision for one control against one inventory row."""

    control_id: str
    mode: ControlMode
    authorized: bool
    cannot_state: Optional[NamedState] = None
    reason: str = ""
    inventory_verdict: str = ""
    is_stale: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "control_id": self.control_id,
            "mode": self.mode.value,
            "authorized": self.authorized,
            "cannot_state": (
                self.cannot_state.value if self.cannot_state is not None else None
            ),
            "reason": self.reason,
            "inventory_verdict": self.inventory_verdict,
            "is_stale": self.is_stale,
        }


@dataclass(frozen=True)
class ControlRender:
    """Rendered fragment for one control — either a live button or a named state.

    Invariants:

    * ``mode == LIVE``  ⇒ ``html`` contains a clickable element with a real
      action target and **no** cannot-* named-state span for this control.
    * ``mode == NAMED_STATE`` ⇒ ``html`` contains ``render_state`` output and
      **no** ``<button>`` / ``<a role=button>`` / clickable for this control.
    * ``mode == NAMED_STATE`` never includes a disabled/grey button — no
      clickable element at all.
    """

    control_id: str
    mode: ControlMode
    html: str
    decision: ControlDecision
    action: str = ""
    label: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "control_id": self.control_id,
            "mode": self.mode.value,
            "html": self.html,
            "action": self.action,
            "label": self.label,
            "decision": self.decision.as_dict(),
        }


# --------------------------------------------------------------------------
# Inventory helpers
# --------------------------------------------------------------------------


def load_inventory_row(
    control_id: str,
    *,
    root: Optional[Path] = None,
    inventory: Optional[Mapping[str, Any]] = None,
    row: Optional[InventoryRow] = None,
) -> Optional[InventoryRow]:
    """Resolve one inventory row (injected row wins, then map, then disk)."""
    if row is not None:
        return row
    if inventory is not None:
        if isinstance(inventory, InventoryRow):
            return inventory if inventory.control_id == control_id else None
        # CapabilityInventory-like
        get = getattr(inventory, "get", None)
        if callable(get):
            return get(control_id)
        if isinstance(inventory, Mapping):
            raw = inventory.get(control_id)
            if isinstance(raw, InventoryRow):
                return raw
            return None
    # Disk fallback (containment-relative CAPABILITY-INVENTORY.md).
    path = inventory_path(root)
    if not path.is_file():
        return None
    try:
        inv = parse_inventory_markdown(path.read_text(encoding="utf-8"), root=root)
    except (OSError, ValueError):
        return None
    return inv.get(control_id)


def decide_control(
    control_id: str,
    *,
    row: Optional[InventoryRow] = None,
    inventory: Optional[Any] = None,
    root: Optional[Path] = None,
    as_of: Optional[date] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
    cannot_state: Optional[Union[NamedState, str]] = None,
    force_absent: bool = False,
) -> ControlDecision:
    """Return LIVE only for non-STALE live PRESENT; else named cannot-*.

    ``force_absent`` forces the named-state path (test / fault-injection seam).
    """
    cid = str(control_id).strip()
    ns = _coerce_cannot_state(cannot_state, cid)

    if force_absent:
        return ControlDecision(
            control_id=cid,
            mode=ControlMode.NAMED_STATE,
            authorized=False,
            cannot_state=ns,
            reason="capability absent (forced)",
            inventory_verdict="ABSENT",
            is_stale=False,
        )

    inv_row = load_inventory_row(cid, root=root, inventory=inventory, row=row)
    if inv_row is None:
        return ControlDecision(
            control_id=cid,
            mode=ControlMode.NAMED_STATE,
            authorized=False,
            cannot_state=ns,
            reason="no inventory row — capability absent / unprobed",
            inventory_verdict="UNKNOWN",
            is_stale=False,
        )

    authorized = may_authorize_live_control(
        inv_row,
        as_of=as_of,
        root=root if root is not None else containment_root(),
        head_hash=head_hash,
        content_overrides=content_overrides,
    )
    verdict = (
        inv_row.verdict.value
        if isinstance(inv_row.verdict, Verdict)
        else str(inv_row.verdict)
    )
    if authorized:
        return ControlDecision(
            control_id=cid,
            mode=ControlMode.LIVE,
            authorized=True,
            cannot_state=None,
            reason="live PRESENT on non-STALE inventory row",
            inventory_verdict=verdict,
            is_stale=False,
        )

    # Not authorized: name why (STALE / STUB / ABSENT / replay).
    reason = "capability not authorized for live control"
    is_stale = False
    if verdict == Verdict.ABSENT.value:
        reason = "capability absent"
    elif verdict == Verdict.STUB.value:
        reason = "capability is STUB — build it; live control refused"
    elif inv_row.evidence_mode and str(inv_row.evidence_mode).lower() == "replay":
        reason = "PRESENT from replay may authorize documentation only"
    else:
        # Staleness / hash mismatch path — may_authorize already refused.
        reason = "inventory row STALE or fail-closed — re-probe required"
        is_stale = True

    return ControlDecision(
        control_id=cid,
        mode=ControlMode.NAMED_STATE,
        authorized=False,
        cannot_state=ns,
        reason=reason,
        inventory_verdict=verdict,
        is_stale=is_stale,
    )


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------


def render_live_control(
    control_id: str,
    *,
    label: str,
    action: str,
    decision: Optional[ControlDecision] = None,
) -> ControlRender:
    """Emit a real clickable control with a non-empty action target.

    Callers must only invoke this after ``decide_control`` returned LIVE.
    Emitting a live-looking button with a blank / no-op action raises.

    A ``decision`` is **required** — inventing an authorized LIVE decision
    inside this function is forbidden (that was live-control theater: a
    button that looks authorized without the inventory seam).
    """
    cid = str(control_id).strip()
    lab = (label or cid).strip()
    act = (action or "").strip()
    if not act or act.lower() in {"#", "javascript:void(0)", "javascript:;", "noop", "none"}:
        raise DeadControlError(
            "refusing dead control %r — live button requires a real action target, "
            "got %r" % (cid, action)
        )
    if decision is None:
        raise DeadControlError(
            "refusing live render for %r without ControlDecision — call "
            "decide_control / render_control so inventory authorization is not bypassed"
            % cid
        )
    dec = decision
    if dec.mode is not ControlMode.LIVE or not dec.authorized:
        raise DeadControlError(
            "refusing live render for unauthorized control %r (mode=%s)"
            % (cid, dec.mode.value)
        )
    # Reject inventing PRESENT without going through authorization language.
    if not str(dec.inventory_verdict or "").strip():
        raise DeadControlError(
            "refusing live render for %r — ControlDecision.inventory_verdict "
            "required (authorization seam)" % cid
        )

    safe_id = html.escape(cid, quote=True)
    safe_lab = html.escape(lab, quote=False)
    safe_act = html.escape(act, quote=True)
    fragment = (
        '<button type="button" class="%s" data-control="%s" data-action="%s" '
        'data-control-mode="live">%s</button>'
        % (LIVE_CONTROL_CLASS, safe_id, safe_act, safe_lab)
    )
    return ControlRender(
        control_id=cid,
        mode=ControlMode.LIVE,
        html=fragment,
        decision=dec,
        action=act,
        label=lab,
    )


def render_cannot_state(
    control_id: str,
    *,
    decision: Optional[ControlDecision] = None,
    cannot_state: Optional[Union[NamedState, str]] = None,
    reason: str = "",
) -> ControlRender:
    """Render a named cannot-* state with **no** clickable element."""
    cid = str(control_id).strip()
    ns = _coerce_cannot_state(
        cannot_state
        or (decision.cannot_state if decision is not None else None),
        cid,
    )
    dec = decision or ControlDecision(
        control_id=cid,
        mode=ControlMode.NAMED_STATE,
        authorized=False,
        cannot_state=ns,
        reason=reason or "capability absent",
        inventory_verdict="ABSENT",
    )
    state_html = render_state(ns)
    detail = html.escape(dec.reason or reason or "", quote=False)
    fragment = (
        '<div class="%s" data-control="%s" data-control-mode="named_state" '
        'data-cannot-reason="%s">'
        '%s'
        '%s'
        "</div>"
        % (
            CANNOT_STATE_CLASS,
            html.escape(cid, quote=True),
            html.escape(dec.reason or reason or "", quote=True),
            state_html,
            (
                ' <span class="cannot-reason">%s</span>' % detail
                if detail
                else ""
            ),
        )
    )
    # Hard invariant: no button tags in named-state path.
    if re.search(r"<\s*button\b", fragment, re.IGNORECASE):
        raise DeadControlError(
            "named-state render for %r produced a <button> — dead-control contract violated"
            % cid
        )
    return ControlRender(
        control_id=cid,
        mode=ControlMode.NAMED_STATE,
        html=fragment,
        decision=dec,
        action="",
        label=ns.label,
    )


def render_control(
    control_id: str,
    *,
    label: Optional[str] = None,
    action: str = "",
    row: Optional[InventoryRow] = None,
    inventory: Optional[Any] = None,
    root: Optional[Path] = None,
    as_of: Optional[date] = None,
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
    cannot_state: Optional[Union[NamedState, str]] = None,
    force_absent: bool = False,
) -> ControlRender:
    """Decide + render: LIVE button or named cannot-* — never a dead button."""
    dec = decide_control(
        control_id,
        row=row,
        inventory=inventory,
        root=root,
        as_of=as_of,
        head_hash=head_hash,
        content_overrides=content_overrides,
        cannot_state=cannot_state,
        force_absent=force_absent,
    )
    lab = (label or control_id).strip()
    if dec.mode is ControlMode.LIVE:
        act = action.strip() or ("action:%s" % control_id)
        return render_live_control(
            control_id, label=lab, action=act, decision=dec
        )
    return render_cannot_state(
        control_id,
        decision=dec,
        cannot_state=dec.cannot_state or cannot_state,
        reason=dec.reason,
    )


# --------------------------------------------------------------------------
# Dead-control audit (clickable no-ops are build failures)
# --------------------------------------------------------------------------

#: Patterns that mark a clickable element in rendered HTML.
_CLICKABLE_RE = re.compile(
    r"<\s*(button|a)\b([^>]*)>",
    re.IGNORECASE,
)
_DISABLED_RE = re.compile(r"\bdisabled\b", re.IGNORECASE)
_ACTION_RE = re.compile(
    r"""(?:data-action|href|onclick)\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(
    r"""data-control\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_NOOP_ACTIONS = frozenset(
    {
        "",
        "#",
        "javascript:void(0)",
        "javascript:;",
        "noop",
        "none",
        "null",
        "undefined",
    }
)


@dataclass
class DeadControlFinding:
    """One clickable no-op found by the audit."""

    tag: str
    control_id: str
    action: str
    snippet: str
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "control_id": self.control_id,
            "action": self.action,
            "snippet": self.snippet,
            "reason": self.reason,
        }


def audit_dead_controls(html_text: str) -> List[DeadControlFinding]:
    """Scan rendered HTML for clickable no-ops (dead controls).

    A finding is raised for any ``<button>`` / ``<a>`` that:

    * has no real action (blank / # / javascript:void(0) / noop), or
    * carries ``class="dead-control"``, or
    * is disabled while still present as a control affordance for open/run
      (disabled buttons are still "dead controls" under this contract —
      the honest path emits no element at all).

    Live controls with a real ``data-action`` are clean. Named-state
    ``render_state`` spans are never findings.
    """
    if not html_text:
        return []
    findings: List[DeadControlFinding] = []
    for m in _CLICKABLE_RE.finditer(html_text):
        tag = m.group(1).lower()
        attrs = m.group(2) or ""
        snippet = m.group(0)[:200]
        ctrl_m = _CONTROL_RE.search(attrs)
        control_id = ctrl_m.group(1) if ctrl_m else ""
        act_m = _ACTION_RE.search(attrs)
        action = (act_m.group(1).strip() if act_m else "")
        # class=dead-control is always a finding.
        if re.search(r"""class\s*=\s*["'][^"']*\bdead-control\b""", attrs, re.I):
            findings.append(
                DeadControlFinding(
                    tag=tag,
                    control_id=control_id,
                    action=action,
                    snippet=snippet,
                    reason="explicit dead-control class",
                )
            )
            continue
        # Disabled control affordance is still a dead control under this
        # contract (honest path emits zero clickable elements).
        if _DISABLED_RE.search(attrs):
            findings.append(
                DeadControlFinding(
                    tag=tag,
                    control_id=control_id,
                    action=action,
                    snippet=snippet,
                    reason="disabled clickable is a dead control — emit named state instead",
                )
            )
            continue
        # No-op action.
        if action.lower() in _NOOP_ACTIONS:
            # Bare <a> without href/action and without data-control may be
            # decorative; only flag when it looks like a control (has
            # data-control, or is a button, or has onclick/href explicitly).
            has_control_marker = bool(control_id) or bool(act_m) or tag == "button"
            if has_control_marker:
                findings.append(
                    DeadControlFinding(
                        tag=tag,
                        control_id=control_id,
                        action=action,
                        snippet=snippet,
                        reason="clickable no-op action %r" % (action,),
                    )
                )
    return findings


def assert_no_dead_controls(html_text: str) -> None:
    """Raise :class:`DeadControlAuditError` if any clickable no-op is present."""
    findings = audit_dead_controls(html_text)
    if findings:
        parts = [
            "%s#%s (%s)" % (f.tag, f.control_id or "?", f.reason) for f in findings
        ]
        raise DeadControlAuditError(
            "dead-control audit found %d clickable no-op(s): %s"
            % (len(findings), "; ".join(parts))
        )


def count_live_controls(html_text: str, control_id: Optional[str] = None) -> int:
    """Count live-control buttons, optionally filtered by control id."""
    if not html_text:
        return 0
    pattern = (
        r'<\s*button\b[^>]*\bclass="[^"]*\b%s\b[^"]*"[^>]*data-control="%s"'
        % (re.escape(LIVE_CONTROL_CLASS), re.escape(control_id))
        if control_id
        else r'<\s*button\b[^>]*\bclass="[^"]*\b%s\b' % re.escape(LIVE_CONTROL_CLASS)
    )
    return len(re.findall(pattern, html_text, flags=re.IGNORECASE))


def count_cannot_states(html_text: str, control_id: Optional[str] = None) -> int:
    """Count cannot-state containers, optionally filtered by control id."""
    if not html_text:
        return 0
    if control_id:
        pattern = (
            r'class="%s"[^>]*data-control="%s"'
            % (re.escape(CANNOT_STATE_CLASS), re.escape(control_id))
        )
    else:
        pattern = r'class="%s"' % re.escape(CANNOT_STATE_CLASS)
    return len(re.findall(pattern, html_text, flags=re.IGNORECASE))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _coerce_cannot_state(
    value: Optional[Union[NamedState, str]],
    control_id: str,
) -> NamedState:
    if isinstance(value, NamedState):
        return value
    if value is not None and str(value).strip():
        key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        try:
            return NamedState(key)
        except ValueError:
            pass
    return DEFAULT_CANNOT_STATE.get(control_id, NamedState.cannot_run)


__all__ = [
    "CONTROL_OPEN",
    "CONTROL_RUN",
    "CONTROL_RETRY",
    "CONTROL_RESTART",
    "CONTROL_DIAGNOSE",
    "DEFAULT_CANNOT_STATE",
    "LIVE_CONTROL_CLASS",
    "CANNOT_STATE_CLASS",
    "DEAD_CONTROL_CLASS",
    "ControlMode",
    "DeadControlError",
    "DeadControlAuditError",
    "ControlDecision",
    "ControlRender",
    "DeadControlFinding",
    "load_inventory_row",
    "decide_control",
    "render_live_control",
    "render_cannot_state",
    "render_control",
    "audit_dead_controls",
    "assert_no_dead_controls",
    "count_live_controls",
    "count_cannot_states",
]

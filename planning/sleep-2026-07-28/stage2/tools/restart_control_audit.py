"""Restart-control audit — W17, Phase 3.

Scans rendered HTML **per restart context** and asserts:

* live restart control count == 1 when the context offers a live control, or
* live restart control count == 0 with a named cannot_restart state when
  restart is not possible

A context that currently renders both a bare ``Restart`` and a
``Restart session`` control **fails** naming the context and both controls
(frozen plan GWT).

Cross-context unification is out of scope — this audit only enforces
**inside** each context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from anchor.session.restart import (
    CONTROL_ID_BY_CONTEXT,
    CONTROL_LABEL_BY_CONTEXT,
    RESTART_CONTEXT_IDS,
    SCOPE_NAME_BY_CONTEXT,
    normalize_context_id,
)
from anchor.ui.dead_control import (
    CANNOT_STATE_CLASS,
    LIVE_CONTROL_CLASS,
    audit_dead_controls,
)

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

WAVE_ID = "W17"
SURFACE_ID = "restart"

#: data-attribute used on context containers and controls.
DATA_RESTART_CONTEXT = "data-restart-context"
DATA_CONTROL = "data-control"
DATA_SCOPE_NAME = "data-scope-name"
DATA_CONTRACT = "data-contract-line"

#: Labels that count as restart affordances (case-insensitive).
_RESTART_LABEL_RE = re.compile(
    r"\bRestart(?:\s+(?:run|session|engine|workbench))?\b",
    re.IGNORECASE,
)

_BUTTON_RE = re.compile(
    r"<\s*button\b([^>]*)>(.*?)</\s*button\s*>",
    re.IGNORECASE | re.DOTALL,
)
_CONTEXT_BLOCK_RE = re.compile(
    r'<\s*(?:section|div)\b([^>]*\bdata-restart-context\s*=\s*["\']([^"\']+)["\'][^>]*)>'
    r"(.*?)"
    r"</\s*(?:section|div)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:]*)\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)
_CANNOT_RE = re.compile(
    r'class\s*=\s*["\'][^"\']*\b%s\b[^"\']*["\']' % re.escape(CANNOT_STATE_CLASS),
    re.IGNORECASE,
)
_LIVE_RE = re.compile(
    r'class\s*=\s*["\'][^"\']*\b%s\b[^"\']*["\']' % re.escape(LIVE_CONTROL_CLASS),
    re.IGNORECASE,
)


class DualRestartControlError(AssertionError):
    """A context rendered more than one restart control."""

    def __init__(self, message: str, *, context_id: str = "", controls: Optional[Sequence[str]] = None):
        super().__init__(message)
        self.message = message
        self.context_id = context_id
        self.controls = list(controls or ())


class RestartControlAuditError(AssertionError):
    """Generic restart-control audit failure."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class RestartControlHit:
    """One restart control (or cannot-state) found in HTML."""

    context_id: str
    control_id: str
    label: str
    kind: str  # "live" | "cannot" | "ambiguous"
    snippet: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "control_id": self.control_id,
            "label": self.label,
            "kind": self.kind,
            "snippet": self.snippet,
        }


@dataclass
class ContextAuditResult:
    """Audit outcome for one restart context."""

    context_id: str
    live_controls: List[RestartControlHit] = field(default_factory=list)
    cannot_states: List[RestartControlHit] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def live_count(self) -> int:
        return len(self.live_controls)

    @property
    def cannot_count(self) -> int:
        return len(self.cannot_states)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "live_count": self.live_count,
            "cannot_count": self.cannot_count,
            "live_controls": [h.as_dict() for h in self.live_controls],
            "cannot_states": [h.as_dict() for h in self.cannot_states],
            "errors": list(self.errors),
            "ok": self.ok,
        }


@dataclass
class RestartAuditReport:
    """Full multi-context audit report."""

    contexts: Dict[str, ContextAuditResult] = field(default_factory=dict)
    dead_control_findings: List[Any] = field(default_factory=list)
    ok: bool = True
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "contexts": {k: v.as_dict() for k, v in self.contexts.items()},
            "dead_control_findings": list(self.dead_control_findings),
        }


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------


def _parse_attrs(attr_blob: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in _ATTR_RE.finditer(attr_blob or ""):
        out[m.group(1).lower()] = m.group(2)
    return out


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _context_from_control_id(control_id: str) -> str:
    raw = (control_id or "").strip().lower()
    for ctx, cid in CONTROL_ID_BY_CONTEXT.items():
        if raw == cid or raw == "restart_%s" % ctx:
            return ctx
    if raw.startswith("restart_"):
        try:
            return normalize_context_id(raw[len("restart_") :])
        except ValueError:
            return ""
    return ""


def _label_matches_restart(label: str) -> bool:
    return bool(_RESTART_LABEL_RE.search(label or ""))


# --------------------------------------------------------------------------
# Collect hits
# --------------------------------------------------------------------------


def find_restart_controls(
    html_text: str,
    *,
    context_id: Optional[str] = None,
) -> List[RestartControlHit]:
    """Find live restart controls (buttons) in rendered HTML.

    When *context_id* is set, only hits for that context are returned.
    """
    if not html_text:
        return []
    want = normalize_context_id(context_id) if context_id else None
    hits: List[RestartControlHit] = []

    for m in _BUTTON_RE.finditer(html_text):
        attrs = _parse_attrs(m.group(1) or "")
        label = _strip_tags(m.group(2) or "")
        control_id = attrs.get("data-control", "")
        ctx_attr = attrs.get("data-restart-context", "")
        is_live = bool(_LIVE_RE.search(m.group(1) or "")) or (
            "live-control" in (attrs.get("class") or "")
        )
        looks_restart = (
            control_id.startswith("restart")
            or bool(ctx_attr)
            or _label_matches_restart(label)
        )
        if not looks_restart:
            continue
        ctx = (
            ctx_attr
            or _context_from_control_id(control_id)
            or ""
        )
        if ctx:
            try:
                ctx = normalize_context_id(ctx)
            except ValueError:
                ctx = ctx_attr or ctx
        if want is not None and ctx != want:
            # Also accept unlabeled dual 'Restart' buttons inside a
            # filtered scan of a context block (handled elsewhere).
            if not (want and not ctx and _label_matches_restart(label)):
                continue
            if not ctx:
                ctx = want
        kind = "live" if is_live else "ambiguous"
        hits.append(
            RestartControlHit(
                context_id=ctx or (want or ""),
                control_id=control_id or "(unmarked)",
                label=label or control_id or "(no label)",
                kind=kind,
                snippet=m.group(0)[:200],
            )
        )
    return hits


def find_cannot_restart_states(
    html_text: str,
    *,
    context_id: Optional[str] = None,
) -> List[RestartControlHit]:
    """Find named cannot_restart / cannot-state containers for restart."""
    if not html_text:
        return []
    want = normalize_context_id(context_id) if context_id else None
    hits: List[RestartControlHit] = []
    # Match cannot-state divs with data-control restart_* or data-restart-context.
    pattern = re.compile(
        r'<\s*div\b([^>]*\bclass\s*=\s*["\'][^"\']*\b%s\b[^"\']*["\'][^>]*)>'
        r"(.*?)"
        r"</\s*div\s*>" % re.escape(CANNOT_STATE_CLASS),
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(html_text):
        attrs = _parse_attrs(m.group(1) or "")
        control_id = attrs.get("data-control", "")
        ctx_attr = attrs.get("data-restart-context", "")
        ctx = ctx_attr or _context_from_control_id(control_id)
        if ctx:
            try:
                ctx = normalize_context_id(ctx)
            except ValueError:
                pass
        if not (control_id.startswith("restart") or ctx_attr or "cannot_restart" in (m.group(0) or "")):
            # Only count restart-related cannot states.
            if "restart" not in control_id and not ctx_attr:
                continue
        if want is not None and ctx != want:
            continue
        hits.append(
            RestartControlHit(
                context_id=ctx or (want or ""),
                control_id=control_id or "(cannot)",
                label=_strip_tags(m.group(2) or "")[:80],
                kind="cannot",
                snippet=m.group(0)[:200],
            )
        )
    return hits


def extract_context_html(html_text: str, context_id: str) -> str:
    """Return the inner HTML of the first block tagged with this context.

    Falls back to the full document when no tagged block is found (so a
    dual-control page that forgot containers is still audited).
    """
    cid = normalize_context_id(context_id)
    for m in _CONTEXT_BLOCK_RE.finditer(html_text or ""):
        raw_ctx = (m.group(2) or "").strip()
        try:
            if normalize_context_id(raw_ctx) == cid:
                return m.group(0)
        except ValueError:
            if raw_ctx == cid:
                return m.group(0)
    return html_text or ""


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------


def audit_context(
    html_text: str,
    context_id: str,
    *,
    expect_live: Optional[bool] = None,
) -> ContextAuditResult:
    """Audit one context: live control count must be 0 or 1, never 2+.

    When ``expect_live`` is True, requires exactly one live control.
    When ``expect_live`` is False, requires zero live controls and at least
    one cannot_restart state.
    When ``expect_live`` is None, enforces only the dual-control ban and
    that live_count ∈ {0, 1}.
    """
    cid = normalize_context_id(context_id)
    block = extract_context_html(html_text, cid)
    live = [
        h
        for h in find_restart_controls(block, context_id=cid)
        if h.kind in ("live", "ambiguous")
    ]
    # Also catch unlabeled dual 'Restart' buttons inside the context block.
    if block is not html_text:
        for h in find_restart_controls(block):
            if h not in live and (h.context_id in ("", cid) or not h.context_id):
                if _label_matches_restart(h.label) or h.control_id.startswith("restart"):
                    live.append(h)
    cannot = find_cannot_restart_states(block, context_id=cid)
    # Fallback: scan cannot states that mention this control id.
    if not cannot:
        control_id = CONTROL_ID_BY_CONTEXT[cid]
        for h in find_cannot_restart_states(html_text):
            if h.control_id == control_id or h.context_id == cid:
                cannot.append(h)

    result = ContextAuditResult(
        context_id=cid,
        live_controls=live,
        cannot_states=cannot,
    )

    if len(live) > 1:
        labels = [h.label for h in live]
        msg = (
            "restart context %r renders %d restart controls (exactly one allowed): %s"
            % (cid, len(live), ", ".join(repr(x) for x in labels))
        )
        result.errors.append(msg)
    if expect_live is True and len(live) != 1:
        result.errors.append(
            "restart context %r expected exactly 1 live control, found %d"
            % (cid, len(live))
        )
    if expect_live is False:
        if len(live) != 0:
            result.errors.append(
                "restart context %r expected 0 live controls (cannot-restart), found %d"
                % (cid, len(live))
            )
        if len(cannot) < 1:
            result.errors.append(
                "restart context %r expected a named cannot_restart state, found none"
                % cid
            )
    return result


def audit_restart_controls(
    html_text: str,
    *,
    contexts: Optional[Sequence[str]] = None,
    expect_live: Optional[Dict[str, bool]] = None,
    raise_on_error: bool = True,
) -> RestartAuditReport:
    """Scan rendered HTML per context; assert control count == 1 (or 0+cannot).

    Raises :class:`DualRestartControlError` when any context has two or more
    restart controls (GWT: dual 'Restart' + 'Restart session').
    """
    ctxs = list(contexts) if contexts is not None else list(RESTART_CONTEXT_IDS)
    report = RestartAuditReport()
    report.dead_control_findings = audit_dead_controls(html_text or "")

    for raw in ctxs:
        cid = normalize_context_id(raw)
        exp = None
        if expect_live is not None and cid in expect_live:
            exp = expect_live[cid]
        result = audit_context(html_text or "", cid, expect_live=exp)
        report.contexts[cid] = result
        if not result.ok:
            report.ok = False
            report.errors.extend(result.errors)
            # Dual-control is the named GWT failure.
            if result.live_count > 1:
                labels = [h.label for h in result.live_controls]
                raise DualRestartControlError(
                    "restart_control_audit failed for context %r — dual (or more) "
                    "restart controls present: %s"
                    % (cid, ", ".join(repr(x) for x in labels)),
                    context_id=cid,
                    controls=labels,
                )

    if report.dead_control_findings:
        report.ok = False
        report.errors.append(
            "dead-control findings: %d" % len(report.dead_control_findings)
        )

    if raise_on_error and not report.ok:
        # Prefer dual error already raised; otherwise generic.
        raise RestartControlAuditError(
            "restart_control_audit failed: %s" % "; ".join(report.errors)
        )
    return report


def assert_exactly_one_control(
    html_text: str,
    context_id: str,
) -> ContextAuditResult:
    """Assert live restart control count == 1 for *context_id*."""
    result = audit_context(html_text, context_id, expect_live=True)
    if not result.ok:
        if result.live_count > 1:
            labels = [h.label for h in result.live_controls]
            raise DualRestartControlError(
                "context %r has %d restart controls: %s"
                % (context_id, result.live_count, labels),
                context_id=normalize_context_id(context_id),
                controls=labels,
            )
        raise RestartControlAuditError("; ".join(result.errors))
    return result


def assert_cannot_restart_only(
    html_text: str,
    context_id: str,
) -> ContextAuditResult:
    """Assert zero live controls + named cannot_restart for *context_id*."""
    result = audit_context(html_text, context_id, expect_live=False)
    if not result.ok:
        raise RestartControlAuditError("; ".join(result.errors))
    return result


def dual_control_violation_html(context_id: str = "session") -> str:
    """Fixture HTML that renders both 'Restart' and 'Restart session'.

    The audit **must** fail naming the context and both controls.
    """
    cid = normalize_context_id(context_id)
    scope = SCOPE_NAME_BY_CONTEXT[cid]
    control_id = CONTROL_ID_BY_CONTEXT[cid]
    # Deliberate dual affordance — production render never emits this.
    return (
        "<!DOCTYPE html><html><body>"
        '<section data-restart-context="%s" data-surface="restart">'
        '<button type="button" class="%s" data-control="%s" '
        'data-restart-context="%s" data-action="action:restart">Restart</button>'
        '<button type="button" class="%s" data-control="%s" '
        'data-restart-context="%s" data-action="action:restart_session">'
        "%s</button>"
        "</section>"
        "</body></html>"
        % (
            cid,
            LIVE_CONTROL_CLASS,
            control_id,
            cid,
            LIVE_CONTROL_CLASS,
            control_id,
            cid,
            scope,
        )
    )


__all__ = [
    "WAVE_ID",
    "SURFACE_ID",
    "DATA_RESTART_CONTEXT",
    "DATA_CONTROL",
    "DATA_SCOPE_NAME",
    "DATA_CONTRACT",
    "DualRestartControlError",
    "RestartControlAuditError",
    "RestartControlHit",
    "ContextAuditResult",
    "RestartAuditReport",
    "find_restart_controls",
    "find_cannot_restart_states",
    "extract_context_html",
    "audit_context",
    "audit_restart_controls",
    "assert_exactly_one_control",
    "assert_cannot_restart_only",
    "dual_control_violation_html",
]

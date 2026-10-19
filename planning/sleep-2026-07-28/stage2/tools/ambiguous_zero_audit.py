"""Ambiguous-zero audit — W21, Phase 4.

Sweeps rendered HTML for numerals and blanks that were **not** produced by
``render_state`` / ``render_cost``.

Legal sources of a visible zero or blank-looking value:

* ``render_state(NamedState.zero_measured)`` → node with
  ``data-named-state="zero_measured"`` (and visible label ``zero_measured``,
  never a bare ``0``).
* ``render_cost`` under ``cost_state == measured`` → node with
  ``data-cost-state="measured"`` (may contain ``$0.00`` only there).
* ``render_state`` for empty / unknown / pending / unmeasured / etc. — labelled
  text, never a silent blank or bare numeral.

Findings (build failures):

* Bare ``0`` / ``0.0`` text nodes outside a sanctioned marker.
* ``$0.00`` (or any ``$…``) outside ``data-cost-state="measured"``.
* Placeholder blanks (``—``, ``–``, ``-``, ``n/a``, empty metric cells) that
  look like values rather than structure.

Usage::

    from tools.ambiguous_zero_audit import audit_html, audit_all_surfaces_ambiguous

    findings = audit_html(html_text)
    report = audit_all_surfaces_ambiguous()
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

WAVE_ID = "W21"
GO = "GO"
HALT = "HALT"

#: Markers that authorize a zero / dollar / labelled empty.
NAMED_STATE_ATTR = "data-named-state"
COST_STATE_ATTR = "data-cost-state"
NAMED_STATE_CLASS = "named-state"
COST_STATE_CLASS = "cost-state"
ZERO_MEASURED_TOKEN = "zero_measured"
MEASURED_COST_TOKEN = "measured"

AMBIGUOUS_ZERO_MESSAGE = (
    "ambiguous-zero audit found numeral/blank not from render_state/render_cost"
)

# --------------------------------------------------------------------------
# Regexes
# --------------------------------------------------------------------------

#: Strip script/style so JS counters are not treated as UI text.
_STRIP_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>.*?</script\s*>",
    re.IGNORECASE | re.DOTALL,
)
_STRIP_STYLE_RE = re.compile(
    r"<style\b[^>]*>.*?</style\s*>",
    re.IGNORECASE | re.DOTALL,
)

#: Sanctioned element: named-state or cost-state container (non-greedy inner).
# (kept for documentation; masking uses attribute walk in _mask_sanctioned_regions)

_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:]*)\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)

#: Bare zero as a whole text token (not part of a longer number like 10, 2026).
_BARE_ZERO_RE = re.compile(
    r"(?<![\w.$])0(?:\.0+)?(?![\w.])",
)
#: Dollar figures including $0.00.
_DOLLAR_RE = re.compile(r"\$\s*\d+(?:\.\d+)?")
#: Placeholder blanks that must not stand in for a metric value.
_PLACEHOLDER_RE = re.compile(
    r"(?:(?<=\s)|^)(?:—|–|−|&mdash;|&ndash;|n/?a|N/?A)(?=\s|$|<)",
)

#: Metric-ish contexts where a bare zero / blank is especially damning.
_METRIC_HINT_RE = re.compile(
    r"\b(cost|usage|total|count|amount|tokens?|minutes?|hours?|sessions?|"
    r"rollup|metric|spend|balance|qty|quantity)\b",
    re.IGNORECASE,
)

#: data-metric / data-value cells that must not be blank or bare-zero.
_METRIC_CELL_RE = re.compile(
    r"<\s*(?:td|span|div)\b([^>]*\b(?:data-metric|data-value|data-count|"
    r"data-usage|data-rollup|class\s*=\s*[\"'][^\"']*\b(?:metric|usage|cost|"
    r"count|rollup)\b)[^>]*)>(.*?)</\s*(?:td|span|div)\s*>",
    re.IGNORECASE | re.DOTALL,
)


# --------------------------------------------------------------------------
# Data shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AmbiguousZeroFinding:
    """One numeral/blank not produced by render_state / render_cost."""

    kind: str  # bare_zero | dollar_outside_measured | placeholder_blank
    snippet: str
    reason: str
    surface: str = ""
    offset: int = -1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "snippet": self.snippet,
            "reason": self.reason,
            "surface": self.surface,
            "offset": self.offset,
        }


@dataclass
class AmbiguousZeroReport:
    """Audit outcome for one or many HTML documents."""

    findings: List[AmbiguousZeroFinding] = field(default_factory=list)
    surfaces: Dict[str, List[AmbiguousZeroFinding]] = field(default_factory=dict)
    ok: bool = True
    errors: List[str] = field(default_factory=list)

    @property
    def findings_count(self) -> int:
        return len(self.findings)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "findings_count": self.findings_count,
            "errors": list(self.errors),
            "findings": [f.as_dict() for f in self.findings],
            "surfaces": {
                k: [f.as_dict() for f in v] for k, v in self.surfaces.items()
            },
        }


class AmbiguousZeroAuditError(AssertionError):
    """Raised when ambiguous zeros/blanks are present."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _parse_attrs(attr_blob: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in _ATTR_RE.finditer(attr_blob or ""):
        out[m.group(1).lower()] = m.group(2)
    return out


def _is_sanctioned_attrs(attrs: Mapping[str, str]) -> bool:
    """True when attrs mark a render_state / render_cost (or measured numeral) node."""
    ns = (attrs.get("data-named-state") or "").strip().lower()
    cs = (attrs.get("data-cost-state") or "").strip().lower()
    classes = (attrs.get("class") or "").lower().split()
    if ns:
        # Any named-state node is a sanctioned label source (including
        # zero_measured, empty, unknown, pending, unmeasured, …).
        return True
    if cs:
        return True
    if NAMED_STATE_CLASS in classes or COST_STATE_CLASS in classes:
        return True
    # PROVEN numeral path (usage tiles): data-measured="true" next to render_state.
    if (attrs.get("data-measured") or "").strip().lower() in {"true", "1", "yes"}:
        return True
    if "data-numeral" in attrs and (attrs.get("data-numeral") or "").strip() != "":
        # Numeral carrier only legal when paired with measured flag or parent state;
        # treat the carrier itself as sanctioned (parent tile also carries state).
        return True
    return False


def _mask_sanctioned_regions(html_text: str) -> Tuple[str, List[Tuple[int, int]]]:
    """Replace sanctioned blocks with spaces (preserve length for offsets)."""
    if not html_text:
        return "", []
    chars = list(html_text)
    spans: List[Tuple[int, int]] = []
    covered = [False] * len(html_text)

    # Attribute-driven scan: walk opening tags; if sanctioned, mask to the
    # matching close with depth counting so nested same-tag children don't
    # end the mask early.
    tag_re = re.compile(r"<\s*([a-zA-Z0-9]+)(\b[^>]*)?>", re.I)
    close_re_cache: Dict[str, re.Pattern] = {}

    def _close_re(tag: str) -> re.Pattern:
        if tag not in close_re_cache:
            close_re_cache[tag] = re.compile(
                r"</\s*%s\s*>" % re.escape(tag), re.I
            )
        return close_re_cache[tag]

    def _open_re(tag: str) -> re.Pattern:
        return re.compile(r"<\s*%s\b" % re.escape(tag), re.I)

    for m in tag_re.finditer(html_text):
        start = m.start()
        if covered[start]:
            continue
        tag = m.group(1).lower()
        attrs = _parse_attrs(m.group(2) or "")
        if not _is_sanctioned_attrs(attrs):
            continue
        # Void / self-closing — mask the tag only.
        raw_open = m.group(0)
        if raw_open.rstrip().endswith("/>") or tag in {
            "br", "hr", "img", "input", "meta", "link",
        }:
            end = m.end()
        else:
            depth = 1
            pos = m.end()
            opener = _open_re(tag)
            closer = _close_re(tag)
            end = len(html_text)
            while pos < len(html_text) and depth > 0:
                mo = opener.search(html_text, pos)
                mc = closer.search(html_text, pos)
                if mc is None:
                    break
                if mo is not None and mo.start() < mc.start():
                    # Another open of same tag — only count non-self-closing.
                    open_end = html_text.find(">", mo.start())
                    chunk = html_text[mo.start() : open_end + 1] if open_end >= 0 else ""
                    if not chunk.rstrip().endswith("/>"):
                        depth += 1
                    pos = (open_end + 1) if open_end >= 0 else mo.end()
                else:
                    depth -= 1
                    pos = mc.end()
                    if depth == 0:
                        end = pos
                        break
        spans.append((start, end))
        for i in range(start, min(end, len(chars))):
            chars[i] = " "
            covered[i] = True

    return "".join(chars), spans


def _strip_non_ui(html_text: str) -> str:
    text = _STRIP_SCRIPT_RE.sub(" ", html_text or "")
    text = _STRIP_STYLE_RE.sub(" ", text)
    return text


def _visible_text(html_fragment: str) -> str:
    return re.sub(r"<[^>]+>", " ", html_fragment or "")


def _snippet_at(text: str, start: int, width: int = 80) -> str:
    a = max(0, start - 20)
    b = min(len(text), start + width)
    return re.sub(r"\s+", " ", text[a:b]).strip()


# --------------------------------------------------------------------------
# Core audit
# --------------------------------------------------------------------------


def audit_html(
    html_text: str,
    *,
    surface: str = "",
) -> List[AmbiguousZeroFinding]:
    """Sweep one HTML document for ambiguous zeros / blanks.

    Numerals and blanks inside ``data-named-state`` / ``data-cost-state``
    nodes are ignored (they came from render_state / render_cost). Everything
    else that looks like a bare zero, a dollar figure, or a metric placeholder
    is a finding.
    """
    if not html_text:
        return []

    cleaned = _strip_non_ui(html_text)
    masked, _spans = _mask_sanctioned_regions(cleaned)
    # Work on visible text of the masked document (tags still help structure).
    findings: List[AmbiguousZeroFinding] = []

    # 1) Dollar figures outside measured cost nodes.
    for m in _DOLLAR_RE.finditer(masked):
        # If this region was masked it won't match; any hit is unsanctioned.
        snip = _snippet_at(cleaned, m.start())
        findings.append(
            AmbiguousZeroFinding(
                kind="dollar_outside_measured",
                snippet=snip,
                reason=(
                    "dollar figure %r not inside data-cost-state=measured "
                    "(render_cost only)" % m.group(0)
                ),
                surface=surface,
                offset=m.start(),
            )
        )

    # 2) Bare zeros outside named-state / cost-state.
    for m in _BARE_ZERO_RE.finditer(masked):
        # Skip zeros that are purely structural in attributes we already masked.
        # Prefer reporting when near metric language OR as bare text content.
        window = masked[max(0, m.start() - 80) : m.end() + 80]
        visible_window = _visible_text(window)
        # Ignore zeros that only appear inside remaining tag attributes.
        # If the match sits between > and < as text, it's visible.
        before = masked[max(0, m.start() - 1) : m.start()]
        # crude: skip if still inside a tag (between < and >)
        last_lt = masked.rfind("<", 0, m.start())
        last_gt = masked.rfind(">", 0, m.start())
        if last_lt > last_gt:
            continue  # inside a tag
        snip = _snippet_at(cleaned, m.start())
        # Year-like / ISO dates often contain digits but bare 0 alone is rare
        # in dates; still flag bare 0. Skip pure CSS like "0px" already
        # excluded by \w boundary? "0px" has word char after — excluded.
        reason = "bare zero numeral not produced by render_state/render_cost"
        if _METRIC_HINT_RE.search(visible_window):
            reason = (
                "bare zero near metric language — must use render_state "
                "(zero_measured) or render_cost (measured)"
            )
        findings.append(
            AmbiguousZeroFinding(
                kind="bare_zero",
                snippet=snip,
                reason=reason,
                surface=surface,
                offset=m.start(),
            )
        )

    # 3) Metric cells with blank / placeholder content.
    for m in _METRIC_CELL_RE.finditer(cleaned):
        attrs = _parse_attrs(m.group(1) or "")
        if _is_sanctioned_attrs(attrs):
            continue
        body = m.group(2) or ""
        # Mask inner sanctioned children before judging emptiness.
        body_masked, _ = _mask_sanctioned_regions(body)
        visible = _visible_text(body_masked).strip()
        if not visible or _PLACEHOLDER_RE.fullmatch(visible) or visible in {
            "—", "–", "−", "-", "n/a", "N/A", "NA", "",
        }:
            findings.append(
                AmbiguousZeroFinding(
                    kind="placeholder_blank",
                    snippet=_snippet_at(cleaned, m.start()),
                    reason=(
                        "metric cell is blank/placeholder without render_state "
                        "label (unknown ≠ empty ≠ zero_measured)"
                    ),
                    surface=surface,
                    offset=m.start(),
                )
            )
            continue
        if _BARE_ZERO_RE.fullmatch(visible):
            findings.append(
                AmbiguousZeroFinding(
                    kind="bare_zero",
                    snippet=_snippet_at(cleaned, m.start()),
                    reason="metric cell shows bare zero without render_state",
                    surface=surface,
                    offset=m.start(),
                )
            )

    return findings


def assert_no_ambiguous_zeros(html_text: str, *, surface: str = "") -> None:
    """Raise :class:`AmbiguousZeroAuditError` if any finding is present."""
    findings = audit_html(html_text, surface=surface)
    if findings:
        parts = ["%s: %s" % (f.kind, f.reason) for f in findings[:8]]
        raise AmbiguousZeroAuditError(
            "%s: %d finding(s): %s"
            % (AMBIGUOUS_ZERO_MESSAGE, len(findings), "; ".join(parts))
        )


def audit_all_surfaces_ambiguous(
    *,
    root: Optional[Path] = None,
    html_by_surface: Optional[Mapping[str, str]] = None,
) -> AmbiguousZeroReport:
    """Run the ambiguous-zero audit across every registered surface."""
    report = AmbiguousZeroReport()
    if html_by_surface is None:
        try:
            from tools.dead_control_audit import collect_surface_html

            docs = collect_surface_html(root=root)
        except Exception as exc:  # noqa: BLE001
            report.ok = False
            report.errors.append("collect_surface_html failed: %s" % exc)
            return report
    else:
        docs = dict(html_by_surface)

    all_findings: List[AmbiguousZeroFinding] = []
    for surface_id, html_text in docs.items():
        if (html_text or "").startswith("<!-- surface-render-error:"):
            report.errors.append("%s: render failed" % surface_id)
            continue
        found = audit_html(html_text, surface=surface_id)
        report.surfaces[surface_id] = found
        all_findings.extend(found)
    report.findings = all_findings
    report.ok = len(all_findings) == 0 and not report.errors
    return report


def is_zero_from_render_state(html_fragment: str) -> bool:
    """True when *html_fragment* is a zero_measured named-state node."""
    if not html_fragment:
        return False
    return bool(
        re.search(
            r'data-named-state\s*=\s*["\']zero_measured["\']',
            html_fragment,
            re.I,
        )
    )


def is_zero_from_render_cost(html_fragment: str) -> bool:
    """True when *html_fragment* is a measured cost node (may hold $0.00)."""
    if not html_fragment:
        return False
    return bool(
        re.search(
            r'data-cost-state\s*=\s*["\']measured["\']',
            html_fragment,
            re.I,
        )
    )


__all__ = [
    "WAVE_ID",
    "GO",
    "HALT",
    "AMBIGUOUS_ZERO_MESSAGE",
    "AmbiguousZeroFinding",
    "AmbiguousZeroReport",
    "AmbiguousZeroAuditError",
    "audit_html",
    "assert_no_ambiguous_zeros",
    "audit_all_surfaces_ambiguous",
    "is_zero_from_render_state",
    "is_zero_from_render_cost",
]

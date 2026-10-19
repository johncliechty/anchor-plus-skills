"""Tri-state conformance harness — W8.

Parameterized harness that drives a surface through **unknown**, **empty**,
and **zero_measured** fixtures and asserts three **distinct** visible text
nodes. Surfaces that collapse unknown into empty (or either into a measured
zero) fail by name, with the offending render call site.

Surface waves instantiate this harness rather than hand-writing per-wave
assertions — a shared harness cannot be written to pass only the surface it
was authored against.

Usage::

    from tests.conformance.tri_state import assert_tri_state, run_tri_state

    def render(fixture: str) -> str:
        # return generate_html / surface HTML for the fixture name
        ...

    assert_tri_state(render, call_site="anchor.ui.doctor_view.render")
"""
from __future__ import annotations

import re
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from anchor.ui.named_state import NamedState, render_state

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

#: The three fixtures every surface must distinguish.
TRI_STATE_FIXTURES: Tuple[str, ...] = ("unknown", "empty", "zero_measured")

#: Alias accepted for the measured-zero fixture.
ZERO_ALIASES: frozenset = frozenset({"zero", "zero_measured", "measured_zero"})

_VISIBLE_RE = re.compile(r">([^<]*)</")


class TriStateCollapseError(AssertionError):
    """Raised when a surface collapses two or more tri-state fixtures."""

    def __init__(
        self,
        message: str,
        *,
        collapsed_pair: Optional[Tuple[str, str]] = None,
        call_site: Optional[str] = None,
        rendered: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.collapsed_pair = collapsed_pair
        self.call_site = call_site
        self.rendered = dict(rendered) if rendered else None


@dataclass
class TriStateResult:
    """Outcome of one harness run."""

    ok: bool
    labels: Dict[str, str] = field(default_factory=dict)
    rendered: Dict[str, str] = field(default_factory=dict)
    call_site: Optional[str] = None
    error: Optional[str] = None
    collapsed_pair: Optional[Tuple[str, str]] = None


# --------------------------------------------------------------------------
# Visible-text extraction (shared with html_assert; kept local to avoid cycle)
# --------------------------------------------------------------------------


def _visible_labels_from_html(html: str) -> List[str]:
    """Collect non-empty text nodes that look like named-state labels."""
    if not html:
        return []
    # Prefer data-named-state spans (render_state output).
    spans = re.findall(
        r'data-named-state="([^"]+)"[^>]*>([^<]*)</',
        html,
        flags=re.IGNORECASE,
    )
    if spans:
        return [text.strip() or token for token, text in spans if (text or token).strip()]
    # Fallback: any tag text nodes.
    texts = []
    for m in _VISIBLE_RE.finditer(html):
        t = m.group(1).strip()
        if t:
            texts.append(t)
    if texts:
        return texts
    # Last resort: strip tags.
    stripped = re.sub(r"<[^>]+>", " ", html)
    parts = [p for p in stripped.split() if p]
    return parts


def _primary_label(html: str, fixture: str) -> str:
    """Pick the primary visible label for a fixture's render output."""
    labels = _visible_labels_from_html(html)
    if not labels:
        # Bare text body
        stripped = re.sub(r"<[^>]+>", " ", html or "").strip()
        if not stripped:
            return ""
        return stripped.split()[0]
    # Prefer a label matching the fixture token if present.
    for lab in labels:
        if lab == fixture or lab.replace("-", "_") == fixture:
            return lab
    return labels[0]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def default_fixture_state(name: str) -> NamedState:
    """Map a fixture name to its NamedState."""
    key = (name or "").strip().lower().replace("-", "_")
    if key in ZERO_ALIASES:
        return NamedState.zero_measured
    if key == "unknown":
        return NamedState.unknown
    if key == "empty":
        return NamedState.empty
    raise ValueError("unknown tri-state fixture %r — expected one of %s" % (name, TRI_STATE_FIXTURES))


def default_render(fixture: str) -> str:
    """Default surface: render_state for the fixture (always distinct)."""
    return render_state(default_fixture_state(fixture))


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

SurfaceRender = Callable[[str], str]


def run_tri_state(
    surface: SurfaceRender,
    *,
    fixtures: Sequence[str] = TRI_STATE_FIXTURES,
    call_site: Optional[str] = None,
) -> TriStateResult:
    """Drive ``surface`` through each fixture; return labels without raising.

    ``surface`` is called as ``surface(fixture_name)`` and must return an HTML
    (or text) string. Collapsed pairs are reported on the result; use
    :func:`assert_tri_state` to raise.
    """
    if call_site is None:
        # Best-effort call site from the caller's stack (basename only —
        # never an absolute host path in the failure string).
        try:
            frame = traceback.extract_stack(limit=3)[0]
            base = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            call_site = "%s:%s in %s" % (base, frame.lineno, frame.name)
        except Exception:
            call_site = "<unknown call site>"

    rendered: Dict[str, str] = {}
    labels: Dict[str, str] = {}
    normalized = []
    for raw in fixtures:
        key = raw.strip().lower().replace("-", "_")
        if key in ZERO_ALIASES:
            key = "zero_measured"
        normalized.append(key)
        try:
            html = surface(raw if raw in ("unknown", "empty", "zero_measured", "zero") else key)
        except TypeError:
            html = surface(key)
        if html is None:
            html = ""
        html = str(html)
        rendered[key] = html
        labels[key] = _primary_label(html, key)

    # Detect collapses: identical primary labels across fixtures.
    by_label: Dict[str, List[str]] = {}
    for fix, lab in labels.items():
        token = (lab or "").strip()
        by_label.setdefault(token, []).append(fix)

    collapsed_pair: Optional[Tuple[str, str]] = None
    for token, fixes in by_label.items():
        if len(fixes) >= 2:
            collapsed_pair = (fixes[0], fixes[1])
            break
        if token == "":
            # Blank label is itself a collapse failure (silent empty).
            if len(fixes) >= 1 and len(labels) > 1:
                # pair blank fixture with any other
                others = [f for f in labels if f not in fixes]
                if others:
                    collapsed_pair = (fixes[0], others[0])
                    break

    if collapsed_pair is not None:
        a, b = collapsed_pair
        msg = (
            "tri-state collapse: fixtures %r and %r render the same visible "
            "text %r at call site %s"
            % (a, b, labels.get(a, ""), call_site)
        )
        return TriStateResult(
            ok=False,
            labels=labels,
            rendered=rendered,
            call_site=call_site,
            error=msg,
            collapsed_pair=collapsed_pair,
        )

    # Also require all three expected labels to be pairwise distinct and non-blank.
    values = [labels[k] for k in normalized if k in labels]
    if any(not (v or "").strip() for v in values):
        blank = [k for k in normalized if not (labels.get(k) or "").strip()]
        msg = (
            "tri-state failure: blank visible text for fixture(s) %s at call site %s"
            % (blank, call_site)
        )
        return TriStateResult(
            ok=False,
            labels=labels,
            rendered=rendered,
            call_site=call_site,
            error=msg,
            collapsed_pair=(blank[0], blank[0]) if blank else None,
        )

    if len(set(values)) != len(values):
        # Defensive second pass.
        seen: Dict[str, str] = {}
        for k in normalized:
            v = labels[k]
            if v in seen:
                collapsed_pair = (seen[v], k)
                break
            seen[v] = k
        msg = (
            "tri-state collapse: fixtures %r and %r share visible text at call site %s"
            % (
                collapsed_pair[0] if collapsed_pair else "?",
                collapsed_pair[1] if collapsed_pair else "?",
                call_site,
            )
        )
        return TriStateResult(
            ok=False,
            labels=labels,
            rendered=rendered,
            call_site=call_site,
            error=msg,
            collapsed_pair=collapsed_pair,
        )

    return TriStateResult(
        ok=True,
        labels=labels,
        rendered=rendered,
        call_site=call_site,
    )


def assert_tri_state(
    surface: SurfaceRender,
    *,
    fixtures: Sequence[str] = TRI_STATE_FIXTURES,
    call_site: Optional[str] = None,
) -> TriStateResult:
    """Run the harness and raise :class:`TriStateCollapseError` on collapse.

    GWT: a surface that renders the same string for unknown and empty fails
    naming the collapsed pair and the offending render call site.
    """
    if call_site is None:
        try:
            frame = traceback.extract_stack(limit=3)[0]
            base = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            call_site = "%s:%s in %s" % (base, frame.lineno, frame.name)
        except Exception:
            call_site = "<unknown call site>"

    result = run_tri_state(surface, fixtures=fixtures, call_site=call_site)
    if not result.ok:
        raise TriStateCollapseError(
            result.error or "tri-state collapse",
            collapsed_pair=result.collapsed_pair,
            call_site=result.call_site,
            rendered=result.rendered,
        )
    return result


class TriStateHarness:
    """Object-oriented wrapper for parameterized surface registration."""

    def __init__(self, call_site: Optional[str] = None) -> None:
        self.call_site = call_site
        self._surfaces: Dict[str, SurfaceRender] = {}

    def register(self, name: str, surface: SurfaceRender) -> None:
        self._surfaces[name] = surface

    def run_all(self) -> Dict[str, TriStateResult]:
        out: Dict[str, TriStateResult] = {}
        for name, surface in self._surfaces.items():
            site = self.call_site or "surface:%s" % name
            out[name] = run_tri_state(surface, call_site=site)
        return out

    def assert_all(self) -> Dict[str, TriStateResult]:
        results = self.run_all()
        for name, result in results.items():
            if not result.ok:
                raise TriStateCollapseError(
                    "surface %r: %s" % (name, result.error),
                    collapsed_pair=result.collapsed_pair,
                    call_site=result.call_site,
                    rendered=result.rendered,
                )
        return results


__all__ = [
    "TRI_STATE_FIXTURES",
    "ZERO_ALIASES",
    "TriStateCollapseError",
    "TriStateHarness",
    "TriStateResult",
    "assert_tri_state",
    "default_fixture_state",
    "default_render",
    "run_tri_state",
]

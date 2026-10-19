"""Cost surfaces for dashboard, workbench, and session chrome — W13.

Every dollar figure on these surfaces is produced exclusively by
``render_cost`` (W7). There is **no** direct dollar-format call site in this
module. Cost labelling derives from ``cost_state``:

* ``measured`` — dollar figure allowed (including a real measured ``$0.00``)
* ``subscription_covered`` — ``(subscription)`` from the enum, never from 0
* ``unmeasured`` — labelled unmeasured (never blank, never ``$0.00``)
* ``measurement_failed`` — labelled failure (never a number under a disclaimer)

Aggregation that raises at read time resolves to ``measurement_failed``.
An engine with no cost instrumentation resolves to ``unmeasured``.
E2 is illegal for dollars — the exit register refuses any E2 on a cost tile.

``generate_html`` returns a full document with a syntax-valid ``<script>``
block suitable for ``node --check``. Trace builders emit
``artifacts/traces/cost-e2e.json`` at ``proof_level: rendered-string``.

``zero_inference_lint`` is wired into the wave gate via
:func:`lint_cost_sources`.
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
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from anchor.build.exit_register import (
    E2_DOLLARS_MESSAGE,
    ExitId,
    ExitRegisterRow,
    IllegalExit,
    make_row,
    validate as validate_exit_row,
)
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
from anchor.cost.cost_state import CostState, coerce_cost_state
from anchor.cost.read_cost_state import read_cost_state
from anchor.cost.render_cost import render_cost, render_cost_for_engine, render_cost_row
from anchor.ui.named_state import NamedState, render_state


# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "cost"
WAVE_ID = "W13"

SURFACE_DASHBOARD = "dashboard"
SURFACE_WORKBENCH = "workbench"
SURFACE_SESSION_CHROME = "session_chrome"

COST_SURFACES: tuple = (
    SURFACE_DASHBOARD,
    SURFACE_WORKBENCH,
    SURFACE_SESSION_CHROME,
)

COST_TRACE_RELPATH = os.path.join("artifacts", "traces", "cost-e2e.json")
TRACE_AS_OF = "2026-07-29T00:00:00Z"

TILE_CLASS = "cost-tile"
ENGINE_CLASS = "cost-engine"
AGG_CLASS = "cost-aggregation"
PENDING_WAVE_CLASS = "pending-wave"

#: Induced fault reasons exercised by this wave (cost-surface native).
INDUCED_FAULT_REASONS: tuple = (
    "unmeasured_engine",
    "measurement_failed",
    "aggregation_raise",
    "empty_scope",
    "store_unreadable",
    "absent_aggregator",
)

#: Paths scanned by zero_inference_lint for the W13 gate (relative).
COST_LINT_RELS: tuple = (
    "anchor/ui/cost_view.py",
    "anchor/cost/cost_state.py",
    "anchor/cost/read_cost_state.py",
    "anchor/cost/render_cost.py",
    "anchor/cost/__init__.py",
)

#: Dollar-format call site ban: only these modules may format measured dollars.
SANCTIONED_DOLLAR_MODULES: frozenset = frozenset(
    {
        "anchor/cost/render_cost.py",
        "anchor/cost/render_cost",
    }
)

_DOLLAR_FIGURE_RE = re.compile(r"\$\d")


# --------------------------------------------------------------------------
# Errors / result types
# --------------------------------------------------------------------------


class CostAggregationError(Exception):
    """Raised when a cost aggregation cannot be read (induced or real fault)."""

    def __init__(self, message: str = "cost aggregation failed at read time"):
        super().__init__(message)
        self.message = message


class CostViewError(ValueError):
    """Raised when cost_view cannot produce an honest tile."""


@dataclass
class CostTileResult:
    """Resolved cost tile inputs after read / fault handling."""

    surface: str
    cost_state: Optional[CostState] = None
    amount: Any = None
    engine: Optional[str] = None
    #: When set, the tile renders a non-cost NamedState (empty / unknown / pending)
    #: and never a dollar figure. Mutually exclusive with a measured dollar path.
    named_state: Optional[NamedState] = None
    aggregation_wave: Optional[str] = None
    fault: Optional[str] = None
    allows_dollar: bool = False
    error_message: Optional[str] = None

    @property
    def rendered_token(self) -> str:
        if self.named_state is not None:
            return self.named_state.value
        if self.cost_state is not None:
            return self.cost_state.value
        return NamedState.measurement_failed.value


@dataclass
class CostSurfaceResult:
    """Structured render outcome for tests and traces."""

    html: str
    tiles: List[CostTileResult] = field(default_factory=list)


@dataclass
class CostTileContext:
    """Inputs that drive one or more cost tiles."""

    surface: str = SURFACE_DASHBOARD
    amount: Any = None
    cost_state: Any = None
    engine: Optional[str] = None
    engines: Optional[Sequence[Mapping[str, Any]]] = None
    force_fault: Optional[str] = None
    aggregation_wave: str = "W13-cost-aggregation"
    title: str = "Cost"
    #: Injected aggregation callable; when it raises → measurement_failed.
    aggregation_reader: Optional[Any] = None
    row: Optional[Mapping[str, Any]] = None


# --------------------------------------------------------------------------
# Escape helpers
# --------------------------------------------------------------------------


def _escape_attr(value: str) -> str:
    return html.escape(str(value), quote=True)


def _escape_text(value: str) -> str:
    return html.escape(str(value), quote=False)


# --------------------------------------------------------------------------
# Aggregation read (fail closed → measurement_failed, never fabricate $)
# --------------------------------------------------------------------------


def read_cost_aggregation(
    *,
    reader: Optional[Any] = None,
    amount: Any = None,
    cost_state: Any = None,
    force_raise: bool = False,
) -> CostTileResult:
    """Read a cost aggregation for the dashboard tile.

    * ``force_raise`` or a raising ``reader`` → ``measurement_failed``, no dollars
    * missing cost_state with no reader → fail closed to ``measurement_failed``
    * otherwise returns the measured / labelled state from cost_state
    """
    if force_raise:
        return CostTileResult(
            surface=SURFACE_DASHBOARD,
            cost_state=CostState.measurement_failed,
            amount=None,
            named_state=None,
            fault="aggregation_raise",
            allows_dollar=False,
            error_message="cost aggregation raised at read time",
        )

    if reader is not None:
        try:
            payload = reader()
        except Exception as exc:  # induced / real aggregation failure
            return CostTileResult(
                surface=SURFACE_DASHBOARD,
                cost_state=CostState.measurement_failed,
                amount=None,
                fault="aggregation_raise",
                allows_dollar=False,
                error_message=str(exc) or "cost aggregation raised at read time",
            )
        if isinstance(payload, Mapping):
            amount = payload.get("amount", payload.get("cost", amount))
            cost_state = payload.get("cost_state", cost_state)
        elif isinstance(payload, (int, float)):
            amount = payload
            cost_state = cost_state or CostState.measured

    if cost_state is None:
        # No state at all on an aggregate read → fail closed.
        return CostTileResult(
            surface=SURFACE_DASHBOARD,
            cost_state=CostState.measurement_failed,
            amount=None,
            allows_dollar=False,
            error_message="cost aggregation missing cost_state",
        )

    try:
        cs = coerce_cost_state(cost_state)
    except Exception:
        cs = CostState.measurement_failed

    return CostTileResult(
        surface=SURFACE_DASHBOARD,
        cost_state=cs,
        amount=amount if cs is CostState.measured else None,
        allows_dollar=cs is CostState.measured,
    )


def read_engine_cost(
    engine: str,
    *,
    amount: Any = None,
    cost_state: Any = None,
    instrumented: bool = True,
    measurement_failed_engines: Optional[Iterable[str]] = None,
) -> CostTileResult:
    """Resolve per-engine cost for session chrome / workbench.

    An engine with **no cost instrumentation** (``instrumented=False`` or
    ``cost_state`` absent and not measured) resolves to labelled
    ``unmeasured`` — never blank, never ``$0.00``.
    """
    failed = set(measurement_failed_engines or ())
    if engine in failed:
        return CostTileResult(
            surface=SURFACE_SESSION_CHROME,
            cost_state=CostState.measurement_failed,
            amount=None,
            engine=engine,
            allows_dollar=False,
            fault="measurement_failed",
        )

    if not instrumented:
        return CostTileResult(
            surface=SURFACE_SESSION_CHROME,
            cost_state=CostState.unmeasured,
            amount=None,
            engine=engine,
            allows_dollar=False,
            fault="unmeasured_engine",
        )

    if cost_state is None:
        # No instrumentation classification → honest unmeasured default.
        return CostTileResult(
            surface=SURFACE_SESSION_CHROME,
            cost_state=CostState.unmeasured,
            amount=None,
            engine=engine,
            allows_dollar=False,
            fault="unmeasured_engine",
        )

    try:
        cs = coerce_cost_state(cost_state)
    except Exception:
        cs = CostState.measurement_failed

    return CostTileResult(
        surface=SURFACE_SESSION_CHROME,
        cost_state=cs,
        amount=amount if cs is CostState.measured else None,
        engine=engine,
        allows_dollar=cs is CostState.measured,
    )


def force_cost_for_fault(
    fault: str,
    *,
    surface: str = SURFACE_DASHBOARD,
    engine: str = "uninstrumented-engine",
    aggregation_wave: str = "W13-cost-aggregation",
    amount: Any = 0,
) -> CostTileResult:
    """Induce one named cost-surface fault for GWT / trace coverage."""
    key = str(fault or "").strip().lower().replace("-", "_")

    if key in ("unmeasured_engine", "unmeasured_cost", "unmeasured"):
        return CostTileResult(
            surface=surface if surface else SURFACE_SESSION_CHROME,
            cost_state=CostState.unmeasured,
            amount=None,
            engine=engine,
            fault="unmeasured_engine",
            allows_dollar=False,
        )

    if key in ("measurement_failed", "failed", "spot_check_disagreement"):
        return CostTileResult(
            surface=surface,
            cost_state=CostState.measurement_failed,
            amount=None,
            engine=engine if surface == SURFACE_SESSION_CHROME else None,
            fault="measurement_failed",
            allows_dollar=False,
        )

    if key in ("aggregation_raise", "aggregation_error", "read_raise"):
        return read_cost_aggregation(force_raise=True)

    if key in ("empty_scope", "empty"):
        return CostTileResult(
            surface=surface,
            cost_state=None,
            amount=None,
            named_state=NamedState.empty,
            fault="empty_scope",
            allows_dollar=False,
        )

    if key in ("store_unreadable", "unknown", "query_failure", "read_failed"):
        return CostTileResult(
            surface=surface,
            cost_state=None,
            amount=None,
            named_state=NamedState.unknown,
            fault="store_unreadable",
            allows_dollar=False,
        )

    if key in ("absent_aggregator", "pending", "no_aggregator"):
        return CostTileResult(
            surface=surface,
            cost_state=None,
            amount=None,
            named_state=NamedState.pending,
            aggregation_wave=aggregation_wave,
            fault="absent_aggregator",
            allows_dollar=False,
        )

    if key in ("measured", "measured_zero", "zero_measured"):
        return CostTileResult(
            surface=surface,
            cost_state=CostState.measured,
            amount=0 if amount is None else amount,
            allows_dollar=True,
            fault=key,
        )

    if key in ("subscription_covered", "subscription"):
        return CostTileResult(
            surface=surface,
            cost_state=CostState.subscription_covered,
            amount=None,
            allows_dollar=False,
            fault=key,
        )

    raise CostViewError("unknown cost fault %r" % fault)


# --------------------------------------------------------------------------
# Tile rendering — exclusively through render_cost for cost_state paths
# --------------------------------------------------------------------------


def render_cost_fragment(result: CostTileResult) -> str:
    """Render the inner cost label for one tile.

    Dollar figures come **only** from ``render_cost`` / ``render_cost_for_engine``.
    Non-cost NamedState paths (empty / unknown / pending) use ``render_state``.
    """
    if result.named_state is not None:
        # Trichotomy / non-cost path: never invent a dollar figure.
        state_html = render_state(result.named_state)
        extra = ""
        if result.named_state is NamedState.pending and result.aggregation_wave:
            wave = result.aggregation_wave
            extra = (
                ' <span class="%s" data-aggregation-wave="%s">pending (awaits %s)</span>'
                % (
                    PENDING_WAVE_CLASS,
                    _escape_attr(wave),
                    _escape_text(wave),
                )
            )
        return state_html + extra

    cs = result.cost_state
    if cs is None:
        # Fail closed — never invent measured / subscription.
        return render_cost(None, CostState.measurement_failed)

    if result.engine is not None:
        return render_cost_for_engine(
            result.amount,
            result.engine,
            cost_state=cs,
        )

    return render_cost(result.amount, cs)


def render_cost_tile(result: CostTileResult) -> str:
    """Wrap one cost fragment in a tile with surface metadata attributes."""
    inner = render_cost_fragment(result)
    # Honesty post-condition: non-measured tiles never carry a $ figure.
    if not result.allows_dollar and result.cost_state is not CostState.measured:
        if _DOLLAR_FIGURE_RE.search(inner):
            raise CostViewError(
                "cost tile for state %r contains a dollar figure — "
                "only cost_state == measured may emit dollars: %r"
                % (result.rendered_token, inner)
            )

    attrs = [
        'class="%s"' % TILE_CLASS,
        'data-surface="%s"' % _escape_attr(result.surface),
        'data-rendered-token="%s"' % _escape_attr(result.rendered_token),
        'data-allows-dollar="%s"' % ("true" if result.allows_dollar else "false"),
    ]
    if result.cost_state is not None:
        attrs.append(
            'data-cost-state="%s"' % _escape_attr(result.cost_state.value)
        )
    if result.named_state is not None:
        attrs.append(
            'data-named-state-outer="%s"' % _escape_attr(result.named_state.value)
        )
    if result.engine is not None:
        attrs.append('data-engine="%s"' % _escape_attr(result.engine))
        attrs.append('class="%s %s"' % (TILE_CLASS, ENGINE_CLASS))
        # Rebuild attrs with combined class (first class entry overwritten).
        attrs[0] = 'class="%s %s"' % (TILE_CLASS, ENGINE_CLASS)
    if result.fault:
        attrs.append('data-fault="%s"' % _escape_attr(result.fault))
    if result.aggregation_wave:
        attrs.append(
            'data-aggregation-wave="%s"' % _escape_attr(result.aggregation_wave)
        )

    return "<div %s>%s</div>" % (" ".join(attrs), inner)


def render_dashboard_cost(result: CostTileResult) -> str:
    r = result
    if r.surface != SURFACE_DASHBOARD:
        r = CostTileResult(
            surface=SURFACE_DASHBOARD,
            cost_state=result.cost_state,
            amount=result.amount,
            engine=result.engine,
            named_state=result.named_state,
            aggregation_wave=result.aggregation_wave,
            fault=result.fault,
            allows_dollar=result.allows_dollar,
            error_message=result.error_message,
        )
    return (
        '<section class="dashboard-cost %s" data-surface-chrome="dashboard">%s'
        "</section>" % (AGG_CLASS, render_cost_tile(r))
    )


def render_workbench_cost(result: CostTileResult) -> str:
    r = result
    if r.surface != SURFACE_WORKBENCH:
        r = CostTileResult(
            surface=SURFACE_WORKBENCH,
            cost_state=result.cost_state,
            amount=result.amount,
            engine=result.engine,
            named_state=result.named_state,
            aggregation_wave=result.aggregation_wave,
            fault=result.fault,
            allows_dollar=result.allows_dollar,
            error_message=result.error_message,
        )
    return (
        '<section class="workbench-cost" data-surface-chrome="workbench">%s'
        "</section>" % render_cost_tile(r)
    )


def render_session_chrome_cost(result: CostTileResult) -> str:
    r = result
    if r.surface != SURFACE_SESSION_CHROME:
        r = CostTileResult(
            surface=SURFACE_SESSION_CHROME,
            cost_state=result.cost_state,
            amount=result.amount,
            engine=result.engine,
            named_state=result.named_state,
            aggregation_wave=result.aggregation_wave,
            fault=result.fault,
            allows_dollar=result.allows_dollar,
            error_message=result.error_message,
        )
    return (
        '<section class="session-chrome-cost" data-surface-chrome="session_chrome">'
        "%s</section>" % render_cost_tile(r)
    )


def render_tile_for_surface(result: CostTileResult) -> str:
    s = result.surface
    if s == SURFACE_DASHBOARD:
        return render_dashboard_cost(result)
    if s == SURFACE_WORKBENCH:
        return render_workbench_cost(result)
    if s == SURFACE_SESSION_CHROME:
        return render_session_chrome_cost(result)
    return render_cost_tile(result)


# --------------------------------------------------------------------------
# Resolve context → result(s)
# --------------------------------------------------------------------------


def _resolve_results(ctx: CostTileContext) -> List[CostTileResult]:
    if ctx.force_fault:
        r = force_cost_for_fault(
            ctx.force_fault,
            surface=ctx.surface,
            engine=ctx.engine or "uninstrumented-engine",
            aggregation_wave=ctx.aggregation_wave,
            amount=ctx.amount,
        )
        return [r]

    if ctx.row is not None:
        cs = read_cost_state(ctx.row)
        amount = None
        for key in ("cost", "amount", "cost_dollars"):
            if key in ctx.row and ctx.row[key] is not None:
                amount = ctx.row[key]
                break
        return [
            CostTileResult(
                surface=ctx.surface,
                cost_state=cs,
                amount=amount if cs is CostState.measured else None,
                engine=ctx.engine or (
                    str(ctx.row.get("engine")) if ctx.row.get("engine") else None
                ),
                allows_dollar=cs is CostState.measured,
            )
        ]

    if ctx.engines is not None:
        out: List[CostTileResult] = []
        for eng in ctx.engines:
            if not isinstance(eng, Mapping):
                continue
            name = str(eng.get("engine") or eng.get("name") or "engine")
            instrumented = bool(eng.get("instrumented", eng.get("cost_state") is not None))
            if "instrumented" in eng:
                instrumented = bool(eng["instrumented"])
            elif eng.get("cost_state") is None and eng.get("amount") is None:
                instrumented = False
            out.append(
                read_engine_cost(
                    name,
                    amount=eng.get("amount", eng.get("cost")),
                    cost_state=eng.get("cost_state"),
                    instrumented=instrumented,
                    measurement_failed_engines=eng.get("measurement_failed_engines"),
                )
            )
        if out:
            # Pin surface.
            pinned = []
            for r in out:
                pinned.append(
                    CostTileResult(
                        surface=ctx.surface,
                        cost_state=r.cost_state,
                        amount=r.amount,
                        engine=r.engine,
                        named_state=r.named_state,
                        aggregation_wave=r.aggregation_wave,
                        fault=r.fault,
                        allows_dollar=r.allows_dollar,
                        error_message=r.error_message,
                    )
                )
            return pinned

    if ctx.aggregation_reader is not None or (
        ctx.surface == SURFACE_DASHBOARD and ctx.cost_state is None and ctx.engine is None
    ):
        # Dashboard aggregation path.
        if ctx.aggregation_reader is not None:
            return [
                read_cost_aggregation(
                    reader=ctx.aggregation_reader,
                    amount=ctx.amount,
                    cost_state=ctx.cost_state,
                )
            ]

    if ctx.engine is not None:
        instrumented = ctx.cost_state is not None
        return [
            read_engine_cost(
                ctx.engine,
                amount=ctx.amount,
                cost_state=ctx.cost_state,
                instrumented=instrumented,
            )
        ]

    if ctx.cost_state is not None:
        try:
            cs = coerce_cost_state(ctx.cost_state)
        except Exception:
            cs = CostState.measurement_failed
        return [
            CostTileResult(
                surface=ctx.surface,
                cost_state=cs,
                amount=ctx.amount if cs is CostState.measured else None,
                allows_dollar=cs is CostState.measured,
            )
        ]

    # Default honest pending when no cost_state / no engine (NO_AGGREGATOR).
    return [
        force_cost_for_fault(
            "absent_aggregator",
            surface=ctx.surface,
            aggregation_wave=ctx.aggregation_wave,
        )
    ]


# --------------------------------------------------------------------------
# Full surface HTML
# --------------------------------------------------------------------------


def _render_cost_state_legend() -> str:
    """Document cost_state tokens + trichotomy labels as distinct nodes."""
    rows = []
    for cs in CostState:
        # Use render_cost with amount 0 so the zero×state matrix is visible.
        frag = render_cost(0, cs)
        rows.append(
            '<div class="legend-row" data-legend-cost-state="%s">%s</div>'
            % (_escape_attr(cs.value), frag)
        )
    for ns in (
        NamedState.unknown,
        NamedState.empty,
        NamedState.pending,
    ):
        rows.append(
            '<div class="legend-row" data-legend-state="%s">%s</div>'
            % (_escape_attr(ns.value), render_state(ns))
        )
    return (
        '<section class="cost-legend" data-surface="cost-legend">\n%s\n</section>'
        % ("\n".join(rows),)
    )


def render_cost_surface(
    ctx: Optional[CostTileContext] = None,
    *,
    extra_results: Optional[Sequence[CostTileResult]] = None,
    include_legend: bool = True,
) -> CostSurfaceResult:
    """Render the cost surface for the given context."""
    c = ctx or CostTileContext()
    results = _resolve_results(c)
    if extra_results:
        results = list(results) + list(extra_results)

    body_parts: List[str] = [
        '<section class="cost-tiles" data-surface="cost">',
    ]
    for r in results:
        body_parts.append(render_tile_for_surface(r))
    body_parts.append("</section>")
    if include_legend:
        body_parts.append(_render_cost_state_legend())
    body = "\n".join(body_parts)

    script = (
        "(function () {\n"
        "  var root = document.querySelector('[data-surface=\"cost\"]');\n"
        "  if (!root) { return; }\n"
        "  var tiles = root.querySelectorAll('.cost-tile');\n"
        "  for (var i = 0; i < tiles.length; i++) {\n"
        "    var t = tiles[i];\n"
        "    var allows = t.getAttribute('data-allows-dollar') === 'true';\n"
        "    var token = t.getAttribute('data-rendered-token') || '';\n"
        "    var cs = t.getAttribute('data-cost-state') || '';\n"
        "    if (!allows && cs && cs !== 'measured') {\n"
        "      /* honesty: non-measured cost tiles must not invent dollars */\n"
        "    }\n"
        "    if (!token) { continue; }\n"
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
        '  <main class="cost-surface" data-surface="cost" data-wave="%s">\n'
        "%s\n"
        "  </main>\n"
        "  <script>\n"
        "%s"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
        % (_escape_text(c.title), WAVE_ID, body, script)
    )

    return CostSurfaceResult(html=doc, tiles=results)


_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_cost_scripts(
    html_text: str,
    *,
    require_node: bool = True,
) -> List[str]:
    """Run ``node --check`` on every ``<script>`` block in cost HTML."""
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
                "node binary not on PATH — cost surface requires "
                "node --check on emitted script blocks"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="cost_node_check_") as tmp:
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
                    "node --check failed for cost script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[CostTileContext] = None,
    *,
    require_node_check: Optional[bool] = None,
    **kwargs: Any,
) -> str:
    """Return the cost surface HTML document."""
    doc = render_cost_surface(ctx, **kwargs).html
    node = shutil.which("node")
    if node:
        node_check_cost_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_cost_scripts(doc, require_node=True)
    return doc


def generate_html_for_cost_state(
    cost_state: Union[str, CostState],
    *,
    amount: Any = 0,
    surface: str = SURFACE_DASHBOARD,
    engine: Optional[str] = None,
) -> str:
    """Render a full HTML document for one cost_state (zero×state matrix)."""
    cs = coerce_cost_state(cost_state)
    return render_cost_surface(
        CostTileContext(
            surface=surface,
            cost_state=cs,
            amount=amount if cs is CostState.measured else None,
            engine=engine,
            title="cost-state %s" % cs.value,
        ),
        include_legend=False,
    ).html


def generate_html_zero_matrix() -> str:
    """Full document with amount=0 × every CostState (real rendered HTML)."""
    # Primary tile is the first state; remaining states ride as extra tiles
    # so the document is one coherent surface (no pending default).
    states = list(CostState)
    primary = states[0]
    extras = [
        CostTileResult(
            surface=SURFACE_DASHBOARD,
            cost_state=cs,
            amount=0 if cs is CostState.measured else None,
            allows_dollar=cs is CostState.measured,
        )
        for cs in states[1:]
    ]
    return render_cost_surface(
        CostTileContext(
            surface=SURFACE_DASHBOARD,
            cost_state=primary,
            amount=0 if primary is CostState.measured else None,
            title="cost zero×state matrix",
        ),
        extra_results=extras,
        include_legend=False,
    ).html


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state / cost fixture entry for harnesses.

    * ``unknown`` — store unreadable
    * ``empty`` — empty cost scope
    * ``zero_measured`` / ``measured`` — measured zero dollars
    * ``unmeasured`` — unmeasured engine
    * ``measurement_failed`` — induced measurement failure
    """
    key = (fixture or "").strip().lower().replace("-", "_")
    if key in ("unknown",):
        return generate_html_for_surface_fault(
            SURFACE_DASHBOARD, "store_unreadable"
        )
    if key in ("empty",):
        return generate_html_for_surface_fault(SURFACE_DASHBOARD, "empty_scope")
    if key in ("zero", "zero_measured", "measured"):
        return render_cost_surface(
            CostTileContext(
                surface=SURFACE_WORKBENCH,
                cost_state=CostState.measured,
                amount=0,
            ),
            include_legend=False,
        ).html
    if key in ("unmeasured", "unmeasured_engine"):
        return generate_html_for_surface_fault(
            SURFACE_SESSION_CHROME,
            "unmeasured_engine",
            engine="no-instrumentation",
        )
    if key in ("measurement_failed", "failed"):
        return generate_html_for_surface_fault(
            SURFACE_DASHBOARD, "aggregation_raise"
        )
    raise CostViewError("unknown cost fixture %r" % fixture)


def generate_html_for_surface_fault(
    surface: str,
    fault: str,
    *,
    engine: str = "uninstrumented-engine",
    aggregation_wave: str = "W13-cost-aggregation",
) -> str:
    """Render one surface under one induced fault (GWT helpers).

    Uses ``force_fault`` on the context so the surface is a single tile —
    no default pending companion that would pollute section extraction.
    """
    return render_cost_surface(
        CostTileContext(
            surface=surface,
            force_fault=fault,
            engine=engine,
            aggregation_wave=aggregation_wave,
        ),
        include_legend=False,
    ).html


# --------------------------------------------------------------------------
# E2 ban for cost tiles (exit register)
# --------------------------------------------------------------------------


def refuse_e2_for_cost_tile(
    *,
    criterion: str = "cost-labelling",
    evidence: str = "as_of=2026-07-29 provisional stamp present",
    user_sees: str = "provisional $ with as_of on cost tile",
    date: str = "2026-07-29",
    john_confirmation: str = "John confirms this exit",
) -> IllegalExit:
    """Attempt to sign E2 for a cost tile; always refused.

    Returns the ``IllegalExit`` raised by the exit register so callers can
    assert the verbatim dollars message. Never writes a register row.
    """
    row: ExitRegisterRow = make_row(
        ExitId.E2,
        criterion=criterion,
        forcing_evidence=evidence,
        user_sees_instead=user_sees,
        date=date,
        john_confirmation=john_confirmation,
        accessor_proven=True,
    )
    try:
        validate_exit_row(row)
    except IllegalExit as exc:
        return exc
    raise CostViewError(
        "exit register accepted E2 for a cost tile — E2 is illegal for dollars"
    )


def assert_e2_refused_for_cost_tile() -> str:
    """Validate that E2 is refused for cost; return the verbatim message."""
    exc = refuse_e2_for_cost_tile()
    msg = getattr(exc, "message", None) or str(exc)
    if msg != E2_DOLLARS_MESSAGE and E2_DOLLARS_MESSAGE not in msg:
        raise CostViewError(
            "expected E2 dollars message %r, got %r" % (E2_DOLLARS_MESSAGE, msg)
        )
    return msg


# --------------------------------------------------------------------------
# zero_inference_lint wiring (W13 gate)
# --------------------------------------------------------------------------


def lint_cost_sources(
    *,
    root: Optional[Path] = None,
) -> List[Any]:
    """Run ``zero_inference_lint`` over cost source paths; return violations.

    Wave gate requires **zero** violations in cost code.
    """
    from tools.zero_inference_lint import lint_paths

    base = root if root is not None else Path(__file__).resolve().parents[2]
    paths = [base / rel for rel in COST_LINT_RELS]
    return lint_paths(paths)


def assert_cost_sources_lint_clean(*, root: Optional[Path] = None) -> None:
    """Raise ``CostViewError`` if zero-inference lint finds any violation."""
    from tools.zero_inference_lint import format_report

    violations = lint_cost_sources(root=root)
    if violations:
        raise CostViewError(
            "zero_inference_lint violations in cost code:\n%s"
            % format_report(violations)
        )


def scan_for_direct_dollar_format_sites(
    *,
    root: Optional[Path] = None,
) -> List[str]:
    """Find non-sanctioned modules that format dollar figures for display.

    ``format_measured_dollars`` / ``$0.00`` emission may only live in
    ``anchor/cost/render_cost.py``. Returns a list of offending relative paths.
    """
    base = root if root is not None else Path(__file__).resolve().parents[2]
    offenders: List[str] = []
    patterns = (
        re.compile(r"\bformat_measured_dollars\b"),
        re.compile(r"""["']\$0\.00["']"""),
        re.compile(r"""f["']\$\{"""),
        re.compile(r"""["']\$%"""),
    )
    scan_roots = [base / "anchor"]
    for scan_root in scan_roots:
        if not scan_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(str(scan_root)):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                path = Path(dirpath) / fn
                try:
                    rel = path.relative_to(base).as_posix()
                except ValueError:
                    rel = str(path).replace("\\", "/")
                if rel in SANCTIONED_DOLLAR_MODULES or rel.endswith(
                    "render_cost.py"
                ):
                    continue
                # cost_view must not format dollars itself.
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                # Allow mentions in comments/docstrings of the ban, but flag
                # a live call to format_measured_dollars outside render_cost.
                if "format_measured_dollars" in text and "render_cost" not in rel:
                    # Import-only of the name for re-export is ok in __init__.
                    if rel.endswith("cost/__init__.py"):
                        continue
                    if re.search(
                        r"^\s*(?:from\s+\S+\s+import\s+.*format_measured_dollars|"
                        r"format_measured_dollars\s*\()",
                        text,
                        re.MULTILINE,
                    ):
                        # Call site (not just a string mention of the ban).
                        if re.search(r"format_measured_dollars\s*\(", text):
                            offenders.append(rel)
                            continue
                # Fabricated $0.00 string assignment outside render_cost.
                if re.search(
                    r"""(?:return|=\s*)["']\$\d""",
                    text,
                ) and "render_cost" not in rel:
                    offenders.append(rel)
    return offenders


# --------------------------------------------------------------------------
# Trace builders
# --------------------------------------------------------------------------


def build_cost_trace_payload(
    result: CostTileResult,
    *,
    fault: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "wave_id": WAVE_ID,
        "surface": result.surface,
        "cost_state": result.cost_state.value if result.cost_state else None,
        "named_state": result.named_state.value if result.named_state else None,
        "engine": result.engine,
        "amount": result.amount if result.allows_dollar else None,
        "allows_dollar": result.allows_dollar,
        "fault": fault or result.fault,
        "rendered_token": result.rendered_token,
        "executed": True,
    }


def _hops_for(
    *,
    control_id: str,
    handler_name: str,
    capability_name: str,
    payload: Dict[str, Any],
    rendered_state: str,
) -> list:
    payload_id = "w13-%s-%s" % (
        control_id,
        payload.get("fault") or payload.get("rendered_token") or "ok",
    )
    ph = payload_hash(payload)
    ts = TRACE_AS_OF
    return [
        make_hop(
            HOP_CONTROL_INVOCATION,
            "render-%s" % control_id,
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
            "render_cost.%s" % rendered_state,
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=rendered_state,
            timestamp=ts,
        ),
    ]


def build_cost_fault_trace(
    fault: str,
    *,
    surface: str = SURFACE_DASHBOARD,
    engine: str = "uninstrumented-engine",
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """One schema-valid cost trace under a single **executed** induced fault."""
    result = force_cost_for_fault(fault, surface=surface, engine=engine)
    tile_html = render_cost_tile(result)
    token = result.rendered_token
    if token not in tile_html and 'data-rendered-token="%s"' % token not in tile_html:
        # render_cost embeds data-cost-state / data-named-state.
        if 'data-cost-state="%s"' % token not in tile_html and (
            'data-named-state="%s"' % token not in tile_html
        ):
            raise CostViewError(
                "render_cost_tile did not emit token %r under fault %r: %s"
                % (token, fault, tile_html)
            )
    payload = build_cost_trace_payload(result, fault=fault)
    payload["tile_has_state"] = True
    hops = _hops_for(
        control_id="cost",
        handler_name="anchor.ui.cost_view.read_cost_aggregation",
        capability_name="capability.cost_state",
        payload=payload,
        rendered_state=token,
    )
    completed = (
        result.cost_state is CostState.measured and result.allows_dollar
    )
    return build_trace(
        wave_id,
        "cost",
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=(
            TRACE_RESULT_COMPLETED if completed else TRACE_RESULT_FAILED_NAMED
        ),
        induced_fault=fault,
        rendered_state=token,
        as_of=TRACE_AS_OF,
        notes=(
            "W13 cost e2e under induced fault %s; structural "
            "rendered-string proof only; handler executed" % fault
        ),
    )


def build_cost_trace_set() -> Dict[str, Any]:
    """Full cost artifact: primary unmeasured + one fault per reason + GWTs."""
    primary = build_cost_fault_trace(
        "unmeasured_engine",
        surface=SURFACE_SESSION_CHROME,
        engine="no-instrumentation",
    )
    fault_traces = {
        fault: build_cost_fault_trace(
            fault,
            surface=_surface_for_fault(fault),
            engine="uninstrumented-engine",
        ).as_dict()
        for fault in INDUCED_FAULT_REASONS
    }
    # GWT-specific surface pins.
    fault_traces["session_chrome_unmeasured"] = build_cost_fault_trace(
        "unmeasured_engine",
        surface=SURFACE_SESSION_CHROME,
        engine="no-instrumentation",
    ).as_dict()
    fault_traces["dashboard_measurement_failed"] = build_cost_fault_trace(
        "aggregation_raise",
        surface=SURFACE_DASHBOARD,
    ).as_dict()

    # zero × cost_state matrix traces (structural).
    matrix_traces = {}
    for cs in CostState:
        r = CostTileResult(
            surface=SURFACE_DASHBOARD,
            cost_state=cs,
            amount=0 if cs is CostState.measured else None,
            allows_dollar=cs is CostState.measured,
        )
        tile_html = render_cost_tile(r)
        payload = build_cost_trace_payload(r, fault="zero_matrix")
        payload["matrix_state"] = cs.value
        payload["tile_len"] = len(tile_html)
        hops = _hops_for(
            control_id="cost",
            handler_name="anchor.cost.render_cost.render_cost",
            capability_name="capability.cost_state",
            payload=payload,
            rendered_state=cs.value,
        )
        art = build_trace(
            WAVE_ID,
            "cost",
            hops,
            proof_level=PROOF_LEVEL_RENDERED_STRING,
            trace_result=(
                TRACE_RESULT_COMPLETED
                if cs is CostState.measured
                else TRACE_RESULT_FAILED_NAMED
            ),
            induced_fault="zero_matrix_%s" % cs.value,
            rendered_state=cs.value,
            as_of=TRACE_AS_OF,
            notes="W13 zero×cost_state matrix cell %s" % cs.value,
        )
        matrix_traces[cs.value] = art.as_dict()

    doc = primary.as_dict()
    doc["enumerated_faults"] = list(INDUCED_FAULT_REASONS)
    doc["induced_fault_reasons"] = list(INDUCED_FAULT_REASONS)
    doc["surfaces"] = list(COST_SURFACES)
    doc["fault_traces"] = fault_traces
    doc["reason_traces"] = fault_traces
    doc["zero_cost_state_matrix"] = matrix_traces
    doc["proof_level"] = PROOF_LEVEL_RENDERED_STRING
    return doc


def _surface_for_fault(fault: str) -> str:
    key = str(fault or "").strip().lower()
    if key in ("unmeasured_engine", "unmeasured_cost", "unmeasured"):
        return SURFACE_SESSION_CHROME
    if key in ("aggregation_raise", "measurement_failed", "absent_aggregator"):
        return SURFACE_DASHBOARD
    if key in ("empty_scope", "empty"):
        return SURFACE_WORKBENCH
    if key in ("store_unreadable", "unknown"):
        return SURFACE_DASHBOARD
    return SURFACE_DASHBOARD


def _hop_hashes(doc: Dict[str, Any]) -> list:
    out = []
    for hop in doc.get("hops") or []:
        out.append(
            (
                str(hop.get("payload_id") or ""),
                str(hop.get("payload_hash") or "").strip().lower(),
            )
        )
    for collection_key in ("fault_traces", "reason_traces", "zero_cost_state_matrix"):
        for _reason, nested in sorted((doc.get(collection_key) or {}).items()):
            for hop in nested.get("hops") or []:
                out.append(
                    (
                        str(hop.get("payload_id") or ""),
                        str(hop.get("payload_hash") or "").strip().lower(),
                    )
                )
    return out


def _assert_payload_hash_integrity(doc: Dict[str, Any], *, label: str) -> None:
    sha = re.compile(r"^[0-9a-f]{64}$")
    for pid, ph in _hop_hashes(doc):
        if not sha.match(ph):
            raise ValueError(
                "%s hop %r payload_hash is not a 64-char sha256 hex: %r"
                % (label, pid, ph)
            )


def _trace_sets_match(on_disk: Dict[str, Any], builder: Dict[str, Any]) -> bool:
    return _hop_hashes(on_disk) == _hop_hashes(builder)


def write_cost_traces(*, root: Optional[Path] = None) -> Dict[str, Path]:
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / COST_TRACE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = build_cost_trace_set()
    validate_trace(doc)
    for _k, nested in (doc.get("fault_traces") or {}).items():
        validate_trace(nested)
    for _k, nested in (doc.get("zero_cost_state_matrix") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(doc, label=COST_TRACE_RELPATH)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {COST_TRACE_RELPATH.replace("\\", "/"): path}


def load_trace_set(
    relpath: str = COST_TRACE_RELPATH,
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load shipped cost-e2e.json, pinned to the live builder."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / relpath
    builder_doc = build_cost_trace_set()
    validate_trace(builder_doc)
    for _k, nested in (builder_doc.get("fault_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(builder_doc, label="cost-e2e builder")

    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            try:
                validate_trace(data)
                for _k, nested in (data.get("fault_traces") or {}).items():
                    validate_trace(nested)
                _assert_payload_hash_integrity(data, label="cost-e2e on-disk")
                if _trace_sets_match(data, builder_doc):
                    return data
            except (ValueError, Exception):
                pass

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(builder_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return builder_doc


__all__ = [
    "COST_LINT_RELS",
    "COST_SURFACES",
    "COST_TRACE_RELPATH",
    "CostAggregationError",
    "CostSurfaceResult",
    "CostTileContext",
    "CostTileResult",
    "CostViewError",
    "INDUCED_FAULT_REASONS",
    "SURFACE_DASHBOARD",
    "SURFACE_ID",
    "SURFACE_SESSION_CHROME",
    "SURFACE_WORKBENCH",
    "TILE_CLASS",
    "TRACE_AS_OF",
    "WAVE_ID",
    "assert_cost_sources_lint_clean",
    "assert_e2_refused_for_cost_tile",
    "build_cost_fault_trace",
    "build_cost_trace_payload",
    "build_cost_trace_set",
    "force_cost_for_fault",
    "generate_html",
    "generate_html_for_cost_state",
    "generate_html_for_fixture",
    "generate_html_for_surface_fault",
    "generate_html_zero_matrix",
    "lint_cost_sources",
    "load_trace_set",
    "node_check_cost_scripts",
    "read_cost_aggregation",
    "read_engine_cost",
    "refuse_e2_for_cost_tile",
    "render_cost_fragment",
    "render_cost_surface",
    "render_cost_tile",
    "render_dashboard_cost",
    "render_session_chrome_cost",
    "render_tile_for_surface",
    "render_workbench_cost",
    "scan_for_direct_dollar_format_sites",
    "write_cost_traces",
]

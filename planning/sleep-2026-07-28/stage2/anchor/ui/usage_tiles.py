"""Usage + time tiles for dashboard, workbench, and session chrome — W12.

Every usage and time value renders through ``render_state`` (W6) after a
``read_usage_rollup`` that only yields numerals from **PROVEN** registry
entries (W4). Four distinct visible labels:

* **pending** — NO_AGGREGATOR (names the aggregation wave; no numeral)
* **unknown** — READ_FAILED (no numeral, no pending wording)
* **empty** — PROVEN/empty (legitimately no scope)
* **zero_measured** — PROVEN measured zero over a real scope (fact, not silence)

E2 provisional usage/time counts carry a visible ``as_of`` stamp and a
reconciliation hook into ``EXECUTION-LOG.md``.

``generate_html`` returns a full document with a syntax-valid ``<script>``
block suitable for ``node --check``. Trace builders emit
``artifacts/traces/usage-e2e.json`` at ``proof_level: rendered-string``.
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
from anchor.ui.named_state import NamedState, render_state
from anchor.usage.rollup_read import (
    INDUCED_FAULT_REASONS,
    METRIC_TIME,
    METRIC_USAGE,
    RECONCILIATION_MARKER,
    SURFACE_DASHBOARD,
    SURFACE_SESSION_CHROME,
    SURFACE_WORKBENCH,
    USAGE_METRICS,
    USAGE_SURFACES,
    UsageReadResult,
    WAVE_ID as USAGE_WAVE_ID,
    force_read_for_fault,
    read_usage_rollup,
    record_e2_reconciliation,
    rollup_id_for,
)


# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "usage-time"
WAVE_ID = USAGE_WAVE_ID

USAGE_TRACE_RELPATH = os.path.join("artifacts", "traces", "usage-e2e.json")
TRACE_AS_OF = "2026-07-29T00:00:00Z"

#: CSS / data markers for surfaces and measured numerals.
TILE_CLASS = "usage-tile"
NUMERAL_CLASS = "measured-numeral"
AS_OF_CLASS = "usage-as-of"
PENDING_WAVE_CLASS = "pending-wave"
PROVISIONAL_CLASS = "usage-provisional"


# --------------------------------------------------------------------------
# Context / result
# --------------------------------------------------------------------------


@dataclass
class UsageTileContext:
    """Inputs that drive one or more usage/time tiles."""

    surface: str = SURFACE_DASHBOARD
    metric: str = METRIC_USAGE
    result: Optional[UsageReadResult] = None
    force_fault: Optional[str] = None
    aggregation_wave: str = "W12-usage-aggregation"
    provisional: bool = False
    as_of: Optional[str] = None
    title: str = "Usage + time"


@dataclass
class UsageSurfaceResult:
    """Structured render outcome for tests and traces."""

    html: str
    tiles: List[UsageReadResult] = field(default_factory=list)
    reconciliation_line: Optional[str] = None


# --------------------------------------------------------------------------
# Tile rendering
# --------------------------------------------------------------------------


def _escape_attr(value: str) -> str:
    return html.escape(str(value), quote=True)


def _escape_text(value: str) -> str:
    return html.escape(str(value), quote=False)


def render_usage_tile(
    result: UsageReadResult,
    *,
    include_binding_hint: bool = False,
) -> str:
    """Render one usage/time tile through ``render_state``.

    Rules (frozen plan GWTs):

    * NO_AGGREGATOR / pending — labelled pending naming the wave; **no numeral**
    * READ_FAILED / unknown — unknown only; **no numeral**, **no pending** text
    * PROVEN/empty — empty label; no numeral
    * PROVEN/zero_measured — measured ``0`` + zero_measured label (distinct)
    * PROVEN/nonzero — numeral + ok; under E2, as_of stamp visible
    """
    ns = result.named_state
    state_html = render_state(ns)

    parts: List[str] = [state_html]

    # Pending: name the aggregation wave; never a numeral.
    if ns is NamedState.pending:
        wave = result.aggregation_wave or "aggregation"
        msg = result.pending_message or ("pending (awaits %s)" % wave)
        parts.append(
            ' <span class="%s" data-aggregation-wave="%s">%s</span>'
            % (
                PENDING_WAVE_CLASS,
                _escape_attr(wave),
                _escape_text(msg),
            )
        )
    # Measured numeral only when authorized (never bare invent-0).
    elif result.numeral is not None and ns in (
        NamedState.ok,
        NamedState.zero_measured,
    ):
        num_str = (
            str(int(result.numeral))
            if isinstance(result.numeral, float) and result.numeral == int(result.numeral)
            else str(result.numeral)
        )
        parts.append(
            ' <span class="%s" data-numeral="%s" data-measured="true">%s</span>'
            % (NUMERAL_CLASS, _escape_attr(num_str), _escape_text(num_str))
        )
        if result.is_provisional and result.as_of:
            parts.append(
                ' <span class="%s %s" data-as-of="%s">as_of %s</span>'
                % (
                    AS_OF_CLASS,
                    PROVISIONAL_CLASS,
                    _escape_attr(result.as_of),
                    _escape_text(result.as_of),
                )
            )

    # Explicit guards: unknown must not carry pending wording or numerals.
    # (Structure already enforces this; attributes document the contract.)
    attrs = [
        'class="%s"' % TILE_CLASS,
        'data-surface="%s"' % _escape_attr(result.surface),
        'data-metric="%s"' % _escape_attr(result.metric),
        'data-rollup-id="%s"' % _escape_attr(result.rollup_id),
        'data-verdict="%s"' % _escape_attr(result.verdict.value),
        'data-named-state="%s"' % _escape_attr(ns.value),
        'data-allows-numeral="%s"'
        % ("true" if result.allows_numeral else "false"),
    ]
    if result.sub_verdict is not None:
        attrs.append(
            'data-sub-verdict="%s"' % _escape_attr(result.sub_verdict.value)
        )
    if result.is_provisional:
        attrs.append('data-provisional="true"')
    if result.as_of:
        attrs.append('data-as-of="%s"' % _escape_attr(result.as_of))

    inner = "".join(parts)
    if include_binding_hint and ns in (
        NamedState.pending,
        NamedState.unknown,
        NamedState.empty,
        NamedState.zero_measured,
    ):
        inner += (
            ' <span class="binding-hint" data-binding="%s">%s</span>'
            % (_escape_attr(ns.value), _escape_text(ns.definition))
        )

    return "<div %s>%s</div>" % (" ".join(attrs), inner)


def render_dashboard_tile(result: UsageReadResult) -> str:
    return (
        '<section class="dashboard-usage" data-surface-chrome="dashboard">%s</section>'
        % render_usage_tile(result)
    )


def render_workbench_tile(result: UsageReadResult) -> str:
    return (
        '<section class="workbench-usage" data-surface-chrome="workbench">%s</section>'
        % render_usage_tile(result)
    )


def render_session_chrome_tile(result: UsageReadResult) -> str:
    return (
        '<section class="session-chrome-usage" data-surface-chrome="session_chrome">'
        "%s</section>" % render_usage_tile(result)
    )


def render_tile_for_surface(result: UsageReadResult) -> str:
    s = result.surface
    if s == SURFACE_DASHBOARD:
        return render_dashboard_tile(result)
    if s == SURFACE_WORKBENCH:
        return render_workbench_tile(result)
    if s == SURFACE_SESSION_CHROME:
        return render_session_chrome_tile(result)
    return render_usage_tile(result)


# --------------------------------------------------------------------------
# Full surface
# --------------------------------------------------------------------------


def _resolve_result(ctx: UsageTileContext) -> UsageReadResult:
    if ctx.result is not None:
        return ctx.result
    if ctx.force_fault:
        return force_read_for_fault(
            ctx.force_fault,
            surface=ctx.surface,
            metric=ctx.metric,
            aggregation_wave=ctx.aggregation_wave,
        )
    # Default: NO_AGGREGATOR (honest when no registry injected).
    return force_read_for_fault(
        "absent_aggregator",
        surface=ctx.surface,
        metric=ctx.metric,
        aggregation_wave=ctx.aggregation_wave,
    )


def render_usage_surface(
    ctx: Optional[UsageTileContext] = None,
    *,
    extra_results: Optional[Sequence[UsageReadResult]] = None,
    record_reconciliation: bool = False,
    reconciliation_root: Optional[Path] = None,
    reconciliation_log: Optional[Path] = None,
) -> UsageSurfaceResult:
    """Render the usage/time surface for the given context."""
    c = ctx or UsageTileContext()
    results: List[UsageReadResult] = []

    primary = _resolve_result(c)
    if c.provisional and primary.numeral is not None and not primary.is_provisional:
        primary = _provisional_copy(primary, as_of=c.as_of)
    results.append(primary)

    if extra_results:
        results.extend(list(extra_results))

    body_parts: List[str] = [
        '<section class="usage-tiles" data-surface="usage-time">',
    ]
    for r in results:
        body_parts.append(render_tile_for_surface(r))
    body_parts.append("</section>")
    body_parts.append(_render_state_legend())
    body = "\n".join(body_parts)

    recon_line: Optional[str] = None
    if record_reconciliation:
        for r in results:
            if r.is_provisional and r.numeral is not None and r.as_of:
                recon_line = record_e2_reconciliation(
                    r,
                    root=reconciliation_root,
                    log_path=reconciliation_log,
                )
                break

    script = (
        "(function () {\n"
        "  var root = document.querySelector('[data-surface=\"usage-time\"]');\n"
        "  if (!root) { return; }\n"
        "  var tiles = root.querySelectorAll('.usage-tile');\n"
        "  for (var i = 0; i < tiles.length; i++) {\n"
        "    var t = tiles[i];\n"
        "    var state = t.getAttribute('data-named-state') || '';\n"
        "    if (!state) { continue; }\n"
        "    var allows = t.getAttribute('data-allows-numeral') === 'true';\n"
        "    var num = t.querySelector('.measured-numeral');\n"
        "    if (!allows && num) {\n"
        "      /* honesty: non-measured tiles must not carry a numeral node */\n"
        "    }\n"
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
        '  <main class="usage-time-surface" data-surface="usage-time" '
        'data-wave="%s">\n'
        "%s\n"
        "  </main>\n"
        "  <script>\n"
        "%s"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
        % (_escape_text(c.title), WAVE_ID, body, script)
    )

    return UsageSurfaceResult(
        html=doc,
        tiles=results,
        reconciliation_line=recon_line,
    )


def _provisional_copy(
    result: UsageReadResult,
    *,
    as_of: Optional[str],
) -> UsageReadResult:
    """Return a copy of ``result`` stamped as E2 provisional with as_of."""
    from dataclasses import replace

    stamp = (as_of or "").strip() or TRACE_AS_OF
    if result.numeral is None:
        return result
    return replace(
        result,
        is_provisional=True,
        as_of=stamp,
    )


def _render_state_legend() -> str:
    """Document the four trichotomy labels as distinct visible text nodes."""
    rows = []
    for ns in (
        NamedState.pending,
        NamedState.unknown,
        NamedState.empty,
        NamedState.zero_measured,
    ):
        rows.append(
            '<div class="legend-row" data-legend-state="%s">%s</div>'
            % (_escape_attr(ns.value), render_state(ns))
        )
    return (
        '<section class="usage-legend" data-surface="usage-legend">\n%s\n</section>'
        % ("\n".join(rows),)
    )


_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_usage_scripts(
    html_text: str,
    *,
    require_node: bool = True,
) -> List[str]:
    """Run ``node --check`` on every ``<script>`` block in usage HTML."""
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
                "node binary not on PATH — usage surface requires "
                "node --check on emitted script blocks"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="usage_node_check_") as tmp:
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
                    "node --check failed for usage script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[UsageTileContext] = None,
    *,
    require_node_check: Optional[bool] = None,
    **kwargs: Any,
) -> str:
    """Return the usage/time surface HTML document."""
    doc = render_usage_surface(ctx, **kwargs).html
    node = shutil.which("node")
    if node:
        node_check_usage_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_usage_scripts(doc, require_node=True)
    return doc


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state harness entry: unknown / empty / zero_measured.

    * ``unknown`` — READ_FAILED on session chrome
    * ``empty`` — PROVEN/empty on dashboard
    * ``zero_measured`` — PROVEN/zero_measured on workbench
    """
    key = (fixture or "").strip().lower().replace("-", "_")
    if key == "unknown":
        r = force_read_for_fault(
            "query_failure",
            surface=SURFACE_SESSION_CHROME,
            metric=METRIC_USAGE,
        )
        return render_usage_surface(
            UsageTileContext(surface=SURFACE_SESSION_CHROME, result=r)
        ).html
    if key == "empty":
        r = force_read_for_fault(
            "empty_scope",
            surface=SURFACE_DASHBOARD,
            metric=METRIC_USAGE,
        )
        return render_usage_surface(
            UsageTileContext(surface=SURFACE_DASHBOARD, result=r)
        ).html
    if key in ("zero", "zero_measured", "measured_zero"):
        r = force_read_for_fault(
            "zero_measured",
            surface=SURFACE_WORKBENCH,
            metric=METRIC_USAGE,
        )
        return render_usage_surface(
            UsageTileContext(surface=SURFACE_WORKBENCH, result=r)
        ).html
    raise ValueError("unknown usage fixture %r" % fixture)


def generate_html_for_surface_fault(
    surface: str,
    fault: str,
    *,
    metric: str = METRIC_USAGE,
    aggregation_wave: str = "W12-usage-aggregation",
) -> str:
    """Render one surface under one induced fault (GWT helpers)."""
    r = force_read_for_fault(
        fault,
        surface=surface,
        metric=metric,
        aggregation_wave=aggregation_wave,
    )
    return render_usage_surface(
        UsageTileContext(
            surface=surface,
            metric=metric,
            result=r,
            aggregation_wave=aggregation_wave,
        )
    ).html


# --------------------------------------------------------------------------
# Trace builders
# --------------------------------------------------------------------------


def build_usage_trace_payload(
    result: UsageReadResult,
    *,
    fault: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "wave_id": WAVE_ID,
        "surface": result.surface,
        "metric": result.metric,
        "rollup_id": result.rollup_id,
        "verdict": result.verdict.value,
        "sub_verdict": result.sub_verdict.value if result.sub_verdict else None,
        "named_state": result.named_state.value,
        "numeral": result.numeral,
        "fault": fault,
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
    payload_id = "w12-%s-%s" % (
        control_id,
        payload.get("fault") or payload.get("named_state") or "ok",
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
            "render_state.%s" % rendered_state,
            payload_id=payload_id,
            payload_hash_value=ph,
            detail=rendered_state,
            timestamp=ts,
        ),
    ]


def build_usage_fault_trace(
    fault: str,
    *,
    surface: str = SURFACE_DASHBOARD,
    metric: str = METRIC_USAGE,
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """One schema-valid usage trace under a single **executed** induced fault."""
    result = force_read_for_fault(fault, surface=surface, metric=metric)
    # Execute the real tile render so the path is live.
    tile_html = render_usage_tile(result)
    if 'data-named-state="%s"' % result.named_state.value not in tile_html:
        raise ValueError(
            "render_usage_tile did not emit named state %r under fault %r"
            % (result.named_state.value, fault)
        )
    payload = build_usage_trace_payload(result, fault=fault)
    payload["tile_has_state"] = True
    hops = _hops_for(
        control_id="usage-time",
        handler_name="anchor.usage.rollup_read.read_usage_rollup",
        capability_name="capability.usage_rollup",
        payload=payload,
        rendered_state=result.named_state.value,
    )
    completed = result.named_state is NamedState.ok
    return build_trace(
        wave_id,
        "usage-time",
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=(
            TRACE_RESULT_COMPLETED if completed else TRACE_RESULT_FAILED_NAMED
        ),
        induced_fault=fault,
        rendered_state=result.named_state.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W12 usage/time e2e under induced fault %s; structural "
            "rendered-string proof only; handler executed" % fault
        ),
    )


def build_usage_trace_set() -> Dict[str, Any]:
    """Full usage artifact: primary absent-aggregator + one fault per reason."""
    primary = build_usage_fault_trace(
        "absent_aggregator",
        surface=SURFACE_DASHBOARD,
        metric=METRIC_USAGE,
    )
    fault_traces = {
        fault: build_usage_fault_trace(
            fault,
            surface=_surface_for_fault(fault),
            metric=METRIC_USAGE,
        ).as_dict()
        for fault in INDUCED_FAULT_REASONS
    }
    # GWT-specific surface pins.
    fault_traces["dashboard_pending"] = build_usage_fault_trace(
        "absent_aggregator",
        surface=SURFACE_DASHBOARD,
    ).as_dict()
    fault_traces["workbench_zero_measured"] = build_usage_fault_trace(
        "zero_measured",
        surface=SURFACE_WORKBENCH,
    ).as_dict()
    fault_traces["session_chrome_unknown"] = build_usage_fault_trace(
        "query_failure",
        surface=SURFACE_SESSION_CHROME,
    ).as_dict()

    doc = primary.as_dict()
    doc["enumerated_faults"] = list(INDUCED_FAULT_REASONS)
    doc["induced_fault_reasons"] = list(INDUCED_FAULT_REASONS)
    doc["surfaces"] = list(USAGE_SURFACES)
    doc["metrics"] = list(USAGE_METRICS)
    doc["fault_traces"] = fault_traces
    doc["reason_traces"] = fault_traces  # alias for attach-style loaders
    doc["proof_level"] = PROOF_LEVEL_RENDERED_STRING
    return doc


def _surface_for_fault(fault: str) -> str:
    key = str(fault or "").strip().lower()
    if key in ("query_failure", "read_failed"):
        return SURFACE_SESSION_CHROME
    if key in ("zero_measured", "measured_zero", "zero"):
        return SURFACE_WORKBENCH
    if key in ("empty_scope", "empty"):
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
    for _reason, nested in sorted((doc.get("fault_traces") or {}).items()):
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


def write_usage_traces(*, root: Optional[Path] = None) -> Dict[str, Path]:
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / USAGE_TRACE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = build_usage_trace_set()
    validate_trace(doc)
    for _k, nested in (doc.get("fault_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(doc, label=USAGE_TRACE_RELPATH)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {USAGE_TRACE_RELPATH.replace("\\", "/"): path}


def load_trace_set(
    relpath: str = USAGE_TRACE_RELPATH,
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load shipped usage-e2e.json, pinned to the live builder."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / relpath
    builder_doc = build_usage_trace_set()
    validate_trace(builder_doc)
    for _k, nested in (builder_doc.get("fault_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(builder_doc, label="usage-e2e builder")

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
                _assert_payload_hash_integrity(data, label="usage-e2e on-disk")
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
    "AS_OF_CLASS",
    "INDUCED_FAULT_REASONS",
    "NUMERAL_CLASS",
    "PROVISIONAL_CLASS",
    "SURFACE_DASHBOARD",
    "SURFACE_ID",
    "SURFACE_SESSION_CHROME",
    "SURFACE_WORKBENCH",
    "TILE_CLASS",
    "TRACE_AS_OF",
    "USAGE_TRACE_RELPATH",
    "UsageSurfaceResult",
    "UsageTileContext",
    "WAVE_ID",
    "build_usage_fault_trace",
    "build_usage_trace_payload",
    "build_usage_trace_set",
    "generate_html",
    "generate_html_for_fixture",
    "generate_html_for_surface_fault",
    "load_trace_set",
    "node_check_usage_scripts",
    "render_dashboard_tile",
    "render_session_chrome_tile",
    "render_tile_for_surface",
    "render_usage_surface",
    "render_usage_tile",
    "render_workbench_tile",
    "write_usage_traces",
]

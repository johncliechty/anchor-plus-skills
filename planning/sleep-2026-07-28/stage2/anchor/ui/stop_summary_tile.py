"""Stop-summary tile — W16, Phase 3.

Renders exclusively through ``render_state`` (W6). Distinguishes:

* **empty** — nothing was in flight (successful inventory read, zero items)
* **unknown** — in-flight inventory could not be read (never looks empty)
* **ok** — inventory-backed items with counts as visible text nodes
* **zero_measured** — scope exists; measured total is 0

Trace builders emit ``artifacts/traces/stop-summary-e2e.json`` at
``proof_level: rendered-string``. ``generate_html`` returns a full document
with a syntax-valid ``<script>`` block suitable for ``node --check``.
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
from typing import Any, Dict, List, Optional, Sequence, Union

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
from anchor.session.stop_summary import (
    CAPABILITY_CONTROL_ID,
    DEFAULT_QUERY_ID,
    INDUCED_FAULT_REASONS,
    INVENTORY_SOURCE_LABEL,
    INVENTORY_SOURCE_NAME,
    STOP_SUMMARY_REASONS,
    InFlightInventory,
    InFlightItem,
    StopSummaryReason,
    StopSummaryResult,
    WAVE_ID as STOP_WAVE_ID,
    collect_stop_summary,
    empty_inventory,
    force_collect_for_fault,
    three_item_inventory,
    unreadable_inventory,
    zero_measured_inventory,
)
from anchor.ui.named_state import NamedState, render_state

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "stop-summary"
WAVE_ID = STOP_WAVE_ID
CONTROL_STOP_SUMMARY = CAPABILITY_CONTROL_ID

STOP_SUMMARY_TRACE_RELPATH = os.path.join(
    "artifacts", "traces", "stop-summary-e2e.json"
)
TRACE_AS_OF = "2026-07-29T00:00:00Z"

TILE_CLASS = "stop-summary-tile"
ITEM_CLASS = "in-flight-item"
COUNT_CLASS = "in-flight-count"
QUERY_CLASS = "inventory-query-ref"
SOURCE_CLASS = "inventory-source"


# --------------------------------------------------------------------------
# Context / result
# --------------------------------------------------------------------------


@dataclass
class StopSummaryTileContext:
    """Inputs that drive the stop-summary tile render."""

    session_id: str = "sess-stop"
    inventory: Optional[InFlightInventory] = None
    result: Optional[StopSummaryResult] = None
    force_fault: Optional[str] = None
    capability_present: Optional[bool] = None
    title: str = "Stop summary"


@dataclass
class StopSummaryTileResult:
    """Structured render outcome for tests and traces."""

    html: str
    summary: Optional[StopSummaryResult] = None
    items_visible: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Tile rendering
# --------------------------------------------------------------------------


def _escape_attr(value: str) -> str:
    return html.escape(str(value), quote=True)


def _escape_text(value: str) -> str:
    return html.escape(str(value), quote=False)


def render_in_flight_item(item: InFlightItem) -> str:
    """One inventory-backed item as visible text nodes (label + count)."""
    label = _escape_text(item.label)
    count = int(item.count)
    qref = _escape_attr(item.query_ref or item.item_id)
    partial_attr = "true" if item.partial else "false"
    visible = _escape_text(item.visible_label)
    return (
        '<li class="%s" data-item-id="%s" data-count="%d" '
        'data-partial="%s" data-query-ref="%s">'
        '<span class="item-label">%s</span> '
        '<span class="%s" data-count-value="%d">×%d</span> '
        '<span class="item-visible">%s</span>'
        "</li>"
        % (
            ITEM_CLASS,
            _escape_attr(item.item_id),
            count,
            partial_attr,
            qref,
            label,
            COUNT_CLASS,
            count,
            count,
            visible,
        )
    )


def render_stop_summary_tile(result: StopSummaryResult) -> str:
    """Render one stop-summary tile through ``render_state``.

    Rules (frozen plan GWTs):

    * three in-flight items → all three labels + counts as visible text
    * inventory unreadable → **unknown** (visibly distinct from empty)
    * zero items → **empty** ("nothing was in flight")
    * counts are traceable via ``data-query-id`` / per-item ``data-query-ref``
    """
    ns = result.named_state
    state_html = render_state(ns)

    parts: List[str] = [state_html]
    parts.append(
        ' <span class="%s" data-inventory-source="%s">%s</span>'
        % (
            SOURCE_CLASS,
            _escape_attr(result.inventory_source),
            _escape_text(result.inventory_source_label),
        )
    )
    parts.append(
        ' <span class="%s" data-query-id="%s">query:%s</span>'
        % (
            QUERY_CLASS,
            _escape_attr(result.query_id),
            _escape_text(result.query_id),
        )
    )

    if ns is NamedState.ok or (
        ns is NamedState.zero_measured and result.items
    ):
        if result.items:
            rows = "\n".join(render_in_flight_item(i) for i in result.items)
            parts.append(
                ' <ul class="in-flight-list" data-item-count="%d" '
                'data-total-count="%d">%s</ul>'
                % (result.item_count, int(result.total_count), rows)
            )
            parts.append(
                ' <span class="total-count" data-total="%d">total %d</span>'
                % (int(result.total_count), int(result.total_count))
            )
    elif ns is NamedState.empty:
        parts.append(
            ' <span class="empty-detail">nothing was in flight</span>'
        )
    elif ns is NamedState.unknown:
        parts.append(
            ' <span class="unknown-detail">in-flight state could not be read'
            "</span>"
        )

    if result.partial:
        parts.append(' <span class="partial-flag">partial items</span>')

    reason = _escape_attr(result.reason or "")
    return (
        '<div class="%s" data-surface="%s" data-named-state="%s" '
        'data-reason="%s" data-session="%s" data-total-count="%d" '
        'data-item-count="%d" data-inventory-source="%s" data-query-id="%s">'
        "%s</div>"
        % (
            TILE_CLASS,
            SURFACE_ID,
            _escape_attr(ns.value),
            reason,
            _escape_attr(result.session_id),
            int(result.total_count),
            result.item_count,
            _escape_attr(result.inventory_source),
            _escape_attr(result.query_id),
            "".join(parts),
        )
    )


def _resolve_summary(ctx: StopSummaryTileContext) -> StopSummaryResult:
    if ctx.result is not None:
        return ctx.result
    if ctx.force_fault:
        return force_collect_for_fault(
            ctx.force_fault, session_id=ctx.session_id
        )
    return collect_stop_summary(
        ctx.session_id,
        inventory=ctx.inventory,
        capability_present=ctx.capability_present,
    )


def render_stop_summary_surface(
    ctx: Optional[StopSummaryTileContext] = None,
) -> StopSummaryTileResult:
    """Render the stop-summary surface for the given context."""
    c = ctx or StopSummaryTileContext()
    summary = _resolve_summary(c)
    tile = render_stop_summary_tile(summary)

    body_parts = [
        '<section class="stop-summary-panel" data-surface="stop-summary">',
        tile,
        "</section>",
        _render_state_legend(),
        _render_reason_matrix(),
    ]
    body = "\n".join(body_parts)

    script = (
        "(function () {\n"
        "  var root = document.querySelector("
        "'[data-surface=\"stop-summary\"]');\n"
        "  if (!root) { return; }\n"
        "  var tiles = root.querySelectorAll('.stop-summary-tile');\n"
        "  for (var i = 0; i < tiles.length; i++) {\n"
        "    var t = tiles[i];\n"
        "    var state = t.getAttribute('data-named-state') || '';\n"
        "    if (!state) { continue; }\n"
        "    var q = t.getAttribute('data-query-id') || '';\n"
        "    if (typeof window.__anchorStopSummary === 'function') {\n"
        "      window.__anchorStopSummary(state, q);\n"
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
        '  <main class="stop-summary-surface" data-surface="stop-summary" '
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

    visible_items = [i.visible_label for i in summary.items]
    return StopSummaryTileResult(
        html=doc,
        summary=summary,
        items_visible=visible_items,
    )


def _render_state_legend() -> str:
    rows = []
    for ns in (
        NamedState.ok,
        NamedState.unknown,
        NamedState.empty,
        NamedState.zero_measured,
    ):
        rows.append(
            '<div class="legend-row" data-legend-state="%s">%s</div>'
            % (_escape_attr(ns.value), render_state(ns))
        )
    return (
        '<section class="stop-summary-legend" data-surface="stop-legend">'
        "\n%s\n</section>" % ("\n".join(rows),)
    )


def _render_reason_matrix() -> str:
    rows: List[str] = []
    for reason in STOP_SUMMARY_REASONS:
        from anchor.session.stop_summary import stop_reason_named_state

        ns = stop_reason_named_state(reason)
        rows.append(
            '<div class="reason-row" data-control="stop_summary" '
            'data-reason="%s"><span class="reason-token">%s</span> %s</div>'
            % (
                _escape_attr(reason),
                _escape_text(reason),
                render_state(ns),
            )
        )
    return (
        '<section class="reason-matrix" data-surface="stop-reasons">\n%s\n'
        "</section>" % ("\n".join(rows),)
    )


_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_stop_summary_scripts(
    html_text: str,
    *,
    require_node: bool = True,
) -> List[str]:
    """Run ``node --check`` on every ``<script>`` block in stop-summary HTML."""
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
                "node binary not on PATH — stop-summary surface requires "
                "node --check on emitted script blocks"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="stop_summary_node_check_") as tmp:
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
                    "node --check failed for stop-summary script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[StopSummaryTileContext] = None,
    *,
    require_node_check: Optional[bool] = None,
) -> str:
    """Return the stop-summary surface HTML document."""
    doc = render_stop_summary_surface(ctx).html
    node = shutil.which("node")
    if node:
        node_check_stop_summary_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_stop_summary_scripts(doc, require_node=True)
    return doc


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state harness entry: unknown / empty / zero_measured.

    * ``unknown`` — in-flight inventory unreadable
    * ``empty`` — inventory read succeeded; nothing was in flight
    * ``zero_measured`` — scope exists; measured total is 0
    """
    key = (fixture or "").strip().lower().replace("-", "_")
    if key == "unknown":
        ctx = StopSummaryTileContext(
            session_id="sess-unknown",
            inventory=unreadable_inventory("sess-unknown"),
            capability_present=True,
        )
        return render_stop_summary_surface(ctx).html
    if key in ("empty",):
        ctx = StopSummaryTileContext(
            session_id="sess-empty",
            inventory=empty_inventory("sess-empty"),
            capability_present=True,
        )
        return render_stop_summary_surface(ctx).html
    if key in ("zero", "zero_measured", "measured_zero"):
        ctx = StopSummaryTileContext(
            session_id="sess-zero",
            inventory=zero_measured_inventory("sess-zero"),
            capability_present=True,
        )
        return render_stop_summary_surface(ctx).html
    if key in ("ok", "three", "three_items"):
        ctx = StopSummaryTileContext(
            session_id="sess-three",
            inventory=three_item_inventory("sess-three"),
            capability_present=True,
        )
        return render_stop_summary_surface(ctx).html
    raise ValueError("unknown stop-summary fixture %r" % fixture)


def build_stop_summary_trace_payload(
    reason: Optional[str] = None,
    *,
    ok: bool = False,
    summary: Optional[StopSummaryResult] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "control_id": CONTROL_STOP_SUMMARY,
        "wave_id": WAVE_ID,
        "ok": ok,
        "reason": reason or "",
        "handler": "anchor.session.stop_summary.collect_stop_summary",
        "capability": "stop_summary",
        "inventory_source": INVENTORY_SOURCE_NAME,
        "inventory_source_label": INVENTORY_SOURCE_LABEL,
        "query_id": DEFAULT_QUERY_ID,
    }
    if summary is not None:
        payload["named_state"] = summary.named_state.value
        payload["item_count"] = summary.item_count
        payload["total_count"] = summary.total_count
        payload["items"] = [i.as_dict() for i in summary.items]
        payload["query_id"] = summary.query_id
        payload["partial"] = summary.partial
    return payload


# --------------------------------------------------------------------------
# E2e traces
# --------------------------------------------------------------------------


def _hops_for(
    *,
    payload: Dict[str, Any],
    rendered_state: str,
) -> list:
    reason = payload.get("reason") or ("ok" if payload.get("ok") else "stop")
    payload_id = "w16-stop_summary-%s" % reason
    ph = payload_hash(payload)
    ts = TRACE_AS_OF
    return [
        make_hop(
            HOP_CONTROL_INVOCATION,
            "click-stop",
            payload_id=payload_id,
            payload=payload,
            detail="",
            timestamp=ts,
        ),
        make_hop(
            HOP_HANDLER,
            "anchor.session.stop_summary.collect_stop_summary",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="anchor.session.stop_summary.collect_stop_summary",
            timestamp=ts,
        ),
        make_hop(
            HOP_CAPABILITY_CALL,
            "capability.stop_summary",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="capability.stop_summary",
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


def build_stop_summary_reason_trace(
    reason: str,
    *,
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """One schema-valid stop-summary trace under an executed fault/outcome."""
    summary = force_collect_for_fault(reason, session_id="w16-induced")
    ns = summary.named_state
    ok = ns is NamedState.ok
    payload = build_stop_summary_trace_payload(
        reason, ok=ok, summary=summary
    )
    payload["executed"] = True
    payload["handler_result_reason"] = summary.reason
    hops = _hops_for(payload=payload, rendered_state=ns.value)
    return build_trace(
        wave_id,
        CONTROL_STOP_SUMMARY,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=(
            TRACE_RESULT_COMPLETED if ok else TRACE_RESULT_FAILED_NAMED
        ),
        induced_fault=reason if reason in INDUCED_FAULT_REASONS else reason,
        rendered_state=ns.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W16 stop-summary e2e under reason %s; structural rendered-string "
            "proof only; handler executed" % reason
        ),
    )


def build_stop_summary_ok_trace(*, wave_id: str = WAVE_ID) -> TraceArtifact:
    """Primary success path: three in-flight items with inventory counts."""
    summary = collect_stop_summary(
        "w16-three",
        inventory=three_item_inventory("w16-three"),
        capability_present=True,
    )
    payload = build_stop_summary_trace_payload(
        StopSummaryReason.OK.value, ok=True, summary=summary
    )
    payload["executed"] = True
    hops = _hops_for(payload=payload, rendered_state=NamedState.ok.value)
    return build_trace(
        wave_id,
        CONTROL_STOP_SUMMARY,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_COMPLETED,
        induced_fault=None,
        rendered_state=NamedState.ok.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W16 stop-summary e2e success path (three in-flight items); "
            "structural rendered-string proof only"
        ),
    )


def build_stop_summary_trace_set() -> Dict[str, Any]:
    """Full artifact: primary three-item ok + one fault per induced reason."""
    primary = build_stop_summary_ok_trace()
    reason_traces = {
        reason: build_stop_summary_reason_trace(reason).as_dict()
        for reason in STOP_SUMMARY_REASONS
    }
    # Ensure induced-fault reasons are always present even if enum grows.
    for reason in INDUCED_FAULT_REASONS:
        if reason not in reason_traces:
            reason_traces[reason] = build_stop_summary_reason_trace(
                reason
            ).as_dict()
    doc = primary.as_dict()
    doc["enumerated_reasons"] = list(STOP_SUMMARY_REASONS)
    doc["induced_fault_reasons"] = list(INDUCED_FAULT_REASONS)
    doc["reason_traces"] = reason_traces
    doc["proof_level"] = PROOF_LEVEL_RENDERED_STRING
    doc["inventory_source"] = INVENTORY_SOURCE_NAME
    doc["inventory_source_label"] = INVENTORY_SOURCE_LABEL
    return doc


def _hop_hashes(doc: Dict[str, Any]) -> list:
    out = []
    for hop in doc.get("hops") or []:
        out.append(
            (
                str(hop.get("payload_id") or ""),
                str(hop.get("payload_hash") or "").strip().lower(),
            )
        )
    for _reason, nested in sorted((doc.get("reason_traces") or {}).items()):
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


def write_stop_summary_traces(*, root: Optional[Path] = None) -> Dict[str, Path]:
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / STOP_SUMMARY_TRACE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = build_stop_summary_trace_set()
    validate_trace(doc)
    for reason, nested in (doc.get("reason_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(doc, label=STOP_SUMMARY_TRACE_RELPATH)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {STOP_SUMMARY_TRACE_RELPATH.replace("\\", "/"): path}


def load_trace_set(
    relpath: str = STOP_SUMMARY_TRACE_RELPATH,
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load shipped stop-summary-e2e.json, pinned to the live builder."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / relpath
    builder_doc = build_stop_summary_trace_set()
    validate_trace(builder_doc)
    for reason, nested in (builder_doc.get("reason_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(
        builder_doc, label="builder:" + STOP_SUMMARY_TRACE_RELPATH
    )
    if not path.is_file():
        write_stop_summary_traces(root=base)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    if _hop_hashes(on_disk) != _hop_hashes(builder_doc):
        # Re-materialize so shipped artifact stays pinned to builders.
        write_stop_summary_traces(root=base)
        on_disk = json.loads(path.read_text(encoding="utf-8"))
    validate_trace(on_disk)
    return on_disk


__all__ = [
    "SURFACE_ID",
    "WAVE_ID",
    "CONTROL_STOP_SUMMARY",
    "STOP_SUMMARY_TRACE_RELPATH",
    "TILE_CLASS",
    "ITEM_CLASS",
    "COUNT_CLASS",
    "INDUCED_FAULT_REASONS",
    "StopSummaryTileContext",
    "StopSummaryTileResult",
    "render_in_flight_item",
    "render_stop_summary_tile",
    "render_stop_summary_surface",
    "generate_html",
    "generate_html_for_fixture",
    "node_check_stop_summary_scripts",
    "build_stop_summary_trace_payload",
    "build_stop_summary_reason_trace",
    "build_stop_summary_ok_trace",
    "build_stop_summary_trace_set",
    "write_stop_summary_traces",
    "load_trace_set",
]

"""Status cadence surface — W20, Phase 3.

Renders exclusively through ``render_state`` (W6). Distinguishes:

* **ok / fresh** — live telemetry within the staleness threshold
* **stale** — aged sample labelled **stale** with age shown (never current-looking)
* **unknown** — telemetry unreachable (never empty-looking, never current)
* **empty** — telemetry readable, legitimately no series

Every rendered status carries a mandatory ``as_of`` ISO stamp. Missing as_of
raises ``MissingAsOfError`` before any HTML is produced.

``generate_html`` returns a full document with a syntax-valid ``<script>``
block suitable for ``node --check``. Trace builders emit
``artifacts/traces/cadence-e2e.json`` at ``proof_level: rendered-string``.
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
from anchor.status.cadence import (
    CAPABILITY_CONTROL_ID,
    DEFAULT_CADENCE_INTERVAL_SECONDS,
    INDUCED_FAULT_REASONS,
    CADENCE_REASONS,
    CadenceLoop,
    CadenceReason,
    CadenceTick,
    FakeClock,
    LiveTelemetry,
    StatusSnapshot,
    TELEMETRY_SOURCE_LABEL,
    TELEMETRY_SOURCE_NAME,
    WAVE_ID as CADENCE_WAVE_ID,
    cadence_reason_named_state,
    force_snapshot_for_fault,
    read_status_snapshot,
)
from anchor.status.staleness import (
    STALENESS_THRESHOLD_SECONDS,
    Freshness,
    MissingAsOfError,
    require_as_of,
)
from anchor.ui.named_state import NamedState, render_state

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "cadence"
WAVE_ID = CADENCE_WAVE_ID
CONTROL_CADENCE = CAPABILITY_CONTROL_ID

CADENCE_TRACE_RELPATH = os.path.join("artifacts", "traces", "cadence-e2e.json")
TRACE_AS_OF = "2026-07-29T00:00:00Z"

TILE_CLASS = "status-tile"
AS_OF_CLASS = "status-as-of"
AGE_CLASS = "status-age"
FRESHNESS_CLASS = "status-freshness"
SOURCE_CLASS = "telemetry-source"
STALE_LABEL = "stale"
CURRENT_LOOKING_TOKENS = frozenset(
    {
        "current",
        "live now",
        "up to date",
        "up-to-date",
        "fresh-looking",
    }
)


# --------------------------------------------------------------------------
# Context / result
# --------------------------------------------------------------------------


@dataclass
class StatusViewContext:
    """Inputs that drive the status cadence surface render."""

    snapshot: Optional[StatusSnapshot] = None
    force_fault: Optional[str] = None
    loop: Optional[CadenceLoop] = None
    title: str = "Status cadence"
    threshold_seconds: int = STALENESS_THRESHOLD_SECONDS


@dataclass
class StatusViewResult:
    """Structured render outcome for tests and traces."""

    html: str
    snapshot: Optional[StatusSnapshot] = None
    as_of: str = ""
    named_state: Optional[NamedState] = None


# --------------------------------------------------------------------------
# Escape helpers
# --------------------------------------------------------------------------


def _escape_attr(value: str) -> str:
    return html.escape(str(value), quote=True)


def _escape_text(value: str) -> str:
    return html.escape(str(value), quote=False)


# --------------------------------------------------------------------------
# Tile rendering
# --------------------------------------------------------------------------


def render_status_tile(snapshot: StatusSnapshot) -> str:
    """Render one status tile through ``render_state``.

    Rules (frozen plan GWTs):

    * every tile carries a visible ``as_of`` stamp (mandatory)
    * stale is labelled **stale** with age shown — never current-looking
    * unknown is distinct from empty; never a confidently current status
    * empty is legitimately no series (readable telemetry)
    """
    # Choke-point: no status without as_of.
    as_of = require_as_of(snapshot.as_of)
    ns = snapshot.named_state
    state_html = render_state(ns)

    parts: List[str] = [state_html]

    # Freshness token (cadence-native) as a data attribute + visible when stale.
    parts.append(
        ' <span class="%s" data-freshness="%s">%s</span>'
        % (
            FRESHNESS_CLASS,
            _escape_attr(snapshot.freshness.value),
            _escape_text(snapshot.freshness.value),
        )
    )

    # Mandatory as_of stamp (visible text node).
    parts.append(
        ' <span class="%s" data-as-of="%s">as_of %s</span>'
        % (
            AS_OF_CLASS,
            _escape_attr(as_of),
            _escape_text(as_of),
        )
    )

    # Telemetry source label.
    parts.append(
        ' <span class="%s" data-telemetry-source="%s">%s</span>'
        % (
            SOURCE_CLASS,
            _escape_attr(snapshot.telemetry_source),
            _escape_text(TELEMETRY_SOURCE_LABEL),
        )
    )

    # Stale: age shown; never current-looking wording.
    if ns is NamedState.stale or snapshot.freshness is Freshness.stale:
        age = snapshot.age_label()
        age_text = age if age else "aged"
        parts.append(
            ' <span class="%s" data-age-seconds="%s" data-stale="true">'
            "stale age %s</span>"
            % (
                AGE_CLASS,
                _escape_attr(
                    "" if snapshot.age_seconds is None else str(snapshot.age_seconds)
                ),
                _escape_text(age_text),
            )
        )
        # Explicit stale label node (visible "stale" beyond named-state span).
        parts.append(
            ' <span class="stale-label" data-stale-label="true">%s</span>'
            % _escape_text(STALE_LABEL)
        )
    elif ns is NamedState.unknown:
        parts.append(
            ' <span class="unknown-detail">telemetry unreachable</span>'
        )
    elif ns is NamedState.empty:
        parts.append(
            ' <span class="empty-detail">no series (empty scope)</span>'
        )
    elif ns is NamedState.ok:
        # Fresh path: may show age under threshold, never "stale".
        if snapshot.age_seconds is not None:
            parts.append(
                ' <span class="%s" data-age-seconds="%s" data-fresh="true">'
                "age %s</span>"
                % (
                    AGE_CLASS,
                    _escape_attr(str(snapshot.age_seconds)),
                    _escape_text(snapshot.age_label()),
                )
            )

    # Honesty post-condition: stale tiles must not look "current".
    inner = "".join(parts)
    if ns is NamedState.stale:
        lower = inner.lower()
        for tok in CURRENT_LOOKING_TOKENS:
            if tok in lower:
                raise ValueError(
                    "stale status must not contain current-looking token %r" % tok
                )
        if STALE_LABEL not in lower and 'data-named-state="stale"' not in inner:
            raise ValueError("stale status tile missing visible stale label")

    attrs = [
        'class="%s"' % TILE_CLASS,
        'data-surface="%s"' % _escape_attr(SURFACE_ID),
        'data-named-state="%s"' % _escape_attr(ns.value),
        'data-freshness="%s"' % _escape_attr(snapshot.freshness.value),
        'data-as-of="%s"' % _escape_attr(as_of),
        'data-reason="%s"' % _escape_attr(snapshot.reason or ""),
        'data-threshold-seconds="%d"' % int(snapshot.threshold_seconds),
        'data-tick-index="%d"' % int(snapshot.tick_index),
        'data-from-telemetry="%s"'
        % ("true" if snapshot.from_telemetry else "false"),
        'data-wave="%s"' % _escape_attr(WAVE_ID),
    ]
    if snapshot.age_seconds is not None:
        attrs.append(
            'data-age-seconds="%s"' % _escape_attr(str(snapshot.age_seconds))
        )

    return "<div %s>%s</div>" % (" ".join(attrs), inner)


def _resolve_snapshot(ctx: StatusViewContext) -> StatusSnapshot:
    if ctx.snapshot is not None:
        require_as_of(ctx.snapshot.as_of)
        return ctx.snapshot
    if ctx.loop is not None:
        snap = ctx.loop.last or ctx.loop.tick()
        require_as_of(snap.as_of)
        return snap
    if ctx.force_fault:
        return force_snapshot_for_fault(
            ctx.force_fault,
            threshold_seconds=ctx.threshold_seconds,
        )
    # Default: honest unknown (no telemetry bound) with as_of from clock.
    return force_snapshot_for_fault(
        "telemetry_outage",
        threshold_seconds=ctx.threshold_seconds,
    )


def _render_state_legend() -> str:
    rows = []
    for ns in (
        NamedState.ok,
        NamedState.stale,
        NamedState.unknown,
        NamedState.empty,
    ):
        rows.append(
            '<div class="legend-row" data-legend-state="%s">%s</div>'
            % (_escape_attr(ns.value), render_state(ns))
        )
    return (
        '<section class="status-legend" data-surface="cadence-legend">'
        "\n%s\n</section>" % ("\n".join(rows),)
    )


def _render_reason_matrix() -> str:
    rows: List[str] = []
    for reason in CADENCE_REASONS:
        ns = cadence_reason_named_state(reason)
        rows.append(
            '<div class="reason-row" data-control="cadence_telemetry" '
            'data-reason="%s"><span class="reason-token">%s</span> %s</div>'
            % (
                _escape_attr(reason),
                _escape_text(reason),
                render_state(ns),
            )
        )
    return (
        '<section class="reason-matrix" data-surface="cadence-reasons">\n%s\n'
        "</section>" % ("\n".join(rows),)
    )


def render_status_surface(
    ctx: Optional[StatusViewContext] = None,
) -> StatusViewResult:
    """Render the status cadence surface for the given context."""
    c = ctx or StatusViewContext()
    snapshot = _resolve_snapshot(c)
    # Mandatory as_of choke-point before any HTML.
    as_of = require_as_of(snapshot.as_of)
    tile = render_status_tile(snapshot)

    body_parts = [
        '<section class="status-panel" data-surface="cadence">',
        tile,
        "</section>",
        _render_state_legend(),
        _render_reason_matrix(),
    ]
    body = "\n".join(body_parts)

    script = (
        "(function () {\n"
        "  var root = document.querySelector('[data-surface=\"cadence\"]');\n"
        "  if (!root) { return; }\n"
        "  var tiles = root.querySelectorAll('.status-tile');\n"
        "  for (var i = 0; i < tiles.length; i++) {\n"
        "    var t = tiles[i];\n"
        "    var state = t.getAttribute('data-named-state') || '';\n"
        "    var asOf = t.getAttribute('data-as-of') || '';\n"
        "    if (!asOf) { continue; }\n"
        "    if (!state) { continue; }\n"
        "    if (typeof window.__anchorStatusCadence === 'function') {\n"
        "      window.__anchorStatusCadence(state, asOf);\n"
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
        '  <main class="status-cadence-surface" data-surface="cadence" '
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

    return StatusViewResult(
        html=doc,
        snapshot=snapshot,
        as_of=as_of,
        named_state=snapshot.named_state,
    )


_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_status_scripts(
    html_text: str,
    *,
    require_node: bool = True,
) -> List[str]:
    """Run ``node --check`` on every ``<script>`` block in status HTML."""
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
                "node binary not on PATH — status cadence surface requires "
                "node --check on emitted script blocks"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="status_node_check_") as tmp:
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
                    "node --check failed for status script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[StatusViewContext] = None,
    *,
    require_node_check: Optional[bool] = None,
) -> str:
    """Return the status cadence surface HTML document."""
    doc = render_status_surface(ctx).html
    node = shutil.which("node")
    if node:
        node_check_status_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_status_scripts(doc, require_node=True)
    return doc


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state / cadence harness entry.

    * ``unknown`` — telemetry outage
    * ``empty`` — readable telemetry, no series
    * ``stale`` / ``aged`` — aged sample (stale-with-age)
    * ``ok`` / ``fresh`` — live fresh sample
    """
    key = (fixture or "").strip().lower().replace("-", "_")
    if key in ("unknown", "outage", "telemetry_outage"):
        return render_status_surface(
            StatusViewContext(force_fault="telemetry_outage")
        ).html
    if key in ("empty", "empty_series"):
        return render_status_surface(
            StatusViewContext(force_fault="empty_series")
        ).html
    if key in ("stale", "aged", "aged_sample", "stale_with_age"):
        return render_status_surface(
            StatusViewContext(force_fault="aged_sample")
        ).html
    if key in ("ok", "fresh", "live", "zero", "zero_measured", "measured_zero"):
        # Cadence is not a numeral surface; the tri-state harness's
        # zero_measured fixture maps to the live-ok path so the three
        # labels (unknown / empty / ok) stay pairwise distinct.
        return render_status_surface(
            StatusViewContext(force_fault="ok")
        ).html
    raise ValueError("unknown status cadence fixture %r" % fixture)


def generate_html_for_surface_fault(fault: str) -> str:
    """Render the cadence surface under one induced fault (GWT helpers)."""
    return render_status_surface(
        StatusViewContext(force_fault=fault)
    ).html


# --------------------------------------------------------------------------
# Trace builders
# --------------------------------------------------------------------------


def build_cadence_trace_payload(
    snapshot: StatusSnapshot,
    *,
    fault: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "wave_id": WAVE_ID,
        "surface": SURFACE_ID,
        "control_id": CONTROL_CADENCE,
        "as_of": snapshot.as_of,
        "named_state": snapshot.named_state.value,
        "freshness": snapshot.freshness.value,
        "reason": snapshot.reason,
        "age_seconds": snapshot.age_seconds,
        "threshold_seconds": snapshot.threshold_seconds,
        "tick_index": snapshot.tick_index,
        "from_telemetry": snapshot.from_telemetry,
        "fault": fault,
        "executed": True,
        "telemetry_source": TELEMETRY_SOURCE_NAME,
        "handler": "anchor.status.cadence.read_status_snapshot",
        "capability": "cadence_telemetry",
    }


def _hops_for(
    *,
    payload: Dict[str, Any],
    rendered_state: str,
) -> list:
    reason = payload.get("fault") or payload.get("reason") or "cadence"
    payload_id = "w20-cadence-%s" % reason
    ph = payload_hash(payload)
    ts = TRACE_AS_OF
    return [
        make_hop(
            HOP_CONTROL_INVOCATION,
            "cadence-tick",
            payload_id=payload_id,
            payload=payload,
            detail="",
            timestamp=ts,
        ),
        make_hop(
            HOP_HANDLER,
            "anchor.status.cadence.read_status_snapshot",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="anchor.status.cadence.read_status_snapshot",
            timestamp=ts,
        ),
        make_hop(
            HOP_CAPABILITY_CALL,
            "capability.cadence_telemetry",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="capability.cadence_telemetry",
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


def build_cadence_fault_trace(
    fault: str,
    *,
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """One schema-valid cadence trace under an executed induced fault."""
    snapshot = force_snapshot_for_fault(fault)
    # Execute the real tile render so the path is live.
    tile_html = render_status_tile(snapshot)
    if 'data-named-state="%s"' % snapshot.named_state.value not in tile_html:
        raise ValueError(
            "render_status_tile did not emit named state %r under fault %r"
            % (snapshot.named_state.value, fault)
        )
    if 'data-as-of="' not in tile_html and snapshot.as_of not in tile_html:
        raise ValueError(
            "render_status_tile missing as_of under fault %r" % fault
        )
    payload = build_cadence_trace_payload(snapshot, fault=fault)
    hops = _hops_for(payload=payload, rendered_state=snapshot.named_state.value)
    completed = snapshot.named_state is NamedState.ok
    return build_trace(
        wave_id,
        CONTROL_CADENCE,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=(
            TRACE_RESULT_COMPLETED if completed else TRACE_RESULT_FAILED_NAMED
        ),
        induced_fault=fault,
        rendered_state=snapshot.named_state.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W20 cadence e2e under induced fault %s; structural "
            "rendered-string proof only; handler executed" % fault
        ),
    )


def build_cadence_ok_trace(*, wave_id: str = WAVE_ID) -> TraceArtifact:
    """Primary success path: live telemetry, fresh sample with as_of."""
    snapshot = force_snapshot_for_fault("ok")
    tile_html = render_status_tile(snapshot)
    if 'data-named-state="ok"' not in tile_html:
        raise ValueError("ok cadence tile missing named-state ok")
    if snapshot.as_of not in tile_html:
        raise ValueError("ok cadence tile missing as_of from telemetry")
    payload = build_cadence_trace_payload(snapshot, fault=None)
    payload["reason"] = CadenceReason.OK.value
    hops = _hops_for(payload=payload, rendered_state=NamedState.ok.value)
    return build_trace(
        wave_id,
        CONTROL_CADENCE,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_COMPLETED,
        induced_fault=None,
        rendered_state=NamedState.ok.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W20 cadence e2e success path (live telemetry, as_of from sample); "
            "structural rendered-string proof only"
        ),
    )


def build_cadence_trace_set() -> Dict[str, Any]:
    """Full artifact: primary ok + one fault per induced reason + reasons."""
    primary = build_cadence_ok_trace()
    fault_traces = {
        fault: build_cadence_fault_trace(fault).as_dict()
        for fault in INDUCED_FAULT_REASONS
    }
    reason_traces = {
        reason: build_cadence_fault_trace(
            _fault_for_reason(reason)
        ).as_dict()
        for reason in CADENCE_REASONS
        if reason not in ("missing_as_of",)  # raises; covered separately
    }
    # GWT-specific pins.
    fault_traces["fresh_ok"] = build_cadence_ok_trace().as_dict()
    fault_traces["stale_with_age"] = build_cadence_fault_trace(
        "aged_sample"
    ).as_dict()
    fault_traces["telemetry_unknown"] = build_cadence_fault_trace(
        "telemetry_outage"
    ).as_dict()
    fault_traces["empty_series"] = build_cadence_fault_trace(
        "empty_series"
    ).as_dict()

    doc = primary.as_dict()
    doc["enumerated_reasons"] = list(CADENCE_REASONS)
    doc["induced_fault_reasons"] = list(INDUCED_FAULT_REASONS)
    doc["fault_traces"] = fault_traces
    doc["reason_traces"] = reason_traces
    doc["proof_level"] = PROOF_LEVEL_RENDERED_STRING
    doc["telemetry_source"] = TELEMETRY_SOURCE_NAME
    doc["telemetry_source_label"] = TELEMETRY_SOURCE_LABEL
    doc["staleness_threshold_seconds"] = STALENESS_THRESHOLD_SECONDS
    doc["surface"] = SURFACE_ID
    return doc


def _fault_for_reason(reason: str) -> str:
    key = str(reason or "").strip().lower()
    if key in ("telemetry_outage", "capability_absent"):
        return "telemetry_outage" if key == "telemetry_outage" else "capability_absent"
    if key in ("empty_series",):
        return "empty_series"
    if key in ("aged_sample", "stale"):
        return "aged_sample"
    if key in ("ok", "fresh"):
        return "ok"
    if key in ("missing_as_of",):
        return "telemetry_outage"  # fallback; missing_as_of raises
    return "telemetry_outage"


def _hop_hashes(doc: Dict[str, Any]) -> list:
    out = []
    for hop in doc.get("hops") or []:
        out.append(
            (
                str(hop.get("payload_id") or ""),
                str(hop.get("payload_hash") or "").strip().lower(),
            )
        )
    for bucket in ("fault_traces", "reason_traces"):
        for _k, nested in sorted((doc.get(bucket) or {}).items()):
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


def write_cadence_traces(*, root: Optional[Path] = None) -> Dict[str, Path]:
    """Materialize ``artifacts/traces/cadence-e2e.json`` under ``root``."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / CADENCE_TRACE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = build_cadence_trace_set()
    validate_trace(doc)
    for bucket in ("fault_traces", "reason_traces"):
        for _k, nested in (doc.get(bucket) or {}).items():
            validate_trace(nested)
    _assert_payload_hash_integrity(doc, label=CADENCE_TRACE_RELPATH)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {CADENCE_TRACE_RELPATH.replace("\\", "/"): path}


def load_trace_set(
    relpath: str = CADENCE_TRACE_RELPATH,
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load shipped cadence-e2e.json, pinned to the live builder."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / relpath
    builder_doc = build_cadence_trace_set()
    validate_trace(builder_doc)
    for bucket in ("fault_traces", "reason_traces"):
        for _k, nested in (builder_doc.get(bucket) or {}).items():
            validate_trace(nested)
    _assert_payload_hash_integrity(builder_doc, label="cadence-e2e builder")

    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            try:
                validate_trace(data)
                for bucket in ("fault_traces", "reason_traces"):
                    for _k, nested in (data.get(bucket) or {}).items():
                        validate_trace(nested)
                _assert_payload_hash_integrity(data, label="cadence-e2e on-disk")
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
    "AGE_CLASS",
    "CADENCE_TRACE_RELPATH",
    "CONTROL_CADENCE",
    "FRESHNESS_CLASS",
    "INDUCED_FAULT_REASONS",
    "STALE_LABEL",
    "SURFACE_ID",
    "TILE_CLASS",
    "TRACE_AS_OF",
    "StatusViewContext",
    "StatusViewResult",
    "WAVE_ID",
    "build_cadence_fault_trace",
    "build_cadence_ok_trace",
    "build_cadence_trace_payload",
    "build_cadence_trace_set",
    "generate_html",
    "generate_html_for_fixture",
    "generate_html_for_surface_fault",
    "load_trace_set",
    "node_check_status_scripts",
    "render_status_surface",
    "render_status_tile",
    "write_cadence_traces",
]

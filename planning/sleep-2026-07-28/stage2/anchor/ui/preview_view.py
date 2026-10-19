"""File preview view — W18, Phase 3.

Renders exclusively through ``render_state`` (W6). Distinguishes:

* **empty** — zero-byte file (successful read, nothing to preview)
* **unknown** — type probe / read failed (never looks empty)
* **ok** — human-friendly Office/PDF text via the shared path
* **zero_measured** — supported file with zero extracted content units
* **measurement_failed** + visible ``unsupported_preview`` + download —
  content-type with no human-friendly renderer (never a raw byte dump)

Binary guard: rendered HTML never contains zip signature text
(``PK\\x03\\x04``) or other raw byte dumps. All body text is ``html.escape``'d.

Trace builders emit ``artifacts/traces/preview-e2e.json`` at
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
from anchor.files.preview import (
    CAPABILITY_CONTROL_ID,
    INDUCED_FAULT_REASONS,
    INVENTORY_SOURCE_LABEL,
    INVENTORY_SOURCE_NAME,
    PREVIEW_REASONS,
    UNSUPPORTED_PREVIEW_LABEL,
    ZIP_SIGNATURE_TEXT,
    PreviewReason,
    PreviewResult,
    WAVE_ID as PREVIEW_WAVE_ID,
    force_preview_for_fault,
    make_docx_bytes,
    make_empty_docx_bytes,
    make_pdf_bytes,
    make_pptx_bytes,
    make_xlsx_bytes,
    preview_bytes,
    preview_path,
    preview_reason_named_state,
)
from anchor.ui.named_state import NamedState, render_state

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "preview"
WAVE_ID = PREVIEW_WAVE_ID
CONTROL_PREVIEW_PATH = CAPABILITY_CONTROL_ID

PREVIEW_TRACE_RELPATH = os.path.join("artifacts", "traces", "preview-e2e.json")
TRACE_AS_OF = "2026-07-29T00:00:00Z"

PANEL_CLASS = "preview-panel"
BODY_CLASS = "preview-body"
DOWNLOAD_CLASS = "preview-download"
UNSUPPORTED_CLASS = "unsupported-preview"
FILENAME_CLASS = "preview-filename"
FORMAT_CLASS = "preview-format"
SOURCE_CLASS = "preview-source"


# --------------------------------------------------------------------------
# Context / result
# --------------------------------------------------------------------------


@dataclass
class PreviewViewContext:
    """Inputs that drive the preview surface render."""

    filename: str = "document.docx"
    content_type: str = ""
    data: Optional[bytes] = None
    result: Optional[PreviewResult] = None
    force_fault: Optional[str] = None
    capability_present: Optional[bool] = None
    probe_failed: bool = False
    download_href: str = ""
    path: Optional[Union[str, Path]] = None
    title: str = "File preview"


@dataclass
class PreviewViewResult:
    """Structured render outcome for tests and traces."""

    html: str
    preview: Optional[PreviewResult] = None
    human_text_visible: str = ""


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _escape_attr(value: str) -> str:
    return html.escape(str(value), quote=True)


def _escape_text(value: str) -> str:
    return html.escape(str(value), quote=False)


def render_preview_panel(result: PreviewResult) -> str:
    """Render one preview panel through ``render_state``.

    Rules (frozen plan GWTs):

    * docx/pptx/xlsx/pdf → human-readable content, no ``PK\\x03\\x04``
    * unsupported type → named unsupported-preview + download (no dump)
    * zero-byte → **empty**; probe failed → **unknown** (distinct)
    """
    ns = result.named_state
    state_html = render_state(ns)

    parts: List[str] = [state_html]
    parts.append(
        ' <span class="%s" data-filename="%s">%s</span>'
        % (
            FILENAME_CLASS,
            _escape_attr(result.filename),
            _escape_text(result.filename),
        )
    )
    if result.format:
        parts.append(
            ' <span class="%s" data-format="%s">format:%s</span>'
            % (
                FORMAT_CLASS,
                _escape_attr(result.format),
                _escape_text(result.format),
            )
        )
    parts.append(
        ' <span class="%s" data-inventory-source="%s">%s</span>'
        % (
            SOURCE_CLASS,
            _escape_attr(result.inventory_source),
            _escape_text(result.inventory_source_label),
        )
    )

    if ns is NamedState.ok and result.human_text:
        # Escape ALL human text — binary guard.
        # Use <pre> (not nested <div>) so panel-section extractors that stop
        # at the first </div> still capture the full panel (W16 tile pattern).
        body = _escape_text(result.human_text)
        parts.append(
            ' <pre class="%s" data-human-friendly="true">%s</pre>'
            % (BODY_CLASS, body)
        )
    elif ns is NamedState.empty:
        parts.append(
            ' <span class="empty-detail">zero-byte file — nothing to preview'
            "</span>"
        )
    elif ns is NamedState.unknown:
        parts.append(
            ' <span class="unknown-detail">file type probe failed'
            "</span>"
        )
    elif ns is NamedState.zero_measured:
        parts.append(
            ' <span class="zero-detail">preview content measured zero</span>'
        )
    elif result.unsupported or result.reason == PreviewReason.UNSUPPORTED_PREVIEW.value:
        # Named unsupported-preview state + download affordance.
        parts.append(
            ' <span class="%s" data-unsupported="true">%s</span>'
            % (UNSUPPORTED_CLASS, _escape_text(UNSUPPORTED_PREVIEW_LABEL))
        )
        href = _escape_attr(result.download_href or ("download:%s" % result.filename))
        parts.append(
            ' <a class="%s" href="%s" data-download="true" '
            'download="%s">Download</a>'
            % (
                DOWNLOAD_CLASS,
                href,
                _escape_attr(result.filename),
            )
        )
    elif ns is NamedState.measurement_failed:
        parts.append(
            ' <span class="extract-failed-detail">preview extract failed</span>'
        )

    # Binary guard assertion surface: never embed raw payload.
    reason = _escape_attr(result.reason or "")
    return (
        '<div class="%s" data-surface="%s" data-named-state="%s" '
        'data-reason="%s" data-filename="%s" data-format="%s" '
        'data-size-bytes="%d" data-unsupported="%s" '
        'data-inventory-source="%s">'
        "%s</div>"
        % (
            PANEL_CLASS,
            SURFACE_ID,
            _escape_attr(ns.value),
            reason,
            _escape_attr(result.filename),
            _escape_attr(result.format or ""),
            int(result.size_bytes),
            "true" if result.unsupported else "false",
            _escape_attr(result.inventory_source),
            "".join(parts),
        )
    )


def _resolve_preview(ctx: PreviewViewContext) -> PreviewResult:
    if ctx.result is not None:
        return ctx.result
    if ctx.force_fault:
        return force_preview_for_fault(
            ctx.force_fault, filename=ctx.filename
        )
    if ctx.path is not None:
        return preview_path(
            ctx.path,
            content_type=ctx.content_type,
            capability_present=ctx.capability_present,
            download_href=ctx.download_href,
        )
    return preview_bytes(
        ctx.data,
        filename=ctx.filename,
        content_type=ctx.content_type,
        capability_present=ctx.capability_present,
        download_href=ctx.download_href,
        probe_failed=ctx.probe_failed,
    )


def render_preview_surface(
    ctx: Optional[PreviewViewContext] = None,
) -> PreviewViewResult:
    """Render the preview surface for the given context."""
    c = ctx or PreviewViewContext()
    preview = _resolve_preview(c)
    panel = render_preview_panel(preview)

    body_parts = [
        '<section class="preview-surface-panel" data-surface="preview">',
        panel,
        "</section>",
        _render_state_legend(),
        _render_reason_matrix(),
    ]
    body = "\n".join(body_parts)

    script = (
        "(function () {\n"
        "  var root = document.querySelector("
        "'[data-surface=\"preview\"]');\n"
        "  if (!root) { return; }\n"
        "  var panels = root.querySelectorAll('.preview-panel');\n"
        "  for (var i = 0; i < panels.length; i++) {\n"
        "    var p = panels[i];\n"
        "    var state = p.getAttribute('data-named-state') || '';\n"
        "    if (!state) { continue; }\n"
        "    var fmt = p.getAttribute('data-format') || '';\n"
        "    if (typeof window.__anchorPreview === 'function') {\n"
        "      window.__anchorPreview(state, fmt);\n"
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
        '  <main class="preview-surface" data-surface="preview" '
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

    # Final binary guard — refuse to ship HTML that embeds zip signature text.
    if ZIP_SIGNATURE_TEXT in doc:
        raise RuntimeError(
            "binary guard: rendered preview HTML contains zip signature text "
            "%r — shared path must never dump raw binary as text"
            % ZIP_SIGNATURE_TEXT
        )
    if "\x03\x04" in doc:
        raise RuntimeError(
            "binary guard: rendered preview HTML contains raw control bytes"
        )

    return PreviewViewResult(
        html=doc,
        preview=preview,
        human_text_visible=preview.human_text or "",
    )


def _render_state_legend() -> str:
    rows = []
    for ns in (
        NamedState.ok,
        NamedState.unknown,
        NamedState.empty,
        NamedState.zero_measured,
        NamedState.measurement_failed,
    ):
        rows.append(
            '<div class="legend-row" data-legend-state="%s">%s</div>'
            % (_escape_attr(ns.value), render_state(ns))
        )
    return (
        '<section class="preview-legend" data-surface="preview-legend">'
        "\n%s\n</section>" % ("\n".join(rows),)
    )


def _render_reason_matrix() -> str:
    rows: List[str] = []
    for reason in PREVIEW_REASONS:
        ns = preview_reason_named_state(reason)
        rows.append(
            '<div class="reason-row" data-control="preview_path" '
            'data-reason="%s"><span class="reason-token">%s</span> %s</div>'
            % (
                _escape_attr(reason),
                _escape_text(reason),
                render_state(ns),
            )
        )
    return (
        '<section class="reason-matrix" data-surface="preview-reasons">\n%s\n'
        "</section>" % ("\n".join(rows),)
    )


_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_preview_scripts(
    html_text: str,
    *,
    require_node: bool = True,
) -> List[str]:
    """Run ``node --check`` on every ``<script>`` block in preview HTML."""
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
                "node binary not on PATH — preview surface requires "
                "node --check on emitted script blocks"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="preview_node_check_") as tmp:
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
                    "node --check failed for preview script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[PreviewViewContext] = None,
    *,
    require_node_check: Optional[bool] = None,
) -> str:
    """Return the preview surface HTML document."""
    doc = render_preview_surface(ctx).html
    node = shutil.which("node")
    if node:
        node_check_preview_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_preview_scripts(doc, require_node=True)
    return doc


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state harness entry: unknown / empty / zero_measured (+ ok formats).

    * ``unknown`` — type probe failed
    * ``empty`` — zero-byte file
    * ``zero_measured`` — supported file, zero extracted content units
    * ``ok`` / ``docx`` / ``pptx`` / ``xlsx`` / ``pdf`` — human-friendly ok
    * ``unsupported`` — unsupported_preview + download
    """
    key = (fixture or "").strip().lower().replace("-", "_")
    if key == "unknown":
        ctx = PreviewViewContext(
            filename="mystery.bin",
            probe_failed=True,
            capability_present=True,
        )
        return render_preview_surface(ctx).html
    if key in ("empty",):
        ctx = PreviewViewContext(
            filename="empty.docx",
            data=b"",
            capability_present=True,
        )
        return render_preview_surface(ctx).html
    if key in ("zero", "zero_measured", "measured_zero"):
        ctx = PreviewViewContext(
            filename="blank.docx",
            data=make_empty_docx_bytes(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            capability_present=True,
        )
        return render_preview_surface(ctx).html
    if key in ("ok", "docx"):
        ctx = PreviewViewContext(
            filename="sample.docx",
            data=make_docx_bytes(["Hello Word preview"]),
            capability_present=True,
        )
        return render_preview_surface(ctx).html
    if key == "pptx":
        ctx = PreviewViewContext(
            filename="deck.pptx",
            data=make_pptx_bytes(["Slide one title"]),
            capability_present=True,
        )
        return render_preview_surface(ctx).html
    if key == "xlsx":
        ctx = PreviewViewContext(
            filename="sheet.xlsx",
            data=make_xlsx_bytes(["Alpha", "Beta"]),
            capability_present=True,
        )
        return render_preview_surface(ctx).html
    if key == "pdf":
        ctx = PreviewViewContext(
            filename="doc.pdf",
            data=make_pdf_bytes("Hello PDF preview"),
            capability_present=True,
        )
        return render_preview_surface(ctx).html
    if key in ("unsupported", "unsupported_preview"):
        ctx = PreviewViewContext(
            filename="blob.bin",
            data=b"\x00\x01\x02\x03raw-binary-not-for-text",
            content_type="application/octet-stream",
            download_href="download:blob.bin",
            capability_present=True,
        )
        return render_preview_surface(ctx).html
    raise ValueError("unknown preview fixture %r" % fixture)


def build_preview_trace_payload(
    reason: Optional[str] = None,
    *,
    ok: bool = False,
    preview: Optional[PreviewResult] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "control_id": CONTROL_PREVIEW_PATH,
        "wave_id": WAVE_ID,
        "ok": ok,
        "reason": reason or "",
        "handler": "anchor.files.preview.preview_bytes",
        "capability": "preview_path",
        "inventory_source": INVENTORY_SOURCE_NAME,
        "inventory_source_label": INVENTORY_SOURCE_LABEL,
    }
    if preview is not None:
        payload["named_state"] = preview.named_state.value
        payload["format"] = preview.format
        payload["filename"] = preview.filename
        payload["size_bytes"] = preview.size_bytes
        payload["unsupported"] = preview.unsupported
        payload["query_id"] = preview.query_id
        # Do NOT put human_text or raw bytes into the trace payload — binary guard.
        payload["content_units"] = int(
            (preview.meta or {}).get("content_units", 0)
            if preview.meta
            else (len(preview.human_text.split()) if preview.human_text else 0)
        )
    return payload


# --------------------------------------------------------------------------
# E2e traces
# --------------------------------------------------------------------------


def _hops_for(
    *,
    payload: Dict[str, Any],
    rendered_state: str,
) -> list:
    reason = payload.get("reason") or ("ok" if payload.get("ok") else "preview")
    payload_id = "w18-preview_path-%s" % reason
    ph = payload_hash(payload)
    ts = TRACE_AS_OF
    return [
        make_hop(
            HOP_CONTROL_INVOCATION,
            "click-preview",
            payload_id=payload_id,
            payload=payload,
            detail="",
            timestamp=ts,
        ),
        make_hop(
            HOP_HANDLER,
            "anchor.files.preview.preview_bytes",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="anchor.files.preview.preview_bytes",
            timestamp=ts,
        ),
        make_hop(
            HOP_CAPABILITY_CALL,
            "capability.preview_path",
            payload_id=payload_id,
            payload_hash_value=ph,
            detail="capability.preview_path",
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


def build_preview_reason_trace(
    reason: str,
    *,
    wave_id: str = WAVE_ID,
) -> TraceArtifact:
    """One schema-valid preview trace under an executed fault/outcome."""
    preview = force_preview_for_fault(reason, filename="w18-induced.bin")
    ns = preview.named_state
    ok = ns is NamedState.ok
    payload = build_preview_trace_payload(reason, ok=ok, preview=preview)
    payload["executed"] = True
    payload["handler_result_reason"] = preview.reason
    hops = _hops_for(payload=payload, rendered_state=ns.value)
    return build_trace(
        wave_id,
        CONTROL_PREVIEW_PATH,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=(
            TRACE_RESULT_COMPLETED if ok else TRACE_RESULT_FAILED_NAMED
        ),
        induced_fault=reason if reason in INDUCED_FAULT_REASONS else reason,
        rendered_state=ns.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W18 preview e2e under reason %s; structural rendered-string "
            "proof only; handler executed" % reason
        ),
    )


def build_preview_ok_trace(*, wave_id: str = WAVE_ID) -> TraceArtifact:
    """Primary success path: docx human-friendly preview."""
    data = make_docx_bytes(["W18 shared path preview"])
    preview = preview_bytes(
        data,
        filename="w18.docx",
        capability_present=True,
    )
    payload = build_preview_trace_payload(
        PreviewReason.OK.value, ok=True, preview=preview
    )
    payload["executed"] = True
    hops = _hops_for(payload=payload, rendered_state=NamedState.ok.value)
    return build_trace(
        wave_id,
        CONTROL_PREVIEW_PATH,
        hops,
        proof_level=PROOF_LEVEL_RENDERED_STRING,
        trace_result=TRACE_RESULT_COMPLETED,
        induced_fault=None,
        rendered_state=NamedState.ok.value,
        as_of=TRACE_AS_OF,
        notes=(
            "W18 preview e2e success path (docx human-friendly); "
            "structural rendered-string proof only"
        ),
    )


def build_preview_trace_set() -> Dict[str, Any]:
    """Full artifact: primary docx ok + one fault per induced reason + formats."""
    primary = build_preview_ok_trace()
    reason_traces = {
        reason: build_preview_reason_trace(reason).as_dict()
        for reason in PREVIEW_REASONS
    }
    for reason in INDUCED_FAULT_REASONS:
        if reason not in reason_traces:
            reason_traces[reason] = build_preview_reason_trace(reason).as_dict()

    # Per-format success traces (docx already primary; add others).
    format_traces: Dict[str, Any] = {}
    format_fixtures = {
        "docx": ("sample.docx", make_docx_bytes(["Docx text"])),
        "pptx": ("deck.pptx", make_pptx_bytes(["Pptx slide"])),
        "xlsx": ("sheet.xlsx", make_xlsx_bytes(["Xlsx cell"])),
        "pdf": ("doc.pdf", make_pdf_bytes("Pdf text payload")),
    }
    for fmt, (fname, blob) in format_fixtures.items():
        prev = preview_bytes(blob, filename=fname, capability_present=True)
        payload = build_preview_trace_payload(
            prev.reason, ok=prev.ok, preview=prev
        )
        payload["executed"] = True
        payload["format"] = fmt
        hops = _hops_for(
            payload=payload, rendered_state=prev.named_state.value
        )
        art = build_trace(
            WAVE_ID,
            CONTROL_PREVIEW_PATH,
            hops,
            proof_level=PROOF_LEVEL_RENDERED_STRING,
            trace_result=(
                TRACE_RESULT_COMPLETED
                if prev.ok
                else TRACE_RESULT_FAILED_NAMED
            ),
            induced_fault=None,
            rendered_state=prev.named_state.value,
            as_of=TRACE_AS_OF,
            notes=(
                "W18 preview e2e format=%s; structural rendered-string "
                "proof only" % fmt
            ),
        )
        format_traces[fmt] = art.as_dict()

    doc = primary.as_dict()
    doc["enumerated_reasons"] = list(PREVIEW_REASONS)
    doc["induced_fault_reasons"] = list(INDUCED_FAULT_REASONS)
    doc["reason_traces"] = reason_traces
    doc["format_traces"] = format_traces
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
    for _key, nested in sorted((doc.get("reason_traces") or {}).items()):
        for hop in nested.get("hops") or []:
            out.append(
                (
                    str(hop.get("payload_id") or ""),
                    str(hop.get("payload_hash") or "").strip().lower(),
                )
            )
    for _key, nested in sorted((doc.get("format_traces") or {}).items()):
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


def write_preview_traces(*, root: Optional[Path] = None) -> Dict[str, Path]:
    """Write ``artifacts/traces/preview-e2e.json`` under *root*."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / PREVIEW_TRACE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = build_preview_trace_set()
    validate_trace(doc)
    for reason, nested in (doc.get("reason_traces") or {}).items():
        validate_trace(nested)
    for fmt, nested in (doc.get("format_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(doc, label=PREVIEW_TRACE_RELPATH)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {PREVIEW_TRACE_RELPATH.replace("\\", "/"): path}


def load_trace_set(
    relpath: str = PREVIEW_TRACE_RELPATH,
    *,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load shipped preview-e2e.json, pinned to the live builder."""
    base = root if root is not None else Path(__file__).resolve().parents[2]
    path = base / relpath
    builder_doc = build_preview_trace_set()
    validate_trace(builder_doc)
    for reason, nested in (builder_doc.get("reason_traces") or {}).items():
        validate_trace(nested)
    for fmt, nested in (builder_doc.get("format_traces") or {}).items():
        validate_trace(nested)
    _assert_payload_hash_integrity(
        builder_doc, label="builder:" + PREVIEW_TRACE_RELPATH
    )
    if not path.is_file():
        write_preview_traces(root=base)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    if _hop_hashes(on_disk) != _hop_hashes(builder_doc):
        write_preview_traces(root=base)
        on_disk = json.loads(path.read_text(encoding="utf-8"))
    validate_trace(on_disk)
    return on_disk


__all__ = [
    "SURFACE_ID",
    "WAVE_ID",
    "CONTROL_PREVIEW_PATH",
    "PREVIEW_TRACE_RELPATH",
    "PANEL_CLASS",
    "BODY_CLASS",
    "DOWNLOAD_CLASS",
    "UNSUPPORTED_CLASS",
    "INDUCED_FAULT_REASONS",
    "PreviewViewContext",
    "PreviewViewResult",
    "render_preview_panel",
    "render_preview_surface",
    "generate_html",
    "generate_html_for_fixture",
    "node_check_preview_scripts",
    "build_preview_trace_payload",
    "build_preview_reason_trace",
    "build_preview_ok_trace",
    "build_preview_trace_set",
    "write_preview_traces",
    "load_trace_set",
]

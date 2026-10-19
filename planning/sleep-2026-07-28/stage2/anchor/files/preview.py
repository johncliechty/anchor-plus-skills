"""Shared human-friendly file preview path — W18, Phase 3.

Single entry point for docx / pptx / xlsx / pdf previews. Binary content is
**never** dumped as text. Formats without a human-friendly renderer yield a
named unsupported-preview outcome plus a download affordance.

Honesty (North Star — unknown ≠ empty):

* **empty** — file read succeeded and the file is zero bytes
* **unknown** — type probe / read failed (never looks empty)
* **ok** — human-friendly text extracted through the shared path
* **zero_measured** — file has size > 0 and a supported format, but
  extracted human content measures 0 units
* **measurement_failed** — content-type has no human-friendly renderer
  (surface also stamps visible ``unsupported_preview`` + download)

Lightweight extractors only (stdlib ``zipfile`` + ``xml.etree`` for Office;
marker-aware stream decode for PDF). No external deps.
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from anchor.ui.named_state import NamedState

# --------------------------------------------------------------------------
# Public constants — inventory source bound to CAPABILITY-INVENTORY.md
# --------------------------------------------------------------------------

WAVE_ID = "W18"
SURFACE_ID = "preview"

#: Control id + label as recorded in CAPABILITY-INVENTORY.md (W3).
CAPABILITY_CONTROL_ID = "preview_path"
INVENTORY_SOURCE_LABEL = "preview path"
INVENTORY_SOURCE_NAME = CAPABILITY_CONTROL_ID

#: Formats with a human-friendly renderer on this path.
SUPPORTED_FORMATS: Tuple[str, ...] = ("docx", "pptx", "xlsx", "pdf")

#: Visible token for the unsupported-preview outcome (no NamedState member).
UNSUPPORTED_PREVIEW_LABEL = "unsupported_preview"

#: Zip local-file signature — must NEVER appear in rendered preview text.
ZIP_SIGNATURE = b"PK\x03\x04"
ZIP_SIGNATURE_TEXT = "PK\x03\x04"

#: PDF magic.
PDF_SIGNATURE = b"%PDF"


class PreviewReason(str, Enum):
    """Enumerated preview outcomes / induced-fault reasons."""

    OK = "ok"
    UNSUPPORTED_PREVIEW = "unsupported_preview"
    EMPTY_FILE = "empty_file"
    PROBE_FAILED = "probe_failed"
    EXTRACT_FAILED = "extract_failed"
    ZERO_MEASURED = "zero_measured"
    CAPABILITY_ABSENT = "capability_absent"


PREVIEW_REASONS: Tuple[str, ...] = tuple(r.value for r in PreviewReason)

#: Induced faults the W18 gate must exercise.
INDUCED_FAULT_UNSUPPORTED = PreviewReason.UNSUPPORTED_PREVIEW.value
INDUCED_FAULT_EMPTY_FILE = PreviewReason.EMPTY_FILE.value
INDUCED_FAULT_PROBE_FAILED = PreviewReason.PROBE_FAILED.value

INDUCED_FAULT_REASONS: Tuple[str, ...] = (
    INDUCED_FAULT_UNSUPPORTED,
    INDUCED_FAULT_EMPTY_FILE,
    INDUCED_FAULT_PROBE_FAILED,
)

REASON_LABELS: Dict[str, str] = {
    PreviewReason.OK.value: "human-friendly preview ready",
    PreviewReason.UNSUPPORTED_PREVIEW.value: "unsupported_preview",
    PreviewReason.EMPTY_FILE.value: "zero-byte file — nothing to preview",
    PreviewReason.PROBE_FAILED.value: "file type probe failed",
    PreviewReason.EXTRACT_FAILED.value: "preview extract failed",
    PreviewReason.ZERO_MEASURED.value: "preview content measured zero",
    PreviewReason.CAPABILITY_ABSENT.value: "preview path capability absent",
}

REASON_STATE: Dict[str, NamedState] = {
    PreviewReason.OK.value: NamedState.ok,
    # No human-friendly renderer → measurement_failed + visible unsupported_preview.
    PreviewReason.UNSUPPORTED_PREVIEW.value: NamedState.measurement_failed,
    # Successful read of a zero-byte file → empty (NEVER unknown).
    PreviewReason.EMPTY_FILE.value: NamedState.empty,
    # Probe / read failure → unknown (NEVER empty).
    PreviewReason.PROBE_FAILED.value: NamedState.unknown,
    PreviewReason.EXTRACT_FAILED.value: NamedState.measurement_failed,
    PreviewReason.ZERO_MEASURED.value: NamedState.zero_measured,
    PreviewReason.CAPABILITY_ABSENT.value: NamedState.unknown,
}

# Extension → format token
_EXT_TO_FORMAT: Dict[str, str] = {
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
}

# content-type / mime hints
_MIME_TO_FORMAT: Dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class PreviewProbeError(Exception):
    """Raised when type probe or file read fails (maps to unknown)."""

    def __init__(self, message: str = "file type probe failed"):
        super().__init__(message)
        self.message = message


class PreviewError(Exception):
    """Base error for preview path."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviewResult:
    """Structured preview outcome for the shared path + view renderer.

    ``human_text`` is always safe printable text (never raw binary).
    ``named_state`` is the honesty state the view must render through
    ``render_state``. For unsupported types, ``unsupported`` is True and
    ``download_href`` carries the download affordance.
    """

    filename: str
    content_type: str
    format: str
    named_state: NamedState
    human_text: str
    reason: str
    detail: str = ""
    size_bytes: int = 0
    download_href: str = ""
    unsupported: bool = False
    query_id: str = "preview_path.extract"
    inventory_source: str = INVENTORY_SOURCE_NAME
    inventory_source_label: str = INVENTORY_SOURCE_LABEL
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.named_state is NamedState.ok

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "filename": self.filename,
            "content_type": self.content_type,
            "format": self.format,
            "named_state": self.named_state.value,
            "human_text": self.human_text,
            "reason": self.reason,
            "detail": self.detail,
            "size_bytes": int(self.size_bytes),
            "download_href": self.download_href,
            "unsupported": bool(self.unsupported),
            "query_id": self.query_id,
            "inventory_source": self.inventory_source,
            "inventory_source_label": self.inventory_source_label,
            "meta": dict(self.meta),
        }


# --------------------------------------------------------------------------
# Public helpers
# --------------------------------------------------------------------------


def supported_formats() -> Tuple[str, ...]:
    """Formats with a human-friendly renderer on the shared path."""
    return SUPPORTED_FORMATS


def normalize_preview_reason(reason: Union[str, PreviewReason]) -> str:
    if isinstance(reason, PreviewReason):
        return reason.value
    raw = str(reason).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ok": PreviewReason.OK.value,
        "success": PreviewReason.OK.value,
        "unsupported_preview": PreviewReason.UNSUPPORTED_PREVIEW.value,
        "unsupported": PreviewReason.UNSUPPORTED_PREVIEW.value,
        "no_renderer": PreviewReason.UNSUPPORTED_PREVIEW.value,
        "empty_file": PreviewReason.EMPTY_FILE.value,
        "empty": PreviewReason.EMPTY_FILE.value,
        "zero_byte": PreviewReason.EMPTY_FILE.value,
        "probe_failed": PreviewReason.PROBE_FAILED.value,
        "unknown": PreviewReason.PROBE_FAILED.value,
        "unreadable": PreviewReason.PROBE_FAILED.value,
        "read_failed": PreviewReason.PROBE_FAILED.value,
        "extract_failed": PreviewReason.EXTRACT_FAILED.value,
        "zero_measured": PreviewReason.ZERO_MEASURED.value,
        "measured_zero": PreviewReason.ZERO_MEASURED.value,
        "capability_absent": PreviewReason.CAPABILITY_ABSENT.value,
        "missing_capability": PreviewReason.CAPABILITY_ABSENT.value,
    }
    if raw not in aliases:
        raise ValueError(
            "unknown preview reason %r — must be one of %s"
            % (reason, list(PREVIEW_REASONS))
        )
    return aliases[raw]


def preview_reason_named_state(reason: Union[str, PreviewReason]) -> NamedState:
    token = normalize_preview_reason(reason)
    return REASON_STATE[token]


def detect_format(
    *,
    filename: str = "",
    content_type: str = "",
    data: Optional[bytes] = None,
) -> Optional[str]:
    """Detect a supported format from name, content-type, or magic bytes.

    Returns a format token (docx/pptx/xlsx/pdf) or None when unsupported /
    unprobeable from the given hints. Does **not** raise.
    """
    name = (filename or "").strip().lower()
    for ext, fmt in _EXT_TO_FORMAT.items():
        if name.endswith(ext):
            return fmt

    mime = (content_type or "").strip().lower().split(";")[0].strip()
    if mime in _MIME_TO_FORMAT:
        return _MIME_TO_FORMAT[mime]

    if data:
        if data[:4] == PDF_SIGNATURE or data[:5] == b"%PDF-":
            return "pdf"
        if data[:4] == ZIP_SIGNATURE:
            # Office Open XML is zip-based; peek for content types / parts.
            peeked = _peek_ooxml_format(data)
            if peeked:
                return peeked
    return None


def preview_bytes(
    data: Optional[bytes],
    *,
    filename: str = "",
    content_type: str = "",
    force_fault: Optional[Union[str, PreviewReason]] = None,
    capability_present: Optional[bool] = None,
    download_href: str = "",
    probe_failed: bool = False,
) -> PreviewResult:
    """Preview in-memory bytes through the shared human-friendly path.

    * ``force_fault`` returns the named outcome without further I/O.
    * ``probe_failed=True`` → ``NamedState.unknown`` (never empty).
    * Zero-length bytes → ``NamedState.empty`` (never unknown).
    * Unsupported type → ``NamedState.measurement_failed`` + visible
      ``unsupported_preview`` + download affordance (never raw dump).
    """
    fname = str(filename or "file").strip() or "file"
    ctype = str(content_type or "").strip()
    href = download_href or ("download:%s" % fname)

    if force_fault is not None:
        return _forced_result(
            fname,
            normalize_preview_reason(force_fault),
            content_type=ctype,
            download_href=href,
            data=data,
        )

    if capability_present is False:
        return PreviewResult(
            filename=fname,
            content_type=ctype,
            format="",
            named_state=NamedState.unknown,
            human_text="",
            reason=PreviewReason.CAPABILITY_ABSENT.value,
            detail=REASON_LABELS[PreviewReason.CAPABILITY_ABSENT.value],
            size_bytes=0 if data is None else len(data),
            download_href="",
            unsupported=False,
        )

    if probe_failed:
        return PreviewResult(
            filename=fname,
            content_type=ctype,
            format="",
            named_state=NamedState.unknown,
            human_text="",
            reason=PreviewReason.PROBE_FAILED.value,
            detail=REASON_LABELS[PreviewReason.PROBE_FAILED.value],
            size_bytes=0 if data is None else len(data),
            download_href="",
            unsupported=False,
        )

    if data is None:
        return PreviewResult(
            filename=fname,
            content_type=ctype,
            format="",
            named_state=NamedState.unknown,
            human_text="",
            reason=PreviewReason.PROBE_FAILED.value,
            detail="file bytes unavailable — type probe failed",
            size_bytes=0,
            download_href="",
            unsupported=False,
        )

    size = len(data)
    if size == 0:
        return PreviewResult(
            filename=fname,
            content_type=ctype or "application/octet-stream",
            format="",
            named_state=NamedState.empty,
            human_text="",
            reason=PreviewReason.EMPTY_FILE.value,
            detail=REASON_LABELS[PreviewReason.EMPTY_FILE.value],
            size_bytes=0,
            download_href="",
            unsupported=False,
        )

    fmt = detect_format(filename=fname, content_type=ctype, data=data)
    if fmt is None:
        return PreviewResult(
            filename=fname,
            content_type=ctype or "application/octet-stream",
            format="unsupported",
            named_state=NamedState.measurement_failed,
            human_text="",
            reason=PreviewReason.UNSUPPORTED_PREVIEW.value,
            detail=REASON_LABELS[PreviewReason.UNSUPPORTED_PREVIEW.value],
            size_bytes=size,
            download_href=href,
            unsupported=True,
            meta={"unsupported_preview": True},
        )

    try:
        text = _extract_human_text(fmt, data)
    except Exception as exc:  # noqa: BLE001 — map any extract failure honestly
        return PreviewResult(
            filename=fname,
            content_type=ctype or _default_content_type(fmt),
            format=fmt,
            named_state=NamedState.measurement_failed,
            human_text="",
            reason=PreviewReason.EXTRACT_FAILED.value,
            detail=str(exc) or REASON_LABELS[PreviewReason.EXTRACT_FAILED.value],
            size_bytes=size,
            download_href=href,
            unsupported=False,
        )

    # Never allow raw zip/pdf signatures into human_text.
    safe = _sanitize_human_text(text)
    if not safe.strip():
        return PreviewResult(
            filename=fname,
            content_type=ctype or _default_content_type(fmt),
            format=fmt,
            named_state=NamedState.zero_measured,
            human_text="",
            reason=PreviewReason.ZERO_MEASURED.value,
            detail=REASON_LABELS[PreviewReason.ZERO_MEASURED.value],
            size_bytes=size,
            download_href="",
            unsupported=False,
            meta={"content_units": 0},
        )

    return PreviewResult(
        filename=fname,
        content_type=ctype or _default_content_type(fmt),
        format=fmt,
        named_state=NamedState.ok,
        human_text=safe,
        reason=PreviewReason.OK.value,
        detail=REASON_LABELS[PreviewReason.OK.value],
        size_bytes=size,
        download_href="",
        unsupported=False,
        meta={"content_units": len(safe.split())},
    )


def preview_path(
    path: Union[str, Path],
    *,
    content_type: str = "",
    force_fault: Optional[Union[str, PreviewReason]] = None,
    capability_present: Optional[bool] = None,
    download_href: str = "",
) -> PreviewResult:
    """Preview a filesystem path through the shared path.

    Unreadable / missing paths map to **unknown** (probe failed), never empty.
    """
    p = Path(path)
    fname = p.name or "file"
    href = download_href or ("download:%s" % fname)

    if force_fault is not None:
        return _forced_result(
            fname,
            normalize_preview_reason(force_fault),
            content_type=content_type,
            download_href=href,
        )

    if capability_present is False:
        return preview_bytes(
            b"",
            filename=fname,
            content_type=content_type,
            capability_present=False,
            download_href=href,
        )

    try:
        if not p.is_file():
            return preview_bytes(
                None,
                filename=fname,
                content_type=content_type,
                probe_failed=True,
                download_href=href,
            )
        data = p.read_bytes()
    except OSError as exc:
        return PreviewResult(
            filename=fname,
            content_type=content_type,
            format="",
            named_state=NamedState.unknown,
            human_text="",
            reason=PreviewReason.PROBE_FAILED.value,
            detail="file unreadable: %s" % exc,
            size_bytes=0,
            download_href="",
            unsupported=False,
        )

    return preview_bytes(
        data,
        filename=fname,
        content_type=content_type,
        download_href=href,
        capability_present=True,
    )


def force_preview_for_fault(
    fault: Union[str, PreviewReason],
    *,
    filename: str = "fixture.bin",
) -> PreviewResult:
    """Induce one named preview fault (W18 gate / fault_inject seam)."""
    return preview_bytes(
        b"",
        filename=filename,
        force_fault=fault,
    )


# --------------------------------------------------------------------------
# Synthetic fixtures (in-memory; tests use these — no host fixtures required)
# --------------------------------------------------------------------------


def make_docx_bytes(paragraphs: Sequence[str]) -> bytes:
    """Minimal OOXML docx with the given paragraph texts."""
    body_parts = []
    for para in paragraphs:
        body_parts.append(
            "<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % _xml_escape(para)
        )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>%s</w:body></w:document>" % "".join(body_parts)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    return _zip_bytes(
        {
            "[Content_Types].xml": content_types.encode("utf-8"),
            "word/document.xml": document_xml.encode("utf-8"),
        }
    )


def make_pptx_bytes(slide_texts: Sequence[str]) -> bytes:
    """Minimal OOXML pptx with one slide part per text string."""
    parts: Dict[str, bytes] = {}
    overrides = []
    for idx, text in enumerate(slide_texts, start=1):
        slide_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            "<p:cSld><p:spTree>"
            "<p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
            "<p:grpSpPr/>"
            "<p:sp><p:nvSpPr><p:cNvPr id=\"2\" name=\"Title\"/><p:cNvSpPr/><p:nvPr/>"
            "</p:nvSpPr><p:spPr/>"
            "<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>%s</a:t></a:r></a:p>"
            "</p:txBody></p:sp>"
            "</p:spTree></p:cSld></p:sld>"
            % _xml_escape(text)
        )
        part_name = "ppt/slides/slide%d.xml" % idx
        parts[part_name] = slide_xml.encode("utf-8")
        overrides.append(
            '<Override PartName="/%s" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            % part_name
        )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        "%s</Types>" % "".join(overrides)
    )
    parts["[Content_Types].xml"] = content_types.encode("utf-8")
    return _zip_bytes(parts)


def make_xlsx_bytes(cells: Sequence[str]) -> bytes:
    """Minimal OOXML xlsx with shared strings + one sheet referencing them."""
    si_parts = []
    for cell in cells:
        si_parts.append("<si><t>%s</t></si>" % _xml_escape(cell))
    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'count="%d" uniqueCount="%d">%s</sst>'
        % (len(cells), len(cells), "".join(si_parts))
    )
    # Sheet cells reference shared-string indices.
    row_parts = []
    for i, _cell in enumerate(cells):
        row_parts.append(
            '<c r="A%d" t="s"><v>%d</v></c>' % (i + 1, i)
        )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData><row r=\"1\">%s</row></sheetData></worksheet>"
        % "".join(row_parts)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    return _zip_bytes(
        {
            "[Content_Types].xml": content_types.encode("utf-8"),
            "xl/sharedStrings.xml": shared.encode("utf-8"),
            "xl/worksheets/sheet1.xml": sheet.encode("utf-8"),
        }
    )


def make_pdf_bytes(text: str) -> bytes:
    """Minimal PDF-like bytes carrying readable text near a PDF header.

    Extractor looks for printable runs after the ``%PDF`` marker — enough for
    human-friendly preview without a full PDF parser.
    """
    # Keep payload as latin-1-safe printable text so extractors find it.
    safe = "".join(ch if 32 <= ord(ch) < 127 else " " for ch in text)
    # Simple PDF skeleton with a text stream containing the payload.
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>endobj\n"
        b"4 0 obj<< /Length "
        + str(len(safe) + 20).encode("ascii")
        + b" >>stream\nBT ("
        + safe.encode("latin-1", errors="replace")
        + b") Tj ET\nendstream\nendobj\n"
        b"xref\n0 5\ntrailer<< /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
    )
    return body


def make_empty_docx_bytes() -> bytes:
    """Valid docx zip with an empty document body (zero measured content)."""
    return make_docx_bytes([])


# --------------------------------------------------------------------------
# Extractors
# --------------------------------------------------------------------------


def _extract_human_text(fmt: str, data: bytes) -> str:
    if fmt == "docx":
        return _extract_docx(data)
    if fmt == "pptx":
        return _extract_pptx(data)
    if fmt == "xlsx":
        return _extract_xlsx(data)
    if fmt == "pdf":
        return _extract_pdf(data)
    raise PreviewError("no extractor for format %r" % fmt)


def _extract_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        try:
            raw = zf.read("word/document.xml")
        except KeyError as exc:
            raise PreviewError("docx missing word/document.xml") from exc
    return _xml_text_nodes(raw, local_names=("t",))


def _extract_pptx(data: bytes) -> str:
    texts: List[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(
            n
            for n in zf.namelist()
            if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        )
        if not names:
            raise PreviewError("pptx has no slide parts")
        for name in names:
            texts.append(_xml_text_nodes(zf.read(name), local_names=("t",)))
    return "\n".join(t for t in texts if t)


def _extract_xlsx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Prefer shared strings; fall back to inline sheet text.
        if "xl/sharedStrings.xml" in zf.namelist():
            return _xml_text_nodes(
                zf.read("xl/sharedStrings.xml"), local_names=("t",)
            )
        sheet_names = sorted(
            n
            for n in zf.namelist()
            if n.startswith("xl/worksheets/") and n.endswith(".xml")
        )
        if not sheet_names:
            raise PreviewError("xlsx has no sheet or sharedStrings parts")
        parts = [
            _xml_text_nodes(zf.read(n), local_names=("v", "t"))
            for n in sheet_names
        ]
        return "\n".join(p for p in parts if p)


def _extract_pdf(data: bytes) -> str:
    """Extract printable text runs from PDF-like bytes without a full parser.

    Strategy: decode as latin-1, pull text inside parentheses in content
    streams and any long printable runs after the ``%PDF`` marker. Never
    returns raw binary; strips control bytes.
    """
    if not data.startswith(PDF_SIGNATURE) and b"%PDF" not in data[:1024]:
        raise PreviewError("not a PDF (missing %PDF marker)")

    decoded = data.decode("latin-1", errors="replace")
    # Parenthesized PDF string literals: (hello world)
    paren = re.findall(r"\(([^()\\]{2,200})\)", decoded)
    # Long printable runs (fallback).
    runs = re.findall(r"[ -~]{6,}", decoded)
    # Prefer paren captures that look like document text, then runs that are
    # not pure PDF operator soup.
    candidates: List[str] = []
    for p in paren:
        cleaned = p.strip()
        if cleaned and not cleaned.startswith("/"):
            candidates.append(cleaned)
    if not candidates:
        skip = {
            "endobj",
            "endstream",
            "startxref",
            "trailer",
            "%PDF-1.4",
            "%%EOF",
        }
        for r in runs:
            token = r.strip()
            if token in skip:
                continue
            if re.fullmatch(r"[0-9\s.]+", token):
                continue
            if any(c.isalpha() for c in token):
                candidates.append(token)
    joined = " ".join(candidates)
    return _sanitize_human_text(joined)


def _xml_text_nodes(raw: bytes, *, local_names: Sequence[str]) -> str:
    """Collect text from XML elements whose localname is in *local_names*."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PreviewError("xml parse failed: %s" % exc) from exc
    wanted = set(local_names)
    chunks: List[str] = []
    for el in root.iter():
        tag = el.tag
        if isinstance(tag, str) and "}" in tag:
            local = tag.rsplit("}", 1)[-1]
        else:
            local = str(tag)
        if local in wanted:
            text = (el.text or "").strip()
            if text:
                chunks.append(text)
    return "\n".join(chunks)


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


def _peek_ooxml_format(data: bytes) -> Optional[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" in names:
                return "docx"
            if any(n.startswith("ppt/slides/") for n in names):
                return "pptx"
            if "xl/sharedStrings.xml" in names or any(
                n.startswith("xl/worksheets/") for n in names
            ):
                return "xlsx"
            # content types fallback
            if "[Content_Types].xml" in names:
                ct = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
                if "wordprocessingml" in ct:
                    return "docx"
                if "presentationml" in ct:
                    return "pptx"
                if "spreadsheetml" in ct:
                    return "xlsx"
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    return None


def _sanitize_human_text(text: str) -> str:
    """Strip binary signatures and non-printable controls from extracted text."""
    if not text:
        return ""
    # Drop any accidental zip signature representation.
    cleaned = text.replace(ZIP_SIGNATURE_TEXT, "")
    cleaned = cleaned.replace("\x03", "").replace("\x04", "")
    # Keep newlines/tabs; drop other controls.
    out_chars: List[str] = []
    for ch in cleaned:
        o = ord(ch)
        if ch in ("\n", "\r", "\t") or 32 <= o < 127 or o >= 160:
            out_chars.append(ch)
    # Collapse runs of whitespace-ish junk but preserve paragraph breaks.
    lines = []
    for line in "".join(out_chars).splitlines():
        stripped = " ".join(line.split())
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)


def _default_content_type(fmt: str) -> str:
    return {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    }.get(fmt, "application/octet-stream")


def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _zip_bytes(parts: Mapping[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in parts.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def _forced_result(
    filename: str,
    reason: str,
    *,
    content_type: str = "",
    download_href: str = "",
    data: Optional[bytes] = None,
) -> PreviewResult:
    ns = REASON_STATE[reason]
    href = download_href or ("download:%s" % filename)

    if reason == PreviewReason.OK.value:
        sample = make_docx_bytes(["Hello from forced ok preview"])
        text = _sanitize_human_text(_extract_docx(sample))
        return PreviewResult(
            filename=filename if filename.endswith(".docx") else "forced.docx",
            content_type=content_type or _default_content_type("docx"),
            format="docx",
            named_state=NamedState.ok,
            human_text=text,
            reason=reason,
            detail=REASON_LABELS[reason],
            size_bytes=len(sample),
        )

    if reason == PreviewReason.UNSUPPORTED_PREVIEW.value:
        return PreviewResult(
            filename=filename,
            content_type=content_type or "application/octet-stream",
            format="unsupported",
            named_state=NamedState.measurement_failed,
            human_text="",
            reason=reason,
            detail=REASON_LABELS[reason],
            size_bytes=len(data) if data else 4,
            download_href=href,
            unsupported=True,
            meta={"unsupported_preview": True},
        )

    if reason == PreviewReason.EMPTY_FILE.value:
        return PreviewResult(
            filename=filename,
            content_type=content_type or "application/octet-stream",
            format="",
            named_state=NamedState.empty,
            human_text="",
            reason=reason,
            detail=REASON_LABELS[reason],
            size_bytes=0,
        )

    if reason == PreviewReason.PROBE_FAILED.value:
        return PreviewResult(
            filename=filename,
            content_type=content_type,
            format="",
            named_state=NamedState.unknown,
            human_text="",
            reason=reason,
            detail=REASON_LABELS[reason],
            size_bytes=0,
        )

    if reason == PreviewReason.ZERO_MEASURED.value:
        empty_docx = make_empty_docx_bytes()
        return PreviewResult(
            filename=filename if filename.endswith(".docx") else "empty.docx",
            content_type=content_type or _default_content_type("docx"),
            format="docx",
            named_state=NamedState.zero_measured,
            human_text="",
            reason=reason,
            detail=REASON_LABELS[reason],
            size_bytes=len(empty_docx),
            meta={"content_units": 0},
        )

    if reason == PreviewReason.EXTRACT_FAILED.value:
        return PreviewResult(
            filename=filename,
            content_type=content_type or "application/octet-stream",
            format="docx",
            named_state=NamedState.measurement_failed,
            human_text="",
            reason=reason,
            detail=REASON_LABELS[reason],
            size_bytes=len(data) if data else 0,
            download_href=href,
        )

    # capability_absent
    return PreviewResult(
        filename=filename,
        content_type=content_type,
        format="",
        named_state=ns,
        human_text="",
        reason=reason,
        detail=REASON_LABELS.get(reason, reason),
        size_bytes=0,
    )


__all__ = [
    "WAVE_ID",
    "SURFACE_ID",
    "CAPABILITY_CONTROL_ID",
    "INVENTORY_SOURCE_LABEL",
    "INVENTORY_SOURCE_NAME",
    "SUPPORTED_FORMATS",
    "UNSUPPORTED_PREVIEW_LABEL",
    "ZIP_SIGNATURE",
    "ZIP_SIGNATURE_TEXT",
    "PREVIEW_REASONS",
    "INDUCED_FAULT_REASONS",
    "INDUCED_FAULT_UNSUPPORTED",
    "INDUCED_FAULT_EMPTY_FILE",
    "INDUCED_FAULT_PROBE_FAILED",
    "REASON_LABELS",
    "REASON_STATE",
    "PreviewReason",
    "PreviewProbeError",
    "PreviewError",
    "PreviewResult",
    "supported_formats",
    "normalize_preview_reason",
    "preview_reason_named_state",
    "detect_format",
    "preview_bytes",
    "preview_path",
    "force_preview_for_fault",
    "make_docx_bytes",
    "make_pptx_bytes",
    "make_xlsx_bytes",
    "make_pdf_bytes",
    "make_empty_docx_bytes",
]

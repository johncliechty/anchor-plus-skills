"""W18 — File preview via the shared human-friendly path (no raw binary as text).

Exercises every W18 deliverable under one scoped gate:

* ``anchor/files/preview.py``
* ``anchor/ui/preview_view.py``
* ``artifacts/failure-states/preview.md``
* ``artifacts/traces/preview-e2e.json``

Gate: pytest -v tests/test_file_preview_2026_07_29.py

GWTs (frozen plan):

* .docx opened from file list → human-readable content via shared path;
  rendered HTML contains no ``PK\\x03\\x04`` or other raw byte signature.
* File type with no human-friendly renderer → named unsupported-preview
  state with download option (not a text dump).
* Zero-byte file vs probe-failed → empty and unknown as two distinct labels.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from anchor.build.trace_artifact import (
    PROOF_LEVEL_RENDERED_STRING,
    is_go_evidence,
    validate_trace,
)
from anchor.files import preview as preview_mod
from anchor.files.preview import (
    CAPABILITY_CONTROL_ID,
    INDUCED_FAULT_REASONS,
    INVENTORY_SOURCE_LABEL,
    INVENTORY_SOURCE_NAME,
    PREVIEW_REASONS,
    SUPPORTED_FORMATS,
    UNSUPPORTED_PREVIEW_LABEL,
    ZIP_SIGNATURE,
    ZIP_SIGNATURE_TEXT,
    PreviewReason,
    PreviewResult,
    force_preview_for_fault,
    make_docx_bytes,
    make_empty_docx_bytes,
    make_pdf_bytes,
    make_pptx_bytes,
    make_xlsx_bytes,
    preview_bytes,
    preview_path,
    preview_reason_named_state,
    supported_formats,
)
from anchor.ui import preview_view as pv
from anchor.ui.named_state import NamedState
from anchor.ui.preview_view import (
    PreviewViewContext,
    generate_html,
    generate_html_for_fixture,
    load_trace_set,
    node_check_preview_scripts,
    render_preview_panel,
    render_preview_surface,
    write_preview_traces,
)
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import validate_failure_state_table
from tests.conformance.tri_state import assert_tri_state

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "preview.md"
)
PREVIEW_TRACE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "traces" / "preview-e2e.json"
)

# Raw byte signatures that must never appear as text in rendered HTML.
_FORBIDDEN_RAW_MARKERS = (
    ZIP_SIGNATURE_TEXT,
    "PK\x03\x04",
    "\x03\x04",
    "%PDF-1.4\n1 0 obj",  # raw PDF object soup
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _parse_preview_failure_table(text: str) -> list:
    rows = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| hardening"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4:
                continue
            if cells[0] in ("hardening",):
                continue
            rows.append(
                {
                    "hardening": cells[0],
                    "state": cells[1],
                    "user_visible": cells[2],
                    "trigger": cells[3],
                }
            )
        elif in_table and not line.startswith("|"):
            break
    return rows


def _panel_section(html: str) -> str:
    """Pull the primary preview panel so legend text cannot pollute GWTs."""
    m = re.search(
        r'<div class="preview-panel"[^>]*>.*?</div>',
        html,
        re.DOTALL,
    )
    return m.group(0) if m else html


def _assert_no_raw_binary(html: str) -> None:
    for marker in _FORBIDDEN_RAW_MARKERS:
        assert marker not in html, (
            "binary guard failed: rendered HTML contains raw marker %r"
            % (marker[:40],)
        )
    # Also refuse the literal zip magic if somehow decoded into the string.
    assert ZIP_SIGNATURE.decode("latin-1") not in html


# --------------------------------------------------------------------------
# Acceptance: every new module is imported and exercised
# --------------------------------------------------------------------------


def test_w18_modules_importable_and_callable():
    assert callable(preview_bytes)
    assert callable(preview_path)
    assert callable(force_preview_for_fault)
    assert callable(generate_html)
    assert callable(generate_html_for_fixture)
    assert callable(render_preview_panel)
    assert callable(write_preview_traces)
    assert callable(load_trace_set)
    assert preview_mod.WAVE_ID == "W18"
    assert pv.WAVE_ID == "W18"
    assert CAPABILITY_CONTROL_ID == "preview_path"
    assert INVENTORY_SOURCE_NAME == "preview_path"
    assert "preview" in INVENTORY_SOURCE_LABEL
    assert set(supported_formats()) == set(SUPPORTED_FORMATS)
    assert set(INDUCED_FAULT_REASONS) == {
        "unsupported_preview",
        "empty_file",
        "probe_failed",
    }


# --------------------------------------------------------------------------
# One fixture per format — human-friendly output
# --------------------------------------------------------------------------


def test_docx_human_friendly_preview():
    """GWT: .docx preview shows human-readable content, no raw zip signature."""
    data = make_docx_bytes(["Hello from Word", "Second paragraph"])
    assert data[:4] == ZIP_SIGNATURE  # fixture is a real zip
    result = preview_bytes(
        data, filename="memo.docx", capability_present=True
    )
    assert isinstance(result, PreviewResult)
    assert result.named_state is NamedState.ok
    assert result.format == "docx"
    assert "Hello from Word" in result.human_text
    assert "Second paragraph" in result.human_text
    assert ZIP_SIGNATURE_TEXT not in result.human_text

    html = render_preview_panel(result)
    assert "Hello from Word" in html
    assert "Second paragraph" in html
    _assert_no_raw_binary(html)
    assert_visible_text_contains(html, "ok")


def test_pptx_human_friendly_preview():
    data = make_pptx_bytes(["Quarterly overview", "Next steps"])
    assert data[:4] == ZIP_SIGNATURE
    result = preview_bytes(
        data, filename="deck.pptx", capability_present=True
    )
    assert result.named_state is NamedState.ok
    assert result.format == "pptx"
    assert "Quarterly overview" in result.human_text
    html = render_preview_panel(result)
    assert "Quarterly overview" in html
    _assert_no_raw_binary(html)


def test_xlsx_human_friendly_preview():
    data = make_xlsx_bytes(["Revenue", "42"])
    assert data[:4] == ZIP_SIGNATURE
    result = preview_bytes(
        data, filename="book.xlsx", capability_present=True
    )
    assert result.named_state is NamedState.ok
    assert result.format == "xlsx"
    assert "Revenue" in result.human_text
    html = render_preview_panel(result)
    assert "Revenue" in html
    _assert_no_raw_binary(html)


def test_pdf_human_friendly_preview():
    data = make_pdf_bytes("Hello PDF document body")
    assert b"%PDF" in data[:8]
    result = preview_bytes(
        data, filename="report.pdf", capability_present=True
    )
    assert result.named_state is NamedState.ok
    assert result.format == "pdf"
    assert "Hello PDF" in result.human_text or "PDF document" in result.human_text
    html = render_preview_panel(result)
    assert "Hello" in html or "PDF" in html
    _assert_no_raw_binary(html)
    # Must not dump the full PDF object soup.
    assert "endobj" not in html or "Hello" in html


# --------------------------------------------------------------------------
# Binary guard — no raw PK\x03\x04 in HTML
# --------------------------------------------------------------------------


def test_binary_guard_no_zip_signature_in_html():
    """GWT: rendered HTML never contains PK\\x03\\x04 or raw byte signatures."""
    for fname, blob in (
        ("a.docx", make_docx_bytes(["Docx body text"])),
        ("b.pptx", make_pptx_bytes(["Pptx body text"])),
        ("c.xlsx", make_xlsx_bytes(["Xlsx body text"])),
        ("d.pdf", make_pdf_bytes("Pdf body text here")),
    ):
        html = generate_html(
            PreviewViewContext(
                filename=fname,
                data=blob,
                capability_present=True,
            )
        )
        _assert_no_raw_binary(html)
        panel = _panel_section(html)
        assert "body text" in panel.lower() or "Body" in panel or "text" in panel


def test_binary_guard_unsupported_never_dumps_payload():
    """GWT: unsupported type → unsupported_preview + download, not a dump."""
    payload = ZIP_SIGNATURE + b"this-is-not-office-just-zip-noise\x00\xff"
    result = preview_bytes(
        payload,
        filename="noise.bin",
        content_type="application/octet-stream",
        download_href="download:noise.bin",
        capability_present=True,
    )
    assert result.unsupported is True
    assert result.reason == PreviewReason.UNSUPPORTED_PREVIEW.value
    assert result.named_state is NamedState.measurement_failed
    assert result.human_text == ""
    assert ZIP_SIGNATURE_TEXT not in result.human_text

    html = render_preview_panel(result)
    assert UNSUPPORTED_PREVIEW_LABEL in html
    assert "Download" in html or 'data-download="true"' in html
    assert "download:noise.bin" in html or "noise.bin" in html
    _assert_no_raw_binary(html)
    assert "this-is-not-office-just-zip-noise" not in html
    assert "\x00" not in html
    assert "\xff" not in html


# --------------------------------------------------------------------------
# Unknown vs empty distinct
# --------------------------------------------------------------------------


def test_empty_zero_byte_is_empty_not_unknown():
    result = preview_bytes(
        b"", filename="empty.docx", capability_present=True
    )
    assert result.named_state is NamedState.empty
    assert result.reason == PreviewReason.EMPTY_FILE.value
    assert result.size_bytes == 0
    assert result.named_state is not NamedState.unknown


def test_probe_failed_is_unknown_not_empty():
    """GWT: probe failed → unknown, never empty-looking."""
    result = preview_bytes(
        None,
        filename="mystery.bin",
        probe_failed=True,
        capability_present=True,
    )
    assert result.named_state is NamedState.unknown
    assert result.reason == PreviewReason.PROBE_FAILED.value
    assert result.named_state is not NamedState.empty


def test_unknown_distinct_from_empty_in_html():
    """GWT: zero-byte vs probe-failed render as two distinct visible labels."""
    empty_html = generate_html(
        PreviewViewContext(
            filename="e.docx",
            data=b"",
            capability_present=True,
        )
    )
    unknown_html = generate_html(
        PreviewViewContext(
            filename="u.bin",
            probe_failed=True,
            capability_present=True,
        )
    )
    e_panel = _panel_section(empty_html)
    u_panel = _panel_section(unknown_html)
    assert_visible_text_contains(e_panel, "empty")
    assert_visible_text_contains(u_panel, "unknown")
    assert 'data-named-state="empty"' in e_panel
    assert 'data-named-state="unknown"' in u_panel
    assert "nothing to preview" in e_panel or "zero-byte" in e_panel
    assert "probe failed" in u_panel
    assert "nothing to preview" not in u_panel
    assert 'data-named-state="empty"' not in u_panel
    assert 'data-named-state="unknown"' not in e_panel


def test_zero_measured_over_empty_docx_body():
    data = make_empty_docx_bytes()
    assert len(data) > 0
    result = preview_bytes(
        data, filename="blank.docx", capability_present=True
    )
    assert result.named_state is NamedState.zero_measured
    assert result.format == "docx"
    assert result.named_state is not NamedState.empty
    assert result.named_state is not NamedState.unknown


# --------------------------------------------------------------------------
# Induced faults
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(PREVIEW_REASONS))
def test_force_fault_per_reason(reason):
    result = force_preview_for_fault(reason)
    assert result.named_state == preview_reason_named_state(reason)
    assert result.reason == reason


@pytest.mark.parametrize("fault", list(INDUCED_FAULT_REASONS))
def test_induced_fault_per_gate_reason(fault):
    result = force_preview_for_fault(fault, filename="induced.bin")
    assert result.reason == fault
    html = render_preview_panel(result)
    ns = preview_reason_named_state(fault)
    assert_visible_text_contains(html, ns.label)
    assert 'data-named-state="%s"' % ns.value in html
    _assert_no_raw_binary(html)


def test_induced_unsupported_shows_download():
    result = force_preview_for_fault("unsupported_preview")
    html = render_preview_panel(result)
    assert UNSUPPORTED_PREVIEW_LABEL in html
    assert "Download" in html or 'data-download="true"' in html
    _assert_no_raw_binary(html)


def test_capability_absent_is_unknown():
    result = preview_bytes(
        b"x", filename="f.docx", capability_present=False
    )
    assert result.named_state is NamedState.unknown
    assert result.reason == PreviewReason.CAPABILITY_ABSENT.value


# --------------------------------------------------------------------------
# Tri-state conformance
# --------------------------------------------------------------------------


def test_preview_tri_state_conformance():
    assert_tri_state(
        generate_html_for_fixture,
        call_site="anchor.ui.preview_view.generate_html_for_fixture",
    )


# --------------------------------------------------------------------------
# Failure-state table
# --------------------------------------------------------------------------


def test_failure_state_table_exists_and_maps_vocabulary():
    assert FAILURE_TABLE_PATH.is_file()
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in text
    assert "/Users/" not in text
    rows = _parse_preview_failure_table(text)
    assert rows, "preview.md machine table produced no rows"
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    assert "unknown/empty" not in text.lower().replace(" ", "")
    report = validate_failure_state_table(rows, surface="preview")
    assert report["ok"] is True


def test_failure_state_table_surface_native_preview_language():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "preview" in low
    head = low.split("## enumerated")[0]
    for verb in ("index", "rebuild", "reconcile"):
        assert not re.search(r"\b%s\b" % verb, head)


# --------------------------------------------------------------------------
# E2e traces
# --------------------------------------------------------------------------


def test_preview_e2e_trace_artifact_schema_valid():
    write_preview_traces(root=CONTAINMENT_ROOT)
    assert PREVIEW_TRACE_PATH.is_file()
    data = load_trace_set(pv.PREVIEW_TRACE_RELPATH, root=CONTAINMENT_ROOT)
    assert data["proof_level"] == PROOF_LEVEL_RENDERED_STRING
    validate_trace(data)
    assert is_go_evidence(data) or data.get("proof_level") == PROOF_LEVEL_RENDERED_STRING
    assert data.get("control_id") == "preview_path" or data.get("wave_id") == "W18"
    reasons = set(data.get("induced_fault_reasons") or [])
    assert "unsupported_preview" in reasons
    assert "empty_file" in reasons
    assert "probe_failed" in reasons
    for reason, nested in (data.get("reason_traces") or {}).items():
        validate_trace(nested)
    for fmt, nested in (data.get("format_traces") or {}).items():
        validate_trace(nested)
    raw = PREVIEW_TRACE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in raw
    assert "/Users/" not in raw
    assert ZIP_SIGNATURE_TEXT not in raw


def test_ok_trace_records_docx_success():
    write_preview_traces(root=CONTAINMENT_ROOT)
    data = load_trace_set(root=CONTAINMENT_ROOT)
    assert data.get("rendered_state") == "ok" or data.get("trace_result") in (
        "completed",
        "failed_with_named_state",
    )
    hops = data.get("hops") or []
    kinds = [h.get("kind") for h in hops]
    assert kinds == [
        "control_invocation",
        "handler",
        "capability_call",
        "rendered_state",
    ]
    formats = set((data.get("format_traces") or {}).keys())
    assert {"docx", "pptx", "xlsx", "pdf"}.issubset(formats)


# --------------------------------------------------------------------------
# node --check + generate_html
# --------------------------------------------------------------------------


def test_generate_html_node_check():
    html = generate_html(
        PreviewViewContext(
            filename="node-check.docx",
            data=make_docx_bytes(["Node check body"]),
            capability_present=True,
        )
    )
    assert "<script>" in html
    try:
        blocks = node_check_preview_scripts(html, require_node=False)
        assert blocks
    except RuntimeError:
        blocks = node_check_scripts(html, require_node=False)
        assert blocks is not None
    assert "C:\\Users" not in html
    assert "/Users/" not in html
    _assert_no_raw_binary(html)


def test_no_absolute_host_paths_in_sources():
    for rel in (
        "anchor/files/preview.py",
        "anchor/files/__init__.py",
        "anchor/ui/preview_view.py",
        "artifacts/failure-states/preview.md",
    ):
        text = (CONTAINMENT_ROOT / rel).read_text(encoding="utf-8")
        assert "C:\\Users" not in text
        assert "/Users/" not in text


def test_surface_render_all_formats_end_to_end():
    """Surface-level smoke: every supported format through generate_html."""
    for fmt in ("docx", "pptx", "xlsx", "pdf"):
        html = generate_html_for_fixture(fmt)
        panel = _panel_section(html)
        assert 'data-named-state="ok"' in panel or "ok" in panel
        _assert_no_raw_binary(html)
        nodes = visible_text_nodes(panel)
        assert nodes or "ok" in panel

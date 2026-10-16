"""Wave 7 — report viewer (AC2).

AC2: Given an effort with report.pdf, when opened, the viewer shows the PDF by
     DEFAULT; given only report.md, the Reader renders it with KaTeX math.

Asserts the served bytes/headers distinguish PDF-default vs Reader, and that the
Reader HTML links the vendored vendor/katex/ assets and includes the md content.
No subprocess, no live claude, no network.
"""
import importlib
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "katex"


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import report_viewer
    importlib.reload(report_viewer)
    return report_viewer, effort_history, rnd_registry


def _project_lane(rnd, eh, tmp_path, lane="research"):
    folder = tmp_path / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    proj = rnd.add_project("P", str(folder))
    pid = proj["id"]
    ld = eh.lane_dir(folder, pid, lane)
    ld.mkdir(parents=True, exist_ok=True)
    return proj, ld


def test_vendored_katex_assets_present():
    # The Reader references these; they must be vendored locally (no network).
    assert (VENDOR / "katex.min.css").is_file()
    assert (VENDOR / "katex.min.js").is_file()
    assert (VENDOR / "auto-render.min.js").is_file()
    assert (VENDOR / "PROVENANCE.txt").is_file()


def test_pdf_present_served_by_default(mods, tmp_path):
    rv, eh, rnd = mods
    proj, ld = _project_lane(rnd, eh, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]

    # BOTH md and pdf present → PDF must win (default).
    (ld / "report.md").write_text("# hi\n", encoding="utf-8")
    pdf_bytes = b"%PDF-1.7\n%fake pdf body\n%%EOF\n"
    (ld / "report.pdf").write_bytes(pdf_bytes)

    out = rv.render_effort(folder, pid, "research")
    assert out["mode"] == "pdf"
    assert out["content_type"] == "application/pdf"
    assert out["body"] == pdf_bytes  # raw PDF bytes served
    assert isinstance(out["body"], bytes)


def test_only_md_renders_reader_with_vendored_katex(mods, tmp_path):
    rv, eh, rnd = mods
    proj, ld = _project_lane(rnd, eh, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]

    md = "# Research Report\n\nMass-energy is $E = mc^2$ and a block:\n\n$$\\int_0^1 x\\,dx$$\n"
    (ld / "report.md").write_text(md, encoding="utf-8")

    out = rv.render_effort(folder, pid, "research")
    assert out["mode"] == "reader"
    assert out["content_type"].startswith("text/html")
    body = out["body"]
    assert isinstance(body, str)
    # Reader links the VENDORED katex assets (local, not a CDN).
    assert "/vendor/katex/katex.min.css" in body
    assert "/vendor/katex/katex.min.js" in body
    assert "/vendor/katex/auto-render.min.js" in body
    assert "renderMathInElement" in body
    assert "cdn.jsdelivr" not in body and "http://" not in body.replace("http://www.w3", "")
    # The md content is present (heading rendered, math delimiters preserved).
    assert "Research Report" in body
    assert "$E = mc^2$" in body or "E = mc^2" in body
    assert "\\int_0^1" in body


def test_missing_artifact_yields_friendly_notice(mods, tmp_path):
    rv, eh, rnd = mods
    proj, ld = _project_lane(rnd, eh, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]
    out = rv.render_effort(folder, pid, "research")
    assert out["mode"] == "missing"
    assert "No report" in out["body"]


def test_resolve_artifact_pdf_default_flag(mods, tmp_path):
    rv, eh, rnd = mods
    proj, ld = _project_lane(rnd, eh, tmp_path)
    pid, folder = proj["id"], proj["folder_path"]
    (ld / "report.md").write_text("# x", encoding="utf-8")
    assert rv.resolve_artifact(folder, pid, "research")["mode"] == "reader"
    (ld / "report.pdf").write_bytes(b"%PDF-1.4\n")
    assert rv.resolve_artifact(folder, pid, "research")["mode"] == "pdf"


def test_katex_asset_serves_local_file_and_blocks_traversal(mods, tmp_path):
    rv, eh, rnd = mods
    css = rv.katex_asset("katex.min.css")
    assert css is not None
    data, ctype = css
    assert ctype.startswith("text/css")
    assert b"KaTeX" in data or b"katex" in data.lower()
    # Path traversal must be refused.
    assert rv.katex_asset("../../paths.py") is None
    assert rv.katex_asset("does-not-exist.js") is None


def test_markdown_escapes_html_but_preserves_math(mods, tmp_path):
    rv, _eh, _rnd = mods
    page = rv.reader_html("Danger <script>alert(1)</script> and $a+b$")
    assert "<script>alert(1)</script>" not in page  # escaped
    assert "&lt;script&gt;" in page
    assert "$a+b$" in page  # math delimiters preserved for KaTeX

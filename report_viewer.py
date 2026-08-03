#!/usr/bin/env python3
"""Anchor report viewer — serve an effort's artifacts (Wave 7).

Given an effort (a project + lane + optional job_id), the viewer serves its
report artifact:

- **PDF by DEFAULT** when ``report.pdf`` is present — the browser renders PDF
  natively, so the viewer returns the PDF bytes with ``Content-Type:
  application/pdf`` (AC2).
- otherwise a **Reader**: ``report.md`` rendered to HTML with **vendored KaTeX**
  for math. No Python dependency and NO network at runtime — the emitted HTML
  links the LOCAL ``vendor/katex/`` CSS + JS + an auto-render call (AC2).

The same viewer serves research AND plan/build docs (it serves any effort's
md/pdf — MASTER-PLAN "Report viewer").

This module is the pure (HTTP-agnostic) core: it resolves the artifact, builds
the Reader HTML, and exposes a single :func:`render_effort` entry the GUI route
wraps. Stdlib only.
"""

import html
import re
from pathlib import Path

import paths as _paths
import effort_history as _eh

# The vendored KaTeX assets live next to the code, under vendor/katex/. They are
# served by the GUI as static files; the Reader HTML references them by URL.
VENDOR_KATEX_DIR = _paths.CODE_DIR / "vendor" / "katex"

#: URL prefix the GUI mounts the vendored KaTeX dir at (read-only static route).
KATEX_URL_PREFIX = "/vendor/katex"

# Content modes returned by resolve_artifact / render_effort.
MODE_PDF = "pdf"
MODE_READER = "reader"
MODE_MISSING = "missing"


# ── Artifact resolution (PDF-default) ───────────────────────────────────────

def resolve_artifact(folder_path, project_id: str, lane: str,
                     job_id: str = None) -> dict:
    """Decide what to serve for an effort. PDF wins when present (AC2).

    Returns ``{"mode": "pdf"|"reader"|"missing", "pdf_path": str|None,
    "md_path": str|None}``. ``mode == "pdf"`` whenever ``report.pdf`` exists
    (default); else ``"reader"`` when ``report.md`` exists; else ``"missing"``.
    """
    arts = _eh.detect_artifacts(folder_path, project_id, lane, job_id)
    if arts["report_pdf"]:
        return {"mode": MODE_PDF, "pdf_path": arts["pdf_path"],
                "md_path": arts["md_path"]}
    if arts["report_md"]:
        return {"mode": MODE_READER, "pdf_path": None,
                "md_path": arts["md_path"]}
    return {"mode": MODE_MISSING, "pdf_path": None, "md_path": None}


# ── Minimal, safe Markdown → HTML (stdlib only) ─────────────────────────────
# Deliberately small: headings, fenced code, inline code, bold/italic, links,
# lists, paragraphs. Math delimiters ($...$, $$...$$, \(..\), \[..\]) are left
# UNTOUCHED so KaTeX auto-render can typeset them client-side.

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    """Apply inline markdown to an already-escaped line."""
    # text arrives HTML-escaped; apply inline formatting on top.
    text = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", text)
    text = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", text)
    text = _LINK.sub(
        lambda m: f'<a href="{m.group(2)}" rel="noopener noreferrer">'
                  f"{m.group(1)}</a>",
        text,
    )
    return text


def markdown_to_html(md_text: str) -> str:
    """Render markdown to a safe HTML fragment, preserving math delimiters.

    Math (``$...$``, ``$$...$$``) is escaped for HTML but NOT formatted, so the
    client-side KaTeX auto-render call typesets it. Fenced ``` code blocks are
    emitted verbatim (escaped) with NO inline formatting and NO math handling.
    """
    lines = md_text.split("\n")
    out = []
    i = 0
    in_code = False
    code_buf = []
    list_open = False

    def close_list():
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code block toggling.
        if stripped.startswith("```"):
            if in_code:
                out.append("<pre><code>" + "\n".join(code_buf) + "</code></pre>")
                code_buf = []
                in_code = False
            else:
                close_list()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(html.escape(line))
            i += 1
            continue

        if not stripped:
            close_list()
            i += 1
            continue

        # Headings.
        m = re.match(r"(#{1,6})\s+(.*)$", stripped)
        if m:
            close_list()
            level = len(m.group(1))
            content = _inline(html.escape(m.group(2)))
            out.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        # Unordered list items.
        if re.match(r"[-*+]\s+", stripped):
            if not list_open:
                out.append("<ul>")
                list_open = True
            item = re.sub(r"^[-*+]\s+", "", stripped)
            out.append(f"<li>{_inline(html.escape(item))}</li>")
            i += 1
            continue

        # Paragraph.
        close_list()
        out.append(f"<p>{_inline(html.escape(stripped))}</p>")
        i += 1

    if in_code:  # unterminated fence — flush what we have
        out.append("<pre><code>" + "\n".join(code_buf) + "</code></pre>")
    close_list()
    return "\n".join(out)


# ── Reader HTML (vendored KaTeX, no network) ────────────────────────────────

def reader_html(md_text: str, title: str = "Report",
                katex_url_prefix: str = KATEX_URL_PREFIX) -> str:
    """Build the full Reader HTML page for a markdown report.

    The page LINKS the vendored KaTeX assets (``<katex_url_prefix>/katex.min.css``
    + ``katex.min.js`` + ``auto-render.min.js``) and calls ``renderMathInElement``
    so ``$...$`` / ``$$...$$`` math typesets client-side with NO network and NO
    Python dependency (AC2). Styled to match the Anchor dark theme.
    """
    body = markdown_to_html(md_text)
    safe_title = html.escape(title)
    css_href = f"{katex_url_prefix}/katex.min.css"
    js_src = f"{katex_url_prefix}/katex.min.js"
    autorender_src = f"{katex_url_prefix}/auto-render.min.js"
    # NOTE: kept as ordinary string concatenation (NOT an f-string) so the CSS/JS
    # braces need no doubling and cannot corrupt the GUI's f-strings.
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>" + safe_title + "</title>\n"
        "<link rel=\"stylesheet\" href=\"" + css_href + "\">\n"
        "<style>\n"
        "  body{background:#0f1117;color:#e6e8ee;"
        "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        "max-width:820px;margin:0 auto;padding:32px 20px;line-height:1.6}\n"
        "  h1,h2,h3,h4{color:#6c9cfc}\n"
        "  a{color:#6c9cfc}\n"
        "  code{background:#1b1f2a;padding:2px 5px;border-radius:4px;"
        "font-size:.92em}\n"
        "  pre{background:#1b1f2a;padding:14px;border-radius:8px;overflow:auto}\n"
        "  pre code{background:none;padding:0}\n"
        "</style>\n</head>\n<body>\n"
        "<article class=\"anchor-reader\">\n" + body + "\n</article>\n"
        "<script defer src=\"" + js_src + "\"></script>\n"
        "<script defer src=\"" + autorender_src + "\"></script>\n"
        "<script>\n"
        "  document.addEventListener('DOMContentLoaded', function(){\n"
        "    if (window.renderMathInElement) {\n"
        "      renderMathInElement(document.body, {\n"
        "        delimiters: [\n"
        "          {left:'$$', right:'$$', display:true},\n"
        "          {left:'$', right:'$', display:false},\n"
        "          {left:'\\\\(', right:'\\\\)', display:false},\n"
        "          {left:'\\\\[', right:'\\\\]', display:true}\n"
        "        ],\n"
        "        throwOnError:false\n"
        "      });\n"
        "    }\n"
        "  });\n"
        "</script>\n</body>\n</html>\n"
    )


# ── The HTTP-agnostic render entry the GUI route wraps ──────────────────────

def render_effort(folder_path, project_id: str, lane: str,
                  job_id: str = None, title: str = None) -> dict:
    """Resolve + render an effort for serving.

    Returns one of:
      - PDF:    ``{"mode":"pdf", "content_type":"application/pdf",
                   "body": <bytes>, "path": <pdf_path>}``
      - Reader: ``{"mode":"reader", "content_type":"text/html; charset=utf-8",
                   "body": <str>, "path": <md_path>}``
      - Missing:``{"mode":"missing", "content_type":"text/html; charset=utf-8",
                   "body": <html str>, "path": None}``  (a friendly notice)

    The GUI route writes ``body`` (encoding str→utf-8) with ``content_type``.
    """
    art = resolve_artifact(folder_path, project_id, lane, job_id)
    if art["mode"] == MODE_PDF:
        data = Path(art["pdf_path"]).read_bytes()
        return {"mode": MODE_PDF, "content_type": "application/pdf",
                "body": data, "path": art["pdf_path"]}
    if art["mode"] == MODE_READER:
        md_text = Path(art["md_path"]).read_text(encoding="utf-8")
        page = reader_html(md_text, title or f"{lane} report")
        return {"mode": MODE_READER,
                "content_type": "text/html; charset=utf-8",
                "body": page, "path": art["md_path"]}
    notice = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>No report</title></head>"
        "<body style='background:#0f1117;color:#e6e8ee;font-family:sans-serif;"
        "padding:40px'>"
        "<h2 style='color:#6c9cfc'>No report yet</h2>"
        "<p>This effort has no <code>report.pdf</code> or <code>report.md</code>"
        " artifact.</p></body></html>"
    )
    return {"mode": MODE_MISSING, "content_type": "text/html; charset=utf-8",
            "body": notice, "path": None}


# ── Vendored static-asset serving (read-only) ───────────────────────────────

_KATEX_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}


# ── Discovered-artifact serving (brownfield, traversal-safe) ────────────────

# Subdirs inside a project folder that must NEVER be served, even if a rel path
# resolves to stay within the folder (defense in depth beyond containment).
_ARTIFACT_FORBIDDEN_TOP = frozenset({".git", ".anchor"})

# Content types for served discovered artifacts (best-effort; default text).
_ARTIFACT_CONTENT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
}


def resolve_project_artifact(folder_path, rel_path: str):
    """Resolve a discovered artifact under a project folder, traversal-safe.

    Mirrors the proven :func:`katex_asset` containment pattern:
      ``target = (folder / rel).resolve()`` then
      ``target.relative_to(folder.resolve())`` or reject.

    Rejects:
      - a missing/blank folder or rel,
      - an ABSOLUTE ``rel`` (e.g. ``/etc/passwd`` / ``C:\\Windows\\...``),
      - any ``rel`` that resolves OUTSIDE the folder (``../..`` / symlink-escape),
      - any path whose first folder-relative component is ``.git`` / ``.anchor``.

    Returns ``(bytes, content_type)`` on success, else ``None`` — and on
    rejection reads ZERO bytes. Stdlib only.
    """
    if not folder_path or not rel_path:
        return None
    rel_raw = str(rel_path)
    # Reject an absolute rel before any join (POSIX or Windows-drive form).
    try:
        if Path(rel_raw).is_absolute():
            return None
    except (TypeError, ValueError):
        return None
    # A leading slash/backslash also denotes absolute on the URL side.
    if rel_raw.startswith("/") or rel_raw.startswith("\\"):
        return None

    try:
        folder = Path(folder_path).resolve()
    except OSError:
        return None
    try:
        target = (folder / rel_raw).resolve()
    except OSError:
        return None

    # Containment: target must stay within the folder.
    try:
        rel_inside = target.relative_to(folder)
    except ValueError:
        return None

    # Reject .git / .anchor at the top of the resolved relative path.
    parts = rel_inside.parts
    if parts and parts[0] in _ARTIFACT_FORBIDDEN_TOP:
        return None
    # Also reject any component that is one of the forbidden dirs (symlink-in).
    if any(p in _ARTIFACT_FORBIDDEN_TOP for p in parts):
        return None

    if not target.is_file():
        return None
    ctype = _ARTIFACT_CONTENT_TYPES.get(target.suffix.lower(),
                                        "application/octet-stream")
    try:
        return target.read_bytes(), ctype
    except OSError:
        return None


def katex_asset(rel_path: str):
    """Resolve a request under ``/vendor/katex/<rel>`` to (bytes, content_type).

    Path-traversal safe: the resolved file MUST stay within ``VENDOR_KATEX_DIR``.
    Returns ``None`` if the asset does not exist or escapes the vendor dir.
    """
    rel = rel_path.lstrip("/")
    target = (VENDOR_KATEX_DIR / rel).resolve()
    try:
        target.relative_to(VENDOR_KATEX_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = _KATEX_CONTENT_TYPES.get(target.suffix.lower(),
                                     "application/octet-stream")
    return target.read_bytes(), ctype

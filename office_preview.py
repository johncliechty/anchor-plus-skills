"""Human-friendly previews of Office documents — stdlib only (2026-09-04).

John: "when I go to open deliverables ... I got something like raw data. PDFs,
MD, Word, PPT, Excel docs should all show up well." A browser renders PDF and
the Reader renders markdown; it renders none of the Office formats, and the
product may carry no third-party dependency. But .docx / .pptx / .xlsx are
zip archives of XML, so this module reads the text a human wants — paragraphs
and tables from Word, slide titles and bodies from PowerPoint, each sheet as a
table from Excel — with ``zipfile`` + ``xml.etree`` alone, and renders a
plain HTML page next to a download link (the native app is one click away).

Honest limits: no images, charts, formatting, formulas (values only), or
embedded objects — the page says so. Every string is HTML-escaped.
"""
from __future__ import annotations

import html
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

OFFICE_EXTENSIONS = {".docx": "Word", ".pptx": "PowerPoint", ".xlsx": "Excel"}
LEGACY_OFFICE = {".doc": "Word", ".ppt": "PowerPoint", ".xls": "Excel"}
MAX_ROWS_PER_SHEET = 500
MAX_SLIDES = 300
MAX_PARAGRAPHS = 5000

_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def is_office(path) -> bool:
    return Path(str(path)).suffix.lower() in OFFICE_EXTENSIONS


def kind_of(path) -> str:
    return OFFICE_EXTENSIONS.get(Path(str(path)).suffix.lower(), "")


# ── Word ───────────────────────────────────────────────────────────────────

def _w_text(el) -> str:
    parts = []
    for node in el.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t" and node.text:
            parts.append(node.text)
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
    return "".join(parts)


def _w_style(p) -> str:
    st = p.find("w:pPr/w:pStyle", _NS)
    return (st.get("{%s}val" % _NS["w"]) or "") if st is not None else ""


def docx_blocks(data: bytes) -> list:
    """Word body → [("h", level, text) | ("p", text) | ("li", text) | ("table", rows)]."""
    out = []
    with zipfile.ZipFile(_bytes_io(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find("w:body", _NS)
    if body is None:
        return out
    n = 0
    for child in list(body):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            n += 1
            if n > MAX_PARAGRAPHS:
                out.append(("p", "… (document truncated for preview)"))
                break
            text = _w_text(child).strip()
            if not text:
                continue
            style = _w_style(child).lower()
            m = re.match(r"heading(\d)", style) or re.match(r"berschrift(\d)", style)
            if style == "title":
                out.append(("h", 1, text))
            elif m:
                out.append(("h", min(6, int(m.group(1)) + 1), text))
            elif child.find("w:pPr/w:numPr", _NS) is not None or style.startswith("list"):
                out.append(("li", text))
            else:
                out.append(("p", text))
        elif tag == "tbl":
            rows = []
            for tr in child.findall("w:tr", _NS):
                rows.append([_w_text(tc).strip() for tc in tr.findall("w:tc", _NS)])
            if rows:
                out.append(("table", rows))
    return out


# ── PowerPoint ─────────────────────────────────────────────────────────────

def _rels(z, rels_path: str) -> dict:
    try:
        root = ET.fromstring(z.read(rels_path))
    except KeyError:
        return {}
    return {r.get("Id"): r.get("Target") for r in root.findall("rel:Relationship", _NS)}


def pptx_slides(data: bytes) -> list:
    """Slides in presentation order → [{"n": i, "title": str, "body": [str], "notes": str}]."""
    out = []
    with zipfile.ZipFile(_bytes_io(data)) as z:
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        rels = _rels(z, "ppt/_rels/presentation.xml.rels")
        order = []
        lst = pres.find("p:sldIdLst", _NS)
        if lst is not None:
            for sld in lst.findall("p:sldId", _NS):
                target = rels.get(sld.get("{%s}id" % _NS["r"]))
                if target:
                    order.append("ppt/" + target.lstrip("/").replace("ppt/", "", 1) if not target.startswith("ppt/") else target)
        if not order:  # no id list: fall back to the archive's slide files
            order = sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n))
        for i, name in enumerate(order[:MAX_SLIDES], 1):
            try:
                slide = ET.fromstring(z.read(name))
            except KeyError:
                continue
            title, body = "", []
            for sp in slide.iter("{%s}sp" % _NS["p"]):
                ph = sp.find("p:nvSpPr/p:nvPr/p:ph", _NS)
                ptype = (ph.get("type") or "body") if ph is not None else ""
                # Slide numbers, dates and footers are chrome, not content.
                if ptype in ("sldNum", "dt", "ftr"):
                    continue
                nv = sp.find("p:nvSpPr/p:cNvPr", _NS)
                shape_name = (nv.get("name") or "").strip().lower() if nv is not None else ""
                paras = []
                for para in sp.iter("{%s}p" % _NS["a"]):
                    t = "".join(x.text or "" for x in para.iter("{%s}t" % _NS["a"])).strip()
                    if t:
                        paras.append(t)
                if not paras:
                    continue
                # A slide built without placeholders (a designed title slide)
                # still names its title shape "Title N" — honor that.
                is_title = ptype in ("title", "ctrTitle") or (ph is None and shape_name.startswith("title"))
                if is_title and not title:
                    title = " ".join(paras)
                else:
                    body.extend(paras)
            notes = ""
            m = re.search(r"slide(\d+)\.xml$", name)
            if m:
                try:
                    nroot = ET.fromstring(z.read("ppt/notesSlides/notesSlide%s.xml" % m.group(1)))
                    notes = " ".join(x.text or "" for x in nroot.iter("{%s}t" % _NS["a"])).strip()
                except KeyError:
                    pass
            out.append({"n": i, "title": title, "body": body, "notes": notes})
    return out


# ── Excel ──────────────────────────────────────────────────────────────────

def _col_index(ref: str) -> int:
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return 0
    n = 0
    for ch in letters.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def xlsx_sheets(data: bytes) -> list:
    """Sheets → [{"name": str, "rows": [[str]], "truncated": bool}] (values only)."""
    out = []
    with zipfile.ZipFile(_bytes_io(data)) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = _rels(z, "xl/_rels/workbook.xml.rels")
        shared = []
        try:
            ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in ss.findall("s:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["s"])))
        except KeyError:
            pass
        sheets = wb.find("s:sheets", _NS)
        for sh in (sheets.findall("s:sheet", _NS) if sheets is not None else []):
            target = rels.get(sh.get("{%s}id" % _NS["r"])) or ""
            path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
            try:
                root = ET.fromstring(z.read(path))
            except KeyError:
                continue
            rows, truncated = [], False
            for i, row in enumerate(root.iter("{%s}row" % _NS["s"])):
                if i >= MAX_ROWS_PER_SHEET:
                    truncated = True
                    break
                cells = []
                for c in row.findall("s:c", _NS):
                    idx = _col_index(c.get("r", ""))
                    while len(cells) < idx:
                        cells.append("")
                    t = c.get("t")
                    v = c.find("s:v", _NS)
                    if t == "s" and v is not None and v.text is not None:
                        try:
                            val = shared[int(v.text)]
                        except (ValueError, IndexError):
                            val = v.text
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter("{%s}t" % _NS["s"]))
                    elif t == "b" and v is not None:
                        val = "TRUE" if v.text == "1" else "FALSE"
                    else:
                        val = (v.text or "") if v is not None else ""
                    cells.append(val)
                rows.append(cells)
            out.append({"name": sh.get("name") or path, "rows": rows, "truncated": truncated})
    return out


# ── HTML ───────────────────────────────────────────────────────────────────

_CSS = """
body{margin:0;background:#0f1117;color:#e2e4e9;font:15px/1.55 -apple-system,'Segoe UI',system-ui,sans-serif}
.bar{position:sticky;top:0;background:#1a1d27;border-bottom:1px solid #2e3340;padding:10px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.bar b{font-size:15px}.bar .kind{color:#8b8f9a;font-size:12px}
.bar a{color:#6c9cfc;text-decoration:none;border:1px solid #2e3340;border-radius:8px;padding:5px 10px;font-size:13px}
.bar .note{color:#8b8f9a;font-size:12px;margin-left:auto}
main{max-width:980px;margin:0 auto;padding:22px 18px 60px}
h1,h2,h3,h4{margin:1.1em 0 .4em;line-height:1.25}h1{font-size:24px}h2{font-size:20px}h3{font-size:17px}
p{margin:.45em 0;white-space:pre-wrap}li{margin:.2em 0}
table{border-collapse:collapse;margin:.8em 0;max-width:100%;display:block;overflow-x:auto}
td,th{border:1px solid #2e3340;padding:4px 8px;font-size:13px;vertical-align:top;white-space:pre-wrap}
th{background:#232733;text-align:left}
.slide{border:1px solid #2e3340;border-radius:10px;padding:14px 18px;margin:14px 0;background:#151922}
.slide .n{color:#8b8f9a;font-size:12px;letter-spacing:.06em;text-transform:uppercase}
.slide h2{margin:.2em 0 .5em;font-size:18px}.slide .notes{color:#8b8f9a;font-size:13px;border-top:1px dashed #2e3340;margin-top:10px;padding-top:8px}
.sheet h2{font-size:16px;margin-top:1.6em}.dim{color:#8b8f9a;font-size:12px}
"""


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _table_html(rows, header_first=False) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    out = ["<table>"]
    for i, r in enumerate(rows):
        cells = list(r) + [""] * (width - len(r))
        tag = "th" if (header_first and i == 0) else "td"
        out.append("<tr>" + "".join("<%s>%s</%s>" % (tag, _esc(c), tag) for c in cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


def render_preview(data: bytes, filename: str, download_href: str = "") -> str:
    """The preview page for one Office file. Total: a broken/unknown file yields an honest page."""
    ext = Path(filename).suffix.lower()
    kind = OFFICE_EXTENSIONS.get(ext, "Office")
    body, problem = "", ""
    try:
        if ext == ".docx":
            parts, in_list = [], False
            for blk in docx_blocks(data):
                if blk[0] == "li":
                    if not in_list:
                        parts.append("<ul>"); in_list = True
                    parts.append("<li>%s</li>" % _esc(blk[1]))
                    continue
                if in_list:
                    parts.append("</ul>"); in_list = False
                if blk[0] == "h":
                    parts.append("<h%d>%s</h%d>" % (blk[1], _esc(blk[2]), blk[1]))
                elif blk[0] == "p":
                    parts.append("<p>%s</p>" % _esc(blk[1]))
                elif blk[0] == "table":
                    parts.append(_table_html(blk[1], header_first=True))
            if in_list:
                parts.append("</ul>")
            body = "".join(parts) or "<p class='dim'>(no text in this document)</p>"
        elif ext == ".pptx":
            parts = []
            for s in pptx_slides(data):
                parts.append("<section class='slide'><div class='n'>Slide %d</div>" % s["n"])
                if s["title"]:
                    parts.append("<h2>%s</h2>" % _esc(s["title"]))
                if s["body"]:
                    parts.append("<ul>" + "".join("<li>%s</li>" % _esc(t) for t in s["body"]) + "</ul>")
                if s["notes"]:
                    parts.append("<div class='notes'>Notes: %s</div>" % _esc(s["notes"]))
                parts.append("</section>")
            body = "".join(parts) or "<p class='dim'>(no slides found)</p>"
        elif ext == ".xlsx":
            parts = []
            for sh in xlsx_sheets(data):
                parts.append("<section class='sheet'><h2>%s</h2>" % _esc(sh["name"]))
                parts.append(_table_html(sh["rows"], header_first=True) or "<p class='dim'>(empty sheet)</p>")
                if sh["truncated"]:
                    parts.append("<p class='dim'>Showing the first %d rows — download for the rest.</p>" % MAX_ROWS_PER_SHEET)
                parts.append("</section>")
            body = "".join(parts) or "<p class='dim'>(no sheets found)</p>"
        else:
            problem = "No preview for this file type."
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError) as exc:
        problem = "Could not read this file as %s (%s: %s)." % (kind, type(exc).__name__, exc)
    if problem:
        body = "<p class='dim'>%s Use Download to open it in %s.</p>" % (_esc(problem), _esc(kind))
    dl = ('<a href="%s">Download · open in %s</a>' % (_esc(download_href), _esc(kind))) if download_href else ""
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>%s</title><style>%s</style></head><body>"
        "<div class='bar'><b>%s</b><span class='kind'>%s · text preview</span>%s"
        "<span class='note'>Text, tables and slide notes only — no images, charts or formatting.</span></div>"
        "<main>%s</main></body></html>"
        % (_esc(Path(filename).name), _CSS, _esc(Path(filename).name), _esc(kind), dl, body)
    )


def _bytes_io(data: bytes):
    import io
    return io.BytesIO(data)

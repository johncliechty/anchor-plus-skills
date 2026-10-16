"""Deliverables open well (John, 2026-09-04): "when I go to open deliverables
... I got something like raw data. PDFs, MD, Word, PPT, Excel docs should all
show up well."

The cockpit's deliverable-file route served everything but PDF/PNG/JSON as
text/plain — a .pptx opened as bytes painted on a page. Now every extension
has an honest content type, Office documents get a stdlib text preview page
(zip + xml, no dependency) with a download that opens the native app, and
unknown types download under their own name.
"""
import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import office_preview as op  # noqa: E402
from steward_cockpit import steward_routes as sr  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def docx_bytes():
    doc = (
        '<w:document xmlns:w="%s"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Lecture 1</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Hello </w:t></w:r><w:r><w:t>world &amp; friends</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>first point</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Term</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>x</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>&lt;script&gt;</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        '</w:body></w:document>' % W
    )
    return _zip({"word/document.xml": doc})


def pptx_bytes():
    pres = ('<p:presentation xmlns:p="%s" xmlns:r="%s"><p:sldIdLst>'
            '<p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>' % (P, R))
    rels = ('<Relationships xmlns="%s"><Relationship Id="rId1" Target="slides/slide2.xml"/>'
            '<Relationship Id="rId2" Target="slides/slide1.xml"/></Relationships>' % REL)

    def slide(title, bullets, kind="title"):
        sp_title = ('<p:sp><p:nvSpPr><p:nvPr><p:ph type="%s"/></p:nvPr></p:nvSpPr><p:txBody>'
                    '<a:p><a:r><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>' % (kind, title))
        body = "".join('<a:p><a:r><a:t>%s</a:t></a:r></a:p>' % b for b in bullets)
        sp_body = '<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody>%s</p:txBody></p:sp>' % body
        return '<p:sld xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree>%s%s</p:spTree></p:cSld></p:sld>' % (P, A, sp_title, sp_body)

    notes = ('<p:notes xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree><p:sp><p:txBody>'
             '<a:p><a:r><a:t>say this slowly</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>' % (P, A))
    return _zip({
        "ppt/presentation.xml": pres,
        "ppt/_rels/presentation.xml.rels": rels,
        "ppt/slides/slide1.xml": slide("AI Supplement", ["why agents", "what changes"], "ctrTitle"),
        "ppt/slides/slide2.xml": slide("Second", ["one more"]),
        "ppt/notesSlides/notesSlide1.xml": notes,
    })


def xlsx_bytes():
    wb = ('<workbook xmlns="%s" xmlns:r="%s"><sheets><sheet name="Budget" sheetId="1" r:id="rId1"/></sheets></workbook>' % (S, R))
    rels = '<Relationships xmlns="%s"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>' % REL
    shared = '<sst xmlns="%s"><si><t>Item</t></si><si><t>Cost</t></si><si><t>Deck</t></si></sst>' % S
    sheet = ('<worksheet xmlns="%s"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>12.5</v></c></row>'
             '<row r="3"><c r="A3" t="inlineStr"><is><t>inline</t></is></c><c r="B3" t="b"><v>1</v></c></row>'
             '</sheetData></worksheet>' % S)
    return _zip({"xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rels,
                 "xl/sharedStrings.xml": shared, "xl/worksheets/sheet1.xml": sheet})


class OfficePreviewTest(unittest.TestCase):
    def test_word_paragraphs_headings_lists_tables_escaped(self):
        html = op.render_preview(docx_bytes(), "Lecture 1.docx", "/dl")
        self.assertIn("<h2>Lecture 1</h2>", html)          # Heading1 → h2 (h1 is the title)
        self.assertIn("<p>Hello world &amp; friends</p>", html)
        self.assertIn("<li>first point</li>", html)
        self.assertIn("<th>Term</th>", html)
        self.assertIn("&lt;script&gt;", html)               # cell text escaped, never active
        self.assertNotIn("<script>", html)
        self.assertIn('href="/dl"', html)
        self.assertIn("open in Word", html)

    def test_powerpoint_slides_in_presentation_order_with_notes(self):
        slides = op.pptx_slides(pptx_bytes())
        self.assertEqual([s["title"] for s in slides], ["AI Supplement", "Second"])
        self.assertEqual(slides[0]["body"], ["why agents", "what changes"])
        self.assertNotIn("2", slides[1]["body"])          # the slide-number placeholder is chrome

    def test_a_designed_slide_without_placeholders_still_finds_its_title(self):
        # John's real deck: slide 1 has no <p:ph> at all, only shapes named "Title 1" / "Content Placeholder".
        pres = ('<p:presentation xmlns:p="%s" xmlns:r="%s"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>' % (P, R))
        rels = '<Relationships xmlns="%s"><Relationship Id="rId1" Target="slides/slide1.xml"/></Relationships>' % REL
        sp = lambda name, text: ('<p:sp><p:nvSpPr><p:cNvPr id="1" name="%s"/><p:nvPr/></p:nvSpPr><p:txBody>'
                                 '<a:p><a:r><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>' % (name, text))
        slide = ('<p:sld xmlns:p="%s" xmlns:a="%s"><p:cSld><p:spTree>%s%s</p:spTree></p:cSld></p:sld>'
                 % (P, A, sp("Title 1", "Artificial Intelligence"), sp("Content Placeholder 13", "A very quick introduction")))
        data = _zip({"ppt/presentation.xml": pres, "ppt/_rels/presentation.xml.rels": rels, "ppt/slides/slide1.xml": slide})
        slides = op.pptx_slides(data)
        self.assertEqual(slides[0]["title"], "Artificial Intelligence")
        self.assertEqual(slides[0]["body"], ["A very quick introduction"])
        self.assertEqual(slides[0]["notes"], "")            # this fixture ships no notes part
        html = op.render_preview(pptx_bytes(), "Lecture 1 AI Supplement v2.pptx", "/dl")
        self.assertIn("Slide 1", html)
        self.assertIn("<h2>AI Supplement</h2>", html)
        self.assertIn("Notes: say this slowly", html)
        self.assertIn("open in PowerPoint", html)

    def test_excel_sheets_as_tables_values_only(self):
        sheets = op.xlsx_sheets(xlsx_bytes())
        self.assertEqual(sheets[0]["name"], "Budget")
        self.assertEqual(sheets[0]["rows"][0], ["Item", "Cost"])
        self.assertEqual(sheets[0]["rows"][1], ["Deck", "", "12.5"])   # gap column honored
        self.assertEqual(sheets[0]["rows"][2], ["inline", "TRUE"])
        html = op.render_preview(xlsx_bytes(), "b.xlsx", "/dl")
        self.assertIn("<h2>Budget</h2>", html)
        self.assertIn("<th>Item</th>", html)
        self.assertIn("open in Excel", html)

    def test_a_broken_file_yields_an_honest_page_not_a_traceback(self):
        html = op.render_preview(b"not a zip", "x.docx", "/dl")
        self.assertIn("Could not read this file as Word", html)
        self.assertIn('href="/dl"', html)


class DeliverableRouteTest(unittest.TestCase):
    def test_content_types_are_honest_and_office_downloads(self):
        self.assertEqual(sr.deliverable_content_type(".pdf"), ("application/pdf", "inline"))
        self.assertEqual(sr.deliverable_content_type(".PPTX")[1], "attachment")
        self.assertIn("presentationml", sr.deliverable_content_type(".pptx")[0])
        self.assertIn("wordprocessingml", sr.deliverable_content_type(".docx")[0])
        self.assertIn("spreadsheetml", sr.deliverable_content_type(".xlsx")[0])
        self.assertEqual(sr.deliverable_content_type(".svg"), ("text/plain; charset=utf-8", "inline"))  # inert
        self.assertEqual(sr.deliverable_content_type(".bin"), ("application/octet-stream", "attachment"))

    def test_route_serves_preview_download_and_inline(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="anchor-deliv-"))
        (d / "deck.pptx").write_bytes(pptx_bytes())
        (d / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        # the cockpit's default for Office: the preview page
        obj, code = sr.handle_get(str(d), "deliverable-file", {"path": "deck.pptx", "view": "1", "pid": "p", "dir": ""})
        self.assertEqual(code, 200)
        self.assertIn("__html__", obj)
        self.assertIn("AI Supplement", obj["__html__"])
        self.assertIn("download=1", obj["__html__"])
        # the download link: attachment under the real content type
        obj, code = sr.handle_get(str(d), "deliverable-file", {"path": "deck.pptx", "download": "1"})
        self.assertEqual(code, 200)
        self.assertEqual(obj["__disposition__"], "attachment")
        self.assertIn("presentationml", obj["__ctype__"])
        # a PDF stays inline for the browser's own viewer
        obj, code = sr.handle_get(str(d), "deliverable-file", {"path": "paper.pdf"})
        self.assertEqual((obj["__ctype__"], obj["__disposition__"]), ("application/pdf", "inline"))
        # containment still holds
        obj, code = sr.handle_get(str(d), "deliverable-file", {"path": "../deck.pptx"})
        self.assertEqual(code, 404)

    def test_a_register_row_without_backticks_still_opens(self):
        # The Fractal Orthogonal Basis register (written by a steward session) lists
        # "report/DRAFT-v1.md" with no backticks; the cockpit showed path=null.
        import tempfile
        from steward_cockpit import steward_campaign as sc
        d = Path(tempfile.mkdtemp(prefix="anchor-reg-"))
        (d / "report").mkdir()
        (d / "report" / "DRAFT-v1.md").write_text("# draft\n", encoding="utf-8")
        (d / "DELIVERABLES.md").write_text(
            "# Deliverables\n\n| What | Where | Date | Step |\n|------|-------|------|------|\n"
            "| Draft v1 of the research report | report/DRAFT-v1.md | 2026-09-04 | formalize |\n"
            "| Something outside | ../elsewhere.md | 2026-09-04 | x |\n"
            "| Prose only | see the email thread | 2026-09-04 | x |\n", encoding="utf-8")
        items = sc.read_deliverables(str(d))["items"]
        self.assertEqual(items[0]["path"], "report/DRAFT-v1.md")
        self.assertTrue(items[0]["openable"])
        self.assertFalse(items[1]["openable"])            # containment still holds
        self.assertFalse(items[2]["openable"])            # prose is not a path

    def test_the_steward_reader_typesets_math_with_the_vendored_katex(self):
        page = (REPO / "steward_cockpit" / "static" / "report.html").read_text(encoding="utf-8")
        self.assertIn('href="/vendor/katex/katex.min.css"', page)
        self.assertIn('src="/vendor/katex/auto-render.min.js"', page)
        self.assertIn("typesetMath(body);", page)
        self.assertIn("ignoredTags", page)                 # code blocks stay code
        for asset in ("katex.min.css", "katex.min.js", "auto-render.min.js"):
            self.assertTrue((REPO / "vendor" / "katex" / asset).is_file(), asset)

    def test_cockpit_opens_office_in_the_preview_and_the_sender_honors_disposition(self):
        js = (REPO / "steward_cockpit" / "static" / "cockpit.html").read_text(encoding="utf-8")
        self.assertIn("const isOffice = /\\.(docx|pptx|xlsx)$/i.test(it.path);", js)
        self.assertIn('(isOffice ? "&view=1" : "")', js)
        gui = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        self.assertIn('"__html__" in obj', gui)
        self.assertIn("obj.get(\"__disposition__\") or \"inline\"", gui)
        manifest = (REPO / "dist_manifest.txt").read_text(encoding="utf-8")
        self.assertIn("\noffice_preview.py\n", manifest)


if __name__ == "__main__":
    unittest.main()

"""The tab icons, by his rule (John, 2026-10-01). 14:1x, his fourth ask: "where are my icons in Chrome tabs? I have asked
for this a number of times". 18:1x, the rule: "the cave of wonders and the campaign web pages should have the cave of
wonders icon in the tab; the rest of the other tabs should have the new anchor icon" and "the new anchor icon should be
used everywhere else where the old anchor icon was used".

What his tab strip showed when it was captured, not what the server sent: the anchor WAS on the two live Cave of Wonders
tabs, but his export scaled to 16 px is a dark stroke on black on a dark tab strip - it read as no icon; the Desk still
linked the lamp painting; the cockpit linked /anchor.ico with no version (Chrome keeps a tab icon it has seen for a
week); the status pages and previews open from disk carried no icon at all.

Here: the two pages wear the steward's High Seat picture, drawn to read at tab size; one rule at the one door every other
page leaves by (``with_tab_icon`` in ``_send_html``) puts the anchor's tab drawing (anchor-tab.*, his pick B) on it; the
old anchor files are his new anchor."""
import io
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import desk_page as dpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_active_set_w1_2026_09_29 as w1  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402
import test_desk_page_2026_09_26 as desk  # noqa: E402
import test_high_seat_page_2026_09_26 as base  # noqa: E402
from test_tab_icons_2026_09_30 import anchor_set  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(HERE, "vendor", "brand")
COCKPIT = open(os.path.join(HERE, "steward_cockpit", "static", "cockpit.html"), encoding="utf-8").read()


def _bytes(*parts):
    with open(os.path.join(HERE, *parts), "rb") as f:
        return f.read()


def test_the_tab_drawing_is_installed_and_reads_at_tab_size():
    """His pick (B: the painting on a verdigris tile). The measure his export failed: at 16 px on a dark tab strip the
    icon must be a bright shape. The .ico holds the three sizes its link declares."""
    PIL = pytest.importorskip("PIL.Image")
    assert hsp.anchor_tab_stem() == "anchor-tab"
    for n in (16, 32, 48):
        im = PIL.open(os.path.join(BRAND, "anchor-tab-%d.png" % n)).convert("RGBA")
        assert im.size == (n, n)
        px = [p for p in im.getdata() if p[3] > 0]
        lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _a in px) / len(px)
        assert lum >= 90, "the %d px drawing reads dark: %d" % (n, lum)
    his = PIL.open(os.path.join(BRAND, "anchor-icon-16.png")).convert("RGBA")
    dark = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _a in his.getdata()) / (16 * 16)
    assert dark < 60, "his export at 16 px is the dark one the drawing stands in for (%d)" % dark
    ico = PIL.open(os.path.join(BRAND, "anchor-tab.ico"))
    assert sorted(ico.info["sizes"]) == [(16, 16), (32, 32), (48, 48)] and hsp.ANCHOR_TAB_SIZES == "16x16 32x32 48x48"


def test_the_tab_drawing_sits_on_the_cave_s_tones_not_on_green():
    """His word on his pick (18:5x): "why is the background for the new anchor green. I would prefer something more
    consistent with the background of the cave of wonders." The tile is umber rising to the amber of the cave's glow."""
    PIL = pytest.importorskip("PIL.Image")
    for n in (16, 32, 48):
        im = PIL.open(os.path.join(BRAND, "anchor-tab-%d.png" % n)).convert("RGBA")
        px = [p for p in im.getdata() if p[3] > 0]
        r, g, b = (sum(p[i] for p in px) / len(px) for i in range(3))
        assert r > g > b and r - b >= 30, "the %d px tile is not warm: %d %d %d" % (n, r, g, b)


def test_the_pages_draw_his_anchor_where_the_old_glyph_stood():
    """18:5x: "there are some anchor icons embedded in the cave of wonder page upper left hand side that need to be
    updated. Same with the Campaign page." The glyph beside the word Anchor is his anchor now, on every masthead."""
    mark = hsp.anchor_mark("test")
    assert 'src="/vendor/brand/anchor-tab-48.png?v=test"' in mark and 'width="26"' in mark and "onerror" not in mark, "a missing mark shows as missing"
    ctx = w2._ctx(w1._steps())
    for html in (hsp.render_high_seat_html(base._ctx()), cpg.render_campaign_html(ctx), dpg.render_desk_html(desk._ctx())):
        assert '<div class="mh-title">' + mark + 'Anchor</div>' in html and "&#9875;" not in html and "⚓" not in html
    assert hsp.anchor_mark("test", 18) not in hsp.render_high_seat_html(base._ctx()), "his word 2026-10-02: the rail's seat line wears the Cave's picture alone"
    gui = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    assert "&#9875;" not in gui and "anchor-tab-48.png" not in gui, "no page pastes its own mark"
    assert gui.count("{_anchor_mark(") == 2 and '("__ANCHOR_MARK__", _anchor_mark(26)),' in gui and "__ANCHOR_MARK__ Anchor" in gui, "the old dashboard's two and the Doctor's, through the one helper (Grok W5)"
    import anchor_gui as ag
    assert ag._anchor_mark(28) == hsp.anchor_mark(ag.BUILD_ID, 28)
    doctor = ag.render_doctor_page_html()
    assert hsp.anchor_mark(ag.BUILD_ID, 26) + " Anchor" in doctor and "__ANCHOR_MARK__" not in doctor, "the Doctor's mark carries the build"


def test_the_tab_drawing_is_worn_only_when_whole_and_his_export_otherwise(tmp_path):
    for f in ("anchor-icon.ico", "anchor-icon-32.png"):
        (tmp_path / f).write_bytes(b"x")
    assert hsp.anchor_tab_stem(tmp_path) == "anchor-icon"
    for f in ("anchor-tab.ico", "anchor-tab-32.png"):
        (tmp_path / f).write_bytes(b"x")
    assert hsp.anchor_tab_stem(tmp_path) == "anchor-icon", "a half-made tab set is not worn"
    (tmp_path / "anchor-tab-16.png").write_bytes(b"x")
    assert hsp.anchor_tab_stem(tmp_path) == "anchor-tab"
    assert hsp.anchor_tab_stem(tmp_path / "nowhere") is None


def test_the_cave_of_wonders_and_the_campaign_wear_the_high_seat_picture_not_the_anchor():
    hs_ctx = base._ctx()
    html = hsp.render_high_seat_html(hs_ctx)
    head = html[:html.index("<body")]
    assert hsp.tab_icon_link(hs_ctx["steward"]["high_seat"], "test", anchor=False) in head and "anchor-" not in head
    ctx = w2._ctx(w1._steps()); ctx["steward"] = dict(ctx["steward"], high_seat="aladdin-high-seat-cave.jpg", seal="aladdin-seal-lamp.jpg")
    html = cpg.render_campaign_html(ctx)
    head = html[:html.index("<body")]
    assert '<link rel="icon" href="/vendor/brand/aladdin-high-seat-cave.png?v=test" type="image/png" sizes="64x64">' in head, "the Campaign wears the cave, not its seal"
    assert "anchor-" not in head and "seal-lamp" not in head and ".jpg?v=" not in head
    assert hsp.with_tab_icon(html, "test") == html, "the door leaves a page with a picture of its own"


def test_the_cave_at_tab_size_is_the_painting_and_reads():
    PIL = pytest.importorskip("PIL.Image")
    im = PIL.open(os.path.join(BRAND, "aladdin-high-seat-cave.png")).convert("RGBA")
    assert im.size == (64, 64) and im.getpixel((0, 0))[3] == 255
    assert len(set(im.getdata())) > 800, "the cave painting, not the letter tile that stood in for it"
    small = im.resize((16, 16))
    lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _a in small.getdata()) / 256
    assert lum >= 100, "the cave reads dark at tab size: %d" % lum


def test_a_page_with_no_icon_gets_the_anchor_set_right_after_its_head_opens():
    page = '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>A report</title></head><body>x</body></html>'
    out = hsp.with_tab_icon(page, "b7")
    assert out == page.replace('<head>', '<head>' + anchor_set("anchor-tab", "b7")), out[:400]
    assert hsp.with_tab_icon(out, "b7") == out, "said once: a page that wears the set is left"


def test_the_old_anchor_links_become_the_set_with_the_build_in_the_address():
    assert '<link rel="icon" href="/anchor.ico" type="image/x-icon">' in COCKPIT, "the cockpit's own link, with no version"
    out = hsp.with_tab_icon(COCKPIT, "b7")
    head = out[:out.index("</head")]
    assert anchor_set("anchor-tab", "b7") in head and "/anchor.ico" not in head
    assert out[out.index("</head"):] == COCKPIT[COCKPIT.index("</head"):], "nothing after the head is touched"
    dash = ('<html><head>\n<title>Anchor</title>\n<link rel="icon" href="/anchor.ico?v=b6" type="image/x-icon">\n'
            '<link rel="icon" href="/anchor.png?v=b6" type="image/png" sizes="256x256">\n<link rel="apple-touch-icon" href="/anchor-touch.png?v=2026-05-11">\n</head><body></body></html>')
    out = hsp.with_tab_icon(dash, "b7")
    assert out.count('rel="icon"') == 3 and out.count("apple-touch-icon") == 1 and "/anchor.ico" not in out and "/anchor.png" not in out and "anchor-touch" not in out
    dark = "<html><head><title>t</title>" + anchor_set("anchor-icon", "b6") + "</head><body></body></html>"
    out = hsp.with_tab_icon(dark, "b7")
    assert anchor_set("anchor-tab", "b7") in out and "anchor-icon.ico" not in out and out.count("apple-touch-icon") == 1, "a page that carries the dark export's set is brought to the drawing (Grok W3d)"


def test_only_a_real_head_is_touched_and_a_mark_of_its_own_is_kept():
    tool = '<!doctype html><html><head><title>Tidy</title><link rel="icon" href="/vendor/brand/tidy-idy-icon.jpg" type="image/jpeg"/></head><body></body></html>'
    assert hsp.with_tab_icon(tool, "b7") == tool
    for page in ("<div>a part of a page</div>",
                 '<html><script>var s = "<head></head>";</script><body></body></html>',                 # a head inside a script string
                 "<html><head><title>never closed</title><body>x</body></html>",                         # no </head>
                 "<html><head><title>t</title><header>x</header><body></body></html>"):                 # </header> is not </head>
        assert hsp.with_tab_icon(page, "b7") == page, page
    late = "<html><head><title>t</title></head><body>" + ("x" * 9000) + '<link rel="icon" href="/x.png"></body></html>'
    assert anchor_set("anchor-tab", "b7") in hsp.with_tab_icon(late, "b7"), "an icon link in the body is not the page's"


def test_without_the_tab_drawing_the_door_writes_nothing(monkeypatch):
    """Grok W3d: his dark export is never written onto a tab that has something else."""
    monkeypatch.setattr(hsp, "anchor_tab_stem", lambda brand=None: "anchor-icon")
    monkeypatch.setattr(dpg, "anchor_tab_stem", lambda brand=None: "anchor-icon")
    assert hsp.with_tab_icon(COCKPIT, "b7") == COCKPIT
    html = dpg.render_desk_html(desk._ctx())
    assert "anchor-" not in html[:html.index("<body")], "the Desk keeps the steward's picture until the drawing is there"


def test_the_desk_wears_the_anchor():
    html = dpg.render_desk_html(desk._ctx())
    head = html[:html.index("<body")]
    assert "<title>The Desk</title>" + anchor_set("anchor-tab", "test") in head and ".jpg?v=" not in head


def test_what_actually_leaves_by_the_door():
    """Grok W3d: a pin on the bytes ``_send_html`` writes, not on its source."""
    import anchor_gui as ag

    def sent(html):
        fake = types.SimpleNamespace(send_response=lambda c: None, send_header=lambda k, v: None, end_headers=lambda: None, wfile=io.BytesIO())
        ag.AnchorHandler._send_html(fake, html)
        return fake.wfile.getvalue().decode("utf-8")

    out = sent(COCKPIT)
    assert anchor_set("anchor-tab", ag.BUILD_ID) in out and 'href="/anchor.ico"' not in out
    assert out[out.index("</head"):] == COCKPIT[COCKPIT.index("</head"):]
    desk_html = dpg.render_desk_html(desk._ctx())
    assert sent(desk_html) == desk_html, "the Desk already wears the set"
    part = "<div>a headless part</div>"
    assert sent(part) == part


def test_the_old_anchor_files_are_his_new_anchor_and_the_default_favicon_is_the_tab_drawing():
    """18:1x: "the new anchor icon should be used everywhere else where the old anchor icon was used" - the three root
    files every old user reads (the routes' fallbacks, the desktop shortcut, the share package) are his export."""
    assert _bytes("anchor.ico") == _bytes("vendor", "brand", "anchor-icon.ico")
    assert _bytes("anchor.png") == _bytes("vendor", "brand", "anchor-icon-256.png")
    assert _bytes("anchor-touch.png") == _bytes("vendor", "brand", "anchor-icon-180.png")
    gui = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    assert '_tab_ico = ANCHOR_DIR / "vendor" / "brand" / "anchor-tab.ico"' in gui, "/favicon.ico serves the tab drawing when it is there"
    maker = open(os.path.join(HERE, "create_shortcut.py"), encoding="utf-8").read()
    assert 'his = ANCHOR_DIR / "vendor" / "brand" / "anchor-icon.ico"' in maker and maker.index("shutil.copyfile(str(his), str(ICON_PATH))") < maker.index("from PIL import Image, ImageDraw"), "the shortcut maker no longer draws the old blue anchor over it"

"""The tab icons (John, 2026-09-30, twice: "where did the icons go for the web page tabs?" / "The icons in the web page tabs
are missing, can you please put those back?"): the High Seat and the Campaign page linked the stewards' 1024-px JPEGs
(0.7-0.9 MB) as the tab icon, which a browser tab does not take. A small PNG made from each steward's two images stands
as the tab icon; the pages link it with its type and size; an SVG is linked as it is."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_active_set_w1_2026_09_29 as w1  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402
import test_high_seat_page_2026_09_26 as base  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(HERE, "vendor", "brand")


def test_every_steward_s_two_images_have_a_small_png_beside_them():
    for stem in ("aladdin-high-seat-cave", "aladdin-seal-lamp", "jarvis-high-seat-hat", "jarvis-seal-salver", "ecgberht-portfolio-high-seat", "ecgberht-project-seal"):
        png = os.path.join(BRAND, stem + ".png")
        assert os.path.isfile(png) and 200 < os.path.getsize(png) < 60000, stem
        with open(png, "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n", stem


def anchor_set(stem, build="test"):
    # the links a tab wears: the small sizes from ``stem`` (his export, or its tab drawing), the touch icon always his
    sizes = "16x16 32x32 48x48" if stem == "anchor-tab" else "16x16 32x32 48x48 64x64 128x128 256x256"
    return ('<link rel="icon" href="/vendor/brand/%s.ico?v=%s" sizes="%s">'
            '<link rel="icon" type="image/png" sizes="32x32" href="/vendor/brand/%s-32.png?v=%s">'
            '<link rel="icon" type="image/png" sizes="16x16" href="/vendor/brand/%s-16.png?v=%s">'
            '<link rel="apple-touch-icon" sizes="180x180" href="/vendor/brand/anchor-icon-180.png?v=%s">' % (stem, build, sizes, stem, build, stem, build, build))


ANCHOR_SET = anchor_set(hsp.anchor_tab_stem() or "anchor-icon")


def test_his_anchor_icon_is_the_tab_icon_of_every_page_but_the_two_and_the_default_favicon():
    """2026-10-01 13:3x, his word: "there is a new anchor icon that I want you to find and use" - the set he dropped into
    vendor/brand at 13:12 (anchor-icon.ico with six sizes; 16-1024 px PNGs). 18:1x, his rule: the Cave of Wonders and
    the Campaign pages wear the cave; the rest of the tabs the anchor."""
    for stem in ("anchor-icon.ico", "anchor-icon-16.png", "anchor-icon-32.png", "anchor-icon-180.png", "anchor-icon-256.png"):
        assert os.path.isfile(os.path.join(BRAND, stem)), stem
    with open(os.path.join(BRAND, "anchor-icon.ico"), "rb") as f:
        assert f.read(4) == b"\x00\x00\x01\x00", "an ICO"
    assert hsp.tab_icon_link("aladdin-high-seat-cave.jpg", "test") == ANCHOR_SET and hsp.tab_icon_link("jarvis-seal-salver.jpg", "test") == ANCHOR_SET, "the anchor on every page, whoever the steward"
    cave = '<link rel="icon" href="/vendor/brand/aladdin-high-seat-cave.png?v=test" type="image/png" sizes="64x64">'
    hs = base._ctx(); hs["steward"] = dict(hs["steward"], high_seat="aladdin-high-seat-cave.jpg")
    assert cave in hsp.render_high_seat_html(hs) and ANCHOR_SET not in hsp.render_high_seat_html(hs)
    ctx = w2._ctx(w1._steps()); ctx["steward"] = dict(ctx["steward"], high_seat="aladdin-high-seat-cave.jpg", seal="aladdin-seal-lamp.jpg")
    html = cpg.render_campaign_html(ctx)
    assert cave in html and ANCHOR_SET not in html and ".jpg?v=" not in html[:html.index("<body")]
    gui = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    assert 'ico_path = ANCHOR_DIR / "vendor" / "brand" / "anchor-icon.ico"' in gui and 'png_path = ANCHOR_DIR / "vendor" / "brand" / "anchor-icon-256.png"' in gui, "the default favicon and the old dashboard's icon are the anchor too"
    assert 'self.send_header("Cache-Control", "no-cache")   # a new icon reaches the tab on the next load, not in a day' in gui


def test_without_the_anchor_set_the_steward_s_small_png_stands_in():
    assert hsp.tab_icon_link("aladdin-high-seat-cave.jpg", "b1", anchor=False) == '<link rel="icon" href="/vendor/brand/aladdin-high-seat-cave.png?v=b1" type="image/png" sizes="64x64">'
    assert hsp.tab_icon_link("gwl-m-icon.svg", "b1", anchor=False) == '<link rel="icon" href="/vendor/brand/gwl-m-icon.svg?v=b1" type="image/svg+xml">'
    assert hsp.tab_icon_link("no-such-image.jpg", "b1", anchor=False) == '<link rel="icon" href="/vendor/brand/no-such-image.jpg?v=b1" type="image/jpeg">', "no PNG: the image as it is"
    assert hsp.tab_icon_link(None, "b1", anchor=False).startswith('<link rel="icon" href="/vendor/brand/gwl-m-icon.svg')


def test_the_two_page_icons_are_legible_at_tab_size():
    """John, 2026-10-01: "put the icons back up in the tabs of the web pages" - the pages linked the PNGs all along and
    the browsers fetched them, but the shrunken paintings read as dark squares on a dark tab bar. The small PNGs are
    bright at 16 px and 64 px (the size the link declares): the Cave of Wonders is the cave painting itself, cropped and
    lifted (his rule of 18:1x - the two pages wear the cave); the seal an amber tile with the steward's initial. A mark
    that survives tab size tells them apart (Grok W3): the High Seat's is SQUARE (the hall), a project's seal is ROUND -
    at 16 px the seal's corners are transparent and the picture's are not."""
    import pytest
    PIL = pytest.importorskip("PIL.Image")
    corners = {}
    for stem in ("aladdin-high-seat-cave", "aladdin-seal-lamp"):
        im = PIL.open(os.path.join(BRAND, stem + ".png")).convert("RGBA")
        assert im.size == (64, 64), stem
        small = im.resize((16, 16))
        px = [p for p in small.getdata() if p[3] > 0]
        lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _a in px) / len(px)
        assert lum >= 100, "%s reads dark at tab size: %d" % (stem, lum)
        corners[stem] = small.getpixel((0, 0))[3]
    assert corners["aladdin-high-seat-cave"] > 128 and corners["aladdin-seal-lamp"] == 0, "the square tile and the round seal must read apart at 16 px: %r" % corners
    assert 'sizes="64x64"' in hsp.tab_icon_link("aladdin-high-seat-cave.jpg", "b1", anchor=False)

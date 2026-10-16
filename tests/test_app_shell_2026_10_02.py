"""The Anchor app (static/app.html + app.js + app-frame.js), PLAN v2.2 S1/S2 of the app-shell cycle
(Skill Foundry/planning/anchor-app-shell-2026-09-29).

A throwaway stdlib server on a spare port (never :8777) serves the real app files and stand-in pages that carry
each pattern the adversarial review found in Anchor's code: target=_blank links on the Cave, a pre-opened
about:blank whose .location is set later, a cockpit whose own shim saves window.open early and rewrites /report,
nested frames, a named target, a New-project popup that answers through window.opener, downloads, and an app link.
Every assertion is on what is PAINTED (computed display / visibility), checked after the page settles.
"""
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
BRAND = ROOT / "vendor" / "brand"

SHIM = ('<script src="/static/app-frame.js"></script><script>var _op=window.open;window.open=function(u,t){'
        'if(typeof u==="string"&&u.indexOf("/report")===0){u="/steward"+u;}return _op(u,t);};</script>')

PAGES = {
    "/": """<!doctype html><html><head><title>Cave of Wonders</title></head><body>
<a id="ck1" href="/project/p1" target="_blank">cockpit</a>
<button id="pre" onclick="var w=window.open('about:blank','_blank');w.opener=null;w.location.replace('/project/p2');">resume</button>
<button id="np" onclick="window.open('/dashboard?new=1&only=1','anchor-new-project','width=640,height=800')">new project</button>
<div id="got"></div>
<script>window.ANCHOR_BOOT={campaign_pid:"camp"};window.ANCHOR_TILES={seat_name:"Cave of Wonders",seat_icon:"/vendor/brand/aladdin-high-seat-cave.png",mode_name:"Star Chart",mode_icon:"/vendor/brand/campaign-aladdin-star-chart.jpg"};</script>
<a id="star" href="/project/camp" target="_blank">Open the Star Chart</a>
<a id="cavecp" href="/steward/v1?pid=camp&amp;dir=Cave%20of%20Wonders" target="_blank">open in the cockpit</a>
<script>window.addEventListener('message',function(e){document.getElementById('got').textContent=e.data;});</script>
</body></html>""",
    "/project/p1": """<!doctype html><html><head><title>MBA Teaching AI</title></head><body>""" + SHIM + """
<textarea id="say"></textarea>
<a id="deliv" href="/api/steward/deliverable-file?pid=p1&path=Deck.pptx&view=1" target="_blank">deck</a>
<button id="rep" onclick="window.open('/report?dir=&path=notes.md')">notes</button>
<a id="dl" href="/api/steward/deliverable-file?pid=p1&path=Deck.pptx&download=1" target="_blank">download</a>
<a id="named" href="/report/x" target="anchor_report_window">named</a>
<a id="p3" href="/project/p3" target="_blank">other cockpit</a>
<button id="tidy" onclick="var w=window.open('','tidy_status');w.document.open();w.document.write('<title>Tidy run</title><p id=n>0</p>');w.document.close();window.__tick=setInterval(function(){var n=w.document.getElementById('n');n.textContent=+n.textContent+1;},100);">tidy</button>
<iframe id="v1" src="/steward/v1?pid=p1" style="width:300px;height:80px"></iframe>
</body></html>""",
    "/project/camp": "<!doctype html><html><head><title>Star Chart</title></head><body>" + SHIM
                     + '<a id="starcp" href="/steward/v1?pid=camp&amp;dir=" target="_blank">open in the cockpit</a>'
                     + '<a id="place" href="/project/camp?open=trusts" target="_blank">its place</a></body></html>',
    "/project/p2": "<!doctype html><html><head><title>Artificial Magi</title></head><body>" + SHIM + "<p>magi</p></body></html>",
    "/project/p3": "<!doctype html><html><head><title>DARPA proposal</title></head><body>" + SHIM + "<p>darpa</p></body></html>",
    "/steward/v1": "<!doctype html><html><head><title>v1</title></head><body>" + SHIM
                   + '<a id="nested" href="/artifact/p1?path=fig.html" target="_blank">figure</a></body></html>',
    "/dashboard": """<!doctype html><html><head><title>New project</title></head><body>
<button id="make" onclick="window.opener.postMessage('created','*');window.close();">create</button></body></html>""",
}
DOCS = ("/api/steward/deliverable-file", "/steward/report", "/report", "/artifact")


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path.startswith("/static/"):
            f = STATIC / path[len("/static/"):]
            ctype = {"js": "text/javascript", "css": "text/css", "html": "text/html"}.get(f.suffix[1:], "text/plain")
            return self._send(f.read_bytes(), ctype + "; charset=utf-8")
        if path.startswith("/vendor/brand/"):
            f = BRAND / path[len("/vendor/brand/"):]
            return self._send(f.read_bytes() if f.is_file() else b"", "image/png")
        if path in PAGES:
            return self._send(PAGES[path])
        if "download=1" in query:
            return self._send(b"PK", "application/octet-stream",
                              {"Content-Disposition": 'attachment; filename="Deck.pptx"'})
        if path.startswith(DOCS):
            return self._send("<!doctype html><title>doc %s</title><p>%s?%s</p>" % (path, path, query))
        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="module")
def base():
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % port
    srv.shutdown()


@pytest.fixture()
def page(base):
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True)
        pg = ctx.new_page()
        pages_opened = []
        ctx.on("page", lambda np: pages_opened.append(np))
        pg.goto(base + "/static/app.html")
        pg.wait_for_function("() => { const f = document.querySelector('#stage iframe');"
                             " return f && f.contentDocument && f.contentDocument.getElementById('ck1'); }")
        pg.pages_opened = pages_opened
        yield pg
        b.close()


def _tiles(pg):
    return pg.eval_on_selector_all("#strip .tile", "els => els.map(e => e.querySelector('.name').textContent)")


def _painted_frames(pg):
    """Paths of the pane frames actually painted (display not none, non-zero box), left to right, top to bottom."""
    return pg.evaluate("""() => [...document.querySelectorAll('#stage > iframe')].filter(f =>
        getComputedStyle(f).display !== 'none' && f.getBoundingClientRect().width > 0)
      .map(f => { const r = f.getBoundingClientRect(); let p = '?';
                  try { p = f.contentWindow.location.pathname; } catch (e) {}
                  return [r.y, r.x, p]; })
      .sort((a, b) => (a[0] - b[0]) || (a[1] - b[1])).map(a => a[2])""")


def _two(pg):
    return pg.evaluate("document.body.classList.contains('two')")


def _cave(pg):
    return pg.frame_locator("#stage iframe >> nth=0")


def _focus_frame(pg, path):
    for fr in pg.frames:
        if fr.url.split("?")[0].endswith(path):
            return fr
    raise AssertionError("no frame at %s; frames: %s" % (path, [f.url for f in pg.frames]))


def _settle(pg, ms=600):
    pg.wait_for_timeout(ms)


def test_the_cave_is_first_alone_and_cannot_be_closed(page):
    assert _tiles(page) == ["Cave of Wonders"]
    assert page.locator("#strip .tile.cave .x").count() == 0
    assert _painted_frames(page) == ["/"]


def test_a_target_blank_link_on_the_cave_opens_a_tile_in_focus_not_a_window(page):
    _cave(page).locator("#ck1").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]
    assert _painted_frames(page) == ["/project/p1"]
    assert page.locator("#strip .tile.focus .name").text_content() == "MBA Teaching AI"
    assert page.pages_opened == []                      # nothing escaped to a browser window


def test_a_preopened_blank_window_gets_its_page_through_location_replace(page):
    _cave(page).locator("#pre").click()
    page.wait_for_function("() => [...document.querySelectorAll('#strip .tile .name')].some(n => n.textContent === 'Artificial Magi')")
    _settle(page)
    assert _painted_frames(page) == ["/project/p2"]
    assert page.pages_opened == []


def test_new_project_popup_answers_its_opener_and_closes_its_tile(page):
    _cave(page).locator("#np").click()
    page.wait_for_function("() => [...document.querySelectorAll('#strip .tile .name')].some(n => n.textContent === 'New project')")
    _focus_frame(page, "/dashboard").locator("#make").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 1")
    _settle(page)
    assert _cave(page).locator("#got").text_content() == "created"
    assert _painted_frames(page) == ["/"]


def _open_p1(page):
    _cave(page).locator("#ck1").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    _focus_frame(page, "/project/p1").wait_for_selector("#say")
    return _focus_frame(page, "/project/p1")








def test_cockpit_to_cockpit_keeps_the_caller_alive_hidden_and_switching_back_shows_it_as_he_left_it(page):
    # his rule (2026-10-08): a tile once opened keeps its content - no reload when he switches back
    p1 = _open_p1(page)
    p1.evaluate("window.__alive = 'same page'; document.getElementById('say').focus()")
    p1.locator("#say").fill("half a sentence")
    p1.evaluate("window.scrollTo(0, 0)")
    p1.locator("#p3").click()
    page.wait_for_function("() => [...document.querySelectorAll('#strip .tile .name')].some(n => n.textContent === 'DARPA proposal')")
    _settle(page, 900)
    assert _painted_frames(page) == ["/project/p3"]
    # the MBA cockpit's frame is still there, hidden (not painted), with its page untouched
    assert page.evaluate("document.querySelectorAll('#stage > iframe').length") == 3     # the Cave + DARPA + MBA kept
    page.wait_for_timeout(16000)                                                         # past the old drop timer
    assert page.evaluate("document.querySelectorAll('#stage > iframe').length") == 3
    page.locator("#strip .tile", has_text="MBA Teaching AI").click()
    page.wait_for_function("() => [...document.querySelectorAll('#stage > iframe')].some(f => { try { return f.contentWindow.location.pathname === '/project/p1' && getComputedStyle(f).display !== 'none'; } catch (e) { return false; } })")
    back = _focus_frame(page, "/project/p1")
    assert back.evaluate("window.__alive") == "same page"                                # the same page, not a reload
    assert back.locator("#say").input_value() == "half a sentence"
    assert _painted_frames(page) == ["/project/p1"]
    assert page.locator("#strip .tile.focus .name").text_content() == "MBA Teaching AI"


def test_a_hidden_tile_and_the_frames_inside_it_are_told_so_and_told_again_when_shown(page):
    p1 = _open_p1(page)
    rec = "window.__vis=[];addEventListener('anchor-app-visibility',e=>__vis.push(e.detail.hidden))"
    p1.evaluate(rec)
    nested = _focus_frame(page, "/steward/v1")
    nested.evaluate(rec)
    p1.locator("#p3").click()
    page.wait_for_function("() => [...document.querySelectorAll('#strip .tile .name')].some(n => n.textContent === 'DARPA proposal')")
    _settle(page, 900)
    assert p1.evaluate("[window.__anchorHidden, window.__vis]") == [True, [True]]
    assert nested.evaluate("[window.__anchorHidden, window.__vis]") == [True, [True]]
    page.locator("#strip .tile", has_text="MBA Teaching AI").click()
    _settle(page)
    assert p1.evaluate("[window.__anchorHidden, window.__vis]") == [False, [True, False]]
    assert nested.evaluate("window.__vis") == [True, False]


def test_past_six_hidden_tiles_the_least_recently_shown_drops_and_comes_back_from_its_address(page):
    p1 = _open_p1(page)
    for i in range(9):                                         # nine documents opened one after another
        p1.evaluate("i => window.open('/artifact/p1?path=f' + i + '.html')", i)
        page.wait_for_function("n => document.querySelectorAll('#strip .tile').length === n", arg=3 + i)
    _settle(page, 900)
    live = page.evaluate("""() => [...document.querySelectorAll('#stage > iframe')].map(f => {
        try { return f.contentWindow.location.pathname + f.contentWindow.location.search; } catch (e) { return '?'; } })""")
    # the Cave + the two shown panes (the cockpit and f8) + six hidden kept; f0 and f1 (least recently shown) dropped
    assert len(live) == 1 + 2 + 6, live
    assert not any("f0.html" in u or "f1.html" in u for u in live), live
    assert all(any(("f%d.html" % i) in u for u in live) for i in range(2, 9)), live
    page.locator("#strip .tile", has_text="f0.html").click()                            # it comes back from its address
    page.wait_for_function("() => [...document.querySelectorAll('#stage > iframe')].some(f => { try { return f.contentWindow.location.search.indexOf('f0.html') >= 0 && getComputedStyle(f).display !== 'none'; } catch (e) { return false; } })")


def test_close_returns_focus_and_drag_reorders_but_never_past_the_cave(page):
    _cave(page).locator("#ck1").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    page.locator("#strip .tile.cave").click()
    _cave(page).locator("#pre").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 3")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI", "Artificial Magi"]
    magi = page.locator("#strip .tile", has_text="Artificial Magi").bounding_box()
    mba = page.locator("#strip .tile", has_text="MBA Teaching AI").bounding_box()
    cave = page.locator("#strip .tile.cave").bounding_box()
    page.mouse.move(magi["x"] + 20, magi["y"] + 10)
    page.mouse.down()
    page.mouse.move(mba["x"] + 10, mba["y"] + 10, steps=6)
    page.mouse.move(cave["x"] + 10, cave["y"] + 10, steps=6)                  # over the Cave: no move past it
    page.mouse.up()
    _settle(page, 200)
    assert _tiles(page) == ["Cave of Wonders", "Artificial Magi", "MBA Teaching AI"]
    page.locator("#strip .tile", has_text="Artificial Magi").locator(".x").click()
    _settle(page, 300)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]
    assert page.locator("#strip .tile.focus").count() == 1


# ---------- the phone: wrapped rows; swipe still navigates; x closes; the Cave never closes ----------
@pytest.fixture()
def phone(base):
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
        pg = ctx.new_page()
        pg.goto(base + "/static/app.html")
        pg.wait_for_function("() => { const f = document.querySelector('#stage iframe');"
                             " return f && f.contentDocument && f.contentDocument.getElementById('ck1'); }")
        yield pg
        b.close()


def _painted_tiles(pg):
    return pg.evaluate("""() => [...document.querySelectorAll('#strip .tile')]
        .filter(t => getComputedStyle(t).display !== 'none' && getComputedStyle(t).visibility !== 'hidden'
                  && t.getBoundingClientRect().width > 0)
        .map(t => t.querySelector('.name').textContent + ' | ' + t.querySelector('.pos').textContent.trim()
                  + ' | x=' + !!t.querySelector('.x'))""")


def _swipe(pg, dx):
    box = pg.locator("#strip").bounding_box()
    y = box["y"] + box["height"] / 2
    x = box["x"] + box["width"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x + dx, y, steps=8)
    pg.mouse.up()
    pg.wait_for_timeout(300)


def test_phone_title_bar_wraps_with_an_arrow_and_swipe_still_moves_along_the_tiles(phone):
    assert _painted_tiles(phone) == ["Cave of Wonders |  | x=false"]
    _cave(phone).locator("#ck1").click()
    phone.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    phone.locator("#strip .tile.cave").click()
    _cave(phone).locator("#pre").click()
    phone.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 3")
    _settle(phone)
    assert _painted_tiles(phone) == ["Cave of Wonders | ‹ 1 of 3 › | x=false"]
    assert phone.locator("#rows").is_visible()
    assert phone.locator("#strip .tile.focus .name").text_content() == "Artificial Magi"
    _swipe(phone, 160)                                                  # right: the previous one
    assert phone.locator("#strip .tile.focus .name").text_content() == "MBA Teaching AI"
    _swipe(phone, 160)
    assert phone.locator("#strip .tile.focus .name").text_content() == "Cave of Wonders"
    _swipe(phone, 160)                                                  # nothing before the Cave
    assert phone.locator("#strip .tile.focus .name").text_content() == "Cave of Wonders"
    _swipe(phone, -160)                                                 # left: the next one
    assert phone.locator("#strip .tile.focus .name").text_content() == "MBA Teaching AI"
    _settle(phone)
    assert _painted_frames(phone) == ["/project/p1"]
    phone.locator("#rows").click()
    assert len(_painted_tiles(phone)) == 3
    phone.locator("#strip .tile.focus .x").click()
    _settle(phone, 300)
    assert len(phone.evaluate("[...document.querySelectorAll('#strip .tile')].map(t => t.dataset.id)")) == 2






def test_ctrl_plus_minus_zero_and_ctrl_wheel_ask_the_host_to_zoom_from_the_strip_and_from_inside_a_frame(base):
    """The desktop program zooms the whole window (shell/anchor_shell.py ZoomApi); the pages only catch the keys -
    in the top page AND inside a framed page (keys never cross frames)."""
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        pg.add_init_script("if (window === window.top) { window.__zoom = [];"
                           " window.pywebview = { api: { zoom: function (s) { window.__zoom.push(s); } } }; }")
        pg.goto(base + "/static/app.html")
        pg.wait_for_function("() => { const f = document.querySelector('#stage iframe');"
                             " return f && f.contentWindow.__anchorFrame; }")
        pg.locator("#strip").click()
        for k in ("Control+Equal", "Control+Minus", "Control+0"):
            pg.keyboard.press(k)
        _cave(pg).locator("#ck1").focus()                          # focus inside the Cave frame
        pg.keyboard.press("Control+Equal")
        pg.mouse.move(600, 500)
        pg.keyboard.down("Control"); pg.mouse.wheel(0, -100); pg.keyboard.up("Control")
        pg.wait_for_timeout(200)
        assert pg.evaluate("window.__zoom") == [1, -1, 0, 1, 1]
        b.close()


def test_in_a_plain_browser_the_zoom_keys_are_left_to_the_browser(page):
    assert page.evaluate("window.ANCHOR_APP.zoom(1)") is False



# ---------- two panes (his layout, 2026-10-03) ----------
def test_a_deliverable_from_a_cockpit_opens_the_second_pane_on_the_right_and_the_cockpit_keeps_the_focus(page):
    p1 = _open_p1(page)
    assert not _two(page)
    p1.locator("#deliv").click()
    page.wait_for_function("() => document.body.classList.contains('two')")
    _settle(page)
    assert _painted_frames(page) == ["/project/p1", "/api/steward/deliverable-file"]
    assert page.locator("#head0").evaluate("e => e.classList.contains('active')")          # the cockpit's pane
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI", "Deck.pptx"]               # a tile like any other
    p1.locator("#rep").click()                          # the cockpit's own shim rewrites /report -> /steward/report
    page.wait_for_function("() => [...document.querySelectorAll('#stage > iframe')].some(f => { try {"
                           " return f.dataset.pane === '1' && f.contentWindow.location.pathname === '/steward/report'; }"
                           " catch (e) { return false; } })")
    assert _painted_frames(page) == ["/project/p1", "/steward/report"]


def test_a_deliverable_from_a_cockpit_on_the_right_goes_to_the_left(page):
    p1 = _open_p1(page)
    p1.locator("#deliv").click()                        # cockpit left, deck right
    page.wait_for_function("() => document.body.classList.contains('two')")
    _settle(page)
    page.locator("#head1").click()                      # make the right pane active, then show the cockpit there
    page.locator("#strip .tile", has_text="MBA Teaching AI").click()
    _settle(page)
    assert _painted_frames(page) == ["/api/steward/deliverable-file", "/project/p1"]        # the two swapped
    _focus_frame(page, "/project/p1").locator("#rep").click()
    page.wait_for_function("() => [...document.querySelectorAll('#stage > iframe')].some(f => { try {"
                           " return f.dataset.pane === '0' && f.contentWindow.location.pathname === '/steward/report'; }"
                           " catch (e) { return false; } })")
    _settle(page)
    assert _painted_frames(page) == ["/steward/report", "/project/p1"]
    assert page.locator("#head1").evaluate("e => e.classList.contains('active')")


def test_click_a_pane_then_a_tile_to_show_it_there_with_its_side_marked(page):
    p1 = _open_p1(page)
    p1.locator("#deliv").click()
    page.wait_for_function("() => document.body.classList.contains('two')")
    _settle(page)
    _focus_frame(page, "/api/steward/deliverable-file").locator("p").click()   # a click inside the right pane
    page.wait_for_function("() => document.getElementById('head1').classList.contains('active')")
    page.locator("#strip .tile.cave").click()
    _settle(page)
    assert _painted_frames(page) == ["/project/p1", "/"]
    sides = page.eval_on_selector_all("#strip .tile", "els => els.map(e => (e.querySelector('.side') || {}).textContent || '')")
    assert sides == ["R", "L", ""]


def test_a_panes_x_on_a_deliverable_removes_its_tile_from_the_top_row_and_the_toggle_keeps_tiles(page):
    p1 = _open_p1(page)
    p1.locator("#deliv").click()
    page.wait_for_function("() => document.body.classList.contains('two')")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI", "Deck.pptx"]
    page.locator("#head1 .x").click()
    _settle(page)
    assert not _two(page)
    assert _painted_frames(page) == ["/project/p1"]
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]          # deliverable removed from top row
    p1.locator("#deliv").click()
    page.wait_for_function("() => document.body.classList.contains('two')")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI", "Deck.pptx"]
    page.locator("#one").click()
    _settle(page)
    assert not _two(page) and _tiles(page) == ["Cave of Wonders", "MBA Teaching AI", "Deck.pptx"]
    page.locator("#two").click()
    _settle(page)
    assert _two(page) and _painted_frames(page) == ["/project/p1", "/api/steward/deliverable-file"]
    page.locator("#one").click()
    _settle(page)
    assert not _two(page) and len(_painted_frames(page)) == 1


def test_a_nested_frame_link_and_a_named_target_land_in_the_app(page):
    p1 = _open_p1(page)
    _focus_frame(page, "/steward/v1").locator("#nested").click()
    page.wait_for_function("() => document.body.classList.contains('two')")
    _settle(page)
    assert _painted_frames(page) == ["/project/p1", "/artifact/p1"]
    p1.locator("#named").click()
    page.wait_for_function("() => [...document.querySelectorAll('#stage > iframe')].some(f => { try {"
                           " return f.dataset.pane === '1' && f.contentWindow.location.pathname === '/report/x'; }"
                           " catch (e) { return false; } })")
    assert page.pages_opened == []


def test_a_download_is_not_a_tile(page):
    p1 = _open_p1(page)
    with page.expect_download() as dl:
        p1.locator("#dl").click()
    assert dl.value.suggested_filename == "Deck.pptx"
    _settle(page, 300)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]
    assert not _two(page)


def test_a_page_written_into_a_blank_window_stays_beside_its_caller_which_keeps_updating_it(page):
    """Tidy-Idy (tidy-idy-run.js): the cockpit writes its progress page into a blank window and polls it.
    document.open gives that page the caller's address - it must stay a deliverable beside the cockpit."""
    p1 = _open_p1(page)
    p1.locator("#tidy").click()
    page.wait_for_function("() => document.body.classList.contains('two')")
    page.wait_for_timeout(1200)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI", "Tidy run"]
    n = page.evaluate("+[...document.querySelectorAll('#stage > iframe')].find(f => f.dataset.pane === '1')"
                      ".contentDocument.getElementById('n').textContent")
    assert n >= 5                                       # the caller is alive and still writing into it


def test_phone_a_deliverable_stacks_under_the_dialogue(phone):
    _cave(phone).locator("#ck1").click()
    phone.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    _focus_frame(phone, "/project/p1").wait_for_selector("#deliv")
    _focus_frame(phone, "/project/p1").locator("#deliv").click()
    phone.wait_for_function("() => document.body.classList.contains('two')")
    _settle(phone)
    boxes = phone.evaluate("""() => [...document.querySelectorAll('#stage > iframe')]
        .filter(f => getComputedStyle(f).display !== 'none')
        .map(f => { const r = f.getBoundingClientRect(); return [r.x, r.y, r.width, r.height, f.dataset.pane]; })
        .sort((a, b) => a[1] - b[1])""")
    top, bottom = boxes
    assert top[4] == "0" and bottom[4] == "1"
    assert bottom[1] >= top[1] + top[3] - 1                     # below the dialogue, not beside it
    assert abs(bottom[2] - top[2]) < 2 and top[2] > 380         # both full width


# ---------- the second review (2026-10-03) ----------
def test_a_link_inside_a_deliverable_opens_in_that_pane_and_the_cockpit_stays(page):
    p1 = _open_p1(page)
    p1.locator("#deliv").click()
    page.wait_for_function("() => document.body.classList.contains('two')")
    _settle(page)
    page.evaluate("""() => { const f = [...document.querySelectorAll('#stage > iframe')].find(f => f.dataset.pane === '1');
        ANCHOR_APP.open('/artifact/p1?path=other.html', '_blank', f.contentWindow); }""")
    _settle(page)
    assert _painted_frames(page) == ["/project/p1", "/artifact/p1"]


def test_closing_the_shown_tile_goes_back_to_what_the_pane_showed_before(page):
    _open_p1(page)                                         # a cockpit opened earlier sits after the Cave in the strip
    page.locator("#strip .tile.cave").click()
    _settle(page)
    _cave(page).locator("#np").click()                     # the New-project popup replaces the Cave in the pane
    page.wait_for_function("() => [...document.querySelectorAll('#strip .tile .name')].some(n => n.textContent === 'New project')")
    _cave_tile = page.locator("#strip .tile.cave")
    page.locator("#strip .tile", has_text="New project").locator(".x").click()
    _settle(page)
    assert _painted_frames(page) == ["/"]
    assert _cave_tile.evaluate("e => e.classList.contains('focus')")


def test_an_open_of_the_cave_shows_the_one_cave_tile(page):
    p1 = _open_p1(page)
    page.evaluate("""() => { const f = [...document.querySelectorAll('#stage > iframe')].find(f => f.dataset.pane === '0');
        ANCHOR_APP.open('/', '_blank', f.contentWindow); }""")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]
    assert _painted_frames(page) == ["/"]


def test_the_desktop_program_snapped_narrow_keeps_its_desktop_bar(base):
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 640, "height": 800})
        pg.add_init_script("if (window === window.top) { window.pywebview = { api: { zoom: function () {},"
                           " window_control: function () {} } }; }")
        pg.goto(base + "/static/app.html")
        pg.wait_for_function("() => document.body.classList.contains('hosted')")
        assert pg.evaluate("getComputedStyle(document.getElementById('two')).display") != "none"
        assert pg.evaluate("getComputedStyle(document.querySelector('#bar .grab')).display") != "none"
        b.close()


# ---------- his naming and one-tile rules (2026-10-03) ----------
def test_the_star_chart_and_both_cockpits_are_named_for_what_they_show_and_open_once(page):
    _cave(page).locator("#star").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "Star Chart"]
    assert "campaign-aladdin-star-chart" in page.eval_on_selector_all("#strip .tile img", "els => els.map(e => e.src).join(' ')")
    _focus_frame(page, "/project/camp").locator("#starcp").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 3")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "Star Chart", "Star Chart — AI Cockpit"]
    page.locator("#strip .tile.cave").click(); _settle(page)
    assert _painted_frames(page) == ["/"], (_painted_frames(page), _tiles(page))
    _cave(page).locator("#cavecp").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 4")
    _settle(page)
    assert _tiles(page)[-1] == "Cave of Wonders — AI Cockpit"
    # selected again while open: the open tile is shown, never a second one
    page.locator("#strip .tile.cave").click(); _settle(page)
    _cave(page).locator("#star").click(); _settle(page)
    assert len(_tiles(page)) == 4 and _painted_frames(page) == ["/project/camp"]
    _focus_frame(page, "/project/camp").locator("#place").click(); _settle(page)
    assert len(_tiles(page)) == 4 and _painted_frames(page) == ["/project/camp"], "a goal's place is the same tile"
    page.locator("#strip .tile.cave").click(); _settle(page)
    _cave(page).locator("#cavecp").click(); _settle(page)
    assert len(_tiles(page)) == 4 and _painted_frames(page) == ["/steward/v1"]

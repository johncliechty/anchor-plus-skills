"""Painted header/Cave regressions with production assets and read-only transport.

Every browser request is fulfilled here; no shared service, events soft-wake,
producer or model is contacted. Timers for feedback polling are shortened, but
CSS animations use the real browser clock and screenshots retain animations.
"""
import io
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright

import high_seat_page


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://anchor-ui.test"
EFFORT = "A long initiative with an exact cockpit scope"


def cave_html():
    # Use the actual card renderer, compact/hover/inline handlers and stylesheet.
    cards = "".join(high_seat_page._card(
        {"id": "p", "name": "Owning project"},
        {"has_record": True, "effort": directory, "next": "Keep the original words"},
        "", goal={"name": "Original goal"},
        step={"id": sid, "kind": "effort", "name": name},
        light={"light": "gray" if sid == "one" else "orange"},
    ) for sid, directory, name in [("one", EFFORT, "Distinct initiative"),
                                 ("two", "Other effort", "Other initiative")])
    return """<!doctype html><html><head><title>Cave of Wonders</title>
<link rel="stylesheet" href="/static/high-seat-page.css">
<script>window.ANCHOR_BOOT={campaign_pid:'camp',steward:'Aladdin'};
window.ANCHOR_TILES={seat_name:'Cave of Wonders',mode_name:'Star Chart'};</script>
</head><body><div class="board" style="padding:16px"><section class="shelf">
<div class="grid">""" + cards + """</div></section></div>
<textarea id="say" aria-label="Cave draft"></textarea><button id="sendBtn">Send</button>
<script src="/static/cockpit-feedback.js"></script>
<script src="/static/high-seat-page.js"></script></body></html>"""


def cockpit_html(query):
    directory = query.get("dir", [""])[0]
    general = query.get("general", [""])[0] == "1"
    title = "Plain session" if general else (directory or "Star Chart") + " — AI Cockpit"
    key = "fixture-draft:" + query.get("pid", [""])[0] + ":" + directory
    return """<!doctype html><html><head><title>""" + title + """</title></head><body>
<p id="history">History of """ + (directory or "Star Chart") + """</p>
<textarea id="draft" aria-label="Cockpit draft"></textarea>
<script>const key=""" + json.dumps(key) + """;
const draft=document.getElementById('draft');draft.value=localStorage.getItem(key)||'';
draft.addEventListener('input',()=>localStorage.setItem(key,draft.value));
// An embedded conversation may subscribe; this is fixture SSE, never a soft-wake.
if(new URLSearchParams(location.search).get('view')==='tile'){
 const stream=new EventSource('/api/steward/events'+location.search);
 stream.addEventListener('message',()=>{});
 parent.postMessage({kind:'ready',inst:new URLSearchParams(location.search).get('inst')},location.origin);
}
</script></body></html>"""


class ReadOnlyUI:
    def __init__(self, context):
        self.context = context
        self.values = {}
        self.reads = []
        self.forbidden = []
        self.errors = []
        self.stamp = 0
        context.route("**/*", self.route)
        context.on("page", lambda page: page.on("pageerror", lambda error: self.errors.append(str(error))))

    def change(self, directory=EFFORT, *, light="quiet", question=False,
               review=False, pin=False, accepted=False, fail=None, general=False, term="",
               legacy=False, label="", owner_phase=None):
        self.stamp += 1
        self.values[("p", directory, general, term)] = dict(
            light=light, question=question, review=review, pin=pin,
            accepted=accepted, fail=fail, stamp=str(self.stamp),
            legacy=legacy, label=label, owner_phase=owner_phase)

    def route(self, route):
        request = route.request
        u = urlsplit(request.url)
        path, q = u.path, parse_qs(u.query, keep_blank_values=True)
        if u.netloc != "anchor-ui.test" or request.method != "GET":
            self.forbidden.append((request.method, request.url))
            return route.abort()
        if path.startswith(("/static/", "/vendor/brand/")):
            file = ROOT / path.lstrip("/")
            if file.is_file():
                mime = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
                        ".png": "image/png", ".jpg": "image/jpeg"}.get(file.suffix, "application/octet-stream")
                return route.fulfill(body=file.read_bytes(), content_type=mime)
        if path in ("/", "/high-seat"):
            return route.fulfill(body=cave_html(), content_type="text/html")
        if path == "/steward/v1":
            return route.fulfill(body=cockpit_html(q), content_type="text/html")
        if path == "/project/camp":
            return route.fulfill(body="<title>Star Chart</title><p>Separate board</p>", content_type="text/html")
        if path == "/api/steward/events":
            # Guard GET as explicitly as POST: this response cannot wake an effort.
            self.reads.append((path, q))
            return route.fulfill(body='data: {"fixture":true}\n\n', content_type="text/event-stream")
        if path == "/api/high-seat/card":
            self.reads.append((path, q))
            return route.fulfill(json={"html": "<p>Original scoped deliverables and brief</p>"})
        if path.startswith("/api/steward/"):
            self.reads.append((path, q))
            key = (q.get("pid", [""])[0], q.get("dir", [""])[0],
                   q.get("general", [""])[0] == "1", q.get("term", [""])[0])
            value = self.values.get(key, dict(light="quiet", question=False, review=False,
                                            pin=False, accepted=False, fail=None, stamp="0"))
            if value["fail"] == path.rsplit("/", 1)[-1]:
                return route.fulfill(status=503, json={"error": "fixture unavailable"})
            if path.endswith("/state"):
                data = {"light": value["light"], "busy": value["light"] == "green",
                        "open_question": value["question"], "stamp": value["stamp"]}
            elif path.endswith("/map"):
                data = {"stamp": value["stamp"], "steps": [{"id": "owner", "status": "active",
                        "navigation": {"current": True, "label": value.get("label", "")},
                        "refinement": {"phase": value.get("owner_phase")}}]}
            elif path.endswith("/deliverables"):
                data = {"items": [{"is_current": True, "managed": not value.get("legacy"), "owner_step_id": "owner",
                                   "phase": "awaiting_review" if value["review"] else "working",
                                   "accepted": value["accepted"], "what": "Original product"}]
                        if value["review"] or value["pin"] else []}
            elif path.endswith("/tile"):
                data = {"html": "<p>Original scoped deliverables and brief</p>"}
            else:
                self.forbidden.append((request.method, request.url))
                return route.abort()
            return route.fulfill(json=data)
        self.forbidden.append((request.method, request.url))
        route.abort()

    def open(self, page, directory, **extra):
        url = "/steward/v1?" + urlencode(dict(pid="p", dir=directory, **extra))
        page.evaluate("url => ANCHOR_APP.open(url,'_blank',window)", url)
        page.wait_for_function("url => [...document.querySelectorAll('#stage > iframe')].some(f => "
                               "f.src.endsWith(url) && f.contentDocument?.getElementById('draft'))", arg=url)
        return page.locator("#strip .tile").last

    def refresh(self, page):
        page.evaluate("() => {window.dispatchEvent(new Event('focus')); "
                      "document.querySelector('#stage iframe').contentWindow.dispatchEvent(new Event('focus'));}")


@pytest.fixture
def ui():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1500, "height": 900}, reduced_motion="no-preference")
        # these tests prove a page comes back right after the app drops its frame (past the keep-alive cap):
        # cap 0 makes every hidden tile drop, as all of them did before 2026-10-08
        context.add_init_script("if(window===window.top)window.ANCHOR_KEEP_LIVE=0;")
        context.add_init_script("""if(window===window.top){
window.hostActions=[];window.pywebview={api:{zoom(){},window_control(act){hostActions.push(act)}}};}
const originalInterval=window.setInterval;
window.setInterval=(fn,ms,...args)=>originalInterval(fn,ms===5000?200:ms,...args);
document.addEventListener('DOMContentLoaded',()=>{
 window.initialAttentionCards=[...document.querySelectorAll('.tile.ready')].map(e=>e.id);
},{once:true});""")
        fixture = ReadOnlyUI(context)
        page = context.new_page()
        page.goto(ORIGIN + "/static/app.html")
        page.wait_for_function("() => document.querySelector('#stage iframe')?.contentDocument?.querySelector('.tile[data-tile]')?._compact")
        yield fixture, page
        browser.close()
        assert not fixture.forbidden, fixture.forbidden
        assert not fixture.errors, fixture.errors


def assert_controls_fit(page):
    for selector in ("#one", "#two", "#winctl [data-act]", "#rows:not([hidden])"):
        for control in page.locator(selector).all():
            r = control.bounding_box()
            assert r and r["x"] >= 0 and r["y"] >= 0
            assert r["x"] + r["width"] <= page.viewport_size["width"]
            assert r["y"] + r["height"] <= page.viewport_size["height"]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("#strip").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.locator("#bar").evaluate("e => getComputedStyle(e).getPropertyValue('app-region')") == "drag"
    assert page.locator("#bar .grab").bounding_box()["width"] >= 24


def row_boxes(page):
    return page.locator("#strip .tile").evaluate_all("""els => els.map(e=>{
const r=e.getBoundingClientRect();return {y:r.y,right:r.right,bottom:r.bottom,
hidden:getComputedStyle(e).visibility==='hidden',inert:e.inert,tab:e.tabIndex};})""")


@pytest.mark.parametrize("width", [1500, 640, 420])
def test_wrapped_rows_controls_keyboard_expand_resize_close(ui, width):
    fixture, page = ui
    page.set_viewport_size({"width": width, "height": 900})
    expect(page.locator("#rows")).to_be_hidden()
    for i in range(13):
        fixture.open(page, f"Long distinct initiative number {i:02d} with its own conversation")
    expect(page.locator("#rows")).to_be_visible()
    boxes = row_boxes(page)
    assert len({b["y"] for b in boxes}) >= 3
    assert all(b["hidden"] == (b["y"] != boxes[0]["y"]) for b in boxes)
    assert all(b["inert"] and b["tab"] == -1 for b in boxes if b["hidden"])
    assert_controls_fit(page)
    page.locator("#rows").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#rows")).to_have_attribute("aria-expanded", "true")
    assert not any(b["hidden"] for b in row_boxes(page))
    assert_controls_fit(page)
    # Expanding and resizing must not rebuild the live composer or its saved words.
    current = next(f for f in page.frames if "number+12" in f.url)
    current.locator("#draft").fill("an unfinished dictated sentence")
    current.locator("#draft").evaluate("e => {window.keptComposer=e;window.navigationCount=1}")
    page.set_viewport_size({"width": 700 if width == 1500 else 1500, "height": 900})
    expect(current.locator("#draft")).to_be_focused()
    assert current.locator("#draft").evaluate("e => e===window.keptComposer")
    assert current.locator("#draft").input_value() == "an unfinished dictated sentence"
    assert_controls_fit(page)
    # A keyboard-selected tile retains focus during a render (including pane toggles).
    last = page.locator("#strip .tile").last
    last.focus()
    page.keyboard.press("Enter")
    expect(last).to_be_focused()
    last.locator(".x").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#strip .tile")).to_have_count(13)
    expect(page.locator("#strip .tile").last).to_be_focused()
    page.locator("#rows").click()
    expect(page.locator("#rows")).to_have_attribute("aria-expanded", "false")
    assert any(b["hidden"] for b in row_boxes(page))
    page.locator("#rows").click()
    page.locator("#strip .tile").last.focus()
    page.keyboard.press("Escape")
    expect(page.locator("#rows")).to_be_focused()
    expect(page.locator("#rows")).to_have_attribute("aria-expanded", "false")
    # Close while expanded down to one row; the overflow-only arrow disappears.
    page.locator("#rows").click()
    while page.locator("#strip .tile .x").count():
        page.locator("#strip .tile .x").last.click()
    expect(page.locator("#rows")).to_be_hidden()
    assert not any(b["hidden"] for b in row_boxes(page))
    assert_controls_fit(page)
    for act in ("minimize", "maximize", "close"):
        page.locator(f'#winctl [data-act="{act}"]').click()
    assert page.evaluate("hostActions") == ["minimize", "maximize", "close"]


def test_resize_alone_recomputes_overflow_and_all_rows_remain_reachable(ui):
    fixture, page = ui
    for i in range(3):
        fixture.open(page, f"A long initiative {i} with saved words and navigation")
    expect(page.locator("#rows")).to_be_hidden()
    page.set_viewport_size({"width": 640, "height": 600})
    expect(page.locator("#rows")).to_be_visible()
    assert any(b["hidden"] for b in row_boxes(page))
    page.locator("#rows").click()
    page.set_viewport_size({"width": 1500, "height": 900})
    expect(page.locator("#rows")).to_be_hidden()
    expect(page.locator("#strip .tile.focus")).to_be_focused()
    page.set_viewport_size({"width": 420, "height": 500})
    for i in range(18):
        fixture.open(page, f"Further long initiative {i} in a small desktop window")
    page.locator("#rows").click()
    expect(page.locator("#strip .tile")).to_have_count(22)
    assert not any(b["hidden"] for b in row_boxes(page))
    # A very tall strip scrolls within the header rather than hiding tiles below the window.
    last = page.locator("#strip .tile").last
    last.focus()
    r = last.bounding_box()
    viewport = page.locator("#strip").bounding_box()
    assert viewport["y"] <= r["y"] < r["y"] + r["height"] <= viewport["y"] + viewport["height"]
    assert_controls_fit(page)
    page.locator("#rows").click()
    expect(page.locator("#rows")).to_be_focused()
    assert page.locator("#strip").evaluate("e=>e.scrollTop") == 0


def painted_samples(locator, *, dot=False):
    """Sample computed styles AND rendered pixels without stopping animations."""
    colors, pixels = [], []
    for _ in range(9):
        colors.append(locator.evaluate("e => {const c=getComputedStyle(e);return [c.borderTopColor,c.backgroundColor,c.opacity,c.animationName,c.boxShadow]}"))
        png = Image.open(io.BytesIO(locator.screenshot(animations="allow"))).convert("RGB")
        point = (png.width // 2, png.height // 2) if dot else (png.width // 2, 0)
        pixels.append(png.getpixel(point))
        locator.page.wait_for_timeout(170)
    return colors, pixels


def assert_flashing(locator, *, dot=False):
    colors, pixels = painted_samples(locator, dot=dot)
    assert len(set(tuple(c[:3]) for c in colors)) > 1, colors
    assert max(sum(abs(a-b) for a, b in zip(p, q)) for p in pixels for q in pixels) > 80, pixels
    return colors


def assert_thin_attention(locator):
    assert locator.evaluate("e=>getComputedStyle(e).borderTopWidth") == "1px"
    assert locator.evaluate("e=>getComputedStyle(e).boxShadow") == "none"
    assert locator.evaluate("e=>getComputedStyle(e).animationDuration") == "2.8s"
    assert_flashing(locator)


def test_running_work_pin_selection_focus_hover_and_legacy_need_are_not_attention(ui):
    fixture, page = ui
    fixture.change(light="green", pin=True)
    # W4 (his rule, 2026-10-05): one rule - the edge pulses exactly when the light is orange; the second Cave card's
    # orange light IS its attention (orange is painted only from a wait-on-him record).
    assert page.frames[1].evaluate("initialAttentionCards") == ["card-p-two"]
    card = page.frames[1].locator("#card-p-one")
    tile = fixture.open(page, EFFORT)
    dot = tile.locator(".activity-dot")
    expect(dot).to_have_attribute("aria-label", "working")
    expect(tile).to_have_class(re.compile(r"\bfocus\b"))
    tile.focus()
    tile.hover()
    colors, pixels = painted_samples(tile)
    assert len(set(pixels)) == 1
    assert all(c[0] == "rgb(111, 162, 255)" and c[3:] == ["none", "none"] for c in colors)
    assert tile.evaluate("e=>getComputedStyle(e).outlineColor") == "rgb(111, 162, 255)"
    page.locator("#strip .tile.cave").click()
    # Legacy work/fact classes must not bypass the exact cockpit's ready state.
    card.evaluate("e=>e.classList.add('need')")
    card.hover()
    expect(card.locator(".t-peek")).to_be_visible()
    card.click()
    expect(card).to_have_attribute("aria-expanded", "true")
    expect(card).not_to_have_class(re.compile(r"\bready\b"))
    colors, pixels = painted_samples(card)
    assert len(set(pixels)) == 1
    assert all(c[0] == "rgb(61, 67, 82)" and c[3:] == ["none", "none"] for c in colors)


@pytest.mark.parametrize("label,owner_phase,attention", [
    ("Current working draft", None, False),
    ("Draft ready for your review", None, True),
    ("Draft no longer ready for your review", None, False),
    ("Draft ready for your review", "revising", False),
    ("Draft ready for your review", "done", False),
])
def test_legacy_review_requires_explicit_designation_without_managed_override(ui, label, owner_phase, attention):
    fixture, page = ui
    fixture.change(light="green", pin=True, legacy=True, label=label, owner_phase=owner_phase)
    tile = fixture.open(page, EFFORT)
    expect(tile.locator(".activity-dot")).to_have_class("activity-dot green")   # John 2026-10-15: working is always green
    page.locator("#strip .tile.cave").click()
    card = page.frames[1].locator("#card-p-one")
    for locator in (tile, card):
        if attention:
            expect(locator).to_have_class(re.compile(r"\bready\b"))
            assert_thin_attention(locator)
        else:
            expect(locator).not_to_have_class(re.compile(r"\bready\b"))
            assert locator.evaluate("e=>getComputedStyle(e).animationName") == "none"


def test_cave_edge_pixels_readiness_highlight_hover_inline_and_resolution(ui):
    fixture, page = ui
    cave = page.frames[1]
    card = cave.locator("#card-p-one")
    baseline = card.bounding_box()
    fixture.change(question=True)
    fixture.refresh(page)
    expect(card).to_have_class(re.compile(r"\bready\b"))
    assert card.evaluate("e=>getComputedStyle(e).borderTopWidth") == "1px"
    # Reproduce the real cascade collision, then check actual painted attention.
    card.evaluate("e=>e.classList.add('flash')")
    assert_thin_attention(card)
    assert card.evaluate("e=>getComputedStyle(e).outlineStyle") == "none"
    assert card.evaluate("e=>getComputedStyle(e).boxShadow") == "none"
    card.evaluate("e=>e.classList.remove('flash')")
    card.hover()
    expect(card.locator(".t-peek")).to_be_visible()
    assert_thin_attention(card)
    # A quiet card has a later border rule; it must also pulse and remain amber
    # with reduced motion, then yield back to the original compact layout.
    card.evaluate("e=>e.classList.add('quiet')")
    assert_thin_attention(card)
    page.emulate_media(reduced_motion="reduce")
    assert card.evaluate("e=>getComputedStyle(e).animationName") in ("readyedge", "attentionedge"), "the edge pulses with reduced motion (his word, 2026-10-05)"
    page.emulate_media(reduced_motion="no-preference")
    card.evaluate("e=>e.classList.remove('quiet')")
    card.focus()
    page.keyboard.press("Escape")
    expect(card).to_be_focused()
    page.keyboard.press("Enter")
    expect(card).to_have_attribute("aria-expanded", "true")
    expect(card).to_have_class(re.compile(r"\bready\b"))
    inline = next(f for f in page.frames if "view=tile" in f.url)
    inline.wait_for_selector("#draft")
    inline.locator("#draft").fill("saved words in the inline dialogue")
    page.set_viewport_size({"width": 1200, "height": 850})
    expect(inline.locator("#draft")).to_be_focused()
    assert inline.locator("#draft").input_value() == "saved words in the inline dialogue"
    assert_flashing(card)
    fixture.change(light="green", review=True)
    fixture.refresh(page)
    expect(card.locator(".tlight")).to_have_class("tlight green")   # John (2026-10-15): working status is always a green light
    expect(card).to_have_class(re.compile(r"\bready\b"))
    assert_flashing(card)
    card.locator(".t-go").click()
    expect(page.locator("#strip .tile")).to_have_count(2)
    page.wait_for_function("() => [...document.querySelectorAll('#stage > iframe')].some(f=>f.contentDocument?.getElementById('draft'))")
    full = next(f for f in page.frames if urlsplit(f.url).path == "/steward/v1" and "view=" not in f.url)
    assert full.locator("#history").text_content() == "History of " + EFFORT
    assert full.locator("#draft").input_value() == "saved words in the inline dialogue"
    # The Cave keeps its dialogue even when hidden; return without accepting.
    page.locator("#strip .tile.cave").click()
    assert inline.locator("#draft").input_value() == "saved words in the inline dialogue"
    card.focus()
    page.keyboard.press("Enter")
    expect(card).to_have_attribute("aria-expanded", "false")
    assert card.bounding_box()["height"] <= baseline["height"] + 2
    fixture.change(light="green", pin=True)
    fixture.refresh(page)
    expect(card).not_to_have_class(re.compile(r"\bready\b"))
    colors, pixels = painted_samples(card)
    assert len(set(pixels)) == 1
    assert all(c[3] == "none" for c in colors)
    assert all(c[0] != "rgb(251, 191, 36)" and c[4] == "none" for c in colors)
    assert any(path == "/api/steward/events" for path, _ in fixture.reads)


@pytest.mark.parametrize("light,question,color", [
    ("green", False, "rgb(74, 222, 128)"),
    ("quiet", False, "rgb(137, 149, 167)"),
    ("red", False, "rgb(224, 95, 95)"),
    ("orange", True, "rgb(251, 191, 36)"),
    ("quiet", True, "rgb(251, 191, 36)"),
    ("orange", False, "rgb(251, 191, 36)"),   # W4: orange is attention by itself
])
def test_status_colors_and_attention_dot_pixels(ui, light, question, color):
    fixture, page = ui
    fixture.change(light=light, question=question)
    tile = fixture.open(page, EFFORT)
    dot = tile.locator(".activity-dot")
    expect(dot).to_have_attribute("aria-label", re.compile("working|idle|a problem|needs your attention"))
    page.wait_for_function("color=>getComputedStyle(document.querySelector('.activity-dot')).backgroundColor===color", arg=color)
    assert dot.evaluate("e=>getComputedStyle(e).backgroundColor") == color
    if question or light == "orange":
        expect(tile).to_have_class(re.compile(r"\bready\b"))
        assert_thin_attention(tile)
        assert_flashing(dot, dot=True)
    else:
        expect(tile).not_to_have_class(re.compile(r"\bready\b"))
        colors, pixels = painted_samples(dot, dot=True)
        assert len(set(pixels)) == 1
        assert all(c[3] == "none" for c in colors)


def test_green_attention_polls_dropped_frames_failure_resolution_and_exact_sessions(ui):
    fixture, page = ui
    fixture.change(light="green", review=True)
    tile = fixture.open(page, EFFORT)
    dot = tile.locator(".activity-dot")
    expect(tile).to_have_class(re.compile(r"\bready\b"))
    assert_thin_attention(tile)
    assert_flashing(dot, dot=True)
    assert dot.evaluate("e=>getComputedStyle(e).backgroundColor") == "rgb(74, 222, 128)"   # John 2026-10-15: the dot is green while working
    expect(dot).to_have_attribute("aria-label", "working; needs your attention")
    original_id = tile.get_attribute("data-id")
    fixture.open(page, "Other effort")
    tile = page.locator(f'#strip [data-id="{original_id}"]')
    dot = tile.locator(".activity-dot")
    page.wait_for_function("() => ![...document.querySelectorAll('#stage > iframe')].some(f=>f.src.includes('exact+cockpit'))")
    expect(page.locator("#strip .tile").last).not_to_have_class(re.compile(r"\bready\b"))
    before = len(fixture.reads)
    fixture.change(light="green", review=True, fail="deliverables")
    fixture.refresh(page)
    page.wait_for_timeout(300)
    expect(tile).to_have_class(re.compile(r"\bready\b"))
    assert len(fixture.reads) > before
    fixture.change(light="quiet", fail="state")
    fixture.refresh(page)
    page.wait_for_timeout(300)
    expect(tile).to_have_class(re.compile(r"\bready\b"))
    assert dot.evaluate("e=>getComputedStyle(e).backgroundColor") == "rgb(251, 191, 36)"   # W4: still waiting on him - orange while the read fails
    tile.hover()
    tile.click()
    expect(tile).to_have_class(re.compile(r"\bready\b"))
    assert_thin_attention(tile)
    fixture.change(light="green", review=True, accepted=True)
    fixture.refresh(page)
    expect(tile).not_to_have_class(re.compile(r"\bready\b"))
    assert dot.evaluate("e=>getComputedStyle(e).animationName") == "none"
    colors, pixels = painted_samples(tile)
    assert len(set(pixels)) == 1
    assert all(c[0] == "rgb(111, 162, 255)" and c[3:] == ["none", "none"] for c in colors)
    fixture.change("", light="green", question=True, general=True, term="7")
    session = fixture.open(page, "", general="1", term="7")
    expect(session).to_have_class(re.compile(r"\bready\b"))
    assert_flashing(session.locator(".activity-dot"), dot=True)
    assert any(q.get("term") == ["7"] and q.get("general") == ["1"] for path, q in fixture.reads if path.endswith("/state"))


def test_reduced_motion_has_steady_amber_edge_and_attention_dot_marker(ui):
    fixture, page = ui
    fixture.change(light="orange", question=True)   # W4: a waiting question IS orange
    tile = fixture.open(page, EFFORT)
    expect(tile).to_have_class(re.compile(r"\bready\b"))
    page.locator("#strip .tile.cave").click()
    card = page.frames[1].locator("#card-p-one")
    expect(card).to_have_class(re.compile(r"\bready\b"))
    page.emulate_media(reduced_motion="reduce")
    card.evaluate("e=>e.classList.add('flash')")
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    # his word (2026-10-05): the attention EDGE pulses even with reduced motion; the dot keeps its steady marker
    for locator in (card, tile):
        assert locator.evaluate("e=>getComputedStyle(e).animationName") in ("readyedge", "attentionedge")
    colors, pixels = painted_samples(tile.locator(".activity-dot"), dot=True)
    assert len(set(pixels)) == 1
    assert all(c[3] == "none" for c in colors)
    assert card.evaluate("e=>getComputedStyle(e).borderTopWidth") == "1px"
    assert tile.evaluate("e=>getComputedStyle(e).animationName") in ("readyedge", "attentionedge")   # pulses (his word)
    assert tile.evaluate("e=>getComputedStyle(e).borderTopWidth") == "1px"
    assert tile.evaluate("e=>getComputedStyle(e).boxShadow") == "none"
    dot = tile.locator(".activity-dot")
    assert dot.evaluate("e=>getComputedStyle(e).outlineColor") == "rgb(224, 168, 54)"
    assert dot.evaluate("e=>getComputedStyle(e).outlineWidth") == "1px"
    page.emulate_media(reduced_motion="no-preference")
    assert_flashing(card)
    assert_thin_attention(tile)
    assert_flashing(dot, dot=True)


def test_singleton_board_and_separate_conversations_survive_row_navigation(ui):
    fixture, page = ui
    for url in ("/project/camp", "/steward/v1?pid=camp&dir=", "/steward/v1?pid=camp&dir=Cave%20of%20Wonders"):
        page.evaluate("url=>ANCHOR_APP.open(url,'_blank',window)", url)
        page.wait_for_timeout(100)
    names = page.locator("#strip .name").all_text_contents()
    assert names == ["Cave of Wonders", "Star Chart", "Star Chart — AI Cockpit", "Cave of Wonders — AI Cockpit"]
    page.evaluate("() => ANCHOR_APP.open('/steward/v1?dir=&pid=camp','_blank',window)")
    expect(page.locator("#strip .tile")).to_have_count(4)
    expect(page.locator("#strip .tile.focus .name")).to_have_text("Star Chart — AI Cockpit")
    frame = next(f for f in page.frames if urlsplit(f.url).path == "/steward/v1")
    assert frame.locator("#history").text_content() == "History of Star Chart"
    page.locator("#two").click()
    expect(page.locator("#two")).to_have_attribute("aria-pressed", "true")
    page.locator("#one").click()
    expect(page.locator("#one")).to_have_attribute("aria-pressed", "true")

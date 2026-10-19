"""The Setup gear on ANCHOR'S OWN upper-left corner (static/app.html), not only the framed Cave's rail.

John's report (2026-10-06): "I don't see a gear on Anchor (upper left corner)." The approved gear landed in
the Cave PAGE's rail head (high_seat_page._rail), which the Anchor program shows inside a pane frame BELOW
the shell's own title bar - so the actual upper-left corner of his window, the app shell's #bar, never
carried a gear at all (a fresh browser at "/" sees the Cave rail at x8,y12; his app shell does not).

These tests drive the REAL shell files (/static/app.html + app.js + app.css) against the REAL server and
the REAL /setup page with normal cookie authentication - the affected production surface, not a stand-in.
Display-only: steward event soft-wake GETs AND every POST besides the login are guarded, so the checks can
never resume another effort or launch work.
"""
import re

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.test_provider_setup import AUTH, stack                    # noqa: F401  (fixture: stack)
from tests.test_provider_setup_browser import cave_server            # noqa: F401  (fixture: cave_server)

DESKTOP = {"width": 1440, "height": 1050}
NARROW = {"width": 390, "height": 844}


def _open_shell(pw, origin, viewport):
    """The app shell, logged in the ordinary way, with the display-only guard armed."""
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(viewport=viewport)
    login = context.request.post(origin + "/api/auth/login", data={"token": AUTH})
    assert login.ok and any(c.get("httpOnly") for c in context.cookies(origin))
    page = context.new_page()
    errors, launched, guarded = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def guard(route):
        req = route.request
        # The framed Cave opens its GET events stream (a soft-wake on the real server). Guard it before it
        # reaches that seam, and guard EVERY POST but the login: a display check must never start work.
        if re.search(r"/api/steward/(events|status-ack)", req.url):
            guarded.append((req.url, req.frame.url))
            route.abort()
            return
        if req.method == "POST" or re.search(r"/api/steward/(say|wake|start)", req.url):
            launched.append((req.method, req.url))
            route.abort()
            return
        route.continue_()

    page.route("**/*", guard)
    page.goto(origin + "/static/app.html")
    page.wait_for_function(
        "() => { const f = document.querySelector('#stage iframe');"
        " return f && f.contentDocument && f.contentDocument.readyState === 'complete'"
        " && f.contentDocument.querySelector('.rail, .masthead'); }")
    return browser, page, errors, launched, guarded


@pytest.mark.parametrize("viewport", [DESKTOP, NARROW])
def test_shell_bar_carries_the_setup_gear_left_of_the_anchor_mark(cave_server, viewport):
    """The gear is on the SHELL's own title bar - very upper left, the Anchor mark shifted to its right."""
    origin, service, data = cave_server
    with sync_playwright() as pw:
        browser, page, errors, launched, guarded = _open_shell(pw, origin, viewport)
        try:
            # page.locator never pierces frames: this is the shell DOCUMENT's bar, not the framed Cave.
            gear = page.locator("#bar #setup-gear")
            expect(gear).to_be_visible()
            expect(gear).to_have_attribute("aria-label", "Setup settings")
            gear_box = gear.bounding_box()
            mark_box = page.locator("#bar .mark").bounding_box()
            assert gear_box and 0 <= gear_box["x"] <= 40 and 0 <= gear_box["y"] <= 45, gear_box
            assert mark_box and gear_box["x"] + gear_box["width"] <= mark_box["x"] + 1, \
                "the Anchor mark did not shift right of the gear"
            # The framed Cave keeps its own working gear (rail head on desktop, masthead when narrow).
            cave = page.frame_locator("#stage iframe >> nth=0")
            assert cave.locator("#setup-gear").count() == 1
            # Steady state: nothing overflows, nothing launched, no script errors.
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not launched, f"Display check launched work: {launched}"
            assert not errors, f"Browser errors: {errors}"
        finally:
            browser.close()


def test_shell_gear_opens_the_saved_setup_page_once_and_reuses_it(cave_server):
    """Keyboard-open the SAME saved /setup page as a tile; repeats reuse it; Return shows the Cave again;
    the Cave's composer draft survives the whole round trip; no second conversation, no launched work."""
    origin, service, data = cave_server
    with sync_playwright() as pw:
        browser, page, errors, launched, guarded = _open_shell(pw, origin, DESKTOP)
        try:
            cave = page.frame_locator("#stage iframe >> nth=0")
            say = cave.locator("#say")
            if not say.count():
                say = cave.locator("textarea").first
            say.fill("Retain this unfinished Cave draft")

            gear = page.locator("#bar #setup-gear")
            gear.focus()
            page.keyboard.press("Enter")                       # keyboard reaches the gear too
            setup = page.frame_locator('#stage iframe[src$="/setup"]')
            expect(setup.locator("#setup-section-providers")).to_be_visible()
            # Normal cookie authentication reached the saved settings: the page's own API read populated it.
            expect(setup.locator("#setup-family")).to_have_value("claude")
            setup_tiles = page.locator("#strip .tile .name", has_text="Anchor · Setup")
            expect(setup_tiles).to_have_count(1)

            # A second open reuses the SAME live page - one tile, one frame, no reload, no new conversation.
            setup.locator("body").evaluate("b => { b._anchorProof = 'same setup page'; }")
            gear.click()
            expect(setup_tiles).to_have_count(1)
            assert page.locator('#stage iframe[src$="/setup"]').count() == 1
            assert setup.locator("body").evaluate("b => b._anchorProof") == "same setup page"

            # "Return to Cave" inside the framed Setup page brings the Cave back to the pane.
            setup.locator("#setup-return").click()
            page.wait_for_function(
                "() => { const shown = [...document.querySelectorAll('#stage iframe')].filter(f => !f.hidden);"
                " return shown.length === 1 && shown[0].contentWindow.location.pathname === '/'; }")
            expect(setup_tiles).to_have_count(1)               # the Setup tile remains a tile
            expect(say).to_have_value("Retain this unfinished Cave draft")

            # Opening again from its tile-less frame state still reuses the one tile.
            gear.click()
            expect(page.frame_locator('#stage iframe[src$="/setup"]').locator("#setup-section-providers")).to_be_visible()
            expect(setup_tiles).to_have_count(1)

            assert not launched, f"Settings opened unrelated work: {launched}"
            assert all("/setup" not in frame for url, frame in guarded), guarded
            assert not errors, f"Browser errors: {errors}"
        finally:
            browser.close()

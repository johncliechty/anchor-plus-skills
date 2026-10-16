"""Painted Cave health updates preserve the existing dialogue and report truth."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

import high_seat_page
from tests.test_app_header_attention import ReadOnlyUI, cave_html, EFFORT, ORIGIN


def health(status="red", day="2026-10-08"):
    return {"ok": True, "status": status, "last_run": day,
            "issues": [{"component": "Steward cockpit surface", "detail": "Injected correctness failure"}]
            if status == "red" else [],
            "warnings": ["Slow but ready"] if status == "yellow" else []}


class HealthUI(ReadOnlyUI):
    def __init__(self, context):
        self.health = health()
        self.health_status = 200
        self.health_reads = 0
        super().__init__(context)

    def route(self, route):
        path = urlsplit(route.request.url).path
        if path == "/api/doctor/status" and route.request.method == "GET":
            self.health_reads += 1
            return route.fulfill(status=self.health_status, json=self.health)
        if path in ("/", "/high-seat"):
            old = high_seat_page._health_banner({"rows": [{"rule": "health", "text": "Health check found issues",
                "why": "2026-10-08 — Doctor can diagnose it",
                "href": "/doctor?issueId=ZH_HEALTH_CHECK_ISSUES&diagnose=1"}], "build": "test"})
            html = cave_html().replace("<body>", '<body><div class="main"><div class="masthead">Cave of Wonders</div>' + old)
            return route.fulfill(body=html.replace("</body>", "</div></body>"), content_type="text/html")
        return super().route(route)


@pytest.fixture
def cave():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_init_script("""const intervals=window.setInterval;
window.setInterval=(fn,ms,...args)=>intervals(fn,ms===15000?100:ms,...args);""")
        fixture = HealthUI(context)
        page = context.new_page()
        page.goto(ORIGIN + "/static/app.html")
        page.wait_for_function("() => document.querySelector('#stage iframe')?.contentWindow?.AnchorCaveHealth")
        frame = next(f for f in page.frames if f != page.main_frame and f.url.rstrip("/") == ORIGIN)
        expect(frame.locator(".healthbar")).to_have_count(1)
        yield fixture, page, frame
        assert not fixture.forbidden, fixture.forbidden
        assert not fixture.errors, fixture.errors
        browser.close()


def test_health_only_change_clears_without_replacing_composer_or_initiative(cave, tmp_path):
    fixture, page, frame = cave
    frame.locator("#say").fill("Keep this unsent Cave draft")
    frame.locator("#card-p-one").click()
    nested = frame.frame_locator("#card-p-one iframe")
    nested.locator("#draft").fill("Keep this unsent initiative draft")
    frame.evaluate("""() => {
 window.keptComposer=document.getElementById('say');
 window.keptFrame=document.querySelector('#card-p-one iframe');
 window.keptHealth=document.querySelector('.healthbar');
 window.keptStamp=JSON.stringify(window.ANCHOR_BOOT);
} """)
    fixture.health = health("yellow")
    expect(frame.locator(".healthbar")).to_have_count(0)
    assert frame.evaluate("keptComposer===document.getElementById('say') && keptFrame===document.querySelector('#card-p-one iframe')")
    assert frame.evaluate("keptStamp===JSON.stringify(window.ANCHOR_BOOT)")
    expect(frame.locator("#say")).to_have_value("Keep this unsent Cave draft")
    expect(nested.locator("#draft")).to_have_value("Keep this unsent initiative draft")
    assert fixture.health["warnings"] == ["Slow but ready"]
    page.screenshot(path=str(tmp_path / "health-cleared.png"))
    fixture.health = health("red")
    expect(frame.locator(".healthbar")).to_have_count(1)
    link = frame.locator(".healthbar a")
    expect(link).to_have_attribute("href", "/doctor?issueId=ZH_HEALTH_CHECK_ISSUES&diagnose=1")
    frame.evaluate("window.keptHealth=document.querySelector('.healthbar')")
    frame.evaluate("window.AnchorCaveHealth.refresh()")
    assert frame.evaluate("keptHealth===document.querySelector('.healthbar')")
    page.screenshot(path=str(tmp_path / "health-returned.png"))


@pytest.mark.parametrize("invalid", [
    {"ok": False}, {**health("green"), "status": "unknown"},
    {**health("green"), "status": "none"}, {**health("green"), "issues": None},
    {**health("red"), "status": "yellow"}, health("green", "2026-10-07"),
])
def test_failed_or_invalid_read_retains_last_known_banner(cave, invalid):
    fixture, page, frame = cave
    frame.evaluate("window.keptHealth=document.querySelector('.healthbar')")
    fixture.health = invalid
    frame.evaluate("window.AnchorCaveHealth.refresh()")
    assert frame.evaluate("keptHealth===document.querySelector('.healthbar')")
    fixture.health_status = 503
    frame.evaluate("window.AnchorCaveHealth.refresh()")
    expect(frame.locator(".healthbar")).to_have_count(1)


def test_return_to_cave_and_repeated_start_use_one_reader(cave):
    fixture, page, frame = cave
    frame.locator("#say").fill("A draft held through switching tiles")
    fixture.open(page, EFFORT)
    fixture.health = health("green")
    page.locator("#strip .tile").first.click()
    frame.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(frame.locator(".healthbar")).to_have_count(0)
    expect(frame.locator("#say")).to_have_value("A draft held through switching tiles")
    assert frame.evaluate("""() => {
 const reader=window.AnchorCaveHealth; reader.start(); reader.start();
 return reader===window.AnchorCaveHealth;
}""")

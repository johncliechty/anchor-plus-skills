"""Demonstrate stale-banner reconciliation in a fresh guarded browser.

This diagnoses existing behavior. It changes neither production source nor any
live report. A prior banner is injected into browser memory to model an open
Cave that predates the corrected report; the real refresh function is exposed
only in this browser for observation.
"""
import json
import os
from pathlib import Path
import sys
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import home_attention
import high_seat_page

OUT = Path(__file__).parent
ORIGIN = "http://127.0.0.1:8777"


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        token = os.environ.get("ANCHOR_TOKEN")
        if token:
            login = context.request.post(ORIGIN + "/api/auth/login", data={"token": token})
            assert login.ok and login.json().get("ok"), "Normal login failed"

        blocked = []

        def guard(route):
            request = route.request
            if request.method != "GET" or "/api/steward/" in request.url or "/steward-api/" in request.url:
                blocked.append({"method": request.method, "path": request.url.split(ORIGIN)[-1].split("?")[0]})
                route.fulfill(json={"ok": True, "events": [], "next": 0})
            else:
                route.continue_()

        context.route("**/api/**", guard)
        context.route("**/steward-api/**", guard)
        instrumented = []

        def instrument(route):
            response = route.fetch()
            source = response.text()
            marker = "var facesBusy = false, facesAgain = false;"
            assert marker in source, "Refresh source changed; inspection hook invalid"
            instrumented.append(True)
            route.fulfill(response=response, body=source.replace(
                marker, "window.__caveHealthReadOnlyProbe = refreshFaces; " + marker, 1))

        context.route("**/static/high-seat-page.js*", instrument)
        page = context.new_page()
        page.goto(ORIGIN + "/static/app.html", wait_until="domcontentloaded")
        cave = page.frame_locator("iframe.pane").first
        cave.locator(".masthead").wait_for(timeout=30000)
        frame = next(f for f in page.frames if f != page.main_frame and f.url.rstrip("/") == ORIGIN)
        frame.wait_for_function("typeof window.__caveHealthReadOnlyProbe === 'function'")
        assert instrumented
        fresh_count = frame.locator(".healthbar").count()
        assert fresh_count == 0
        page.screenshot(path=str(OUT / "fresh-app.png"))
        source_rows = home_attention.build_attention(health=("2026-10-07", "ISSUES FOUND"))
        stale = high_seat_page._health_banner({"rows": source_rows, "build": "diagnosis"})
        assert stale
        frame.evaluate("html => document.querySelector('.masthead').insertAdjacentHTML('afterend', html)", stale)
        before = frame.locator(".healthbar").inner_text()
        frame.evaluate("""() => {
          window.__caveOriginalComposer = document.querySelector('textarea');
          window.__caveHealthReadOnlyProbe();
        }""")
        with page.expect_response(lambda r: r.url.split("?")[0] == ORIGIN + "/high-seat") as fresh:
            frame.evaluate("window.__caveHealthReadOnlyProbe()")
        response = fresh.value
        response.finished()
        page.wait_for_timeout(700)
        after_count = frame.locator(".healthbar").count()
        after = frame.locator(".healthbar").inner_text()
        assert after_count == 1 and after == before
        assert frame.evaluate("window.__caveOriginalComposer === document.querySelector('textarea')")
        page.screenshot(path=str(OUT / "stale-after-refresh.png"))
        receipt = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": "Fresh Chromium app shell against the actual service; stale banner injected into browser memory; refresh hook only in this browser.",
            "normal_login_cookie": bool(token),
            "fresh_banner_count": fresh_count,
            "fresh_refresh_http_status": response.status,
            "fresh_refresh_contains_healthbar": 'class="healthbar"' in response.text(),
            "stale_banner_count_after_refresh": after_count,
            "stale_banner_text": after,
            "composer_node_preserved": True,
            "native_wake_and_write_guard": True,
            "blocked_request_count": len(blocked),
            "existing_client": "Not inspected by this browser; separate interactive capture found no local Anchor window.",
        }
        (OUT / "browser-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        browser.close()


if __name__ == "__main__":
    main()

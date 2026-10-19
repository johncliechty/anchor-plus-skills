"""Session-owned read-only pixel checks against the actual Anchor service."""
import importlib.util
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("repair_live", HERE / "recovery-live.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


def main():
    credential = live.token()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        def authorize(route):
            if route.request.method != "GET":
                route.abort()
                return
            headers = dict(route.request.headers)
            headers["Authorization"] = "Bearer " + credential
            route.continue_(headers=headers)
        context.route(live.BASE + "/**", authorize)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(live.BASE + "/doctor", wait_until="domcontentloaded")
        page.locator("#engChat").wait_for(timeout=10000)
        page.wait_for_function("!document.getElementById('engChat').disabled && document.getElementById('engHealth').textContent.includes('chatgpt ready')")
        assert page.locator("#engChat").is_visible()
        assert page.locator("#diagnoseBtn").is_enabled()
        page.evaluate("window.dispatchEvent(new Event('focus'))")
        page.wait_for_function("document.getElementById('cardStatusDetail').textContent.includes('sidecar drift')")
        assert page.locator("#doctorIssues").inner_text().strip() == ""
        assert "1px" in page.locator("#engChat").get_attribute("style")
        page.screenshot(path=str(HERE / "repair-doctor-live.png"))
        doctor = {"chatgpt_button_visible_and_selected": True,
                  "diagnose_enabled": True, "no_stale_issue_panel": True,
                  "remaining_warning_explained": True}
        page.goto(live.BASE + "/project/" + live.PROJECT, wait_until="domcontentloaded")
        page.get_by_text(live.EFFORT, exact=True).first.click(timeout=15000)
        frame = page.frame_locator("[data-fsframe]")
        frame.locator("[data-spend]").filter(has_text="cost unavailable").wait_for(timeout=20000)
        frame.get_by_text("Jarvis here, John", exact=False).first.wait_for(timeout=10000)
        greeting = frame.get_by_text("Jarvis here, John", exact=False).first.inner_text()
        assert "\ufffd" not in greeting
        assert "tokens" in frame.locator("[data-spend]").inner_text()
        page.screenshot(path=str(HERE / "repair-cockpit-live.png"))
        if errors:
            raise RuntimeError("Browser script error: " + errors[0])
        print(json.dumps({"doctor": doctor,
                          "cockpit": {"unknown_cost_not_zero": True,
                                      "tokens_visible": True,
                                      "restored_greeting_unicode_intact": True},
                          "mutating_browser_requests_blocked": True}))
        browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:300]}))
        raise SystemExit(2)

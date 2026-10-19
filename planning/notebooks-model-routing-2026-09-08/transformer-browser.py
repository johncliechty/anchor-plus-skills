"""Read-only desktop/tablet view proof of the recovered live project."""
import importlib.util
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("recovery", HERE / "transformer-recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def main():
    credential = recovery.live.token()
    proof = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for label, width, height in (("desktop", 1440, 1000), ("tablet", 1024, 1366)):
            context = browser.new_context(viewport={"width": width, "height": height})
            def authorize(route):
                if route.request.method != "GET":
                    route.abort()
                    return
                headers = dict(route.request.headers)
                headers["Authorization"] = "Bearer " + credential
                route.continue_(headers=headers)
            context.route(recovery.live.BASE + "/**", authorize)
            page = context.new_page()
            page.goto(recovery.live.BASE + "/project/" + recovery.PROJECT, wait_until="domcontentloaded")
            page.get_by_text(recovery.EFFORT, exact=True).first.click(timeout=15000)
            frame = page.frame_locator("[data-fsframe]")
            original = frame.get_by_text("You should be using ChatGPT and Grok now, not fabel", exact=True)
            original.first.wait_for(timeout=20000)
            frame.get_by_text("What are you looking for wrt getting approvals", exact=True).first.wait_for(timeout=10000)
            frame.locator("[data-statetext]").filter(has_text="chatgpt").wait_for(timeout=15000)
            state_text = frame.locator("[data-statetext]").inner_text()
            original.first.scroll_into_view_if_needed()
            page.screenshot(path=str(HERE / ("transformer-" + label + "-live.png")))
            proof.append({"viewport": label, "morning_instructions_visible": True,
                "chatgpt_visible": "chatgpt" in state_text, "mutating_browser_requests_blocked": True})
            context.close()
        browser.close()
    print(json.dumps({"proof": proof, "physical_ipad_tested": False}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:180]}))
        raise SystemExit(2)

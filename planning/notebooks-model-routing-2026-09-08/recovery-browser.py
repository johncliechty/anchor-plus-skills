"""Read-only pixel check of the real recovered cockpit; no prompt submission."""
import importlib.util
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('recovery_live', HERE / 'recovery-live.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)

def main():
    credential = live.token()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':1440,'height':1000})
        def authorize(route):
            if route.request.method != 'GET':
                route.abort()
                return
            headers = dict(route.request.headers)
            headers['Authorization'] = 'Bearer ' + credential
            route.continue_(headers=headers)
        context.route(live.BASE+'/**', authorize)
        page = context.new_page()
        page.goto(live.BASE+'/project/'+live.PROJECT, wait_until='domcontentloaded')
        page.get_by_text(live.EFFORT, exact=True).first.click(timeout=15000)
        frame = page.frame_locator('[data-fsframe]')
        frame.get_by_text('Jarvis here, John', exact=False).wait_for(timeout=20000)
        screenshot = HERE / 'recovery-live-cockpit.png'
        page.screenshot(path=str(screenshot))
        print(json.dumps({'live_cockpit_greeting_visible':True,'screenshot':screenshot.name,
            'mutating_requests_blocked':True}))
        browser.close()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'ok':False,'error_type':type(exc).__name__}))
        raise SystemExit(2)

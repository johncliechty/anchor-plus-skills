"""Normally authenticated, disposable browser/server proof of Setup and Cave."""
from copy import deepcopy
from pathlib import Path
import json
import re
import threading

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.test_provider_setup import AUTH, stack, row


@pytest.fixture
def cave_server(stack, monkeypatch):
    import anchor_gui
    import high_seat_page
    from tests.test_high_seat_page_2026_09_26 import _ctx
    service, _, data, _ = stack
    service.snapshot(True)
    context=_ctx()
    context.update(auth_required=True,logged_in=True,build=anchor_gui.BUILD_ID,capacity=[])
    context["steward"]={"key":"aladdin","label":"Aladdin","high_seat":"aladdin-high-seat-cave.jpg",
                        "high_seat_name":"Cave of Wonders","seal_name":"Lamp","campaign_name":"Star Chart","campaign_icon":"campaign-aladdin-star-chart.jpg"}
    # Use the real Cave page and route with frozen display fixtures. Every
    # account action and authentication request is the actual application seam.
    monkeypatch.setattr(anchor_gui,"_high_seat_context",lambda:deepcopy(context))
    server=anchor_gui.make_server("127.0.0.1",0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}",service,data
    finally:
        server.shutdown();server.server_close();thread.join(3)
        assert not thread.is_alive()


def test_setup_cached_page_loads_while_native_refresh_is_busy(cave_server, monkeypatch):
    import anchor_settings
    import provider_native
    import provider_settings
    origin, service, data = cave_server
    ledger = data / ".anchor" / "usage_ledger"
    ledger.mkdir(parents=True)
    for i in range(257):
        (ledger / f"{i}.json").write_text(json.dumps({"entries": {
            "one": {"provider_connection_id": "claude-default", "tokens": 123},
            "legacy": {"tokens": 999},
        }}), encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    def busy(connection):
        entered.set()
        assert release.wait(15)
        raise provider_native.NativeError("unsupported")
    monkeypatch.setattr(service.native, "observe", busy)
    account = provider_settings.find_connection(anchor_settings.load_settings(), "chatgpt-default")
    worker = threading.Thread(target=service.refresh, args=(account,))
    worker.start()
    try:
        assert entered.wait(2)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                login = context.request.post(origin + "/api/auth/login", data={"token": AUTH})
                assert login.ok and any(c.get("httpOnly") for c in context.cookies(origin))
                page = context.new_page()
                errors, blocked = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                def guard(route):
                    if route.request.method != "GET" or "/api/steward/events" in route.request.url:
                        blocked.append(route.request.url)
                        route.abort()
                    else:
                        route.continue_()
                page.route("**/*", guard)
                for _ in range(2):
                    page.goto(origin + "/setup", wait_until="domcontentloaded")
                    expect(page.locator("#host-runtime")).to_contain_text("existing setup retained", timeout=3000)
                    expect(page.locator("#provider-detail")).to_contain_text("31,611 tokens")
                    assert worker.is_alive(), "Page load did not overlap the native refresh"
                # A failed ledger read retains the observed figure with an
                # explicit stale label on the actual account detail surface.
                (ledger / "0.json").write_text("invalid", encoding="utf-8")
                page.reload(wait_until="domcontentloaded")
                expect(page.locator("#provider-detail")).to_contain_text("31,611 tokens")
                consumption = page.locator(".provider-facts div").filter(has=page.locator("dt", has_text="Anchor-observed consumption"))
                expect(consumption).to_contain_text("stale")
                assert not errors and not blocked
            finally:
                browser.close()
    finally:
        release.set(); worker.join(5)
    assert not worker.is_alive()


@pytest.mark.parametrize("viewport",[{"width":1440,"height":1050},{"width":390,"height":844}])
def test_setup_gear_retains_settings_draft_and_cave_controls(cave_server,viewport):
    origin,service,data=cave_server
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport=viewport)
        page=context.new_page()
        launched=[];errors=[];guarded_streams=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def prevent_work(route):
            req=route.request
            # The existing Cave dialogue opens its GET events stream (a
            # soft-wake on the real server). Guard it before it reaches that
            # seam, as well as POSTs. Setup itself must never open such a stream.
            if re.search(r'/api/steward/(events|status-ack)',req.url):
                guarded_streams.append((req.url,req.frame.url))
                route.abort()
                return
            if (req.method=='POST' and '/api/provider-setup/' not in req.url and '/api/auth/login' not in req.url
                    or re.search(r'/api/steward/(say|wake|start)',req.url)):
                launched.append((req.method,req.url))
                route.abort()
            else:route.continue_()
        page.route('**/*',prevent_work)
        try:
            # Ordinary login grants an HttpOnly cookie; no injected auth header.
            response=context.request.post(origin+'/api/auth/login',data={"token":AUTH})
            assert response.ok
            assert any(cookie.get('httpOnly') for cookie in context.cookies(origin))
            page.goto(origin+'/high-seat')
            expect(page.locator('#cave-family')).to_have_value('claude')
            expect(page.locator('#cave-account')).to_have_value('claude-default')
            expect(page.locator('#cave-provider-capacity')).to_contain_text('allowance unsupported')
            expect(page.locator('#cave-model')).to_have_value('latest_supported')
            expect(page.locator('#cave-effort')).to_have_value('highest_supported')
            gear=page.locator('#setup-gear')
            gear_box=gear.bounding_box()
            assert gear_box and 0<=gear_box['x']<=40 and 0<=gear_box['y']<=45
            # Saved composer nodes remain mounted behind the contained settings.
            say=page.locator('#say')
            if not say.count():say=page.locator('textarea').first
            expect(say).to_be_visible()
            say.fill('Retain this unfinished Cave draft')
            identity=say.evaluate('e=>{e._providerProof="same composer";return e.id}')
            gear.scroll_into_view_if_needed();gear.focus();page.keyboard.press('Enter')
            expect(page.locator('.provider-dialog')).to_be_visible()
            box=page.locator('.provider-dialog').bounding_box()
            assert box and box['x']>=-1 and box['y']>=-1
            assert box['x']+box['width']<=viewport['width']+1 and box['y']+box['height']<=viewport['height']+1
            surface=page.frame_locator('.provider-dialog iframe')
            expect(surface.locator('#setup-family')).to_have_value('claude')
            expect(surface.locator('#setup-account')).to_have_value('claude-default')
            expect(surface.locator('#setup-section-providers')).to_be_visible()
            surface.locator('#setup-threshold').select_option('30')
            surface.locator('#setup-apply').click()
            expect(surface.locator('#apply-message')).to_contain_text('Saved for new work')
            assert service.snapshot()['preferences']['warning_threshold']==30
            surface.locator('#setup-return').click()
            expect(page.locator('.provider-dialog')).not_to_be_visible()
            expect(say).to_have_value('Retain this unfinished Cave draft')
            assert say.evaluate('e=>e._providerProof')=='same composer'
            expect(gear).to_be_focused()
            gear.click()
            expect(surface.locator('#setup-threshold')).to_have_value('30')
            surface.locator('#setup-model').select_option('frontier')
            surface.locator('#setup-effort').select_option('high')
            surface.locator('#setup-apply').click()
            expect(surface.locator('#apply-message')).to_contain_text('Saved for new work')
            surface.locator('#setup-return').click()
            expect(page.locator('#cave-model')).to_have_value('frontier')
            expect(page.locator('#cave-effort')).to_have_value('high')
            page.locator('#cave-provider-settings').click()
            surface.locator('#setup-return').focus();surface.locator('body').press('Escape')
            expect(page.locator('.provider-dialog')).not_to_be_visible()
            page.locator('#cave-model').select_option('balanced')
            page.locator('#cave-effort').select_option('high')
            gear.click();surface.locator('#setup-return').click()
            expect(page.locator('.provider-dialog')).not_to_be_visible()
            expect(page.locator('#cave-model')).to_have_value('balanced')
            assert service.snapshot()['preferences']['quality']['claude']['model']=='frontier'
            assert not launched, f'Settings launched unrelated work: {launched}'
            assert all('/setup' not in frame and 'dir=Cave%20of%20Wonders' in url for url,frame in guarded_streams)
            assert not errors, f'Browser errors: {errors}'
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            resized={'width':390,'height':844} if viewport['width']>760 else {'width':1440,'height':1050}
            page.set_viewport_size(resized)
            parent='.masthead .mh-title' if resized['width']<=760 else '.provider-rail-head'
            expect(page.locator(parent+' #setup-gear')).to_have_count(1)
            page.evaluate('()=>window.scrollTo(0,0)')
            assert gear.bounding_box()['y']<=45 and gear.count()==1
            assert say.evaluate('e=>e._providerProof')=='same composer'
            page.set_viewport_size(viewport)
            parent='.masthead .mh-title' if viewport['width']<=760 else '.provider-rail-head'
            expect(page.locator(parent+' #setup-gear')).to_have_count(1)
            # Capture actual pixels from the isolated page, never John's client.
            screenshots=data.parent/'browser-pixels';screenshots.mkdir(exist_ok=True)
            gear.click()
            surface.locator('#setup-section-providers').wait_for(state='visible')
            surface.locator('body').evaluate('()=>window.scrollTo(0,0)')
            page.screenshot(path=str(screenshots/f'setup-{viewport["width"]}.png'))
            surface.locator('#setup-return').click()
            expect(page.locator('.provider-dialog')).not_to_be_visible()
            page.evaluate('()=>window.scrollTo(0,0)')
            page.screenshot(path=str(screenshots/f'cave-{viewport["width"]}.png'))
        finally:
            context.close();browser.close()


def test_wave3_star_chart_onboarding_browser_interactions(cave_server):
    origin, service, data = cave_server
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            response = context.request.post(origin + "/api/auth/login", data={"token": AUTH})
            assert response.ok
            page.goto(origin + "/setup", wait_until="domcontentloaded")
            page.locator('.setup-steps [data-section="chart"]').click()
            expect(page.locator("#setup-section-chart")).to_be_visible()
            expect(page.locator("#root-path-display")).to_have_text(r"C:\dev")
            expect(page.locator("#folder-list-container .w3-folder-row")).to_have_count(8)

            # Change Workspace Root via Drawer 1
            page.locator("#btn-toggle-change-root").click()
            expect(page.locator("#drawer-change-root")).to_be_visible()
            page.locator("#input-new-root").fill(r"D:\CaveWorkspace")
            page.locator("#btn-apply-root").click()
            expect(page.locator("#root-path-display")).to_have_text(r"D:\CaveWorkspace")

            # Toggle a folder to Excluded and verify Undo toast
            anchor_row = page.locator('#folder-list-container .w3-folder-row[data-folder-id="f-fin"]')
            anchor_row.locator("button", has_text="○ Excluded").click()
            expect(page.locator("#exclude-undo-toast")).to_be_visible()
            page.locator("#btn-undo-exclude").click()
            expect(page.locator("#exclude-undo-toast")).not_to_be_visible()

            # Switch across Right-Column modes (Projects -> Star Chart -> Setup Coach)
            page.locator("#tab-mode-starchart").click()
            expect(page.locator("#view-mode-starchart")).to_be_visible()
            expect(page.locator("#goals-grid-container .w3-goal-card")).to_have_count(3)

            page.locator("#tab-mode-guide").click()
            expect(page.locator("#view-mode-guide")).to_be_visible()

            assert not errors, f"Browser errors: {errors}"
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        finally:
            context.close()
            browser.close()


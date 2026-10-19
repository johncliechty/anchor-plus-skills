"""Drive the landed Lamp through a fresh Anchor server and the real live route.

Writes only screenshots and isolated runtime data inside this worktree. No
campaign files, registry copies, cockpit event GETs, control POSTs or activation.
The existing Foundry project is bound in memory for the isolated route check.
"""
import hashlib
import json
import os
import secrets
import sys
import threading
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
scratch = ROOT / 'test_tmp_foundry_lamp'
scratch.mkdir(exist_ok=True)
os.environ.update(ANCHOR_DATA_DIR=str(scratch), TEMP=str(scratch), TMP=str(scratch),
                  ANCHOR_PROACTIVE_SUMMARY='0', ANCHOR_PTY_BACKEND='stub',
                  ANCHOR_ENGINE_CMD=f'{sys.executable} -c pass', ANCHOR_TOKEN=secrets.token_hex(32))

import anchor_gui
import foundry_page
from playwright.sync_api import sync_playwright

PID = '30ffba93f3614ce48aeda6252b74cf42'
REL = 'Foundry page and knowledge maps/steward-lamp/index.html'
REVIEW = '/artifact/' + PID + '?path=' + quote(REL, safe='')
SHOTS = ROOT / 'tests/artifacts/foundry-walkthrough/lamp-integrated'


def authenticate(tab, base):
    # Let the normal local-page rule set the HttpOnly cookie. Block all
    # incidental page reads, including events GETs that could soft-wake work.
    tab.route('**/*', lambda route: route.continue_() if
              route.request.is_navigation_request() and urlsplit(route.request.url).path == '/doctor'
              else route.abort())
    tab.goto(base + '/doctor')
    assert any(c['name'] == 'anchor_auth' and c['httpOnly'] for c in tab.context.cookies())
    tab.unroute('**/*')


def watch(tab, failures, errors, writes):
    tab.on('pageerror', lambda e: errors.append(str(e)))
    tab.on('requestfailed', lambda r: failures.append(r.url))
    tab.on('response', lambda r: failures.append(f'{r.status} {r.url}') if r.status >= 400 else None)
    tab.on('request', lambda r: writes.append(r.url) if r.method != 'GET' else None)


def live_check(browser):
    base = os.environ.get('FOUNDRY_LIVE_ORIGIN', 'http://127.0.0.1:8777')
    context = browser.new_context(viewport={'width': 1440, 'height': 1050})
    tab = context.new_page()
    failures, errors, writes = [], [], []
    try:
        authenticate(tab, base)
        watch(tab, failures, errors, writes)
        response = tab.goto(base + REVIEW)
        tab.wait_for_load_state('networkidle')
        populated = tab.locator('#panel').count() and bool(tab.locator('#panel').inner_text())
        tab.screenshot(path=str(SHOTS / 'current-live-opening.png'))
        assert not writes
        return dict(route=base + REVIEW, status=response.status, panel_populated=bool(populated),
                    loading_failures=failures, errors=errors, writes=writes,
                    activation='Observed only; server and existing client were not restarted or reloaded.')
    finally:
        context.close()


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    root = str(Path(foundry_page.api.FOUNDRY_ROOT))
    entry = {'id': PID, 'folder_path': root}
    anchor_gui._rnd.get_project = lambda pid: entry if pid == PID else None
    anchor_gui._rnd.list_projects = lambda **kwargs: [entry]
    profile = foundry_page.anchor_settings.steward_profile
    foundry_page.anchor_settings.steward_profile = lambda: profile({'steward_type': 'aladdin'})
    detail = foundry_page.skill_detail('steward-project')
    assert len(detail['libraryResources']) == len(detail['knowledgeMap']['nodes']) == 46
    assert len(detail['processMap']['steps']) == 40
    server = anchor_gui.make_server('127.0.0.1', 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    failures, errors, writes, clicks = [], [], [], 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for width, height, name in [(1440, 1050, 'desktop'), (390, 844, 'phone')]:
                    context = browser.new_context(viewport={'width': width, 'height': height})
                    tab = context.new_page()
                    authenticate(tab, base)
                    watch(tab, failures, errors, writes)
                    response = tab.goto(base + REVIEW)
                    tab.get_by_role('heading', name='Knowledge map', exact=True).wait_for()
                    assert response.status == 200 and '/steward-lamp/index.html' in tab.url
                    assert 'allow-same-origin' not in response.headers.get('content-security-policy', '')
                    assert tab.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert tab.locator('#persona-icon').evaluate('(el) => el.complete && el.naturalWidth > 0')
                    if width < 780:
                        tab.locator('#panel').scroll_into_view_if_needed()
                    tab.screenshot(path=str(SHOTS / f'{name}-artifact-opening.png'))
                    tab.get_by_role('link', name='Library', exact=True).click()
                    tab.locator('#panel .card').first.wait_for()
                    assert tab.locator('#panel .card').count() == 46
                    tab.locator('#panel').scroll_into_view_if_needed()
                    tab.screenshot(path=str(SHOTS / f'{name}-artifact-library.png'))
                    for link in tab.locator('#panel [data-resource]').all():
                        rid = link.get_attribute('data-resource')
                        link.click()
                        frame = tab.frame_locator('#resource-frame')
                        frame.locator(f'article[data-resource-id="{rid}"]').wait_for()
                        source = frame.get_by_role('link', name='Open numbered source', exact=True)
                        source.click()
                        frame.locator('#L1').wait_for()
                        frame.locator('.source-provenance').wait_for()
                        assert frame.locator('pre').inner_text()
                        clicks += 1
                        tab.get_by_role('button', name='Close resource', exact=True).click()
                    for persona, label in [('jarvis', 'Jarvis-Server'), ('ecgberht', 'Ecgberht-Seal'), ('aladdin', 'Aladdin-Lamp')]:
                        tab.get_by_label('Preview selected persona').select_option(persona)
                        assert tab.get_by_role('heading', name=label, exact=True).is_visible()
                    tab.goto(base + REVIEW + '#handoff')
                    tab.get_by_role('heading', name='Anchor handoff', exact=True).wait_for()
                    tab.goto(base + '/foundry?skill=steward-project')
                    tab.get_by_role('heading', name='Aladdin-Lamp', exact=True).wait_for()
                    assert 'Walkthrough unfinished' not in tab.locator('#skill-main').inner_text()
                    tab.get_by_role('button', name='Concept: Keep one effort coherent', exact=True).click()
                    with tab.expect_popup() as popup:
                        tab.get_by_role('link', name='Open Library resource', exact=True).click()
                    watch(popup.value, failures, errors, writes)
                    popup.value.get_by_role('heading', name='Keep one effort coherent', exact=True).wait_for()
                    popup.value.close()
                    tab.get_by_role('button', name='Outline', exact=True).click()
                    assert tab.locator('.map-outline').is_visible()
                    tab.screenshot(path=str(SHOTS / f'{name}-foundry-knowledge.png'))
                    tab.locator('#library > summary').click()
                    assert tab.locator('#library .library-resource').count() == 46
                    # Actual exact provenance, including frozen examples.
                    for resource in detail['libraryResources'] if name == 'desktop' else []:
                        source = resource['sourceHref']
                        r = context.request.get(base + source)
                        assert r.status == 200, source
                        assert 'class="hit"' in r.text()
                        clicks += 1
                    tab.locator('#process-map > summary').click()
                    assert tab.locator('.process-step').count() == 40
                    tab.locator('.disagreements details').first.locator('summary').click()
                    with tab.expect_popup() as popup:
                        tab.locator('.disagreements details').first.get_by_role('link').first.click()
                    watch(popup.value, failures, errors, writes)
                    popup.value.locator('.hit').wait_for()
                    popup.value.close()
                    tab.locator('.observed-examples details').first.locator('summary').click()
                    with tab.expect_popup() as popup:
                        tab.locator('.observed-examples details').first.get_by_role('link').first.click()
                    watch(popup.value, failures, errors, writes)
                    popup.value.locator('[data-source-freshness="frozen-example"]').wait_for()
                    popup.value.screenshot(path=str(SHOTS / f'{name}-frozen-source.png'))
                    popup.value.close()
                    tab.locator('#process-map').scroll_into_view_if_needed()
                    tab.screenshot(path=str(SHOTS / f'{name}-foundry-process.png'))
                    assert tab.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    context.close()
                assert not failures and not errors and not writes, (failures, errors, writes)
                live = live_check(browser)
                print(json.dumps(dict(isolated_route=base + REVIEW, foundry_route=base + '/foundry?skill=steward-project',
                    content=detail['librarySource'], content_sha256=hashlib.sha256(Path(detail['librarySource']).read_bytes()).hexdigest(),
                    resources=46, nodes=46, steps=40, clicks=clicks,
                    source_warnings=list(dict.fromkeys(detail['libraryIssues'])), failures=failures, errors=errors, writes=writes,
                    screenshots=[p.name for p in SHOTS.glob('*.png')], current_live=live)))
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


if __name__ == '__main__':
    main()

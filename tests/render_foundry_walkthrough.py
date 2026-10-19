"""Inspect the actual Foundry sources in a fresh, isolated worktree server.

Run from the Anchor worktree. Optional FOUNDRY_PAGE_CONTENT_ROOT points at a
read-only Foundry handoff. Captures pixels and exercises real source links;
never reads cockpit events or sends sleep/control POSTs.
"""
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['ANCHOR_DATA_DIR'] = str(ROOT / 'test_tmp_foundry_render')
Path(os.environ['ANCHOR_DATA_DIR']).mkdir(exist_ok=True)
os.environ['TEMP'] = os.environ['ANCHOR_DATA_DIR']
os.environ['TMP'] = os.environ['ANCHOR_DATA_DIR']
os.environ['ANCHOR_PROACTIVE_SUMMARY'] = '0'
os.environ['ANCHOR_PTY_BACKEND'] = 'stub'
os.environ['ANCHOR_ENGINE_CMD'] = f'{sys.executable} -c pass'

import anchor_gui
import foundry_page
from playwright.sync_api import sync_playwright


def main():
    shots = ROOT / 'tests/artifacts/foundry-walkthrough' / os.environ.get('FOUNDRY_RENDER_LABEL', '')
    shots.mkdir(parents=True, exist_ok=True)
    server = anchor_gui.make_server('127.0.0.1', 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    detail = foundry_page.skill_detail('researchprime')
    errors, writes, clicks = [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for width, height, name in [(1440, 1050, 'desktop'), (390, 844, 'phone')]:
                    context = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1)
                    tab = context.new_page()
                    tab.on('pageerror', lambda e: errors.append(str(e)))
                    tab.on('request', lambda r: writes.append(r.url) if r.method != 'GET' else None)
                    tab.goto(base + '/foundry?skill=researchprime')
                    tab.get_by_role('heading', name='researchPrime', exact=True).wait_for()
                    assert tab.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    for img in tab.locator('img').all():
                        assert img.evaluate('(el) => el.complete && el.naturalWidth > 0'), img.get_attribute('src')
                    tab.screenshot(path=str(shots / f'{name}-knowledge.png'), full_page=True)
                    if detail['knowledgeMap']['nodes']:
                        tab.get_by_role('button', name='Concept: A decision-ready answer', exact=True).click()
                        with tab.expect_popup() as popup:
                            tab.get_by_role('link', name='Open Library resource', exact=True).click()
                        popup.value.wait_for_load_state()
                        assert popup.value.locator('.hit').count() == 1
                        clicks.append(popup.value.url)
                        popup.value.screenshot(path=str(shots / f'{name}-source.png'))
                        popup.value.close()
                        tab.get_by_role('button', name='Explore this branch', exact=True).click()
                        tab.get_by_role('button', name='Zoom in', exact=True).click()
                        tab.get_by_role('button', name='Whole map', exact=True).first.click()
                        tab.get_by_role('button', name='Outline', exact=True).click()
                        assert tab.locator('.map-outline').is_visible()
                        tab.get_by_label('Search knowledge map').fill('budget')
                        assert tab.locator('.map-search-results button').count() > 0
                        tab.get_by_label('Search knowledge map').fill('')
                    tab.locator('#process-map > summary').click()
                    if detail['processMap']['steps']:
                        # Verify BOTH real source anchors from the first program.
                        step = tab.locator('.process-step.program').first
                        for link in step.locator('.step-sources a').all():
                            with tab.expect_popup() as popup:
                                link.click()
                            popup.value.wait_for_load_state()
                            assert popup.value.locator('.hit').count() == 1
                            clicks.append(popup.value.url)
                            popup.value.close()
                    tab.locator('#process-map').scroll_into_view_if_needed()
                    tab.screenshot(path=str(shots / f'{name}-process.png'))
                    tab.locator('#library > summary').click()
                    tab.locator('#library').scroll_into_view_if_needed()
                    tab.screenshot(path=str(shots / f'{name}-library.png'))
                    if width < 780:
                        tab.get_by_role('button', name='Skills A–Z', exact=True).click()
                        tab.screenshot(path=str(shots / 'phone-skills.png'))
                    tab.locator('#skill-rail').get_by_role('button', name='Gandalf', exact=False).click()
                    tab.get_by_role('heading', name='Gandalf', exact=True).wait_for()
                    assert tab.get_by_text('Knowledge map unfinished.', exact=False).is_visible()
                    context.close()
                assert not errors, errors
                assert not writes, writes
                print(json.dumps({'route': base + '/foundry?skill=researchprime', 'content': detail['librarySource'],
                                  'resources': len(detail['libraryResources']), 'steps': len(detail['processMap']['steps']),
                                  'nodes': len(detail['knowledgeMap']['nodes']), 'source_clicks': len(clicks),
                                  'screenshots': [p.name for p in shots.glob('*.png')], 'errors': errors, 'writes': writes}))
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


if __name__ == '__main__':
    main()

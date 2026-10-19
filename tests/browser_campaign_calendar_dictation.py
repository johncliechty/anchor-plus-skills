"""Exercise John's Calendar and dictation requests on the running Anchor pages.

Login uses the ordinary page form. Message POSTs are simulated so the check
cannot commission work or change the portfolio. All rendering and interaction
use the live server's HTML, JavaScript and CSS. Requires installed Playwright.
"""
import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def require(condition, description):
    if not condition:
        raise AssertionError(description)


def snapshot_calendar(page):
    return page.evaluate("""() => {
      const lanes = [...document.querySelectorAll('#viewCal .lane')];
      return {
        lanes: lanes.filter(l => getComputedStyle(l).display !== 'none').map(l => ({
          id: l.dataset.lane, area: l.querySelector('.larea').textContent.trim().toLowerCase(),
          columns: [...l.querySelectorAll('.track > .cell')].map(c => c.querySelectorAll('.pc').length)
        })),
        counts: [...document.querySelectorAll('#viewCal .rl-head .cn')].map(n => n.textContent),
        tiers: [...document.querySelectorAll('#viewCal .tierstrip')].map(t => {
          const mine = []; let l = t.nextElementSibling;
          while (l && !l.classList.contains('tierstrip')) {
            if (l.classList.contains('lane') && getComputedStyle(l).display !== 'none') mine.push(l);
            l = l.nextElementSibling;
          }
          return {visible: getComputedStyle(t).display !== 'none', text: t.querySelector('.tm').textContent,
            goals: mine.length, needs: mine.filter(l => l.querySelector('.fl')).length,
            dated: mine.reduce((n,l) => n + Number((l.querySelector('.lmeta').textContent.match(/(\\d+)\\s+dated/) || [0,0])[1]), 0)};
        })
      };
    }""")


def check_calendar(page, output):
    initial = snapshot_calendar(page)
    require(initial['lanes'], 'Live Calendar contains goals to exercise')
    areas = page.locator('.ac[data-area]').evaluate_all('(bs) => bs.map(b => b.dataset.area)')
    tested = []
    # Select in Grouped view, then enter Calendar. Switch directly between all
    # groups before clearing: this catches state which only works on first click.
    for index, area in enumerate(areas):
        page.locator(f'.ac[data-area="{area}"]').click()
        if index == 0:
            page.locator('#viewBtn').click()
        state = snapshot_calendar(page)
        expected = [l for l in initial['lanes'] if l['area'] == area]
        require([l['id'] for l in state['lanes']] == [l['id'] for l in expected], f'{area}: only matching goals appear')
        counts = [sum(l['columns'][k] for l in expected) for k in range(len(state['counts']))]
        for text, count in zip(state['counts'], counts):
            require((text == 'nothing dated' and count == 0) or text.startswith(str(count) + ' '), f'{area}: ruler count {text} agrees with {count} visible parts')
        for tier in state['tiers']:
            require(tier['visible'] == bool(tier['goals']), f'{area}: empty tier is hidden')
            if tier['goals']:
                require(tier['text'].startswith(str(tier['goals']) + ' goal'), f'{area}: tier goal count')
                require(f"{tier['dated']} dated part" in tier['text'], f'{area}: tier open dated count')
                if tier['needs']:
                    require(f"{tier['needs']} goal" in tier['text'].split('·')[1], f'{area}: tier attention count')
        require(page.locator('.calendar-empty').is_visible() == (not expected), f'{area}: truthful empty message')
        require(page.locator(f'.ac[data-area="{area}"]').get_attribute('aria-pressed') == 'true', 'Selected group is exposed to assistive technology')
        require(page.locator('#boardCount').inner_text().startswith(area.title() + ' · ' + str(len(expected)) + ' goal'), f'{area}: board summary describes this group')
        tested.append({'area': area, 'goals': len(expected), 'ruler_parts': counts})
        if area == 'family':
            page.screenshot(path=str(output / 'calendar-family.png'))
    page.locator(f'.ac[data-area="{areas[-1]}"]').click()
    restored = snapshot_calendar(page)
    require(restored == initial, 'Clearing restores all goals, counts and tier headings exactly')
    page.locator('#viewBtn').click()
    require(page.locator('#viewGrouped').is_visible(), 'Grouped view still opens after filtering')
    return tested


def size(box):
    return box.evaluate('(b) => ({height:b.getBoundingClientRect().height, scroll:b.scrollHeight, client:b.clientHeight, overflow:getComputedStyle(b).overflowY})')


def check_composer(page, name, draft_key, output):
    box = page.locator('#say')
    box.fill('')
    baseline = size(box)['height']
    draft = '\n'.join(f'Dictation line {i}: I can read the words as I speak.' for i in range(6))
    box.fill(draft)
    grown = size(box)
    require(grown['height'] > baseline + 40, f'{name}: draft grows beyond empty height')
    require(grown['scroll'] <= grown['client'], f'{name}: moderate draft is fully visible')
    page.screenshot(path=str(output / f'{name}-dictation.png'))
    box.fill('Short draft')
    require(size(box)['height'] <= baseline + 2, f'{name}: deleting text shrinks the box')
    long_draft = draft * 20
    box.fill(long_draft)
    require(size(box)['height'] <= page.viewport_size['height'] * .4 + 1, f'{name}: long draft leaves conversation space')
    require(size(box)['overflow'] == 'auto', f'{name}: long draft can scroll')
    page.set_viewport_size({'width': 1280, 'height': 700})
    page.wait_for_timeout(100)
    require(size(box)['height'] <= 281, f'{name}: viewport resize changes the cap')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    box.fill(draft)
    page.wait_for_timeout(350)  # existing draft-save debounce
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('() => !!(window.StewardDialogue && window.StewardDialogue.fitComposer)')
    require(box.input_value() == draft, f'{name}: reload restores the draft')
    require(size(box)['height'] > baseline + 40, f'{name}: restored draft is sized without another keystroke')
    page.locator('#sendBtn').click()
    page.wait_for_function("document.querySelector('#say').value === ''")
    require(size(box)['height'] <= baseline + 2, f'{name}: successful send returns to empty height')
    require(draft in page.locator('#exList').inner_text(), f'{name}: successful text appears in the dialogue')
    failure = '[UI probe failure]\n' + draft
    box.fill(failure)
    page.locator('#sendBtn').click()
    page.wait_for_function("!document.querySelector('#sendBtn').disabled")
    require(box.input_value() == failure and size(box)['height'] > baseline + 40, f'{name}: failure retains visible draft')
    page.wait_for_timeout(350)
    require(page.evaluate('(key) => localStorage.getItem(key)', draft_key) == failure, f'{name}: failed draft remains saved')
    box.fill('')
    return {'empty_height': baseline, 'six_line_height': grown['height'], 'restore': 'passed', 'success_reset': 'passed', 'failure_preserved': 'passed'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8777')
    parser.add_argument('--pid', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    errors, sends = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.base_url + '/high-seat', wait_until='domcontentloaded')
        token = os.environ.get('ANCHOR_TOKEN')
        # Local trusted entry can already issue the normal auth cookie. Use the
        # visible form only if the server actually asks this browser to log in.
        page.wait_for_timeout(500)
        if token and page.locator('#loginBox').is_visible():
            page.locator('#loginTok').fill(token)
            with page.expect_navigation(wait_until='domcontentloaded'):
                page.locator('#loginGo').click()
        require(not page.locator('#loginBox').is_visible(), 'Ordinary page login succeeded')

        def simulate_send(route):
            payload = route.request.post_data_json
            if route.request.url.endswith('/api/ecgberht/high_seat_say'):
                reply = {'ok': True, 'talk': True}
            else:
                sends.append({'goal': payload.get('goal'), 'failure': payload['text'].startswith('[UI probe failure]')})
                reply = {'ok': False, 'error': 'Simulated failed send'} if sends[-1]['failure'] else {'ok': True, 'read_only': True}
            route.fulfill(status=200, content_type='application/json', body=json.dumps(reply))

        context.route('**/api/steward/say', simulate_send)
        context.route('**/api/ecgberht/high_seat_say', simulate_send)
        page.goto(args.base_url + '/project/' + args.pid, wait_until='domcontentloaded')
        page.locator('#viewBtn').wait_for()
        results = {'calendar': check_calendar(page, args.output_dir)}
        results['campaign'] = check_composer(page, 'campaign', 'anchor:draft:campaign:' + args.pid, args.output_dir)
        # A goal's restored draft was hidden at boot; opening must size it too.
        goal = page.locator('.gsay').first.get_attribute('data-goal')
        goal_key = 'anchor:draft:goal:' + args.pid + ':' + goal
        goal_draft = '\n'.join('Restored goal dictation ' + str(i) for i in range(6))
        page.evaluate('([key,text]) => localStorage.setItem(key,text)', [goal_key, goal_draft])
        page.goto(args.base_url + '/project/' + args.pid, wait_until='domcontentloaded')
        page.locator(f'[data-open="{goal}"]').first.click()
        goal_box = page.locator(f'.gsay[data-goal="{goal}"]')
        require(goal_box.input_value() == goal_draft and size(goal_box)['height'] > 100, 'Opening a hidden goal sizes its restored draft')
        results['hidden_goal_restore'] = 'passed'
        page.goto(args.base_url + '/high-seat', wait_until='domcontentloaded')
        results['cave-of-wonders'] = check_composer(page, 'cave-of-wonders', 'anchor:draft:highseat', args.output_dir)
        seed = page.locator('#seedPanel .go[data-seed-text]').first
        if seed.count():
            page.locator('#seedBtn').click()
            seed.click()
            require(page.locator('#say').input_value().startswith('make '), 'Cave seed fills composer')
            require(size(page.locator('#say'))['scroll'] <= size(page.locator('#say'))['client'], 'Cave seed text fits')
            results['seed_prefill'] = 'passed'
        require(not errors, 'No JavaScript errors: ' + '; '.join(errors))
        require(len(sends) == 4, 'Only four simulated sends; no production messages')
        results.update({'ok': True, 'surface': 'live authenticated Anchor pages', 'message_transport': 'simulated; no work commissioned', 'javascript_errors': errors, 'simulated_sends': len(sends)})
        (args.output_dir / 'receipt.json').write_text(json.dumps(results, indent=2), encoding='utf8')
        print(json.dumps(results, indent=2))
        context.close()
        browser.close()


if __name__ == '__main__':
    main()

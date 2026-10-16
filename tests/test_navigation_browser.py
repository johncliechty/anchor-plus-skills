import json
import re
from pathlib import Path
from playwright.sync_api import expect
from tests.test_steward_refinement_browser import campaign_server, cockpit


def test_legacy_components_current_links_and_persistent_navigation(cockpit):
    page, server = cockpit
    root = server.campaign.parent / 'Navigation project'
    root.mkdir()
    (root/'ECGBERHT.md').write_text('# Navigation project\n\n## North star\nA usable weekly tracker.\n', encoding='utf-8')
    product = {'id': 'tracker', 'name': 'Weekly tracker', 'components': [
        {'id': 'calendar', 'name': 'Calendar'}, {'id': 'strength', 'name': 'Strength log'}]}
    (root/'roadmap.json').write_text(json.dumps({'roadmap_events': [
        {'kind': 'kickoff_proposal', 'proposal_id': 'p1', 'proposal_hash': 'hash1', 'version': 1, 'work_product': product},
        {'kind': 'kickoff_confirm', 'proposal_id': 'p1', 'proposal_hash': 'hash1', 'version': 1}],
        'roadmap_projection': [{'id': 'live', 'name': 'Build tracker', 'status': 'active', 'component_ids': ['calendar', 'strength'], 'navigation': {'current': True}, 'commissioned_as': 'foreman:run-1'},
                               {'id': 'research', 'name': 'Research', 'status': 'active', 'navigation': {'role': 'support'}},
                               {'id': 'later', 'name': 'Field test', 'status': 'parked'}]}), encoding='utf-8')
    register = '| What | Where | Date | Step |\n| --- | --- | --- | --- |\n' + \
        '| START HERE — Working tracker | `current.html` | 2026-09-13 | LIVE |\n' + \
        '| Earlier workbook | `old.html` | 2026-09-12 | live |\n' + \
        '| START HERE: supporting evidence | `support.html` | 2026-09-13 | research |\n' + \
        '| Unassigned reference | `orphan.html` | 2026-09-13 | unresolved |\n' + \
        '| Field notes | `gandalf/notes.md` | 2026-09-12 | unresolved |\n' + \
        '| Gandalf read LITE — INSTALL | `reads/first.md` | 2026-09-12 | unresolved |\n' + \
        '| Chapter 1 manuscript | `chapters/ch1.docx` | 2026-09-13 | live |\n'
    (root/'DELIVERABLES.md').write_text(register, encoding='utf-8')
    (root/'chapters').mkdir(); (root/'chapters'/'ch1.docx').write_bytes(b'PK\x03\x04 not a real document')
    for name in ('current', 'old', 'support', 'orphan'):
        (root/(name+'.html')).write_text('<h1>'+name+' tracker example</h1>', encoding='utf-8')
    (root/'gandalf').mkdir(); (root/'gandalf'/'notes.md').write_text('# notes\n', encoding='utf-8')
    (root/'reads').mkdir(); (root/'reads'/'first.md').write_text('# read\n', encoding='utf-8')
    page.reload()

    def open_surface():
        page.locator('[data-efforts] .efrow').filter(has_text='Navigation project').first.click()
        surface = page.frame_locator('[data-fsframe]')
        expect(surface.locator('[data-say]')).to_be_visible()
        panel = surface.locator('[data-delivmount] .blk.deliv')
        expect(panel).to_be_visible()
        folded = panel.locator(':scope.folded > .who')
        if folded.count(): folded.click()
        expect(panel.locator('.navpin')).to_be_visible()
        return surface, panel

    surface, panel = open_surface()
    nxt = surface.locator('[data-delivmount] .blk.next')                 # the Next steps tile, second in the slot, closed by default (Wave G, 2026-09-24)
    expect(nxt).to_have_class(re.compile(r'\bfolded\b'))
    expect(nxt.locator('.who')).to_contain_text('NEXT STEPS')
    nxt.locator('.who').click()
    donow = nxt.locator('.body')
    expect(donow.locator('.navfile')).to_have_count(1)                   # the current file is the one Open act
    expect(donow).to_contain_text('Working tracker')
    expect(donow).to_contain_text('Next in the plan')
    expect(donow.locator('.action-needed')).to_have_count(1)                # the current question lives in the tile
    expect(surface.locator('.blk.status.latest .sdonow')).to_have_count(0)   # the status report carries no to-do list
    expect(surface.locator('.blk.status.latest .action-needed')).to_have_count(0)   # and no question card
    expect(panel.locator('.navpin')).to_contain_text('Working tracker')            # the pin block lists the current files
    notdone = surface.locator('[data-steps] .notdone')
    notdone.locator('summary').first.click()                                       # closed when a cockpit opens (his word 2026-10-06); a click opens it
    expect(notdone).to_contain_text('Not done \u00b7 1')                            # the pinned step only: the parked and the supporting step are kept out
    expect(notdone).to_contain_text('Parked \u00b7 1 \u00b7 Supporting steps \u00b7 1')
    expect(notdone.locator('.ndhead .mark.now')).to_have_count(1)                  # the one current step carries the now mark
    expect(notdone).to_contain_text('\u25cf now')                                   # and the legend names it
    expect(surface.locator('[data-steps] li[data-step-id="live"] > .mark.now')).to_have_count(1)
    expect(surface.locator('[data-steps] li[data-step-id="live"] .stitle img.skico')).to_have_attribute('alt', 'Foreman')   # the commissioned skill's mark on the step
    expect(panel.locator('details[data-group-id="unclassified"] .navfile img.skico[alt="Gandalf"]')).to_have_count(2)   # from a skill-named folder (Wave I) and from a title naming the skill as a word (Wave J)
    expect(surface.locator('.bar [data-barlead]')).to_have_text(re.compile(r'^(Next|Next not stated)'))   # the status lead on the top line (Wave J)
    expect(surface.locator('.bar [data-busy]')).to_be_empty()                                              # nothing waits and nothing runs: no state word beside the name
    expect(surface.locator('.bar [data-theme-toggle]')).to_have_count(0)                                    # the style button is gone
    expect(surface.locator('[data-steps] .stitle .tw')).to_have_count(0)                                    # no arrow beside the mark
    spend = surface.locator('[data-spend]')
    expect(spend).not_to_contain_text('effort sessions')                            # one total on the line, the parts in the hover (Wave I)
    expect(spend).to_have_text(re.compile(r'^(Total|cost unavailable)'))
    surface.locator('[data-say]').fill('My own note')
    notdone.locator('.ndact').first.click()                                        # "act on" adds a reference to the item after what John typed
    expect(surface.locator('[data-say]')).to_have_value(re.compile(r'^My own note\nAct on: Build tracker'))
    surface.locator('[data-say]').fill('')
    expect(panel.locator('summary').filter(has_text='Approved deliverables · 0')).to_be_visible()
    tracker = panel.locator('details[data-group-id="tracker"]')                    # the deliverables tile is the plan's tree
    expect(tracker.locator('> summary')).to_be_visible()
    expect(panel.locator('summary').filter(has_text='Sections and deliverables')).to_have_count(0)
    tracker.locator('> summary').click()
    calendar = tracker.locator('details[data-group-id="calendar"]')                # the section sits inside its group
    calendar.locator('> summary').click()
    expect(calendar).to_have_attribute('open', '')
    calendar.locator('summary').filter(has_text='Shared work and deliverables').click()
    expect(calendar.locator('.navfilelink a').first).to_be_visible()
    expect(calendar).to_contain_text('Working tracker')
    expect(calendar).to_contain_text('Earlier workbook')
    word = calendar.locator('a[href^="ms-word:ofe|u|file:///"]')                   # (Wave D0) one click opens the manuscript in desktop Word
    expect(word).to_have_count(1)
    href = word.first.get_attribute('href')
    assert href.endswith('/Navigation%20project/chapters/ch1.docx') and '%3A' not in href   # the drive letter's colon stays literal
    expect(calendar.locator('.nav-accept')).to_have_count(0)
    with page.expect_popup() as opened:
        donow.locator('.navfilelink a').first.click()
    popup = opened.value
    popup.wait_for_load_state('domcontentloaded')
    assert 'current tracker example' in popup.content()
    popup.close()
    # Change the register to force its periodic repaint, without changing ownership.
    (root/'DELIVERABLES.md').write_text(register.replace('Earlier workbook', 'Earlier workbook retained'), encoding='utf-8')
    expect(panel.locator('details[data-group-id="calendar"]')).to_contain_text('Earlier workbook retained', timeout=20000)
    expect(panel.locator('details[data-group-id="calendar"]')).to_have_attribute('open', '')   # the open group survives the repaint
    expect(surface.locator('[data-say]')).to_be_visible()
    page.reload()
    surface, panel = open_surface()
    expect(panel.locator('details[data-group-id="calendar"]')).to_have_attribute('open', '')   # and the reload
    panel.locator('details[data-group-id="unclassified"] > summary').click()
    expect(panel.locator('details[data-group-id="unclassified"]')).to_contain_text('Unassigned reference')
    assert not (root/'Finished Deliverables').exists()


def test_empty_campaign_uses_same_panel_order(cockpit):
    page, server = cockpit
    root = server.campaign.parent / 'Empty campaign'
    root.mkdir()
    (root/'ECGBERHT.md').write_text('# Empty campaign\n\n## North star\nNo plan confirmed yet.\n', encoding='utf-8')
    (root/'roadmap.json').write_text('{"roadmap_events":[],"roadmap_projection":[]}', encoding='utf-8')
    page.reload()
    page.locator('[data-efforts] .efrow').filter(has_text='Empty campaign').first.click()
    surface = page.frame_locator('[data-fsframe]')
    expect(surface.locator('[data-say]')).to_be_visible()
    panel = surface.locator('[data-delivmount] .blk.deliv')
    expect(panel).to_be_visible()
    folded = panel.locator(':scope.folded > .who')
    if folded.count(): folded.click()
    expect(panel.locator('.navpin')).to_contain_text('No files awaiting review.')
    nxt = surface.locator('[data-delivmount] .blk.next')
    expect(nxt.locator('.who')).to_contain_text('nothing waits on you')
    nxt.locator('.who').click()
    expect(nxt.locator('.body')).to_contain_text('Nothing waits on you.')
    expect(panel.locator('summary').filter(has_text='Approved deliverables · 0')).to_be_visible()
    expect(panel.locator('details[data-group-id="compat-root"] > summary')).to_be_visible()
    expect(surface.locator('[data-steps] .navgroup > summary').first).to_contain_text('Empty campaign')
    order = panel.locator('.body').evaluate("e=>[...e.children].map(c=>c.className)")
    assert order.index('navpin') < order.index('navgroup')                        # current work, approved, then the tree


def test_a_waiting_current_step_keeps_the_flag_and_says_now(cockpit):
    page, server = cockpit
    root = server.campaign.parent / 'Waiting campaign'
    root.mkdir()
    (root/'ECGBERHT.md').write_text('# Waiting campaign\n\n## North star\nOne read.\n', encoding='utf-8')
    (root/'roadmap.json').write_text(json.dumps({'roadmap_events': [], 'roadmap_projection': [
        {'id': 'read', 'name': 'John reads the draft', 'status': 'waiting', 'waiting_on': 'your read', 'navigation': {'current': True}},
        {'id': 'next', 'name': 'Fold the notes in', 'status': 'proposed'}]}), encoding='utf-8')
    page.reload()
    page.locator('[data-efforts] .efrow').filter(has_text='Waiting campaign').first.click()
    surface = page.frame_locator('[data-fsframe]')
    expect(surface.locator('[data-say]')).to_be_visible()
    notdone = surface.locator('[data-steps] .notdone')
    expect(notdone).to_contain_text('Not done \u00b7 2')
    expect(notdone.locator('.ndwait > summary').first).to_have_text('now \u00b7 waiting on you')   # the flag wins the mark; the word says now
    expect(surface.locator('[data-steps] .mark.now')).to_have_count(0)
    expect(surface.locator('[data-steps] li[data-step-id="read"] > .mark.flag')).to_have_count(1)

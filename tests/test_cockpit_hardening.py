"""Post-review hardening on ordinary authenticated browser surfaces."""
import re
from playwright.sync_api import expect
from tests.test_steward_refinement_browser import campaign_server, cockpit, _state
from tests.test_cockpit_selected_b import navigation, open_surface


def test_transient_projection_warning_rechecks_without_new_roadmap_event(cockpit):
    page,server=cockpit
    reads=[]
    def map_response(route):
        response=route.fetch();data=response.json();reads.append(data['stamp'])
        if len(reads)==1:
            data['refinement']['consistent']=False
            data['gaps']=['Refinement views need repair: projection-lag']
        route.fulfill(response=response,json=data)
    page.route('**/api/steward/map?*',map_response)
    surface=open_surface(page)
    gaps=surface.locator('[data-gaps]')
    expect(gaps).not_to_contain_text('Refinement views need repair',timeout=15000)
    assert len(reads)>=2 and reads[0]==reads[1]


def test_compact_now_tracks_live_activity_without_retimestamping_summary(cockpit):
    import json
    page,server=cockpit
    mode={'busy':False}
    def state(route):
        response=route.fetch();data=response.json()
        data.update(busy=mode['busy'],working_bg=False,queued=0,light='green' if mode['busy'] else 'orange')
        route.fulfill(response=response,json=data)
    page.route('**/api/steward/state?*',state)
    surface=open_surface(page)
    live=surface.locator('.blk.status.latest [data-live-activity]')
    expect(live).to_have_text('Needs your input',timeout=15000)
    expect(surface.locator('.status-compact .stab')).to_be_visible()
    expect(surface.locator('.status-compact th').filter(has_text='Doing')).to_be_visible()
    stamp=surface.locator('[data-statusstamp]').inner_text()
    mode['busy']=True
    expect(live).to_have_text('Working',timeout=15000)
    expect(surface.locator('[data-light]')).to_have_class('light green')
    assert surface.locator('[data-statusstamp]').inner_text()==stamp
    mode['busy']=False
    expect(live).to_have_text('Needs your input',timeout=15000)
    assert surface.locator('[data-statusstamp]').inner_text()==stamp


def test_unorganized_campaign_still_exposes_current_and_approved(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    panel = surface.locator('[data-delivmount]')
    expect(panel.locator('.navpin')).to_contain_text('guide')
    expect(panel.locator('summary').filter(has_text='Approved deliverables')).to_be_visible()
    expect(surface.locator('[data-steps] .navpin')).to_have_count(0)


def test_saved_original_exchange_opens_without_answering(cockpit):
    from steward_cockpit import steward_routes
    from steward_cockpit.question_context import save_question_context
    from steward_cockpit.conversation_history import append_turn
    page, server = cockpit
    navigation(server)
    engine = steward_routes.get_engine(str(server.campaign))
    request = _state(server)['pending_request']
    append_turn(str(server.campaign), 'john', 'Explain the effect on the report first.', turn_id='context-human')
    append_turn(str(server.campaign), 'steward', 'The report will reuse this guide. Shall we keep it?', turn_id='context-steward')
    engine.question_context = save_question_context('Shall we keep it?', 'The report will reuse this guide. Shall we keep it?',
        asked_at='2026-09-11T21:00:00Z', source_ref='Cockpit conversation context-steward',
        scope={'request_id': request['id'], 'presentation_id':'p1', 'step_id':'foundation', 'source_turn_id':'context-steward'})
    surface = open_surface(page)
    tile = surface.locator('[data-openq]')
    expect(tile).to_contain_text('Action needed')
    tile.click()
    expect(tile).to_have_class(re.compile(r'\bopen\b'))
    dialog = tile.locator('[data-question-dialog]')
    dialog.get_by_role('button', name='Original exchange', exact=True).click()
    expect(dialog).to_contain_text('Explain the effect on the report first.')
    assert _state(server)['pending_request']['id'] == request['id']
    assert not engine.question_history


def test_action_needed_close_collapses_so_john_can_type(cockpit):
    from steward_cockpit import steward_routes
    from steward_cockpit.question_context import save_question_context
    page, server = cockpit
    navigation(server)
    engine = steward_routes.get_engine(str(server.campaign))
    request = _state(server)['pending_request']
    engine.question_context = save_question_context(
        'Shall we keep it?',
        'I recommend keeping the current guide.\nShall we keep it?',
        asked_at='2026-09-11T21:00:00Z', source_ref='Cockpit conversation',
        scope={'request_id': request['id'], 'presentation_id':'p1', 'step_id':'foundation'})
    surface = open_surface(page)
    tile = surface.locator('[data-openq]')
    tile.click()
    expect(tile).to_have_class(re.compile(r'\bopen\b'))
    expect(tile.get_by_role('button', name='Accept recommendation', exact=True)).to_be_visible()
    tile.get_by_role('button', name='Close decision details', exact=True).click()
    expect(tile).not_to_have_class(re.compile(r'\bopen\b'))
    expect(surface.locator('[data-say]')).to_be_focused()
    assert _state(server)['pending_request']['id'] == request['id']


def test_accept_recommendation_sends_the_saved_choice(cockpit):
    import json
    from steward_cockpit import steward_routes
    from steward_cockpit.question_context import save_question_context
    page, server = cockpit
    navigation(server)
    engine = steward_routes.get_engine(str(server.campaign))
    request = _state(server)['pending_request']
    saved = save_question_context(
        'Shall we keep it?',
        'I recommend keeping the current guide.\nShall we keep it?',
        asked_at='2026-09-11T21:00:00Z', source_ref='Cockpit conversation',
        scope={'request_id': request['id'], 'presentation_id':'p1', 'step_id':'foundation'})
    engine.question_context = saved
    surface = open_surface(page)
    posted = []
    def respond(route):
        posted.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True}))
    page.route('**/api/steward/say?*', respond)
    tile = surface.locator('[data-openq]')
    expect(surface.locator('.bar [data-busy]')).to_contain_text('need your input')   # the state word beside the name while a question is open (Wave J)
    tile.click()
    tile.get_by_role('button', name='Accept recommendation', exact=True).click()
    expect(tile).not_to_have_class(re.compile(r'\bopen\b'), timeout=5000)
    assert posted and posted[0]['question_id'] == saved['id']
    assert 'keeping the current guide' in posted[0]['text']


def test_choose_sends_the_alternative_as_the_answer(cockpit):
    import json
    from steward_cockpit import steward_routes
    from steward_cockpit.question_context import save_question_context
    page, server = cockpit
    navigation(server)
    engine = steward_routes.get_engine(str(server.campaign))
    request = _state(server)['pending_request']
    saved = save_question_context(
        'Shall we keep it?',
        'I recommend keeping the current guide.\n- Rebuild from the outline: a day more.\nShall we keep it?',
        asked_at='2026-09-24T18:00:00Z', source_ref='Cockpit conversation',
        scope={'request_id': request['id'], 'presentation_id':'p1', 'step_id':'foundation'})
    engine.question_context = saved
    surface = open_surface(page)
    posted = []
    def respond(route):
        posted.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True}))
    page.route('**/api/steward/say?*', respond)
    tile = surface.locator('[data-openq]')
    tile.click()
    tile.get_by_role('button', name='Choose', exact=True).click()                 # the alternative is an equal button (Wave H)
    expect(tile).not_to_have_class(re.compile(r'\bopen\b'), timeout=5000)
    assert posted and posted[0]['question_id'] == saved['id']
    assert posted[0]['text'] == 'Alternative: Rebuild from the outline: a day more.'


def test_side_panel_expansion_preserves_conversation_at_laptop_width(cockpit):
    page, server = cockpit
    navigation(server)
    surface = open_surface(page)
    # 2026-10-07 (PROPOSAL v1.1, evidence E6): a laptop-width cockpit closes the plan rail and the status pane for
    # now (never in his preferences); he opens the rail himself, and it overlays instead of squeezing the dialogue
    page.set_viewport_size({'width':1024, 'height':768})
    surface.locator('[data-railtoggle2]').click()
    grip = surface.locator('[data-plangrip]')
    grip.focus()
    for _ in range(25): grip.press('ArrowRight')
    main = surface.locator('.main')
    assert main.bounding_box()['width'] >= 320
    expect(surface.locator('[data-say]')).to_be_visible()
    assert surface.locator('body').evaluate('(e)=>e.scrollWidth <= innerWidth')


def test_failed_scoped_answer_does_not_poison_later_composer_messages(cockpit):
    import json
    page,server=cockpit
    navigation(server);surface=open_surface(page)
    surface.locator('[data-openq]').click()
    surface.locator('[data-question-dialog]').get_by_role('button',name='Answer this question',exact=True).click()
    posted=[]
    def respond(route):
        posted.append(route.request.post_data_json)
        route.fulfill(status=409 if len(posted)==1 else 200,content_type='application/json',
            body=json.dumps({'ok':len(posted)>1,'error':'question-is-no-longer-current'}))
    page.route('**/api/steward/say?*',respond)
    surface.locator('[data-say]').fill('Yes')
    surface.locator('[data-send]').click()
    expect(surface.locator('[data-say]')).to_have_value('Yes')
    surface.locator('[data-say]').fill('Explain the current draft.')
    surface.locator('[data-send]').click()
    expect(surface.locator('[data-say]')).to_have_value('')
    assert len(posted)==2 and posted[0]['question_id']
    assert posted[1]['question_id'] is None


def test_real_client_keeps_committed_approval_when_finished_copy_conflicts(cockpit):
    page,server=cockpit
    navigation(server)
    target=server.campaign/'Finished Deliverables/Block 1/Lecture 2/guide.html'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text('User-owned unrelated file',encoding='utf-8')
    surface=open_surface(page)
    nxt=surface.locator('[data-delivmount] .blk.next')                              # the Review act sits in the Next steps tile (Wave G)
    if nxt.locator(':scope.folded').count(): nxt.locator('.who').click()
    row=nxt.locator('[data-product-id="guide"]')
    with page.expect_response(lambda r:'/refinement-accept' in r.url and r.request.method=='POST') as response:
        row.get_by_role('button',name='Done with this item',exact=True).click()
    result=response.value.json()
    assert response.value.ok and result['ok'] and result['committed']
    assert result['consistent'] is False and 'saved' in result['warning']
    state=_state(server)
    assert len(state['slices']['foundation']['acceptance_history'])==1
    assert state['slices']['foundation']['phase']=='done'
    assert target.read_text(encoding='utf-8')=='User-owned unrelated file'
    expect(surface.locator('[data-delivmount]')).to_contain_text('Finished Deliverables needs repair')

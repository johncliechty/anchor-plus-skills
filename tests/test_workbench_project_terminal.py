import json
from types import SimpleNamespace
from urllib.parse import urlencode
from playwright.sync_api import expect
from tests.test_steward_refinement_browser import campaign_server, cockpit


def test_project_workbench_open_retry_and_registered_terminal_routes(cockpit, monkeypatch):
    page, server = cockpit
    root = server.campaign.parent
    assert not (root/'ECGBERHT.md').exists()
    page.locator('[data-tile-wb] .thead').click()
    plus = page.get_by_role('button', name='＋ Terminal', exact=True)
    expect(plus).to_be_visible()
    blocked = '**/api/steward/term_new?**'
    page.route(blocked, lambda route: route.fulfill(status=503,content_type='application/json',body='{"ok":false,"error":"Temporary launch failure"}'))
    plus.click()
    expect(page.locator('[data-terminal-error]')).to_contain_text('Temporary launch failure')
    expect(plus).to_be_enabled()
    assert not (root/'.anchor/steward-terms.json').exists()
    page.unroute(blocked)
    with page.expect_response(lambda r:'/api/steward/term_new?' in r.url) as created:
        plus.click()
    assert created.value.ok
    tid = created.value.json()['tid']
    frame = page.frame_locator('.dmain iframe.on')
    expect(frame.locator('[data-say]')).to_be_visible()
    expect(frame.locator('[data-name]')).to_contain_text('workbench terminal')
    expect(frame.locator('select option[value="chatgpt"]')).to_have_count(1)
    terms = json.loads((root/'.anchor/steward-terms.json').read_text(encoding='utf-8'))
    assert list(terms) == [tid], 'Retry must not create duplicate terminals'

    def url(verb, **extra):
        return server.origin+'/api/steward/'+verb+'?'+urlencode({'pid':server.project_id,'dir':'','general':'1','term':tid,**extra})
    def post(verb, body):
        result = page.evaluate("""async ({verb,body})=>{const r=await fetch('/api/'+verb,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {ok:r.ok,status:r.status};}""", {'verb':verb,'body':body})
        return SimpleNamespace(**result)
    for verb in ('map','state','history','deliverables'):
        response=page.request.get(url(verb))
        assert response.ok,(verb,response.status,response.text())
    from steward_cockpit import steward_routes as routes
    engine = routes.get_engine(str(root),True,tid,create=False)
    assert engine is not None and engine.general
    delivered=[]
    monkeypatch.setattr(engine,'say',lambda text: delivered.append(text) or {'ok':True})
    response=post('say', {'pid':server.project_id,'dir':'','general':True,'term':tid,'text':'Test terminal input'})
    assert response.ok and delivered==['Test terminal input']
    monkeypatch.setattr(engine,'events_since',lambda since,timeout: ([],0,False))
    assert page.request.get(url('events',since='0')).ok
    for verb in ('map','history','state','events'):
        assert page.request.get(url(verb,term='999999')).status==404
    assert post('say', {'pid':server.project_id,'dir':'','general':True,'term':'999999','text':'Must not deliver'}).status==404
    assert delivered==['Test terminal input']
    # General terminal privileges cannot route a campaign mutation at a faceless root.
    assert post('refinement-update', {'pid':server.project_id,'dir':'','general':True,'term':tid}).status==404
    assert page.request.get(server.origin+'/api/steward/map?'+urlencode({'pid':server.project_id,'dir':'../'})).status==404
    for action in ('term_archive','term_restore'):
        r=post(action, {'pid':server.project_id,'dir':'','tid':tid})
        assert r.ok
        if action=='term_archive': assert page.request.get(url('state')).status==404
    assert page.request.get(url('state')).ok
    # The independently managed campaign still has its original presentation.
    from tests.test_steward_refinement_browser import _state
    assert _state(server)['slices']['foundation']['acceptance_history']==[]


def test_terminal_save_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    import pytest
    from steward_cockpit import steward_routes as routes
    monkeypatch.setattr(routes.os, 'replace', lambda *args: (_ for _ in ()).throw(PermissionError('Synthetic save failure')))
    with pytest.raises(PermissionError):
        routes.api_post(str(tmp_path),'term_new',{'dir':''})
    assert not (tmp_path/'.anchor/steward-terms.json').exists()

"""Selected B through real authenticated Anchor routes; production seats are fake."""
import hashlib
import json
import re
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
from urllib.parse import urlencode

from playwright.sync_api import expect
from tests.test_steward_refinement_browser import campaign_server, cockpit, _state
from steward_cockpit import refinement_client


def navigation(server):
    ecg = Path(refinement_client.__file__).resolve().parents[2] / 'ecgberht'
    code = '''import {appendRoadmapEventThroughSpine as append} from %s;
    const root=process.argv[1];
    const groups=[{id:'block1',label:'Block 1',order:1,parent_id:null},
      {id:'lecture2',label:'Lecture 2',order:1,parent_id:'block1'},
      {id:'block2',label:'Block 2',order:2,parent_id:null}];
    for(const [id,nav] of [['foundation',{path:['block1','lecture2'],groups,role:'primary',pin:true}],
      ['independent',{path:['block1'],role:'primary'}],['report',{path:['block2'],role:'primary'}]]) {
      const r=append(root,{kind:'step_set',step_id:id,fields:{navigation:nav}},{skip_index:true});
      if(!r.ok)throw Error(JSON.stringify(r));
    }''' % json.dumps((ecg / 'engine/ledger-spine.mjs').as_uri())
    subprocess.run(['node', '--input-type=module', '-e', code, str(server.campaign)],
                   check=True, capture_output=True, timeout=30)


def endpoint(server, verb):
    return server.origin + '/api/steward/' + verb + '?' + urlencode({'pid': server.project_id, 'dir':server.campaign.name})


def open_surface(page):
    page.locator('[data-efforts] .efrow').filter(has_text='foundation campaign').first.click()
    surface=page.frame_locator('[data-fsframe]')
    expect(surface.locator('[data-say]')).to_be_visible()
    expect(surface.locator('[data-delivmount] .blk.deliv')).to_be_visible()
    folded=surface.locator('[data-delivmount] .blk.deliv.folded > .who')
    if folded.count(): folded.click()
    expect(surface.locator('[data-delivmount] .blk.deliv')).not_to_have_class(re.compile(r'\bfolded\b'))
    expect(surface.locator('[data-delivmount] .navpin')).to_be_visible()
    return surface


def test_managed_current_link_records_view_and_opens_in_nested_effort(cockpit):
    page,server=cockpit
    surface=open_surface(page)
    row=surface.locator('[data-delivmount] .navpin [data-product-id="guide"]')
    with page.expect_response(lambda r:'/refinement-open' in r.url and r.request.method=='POST') as response:
        with page.expect_popup() as opened:
            row.locator('.navfilelink a').first.click()
    result=response.value.json()
    assert response.value.ok and result.get('ok'),result
    popup=opened.value
    popup.wait_for_url(re.compile(r'^http'),wait_until='domcontentloaded')
    assert 'guide' in popup.content().lower()
    assert _state(server)['slices']['foundation']['acceptance_history']==[]
    popup.close()


def test_managed_current_link_opens_when_view_recording_fails(cockpit, monkeypatch):
    from steward_cockpit import refinement_client
    monkeypatch.setattr(refinement_client, 'update', lambda *args, **kwargs: {
        'ok': False, 'error': 'dependency-slow-or-killed',
        'message': 'The refinement CLI exceeded its time limit.'})
    page,server=cockpit
    surface=open_surface(page)
    row=surface.locator('[data-delivmount] .navpin [data-product-id="guide"]')
    with page.expect_popup() as opened:
        row.locator('.navfilelink a').first.click()
    popup=opened.value
    popup.wait_for_url(re.compile(r'^http'),wait_until='domcontentloaded')
    assert 'guide' in popup.content().lower()
    expect(row.locator('[data-view-record-miss]')).to_contain_text('Opened the file')
    popup.close()


def test_selected_b_individual_approval_retains_approved_copy_during_revision(cockpit):
    page,server=cockpit
    navigation(server)
    surface=open_surface(page)
    expect(surface.locator('[data-steps] .navpin')).to_have_count(0)
    panel=surface.locator('[data-delivmount]')
    expect(panel.locator('.navpin')).to_contain_text('Current work and review')
    approved=panel.locator('details').filter(has=surface.locator('summary',has_text='Approved deliverables')).first
    expect(approved).to_contain_text('Approved deliverables · 0')
    panel.locator('details[data-group-id="block2"] > summary').click()
    expect(panel.locator('details[data-group-id="block2"]')).to_have_attribute('open', '')
    nxt=surface.locator('[data-delivmount] .blk.next')                              # the Review act sits in the Next steps tile (Wave G)
    if nxt.locator(':scope.folded').count(): nxt.locator('.who').click()
    row=nxt.locator('[data-product-id="guide"]')
    with page.expect_response(lambda r:'/refinement-accept' in r.url and r.request.method=='POST') as result:
        row.get_by_role('button',name='Done with this item').click()
    assert result.value.ok
    assert _state(server)['slices']['foundation']['phase']=='done'
    expect(approved).to_contain_text('Approved deliverables · 1')
    # Another required part is unfinished: approving the guide does not finish Block 1.
    expect(panel.locator('details[data-group-id="block1"] > summary .plan-mark')).not_to_have_class(re.compile(r'\bdone\b'))
    index=json.loads((server.campaign/'Finished Deliverables/index.json').read_text(encoding='utf-8'))
    saved=server.campaign/'Finished Deliverables'/index['files'][0]['path']
    before=saved.read_bytes()
    current=refinement_client.read_state(server.campaign)
    result=refinement_client.update(server.campaign,{'action':'feedback','operation_id':'b-reopen',
        'expected_seq':current['sequence'],'step_id':'foundation','feedback_id':'b-feedback',
        'source_message':'Preserve the working explanation and improve the example.','base_presentation_id':'p1',
        'changes':[{'id':'better-example','scope':'slice','directive':'require','text':'Improve the example.'}],
        'elegance':{'mode':'RC6','source':'browser fixture user feedback','reason':'Refine the same guide.'}})
    assert result['ok'],result
    page.reload();surface=open_surface(page);panel=surface.locator('[data-delivmount]')
    expect(panel.locator('.navpin')).to_contain_text('guide')
    expect(panel.locator('summary').filter(has_text='Approved deliverables · 1')).to_be_visible()
    assert saved.read_bytes()==before
    assert _state(server)['slices']['foundation']['phase']=='revising'
    expect(surface.locator('[data-say]')).to_be_visible()


def test_saved_question_window_has_literal_context_and_refuses_stale_reply(cockpit):
    page,server=cockpit
    navigation(server)
    from steward_cockpit import steward_routes
    from steward_cockpit.question_context import save_question_context
    engine=steward_routes.get_engine(str(server.campaign))
    request=_state(server)['pending_request']
    question='Keep this exact guide as the foundation?'
    context='The guide will be reused by the report. I recommend keeping this version.\n'+question+'\n<img src=x onerror=alert(1)>'
    engine.question_context=save_question_context(question,context,asked_at='2026-09-11T19:00:00Z',
        source_ref='Original exchange test-turn',scope={'request_id':request['id'],'step_id':'foundation','presentation_id':'p1'})
    surface=open_surface(page)
    expect(surface.locator('[data-openq]')).to_contain_text(question)
    surface.locator('[data-openq]').click()
    dialog=surface.locator('[data-question-dialog]')
    expect(dialog).to_be_visible();expect(dialog).to_contain_text(context)
    expect(dialog.locator('img')).to_have_count(0)
    question_id=engine.state()['question_context']['id']
    response=surface.locator('body').evaluate('''async (el,body)=>{const r=await fetch('/api/refinement-close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {ok:r.ok,status:r.status};}''',
        {'dir':server.campaign.name,'step_id':'foundation','presentation_id':'p1'})
    assert response['ok'],response
    stale=surface.locator('body').evaluate('''async (el,body)=>{const r=await fetch('/api/say',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.status;}''',
        {'dir':server.campaign.name,'text':'Yes','question_id':question_id})
    assert stale==409
    assert _state(server)['slices']['foundation']['closed_presentation']=='p1'
    dialog.get_by_role('button',name='Close',exact=True).click()
    expect(dialog).to_have_count(0)


def test_current_powerpoint_opens_bound_pdf_and_download_remains_original(cockpit):
    page,server=cockpit
    root=server.campaign
    # Registration is sourced metadata; opening grants no acceptance.
    deck=root/'deck.pptx';deck.write_bytes(b'PK fixture deck bytes')
    pdf=root/'slides.pdf';pdf.write_bytes(b'%PDF-1.4\nfixture same-version slides')
    source_hash=hashlib.sha256(deck.read_bytes()).hexdigest()
    def update(operation):
        current=refinement_client.read_state(root)
        result=refinement_client.update(root,dict(operation,operation_id='preview-'+operation['action'],expected_seq=current['sequence']))
        assert result['ok'],result
    full={'mode':'full','source':'Browser companion fixture',
          'assessments':{k:'Proves the requested contained same-version preview.' for k in
                         ['RC-1','RC-2','RC-3','RC-4','RC-5','RC-6','RC-7','RC-8','RC-G']}}
    update({'action':'open_slice','step_id':'independent','title':'Presentation','product_ids':['deck'],'depends_on':[],'elegance':full})
    update({'action':'publish','step_id':'independent','products':[{'product_id':'deck','revision_id':'deck-v1',
            'source_path':'deck.pptx','parent_revision_id':None}],
            'elegance':{'mode':'RC6','source':'Browser fixture','reason':'Deliver the selected slide version.'}})
    update({'action':'visual_companion','step_id':'independent','revision_id':'deck-v1','source_hash':source_hash,
            'preview_source_path':'slides.pdf','evidence':'Fixture companion produced with this source revision.'})
    url=endpoint(server,'deliverable-file')+'&'+urlencode({'path':'deck.pptx','hash':source_hash,'view':1})
    viewed=page.request.get(url)
    assert viewed.ok and viewed.headers['content-type'].startswith('application/pdf')
    assert viewed.body()==pdf.read_bytes()
    downloaded=page.request.get(url+'&download=1')
    assert downloaded.ok and downloaded.body()==deck.read_bytes()
    current=refinement_client.read_state(root)
    binding=current['state']['slices']['independent']['revisions']['deck-v1']['visual_companion']
    (root/binding['path']).write_bytes(b'%PDF-tampered')
    assert page.request.get(url).status==409


def test_shared_indicators_and_latest_compact_status_are_visible(cockpit):
    page,server=cockpit
    navigation(server)
    surface=open_surface(page)
    from steward_cockpit import steward_routes,steward_campaign
    engine=steward_routes.get_engine(str(server.campaign))
    for color,busy,broken in [('orange',False,False),('green',True,False),('red',False,True)]:
        engine.proc=SimpleNamespace(poll=lambda:None)
        engine.busy=busy;engine.broken=broken;engine.last_output=time.time();engine.woke_at=time.time()
        for selector in ['[data-att]','[data-light]','[data-light2]']:
            expect(surface.locator(selector)).to_have_class(re.compile(r'\b'+color+r'\b'),timeout=12000)
        assert len(surface.locator('[data-statetext]').inner_text().split())<=3
        expect(surface.locator('[data-openq]')).to_contain_text('Action needed')
    engine.broken=False;engine.busy=False;engine.proc=None
    for stamp in ['2001-01-01 10:10','2001-01-01 10:20']:
        status=steward_campaign.compose_status(str(server.campaign),engine.state())
        status['at']=stamp
        engine._emit({'t':'status','status':status})
    expect(surface.locator('[data-statusstamp]')).to_contain_text('10:20',timeout=15000)
    latest=surface.locator('[data-pstatus] .blk.status.latest')
    expect(latest.locator('.status-compact')).to_be_visible()
    expect(latest.locator('.status-compact .stab')).to_be_visible()
    for label in ('Summary','Effort','Doing','Status','Tests','Blocker','Procs','Journal','ETA','To do'):
        expect(latest.locator('.status-compact th').filter(has_text=label)).to_be_visible()
    expect(latest.locator('.status-details')).to_have_count(0)
    assert latest.evaluate('(el)=>el.parentElement.firstElementChild===el')
    surface.locator('body').screenshot(path=str(Path(__file__).resolve().parents[3]/'test-runs/selected-b-desktop.png'))
    current=refinement_client.read_state(server.campaign)
    result=refinement_client.update(server.campaign,{'action':'close','operation_id':'indicator-close',
        'expected_seq':current['sequence'],'step_id':'foundation','presentation_id':'p1',
        'human':{'explicit':True,'source_message':'Fixture user closes the named presentation.'}})
    assert result['ok'],result
    expect(surface.locator('[data-light]')).to_have_class(re.compile(r'\bquiet\b'),timeout=12000)
    expect(surface.locator('[data-att]')).to_have_class(re.compile(r'\bquiet\b'))

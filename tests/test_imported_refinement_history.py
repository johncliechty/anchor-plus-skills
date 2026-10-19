from steward_cockpit.steward_campaign import refinement_items


def fixture():
    revisions={f'r{i}':{'product_id':'deck','revision_id':f'r{i}','path':f'deliverables/deck/{i}.pdf',
        'hash':str(i)*64,'at':f'2026-09-11T1{i}:00:00Z',
        'source_history':{'iteration':i,'at':f'2026-09-10T1{i}:00:00Z','source':f'Original revision {i}'}}
        for i in range(3)}
    return {'slices':{'lecture':{'candidate':{'deck':'r2'},'revisions':revisions,'round':0,
        'phase':'waiting_foundation','presentations':[]}}}


def test_imported_r2_keeps_its_name_and_two_earlier_versions_without_fake_handbacks():
    state=fixture();item=refinement_items('',state)[0]
    assert item['round']==2
    assert [x['what'] for x in item['history']]==['Initial draft','Refinement 1']
    assert not state['slices']['lecture']['presentations']


def test_native_feedback_continues_after_the_imported_iteration_number():
    state=fixture();sl=state['slices']['lecture']
    sl['presentations']=[{'id':'p0','round':0,'at':'2026-09-11T19:00:00Z','members':[sl['revisions']['r2']]}]
    sl['round']=1;sl['candidate']['deck']='r3'
    sl['revisions']['r3']={'product_id':'deck','revision_id':'r3','path':'deliverables/deck/3.pdf','hash':'3'*64,'at':'2026-09-11T20:00:00Z'}
    item=refinement_items('',state)[0]
    assert item['round']==3
    assert {x['what'] for x in item['history']}=={'Initial draft','Refinement 1','Refinement 2'}


def test_first_native_handback_of_a_new_revision_does_not_renumber_it_initial():
    state=fixture();sl=state['slices']['lecture'];sl['candidate']['deck']='r3'
    sl['revisions']['r3']={'product_id':'deck','revision_id':'r3','path':'deliverables/deck/3.pdf','hash':'3'*64}
    sl['presentations']=[{'id':'p0','round':0,'members':[sl['revisions']['r3']]}]
    assert refinement_items('',state)[0]['round']==3

"""Saved questions survive engine pickup and replies keep their exact scope."""
from tests.test_usage_checkpoint_engine import cockpit
from steward_cockpit import steward_engine as engine_mod


def finish(engine,text):
    engine.turn_text=text
    engine._handle({'type':'result','total_cost_usd':0.0,'duration_ms':1,'usage':{}},engine.proc)


def test_question_saved_at_result_survives_restart_with_full_context(cockpit,monkeypatch):
    monkeypatch.setattr(cockpit,'_attention',lambda:{'state':'quiet'})
    text='The shared method changes every block.\nI recommend solving it once.\nShould we use one shared method?'
    finish(cockpit,text)
    saved=cockpit.state()['question_context']
    assert saved['question']=='Should we use one shared method?'
    assert saved['context']==text
    assert saved['recommendation']=='I recommend solving it once.'
    restarted=engine_mod.Engine(cockpit.dir,fake=True)
    monkeypatch.setattr(restarted,'_attention',lambda:{'state':'quiet'})
    assert restarted.state()['question_context']==saved


def test_answer_context_is_saved_and_delivered_without_minting_acceptance(cockpit,monkeypatch):
    monkeypatch.setattr(cockpit,'_attention',lambda:{'state':'quiet'})
    finish(cockpit,'This affects the plan.\nI recommend one shared method.\nUse one shared method?')
    saved=cockpit.state()['question_context'];sent=[]
    monkeypatch.setattr(cockpit,'_send_locked',lambda text,**kw:(sent.append(text),True)[1])
    assert cockpit.say('Yes',question_id=saved['id'])['ok']
    assert len(sent)==1 and saved['question'] in sent[0]
    assert 'not automatic acceptance' in sent[0]
    assert cockpit.question_history[-1]['answer']=='Yes'
    assert cockpit.question_history[-1]['question']['id']==saved['id']
    assert cockpit.state()['question_context'] is None
    assert not cockpit.say('Yes',question_id=saved['id'])['ok']
    assert len(sent)==1,'A stale reply must never reach the model'


def test_managed_nonreview_decision_is_bound_to_work_and_does_not_revive_after_change(cockpit,monkeypatch):
    attention={'state':'quiet','managed_refinement':True,'pending_request':None,'work_digest':'work-1'}
    monkeypatch.setattr(cockpit,'_attention',lambda:attention)
    finish(cockpit,'This affects both blocks.\nI recommend a shared solution.\nUse that approach?')
    assert cockpit.state()['question_context']['question']=='Use that approach?'
    assert cockpit.state()['light']=='orange'
    attention['work_digest']='work-2'
    assert cockpit.state()['question_context'] is None
    assert cockpit.state()['open_question']==''
    assert cockpit.state()['light']=='quiet'


def test_review_context_expires_when_its_exact_request_is_resolved(cockpit,monkeypatch):
    request={'id':'review-1','step_id':'lecture','presentation_id':'p1','purpose':'Review this lecture',
             'source_message':'The source explanation is preserved.'}
    attention={'state':'needs_you','managed_refinement':True,'pending_request':request}
    monkeypatch.setattr(cockpit,'_attention',lambda:attention)
    finish(cockpit,'This is the revised lecture.\nI recommend this version.\nDoes this version look good?')
    saved=cockpit.state()['question_context']
    assert saved['authorization_scope']['presentation_id']=='p1'
    attention.update(state='quiet',pending_request=None)
    assert cockpit.state()['question_context'] is None
    assert not cockpit.say('Yes',question_id=saved['id'])['ok']


def test_a_review_request_memo_gets_the_decision_shape(cockpit, monkeypatch):
    memo = ("AI Supplement 3 Draft 5 is ready: interfaces and permissions. I recommend reviewing its teaching flow "
            "alongside the companion lesson. Alternatively, review one lesson now and defer the other. "
            "Does this version match your intended explanation?")
    request = {'id': 'review-9', 'step_id': 'lecture', 'presentation_id': 'p9', 'purpose': memo, 'source_message': ''}
    attention = {'state': 'needs_you', 'managed_refinement': True, 'pending_request': request}
    monkeypatch.setattr(cockpit, '_attention', lambda: attention)
    q = [x for x in cockpit.state()['pending_questions'] if x['source_ref'] == 'Review request review-9'][0]
    assert q['question'] == 'Does this version match your intended explanation?'          # the asking sentence, not the memo
    assert q['recommendation'].startswith('I recommend reviewing its teaching flow')       # the memo is the source
    assert q['stake'] == ['AI Supplement 3 Draft 5 is ready: interfaces and permissions.']
    assert q['authorization_scope']['request_id'] == 'review-9'


# ---- Wave M (John, 2026-09-26): reversible decisions proceed on silence ----
import time as _time
from pathlib import Path as _Path
from steward_cockpit import steward_routes as _routes

REVERSIBLE = ("The draft folder is a copy.\nI recommend replacing it.\nThis authorizes: the swap.\n"
              "Reversible: yes - undo: restore the folder from yesterday's copy.\nReplace it?")


def _age(engine, hours):
    engine.question_context["asked_at"] = _time.time() - hours * 3600
    engine_mod._update_state(engine.skey(), {"question_context": engine.question_context})


def test_a_reversible_decision_proceeds_on_four_hours_of_silence(cockpit, monkeypatch):
    monkeypatch.setattr(cockpit, "_attention", lambda: {"state": "quiet"})
    monkeypatch.setitem(_routes.ENGINES, cockpit.skey(), cockpit)
    sent = []
    monkeypatch.setattr(cockpit, "_send_locked", lambda text, **kw: (sent.append(text), True)[1])
    finish(cockpit, REVERSIBLE)
    saved = cockpit.state()["question_context"]
    assert saved["reversible"] is True and saved["undo"].startswith("restore the folder")
    _age(cockpit, 3)
    assert _routes.proceed_on_silence_sweep() == []                       # three hours: still his
    assert cockpit.state()["question_context"]["id"] == saved["id"] and sent == []
    _age(cockpit, 5)
    assert _routes.proceed_on_silence_sweep() == [cockpit.skey()]        # five hours: the recommendation stands
    assert cockpit.state()["question_context"] is None and cockpit.open_question == ""
    last = cockpit.question_history[-1]
    assert last["status"] == "proceeded_on_silence" and last["answer"] == "I recommend replacing it."
    assert len(sent) == 1 and "Proceeded on silence" in sent[0] and "Undo: restore the folder" in sent[0]
    assert [e for e in cockpit.events if e["t"] == "sys" and "Proceeded on silence" in e["text"]]   # said once, never as his words
    assert not [e for e in cockpit.events if e["t"] == "john"]
    row = cockpit.state()["decision_history"][-1]
    assert row["status"] == "proceeded_on_silence" and row["undo"].startswith("restore")
    assert _routes.proceed_on_silence_sweep() == [] and len(sent) == 1   # never twice
    assert not cockpit.say("Yes", question_id=saved["id"])["ok"]          # the retired question takes no late answer


def test_irreversible_or_unmarked_decisions_wait_however_long(cockpit, monkeypatch):
    monkeypatch.setattr(cockpit, "_attention", lambda: {"state": "quiet"})
    monkeypatch.setitem(_routes.ENGINES, cockpit.skey(), cockpit)
    sent = []
    monkeypatch.setattr(cockpit, "_send_locked", lambda text, **kw: (sent.append(text), True)[1])
    finish(cockpit, "This changes the syllabus for good.\nI recommend sending it.\nReversible: no\nSend it?")
    _age(cockpit, 30)
    assert _routes.proceed_on_silence_sweep() == [] and sent == []
    assert cockpit.state()["question_context"]["question"] == "Send it?"
    finish(cockpit, "I recommend keeping this version.\nKeep it?")
    _age(cockpit, 30)
    assert _routes.proceed_on_silence_sweep() == [] and sent == []
    assert cockpit.state()["question_context"]["reversible"] is None


def test_a_review_request_never_proceeds_on_silence(cockpit, monkeypatch):
    request = {"id": "r1", "step_id": "s1", "presentation_id": "p1",
               "purpose": "The draft is ready.\nI recommend accepting it.\nReversible: yes - undo: reopen the review.\nAccept it?",
               "asked_at": _time.time() - 9 * 3600}
    monkeypatch.setattr(cockpit, "_attention", lambda: {"state": "quiet", "managed_refinement": True, "pending_request": request, "work_digest": "w1"})
    monkeypatch.setitem(_routes.ENGINES, cockpit.skey(), cockpit)
    q = cockpit.state()["pending_questions"][0]
    assert q["reversible"] is True and (q.get("authorization_scope") or {}).get("request_id") == "r1"
    assert not cockpit.proceed_on_silence(q["id"])["ok"]                   # the ledger owns acceptance

import io
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import model_policy
from steward_cockpit import steward_engine as se


import pytest as _pytest


@_pytest.fixture(autouse=True)
def _no_conversation_effort_cap(monkeypatch):
    # these test the refresh mechanics with a high -> ultra change; the conversation cap (2026-10-05) is its own test
    from steward_cockpit import steward_engine as _se
    monkeypatch.setattr(_se, "STEWARD_CONVERSATION_EFFORT", None)

POLICY = {'mode': 'latest_supported', 'effort': 'highest_supported'}
NATIVE_ID = '12345678-1234-4234-8234-123456789012'

@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.delenv('STEWARD_COCKPIT_FAKE', raising=False)
    monkeypatch.setattr(se, 'STATE_FILE', tmp_path/'state.json')
    e = se.Engine(str(tmp_path), fake=True)
    e.fake = False
    e.cli = 'chatgpt'
    e.busy = False
    e.session_id = NATIVE_ID
    e.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    e.queue = ['queued second']
    e.model_selection = {'family':'chatgpt','model':'old','effort':'high','requested_policy':POLICY}
    new = {**e.model_selection,'model':'new','effort':'ultra'}
    settings = {'default_cli':'chatgpt','coding_family':'chatgpt','review_family':'grok','settings_revision':1,'model_policy':POLICY}
    monkeypatch.setattr(e, '_desired_policy', lambda:(settings,'chatgpt'))
    monkeypatch.setattr(e, '_select_available_policy', lambda *a:('chatgpt',dict(new)))
    monkeypatch.setattr(e, '_kill_tree', Mock())
    return e,new

def test_idle_refresh_resumes_exact_uuid_sends_once_and_keeps_queue(setup,monkeypatch):
    e,new=setup
    old=e.proc
    replacement=SimpleNamespace(stdin=io.StringIO(),poll=lambda:None)
    def wake(fresh,seed,**kwargs):
        assert fresh is False and seed is None and kwargs['send_initial'] is False
        assert kwargs['expected_session_id']==NATIVE_ID
        state=se._read_state_entry(e.skey())
        assert state['session_id']==NATIVE_ID
        assert state['routing_events'][-1]['action']=='model_refresh'
        e.model_selection=kwargs['expected_selection'];e.proc=replacement
        return True,'awake'
    monkeypatch.setattr(e,'_wake_locked',wake)
    assert e._send_locked('original message')
    assert old.stdin.getvalue()==''
    assert replacement.stdin.getvalue().count('original message')==1
    assert e.queue==['queued second'] and e.session_id==NATIVE_ID
    e._kill_tree.assert_called_once_with(old)

def test_failed_wake_retains_identity_queue_and_does_not_send(setup,monkeypatch):
    e,new=setup;old=e.proc
    monkeypatch.setattr(e,'_wake_locked',lambda **kw:(False,'unavailable'))
    assert e._send_locked('retain this') is False
    assert e.session_id==NATIVE_ID and e.queue==['queued second']
    assert old.stdin.getvalue()==''
    assert se._read_state_entry(e.skey())['session_id']==NATIVE_ID
    assert se._read_state_entry(e.skey())['retain_native_on_resume_failure'] is True

@pytest.mark.parametrize('retain_flag', [True, False, None])
def test_later_wake_never_discards_identity_after_refresh_failure(setup,monkeypatch,retain_flag):
    e,new=setup
    se._update_state(e.skey(),{'cli':'chatgpt','session_id':NATIVE_ID,
                              'model_policy':e.model_selection,'retain_native_on_resume_failure':retain_flag})
    monkeypatch.setattr(e,'_recover_legacy_history',lambda entry:None)
    monkeypatch.setattr(e,'_history_reference',lambda:'')
    monkeypatch.setattr(se,'_cli_cmd',lambda family:['codex-stub'])
    failed=SimpleNamespace(poll=lambda:1)
    spawn=Mock(return_value=failed)
    monkeypatch.setattr(se.subprocess,'Popen',spawn)
    monkeypatch.setattr(se.time,'sleep',lambda seconds:None)
    ok,note=e._wake_locked(False,None)
    assert not ok and 'identity retained' in note
    assert spawn.call_count==1
    assert '--resume' in spawn.call_args.args[0] and NATIVE_ID in spawn.call_args.args[0]
    assert se._read_state_entry(e.skey())['session_id']==NATIVE_ID
    assert e.session_id==NATIVE_ID

def test_busy_refresh_never_terminates_or_replaces(setup,monkeypatch):
    e,new=setup;e.busy=True
    assert e._refresh_model_locked(new) is False
    e._kill_tree.assert_not_called()

def test_unchanged_selection_has_no_replacement(setup):
    e,new=setup
    assert e._refresh_model_locked(dict(e.model_selection)) is True
    e._kill_tree.assert_not_called()

def test_failed_journal_keeps_original_process(setup,monkeypatch):
    e,new=setup;old=e.proc
    monkeypatch.setattr(e,'_journal_routing',Mock(side_effect=RuntimeError('journal unavailable')))
    assert e._send_locked('retain') is False
    assert e.proc is old and old.stdin.getvalue()==''
    e._kill_tree.assert_not_called()

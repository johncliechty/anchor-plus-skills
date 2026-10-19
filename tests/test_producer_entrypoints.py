"""Real completion hooks and Node ledger, with only the producer process simulated."""
import io
import json
import uuid
import threading
import time
import pytest

from tests.test_steward_refinement_browser import campaign_server


@pytest.mark.parametrize('write_tool', ['Write', 'file_change'])
def test_cockpit_tool_turn_records_same_dispatch_handoff_without_closing(campaign_server, monkeypatch, write_tool):
    from steward_cockpit import steward_engine, refinement_client
    from steward_cockpit.producer_handoff import _handoff_id
    server = campaign_server
    engine = steward_engine.Engine(str(server.campaign), fake=True)
    class Proc:
        stdin = io.StringIO()
        def poll(self):
            return None
    engine.proc = Proc()
    engine.cli = 'claude'
    engine.session_id = str(uuid.uuid4())
    engine.drive = False
    assert engine._send_locked('Refine the existing foundation')
    identifier = _handoff_id('conversation', engine._refinement_producer_id)
    assert identifier in json.loads(engine.proc.stdin.getvalue())['message']['content'][0]['text']
    assert 'resolve to' not in json.loads(engine.proc.stdin.getvalue())['message']['content'][0]['text']
    engine._handle({'type':'assistant','message':{'content':[{'type':'tool_use','name':write_tool,'input':{'file_path':str(server.campaign/'draft.md')}}]}}, engine.proc)
    engine.turn_text = 'The work is ready for Steward to check.'
    engine._handle({'type':'result','total_cost_usd':0,'duration_ms':1,'usage':{}}, engine.proc)
    result = refinement_client.read_state(server.campaign)
    assert result['ok'], result
    assert result['state']['producer_handoffs'][identifier]['status'] == 'pending_steward_review'
    assert result['state']['producer_handoffs'][identifier]['outputs'] == [str(server.campaign/'draft.md')]
    assert result['state']['producer_handoffs'][identifier]['inventory_complete'] is False
    assert result['state']['slices']['foundation']['closed_presentation'] is None
    before = result['sequence']
    assert engine._send_locked('Inspect existing handoffs')
    engine._handle({'type':'assistant','message':{'content':[{'type':'tool_use','name':'Bash','input':{'command':'refinement-update read'}}]}}, engine.proc)
    engine.turn_text = 'Inspection complete.'
    engine._handle({'type':'result','total_cost_usd':0,'duration_ms':1,'usage':{}}, engine.proc)
    assert refinement_client.read_state(server.campaign)['sequence'] == before
    engine.busy = True
    producer = engine._refinement_producer_id
    assert engine._send_locked(steward_engine.TICK)
    tick = json.loads(engine.proc.stdin.getvalue().splitlines()[-1])
    assert 'producer_handoff id' not in tick['message']['content'][0]['text']
    assert engine._refinement_producer_id == producer
    assert refinement_client.read_state(server.campaign)['sequence'] == before


def test_slow_completion_handoff_does_not_hold_user_queue_lock(campaign_server, monkeypatch):
    from steward_cockpit import steward_engine, producer_handoff
    engine = steward_engine.Engine(str(campaign_server.campaign), fake=True)
    class Proc:
        stdin = io.StringIO()
        def poll(self): return None
    engine.proc = Proc()
    engine.cli = 'claude'
    engine.session_id = str(uuid.uuid4())
    engine.drive = False
    engine._send_locked('Produce the draft')
    engine._turn_wrote_files = True
    engine.turn_text = 'Draft ready.'
    entered, release = threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {'ok':True}
    monkeypatch.setattr(producer_handoff, 'record_handoff', blocked)
    worker = threading.Thread(target=engine._handle,args=({'type':'result','total_cost_usd':0,'usage':{}},engine.proc))
    worker.start()
    try:
        assert entered.wait(5)
        start = time.monotonic()
        result = engine.say('Keep the earlier working parts')
        assert result.get('queued'), result
        assert time.monotonic()-start < 1
    finally:
        release.set()
        worker.join(10)
        assert not worker.is_alive()


def test_actual_job_finalizer_persists_handoff_failure_and_retry(campaign_server, monkeypatch):
    import job_runner
    from steward_cockpit import refinement_client
    server = campaign_server
    identifier = 'producer-entry-' + uuid.uuid4().hex
    records = {identifier:{'job_id':identifier,'status':job_runner.STATUS_RUNNING,
                          'backend':'claude','refinement_dir':str(server.campaign),
                          'refinement_context':None}}
    monkeypatch.setattr(job_runner, 'load_record', lambda job_id: dict(records[job_id]))
    monkeypatch.setattr(job_runner, '_write_record', lambda record: records.update({identifier:dict(record)}))
    monkeypatch.setattr(job_runner, '_mirror_session_status', lambda *args: None)
    plan = server.campaign / 'PLAN.md'
    original = plan.read_bytes()
    plan.write_bytes(original.replace(b'Current slice work',b'outside edited region'))
    job_runner._finalize(identifier, 0)
    assert records[identifier]['status'] == job_runner.STATUS_DONE
    assert records[identifier]['refinement_handoff']['ok'] is False
    plan.write_bytes(original)
    job_runner._finalize(identifier, 0)
    assert records[identifier]['refinement_handoff']['ok'] is True, records[identifier]['refinement_handoff']
    state = refinement_client.read_state(server.campaign)['state']
    assert len(state['producer_handoffs']) == 1
    assert state['slices']['foundation']['closed_presentation'] is None


def test_failed_producer_is_visible_as_recovery_without_fabricated_human_close(campaign_server):
    from steward_cockpit import producer_handoff, steward_campaign
    root = campaign_server.campaign
    context = producer_handoff.capture_context(root, 'foundation')
    result = producer_handoff.record_handoff(root, 'job', 'failed-producer', 'Failed job fixture', context=context, terminal='failed')
    assert result['ok'], result
    view = steward_campaign.read_map(root)
    step = next(s for s in view['steps'] if s['id'] == 'foundation')
    assert step['status'] == 'waiting'
    assert 'Steward recovery required' in step['waiting_on']
    assert step['refinement']['closed_presentation'] is None
    assert view['attention']['producer_recovery_required'] is True


@pytest.mark.parametrize('terminal_path', ['cancel', 'startup', 'liveness', 'already_interrupted'])
def test_abnormal_terminal_paths_reach_ledger(campaign_server, monkeypatch, terminal_path):
    import job_runner
    from steward_cockpit import producer_handoff, refinement_client
    root = campaign_server.campaign
    identifier = 'abnormal-' + uuid.uuid4().hex
    records = {identifier: {'job_id':identifier, 'status':'running', 'backend':'claude',
                           'pid':None, 'refinement_dir':str(root),
                           'refinement_context':producer_handoff.capture_context(root, 'foundation')}}
    monkeypatch.setattr(job_runner, 'load_record', lambda jid: dict(records[jid]))
    monkeypatch.setattr(job_runner, '_write_record', lambda rec: records.update({identifier:dict(rec)}))
    monkeypatch.setattr(job_runner, '_mirror_session_status', lambda *args: None)
    monkeypatch.setattr(job_runner, '_pid_alive', lambda *args: False)
    monkeypatch.setattr(job_runner, 'list_records', lambda: list(records.values()))
    monkeypatch.setattr(job_runner, 'gc_old_job_logs', lambda: None)
    if terminal_path == 'cancel':
        job_runner._commit_cancelled(identifier, records[identifier], 'already-absent')
        expected = 'cancelled'
    elif terminal_path == 'startup':
        job_runner.reconcile_on_startup()
        expected = 'interrupted'
    elif terminal_path == 'liveness':
        job_runner.liveness_check(identifier)
        expected = 'interrupted'
    else:
        records[identifier]['status'] = 'interrupted'
        job_runner._finalize(identifier, 1)
        expected = 'interrupted'
    job_runner.reconcile_on_startup()
    state = refinement_client.read_state(root)['state']
    assert len(state['producer_handoffs']) == 1
    assert next(iter(state['producer_handoffs'].values()))['terminal'] == expected
    assert state['slices']['foundation']['closed_presentation'] is None
    assert records[identifier]['refinement_handoff']['ok'] is True


def test_drive_edit_is_not_a_producer_and_recovery_stops_drive(campaign_server, monkeypatch):
    from steward_cockpit import steward_engine, steward_campaign, refinement_client
    engine = steward_engine.Engine(str(campaign_server.campaign), fake=True)
    class Proc:
        stdin = io.StringIO()
        def poll(self): return None
    engine.proc = Proc()
    engine.cli = 'claude'
    engine.session_id = str(uuid.uuid4())
    engine.drive = False
    before = refinement_client.read_state(campaign_server.campaign)['sequence']
    assert engine._send_locked('(drive - not John) Continue')
    assert engine._refinement_producer_id is None
    engine._turn_wrote_files = True
    engine.turn_text = 'Updated bookkeeping.'
    engine._handle({'type':'result','total_cost_usd':0,'usage':{}}, engine.proc)
    assert refinement_client.read_state(campaign_server.campaign)['sequence'] == before
    engine.drive = True
    monkeypatch.setattr(engine, 'alive', lambda: True)
    monkeypatch.setattr(steward_campaign, 'read_map', lambda *_: {'attention':{
        'managed_refinement':True, 'pending_request':None,
        'producer_recovery_required':True, 'state':'quiet'}})
    sends = []
    monkeypatch.setattr(engine, '_send_locked', lambda text: sends.append(text))
    engine._maybe_drive_locked(completed_text='Ready')
    assert sends == []


class _R7Proc:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stop = False

    def poll(self):
        return 0 if self.stop else None


def _r7_engine(campaign_server, monkeypatch, tmp_path):
    from steward_cockpit import steward_engine

    monkeypatch.setattr(steward_engine, 'STATE_FILE', tmp_path / 'r7-engine-state.json')
    engine = steward_engine.Engine(str(campaign_server.campaign), fake=True)
    engine.cli = 'claude'
    engine.session_id = str(uuid.uuid4())
    engine.drive = False
    engine.proc = _R7Proc()
    monkeypatch.setattr(engine, '_status_update', lambda **kwargs: None)
    # A real init records this selected provider/session before a human send.
    assert steward_engine._update_state(engine.skey(), {
        'cli': engine.cli, 'session_id': engine.session_id,
    }) is True
    return engine


def _r7_actual_write_turn(engine, campaign):
    engine._send_locked('Produce the draft')
    draft = campaign / 'draft.md'
    draft.write_text('# Draft\nA produced intermediate deliverable.\n', encoding='utf-8')
    engine._handle({'type': 'assistant', 'message': {'content': [{
        'type': 'tool_use', 'id': 'r7-write', 'name': 'Write',
        'input': {'file_path': str(draft), 'content': '# Draft\nA produced intermediate deliverable.\n'},
    }]}}, engine.proc)
    engine.turn_text = 'Draft ready.'
    engine._handle({'type': 'result', 'total_cost_usd': 0, 'usage': {}}, engine.proc)


def _r7_handoff_call(original, args, kwargs):
    import inspect

    bound = inspect.signature(original).bind(*args, **kwargs)
    bound.apply_defaults()
    return json.loads(json.dumps(dict(bound.arguments), default=str))


def test_failed_conversation_handoff_is_retried_by_idle_ticker_without_another_send(campaign_server, monkeypatch, tmp_path):
    from steward_cockpit import producer_handoff, refinement_client, steward_engine

    engine = _r7_engine(campaign_server, monkeypatch, tmp_path)
    proc = engine.proc
    original = producer_handoff.record_handoff
    calls = []

    def fail_once(*args, **kwargs):
        calls.append(_r7_handoff_call(original, args, kwargs))
        if len(calls) == 1:
            return {'ok': False, 'error': 'dependency-slow-or-killed'}
        result = original(*args, **kwargs)
        if result.get('ok') is True:
            proc.stop = True
        return result

    monkeypatch.setattr(producer_handoff, 'record_handoff', fail_once)
    _r7_actual_write_turn(engine, campaign_server.campaign)
    assert len(calls) == 1
    assert calls[0]['outputs'], 'The real Write event must produce an explicit inventory'
    assert calls[0]['source_ref']
    assert engine.busy is False
    stored = steward_engine._read_state_entry(engine.skey())
    pending = stored['pending_refinement_handoffs']
    assert pending == engine._pending_refinement_handoffs
    assert len(pending) == 1
    assert calls[0]['producer_id'] in json.dumps(pending)
    assert 'draft.md' in json.dumps(pending)
    before = refinement_client.read_state(campaign_server.campaign)
    assert before['ok'] is True
    assert before['state']['slices']['foundation']['closed_presentation'] is None
    before_ids = set(before['state'].get('producer_handoffs', {}))
    sent_before_retry = proc.stdin.getvalue()
    engine.drive = True
    engine._maybe_drive_locked(completed_text='Draft ready')
    assert proc.stdin.getvalue() == sent_before_retry
    engine.drive = False

    monkeypatch.setattr(steward_engine, 'TICK_CHECK', 0.01)
    ticker = threading.Thread(target=engine._ticker, args=(proc,), name='r7-idle-receipt-retry', daemon=True)
    ticker.start()
    try:
        ticker.join(timeout=20)
    finally:
        proc.stop = True
        ticker.join(timeout=30)
    assert not ticker.is_alive(), 'The owned ticker did not stop'
    assert len(calls) == 2
    assert calls[1]['producer_id'] == calls[0]['producer_id']
    assert calls[1]['outputs'] == calls[0]['outputs']
    assert calls[1]['source_ref'] == calls[0]['source_ref']
    assert calls[1]['context'] == calls[0]['context']
    assert proc.stdin.getvalue() == sent_before_retry
    assert engine._pending_refinement_handoffs == {}
    assert steward_engine._read_state_entry(engine.skey())['pending_refinement_handoffs'] == {}
    after = refinement_client.read_state(campaign_server.campaign)
    assert after['ok'] is True
    handoffs = after['state']['producer_handoffs']
    new_ids = set(handoffs) - before_ids
    assert len(new_ids) == 1
    assert handoffs[next(iter(new_ids))]['status'] == 'pending_steward_review'
    assert after['state']['slices']['foundation']['closed_presentation'] is None

    # A subsequent human inspection is a distinct read-only turn, and must
    # neither reproduce the recovered handoff nor create another pending one.
    engine.proc = _R7Proc()
    engine._send_locked('Inspect the draft')
    engine._handle({'type': 'assistant', 'message': {'content': [{
        'type': 'tool_use', 'id': 'r7-inspect', 'name': 'Bash',
        'input': {'command': 'cat draft.md'},
    }]}}, engine.proc)
    engine.turn_text = 'Inspected the draft.'
    engine._handle({'type': 'result', 'total_cost_usd': 0, 'usage': {}}, engine.proc)
    inspected = refinement_client.read_state(campaign_server.campaign)
    assert inspected['ok'] is True
    assert set(inspected['state']['producer_handoffs']) == set(handoffs)
    assert len(calls) == 2


def test_reconstructed_engine_retries_its_frozen_handoff_once(campaign_server, monkeypatch, tmp_path):
    from steward_cockpit import producer_handoff, refinement_client, steward_engine

    engine = _r7_engine(campaign_server, monkeypatch, tmp_path)
    original = producer_handoff.record_handoff
    calls = []

    def fail_once(*args, **kwargs):
        calls.append(_r7_handoff_call(original, args, kwargs))
        if len(calls) == 1:
            return {'ok': False, 'error': 'dependency-missing'}
        return original(*args, **kwargs)

    monkeypatch.setattr(producer_handoff, 'record_handoff', fail_once)
    _r7_actual_write_turn(engine, campaign_server.campaign)
    assert len(calls) == 1
    frozen = json.loads(json.dumps(engine._pending_refinement_handoffs))
    assert frozen
    assert steward_engine._read_state_entry(engine.skey())['pending_refinement_handoffs'] == frozen
    before = refinement_client.read_state(campaign_server.campaign)
    assert before['ok'] is True
    before_ids = set(before['state'].get('producer_handoffs', {}))

    rebuilt = steward_engine.Engine(str(campaign_server.campaign), fake=True)
    assert rebuilt._pending_refinement_handoffs == frozen
    rebuilt._retry_refinement_handoffs()
    assert len(calls) == 2
    assert calls[1]['producer_id'] == calls[0]['producer_id']
    assert calls[1]['outputs'] == calls[0]['outputs']
    assert calls[1]['source_ref'] == calls[0]['source_ref']
    assert calls[1]['context'] == calls[0]['context']
    assert rebuilt._pending_refinement_handoffs == {}
    assert steward_engine._read_state_entry(rebuilt.skey())['pending_refinement_handoffs'] == {}
    rebuilt._retry_refinement_handoffs()
    assert len(calls) == 2
    after = refinement_client.read_state(campaign_server.campaign)
    assert after['ok'] is True
    new_ids = set(after['state']['producer_handoffs']) - before_ids
    assert len(new_ids) == 1
    assert after['state']['producer_handoffs'][next(iter(new_ids))]['status'] == 'pending_steward_review'
    assert after['state']['slices']['foundation']['closed_presentation'] is None

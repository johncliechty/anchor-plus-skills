"""Durable machine-result acceptance, independently of model transport."""

import copy
import threading
from types import SimpleNamespace

import pytest

from steward_cockpit import maintenance
from steward_cockpit import steward_engine as se


@pytest.fixture
def queue_env(tmp_path, monkeypatch):
    durable = {}
    writes = []
    dispatches = []
    events = []

    def persist(key, patch):
        writes.append(copy.deepcopy(patch))
        durable.setdefault(key, {}).update(copy.deepcopy(patch))
        return True

    def make_engine(stored=None):
        stored = stored or {}
        eng = se.Engine.__new__(se.Engine)
        eng._lock = threading.RLock()
        eng.dir = tmp_path
        eng.general = False
        eng.tid = None
        eng.queue = list(stored.get("pending_queue") or [])
        eng.accepted_job_results = copy.deepcopy(stored.get("accepted_job_results") or {})
        eng.job_results_paused = bool(stored.get("job_results_paused", False))
        eng.drive = False
        eng.busy = True
        eng.alive = lambda: True
        eng.effort_on = lambda: False
        eng.skey = lambda: "test-steward"
        eng._emit = events.append

        def dispatch():
            dispatches.append({"queue": list(eng.queue), "state": copy.deepcopy(durable)})
            return True

        eng._deliver_next_queued_locked = dispatch
        return eng

    monkeypatch.setattr(se, "_update_state", persist)
    monkeypatch.setattr(maintenance, "is_active", lambda: False)
    return SimpleNamespace(
        engine=make_engine(), make_engine=make_engine, durable=durable,
        writes=writes, dispatches=dispatches, events=events, persist=persist,
    )


def test_acceptance_persists_identity_and_queue_together_before_dispatch(queue_env):
    env = queue_env
    eng = env.engine
    eng.queue = ["unrelated pending work"]
    eng.busy = False
    result = eng.enqueue_job_result("job-1:attempt-1:result-1", "Checks passed; product landed.")

    assert result["ok"] and not result["duplicate"]
    assert len(env.writes) == 1
    patch = env.writes[0]
    assert set(patch) == {"pending_queue", "accepted_job_results"}
    assert patch["pending_queue"][0] == "unrelated pending work"
    control = patch["pending_queue"][1]
    assert control.startswith(se.MACHINE_MARK + "[job result job-1:attempt-1:result-1]")
    assert se._is_machine_text(control)
    assert len(env.dispatches) == 1
    assert env.dispatches[0]["state"]["test-steward"] == patch


@pytest.mark.parametrize("failure", ["false", "exception"])
def test_failed_persistence_rolls_back_without_dispatch_and_can_retry(queue_env, monkeypatch, failure):
    env = queue_env
    eng = env.engine
    eng.queue = ["unrelated pending work"]
    eng.busy = False

    def fail_write(_key, _patch):
        if failure == "exception":
            raise OSError("disk unavailable")
        return False

    monkeypatch.setattr(se, "_update_state", fail_write)
    result = eng.enqueue_job_result("job-1:attempt-1", "Product kept for recovery.")
    assert not result["ok"]
    assert eng.queue == ["unrelated pending work"]
    assert eng.accepted_job_results == {}
    assert env.durable == {}
    assert env.dispatches == []

    monkeypatch.setattr(se, "_update_state", env.persist)
    assert eng.enqueue_job_result("job-1:attempt-1", "Product kept for recovery.")["ok"]
    assert len(eng.queue) == 2


def test_duplicate_after_reconstruction_is_acknowledged_without_second_queue_item(queue_env):
    env = queue_env
    text = "Check not run; inspect the retained work."
    assert env.engine.enqueue_job_result("job-1:attempt-1", text)["ok"]
    recreated = env.make_engine(env.durable["test-steward"])
    recreated.busy = False
    result = recreated.enqueue_job_result("job-1:attempt-1", text)

    assert result["ok"] and result["duplicate"]
    assert len(recreated.queue) == 1
    assert len(env.writes) == 1
    assert env.dispatches == []


def test_reused_identity_with_changed_content_is_rejected(queue_env):
    env = queue_env
    assert env.engine.enqueue_job_result("job-1:attempt-1", "Not landed.")["ok"]
    result = env.engine.enqueue_job_result("job-1:attempt-1", "Landed.")
    assert not result["ok"]
    assert len(env.engine.queue) == 1
    assert len(env.writes) == 1


@pytest.mark.parametrize("condition", ["paused", "maintenance", "asleep"])
def test_new_result_remains_pending_while_dispatch_is_disallowed(queue_env, monkeypatch, condition):
    env = queue_env
    eng = env.engine
    eng.busy = False
    if condition == "paused":
        eng.job_results_paused = True
    elif condition == "maintenance":
        monkeypatch.setattr(maintenance, "is_active", lambda: True)
    else:
        eng.alive = lambda: False

    result = eng.enqueue_job_result("job-1:attempt-1", "Ready to collect.")
    assert not result["ok"]
    assert eng.queue == []
    assert eng.accepted_job_results == {}
    assert env.writes == []
    assert env.dispatches == []


def test_drive_off_without_an_explicit_pause_accepts_result(queue_env):
    eng = queue_env.engine
    assert eng.drive is False and eng.job_results_paused is False
    assert eng.enqueue_job_result("job-1:attempt-1", "Ready to collect.")["ok"]


def test_dashboard_drive_off_keeps_result_dispatch_available(queue_env):
    env = queue_env
    eng = env.engine
    eng.drive = True
    eng.busy = False

    eng.set_drive(False)

    assert eng.drive is False
    assert eng.job_results_paused is False
    assert env.writes == []
    assert eng.enqueue_job_result("job-1:attempt-1", "Ready to collect.")["ok"]
    assert len(env.dispatches) == 1


def test_dashboard_drive_on_does_not_clear_an_explicit_result_pause(queue_env):
    env = queue_env
    eng = env.engine
    eng.job_results_paused = True
    eng.busy = False

    eng.set_drive(True)

    assert eng.drive is True
    assert eng.job_results_paused is True
    assert not eng.enqueue_job_result("job-1:attempt-1", "Ready to collect.")["ok"]
    assert env.writes == []
    assert env.dispatches == []


def test_already_accepted_result_acknowledges_during_pause_without_dispatch(queue_env, monkeypatch):
    env = queue_env
    text = "Ready to collect."
    assert env.engine.enqueue_job_result("job-1:attempt-1", text)["ok"]
    env.engine.job_results_paused = True
    env.engine.busy = False
    monkeypatch.setattr(maintenance, "is_active", lambda: True)
    result = env.engine.enqueue_job_result("job-1:attempt-1", text)
    assert result["ok"] and result["duplicate"]
    assert env.dispatches == []
    assert len(env.writes) == 1


def test_dispatch_failure_does_not_undo_durable_acceptance(queue_env):
    env = queue_env
    eng = env.engine
    eng.busy = False

    def failed_send():
        raise OSError("transport unavailable")

    eng._deliver_next_queued_locked = failed_send
    result = eng.enqueue_job_result("job-1:attempt-1", "Ready to collect.")
    assert result["ok"] and "dispatch_error" in result
    assert len(env.durable["test-steward"]["pending_queue"]) == 1
    assert env.events
    assert eng.enqueue_job_result("job-1:attempt-1", "Ready to collect.")["duplicate"]
    assert len(env.writes) == 1


def test_paused_result_at_queue_head_is_not_sent_or_removed(queue_env):
    env = queue_env
    eng = env.engine
    assert eng.enqueue_job_result("job-1:attempt-1", "Ready to collect.")["ok"]
    saved = list(eng.queue)
    eng.job_results_paused = True
    eng.busy = False

    def unexpected_send(*args, **kwargs):
        pytest.fail("A paused job-result control must not reach the model transport")

    eng._send_locked = unexpected_send
    assert se.Engine._deliver_next_queued_locked(eng) is False
    assert eng.queue == saved


def test_paused_results_do_not_block_later_human_messages_and_keep_their_order(queue_env):
    env = queue_env
    eng = env.engine
    assert eng.enqueue_job_result("job-1:attempt-1", "First result.")["ok"]
    first_result = eng.queue[0]
    other_control = se.MACHINE_MARK + "Other pending automatic control."
    eng.queue.append(other_control)
    eng.queue.append("Please answer this question.")
    assert eng.enqueue_job_result("job-2:attempt-1", "Second result.")["ok"]
    second_result = eng.queue[-1]
    eng.queue.append("Then answer this follow-up.")
    eng.job_results_paused = True
    eng.busy = False
    sent = []

    def send(text, **kwargs):
        sent.append((text, kwargs))
        return True

    eng._send_locked = send
    assert se.Engine._deliver_next_queued_locked(eng) is True
    assert sent[0][0] == "Please answer this question."
    assert sent[0][1]["origin"] == "human"
    assert eng.queue == [first_result, other_control, second_result, "Then answer this follow-up."]
    assert eng.job_results_paused is True
    assert se.Engine._deliver_next_queued_locked(eng) is True
    assert sent[1][0] == "Then answer this follow-up."
    assert eng.queue == [first_result, other_control, second_result]
    assert se.Engine._deliver_next_queued_locked(eng) is False
    assert len(sent) == 2
    assert env.durable["test-steward"]["pending_queue"] == [first_result, other_control, second_result]


def test_failed_send_keeps_both_held_result_and_later_human_message(queue_env):
    env = queue_env
    eng = env.engine
    assert eng.enqueue_job_result("job-1:attempt-1", "Ready to collect.")["ok"]
    eng.queue.append("Please answer this question.")
    eng.job_results_paused = True
    eng.busy = False
    saved = list(eng.queue)
    eng._send_locked = lambda *args, **kwargs: False
    assert eng._persist_queue()

    se.Engine._deliver_next_queued_locked(eng)
    assert eng.queue == saved
    assert env.durable["test-steward"]["pending_queue"] == saved
    assert eng.job_results_paused is True


@pytest.mark.parametrize("identity,text", [("", "result"), ("bad\nidentity", "result"), ("job-1", "")])
def test_invalid_result_has_no_queue_or_state_effect(queue_env, identity, text):
    env = queue_env
    assert not env.engine.enqueue_job_result(identity, text)["ok"]
    assert env.engine.queue == []
    assert env.writes == []

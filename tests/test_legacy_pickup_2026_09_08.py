"""Parked-session recovery gates; all provider imports/launches are synthetic."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import anchor_settings
from steward_cockpit import conversation_history, legacy_claude_history, steward_engine


SESSION_ID = "00000000-0000-0000-0000-000000000541"


@pytest.fixture
def pickup(tmp_path, monkeypatch):
    monkeypatch.delenv("STEWARD_COCKPIT_FAKE", raising=False)
    state_file = tmp_path / "synthetic-engine-state.json"
    monkeypatch.setattr(steward_engine, "STATE_FILE", state_file)
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {
        "default_cli": "chatgpt",
        "coding_family": "chatgpt",
        "review_family": "grok",
        "settings_revision": 1,
        "model_policy": {"mode": "latest_supported", "effort": "highest_supported"},
    })
    imported = []
    emitted = []
    journaled = []

    def importer(*args, **kwargs):
        imported.append((args, kwargs))
        return {"imported": 2, "eligible": 2, "source": "synthetic-native.jsonl", "session_id": SESSION_ID}

    monkeypatch.setattr(legacy_claude_history, "import_legacy_claude", importer)

    def make_engine(*, general=False, tid=None):
        engine = steward_engine.Engine(str(tmp_path), fake=True, general=general, tid=tid)
        engine.fake = False
        engine.proc = None
        engine.busy = False
        monkeypatch.setattr(engine, "_emit", lambda *args, **kwargs: emitted.append((args, kwargs)))
        monkeypatch.setattr(engine, "_journal_routing", lambda *args, **kwargs: journaled.append((args, kwargs)))
        return engine

    return SimpleNamespace(
        root=tmp_path,
        state_file=state_file,
        engine=make_engine(),
        make_engine=make_engine,
        imported=imported,
        emitted=emitted,
        journaled=journaled,
    )


def _legacy_entry():
    return {"cli": "claude", "session_id": SESSION_ID, "other_metadata": {"preserve": True}}


def _assert_no_recovery_actions(pickup):
    assert pickup.imported == []
    assert pickup.emitted == []
    assert pickup.journaled == []


@pytest.mark.parametrize("fake_mode", ["engine", "environment"])
def test_fake_mode_bypasses_native_recovery(pickup, monkeypatch, fake_mode):
    if fake_mode == "engine":
        pickup.engine.fake = True
    else:
        monkeypatch.setenv("STEWARD_COCKPIT_FAKE", "1")
    assert pickup.engine._recover_legacy_history(_legacy_entry()) is False
    _assert_no_recovery_actions(pickup)


@pytest.mark.parametrize("entry", [
    {"cli": "chatgpt", "session_id": SESSION_ID},
    {"cli": "grok", "session_id": SESSION_ID},
    {"cli": "claude"},
    {"cli": "claude", "session_id": None},
    {"cli": "claude", "session_id": ""},
])
def test_only_legacy_claude_with_a_session_pointer_is_eligible(pickup, entry):
    original = deepcopy(entry)
    assert pickup.engine._recover_legacy_history(entry) is False
    assert entry == original
    _assert_no_recovery_actions(pickup)


def test_existing_canonical_history_is_authoritative_and_bypasses_import(pickup):
    conversation_history.append_turn(pickup.root, "john", "Synthetic instruction")
    target = pickup.root / ".ecgberht" / "conversation-log.json"
    original = target.read_bytes()
    assert pickup.engine._recover_legacy_history(_legacy_entry()) is False
    assert target.read_bytes() == original
    _assert_no_recovery_actions(pickup)


def test_corrupt_canonical_history_refuses_recovery_without_overwrite(pickup):
    target = pickup.root / ".ecgberht" / "conversation-log.json"
    target.parent.mkdir(exist_ok=True)
    original = b'{"turns": [incomplete synthetic history'
    target.write_bytes(original)
    with pytest.raises(ValueError):
        pickup.engine._recover_legacy_history(_legacy_entry())
    assert target.read_bytes() == original
    _assert_no_recovery_actions(pickup)


@pytest.mark.parametrize("running_state", ["live", "busy"])
def test_native_recovery_requires_a_parked_session(pickup, running_state):
    if running_state == "live":
        pickup.engine.proc = SimpleNamespace(poll=lambda: None)
    else:
        pickup.engine.busy = True
    with pytest.raises(ValueError, match="legacy conversation recovery requires a parked session"):
        pickup.engine._recover_legacy_history(_legacy_entry())
    _assert_no_recovery_actions(pickup)


@pytest.mark.parametrize("thread_id", [None, "303"])
def test_exact_legacy_session_and_history_thread_are_forwarded_without_pointer_changes(pickup, thread_id):
    engine = pickup.engine if thread_id is None else pickup.make_engine(general=True, tid=thread_id)
    entry = _legacy_entry()
    original_entry = deepcopy(entry)
    pickup.state_file.write_text(json.dumps({"legacy_pointer": entry}), encoding="utf-8")
    original_state = pickup.state_file.read_bytes()

    assert engine._recover_legacy_history(entry) is True

    assert len(pickup.imported) == 1
    args, kwargs = pickup.imported[0]
    assert Path(args[0]) == pickup.root
    assert args[1] == SESSION_ID
    assert kwargs["thread_id"] == thread_id
    assert kwargs["excluded_prompts"] == (
        steward_engine.STAND_UP,
        steward_engine.STAND_UP_NEW,
        steward_engine.RESUME_BRIEF,
        steward_engine.REASSERT,
        steward_engine.TICK,
    )
    assert entry == original_entry
    assert pickup.state_file.read_bytes() == original_state
    assert len(pickup.journaled) == 1
    journal_args, journal_kwargs = pickup.journaled[0]
    journal = dict(journal_kwargs)
    if journal_args:
        assert len(journal_args) == 1
        journal["kind"] = journal_args[0]
    assert journal == {
        "kind": "legacy_conversation_recovered",
        "family": "claude",
        "source_session": SESSION_ID,
        "turns": 2,
    }
    assert any("sys" in repr(event) and "recover" in repr(event).lower() and "2" in repr(event) for event in pickup.emitted)


def test_importer_failure_bubbles_before_success_reporting_or_pointer_changes(pickup, monkeypatch):
    entry = _legacy_entry()
    original_entry = deepcopy(entry)
    pickup.state_file.write_text(json.dumps({"legacy_pointer": entry}), encoding="utf-8")
    original_state = pickup.state_file.read_bytes()
    attempted = []

    def fail_import(*args, **kwargs):
        attempted.append((args, kwargs))
        raise ValueError("synthetic native transcript mismatch")

    monkeypatch.setattr(legacy_claude_history, "import_legacy_claude", fail_import)
    with pytest.raises(ValueError, match="synthetic native transcript mismatch"):
        pickup.engine._recover_legacy_history(entry)
    assert len(attempted) == 1
    assert pickup.emitted == []
    assert pickup.journaled == []
    assert entry == original_entry
    assert pickup.state_file.read_bytes() == original_state
    assert not (pickup.root / ".ecgberht" / "conversation-log.json").exists()

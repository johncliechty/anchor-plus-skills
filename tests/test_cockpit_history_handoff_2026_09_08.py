"""No-loss cockpit history canaries; synthetic roots and no provider launches."""

import io
from types import SimpleNamespace

import pytest

import anchor_settings
from steward_cockpit import conversation_history, steward_engine


LONG_INSTRUCTIONS = (
    "Original dictated requirements: "
    + "Preserve the complete teaching instructions and their original order. " * 120
    + "END-OF-ORIGINAL-DICTATION-MUST-SURVIVE"
)


@pytest.fixture
def cockpit(monkeypatch, tmp_path):
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {
        "default_cli": "chatgpt", "coding_family": "chatgpt", "review_family": "grok",
        "settings_revision": 1,
        "model_policy": {"mode": "latest_supported", "effort": "highest_supported"},
    })
    engine = steward_engine.Engine(str(tmp_path), fake=True, general=False, tid=None)
    engine.fake = False
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    engine.busy = False
    return engine, tmp_path


def texts(root, thread_id=None):
    document = conversation_history.read_history_document(root, thread_id=thread_id)
    return [turn["text"] for turn in document["turns"]]


def test_archiving_a_stale_pointer_does_not_erase_newer_provider_history(cockpit):
    engine, _ = cockpit
    first = {"cli": "claude", "session_id": "old-claude"}
    second = {"cli": "chatgpt", "session_id": "new-chatgpt"}
    assert engine._retain_native_session(first)
    assert engine._retain_native_session(second)
    assert engine._retain_native_session(first)
    records = steward_engine._read_state_entry(engine.skey())["provider_sessions"]
    assert {(r["family"], r["session_id"]) for r in records} == {
        ("claude", "old-claude"), ("chatgpt", "new-chatgpt")}


def test_long_john_instructions_are_durable_before_send(cockpit, monkeypatch):
    engine, root = cockpit
    sent = []
    assert len(LONG_INSTRUCTIONS) > 3500

    def send(text):
        assert LONG_INSTRUCTIONS in text
        assert texts(root)[-1] == LONG_INSTRUCTIONS
        sent.append(text)
        return True

    monkeypatch.setattr(engine, "_send_locked", send)
    response = engine.say(LONG_INSTRUCTIONS, human=True)
    assert response["ok"] is True
    assert len(sent) == 1 and LONG_INSTRUCTIONS in sent[0]
    assert texts(root)[-1].endswith("END-OF-ORIGINAL-DICTATION-MUST-SURVIVE")
    assert engine.proc.stdin.getvalue() == ""


def test_corrupt_canonical_history_refuses_delivery_and_preserves_original_bytes(cockpit, monkeypatch):
    engine, root = cockpit
    path = root / ".ecgberht" / "conversation-log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"turns": [original damaged bytes must be preserved'
    path.write_bytes(original)
    engine.queue = ["previously queued user instruction"]
    before_queue = list(engine.queue)
    calls = []

    def send(text):
        calls.append(text)
        return True

    monkeypatch.setattr(engine, "_send_locked", send)
    response = engine.say("Do not deliver this while durable history is unavailable", human=True)
    assert response["ok"] is False
    assert calls == []
    assert engine.queue == before_queue
    assert engine.proc.stdin.getvalue() == ""
    assert path.read_bytes() == original


def test_new_engine_references_complete_existing_history_instead_of_a_truncated_seed(cockpit):
    first, root = cockpit
    conversation_history.append_turn(root, "john", LONG_INSTRUCTIONS)
    conversation_history.append_turn(root, "steward", "Original full assistant acknowledgement")
    second = steward_engine.Engine(str(root), fake=True, general=False, tid=None)
    second.fake = False

    for engine in (first, second):
        reference = engine._history_reference()
        handoff = engine._handoff_text()
        assert "read the complete durable history" in reference.lower()
        assert ".ecgberht/conversation-log.json" in reference.replace("\\", "/")
        assert "read the complete durable history" in handoff.lower()
        assert ".ecgberht/conversation-log.json" in handoff.replace("\\", "/")
        assert LONG_INSTRUCTIONS not in reference
        assert "END-OF-ORIGINAL-DICTATION-MUST-SURVIVE" not in handoff
    assert texts(root) == [LONG_INSTRUCTIONS, "Original full assistant acknowledgement"]


def test_original_native_session_pointer_survives_active_id_replacement_without_duplicates(cockpit):
    engine, _ = cockpit
    old_policy = {"family": "claude", "model": "best", "effort": "max", "model_attested": False}
    original = {"cli": "claude", "session_id": "original-native-session", "model_policy": old_policy}
    assert engine._retain_native_session(original) is True
    assert steward_engine._update_state(engine.skey(), {
        "cli": "chatgpt", "session_id": "replacement-native-session",
        "model_policy": {"family": "chatgpt", "model": "gpt-synthetic", "effort": "ultra"},
    }) is True
    engine._retain_native_session(original)

    persisted = steward_engine._read_state_entry(engine.skey())
    assert persisted["session_id"] == "replacement-native-session"
    archived = [entry for entry in persisted["provider_sessions"]
                if entry["family"] == "claude" and entry["session_id"] == "original-native-session"]
    assert len(archived) == 1
    assert archived[0]["model_policy"] == old_policy
    assert isinstance(archived[0]["preserved_at"], (int, float))


def test_two_terminal_threads_keep_their_original_instructions_separate(cockpit):
    _, root = cockpit
    conversation_history.append_turn(root, "john", "First terminal original instruction", thread_id="101")
    conversation_history.append_turn(root, "john", "Second terminal original instruction", thread_id="202")
    conversation_history.append_turn(root, "steward", "First terminal acknowledgement", thread_id="101")

    assert texts(root, "101") == ["First terminal original instruction", "First terminal acknowledgement"]
    assert texts(root, "202") == ["Second terminal original instruction"]
    assert (root / ".ecgberht" / "terminal-history" / "101.json").is_file()
    assert (root / ".ecgberht" / "terminal-history" / "202.json").is_file()


def test_project_and_general_thread_handoffs_point_to_their_own_complete_histories(cockpit):
    project_engine, root = cockpit
    conversation_history.append_turn(root, "john", "Project-wide original requirement")
    conversation_history.append_turn(root, "john", "General terminal original requirement", thread_id="303")
    general_engine = steward_engine.Engine(str(root), fake=True, general=True, tid="303")
    general_engine.fake = False

    project_reference = project_engine._history_reference().replace("\\", "/")
    general_reference = general_engine._history_reference().replace("\\", "/")
    assert ".ecgberht/conversation-log.json" in project_reference
    assert "terminal-history/303.json" not in project_reference
    assert ".ecgberht/terminal-history/303.json" in general_reference
    assert "conversation-log.json" not in general_reference
    assert "read the complete durable history" in general_reference.lower()
    assert texts(root) == ["Project-wide original requirement"]
    assert texts(root, "303") == ["General terminal original requirement"]

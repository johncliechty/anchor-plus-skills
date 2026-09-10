"""Isolated history tests. No providers, terminals, or processes are started."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path

import pytest

from steward_cockpit import conversation_history as history


def _target(root, thread_id=None):
    directory = root / ".ecgberht"
    return (
        directory / "conversation-log.json"
        if thread_id is None
        else directory / "terminal-history" / (thread_id + ".json")
    )


def _seed(root, document):
    target = _target(root)
    target.parent.mkdir()
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return target


def test_missing_history_reads_do_not_create_files(tmp_path):
    assert history.read_history_document(tmp_path) == {"turns": []}
    assert history.has_history(tmp_path) is False
    assert not (tmp_path / ".ecgberht").exists()


def test_full_unicode_dictation_survives_a_new_module_instance(tmp_path):
    text = ("Integral ∫, résumé, 中文, 🧮\r\n  Preserve spaces.\t" * 200) + "\nlast line"
    assert len(text) > 3500
    assert history.append_turn(tmp_path, "john", text, at="2026-09-08T00:00:00Z")
    spec = importlib.util.spec_from_file_location("isolated_history_reader", history.__file__)
    instance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instance)
    assert instance.has_history(tmp_path)
    assert instance.read_history_document(tmp_path)["turns"] == [
        {"role": "john", "text": text, "at": "2026-09-08T00:00:00Z"}
    ]
    assert text.encode("utf-8").split(b"\r\n")[0] in _target(tmp_path).read_bytes()


def test_append_preserves_all_document_and_prior_turn_metadata(tmp_path):
    original = {
        "version": 3,
        "context": {"labels": ["class", "draft"], "retained": True},
        "turns": [
            {"role": "steward", "text": "Prior answer", "at": "earlier", "provider": {"name": "original"}}
        ],
    }
    _seed(tmp_path, original)
    assert history.append_turn(tmp_path, "john", "Follow-up", at="later")
    actual = history.read_history_document(tmp_path)
    assert actual["version"] == original["version"]
    assert actual["context"] == original["context"]
    assert actual["turns"][:-1] == original["turns"]


@pytest.mark.parametrize("payload", [b"{broken", b"[]", b'{"turns":null}', b'{"turns":[],"turns":[]}'])
def test_corrupt_log_is_never_overwritten(tmp_path, payload):
    target = _target(tmp_path)
    target.parent.mkdir()
    target.write_bytes(payload)
    with pytest.raises(history.ConversationHistoryError):
        history.append_turn(tmp_path, "john", "New text")
    with pytest.raises(history.ConversationHistoryError):
        history.has_history(tmp_path)
    assert target.read_bytes() == payload


def test_idempotent_id_retains_original_timestamp_and_exact_file(tmp_path):
    assert history.append_turn(tmp_path, "john", "Same submission", at="first", turn_id="submission-1")
    before = _target(tmp_path).read_bytes()
    assert history.append_turn(tmp_path, "john", "Same submission", at="retry", turn_id="submission-1") is False
    assert _target(tmp_path).read_bytes() == before
    with pytest.raises(history.ConversationHistoryError, match="turn_id_conflict"):
        history.append_turn(tmp_path, "john", "Different submission", turn_id="submission-1")
    assert _target(tmp_path).read_bytes() == before


def test_no_id_does_not_silently_deduplicate_equal_text(tmp_path):
    assert history.append_turn(tmp_path, "john", "Repeat")
    assert history.append_turn(tmp_path, "john", "Repeat")
    assert len(history.read_history_document(tmp_path)["turns"]) == 2


def test_threaded_appends_and_duplicate_retries_lose_no_turns(tmp_path):
    def append(index):
        return history.append_turn(tmp_path, "john", "Text " + str(index), turn_id="turn-" + str(index))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(append, list(range(40)) * 2))
    assert sum(results) == 40
    turns = history.read_history_document(tmp_path)["turns"]
    assert len(turns) == 40
    assert {turn["turn_id"] for turn in turns} == {"turn-" + str(index) for index in range(40)}


def test_os_lock_is_acquired_released_and_file_is_retained(tmp_path, monkeypatch):
    calls = []
    if os.name == "nt":
        import msvcrt

        original = msvcrt.locking

        def observe(descriptor, operation, size):
            calls.append((operation, size))
            return original(descriptor, operation, size)

        monkeypatch.setattr(msvcrt, "locking", observe)
        expected = [(msvcrt.LK_LOCK, 1), (msvcrt.LK_UNLCK, 1)]
    else:
        import fcntl

        original = fcntl.flock

        def observe(descriptor, operation):
            calls.append(operation)
            return original(descriptor, operation)

        monkeypatch.setattr(fcntl, "flock", observe)
        expected = [fcntl.LOCK_EX, fcntl.LOCK_UN]
    assert history.append_turn(tmp_path, "john", "Locked append")
    assert calls == expected
    assert (_target(tmp_path).parent / "conversation-log.lock").is_file()


def test_read_modify_replace_occurs_inside_process_lock(tmp_path, monkeypatch):
    active = []
    original_replace = history._replace

    @contextmanager
    def fake_lock(_path):
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    def observed_replace(target, payload):
        assert active == [True]
        return original_replace(target, payload)

    monkeypatch.setattr(history, "_process_lock", fake_lock)
    monkeypatch.setattr(history, "_replace", observed_replace)
    assert history.append_turn(tmp_path, "john", "One turn")


def test_atomic_replace_failure_keeps_old_file_and_releases_lock(tmp_path, monkeypatch):
    history.append_turn(tmp_path, "john", "Original")
    before = _target(tmp_path).read_bytes()

    def fail_replace(*_args):
        raise OSError("synthetic replacement failure")

    with monkeypatch.context() as patch:
        patch.setattr(history.os, "replace", fail_replace)
        with pytest.raises(history.ConversationHistoryError) as caught:
            history.append_turn(tmp_path, "steward", "Not committed")
        assert caught.value.committed is False
    assert _target(tmp_path).read_bytes() == before
    assert not list(_target(tmp_path).parent.glob("*.tmp"))
    assert history.append_turn(tmp_path, "steward", "Successful retry")


def test_size_limit_is_explicit_and_preserves_existing_bytes(tmp_path, monkeypatch):
    history.append_turn(tmp_path, "john", "Original")
    before = _target(tmp_path).read_bytes()
    monkeypatch.setattr(history, "MAX_HISTORY_BYTES", len(before) + 20)
    with pytest.raises(history.ConversationHistoryError, match="history_size_limit"):
        history.append_turn(tmp_path, "john", "Large " * 100)
    assert _target(tmp_path).read_bytes() == before


def test_campaign_and_terminal_threads_have_distinct_authorities(tmp_path):
    assert history.read_history_document(tmp_path, thread_id="12") == {"turns": []}
    assert not (tmp_path / ".ecgberht").exists()
    history.append_turn(tmp_path, "john", "Campaign", turn_id="same-id")
    history.append_turn(tmp_path, "john", "Terminal one", thread_id="1", turn_id="same-id")
    history.append_turn(tmp_path, "john", "Terminal two", thread_id="2", turn_id="same-id")
    assert history.read_history_document(tmp_path)["turns"][0]["text"] == "Campaign"
    assert history.read_history_document(tmp_path, thread_id="1")["turns"][0]["text"] == "Terminal one"
    assert history.read_history_document(tmp_path, thread_id="2")["turns"][0]["text"] == "Terminal two"
    assert history.has_history(tmp_path, thread_id="3") is False
    assert not _target(tmp_path, "3").exists()


@pytest.mark.parametrize("thread_id", ["", "../1", "1/2", "1\\2", "1234567", "１", "1.json", 1, True])
def test_invalid_terminal_identity_is_rejected_without_writes(tmp_path, thread_id):
    with pytest.raises(history.ConversationHistoryError, match="invalid_thread_id"):
        history.append_turn(tmp_path, "john", "Unsafe identity", thread_id=thread_id)
    with pytest.raises(history.ConversationHistoryError, match="invalid_thread_id"):
        history.read_history_document(tmp_path, thread_id=thread_id)
    assert not (tmp_path / ".ecgberht").exists()


def _native_transcript(tmp_path, messages):
    import re
    from uuid import UUID

    campaign = tmp_path / "campaign"
    campaign.mkdir()
    native_home = tmp_path / "synthetic-claude-home"
    session = str(UUID(int=500))
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(campaign.resolve()))
    source = native_home / "projects" / slug / (session + ".jsonl")
    source.parent.mkdir(parents=True)
    entries = []
    for index, message in enumerate(messages, 1):
        entries.append({
            "sessionId": session,
            "cwd": str(campaign.resolve()),
            "uuid": str(UUID(int=index)),
            "timestamp": "2026-09-08T01:02:03.456Z",
            **message,
        })
    source.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
    return campaign, native_home, session, source


def test_legacy_import_preserves_dictation_excludes_bootstrap_and_is_idempotent(tmp_path):
    from steward_cockpit.legacy_claude_history import import_legacy_claude

    bootstrap = "Exact engine bootstrap.\nDo not classify this as John."
    dictation = "My original instruction: ∫ résumé 中文 🧮\r\n  " * 150
    campaign, native_home, session, source = _native_transcript(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": bootstrap}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": dictation}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "Not a human instruction"}]}},
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Internal metadata"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "Not user-facing"},
            {"type": "text", "text": "First answer paragraph."},
            {"type": "tool_use", "name": "unused", "input": {}},
            {"type": "text", "text": "Second answer paragraph."},
        ]}},
        {"type": "progress", "data": {"opaque": True}},
    ])
    original = source.read_bytes()
    result = import_legacy_claude(campaign, session, excluded_prompts=(bootstrap,), claude_home=native_home)
    assert result["imported"] == result["eligible"] == 2
    turns = history.read_history_document(campaign)["turns"]
    assert turns[0]["role"] == "john"
    assert turns[0]["text"] == dictation
    assert len(turns[0]["text"]) > 3500
    assert turns[0]["at"] == "2026-09-08T01:02:03.456Z"
    assert turns[0]["turn_id"].startswith("claude:")
    assert turns[0]["source"]["transcript"] == str(source)
    assert turns[1]["role"] == "steward"
    assert turns[1]["text"] == "First answer paragraph.\nSecond answer paragraph."
    assert turns[1]["source"]["text_blocks"] == ["First answer paragraph.", "Second answer paragraph."]
    before_retry = _target(campaign).read_bytes()
    assert import_legacy_claude(campaign, session, excluded_prompts=(bootstrap,), claude_home=native_home)["imported"] == 0
    assert _target(campaign).read_bytes() == before_retry
    assert source.read_bytes() == original


@pytest.mark.parametrize("failure", ["corrupt_last_line", "session_mismatch", "cwd_mismatch", "missing_source"])
def test_legacy_import_validates_entire_exact_source_before_history_write(tmp_path, failure):
    from steward_cockpit.legacy_claude_history import import_legacy_claude
    from uuid import UUID

    campaign, native_home, session, source = _native_transcript(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "Valid first instruction"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "Later answer"}},
    ])
    if failure == "corrupt_last_line":
        source.write_bytes(source.read_bytes() + b"{incomplete")
    elif failure in ("session_mismatch", "cwd_mismatch"):
        entries = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
        if failure == "session_mismatch":
            entries[-1]["sessionId"] = str(UUID(int=999))
        else:
            entries[0]["cwd"] = str(tmp_path.resolve())
        source.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    else:
        source.rename(source.with_suffix(".original.jsonl"))
    original = source.read_bytes() if source.exists() else None
    with pytest.raises(history.ConversationHistoryError):
        import_legacy_claude(campaign, session, claude_home=native_home)
    assert not (campaign / ".ecgberht").exists()
    assert (source.read_bytes() if source.exists() else None) == original


def test_atomic_batch_conflict_does_not_commit_earlier_valid_items(tmp_path):
    history.append_turn(tmp_path, "john", "Existing", turn_id="already-recorded")
    original = _target(tmp_path).read_bytes()
    with pytest.raises(history.ConversationHistoryError, match="turn_id_conflict"):
        history.append_turns(tmp_path, [
            {"role": "john", "text": "Would otherwise append", "at": "native timestamp", "turn_id": "new", "source": {"retained": True}},
            {"role": "john", "text": "Conflicts with existing", "turn_id": "already-recorded"},
        ])
    assert _target(tmp_path).read_bytes() == original
    with pytest.raises(history.ConversationHistoryError, match="invalid_turn_batch"):
        history.append_turns(tmp_path, [
            {"role": "john", "text": "Another valid first item"},
            {"role": "john", "text": None},
        ])
    assert _target(tmp_path).read_bytes() == original

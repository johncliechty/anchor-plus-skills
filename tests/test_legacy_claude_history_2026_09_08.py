"""Hermetic regression tests for recovering native Claude conversation history."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from steward_cockpit.conversation_history import (
    ConversationHistoryError,
    append_turn,
    read_history_document,
)
from steward_cockpit.legacy_claude_history import import_legacy_claude


SESSION_ID = "15729b84-20b4-4d04-8208-6dbba8ee1df7"
OTHER_SESSION_ID = "61076a19-413d-443b-b603-754bba1f669d"
TIMESTAMP = "2026-09-08T14:15:16.123Z"


@pytest.fixture
def legacy_source(tmp_path):
    campaign = (tmp_path / "Synthetic Course").resolve()
    campaign.mkdir()
    claude_home = tmp_path / "synthetic-claude"
    encoded_project = re.sub(r"[^A-Za-z0-9]", "-", str(campaign))
    transcript = (
        claude_home / "projects" / encoded_project / (SESSION_ID + ".jsonl")
    )
    transcript.parent.mkdir(parents=True)
    return SimpleNamespace(
        campaign=campaign,
        claude_home=claude_home,
        transcript=transcript,
        canonical=campaign / ".ecgberht" / "conversation-log.json",
    )


def entry(source, number, role, text, *, cwd=None, session_id=SESSION_ID):
    return {
        "type": role,
        "uuid": f"00000000-0000-4000-8000-{number:012d}",
        "sessionId": session_id,
        "cwd": str(source.campaign if cwd is None else Path(cwd).resolve()),
        "timestamp": TIMESTAMP,
        "message": {
            "role": role,
            "content": [{"type": "text", "text": text}],
        },
    }


def write_entries(source, *entries):
    source.transcript.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in entries),
        encoding="utf-8",
    )


def import_source(source, **kwargs):
    return import_legacy_claude(
        source.campaign,
        SESSION_ID,
        claude_home=source.claude_home,
        **kwargs,
    )


def turns(source, *, thread_id=None):
    return read_history_document(source.campaign, thread_id=thread_id)["turns"]


def test_long_unicode_dictation_is_complete_and_has_native_provenance(legacy_source):
    source = legacy_source
    instruction = (
        "Dictated requirements: α, β, 日本語, café, 🧪. Preserve every instruction.\n"
        * 100
    ) + "FINAL REQUIREMENT: do not replace my existing course materials."
    assert len(instruction) > 3500
    native = entry(source, 1, "user", instruction)
    write_entries(source, native)
    original_transcript = source.transcript.read_bytes()

    result = import_source(source)

    assert result["imported"] == 1
    assert result["eligible"] == 1
    assert result["session_id"] == SESSION_ID
    assert Path(result["source"]) == source.transcript
    recovered = turns(source)
    assert len(recovered) == 1
    assert recovered[0]["role"] == "john"
    assert recovered[0]["text"] == instruction
    assert recovered[0]["at"] == TIMESTAMP
    assert recovered[0]["turn_id"] == "claude:" + native["uuid"]
    provenance = recovered[0]["source"]
    assert provenance["provider"] == "claude"
    assert provenance["session_id"] == SESSION_ID
    assert provenance["entry_uuid"] == native["uuid"]
    assert Path(provenance["transcript"]) == source.transcript
    assert provenance["line"] == 1
    assert provenance["text_blocks"] == [instruction]
    assert provenance["cwd"] == str(source.campaign)
    assert source.transcript.read_bytes() == original_transcript


def test_exact_machine_prompt_is_excluded_but_quoted_dictation_is_preserved(
    legacy_source,
):
    source = legacy_source
    machine_prompt = "Synthetic generated stand-up: introduce the new project."
    dictation = (
        "My actual dictated instruction quotes the old generated prompt: "
        + machine_prompt
        + " Please recover our existing work instead."
    )
    assistant = entry(source, 3, "assistant", "I will preserve the existing work.")
    assistant["message"]["content"].extend(
        [
            {"type": "thinking", "thinking": "Synthetic private reasoning."},
            {
                "type": "tool_use",
                "id": "synthetic-tool",
                "name": "Read",
                "input": {"file_path": "synthetic.txt"},
            },
        ]
    )
    meta = entry(source, 4, "user", "Synthetic transport metadata, not dictation.")
    meta["isMeta"] = True
    write_entries(
        source,
        entry(source, 1, "user", machine_prompt),
        entry(source, 2, "user", dictation),
        assistant,
        meta,
    )
    before = source.transcript.read_bytes()

    result = import_source(source, excluded_prompts=(machine_prompt,))

    assert result["imported"] == 2
    recovered = turns(source)
    assert [(turn["role"], turn["text"]) for turn in recovered] == [
        ("john", dictation),
        ("steward", "I will preserve the existing work."),
    ]
    assert [turn["source"]["line"] for turn in recovered] == [2, 3]
    assert recovered[1]["source"]["text_blocks"] == [
        "I will preserve the existing work."
    ]
    assert source.transcript.read_bytes() == before


def test_same_session_can_change_cwd_after_initial_project_entry(
    legacy_source, tmp_path
):
    source = legacy_source
    skill_folder = (tmp_path / "Synthetic Skill Foundry").resolve()
    skill_folder.mkdir()
    write_entries(
        source,
        entry(source, 1, "user", "Recover these project instructions."),
        entry(source, 2, "assistant", "Inspecting a shared skill.", cwd=skill_folder),
        entry(source, 3, "user", "This is still the same conversation.", cwd=skill_folder),
    )
    before = source.transcript.read_bytes()

    result = import_source(source)

    assert result["imported"] == 3
    recovered = turns(source)
    assert [turn["source"]["cwd"] for turn in recovered] == [
        str(source.campaign),
        str(skill_folder),
        str(skill_folder),
    ]
    assert all(turn["source"]["session_id"] == SESSION_ID for turn in recovered)
    assert recovered[-1]["text"] == "This is still the same conversation."
    assert source.transcript.read_bytes() == before


@pytest.mark.parametrize("invalid_field", ["initial_cwd", "session_id", "entry_uuid"])
def test_wrong_identity_rejects_entire_batch_without_changing_source(
    legacy_source, tmp_path, invalid_field
):
    source = legacy_source
    first = entry(source, 1, "user", "Original project instruction.")
    second = entry(source, 2, "assistant", "Later response.")
    if invalid_field == "initial_cwd":
        other_project = (tmp_path / "Unrelated Project").resolve()
        other_project.mkdir()
        first["cwd"] = str(other_project)
    elif invalid_field == "session_id":
        second["sessionId"] = OTHER_SESSION_ID
    else:
        second["uuid"] = "not-a-valid-native-uuid"
    write_entries(source, first, second)
    before = source.transcript.read_bytes()

    with pytest.raises(ConversationHistoryError):
        import_source(source)

    assert not source.canonical.exists()
    assert source.transcript.read_bytes() == before


@pytest.mark.parametrize("existing_history", [False, True])
def test_malformed_late_entry_cannot_leave_a_partial_import(
    legacy_source, existing_history
):
    source = legacy_source
    if existing_history:
        append_turn(source.campaign, "john", "Already saved canonical instruction.")
    before_canonical = (
        source.canonical.read_bytes() if source.canonical.exists() else None
    )
    first = entry(source, 1, "user", "Valid native instruction before corrupt line.")
    source.transcript.write_text(
        json.dumps(first) + "\n" + '{"type":"assistant","message":\n',
        encoding="utf-8",
    )
    before_source = source.transcript.read_bytes()

    with pytest.raises(ConversationHistoryError):
        import_source(source)

    if before_canonical is None:
        assert not source.canonical.exists()
    else:
        assert source.canonical.read_bytes() == before_canonical
    assert source.transcript.read_bytes() == before_source


def test_duplicate_import_is_idempotent_and_preserves_both_files(legacy_source):
    source = legacy_source
    write_entries(
        source,
        entry(source, 1, "user", "The original instruction."),
        entry(source, 2, "assistant", "The original answer."),
    )
    first_result = import_source(source)
    before_canonical = source.canonical.read_bytes()
    before_source = source.transcript.read_bytes()

    second_result = import_source(source)

    assert first_result["imported"] == 2
    assert second_result["imported"] == 0
    assert len(turns(source)) == 2
    assert source.canonical.read_bytes() == before_canonical
    assert source.transcript.read_bytes() == before_source


def test_conflicting_native_turn_id_blocks_new_turns_atomically(legacy_source):
    source = legacy_source
    original = entry(source, 1, "user", "The original dictated instruction.")
    write_entries(source, original)
    import_source(source)
    before_canonical = source.canonical.read_bytes()
    conflict = entry(source, 1, "user", "Different text with the original UUID.")
    write_entries(
        source,
        entry(source, 2, "assistant", "A new turn that must not be partly imported."),
        conflict,
    )
    before_source = source.transcript.read_bytes()

    with pytest.raises(ConversationHistoryError):
        import_source(source)

    assert source.canonical.read_bytes() == before_canonical
    assert source.transcript.read_bytes() == before_source
    assert [turn["text"] for turn in turns(source)] == [
        "The original dictated instruction."
    ]


def test_numeric_terminal_threads_are_isolated_from_each_other_and_project(
    legacy_source,
):
    source = legacy_source
    append_turn(source.campaign, "john", "Project-scoped canonical instruction.")
    before_project = source.canonical.read_bytes()
    write_entries(source, entry(source, 1, "user", "Terminal seventeen instruction."))

    first_result = import_source(source, thread_id="17")

    first_path = source.campaign / ".ecgberht" / "terminal-history" / "17.json"
    second_path = source.campaign / ".ecgberht" / "terminal-history" / "28.json"
    assert first_result["imported"] == 1
    assert first_path.is_file()
    assert not second_path.exists()
    before_first = first_path.read_bytes()
    assert source.canonical.read_bytes() == before_project

    write_entries(source, entry(source, 2, "user", "Terminal twenty-eight instruction."))
    second_source = source.transcript.read_bytes()
    second_result = import_source(source, thread_id="28")

    assert second_result["imported"] == 1
    assert second_path.is_file()
    assert [turn["text"] for turn in turns(source, thread_id="17")] == [
        "Terminal seventeen instruction."
    ]
    assert [turn["text"] for turn in turns(source, thread_id="28")] == [
        "Terminal twenty-eight instruction."
    ]
    assert first_path.read_bytes() == before_first
    assert source.canonical.read_bytes() == before_project
    assert source.transcript.read_bytes() == second_source

"""Strict, read-only-source migration of one explicitly identified transcript.

There is no transcript discovery or alternate-path fallback. The resulting
conversation-log remains the sole Anchor authority; native originals stay in
place and every imported turn retains its source pointer and original blocks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from uuid import UUID

from .conversation_history import (
    ConversationHistoryError,
    MAX_HISTORY_BYTES,
    _check_path,
    _invalid_constant,
    _object,
    append_turns,
)


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")


def _uuid(value) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise ConversationHistoryError("legacy_claude_uuid_invalid")
    return str(UUID(value))


def import_legacy_claude(
    campaign_dir,
    session_id,
    *,
    thread_id: str | None = None,
    excluded_prompts=(),
    claude_home=None,
) -> dict:
    """Validate the entire selected JSONL, then import all eligible turns once.

    claude_home, when supplied by an isolated test, denotes its synthetic
    .claude directory. User/assistant textual content is retained verbatim;
    multiple text blocks use a newline separator and retain their original
    block strings in metadata. Tool, thinking, and isMeta content is not text.
    """
    session = _uuid(session_id)
    if isinstance(excluded_prompts, str):
        raise ConversationHistoryError("legacy_claude_exclusions_invalid")
    try:
        exclusions = tuple(excluded_prompts)
    except TypeError as exc:
        raise ConversationHistoryError("legacy_claude_exclusions_invalid") from exc
    if any(not isinstance(prompt, str) for prompt in exclusions):
        raise ConversationHistoryError("legacy_claude_exclusions_invalid")
    try:
        campaign = Path(campaign_dir).resolve(strict=True)
        if not campaign.is_dir():
            raise ConversationHistoryError("campaign_directory_required")
        native_home = Path.home() / ".claude" if claude_home is None else Path(claude_home)
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(campaign))
        projects = native_home / "projects"
        project = projects / slug
        source = project / (session + ".jsonl")
        for directory in (native_home, projects, project):
            _check_path(directory, directory=True)
        _check_path(source, directory=False)
        with source.open("rb") as handle:
            before = os.fstat(handle.fileno())
            payload = handle.read(MAX_HISTORY_BYTES + 1)
            after = os.fstat(handle.fileno())
    except ConversationHistoryError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ConversationHistoryError("legacy_claude_source_unavailable") from exc
    if len(payload) > MAX_HISTORY_BYTES:
        raise ConversationHistoryError("legacy_claude_size_limit")
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ConversationHistoryError("legacy_claude_source_changed")
    try:
        # JSONL uses LF delimiters. Unicode U+2028/U+2029 are legal characters
        # inside JSON strings and must not be mistaken for record boundaries.
        lines = payload.decode("utf-8-sig").split("\n")
    except UnicodeError as exc:
        raise ConversationHistoryError("legacy_claude_encoding_invalid") from exc
    turns = []
    initial_cwd_checked = False
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line, object_pairs_hook=_object, parse_constant=_invalid_constant)
        except (ValueError, RecursionError) as exc:
            raise ConversationHistoryError("legacy_claude_json_invalid") from exc
        if not isinstance(entry, dict):
            raise ConversationHistoryError("legacy_claude_entry_invalid")
        if "sessionId" in entry and _uuid(entry["sessionId"]) != session:
            raise ConversationHistoryError("legacy_claude_session_mismatch")
        if "cwd" in entry:
            try:
                cwd = entry["cwd"]
                valid_cwd = isinstance(cwd, str) and Path(cwd).is_absolute()
                matches = valid_cwd and os.path.normcase(str(Path(cwd).resolve())) == os.path.normcase(str(campaign))
            except (OSError, ValueError):
                valid_cwd = matches = False
            # One native session legitimately changes directory to run skills.
            # Anchor identity comes from the exact project/UUID source plus its
            # initial cwd, not a claim that every later command ran at root.
            if not valid_cwd or (not initial_cwd_checked and not matches):
                raise ConversationHistoryError("legacy_claude_cwd_mismatch")
            initial_cwd_checked = True
        role = entry.get("type")
        if role not in ("user", "assistant") or entry.get("isMeta"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role", role) != role:
            raise ConversationHistoryError("legacy_claude_message_invalid")
        content = message.get("content")
        if isinstance(content, str):
            blocks = [content]
        elif isinstance(content, list):
            blocks = []
            for block in content:
                if not isinstance(block, dict):
                    raise ConversationHistoryError("legacy_claude_content_invalid")
                if block.get("type") == "text":
                    if not isinstance(block.get("text"), str):
                        raise ConversationHistoryError("legacy_claude_content_invalid")
                    blocks.append(block["text"])
        else:
            raise ConversationHistoryError("legacy_claude_content_invalid")
        if not blocks:
            continue
        original_blocks = list(blocks)
        joined = "\n".join(blocks)
        if role == "user":
            if joined in exclusions:
                continue
            blocks = [block for block in blocks if block not in exclusions]
            if not blocks:
                continue
            joined = "\n".join(blocks)
        entry_id = _uuid(entry.get("uuid"))
        timestamp = entry.get("timestamp")
        if not isinstance(timestamp, str):
            raise ConversationHistoryError("legacy_claude_timestamp_invalid")
        turns.append({
            "role": "john" if role == "user" else "steward",
            "text": joined,
            "at": timestamp,
            "turn_id": "claude:" + entry_id,
            "source": {
                "provider": "claude",
                "session_id": session,
                "entry_uuid": entry_id,
                "transcript": str(source),
                "line": line_number,
                "text_blocks": original_blocks,
                "cwd": entry.get("cwd"),
            },
        })
    # Recheck the exact selected source immediately before committing its
    # validated snapshot. A live native writer is not silently treated as done.
    try:
        current = source.stat()
    except OSError as exc:
        raise ConversationHistoryError("legacy_claude_source_changed") from exc
    if (current.st_size, current.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ConversationHistoryError("legacy_claude_source_changed")
    imported = append_turns(campaign, turns, thread_id=thread_id)
    return {"imported": imported, "eligible": len(turns), "source": str(source), "session_id": session}

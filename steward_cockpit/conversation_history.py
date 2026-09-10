"""Durable conversation-log appends; no provider transcript is an authority.

Campaign history stays in .ecgberht/conversation-log.json. An explicitly named
numeric terminal thread instead owns .ecgberht/terminal-history/<thread_id>.json.
Readers never create files. Writers serialize with a process RLock and a
persistent OS lock file, then replace the complete JSON document atomically.
The containing project is a trusted writer boundary, not a security sandbox.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading


MAX_HISTORY_BYTES = 64 * 1024 * 1024
_THREAD_LOCK = threading.RLock()
_THREAD_ID = re.compile(r"[0-9]{1,6}\Z")


class ConversationHistoryError(ValueError):
    """An explicit failure, without embedding conversation contents in errors."""

    def __init__(self, code: str, *, committed: bool = False):
        super().__init__(code)
        self.code = code
        # A directory-sync failure may happen after an atomic replacement.
        # A retry with the same turn_id is safe in that case.
        self.committed = committed


def _check_path(path: Path, *, directory: bool) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ConversationHistoryError("history_reparse_path")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ConversationHistoryError("history_path_type_invalid")


def _paths(campaign_dir, thread_id, *, create: bool) -> tuple[Path, Path]:
    if thread_id is not None and (
        not isinstance(thread_id, str) or not _THREAD_ID.fullmatch(thread_id)
    ):
        raise ConversationHistoryError("invalid_thread_id")
    try:
        root = Path(campaign_dir).resolve(strict=True)
        if not root.is_dir():
            raise ConversationHistoryError("campaign_directory_required")
        directory = root / ".ecgberht"
        components = [directory]
        if thread_id is not None:
            directory = directory / "terminal-history"
            components.append(directory)
        for component in components:
            _check_path(component, directory=True)
            if create:
                component.mkdir(mode=0o700, exist_ok=True)
        name = "conversation-log" if thread_id is None else thread_id
        target = directory / (name + ".json")
        lock = directory / (name + ".lock")
        _check_path(target, directory=False)
        _check_path(lock, directory=False)
        return target, lock
    except ConversationHistoryError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ConversationHistoryError("history_path_unavailable") from exc


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConversationHistoryError("history_duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ConversationHistoryError("history_nonfinite_json_value")


def _read(target: Path) -> dict:
    try:
        with target.open("rb") as handle:
            payload = handle.read(MAX_HISTORY_BYTES + 1)
    except FileNotFoundError:
        return {"turns": []}
    except OSError as exc:
        raise ConversationHistoryError("history_read_failed") from exc
    if len(payload) > MAX_HISTORY_BYTES:
        raise ConversationHistoryError("history_size_limit")
    try:
        document = json.loads(
            payload.decode("utf-8-sig"),
            object_pairs_hook=_object,
            parse_constant=_invalid_constant,
        )
    except ConversationHistoryError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ConversationHistoryError("history_json_invalid") from exc
    if not isinstance(document, dict) or not isinstance(document.get("turns"), list):
        raise ConversationHistoryError("history_document_invalid")
    seen = set()
    for turn in document["turns"]:
        if (
            not isinstance(turn, dict)
            or turn.get("role") not in ("john", "steward")
            or not isinstance(turn.get("text"), str)
            or not isinstance(turn.get("at"), str)
        ):
            raise ConversationHistoryError("history_turn_invalid")
        if "turn_id" in turn:
            identity = turn["turn_id"]
            if not isinstance(identity, str) or not identity or identity in seen:
                raise ConversationHistoryError("history_turn_id_invalid")
            seen.add(identity)
    return document


@contextmanager
def _process_lock(lock: Path):
    """The lock file is permanent: unlinking it would split writer exclusion."""
    try:
        descriptor = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise ConversationHistoryError("history_lock_unavailable") from exc
    with os.fdopen(descriptor, "r+b", buffering=0) as handle:
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"\0")
                handle.seek(0)
                # The stdlib's bounded blocking lock raises if still occupied.
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            raise ConversationHistoryError("history_lock_unavailable") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _replace(target: Path, payload: bytes) -> None:
    temporary = None
    committed = False
    try:
        descriptor, name = tempfile.mkstemp(
            prefix="." + target.stem + ".", suffix=".tmp", dir=target.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        committed = True
        # File data is flushed before replacement on both platforms. POSIX
        # additionally exposes a directory fsync through the standard library.
        if os.name != "nt":
            directory_fd = os.open(str(target.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        raise ConversationHistoryError("history_write_failed", committed=committed) from exc
    finally:
        if temporary is not None and not committed:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Do not obscure the original failure or touch the live log.
                pass


def read_history_document(campaign_dir, *, thread_id: str | None = None) -> dict:
    """Return the complete document, or {'turns': []} when this log is absent."""
    with _THREAD_LOCK:
        target, _lock = _paths(campaign_dir, thread_id, create=False)
        return _read(target)


def has_history(campaign_dir, *, thread_id: str | None = None) -> bool:
    """True only for recorded turns; malformed history raises, never hides."""
    return bool(read_history_document(campaign_dir, thread_id=thread_id)["turns"])


def append_turn(
    campaign_dir,
    role: str,
    text: str,
    *,
    at: str | None = None,
    turn_id: str | None = None,
    thread_id: str | None = None,
) -> bool:
    """Append exactly once when turn_id is supplied; never truncate text.

    True means a new turn was written. False means the same ID already has the
    same role/text; its original timestamp and other fields are retained. ID
    reuse with different role/text is an error. Omitting an ID always appends.
    Existing JSON fields are preserved; corrupt or oversized logs fail closed.
    """
    if role not in ("john", "steward") or not isinstance(text, str):
        raise ConversationHistoryError("invalid_turn")
    if at is not None and not isinstance(at, str):
        raise ConversationHistoryError("invalid_turn_timestamp")
    if turn_id is not None and (not isinstance(turn_id, str) or not turn_id):
        raise ConversationHistoryError("invalid_turn_id")
    turn = {"role": role, "text": text}
    if at is not None:
        turn["at"] = at
    if turn_id is not None:
        turn["turn_id"] = turn_id
    return bool(append_turns(campaign_dir, [turn], thread_id=thread_id))


def append_turns(campaign_dir, turns, *, thread_id: str | None = None) -> int:
    """Validate a complete batch, then append it with one lock/read/replace.

    Additional JSON fields on each turn are preserved. Matching IDs are skipped
    using append_turn's role/text semantics. Any invalid item or conflicting ID
    rejects the whole batch, never leaving a partially imported conversation.
    """
    if not isinstance(turns, (list, tuple)):
        raise ConversationHistoryError("invalid_turn_batch")
    prepared = []
    batch_ids = {}
    for item in turns:
        if (
            not isinstance(item, dict)
            or item.get("role") not in ("john", "steward")
            or not isinstance(item.get("text"), str)
            or ("at" in item and not isinstance(item["at"], str))
            or ("turn_id" in item and (not isinstance(item["turn_id"], str) or not item["turn_id"]))
        ):
            raise ConversationHistoryError("invalid_turn_batch")
        try:
            # Detach caller-owned nested metadata and reject non-JSON values
            # before creating history directories or acquiring the file lock.
            encoded = json.dumps(item, ensure_ascii=False, allow_nan=False)
            encoded.encode("utf-8")
            turn = json.loads(encoded)
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise ConversationHistoryError("history_encoding_failed") from exc
        turn.setdefault("at", datetime.now(timezone.utc).isoformat())
        identity = turn.get("turn_id")
        if identity is not None:
            previous = batch_ids.get(identity)
            if previous is not None:
                if (previous["role"], previous["text"]) != (turn["role"], turn["text"]):
                    raise ConversationHistoryError("turn_id_conflict")
                continue
            batch_ids[identity] = turn
        prepared.append(turn)
    with _THREAD_LOCK:
        target, lock = _paths(campaign_dir, thread_id, create=bool(prepared))
        if not prepared:
            return 0
        with _process_lock(lock):
            _check_path(target, directory=False)
            document = _read(target)
            existing_ids = {turn["turn_id"]: turn for turn in document["turns"] if "turn_id" in turn}
            additions = []
            for turn in prepared:
                previous = existing_ids.get(turn.get("turn_id"))
                if previous is not None:
                    if (previous["role"], previous["text"]) != (turn["role"], turn["text"]):
                        raise ConversationHistoryError("turn_id_conflict")
                    continue
                additions.append(turn)
            if not additions:
                return 0
            document["turns"].extend(additions)
            try:
                payload = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise ConversationHistoryError("history_encoding_failed") from exc
            if len(payload) > MAX_HISTORY_BYTES:
                raise ConversationHistoryError("history_size_limit")
            _replace(target, payload)
            return len(additions)

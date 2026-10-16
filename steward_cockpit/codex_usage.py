"""Bounded usage checkpoints from one owned Codex invocation's rollout.

The broker creates this reader before starting its child.  An existing thread
starts at its current EOF; a newly announced thread starts at byte zero.  This
requires one owned invocation to append that exact thread at a time.  The
reader adds no service, thread, storage, pricing or cross-session attribution.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid


POLL_INTERVAL = 5.0
MAX_POLL_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_BASELINE_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
_USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")
_OPTIONAL_KEYS = ("reasoning_output_tokens", "total_tokens")


def _canonical_path(path):
    return os.path.normcase(os.path.realpath(os.path.expanduser(os.fspath(path))))


def _uuid(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None
    return parsed if parsed == value.lower() else None


def _validated_totals(totals):
    if not isinstance(totals, dict):
        return None
    keys = _USAGE_KEYS + tuple(key for key in _OPTIONAL_KEYS if key in totals)
    if any(type(totals.get(key)) is not int or totals[key] < 0 for key in keys):
        return None
    if totals["cached_input_tokens"] > totals["input_tokens"]:
        return None
    if totals.get("reasoning_output_tokens", 0) > totals["output_tokens"]:
        return None
    if "total_tokens" in totals and totals["total_tokens"] != totals["input_tokens"] + totals["output_tokens"]:
        return None
    return {key: totals[key] for key in keys}


def _prefix_field_start(text, wanted):
    """Find an early object field without decoding its unfinished value."""
    decoder = json.JSONDecoder()
    offset = 0
    while offset < len(text) and text[offset].isspace():
        offset += 1
    if offset >= len(text) or text[offset] != "{":
        return None
    offset += 1
    try:
        while offset < len(text):
            while offset < len(text) and text[offset].isspace():
                offset += 1
            key, offset = decoder.raw_decode(text, offset)
            while offset < len(text) and text[offset].isspace():
                offset += 1
            if not isinstance(key, str) or offset >= len(text) or text[offset] != ":":
                return None
            offset += 1
            while offset < len(text) and text[offset].isspace():
                offset += 1
            if key == wanted:
                return offset
            _, offset = decoder.raw_decode(text, offset)
            while offset < len(text) and text[offset].isspace():
                offset += 1
            if offset >= len(text) or text[offset] != ",":
                return None
            offset += 1
    except (ValueError, RecursionError):
        return None
    return None


def _prefix_field(text, field):
    offset = _prefix_field_start(text, field)
    if offset is None:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, offset)
        return value
    except (ValueError, RecursionError):
        return None


def _oversized_non_usage(prefix):
    # Inspect only early JSON field names/types, never transcript contents.
    text = prefix.decode("utf-8", errors="ignore")
    record_type = _prefix_field(text, "type")
    if record_type in {"response_item", "session_meta", "turn_context", "compacted"}:
        return True
    if record_type != "event_msg":
        return False
    offset = _prefix_field_start(text, "payload")
    if offset is None:
        return False
    event_type = _prefix_field(text[offset:], "type")
    return isinstance(event_type, str) and event_type not in {"token_count", "task_started"}


class CodexUsageTracker:
    """Read cumulative checkpoints without summing repeated provider totals."""

    def __init__(self, target, thread_id=None, sessions_root=None, clock=time.monotonic):
        self._clock = clock
        self._target = None
        self._root = None
        self._thread_id = None
        self._path = None
        self._identity = None
        self._offset = 0
        self._pending = bytearray()
        self._skip_line = False
        self._next_discovery = None
        self._discovery_read_bytes = 0
        self._last_poll = None
        self._usage = None
        self._totals = None
        self._resume = thread_id is not None
        self._baseline = None
        self._origin = None
        self._turn_id = None
        self._error = None
        self._blocked = False
        self._changed = False
        try:
            self._target = _canonical_path(target)
            codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
            self._root = Path(sessions_root) if sessions_root is not None else codex_home / "sessions"
            if thread_id is not None:
                self._bind(thread_id, resume=True)
        except Exception:
            self._fail("usage-source-unavailable", block=True)

    def _fail(self, code, *, block=False):
        if self._error is None or (block and self._error != code):
            self._error = code
            self._changed = True
        self._blocked = self._blocked or block

    def _bind(self, thread_id, *, resume):
        identifier = _uuid(thread_id)
        if identifier is None:
            self._fail("usage-session-invalid", block=True)
            return
        if self._thread_id is not None:
            if self._thread_id != identifier:
                self._fail("usage-scope-ambiguous", block=True)
            return
        self._thread_id = identifier
        self._discover(self._clock(), latch_eof=resume)

    def bind(self, thread_id):
        """Bind a new child thread.started identity; never reset an existing one."""
        try:
            self._bind(thread_id, resume=False)
        except Exception:
            self._fail("usage-source-unavailable", block=True)

    def _discover(self, now, *, latch_eof=False):
        if self._path is not None or self._blocked or self._thread_id is None:
            return
        if self._next_discovery is not None and now < self._next_discovery:
            return
        self._next_discovery = now + POLL_INTERVAL
        matches = []
        try:
            for path in self._root.glob(f"*/*/*/*{self._thread_id}.jsonl"):
                if path.is_file():
                    matches.append(path)
                    if len(matches) > 1:
                        self._fail("usage-source-ambiguous", block=True)
                        return
            if not matches:
                if latch_eof:
                    self._fail("usage-resume-baseline-unavailable", block=True)
                return
            path = matches[0]
            with path.open("rb") as source:
                # A partially created metadata line may become valid next poll.
                header = source.readline(MAX_LINE_BYTES)
                self._discovery_read_bytes += len(header)
                if not header.endswith(b"\n"):
                    if latch_eof or len(header) >= MAX_LINE_BYTES:
                        self._fail("usage-session-metadata-invalid", block=True)
                    return
                try:
                    metadata = json.loads(header)
                except (ValueError, UnicodeError, RecursionError):
                    self._fail("usage-session-metadata-invalid", block=True)
                    return
                if not isinstance(metadata, dict) or metadata.get("type") != "session_meta":
                    self._fail("usage-session-metadata-invalid", block=True)
                    return
                payload = metadata.get("payload")
                if not isinstance(payload, dict) or payload.get("id") != self._thread_id:
                    self._fail("usage-session-mismatch", block=True)
                    return
                cwd = payload.get("cwd")
                if not isinstance(cwd, str) or _canonical_path(cwd) != self._target:
                    self._fail("usage-project-mismatch", block=True)
                    return
                stat = os.fstat(source.fileno())
                self._identity = (stat.st_dev, stat.st_ino)
                self._offset = stat.st_size if latch_eof else 0
                if latch_eof and stat.st_size:
                    # Only a bounded prelaunch tail is inspected, and only
                    # validated token counters become accounting evidence.
                    start = max(0, stat.st_size - MAX_BASELINE_BYTES)
                    source.seek(start)
                    tail = source.read(stat.st_size - start)
                    self._discovery_read_bytes += len(tail)
                    lines = tail.split(b"\n")
                    if start:
                        lines = lines[1:]
                    for raw in reversed(lines[:-1]):
                        if not raw or len(raw) > MAX_LINE_BYTES:
                            continue
                        try:
                            item = json.loads(raw)
                        except (ValueError, UnicodeError, RecursionError):
                            continue
                        if not isinstance(item, dict) or item.get("type") != "event_msg":
                            continue
                        event = item.get("payload")
                        if not isinstance(event, dict) or event.get("type") != "token_count":
                            continue
                        info = event.get("info")
                        self._baseline = _validated_totals(info.get("total_token_usage")) if isinstance(info, dict) else None
                        # An invalid latest counter cannot license falling
                        # back to an older value and recrediting the gap.
                        break
                    source.seek(stat.st_size - 1)
                    tail = source.read(1)
                    self._discovery_read_bytes += len(tail)
                    self._skip_line = tail != b"\n"
                self._path = path
        except OSError:
            self._fail("usage-source-unreadable", block=latch_eof)

    def _record(self, raw):
        if not raw.strip() or self._blocked:
            return
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            self._fail("usage-record-malformed")
            return
        if not isinstance(record, dict):
            self._fail("usage-record-malformed")
            return
        if record.get("type") != "event_msg":
            return
        payload = record.get("payload")
        if not isinstance(payload, dict):
            self._fail("usage-record-malformed")
            return
        if payload.get("type") == "task_started":
            turn_id = payload.get("turn_id")
            if isinstance(turn_id, str) and turn_id:
                if self._turn_id is None:
                    self._turn_id = turn_id
                elif self._turn_id != turn_id:
                    self._fail("usage-scope-ambiguous", block=True)
            return
        if payload.get("type") != "token_count":
            return
        info = payload.get("info")
        totals = info.get("total_token_usage") if isinstance(info, dict) else None
        normalized = _validated_totals(totals)
        if normalized is None:
            self._fail("usage-counters-malformed")
            return
        if self._totals is not None and any(normalized[key] < value for key, value in self._totals.items() if key in normalized):
            self._fail("usage-counters-decreased", block=True)
            return
        if self._origin is None:
            zero = {key: 0 for key in _USAGE_KEYS}
            if not self._resume:
                self._origin = zero
            elif self._baseline is None:
                # No safe historical origin: retain future increases only;
                # the authoritative CLI final can reconcile the missing start.
                self._origin = {key: normalized[key] for key in _USAGE_KEYS}
                self._fail("usage-baseline-unavailable")
            else:
                baseline = {key: self._baseline[key] for key in _USAGE_KEYS}
                last = _validated_totals(info.get("last_token_usage"))
                if all(normalized[key] == baseline[key] for key in _USAGE_KEYS):
                    self._origin = baseline
                    if any(baseline.values()):
                        self._fail("usage-counter-origin-ambiguous")
                elif self._turn_id is not None and last is not None and all(normalized[key] == last[key] for key in _USAGE_KEYS):
                    # A first-call total at the new task boundary attests a
                    # reset even when this new call exceeds the old total.
                    self._origin = zero
                elif any(normalized[key] < baseline[key] for key in _USAGE_KEYS):
                    self._origin = zero
                    self._fail("usage-counter-reset")
                else:
                    self._origin = baseline
        usage = {key: normalized[key] - self._origin[key] for key in _USAGE_KEYS}
        if self._error == "usage-baseline-unavailable" and self._usage is None and not any(usage.values()):
            self._totals = normalized
            return
        if usage != self._usage:
            self._usage = usage
            self._changed = True
        self._totals = normalized

    def _consume(self, chunk):
        cursor = 0
        while cursor < len(chunk) and not self._blocked:
            newline = chunk.find(b"\n", cursor)
            end = len(chunk) if newline < 0 else newline
            if self._skip_line:
                if newline < 0:
                    return
                self._skip_line = False
                cursor = newline + 1
                continue
            fragment = chunk[cursor:end]
            if len(self._pending) + len(fragment) > MAX_LINE_BYTES:
                room = MAX_LINE_BYTES - len(self._pending)
                self._pending.extend(fragment[:room])
                if not _oversized_non_usage(self._pending):
                    self._fail("usage-record-too-large")
                self._pending.clear()
                self._skip_line = newline < 0
            else:
                self._pending.extend(fragment)
                if newline >= 0:
                    self._record(self._pending)
                    self._pending.clear()
            if newline < 0:
                return
            cursor = newline + 1

    def _snapshot(self):
        if not self._changed:
            return None
        self._changed = False
        result = {
            "usage": dict(self._usage) if self._usage is not None else None,
            "token_status": "partial" if self._error and self._usage is not None else "unavailable" if self._error else "reported",
            "source": "codex-rollout",
        }
        if self._error:
            result["error"] = self._error
        return result

    def poll(self, force=False):
        """Return a changed cumulative checkpoint, or None; never raise to work."""
        try:
            now = self._clock()
            if self._blocked:
                return self._snapshot()
            if not force and self._last_poll is not None and now - self._last_poll < POLL_INTERVAL:
                return self._snapshot()
            self._last_poll = now
            discovery_before = self._discovery_read_bytes
            self._discover(now)
            if self._path is None or self._blocked:
                return self._snapshot()
            with self._path.open("rb") as source:
                stat = os.fstat(source.fileno())
                if (stat.st_dev, stat.st_ino) != self._identity:
                    self._fail("usage-source-replaced", block=True)
                    return self._snapshot()
                if stat.st_size < self._offset:
                    self._fail("usage-source-truncated", block=True)
                    return self._snapshot()
                source.seek(self._offset)
                remaining = MAX_POLL_BYTES - (self._discovery_read_bytes - discovery_before)
                while remaining > 0 and not self._blocked:
                    chunk = source.read(min(READ_CHUNK_BYTES, remaining))
                    if not chunk:
                        break
                    self._offset += len(chunk)
                    remaining -= len(chunk)
                    self._consume(chunk)
            return self._snapshot()
        except OSError:
            self._fail("usage-source-unreadable")
        except Exception:
            # Usage visibility must never terminate or restart productive work.
            self._fail("usage-source-unavailable", block=True)
        return self._snapshot()

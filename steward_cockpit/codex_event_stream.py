"""Incrementally validate Codex JSONL while projecting fields used by Anchor.

Tool output is hashed, not retained. Assistant text is retained in full. There
is no default event-size ceiling; the optional cap is for explicit callers.
"""

import codecs
import hashlib
import math
import re
from pathlib import Path

SERVED_ROOT = Path(__file__).resolve().parents[1]
_SCAN_CAP = 20000
_OVERFLOW = object()
_LAUNCH = r"(?:python[0-9.]*|py)(?:\.exe)?[\"']?\s+[\"']?"


def names_served(command, root=None):
    """True when a command names Anchor's served folder, or cannot be read (2026-10-08). Only a RUN of the code-job
    launcher is excused - an interpreter followed by its path - never a write to that file."""
    if isinstance(command, (list, tuple)):
        command = " ".join(str(x) for x in command if isinstance(x, str))
    if not isinstance(command, str) or not command.strip() or len(command) > _SCAN_CAP:
        return True
    flat = command.replace("\\\\", "/").replace("\\", "/").lower()
    root = str(root or SERVED_ROOT).replace("\\", "/").lower().rstrip("/")
    spellings = [root]
    if re.match(r"^[a-z]:/", root):                 # Git Bash spells C:/dev/Anchor as /c/dev/anchor (ChatGPT round 4)
        spellings.append("/" + root[0] + root[2:])
    for spelling in spellings:
        flat = re.sub(_LAUNCH + re.escape(spelling) + r"/tools/steward_code_job\.py\b", " ", flat)
    return any(re.search(re.escape(spelling) + r"(?:[^a-z0-9_.-]|$)", flat) for spelling in spellings)


class EventStreamError(ValueError):
    """Invalid or cancelled Codex event input."""


class EventSizeError(EventStreamError):
    """An explicitly configured event-size cap was exceeded."""


_CHUNK_BYTES = 65536
_MAX_DEPTH = 128
_DROP = object()
_STRING_SPECIAL = re.compile(r'["\\\x00-\x1f]')
_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')
_NUMBER_CHARS = frozenset('-+0123456789.eE')
_HEX = frozenset('0123456789abcdefABCDEF')
_ESCAPES = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f',
            'n': '\n', 'r': '\r', 't': '\t'}
_FIELDS = {
    'top': {
        'type': 'id', 'thread_id': 'id', 'model': 'id',
        'model_served': 'id', 'effort_served': 'id',
        'message': 'message', 'code': 'id',
        'usage': 'usage', 'error': 'error', 'item': 'item',
    },
    'item': {
        'id': 'id', 'type': 'id', 'status': 'id', 'exit_code': 'id',
        'text': 'text', 'model': 'id', 'model_served': 'id',
        'effort_served': 'id',
    },
    'usage': {'input_tokens': 'id', 'cached_input_tokens': 'id', 'output_tokens': 'id'},
    'error': {'code': 'id', 'message': 'message'},
    'change': {'path': 'scan'},
}


class _Frame:
    """Keep at most one bounded decoded chunk, without reading the next line."""

    def __init__(self, pipe, cancelled, cap):
        self.pipe = pipe
        self.cancelled = cancelled
        self.cap = cap
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.buffer = ''
        self.pos = 0
        self.raw_bytes = 0
        self.eof = False
        self.line_end = False
        self.digest = None

    def check_cancelled(self):
        if self.cancelled():
            raise EventStreamError('Codex event stream cancelled.')

    def ensure(self):
        while self.pos == len(self.buffer):
            if self.eof or self.line_end:
                return False
            self.check_cancelled()
            chunk = self.pipe.readline(_CHUNK_BYTES)
            self.check_cancelled()
            if not isinstance(chunk, (bytes, bytearray)):
                raise EventStreamError('Codex event input must be a binary stream.')
            self.raw_bytes += len(chunk)
            if self.cap is not None and self.raw_bytes > self.cap:
                raise EventSizeError(
                    'Anchor transport event local size bound exceeded: measured at least '
                    f'{self.raw_bytes} bytes; {self.cap} bytes configured.')
            try:
                if not chunk:
                    self.eof = True
                    decoded = self.decoder.decode(b'', final=True)
                else:
                    self.line_end = chunk.endswith(b'\n')
                    decoded = self.decoder.decode(chunk, final=self.line_end)
            except UnicodeError as exc:
                raise EventStreamError('Invalid UTF-8 in Codex event.') from exc
            self.buffer = decoded
            self.pos = 0
        return True

    def peek(self):
        return self.buffer[self.pos] if self.ensure() else ''

    def take(self, count=1):
        if not self.ensure() or count > len(self.buffer) - self.pos:
            raise EventStreamError('Unexpected end of Codex event.')
        result = self.buffer[self.pos:self.pos + count]
        self.pos += count
        if self.digest is not None:
            self.digest.update(result.encode('utf-8'))
        return result


class _Parser:
    def __init__(self, frame):
        self.frame = frame

    def space(self):
        # JSONL records cannot span physical lines. CR before LF is allowed.
        while self.frame.peek() in (' ', '\t', '\r'):
            self.frame.take()

    def expect(self, char):
        if self.frame.peek() != char:
            raise EventStreamError('Malformed Codex JSON event: expected ' + repr(char) + '.')
        self.frame.take()

    def string(self, mode):
        self.expect('"')
        if mode == 'error':
            mode = 'message'
        retain = mode in ('key', 'id', 'message', 'text', 'scan')
        parts = []
        length = 0
        kept = 0
        pending_high = ''

        def append_piece(piece):
            nonlocal length, kept
            if not retain or not piece:
                return
            length += len(piece)
            if mode == 'id' and length > 256:
                raise EventStreamError('Codex identity/provenance string exceeds 256 characters.')
            limit = 256 if mode == 'key' else (_SCAN_CAP if mode == 'scan' else None)
            if limit is None:
                parts.append(piece)
            elif kept < limit:
                fragment = piece[:limit - kept]
                parts.append(fragment)
                kept += len(fragment)

        def decoded_piece(piece):
            nonlocal pending_high
            if not retain or not piece:
                return
            if pending_high:
                if 0xDC00 <= ord(piece[0]) <= 0xDFFF:
                    append_piece(chr(0x10000 + ((ord(pending_high) - 0xD800) << 10)
                                     + ord(piece[0]) - 0xDC00))
                    piece = piece[1:]
                else:
                    append_piece(pending_high)
                pending_high = ''
            if piece and 0xD800 <= ord(piece[-1]) <= 0xDBFF:
                pending_high = piece[-1]
                piece = piece[:-1]
            append_piece(piece)

        while True:
            if not self.frame.ensure():
                raise EventStreamError('Unterminated Codex JSON string.')
            match = _STRING_SPECIAL.search(self.frame.buffer, self.frame.pos)
            end = match.start() if match else len(self.frame.buffer)
            if end > self.frame.pos:
                decoded_piece(self.frame.take(end - self.frame.pos))
                continue
            char = self.frame.take()
            if char == '"':
                append_piece(pending_high)
                if not retain or (mode == 'key' and length > 256):
                    return _DROP
                if mode == 'scan' and length > _SCAN_CAP:
                    return _OVERFLOW
                return ''.join(parts)
            if char != '\\':
                raise EventStreamError('Unescaped control character in Codex JSON string.')
            escape = self.frame.take()
            if escape in _ESCAPES:
                decoded_piece(_ESCAPES[escape])
            elif escape == 'u':
                digits = ''.join(self.frame.take() for _ in range(4))
                if any(char not in _HEX for char in digits):
                    raise EventStreamError('Invalid Unicode escape in Codex JSON string.')
                decoded_piece(chr(int(digits, 16)))
            else:
                raise EventStreamError('Invalid escape in Codex JSON string.')

    def number(self, retain):
        chars = []
        while self.frame.peek() in _NUMBER_CHARS:
            if len(chars) == 128:
                raise EventStreamError('Codex JSON number token exceeds 128 characters.')
            chars.append(self.frame.take())
        token = ''.join(chars)
        if not _NUMBER.fullmatch(token):
            raise EventStreamError('Malformed number in Codex JSON event.')
        if not retain:
            return _DROP
        if not any(char in token for char in '.eE'):
            return int(token)
        result = float(token)
        if not math.isfinite(result):
            raise EventStreamError('Non-finite number in Codex JSON event.')
        return result

    def value(self, mode='discard', depth=0):
        self.frame.check_cancelled()
        self.space()
        char = self.frame.peek()
        if char == '"':
            return self.string(mode)
        if char == '{':
            return self.object(mode, depth + 1)
        if char == '[':
            return self.array(mode, depth + 1)
        retain = mode in ('id', 'message', 'text')
        if char and char in '-0123456789':
            return self.number(retain)
        for token, result in (('true', True), ('false', False), ('null', None)):
            if char == token[0]:
                for expected in token:
                    self.expect(expected)
                return result if retain else _DROP
        raise EventStreamError('Malformed value in Codex JSON event.')

    def hashed_value(self, depth):
        self.space()
        digest = hashlib.sha256()
        self.frame.digest = digest
        try:
            self.value('discard', depth)
        finally:
            self.frame.digest = None
        return 'sha256:' + digest.hexdigest()

    def object(self, mode, depth):
        if depth > _MAX_DEPTH:
            raise EventStreamError('Codex JSON nesting exceeds 128 levels.')
        self.expect('{')
        fields = _FIELDS.get(mode)
        result = {} if fields is not None else _DROP
        self.space()
        if self.frame.peek() == '}':
            self.frame.take()
            return result
        while True:
            self.space()
            key = self.string('key')
            self.space()
            self.expect(':')
            if mode == 'item' and key == 'aggregated_output':
                result['aggregated_output'] = self.hashed_value(depth)
            elif mode == 'item' and key == 'changes':
                changes = self.value('changes', depth)
                if not isinstance(changes, list):
                    result.pop('_change_count', None)
                    result.pop('changes', None)
                else:
                    result['_change_count'] = len(changes)
                    result['changes'] = [{'path': c['path']} for c in changes[:20]
                                         if isinstance(c, dict) and isinstance(c.get('path'), str)
                                         and 0 < len(c['path']) <= 240]
                    if len(result['changes']) < len(changes):   # cut or unreadable paths: the list is not the whole
                        result['_paths_incomplete'] = True
            elif mode == 'item' and key == 'command':
                # 2026-10-08: the command is read only to answer "does it name Anchor's served folder?" - never kept
                command = self.value('scan', depth)
                result['_names_served'] = names_served(None if command is _OVERFLOW or command is _DROP else command)
            else:
                child_mode = fields.get(key, 'discard') if fields is not None else 'discard'
                child = self.value(child_mode, depth)
                if fields is not None and key in fields:
                    if child is _DROP:
                        result.pop(key, None)
                    else:
                        result[key] = child
            self.space()
            if self.frame.peek() == '}':
                self.frame.take()
                return result
            self.expect(',')

    def array(self, mode, depth):
        if depth > _MAX_DEPTH:
            raise EventStreamError('Codex JSON nesting exceeds 128 levels.')
        self.expect('[')
        count = 0
        kept = [] if mode in ('scan', 'changes') else None
        child = {'scan': 'scan', 'changes': 'change'}.get(mode, 'discard')

        def done():
            if kept is not None:
                return _OVERFLOW if (mode == 'scan' and _OVERFLOW in kept) else kept
            return count if mode == 'count' else _DROP
        self.space()
        if self.frame.peek() == ']':
            self.frame.take()
            return done()
        while True:
            item = self.value(child, depth)
            if kept is not None and len(kept) < 200:
                kept.append(item)
            count += 1
            self.space()
            if self.frame.peek() == ']':
                self.frame.take()
                return done()
            self.expect(',')

    def event(self):
        self.space()
        if self.frame.peek() != '{':
            raise EventStreamError('Each Codex JSONL record must be a nonblank JSON object.')
        result = self.object('top', 1)
        self.space()
        end = self.frame.peek()
        if end == '\n':
            self.frame.take()
            if self.frame.pos != len(self.frame.buffer):
                raise EventStreamError('Unexpected data after Codex JSONL separator.')
        elif end:
            raise EventStreamError('Unexpected data after Codex JSON object.')
        return result


def iter_codex_events(pipe, *, cancelled=lambda: False, max_event_bytes=None):
    """Yield ``(projected_event, raw_byte_count)`` without retaining tool output.

    Counts include the line separator. A final record without LF is accepted.
    Cancellation raises EventStreamError. Explicit size caps include separators;
    no size cap is applied by default to events or the complete stream.
    """
    if max_event_bytes is not None and (
            isinstance(max_event_bytes, bool) or not isinstance(max_event_bytes, int)
            or max_event_bytes < 1):
        raise ValueError('max_event_bytes must be a positive integer or None.')
    while True:
        frame = _Frame(pipe, cancelled, max_event_bytes)
        if not frame.peek() and frame.raw_bytes == 0:
            return
        event = _Parser(frame).event()
        yield event, frame.raw_bytes
        if frame.eof:
            return

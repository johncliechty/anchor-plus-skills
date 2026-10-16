"""Behavioral coverage for the bounded-buffer Codex event projector."""

import hashlib
import io
import json
import unittest

from steward_cockpit.codex_event_stream import (
    EventSizeError,
    EventStreamError,
    iter_codex_events,
)


class TinyPipe:
    def __init__(self, data, chunk=1):
        self.source = io.BytesIO(data)
        self.chunk = chunk
        self.requests = []

    def readline(self, size):
        self.requests.append(size)
        return self.source.readline(min(size, self.chunk))


class GeneratedToolOutput:
    """Produce a large JSON string without ever allocating the whole record."""

    prefix = b'{"item":{"aggregated_output":"'
    suffix = (b'","id":"call-1","type":"command_execution","exit_code":0},'
              b'"type":"item.completed"}\n')

    def __init__(self, size):
        self.remaining = size
        self.prefix_left = self.prefix
        self.suffix_left = self.suffix
        self.reads = 0
        self.largest_request = 0

    def readline(self, size):
        self.reads += 1
        self.largest_request = max(self.largest_request, size)
        if self.prefix_left:
            result = self.prefix_left[:size]
            self.prefix_left = self.prefix_left[size:]
            return result
        if self.remaining:
            count = min(size, self.remaining)
            self.remaining -= count
            return b'x' * count
        result = self.suffix_left[:size]
        self.suffix_left = self.suffix_left[size:]
        return result


class CodexEventStreamTests(unittest.TestCase):
    def test_split_utf8_and_json_escapes_match_json_loads(self):
        cases = [
            json.dumps({'item': {'text': 'café 🙂\n\t"\\/', 'type': 'agent_message'},
                        'type': 'item.completed'}, ensure_ascii=False).encode('utf-8'),
            json.dumps({'item': {'text': '\ud800 X \udc00 🙂', 'type': 'agent_message'},
                        'type': 'item.completed'}, ensure_ascii=True).encode('ascii'),
            b'{"item":{"text":"\\/\\b\\f\\r\\t\\uD83D\\uDE00"},"type":"item.completed"}',
        ]
        for source in cases:
            for chunk in (1, 2, 7):
                with self.subTest(chunk=chunk, source=source):
                    pipe = TinyPipe(source + b'\n', chunk)
                    self.assertEqual(list(iter_codex_events(pipe)),
                                     [(json.loads(source), len(source) + 1)])
                    self.assertTrue(all(size == 65536 for size in pipe.requests))

    def test_generated_output_over_sixteen_mib_is_hashed_without_default_cap(self):
        size = 17 * 1024 * 1024 + 3
        pipe = GeneratedToolOutput(size)
        events = list(iter_codex_events(pipe))
        digest = hashlib.sha256(b'"')
        remaining = size
        while remaining:
            count = min(65536, remaining)
            digest.update(b'x' * count)
            remaining -= count
        digest.update(b'"')
        self.assertEqual(events, [({
            'item': {'aggregated_output': 'sha256:' + digest.hexdigest(),
                     'id': 'call-1', 'type': 'command_execution', 'exit_code': 0},
            'type': 'item.completed',
        }, len(pipe.prefix) + size + len(pipe.suffix))])
        self.assertEqual(pipe.largest_request, 65536)

    def test_complete_assistant_text_is_retained_when_type_arrives_last(self):
        answer = ('Long answer café 🙂 with "quotes" and \\slashes\n' * 4000) + 'THE END'
        source = json.dumps({'item': {'text': answer, 'unknown': [1, {'x': True}],
                                     'type': 'agent_message'},
                             'type': 'item.completed'}, ensure_ascii=False).encode('utf-8')
        event, count = list(iter_codex_events(TinyPipe(source, 257)))[0]
        self.assertEqual(event['item']['text'], answer)
        self.assertNotIn('unknown', event['item'])
        self.assertEqual(count, len(source))

    def test_errors_usage_provenance_and_exact_frame_byte_counts(self):
        first = {
            'type': 'error', 'thread_id': 'thread-1', 'model': 'dynamic-model',
            'model_served': 'served-model', 'effort_served': 'ultra',
            'code': 'ERR', 'message': 'm' * 3000,
            'error': {'code': 'FAIL', 'message': 'e' * 3000, 'ignored': {'x': []}},
            'usage': {'input_tokens': 12, 'cached_input_tokens': 3, 'output_tokens': 7,
                      'unknown': {'cost': 1}},
        }
        second = {'type': 'error', 'error': 's' * 3000}
        first_bytes = json.dumps(first).encode() + b'\r\n'
        second_bytes = json.dumps(second).encode()
        events = list(iter_codex_events(TinyPipe(first_bytes + second_bytes, 11)))
        self.assertEqual([count for _, count in events], [len(first_bytes), len(second_bytes)])
        self.assertEqual(events[0][0], {
            **{key: first[key] for key in ('type', 'thread_id', 'model', 'model_served',
                                         'effort_served', 'code')},
            'message': 'm' * 3000,
            'error': {'code': 'FAIL', 'message': 'e' * 3000},
            'usage': {'input_tokens': 12, 'cached_input_tokens': 3, 'output_tokens': 7},
        })
        self.assertEqual(events[1][0], {'type': 'error', 'error': 's' * 3000})

    def test_changes_are_counted_and_nested_tool_output_is_validated_and_hashed(self):
        raw_value = b'{"data":[true,null,1.25],"text":"\\u00e9"}'
        source = (b'{"item":{"changes":[{"path":"a"},{"path":"b"}],'
                  b'"aggregated_output":' + raw_value +
                  b',"model":"m","model_served":"m2","effort_served":"ultra"}}\n')
        event, _ = next(iter_codex_events(TinyPipe(source, 3)))
        self.assertEqual(event, {'item': {
            '_change_count': 2,
            'changes': [{'path': 'a'}, {'path': 'b'}],   # 2026-10-08: bounded paths kept (the served-code audit)
            'aggregated_output': 'sha256:' + hashlib.sha256(raw_value).hexdigest(),
            'model': 'm', 'model_served': 'm2', 'effort_served': 'ultra',
        }})

    def test_ignored_fields_are_fully_validated(self):
        malformed = [
            b'{"ignored":"\\q"}\n', b'{"ignored":"\\uXYZ0"}\n',
            b'{"ignored":"\xff"}\n', b'{"ignored":"\x00"}\n',
            b'{"ignored":01}\n', b'{"ignored":1e+}\n',
            b'{"ignored":NaN}\n', b'{"ignored":Infinity}\n',
            b'{"ignored":[1,]}\n', b'{"ignored":{"a":1 "b":2}}\n',
            b'{"ignored":"unfinished\n', b'{} trailing\n',
            b'[]\n', b'\n', b'   ', b'{}\n\n', b'{\n"type":"x"}\n',
        ]
        for source in malformed:
            with self.subTest(source=source):
                with self.assertRaises(EventStreamError):
                    list(iter_codex_events(TinyPipe(source, 2)))

    def test_depth_guard_applies_inside_discarded_values(self):
        allowed = b'{"ignored":' + b'[' * 127 + b'0' + b']' * 127 + b'}\n'
        self.assertEqual(list(iter_codex_events(io.BytesIO(allowed))), [({}, len(allowed))])
        excessive = b'{"ignored":' + b'[' * 128 + b'0' + b']' * 128 + b'}\n'
        with self.assertRaisesRegex(EventStreamError, 'nesting'):
            list(iter_codex_events(io.BytesIO(excessive)))

    def test_explicit_size_cap_includes_newline_and_has_no_global_stream_budget(self):
        source = b'{"type":"ok"}\n'
        self.assertEqual(len(list(iter_codex_events(io.BytesIO(source * 10),
                                                   max_event_bytes=len(source)))), 10)
        with self.assertRaises(EventSizeError):
            list(iter_codex_events(io.BytesIO(source), max_event_bytes=len(source) - 1))

    def test_identity_and_number_guards_do_not_truncate_metadata(self):
        with self.assertRaisesRegex(EventStreamError, 'identity/provenance'):
            list(iter_codex_events(io.BytesIO(json.dumps({'thread_id': 't' * 257}).encode())))
        with self.assertRaisesRegex(EventStreamError, 'number token'):
            list(iter_codex_events(io.BytesIO(b'{"ignored":' + b'1' * 129 + b'}')))

    def test_unknown_long_keys_are_discarded_and_duplicate_fields_use_last_value(self):
        source = ('{"' + 'k' * 10000 + '":[1,2],"type":"old","type":"new"}').encode()
        self.assertEqual(list(iter_codex_events(TinyPipe(source, 79))),
                         [({'type': 'new'}, len(source))])

    def test_cancellation_interrupts_an_ignored_payload(self):
        pipe = GeneratedToolOutput(17 * 1024 * 1024)
        with self.assertRaisesRegex(EventStreamError, 'cancelled'):
            list(iter_codex_events(pipe, cancelled=lambda: pipe.reads >= 3))
        self.assertGreater(pipe.remaining, 0)
        self.assertLess(pipe.reads, 10)

    def test_empty_stream_has_no_events(self):
        self.assertEqual(list(iter_codex_events(io.BytesIO(b''))), [])


if __name__ == '__main__':
    unittest.main()

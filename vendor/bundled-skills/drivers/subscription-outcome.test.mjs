import test from 'node:test';
import assert from 'node:assert/strict';
import { classifySubscriptionOutcome } from './subscription-outcome.mjs';

const jsonl = (...frames) => frames.map(frame => JSON.stringify(frame)).join('\n') + '\n';
const thread = { type: 'thread.started', thread_id: 'owned-thread' };
const started = { type: 'turn.started' };
const quota = { type: 'turn.failed', error: { code: 'usage_limit_reached', message: 'Usage limit reached' } };
const auth = { type: 'turn.failed', error: { code: 'authentication_required', message: 'Please log in' } };
const claudeInit = { type: 'system', subtype: 'init', session_id: 'owned-session' };
const claudeError = {
  type: 'result', subtype: 'error_during_execution', is_error: true,
  session_id: 'owned-session',
  num_turns: 0, usage: { input_tokens: 0, output_tokens: 0 }, errors: ['Usage limit reached'],
};
const receipt = (family, stdout, changes = {}) => ({
  family, stdout, stderr: '', code: 1, terminal: 'closed', kill_status: null, spawned: true, ...changes,
});
const codex = (...frames) => receipt('chatgpt', jsonl(...frames));
const claude = (...frames) => receipt('claude', jsonl(...frames));

test('Codex native pre-activity quota rejection and clean close permit replay', () => {
  assert.deepEqual(classifySubscriptionOutcome(codex(thread, started, quota)), {
    failure_status: 'usage_limit', replay_safe: true,
    replay_evidence: 'codex_native_pre_activity_rejection', tools_observed: false,
  });
});

test('Codex authentication rejection can be proven before first turn', () => {
  const actual = classifySubscriptionOutcome(codex(thread, auth));
  assert.equal(actual.failure_status, 'auth_error');
  assert.equal(actual.replay_safe, true);
});

test('recognized native error frame followed by matching turn.failed is accepted', () => {
  const actual = classifySubscriptionOutcome(codex(thread, started,
    { type: 'error', message: "You've hit your usage limit" }, quota));
  assert.equal(actual.replay_safe, true);
});

test('an error without a recognized thread prefix is not replay proof', () => {
  const actual = classifySubscriptionOutcome(codex(quota));
  assert.equal(actual.failure_status, 'usage_limit');
  assert.equal(actual.replay_safe, false);
});

for (const type of ['reasoning', 'agent_message', 'command_execution', 'file_change', 'mcp_tool_call', 'web_search']) {
  test(`every Codex item defeats replay, including ${type}`, () => {
    const actual = classifySubscriptionOutcome(codex(thread, started,
      { type: 'item.completed', item: { id: 'item-1', type, text: 'partial activity' } }, quota));
    assert.equal(actual.replay_safe, false);
    assert.equal(actual.tools_observed, !['reasoning', 'agent_message'].includes(type));
  });
}

test('unknown Codex frames cannot disappear from a replay proof', () => {
  const actual = classifySubscriptionOutcome(codex(thread, { type: 'future.native.operation' }, quota));
  assert.equal(actual.replay_safe, false);
  assert.equal(actual.tools_observed, false); // Observation is not an execution claim.
});

test('unknown fields in pre-activity Codex frames defeat the strict protocol proof', () => {
  for (const frames of [
    [{ ...thread, new_execution_state: 'unrecognized' }, quota],
    [thread, { ...started, unrecognized_output: 'something happened' }, quota],
    [thread, { ...quota, result: 'partial answer' }],
  ]) {
    assert.equal(classifySubscriptionOutcome(codex(...frames)).replay_safe, false);
  }
});

test('repeated or out-of-order lifecycle frames defeat proof', () => {
  for (const frames of [[thread, thread, quota], [thread, started, started, quota], [thread, quota, started, quota]]) {
    assert.equal(classifySubscriptionOutcome(codex(...frames)).replay_safe, false);
  }
});

test('successful output quoting a usage limit is never classified as a quota failure', () => {
  const actual = classifySubscriptionOutcome(codex(thread, started,
    { type: 'item.completed', item: { id: 'answer', type: 'agent_message', text: 'The phrase "Usage limit reached" is illustrative.' } },
    { type: 'turn.completed', usage: { input_tokens: 4, output_tokens: 12 } }));
  assert.equal(actual.replay_safe, false);
  const successful = classifySubscriptionOutcome({ ...codex(thread,
    { type: 'turn.completed' }), code: 0, stderr: 'Usage limit reached' });
  assert.equal(successful.failure_status, null);
  assert.equal(successful.replay_safe, false);
});

test('transient quota followed by actual success is not a failed turn', () => {
  const actual = classifySubscriptionOutcome({ ...codex(thread,
    { type: 'error', message: 'Rate limit exceeded' }, { type: 'turn.completed' }), code: 0 });
  assert.equal(actual.failure_status, null);
  assert.equal(actual.replay_safe, false);
});

test('a non-quota native failure is not upgraded by quoted or embedded quota prose', () => {
  for (const message of ['The document says "Usage limit reached".', 'A tool printed Usage limit reached', 'Unexpected error']) {
    const actual = classifySubscriptionOutcome(codex(thread, { type: 'turn.failed', error: { message } }));
    assert.equal(actual.failure_status, 'cli_error');
    assert.equal(actual.replay_safe, false);
  }
});

test('mixed auth and quota errors are ambiguous rather than a replay proof', () => {
  const actual = classifySubscriptionOutcome(codex(thread, auth, quota));
  assert.equal(actual.replay_safe, false);
});

test('bare stderr quota/auth can classify but never prove no actions', () => {
  for (const [text, expected] of [['Usage limit reached', 'usage_limit'], ['Not logged in', 'auth_error']]) {
    const actual = classifySubscriptionOutcome(receipt('chatgpt', '', { stderr: text }));
    assert.equal(actual.failure_status, expected);
    assert.equal(actual.replay_safe, false);
  }
});

test('malformed, truncated, primitive, and non-finite frames defeat replay', () => {
  const complete = jsonl(thread, quota);
  for (const bad of [
    complete + '{"type":', jsonl(thread) + 'not json\n' + jsonl(quota),
    jsonl(thread) + 'null\n' + jsonl(quota),
    jsonl(thread) + '{"type":"turn.started","tokens":1e999}\n' + jsonl(quota),
  ]) {
    assert.equal(classifySubscriptionOutcome(receipt('chatgpt', bad)).replay_safe, false);
  }
});

test('tools after malformed lines still count as observed', () => {
  const actual = classifySubscriptionOutcome(receipt('chatgpt', jsonl(thread) + 'broken\n' + jsonl(
    { type: 'item.completed', item: { type: 'command_execution' } }, quota)));
  assert.equal(actual.tools_observed, true);
  assert.equal(actual.replay_safe, false);
});

test('Claude init plus explicit zero-turn zero-output quota rejection permits replay', () => {
  assert.deepEqual(classifySubscriptionOutcome(claude(claudeInit, claudeError)), {
    failure_status: 'usage_limit', replay_safe: true,
    replay_evidence: 'claude_native_zero_turn_zero_output_rejection', tools_observed: false,
  });
});

test('Claude zero-turn authentication failure also qualifies', () => {
  const actual = classifySubscriptionOutcome(claude(claudeInit,
    { ...claudeError, errors: ['Not logged in. Please run /login'] }));
  assert.equal(actual.failure_status, 'auth_error');
  assert.equal(actual.replay_safe, true);
});

for (const changes of [
  { num_turns: undefined }, { num_turns: 1 }, { num_turns: '0' }, { num_turns: null },
  { usage: undefined }, { usage: {} }, { usage: { output_tokens: 1 } },
  { usage: { output_tokens: '0' } }, { is_error: undefined }, { subtype: undefined },
  { session_id: undefined }, { session_id: 'different-session' },
  { usage: { output_tokens: Infinity } }, { usage: { output_tokens: NaN } },
  { tool_count: -1 }, { tool_count: '0' }, { tool_count: 0.5 },
  { tool_count: 1 }, { usage: { output_tokens: 0, server_tool_use: { web_search_requests: 1 } } },
  { modelUsage: { 'served-model': { outputTokens: 3 } } },
  { permission_denials: [{ tool_name: 'Write' }] }, { structured_output: { answer: 'partial' } },
  { result: 'Partial work already performed' },
]) {
  test(`Claude rejects missing/nonzero/contradictory metrics ${JSON.stringify(changes)}`, () => {
    assert.equal(classifySubscriptionOutcome(claude(claudeInit, { ...claudeError, ...changes })).replay_safe, false);
  });
}

test('Claude permits error-only result text, not assistant answer text', () => {
  const actual = classifySubscriptionOutcome(claude(claudeInit,
    { ...claudeError, result: 'Usage limit reached' }));
  assert.equal(actual.replay_safe, true);
});

test('every intervening Claude assistant/tool/unknown frame defeats proof', () => {
  const extraFrames = [
    { type: 'assistant', message: { content: [{ type: 'text', text: 'thinking aloud' }] } },
    { type: 'assistant', message: { content: [{ type: 'tool_use', id: 't', name: 'Read' }] } },
    { type: 'user', message: { content: [{ type: 'tool_result', tool_use_id: 't' }] } },
    { type: 'system', subtype: 'hook_started' },
    { type: 'future_unknown_frame' },
  ];
  for (const frame of extraFrames) {
    assert.equal(classifySubscriptionOutcome(claude(claudeInit, frame, claudeError)).replay_safe, false);
  }
});

test('Claude cannot omit init or have duplicate error-result frames', () => {
  assert.equal(classifySubscriptionOutcome(claude(claudeError)).replay_safe, false);
  assert.equal(classifySubscriptionOutcome(claude(claudeInit, claudeError, claudeError)).replay_safe, false);
});

test('successful Claude answer that quotes authentication/quota language is not a failure', () => {
  const actual = classifySubscriptionOutcome(receipt('claude', jsonl(claudeInit, {
    type: 'result', subtype: 'success', is_error: false, result: 'Example: "Not logged in" or "Usage limit reached"',
  }), { code: 0 }));
  assert.equal(actual.failure_status, null);
  assert.equal(actual.replay_safe, false);
});

test('Grok quota is classified but invented zero counters do not authorize replay', () => {
  const actual = classifySubscriptionOutcome(receipt('grok', JSON.stringify({
    type: 'result', is_error: true, stopReason: 'error', num_turns: 0, tool_count: 0,
    usage: { output_tokens: 0 }, errors: ['Usage limit reached'],
  })));
  assert.equal(actual.failure_status, 'usage_limit');
  assert.equal(actual.replay_safe, false);
  assert.equal(actual.replay_evidence, 'grok_native_zero_activity_contract_not_established');
});

test('Grok partial answer and reported tools remain ambiguous', () => {
  const actual = classifySubscriptionOutcome(receipt('grok', JSON.stringify({
    is_error: true, errors: ['Usage limit reached'], result: 'Partial answer',
    messages: [{ type: 'assistant', message: { content: [{ type: 'tool_use', id: 't' }] } }],
  })));
  assert.equal(actual.tools_observed, true);
  assert.equal(actual.replay_safe, false);
});

test('Grok success quoting quota language is not classified as usage exhaustion', () => {
  const actual = classifySubscriptionOutcome(receipt('grok', JSON.stringify({
    is_error: false, stopReason: 'completed', result: 'Quoted example: Usage limit reached',
  }), { code: 0 }));
  assert.equal(actual.failure_status, null);
});

test('Grok accepts only one complete JSON document, not narration or trailing frames', () => {
  for (const text of ['narration\n{"is_error":true}', '{"is_error":true}\n{"extra":true}']) {
    assert.equal(classifySubscriptionOutcome(receipt('grok', text)).replay_safe, false);
  }
});

for (const changes of [
  { spawned: undefined }, { spawned: false }, { terminal: undefined }, { terminal: 'running' },
  { kill_status: undefined }, { kill_status: 'terminated' }, { kill_status: { verified: true } },
  { code: null }, { code: -1 }, { code: Infinity }, { code: NaN }, { code: 0.5 },
]) {
  test(`clean close evidence cannot be inferred: ${JSON.stringify(changes)}`, () => {
    assert.equal(classifySubscriptionOutcome({ ...codex(thread, quota), ...changes }).replay_safe, false);
  });
}

test('timeouts and cancellations never authorize replay, even before spawn', () => {
  for (const terminal of ['aborted', 'cancelled', 'timeout', 'timed_out']) {
    const actual = classifySubscriptionOutcome(receipt('chatgpt', '', { terminal, spawned: false, code: null }));
    assert.equal(actual.replay_safe, false);
    assert.equal(actual.failure_status, ['timeout', 'timed_out'].includes(terminal) ? 'timeout' : 'aborted');
  }
});

test('only an explicit no-launch spawn error can prove safe preflight failure', () => {
  const beforeLaunch = receipt('chatgpt', '', { terminal: 'spawn_error', spawned: false, code: null });
  assert.equal(classifySubscriptionOutcome(beforeLaunch).replay_safe, true);
  assert.equal(classifySubscriptionOutcome(beforeLaunch).replay_evidence, 'explicit_not_spawned_receipt');
  for (const changes of [{ spawned: undefined }, { spawned: true }, { stdout: jsonl(thread) }, { kill_status: 'killed' }]) {
    assert.equal(classifySubscriptionOutcome({ ...beforeLaunch, ...changes }).replay_safe, false);
  }
});

test('oversized and excessively nested native payloads fail closed without throwing', () => {
  const oversized = jsonl(thread) + 'x'.repeat(1024 * 1024 + 1) + '\n' + jsonl(quota);
  assert.equal(classifySubscriptionOutcome(receipt('chatgpt', oversized)).replay_safe, false);
  let nested = {};
  for (let index = 0; index < 80; index += 1) nested = { messages: [nested] };
  assert.equal(classifySubscriptionOutcome(receipt('grok', JSON.stringify(nested))).replay_safe, false);
});

test('unsupported providers and missing receipts cannot authorize replay', () => {
  assert.equal(classifySubscriptionOutcome().replay_safe, false);
  assert.equal(classifySubscriptionOutcome(null).replay_safe, false);
  assert.equal(classifySubscriptionOutcome(receipt('unknown', jsonl(thread, quota))).replay_safe, false);
});

test('classifier does not mutate receipts or nested native data', () => {
  const input = Object.freeze(codex(thread, quota));
  const before = JSON.stringify(input);
  classifySubscriptionOutcome(input);
  assert.equal(JSON.stringify(input), before);
});

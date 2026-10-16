/**
 * Pure classification of subscription CLI receipts. No I/O, retries, or model
 * selection happens here. `tools_observed: false` NEVER means no tools executed.
 *
 * Replay proof requires a complete native transcript AND an explicit clean
 * process receipt: spawned:true, terminal:'closed', kill_status:null, finite
 * nonnegative integer exit code. Text-only failures can classify a limit/auth
 * problem but cannot authorize replay.
 *
 * Codex proof: one thread.started, optional turn.started, then only recognized
 * native quota/auth error/turn.failed frames. Every item (including reasoning),
 * unknown frame, malformed line, success, or contradictory error defeats proof.
 *
 * Claude proof: one system/init, then one native error result with num_turns:0
 * and usage.output_tokens:0, with matching explicit session IDs. These native counters establish zero
 * completed/requested assistant turns; a tool invocation requires an assistant
 * tool_use frame, and every assistant/tool/other frame is disallowed. Absence of
 * tool frames by itself is not proof. Missing/invalid counters defeat proof.
 *
 * Grok's --output-format json has no established authoritative zero-action
 * contract here. It is classified, but is NEVER automatically replay-safe.
 *
 * An explicit spawn_error + spawned:false + empty stdout + no kill receipt can
 * prove no launch. Aborts/timeouts never grant replay, even with spawned:false.
 */

const MAX_OUTPUT_BYTES = 8 * 1024 * 1024;
const MAX_FRAME_BYTES = 1024 * 1024;
const MAX_FRAMES = 10000;

const USAGE_CODES = new Set([
  'usage_limit', 'usage_limit_reached', 'usage_limit_exceeded',
  'quota_exceeded', 'quota_exhausted', 'insufficient_quota',
  'rate_limit_error', 'rate_limit_exceeded', 'rate_limited', 'too_many_requests',
  'credit_balance_too_low',
]);
const AUTH_CODES = new Set([
  'authentication_error', 'authentication_required', 'authentication_failed',
  'unauthenticated', 'unauthorized', 'not_authenticated', 'login_required',
  'session_expired', 'invalid_authentication', 'invalid_api_key',
]);

const USAGE_TEXT = /^(?:error:\s*)?(?:you(?:['’]ve| have) (?:hit|reached|exceeded) (?:your|the) (?:usage |rate )?limit|you (?:have )?(?:hit|reached|exceeded) your (?:usage |rate )?limit|you(?:['’]re| are) out of (?:extra )?usage|(?:claude ai )?usage limit (?:reached|exceeded)|rate limit (?:reached|exceeded)|too many requests|insufficient (?:quota|credits)|quota (?:exceeded|exhausted)|credit balance (?:is )?too low)\b/i;
const AUTH_TEXT = /^(?:error:\s*)?(?:not logged in|authentication (?:required|failed)|failed to authenticate|login required|please (?:log|sign) in|your (?:login )?session has expired|invalid authentication credentials|unauthorized(?: request)?)\b/i;

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const integer = value => typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value);
const zero = value => integer(value) && value === 0;
const nonempty = value => typeof value === 'string' && value.trim().length > 0;

function byteLength(value) {
  // TextEncoder is standard JavaScript; no Buffer, filesystem, or process API.
  return new TextEncoder().encode(value).length;
}

function finiteTree(value, depth = 0) {
  if (depth > 64) return false;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(entry => finiteTree(entry, depth + 1));
  if (object(value)) return Object.values(value).every(entry => finiteTree(entry, depth + 1));
  return true;
}

function category(value) {
  if (typeof value === 'string') {
    const text = value.trim();
    if (USAGE_TEXT.test(text)) return 'usage_limit';
    if (AUTH_TEXT.test(text)) return 'auth_error';
    return null;
  }
  if (!object(value)) return null;
  if (typeof value.code === 'string') {
    const code = value.code.toLowerCase();
    if (USAGE_CODES.has(code)) return 'usage_limit';
    if (AUTH_CODES.has(code)) return 'auth_error';
  }
  return category(value.message);
}

function errorCategories(frame) {
  const values = [];
  if (frame.error !== undefined) values.push(frame.error);
  if (Array.isArray(frame.errors)) values.push(...frame.errors);
  if (frame.message !== undefined) values.push(frame.message);
  if (frame.code !== undefined) values.push({ code: frame.code });
  if (typeof frame.result === 'string' && frame.result.trim()) values.push(frame.result);
  return values.map(category).filter(Boolean);
}

function positiveToolCounter(value, depth = 0) {
  if (!object(value) || depth > 8) return false;
  for (const [key, entry] of Object.entries(value)) {
    if (['num_tool_uses', 'tool_count', 'tool_use_count', 'web_search_requests', 'web_fetch_requests'].includes(key)
        && typeof entry === 'number' && Number.isFinite(entry) && entry > 0) return true;
    if (['tool_calls', 'toolCalls', 'tool_uses', 'toolUses'].includes(key)
        && Array.isArray(entry) && entry.length > 0) return true;
    if (['usage', 'server_tool_use'].includes(key) && positiveToolCounter(entry, depth + 1)) return true;
  }
  return false;
}

function toolsInFrame(frame, depth = 0) {
  if (!object(frame) || depth > 64) return false;
  if (['tool_use', 'tool_result'].includes(frame.type)) return true;
  if (object(frame.item) && [
    'command_execution', 'file_change', 'mcp_tool_call', 'web_search', 'tool_call', 'tool_use',
  ].includes(frame.item.type)) return true;
  if (Array.isArray(frame.message?.content) && frame.message.content.some(block =>
    object(block) && ['tool_use', 'tool_result'].includes(block.type))) return true;
  if (positiveToolCounter(frame)) return true;
  return Array.isArray(frame.messages) && frame.messages.some(entry => toolsInFrame(entry, depth + 1));
}

function onlyKeys(frame, allowed) {
  return Object.keys(frame).every(key => allowed.includes(key));
}

function contradictoryOutput(value, depth = 0) {
  if (!object(value) || depth > 64) return false;
  return Object.entries(value).some(([key, entry]) =>
    (['output_tokens', 'outputTokens'].includes(key) && !zero(entry))
    || (object(entry) && contradictoryOutput(entry, depth + 1)));
}

function contradictoryToolCounter(value, depth = 0) {
  if (!object(value) || depth > 64) return false;
  return Object.entries(value).some(([key, entry]) =>
    (['num_tool_uses', 'tool_count', 'tool_use_count', 'web_search_requests', 'web_fetch_requests'].includes(key)
      && !zero(entry))
    || (['tool_calls', 'toolCalls', 'tool_uses', 'toolUses'].includes(key)
      && (!Array.isArray(entry) || entry.length > 0))
    || (object(entry) && contradictoryToolCounter(entry, depth + 1)));
}

function parseFrames(stdout, family) {
  if (typeof stdout !== 'string' || byteLength(stdout) > MAX_OUTPUT_BYTES) {
    return { frames: [], valid: false };
  }
  const pieces = family === 'grok' ? (stdout.trim() ? [stdout.trim()] : [])
    : stdout.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (pieces.length > MAX_FRAMES) return { frames: [], valid: false };
  const frames = [];
  let valid = pieces.length > 0;
  for (const piece of pieces) {
    if (byteLength(piece) > MAX_FRAME_BYTES) { valid = false; continue; }
    try {
      const frame = JSON.parse(piece);
      if (!object(frame) || !finiteTree(frame)) valid = false;
      if (object(frame)) frames.push(frame);
    } catch {
      valid = false;
    }
  }
  return { frames, valid };
}

function inspectCodex(frames) {
  let phase = 'start';
  let allowed = true;
  let terminal = false;
  let success = false;
  let activity = false;
  const categories = [];
  for (const frame of frames) {
    switch (frame.type) {
      case 'thread.started':
        if (phase !== 'start' || !nonempty(frame.thread_id)
            || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(frame.thread_id)
            || !onlyKeys(frame, ['type', 'thread_id'])) allowed = false;
        phase = 'thread';
        break;
      case 'turn.started':
        if (phase !== 'thread' || !onlyKeys(frame, ['type'])) allowed = false;
        phase = 'turn';
        break;
      case 'error':
      case 'turn.failed': {
        if (!['thread', 'turn', 'failed'].includes(phase)) allowed = false;
        if (!onlyKeys(frame, ['type', 'error', 'message', 'code'])) allowed = false;
        const found = errorCategories(frame);
        if (!found.length) allowed = false;
        categories.push(...found);
        terminal = true;
        phase = 'failed';
        break;
      }
      case 'turn.completed':
        success = true;
        terminal = true;
        allowed = false;
        phase = 'completed';
        break;
      default:
        if (typeof frame.type === 'string' && frame.type.startsWith('item.')) activity = true;
        allowed = false;
    }
  }
  const unique = [...new Set(categories)];
  return {
    success, terminal, activity, categories,
    proof: allowed && phase === 'failed' && unique.length === 1,
    evidence: 'codex_native_pre_activity_rejection',
  };
}

function inspectClaude(frames) {
  const init = frames[0];
  const result = frames[1];
  const success = frames.some(frame => frame.type === 'result' && frame.is_error === false
    && !(typeof frame.subtype === 'string' && frame.subtype.startsWith('error')));
  const failures = frames.filter(frame => frame.type === 'result' &&
    (frame.is_error === true || (typeof frame.subtype === 'string' && frame.subtype.startsWith('error'))));
  const categories = failures.flatMap(errorCategories);
  const unique = [...new Set(categories)];
  const resultIsError = object(result) && result.type === 'result' && result.is_error === true
    && typeof result.subtype === 'string' && result.subtype.startsWith('error');
  const noAnswer = !nonempty(result?.result) || category(result.result) === unique[0];
  const proof = frames.length === 2 && init?.type === 'system' && init.subtype === 'init'
    && nonempty(init.session_id) && result?.session_id === init.session_id
    && resultIsError && zero(result.num_turns) && zero(result.usage?.output_tokens)
    && !contradictoryToolCounter(result) && !contradictoryOutput(result.usage)
    && !contradictoryOutput(result.modelUsage)
    && (!Array.isArray(result.permission_denials) || result.permission_denials.length === 0)
    && (result.structured_output === undefined || result.structured_output === null)
    && unique.length === 1 && noAnswer;
  return {
    success, terminal: frames.some(frame => frame.type === 'result'), categories,
    activity: frames.some(frame => ['assistant', 'user', 'tool_use', 'tool_result'].includes(frame.type)),
    proof, evidence: 'claude_native_zero_turn_zero_output_rejection',
  };
}

function inspectGrok(frames) {
  const result = frames[0];
  const isError = object(result) && (result.is_error === true || result.stopReason === 'error'
    || result.stop_reason === 'error' || (typeof result.subtype === 'string' && result.subtype.startsWith('error')));
  const success = object(result) && !isError && (result.is_error === false ||
    ['completed', 'success', 'end_turn'].includes(result.stopReason));
  return {
    success, terminal: object(result) && (isError || success),
    categories: isError ? errorCategories(result) : [],
    activity: frames.some(frame => toolsInFrame(frame)), proof: false,
    evidence: 'grok_native_zero_activity_contract_not_established',
  };
}

/**
 * @param {{family:string,stdout:string,stderr:string,code:number|null,
 *   terminal:string,kill_status:unknown,spawned?:boolean}} receipt
 * @returns {{failure_status:string|null,replay_safe:boolean,
 *   replay_evidence:string,tools_observed:boolean}}
 */
export function classifySubscriptionOutcome(receipt = {}) {
  const input = object(receipt) ? receipt : {};
  const { family, stdout, stderr, code, terminal, kill_status, spawned } = input;
  const parsed = parseFrames(stdout, family);
  const tools_observed = parsed.frames.some(frame => toolsInFrame(frame));
  const outcome = (failure_status, replay_safe, replay_evidence) => ({
    failure_status, replay_safe, replay_evidence, tools_observed,
  });

  if (terminal === 'aborted' || terminal === 'cancelled') {
    return outcome('aborted', false, 'aborted_terminal_is_not_replay_proof');
  }
  if (terminal === 'timeout' || terminal === 'timed_out') {
    return outcome('timeout', false, 'timeout_terminal_is_not_replay_proof');
  }
  if (terminal === 'spawn_error') {
    const safe = spawned === false && kill_status === null && typeof stdout === 'string'
      && stdout.trim() === '' && (code === null || code === undefined || integer(code));
    return outcome('spawn_error', safe, safe ? 'explicit_not_spawned_receipt' : 'spawn_failure_without_no_launch_proof');
  }

  let inspection;
  if (family === 'chatgpt') inspection = inspectCodex(parsed.frames);
  else if (family === 'claude') inspection = inspectClaude(parsed.frames);
  else if (family === 'grok') inspection = inspectGrok(parsed.frames);
  else return outcome('protocol_error', false, 'unsupported_subscription_family');

  // A provider can report a transient error and then finish successfully. Never
  // mistake successful answer text (including quoted limits) for a failed turn.
  const clean = terminal === 'closed' && kill_status === null && spawned === true && integer(code) && code >= 0;
  if (inspection.success && code === 0 && clean && parsed.valid) {
    return outcome(null, false, 'successful_completion_does_not_authorize_replay');
  }
  const nativeCategories = [...new Set(inspection.categories)];
  const nativeFailure = nativeCategories.length === 1 ? nativeCategories[0] : null;
  const stderrFailure = integer(code) && code !== 0 && typeof stderr === 'string'
    ? stderr.split(/\r?\n/).slice(0, 16).map(category).find(Boolean) : null;
  const failure = nativeFailure || stderrFailure || (!parsed.valid || !inspection.terminal
    ? 'protocol_error' : 'cli_error');

  if (!clean) return outcome(failure, false, 'missing_or_unclean_process_close_receipt');
  if (!parsed.valid) return outcome(failure, false, 'malformed_or_incomplete_native_transcript');
  if (tools_observed || inspection.activity) return outcome(failure, false, 'native_activity_defeats_replay_proof');
  if (nativeCategories.length !== 1) return outcome(failure, false, 'no_unambiguous_native_rejection');
  if (!inspection.proof) return outcome(failure, false, family === 'grok'
    ? inspection.evidence : 'native_transcript_does_not_prove_zero_activity');
  return outcome(nativeFailure, true, inspection.evidence);
}

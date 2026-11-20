// drivers/gemini-cli.mjs — Gemini subscription CLI backend (`agy` 1.3+ stream-json).
// Streams NDJSON over stdin/stdout (`--input-format stream-json --output-format stream-json -p=`),
// passes `--print-timeout`, enforces a stream-idle watchdog (`180s` default, reset on any
// stdout/reasoning frame), and resolves cleanly after a short grace window (`1500ms`) once a
// terminal `{"event":"result", ...}` frame arrives so a lingering `agy` child never hangs 60m.

import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { extractJson } from './claude.mjs';
import { isVerificationRole, normalizeRole } from './roles.mjs';
import { runCliSchemaAttempts } from './cli-schema.mjs';
import { runCloseBoundProcess } from './subscription-process.mjs';
import { resolveModelPolicy, policyEnvironment, modelLaunchArgs } from './model-policy.mjs';

export const GEMINI_CLI_BASE_ARGS = [];
export const GEMINI_HEAVY_MODEL = 'Gemini 3.1 Pro (High)';
export const GEMINI_STANDARD_MODEL = 'Gemini 3.5 Flash (Medium)';
export const DEFAULT_GEMINI_CLI_MODEL = GEMINI_HEAVY_MODEL;
export const DEFAULT_GEMINI_APPROVAL_MODE = 'auto_edit';
export const DEFAULT_GEMINI_TIMEOUT_MS = 25 * 60 * 1000;
export const DEFAULT_GEMINI_IDLE_TIMEOUT_MS = 180 * 1000;
export const DEFAULT_GEMINI_RESULT_GRACE_MS = 1500;
export const OVERSIZE_PROMPT_ARGV_BYTES = 28000;

export const READONLY_ROLES = new Set([
  'review', 'reviewer', 'shark', 'judge', 'synthesizer', 'synth', 'research', 'researcher', 'plan', 'planner',
]);
const EDIT_ROLES = new Set(['execute', 'exec', 'fix', 'build', 'builder']);

const STEER = `TOOL POLICY (MANDATORY): Use ONLY your in-process file tools — read_file, ` +
  `list_directory, glob, search/grep, and (for edit tasks) write/edit file. Do NOT use the ` +
  `shell / terminal / run_shell_command tool for ANY reason — no git, python, node, grep, ` +
  `pytest, ls, cat, etc. On Windows agy opens a VISIBLE PowerShell window for every shell ` +
  `call, which steals the user's keyboard focus, so shell use is forbidden here. If a step ` +
  `seems to need a shell, do it with the file tools instead, or state plainly that it needs ` +
  `a shell — the human operator runs all shell / test / git / build commands. Stay file-tools-only.\n\n---\n\n`;

const norm = (s) => String(s ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
const modelsEqual = (a, b) => norm(a) === norm(b);
const reEscape = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

export const KNOWN_AGY_LABELS = new Set(['Gemini 3.1 Pro (High)', 'Gemini 3.5 Flash (Medium)']);
const KNOWN_AGY_LABELS_NORM = new Set([...KNOWN_AGY_LABELS].map(norm));

function familyFromModel(m) {
  const s = String(m ?? '');
  if (!s) return null;
  const t = s.trim().toLowerCase();
  if (t.startsWith('gemini')) return 'gemini';
  if (t.startsWith('claude')) return 'claude';
  return s.split(/[\s\-]/)[0].toLowerCase() || null;
}

export function approvalModeFor({ approvalMode, role, label } = {}) {
  if (approvalMode) return approvalMode;
  const key = normalizeRole({ role, label });
  if (READONLY_ROLES.has(key)) return 'plan';
  if (EDIT_ROLES.has(key)) return 'auto_edit';
  return DEFAULT_GEMINI_APPROVAL_MODE;
}

export function isReadonlyRole({ role, label } = {}) {
  const key = normalizeRole({ role, label });
  return isVerificationRole({ role: key, label }) || READONLY_ROLES.has(key);
}

const TIER_GEMINI_MODELS = {
  heavy: GEMINI_HEAVY_MODEL,
  standard: GEMINI_STANDARD_MODEL,
};

export function resolveGeminiModel({ model, role, env = process.env } = {}) {
  if (model) return model;
  const tier = String(env.TRIO_TIER || '').trim().toLowerCase();
  if (tier && TIER_GEMINI_MODELS[tier]) return TIER_GEMINI_MODELS[tier];
  const roleKey = role ? `TRIO_MODEL_${String(role).toUpperCase()}` : null;
  return (
    (roleKey && env[roleKey]) ||
    env.TRIO_MODEL ||
    env.GEMINI_MODEL ||
    DEFAULT_GEMINI_CLI_MODEL
  );
}

// Pure compatibility shims retained for existing unit tests in gemini-cli.test.mjs.
export function buildGeminiCliArgs({
  prompt = '', promptFile = null, logPath, model,
  target = process.cwd(), readonly = false, timeoutMs = DEFAULT_GEMINI_TIMEOUT_MS,
} = {}) {
  const argvPrompt = promptFile
    ? STEER + `Your ENTIRE task prompt is in the UTF-8 file ${promptFile} — read that file NOW with your ` +
      `in-process file-read tool and follow its contents EXACTLY as if it were this message. ` +
      `Do not summarize it back; execute it and reply as it instructs.`
    : prompt;
  const args = ['-p', argvPrompt, '--log-file', logPath, '--model', model ?? DEFAULT_GEMINI_CLI_MODEL];
  const secs = timeoutMs > 0 ? Math.max(60, Math.floor((timeoutMs * 0.95) / 1000)) : 60;
  args.push('--print-timeout', `${secs}s`);
  if (!readonly) {
    args.push('--sandbox', '--add-dir', target);
    if (promptFile) args.push('--add-dir', path.dirname(promptFile));
  }
  return args;
}

export function finalTextFromTranscript(pathOrText, { isText = false } = {}) {
  let raw = '';
  if (isText) raw = String(pathOrText ?? '');
  else if (pathOrText && existsSync(pathOrText)) {
    try { raw = readFileSync(pathOrText, 'utf8'); } catch { return ''; }
  } else return '';
  let last = '';
  for (const line of raw.split('\n')) {
    const s = line.trim();
    if (!s) continue;
    let o; try { o = JSON.parse(s); } catch { continue; }
    if (o && o.source === 'MODEL' && typeof o.content === 'string' && o.content.trim()) last = o.content.trim();
  }
  return last;
}

export function shouldStopAttestationPoll({ cliWindow, requested, elapsedMs, graceMs = 2000 } = {}) {
  if (typeof cliWindow === 'string' &&
      (/Failed to resolve model flag/i.test(cliWindow) ||
       /Propagating selected model override to backend:/i.test(cliWindow))) {
    return 'substitution-evidence';
  }
  if (requested && KNOWN_AGY_LABELS_NORM.has(norm(requested)) &&
      typeof cliWindow === 'string' && elapsedMs >= graceMs) {
    return 'known-label-clean';
  }
  return null;
}

export function servedModelFromCliLog(cliLogWindow, { requested = null } = {}) {
  if (typeof cliLogWindow !== 'string') return { served: null, substituted: false };
  if (requested) {
    const failedRe = new RegExp(`Failed to resolve model flag\\s+${reEscape(requested)}`, 'i');
    if (failedRe.test(cliLogWindow)) {
      const overrides = [...cliLogWindow.matchAll(/Propagating selected model override to backend:\s*label="([^"]+)"/g)];
      const served = overrides.length ? overrides[overrides.length - 1][1].trim() : null;
      return { served, substituted: true };
    }
  }
  if (requested && KNOWN_AGY_LABELS_NORM.has(norm(requested))) {
    return { served: requested, substituted: false };
  }
  return { served: null, substituted: false };
}

export function parseGeminiCliFrames(replyText, {
  label = '(unlabeled)', cli_status = null, requested_model = null,
  served_model = null, substituted = false,
} = {}) {
  const text = String(replyText ?? '').trim();
  const transportOk = cli_status === 0;
  const rec = {
    label,
    cli_status,
    ok: transportOk && text.length > 0,
    status: transportOk ? (text.length > 0 ? 'success' : 'no_reply') : 'cli_error',
    duration_ms: null,
    tools: 0,
    output_tokens: null,
    input_tokens: null,
    total_tokens: null,
    cost_usd: null,
    requested_model,
    model_served: null,
    model_family: transportOk ? 'gemini' : null,
    model_attested: false,
    degraded: true,
    multi_model: false,
    family_attested: transportOk,
  };
  if (substituted) {
    const attested = typeof served_model === 'string' && served_model.trim().length > 0;
    const servedFamily = attested ? familyFromModel(served_model) : null;
    rec.model_served = attested ? served_model : null;
    rec.model_family = ['claude', 'gemini', 'grok', 'chatgpt'].includes(servedFamily) ? servedFamily : null;
    rec.family_attested = rec.model_family !== null;
    rec.model_attested = attested;
    rec.degraded = !attested;
    rec.ok = false;
    rec.status = 'model_substituted';
  } else if (typeof served_model === 'string' && served_model.length > 0
             && requested_model && modelsEqual(served_model, requested_model)) {
    rec.model_served = served_model;
    rec.model_family = familyFromModel(served_model);
    rec.model_attested = true;
    rec.degraded = false;
  } else {
    rec.model_served = null;
    rec.model_family = null;
    rec.model_attested = false;
    rec.ok = false;
    rec.status = 'unattested_model';
  }
  return { text, rec };
}

/** Deterministic `agy` subscription auth preflight (`agy models`). */
export function preflightGeminiSubscription({
  cmd = null,
  env = process.env,
  platform = process.platform,
  spawnSyncImpl = spawnSync,
} = {}) {
  const command = cmd || agyCommand(platform, env);
  const run = spawnSyncImpl(command, ['models'], {
    env: Object.assign({}, policyEnvironment(env), { NO_COLOR: '1', CI: '1' }),
    shell: false, windowsHide: true, encoding: 'utf8', timeout: 15_000,
  });
  const detail = `${run?.error?.message || ''}\n${run?.stdout || ''}\n${run?.stderr || ''}`.trim();
  if (run?.error?.code === 'ETIMEDOUT') {
    return { ok: false, status: 'preflight_timeout', subscription_auth: null, replay_safe: true, error: detail.slice(0, 300) };
  }
  if (run?.error || run?.status == null) {
    return { ok: false, status: 'spawn_error', subscription_auth: null, replay_safe: true, error: detail.slice(0, 300) };
  }
  if (/not logged in|login required|authentication|please (?:log|sign) in|oauth.*expired|unauthenticated/i.test(detail)) {
    return {
      ok: false, status: 'auth_expired', login_required: true,
      subscription_auth: false, replay_safe: true,
      error: detail.slice(0, 300) || 'Antigravity CLI login required',
    };
  }
  if (run.status !== 0 || !/\bgemini-/i.test(String(run.stdout || ''))) {
    return {
      ok: false, status: 'auth_expired', login_required: true,
      subscription_auth: false, replay_safe: true,
      error: detail.slice(0, 300) || 'Antigravity CLI did not advertise authenticated Gemini models',
    };
  }
  return { ok: true, status: 'ready', subscription_auth: true };
}

/** agy 1.3.x headless argv: NDJSON over stdin (`-p=`), optional `--print-timeout`. */
export function buildAgyStreamArgs({ model, readonly = false, timeoutMs = 0 } = {}) {
  const args = ['--input-format', 'stream-json', '--output-format', 'stream-json', '--model', model];
  if (readonly) args.push('--mode', 'plan');
  if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
    const secs = Math.max(5, Math.floor((timeoutMs * 0.95) / 1000));
    args.push('--print-timeout', `${secs}s`);
  }
  args.push('-p=');
  return args;
}

export function agyStreamInput(prompt) {
  return JSON.stringify({ event: 'user', message: { role: 'user', content: String(prompt ?? '') } }) + '\n';
}

export function agyCommand(platform = process.platform, env = process.env) {
  if (platform !== 'win32') return 'agy';
  const local = env.LOCALAPPDATA ? path.join(env.LOCALAPPDATA, 'agy', 'bin', 'agy.exe') : null;
  return local && existsSync(local) ? local : 'agy.exe';
}

/** True once stdout contains a parseable terminal `{"event":"result", ...}` JSON line. */
export function hasAgyTerminalResult(stdout) {
  const raw = String(stdout ?? '');
  if (!raw.includes('"result"')) return false;
  for (const line of raw.split('\n')) {
    const s = line.trim();
    if (!s || !s.includes('"result"')) continue;
    try {
      const ev = JSON.parse(s);
      if (ev && ev.event === 'result' && ev.result && typeof ev.result === 'object') return true;
    } catch { /* partial line */ }
  }
  return false;
}

/** agy stream-json stdout -> { status, text, model, conversation_id, usage, error, tools, duration_seconds, hasResult }. */
export function parseAgyStream(stdout) {
  const out = {
    status: null, text: '', model: null, conversation_id: null, usage: null, error: '',
    tools: 0, duration_seconds: null, hasResult: false,
  };
  let streamed = '';
  const toolSteps = new Set();
  for (const line of String(stdout ?? '').split('\n')) {
    const raw = line.trim();
    if (!raw) continue;
    let event;
    try { event = JSON.parse(raw); } catch { continue; }
    if (event.event === 'init') {
      out.conversation_id = event.conversation_id ?? out.conversation_id;
      if (typeof event.init?.model === 'string') out.model = event.init.model;
    } else if (event.event === 'step_update') {
      const step = event.step_update || {};
      if (step.step_type === 'agent_response' && typeof step.text_delta === 'string') streamed += step.text_delta;
      if (step.step_type === 'tool' && Number.isInteger(step.step_index)) toolSteps.add(step.step_index);
    } else if (event.event === 'result' && event.result) {
      out.hasResult = true;
      out.status = event.result.status ?? null;
      out.conversation_id = event.result.conversation_id ?? out.conversation_id;
      out.usage = event.result.usage ?? null;
      out.error = event.result.error ?? '';
      out.duration_seconds = event.result.duration_seconds ?? null;
      out.text = typeof event.result.response === 'string' && event.result.response ? event.result.response : streamed;
    }
  }
  if (!out.text) out.text = streamed;
  out.tools = toolSteps.size;
  return out;
}

export function defaultRunGeminiCli(fullPrompt, label, {
  env = process.env,
  target = process.cwd(),
  model,
  role,
  approvalMode,
  timeoutMs = DEFAULT_GEMINI_TIMEOUT_MS,
  idleTimeoutMs = undefined,
  earlyGraceMs = undefined,
  policyResolver = undefined,
  signal = null,
  log = () => {},
  processRunner = runCloseBoundProcess,
  spawnImpl,
  spawnSyncImpl,
  platform = process.platform,
  killImpl,
  repairOnly = false,
} = {}) {
  if (env.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError(
      'live agent seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `agy` sub-agent, or inject a stub `runGemini` (tests/orchestrator)',
    );
  }

  let mdl;
  if (typeof policyResolver === 'function') {
    const selection = policyResolver('gemini', { env });
    mdl = selection.model && /\s/.test(selection.model) ? selection.model : modelLaunchArgs(selection)[1];
  } else if (processRunner === runCloseBoundProcess) {
    const selection = resolveModelPolicy('gemini', { env });
    mdl = modelLaunchArgs(selection)[1];
  } else {
    mdl = resolveGeminiModel({ model, role, env });
  }
  const readonly = repairOnly || isReadonlyRole({ role, label });
  const prompt = (repairOnly ? '' : STEER) + String(fullPrompt ?? '');
  const childEnv = Object.assign({}, policyEnvironment(env), { NO_COLOR: '1', FORCE_COLOR: '0', CI: '1' });
  if (signal?.aborted) {
    return Promise.resolve({ text: '', rec: {
      label, cli_status: null, ok: false, status: 'aborted', aborted: true,
      requested_model: mdl, model_served: null, model_family: null,
      family_attested: false, model_attested: false, degraded: true, cost_usd: null,
    } });
  }
  const effectiveIdleMs = idleTimeoutMs !== undefined
    ? idleTimeoutMs
    : (Number(env.GEMINI_STREAM_IDLE_TIMEOUT_MS) || DEFAULT_GEMINI_IDLE_TIMEOUT_MS);
  const effectiveGraceMs = earlyGraceMs !== undefined
    ? earlyGraceMs
    : (Number(env.GEMINI_RESULT_GRACE_MS) || DEFAULT_GEMINI_RESULT_GRACE_MS);

  return processRunner({
    command: agyCommand(platform, env),
    args: buildAgyStreamArgs({ model: mdl, readonly, timeoutMs }),
    input: agyStreamInput(prompt),
    options: {
      cwd: target, env: childEnv, shell: false, windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    },
    signal,
    timeoutMs,
    idleTimeoutMs: effectiveIdleMs,
    shouldCompleteEarly: hasAgyTerminalResult,
    earlyGraceMs: effectiveGraceMs,
    label,
    log,
    ...(spawnImpl ? { spawnImpl } : {}),
    ...(spawnSyncImpl ? { spawnSyncImpl } : {}),
    platform,
    ...(killImpl ? { killImpl } : {}),
  }).then((result) => {
    const parsed = parseAgyStream(result.stdout);
    // CRITICAL: if agy emitted a valid terminal `result` frame (`status === 'SUCCESS'`)
    // and then lingered into a timeout/grace reap, NEVER discard the completed result!
    const completedDespiteLinger = parsed.hasResult
      && parsed.status === 'SUCCESS'
      && Boolean(String(parsed.text || '').trim())
      && result.terminal !== 'aborted'
      && result.terminal !== 'spawn_error';
    const effectiveTerminal = completedDespiteLinger ? 'closed' : result.terminal;
    const effectiveCode = completedDespiteLinger ? 0 : result.code;

    if (effectiveTerminal !== 'closed' || effectiveCode !== 0 || parsed.status !== 'SUCCESS') {
      const rawErr = parsed.error || result.error || String(result.stderr || '').slice(0, 500);
      let status = effectiveTerminal !== 'closed' ? effectiveTerminal : 'cli_error';
      let replaySafe = false;
      if (effectiveTerminal === 'closed') {
        if (/usage limit|rate limit|quota|insufficient (?:quota|credits)|429/i.test(rawErr)) {
          status = 'usage_limit';
          replaySafe = parsed.tools === 0;
        } else if (/not logged in|login required|authentication|oauth.*expired|unauthenticated|401/i.test(rawErr)) {
          status = 'auth_expired';
          replaySafe = parsed.tools === 0;
        }
      }
      log(`!! ${label}: agy ${status}${parsed.status ? ` (${parsed.status})` : ''}. ${String(rawErr).slice(0, 300)}`);
      return { text: '', rec: {
        label, cli_status: effectiveCode, ok: false, status,
        error: rawErr,
        replay_safe: replaySafe,
        requested_model: mdl, model_served: null, model_family: null,
        family_attested: false, model_attested: false, degraded: true,
        cost_usd: null, timed_out: status === 'timeout', aborted: status === 'aborted',
        kill_status: result.kill_status, conversation_id: parsed.conversation_id,
      } };
    }
    const { text, rec } = parseGeminiCliFrames(parsed.text, {
      label,
      cli_status: 0,
      requested_model: mdl,
      served_model: parsed.model,
      substituted: Boolean(parsed.model) && !modelsEqual(parsed.model, mdl),
    });
    rec.conversation_id = parsed.conversation_id;
    rec.kill_status = completedDespiteLinger ? null : result.kill_status;
    if (result.reaped_after_result || (completedDespiteLinger && result.terminal !== 'closed')) {
      rec.reaped_after_result = true;
    }
    if (parsed.usage) {
      rec.input_tokens = parsed.usage.input_tokens ?? null;
      rec.output_tokens = (parsed.usage.output_tokens ?? 0) + (parsed.usage.thinking_tokens ?? 0);
      rec.total_tokens = parsed.usage.total_tokens ?? null;
      rec.usage = parsed.usage;
    }
    if (parsed.duration_seconds != null) rec.duration_ms = Math.round(parsed.duration_seconds * 1000);
    rec.tools = parsed.tools;
    if (rec.ok) rec.model_source = 'cli-recorded';
    if (!rec.ok) {
      log(`!! ${label}: status=${rec.status} (requested="${mdl}" served="${parsed.model ?? 'unattested'}").`);
    }
    return { text, rec };
  });
}

export function makeGeminiCliSeam(options = {}) {
  const {
    runGemini = null,
    env = process.env,
    target = process.cwd(),
    model,
    role,
    approvalMode,
    timeoutMs,
    log = () => {},
  } = options;
  const run = runGemini
    || ((prompt, label, callOpts = {}) => defaultRunGeminiCli(prompt, label, {
      ...options, env, target, model: callOpts.model ?? model,
      role: callOpts.role ?? role, approvalMode,
      timeoutMs: callOpts.timeoutMs ?? timeoutMs, signal: callOpts.signal,
      repairOnly: callOpts.repairOnly === true, log,
    }));

  async function agent(prompt, opts = {}) {
    const label = opts.label || '(unlabeled)';
    return runCliSchemaAttempts({
      run,
      prompt,
      schema: opts.schema,
      label,
      callOpts: {
        model: opts.model ?? model,
        role: normalizeRole({ role: opts.role ?? role, label }),
        timeoutMs: opts.timeoutMs ?? timeoutMs,
        signal: opts.signal,
      },
      driverOpts: opts,
      familyName: 'Gemini',
      log,
      parse: extractJson,
    });
  }

  return { agent };
}

export const geminiCliDriver = {
  name: 'gemini-cli',
  subAgentCapable: true,
  structuredOutput: 'cli-subagent (prompt-suffix)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, timeoutMs } = opts;
    const { agent } = makeGeminiCliSeam(opts);
    return agent(prompt, { ...opts, schema, label, timeoutMs });
  },
};

export default geminiCliDriver;

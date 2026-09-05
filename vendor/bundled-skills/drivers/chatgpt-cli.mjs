// drivers/chatgpt-cli.mjs — ChatGPT **subscription** CLI backend (`codex exec`).
//
// Family `chatgpt` on Anchor knobs. Spawns the logged-in Codex CLI
// (`codex.exe exec`), NOT the raw OpenAI HTTP driver (`openai` + OPENAI_API_KEY).
//
// Capability: subAgentCapable true — fresh `codex exec` per call.
// Structured output: schema appended to the prompt + JSON parse with
// retry-once-then-failure (same contract as grok-cli).
//
// Live gate: CRUCIBLE_AGENT_LIVE=1.

import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { extractJson } from './claude.mjs';
import { isVerificationRole, normalizeRole } from './roles.mjs';
import { conformsJsonSchema, runCliSchemaAttempts } from './cli-schema.mjs';
import { runCloseBoundProcess } from './subscription-process.mjs';

export const DEFAULT_CODEX_CLI_TIMEOUT_MS = 45 * 60 * 1000;

export const CODEX_CLI_HEAVY_MODEL = 'gpt-5.6-sol';
export const CODEX_CLI_STANDARD_MODEL = 'gpt-5.6-terra';
export const CODEX_REASONING_EFFORTS = Object.freeze([
  'none', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra',
]);

const API_AUTH_ENV_KEYS = Object.freeze([
  'OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN',
  'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID',
  'OPENAI_BASE_URL', 'OPENAI_API_BASE', 'CODEX_BASE_URL',
]);

const WRITE_ROLES = new Set([
  'build', 'builder', 'coding', 'develop', 'developer', 'execute', 'fix',
  'implement', 'implementation',
]);

const CODEX_SANDBOXES = new Set(['read-only', 'workspace-write']);

/** True only for ids Codex will accept — reject stale Claude/Gemini/Grok pins. */
export function isPlausibleCodexModelId(m) {
  const s = String(m ?? '').trim().toLowerCase();
  if (!s) return false;
  if (/gemini|claude|grok|anthropic|flash|opus|sonnet|fable/.test(s)) return false;
  return /^(gpt-|o\d|codex|chatgpt)/.test(s) || s.includes('codex');
}

export function resolveCodexCliModel({ model, role, env = process.env } = {}) {
  const candidates = [];
  if (model) candidates.push(model);
  const roleKey = role ? `TRIO_MODEL_${String(role).toUpperCase().replace(/[^A-Z0-9]+/g, '_')}` : null;
  if (roleKey && env[roleKey]) candidates.push(env[roleKey]);
  if (env.TRIO_MODEL) candidates.push(env.TRIO_MODEL);
  if (env.CODEX_MODEL) candidates.push(env.CODEX_MODEL);
  if (env.CHATGPT_MODEL) candidates.push(env.CHATGPT_MODEL);
  const tier = String(env.TRIO_TIER || '').trim().toLowerCase();
  if (tier === 'heavy') candidates.push(env.CODEX_CLI_HEAVY_MODEL || CODEX_CLI_HEAVY_MODEL);
  if (tier === 'standard') candidates.push(env.CODEX_CLI_STANDARD_MODEL || CODEX_CLI_STANDARD_MODEL);
  for (const c of candidates) {
    if (isPlausibleCodexModelId(c)) return String(c).trim();
  }
  return null; // CLI account default
}

/**
 * Resolve a candidate effort. `ultra` is accepted here only as a request; the
 * production path separately proves the selected installed model advertises
 * it through `codex debug models` before the actual seat is launched.
 */
export function resolveCodexReasoningEffort({ reasoningEffort, role, env = process.env } = {}) {
  const roleKey = role
    ? `TRIO_REASONING_EFFORT_${String(role).toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`
    : null;
  const candidates = [
    reasoningEffort,
    roleKey ? env[roleKey] : null,
    env.CODEX_REASONING_EFFORT,
    String(env.TRIO_TIER || '').trim().toLowerCase() === 'heavy' ? 'ultra' : null,
    'high',
  ];
  for (const candidate of candidates) {
    const effort = String(candidate || '').trim().toLowerCase();
    if (!effort) continue;
    if (CODEX_REASONING_EFFORTS.includes(effort)) return effort;
    throw new TypeError(
      `unsupported Codex reasoning effort "${candidate}" (expected ${CODEX_REASONING_EFFORTS.join('|')})`,
    );
  }
  return 'high';
}

export function resolveCodexOrchestrationMode({ orchestrationMode, env = process.env } = {}) {
  const mode = String(orchestrationMode || env.TRIO_ORCHESTRATION_MODE || 'single')
    .trim().toLowerCase();
  if (mode !== 'single' && mode !== 'ultra') {
    throw new TypeError(`unsupported Codex orchestration mode "${mode}" (expected single|ultra)`);
  }
  return mode;
}

/** Copy the process environment while guaranteeing this seat cannot use API-key auth. */
export function subscriptionOnlyEnv(env = process.env) {
  const clean = { ...env, NO_COLOR: '1', CI: '1' };
  for (const key of API_AUTH_ENV_KEYS) delete clean[key];
  return clean;
}

const PREFLIGHT_CACHE = new Map();
const PREFLIGHT_SUCCESS_TTL_MS = 5 * 60 * 1000;

export function parseCodexModelCatalog(stdout) {
  const parsed = JSON.parse(String(stdout || '').trim());
  if (!parsed || !Array.isArray(parsed.models)) {
    throw new TypeError('Codex model catalog did not contain a models array');
  }
  return parsed.models.map((model) => ({
    slug: String(model?.slug || ''),
    efforts: Array.isArray(model?.supported_reasoning_levels)
      ? model.supported_reasoning_levels
        .map((level) => String(level?.effort || '').trim().toLowerCase())
        .filter(Boolean)
      : [],
  }));
}

/**
 * Prove this binary is using ChatGPT subscription auth and that its installed
 * model catalog supports the requested effort. Results are cached per
 * binary/model/effort for this process; no prompt or project data is involved.
 */
function syncProbeFailure(run, phase, subscriptionAuth = null) {
  const detail = `${run?.error?.message || ''}\n${run?.stderr || ''}`.trim();
  const timedOut = run?.error?.code === 'ETIMEDOUT' || /timed out|timeout/i.test(detail);
  if (timedOut) {
    return {
      ok: false, status: 'preflight_timeout', subscription_auth: subscriptionAuth,
      error: `${phase} timed out${detail ? `: ${detail}` : ''}`.slice(0, 500),
    };
  }
  if (run?.error || run?.status == null) {
    return {
      ok: false, status: 'spawn_error', subscription_auth: subscriptionAuth,
      error: `${phase} could not start${detail ? `: ${detail}` : ''}`.slice(0, 500),
    };
  }
  return null;
}

export function preflightCodexSubscription({
  cmd,
  model,
  effort,
  env = process.env,
  spawnSyncImpl = spawnSync,
  cache = PREFLIGHT_CACHE,
  now = Date.now,
} = {}) {
  const key = `${cmd}\0${model || ''}\0${effort || ''}`;
  const nowMs = Number(now());
  const cached = cache?.get(key);
  if (cached && Number.isFinite(nowMs)
      && nowMs - cached.checked_at_ms < PREFLIGHT_SUCCESS_TTL_MS) {
    return cached.result;
  }
  if (cached) cache.delete(key);
  const childEnv = subscriptionOnlyEnv(env);
  const login = spawnSyncImpl(cmd, ['login', 'status'], {
    env: childEnv, shell: false, windowsHide: true, encoding: 'utf8', timeout: 15_000,
  });
  const loginProbeFailure = syncProbeFailure(login, 'Codex subscription login probe');
  if (loginProbeFailure) return loginProbeFailure;
  const loginText = `${login.stdout || ''}\n${login.stderr || ''}`.trim();
  if (login.status !== 0 || !/logged in using chatgpt/i.test(loginText)) {
    return {
      ok: false, status: 'subscription_auth_required',
      subscription_auth: false,
      error: loginText.slice(0, 300) || 'Codex CLI is not logged in using ChatGPT',
    };
  }
  const catalogRun = spawnSyncImpl(cmd, ['debug', 'models'], {
    env: childEnv, shell: false, windowsHide: true, encoding: 'utf8',
    timeout: 30_000, maxBuffer: 10 * 1024 * 1024,
  });
  const catalogProbeFailure = syncProbeFailure(
    catalogRun, 'Codex installed-model capability probe', true,
  );
  if (catalogProbeFailure) return catalogProbeFailure;
  try {
    if (catalogRun.status !== 0) throw new Error(String(catalogRun.stderr || 'catalog command failed'));
    const catalog = parseCodexModelCatalog(catalogRun.stdout);
    const selected = catalog.find((item) => item.slug === model);
    if (!selected) throw new Error(`installed Codex catalog does not advertise model ${model}`);
    if (!selected.efforts.includes(effort)) {
      throw new Error(
        `installed Codex model ${model} does not advertise effort ${effort} `
        + `(supports ${selected.efforts.join('|') || 'none'})`,
      );
    }
    const result = {
      ok: true, status: 'ready', auth: 'chatgpt', subscription_auth: true, model, effort,
    };
    cache?.set(key, { checked_at_ms: nowMs, result });
    return result;
  } catch (error) {
    return {
      ok: false, status: 'capability_unavailable',
      subscription_auth: true,
      error: String(error?.message || error).slice(0, 500),
    };
  }
}

/** Known Windows install + PATH name. */
export function resolveCodexCmd(env = process.env) {
  const isWin = process.platform === 'win32';
  const exe = isWin ? 'codex.exe' : 'codex';
  const local = env.LOCALAPPDATA || '';
  const home = env.USERPROFILE || env.HOME || os.homedir();
  const pinned = env.CODEX_BIN;
  const cands = [
    pinned,
    local && path.join(local, 'Programs', 'OpenAI', 'Codex', 'bin', exe),
    path.join(home, '.codex', 'bin', exe),
  ].filter(Boolean);
  for (const p of cands) {
    try { if (fs.existsSync(p)) return p; } catch { /* ignore */ }
  }
  return exe;
}

/** Parse the stable JSONL events emitted by `codex exec --json`. */
export function parseCodexJsonl(stdout) {
  const events = [];
  const malformed = [];
  for (const rawLine of String(stdout || '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    try {
      events.push(JSON.parse(line));
    } catch {
      malformed.push(line);
    }
  }
  const thread = events.find((event) => event?.type === 'thread.started');
  const completed = [...events].reverse().find((event) => event?.type === 'turn.completed');
  const messages = events
    .filter((event) => event?.type === 'item.completed'
      && event?.item?.type === 'agent_message'
      && typeof event.item.text === 'string')
    .map((event) => event.item.text.trim())
    .filter(Boolean);
  const usage = completed?.usage && typeof completed.usage === 'object'
    ? completed.usage
    : {};
  return {
    ok: messages.length > 0 && !!completed && malformed.length === 0,
    text: messages.at(-1) || '',
    thread_id: typeof thread?.thread_id === 'string' ? thread.thread_id : null,
    usage: {
      input_tokens: Number(usage.input_tokens) || 0,
      cached_input_tokens: Number(usage.cached_input_tokens) || 0,
      cache_write_input_tokens: Number(usage.cache_write_input_tokens) || 0,
      output_tokens: Number(usage.output_tokens) || 0,
      reasoning_output_tokens: Number(usage.reasoning_output_tokens) || 0,
    },
    event_count: events.length,
    malformed_count: malformed.length,
  };
}

export function classifyCodexFailure(text) {
  const detail = String(text || '');
  if (/usage limit|rate limit|quota|resource exhausted|too many requests|\b429\b/i.test(detail)) {
    return 'usage_limit';
  }
  if (/not logged in|authentication|unauthorized|forbidden|\b401\b|\b403\b/i.test(detail)) {
    return 'auth_error';
  }
  return 'cli_error';
}

/** Pure argv builder used by both the production transport and its hermetic gate. */
export function buildCodexExecArgs({
  model = null,
  reasoningEffort = 'high',
  sandbox = 'read-only',
  target = null,
  platform = process.platform,
} = {}) {
  if (!CODEX_REASONING_EFFORTS.includes(String(reasoningEffort))) {
    throw new TypeError(`unsupported Codex reasoning effort "${reasoningEffort}"`);
  }
  if (!CODEX_SANDBOXES.has(String(sandbox))) {
    throw new TypeError(`unsupported Codex sandbox "${sandbox}" (expected read-only|workspace-write)`);
  }
  const args = [
    'exec', '--skip-git-repo-check', '--ephemeral', '--ignore-user-config',
    '--strict-config', '--color', 'never',
    '--json', '--sandbox', sandbox,
    '-c', 'approval_policy="never"',
    '-c', `model_reasoning_effort="${reasoningEffort}"`,
  ];
  // 2026-09-01 (Gate 5 Foreman wave 1, proven live): on Windows the workspace-write sandbox
  // needs a Windows sandbox implementation selected; `--ignore-user-config` drops the user's
  // `[windows] sandbox = "unelevated"`, so Codex 0.151 fell back to READ-ONLY and every execute
  // seat answered "workspace is read-only" while Foreman logged "execute complete". Select the
  // unelevated Windows sandbox inline for write seats only; read-only seats stay untouched.
  if (String(platform) === 'win32' && String(sandbox) === 'workspace-write') {
    args.push('-c', 'windows.sandbox="unelevated"');
  }
  if (target) args.push('--cd', target);
  if (model) args.push('--model', model);
  args.push('-');
  return args;
}

export function resolveCodexSandbox({ sandbox, role, env = process.env } = {}) {
  const verification = isVerificationRole({ role });
  const explicit = sandbox || env.CODEX_CLI_SANDBOX;
  const selected = verification
    ? 'read-only'
    : explicit || (WRITE_ROLES.has(String(role || '').toLowerCase())
      ? 'workspace-write' : 'read-only');
  if (!CODEX_SANDBOXES.has(String(selected))) {
    throw new TypeError(
      `unsupported Codex sandbox "${selected}" (expected read-only|workspace-write)`,
    );
  }
  return String(selected);
}

function unavailableFromReceipt(rec) {
  const aborted = rec.status === 'aborted' || rec.aborted === true;
  const err = new HaltError(
    aborted
      ? 'ChatGPT/Codex subscription seat aborted by its supervisor'
      : `ChatGPT/Codex subscription seat unavailable (${rec.status})`,
    rec.error || 'inspect the Codex receipt and subscription login, then retry or use the driver ladder',
  );
  if (!aborted) err.seat_unavailable = true;
  err.aborted = aborted;
  err.requested_model = rec.requested_model ?? null;
  err.served_model = rec.model_served ?? null;
  err.seat_status = rec.status;
  err.receipt = rec;
  return err;
}

/**
 * Spawn headless `codex exec` (ChatGPT subscription login). Returns { text, rec }.
 */
export function defaultRunCodexCli(fullPrompt, label, {
  env = process.env,
  target = process.cwd(),
  model = null,
  role = null,
  reasoningEffort = null,
  orchestrationMode = null,
  timeoutMs = (Number(env.CODEX_CLI_TIMEOUT_MS) || DEFAULT_CODEX_CLI_TIMEOUT_MS),
  sandbox = null,
  signal = null,
  log = () => {},
  processRunner = runCloseBoundProcess,
  preflightImpl = preflightCodexSubscription,
  spawnImpl,
  spawnSyncImpl,
  platform = process.platform,
  killImpl,
} = {}) {
  if (env.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError(
      'live ChatGPT/Codex CLI seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `codex exec` sub-agent (subscription), or inject runCodexCli',
    );
  }
  const cmd = resolveCodexCmd(env);
  const requestedOrchestration = resolveCodexOrchestrationMode({ orchestrationMode, env });
  const effort = resolveCodexReasoningEffort({
    reasoningEffort: reasoningEffort
      || (requestedOrchestration === 'ultra' ? 'ultra' : null),
    role,
    env,
  });
  const orchestration = effort === 'ultra' ? 'ultra' : requestedOrchestration;
  if (orchestration === 'ultra' && effort !== 'ultra') {
    throw new TypeError('Codex ultra orchestration requires the installed ultra effort');
  }
  const mdl = resolveCodexCliModel({ model, role, env })
    || (['xhigh', 'max', 'ultra'].includes(effort)
      ? CODEX_CLI_HEAVY_MODEL : CODEX_CLI_STANDARD_MODEL);
  const seatRole = normalizeRole({ role, label });
  const box = resolveCodexSandbox({ sandbox, role: seatRole, env });
  if (signal?.aborted) {
    return Promise.resolve({
      text: '',
      rec: {
        label, ok: false, status: 'aborted', error: 'seat aborted before spawn',
        requested_model: mdl, requested_effort: effort,
        orchestration_mode: orchestration, model_served: null,
        model_family: null, family_attested: false, model_attested: false, degraded: true,
        subscription_cli: true, subscription_auth: null, timed_out: false,
        aborted: true, sandbox: box,
      },
    });
  }
  // (John, 2026-09-05) ChatGPT IS a reviewer/judge seat. The Codex JSONL still names no
  // served model, so a verification call runs read-only (sandbox above) and its receipt is
  // stamped family_attested:true / model_attested:false — the seat contract accepts that
  // honestly and says so on the log. The old up-front refusal is gone.
  const preflight = preflightImpl({ cmd, model: mdl, effort, env });
  if (!preflight.ok) {
    return Promise.resolve({
      text: '',
      rec: {
        label, ok: false, status: preflight.status, error: preflight.error,
        requested_model: mdl, requested_effort: effort,
        orchestration_mode: orchestration, model_served: null,
        model_family: null, family_attested: false, model_attested: false, degraded: true,
        subscription_cli: true, subscription_auth: preflight.subscription_auth ?? null,
        timed_out: false, sandbox: box,
      },
    });
  }
  const args = buildCodexExecArgs({
    model: mdl, reasoningEffort: effort, sandbox: box, target, platform,
  });
  return processRunner({
    command: cmd,
    args,
    options: {
      cwd: target || undefined,
      env: subscriptionOnlyEnv(env),
      shell: false,
      windowsHide: true,
    },
    input: fullPrompt,
    signal,
    timeoutMs,
    label,
    log,
    ...(spawnImpl ? { spawnImpl } : {}),
    ...(spawnSyncImpl ? { spawnSyncImpl } : {}),
    platform,
    ...(killImpl ? { killImpl } : {}),
  }).then((result) => {
    const parsed = parseCodexJsonl(result.stdout);
    const detail = `${result.stderr}\n${result.stdout}`.trim();
    const classifiedFailure = classifyCodexFailure(detail);
    const status = result.terminal !== 'closed'
      ? result.terminal
      : result.code !== 0
        ? classifiedFailure
        : parsed.ok
          ? 'success'
          : classifiedFailure !== 'cli_error'
            ? classifiedFailure
            : parsed.text
              ? 'protocol_error'
              : 'no_reply';
    const ok = status === 'success';
    const rec = {
      label,
      cli_status: result.code,
      ok,
      status,
      requested_model: mdl,
      requested_effort: effort,
      orchestration_mode: orchestration,
      model_served: null,
      model_family: ok ? 'chatgpt' : null,
      family_attested: ok,
      model_attested: false,
      degraded: true,
      subscription_cli: true,
      subscription_auth: true,
      api_key_env_scrubbed: true,
      sandbox: box,
      thread_id: parsed.thread_id,
      usage: parsed.usage,
      event_count: parsed.event_count,
      prompt_sha256: crypto.createHash('sha256').update(String(fullPrompt)).digest('hex'),
      timed_out: status === 'timeout',
      aborted: status === 'aborted',
      kill_status: result.kill_status,
    };
    if (!ok) {
      rec.error = result.error || detail.slice(0, 500);
      log(`!! ${label}: chatgpt-cli ${status}. stderr=${result.stderr.slice(0, 300)}`);
    }
    return { text: parsed.text, rec };
  });
}

// Backwards-compatible export name; every CLI seam now uses the same validator.
export { conformsJsonSchema as conformsRequiredBooleans };

export function makeChatgptCliAgentSeam(options = {}) {
  const {
    runCodexCli = null,
    env = process.env,
    target = process.cwd(),
    log = () => {},
  } = options;
  const run = runCodexCli || ((prompt, label, callOpts = {}) =>
    defaultRunCodexCli(prompt, label, { ...options, env, target, log, ...callOpts }));

  async function agent(prompt, opts = {}) {
    const label = opts.label || '(unlabeled)';
    const role = normalizeRole({ role: opts.role, label });
    const callOpts = {
      model: opts.model, role, timeoutMs: opts.timeoutMs, sandbox: opts.sandbox,
      reasoningEffort: opts.reasoningEffort,
      orchestrationMode: opts.orchestrationMode,
      signal: opts.signal,
    };
    return runCliSchemaAttempts({
      run,
      prompt,
      schema: opts.schema,
      label,
      callOpts,
      driverOpts: opts,
      familyName: 'ChatGPT/Codex',
      log,
      parse: extractJson,
    });
  }

  return { agent };
}

export const chatgptCliDriver = {
  name: 'chatgpt-cli',
  subAgentCapable: true,
  structuredOutput: 'cli-subagent (prompt-suffix + json parse)',
  async runAgent(opts = {}) {
    const {
      prompt, schema, label, model, role, log, timeoutMs, sandbox,
      reasoningEffort, orchestrationMode, signal,
    } = opts;
    const { agent } = makeChatgptCliAgentSeam(opts);
    return agent(prompt, {
      schema, label, model, role, timeoutMs, sandbox,
      ...opts, reasoningEffort, orchestrationMode, signal,
    });
  },
};

export default chatgptCliDriver;

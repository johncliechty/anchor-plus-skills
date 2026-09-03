// drivers/grok-cli.mjs — Grok Build **subscription** CLI backend (`grok -p` / `grok --single`).
//
// This is the seat family for coding_family=grok / review_family=grok when the user is
// logged into Grok Build (OAuth), NOT the raw xAI HTTP API (that remains drivers/grok.mjs
// under driver name `grok` for optional API-key use).
//
// Capability: subAgentCapable true — spawns a fresh `grok.exe` process per call (same
// shape as claude-cli / gemini-cli). Structured output: schema appended to the prompt +
// JSON parse with retry-once-then-failure (mirrors makeAgentSeam in claude.mjs).
//
// Live gate: CRUCIBLE_AGENT_LIVE=1 (same as Claude/Gemini CLI seats).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { extractJson } from './claude.mjs';
import { isVerificationRole, normalizeRole } from './roles.mjs';
import { conformsJsonSchema, runCliSchemaAttempts } from './cli-schema.mjs';
import { runCloseBoundProcess } from './subscription-process.mjs';

// Live catalog (this host, 2026-07-22): `grok models` → default grok-4.5.
// Prefer null (omit --model) so the logged-in CLI default always wins unless env pins.
export const GROK_CLI_HEAVY_MODEL = process.env.GROK_CLI_HEAVY_MODEL || 'grok-4.5';
export const GROK_CLI_STANDARD_MODEL = process.env.GROK_CLI_STANDARD_MODEL || 'grok-4.5';
export const DEFAULT_GROK_CLI_TIMEOUT_MS = 20 * 60 * 1000;

/** True only for ids the Grok CLI will accept — reject stale Gemini/Claude setx pins. */
export function isPlausibleGrokModelId(m) {
  const s = String(m ?? '').trim().toLowerCase();
  if (!s) return false;
  if (/gemini|claude|gpt|flash|opus|sonnet|fable|anthropic/.test(s)) return false;
  return s.startsWith('grok');
}

/**
 * Resolve model for a Grok CLI call.
 * Default: null → do not pass --model (subscription CLI default, currently grok-4.5).
 * Explicit model / GROK_MODEL / TRIO_MODEL_* apply ONLY when they look like Grok ids
 * (stale TRIO_MODEL_SHARK="Gemini 3.1 Pro (High)" must not be forwarded to grok.exe).
 */
export function resolveGrokCliModel({ model, role, env = process.env } = {}) {
  const candidates = [];
  if (model) candidates.push(model);
  const roleKey = role ? `TRIO_MODEL_${String(role).toUpperCase().replace(/[^A-Z0-9]+/g, '_')}` : null;
  if (roleKey && env[roleKey]) candidates.push(env[roleKey]);
  if (env.TRIO_MODEL) candidates.push(env.TRIO_MODEL);
  if (env.GROK_MODEL) candidates.push(env.GROK_MODEL);
  const tier = String(env.TRIO_TIER || '').trim().toLowerCase();
  if (tier === 'heavy' && env.GROK_CLI_HEAVY_MODEL) candidates.push(env.GROK_CLI_HEAVY_MODEL);
  if (tier === 'standard' && env.GROK_CLI_STANDARD_MODEL) candidates.push(env.GROK_CLI_STANDARD_MODEL);
  for (const c of candidates) {
    if (isPlausibleGrokModelId(c)) return String(c).trim();
  }
  return null; // CLI account default
}

/**
 * Spawn headless `grok -p` (subscription login). Returns { text, rec }.
 * @param {string} fullPrompt
 * @param {string} label
 * @param {object} [o]
 */
export function defaultRunGrokCli(fullPrompt, label, {
  env = process.env,
  target = process.cwd(),
  model = null,
  role = null,
  timeoutMs = (Number(env.GROK_CLI_TIMEOUT_MS) || DEFAULT_GROK_CLI_TIMEOUT_MS),
  signal = null,
  log = () => {},
  processRunner = runCloseBoundProcess,
  spawnImpl,
  spawnSyncImpl,
  platform = process.platform,
  killImpl,
} = {}) {
  if (env.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError(
      'live Grok CLI seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `grok -p` sub-agent (subscription), or inject runGrokCli',
    );
  }
  const cmdName = platform === 'win32' ? 'grok.exe' : 'grok';
  const args = ['--output-format', 'plain'];
  const mdl = resolveGrokCliModel({ model, role, env });
  if (mdl) args.push('--model', mdl);
  const perm = isVerificationRole({ role, label })
    ? 'plan'
    : (env.GROK_CLI_PERMISSION_MODE || 'acceptEdits');
  if (perm) args.push('--permission-mode', perm);
  if (signal?.aborted) {
    return Promise.resolve({ text: '', rec: {
      label, cli_status: null, ok: false, status: 'aborted', aborted: true,
      requested_model: mdl, model_served: null, model_family: null,
      family_attested: false, model_attested: false, degraded: true,
    } });
  }
  const useFile = Buffer.byteLength(fullPrompt, 'utf8') > 24000;
  let tmpPath = null;
  if (useFile) {
    tmpPath = path.join(os.tmpdir(), `grok-cli-prompt-${process.pid}-${Date.now()}.txt`);
    fs.writeFileSync(tmpPath, fullPrompt, 'utf8');
    args.push('--prompt-file', tmpPath);
  } else {
    args.push('-p', fullPrompt);
  }
  return processRunner({
    command: cmdName,
    args,
    options: {
      cwd: target,
      env: { ...env, NO_COLOR: '1', CI: '1' },
      shell: false,
      windowsHide: true,
    },
    signal,
    timeoutMs,
    label,
    log,
    ...(spawnImpl ? { spawnImpl } : {}),
    ...(spawnSyncImpl ? { spawnSyncImpl } : {}),
    platform,
    ...(killImpl ? { killImpl } : {}),
  }).then((result) => {
    if (tmpPath) {
      try { fs.unlinkSync(tmpPath); } catch { /* best effort */ }
    }
    const text = String(result.stdout || '').trim();
    const status = result.terminal !== 'closed'
      ? result.terminal
      : result.code === 0
        ? (text ? 'success' : 'no_reply')
        : 'cli_error';
    const ok = status === 'success';
    const rec = {
      label,
      cli_status: result.code,
      ok,
      status,
      error: ok ? undefined : (result.error || result.stderr.slice(0, 500)),
      requested_model: mdl,
      // Plain Grok output exposes no served model. Never stamp a session default.
      model_served: null,
      model_family: ok ? 'grok' : null,
      family_attested: ok,
      model_attested: false,
      degraded: true,
      timed_out: status === 'timeout',
      aborted: status === 'aborted',
      kill_status: result.kill_status,
    };
    if (!ok) log(`!! ${label}: grok-cli ${status}. stderr=${result.stderr.slice(0, 300)}`);
    return { text, rec };
  });
}

/**
 * Compatibility export for callers of the former required-boolean predicate.
 * It now delegates to the same recursive schema predicate every CLI seam uses.
 */
// Backwards-compatible export name; every CLI seam now uses the same validator.
export { conformsJsonSchema as conformsRequiredBooleans };

/**
 * Agent seam: optional schema → JSON parse with one strict retry then failure.
 *
 * 2026-08-20 (Jumper gate-3 repair): the strict retry now ALSO fires when the first
 * reply PARSES but lacks a schema-required boolean (e.g. no boolean `passed`).
 * Before, a parsed-but-shapeless reply was returned WITHOUT any retry — the live
 * grok seat never got its second chance and Jumper HALTed on a nonconforming
 * verdict. Still exactly ONE retry total; still NEVER a verdict invented from
 * prose: any reply that remains nonconforming after the retry fails.
 */
export function makeGrokCliAgentSeam(options = {}) {
  const {
    runGrokCli = null,
    env = process.env,
    target = process.cwd(),
    log = () => {},
  } = options;
  const run = runGrokCli || ((prompt, label, callOpts = {}) =>
    defaultRunGrokCli(prompt, label, { ...options, env, target, log, ...callOpts }));

  async function agent(prompt, opts = {}) {
    const label = opts.label || '(unlabeled)';
    return runCliSchemaAttempts({
      run,
      prompt,
      schema: opts.schema,
      label,
      callOpts: {
        model: opts.model,
        role: normalizeRole({ role: opts.role, label }),
        timeoutMs: opts.timeoutMs,
        signal: opts.signal,
      },
      driverOpts: opts,
      familyName: 'Grok',
      log,
      parse: extractJson,
    });
  }

  return { agent };
}

export const grokCliDriver = {
  name: 'grok-cli',
  subAgentCapable: true,
  structuredOutput: 'cli-subagent (prompt-suffix + json parse)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, model, role, log, timeoutMs } = opts;
    const { agent } = makeGrokCliAgentSeam(opts);
    return agent(prompt, { ...opts, schema, label, model, role, timeoutMs });
  },
};

export default grokCliDriver;

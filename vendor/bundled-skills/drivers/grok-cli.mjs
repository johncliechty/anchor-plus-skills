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
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { extractJson } from './claude.mjs';
import { isVerificationRole, normalizeRole } from './roles.mjs';
import { conformsJsonSchema, runCliSchemaAttempts } from './cli-schema.mjs';
import { runCloseBoundProcess } from './subscription-process.mjs';
import { resolveModelPolicy, policyEnvironment, modelLaunchArgs } from './model-policy.mjs';
import { classifySubscriptionOutcome } from './subscription-outcome.mjs';

// Live catalog (this host, 2026-07-22): `grok models` → default grok-4.5.
// Prefer null (omit --model) so the logged-in CLI default always wins unless env pins.
export const GROK_CLI_HEAVY_MODEL = null;
export const GROK_CLI_STANDARD_MODEL = null;
export const DEFAULT_GROK_CLI_TIMEOUT_MS = 20 * 60 * 1000;
// (2026-09-05) grok's headless `-p` mode stops after a handful of agent turns by default;
// a reviewer that reads files hit that cap mid-investigation and its last prose line was
// the whole reply (schema-nonconforming twice → verification failed closed; every Foreman
// wave then went GREEN as review:degraded). The cap is now explicit and generous.
export const DEFAULT_GROK_CLI_MAX_TURNS = 40;
// (2026-09-05, foreman journal 0112 addendum) a tool ask that headless mode cannot answer CANCELS
// the whole turn (stopReason 'cancelled', no reply) — seen with chained (;), branching (if/else) and
// redirected (2>$null) shell commands in plan AND dontAsk modes. A verification seat is told first.
export const GROK_HEADLESS_READONLY_NOTE =
  'READ-ONLY SEAT (headless grok): a shell command that chains (;), branches (if/else) or redirects '
  + '(2>$null, >) needs an approval no one can give here and ENDS your turn unanswered. Use plain single '
  + 'commands or your file tools, and always finish with the JSON you were asked for.';
// (2026-10-06) The note alone did not hold: both Grok reviewers of an Anchor code job chained a
// command after minutes of work and the turn was cancelled with no review. A cancelled turn is now
// RESUMED in the same session (`--resume <id>`, proven live 2026-10-06: the resumed turn read the
// file instead and ended end_turn with the JSON) up to GROK_CLI_PERMISSION_RESUMES times.
export const DEFAULT_GROK_CLI_PERMISSION_RESUMES = 2;
export const GROK_RESUME_AFTER_REFUSAL =
  'Continue the task using your file tools only: your last shell command needed an approval no one '
  + 'can give here and did not run, so do not run it again. Finish with the JSON you were asked for.';
// (2026-10-06) Grok's --sandbox is Landlock/Seatbelt only (no Windows), and a plan-mode Grok with its
// terminal removed still ran a writing command through a deferred tool. So a verification seat's
// worktree is snapshotted before the call; anything the reviewer changed is put back and the review
// is not trusted. Foreman's own bookkeeping (git-excluded in code jobs) is never a reviewer write.
export const GROK_WRITE_GUARD_IGNORE = [
  '.foreman/', '.foreman-job/', '.anchor/', '.ecgberht/', 'foreman-checkpoint.json',
  '_foreman-status.log', 'foreman.config.json',
];

function ignoredByGuard(p) {
  return GROK_WRITE_GUARD_IGNORE.some((x) => (x.endsWith('/') ? p.startsWith(x) : p === x));
}

function git(dir, args, gitImpl) {
  const r = gitImpl(['-C', dir, ...args]);
  return r && r.status === 0 ? r.stdout : null;
}

function defaultGitImpl(args) {
  return spawnSync('git', args, { encoding: 'buffer', windowsHide: true, timeout: 120000, maxBuffer: 256 * 1024 * 1024 });
}

/** The worktree's dirty files (tracked changes + untracked) with their bytes; null when not a git tree. */
export function worktreeSnapshot(dir, gitImpl = defaultGitImpl) {
  const out = git(dir, ['status', '--porcelain=v1', '-z', '--untracked-files=all'], gitImpl);
  if (out == null) return null;
  const entries = Buffer.from(out).toString('utf8').split('\0').filter(Boolean);
  const snap = new Map();
  for (let i = 0; i < entries.length; i++) {
    const xy = entries[i].slice(0, 2);
    const p = entries[i].slice(3);
    if (xy[0] === 'R' || xy[0] === 'C') i++;      // a rename/copy entry is followed by its source path
    if (ignoredByGuard(p)) continue;
    let bytes = null;
    try { bytes = fs.readFileSync(path.join(dir, p)); } catch { bytes = null; }
    snap.set(p, bytes);
  }
  return snap;
}

/** Put back every path a read-only call changed between two snapshots; returns the paths restored. */
export function restoreWorktree(dir, before, after, gitImpl = defaultGitImpl) {
  const restored = [];
  const same = (a, b) => (a == null && b == null) || (a != null && b != null && Buffer.compare(a, b) === 0);
  for (const p of new Set([...before.keys(), ...after.keys()])) {
    const had = before.has(p);
    if (had && after.has(p) && same(before.get(p), after.get(p))) continue;
    const full = path.join(dir, p);
    try {
      if (had) {      // dirty before: back to its exact bytes (or gone again, if it was deleted)
        const b = before.get(p);
        if (b == null) fs.rmSync(full, { force: true });
        else { fs.mkdirSync(path.dirname(full), { recursive: true }); fs.writeFileSync(full, b); }
      } else if (git(dir, ['cat-file', '-e', `HEAD:${p}`], gitImpl) != null) {
        git(dir, ['checkout', 'HEAD', '--', p], gitImpl);      // clean before: back to HEAD
      } else {
        fs.rmSync(full, { force: true });                   // a new file the reviewer made
      }
      restored.push(p);
    } catch { /* reported by the caller as still changed */ }
  }
  return restored;
}

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
 * Parse `grok --output-format json` stdout: `{ text, modelUsage: { "<served>": {...} }, ... }`.
 * Returns `{ text, servedModel, ..., sessionId, usage, total_cost_usd }` — `servedModel` is the
 * single served model, else null (several contributors stay honestly unattested);
 * `usage` is the envelope's usage block, else the per-model token counts summed into the same
 * shape; `total_cost_usd` the envelope's, else the per-model charges summed. Null when stdout is
 * not that envelope (the caller then treats stdout as plain text, unattested).
 */
export function parseGrokJsonOutput(stdout, { requested = null } = {}) {
  const raw = String(stdout || '').trim();
  if (!raw) return null;
  let obj = null;
  try { obj = JSON.parse(raw); } catch {
    // narration glued before the envelope: take the LAST top-level object
    const i = raw.lastIndexOf('\n{');
    if (i >= 0) { try { obj = JSON.parse(raw.slice(i + 1)); } catch { obj = null; } }
  }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null;
  const perModel = obj.modelUsage && typeof obj.modelUsage === 'object' ? obj.modelUsage : {};
  const names = Object.keys(perModel);
  let servedModel = null;
  if (names.length === 1) servedModel = names[0];
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
  let usage = obj.usage && typeof obj.usage === 'object' ? obj.usage : null;
  if (!usage && names.length) {
    usage = { input_tokens: 0, output_tokens: 0, cache_read_input_tokens: 0 };
    for (const m of Object.values(perModel)) {
      usage.input_tokens += num(m?.inputTokens);
      usage.output_tokens += num(m?.outputTokens);
      usage.cache_read_input_tokens += num(m?.cachedInputTokens ?? m?.cacheReadInputTokens);
    }
  }
  let cost = typeof obj.total_cost_usd === 'number' ? obj.total_cost_usd : null;
  if (cost === null && names.some((n) => typeof perModel[n]?.costUSD === 'number')) {
    cost = Object.values(perModel).reduce((acc, m) => acc + num(m?.costUSD), 0);
  }
  return {
    text: typeof obj.text === 'string' ? obj.text.trim()
      : typeof obj.result === 'string' ? obj.result.trim() : '', servedModel,
    isError: obj.is_error === true || obj.isError === true
      || Boolean(obj.error) || (Array.isArray(obj.errors) && obj.errors.length > 0),
    stopReason: typeof obj.stopReason === 'string' ? obj.stopReason : null,
    numTurns: Number.isFinite(obj.num_turns) ? obj.num_turns : null,
    sessionId: typeof obj.sessionId === 'string' ? obj.sessionId
      : typeof obj.session_id === 'string' ? obj.session_id : null,
    usage,
    total_cost_usd: cost,
  };
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
  sandbox = null,
  timeoutMs = (Number(env.GROK_CLI_TIMEOUT_MS) || DEFAULT_GROK_CLI_TIMEOUT_MS),
  maxTurns = (Number(env.GROK_CLI_MAX_TURNS) || DEFAULT_GROK_CLI_MAX_TURNS),
  signal = null,
  log = () => {},
  processRunner = runCloseBoundProcess,
  policyResolver = resolveModelPolicy,
  spawnImpl,
  spawnSyncImpl,
  platform = process.platform,
  killImpl,
  gitImpl = defaultGitImpl,
} = {}) {
  if (env.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError(
      'live Grok CLI seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `grok -p` sub-agent (subscription), or inject runGrokCli',
    );
  }
  const cmdName = platform === 'win32' ? 'grok.exe' : 'grok';
  // (2026-09-04, foreman journal 0109) JSON output carries `modelUsage`, which names the
  // SERVED model — the attestation a verification seat needs. Plain output never did, so
  // every Grok review ran to completion and was then rejected as unattested.
  const selection = policyResolver('grok', { env });
  const mdl = selection.model;
  const args = ['--output-format', 'json', ...modelLaunchArgs(selection)];
  const perm = sandbox === 'read-only' || isVerificationRole({ role, label })
    ? 'plan'
    : (env.GROK_CLI_PERMISSION_MODE || 'acceptEdits');
  if (perm) args.push('--permission-mode', perm);
  if (Number.isFinite(maxTurns) && maxTurns > 0) args.push('--max-turns', String(maxTurns));
  // NOT grok's `--json-schema`: under it the model answers on its FIRST turn without touching
  // its tools (live smoke 2026-09-05 — a reviewer said "not answerable" in 8 s, 0 tool calls).
  // The schema stays the prompt-suffix + parse contract (cli-schema.mjs); the cap is the fix.
  if (signal?.aborted) {
    return Promise.resolve({ text: '', rec: {
      label, cli_status: null, ok: false, status: 'aborted', aborted: true,
      requested_model: mdl, model_served: null, model_family: null,
      family_attested: false, model_attested: false, degraded: true,
    } });
  }
  if (isVerificationRole({ role, label })) fullPrompt = GROK_HEADLESS_READONLY_NOTE + String.fromCharCode(10, 10) + fullPrompt;
  const useFile = Buffer.byteLength(fullPrompt, 'utf8') > 24000;
  let tmpPath = null;
  if (useFile) {
    tmpPath = path.join(os.tmpdir(), `grok-cli-prompt-${process.pid}-${Date.now()}.txt`);
    fs.writeFileSync(tmpPath, fullPrompt, 'utf8');
  }
  const verification = isVerificationRole({ role, label });
  const guard = verification && env.GROK_CLI_WRITE_GUARD !== '0' ? worktreeSnapshot(target, gitImpl) : null;
  const resumesAllowed = Number.isFinite(Number(env.GROK_CLI_PERMISSION_RESUMES))
    && env.GROK_CLI_PERMISSION_RESUMES !== undefined && env.GROK_CLI_PERMISSION_RESUMES !== ''
    ? Math.max(0, Number(env.GROK_CLI_PERMISSION_RESUMES)) : DEFAULT_GROK_CLI_PERMISSION_RESUMES;
  const first = useFile ? ['--prompt-file', tmpPath] : ['-p', fullPrompt];
  return (async () => {
    let out;
    try {
      out = await runGrokOnce([...args, ...first]);
    } finally {
      if (tmpPath) {
        try { fs.unlinkSync(tmpPath); } catch { /* best effort */ }
      }
    }
    let resumes = 0;
    while (out.rec.turn_cancelled && out.rec.session_id && resumes < resumesAllowed && !signal?.aborted) {
      resumes++;
      log(`${label}: grok turn cancelled by an unanswerable tool ask; resuming session ${out.rec.session_id} (${resumes}/${resumesAllowed})`);
      out = await runGrokOnce([...args, '--resume', out.rec.session_id, '-p', GROK_RESUME_AFTER_REFUSAL]);
    }
    out.rec.permission_resumes = resumes;
    if (guard) {
      const after = worktreeSnapshot(target, gitImpl);
      const restored = after ? restoreWorktree(target, guard, after, gitImpl) : [];
      if (restored.length) {
        log(`!! ${label}: the read-only grok seat changed ${restored.length} file(s); put back: ${restored.slice(0, 10).join(', ')}`);
        Object.assign(out.rec, {
          ok: false, status: 'wrote_files', reviewer_wrote: restored,
          error: `read-only grok seat changed files (put back): ${restored.slice(0, 10).join(', ')}`,
          model_family: null, family_attested: false, model_attested: false, degraded: true,
        });
      }
    }
    return out;
  })();

  function runGrokOnce(callArgs) {
    return processRunner({
    command: cmdName,
    args: callArgs,
    options: {
      cwd: target,
      env: { ...policyEnvironment(env), NO_COLOR: '1', CI: '1' },
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
    const parsed = parseGrokJsonOutput(result.stdout, { requested: mdl });
    const outcome = classifySubscriptionOutcome({family: 'grok', ...result});
    const text = parsed ? parsed.text : String(result.stdout || '').trim();
    const status = result.terminal !== 'closed'
      ? result.terminal
      : parsed?.isError || ['error', 'cancelled', 'max_turns', 'max_turns_reached'].includes(parsed?.stopReason)
        ? outcome.failure_status || (parsed?.stopReason === 'cancelled' ? 'aborted' : 'cli_error')
      : result.code === 0
        ? (text ? 'success' : 'no_reply')
        : outcome.failure_status || 'cli_error';
    const ok = status === 'success';
    const served = ok && parsed ? parsed.servedModel : null;
    const rec = {
      label,
      cli_status: result.code,
      ok,
      status,
      replay_safe: !ok && outcome.replay_safe,
      replay_evidence: outcome.replay_evidence,
      error: ok ? undefined : (result.error || result.stderr.slice(0, 500)),
      requested_model: mdl,
      requested_effort: selection.effort,
      model_policy: selection,
      highest_effort_verified: true,
      // The served model comes from one unambiguous `modelUsage` contributor.
      // Multiple contributors stay honestly unattested —
      // never a session default.
      model_served: served,
      model_family: ok ? 'grok' : null,
      family_attested: ok,
      model_attested: !!served,
      degraded: !served,
      timed_out: status === 'timeout',
      stop_reason: parsed?.stopReason ?? null,
      num_turns: parsed?.numTurns ?? null,
      turn_cancelled: parsed?.stopReason === 'cancelled',
      aborted: status === 'aborted',
      kill_status: result.kill_status,
      // Attribution (Anchor S3): session, usage and cost for the dispatcher's sink.
      session_id: typeof parsed?.sessionId === 'string' ? parsed.sessionId : null,
      usage: parsed?.usage && typeof parsed.usage === 'object' ? parsed.usage : null,
      cost_usd: typeof parsed?.total_cost_usd === 'number' ? parsed.total_cost_usd : null,
    };
    if (!ok) log(`!! ${label}: grok-cli ${status}. stderr=${result.stderr.slice(0, 300)}`);
    return { text, rec };
  });
  }
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

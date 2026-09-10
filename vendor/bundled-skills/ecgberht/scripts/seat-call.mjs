/**
 * THE SEAT TRANSPORT — the one place Ecgberht actually talks to a model.
 *
 * WHY IT LIVES HERE AND NOT IN engine/. Engine law: nothing under engine/ may import
 * child_process or call spawn*() (exec-insession.mjs:13, enforced by
 * test/w20-exec-insession.test.mjs). Process creation arrives via INJECTED hooks. So the
 * conversational steward's `converse()` takes a `seatCall` function, and this module is
 * the real one — the bridge injects it, tests inject a fake or a recording.
 *
 * TRANSPORT FACTS validated on this host 2026-08-04 (the Step-0 probe):
 *   * `claude -p "<prompt>"` → exit 0, ~8.6s, the reply on stdout. Bare JSON came back
 *     clean with no fence when the prompt asked for JSON.
 *   * `--output-format json` wraps it with usage + cost + session_id. We use the WRAPPER
 *     for token counts, and read the reply out of `.result`.
 *   * The wrapper carries VENDOR PRODUCT MODEL IDS (`modelUsage: {"claude-fable-5": …}`).
 *     `seating.findProductModelIds` forbids those on seat stamps, so this module returns
 *     ONLY a whitelisted `meta` — never the raw wrapper.
 *   * `session_id` comes back and `--resume` exists. We deliberately DO NOT use it: that
 *     would put the steward's memory in the CLI's on-disk session store, a second memory
 *     outside E5. Context is rebuilt each turn from the ledger + ephemeral turns.
 *
 * Gemini seats route through Skill Foundry's agy-dispatch (the canonical `agy` transport;
 * a bare `gemini` call is dead). Bare `grok` is refused upstream by isProductionSeatSafe.
 *
 * REPLAY. `ECGBERHT_SEAT_REPLAY=<file>` returns a RECORDED REAL reply instead of calling
 * out. That is how the offline gate exercises the true parse→propose→confirm path without
 * a network hop — the recording is real model output, not a hand-written stub, and the
 * prompt is asserted against the recording's prompt hash so a drifting prompt FAILS rather
 * than passing on a stale tape.
 */

import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

import { SEAT_ROLE, resolveTierAlias } from '../engine/seat-tiers.mjs';
import { familyToSubscriptionDriver } from '../engine/seating.mjs';

/** Default wall-clock bound for one conversational turn. */
export const SEAT_TIMEOUT_MS = 180_000;

/** Where a gemini seat's dispatcher lives (resolved, never assumed present). */
export const AGY_DISPATCH_REL = path.join('tools', 'agy-dispatch.mjs');

/**
 * Deterministic hash of a prompt — binds a recording to the prompt that produced it.
 * @param {string} prompt
 * @returns {string}
 */
export function hashPrompt(prompt) {
  return crypto.createHash('sha256').update(String(prompt ?? ''), 'utf8').digest('hex');
}

/**
 * Run a child process to completion with a hard timeout, capturing stdout.
 * Never uses a shell; always hides the window (agy/claude both spawn consoles otherwise).
 *
 * @param {string} cmd
 * @param {string[]} args
 * @param {{ timeoutMs?: number, cwd?: string }} [opts]
 * @returns {Promise<{ ok: boolean, code: number|null, out: string, err: string, ms: number, reason?: string }>}
 */
export function runProcess(cmd, args, opts = {}) {
  const timeoutMs = Number(opts.timeoutMs) || SEAT_TIMEOUT_MS;
  const hasStdin = typeof opts.stdin === 'string';
  return new Promise((resolve) => {
    const started = Date.now();
    let child;
    try {
      child = spawn(cmd, args, {
        cwd: opts.cwd,
        windowsHide: true,
        shell: false,
        stdio: [hasStdin ? 'pipe' : 'ignore', 'pipe', 'pipe'],
        env: { ...process.env, NO_COLOR: '1' },
      });
    } catch (e) {
      return resolve({
        ok: false, code: null, out: '', err: String(e?.message ?? e),
        ms: 0, reason: 'spawn_failed',
      });
    }

    let out = '';
    let err = '';
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ...result, ms: Date.now() - started });
    };
    const timer = setTimeout(() => {
      try { child.kill(); } catch { /* already gone */ }
      finish({ ok: false, code: null, out, err, reason: 'timeout' });
    }, timeoutMs);

    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { err += d; });
    child.on('error', (e) => {
      finish({ ok: false, code: null, out, err: String(e?.message ?? e), reason: 'spawn_error' });
    });
    child.on('exit', (code) => {
      finish({ ok: code === 0, code, out, err, reason: code === 0 ? undefined : 'nonzero_exit' });
    });

    if (hasStdin) {
      child.stdin.on('error', () => { /* child died first; exit handler reports it */ });
      child.stdin.end(opts.stdin);
    }
  });
}

// ── Replay (the offline gate's honest stand-in for the network hop) ────────

/**
 * Read a recorded seat reply. The recording carries the prompt hash it was produced
 * from; a mismatch is a HARD FAILURE, not a warning — otherwise a drifting prompt would
 * keep passing against a stale tape, which is exactly the vacuous guard this project has
 * shipped three times already.
 *
 * @param {string} file
 * @param {string} prompt
 * @returns {{ ok: boolean, text?: string, meta?: object, reason?: string, detail?: string }}
 */
/** Position within an UNBOUND tape, per process. Each bridge invocation is a fresh
 *  process, so this counts the calls of a single turn: 0 = talk, 1 = plan. */
let _unboundCallIndex = 0;

export function replaySeatCall(file, prompt) {
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return { ok: false, reason: 'replay_unreadable', detail: String(e?.message ?? e) };
  }

  // A TAPE IS A SET OF CALLS, KEYED BY PROMPT HASH. One conversational turn can make
  // TWO seat calls — the conversational tier talks, then the frontier tier frames a
  // plan — so a single-record tape could only ever answer one of them, and the other
  // failed as "could not reach the seat". Matching by hash serves whichever call is
  // asking, in any order, and keeps the drift guard exactly as strict: no matching
  // hash is still a hard failure.
  const want = hashPrompt(prompt);
  let record = raw;
  if (Array.isArray(raw)) {
    record = raw.find((r) => r && r.prompt_sha256 === want);
    // AN UNBOUND TAPE SERVES IN CALL ORDER. The browser lane runs against a live server
    // whose prompts carry that session's own project and goal, so their hashes can
    // never match a recording made elsewhere — but it still needs a talk reply for
    // call 1 and a plan reply for call 2. A tape with no hashes is explicitly not
    // prompt-bound (it proves the SURFACE is wired; the bridge lane proves behaviour
    // under a strict hash) and is served positionally within the process.
    if (!record && raw.length && raw.every((r) => r && !r.prompt_sha256)) {
      record = raw[Math.min(_unboundCallIndex++, raw.length - 1)];
    }
    if (!record) {
      return {
        ok: false,
        reason: 'replay_prompt_drift',
        detail:
          'No recorded reply matches this prompt. Re-record with a live seat rather '
          + 'than trusting a stale recording.',
        actual_prompt_sha256: want,
        recorded: raw.length,
      };
    }
  }
  if (!record || typeof record !== 'object' || typeof record.reply_text !== 'string') {
    return { ok: false, reason: 'replay_malformed' };
  }
  if (record.prompt_sha256 && record.prompt_sha256 !== want) {
    return {
      ok: false,
      reason: 'replay_prompt_drift',
      detail:
        'The prompt no longer matches the one this reply was recorded against. '
        + 'Re-record with a live seat rather than trusting a stale recording.',
      expected_prompt_sha256: record.prompt_sha256,
      actual_prompt_sha256: hashPrompt(prompt),
    };
  }
  return {
    ok: true,
    text: record.reply_text,
    meta: {
      tokens: Number(record.tokens) || 0,
      duration_ms: Number(record.duration_ms) || 0,
      replayed: true,
      recorded_at: record.recorded_at ?? null,
    },
  };
}

// ── Claude seat ────────────────────────────────────────────────────────────

/**
 * Pull the reply + token count out of `claude -p --output-format json`.
 * Returns ONLY whitelisted metadata — the wrapper's `modelUsage` keys are vendor product
 * model IDs and must never reach a durable event.
 *
 * @param {string} stdout
 * @returns {{ ok: boolean, text?: string, meta?: object, reason?: string }}
 */
export function parseClaudeWrapper(stdout) {
  const raw = String(stdout ?? '').trim();
  if (!raw) return { ok: false, reason: 'empty_stdout' };

  let wrapper;
  try {
    wrapper = JSON.parse(raw);
  } catch {
    // Not the JSON wrapper — plain `-p` output IS the reply. Honest fallback.
    return { ok: true, text: raw, meta: { tokens: 0, duration_ms: 0 } };
  }
  if (!wrapper || typeof wrapper !== 'object') return { ok: false, reason: 'wrapper_not_object' };
  if (wrapper.is_error === true) {
    return { ok: false, reason: 'seat_reported_error' };
  }

  const text = typeof wrapper.result === 'string' ? wrapper.result : '';
  if (!text.trim()) return { ok: false, reason: 'wrapper_no_result' };

  const usage = wrapper.usage ?? {};
  const tokens =
    (Number(usage.input_tokens) || 0)
    + (Number(usage.output_tokens) || 0)
    + (Number(usage.cache_read_input_tokens) || 0)
    + (Number(usage.cache_creation_input_tokens) || 0);

  return {
    ok: true,
    text,
    // Whitelist only — no model id, no session_id (those would leak a product model
    // id into a durable event). `total_cost_usd` IS taken: John's point that the
    // budget "is really not priced well" was right, and the synthetic accounting unit
    // made a dollar cap meaningless. This is the real number the CLI reports.
    meta: {
      tokens,
      duration_ms: Number(wrapper.duration_api_ms) || 0,
      cost_usd: Number(wrapper.total_cost_usd) || 0,
    },
  };
}

/**
 * Tools the steward's seat may use — READ-ONLY, explicitly whitelisted.
 *
 * WHY THIS IS NOT OPTIONAL (discovered in the 2026-08-04 end-to-end smoke). `claude -p`
 * runs with FULL tool access by default. The first real turn happily explored the disk
 * and read John's actual BA 815 folder — which produced a much better-grounded proposal,
 * but also means an unrestricted seat could WRITE. The steward's whole contract is that
 * a model never writes and never spends; leaving that to the model's goodwill rather
 * than to a flag would be exactly the kind of gap that looks fine until it isn't.
 *
 * Read/Grep/Glob also satisfies the standing house rule that agent-shaped calls must not
 * spawn shells (spawned PowerShells steal focus on this host).
 */
export const SEAT_ALLOWED_TOOLS = Object.freeze(['Read', 'Grep', 'Glob']);

/**
 * Tools DENIED on every seat call, always.
 *
 * `--allowed-tools` turned out NOT to be restrictive: a call allow-listing only a
 * non-existent tool still happily listed a directory (measured 2026-08-05). So the
 * allow-list cannot be the thing that keeps the steward read-only — an explicit DENY
 * list is. `--permission-mode plan` is the second layer, not the only one.
 */
export const SEAT_DENIED_TOOLS = Object.freeze([
  'Write', 'Edit', 'NotebookEdit', 'Bash', 'Task',
]);

/**
 * Additionally denied on a TALKING turn.
 *
 * Reading the project is what made the first BA 815 proposal good — and what made that
 * turn take 162s. The scaffolding and conversation history are already in the prompt, so
 * a talking turn has nothing to look up; denying the read tools is the speed fix.
 */
export const TALK_DENIED_TOOLS = Object.freeze([
  'Read', 'Grep', 'Glob', 'WebFetch', 'WebSearch',
]);

/**
 * @param {string} prompt
 * @param {{ timeoutMs?: number, bin?: string, cwd?: string, model?: string,
 *           allowTools?: boolean }} [opts]
 */
export async function callClaudeSeat(prompt, opts = {}) {
  return callTrioSeat(prompt, { ...opts, family: 'claude' });
}

/** Legacy pure argv helper; callers must supply a verified frozen selection. */
export function buildCodexSeatArgs(opts = {}) {
  const selection = opts.selection;
  if (!selection || selection.family !== 'chatgpt'
      || !/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/.test(selection.model || '')
      || !['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'].includes(selection.effort)) {
    throw new TypeError('A verified current ChatGPT model-policy selection is required');
  }
  const { model, effort } = selection;
  const args = ['exec', '--ephemeral', '--ignore-rules', '--skip-git-repo-check',
    '--sandbox', 'read-only', '--color', 'never', '--model', model,
    '-c', 'model_reasoning_effort="' + effort + '"',
    '-c', 'forced_login_method="chatgpt"',
    '-c', 'agents.default_subagent_model="' + model + '"',
    '-c', 'agents.default_subagent_reasoning_effort="' + effort + '"'];
  if (opts.cwd) args.push('--cd', String(opts.cwd));
  args.push('-');
  return { args, effort };
}

export async function callCodexSeat(prompt, opts = {}) {
  return callTrioSeat(prompt, { ...opts, family: 'chatgpt' });
}

// ── Shared Trio seat ──────────────────────────────────────────────────────

/** The shared driver registry next to this installed skill's development root. */
export function resolveTrioIndexSpec(env = process.env) {
  const override = env.ECGBERHT_TRIO_INDEX || env.TRIO_DRIVERS_INDEX
    || (env.ANCHOR_TRIO_DIR && path.join(env.ANCHOR_TRIO_DIR, 'drivers', 'index.mjs'));
  if (override) {
    const target = String(override).startsWith('file:') ? fileURLToPath(override) : String(override);
    if (!path.isAbsolute(target) || /^(?:\\\\|\/\/)/.test(target) || !fs.existsSync(target)) {
      throw new TypeError('Explicit Trio module must be an existing absolute local file');
    }
    return pathToFileURL(target).href;
  }
  for (const rel of ['../../trio/drivers/index.mjs', '../../drivers/index.mjs']) {
    const candidate = new URL(rel, import.meta.url);
    if (fs.existsSync(fileURLToPath(candidate))) return candidate.href;
  }
  throw new TypeError('Shared Trio drivers are missing; install the bundled skills or set ANCHOR_TRIO_DIR');
}

async function resolveTrioRunAgent(opts, env) {
  if (typeof opts.runAgent === 'function') return opts.runAgent;
  const importer = opts.importTrio ?? ((spec) => import(spec));
  const mod = await importer(resolveTrioIndexSpec(env));
  if (typeof mod?.runAgent !== 'function') {
    throw new TypeError('shared Trio module does not export runAgent');
  }
  return mod.runAgent;
}

const MODEL_ENV_SCRUB_EXACT = ['TRIO_MODEL', 'TRIO_TIER', 'CODEX_MODEL', 'CHATGPT_MODEL', 'GEMINI_MODEL', 'GROK_MODEL'];
function scrubModelEnv(env) {
  const out = { ...env };
  for (const key of Object.keys(out)) {
    if (MODEL_ENV_SCRUB_EXACT.includes(key) || key.startsWith('TRIO_MODEL_')) delete out[key];
  }
  return out;
}

/** The dispatcher's opt-in raw physical-receipt channel (drivers report usage there). */
const PHYSICAL_RECEIPT_HOOK = Symbol.for('trio.seat.physical-receipt');

/**
 * Call one Steward seat through Trio's single receipt-bearing dispatcher.
 * `runAgent` is injectable so gates never touch a subscription CLI. Production
 * callers reach the same Trio seam used by the other Foundry skills.
 */
export async function callTrioSeat(prompt, opts = {}) {
  const env = opts.env ?? process.env;
  const family = String(opts.family || '').trim().toLowerCase();
  const driver = opts.driver || familyToSubscriptionDriver(family);
  if (!driver) {
    return {
      ok: false,
      reason: 'seat_family_unsupported',
      detail: `No Trio subscription transport for seat family "${family}".`,
    };
  }

  let runAgent;
  try {
    runAgent = await resolveTrioRunAgent(opts, env);
  } catch (error) {
    return {
      ok: false,
      reason: 'trio_adapter_unavailable',
      detail: String(error?.message ?? error).slice(0, 500),
    };
  }

  const seatRole = opts.role === SEAT_ROLE.FRONTIER ? 'synthesizer' : 'orchestrator';
  // Role determines tools/depth, never a lower model/effort. Trio resolves
  // latest-supported/highest-supported for every production family and role.
  const reasoningEffort = null;
  const orchestrationMode = 'native';
  const started = Date.now();
  let receipt = null;
  // Measured usage rides the raw physical receipts (the public trio.seat.v1 shape is
  // frozen by strict consumers) — captured here so the debit is real, never invented.
  let measuredTokens = 0;
  let measuredCost = 0;
  let selection = null;
  try {
    const text = await runAgent({
      prompt: String(prompt),
      driver,
      role: seatRole,
      label: `Ecgberht:${opts.role || SEAT_ROLE.CONVERSATIONAL}`,
      freshContext: true,
      env: { ...scrubModelEnv(env), CRUCIBLE_AGENT_LIVE: env.CRUCIBLE_AGENT_LIVE || '1' },
      target: opts.cwd,
      model: undefined,
      timeoutMs: opts.timeoutMs,
      sandbox: 'read-only',
      reasoningEffort,
      orchestrationMode,
      [PHYSICAL_RECEIPT_HOOK]: (entry) => {
        selection = entry?.receipt?.model_policy || selection;
        const usage = entry?.receipt?.usage;
        if (usage && typeof usage === 'object') {
          measuredTokens += (Number(usage.input_tokens) || 0)
            + (Number(usage.output_tokens) || 0)
            + (Number(usage.reasoning_output_tokens) || 0);
        }
        const cost = Number(entry?.receipt?.total_cost_usd ?? entry?.receipt?.cost_usd);
        if (Number.isFinite(cost)) measuredCost += cost;
      },
      onReceipt: async (value) => {
        receipt = value;
        if (typeof opts.onReceipt === 'function') await opts.onReceipt(value);
      },
    });
    if (!receipt || receipt.schema !== 'trio.seat.v1' || receipt.ok !== true) {
      return {
        ok: false,
        reason: 'trio_receipt_missing',
        detail: 'Trio returned seat output without a successful trio.seat.v1 receipt.',
      };
    }
    const reply = typeof text === 'string' ? text.trim() : JSON.stringify(text);
    if (!reply) {
      return {
        ok: false,
        reason: 'seat_no_reply',
        detail: 'Trio returned an empty Steward reply.',
        meta: { trio_receipt: receipt },
      };
    }
    return {
      ok: true,
      text: reply,
      meta: {
        tokens: measuredTokens,
        cost_usd: measuredCost,
        duration_ms: Date.now() - started,
        reasoning_effort: selection?.effort ?? null,
        model_policy: selection,
        orchestration_mode: orchestrationMode,
        subscription_cli: true,
        requested_family: receipt.requested?.family ?? family,
        served_family: receipt.served?.family ?? null,
        served_family_attested: receipt.served?.family_attested === true,
        trio_receipt: receipt,
      },
    };
  } catch (error) {
    const failedReceipt = error?.receipt ?? null;
    return {
      ok: false,
      reason: failedReceipt?.status || error?.seat_status || 'seat_failed',
      detail: String(error?.message ?? error).slice(0, 500),
      meta: failedReceipt ? { trio_receipt: failedReceipt } : undefined,
    };
  }
}

// ── Gemini seat (via Skill Foundry's agy-dispatch) ─────────────────────────

/**
 * Resolve agy-dispatch without embedding a host-absolute literal in shipped strings.
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {string|null}
 */
export function resolveAgyDispatch(env = process.env) {
  const explicit = env.ECGBERHT_AGY_DISPATCH;
  if (explicit && fs.existsSync(explicit)) return explicit;
  const foundry = env.SKILL_FOUNDRY_DIR;
  if (foundry) {
    const p = path.join(foundry, AGY_DISPATCH_REL);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

/**
 * @param {string} prompt
 * @param {{ timeoutMs?: number }} [opts]
 */
export async function callGeminiSeat(prompt, opts = {}) {
  return callTrioSeat(prompt, { ...opts, family: 'gemini' });
}

// ── The injected hook ──────────────────────────────────────────────────────

/**
 * Build the `seatCall` function `converse()` expects.
 *
 * Honest failure is the contract: every path returns `{ok:false, reason}` rather than a
 * fabricated reply, because the steward saying "I could not reach the seat" is correct
 * and the steward inventing a plan is the one thing it must never do.
 *
 * @param {{ timeoutMs?: number, env?: NodeJS.ProcessEnv }} [opts]
 * @returns {(prompt: string, ctx: object) => Promise<object>}
 */
export function makeSeatCall(opts = {}) {
  const env = opts.env ?? process.env;
  return async function seatCall(prompt, ctx = {}) {
    const replay = env.ECGBERHT_SEAT_REPLAY;
    if (replay) return replaySeatCall(replay, prompt);

    // RECORDING MODE. `ECGBERHT_SEAT_RECORD=<file>` writes the REAL reply plus the
    // hash of the prompt that produced it. That file becomes the offline gate's
    // replay fixture — real model output, captured from a real run, never authored
    // by hand. The prompt hash is what stops it silently going stale.
    const record = env.ECGBERHT_SEAT_RECORD;

    // Ground the seat IN the project: read-only exploration is genuinely valuable
    // (the smoke run found the real course folder and reasoned about it), and the
    // project root is the honest boundary for it.
    const family = String(ctx.seat_family ?? 'claude').toLowerCase();

    // ROLE -> TIER -> ALIAS. The caller asks for `frontier` (planning) or
    // `conversational` (talking); seat-tiers resolves it to a CLI alias, never a
    // versioned id, so new model releases are picked up automatically.
    const role = ctx.role ?? SEAT_ROLE.CONVERSATIONAL;
    const tier = resolveTierAlias(family, role, { env });
    if (!tier.ok) return { ok: false, reason: tier.error, detail: tier.message };

    const callOpts = {
      ...opts,
      cwd: opts.cwd ?? ctx.project_path ?? opts.cwd,
      model: tier.alias,
      role,
      // Only the planning turn reads the project. Talking turns already carry the
      // scaffolding and history in the prompt, and tool loops are what made turns slow.
      allowTools: role === SEAT_ROLE.FRONTIER,
    };

    const result = await callTrioSeat(prompt, {
      ...callOpts,
      family,
      driver: familyToSubscriptionDriver(family),
    });
    if (result.ok) {
      result.meta = { ...(result.meta ?? {}), role, tier_alias: tier.alias, tier_source: tier.source };
    }

    if (record && result.ok) {
      // APPEND to a hash-keyed tape so every call in a turn is captured, not just the
      // last one to write.
      const file = record;
      fs.mkdirSync(path.dirname(file), { recursive: true });
      let tape = [];
      try {
        const prior = JSON.parse(fs.readFileSync(file, 'utf8'));
        tape = Array.isArray(prior) ? prior : [prior];
      } catch { /* first write */ }
      const entry = {
        note: 'REAL seat output captured from a live run — replayed by the offline gate.',
        prompt_sha256: hashPrompt(prompt),
        seat_family: family,
        reasoning_effort: result.meta?.reasoning_effort ?? null,
        subscription_cli: result.meta?.subscription_cli === true,
        trio_receipt: result.meta?.trio_receipt ?? null,
        tokens: result.meta?.tokens ?? 0,
        duration_ms: result.meta?.duration_ms ?? 0,
        recorded_at: new Date().toISOString(),
        reply_text: result.text,
      };
      const at = tape.findIndex((r) => r && r.prompt_sha256 === entry.prompt_sha256);
      if (at >= 0) tape[at] = entry; else tape.push(entry);
      fs.writeFileSync(file, `${JSON.stringify(tape, null, 2)}\n`, 'utf8');
    }
    return result;
  };
}

// drivers/claude.mjs — the DEFAULT trio model backend: headless `claude -p` on the
// subscription (NO ANTHROPIC_API_KEY => subscription usage). This is the canonical
// home of the existing `claude -p` behavior that previously lived inline in
// `crucible/bin/agent.mjs` and Foreman's `run-live.mjs`; both now route through this
// module so the Claude path stays byte-for-byte equivalent (Wave 4 non-regression).
//
// The seam is:
//   - ENV-GATED: the live process is only spawned when CRUCIBLE_AGENT_LIVE=1, so an
//     accidental import/test never launches a real (billable) agent.
//   - STUBBABLE: `makeAgentSeam({ runClaude })` accepts an injected transport, so
//     tests drive the full schema/retry/failure logic with zero subprocesses.
// The returned `agent(prompt, opts)` honors Workflow's contract: it returns text by
// default, and the validated object when `opts.schema` is supplied (retry-once then
// fail on nonconforming schema replies, exactly like run-live's C1 hardening).
//
// `claudeDriver` is the registry entry consumed by `drivers/index.mjs`; its
// `runAgent({ prompt, schema, freshContext })` is the pluggable interface. claude -p
// spawns a fresh sub-agent process, so `freshContext` is satisfied natively
// (subAgentCapable: true) and the flag is accepted as a no-op for this backend.

import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { attestStamp } from './attest.mjs';
import { isVerificationRole, normalizeRole } from './roles.mjs';
import { runCliSchemaAttempts } from './cli-schema.mjs';
import { runCloseBoundProcess } from './subscription-process.mjs';

const BASE_ARGS = [
  '-p', ' ', '--output-format', 'stream-json', '--verbose',
  '--permission-mode', 'acceptEdits',
];
const DEFAULT_ALLOWED_TOOLS = 'Bash,Edit,Write,Read,Glob,Grep';

/** Pull the first JSON object out of a model reply (bare, fenced, or embedded). */
export function extractJson(text) {
  if (typeof text !== 'string') return null;
  let t = text.trim();
  // Strip a leading ```json / ``` fence if the model wrapped its reply.
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  // Try, in order: the text as-is; the outermost {object} or [array] embedded in prose.
  // Each attempt is also retried with trailing commas stripped (a common model malformation
  // that breaks JSON.parse). Hardened 2026-07-17 to cut transient reviewer abstains.
  const stripTrailingCommas = (s) => s.replace(/,(\s*[}\]])/g, '$1');
  // Grok CLI plain output (2026-08-20 gate-3 probe): the model can emit JSON whose
  // string values contain LITERAL newlines/control chars — invalid JSON that broke
  // Jumper Gate-3 as a phantom "transport failure". Last-resort candidate: control
  // chars → spaces (legal between tokens, content-neutral inside prose strings).
  const stripControlChars = (s) => s.replace(/[\u0000-\u001F]/g, ' ');
  const candidates = [
    t,
    (t.match(/\{[\s\S]*\}/) || [])[0],
    (t.match(/\[[\s\S]*\]/) || [])[0],
  ];
  for (const c of candidates) {
    if (typeof c !== 'string' || !c) continue;
    try { return JSON.parse(c); } catch { /* try comma-stripped */ }
    try { return JSON.parse(stripTrailingCommas(c)); } catch { /* try control-char-sanitized */ }
    try { return JSON.parse(stripControlChars(stripTrailingCommas(c))); } catch { /* next candidate */ }
  }
  return null;
}

/**
 * Parse the full `claude -p --output-format stream-json --verbose` stdout into
 * `{ text, rec }`. PURE + testable (symmetric to gemini-cli's `parseGeminiCliFrames`),
 * so the SR-5 attestation logic is unit-tested with no subprocess.
 *
 * Served-model discovery (Phase 1.3): the Claude stream exposes the served model on
 * (in order of authority) the `result` envelope's `model`, then each `assistant`
 * message's `message.model`, then the `system`/init envelope's `model`. Whichever is
 * present POSITIVELY attests (`model_attested:true`); if NONE exposes a served-model id
 * the stamp DEGRADES (SR-5 — never fabricate). Today `claude -p` emits the model on the
 * assistant/init frames, so the positive branch is exercised live; the degrade branch
 * is the documented fallback if a future CLI build drops the field.
 * @param {string} stdout            raw newline-delimited JSON frames
 * @param {object} [meta]
 * @param {string} [meta.label]
 * @param {?number}[meta.cli_status] process exit code
 * @returns {{ text:string, rec:object }}
 */
export function parseClaudeFrames(stdout, {
  label = '(unlabeled)', cli_status = null, requested_model = null,
} = {}) {
  let finalEnv = null, lastText = '', tools = 0, servedModel = null;
  for (const raw of String(stdout).split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    let o; try { o = JSON.parse(line); } catch { continue; }
    if (o.type === 'system' && typeof o.model === 'string' && o.model) {
      servedModel = servedModel || o.model;
    } else if (o.type === 'assistant' && o.message?.content) {
      if (typeof o.message.model === 'string' && o.message.model) servedModel = o.message.model;
      for (const x of o.message.content) {
        if (x.type === 'tool_use') { tools++; }
        else if (x.type === 'text' && x.text?.trim()) { lastText = x.text.trim(); }
      }
    } else if (o.type === 'result') {
      finalEnv = o;
      if (typeof o.model === 'string' && o.model) servedModel = o.model; // most authoritative
    }
  }
  const rec = {
    label, cli_status,
    ok: cli_status === 0 && !!finalEnv && finalEnv.is_error === false,
    status: cli_status === 0 && !!finalEnv && finalEnv.is_error === false
      ? 'success'
      : 'cli_error',
    requested_model,
    duration_ms: finalEnv?.duration_ms ?? null, tools,
    output_tokens: finalEnv?.usage?.output_tokens ?? null,
    cost_usd: finalEnv?.total_cost_usd ?? null,
    ...attestStamp(servedModel), // SR-5 served-model stamp
  };
  rec.model_family = rec.ok ? 'claude' : null;
  rec.family_attested = rec.ok;
  return { text: finalEnv?.result ?? lastText ?? '', rec, _finalEnv: finalEnv };
}

/**
 * Resolve the designated Claude model for this call — the per-role ladder, mirroring
 * `resolveGeminiModel` (gemini-cli.mjs): explicit `model` wins, then a per-role env
 * (`CLAUDE_MODEL_<ROLE>`, role taken from `role` else the label's prefix before
 * ':' / '#' / '.'), then the global `CLAUDE_MODEL`, else null (the CLI session
 * default — the pre-existing behavior, so unset env changes nothing).
 * This is what makes `CLAUDE_MODEL_EXECUTE=claude-fable-5` (etc.) reachable on every
 * path that flows through this driver.
 */
/**
 * TRIO_TIER (John 2026-07-04): one switch that flips every Claude seat of a run.
 *  - heavy    => the latest frontier Claude ("Fable builds") — for work that
 *                genuinely needs the top tier.
 *  - standard => one notch below frontier — the affordable default for builds
 *                whose rigor lives in the machinery (gates/reviewers/guards),
 *                not the builder's model tier.
 * Both tiers keep the 5:1 pattern (Gemini holds the checking seats regardless).
 * Precedence: an explicit opts.model (e.g. a project's foreman.config.json
 * models block) still wins over everything; TRIO_TIER, when set, deliberately
 * BEATS the setx-pinned CLAUDE_MODEL/CLAUDE_MODEL_<ROLE> user env — those encode
 * the old always-heavy default, and the point of the switch is to flip a run
 * without unpinning machine-wide env. Update ids when a new frontier ships.
 */
const TIER_CLAUDE_MODELS = {
  heavy: 'claude-fable-5',
  // one notch below frontier (2026-07-27): Opus 5 — was claude-opus-4-8 until Opus 5 shipped
  standard: 'claude-opus-5',
};

/** The Claude model ONE NOTCH BELOW frontier (the `standard` tier) — the failover target when a
 * non-Claude verification seat can't serve its attested requested model. Symbolic so it TRACKS
 * the ladder as frontier ships forward; never hard-coded at the call site (John 2026-07-17). */
export function belowFrontierClaudeModel() { return TIER_CLAUDE_MODELS.standard; }

export function resolveClaudeModel({ model, role, label, env = process.env } = {}) {
  if (model) return model;
  const tier = String(env.TRIO_TIER || '').trim().toLowerCase();
  if (tier && TIER_CLAUDE_MODELS[tier]) return TIER_CLAUDE_MODELS[tier];
  const key = normalizeRole({ role, label }) || '';
  const roleKey = key ? `CLAUDE_MODEL_${key.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}` : null;
  return (roleKey && env[roleKey]) || env.CLAUDE_MODEL || null;
}

/**
 * Live transport: spawn `claude -p` and resolve `{ text, rec }` once the stream's
 * result envelope arrives. ENV-GATED — throws unless CRUCIBLE_AGENT_LIVE=1 so it
 * can never fire by accident (tests inject a stub instead).
 */
export function defaultRunClaude(fullPrompt, label, {
  env = process.env,
  target = process.cwd(),
  allowedTools = DEFAULT_ALLOWED_TOOLS,
  model = null,
  role = null,
  timeoutMs = (Number(env.CLAUDE_CALL_TIMEOUT_MS) || 20 * 60000),
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
      'live agent seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `claude -p` sub-agent, or inject a stub `runClaude` (tests/orchestrator)',
    );
  }
  const args = [...BASE_ARGS, '--allowedTools', allowedTools];
  if (isVerificationRole({ role, label })) {
    const modeIndex = args.indexOf('--permission-mode');
    if (modeIndex !== -1) args[modeIndex + 1] = 'plan';
    const toolsIndex = args.indexOf('--allowedTools');
    if (toolsIndex !== -1) args[toolsIndex + 1] = 'Read,Glob,Grep';
  }
  const mdl = resolveClaudeModel({ model, role, label, env });
  if (mdl) args.push('--model', mdl);
  const cmdName = platform === 'win32' ? 'claude.exe' : 'claude';
  return processRunner({
    command: cmdName,
    args,
    options: { cwd: target, env, shell: false, windowsHide: true },
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
    const { text, rec, _finalEnv } = parseClaudeFrames(result.stdout, {
      label,
      cli_status: result.code,
      requested_model: mdl,
    });
    if (result.terminal !== 'closed') {
      rec.ok = false;
      rec.status = result.terminal;
      rec.error = result.error || result.stderr.slice(0, 500);
    }
    rec.timed_out = result.terminal === 'timeout';
    rec.aborted = result.terminal === 'aborted';
    rec.kill_status = result.kill_status;
    if (!_finalEnv) {
      log(`!! ${label}: no result envelope. stderr=${result.stderr.slice(0, 300)}`);
    }
    return { text, rec };
  });
}

/**
 * Build the `agent()` seam.
 * @param {object} [o]
 * @param {?Function} [o.runClaude]  injected transport `(prompt,label)=>Promise<{text}>`
 *                                   (omit to use the env-gated live `claude -p`).
 * @param {object}    [o.env=process.env]
 * @param {string}    [o.target=process.cwd()]  cwd for the live sub-agent
 * @param {string}    [o.allowedTools]
 * @param {Function}  [o.log=()=>{}]
 * @returns {{ agent: (prompt:string, opts?:object)=>Promise<any> }}
 */
export function makeAgentSeam(options = {}) {
  const {
    runClaude = null,
    env = process.env,
    target = process.cwd(),
    allowedTools = DEFAULT_ALLOWED_TOOLS,
    log = () => {},
  } = options;
  // Per-call opts (model/role) thread through as a third arg so the per-role model
  // ladder is reachable; injected `runClaude` stubs keep their 2-arg shape unharmed.
  const run = runClaude || ((prompt, label, callOpts = {}) =>
    defaultRunClaude(prompt, label, { ...options, env, target, allowedTools, log, ...callOpts }));

  async function agent(prompt, opts = {}) {
    const label = opts.label || '(unlabeled)';
    const callOpts = {
      model: opts.model,
      role: normalizeRole({ role: opts.role, label }),
      timeoutMs: opts.timeoutMs,
      signal: opts.signal,
    };
    return runCliSchemaAttempts({
      run,
      prompt,
      schema: opts.schema,
      label,
      callOpts,
      driverOpts: opts,
      familyName: 'Claude',
      log,
      parse: extractJson,
    });
  }

  return { agent };
}

/**
 * The Claude registry entry (the trio's default backend).
 *
 * `runAgent` is the pluggable interface (`drivers/index.mjs` dispatches to it):
 * it builds the env-gated/stubbable `agent()` seam and invokes it once. A test or
 * orchestrator may inject `runClaude` (a stub transport) to drive the full
 * schema/retry/failure logic with no subprocess. `freshContext` is accepted for
 * interface parity — claude -p spawns a fresh sub-agent process, so a fresh context
 * is the native behavior and the flag is a no-op for this backend.
 *
 * @type {{ name: string, subAgentCapable: boolean, structuredOutput: string,
 *          runAgent: (opts?: object) => Promise<any> }}
 */
export const claudeDriver = {
  name: 'claude',
  subAgentCapable: true,
  // Structured output comes from the CLI sub-agent: the schema is appended to the
  // prompt and the reply is parsed (retry-once-then-failure). Contrast the raw-API
  // backends, which use native JSON-mode / function-calling.
  structuredOutput: 'cli-subagent (prompt-suffix)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, model, role, timeoutMs, signal } = opts;
    // makeAgentSeam reads runClaude/env/target/allowedTools/log from the same opts
    // bag; an absent runClaude falls back to the env-gated live transport.
    // model/role thread through to the per-role ladder (resolveClaudeModel).
    const { agent } = makeAgentSeam(opts);
    return agent(prompt, { ...opts, schema, label, model, role, timeoutMs, signal });
  },
};

export default claudeDriver;


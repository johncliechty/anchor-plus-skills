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
//     tests drive the full schema/retry/abstain logic with zero subprocesses.
// The returned `agent(prompt, opts)` honors Workflow's contract: it returns text by
// default, and the validated object when `opts.schema` is supplied (retry-once then
// ABSTAIN on unparseable schema replies, exactly like run-live's C1 hardening).
//
// `claudeDriver` is the registry entry consumed by `drivers/index.mjs`; its
// `runAgent({ prompt, schema, freshContext })` is the pluggable interface. claude -p
// spawns a fresh sub-agent process, so `freshContext` is satisfied natively
// (subAgentCapable: true) and the flag is accepted as a no-op for this backend.

import { spawn } from 'node:child_process';

import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { attestStamp } from './attest.mjs';

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
export function parseClaudeFrames(stdout, { label = '(unlabeled)', cli_status = null } = {}) {
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
    ok: !!finalEnv && finalEnv.is_error === false,
    duration_ms: finalEnv?.duration_ms ?? null, tools,
    output_tokens: finalEnv?.usage?.output_tokens ?? null,
    cost_usd: finalEnv?.total_cost_usd ?? null,
    ...attestStamp(servedModel), // SR-5 served-model stamp
  };
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
  const key = String(role || '').trim() || String(label || '').split(/[:#.\s]/)[0];
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
  // Per-call hard ceiling (2026-07-02 live finding: a stage1 revise call sat
  // >35 min — this seam had NO timeout while run-live has a 20-min guard; now
  // both do). On expiry the child is tree-killed and the call resolves as an
  // HONEST failure (ok:false, timed_out) the caller's retry/abstain logic sees.
  // Override via CLAUDE_CALL_TIMEOUT_MS; <=0 disables.
  timeoutMs = (Number(env.CLAUDE_CALL_TIMEOUT_MS) || 20 * 60000),
  log = () => {},
} = {}) {
  if (env.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError(
      'live agent seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `claude -p` sub-agent, or inject a stub `runClaude` (tests/orchestrator)',
    );
  }
  return new Promise((resolve) => {
    const args = [...BASE_ARGS, '--allowedTools', allowedTools];
    // NOTE: the long-form --model flag — this CLI build rejects a short -m
    // (proven live 2026-07-02: `error: unknown option '-m'`).
    const mdl = resolveClaudeModel({ model, role, label, env });
    if (mdl) { args.push('--model', mdl); }
    
    const isWin = process.platform === 'win32';
    // claude.exe, NEVER claude.cmd: modern Node refuses to spawn a .cmd with
    // shell:false (EINVAL) — the documented host fact run-live.mjs was already
    // patched for; this seam hit it live 2026-07-02.
    const cmdName = isWin ? 'claude.exe' : 'claude';
    const child = spawn(cmdName, args, { cwd: target, env, shell: false, windowsHide: true });
    
    const killChild = () => {
      try {
        if (process.platform === 'win32') {
          import('node:child_process').then(cp => cp.spawnSync('taskkill', ['/pid', child.pid, '/t', '/f']));
        } else {
          child.kill('SIGKILL');
        }
      } catch {}
    };
    const onExit = () => killChild();
    const onSigInt = () => { killChild(); process.exit(130); };
    process.on('exit', onExit);
    process.on('SIGINT', onSigInt);

    let out = '', stderr = '';
    let timer = null;
    let timedOut = false;
    if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        log(`!! ${label}: per-call timeout (${Math.round(timeoutMs / 60000)}m) — tree-killing the hung child`);
        killChild();
      }, timeoutMs);
      if (typeof timer.unref === 'function') timer.unref();
    }
    child.stdout.on('data', (d) => { out += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    child.on('close', (code) => {
      if (timer) clearTimeout(timer);
      process.removeListener('exit', onExit);
      process.removeListener('SIGINT', onSigInt);
      const { text, rec, _finalEnv } = parseClaudeFrames(out, { label, cli_status: code });
      if (timedOut) rec.timed_out = true;
      if (!_finalEnv) log(`!! ${label}: no result envelope${timedOut ? ' (per-call timeout kill)' : ''}. stderr=${stderr.slice(0, 300)}`);
      resolve({ text, rec });
    });
    child.stdin.on('error', (err) => { log(`!! ${label}: stdin EPIPE - child likely exited early. err=${err.message}`); });
    child.stdin.write(fullPrompt);
    child.stdin.end();
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
export function makeAgentSeam({
  runClaude = null,
  env = process.env,
  target = process.cwd(),
  allowedTools = DEFAULT_ALLOWED_TOOLS,
  log = () => {},
} = {}) {
  // Per-call opts (model/role) thread through as a third arg so the per-role model
  // ladder is reachable; injected `runClaude` stubs keep their 2-arg shape unharmed.
  const run = runClaude || ((prompt, label, callOpts = {}) =>
    defaultRunClaude(prompt, label, { env, target, allowedTools, log, ...callOpts }));

  async function agent(prompt, opts = {}) {
    const label = opts.label || '(unlabeled)';
    const callOpts = { model: opts.model, role: opts.role };
    const schemaSuffix = opts.schema
      ? `\n\nRespond with ONLY a single raw JSON object (no markdown fences, no prose) ` +
        `that conforms to this JSON Schema:\n${JSON.stringify(opts.schema)}`
      : '';
    const { text } = await run(prompt + schemaSuffix, label, callOpts);
    if (!opts.schema) return text;

    let obj = extractJson(text);
    if (!obj) {
      log(`   !! ${label} reply was not valid JSON — retrying once (strict reprompt)`);
      const strict = `${prompt}\n\nYour previous reply was NOT valid JSON and could not be parsed. ` +
        `Respond with ONLY a single raw JSON object that conforms to this JSON Schema — ` +
        `no prose, no markdown fences, nothing else:\n${JSON.stringify(opts.schema)}`;
      obj = extractJson((await run(strict, `${label}#retry`, callOpts)).text);
    }
    if (!obj) {
      log(`   !! ${label} still unparseable after retry — TRANSPORT FAILURE (abstain; degradable)`);
      return {
        answerable: 'no',
        transport_failed: true,
        note: `reviewer ${label} response was not parseable JSON after one retry ` +
          `(transport failure, not a plan problem)`,
        findings: [],
      };
    }
    return obj;
  }

  return { agent };
}

/**
 * The Claude registry entry (the trio's default backend).
 *
 * `runAgent` is the pluggable interface (`drivers/index.mjs` dispatches to it):
 * it builds the env-gated/stubbable `agent()` seam and invokes it once. A test or
 * orchestrator may inject `runClaude` (a stub transport) to drive the full
 * schema/retry/abstain logic with no subprocess. `freshContext` is accepted for
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
  // prompt and the reply is parsed (retry-once-then-ABSTAIN). Contrast the raw-API
  // backends, which use native JSON-mode / function-calling.
  structuredOutput: 'cli-subagent (prompt-suffix)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, model, role } = opts;
    // makeAgentSeam reads runClaude/env/target/allowedTools/log from the same opts
    // bag; an absent runClaude falls back to the env-gated live transport.
    // model/role thread through to the per-role ladder (resolveClaudeModel).
    const { agent } = makeAgentSeam(opts);
    return agent(prompt, { schema, label, model, role });
  },
};

export default claudeDriver;


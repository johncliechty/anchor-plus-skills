// drivers/grok-cli.mjs — Grok Build **subscription** CLI backend (`grok -p` / `grok --single`).
//
// This is the seat family for coding_family=grok / review_family=grok when the user is
// logged into Grok Build (OAuth), NOT the raw xAI HTTP API (that remains drivers/grok.mjs
// under driver name `grok` for optional API-key use).
//
// Capability: subAgentCapable true — spawns a fresh `grok.exe` process per call (same
// shape as claude-cli / gemini-cli). Structured output: schema appended to the prompt +
// JSON parse with retry-once-then-ABSTAIN (mirrors makeAgentSeam in claude.mjs).
//
// Live gate: CRUCIBLE_AGENT_LIVE=1 (same as Claude/Gemini CLI seats).

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { extractJson } from './claude.mjs';

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
  log = () => {},
} = {}) {
  if (env.CRUCIBLE_AGENT_LIVE !== '1') {
    throw new HaltError(
      'live Grok CLI seam is disabled',
      'set CRUCIBLE_AGENT_LIVE=1 to spawn a real `grok -p` sub-agent (subscription), or inject runGrokCli',
    );
  }
  return new Promise((resolve) => {
    const isWin = process.platform === 'win32';
    const cmdName = isWin ? 'grok.exe' : 'grok';
    // Prefer argv prompt when short; long prompts via --prompt-file to avoid ENAMETOOLONG.
    const useFile = Buffer.byteLength(fullPrompt, 'utf8') > 24000;
    const args = ['--output-format', 'plain'];
    const mdl = resolveGrokCliModel({ model, role, env });
    if (mdl) args.push('--model', mdl);
    // Permission mode for agentic seats (Foreman/Crucible edits). Override via env.
    const perm = env.GROK_CLI_PERMISSION_MODE || 'acceptEdits';
    if (perm) args.push('--permission-mode', perm);

    let tmpPath = null;
    if (useFile) {
      tmpPath = path.join(os.tmpdir(), `grok-cli-prompt-${process.pid}-${Date.now()}.txt`);
      fs.writeFileSync(tmpPath, fullPrompt, 'utf8');
      args.push('--prompt-file', tmpPath);
    } else {
      args.push('-p', fullPrompt);
    }

    const child = spawn(cmdName, args, {
      cwd: target,
      env: { ...env, NO_COLOR: '1', CI: '1' },
      shell: false,
      windowsHide: true,
    });

    const killChild = () => {
      try {
        if (process.platform === 'win32') {
          spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true });
        } else {
          child.kill('SIGKILL');
        }
      } catch { /* best-effort */ }
    };

    let out = '';
    let stderr = '';
    let timedOut = false;
    let timer = null;
    if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        log(`!! ${label}: Grok CLI timeout (${Math.round(timeoutMs / 60000)}m) — killing child`);
        killChild();
      }, timeoutMs);
      if (typeof timer.unref === 'function') timer.unref();
    }

    child.stdout.on('data', (d) => { out += d.toString(); });
    child.stderr.on('data', (d) => { stderr += d.toString(); });
    child.on('error', (err) => {
      if (timer) clearTimeout(timer);
      log(`!! ${label}: failed to spawn grok: ${err.message}`);
      resolve({
        text: '',
        rec: { label, ok: false, status: 'spawn_error', error: String(err.message), timed_out: false },
      });
    });
    child.on('close', (code) => {
      if (timer) clearTimeout(timer);
      if (tmpPath) {
        try { fs.unlinkSync(tmpPath); } catch { /* ignore */ }
      }
      const text = String(out || '').trim();
      const rec = {
        label,
        cli_status: code,
        ok: code === 0 && text.length > 0 && !timedOut,
        status: timedOut ? 'timeout' : (code === 0 ? (text ? 'success' : 'no_reply') : 'cli_error'),
        model_served: mdl || 'session-default',
        model_family: 'grok',
        model_attested: true,
        timed_out: timedOut,
      };
      if (!rec.ok) {
        log(`!! ${label}: grok-cli exit=${code} timedOut=${timedOut} stderr=${stderr.slice(0, 300)}`);
      }
      resolve({ text, rec });
    });
  });
}

/**
 * Required-boolean conformance for a parsed reply against the call's JSON Schema:
 * every `required` property the schema types as boolean must BE a boolean on the
 * object. Schemas with no required booleans (shark/reviewer shapes) trivially
 * conform — this gate exists for verdict schemas like Jumper Gate-3's `passed`.
 * PURE + exported for the driver test gate.
 */
export function conformsRequiredBooleans(obj, schema) {
  if (!obj || typeof obj !== 'object') return false;
  const req = Array.isArray(schema?.required) ? schema.required : [];
  return req.every((k) =>
    schema?.properties?.[k]?.type !== 'boolean' || typeof obj[k] === 'boolean');
}

/**
 * Agent seam: optional schema → JSON parse with one strict retry then ABSTAIN object.
 *
 * 2026-08-20 (Jumper gate-3 repair): the strict retry now ALSO fires when the first
 * reply PARSES but lacks a schema-required boolean (e.g. no boolean `passed`).
 * Before, a parsed-but-shapeless reply was returned WITHOUT any retry — the live
 * grok seat never got its second chance and Jumper HALTed on a nonconforming
 * verdict. Still exactly ONE retry total; still NEVER a verdict invented from
 * prose: a reply that stays shapeless after the retry is returned as-is for the
 * caller's own honesty gate, and a reply that stays unparseable abstains.
 */
export function makeGrokCliAgentSeam({
  runGrokCli = null,
  env = process.env,
  target = process.cwd(),
  log = () => {},
} = {}) {
  const run = runGrokCli || ((prompt, label, callOpts = {}) =>
    defaultRunGrokCli(prompt, label, { env, target, log, ...callOpts }));

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
    if (!obj || !conformsRequiredBooleans(obj, opts.schema)) {
      const why = !obj
        ? 'was NOT valid JSON and could not be parsed'
        : 'parsed as JSON but did not carry the schema-required boolean field(s) as booleans';
      log(`   !! ${label} reply ${!obj ? 'was not valid JSON' : 'parsed but was nonconforming (missing required boolean)'} — retrying once (strict reprompt)`);
      const strict = `${prompt}\n\nYour previous reply ${why}. ` +
        `Respond with ONLY a single raw JSON object that conforms to this JSON Schema — ` +
        `no prose, no markdown fences, nothing else:\n${JSON.stringify(opts.schema)}`;
      const retryObj = extractJson((await run(strict, `${label}#retry`, callOpts)).text);
      // Prefer the retry's parse; if the retry came back unparseable, keep the
      // first parse (when one exists) — never trade a real object for nothing.
      obj = retryObj ?? obj;
    }
    if (!obj) {
      log(`   !! ${label} still unparseable after retry — TRANSPORT FAILURE (abstain; degradable)`);
      return {
        answerable: 'no',
        transport_failed: true,
        note: `reviewer ${label} response was not parseable JSON after one retry (transport failure, not a plan problem)`,
        findings: [],
      };
    }
    return obj;
  }

  return { agent };
}

export const grokCliDriver = {
  name: 'grok-cli',
  subAgentCapable: true,
  structuredOutput: 'cli-subagent (prompt-suffix + json parse)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, model, role, log } = opts;
    const { agent } = makeGrokCliAgentSeam(opts);
    return agent(prompt, { schema, label, model, role });
  },
};

export default grokCliDriver;

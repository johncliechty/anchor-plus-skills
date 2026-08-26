#!/usr/bin/env node
// run-live.mjs — drive a REAL project to done with LIVE `claude -p` sub-agents on the
// subscription, through Foreman's production agent() seam (C1/C2 hardened), with budget
// caps + git hygiene + a durable status log. Generalized from foreman-targets/_calib-run.mjs.
//
//   node run-live.mjs <projectDir> [--reviewers N] [--cap K] [--max-waves N]
//        [--max-wallclock-min M] [--git] [--branch NAME] [--status <file>]
//        [--allowed-tools "Bash,Edit,Write,Read,Glob,Grep"]
//
// GROUND TRUTH stays the orchestrator-run gate (the discovered test command); sub-agents
// only drive execute/review/fix. NO ANTHROPIC_API_KEY in env => subscription usage; the
// per-call `$` is a subscription EQUIVALENT-cost estimate, not a metered API charge.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn, spawnSync } from 'node:child_process';

import { classifyExit, makeTelemetryRecord } from './transport.mjs';
import { spawnGuarded, makeChildRegistry, acquireLock } from './proc-guard.mjs';
import { resolveClaudeModel } from '../../drivers/claude.mjs';
import { installProcessLifetimeGuards } from '../../drivers/process-lifetime.mjs';

const argv = process.argv.slice(2);
function flag(name, def) { const i = argv.indexOf(name); return i >= 0 && i + 1 < argv.length ? argv[i + 1] : def; }
const PROJECT = path.resolve(argv.find((a) => !a.startsWith('--')) || process.cwd());
let REVIEWERS = Number(flag('--reviewers', '2'));
const CAP = Number(flag('--cap', '3'));
const MAX_WAVES = flag('--max-waves', null);
const MAX_WALL_MIN = flag('--max-wallclock-min', null);
const USE_GIT = argv.includes('--git');
const RESUME = argv.includes('--resume');
// --clear-halt: human acknowledgment that a HALTED checkpoint's blocker is handled.
// Idempotent no-op on non-halted checkpoints; resume still re-proves GREEN at the gate.
const CLEAR_HALT = argv.includes('--clear-halt');
// Escape hatch for vacuous-GREEN clear-halt refuse (0076 package 3) — still requires --resume.
const CLEAR_HALT_FORCE = argv.includes('--force') || argv.includes('--clear-halt-force');
const BRANCH = flag('--branch', null);
const STATUS_FILE = flag('--status', path.join(PROJECT, '_foreman-status.log'));
const ALLOWED = flag('--allowed-tools', 'Bash,Edit,Write,Read,Glob,Grep');
// Wave 7: per-call hard timeout (SIGKILL a hung sub-agent) + the single-run lock.
// 2026-08-25 (journals 0102/0103, John-ratified card): default raised 20→45 — the 20-min
// default SIGKILLed HEALTHY agents in two builds after diagnosis (cross-repo/content waves
// legitimately need 43+ min). The floor is the dead-process backstop, not the supervisor.
const CALL_TIMEOUT_MIN = flag('--call-timeout-min', '45');
const CALL_TIMEOUT_MS = Number(CALL_TIMEOUT_MIN) > 0 ? Number(CALL_TIMEOUT_MIN) * 60000 : null;
if (CALL_TIMEOUT_MS !== null && Number(CALL_TIMEOUT_MIN) < 45) {
  console.log(`!! call-timeout ${CALL_TIMEOUT_MIN}m is below the 45m floor (journals 0102/0103: healthy agents killed at 20m) — proceeding as explicitly instructed`);
}
if (CALL_TIMEOUT_MS === null) {
  console.log('!! per-call timeout DISABLED (--call-timeout-min 0) — NO dead-process backstop this run; a hung agent will hang the wave (explicit operator choice, named here)');
}
const LOCK_FILE = flag('--lock', path.join(PROJECT, '.foreman', 'run.lock'));

// F-H sleep fix (0072): fail-loud guards + heartbeat so mid-wave deaths leave forensics
// (uncaughtException / unhandledRejection previously could exit with empty stderr).
const _lifetime = installProcessLifetimeGuards({
  log: (s) => {
    try {
      const line = `[${new Date().toISOString().slice(11, 19)}] ${s}\n`;
      fs.appendFileSync(STATUS_FILE, line);
    } catch { /* never crash on logging */ }
  },
  crashPath: path.join(PROJECT, '.foreman', 'last-crash.json'),
  heartbeatPath: path.join(PROJECT, '.foreman', 'heartbeat.json'),
  label: 'foreman-run-live',
});

const CLAUDE_ARGS = ['-p', ' ', '--output-format', 'stream-json', '--verbose',
  '--permission-mode', 'acceptEdits', '--allowedTools', ALLOWED,
  // The orchestrator owns ALL git (commit-on-GO, branch, reconcile). Secondary guard
  // (the prompt is the primary one) using the documented space-form pattern.
  '--disallowedTools', 'Bash(git *)'];

// Phase-1: Foreman inherit-only via @foundry/triage foreman-wire (never re-triage;
// LITE/LIGHT never map to 0 reviewers). Explicit --reviewers still wins.
// Resolve without hardcoding host paths (collaborator / package ship).
import { importFoundryTriage } from '../../drivers/foundry-triage-resolve.mjs';
const { inheritReviewerCount } = await importFoundryTriage('foreman-wire.mjs');

// Declarative per-role model routing from the project's foreman.config.json "models"
// block, e.g. {"models":{"execute":"claude:claude-fable-5","fix":"claude:claude-fable-5",
// "review":"gemini-cli:gemini-3.1-pro"}}. Each entry is exported as per-role env —
// CLAUDE_MODEL_<ROLE> for claude, TRIO_DRIVER_<ROLE>+TRIO_MODEL_<ROLE> for another
// backend — which both the bespoke transport below and the registry drivers resolve.
// Pre-set env always wins (config never overrides an explicit operator choice).
try {
  const cfg = JSON.parse(fs.readFileSync(path.join(PROJECT, 'foreman.config.json'), 'utf8'));

  // Inherit process depth → reviewer fan-out from Stage-0 handoff (triage / triage_track).
  // Explicit --reviewers always wins; else inheritReviewerCount (LITE→1, FULL→2, never 0).
  if (!argv.includes('--reviewers')) {
    const inherited = inheritReviewerCount(cfg, { defaultCount: REVIEWERS });
    REVIEWERS = Math.max(1, Number(inherited.reviewers) || 1);
    if (inherited.depth) {
      process.env.FOREMAN_BAND_DEPTH = inherited.depth;
      process.env.FOREMAN_BAND_LABEL = inherited.depth;
      process.env.FOREMAN_TRIAGE_INHERIT = inherited.source || 'inherit';
    }
  } else {
    // Still stamp depth for telemetry when CLI overrides reviewer count.
    const inherited = inheritReviewerCount(cfg, { defaultCount: REVIEWERS });
    if (inherited.depth) {
      process.env.FOREMAN_BAND_DEPTH = inherited.depth;
      process.env.FOREMAN_BAND_LABEL = inherited.depth;
    }
  }

  for (const [role, spec] of Object.entries(cfg.models || {})) {
    const s = String(spec); const i = s.indexOf(':');
    const drv = i > 0 ? s.slice(0, i) : 'claude';
    const model = i > 0 ? s.slice(i + 1) : s;
    const R = role.toUpperCase().replace(/[^A-Z0-9]+/g, '_');
    if (drv === 'claude') {
      if (!process.env[`CLAUDE_MODEL_${R}`]) process.env[`CLAUDE_MODEL_${R}`] = model;
    } else {
      if (!process.env[`TRIO_DRIVER_${R}`]) process.env[`TRIO_DRIVER_${R}`] = drv;
      if (!process.env[`TRIO_MODEL_${R}`]) process.env[`TRIO_MODEL_${R}`] = model;
    }
  }
} catch { /* no config or no models block — env-only routing */ }

// Dashboard / ~/.anchor/model_prefs.json → TRIO_DRIVER_<ROLE> when unset (never overrides
// explicit env or foreman.config.json models block above).
try {
  const { applyFamilyPrefsToEnv } = await import('../../drivers/index.mjs');
  applyFamilyPrefsToEnv(process.env);
} catch { /* registry optional at this load point — env-only */ }

// Once: never let a broken parent pipe kill the engine (canonical onboard 2026-07-24
// last-crash: uncaughtException EPIPE at emit → process.stdout.write).
if (process.stdout && !process.stdout.__foremanEpipeHooked) {
  process.stdout.on('error', () => { /* EPIPE/EIO when parent closed — continue on file log */ });
  process.stdout.__foremanEpipeHooked = true;
}
if (process.stderr && !process.stderr.__foremanEpipeHooked) {
  process.stderr.on('error', () => { /* same */ });
  process.stderr.__foremanEpipeHooked = true;
}

function emit(line) {
  // LOCAL wall-clock (2026-07-11 fix): the log-line prefix used UTC while the
  // Status-table header used local time, so a run read as two clocks 6h apart.
  // The locked global format is human wall-clock — one clock, local, everywhere.
  const d = new Date();
  const stamp = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  const out = `[${stamp}] ${line}\n`;
  // Never throw on log write — durable status file is the source of truth for
  // operators; stdout is best-effort (parent shell may have closed the pipe).
  try { process.stdout.write(out); } catch { /* EPIPE etc. — keep going */ }
  try { fs.appendFileSync(STATUS_FILE, out); } catch { /* never crash on logging */ }
}

const calls = [];

// Wave 7 kill-on-exit: every spawned sub-agent is tracked here; an orchestrator
// teardown (clean exit OR SIGINT/SIGTERM) SIGKILLs any still-live child, so no
// leaked, wedged claude process survives the run (the induced-kill invariant).
const registry = makeChildRegistry({ log: emit });
registry.install();

function extractJson(text) {
  if (typeof text !== 'string') return null;
  let t = text.trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  try { return JSON.parse(t); } catch { /* try substring */ }
  const m = t.match(/\{[\s\S]*\}/);
  if (m) { try { return JSON.parse(m[0]); } catch { /* fall through */ } }
  return null;
}

function runClaude(fullPrompt, label) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const secs = () => Math.round((Date.now() - t0) / 1000);
    emit(`┌ ${label} … launching agent` + (CALL_TIMEOUT_MS ? ` (per-call timeout ${CALL_TIMEOUT_MIN}m)` : ''));
    // Spawn under the timeout + kill-on-exit guard (proc-guard). `done` resolves
    // with the typed-exit inputs; we attach our own stream-json listeners to the
    // returned child for the served-model/tool/usage telemetry.
    const isWin = process.platform === 'win32';
    // Per-role model pin: role derives from the label prefix (execute:/review:/fix:),
    // resolved through the driver ladder (CLAUDE_MODEL_<ROLE> → CLAUDE_MODEL → session
    // default). No env set ⇒ args are unchanged (the pre-existing behavior).
    const mdl = resolveClaudeModel({ label, env: process.env });
    // --model long form: this CLI build rejects -m (proven live 2026-07-02).
    const args = mdl ? [...CLAUDE_ARGS, '--model', mdl] : CLAUDE_ARGS;
    const { child, done } = spawnGuarded({
      command: isWin ? 'claude.exe' : 'claude', args, cwd: PROJECT, timeoutMs: CALL_TIMEOUT_MS, registry,
      spawnImpl: (cmd, args, opts) => spawn(cmd, args, { ...opts, shell: false, windowsHide: true })
    });
    let buf = '', finalEnv = null, tools = 0, lastText = '', servedModel = null, stderr = '';
    const tick = setInterval(() => emit(`│ ${label} … working — ${secs()}s, ${tools} tool call(s) so far`), 20000);
    if (typeof tick.unref === 'function') tick.unref();

    if (child) {
      child.stdout.on('data', (d) => {
        buf += d.toString();
        let nl;
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
          if (!line.trim()) continue;
          let o; try { o = JSON.parse(line); } catch { continue; }
          if (o.type === 'system' && typeof o.model === 'string' && o.model) {
            servedModel = servedModel || o.model; // init/system envelope carries the served model
          }
          if (o.type === 'assistant' && o.message?.content) {
            if (typeof o.message.model === 'string' && o.message.model) servedModel = o.message.model;
            for (const x of o.message.content) {
              if (x.type === 'tool_use') {
                tools++;
                const hint = x.input?.file_path ? ` ${String(x.input.file_path).split(/[\\/]/).pop()}`
                  : x.input?.command ? ` ${String(x.input.command).slice(0, 44)}` : '';
                emit(`│ ${label} → ${x.name}${hint}  (${secs()}s)`);
              } else if (x.type === 'text' && x.text?.trim()) { lastText = x.text.trim(); }
            }
          } else if (o.type === 'result') {
            finalEnv = o;
            if (typeof o.model === 'string' && o.model) servedModel = o.model; // result envelope is authoritative
          }
        }
      });
      child.stderr.on('data', (d) => { stderr += d.toString(); });
      child.stdin.on('error', (err) => { emit(`!! ${label}: stdin EPIPE - child likely exited early. err=${err.message}`); });
      child.stdin.write(fullPrompt);
      child.stdin.end();
    }

    done.then(({ code, signal, timedOut, spawnError }) => {
      clearInterval(tick);
      // Wave 7: TYPE the outcome (exit-class taxonomy) and stamp a schema-valid
      // per-call telemetry record. Every call is classified — no unclassified exit.
      const classification = classifyExit({ spawnError, timedOut, code, signal, finalEnv });
      const u = finalEnv?.usage || {};
      const rec = makeTelemetryRecord({
        label,
        classification,
        cli_status: typeof code === 'number' ? code : null,
        signal: signal || null,
        duration_ms: finalEnv?.duration_ms ?? (Date.now() - t0),
        tools,
        output_tokens: u.output_tokens ?? null,
        cost_usd: finalEnv?.total_cost_usd ?? null,
        permission_denials: Array.isArray(finalEnv?.permission_denials) ? finalEnv.permission_denials.length : null,
        servedModel,
      });
      calls.push(rec);
      // SPIKE(foreman-parallel): passive per-call phase-timing sink for phase-report.mjs.
      // Append-only, off the hot path's critical work; the run never crashes on logging.
      try {
        fs.mkdirSync(path.join(PROJECT, '.foreman'), { recursive: true });
        fs.appendFileSync(path.join(PROJECT, '.foreman', 'phase-timings.jsonl'),
          JSON.stringify({ kind: 'call', label: rec.label, duration_ms: rec.duration_ms,
            output_tokens: rec.output_tokens, cost_usd: rec.cost_usd, ts: Date.now() }) + '\n');
      } catch { /* never crash the run on logging */ }
      emit(`└ ${label} done — class ${rec.exit_class}, code ${code ?? signal ?? '?'}, ok ${rec.ok}, ${tools} tools, ` +
        `out ${rec.output_tokens}tok, ~$${(rec.cost_usd ?? 0).toFixed(4)} est (subscription equiv, not an API charge), ` +
        `${rec.duration_ms}ms` + (rec.permission_denials ? `, denials ${rec.permission_denials}` : ''));
      if (!finalEnv) emit(`   !! ${classification.detail}${stderr ? `. stderr=${stderr.slice(0, 300)}` : ''}`);
      resolve({ text: finalEnv?.result ?? lastText ?? '', rec });
    });
  });
}

// C1: retry-then-abstain on a malformed schema (review) reply.
async function agent(prompt, opts = {}) {
  const label = opts.label || '(unlabeled)';
  // Per-role backend dispatch (the 5:1 seam): a TRIO_DRIVER_<ROLE> env (typically set
  // from foreman.config.json's "models" block above) routes THIS role to another
  // registry backend — e.g. review → gemini-cli while execute/fix stay on the bespoke
  // claude transport below. The registry driver owns its own schema/retry/abstain.
  const role = String(opts.role || label).split(/[:#.\s]/)[0].toLowerCase();
  const roleDriver = process.env[`TRIO_DRIVER_${role.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`];
  if (roleDriver && roleDriver !== 'claude') {
    return runAgent({
      prompt, schema: opts.schema, label, role, driver: roleDriver,
      freshContext: true, target: PROJECT, log: (s) => emit(s),
    });
  }
  const schemaSuffix = opts.schema
    ? `\n\nRespond with ONLY a single raw JSON object (no markdown fences, no prose) ` +
      `that conforms to this JSON Schema:\n${JSON.stringify(opts.schema)}`
    : '';
  const { text, rec } = await runClaude(prompt + schemaSuffix, label);
  // 0102: THE DISCRIMINATING FIELD IS ok:false, FULL STOP. A per-call-timeout
  // SIGKILL of a 20-minute, 60-tool execute was logged "execute complete" and
  // auto-advanced to a gate that would have gone GREEN on the previous wave's
  // tree — because this function destructured only { text } and the rec died
  // here. A dead agent now returns a TYPED failure marker (never bare '') so
  // the engine can HALT loudly instead of blessing an empty step. Deliberately
  // a marker, not a throw: a timeout re-run dies at the same cap, so the right
  // move is a deterministic [taxonomy:agent-died] HALT with the cap named —
  // not a reliability-wrapper retry that pays for the same death twice.
  if (rec && rec.ok === false) {
    emit(`   !! ${label} agent DIED (class ${rec.exit_class}, ${rec.tools ?? 0} tools, ` +
      `${rec.duration_ms ?? '?'}ms) — typed failure, never "complete"`);
    return {
      agent_failed: true, exit_class: rec.exit_class, label,
      tools: rec.tools ?? 0, duration_ms: rec.duration_ms ?? null,
      detail: `agent ${label} died: class ${rec.exit_class}, ${rec.tools ?? 0} tool calls, ${rec.duration_ms ?? '?'}ms`,
    };
  }
  if (!opts.schema) return text;
  let obj = extractJson(text);
  if (!obj) {
    emit(`   !! ${label} reply was not valid JSON — retrying once (strict reprompt)`);
    const strict = `${prompt}\n\nYour previous reply was NOT valid JSON. Respond with ONLY a single raw JSON ` +
      `object conforming to this JSON Schema — no prose, no fences:\n${JSON.stringify(opts.schema)}`;
    obj = extractJson((await runClaude(strict, `${label}#retry`)).text);
  }
  if (!obj) {
    // T10 (2026-07-11): an unparseable reply is a TRANSPORT failure, not a plan
    // problem — it must never masquerade as the §4.7 "docs don't answer" ambiguity
    // HALT (observed live: one agy hiccup halted a whole run). Marked so the engine
    // DROPS this reviewer and proceeds with survivors; only ALL-failed halts.
    emit(`   !! ${label} still unparseable after one retry — marking transport_failed (engine proceeds with surviving reviewers)`);
    return { answerable: 'transport-failed', transport_failed: true, note: `reviewer ${label} response was not parseable JSON after one retry`, findings: [] };
  }
  return obj;
}

// BLOCKER-1 fix (Phase 1.1): resolve the engine TREE-RELATIVE to this file, never via
// an absolute `fil<path> archive path. `new URL(spec, import.meta.url)`
// pins resolution inside the canonical trio tree, so a renamed/removed archive can never
// be silently executed (asserted by drivers/test/canonical-no-escape.test.mjs).
const { runProject, clearHaltedCheckpoint } = await import(new URL('./project-engine.mjs', import.meta.url));
// Wave 4: obtain the foreman driver seam through the trio driver registry (claude
// default) rather than calling makeAgentDriver directly. The instrumented `agent`
// above is injected unchanged, so the live `claude -p` path stays byte-for-byte
// equivalent; the registry is the seam through which a future TRIO_DRIVER selection
// would swap the backend.
const { makeForemanDriver, runAgent } = await import('../../drivers/index.mjs');

try { fs.writeFileSync(STATUS_FILE, ''); } catch { /* fresh log */ }
emit(`=== FOREMAN LIVE RUN ===`);
emit(`project: ${PROJECT}`);
emit(`reviewers=${REVIEWERS} fixIterCap=${CAP} maxWaves=${MAX_WAVES ?? '∞'} maxWallClock=${MAX_WALL_MIN ?? '∞'}min git=${USE_GIT} branch=${BRANCH ?? 'foreman/run'}`);
if (process.env.FOREMAN_BAND_DEPTH) {
  emit(`band inherit: depth=${process.env.FOREMAN_BAND_DEPTH} · ${process.env.FOREMAN_BAND_LABEL || ''} · reviewers=${REVIEWERS}`);
}
emit(`binding: headless \`claude -p … --permission-mode acceptEdits --allowedTools ${ALLOWED}\` (cwd=project); ground truth = orchestrator gate`);
emit(`model routing: ${['execute', 'review', 'fix'].map((r) => {
  const R = r.toUpperCase();
  const d = process.env[`TRIO_DRIVER_${R}`];
  const m = d ? (process.env[`TRIO_MODEL_${R}`] || 'driver-default')
    : (process.env[`CLAUDE_MODEL_${R}`] || process.env.CLAUDE_MODEL || 'session-default');
  return `${r}=${d || 'claude'}:${m}`;
}).join(' · ')}`);

// Wave 7: acquire the single-run lock. A lock held by a LIVE pid refuses a
// concurrent run; a lock left by a crashed/killed run (dead pid) is stale and is
// reclaimed. The lock RELEASES on exit (clean OR signalled — registered below),
// so a mid-wave kill never wedges the next --resume out.
try { fs.mkdirSync(path.dirname(LOCK_FILE), { recursive: true }); } catch { /* dir may exist */ }

// --doctor: prove gate collects >0 tests then exit (0082 P2.13)
if (argv.includes('--doctor')) {
  try {
    const { resolveContract } = await import(new URL('./project-engine.mjs', import.meta.url));
    const { doctorTestCommand } = await import(new URL('./foreman-lib.mjs', import.meta.url));
    const c = resolveContract(PROJECT);
    const d = doctorTestCommand(c.testCmd.command, PROJECT);
    emit(`doctor: command=${d.command}`);
    emit(`doctor: ${d.ok ? 'OK' : 'FAIL'} tests=${d.tests} — ${d.note}`);
    process.exit(d.ok ? 0 : 3);
  } catch (e) {
    emit(`doctor: FAIL — ${e.reason || e.message}${e.detail ? ' — ' + e.detail : ''}`);
    process.exit(3);
  }
}

let lock;
try {
  lock = acquireLock(LOCK_FILE, {
    label: `run-live ${PROJECT}`,
    onStale: (prev) => {
      // 0082 P2.10: dead-process honesty — stamp checkpoint if present.
      emit(`[taxonomy:dead-process] reclaimed stale lock from dead pid ${prev.pid} (started ${prev.started_at ?? '?'})`);
      try {
        const cpPath = path.join(PROJECT, 'foreman-checkpoint.json');
        if (!fs.existsSync(cpPath)) return;
        const cp = JSON.parse(fs.readFileSync(cpPath, 'utf8'));
        if (cp && cp.status === 'running') {
          cp.status = 'halted';
          cp.pending_action = `dead-process: previous pid ${prev.pid} gone — resume re-proves at gate`;
          cp.last_verdict = cp.last_verdict || 'HALT';
          const tmp = `${cpPath}.${process.pid}.tmp`;
          fs.writeFileSync(tmp, JSON.stringify(cp, null, 2) + '\n', 'utf8');
          fs.renameSync(tmp, cpPath);
          emit(`checkpoint: stamped halted (dead-process) — use --resume after inspecting`);
        }
      } catch { /* best-effort forensics */ }
    },
  });
  emit(`lock: acquired ${LOCK_FILE} (pid ${process.pid})`);
} catch (e) {
  emit(`!! could not acquire run lock: ${e.reason || e.message}${e.detail ? ' — ' + e.detail : ''}`);
  process.exit(3);
}
process.on('exit', () => { try { lock.release(); } catch { /* best-effort */ } });

// ---- Sibling-repo cleanliness pre-flight (2026-08-25 — journal 0102 defect 2, John-ratified
// card): a wave that wrote outside its repo once reported GREEN over a DIRTY sibling with
// nothing complaining. Before the engine starts, every OTHER git repo the plan text names
// (absolute paths — "the plan already names them as normative inputs") must be clean. The
// HALT names the dirty repo AND exactly what was checked (the 0103 halt-transparency lesson).
// The engine's own home repo and PROJECT itself are excluded (foreman's git flow owns those).
// FOREMAN_ALLOW_DIRTY_SIBLINGS=1 proceeds with the state recorded, never silently.
try {
  const { resolveContract } = await import(new URL('./project-engine.mjs', import.meta.url));
  const planText = resolveContract(PROJECT).planText;
  const projReal = fs.realpathSync(PROJECT);
  let engineHome = null;
  try {
    let cur = path.dirname(fileURLToPath(import.meta.url));
    while (cur && path.dirname(cur) !== cur) {
      if (fs.existsSync(path.join(cur, '.git'))) { engineHome = fs.realpathSync(cur); break; }
      cur = path.dirname(cur);
    }
  } catch { /* engine outside a repo — nothing to exclude */ }
  const gitRootOf = (p) => {
    let cur = p;
    while (cur && path.dirname(cur) !== cur) {
      if (fs.existsSync(path.join(cur, '.git'))) return fs.realpathSync(cur);
      cur = path.dirname(cur);
    }
    return null;
  };
  const candidates = new Set();
  const unresolved = [];
  const addCandidate = (m) => {
    const cleaned = m.replace(/[),.;:\]]+$/, '');
    try {
      const st = fs.statSync(cleaned);
      const root = gitRootOf(st.isDirectory() ? cleaned : path.dirname(cleaned));
      if (root) candidates.add(root);
    } catch { unresolved.push(cleaned); }
  };
  // Pass 1 (2026-08-25 review fix — the guard was FAIL-OPEN on spacey paths): quoted or
  // backticked spans may contain spaces ("<path> Foundry\..."); the unquoted pass
  // truncates at the first space, which both MISSES a spacey sibling entirely and can
  // FALSE-match an existing shorter prefix. Quoted spans are scanned first, spaces allowed.
  for (const m of planText.match(/["'`][A-Za-z]:[\\/][^"'`\r\n]+["'`]/g) ?? []) addCandidate(m.slice(1, -1));
  // Pass 2: unquoted prose paths (no spaces — the honest limit of unquoted matching).
  for (const m of planText.match(/[A-Za-z]:[\\/](?:[^\s"'`|<>:*?\r\n]+[\\/])*[^\s"'`|<>:*?\r\n]+/g) ?? []) addCandidate(m);
  if (unresolved.length) {
    emit(`sibling-repos: ${unresolved.length} plan path token(s) did not resolve on disk (first: ${unresolved[0].slice(0, 80)}) — note: unquoted paths cannot carry spaces; QUOTE spacey repo paths in the plan to have them guarded`);
  }
  candidates.delete(projReal);
  if (engineHome) candidates.delete(engineHome);
  const checked = [...candidates];
  if (checked.length) emit(`sibling-repos: checked ${checked.length} plan-named repo(s): ${checked.join(' · ')}`);
  const dirty = [];
  for (const repo of checked) {
    const r = spawnSync('git', ['status', '--porcelain'], { cwd: repo, encoding: 'utf8', timeout: 20000 });
    if (r.error || r.status !== 0) {
      // Review fix: a git failure was silently counted CLEAN — say it, don't bless it.
      emit(`sibling-repos: git status FAILED in ${repo} (${r.error?.message || `exit ${r.status}`}) — repo NOT verified clean`);
      continue;
    }
    if (r.stdout.trim() !== '') dirty.push(`${repo} (${r.stdout.trim().split('\n').length} uncommitted path(s))`);
  }
  if (dirty.length) {
    if (process.env.FOREMAN_ALLOW_DIRTY_SIBLINGS === '1') {
      emit(`!! sibling-repo DIRTY at start (FOREMAN_ALLOW_DIRTY_SIBLINGS=1 — proceeding with eyes open): ${dirty.join('; ')}`);
    } else {
      emit(`[taxonomy:dirty-sibling] HALT before start: plan-named repo(s) not clean — ${dirty.join('; ')}. Commit or stash them, or set FOREMAN_ALLOW_DIRTY_SIBLINGS=1 to proceed with the state recorded. Checked: ${checked.join(' · ')}`);
      process.exit(3);
    }
  }
} catch (e) {
  emit(`sibling-repos: preflight skipped (non-fatal) — ${e?.message || e}`);
}

const budgetConfig = (MAX_WAVES != null || MAX_WALL_MIN != null) ? {
  maxWaves: MAX_WAVES != null ? Number(MAX_WAVES) : null,
  maxWallClockMs: MAX_WALL_MIN != null ? Number(MAX_WALL_MIN) * 60000 : null,
} : null;

// ---- The LOCKED 10-minute Status table (global AGENTS.md rule), engine-emitted ----
// Code-enforced cadence: the engine itself posts the table to the status log every
// ~10 min (armed AT LAUNCH), so a long run can never silently go dark because a
// supervising session forgot. Shell-free: reads only the checkpoint + in-process
// telemetry. The supervising session relays these to chat per the global rule.
const RUN_T0 = Date.now();
function emitStatusTable(tag = '') {
  let cp = null;
  try { cp = JSON.parse(fs.readFileSync(path.join(PROJECT, 'foreman-checkpoint.json'), 'utf8')); } catch { /* pre-checkpoint */ }
  const now = new Date();
  const hhmm = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  const elapsedMin = Math.round((Date.now() - RUN_T0) / 60000);
  const doneWaves = cp ? (cp.last_verdict === 'GO' ? cp.current_wave : cp.current_wave - 1) : 0;
  const total = cp?.total_waves ?? '?';
  const perWave = doneWaves > 0 ? (Date.now() - RUN_T0) / doneWaves : null;
  const remaining = perWave && Number.isInteger(cp?.total_waves) ? Math.max(0, cp.total_waves - doneWaves) : null;
  const eta = perWave && remaining != null ? `~${Math.round((perWave * remaining) / 60000)}m to run end (pace estimate)` : 'estimating (no completed wave yet)';
  const est = calls.reduce((a, c) => a + (c.cost_usd || 0), 0);
  // Plain ASCII separators (0082 / crucible 0075) — unicode boxes garble on some hosts.
  const bar = '---------------------------------';
  const pending = cp?.pending_action || '';
  let waitLine = '';
  try {
    const w = JSON.parse(fs.readFileSync(path.join(PROJECT, '.foreman', 'waiting-on.json'), 'utf8'));
    if (w && w.line) waitLine = w.line;
  } catch { /* none */ }
  const stuckHint = waitLine
    || (/waiting on agent/i.test(pending) ? pending
      : (cp?.intra_wave_step && cp.intra_wave_step !== 'done'
        ? `wave ${cp.current_wave} at ${cp.intra_wave_step}` : ''));
  emit([
    `[${hhmm}] Foreman build · ${path.basename(PROJECT)}${tag ? ` · ${tag}` : ''}`,
    bar,
    `Effort   ${cp ? path.basename(cp.plan_path) : '(resolving contract)'} (${total} waves)`,
    `Doing    wave ${cp?.current_wave ?? '?'} · ${cp?.intra_wave_step ?? 'starting'} (iter ${cp?.iteration ?? 0})` +
      (stuckHint ? ` · ${stuckHint}` : ''),
    `Status   ${doneWaves}/${total} waves · elapsed ${elapsedMin}m`,
    `Tests    last verdict ${cp?.last_verdict ?? '-'}`,
    `Blocker  ${cp?.status === 'halted' ? (cp.pending_action || 'HALTED') : 'none'}`,
    `Procs    agent_calls ${calls.length} · est $${est.toFixed(2)} (subscription equiv)`,
    bar,
    `ETA      ${eta}`,
    `To do    waves ${Math.min(doneWaves + 1, Number(total) || doneWaves + 1)}..${total}`,
  ].join('\n'));
}
emitStatusTable('t=0');
const statusTimer = setInterval(() => emitStatusTable(), 10 * 60 * 1000);
if (typeof statusTimer.unref === 'function') statusTimer.unref();

// P2 2026-07-25: `--attest-wave-proven` — the sanctioned finish for a verifiably-GREEN
// wave the vacuous-guard cannot see (F-AT-1). Re-runs the REAL gate, verifies the
// proven ledger's files live on disk, writes the signed attestation, advances the
// checkpoint, and exits (run --resume afterward to continue the build).
if (argv.includes('--attest-wave-proven')) {
  const cpPath = path.join(PROJECT, 'foreman-checkpoint.json');
  const { attestWaveProven } = await import(new URL('./project-engine.mjs', import.meta.url));
  const { locateDocs, discoverTestCommand } = await import(new URL('./foreman-lib.mjs', import.meta.url));
  try {
    const docs = locateDocs(PROJECT);
    const planAbs = path.isAbsolute(docs.plan) ? docs.plan : path.join(PROJECT, docs.plan);
    const d = discoverTestCommand(fs.readFileSync(planAbs, 'utf8'), PROJECT);
    const testCommand = d && typeof d === 'object' ? d.command : d;
    const r = await attestWaveProven(cpPath, { projectDir: PROJECT, testCommand, log: (s) => emit(s) });
    if (!r.attested) {
      emit(`!! attest refused: ${r.reason}`);
      process.exit(3);
    }
    emit(`attested: wave ${r.wave} GO (${r.attestPath})${r.terminal ? ' — project DONE' : ' — run --resume to continue'}`);
    process.exit(0);
  } catch (e) {
    emit(`!! attest failed: ${e.reason || e.message}`);
    process.exit(3);
  }
}

// Clear a halted checkpoint BEFORE runProject (whose planResume refuses 'halted').
// Only meaningful with --resume; without a checkpoint on disk there is nothing to clear.
if (RESUME && CLEAR_HALT) {
  const cpPath = path.join(PROJECT, 'foreman-checkpoint.json');
  if (fs.existsSync(cpPath)) {
    try {
      const r = clearHaltedCheckpoint(cpPath, { log: (s) => emit(s), force: CLEAR_HALT_FORCE });
      if (r && r.refused) {
        emit(`!! --clear-halt refused: ${r.reason || 'policy'} — ${r.clearedHalt ? 'see checkpoint pending_action' : ''}`);
        process.exit(3);
      }
    } catch (e) {
      emit(`!! --clear-halt failed: ${e.reason || e.message}${e.detail ? ' — ' + e.detail : ''}`);
      process.exit(3);
    }
  }
}

let result, threw = null;
try {
  result = await runProject({
    projectDir: PROJECT,
    // Sleep 0076 package 2: ALWAYS inject the instrumented `agent` so agent_calls /
    // tool lines / phase-timings stay truthful. TRIO_DRIVER_<ROLE> routing still
    // happens inside `agent()` (run-live). Never drop to {log}-only under TRIO_DRIVER
    // (that made status tables report agent_calls:0 while claude was live — 0078).
    driver: await makeForemanDriver({ agent, log: (s) => emit(s) }),
    reviewerCount: REVIEWERS,
    fixIterCap: CAP,
    budgetConfig,
    resume: RESUME,
    git: USE_GIT ? (BRANCH ? { branch: BRANCH } : true) : false,
    log: (s) => emit(s),
  });
} catch (e) {
  threw = { name: e?.name, message: e?.message, reason: e?.reason };
  emit(`!! runProject THREW: ${threw.name}: ${threw.message}${threw.reason ? ' — ' + threw.reason : ''}`);
}

const tot = calls.reduce((a, c) => ({
  out: a.out + (c.output_tokens || 0), cost: a.cost + (c.cost_usd || 0),
  ms: a.ms + (c.duration_ms || 0), denials: a.denials + (c.permission_denials || 0),
}), { out: 0, cost: 0, ms: 0, denials: 0 });

clearInterval(statusTimer);
emitStatusTable('final');
emit(`=== DONE === status=${result?.status ?? (threw ? 'THREW' : 'n/a')} · ` +
  `waves=${(result?.waveResults || []).map((w) => `${w.wave}:${w.status}`).join(',') || 'none'} · ` +
  `stoppedAt=${result?.stoppedAt ?? '-'} · agent_calls=${calls.length} · denials=${tot.denials} · ` +
  `est_cost=$${tot.cost.toFixed(4)} (subscription equiv) · out_tokens=${tot.out}`);

// ---- Run capture for training (Skill Foundry AGENTS.md "Run capture") — best-effort ----
try {
  const skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const runsDir = path.join(skillDir, 'journal', 'runs');
  fs.mkdirSync(runsDir, { recursive: true });
  const startedIso = new Date(RUN_T0).toISOString();
  fs.writeFileSync(path.join(runsDir, `${startedIso.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`),
    JSON.stringify({
      skill: 'foreman',
      tier: process.env.TRIO_TIER || 'standard',
      started: startedIso, ended: new Date().toISOString(),
      input: PROJECT,
      params: { reviewers: REVIEWERS, fixIterCap: CAP, maxWaves: MAX_WAVES, git: USE_GIT, resume: RESUME, clearHalt: CLEAR_HALT },
      output: STATUS_FILE,
      result: `${result?.status ?? (threw ? 'THREW' : 'n/a')}: ` +
        `${(result?.waveResults || []).map((w) => `${w.wave}:${w.status}`).join(',') || 'none'}` +
        (result?.haltReason ? ` — ${String(result.haltReason).slice(0, 200)}` : ''),
      cross_model: ['REVIEW', 'SHARK', 'REVIEWER', 'DEBATE'].some((r) => String(process.env[`TRIO_DRIVER_${r}`] || '').startsWith('gemini')),
      models: null,
      duration_s: Math.round((Date.now() - RUN_T0) / 1000),
      journal_ref: null,
    }, null, 2) + '\n');
} catch { /* capture is best-effort by design */ }
if (result?.haltReason) emit(`HALT/STOP reason: ${result.haltReason}`);
if (result?.recommend) emit(`recommended next: ${result.recommend}`);

console.log('RUN_JSON_START');
console.log(JSON.stringify({
  threw, status: result?.status ?? null, stoppedAt: result?.stoppedAt ?? null,
  totalWaves: result?.totalWaves ?? null, haltReason: result?.haltReason ?? null,
  recommend: result?.recommend ?? null,
  waveResults: (result?.waveResults || []).map((w) => ({ wave: w.wave, title: w.title, status: w.status, green: w.green, tap: w.tap, iterations: w.iterations, halt: w.haltReason || null })),
  agent_calls: calls.length, totals: tot,
}, null, 2));
console.log('RUN_JSON_END');


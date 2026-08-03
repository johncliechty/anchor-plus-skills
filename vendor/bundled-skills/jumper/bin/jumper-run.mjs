#!/usr/bin/env node
// jumper-run.mjs — the thin CLI entry for the Jumper ideation engine (W2–W4, 2026-07).
//
// Before this file existed, SKILL.md gave no invocation path at all, so a real
// /jumper invocation IMPROVISED the tripartite pipeline in prose — bypassing the
// ledger, the cross-family Gate 3, and every honesty guarantee (the exact failure
// mode index.js documents fixing for the composed Gandalf). This CLI is the
// documented way a session runs the REAL engine.
//
//   node bin/jumper-run.mjs --problem "<statement>" [--fan-out N] [--retry-on-kill]
//        [--output out.json] [--input problem.txt]
//
// Defaults are the AGENTS.md invocation discipline: portfolio fanOut=3, drafter =
// Claude, Gate 3 = Gemini via agy (cross-family, fail-closed). HALT semantics are
// BY DESIGN, not bugs: JumperSelfReviewHalt (Gate 3 routed to the drafter family)
// and JumperCrossFamilyDegradeHalt (agy down) exit non-zero with the reason —
// Jumper never silently self-reviews.
//
// B3 W3: SC2 omit-path fanOut := resolved.ideaRounds (one derivation); SC3 pre-run
// refuse killGates < 3 with named JumperKillGatesFloorHalt before Jumper().run;
// killGates passed into engine so kill-filter stage count matches knobs.
// B3 W4: P-CONFLICT (not SC2) — both --depth and --fan-out: allow only when
// fanOut === live ideaRounds; mismatch → named JumperDepthFanOutConflictHalt,
// exit≠0, stderr names both values, Jumper().run never called (no warn-and-inherit,
// no silent prefer of either flag).
// B3 W5: Gate 3 cross-family fail-closed under LITE — depthLockedGate3Seating +
// resolveGate3Seating; same-family → JumperSelfReviewHalt; agy down →
// JumperCrossFamilyDegradeHalt; JUMPER_GATE3_DRIVER may retarget family never skip independence.

import { readFileSync, writeFileSync, mkdirSync, realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import process from 'node:process';

import {
  Jumper,
  resolveGate3Seating,
  JumperSelfReviewHalt,
  JumperCrossFamilyDegradeHalt,
} from '../index.js';
// B3 SC1 sole resolver — depth → ideaRounds/killGates ONLY via this helper
// (no second depth→knob map; no path-local depth→knob table).
import {
  resolveJumperDepthKnobs,
  JUMPER_KILL_GATES_MIN,
} from 'fil<path>';

const USAGE =
  'usage: node bin/jumper-run.mjs --problem "<statement>" [--fan-out N] [--depth LITE|SPIKE|FULL] [--tier Heavy|Standard] [--retry-on-kill]\n' +
  '       [--input <file>] [--output <out.json>]\n' +
  '       (default: portfolio mode fanOut=3; --fan-out 1 = legacy single-candidate;\n' +
  '        --depth locks @foundry/triage knobs via resolveJumperDepthKnobs → ideaRounds as fanOut when --fan-out omitted;\n' +
  '        both --depth and --fan-out: only allowed when --fan-out equals live ideaRounds (P-CONFLICT fail-closed on mismatch);\n' +
  '        recovery: omit --fan-out (SC2 inherit) or set --fan-out equal to ideaRounds;\n' +
  '        --tier does not rebind ideaRounds/killGates (depth selects those knobs);\n' +
  '        killGates ≥ 3 at every depth (pre-run refuse if thinned); Gate 3 cross-family on agy, HALTs honestly if agy is down)';

/**
 * Named pre-run HALT when resolved killGates is below the floor (B3-SC3-PRERUN-REFUSE).
 * Stable class — not stringly-only — so operators/Foreman triage one fail surface.
 * Engine must never start after this HALT (Jumper().run call count === 0).
 */
export class JumperKillGatesFloorHalt extends Error {
  /**
   * @param {unknown} killGates
   * @param {number} [min]
   */
  constructor(killGates, min = JUMPER_KILL_GATES_MIN) {
    super(
      `jumper-run: refusing killGates=${JSON.stringify(killGates)} below floor ${min} ` +
        `(never clamp; never start engine)`,
    );
    this.name = 'JumperKillGatesFloorHalt';
    this.code = 'JUMPER_KILLGATES_FLOOR_HALT';
    this.killGates = killGates;
    this.min = min;
  }
}

/**
 * Named pre-run HALT when both --depth and --fan-out are set and disagree (B3 P-CONFLICT).
 * Not SC2 (SC2 is omit-path only). Fail-closed: no warn-and-inherit, no silent prefer
 * of either flag. Engine must never start after this HALT (Jumper().run call count === 0).
 * Stderr / message always names both numbers so operators can recover (omit fan-out or equalize).
 */
export class JumperDepthFanOutConflictHalt extends Error {
  /**
   * @param {unknown} fanOut  explicit --fan-out value
   * @param {unknown} ideaRounds  live resolved.ideaRounds for the locked depth
   */
  constructor(fanOut, ideaRounds) {
    super(
      `jumper-run: P-CONFLICT — --fan-out=${JSON.stringify(fanOut)} conflicts with ` +
        `depth ideaRounds=${JSON.stringify(ideaRounds)} ` +
        `(fail-closed; do not warn-and-inherit; omit --fan-out or set --fan-out equal to ideaRounds)`,
    );
    this.name = 'JumperDepthFanOutConflictHalt';
    this.code = 'JUMPER_DEPTH_FANOUT_CONFLICT';
    this.fanOut = fanOut;
    this.ideaRounds = ideaRounds;
  }
}

/** @param {string[]} argv */
export function parseArgs(argv) {
  const o = { problem: null, input: null, output: null, fanOut: null, depth: null, tier: null, retryOnKill: false, budget: null, liveRefuter: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--problem') { o.problem = argv[++i]; if (o.problem === undefined) throw new Error('--problem requires text'); }
    else if (a === '--input') { o.input = argv[++i]; if (o.input === undefined) throw new Error('--input requires a file'); }
    else if (a === '--output') { o.output = argv[++i]; if (o.output === undefined) throw new Error('--output requires a file'); }
    else if (a === '--fan-out') { const n = Number(argv[++i]); if (!Number.isInteger(n) || n < 1) throw new Error('--fan-out requires a positive integer'); o.fanOut = n; }
    else if (a === '--depth') { o.depth = argv[++i]; if (o.depth === undefined) throw new Error('--depth requires LITE|SPIKE|FULL'); }
    else if (a === '--tier') { o.tier = argv[++i]; if (o.tier === undefined) throw new Error('--tier requires Heavy|Standard'); }
    else if (a === '--retry-on-kill') { o.retryOnKill = true; }
    // P1 2026-07-25 (journals 0003/0012): the refuter-budget dial — RefuterBudgetHalt
    // (elevations > prereg R=3) killed whole tournaments with no CLI override.
    else if (a === '--budget') { const n = Number(argv[++i]); if (!Number.isInteger(n) || n < 1) throw new Error('--budget requires a positive integer (refuter budget)'); o.budget = n; }
    // Explicit single-family run: floor elevations to SPECULATIVE without paying for
    // (or HALTing on) the cross-family refuter lane. Honest — never a fake grant.
    else if (a === '--no-live-refuter') { o.liveRefuter = false; }
    else if (a === '--help' || a === '-h') { o.help = true; }
    else throw new Error(`unknown argument ${JSON.stringify(a)}`);
  }
  return o;
}

/**
 * Hermetic depth-lock step (B3 SC1). Sole production path when --depth is set.
 * Tier is accepted for operator ergonomics but does NOT rebind ideaRounds/killGates.
 *
 * @param {unknown} depthArg
 * @param {unknown} [_tierArg] intentionally ignored for ideaRounds/killGates
 * @returns {{ ok: true, resolved: Readonly<{depth:string,ideaRounds:number,killGates:number}> }
 *   | { ok: false, exitCode: number, stderr: string, error: Error }}
 */
export function depthLockStep(depthArg, _tierArg) {
  try {
    const resolved = resolveJumperDepthKnobs(depthArg);
    return { ok: true, resolved };
  } catch (err) {
    const message = err?.message ?? String(err);
    return {
      ok: false,
      exitCode: 2,
      stderr: `jumper-run: ${message}\n`,
      error: /** @type {Error} */ (err),
    };
  }
}

/**
 * SC3 pre-run refuse: resolved killGates must be integer ≥ floor before Jumper().run.
 * Never clamps. Throws JumperKillGatesFloorHalt on thin/invalid values.
 *
 * @param {{ killGates?: unknown } | null | undefined} resolved
 * @param {{ min?: number }} [opts]
 * @returns {true}
 */
export function assertPreRunKillGatesFloor(resolved, opts = {}) {
  const min = Number.isInteger(opts.min) ? /** @type {number} */ (opts.min) : JUMPER_KILL_GATES_MIN;
  const kg = resolved?.killGates;
  if (!Number.isInteger(kg) || /** @type {number} */ (kg) < min) {
    throw new JumperKillGatesFloorHalt(kg, min);
  }
  return true;
}

/**
 * B3 P-CONFLICT (W4, not SC2): when both --depth and an explicit --fan-out are set,
 * allow only if fanOut === live resolved.ideaRounds (idempotent dual-flag).
 * Mismatch → JumperDepthFanOutConflictHalt (fail-closed; no warn-and-inherit;
 * no silent prefer of either flag). Omit path (fanOut null/undefined) is SC2 — not this gate.
 *
 * @param {{ ideaRounds?: unknown } | null | undefined} resolved
 * @param {unknown} fanOut  explicit --fan-out, or null/undefined when omitted
 * @returns {true}
 */
export function assertDepthFanOutNoConflict(resolved, fanOut) {
  if (fanOut == null) return true; // SC2 omit path — not a dual-flag conflict
  const ideaRounds = resolved?.ideaRounds;
  if (!Number.isInteger(fanOut) || fanOut !== ideaRounds) {
    throw new JumperDepthFanOutConflictHalt(fanOut, ideaRounds);
  }
  return true;
}

/**
 * Build engine runOptions for a depth-locked CLI path (B3 W3–W4).
 *
 * SC2 omit path: when fanOut is null/undefined, fanOut := resolved.ideaRounds
 * (one derivation from live resolve — never portfolio literals).
 * SC3: pre-run floor refuse; pass killGates into engine for Decision A cardinality.
 * W4 P-CONFLICT: when fanOut is explicit, require fanOut === ideaRounds or hard-fail
 * before engine entry (no warn-and-inherit; no silent prefer of either flag).
 *
 * @param {{
 *   resolved: Readonly<{ depth: string, ideaRounds: number, killGates: number }>,
 *   fanOut?: number | null,
 *   retryOnKill?: boolean,
 * }} p
 * @returns {{ fanOut: number, killGates: number, retryOnKill: boolean }}
 */
export function buildDepthLockedRunOptions({ resolved, fanOut = null, retryOnKill = false }) {
  assertPreRunKillGatesFloor(resolved);
  assertDepthFanOutNoConflict(resolved, fanOut);
  /** @type {{ fanOut: number, killGates: number, retryOnKill: boolean }} */
  const runOptions = {
    retryOnKill: !!retryOnKill,
    // Decision A substrate: engine receives killGates so stage count can match knobs.
    killGates: resolved.killGates,
    // SC2 omit → ideaRounds; dual-flag equal → same value (idempotent); mismatch already threw.
    fanOut: fanOut == null ? resolved.ideaRounds : fanOut,
  };
  return runOptions;
}

/**
 * Hermetic depth-locked CLI → engine-entry step (B3 SC2 / SC3 spy surface).
 *
 * Resolve knobs via depthLockStep (or resolvedOverride for pre-run inject),
 * build runOptions (omit-path fanOut + killGates), optionally invoke an injected
 * Jumper implementation so tests can spy Jumper().run call count and options.
 *
 * @param {{
 *   depth: unknown,
 *   tier?: unknown,
 *   fanOut?: number | null,
 *   problem?: string,
 *   retryOnKill?: boolean,
 *   resolvedOverride?: Partial<{ depth: string, ideaRounds: number, killGates: number }> | null,
 *   createJumper?: (() => { run: (problem: string, opts: object) => Promise<unknown> }) | null,
 * }} p
 */
export async function depthLockedEngineEntry({
  depth,
  tier = null,
  fanOut = null,
  problem = 'hermetic-problem',
  retryOnKill = false,
  resolvedOverride = null,
  createJumper = null,
} = {}) {
  const lock = depthLockStep(depth, tier);
  if (!lock.ok) {
    return {
      ok: false,
      exitCode: lock.exitCode,
      stderr: lock.stderr,
      error: lock.error,
      jumperRunCalls: 0,
      runOptions: null,
      resolved: null,
      result: null,
    };
  }

  const base = lock.resolved;
  const resolved = Object.freeze({
    depth: resolvedOverride?.depth ?? base.depth,
    ideaRounds: resolvedOverride?.ideaRounds ?? base.ideaRounds,
    killGates: resolvedOverride?.killGates ?? base.killGates,
  });

  let runOptions;
  try {
    runOptions = buildDepthLockedRunOptions({ resolved, fanOut, retryOnKill });
  } catch (err) {
    if (
      err instanceof JumperKillGatesFloorHalt ||
      err?.name === 'JumperKillGatesFloorHalt' ||
      err instanceof JumperDepthFanOutConflictHalt ||
      err?.name === 'JumperDepthFanOutConflictHalt'
    ) {
      return {
        ok: false,
        exitCode: 2,
        stderr: `jumper-run: HALT — ${err.name}: ${err.message}\n`,
        error: /** @type {Error} */ (err),
        jumperRunCalls: 0,
        runOptions: null,
        resolved,
        result: null,
      };
    }
    throw err;
  }

  if (typeof createJumper !== 'function') {
    // Options-only path: proves SC2 derivation without starting the real engine.
    return {
      ok: true,
      exitCode: 0,
      resolved,
      runOptions,
      jumperRunCalls: 0,
      result: null,
      error: null,
      stderr: '',
    };
  }

  let jumperRunCalls = 0;
  const jumper = createJumper();
  const originalRun = jumper.run.bind(jumper);
  jumper.run = async (problemArg, opts) => {
    jumperRunCalls += 1;
    return originalRun(problemArg, opts);
  };

  try {
    const result = await jumper.run(problem, runOptions);
    return {
      ok: true,
      exitCode: 0,
      resolved,
      runOptions,
      jumperRunCalls,
      result,
      error: null,
      stderr: '',
    };
  } catch (err) {
    return {
      ok: false,
      exitCode: 1,
      resolved,
      runOptions,
      jumperRunCalls,
      result: null,
      error: /** @type {Error} */ (err),
      stderr: `jumper-run: HALT — ${err?.name ?? 'Error'}: ${err?.message ?? err}\n`,
    };
  }
}

export { resolveJumperDepthKnobs, JUMPER_KILL_GATES_MIN };
export {
  resolveGate3Seating,
  JumperSelfReviewHalt,
  JumperCrossFamilyDegradeHalt,
};

/**
 * Production-entry Gate-3 seating under a depth lock (B3-G3-LITE-SEATING).
 *
 * Composes the same CLI depth-lock path (resolveJumperDepthKnobs → buildDepthLockedRunOptions)
 * with resolveGate3Seating — the seating policy KillFilter uses at engine entry. LITE may lean
 * ideaRounds (in runOptions.fanOut) but never collapses Gate-3 independence.
 *
 * Hermetic: no network; no live agy. assertIndependent defaults true (fail-closed).
 *
 * @param {{
 *   depth?: unknown,
 *   tier?: unknown,
 *   gate3Driver?: string | null,
 *   drafterDriver?: string | null,
 *   gate3Agent?: Function | null,
 *   env?: NodeJS.ProcessEnv,
 *   assertIndependent?: boolean,
 * }} [p]
 */
export function depthLockedGate3Seating({
  depth = 'LITE',
  tier = null,
  gate3Driver = null,
  drafterDriver = null,
  gate3Agent = null,
  env = process.env,
  assertIndependent = true,
} = {}) {
  const lock = depthLockStep(depth, tier);
  if (!lock.ok) {
    return {
      ok: false,
      exitCode: lock.exitCode,
      stderr: lock.stderr,
      error: lock.error,
      resolved: null,
      runOptions: null,
      seating: null,
    };
  }
  let runOptions;
  try {
    runOptions = buildDepthLockedRunOptions({
      resolved: lock.resolved,
      fanOut: null, // SC2 omit-path — ideaRounds lean only; Gate-3 seating orthogonal
    });
  } catch (err) {
    return {
      ok: false,
      exitCode: 2,
      stderr: `jumper-run: HALT — ${err?.name ?? 'Error'}: ${err?.message ?? err}\n`,
      error: /** @type {Error} */ (err),
      resolved: lock.resolved,
      runOptions: null,
      seating: null,
    };
  }

  try {
    const seating = resolveGate3Seating({
      drafterDriver,
      gate3Driver,
      gate3Agent,
      env,
      assertIndependent,
    });
    return {
      ok: true,
      exitCode: 0,
      resolved: lock.resolved,
      runOptions,
      seating,
      error: null,
      stderr: '',
    };
  } catch (err) {
    // Named Gate-3 HALTs (self-review) surface as production-entry fail-closed.
    return {
      ok: false,
      exitCode: 1,
      resolved: lock.resolved,
      runOptions,
      seating: null,
      error: /** @type {Error} */ (err),
      stderr: `jumper-run: HALT — ${err?.name ?? 'Error'}: ${err?.message ?? err}\n`,
    };
  }
}

/** Run-capture for training (canonical: Skill Foundry AGENTS.md → "Run capture"). Best-effort. */
export function writeRunRecord(record, { skillDir = resolve(dirname(fileURLToPath(import.meta.url)), '..') } = {}) {
  try {
    const dir = join(skillDir, 'journal', 'runs');
    mkdirSync(dir, { recursive: true });
    const started = record.started || new Date().toISOString();
    const file = join(dir, `${started.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`);
    writeFileSync(file, JSON.stringify({ skill: 'jumper', ...record }, null, 2) + '\n', 'utf8');
    return file;
  } catch { return null; }
}

async function main() {
  let opts;
  try { opts = parseArgs(process.argv.slice(2)); }
  catch (err) { process.stderr.write(`jumper-run: ${err.message}\n${USAGE}\n`); process.exitCode = 2; return; }
  if (opts.help) { process.stdout.write(`${USAGE}\n`); return; }

  let problem = opts.problem;
  if (!problem && opts.input) {
    try { problem = readFileSync(opts.input, 'utf8'); }
    catch (err) { process.stderr.write(`jumper-run: could not read --input: ${err.message}\n`); process.exitCode = 2; return; }
  }
  if (!problem || !String(problem).trim()) {
    process.stderr.write(`jumper-run: a problem statement is required (--problem or --input)\n${USAGE}\n`);
    process.exitCode = 2;
    return;
  }

  const started = new Date().toISOString();
  const t0 = Date.now();
  /** @type {{ retryOnKill: boolean, fanOut?: number, killGates?: number, refuterBudget?: number, liveRefuter?: boolean, log?: Function }} */
  const runOptions = { retryOnKill: opts.retryOnKill };
  // P1 2026-07-25: heartbeat sink (stderr keeps stdout's JSON result clean) + the
  // new dials. Stage lines let a cadence agent tell healthy-long-run from hang
  // (journal 0014's false-DONE came from exactly this blindness).
  runOptions.log = (m) => process.stderr.write(`${m}\n`);
  if (Number.isInteger(opts.budget) && opts.budget > 0) runOptions.refuterBudget = opts.budget;
  if (opts.liveRefuter === false) runOptions.liveRefuter = false;

  // P1 2026-07-25 (journal 0006): PRE-FLIGHT Gate-3 seating check. JumperSelfReviewHalt
  // used to fire only inside the kill filter — AFTER ~8 minutes of paid seats on a
  // single-family host. Resolve the seating now (sub-second, env-only) and refuse
  // BEFORE any model call. Skipped when the live refuter is explicitly off.
  if (opts.liveRefuter !== false) {
    try {
      resolveGate3Seating({ env: process.env, assertIndependent: true });
    } catch (err) {
      process.stderr.write(`jumper-run: HALT (pre-flight) — ${err?.name ?? 'Error'}: ${err?.message ?? err}\n`);
      process.stderr.write('jumper-run: fix model prefs (coding vs review family) or pass --no-live-refuter for an honest single-family run.\n');
      process.exitCode = 1;
      return;
    }
  }

  // B3 SC1: --depth → sole resolveJumperDepthKnobs (no second local map).
  // --tier does not rebind ideaRounds/killGates (B3-SC1-TIER-INERT).
  // B3 SC2/SC3: omit-path fanOut inherit + pre-run killGates floor + killGates pass-through.
  // B3 W4 P-CONFLICT: dual-flag equal allowed; mismatch named halt before engine.
  if (opts.depth) {
    const step = depthLockStep(opts.depth, opts.tier);
    if (!step.ok) {
      process.stderr.write(step.stderr);
      process.exitCode = step.exitCode;
      return;
    }
    const resolved = step.resolved;
    try {
      // Shared derivation with hermetic depthLockedEngineEntry / buildDepthLockedRunOptions.
      // Omit path: fanOut from ideaRounds when --fan-out omitted.
      // Dual-flag: equal to ideaRounds allowed; mismatch → JumperDepthFanOutConflictHalt.
      const depthOpts = buildDepthLockedRunOptions({
        resolved,
        fanOut: opts.fanOut,
        retryOnKill: opts.retryOnKill,
      });
      runOptions.fanOut = depthOpts.fanOut;
      runOptions.killGates = depthOpts.killGates;
      runOptions.retryOnKill = depthOpts.retryOnKill;
    } catch (err) {
      if (
        err instanceof JumperKillGatesFloorHalt ||
        err?.name === 'JumperKillGatesFloorHalt' ||
        err instanceof JumperDepthFanOutConflictHalt ||
        err?.name === 'JumperDepthFanOutConflictHalt'
      ) {
        // Named class HALT before Jumper().run — exit≠0, engine never starts.
        process.stderr.write(`jumper-run: HALT — ${err.name}: ${err.message}\n`);
        process.exitCode = 2;
        return;
      }
      throw err;
    }
    process.stderr.write(
      `jumper-run: triage depth=${resolved.depth} ideaRounds=${resolved.ideaRounds} killGates=${resolved.killGates}\n`,
    );
  } else if (opts.fanOut != null) {
    // Unlocked path: explicit --fan-out only (legacy default stays inside Jumper when omitted).
    runOptions.fanOut = opts.fanOut;
  }

  let result;
  try {
    result = await new Jumper().run(problem, runOptions);
  } catch (err) {
    // Named HALTs are honest outcomes (self-review route / agy down) — report and exit non-zero.
    process.stderr.write(`jumper-run: HALT — ${err?.name ?? 'Error'}: ${err?.message ?? err}\n`);
    writeRunRecord({
      tier: 'halted', started, ended: new Date().toISOString(),
      input: opts.input || '(--problem argv)', params: runOptions, output: null,
      result: `HALT: ${err?.name ?? 'Error'}`, cross_model: false, models: null,
      duration_s: Math.round((Date.now() - t0) / 1000), journal_ref: null,
    });
    process.exitCode = 1;
    return;
  }

  const serialized = `${JSON.stringify(result, null, 2)}\n`;
  if (opts.output) writeFileSync(opts.output, serialized, 'utf8');
  else process.stdout.write(serialized);

  writeRunRecord({
    tier: result.fanOut ? `portfolio-${result.fanOut}` : 'legacy-single',
    started, ended: new Date().toISOString(),
    input: opts.input || '(--problem argv)',
    params: runOptions,
    output: opts.output || '(stdout)',
    result: result.passed
      ? `passed: ${result.survivors ? `${result.survivors.length} survivor(s)` : 'concept'} + GEP`
      : `killed: gate ${result.failedAtGate ?? '?'}${result.retried ? ' (after retry)' : ''}`,
    cross_model: true, // Gate 3 is cross-family by construction or the run HALTs
    models: null,
    duration_s: Math.round((Date.now() - t0) / 1000),
    journal_ref: null,
  });
}

// P0 2026-07-25 (journals 0001/0008/0011): realpath + case-fold BOTH sides — a junction path
// in argv never string-equals the resolved module URL, so the CLI silently exited 0 producing
// nothing. Same fix as gandalf-run.mjs.
function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    const canon = (p) => {
      const abs = resolve(p);
      let real = abs;
      try { real = realpathSync(abs); } catch { /* keep abs */ }
      return process.platform === 'win32' ? real.toLowerCase() : real;
    };
    return canon(fileURLToPath(import.meta.url)) === canon(entry);
  } catch { return false; }
}
if (invokedDirectly()) {
  main().catch((err) => {
    process.stderr.write(`jumper-run: fatal — ${err?.message ?? err}\n`);
    process.exitCode = 1;
  });
}

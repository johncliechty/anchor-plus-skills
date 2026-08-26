#!/usr/bin/env node
// Gandalf runtime host — the thin runtime ENTRY (Tier-1 CLI).
//
// THE REAL HOST (journal/0001 + LESSONS.md): read a model's RAW draft → run the deterministic seam
// pass (`runtime/seam-pass.applySeamPass`) → validate it with the shipped `assertIncrement1Conformant`
// → emit the canary-conformant, honestly-graded advisor output. This is the chain the v1 build was
// missing: model-content → seam-stamping → conformant output.
//
// CONTRACT (see runtime/RAW-DRAFT-CONTRACT.md): the model emits ONLY the raw draft and does NOT
// self-assign tiers/stamps — the host applies them via the seams.
//
// USAGE:
//   node runtime/gandalf-run.mjs --input <file.json> [--output <file.json>]
//   cat draft.json | node runtime/gandalf-run.mjs            (stdin → stdout)
//   node runtime/gandalf-run.mjs < draft.json --output out.json
//
// HONESTY DISCIPLINE: on malformed input OR a failed conformance assertion, the host exits NON-ZERO
// with an honest stderr reason and writes NOTHING (no partial / no forged output). It NEVER fabricates
// a finding to make the gate pass — that would defeat the entire anti-illusion spine.

import { readFileSync, writeFileSync, readdirSync, statSync, mkdirSync, realpathSync } from 'node:fs';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { resolve, relative, join, dirname } from 'node:path';

import { applySeamPass, SeamPassInputError } from './seam-pass.mjs';
import { assertIncrement1Conformant } from '../test/harness.mjs';
import { getGitignorePatterns, isIgnored } from './context-sizer.mjs';
import { runMapReduce } from './map-reduce.mjs';
import {
  resolveGandalfBand,
  isGandalfBandLocked,
  assertGandalfSeatsFloor,
} from './triage-band.mjs';
import { createCommissionLedger } from '../seam/commission-ledger.mjs';
import { runLiveRefutation, buildLiveRefuterAgent, DEFAULT_REFUTER_ROUTES, DRAFTER_FAMILY, REFUTER_FAMILY } from './live-refuter.mjs';
import { makeGeminiCliSeam, resolveGeminiModel } from 'fil<path>';
import { loadModelFamilies, familyToDriverName, runAgent } from 'fil<path>';

const USAGE =
  'usage: node runtime/gandalf-run.mjs --live [--budget N] [--input <file>] [--output <file>] [--project <dir>]\n' +
  '       node runtime/gandalf-run.mjs [--input <file>] [--output <file>] [--cross-model] [--project <dir>]\n' +
  '       node runtime/gandalf-run.mjs --analyze --project <dir> --objective "<question>" [--depth LITE|FULL|SPIKE-FIRST] [--output <file>]\n' +
  '       (--live: THE DEFAULT REAL PATH — dispatch cross-family agy refuters on firing elevations, mint\n' +
  '        claim-bound commissions, grade against the shared ledger; GROUNDED becomes reachable. Requires agy.)\n' +
  '       (grade mode: Tier-1 deterministic stamp only — every elevation floors at SPECULATIVE; use for\n' +
  '        offline/agy-down runs, honestly stamped cross_model:false)\n' +
  '       (--analyze mode: Scaled-Gandalf context-size router → single frontier pass for a SMALL target,\n' +
  '        or shard→scout→map→reduce for a LARGE one; --depth locks @foundry/triage band knobs)\n' +
  '       (grade/live: with no --input, the raw draft is read from stdin; no --output → stdout)';

/** Parse argv into { input, output, cross_model, project }. `--cross-model` is an INTENT flag only
 *  (W2b): it records that a cross-family attempt was REQUESTED; it does NOT force the output
 *  `cross_model` stamp or lift any tier ceiling — that stamp is DERIVED from genuine ledger-bound
 *  refutations inside applySeamPass. Throws on an unknown / malformed flag. */
/** Parse CLI argv (exported for E1 hermetics — production `main` is the only other caller). */
export function parseArgs(argv) {
  const opts = {
    input: null,
    output: null,
    cross_model: false,
    project: null,
    analyze: false,
    objective: null,
    live: false,
    budget: null,
    depth: null,
    tier: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--input' || a === '-i') {
      opts.input = argv[++i];
      if (opts.input === undefined) throw new Error('--input requires a file path');
    } else if (a === '--output' || a === '-o') {
      opts.output = argv[++i];
      if (opts.output === undefined) throw new Error('--output requires a file path');
    } else if (a === '--project' || a === '-p') {
      opts.project = argv[++i];
      if (opts.project === undefined) throw new Error('--project requires a directory path');
    } else if (a === '--objective' || a === '-q') {
      opts.objective = argv[++i];
      if (opts.objective === undefined) throw new Error('--objective requires a text argument');
    } else if (a === '--analyze') {
      opts.analyze = true; // Scaled-Gandalf map-reduce mode (route by CONTEXT SIZE over a codebase)
    } else if (a === '--live') {
      // C1 (2026-07-11): the LIVE cross-family path IS now CLI-reachable — the
      // always/stakes-gated cross-model rule stops requiring ad-hoc import glue.
      opts.live = true;
    } else if (a === '--budget') {
      const n = Number(argv[++i]);
      if (!Number.isInteger(n) || n < 1) throw new Error('--budget requires a positive integer');
      opts.budget = n;
    } else if (a === '--depth') {
      opts.depth = argv[++i];
      if (opts.depth === undefined) throw new Error('--depth requires LITE|FULL|SPIKE-FIRST');
    } else if (a === '--tier') {
      opts.tier = argv[++i];
      if (opts.tier === undefined) throw new Error('--tier requires Heavy|Standard');
    } else if (a === '--cross-model') {
      opts.cross_model = true; // INTENT only — the output stamp is DERIVED, never set by this flag
    } else if (a === '--help' || a === '-h') {
      opts.help = true;
    } else {
      throw new Error(`unknown argument ${JSON.stringify(a)}`);
    }
  }
  return opts;
}

/**
 * L2 lock authority — pure resolve of maxShards/fusionPasses for the runMapReduce call object.
 *
 * When locked (any depth|tier lock input): band knobs are authoritative. Caller-supplied
 * maxShards/fusionPasses are ignored (unlock-only override). Values equal knobsForSkill via
 * resolveGandalfBand.
 *
 * When unlocked: caller caps pass through unchanged (null = pre-band uncapped baseline).
 *
 * @param {object} [o]
 * @param {?string} [o.depth]
 * @param {?string} [o.tier]
 * @param {object}  [o.env]
 * @param {?number} [o.maxShards]     unlock-only override
 * @param {?number} [o.fusionPasses]  unlock-only override
 * @param {string}  [o.userObjective]
 * @returns {{ locked: boolean, maxShards: number|null, fusionPasses: number|null, knobs: object|null, source: string|null }}
 */
export function resolveConsumeKnobs({
  depth = null,
  tier = null,
  env = process.env,
  maxShards = null,
  fusionPasses = null,
  userObjective = '',
} = {}) {
  if (!isGandalfBandLocked({ depth, tier, env })) {
    return {
      locked: false,
      maxShards: maxShards == null ? null : maxShards,
      fusionPasses: fusionPasses == null ? null : fusionPasses,
      knobs: null,
      source: null,
    };
  }
  const band = resolveGandalfBand({
    depth,
    tier,
    intake: { intent: userObjective, scope: depth === 'LITE' ? 'small' : 'large' },
    allowDefault: true,
    env,
  });
  // L4/L5 safety floor: refuse locked band-thin that zeros or omits seats.
  assertGandalfSeatsFloor(band.knobs);
  // Lock wins: never let caller maxShards/fusionPasses invert locked knobs (L2).
  const shards = band.knobs?.shards ?? null;
  const fusions = band.knobs?.fusionPasses ?? null;
  return {
    locked: true,
    maxShards: shards,
    fusionPasses: fusions,
    knobs: band.knobs ?? null,
    source: band.source ?? null,
  };
}

/**
 * Run-capture for training (canonical standard: Skill Foundry AGENTS.md → "Run capture").
 * One small machine-readable record per run under journal/runs/ — the Foundry's training
 * feed. NEVER writes into the human NNNN namespace. Best-effort: a capture failure must
 * not fail the run it records.
 */
export function writeRunRecord(record, { skillDir = resolve(dirname(fileURLToPath(import.meta.url)), '..') } = {}) {
  try {
    // Provenance discipline: capture is for REAL runs only. The test suite spawns
    // this CLI, and those children inherit NODE_TEST_CONTEXT — skip capture there
    // so mock runs never pollute the training feed (same rule as tidy-idy).
    if (process.env.NODE_TEST_CONTEXT) return null;
    const dir = join(skillDir, 'journal', 'runs');
    mkdirSync(dir, { recursive: true });
    const started = record.started || new Date().toISOString();
    const id = `${started.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}`;
    const file = join(dir, `${id}.json`);
    writeFileSync(file, JSON.stringify({ skill: 'gandalf', ...record }, null, 2) + '\n', 'utf8');
    return file;
  } catch {
    return null; // capture is best-effort by design
  }
}

/** Read all of stdin synchronously as a UTF-8 string (fd 0). */
function readStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch (err) {
    throw new Error(`could not read stdin: ${err.message}`);
  }
}

/** Grade a draft and return the conformant output, or null if it trips the canary (a genuinely
 *  malformed DRAFT still throws SeamPassInputError — that is an input problem, not a salvageable one). */
function tryGrade(draft, cross_model, resolveCommission) {
  try {
    const o = applySeamPass(draft, { cross_model, resolveCommission });
    assertIncrement1Conformant(o);
    return o;
  } catch (err) {
    if (err instanceof SeamPassInputError) throw err;
    return null; // a conformance trip on THIS shape — the caller degrades further
  }
}

/** Salvage the LARGEST conformant subset of a real (non-garbage) draft whose full form tripped the
 *  canary — a real cross-model/fused draft occasionally carries ONE item that trips a cap / rung-gated
 *  field / provenance rule. We never emit anything the canary rejects (every returned output is
 *  re-asserted); we simply refuse to lose the WHOLE read over one item. The output is honestly stamped
 *  `degraded:true` with a note; the per-shard reasoning narrative is preserved regardless of which
 *  structured items are dropped. Order of sacrifice (P0 2026-07-25): a SINGLE offending item first
 *  (preserving every other finding/elevation/nitpick), then a tail-shrink of one forward leg, then
 *  whole legs in increasing-value order, then finding subsets, then the minimal (empty-arrays) form. */
function degradeToConformant(rawDraft, { cross_model, resolveCommission, reason }) {
  const firstLine = String(reason || 'conformance failure').split('\n')[0];
  const note =
    `\n\n[gandalf-host] Grading degraded: the full draft tripped a conformance canary (${firstLine}); ` +
    `the read was salvaged to the largest conformant subset (the reasoning narrative above is intact).`;
  const base = { ...rawDraft, reasoning: String(rawDraft.reasoning || '') + note, degraded: true };
  const findings = Array.isArray(base.findings) ? base.findings.slice() : [];
  const nitpicks = Array.isArray(base.nitpicks) ? base.nitpicks.slice() : [];
  const elevations = Array.isArray(base.elevations) ? base.elevations.slice() : [];

  // 1) P0 2026-07-25 (journals 0276/0277): the common case is ONE offending item —
  //    drop just IT and preserve every other finding, elevation, and nitpick. The old
  //    ladder sacrificed the ENTIRE elevations+nitpicks forward layer as its FIRST step,
  //    which almost always conformed — so any single canary trip silently cost the whole
  //    recommendation layer (deterministic, byte-identical, observed live twice on
  //    --live runs; the expensive path returned strictly less advice than the cheap one).
  let out;
  for (const [legName, leg] of [['nitpicks', nitpicks], ['elevations', elevations], ['findings', findings]]) {
    for (let i = 0; i < leg.length; i++) {
      out = tryGrade({ ...base, [legName]: leg.filter((_, j) => j !== i) }, cross_model, resolveCommission);
      if (out) return out;
    }
  }
  // 1b) multiple offenders in ONE forward leg (e.g. an over-cap overrun by >1): shrink
  //     that leg from the tail while keeping the other legs whole.
  for (const [legName, leg] of [['nitpicks', nitpicks], ['elevations', elevations]]) {
    for (let keep = leg.length - 2; keep >= 0; keep--) {
      out = tryGrade({ ...base, [legName]: leg.slice(0, keep) }, cross_model, resolveCommission);
      if (out) return out;
    }
  }
  // 2) cross-leg offenders: drop whole legs in INCREASING-value order — nitpicks, then
  //    elevations, then both. (This was the old step 1; it is now a late resort.)
  out = tryGrade({ ...base, nitpicks: [] }, cross_model, resolveCommission);
  if (out) return out;
  out = tryGrade({ ...base, elevations: [] }, cross_model, resolveCommission);
  if (out) return out;
  out = tryGrade({ ...base, nitpicks: [], elevations: [] }, cross_model, resolveCommission);
  if (out) return out;
  // 3) the offending FINDING cases (with the forward legs already sacrificed):
  //    single offender, then a shrinking prefix (multiple/interacting offenders).
  for (let i = 0; i < findings.length; i++) {
    out = tryGrade({ ...base, findings: findings.filter((_, j) => j !== i), nitpicks: [], elevations: [] }, cross_model, resolveCommission);
    if (out) return out;
  }
  for (let keep = findings.length - 1; keep >= 0; keep--) {
    out = tryGrade({ ...base, findings: findings.slice(0, keep), nitpicks: [], elevations: [] }, cross_model, resolveCommission);
    if (out) return out;
  }
  // 4) minimal conformant output (reasoning+verdict only) — empty item arrays always conform
  out = tryGrade({ ...base, findings: [], nitpicks: [], elevations: [] }, cross_model, resolveCommission);
  if (out) return out;
  // Unreachable in practice (the empty shape is conformant); stay honest if a seam ever breaks it.
  throw new Error(`gandalf-host: could not salvage a conformant output (${firstLine})`);
}

/** The host pipeline. Returns the conformant output object. Throws SeamPassInputError (malformed
 *  input); a real draft that trips the canary is DEGRADED to its largest conformant subset (never a
 *  whole-run crash over one item) — the returned output always passes the canary. */
export function runHost(rawText, { cross_model = false, resolveCommission } = {}) {
  let rawDraft;
  try {
    rawDraft = JSON.parse(rawText);
  } catch (err) {
    throw new SeamPassInputError(`the input is not valid JSON: ${err.message}`);
  }
  // W2b: `cross_model` here is the caller INTENT flag only; the output stamp is DERIVED inside
  // applySeamPass from genuine ledger-bound refutations. `resolveCommission` defaults (inside
  // applySeamPass) to the real commission-ledger resolver so the gate is ACTIVE in a real run; a
  // test may inject a stub. We thread `undefined` through untouched so that default applies.
  const output = applySeamPass(rawDraft, { cross_model, resolveCommission });
  // The host's guarantee: never emit anything the canary set would reject. The seam pass is
  // conformant by construction for well-shaped items, but a real cross-model/fused draft can still
  // carry ONE item that trips the canary — degrade to the largest conformant subset (honestly
  // stamped) instead of losing the entire read.
  try {
    assertIncrement1Conformant(output);
    return output;
  } catch (err) {
    if (err instanceof SeamPassInputError) throw err;
    return degradeToConformant(rawDraft, { cross_model, resolveCommission, reason: err.message });
  }
}

/** Finalize a graded output: return it if conformant, else degrade to the largest conformant subset.
 *  Shared by the Tier-1 (`runHost`) and W3 live (`runHostLive`) paths so both honour the "never emit
 *  anything the canary rejects" guarantee identically. */
function finalizeConformant(rawDraft, output, { cross_model, resolveCommission }) {
  try {
    assertIncrement1Conformant(output);
    return output;
  } catch (err) {
    if (err instanceof SeamPassInputError) throw err;
    return degradeToConformant(rawDraft, { cross_model, resolveCommission, reason: err.message });
  }
}

/**
 * runHostLive — the W3 LIVE cross-family host pipeline (the sequenced follow-on Tier-1 could not run).
 *
 * THE ONE SHARED PER-RUN LEDGER (invariant 1): a single `createCommissionLedger()` is the sole ledger —
 * `runLiveRefutation` MINTS into `ledger.mintCommission` and `applySeamPass` RESOLVES via the SAME
 * `ledger.resolveCommission`. The minter and the gate can NEVER be on different ledger instances (that
 * would make every genuine cross-family mint a false negative). The mint binds each commission to the
 * exact elevation object the gate then reads (invariant 2), so a surviving, genuinely cross-family
 * refutation reaches GROUNDED with the DERIVED cross_model:true; a failed/absent refutation stays
 * SPECULATIVE (honest floor). Async because it dispatches real refuters.
 *
 * The live role-routed agent (refuter → Gemini, drafter → Claude) is built via buildLiveRefuterAgent
 * (routing guard enforced) unless an `agent` is injected (tests inject a stub). Likewise the ledger may
 * be injected for a reproducible fixture; otherwise a fresh per-run ledger is minted here.
 *
 * @param {string} rawText
 * @param {object} [o]
 * @param {boolean}[o.cross_model]           the caller INTENT flag (recorded only; the stamp is DERIVED)
 * @param {Function}[o.agent]                injected role-routed agent (tests); omit for the live agent
 * @param {object} [o.ledger]                injected shared ledger (tests); omit for a fresh per-run ledger
 * @param {object} [o.routes]                the route table (routing guard + live-agent build)
 * @param {string} [o.drafterFamily]
 * @param {string} [o.refuterFamily]
 * @param {number} [o.budget]
 * @param {Function}[o.log]
 * @returns {Promise<{output:object, dispatch:object[], ledger:object}>}
 */
export async function runHostLive(rawText, {
  cross_model = false,
  agent,
  ledger: injectedLedger,
  routes,
  drafterFamily,
  refuterFamily = REFUTER_FAMILY,
  budget,
  log = () => {},
} = {}) {
  let rawDraft;
  try {
    rawDraft = JSON.parse(rawText);
  } catch (err) {
    throw new SeamPassInputError(`the input is not valid JSON: ${err.message}`);
  }
  // INVARIANT 1: ONE shared per-run ledger for BOTH the minter and the gate.
  const ledger = injectedLedger || createCommissionLedger();
  const resolveCommission = ledger.resolveCommission;
  // Live agent: omit routes/drafter → coding/review family prefs; tests pass explicit pins.
  const theAgent = agent || (await buildLiveRefuterAgent({ routes, drafterFamily, env: process.env }));

  // Dispatch the live refuters and mint claim-bound commissions into the shared ledger.
  const { draft, dispatch } = await runLiveRefutation(rawDraft, {
    agent: theAgent, ledger, routes, drafterFamily, refuterFamily, budget, log,
  });

  // Grade the refuted draft against the SAME ledger's resolver — cross_model / GROUNDED are DERIVED here.
  const output = applySeamPass(draft, { cross_model, resolveCommission });
  const finalized = finalizeConformant(draft, output, { cross_model, resolveCommission });
  return { output: finalized, dispatch, ledger };
}

// ===========================================================================================
// W4 (2026-07-05) — SCALED-GANDALF wiring: actually invoke scout + map-reduce from the CLI.
//
// Before W4 this entry imported ONLY runRouter (context-sizing) and NEVER invoked the big-repo
// map-reduce engine — the scout/map/reduce pipeline was built but dead. `runScaledAnalysis` wires it
// in and routes by CONTEXT SIZE:
//   • a SMALL target → runMapReduce/decideTier returns 'direct' → ONE frontier pass, NO scout, NO
//     shard, NO map-reduce ceremony.
//   • a LARGE target → shard → scout → map → reduce.
// The size decision itself lives in ONE place (runMapReduce → decideTier); this wrapper adds the
// CLEVER TWO-MODEL split on top of it.
// ===========================================================================================

/**
 * Scaled-Gandalf seat models from UNIVERSAL SEATING LAW (Anchor prefs).
 * - bulk MAP / scout → REVIEW_FAMILY (standard tier when that family is Gemini)
 * - REDUCE / synthesis → CODING_FAMILY (heavy tier when that family is Gemini)
 * Gemini models stay agy LABELS via resolveGeminiModel; other families leave model null
 * (CLI session / driver default). Never hardcode Claude/Gemini/Grok product IDs here.
 * @param {object} [env=process.env]
 * @returns {{ mapModel:?string, reduceModel:?string, mapDriver:string, reduceDriver:string, families:object }}
 */
export function resolveScaledModels(env = process.env) {
  const families = loadModelFamilies(env);
  const mapDriver = familyToDriverName(families.review) || 'gemini-cli';
  const reduceDriver = familyToDriverName(families.coding) || 'claude';
  let mapModel = null;
  let reduceModel = null;
  if (mapDriver === 'gemini-cli' || mapDriver.startsWith('gemini')) {
    mapModel = resolveGeminiModel({ env: { ...env, TRIO_TIER: 'standard' } });
  }
  if (reduceDriver === 'gemini-cli' || reduceDriver.startsWith('gemini')) {
    reduceModel = resolveGeminiModel({ env: { ...env, TRIO_TIER: 'heavy' } });
  }
  return { mapModel, reduceModel, mapDriver, reduceDriver, families };
}

/**
 * runScaledAnalysis — the Scaled-Gandalf map-reduce pipeline, wired to route by CONTEXT SIZE (via
 * runMapReduce/decideTier) with the clever map=STANDARD / reduce=HEAVY split applied on top.
 *
 * A SMALL target is answered by a single frontier (HEAVY) pass (decideTier='direct') — no scout, no
 * shard. A LARGE target shards → scouts (STANDARD) → maps (STANDARD) → reduces/synthesizes (HEAVY).
 *
 * `makeAgent(model, role)` is INJECTABLE so a deterministic test drives the whole pipeline with stub
 * agents (no live agy); omit it for the live agy seam. Returns the raw map-reduce advisory prose (a
 * PRE-STAGE — the canonical branded output is still the graded gandalf-advisor-1 envelope).
 *
 * @param {object} o
 * @param {?string}  [o.projectDir]
 * @param {Array|Object} o.payload            the codebase payload (path strings / {path,content} / dict)
 * @param {string}   o.userObjective
 * @param {object}   [o.env=process.env]
 * @param {Function} [o.log]
 * @param {?Function}[o.makeAgent]            (model, role) => agentFn — injected for tests
 * @param {?number}  [o.highContextLimit]
 * @param {number}   [o.concurrencyLimit=3]
 * @returns {Promise<string>}
 */
export async function runScaledAnalysis({
  projectDir = null,
  payload,
  userObjective,
  env = process.env,
  log = () => {},
  makeAgent = null,
  highContextLimit = null,
  concurrencyLimit = 3,
  depth = null,
  tier = null,
  maxShards = null,
  fusionPasses = null,
  /** Optional inject for hermetic E1–E4 call-object capture (production omits → live runMapReduce). */
  mapReduceRunner = null,
} = {}) {
  // B2 L2: locked path forwards authoritative band knobs; unlocked keeps caller caps / null.
  // Caller maxShards/fusionPasses cannot invert a lock (unlock-only override).
  const consume = resolveConsumeKnobs({
    depth,
    tier,
    env,
    maxShards,
    fusionPasses,
    userObjective,
  });
  const shards = consume.maxShards;
  const fusions = consume.fusionPasses;
  if (consume.locked) {
    log(`gandalf band: depth=${consume.knobs?.depth} shards=${shards} fusionPasses=${fusions} source=${consume.source}`);
  }

  const { mapModel, reduceModel, mapDriver, reduceDriver } = resolveScaledModels(env);
  const target = projectDir || process.cwd();
  const factory = makeAgent || ((model, role) => {
    const driver = role === 'reduce' ? reduceDriver : mapDriver;
    // Gemini seats keep the dedicated agy seam; all other families use the prefs-routed runAgent.
    if (driver === 'gemini-cli' || String(driver).startsWith('gemini')) {
      return makeGeminiCliSeam({ model, role, env, target, log }).agent;
    }
    return (prompt, opts = {}) => runAgent({
      prompt,
      schema: opts.schema,
      label: opts.label || `gandalf:${role}`,
      role: opts.role || role,
      model: model || opts.model || null,
      driver,
      env: { ...env, CRUCIBLE_AGENT_LIVE: env.CRUCIBLE_AGENT_LIVE || '1' },
      target,
      log,
    });
  });
  const mapAgent = factory(mapModel, 'map');       // REVIEW_FAMILY bulk reads
  const reduceAgent = factory(reduceModel, 'reduce'); // CODING_FAMILY synthesis
  const invokeMapReduce = typeof mapReduceRunner === 'function' ? mapReduceRunner : runMapReduce;
  return invokeMapReduce({
    projectDir,
    payload,
    userObjective,
    env,
    log,
    agent: mapAgent,
    reduceAgent,
    highContextLimit,
    concurrencyLimit,
    maxShards: shards,
    fusionPasses: fusions,
  });
}

/**
 * Collect a codebase payload (an array of repo-relative path strings) by walking `projectDir` and
 * respecting the same gitignore/default ignores the context-sizer uses. Content is read lazily by the
 * map-reduce runtime (it resolves string paths against projectDir), so this stays cheap.
 * @param {string} projectDir
 * @returns {string[]} repo-relative POSIX-ish path strings
 */
export function collectProjectPayload(projectDir) {
  const patterns = getGitignorePatterns(projectDir);
  const out = [];
  const walk = (dir) => {
    let entries;
    try { entries = readdirSync(dir); } catch { return; }
    for (const name of entries) {
      const full = join(dir, name);
      const rel = relative(projectDir, full);
      let st;
      try { st = statSync(full); } catch { continue; }
      if (st.isDirectory()) {
        if (isIgnored(rel, patterns, true)) continue;
        walk(full);
      } else if (st.isFile()) {
        if (isIgnored(rel, patterns, false)) continue;
        out.push(rel.replace(/\\/g, '/'));
      }
    }
  };
  walk(projectDir);
  return out;
}

/**
 * C2 (2026-07-11): grade a scaled-analysis report through the SAME honesty spine as
 * every other run. The map-reduce used to ship RAW PROSE straight to the user — the
 * one thing Gandalf exists to prevent (map-reduce.mjs's own comment promised the
 * seam-pass feedback that nothing performed). If the reduce seat emitted the
 * RAW-DRAFT-CONTRACT JSON, grade it directly; otherwise wrap the prose in a minimal
 * raw draft (reasoning = the report; zero self-assigned tiers) and grade THAT — the
 * output is the stamped, canary-conformant envelope either way, honestly marked
 * degraded (no live refuters ran on the scaled path).
 */
export function gradeScaledReport(report) {
  const text = String(report);
  let rawDraft = null;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) rawDraft = parsed;
  } catch { /* prose report — wrap it */ }
  if (!rawDraft) {
    rawDraft = {
      reasoning: text,
      verdict: 'scaled analyze — see reasoning (map-reduce advisory prose, host-graded)',
      findings: [],
      nitpicks: [],
      elevations: [],
    };
  }
  const output = runHost(JSON.stringify(rawDraft), { cross_model: false });
  // Carry the map-reduce degradation stamp forward — never silently dropped.
  output.degraded = true;
  const stamp = report && typeof report === 'object' && 'stamp' in report ? report.stamp : null;
  if (stamp) output.scaled_stamp = String(stamp);
  return output;
}

/** The `--analyze` CLI path: build the codebase payload, run the Scaled-Gandalf pipeline (context-size
 *  routed, clever two-model), grade the result through the seam pass (C2), and write the STAMPED
 *  envelope to --output or stdout. Throws on failure so the caller emits an honest stderr reason and
 *  a non-zero exit. */
async function runAnalyzeMode(opts) {
  const projectDir = resolve(opts.project || process.cwd());
  const objective = opts.objective || 'Provide a deep-think advisory review of this codebase.';
  const payload = collectProjectPayload(projectDir);
  process.stderr.write(`gandalf-run: --analyze over ${payload.length} files in ${projectDir}\n`);
  const report = await runScaledAnalysis({
    projectDir,
    payload,
    userObjective: objective,
    env: process.env,
    log: (m) => process.stderr.write(`${m}\n`),
    depth: opts.depth || null,
    tier: opts.tier || null,
  });
  const graded = gradeScaledReport(report);
  const serialized = `${JSON.stringify(graded, null, 2)}\n`;
  if (opts.output) writeFileSync(opts.output, serialized, 'utf8');
  else process.stdout.write(serialized);
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`gandalf-run: ${err.message}\n${USAGE}\n`);
    process.exitCode = 2;
    return;
  }
  if (opts.help) {
    process.stdout.write(`${USAGE}\n`);
    return;
  }

  // W4: the SCALED-GANDALF analyze mode — actually invoke scout + map-reduce over a codebase, routed
  // by context size (single frontier pass for a small target; shard→scout→map→reduce for a large one).
  const started = new Date().toISOString();
  const t0 = Date.now();

  if (opts.analyze) {
    try {
      await runAnalyzeMode(opts);
      writeRunRecord({
        tier: 'scaled-analyze', started, ended: new Date().toISOString(),
        input: `--project ${opts.project || process.cwd()} --objective ${JSON.stringify(opts.objective || '(default)')}`,
        params: { mode: 'analyze' },
        output: opts.output || '(stdout)',
        result: 'analyze completed (see degraded stamp in the report)',
        cross_model: false, models: null, duration_s: Math.round((Date.now() - t0) / 1000), journal_ref: null,
      });
    } catch (err) {
      process.stderr.write(`gandalf-run: --analyze failed — no output written.\n${err.message}\n`);
      process.exitCode = 1;
    }
    return;
  }

  // Read the ARTIFACT under analysis. (2026-07-11: the old grade-mode "router" pass is
  // DELETED — it token-sized the draft JSON, logged model choices, and mutated
  // GEMINI_MODEL/TRIO_MODEL env in a mode that makes zero model calls: pure ceremony
  // with a misleading log and an env side effect. --analyze keeps the real router.)
  let rawText;
  try {
    rawText = opts.input ? readFileSync(opts.input, 'utf8') : readStdin();
  } catch (err) {
    process.stderr.write(`gandalf-run: could not read input: ${err.message}\n`);
    process.exitCode = 2;
    return;
  }

  let output, dispatch = null;
  try {
    if (opts.live) {
      // C1: the LIVE cross-family path — refuters via agy, commissions minted into the
      // shared ledger, cross_model/GROUNDED derived by the gate. HALTs honestly if agy
      // is down (the seam throws; we write NOTHING and exit non-zero).
      const live = await runHostLive(rawText, {
        cross_model: true,
        budget: opts.budget ?? undefined,
        log: (m) => process.stderr.write(`${m}\n`),
      });
      output = live.output;
      dispatch = live.dispatch;
      const minted = dispatch.filter((d) => d.minted).length;
      process.stderr.write(`gandalf-run: --live dispatched ${dispatch.length} refuter(s), ${minted} commission(s) minted\n`);
    } else {
      output = runHost(rawText, { cross_model: opts.cross_model });
    }
  } catch (err) {
    // HONEST failure: malformed draft or a live-path error. Write NOTHING. Label revised
    // 2026-08-25 (journal 0300, rule 9): the old blanket "(agy down / non-attested)" branded
    // EVERY live error a substrate failure — twice misdiagnosing a budget stop as "agy down".
    // Read err.message; it names the actual cause. (Budget excess no longer halts at all —
    // it pre-flights and floors; see live-refuter.mjs.)
    const kind = err instanceof SeamPassInputError ? 'malformed raw draft'
      : opts.live ? `live refutation failed — ${err?.name || 'error'} (read the message below; NOT necessarily agy)` : 'conformance failure';
    process.stderr.write(`gandalf-run: ${kind} — no output written.\n${err.message}\n`);
    process.exitCode = 1;
    return;
  }

  const serialized = `${JSON.stringify(output, null, 2)}\n`;
  if (opts.output) {
    try {
      writeFileSync(opts.output, serialized, 'utf8');
    } catch (err) {
      process.stderr.write(`gandalf-run: could not write output: ${err.message}\n`);
      process.exitCode = 2;
      return;
    }
  } else {
    process.stdout.write(serialized);
  }

  writeRunRecord({
    tier: opts.live ? 'live-cross-family' : 'tier1-deterministic',
    started, ended: new Date().toISOString(),
    input: opts.input || '(stdin)',
    // P0 2026-07-25 (journal 0276): --live hardcodes cross_model:true into runHostLive, so the
    // intent stamp must reflect it — recording opts.cross_model alone stamped intent:false on
    // every --live run, corrupting the training feed for the highest-value runs.
    params: { live: opts.live, budget: opts.budget, cross_model_intent: !!(opts.live || opts.cross_model) },
    output: opts.output || '(stdout)',
    result: `graded: ${Array.isArray(output?.elevations) ? output.elevations.length : 0} elevation(s)` +
      (dispatch ? `; refuters ${dispatch.length}, minted ${dispatch.filter((d) => d.minted).length}` : ''),
    cross_model: output?.cross_model ?? false,
    models: null,
    duration_s: Math.round((Date.now() - t0) / 1000),
    journal_ref: null,
  });
}

// Run as a CLI when invoked directly (node runtime/gandalf-run.mjs). Importable for tests otherwise.
// P0 2026-07-25 (journals 0275/0281/0283 + 0001-heavy-smoke): realpath + case-fold BOTH sides —
// a junction/symlink path in argv (e.g. ~/.claude/skills junctions) never string-equals the
// resolved module URL, so the CLI silently exited 0 writing NOTHING (the worst failure mode
// for an honesty-first host). realpathSync collapses junctions; toLowerCase absorbs Windows
// drive-letter/case variants.
function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    const canon = (p) => {
      const abs = resolve(p);
      let real = abs;
      try { real = realpathSync(abs); } catch { /* keep abs (file may be a virtual path) */ }
      return process.platform === 'win32' ? real.toLowerCase() : real;
    };
    return canon(fileURLToPath(import.meta.url)) === canon(entry);
  } catch {
    return false;
  }
}
if (invokedDirectly()) {
  main().catch((err) => {
    process.stderr.write(`gandalf-run: fatal — ${err?.message ?? err}\n`);
    process.exitCode = 1;
  });
}

export { main };

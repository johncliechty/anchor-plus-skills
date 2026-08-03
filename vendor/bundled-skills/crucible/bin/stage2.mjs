// stage2.mjs — Crucible's Stage 2: the Implementation Plan + handoff (Wave 8).
//
// Stage 2 is the LITERAL North-Star deliverable: it turns an APPROVED Master Plan
// (the Stage-1 output) into a Foreman-ready DOC-TRIO and hands it off (MASTER-PLAN
// §4 Stage 2). The flow, in order:
//
//   1. WAVE DECOMPOSITION (PM heuristics): decompose the approved Master Plan's
//      phases + near-term specifics into ordered, dependency-respecting waves —
//      each shipping real testable source, each with a one-line **done-when**, and
//      (D16 hybrid acceptance criteria) non-trivial waves carrying 1–3 Given/When/
//      Then scenarios. Wave NUMBERS are assigned by the renderer (1..N contiguous),
//      never trusted from the model — so Foreman's `parseWaves` contiguity/ascending
//      guard can never trip on a mis-numbered emission.
//   2. RENDER the doc-trio: the implementation plan (with `## Wave N` headings, a
//      `test-command:` line, and the hybrid acceptance criteria) + a description doc
//      + an execution-log scaffold + a generated `foreman.config.json` that NAMES the
//      three docs explicitly (so Foreman's `locateDocs` resolves via config, never the
//      ambiguous *.md heuristic).
//   3. The SHARK-TANK LOOP (Waves 2–4, reached through Stage-1's generic
//      `runMasterPlanLoop`): sharkfood → fix → … until dry, Synthesizer direction
//      between rounds, a fresh-eyes cold pass, the Judge deciding, the convergence
//      gate. This is the QUALITY gate (§8).
//   4. The user-approval HALT gate — the canonical HALT_GATES['stage2->done']
//      ('implementation-plan-approval'), so this gate and the engine's terminal
//      state-machine boundary name the SAME gate. The user is the convergence authority.
//   5. EMIT the doc-trio + config to the output dir, then the HANDOFF guarded by the
//      WELL-FORMEDNESS gate (Wave 4): Crucible SPAWNS Foreman's `locate-plan.mjs
//      --json` over the emitted dir and refuses to hand off unless it exits 0. This is
//      the machine gate (§8) — distinct from the quality gate above.
//
// The TWO gates stay separate (§8): well-formedness is guaranteed BY CONSTRUCTION —
// the emitted plan is rendered deterministically from the structured decomposition
// (contiguous `## Wave N`, a `test-command:`, a done-when per wave), so it passes the
// machine gate regardless of how the free-text Shark-Tank revision loop reshaped the
// human-readable draft it vetted. Quality is proven by the loop converging.
//
// REUSE, NOT REINVENT: the adversarial loop is Stage-1's `runMasterPlanLoop` (itself
// the Wave 2–4 machinery via the Wave-1 seam); the machine gate is Wave-4's
// `runWellFormednessGate` (spawning Foreman's real resolver); the approval gate reuses
// crucible-lib's `haltForHuman` + the canonical `HALT_GATES`. Stage 2 ORCHESTRATES.

import fs from 'node:fs';
import path from 'node:path';

import { HaltError, haltForHuman, HALT_GATES, draftToText, assertPlanText } from './crucible-lib.mjs';
import { runMasterPlanLoop } from './stage1.mjs';
import { resolveBandProfile, bandProfileStamp } from './band-profile.mjs';
import { runWellFormednessGate } from './gates.mjs';
import { enforceHardeningGate } from './apply-hardening-to-plan.mjs';
import {
  installProcessLifetimeGuards,
  withPhaseProgress,
} from '../../drivers/process-lifetime.mjs';

// NS-01 Wave 3: handoff emit shape from shared triage — resolve without host paths.
import { importFoundryTriage } from '../../drivers/foundry-triage-resolve.mjs';
const {
  buildHandoffTriageEmit,
  createLockRecord,
  legacyBandToDepth,
  MODEL_TIERS,
  DEPTH_BANDS,
} = await importFoundryTriage('crucible-wire.mjs');

// ---------------------------------------------------------------------------
// Stage-2 durability (2026-07-24 wave 3 / journal 0075)
// Never die silent: progress stamp + HALT.json + human-lockable force-emit.
// ---------------------------------------------------------------------------

/**
 * Write HALT.json so operators can tell crash vs long agent call vs human gate.
 * Best-effort; never throws.
 *
 * @param {string} dir  artifacts / .crucible dir
 * @param {object} o
 * @returns {object|null} payload written, or null
 */
export function writeStage2HaltJson(dir, {
  reason = 'stage2 halted',
  lastStep = null,
  humanLockable = false,
  artifacts = {},
  pendingAction = 'stage2-process-death',
  extra = {},
} = {}) {
  if (!dir) return null;
  try {
    fs.mkdirSync(dir, { recursive: true });
    const payload = {
      skill: 'crucible',
      stage: 2,
      reason: String(reason).slice(0, 2000),
      last_step: lastStep,
      human_lockable: !!humanLockable,
      pending_action: pendingAction,
      artifacts: artifacts && typeof artifacts === 'object' ? artifacts : {},
      pid: process.pid,
      ts: new Date().toISOString(),
      ...extra,
    };
    const haltPath = path.join(dir, 'HALT.json');
    const tmp = `${haltPath}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(payload, null, 2) + '\n', 'utf8');
    fs.renameSync(tmp, haltPath);
    return payload;
  } catch {
    return null;
  }
}

/**
 * Stamp stage2-progress.json (and optional wave-decomposition.json).
 * Best-effort; never throws.
 */
export function stampStage2Progress(dir, { phase, status = 'running', extra = {} } = {}) {
  if (!dir || !phase) return;
  try {
    fs.mkdirSync(dir, { recursive: true });
    const payload = {
      stage: 2,
      phase,
      status,
      ts: new Date().toISOString(),
      pid: process.pid,
      ...extra,
    };
    const p = path.join(dir, 'stage2-progress.json');
    const tmp = `${p}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(payload, null, 2) + '\n', 'utf8');
    fs.renameSync(tmp, p);
  } catch { /* never crash the plan on progress */ }
}

/**
 * First-class force-emit when Stage-2 dies mid-challenge but wave decomp exists.
 * Writes doc-trio under `<outputDir>/_human-lockable-draft` and stamps HALT.json
 * with human_lockable:true. Does NOT hand off to Foreman (approval still required).
 *
 * @returns {{ draftDir: string, docTrio: object, halt: object|null }|null}
 */
export function forceEmitStage2HumanLockable({
  waves,
  outputDir,
  title = 'Crucible-planned project',
  northStar = '',
  criteria = [],
  summary = '',
  testCommand = DEFAULT_TEST_COMMAND,
  depth = null,
  tier = null,
  triageLock = null,
  handoffTriage = null,
  artifactsDir = null,
  reason = 'Stage-2 force-emit after stall/crash — human-lockable draft (not a handoff)',
  log = () => {},
} = {}) {
  if (!outputDir || !Array.isArray(waves) || !waves.length) return null;
  const draftDir = path.join(path.resolve(outputDir), '_human-lockable-draft');
  const plan = renderImplementationPlan({ title, northStar, criteria, waves, testCommand });
  const description = renderDescriptionDoc({ title, northStar, criteria, summary });
  const executionLog = renderExecutionLog({ title, waveCount: waves.length });
  const docTrio = writeDocTrio({
    outputDir: draftDir, plan, description, executionLog,
    depth, tier, triageLock, handoffTriage, log,
  });
  const stateDir = artifactsDir || path.join(path.resolve(outputDir), '.crucible');
  const halt = writeStage2HaltJson(stateDir, {
    reason,
    lastStep: 'force-emit-human-lockable',
    humanLockable: true,
    pendingAction: 'stage2-force-emit-review',
    artifacts: {
      draft_dir: docTrio.dir,
      plan: docTrio.files?.plan || null,
      config: docTrio.configPath || null,
    },
  });
  log(`stage2 force-emit: human-lockable draft at ${docTrio.dir}`);
  return { draftDir: docTrio.dir, docTrio, halt };
}

// ---------------------------------------------------------------------------
// (1) Wave decomposition — PM heuristics over the approved Master Plan.
// ---------------------------------------------------------------------------

/**
 * The decomposition output. Each wave carries the hybrid acceptance criteria (D16):
 * a mandatory one-line `doneWhen`, and — for a non-trivial wave — 1–3 Given/When/Then
 * scenarios. `dependsOn` records the wave ordering rationale (a prior wave name, or
 * null for the first).
 */
export const WAVE_DECOMP_SCHEMA = {
  type: 'object',
  required: ['waves'],
  properties: {
    waves: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'doneWhen'],
        properties: {
          title: { type: 'string' },
          intent: { type: 'string' },
          deliverables: { type: 'array', items: { type: 'string' } },
          dependsOn: { type: ['string', 'null'] },
          doneWhen: { type: 'string' },
          nonTrivial: { type: 'boolean' },
          gwt: {
            type: 'array',
            items: {
              type: 'object',
              required: ['given', 'when', 'then'],
              properties: {
                given: { type: 'string' },
                when: { type: 'string' },
                then: { type: 'string' },
              },
            },
          },
        },
      },
    },
  },
};

function decomposePrompt({ northStar, criteria, masterPlan }) {
  // 0075 input budget: truncate huge embeds so Stage-2 does not paste 40k×2.
  // Prefer the head of each doc (criteria + architecture) over a full dump.
  const budget = (s, max = 12000) => {
    const t = String(s || '');
    if (t.length <= max) return t;
    return t.slice(0, max) +
      `\n\n[… truncated for Stage-2 input budget; full length ${t.length} chars — ` +
      `use the on-disk North-Star / Master Plan files for any detail past this cut …]\n`;
  };
  return [
    `You are the Crucible STAGE-2 WAVE-DECOMPOSITION step. Decompose the APPROVED Master Plan`,
    `below into an ORDERED, dependency-respecting set of build WAVES for Foreman, applying PM`,
    `heuristics: each wave must be independently buildable on top of the prior ones, must ship`,
    `REAL testable source (not docs-only), and must carry acceptance criteria. Do NOT drift`,
    `from the North Star — every wave must serve a North-Star criterion (the inclusion test).`,
    ``,
    `=== THE NORTH STAR (verbatim, may be budget-truncated) ===`,
    budget(northStar, 8000),
    `=== END NORTH STAR ===`,
    criteria.length ? `\n=== SUCCESS CRITERIA ===\n${criteria.map((c, i) => `(${i + 1}) ${c}`).join('\n')}\n=== END CRITERIA ===` : '',
    ``,
    `=== APPROVED MASTER PLAN (decompose THIS; may be budget-truncated) ===`,
    budget(masterPlan, 14000),
    `=== END MASTER PLAN ===`,
    ``,
    `Acceptance-criteria convention (D16): EVERY wave gets a one-line done-when; a non-trivial`,
    `wave additionally gets 1–3 Given/When/Then scenarios. Order the waves so each wave's`,
    `dependsOn names the wave it builds on (null for the first).`,
    `Emit: waves [{title, intent, deliverables, dependsOn, doneWhen, nonTrivial, gwt:[{given,when,then}]}].`,
  ].join('\n');
}

/**
 * Normalize the raw decomposition into clean, ordered waves. Assigns the wave NUMBER
 * by position (1..N) so the emission is always contiguous/ascending for Foreman's
 * `parseWaves` guard — the model's own numbering is never trusted. HALTs (never
 * silently emits a malformed plan) if there are no waves, or any wave lacks a
 * one-line done-when (the D16 floor: every wave must have a done-when).
 */
export function normalizeWaves(rawWaves = []) {
  const waves = (Array.isArray(rawWaves) ? rawWaves : [])
    .filter((w) => w && (w.title || w.intent))
    .map((w, i) => {
      const doneWhen = String(w.doneWhen ?? '').trim();
      if (!doneWhen) {
        throw haltForHuman(
          `Stage-2 wave ${i + 1} ("${w.title || 'untitled'}") has no done-when — every wave needs one (D16)`,
          'rerun-decomposition',
        );
      }
      const gwt = (Array.isArray(w.gwt) ? w.gwt : [])
        .filter((s) => s && (s.given || s.when || s.then))
        .map((s) => ({ given: String(s.given ?? ''), when: String(s.when ?? ''), then: String(s.then ?? '') }));
      const nonTrivial = w.nonTrivial === true || gwt.length > 0;
      return {
        n: i + 1,
        title: String(w.title ?? `Wave ${i + 1}`).trim(),
        intent: String(w.intent ?? '').trim(),
        deliverables: (Array.isArray(w.deliverables) ? w.deliverables : []).map((d) => String(d)),
        dependsOn: w.dependsOn != null && String(w.dependsOn).trim() ? String(w.dependsOn).trim() : null,
        doneWhen,
        nonTrivial,
        gwt,
      };
    });

  if (!waves.length) {
    throw haltForHuman('Stage-2 decomposition produced no waves', 'rerun-decomposition');
  }
  return waves;
}

/**
 * Decompose the approved Master Plan into waves (PM heuristics), schema-forced and
 * North-Star-bound. Returns the normalized, numbered waves.
 *
 * @param {object} o
 * @param {Function} o.agent                  the Wave-1 agent seam
 * @param {string}   o.northStar
 * @param {string[]}[o.criteria=[]]
 * @param {string}   o.masterPlan             the APPROVED Master-Plan text (Stage-1 output)
 * @param {Function}[o.log=()=>{}]
 * @returns {Promise<object[]>}               normalized waves [{n,title,intent,deliverables,dependsOn,doneWhen,nonTrivial,gwt}]
 */
export async function decomposeIntoWaves({ agent, northStar, criteria = [], masterPlan, log = () => {} } = {}) {
  requireAgent(agent, 'decomposeIntoWaves');
  if (!northStar) throw new HaltError('decomposeIntoWaves requires a locked North Star', 'lock the North Star in Stage 0 first');
  if (!masterPlan) throw new HaltError('decomposeIntoWaves requires the approved Master Plan', 'approve the Master Plan in Stage 1 first');

  const out = await agent(decomposePrompt({ northStar, criteria, masterPlan }), { label: 'stage2:decompose', schema: WAVE_DECOMP_SCHEMA });
  const rawWaves = out && typeof out === 'object' && Array.isArray(out.waves)
    ? out.waves
    // Raw-text reply — a live driver that could not escape the decomposition into
    // valid JSON (journal 0002): recover the waves from markdown-style headers.
    : parseWavesFromMarkdown(typeof out === 'string' ? out : '');

  const waves = normalizeWaves(rawWaves);
  const nonTrivial = waves.filter((w) => w.nonTrivial).length;
  log(`stage2 decomposition: ${waves.length} wave(s), ${nonTrivial} non-trivial (with G/W/T)`);
  return waves;
}

/**
 * Best-effort recovery of the wave decomposition from a RAW-TEXT reply (the
 * journal-0002 fallback): `## Wave: title` blocks with `Intent:` / `Deliverables:` /
 * `Depends On:` / `Done When:` / `Given/When/Then` lines. Returns raw waves for
 * normalizeWaves (which still HALTs when nothing usable came back).
 */
export function parseWavesFromMarkdown(rawText) {
  const rawWaves = [];
  let currentWave = null;
  let currentGwt = null;
  // Handle literal \n and missing newlines before keywords.
  let normalizedText = String(rawText).replace(/\\n/g, '\n');
  normalizedText = normalizedText.replace(/\s+(?:\*\*)?(Intent|Deliverables|Depends On|Done[\s\-]*When|Given|When|Then)(?:\*\*)?[:\-]/gi, '\n$1:');

  const lines = normalizedText.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0);
  for (const line of lines) {
    let m;
    if ((m = line.match(/^(?:##\s*)?(?:\*\*)?Wave(?:\s+\d+)?(?:\*\*)?[:\-\s]+(.*)/i))) {
      if (currentGwt) currentWave.gwt.push(currentGwt);
      currentGwt = null;
      currentWave = { title: m[1].trim(), intent: '', deliverables: [], dependsOn: null, doneWhen: '', nonTrivial: true, gwt: [] };
      rawWaves.push(currentWave);
    } else if (currentWave) {
      if ((m = line.match(/^(?:\*\*)?Intent(?:\*\*)?[:\-\s]+(.*)/i))) currentWave.intent = m[1].trim();
      else if ((m = line.match(/^(?:\*\*)?Deliverables(?:\*\*)?[:\-\s]+(.*)/i))) currentWave.deliverables = m[1].split(';').map((s) => s.trim());
      else if ((m = line.match(/^(?:\*\*)?Depends On(?:\*\*)?[:\-\s]+(.*)/i))) currentWave.dependsOn = m[1].trim().toLowerCase() === 'null' ? null : m[1].trim();
      else if ((m = line.match(/^(?:\*\*)?Done[\s\-]*When(?:\*\*)?[:\-\s]+(.*)/i))) currentWave.doneWhen = m[1].trim();
      else if ((m = line.match(/^(?:\*\*)?Given(?:\*\*)?[:\-\s]+(.*)/i))) {
        if (currentGwt) currentWave.gwt.push(currentGwt);
        currentGwt = { given: m[1].trim(), when: '', then: '' };
      }
      else if ((m = line.match(/^(?:\*\*)?When(?:\*\*)?[:\-\s]+(.*)/i)) && currentGwt) currentGwt.when = m[1].trim();
      else if ((m = line.match(/^(?:\*\*)?Then(?:\*\*)?[:\-\s]+(.*)/i)) && currentGwt) currentGwt.then = m[1].trim();
    }
  }
  if (currentGwt && currentWave) currentWave.gwt.push(currentGwt);
  return rawWaves;
}

// ---------------------------------------------------------------------------
// (2) Render the Foreman-ready doc-trio + the explicit config.
// ---------------------------------------------------------------------------

/** The doc-trio filenames + the config that names them (so locateDocs uses config). */
export const DEFAULT_DOC_FILENAMES = {
  description: 'DESCRIPTION.md',
  plan: 'IMPLEMENTATION-PLAN.md',
  execution_log: 'EXECUTION-LOG.md',
};

// Windows-safe expanding gate (0076 package 4 / F053): bare `node --test test/` is
// hard-broken on Win Node. Prefer a project helper that lists test/*.test.mjs.
// Projects without the helper should still declare explicit files; this default
// documents the preferred emit shape for Stage-2 handoffs. writeDocTrio also emits
// the helper script so the handoff is runnable without a manual scaffold.
export const DEFAULT_TEST_COMMAND = 'node scripts/run-all-tests.mjs';

/** Canonical body of scripts/run-all-tests.mjs emitted with every doc-trio. */
export const RUN_ALL_TESTS_SCRIPT = `/**
 * Windows-safe expanding gate: list test/*.test.mjs explicitly.
 * Bare \`node --test test/\` is hard-broken on Windows Node (Foreman isBadNodeTestDirectoryCommand).
 * Usage (plan test-command): node scripts/run-all-tests.mjs
 * Sleep 0076 package 4 / Crucible Stage-2 default emit.
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const testDir = path.join(root, 'test');
let files = [];
try {
  files = fs
    .readdirSync(testDir)
    .filter((f) => f.endsWith('.test.mjs') || f.endsWith('.test.js'))
    .sort()
    .map((f) => path.join('test', f));
} catch {
  console.error('run-all-tests: test/ directory missing or unreadable');
  process.exit(2);
}

if (!files.length) {
  console.error('run-all-tests: no test/*.test.mjs files found');
  process.exit(2);
}

const r = spawnSync(process.execPath, ['--test', ...files], {
  cwd: root,
  stdio: 'inherit',
  windowsHide: true,
  shell: false,
});
process.exit(typeof r.status === 'number' ? r.status : 1);
`;

/**
 * Render the implementation plan markdown. The structure is what makes the
 * well-formedness gate pass BY CONSTRUCTION: a single early `test-command:` line
 * (Foreman's `discoverTestCommand` takes the first match), `## Wave N` headings in
 * contiguous ascending order (`parseWaves`), and per-wave acceptance criteria.
 */
export function renderImplementationPlan({ title = 'Crucible-planned project', northStar, criteria = [], waves = [], testCommand = DEFAULT_TEST_COMMAND } = {}) {
  const lines = [
    `# ${title} — Implementation Plan (Foreman-ready)`,
    '',
    // The ground-truth gate command, declared first so it wins discovery.
    `test-command: ${testCommand}`,
    '',
    `**North Star:** ${northStar}`,
    '',
  ];
  if (criteria.length) {
    lines.push('## Success criteria', ...criteria.map((c) => `- ${c}`), '');
  }
  lines.push('> Every wave ships real source its new tests import and exercise; acceptance criteria follow the D16 hybrid convention (a one-line done-when + Given/When/Then for non-trivial waves).', '');

  for (const w of waves) {
    lines.push(`## Wave ${w.n} — ${w.title}`);
    lines.push('');
    if (w.intent) lines.push(`**Intent:** ${w.intent}`, '');
    if (w.deliverables.length) lines.push(`**Deliverables:** ${w.deliverables.join('; ')}`, '');
    lines.push(`**Depends on:** ${w.dependsOn || '—'}`, '');
    lines.push(`**done-when:** ${w.doneWhen}`, '');
    for (const s of w.gwt) {
      lines.push(`- **Given** ${s.given}, **when** ${s.when}, **then** ${s.then}`);
    }
    if (w.gwt.length) lines.push('');
  }
  return lines.join('\n').replace(/\n+$/, '\n');
}

/** Render the description / design doc (the "what & why"). */
export function renderDescriptionDoc({ title = 'Crucible-planned project', northStar, criteria = [], summary = '' } = {}) {
  const lines = [
    `# ${title} — Description`,
    '',
    `**North Star:** ${northStar}`,
    '',
  ];
  if (summary) lines.push(summary, '');
  if (criteria.length) lines.push('## Success criteria', ...criteria.map((c) => `- ${c}`), '');
  lines.push('## Provenance', '', 'Generated by Crucible Stage 2 from an approved Master Plan, vetted by the Shark-Tank loop and the well-formedness gate before handoff.', '');
  return lines.join('\n');
}

/** Render the execution-log scaffold (Foreman appends per-wave outcomes here). */
export function renderExecutionLog({ title = 'Crucible-planned project', waveCount = 0 } = {}) {
  return [
    `# ${title} — Execution Log`,
    '',
    `Foreman records per-wave build outcomes below. ${waveCount} wave(s) planned.`,
    '',
    '## Waves',
    '',
    '_(no waves built yet — Foreman appends a GREEN/HALT entry per wave)_',
    '',
  ].join('\n');
}

/**
 * Write the doc-trio + `foreman.config.json` into `outputDir`. The config names the
 * three docs EXPLICITLY so Foreman's `locateDocs` resolves via config (never the
 * ambiguous *.md heuristic, which would HALT if a project has more than one plan-ish
 * filename). Returns the written paths.
 *
 * Wave 3 (NS-01): `triage_track` is the process-depth pin (FULL|LITE|SPIKE-FIRST)
 * for the Foreman consumer; `triage: { tier, depth, … }` carries both axes.
 * Prefer a Stage-0 `handoffTriage` / `triageLock`; fall back to confirmed depth/tier.
 *
 * @returns {{dir:string, files:{description:string,plan:string,execution_log:string},
 *            configPath:string, fileNames:object, handoffTriage:?object}}
 */
export function writeDocTrio({
  outputDir,
  plan,
  description,
  executionLog,
  fileNames = DEFAULT_DOC_FILENAMES,
  depth = null,
  tier = null,
  triageLock = null,
  handoffTriage = null,
  log = () => {},
  /** When true (default), assert+inject journal-0080 property gates before write. */
  enforceHardening = true,
  addsSurface = true,
} = {}) {
  if (!outputDir) throw new HaltError('writeDocTrio requires an outputDir', 'pass the handoff output directory');
  const dir = path.resolve(outputDir);
  fs.mkdirSync(dir, { recursive: true });

  const files = {
    description: path.join(dir, fileNames.description),
    plan: path.join(dir, fileNames.plan),
    execution_log: path.join(dir, fileNames.execution_log),
  };
  // P1 2026-07-25 (0063 P0): the handoff PLAN goes through the canonical serializer +
  // corrupt/short refusal — the engine never writes `[object Object]` or a stub plan.
  // Journal 0080 / 2026-07-27 dogfood: a plan that ASSERTS a property must EMIT a
  // mechanical gate — inject checklist + fail-closed before the plan hits disk.
  let planText = assertPlanText(plan, { label: 'implementation plan' });
  let hardeningResult = null;
  if (enforceHardening) {
    const applied = enforceHardeningGate({ plan: planText, addsSurface, log });
    planText = applied.plan;
    hardeningResult = applied.gate;
    try {
      fs.writeFileSync(
        path.join(dir, 'hardening-gate-result.json'),
        JSON.stringify({ ...applied.gate, claims: applied.claims, injected: applied.injected, ts: new Date().toISOString() }, null, 2) + '\n',
        'utf8',
      );
    } catch { /* best-effort */ }
    if (!applied.gate.pass) {
      throw haltForHuman(
        `Stage-2 emit BLOCKED by hardening-gate (journal 0080): ${applied.gate.detail} — ` +
          `the plan asserts properties without mechanical gates in acceptance/obligation text. ` +
          `Fix the plan (or propertyGates map) then re-emit.`,
        'hardening-gate-failed',
      );
    }
  }
  fs.writeFileSync(files.description, draftToText(description));
  fs.writeFileSync(files.plan, planText);
  fs.writeFileSync(files.execution_log, draftToText(executionLog));

  // Sleep 0076 package 4: always emit Windows-safe expanding gate helper so
  // DEFAULT_TEST_COMMAND (`node scripts/run-all-tests.mjs`) is runnable at handoff
  // without a manual scaffold. Idempotent overwrite with the canonical body.
  const scriptsDir = path.join(dir, 'scripts');
  fs.mkdirSync(scriptsDir, { recursive: true });
  const runAllPath = path.join(scriptsDir, 'run-all-tests.mjs');
  fs.writeFileSync(runAllPath, RUN_ALL_TESTS_SCRIPT, 'utf8');

  // Handoff triage emit (Wave 3) — Foreman reads triage_track as a string depth band.
  let emit = handoffTriage && typeof handoffTriage === 'object' && handoffTriage.triage_track
    ? handoffTriage
    : null;
  if (!emit && triageLock) {
    emit = buildHandoffTriageEmit(triageLock);
  }
  if (!emit) {
    // Confirmed depth/tier from Stage-0, or safe FULL+Heavy when callers still pass
    // only a depth string (legacy Stage-2 call sites / dogfood). Never emit bare
    // "HEAVY" as triage_track (that was a model-tier mis-label).
    const depthPin = legacyBandToDepth(depth) || DEPTH_BANDS.FULL;
    const tierPin =
      tier === 'Standard' || tier === 'standard' || tier === MODEL_TIERS.STANDARD
        ? MODEL_TIERS.STANDARD
        : MODEL_TIERS.HEAVY;
    emit = buildHandoffTriageEmit(
      createLockRecord({
        tier: tierPin,
        depth: depthPin,
        rationale: depth
          ? `Stage-2 handoff from confirmed depth=${depthPin} tier=${tierPin}`
          : `Stage-2 handoff default FULL+Heavy (no Stage-0 triageLock passed — prefer wiring handoffTriage)`,
        source: 'inherit',
      }),
    );
  }

  // The explicit doc-resolution config (paths relative to the output dir).
  const configPath = path.join(dir, 'foreman.config.json');
  const config = {
    triage_track: emit.triage_track,
    triage: emit.triage,
    docs: {
      description: fileNames.description,
      plan: fileNames.plan,
      execution_log: fileNames.execution_log,
    },
  };
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n');

  log(`stage2 emit: doc-trio + foreman.config.json + scripts/run-all-tests.mjs → ${dir} (triage_track=${emit.triage_track})`);
  return {
    dir,
    files: { ...files, run_all_tests: runAllPath },
    configPath,
    fileNames,
    handoffTriage: emit,
    hardening: hardeningResult,
  };
}

// ---------------------------------------------------------------------------
// (3) The handoff — guarded by the well-formedness gate (must pass first).
// ---------------------------------------------------------------------------

/**
 * Gate the handoff on the machine WELL-FORMEDNESS gate (Wave 4): SPAWN Foreman's
 * `locate-plan.mjs --json` over the emitted dir and refuse to hand off unless it
 * exits 0 (zero HALTs). On FAIL this HALTs for the human with the captured exit code
 * + stderr (forge-proof evidence) — Crucible never hands Foreman a malformed doc-trio.
 *
 * @param {object} o
 * @param {string}   o.projectDir                 the emitted doc-trio dir
 * @param {?string} [o.artifactsDir=null]         when set, persists the forge-proof artifact
 * @param {Function}[o.runGate=runWellFormednessGate]  injectable (tests)
 * @param {Function}[o.log=()=>{}]
 * @returns {{handed_off:true, gate:object}}
 */
export function runHandoffGate({ projectDir, artifactsDir = null, runGate = runWellFormednessGate, log = () => {} } = {}) {
  if (!projectDir) throw new HaltError('runHandoffGate requires a projectDir', 'pass the emitted doc-trio dir');
  const gate = runGate({ projectDir, artifactsDir, log });
  if (!gate.pass) {
    throw haltForHuman(
      `Stage-2 handoff BLOCKED: the well-formedness gate failed (exit ${gate.status ?? 'spawn-error'}) — ${(gate.stderr || '').trim() || 'see the forge-proof artifact'}`,
      'well-formedness-gate-failed',
    );
  }
  log(`stage2 handoff: well-formedness gate PASS (${gate.report?.total_waves ?? '?'} waves resolved) — clear to hand off`);
  return { handed_off: true, gate };
}

// ---------------------------------------------------------------------------
// (4) The user-approval HALT gate — the canonical stage2->done boundary.
// ---------------------------------------------------------------------------

/**
 * The Stage-2 → done approval gate. Even a model-side-converged Implementation Plan
 * does NOT hand off on its own — the user is the convergence authority. Without
 * approval this HALTs (reusing HALT_GATES['stage2->done'] = 'implementation-plan-
 * approval'). With approval and a model-side-lockable loop it returns the approval.
 *
 * @param {object} o
 * @param {object}  o.loop                  the runMasterPlanLoop result
 * @param {boolean}[o.approved=false]
 * @param {Function}[o.log=()=>{}]
 */
export function approveImplementationPlan({ loop, approved = false, log = () => {} } = {}) {
  // P1 2026-07-25 (0069): a HUMAN-LOCKABLE loop is approvable when the user has
  // explicitly approved — that is the human-lockable design ("approve to lock";
  // the user is the convergence authority). Model-side convergence stays required
  // in every other case; nothing here weakens the unapproved paths.
  const humanLockApproved = !!(loop && loop.humanLockable && approved === true);
  if (!loop || !(loop.modelSideLockable || humanLockApproved)) {
    throw haltForHuman(
      'Stage 2 has not converged model-side — cannot approve the Implementation Plan yet',
      'stage2-not-converged',
    );
  }
  const gate = HALT_GATES['stage2->done'];
  if (!approved) {
    log('stage2: Implementation Plan converged model-side — HALT for the user to approve (the convergence authority)');
    throw haltForHuman(gate.reason, gate.name);
  }
  log(humanLockApproved
    ? 'stage2: HUMAN-LOCKABLE Implementation Plan APPROVED by the user (convergence authority) — ready to emit + hand off'
    : 'stage2: Implementation Plan APPROVED — ready to emit + hand off');
  return { approved: true, gate: gate.name, roundsRun: loop.roundsRun, humanLockable: humanLockApproved || undefined };
}

// ---------------------------------------------------------------------------
// The Stage-2 orchestration — decompose → render → loop → approve → emit → handoff.
// ---------------------------------------------------------------------------

/**
 * Run Stage 2 end-to-end. Requires an APPROVED Master Plan (the Stage-1 deliverable).
 * Decomposes it into waves, renders the Foreman-ready doc-trio, runs the Shark-Tank
 * loop to model-side convergence, HALTs at the user-approval gate, then (on approval)
 * emits the doc-trio + `foreman.config.json` and gates the handoff on the machine
 * well-formedness gate — which must PASS before handoff. Without approval (or on a
 * blocking HALT) it HALTs for the human.
 *
 * @param {object} o
 * @param {Function} o.agent                  the Wave-1 agent seam
 * @param {string}   o.northStar              the LOCKED North Star
 * @param {string}   o.masterPlan             the APPROVED Master Plan (Stage-1 output)
 * @param {string[]}[o.criteria=[]]
 * @param {string}   o.outputDir              where the doc-trio is emitted (the handoff target)
 * @param {string}  [o.title]                 the planned project's title
 * @param {string}  [o.summary='']            description-doc summary
 * @param {string}  [o.testCommand]           the ground-truth gate command for the emitted plan
 * @param {?object} [o.research=null]         the Wave-5 coordinator (passed to the loop)
 * @param {string[]}[o.acceptanceCriteria=[]] the Judge's oracle
 * @param {boolean} [o.approved=false]        the user's Implementation-Plan approval
 * @param {number}  [o.roundCap=5]
 * @param {?string} [o.depth=null]            the user-CONFIRMED Stage-0 triage depth
 *                                            ('LITE' → default roundCap 2; explicit wins)
 * @param {?string} [o.tier=null]             the user-CONFIRMED Stage-0 model tier
 * @param {?object} [o.triageLock=null]       Stage-0 validating lock (preferred for emit)
 * @param {?object} [o.handoffTriage=null]    Stage-0 buildHandoffTriageEmit result
 * @param {?string} [o.artifactsDir=null]     Shark-Tank + gate artifacts dir
 * @param {Function}[o.log=()=>{}]
 * @returns {Promise<{waves:object[], plan:string, loop:object, approval:object,
 *                    docTrio:object, handoff:object}>}
 */
export async function runStage2({
  agent,
  northStar,
  masterPlan,
  criteria = [],
  outputDir,
  title = 'Crucible-planned project',
  summary = '',
  testCommand = DEFAULT_TEST_COMMAND,
  research = null,
  acceptanceCriteria = [],
  approved = false,
  roundCap = undefined,
  depth = null,
  tier = null,
  triageLock = null,
  handoffTriage = null,
  artifactsDir = null,
  statusLog = null,
  routes = null,
  log = () => {},
} = {}) {
  requireAgent(agent, 'runStage2');
  // cf-slick: band profile from locked depth (same as Stage 1). Explicit roundCap wins.
  const band = resolveBandProfile(depth);
  if (roundCap === undefined) roundCap = band.roundCap;
  if (depth) log(`stage2: depth=${band.depth} → roundCap=${roundCap} · sharks=${band.sharkRoles}`);
  log(`stage2: band stamp ${JSON.stringify(bandProfileStamp(band))}`);
  // 0075 LITE honest ETA banner
  log(`stage2: planning typically 20-60m; if silent >15m check stage2-progress.json / heartbeat / process`);
  if (!northStar) throw new HaltError('runStage2 requires a locked North Star', 'Stage 2 starts from the Stage-0 North-Star lock');
  if (!masterPlan) throw new HaltError('runStage2 requires the approved Master Plan', 'Stage 2 starts from the Stage-1 Master-Plan approval');
  if (!outputDir) throw new HaltError('runStage2 requires an outputDir', 'pass the handoff output directory');

  // Durability root (0075): progress + last-crash + HALT.json live here.
  const stateDir = path.resolve(artifactsDir || path.join(path.resolve(outputDir), '.crucible'));
  try { fs.mkdirSync(stateDir, { recursive: true }); } catch { /* */ }
  const progressPath = path.join(stateDir, 'stage2-progress.json');
  const live = { lastStep: 'init', waves: null, plan: null };

  const guards = installProcessLifetimeGuards({
    log: (m) => { try { log(m); } catch { /* */ } },
    crashPath: path.join(stateDir, 'last-crash.json'),
    heartbeatPath: path.join(stateDir, 'heartbeat.json'),
    label: 'crucible-stage2',
    onFatal: (payload) => {
      // Process death must never be silent (0075): HALT.json + force-emit if decomp exists.
      try {
        writeStage2HaltJson(stateDir, {
          reason: `process death (${payload?.kind || 'fatal'}): ${String(payload?.message || '').slice(0, 400)}`,
          lastStep: live.lastStep,
          humanLockable: Array.isArray(live.waves) && live.waves.length > 0,
          pendingAction: 'stage2-process-death',
          artifacts: {
            last_crash: path.join(stateDir, 'last-crash.json'),
            progress: progressPath,
            wave_decomposition: fs.existsSync(path.join(stateDir, 'wave-decomposition.json'))
              ? path.join(stateDir, 'wave-decomposition.json') : null,
          },
        });
        if (Array.isArray(live.waves) && live.waves.length) {
          forceEmitStage2HumanLockable({
            waves: live.waves, outputDir, title, northStar, criteria, summary, testCommand,
            depth, tier, triageLock, handoffTriage, artifactsDir: stateDir, log,
            reason: 'Stage-2 process death after wave decomp — human-lockable draft emitted',
          });
        }
      } catch { /* never throw from onFatal */ }
    },
  });

  try {
    // (1) Decompose the approved Master Plan into waves (PM heuristics).
    live.lastStep = 'decompose';
    stampStage2Progress(stateDir, { phase: 'decompose', status: 'start' });
    const waves = await withPhaseProgress({
      phase: 'stage2-decompose',
      log,
      progressPath,
      guards,
      fn: () => decomposeIntoWaves({ agent, northStar, criteria, masterPlan, log }),
    });
    live.waves = waves;
    try {
      fs.writeFileSync(
        path.join(stateDir, 'wave-decomposition.json'),
        JSON.stringify({ waves, ts: new Date().toISOString() }, null, 2) + '\n',
        'utf8',
      );
    } catch { /* best-effort */ }
    stampStage2Progress(stateDir, {
      phase: 'decompose', status: 'done',
      extra: { wave_count: waves.length },
    });

    // (2) Render the Foreman-ready plan (the loop vets THIS human-readable draft; the
    //     final emission re-renders from the same structured waves, so well-formedness
    //     is guaranteed by construction regardless of free-text revision).
    //     Journal 0080: inject property-gate checklist into the draft the Sharks review
    //     so "asserted as prose" cannot leave Stage 2 as GREEN without mechanism text.
    live.lastStep = 'render-plan';
    let plan = renderImplementationPlan({ title, northStar, criteria, waves, testCommand });
    {
      const applied = enforceHardeningGate({ plan, addsSurface: true, log });
      plan = applied.plan;
      try {
        fs.writeFileSync(
          path.join(stateDir, 'hardening-gate-result.json'),
          JSON.stringify({ ...applied.gate, claims: applied.claims, injected: applied.injected, phase: 'post-render', ts: new Date().toISOString() }, null, 2) + '\n',
          'utf8',
        );
      } catch { /* best-effort */ }
      // Do not HALT on fail at draft stage — Shark loop may add mechanisms; emit path is fail-closed.
      if (!applied.gate.pass) {
        log(`stage2: hardening draft not yet pass (will re-check on emit): ${applied.gate.detail}`);
      }
    }
    live.plan = plan;

    // (3) The Shark-Tank loop to model-side convergence (Stage-1's generic loop).
    //
    // T5 (2026-07-11): a round-cap HALT no longer throws the run away. The emission
    // path re-renders from the STRUCTURED waves (well-formed by construction — the
    // same property the approved path relies on), so on cap we can honestly emit
    // the current doc-trio to an UNMISTAKABLY-unapproved draft dir, run the machine
    // well-formedness gate over it, and HALT with everything attached for the user
    // to review. The user stays the convergence authority; Foreman is never handed
    // the draft dir (handoff still requires approval on the real outputDir).
    live.lastStep = 'shark-tank';
    stampStage2Progress(stateDir, { phase: 'shark-tank', status: 'start' });
    let loop;
    try {
      loop = await withPhaseProgress({
        phase: 'stage2-shark-tank',
        log,
        progressPath,
        guards,
        fn: () => runMasterPlanLoop({
          agent, northStar, criteria,
          draft: plan, research, acceptanceCriteria, roundCap, artifactsDir: stateDir, log,
          sharkRoles: band.sharkRoles,
          capPendingAction: 'stage2-round-cap',
          statusLog, statusLabel: `Crucible Stage 2 (${band.depth})`,
          routes,
        }),
      });
    } catch (e) {
      // P1 2026-07-25 (journal 0069): with `approved: true` the user has ALREADY
      // exercised the convergence authority — a human-lockable / round-cap outcome
      // must EMIT-AND-RETURN on the real outputDir ("go go go" was impossible: the
      // loop re-tanked, threw, and no doc-trio was ever written; the only recovery
      // was an out-of-tree force-emit script). The machine well-formedness gate
      // below still fails closed; only the throw-without-docs is retired.
      const lockableWithApproval = approved === true && e && e.halt_for_human &&
        (e.pending_action === 'stage1-human-lockable' || e.pending_action === 'stage2-round-cap') &&
        (e.loop?.draft != null || e.best_draft != null);
      if (lockableWithApproval) {
        plan = assertPlanText(e.loop?.draft ?? e.best_draft, { label: 'implementation plan (human-lockable best draft)' });
        loop = e.loop
          ? { ...e.loop, humanLockable: true }
          : { humanLockable: true, modelSideLockable: false, roundsRun: e.best_draft?.roundsRun ?? null, draft: plan };
        log(`stage2: approved:true + ${e.pending_action} — emitting the HALT's best draft as the handoff ` +
          `(0069 emit-and-return; the user is the convergence authority; well-formedness gate still applies)`);
        stampStage2Progress(stateDir, { phase: 'shark-tank', status: 'human-lockable-approved' });
      } else {
      if (e && e.halt_for_human && e.pending_action === 'stage2-round-cap') {
        const draftDir = path.join(path.resolve(outputDir), '_unapproved-cap-draft');
        try {
          const description = renderDescriptionDoc({ title, northStar, criteria, summary });
          const executionLog = renderExecutionLog({ title, waveCount: waves.length });
          const docTrio = writeDocTrio({
            outputDir: draftDir, plan, description, executionLog,
            depth, tier, triageLock, handoffTriage, log,
          });
          const gate = runWellFormednessGate({ projectDir: docTrio.dir, artifactsDir: stateDir, log });
          e.emitted = { docTrio, wellFormedness: { pass: !!gate.pass, status: gate.status ?? null } };
          e.reason += ` — the full doc-trio is EMITTED for review at ${docTrio.dir} ` +
            `(well-formedness gate: ${gate.pass ? 'PASS' : 'FAIL'}; this draft dir is NOT the handoff)`;
          log(`stage2 cap: unapproved doc-trio emitted to ${docTrio.dir} (well-formedness ${gate.pass ? 'PASS' : 'FAIL'})`);
          writeStage2HaltJson(stateDir, {
            reason: e.reason,
            lastStep: 'shark-tank-round-cap',
            humanLockable: true,
            pendingAction: 'stage2-round-cap',
            artifacts: { draft_dir: docTrio.dir },
          });
        } catch (emitErr) {
          // Emission is best-effort on the HALT path — the HaltError still carries
          // the best draft; never mask the cap HALT with an emission failure.
          log(`stage2 cap: could not emit the draft doc-trio (${emitErr.reason || emitErr.message})`);
        }
      }
      throw e;
      }
    }
    stampStage2Progress(stateDir, { phase: 'shark-tank', status: 'done' });

    // Prefer the loop's revised draft when present (human-readable Shark revisions).
    if (loop?.draft) {
      plan = assertPlanText(loop.draft, { label: 'implementation plan (post-shark)' });
      live.plan = plan;
    }
    // Re-apply hardening after Shark free-text edits (checklist may have been stripped).
    {
      const applied = enforceHardeningGate({ plan, addsSurface: true, log });
      plan = applied.plan;
      live.plan = plan;
      try {
        fs.writeFileSync(
          path.join(stateDir, 'hardening-gate-result.json'),
          JSON.stringify({ ...applied.gate, claims: applied.claims, injected: applied.injected, phase: 'post-shark', ts: new Date().toISOString() }, null, 2) + '\n',
          'utf8',
        );
      } catch { /* */ }
    }

    // (4) The user-approval HALT gate (implementation-plan-approval). HALTs if unapproved.
    live.lastStep = 'approval';
    const approval = approveImplementationPlan({ loop, approved, log });

    // (5) Emit the doc-trio + config, then gate on hardening (0080) + well-formedness.
    live.lastStep = 'emit-handoff';
    stampStage2Progress(stateDir, { phase: 'emit-handoff', status: 'start' });
    const description = renderDescriptionDoc({ title, northStar, criteria, summary });
    const executionLog = renderExecutionLog({ title, waveCount: waves.length });
    const docTrio = writeDocTrio({
      outputDir, plan, description, executionLog,
      depth, tier, triageLock, handoffTriage, log,
      enforceHardening: true,
      addsSurface: true,
    });
    const handoff = runHandoffGate({ projectDir: docTrio.dir, artifactsDir: stateDir, log });
    stampStage2Progress(stateDir, { phase: 'emit-handoff', status: 'done' });
    live.lastStep = 'done';

    return { waves, plan, loop, approval, docTrio, handoff };
  } catch (e) {
    // Expected human HALTs (approval, cap, well-formedness) stay HaltErrors — do not
    // re-label them as process death. Unexpected errors + process-death path leave HALT.json.
    const expectedHuman = e && e.halt_for_human;
    if (!expectedHuman) {
      writeStage2HaltJson(stateDir, {
        reason: `unexpected Stage-2 failure at ${live.lastStep}: ${e?.message || e}`,
        lastStep: live.lastStep,
        humanLockable: Array.isArray(live.waves) && live.waves.length > 0,
        pendingAction: 'stage2-unexpected-error',
        artifacts: {
          progress: progressPath,
          wave_decomposition: fs.existsSync(path.join(stateDir, 'wave-decomposition.json'))
            ? path.join(stateDir, 'wave-decomposition.json') : null,
        },
      });
      if (Array.isArray(live.waves) && live.waves.length) {
        try {
          forceEmitStage2HumanLockable({
            waves: live.waves, outputDir, title, northStar, criteria, summary, testCommand,
            depth, tier, triageLock, handoffTriage, artifactsDir: stateDir, log,
            reason: `Stage-2 unexpected error at ${live.lastStep} — human-lockable draft emitted`,
          });
        } catch { /* best-effort */ }
      }
    }
    throw e;
  } finally {
    try { guards.uninstall(); } catch { /* */ }
  }
}

// ---------------------------------------------------------------------------
// Shared guard.
// ---------------------------------------------------------------------------

function requireAgent(agent, who) {
  if (typeof agent !== 'function') {
    throw new HaltError(`${who} requires an agent() function`, `pass the Wave-1 seam: ${who}({ agent: makeAgentSeam(...).agent })`);
  }
}

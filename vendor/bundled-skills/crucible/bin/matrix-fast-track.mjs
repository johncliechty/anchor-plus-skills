#!/usr/bin/env node
// matrix-fast-track.mjs — Crucible's Lean 2-Stage `--matrix-fast-track` (6-9 model calls)
// and Enforced `LITE` Fast Path (<= 4 model calls).
//
// Retires the redundant Stage-2 Shark-Tank + Stage-2 Elegance loop on LITE and MATRIX-FAST-TRACK:
//   - Stage 0: Automatic Anvil brownfield AST intake (`python anvil_engine.py facts --repo <repoDir> --json`,
//     falling back cleanly to deterministic zero-LLM repo/symbol scan in <2s) + deterministic `testCommand`
//     preflight validation (`0` LLM calls).
//   - Stage 1: Conditional Superjump architectural option pass (when `SPIKE-FIRST` or `>=2` competing designs)
//     + unified Plan+Waves draft + 1 cross-family heterogeneous L0-L5 6-Layer Adversarial Matrix + <=1 `120s`
//     delta-only verification pass on patched blockers (stopping immediately on 0 blockers per ELEGANCE.md Rule 5).
//   - Stage 2: Deterministic wave serialization (`## Wave 1 .. ## Wave N` + `### Wave W.k` disjoint-write-set
//     sub-waves) + Chekhov plan-quality guards + portfolio skill gates + `locate-plan.mjs` validation (`0` LLM calls).

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { HaltError, haltForHuman } from './crucible-lib.mjs';
import { resolveBandProfile, normalizeBandDepth, bandProfileStamp } from './band-profile.mjs';
import { tracesToNorthStar } from './shark-tank.mjs';
import { runWellFormednessGate } from './gates.mjs';
import { runSlim } from './slim.mjs';
import {
  DEFAULT_TEST_COMMAND,
  normalizeWaves,
  renderImplementationPlan,
  renderDescriptionDoc,
  renderExecutionLog,
  writeDocTrio,
  runHandoffGate,
} from './stage2.mjs';
import {
  APPROVAL_MAX_WORDS,
  attachPortfolioSkillGates,
  checkApprovalBlockWordBudget,
  detectPortfolioSkillGates,
  formatPlainEnglishApprovalGate,
  partitionDisjointSubWaves,
  runChekhovPlanQualityLint,
} from './plan-quality-gates.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));

export const LITE_MAX_MODEL_CALLS = 4;
export const MATRIX_MIN_MODEL_CALLS_TARGET = 6;
export const MATRIX_MAX_MODEL_CALLS = 9;
export const DELTA_VERIFY_TIMEOUT_MS = 120_000;

export const MATRIX_LAYERS = Object.freeze([
  { id: 'L0', name: 'North Star Fidelity & Scope-Cut Honesty' },
  { id: 'L1', name: 'Anvil Pure-Core / Deep-Module Architecture' },
  { id: 'L2', name: 'Aegis Security CWE Boundaries' },
  { id: 'L3', name: 'UI Chrome Mockup & Figure-Designer Gate' },
  { id: 'L4', name: 'Testability, Wave-1 Pilot Slice & O(N) Call Budget' },
  { id: 'L5', name: 'Gandalf Operational Simplicity & Rabbit-Catcher Cut' },
]);

const DEFAULT_ANVIL_CANDIDATES = [
  process.env.ANVIL_ENGINE_PATH,
  '<path> Foundry\\skills\\anvil\\scripts\\anvil_engine.py',
  '<path> Foundry\\skills\\anvil\\anvil_engine.py',
  path.resolve(HERE, '../../../Skill Foundry/skills/anvil/scripts/anvil_engine.py'),
  path.resolve(HERE, '../../../Skill Foundry/skills/anvil/anvil_engine.py'),
].filter(Boolean);

const SKIP_SCAN_DIRS = new Set([
  '.git', 'node_modules', '_archive', '.foreman', '.crucible', '__pycache__', '.venv', 'venv', 'dist', 'build', 'coverage',
]);

const CODE_EXT_RE = /\.(?:mjs|cjs|js|ts|tsx|jsx|py|go|rs|java|cs)$/i;

/**
 * Deterministic zero-LLM fallback symbol & file-tree scan (<2s, max 160 files).
 */
export function scanDeterministicRepoFacts(repoDir, { maxFiles = 160, budgetMs = 1500 } = {}) {
  const start = Date.now();
  const root = path.resolve(repoDir);
  const files = [];
  const symbols = [];
  const extCounts = {};

  function walk(dir, depth = 0) {
    if (files.length >= maxFiles || Date.now() - start > budgetMs || depth > 5) return;
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (files.length >= maxFiles || Date.now() - start > budgetMs) break;
      if (e.name.startsWith('.') && e.name !== '.github') continue;
      if (SKIP_SCAN_DIRS.has(e.name)) continue;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        walk(full, depth + 1);
      } else if (e.isFile()) {
        const rel = path.relative(root, full).replace(/\\/g, '/');
        files.push(rel);
        const ext = path.extname(e.name).toLowerCase() || '(no-ext)';
        extCounts[ext] = (extCounts[ext] || 0) + 1;
        if (CODE_EXT_RE.test(e.name) && symbols.length < 120) {
          try {
            const stat = fs.statSync(full);
            if (stat.size <= 128_000) {
              const snippet = fs.readFileSync(full, 'utf8');
              const symRe = /(?:export\s+(?:async\s+)?(?:function|class|const)\s+([A-Za-z0-9_$]+)|^(?:async\s+)?def\s+([A-Za-z0-9_]+)|^class\s+([A-Za-z0-9_]+))/gm;
              let m;
              while ((m = symRe.exec(snippet)) !== null && symbols.length < 120) {
                const sym = m[1] || m[2] || m[3];
                if (sym) symbols.push(`${rel}:${sym}`);
              }
            }
          } catch { /* ignore unreadable file */ }
        }
      }
    }
  }

  walk(root, 0);

  let packageTestScript = null;
  const pkgPath = path.join(root, 'package.json');
  if (fs.existsSync(pkgPath)) {
    try {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
      packageTestScript = pkg?.scripts?.test ?? null;
    } catch { /* ignore */ }
  }

  return {
    repoDir: root,
    fileCount: files.length,
    files: files.slice(0, 80),
    symbols: symbols.slice(0, 80),
    extCounts,
    packageTestScript,
  };
}

/**
 * Stage-0 Anvil brownfield AST intake (`0` LLM calls, `<2s`).
 * Spawns `python anvil_engine.py facts --repo <repoDir> --json` if available;
 * falls back cleanly to deterministic file-tree/symbol scan if absent or non-zero.
 */
export function runAnvilBrownfieldIntake({
  repoDir,
  spawn = spawnSync,
  pythonBin = 'python',
  anvilPath = null,
  timeoutMs = 1800,
  log = () => {},
} = {}) {
  const t0 = Date.now();
  if (!repoDir || !fs.existsSync(repoDir)) {
    return { ok: false, source: 'none', llmCalls: 0, elapsedMs: Date.now() - t0, facts: null };
  }
  const root = path.resolve(repoDir);
  const candidates = anvilPath ? [anvilPath] : DEFAULT_ANVIL_CANDIDATES;
  const resolvedAnvil = candidates.find((p) => p && fs.existsSync(p)) || null;

  if (resolvedAnvil) {
    try {
      const r = spawn(pythonBin, [resolvedAnvil, 'facts', '--repo', root, '--json'], {
        encoding: 'utf8',
        timeout: timeoutMs,
        windowsHide: true,
        shell: false,
      }) || {};
      if (!r.error && r.status === 0 && r.stdout) {
        const parsed = JSON.parse(String(r.stdout));
        const elapsedMs = Date.now() - t0;
        log(`stage0 anvil: AST facts extracted in ${elapsedMs}ms (0 LLM calls)`);
        return { ok: true, source: 'anvil-ast', llmCalls: 0, elapsedMs, facts: parsed };
      }
    } catch {
      // Clean fallback below.
    }
  }

  const facts = scanDeterministicRepoFacts(root, { budgetMs: Math.max(300, timeoutMs - 200) });
  const elapsedMs = Date.now() - t0;
  log(`stage0 anvil fallback: deterministic repo scan (${facts.fileCount} files, ${facts.symbols.length} symbols) in ${elapsedMs}ms (0 LLM calls)`);
  return { ok: true, source: 'deterministic-scan', llmCalls: 0, elapsedMs, facts };
}

/**
 * Deterministic `testCommand` doctor preflight (`0` LLM calls).
 */
export function validateTestCommandPreflight({
  testCommand = DEFAULT_TEST_COMMAND,
  repoDir = null,
  willEmitRunner = true,
  docsOnly = false,
} = {}) {
  if (docsOnly) {
    return { ok: true, llmCalls: 0, command: null, detail: 'docs-only plan requires no test-command' };
  }
  const cmd = typeof testCommand === 'string' ? testCommand.trim() : '';
  if (!cmd) {
    return {
      ok: false,
      llmCalls: 0,
      command: null,
      detail: 'empty testCommand — code waves require an executable test-command (e.g. `node scripts/run-all-tests.mjs`)',
    };
  }
  if (cmd.includes('&&')) {
    return {
      ok: false,
      llmCalls: 0,
      command: cmd,
      detail: 'testCommand contains `&&` shell chaining — incompatible with shell:false / PowerShell 5.1',
    };
  }
  if (/^node\s+--test\s+test\/?\s*$/i.test(cmd)) {
    return {
      ok: false,
      llmCalls: 0,
      command: cmd,
      detail: 'bare `node --test test/` fails on Windows directory expansion — use `node scripts/run-all-tests.mjs`',
    };
  }
  const scriptMatch = cmd.match(/^node\s+([^\s]+\.m?js)$/i);
  if (scriptMatch && repoDir && !willEmitRunner) {
    const candidate = path.resolve(repoDir, scriptMatch[1]);
    if (!fs.existsSync(candidate)) {
      return {
        ok: false,
        llmCalls: 0,
        command: cmd,
        detail: `referenced test runner script does not exist: ${candidate}`,
      };
    }
  }
  return { ok: true, llmCalls: 0, command: cmd, detail: 'testCommand preflight OK' };
}

/** Wrap `agent` with a strict hard ceiling on model calls (`maxCalls`). */
export function createCallBudgetedAgent(agent, { maxCalls, bandName = 'Crucible' }) {
  if (typeof agent !== 'function') {
    throw new HaltError(`${bandName} requires an agent() function`, 'pass an agent(prompt, opts) seam');
  }
  let count = 0;
  const history = [];
  const wrapped = async (prompt, opts = {}) => {
    if (count >= maxCalls) {
      throw haltForHuman(
        `${bandName} model-call cap exceeded: attempted call #${count + 1} with hard ceiling maxModelCalls=${maxCalls}`,
        `${bandName.toLowerCase()}-call-cap-exceeded`,
      );
    }
    count += 1;
    history.push({ ordinal: count, label: opts.label || null, role: opts.role || null, timeoutMs: opts.timeoutMs ?? null });
    return agent(prompt, opts);
  };
  wrapped.count = () => count;
  wrapped.history = () => [...history];
  return wrapped;
}

/**
 * Enforced `LITE` Fast Path (`<= 4` model calls):
 * Stage-0 intake (optional 1 call if `frameIntake: true`) + `testCommand` doctor preflight (`0` calls)
 * -> unified Plan+Waves draft -> 1 cross-family review -> <=1 delta patch -> Chekhov lint -> `locate-plan.mjs`.
 */
export async function runLiteFastPath({
  agent,
  task,
  intent = null,
  context = '',
  repoDir = null,
  outDir = null,
  outputDir = null,
  testCommand = DEFAULT_TEST_COMMAND,
  frameIntake = false,
  families = {},
  requireIndependentReview = false,
  wellFormedness = null,
  tier = 'standard',
  title = null,
  spawn = spawnSync,
  log = () => {},
} = {}) {
  const effectiveTask = String(task || intent || '').trim();
  if (!effectiveTask) {
    throw new HaltError('runLiteFastPath requires a non-empty task/intent', 'pass { task } or { intent }');
  }
  const targetOutDir = outDir || outputDir || null;
  const preflight = validateTestCommandPreflight({ testCommand, repoDir, willEmitRunner: true });
  if (!preflight.ok) {
    throw haltForHuman(`LITE preflight failed: ${preflight.detail}`, 'lite-test-command-preflight-failed');
  }

  const anvil = repoDir ? runAnvilBrownfieldIntake({ repoDir, spawn, log }) : null;
  const budgetedAgent = createCallBudgetedAgent(agent, { maxCalls: LITE_MAX_MODEL_CALLS, bandName: 'LITE' });

  let framedContext = context ? String(context) : '';
  if (anvil?.ok && anvil.facts) {
    framedContext = [
      framedContext,
      `Brownfield facts (${anvil.source}, 0 LLM calls): ${JSON.stringify({
        fileCount: anvil.facts.fileCount,
        files: (anvil.facts.files || []).slice(0, 25),
        symbols: (anvil.facts.symbols || []).slice(0, 25),
      })}`,
    ].filter(Boolean).join('\n\n');
  }

  let stage0Framing = null;
  if (frameIntake) {
    stage0Framing = await budgetedAgent(
      `Frame a crisp 1-sentence North Star and <=3 testable criteria for:\n${effectiveTask}\n${framedContext}`,
      { label: 'lite:stage0-intake', role: 'synthesizer' },
    );
    if (stage0Framing) {
      const textFrame = typeof stage0Framing === 'string' ? stage0Framing : JSON.stringify(stage0Framing);
      framedContext = [framedContext, `Locked Stage-0 Framing:\n${textFrame}`].filter(Boolean).join('\n\n');
    }
  }

  const slimResult = await runSlim({
    agent: budgetedAgent,
    task: effectiveTask,
    context: framedContext,
    outDir: targetOutDir,
    log,
    wellFormedness,
    requireIndependentReview,
    families,
    depth: 'LITE',
    tier,
    title,
  });

  const totalCalls = budgetedAgent.count();
  const portfolioGates = detectPortfolioSkillGates({
    intent: effectiveTask,
    northStar: slimResult.northStar,
    plan: slimResult.plan,
    waves: slimResult.waves,
  });
  const wordBudget = checkApprovalBlockWordBudget(slimResult.gate?.message || '', APPROVAL_MAX_WORDS);

  return {
    ...slimResult,
    band: 'LITE',
    calls: totalCalls,
    maxModelCalls: LITE_MAX_MODEL_CALLS,
    callHistory: budgetedAgent.history(),
    preflight,
    anvil,
    stage0Framing,
    portfolioGates,
    wordBudget,
  };
}

// ---------------------------------------------------------------------------
// Real `MATRIX-FAST-TRACK` (6-9 bounded model calls)
// ---------------------------------------------------------------------------

export const MATRIX_STAGE0_SCHEMA = {
  type: 'object',
  required: ['northStar', 'criteria'],
  properties: {
    northStar: { type: 'string' },
    criteria: { type: 'array', items: { type: 'string' } },
    deferredScope: { type: 'array', items: { type: 'string' } },
    competingDesigns: { type: 'number' },
  },
};

export const SUPERJUMP_OPTIONS_SCHEMA = {
  type: 'object',
  required: ['selectedOption', 'rationale', 'options'],
  properties: {
    selectedOption: { type: 'string' },
    rationale: { type: 'string' },
    options: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'summary'],
        properties: {
          name: { type: 'string' },
          summary: { type: 'string' },
          tradeOff: { type: 'string' },
        },
      },
    },
  },
};

export const MATRIX_DRAFT_SCHEMA = {
  type: 'object',
  required: ['waves'],
  properties: {
    title: { type: 'string' },
    summary: { type: 'string' },
    testCommand: { type: 'string' },
    deferredScope: { type: 'array', items: { type: 'string' } },
    cutElement: { type: 'string' },
    waves: {
      type: 'array',
      minItems: 1,
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

export const MATRIX_CELL_REVIEW_SCHEMA = {
  type: 'object',
  required: ['layersChecked', 'findings'],
  properties: {
    layersChecked: { type: 'array', items: { type: 'string' } },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['layer', 'severity', 'topic', 'traces_to_north_star', 'message'],
        properties: {
          layer: { enum: ['L0', 'L1', 'L2', 'L3', 'L4', 'L5'] },
          severity: { enum: ['BLOCKER', 'MAJOR', 'MINOR', 'NIT'] },
          topic: { type: 'string' },
          traces_to_north_star: { type: ['boolean', 'string'] },
          message: { type: 'string' },
          fix: { type: 'string' },
        },
      },
    },
  },
};

export const MATRIX_DELTA_VERIFY_SCHEMA = {
  type: 'object',
  required: ['resolved', 'remainingBlockers'],
  properties: {
    resolved: { type: 'boolean' },
    remainingBlockers: {
      type: 'array',
      items: {
        type: 'object',
        required: ['topic', 'message'],
        properties: {
          layer: { type: 'string' },
          topic: { type: 'string' },
          message: { type: 'string' },
        },
      },
    },
  },
};

const MATRIX_SEATS = Object.freeze([
  {
    id: 'M1',
    label: 'matrix:L0-L5:northstar-simplicity',
    layers: ['L0', 'L5'],
    focus:
      'L0 North Star fidelity & scope-cut honesty (every wave serves the locked North Star; deferred scope named aloud) + ' +
      'L5 Gandalf operational simplicity / Rabbit-Catcher cut check (flag unnecessary abstractions or over-engineering).',
  },
  {
    id: 'M2',
    label: 'matrix:L1-L2:arch-security',
    layers: ['L1', 'L2'],
    focus:
      'L1 Anvil Pure-Core / Deep-Module / Functional-Core-Imperative-Shell architecture + ' +
      'L2 Aegis defensive security CWE boundaries (CWE-78 shell injection, CWE-22 path traversal, CWE-94/502 unsafe eval/deser, CWE-918 SSRF, CWE-798 secrets).',
  },
  {
    id: 'M3',
    label: 'matrix:L3-L4:surface-budget',
    layers: ['L3', 'L4'],
    focus:
      'L3 UI Interactive Chrome Mockup (`ft.py chrome-open` + `ft.py look`) / `Figure-Designer` visual gate when UI/SVG files are touched + ' +
      'L4 deterministic testability, Chekhov Wave-1 usable end-to-end pilot slice, and O(N) LLM call/latency budget bounds.',
  },
]);

function tallyMatrixReviews(seatOutputs = []) {
  const byTopic = new Map();
  const layersCovered = new Set();

  seatOutputs.forEach((out, seatIdx) => {
    const layers = Array.isArray(out?.layersChecked) ? out.layersChecked : MATRIX_SEATS[seatIdx]?.layers || [];
    layers.forEach((l) => layersCovered.add(l));
    const findings = Array.isArray(out?.findings) ? out.findings : [];
    for (const f of findings) {
      if (f?.layer) layersCovered.add(f.layer);
      const key = String(f?.topic || f?.message || `finding-${seatIdx}`).trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
      const prev = byTopic.get(key) || {
        id: key,
        layer: f?.layer || 'L0',
        severity: 'NIT',
        traces: false,
        agreement: 0,
        seats: new Set(),
        messages: [],
        fixes: [],
      };
      const rank = { BLOCKER: 4, MAJOR: 3, MINOR: 2, NIT: 1 };
      if ((rank[String(f?.severity).toUpperCase()] || 0) > (rank[prev.severity] || 0)) {
        prev.severity = String(f.severity).toUpperCase();
      }
      if (tracesToNorthStar(f?.traces_to_north_star)) prev.traces = true;
      prev.seats.add(seatIdx);
      prev.agreement = prev.seats.size;
      if (f?.message) prev.messages.push(f.message);
      if (f?.fix) prev.fixes.push(f.fix);
      byTopic.set(key, prev);
    }
  });

  const findings = [...byTopic.values()].map((e) => {
    const demoted = !e.traces;
    const isBlocker = !demoted && (e.severity === 'BLOCKER' || (e.severity === 'MAJOR' && e.agreement >= 2));
    return {
      id: e.id,
      layer: e.layer,
      severity: e.severity,
      traces: e.traces,
      demoted,
      agreement: e.agreement,
      isBlocker,
      message: e.messages[0] || e.id,
      fix: e.fixes[0] || null,
    };
  });

  const blockers = findings.filter((f) => f.isBlocker);
  return {
    dry: blockers.length === 0,
    blockers,
    findings,
    layersCovered: [...layersCovered].sort(),
  };
}

/**
 * Execute the real 2-Stage `MATRIX-FAST-TRACK` pipeline (`6-9` bounded model calls).
 */
export async function runMatrixFastTrack({
  agent,
  intent,
  northStar = null,
  criteria = [],
  repoDir = null,
  outputDir = null,
  artifactsDir = null,
  title = 'Crucible Matrix-Fast-Track Project',
  testCommand = DEFAULT_TEST_COMMAND,
  band = 'MATRIX-FAST-TRACK',
  tier = 'Heavy',
  superjump = false,
  competingDesigns = 0,
  approved = false,
  pilotOverrideReason = null,
  addsSurface = false,
  propertyGates = {},
  triageLock = null,
  handoffTriage = null,
  wellFormedness = null,
  spawn = spawnSync,
  log = () => {},
} = {}) {
  const normalizedBand = normalizeBandDepth(band === 'SPIKE-FIRST' ? 'SPIKE-FIRST' : 'MATRIX-FAST-TRACK');
  const profile = resolveBandProfile('MATRIX-FAST-TRACK');
  const rawIntent = String(intent || northStar || '').trim();
  if (!rawIntent) {
    throw new HaltError('runMatrixFastTrack requires an intent or northStar', 'pass { intent } or { northStar }');
  }

  // --- Stage 0 (0 LLM calls for Anvil AST + testCommand preflight; 1 LLM call for framing) ---
  const preflight = validateTestCommandPreflight({ testCommand, repoDir, willEmitRunner: true });
  if (!preflight.ok) {
    throw haltForHuman(`Matrix-Fast-Track preflight failed: ${preflight.detail}`, 'matrix-test-command-preflight-failed');
  }
  const anvil = repoDir ? runAnvilBrownfieldIntake({ repoDir, spawn, log }) : null;

  const receipts = [];
  const baseAgent = async (prompt, opts = {}) => agent(prompt, {
    ...opts,
    onReceipt: async (r) => {
      if (r) receipts.push(r);
      if (typeof opts.onReceipt === 'function') await opts.onReceipt(r);
    },
  });
  const budgetedAgent = createCallBudgetedAgent(baseAgent, {
    maxCalls: MATRIX_MAX_MODEL_CALLS,
    bandName: 'MATRIX-FAST-TRACK',
  });

  const anvilContext = anvil?.ok && anvil.facts
    ? `Anvil Brownfield Facts (${anvil.source}, 0 LLM calls):\n${JSON.stringify({
        fileCount: anvil.facts.fileCount,
        files: (anvil.facts.files || []).slice(0, 30),
        symbols: (anvil.facts.symbols || []).slice(0, 30),
      })}`
    : '';

  // Call 1: Stage-0 North-Star & Scope Framing (runs even when northStar is seeded so criteria/competingDesigns are structured).
  const stage0Out = (await budgetedAgent(
    [
      'You are Crucible STAGE-0 Matrix-Fast-Track Intake.',
      'Lock a crisp, drift-proof North Star, <=5 testable criteria, explicit deferredScope (if any), and competingDesigns count.',
      northStar ? `Seed North Star (preserve intent): ${northStar}` : `User Intent: ${rawIntent}`,
      criteria.length ? `Seed Criteria: ${criteria.join(' · ')}` : '',
      anvilContext,
    ].filter(Boolean).join('\n\n'),
    { label: 'matrix:stage0-frame', role: 'synthesizer', schema: MATRIX_STAGE0_SCHEMA },
  )) || {};

  const lockedNorthStar = String(northStar || stage0Out.northStar || rawIntent).trim();
  const lockedCriteria = criteria.length
    ? [...criteria]
    : (Array.isArray(stage0Out.criteria) && stage0Out.criteria.length ? stage0Out.criteria : ['passes locate-plan.mjs and test suite']);
  const stage0Deferred = Array.isArray(stage0Out.deferredScope) ? stage0Out.deferredScope : [];
  const designCount = Math.max(Number(competingDesigns) || 0, Number(stage0Out.competingDesigns) || 0);

  // --- Stage 1: Optional Superjump + Plan+Waves Draft + L0-L5 Matrix + <=1 Delta Pass ---
  let superjumpResult = null;
  if (superjump || normalizedBand === 'SPIKE-FIRST' || designCount >= 2) {
    superjumpResult = (await budgetedAgent(
      [
        'You are Crucible Stage-1 Superjump Architectural Option Explorer.',
        'Generate >=2 genuinely distinct architectural options against the Fit Contract (North Star + criteria) and select the Deep-Module winner.',
        `North Star: ${lockedNorthStar}`,
        `Criteria: ${lockedCriteria.join(' · ')}`,
        anvilContext,
      ].filter(Boolean).join('\n\n'),
      { label: 'matrix:superjump-options', role: 'synthesizer', schema: SUPERJUMP_OPTIONS_SCHEMA },
    )) || null;
  }

  const preDetectedGates = detectPortfolioSkillGates({ intent: rawIntent, northStar: lockedNorthStar });

  // Unified Master Plan + Structured Waves Draft (1 call)
  const draftOut = (await budgetedAgent(
    [
      'You are Crucible Matrix-Fast-Track Unified Planner.',
      'Produce the shortest gold-standard wave plan serving ONLY the locked North Star.',
      'Rules:',
      '- Wave 1 MUST deliver a thin, runnable end-to-end user or CLI pilot slice (never pure internal plumbing/schemas across Waves 1-2).',
      '- Bound any LLM/model calls via explicit batching or concurrency caps (never unbounded per-item serial spawns).',
      '- Name at least one scope cut / simplification (`cutElement`) or state "nothing cut".',
      `North Star: ${lockedNorthStar}`,
      `Criteria: ${lockedCriteria.join(' · ')}`,
      superjumpResult?.selectedOption ? `Selected Superjump Architecture: ${superjumpResult.selectedOption} (${superjumpResult.rationale || ''})` : '',
      preDetectedGates.length ? `Required Portfolio Skill Gates: ${preDetectedGates.map((g) => g.skill).join(', ')}` : '',
      anvilContext,
    ].filter(Boolean).join('\n\n'),
    { label: 'matrix:draft', role: 'synthesizer', schema: MATRIX_DRAFT_SCHEMA },
  )) || {};

  let waves = normalizeWaves(Array.isArray(draftOut.waves) ? draftOut.waves : []);
  let deferredScope = [
    ...stage0Deferred,
    ...(Array.isArray(draftOut.deferredScope) ? draftOut.deferredScope : []),
  ];
  const cutElement = draftOut.cutElement ? String(draftOut.cutElement).trim() : null;
  const planTitle = String(draftOut.title || title).trim();
  const planSummary = String(draftOut.summary || '').trim();

  // Attach disjoint sub-waves + portfolio skill gates BEFORE L0-L5 matrix review so reviewers inspect the real plan.
  waves = waves.map((w) => ({ ...w, subWaves: partitionDisjointSubWaves(w, w.n) }));
  const detectedGates = detectPortfolioSkillGates({ intent: rawIntent, northStar: lockedNorthStar, waves });
  waves = attachPortfolioSkillGates(waves, detectedGates);
  let renderedPlan = renderImplementationPlan({
    title: planTitle,
    northStar: lockedNorthStar,
    criteria: lockedCriteria,
    waves,
    testCommand: preflight.command,
  });

  // Cross-family L0-L5 6-Layer Adversarial Matrix (3 focused seats in parallel)
  const matrixReviews = await Promise.all(
    MATRIX_SEATS.map((seat) =>
      budgetedAgent(
        [
          `You are Crucible L0-L5 Adversarial Matrix Seat ${seat.id} (${seat.layers.join(' + ')}).`,
          `Focus: ${seat.focus}`,
          `North Star: ${lockedNorthStar}`,
          `Criteria: ${lockedCriteria.join(' · ')}`,
          `=== CANDIDATE IMPLEMENTATION PLAN ===\n${renderedPlan}\n=== END PLAN ===`,
          'Return JSON { layersChecked, findings[] } where traces_to_north_star is true/false (or explanation string).',
        ].join('\n\n'),
        { label: seat.label, role: 'shark', schema: MATRIX_CELL_REVIEW_SCHEMA },
      ),
    ),
  );

  const matrixTally = tallyMatrixReviews(matrixReviews);
  let revised = false;
  let deltaVerification = null;

  // ELEGANCE.md Rule 5: ONE dry matrix pass stops immediately (0 delta calls!).
  // Only when >=1 blocker exists do we run 1 targeted patch + 1 120s delta-only verification pass.
  if (!matrixTally.dry) {
    const revOut = (await budgetedAgent(
      [
        'You are Crucible Matrix-Fast-Track Targeted Reviser.',
        'Patch ONLY the blocking L0-L5 matrix findings below while preserving all contiguous waves and North Star fidelity.',
        `North Star: ${lockedNorthStar}`,
        `Blocking Findings:\n${matrixTally.blockers.map((b, i) => `(${i + 1}) [${b.layer}/${b.severity}] ${b.message}${b.fix ? ` -> Fix: ${b.fix}` : ''}`).join('\n')}`,
        `Current Waves JSON:\n${JSON.stringify(waves, null, 2)}`,
      ].join('\n\n'),
      { label: 'matrix:revise', role: 'synthesizer', schema: MATRIX_DRAFT_SCHEMA },
    )) || {};

    if (typeof revOut.testCommand === 'string' && revOut.testCommand.trim()) {
      const candPf = validateTestCommandPreflight({ testCommand: revOut.testCommand.trim(), repoDir, willEmitRunner: true });
      if (candPf.ok) preflight.command = candPf.command;
    }
    if (Array.isArray(revOut.waves) && revOut.waves.length) {
      waves = normalizeWaves(revOut.waves);
      waves = waves.map((w) => ({ ...w, subWaves: partitionDisjointSubWaves(w, w.n) }));
      const postGates = detectPortfolioSkillGates({ intent: rawIntent, northStar: lockedNorthStar, waves });
      waves = attachPortfolioSkillGates(waves, postGates);
      renderedPlan = renderImplementationPlan({
        title: planTitle,
        northStar: lockedNorthStar,
        criteria: lockedCriteria,
        waves,
        testCommand: preflight.command,
      });
      revised = true;
    }

    deltaVerification = (await budgetedAgent(
      [
        'You are Crucible Matrix-Fast-Track Delta Verifier (120s bounded delta-only pass).',
        'Verify ONLY whether the previously raised blocking findings are resolved in the patched plan.',
        `Patched Blockers:\n${matrixTally.blockers.map((b) => `- [${b.layer}] ${b.message}`).join('\n')}`,
        `=== PATCHED IMPLEMENTATION PLAN ===\n${renderedPlan}\n=== END PLAN ===`,
      ].join('\n\n'),
      {
        label: 'matrix:delta-verify',
        role: 'shark',
        timeoutMs: profile.deltaVerifyTimeoutMs || DELTA_VERIFY_TIMEOUT_MS,
        schema: MATRIX_DELTA_VERIFY_SCHEMA,
      },
    )) || { resolved: false, remainingBlockers: [] };

    if (deltaVerification.resolved === false && Array.isArray(deltaVerification.remainingBlockers) && deltaVerification.remainingBlockers.length > 0) {
      throw haltForHuman(
        `Matrix-Fast-Track delta verification still reports ${deltaVerification.remainingBlockers.length} unresolved blocker(s): ` +
          deltaVerification.remainingBlockers.map((b) => b.message).join('; '),
        'matrix-delta-unresolved-blockers',
      );
    }
  }

  // --- Stage 2: Deterministic Wave Serialization + Chekhov Guards + locate-plan.mjs (0 LLM calls!) ---
  const finalPortfolioGates = detectPortfolioSkillGates({
    intent: rawIntent,
    northStar: lockedNorthStar,
    plan: renderedPlan,
    waves,
  });

  const planPathHint = outputDir ? path.join(path.resolve(outputDir), 'IMPLEMENTATION-PLAN.md') : 'IMPLEMENTATION-PLAN.md';
  const gateBlock = formatPlainEnglishApprovalGate({
    goal: lockedNorthStar,
    recommendation: 'Approve and hand off to Foreman.',
    tradeOff: deferredScope.length ? 'Deferred items stay parked for a follow-up.' : 'Lean single-matrix pass trades multi-round Shark churn for speed.',
    deferredScope,
    eleganceCuts: cutElement ? [cutElement] : [],
    artifactPath: planPathHint,
    portfolioGates: finalPortfolioGates,
  });

  const chekhov = runChekhovPlanQualityLint({
    plan: renderedPlan,
    waves,
    intent: rawIntent,
    northStar: lockedNorthStar,
    deferredScope,
    eleganceCuts: cutElement ? [cutElement] : [],
    pilotOverrideReason,
    gateBlock,
  });

  if (!chekhov.pass) {
    throw haltForHuman(
      `Chekhov Plan-Quality Guard blocked Stage-2 serialization: ${chekhov.issues.join(' | ')}`,
      'chekhov-plan-quality-failed',
    );
  }

  const stateDir = artifactsDir
    ? path.resolve(artifactsDir)
    : (outputDir ? path.join(path.resolve(outputDir), '.crucible') : null);
  if (stateDir) {
    fs.mkdirSync(stateDir, { recursive: true });
    fs.writeFileSync(
      path.join(stateDir, 'matrix-fast-track.json'),
      JSON.stringify({
        band: 'MATRIX-FAST-TRACK',
        calls: budgetedAgent.count(),
        maxModelCalls: MATRIX_MAX_MODEL_CALLS,
        layersCovered: matrixTally.layersCovered,
        revised,
        deltaVerified: Boolean(deltaVerification?.resolved),
        portfolioGates: finalPortfolioGates.map((g) => g.skill),
        chekhovPass: chekhov.pass,
        ts: new Date().toISOString(),
      }, null, 2) + '\n',
      'utf8',
    );
  }

  if (!approved) {
    const halt = haltForHuman(gateBlock, 'implementation-plan-approval');
    halt.plan = renderedPlan;
    halt.waves = waves;
    halt.calls = budgetedAgent.count();
    halt.chekhov = chekhov;
    halt.matrixTally = matrixTally;
    throw halt;
  }

  let docTrio = null;
  let handoff = null;
  if (outputDir) {
    const description = renderDescriptionDoc({
      title: planTitle,
      northStar: lockedNorthStar,
      criteria: lockedCriteria,
      summary: planSummary,
    });
    const executionLog = renderExecutionLog({ title: planTitle, waveCount: waves.length });
    docTrio = writeDocTrio({
      outputDir,
      plan: renderedPlan,
      description,
      executionLog,
      depth: 'MATRIX-FAST-TRACK',
      tier,
      triageLock,
      handoffTriage,
      addsSurface,
      propertyGates,
      log,
    });
    const runGate = typeof wellFormedness === 'function' ? wellFormedness : runWellFormednessGate;
    handoff = runHandoffGate({ projectDir: docTrio.dir, artifactsDir: stateDir, runGate, log });
  }

  return {
    band: 'MATRIX-FAST-TRACK',
    bandStamp: bandProfileStamp(profile),
    northStar: lockedNorthStar,
    criteria: lockedCriteria,
    deferredScope,
    cutElement,
    preflight,
    anvil,
    superjump: superjumpResult,
    waves,
    plan: renderedPlan,
    matrixTally,
    revised,
    deltaVerification,
    chekhov,
    portfolioGates: finalPortfolioGates,
    gateBlock,
    calls: budgetedAgent.count(),
    maxModelCalls: MATRIX_MAX_MODEL_CALLS,
    callHistory: budgetedAgent.history(),
    receipts,
    docTrio,
    handoff,
  };
}

function isMain() {
  try {
    if (!process.argv[1]) return false;
    return fs.realpathSync(fileURLToPath(import.meta.url)) === fs.realpathSync(path.resolve(process.argv[1]));
  } catch {
    return false;
  }
}

if (isMain()) {
  const argv = process.argv.slice(2);
  const flag = (n) => {
    const i = argv.indexOf(n);
    return i >= 0 && i + 1 < argv.length ? argv[i + 1] : null;
  };
  const outDir = flag('--out') || flag('--output') || argv.find((a) => !a.startsWith('--'));
  const intent = flag('--intent') || flag('--task');
  const repoDir = flag('--repo') || flag('--project');
  const approved = argv.includes('--approve') || argv.includes('--approved');
  const isLite = (flag('--depth') || '').toUpperCase() === 'LITE' || argv.includes('--lite');

  if (!intent || !outDir) {
    process.stderr.write(
      'usage: node crucible/bin/matrix-fast-track.mjs <outDir> --intent "<goal>" [--repo <dir>] [--matrix-fast-track|--lite] [--superjump] [--approve]\n',
    );
    process.exit(2);
  }

  const { buildLiveCrucibleAgent } = await import('./enhanced.mjs');
  const built = await buildLiveCrucibleAgent({
    env: process.env,
    target: repoDir || process.cwd(),
    log: (s) => console.log(s),
  });

  try {
    if (isLite) {
      const res = await runLiteFastPath({
        agent: built.agent,
        task: intent,
        repoDir,
        outDir,
        families: built.families,
        log: (s) => console.log(s),
      });
      console.log(`LITE_PLAN ${res.files?.plan || outDir} (calls=${res.calls}/${LITE_MAX_MODEL_CALLS})`);
    } else {
      const res = await runMatrixFastTrack({
        agent: built.agent,
        intent,
        repoDir,
        outputDir: outDir,
        superjump: argv.includes('--superjump'),
        approved,
        log: (s) => console.log(s),
      });
      console.log(`MATRIX_PLAN ${res.docTrio?.files?.plan || outDir} (calls=${res.calls}/${MATRIX_MAX_MODEL_CALLS})`);
    }
    process.exit(0);
  } catch (e) {
    if (e && e.halt_for_human) {
      console.log(`GATE ${e.message}`);
      process.exit(3);
    }
    console.error(`matrix-fast-track failed: ${e?.message || e}`);
    process.exit(2);
  }
}

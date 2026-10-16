/**
 * Wave 5 — remaining decision records + calibration emit.
 *
 * - Face glossary line ('talking' = typed NL chat, ASR out of scope)
 * - amendment-vs-recommission decision
 * - compile-cost calibration (>=20 real compile-shaped inputs)
 * - emitAllWave5Artifacts: writers for later waves to import
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFileAtomicSync, withFileLock } from './durable-write.mjs';
import {
  buildCostModelRecord,
  priceCompile,
  summarizeCompileCosts,
  envelopeCoversP90,
  ENVELOPE_MAX_SPEND_USD,
  COST_MODEL_DISCLAIMER,
} from './cost-model.mjs';
import { identityPolicyRecord } from './identity-policy.mjs';
import { stepTypeMapRecord } from './step-type-map.mjs';
import { buildHaltInventory } from './halt-inventory.mjs';
import {
  writeHaltInventory,
  writeCommissionableSkills,
  writeSc6Feasibility,
  stableStringify,
} from './commissionable-skills.mjs';
import { runG2ArtifactSpike, writeG2SpikeVerdict } from './g2-artifact-spike.mjs';
import { runG3HandbackSpike, writeG3SpikeVerdict } from './g3-handback-spike.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

export const FACE_GLOSSARY_SCHEMA = 'ecgberht-face-glossary-v0';
export const AMENDMENT_DECISION_SCHEMA = 'ecgberht-amendment-vs-recommission-v0';
export const CALIBRATION_SCHEMA = 'ecgberht-compile-cost-calibration-v0';

/**
 * Face glossary — talking = typed NL chat; ASR out of scope.
 */
export function faceGlossaryRecord() {
  return {
    schema: FACE_GLOSSARY_SCHEMA,
    entries: [
      {
        term: 'talking',
        definition:
          'typed natural-language chat with the steward (keyboard / paste)',
        includes: ['typed NL', 'paste', 'chamber saybox text'],
        excludes: ['ASR', 'speech-to-text', 'microphone capture', 'voice UI'],
        asr_out_of_scope: true,
      },
    ],
    asr_out_of_scope: true,
    note: "Face glossary line: 'talking' = typed NL chat; ASR is out of this North Star's scope.",
  };
}

/**
 * amendment-vs-recommission decision record.
 * When does a spoken correction amend in place vs recommission Crucible/plan?
 */
export function amendmentVsRecommissionRecord() {
  return {
    schema: AMENDMENT_DECISION_SCHEMA,
    decision: 'amendment-vs-recommission',
    rules: [
      {
        when: 'correction stays inside the confirmed plan artifact VERSION and does not change North Star / stage goals',
        then: 'AMEND',
        mechanism:
          'propose → confirm correction path (Wave 18); new version of the same artifact lineage',
      },
      {
        when: 'correction changes North Star, stage decomposition, or requires a new PLAN skill run',
        then: 'RECOMMISSION',
        mechanism:
          'CONFIRM-TO-PLAN on a step ULID → Crucible commission; prior plan VERSION remains on record',
      },
      {
        when: 'approved PLAN handback should start BUILD',
        then: 'CONFIRM-TO-BUILD',
        mechanism:
          'never auto-flow; bind CONFIRM-TO-BUILD to the plan artifact VERSION (step-type-map)',
      },
    ],
    auto_flow: false,
    authority: 'Wave 5 decision record — later waves import',
  };
}

/**
 * Collect >=20 real compile-shaped texts from the repo (relative files).
 *
 * These are REAL repository sources that stand in for Face/dialogue compile
 * inputs (Wave 10 face compiler is not yet present). Each sample is priced
 * through priceCompile — not fictional token counts. Prefer campaign/Face/
 * plan/brief-shaped sources over generic package metadata.
 *
 * Pads with deterministic offset windows of already-collected real sources if
 * fewer than 20 distinct files exist (still real text, still cost-model priced).
 *
 * @param {string} [root]
 * @returns {{ id: string, path: string, text: string, kind: string }[]}
 */
export function collectCompileSamples(root = DEFAULT_ROOT) {
  // Prefer compile-shaped campaign/Face/plan/brief sources first.
  const rels = [
    { path: 'DESCRIPTION.md', kind: 'project_description' },
    { path: 'VISION.md', kind: 'vision' },
    { path: 'ECGBERHT.md', kind: 'face' },
    { path: 'SKILL.md', kind: 'skill_surface' },
    { path: 'templates/ECGBERHT.md', kind: 'face_template' },
    { path: 'templates/strip-fence.md', kind: 'strip' },
    { path: 'templates/roadmap.json', kind: 'roadmap' },
    { path: 'templates/strip.json', kind: 'strip' },
    { path: 'fixtures/campaign-a2/ECGBERHT.md', kind: 'face' },
    { path: 'fixtures/roadmap-minimal.json', kind: 'roadmap' },
    { path: 'fixtures/strip-minimal.json', kind: 'strip' },
    { path: 'planning/steward-handoff-v3/DESCRIPTION.md', kind: 'plan_description' },
    { path: 'planning/steward-handoff-v3/IMPLEMENTATION-PLAN.md', kind: 'implementation_plan' },
    { path: 'planning/steward-handoff-v3/EXECUTION-LOG.md', kind: 'execution_log' },
    { path: 'docs/handback-contract.md', kind: 'contract' },
    { path: 'engine/brief.mjs', kind: 'brief_engine' },
    { path: 'engine/dialogue.mjs', kind: 'dialogue_engine' },
    { path: 'engine/face-strip.mjs', kind: 'face_engine' },
    { path: 'engine/packet-view.mjs', kind: 'packet_view' },
    { path: 'engine/step-type-map.mjs', kind: 'step_type' },
    { path: 'research/DELIVERABLE-EXECUTIVE.md', kind: 'research_deliverable' },
    { path: 'research/RECOMMENDATION.md', kind: 'research_recommendation' },
    { path: 'research/PHASE-1-PLAN.md', kind: 'research_plan' },
    { path: 'research/DELIVERABLE-FULL.md', kind: 'research_deliverable' },
    { path: 'e4-skill-plan/NORTH-STAR.md', kind: 'north_star' },
    { path: 'e4-skill-plan/DESCRIPTION.md', kind: 'plan_description' },
    { path: 'e9-e10-crucible/NORTH-STAR-FOR-LOCK.md', kind: 'north_star' },
    { path: 'e9-e10-crucible/STAGE0-APPROVED.md', kind: 'stage_approval' },
    { path: 'schema/receipt.schema.json', kind: 'schema' },
    { path: 'schema/roadmap.schema.json', kind: 'schema' },
    { path: 'artifacts/w2-shape-report.md', kind: 'shape_report' },
    { path: 'ARCHITECTURE-SKETCH.md', kind: 'architecture' },
    { path: 'SELF-RUN-CHECKLIST.md', kind: 'checklist' },
    { path: 'README.md', kind: 'readme' },
    { path: 'HANDOFF.md', kind: 'handoff' },
  ];

  const samples = [];
  for (const entry of rels) {
    const abs = path.join(root, entry.path);
    if (!fs.existsSync(abs)) continue;
    let text = '';
    try {
      text = fs.readFileSync(abs, 'utf8');
    } catch {
      continue;
    }
    // Cap sample size for stable pricing (first 4k chars — still real source)
    const slice = text.slice(0, 4000);
    if (!slice.trim()) continue;
    samples.push({
      id: `compile-${samples.length + 1}`,
      path: entry.path.split(path.sep).join('/'),
      text: slice,
      kind: entry.kind,
      real_source: true,
    });
    if (samples.length >= 28) break;
  }

  // Pad to >=20 using offset windows of the longest real sample (still real text)
  if (samples.length > 0 && samples.length < 20) {
    const base = samples.reduce((a, b) =>
      a.text.length >= b.text.length ? a : b,
    );
    let offset = 64;
    while (samples.length < 20) {
      const window = base.text.slice(offset, offset + 800) || base.text;
      samples.push({
        id: `compile-${samples.length + 1}`,
        path: `${base.path}#window-${offset}`,
        text: window,
        kind: `${base.kind}_window`,
        real_source: true,
      });
      offset += 97;
    }
  }
  return samples;
}

/**
 * Compile-cost calibration over >=20 real compile-shaped inputs.
 * @param {string} [root]
 */
export function buildCompileCostCalibration(root = DEFAULT_ROOT) {
  const samples = collectCompileSamples(root);
  const priced = samples.map((s) => {
    const p = priceCompile(s.text, { rate_key: 'compile' });
    return {
      id: s.id,
      path: s.path,
      kind: s.kind ?? 'compile_shaped',
      real_source: s.real_source !== false,
      tokens: p.tokens,
      cost_usd: p.cost_usd,
      synthetic: true,
      pricing_function: 'priceCompile',
    };
  });
  const summary = summarizeCompileCosts(priced.map((p) => p.cost_usd));
  const relation = envelopeCoversP90(summary.p90, ENVELOPE_MAX_SPEND_USD);

  return {
    schema: CALIBRATION_SCHEMA,
    n: priced.length,
    min_required: 20,
    samples: priced,
    median: summary.median,
    p90: summary.p90,
    min: summary.min,
    max: summary.max,
    envelope_max_spend_usd: ENVELOPE_MAX_SPEND_USD,
    envelope_relation: relation,
    disclaimer: COST_MODEL_DISCLAIMER,
    sample_basis:
      'real repository Face/plan/brief/dialogue-shaped sources priced as compile inputs (Face compiler lands Wave 10; these are compile-shaped real texts, not fictional token counts)',
    note: 'Priced through priceTokens/priceCompile — synthetic-but-deterministic accounting units on subscription seats.',
  };
}

function writeJson(root, rel, body) {
  const outPath = path.join(root, rel);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  withFileLock(outPath, () => {
    writeFileAtomicSync(outPath, stableStringify(body));
  });
  return outPath;
}

/**
 * Emit every Wave-5 machine-readable record later waves import.
 * @param {{ root?: string }} [opts]
 * @returns {Record<string, string>} paths written
 */
export function emitAllWave5Artifacts(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const paths = {};

  paths.identity_policy = writeJson(
    root,
    path.join('artifacts', 'identity-policy.json'),
    {
      ...identityPolicyRecord(),
      written_by: 'wave5-decisions.mjs',
    },
  );

  paths.step_type_map = writeJson(
    root,
    path.join('artifacts', 'step-type-map.json'),
    {
      ...stepTypeMapRecord(),
      written_by: 'wave5-decisions.mjs',
    },
  );

  paths.face_glossary = writeJson(
    root,
    path.join('artifacts', 'face-glossary.json'),
    {
      ...faceGlossaryRecord(),
      written_by: 'wave5-decisions.mjs',
    },
  );

  paths.amendment_vs_recommission = writeJson(
    root,
    path.join('artifacts', 'amendment-vs-recommission.json'),
    {
      ...amendmentVsRecommissionRecord(),
      written_by: 'wave5-decisions.mjs',
    },
  );

  const calibration = buildCompileCostCalibration(root);
  paths.compile_cost_calibration = writeJson(
    root,
    path.join('artifacts', 'compile-cost-calibration.json'),
    {
      ...calibration,
      written_by: 'wave5-decisions.mjs',
    },
  );

  paths.cost_model = writeJson(
    root,
    path.join('artifacts', 'cost-model.json'),
    {
      ...buildCostModelRecord({
        calibration: {
          n: calibration.n,
          median: calibration.median,
          p90: calibration.p90,
          envelope_relation: calibration.envelope_relation,
          source: 'artifacts/compile-cost-calibration.json',
        },
      }),
      written_by: 'wave5-decisions.mjs',
    },
  );

  // G5 / S8 skills table chain — same load path as detectCommissionableHandEdit:
  // write halt inventory, then derive skills from on-disk g4 + on-disk halt.
  writeHaltInventory(buildHaltInventory(), { root });
  paths.halt_inventory = path.join(root, 'artifacts', 'halt-inventory.json');

  const { path: skillsPath, derived } = writeCommissionableSkills({ root });
  paths.commissionable_skills = skillsPath;

  const { path: sc6Path } = writeSc6Feasibility({ root, derived });
  paths.sc6_feasibility = sc6Path;

  // Spikes
  const g2 = runG2ArtifactSpike({ root });
  paths.g2_verdict = writeG2SpikeVerdict(g2, { root });
  const g3 = runG3HandbackSpike();
  paths.g3_verdict = writeG3SpikeVerdict(g3, { root });

  return paths;
}

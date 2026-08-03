// Generated triage prose blocks (NS-01 / Wave 6).
//
// ONE template → per-skill markdown blocks. Prose hosts stamp
// runtime_enforced:false honestly; engine hosts stamp true and point at the
// shared lock entry point. regenerate-and-diff CI keeps wording from drifting.
//
// Markers (machine-stable for stamp/diff):
//   <!-- BEGIN NS01-TRIAGE-BLOCK --> … <!-- END NS01-TRIAGE-BLOCK -->

import {
  DEPTH_BAND_VALUES,
  MODEL_TIER_VALUES,
  NS01_WAVE1_STAMP,
} from './core.mjs';
import { knobsForSkill } from './mapping.mjs';
import {
  ALL_SKILLS,
  NS01_WAVE6_STAMP,
  SKILLS_MANIFEST,
  WAVE6_BLOCK_SKILLS,
  getSkillManifestEntry,
} from './skills-manifest.mjs';

/** Stable fence markers for stamp / grep / regenerate-and-diff. */
export const TRIAGE_BLOCK_BEGIN = '<!-- BEGIN NS01-TRIAGE-BLOCK -->';
export const TRIAGE_BLOCK_END = '<!-- END NS01-TRIAGE-BLOCK -->';

/**
 * Machine-readable triage contract embedded in every generated block.
 * @param {string} skillId
 * @returns {Readonly<object>}
 */
export function buildTriageBlockPayload(skillId) {
  const entry = getSkillManifestEntry(skillId);
  if (!entry) {
    throw new Error(`unknown skill for triage block: ${skillId}`);
  }
  const fullKnobs = knobsForSkill(skillId, 'FULL');
  const liteKnobs = knobsForSkill(skillId, 'LITE');
  const spikeKnobs = knobsForSkill(skillId, 'SPIKE');
  return Object.freeze({
    schema: 'ns01-triage-block/v1',
    stamp: NS01_WAVE6_STAMP,
    coreStamp: NS01_WAVE1_STAMP,
    skill: entry.id,
    intakeClass: entry.intakeClass,
    runtime_enforced: entry.runtimeEnforced,
    axes: Object.freeze({
      tier: MODEL_TIER_VALUES.slice(),
      depth: DEPTH_BAND_VALUES.slice(),
    }),
    triageSurface: entry.triageSurface,
    sourceModule: '@foundry/triage',
    singleSource: true,
    knobsByDepth: Object.freeze({
      FULL: fullKnobs,
      LITE: liteKnobs,
      SPIKE: spikeKnobs,
    }),
    notes: entry.notes,
  });
}

/**
 * Render the human-facing + machine-readable triage block for one skill.
 * @param {string} skillId
 * @returns {string}
 */
export function renderTriageBlock(skillId) {
  const entry = getSkillManifestEntry(skillId);
  if (!entry) {
    throw new Error(`unknown skill for triage block: ${skillId}`);
  }
  const payload = buildTriageBlockPayload(skillId);
  const runtimeLine = entry.runtimeEnforced
    ? '**Runtime enforcement:** `runtime_enforced: true` — no dimension may be acted on without a validating lock (`getLockedBand` / skill entry point). Unlocked headless → HALT.'
    : '**Runtime enforcement:** `runtime_enforced: false` (honest) — pure prose host; the model must still emit both axes + rationale first and treat lock confirmation as mandatory ceremony. CI contracts this block; there is no hard Node gate on this skill until its NS engine ships.';

  const lockLine = entry.intakeClass === 'engine'
    ? `**Authoritative surface:** \`${entry.triageSurface}\` (shared \`@foundry/triage\` — never a second hand-rolled rubric).`
    : `**Authoritative surface:** this generated block (prose) + shared \`@foundry/triage\` vocabulary. Engine path: ${entry.notes}.`;

  const body = [
    TRIAGE_BLOCK_BEGIN,
    '',
    `## NS-01 triage (generated · ${entry.id})`,
    '',
    'Open every run with the **shared two-dimension triage** from `@foundry/triage`:',
    '',
    `- **Model tier:** \`${MODEL_TIER_VALUES.join('` | `')}\``,
    `- **Process depth:** \`${DEPTH_BAND_VALUES.join('` | `')}\``,
    '- Plus a written **rationale** for both.',
    '',
    runtimeLine,
    '',
    lockLine,
    '',
    'Emit a fenced JSON object **first** (before substantive work) matching the schema below.',
    'Do **not** invent a second Heavy/Standard × FULL/LITE/SPIKE rubric — recommend via the shared core, lock via the skill entry path.',
    '',
    '```json',
    JSON.stringify(
      {
        skill: entry.id,
        tier: '<Heavy|Standard>',
        depth: '<FULL|LITE|SPIKE>',
        rationale: '<why both axes>',
        runtime_enforced: entry.runtimeEnforced,
        stamp: NS01_WAVE6_STAMP,
      },
      null,
      2,
    ),
    '```',
    '',
    '<details><summary>Machine payload (regenerate-and-diff)</summary>',
    '',
    '```json',
    JSON.stringify(payload, null, 2),
    '```',
    '',
    '</details>',
    '',
    TRIAGE_BLOCK_END,
    '',
  ].join('\n');

  return body;
}

/**
 * Render blocks for every Wave-6 target skill (or all 11 when `all`).
 * @param {{ all?: boolean }} [opts]
 * @returns {Readonly<Record<string, string>>}
 */
export function renderAllTriageBlocks(opts = {}) {
  const ids = opts.all ? ALL_SKILLS : WAVE6_BLOCK_SKILLS;
  /** @type {Record<string, string>} */
  const out = {};
  for (const id of ids) {
    out[id] = renderTriageBlock(id);
  }
  return Object.freeze(out);
}

/**
 * Filename for a committed generated block.
 * @param {string} skillId
 * @returns {string}
 */
export function generatedBlockFileName(skillId) {
  const safe = String(skillId).replace(/[^a-zA-Z0-9._-]+/g, '-');
  return `${safe}.triage-block.md`;
}

/**
 * Full generated file body (header + block) for regenerate-and-diff.
 * @param {string} skillId
 * @returns {string}
 */
export function renderGeneratedFile(skillId) {
  const entry = getSkillManifestEntry(skillId);
  if (!entry) throw new Error(`unknown skill: ${skillId}`);
  return [
    `<!-- AUTO-GENERATED by @foundry/triage prose-block.mjs — do not hand-edit. -->`,
    `<!-- Stamp: ${NS01_WAVE6_STAMP} · skill: ${entry.id} · intakeClass: ${entry.intakeClass} -->`,
    `<!-- Regenerate: node scripts/regenerate-prose-blocks.mjs -->`,
    '',
    renderTriageBlock(skillId),
  ].join('\n');
}

/**
 * Normalize text for regenerate-and-diff (LF only).
 * @param {string} text
 * @returns {string}
 */
export function normalizeGeneratedText(text) {
  return String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

/**
 * Diff expected generated content vs disk content.
 * @param {string} expected
 * @param {string} actual
 * @returns {{ match: boolean, detail: string }}
 */
export function diffGenerated(expected, actual) {
  const a = normalizeGeneratedText(expected);
  const b = normalizeGeneratedText(actual);
  if (a === b) return { match: true, detail: 'identical' };
  return {
    match: false,
    detail: `length expected=${a.length} actual=${b.length}; first mismatch at index ${firstMismatch(a, b)}`,
  };
}

function firstMismatch(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    if (a[i] !== b[i]) return i;
  }
  return n;
}

export {
  ALL_SKILLS,
  NS01_WAVE6_STAMP,
  SKILLS_MANIFEST,
  WAVE6_BLOCK_SKILLS,
};

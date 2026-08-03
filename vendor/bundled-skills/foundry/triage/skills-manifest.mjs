// Skills manifest — all 11 NS-01 trio+foundry skills (Wave 6).
//
// Single edit point for skill-id → intake class + paths + triage surface.
// Intake class drives the uniform intake invariant:
//   · engine  → runtime lock path is authoritative; generated SKILL stanza defers to engine
//   · prose   → generated triage block + CI contract; honest runtime_enforced:false
//
// Paths are best-effort pins (host may have skill under ~/.claude/skills or
// Skill Foundry/skills). Manifest resolution is soft for path existence; the
// hard contract is that all 11 ids are listed and mapped.

import { MAPPED_SKILLS } from './mapping.mjs';

/** Wave-6 surface stamp. */
export const NS01_WAVE6_STAMP = 'ns01-w6-remaining-skills-prose';

/** Canonical ordered list of the 11 skills (must match North Star manifest). */
export const ALL_SKILLS = Object.freeze([
  'crucible',
  'foreman',
  'researchPrime',
  'gandalf',
  'jumper',
  'ramanujan',
  'tidy-idy',
  'zombie-hunter',
  'literature-review',
  'financial-analyst',
  'legal-beagle',
]);

/**
 * @typedef {'engine' | 'prose'} IntakeClass
 *
 * @typedef {{
 *   id: string,
 *   intakeClass: IntakeClass,
 *   runtimeEnforced: boolean,
 *   triageSurface: string,
 *   skillMdHint: string,
 *   notes: string,
 * }} SkillManifestEntry
 */

/**
 * Per-skill intake contract.
 * Pure-prose hosts (no hard runtime gate for bands) stamp runtime_enforced:false.
 * Engine hosts use the shared lock path and stamp runtime_enforced:true.
 *
 * @type {Readonly<Record<string, Readonly<SkillManifestEntry>>>}
 */
export const SKILLS_MANIFEST = Object.freeze({
  crucible: Object.freeze({
    id: 'crucible',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'crucible-wire.mjs / Stage-0 assessComplexity',
    skillMdHint: 'defer-to-engine',
    notes: 'Stage-0 calls shared recommend + lock; handoff emits both axes',
  }),
  foreman: Object.freeze({
    id: 'foreman',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'foreman-wire.mjs inherit only',
    skillMdHint: 'defer-to-engine',
    notes: 'Inherits triage_track / triage; never re-triages',
  }),
  researchPrime: Object.freeze({
    id: 'researchPrime',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'researchprime-wire.mjs intake extension only',
    skillMdHint: 'defer-to-engine',
    notes: 'governance.mjs byte-unchanged; triage only via intake extension',
  }),
  gandalf: Object.freeze({
    id: 'gandalf',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'entry-points.mjs + gandalfKnobs',
    skillMdHint: 'generated-block+entry',
    notes: 'Map-reduce advisor; entry recommends both axes; lock before work',
  }),
  jumper: Object.freeze({
    id: 'jumper',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'entry-points.mjs + jumperKnobs',
    skillMdHint: 'generated-block+entry',
    notes: 'Ideation engine; composes Gandalf at matching tier',
  }),
  ramanujan: Object.freeze({
    id: 'ramanujan',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'entry-points.mjs + ramanujanKnobs',
    skillMdHint: 'generated-block+entry',
    notes:
      'Math partner; honesty law + optional certifier arm. LITE = direct answer + honesty labels (full-strength; not a ceremony knob), certifier off, fewer verify arms; FULL/SPIKE may arm certifier per mapping; labels never thinned by depth',
  }),
  'tidy-idy': Object.freeze({
    id: 'tidy-idy',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'entry-points.mjs + tidyIdyKnobs',
    skillMdHint: 'generated-block+entry',
    notes: 'Repo hygiene; git-required; RETAIN fail-safe',
  }),
  'zombie-hunter': Object.freeze({
    id: 'zombie-hunter',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'entry-points.mjs + zombieHunterKnobs',
    skillMdHint: 'generated-block+entry',
    notes: 'Orphan reaper; abstain-by-default safety gate',
  }),
  'literature-review': Object.freeze({
    id: 'literature-review',
    intakeClass: 'engine',
    runtimeEnforced: true,
    triageSurface: 'entry-points.mjs + literatureReviewKnobs',
    skillMdHint: 'generated-block+entry',
    notes: 'Composes researchPrime; snowball + PRISMA discipline',
  }),
  'financial-analyst': Object.freeze({
    id: 'financial-analyst',
    intakeClass: 'prose',
    runtimeEnforced: false,
    triageSurface: 'generated prose block (NS-03 engine out of scope)',
    skillMdHint: 'generated-prose-block',
    notes: 'Honest runtime_enforced:false until NS-03; knobs = ceremony',
  }),
  'legal-beagle': Object.freeze({
    id: 'legal-beagle',
    intakeClass: 'prose',
    runtimeEnforced: false,
    triageSurface: 'generated prose block (NS-02 engine out of scope)',
    skillMdHint: 'generated-prose-block',
    notes: 'Honest runtime_enforced:false until NS-02; knobs = ceremony',
  }),
});

/**
 * Skills that receive a generated prose / entry triage block under Wave 6
 * (the remaining 8 after trio wiring in waves 3–5).
 */
export const WAVE6_BLOCK_SKILLS = Object.freeze([
  'gandalf',
  'jumper',
  'ramanujan',
  'tidy-idy',
  'zombie-hunter',
  'literature-review',
  'financial-analyst',
  'legal-beagle',
]);

/**
 * @param {unknown} skillId
 * @returns {Readonly<SkillManifestEntry> | null}
 */
export function getSkillManifestEntry(skillId) {
  if (typeof skillId !== 'string' || !skillId.trim()) return null;
  const direct = SKILLS_MANIFEST[skillId];
  if (direct) return direct;
  // light alias tolerance
  const key = skillId.trim().toLowerCase().replace(/_/g, '-');
  if (key === 'researchprime' || key === 'research-prime') return SKILLS_MANIFEST.researchPrime;
  if (key === 'tidyidy' || key === 'tidy') return SKILLS_MANIFEST['tidy-idy'];
  if (key === 'zombiehunter' || key === 'zombie') return SKILLS_MANIFEST['zombie-hunter'];
  if (key === 'literaturereview' || key === 'lit-review') {
    return SKILLS_MANIFEST['literature-review'];
  }
  if (key === 'financialanalyst' || key === 'fin-analyst') {
    return SKILLS_MANIFEST['financial-analyst'];
  }
  if (key === 'legalbeagle' || key === 'legal') return SKILLS_MANIFEST['legal-beagle'];
  return SKILLS_MANIFEST[key] ?? null;
}

/**
 * True when every NS-01 skill is listed, mapped, and classified.
 * @returns {{ ok: boolean, missing: string[] }}
 */
export function assertManifestComplete() {
  const missing = [];
  for (const id of ALL_SKILLS) {
    if (!SKILLS_MANIFEST[id]) missing.push(`manifest:${id}`);
    if (!MAPPED_SKILLS.includes(id)) missing.push(`mapped:${id}`);
  }
  if (ALL_SKILLS.length !== 11) missing.push(`count:${ALL_SKILLS.length}`);
  if (MAPPED_SKILLS.length !== 11) missing.push(`mappedCount:${MAPPED_SKILLS.length}`);
  return { ok: missing.length === 0, missing };
}

/**
 * Skills whose generated block must stamp runtime_enforced:false.
 * @returns {string[]}
 */
export function proseSkillIds() {
  return ALL_SKILLS.filter((id) => SKILLS_MANIFEST[id].intakeClass === 'prose');
}

/**
 * Skills with hard runtime lock enforcement.
 * @returns {string[]}
 */
export function engineSkillIds() {
  return ALL_SKILLS.filter((id) => SKILLS_MANIFEST[id].intakeClass === 'engine');
}

export { MAPPED_SKILLS };

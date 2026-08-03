// Unified skill entry points for NS-01 triage (Wave 6).
//
// Every one of the 11 skills can:
//   1. recommend both axes + rationale via the shared core (no second rubric)
//   2. resolve a validating lock (engine: hard fail-closed; prose: same API with
//      honest runtime_enforced:false stamped on the contract)
//   3. read band knobs only after a lock is present
//
// Trio live wires remain in crucible-wire / foreman-wire / researchprime-wire;
// this module is the uniform entry for the remaining skills and a single
// front-door for hosts that want skill-id → triage without per-skill forks.

import { recommend } from './core.mjs';
import {
  createLockRecord,
  getLockedBand,
  lockFromHeadless,
  lockFromInteractive,
} from './lock.mjs';
import { knobsForSkill, normalizeMappedSkill } from './mapping.mjs';
import {
  ALL_SKILLS,
  NS01_WAVE6_STAMP,
  SKILLS_MANIFEST,
  getSkillManifestEntry,
} from './skills-manifest.mjs';
import { buildTriageBlockPayload, renderTriageBlock } from './prose-block.mjs';

export { NS01_WAVE6_STAMP, ALL_SKILLS };

/**
 * Entry-point contract for one skill (recommendation + enforcement honesty).
 * @param {unknown} skill
 * @param {object} [intake]
 * @returns {Readonly<object>}
 */
export function entryPointContract(skill, intake = {}) {
  const entry = getSkillManifestEntry(skill);
  if (!entry) {
    const err = new Error(`unknown skill for entry point: ${skill}`);
    err.code = 'TRIAGE_UNKNOWN_SKILL';
    throw err;
  }
  const skillId = entry.id;
  const bag = intake && typeof intake === 'object' ? { ...intake } : {};
  if (!bag.skill) bag.skill = skillId;
  const recommendation = recommend(bag);
  const knobs = knobsForSkill(skillId, recommendation.depth, recommendation.tier);
  return Object.freeze({
    skill: skillId,
    stamp: NS01_WAVE6_STAMP,
    intakeClass: entry.intakeClass,
    runtime_enforced: entry.runtimeEnforced,
    triageSurface: entry.triageSurface,
    recommendation: Object.freeze({
      tier: recommendation.tier,
      depth: recommendation.depth,
      rationale: recommendation.rationale,
      defaulted: !!recommendation.defaulted,
    }),
    knobs,
    // No lock yet — callers must resolveSkillLock before acting on knobs as locked.
    locked: false,
  });
}

/**
 * Recommend both axes for a skill (advisory only).
 * @param {unknown} skill
 * @param {object} [intake]
 * @returns {ReturnType<typeof recommend>}
 */
export function recommendForSkill(skill, intake = {}) {
  const entry = getSkillManifestEntry(skill);
  if (!entry) {
    const err = new Error(`unknown skill for recommend: ${skill}`);
    err.code = 'TRIAGE_UNKNOWN_SKILL';
    throw err;
  }
  const bag = intake && typeof intake === 'object' ? { ...intake, skill: entry.id } : { skill: entry.id };
  return recommend(bag);
}

/**
 * Resolve a validating lock for any manifest skill, or throw.
 *
 * Precedence mirrors researchPrime / Stage-0:
 *   1. explicit triageLock / lock
 *   2. headless config / inherit
 *   3. interactive confirm / edit
 *   4. decision: 'confirm' on advisory recommendation
 *
 * Prose hosts use the same API so tests can prove "no path sets a dimension
 * without a recorded lock"; they stamp runtime_enforced:false on the contract.
 *
 * @param {unknown} skill
 * @param {object} [args]
 * @returns {{
 *   lock: Readonly<object>,
 *   band: ReturnType<typeof getLockedBand>,
 *   knobs: Readonly<object>,
 *   recommendation: object,
 *   contract: Readonly<object>,
 * }}
 */
export function resolveSkillLock(skill, args = {}) {
  const entry = getSkillManifestEntry(skill);
  if (!entry) {
    const err = new Error(`unknown skill for lock resolve: ${skill}`);
    err.code = 'TRIAGE_UNKNOWN_SKILL';
    throw err;
  }
  const skillId = entry.id;
  const a = args && typeof args === 'object' ? args : {};
  const inputs = a.inputs && typeof a.inputs === 'object' ? a.inputs : a.intake || {};
  const recommendation =
    a.recommendation && typeof a.recommendation === 'object'
      ? a.recommendation
      : recommendForSkill(skillId, inputs);

  const explicit = a.triageLock ?? a.lock ?? null;
  if (explicit != null) {
    const band = getLockedBand(explicit);
    const lock = createLockRecord({
      tier: band.tier,
      depth: band.depth,
      rationale: band.rationale,
      source: band.source,
      lockedAt: band.lockedAt,
    });
    const knobs = knobsForSkill(skillId, lock.depth, lock.tier);
    return finalize(entry, lock, recommendation, knobs);
  }

  if (a.headless === true) {
    const lock = lockFromHeadless({
      config: a.triageConfig ?? a.config ?? null,
      inherit: a.triageInherit ?? a.inherit ?? null,
    });
    const knobs = knobsForSkill(skillId, lock.depth, lock.tier);
    return finalize(entry, lock, recommendation, knobs);
  }

  if (a.decision === 'confirm' || a.confirmedDepth || a.depth || a.confirmedTier || a.tier) {
    const depth = a.confirmedDepth ?? a.depth ?? recommendation.depth;
    const tier = a.confirmedTier ?? a.tier ?? recommendation.tier;
    // Explicit depth/tier override → edit path (human pin). Plain confirm → recommendation axes.
    const hasExplicit =
      a.confirmedDepth != null ||
      a.depth != null ||
      a.confirmedTier != null ||
      a.tier != null ||
      a.decision === 'edit';
    const lock = lockFromInteractive({
      decision: hasExplicit ? 'edit' : 'confirm',
      recommendation: hasExplicit
        ? undefined
        : {
            tier: recommendation.tier,
            depth: recommendation.depth,
            rationale: recommendation.rationale,
          },
      tier,
      depth,
      rationale:
        a.rationale ||
        `${skillId} entry confirm: tier=${tier} depth=${depth}`,
    });
    const knobs = knobsForSkill(skillId, lock.depth, lock.tier);
    return finalize(entry, lock, recommendation, knobs);
  }

  const err = new Error(
    `${skillId}: unlocked — confirm tier + depth (interactive, triageLock, or ` +
      `headless config/inherit) before work proceeds. ` +
      `runtime_enforced=${entry.runtimeEnforced}.`,
  );
  err.name = 'TriageUnlockedError';
  err.code = 'TRIAGE_UNLOCKED';
  err.halt_for_human = true;
  err.pending_action = `confirm-${skillId}-triage`;
  err.runtime_enforced = entry.runtimeEnforced;
  throw err;
}

/**
 * Knobs only after lock — throws if unlocked.
 * @param {unknown} skill
 * @param {unknown} hostOrLock
 * @returns {Readonly<object>}
 */
export function knobsAfterLock(skill, hostOrLock) {
  const skillId = normalizeMappedSkill(skill) || getSkillManifestEntry(skill)?.id;
  if (!skillId) {
    const err = new Error(`unknown skill: ${skill}`);
    err.code = 'TRIAGE_UNKNOWN_SKILL';
    throw err;
  }
  const band = getLockedBand(hostOrLock);
  const knobs = knobsForSkill(skillId, band.depth, band.tier);
  if (!knobs) {
    const err = new Error(`no knobs for ${skillId} @ ${band.depth}`);
    err.code = 'TRIAGE_NO_KNOBS';
    throw err;
  }
  return knobs;
}

/**
 * Generated triage block text for a skill (prose stamp surface).
 * @param {unknown} skill
 * @returns {string}
 */
export function triageBlockForSkill(skill) {
  const entry = getSkillManifestEntry(skill);
  if (!entry) {
    const err = new Error(`unknown skill: ${skill}`);
    err.code = 'TRIAGE_UNKNOWN_SKILL';
    throw err;
  }
  return renderTriageBlock(entry.id);
}

/**
 * Full entry payload: contract + optional lock + block payload.
 * @param {unknown} skill
 * @param {object} [args]
 * @returns {Readonly<object>}
 */
export function openSkillEntry(skill, args = {}) {
  const contract = entryPointContract(skill, args.intake ?? args.inputs ?? {});
  const block = buildTriageBlockPayload(contract.skill);
  let lockResult = null;
  try {
    if (
      args.triageLock != null ||
      args.lock != null ||
      args.headless === true ||
      args.decision === 'confirm' ||
      args.confirmedDepth != null ||
      args.requireLock === true
    ) {
      lockResult = resolveSkillLock(skill, args);
    }
  } catch (err) {
    if (args.requireLock === true || args.headless === true) throw err;
  }
  return Object.freeze({
    ...contract,
    block,
    locked: !!(lockResult && lockResult.lock),
    lock: lockResult ? lockResult.lock : null,
    knobs: lockResult ? lockResult.knobs : contract.knobs,
  });
}

function finalize(entry, lock, recommendation, knobs) {
  const band = getLockedBand(lock);
  return {
    lock,
    band,
    knobs,
    recommendation,
    contract: Object.freeze({
      skill: entry.id,
      stamp: NS01_WAVE6_STAMP,
      intakeClass: entry.intakeClass,
      runtime_enforced: entry.runtimeEnforced,
      triageSurface: entry.triageSurface,
      locked: true,
    }),
  };
}

export {
  SKILLS_MANIFEST,
  getSkillManifestEntry,
  knobsForSkill,
  getLockedBand,
  recommend,
};

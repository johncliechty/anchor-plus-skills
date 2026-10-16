// Resolve @foundry/triage lock + knobs for Gandalf (Phase 2b band-thin + B2 L1).
// LITE → fewer shards / one fusion; FULL → mapping table defaults; never unlocks silently
// when a depth/tier lock input is present (fail-closed).

import {
  recommendForSkill,
  resolveSkillLock,
  knobsAfterLock,
} from 'fil<path>';
import { knobsForSkill } from 'fil<path>';

/**
 * First non-empty string token (trim). Empty / whitespace → null.
 * @param {unknown} value
 * @returns {string | null}
 */
export function nonEmptyToken(value) {
  if (value == null) return null;
  const s = typeof value === 'string' ? value.trim() : String(value).trim();
  return s ? s : null;
}

/**
 * L1 depth chain — first non-empty wins:
 * explicit arg → GANDALF_DEPTH → FOUNDRY_TRIAGE_DEPTH
 * @param {{ depth?: unknown, env?: NodeJS.ProcessEnv | Record<string, string|undefined> }} [opts]
 * @returns {string | null}
 */
export function pickGandalfDepth({ depth = null, env = process.env } = {}) {
  const e = env && typeof env === 'object' ? env : {};
  return (
    nonEmptyToken(depth) ||
    nonEmptyToken(e.GANDALF_DEPTH) ||
    nonEmptyToken(e.FOUNDRY_TRIAGE_DEPTH) ||
    null
  );
}

/**
 * L1 tier chain — first non-empty wins:
 * explicit arg → GANDALF_TIER → FOUNDRY_TRIAGE_TIER
 * @param {{ tier?: unknown, env?: NodeJS.ProcessEnv | Record<string, string|undefined> }} [opts]
 * @returns {string | null}
 */
export function pickGandalfTier({ tier = null, env = process.env } = {}) {
  const e = env && typeof env === 'object' ? env : {};
  return (
    nonEmptyToken(tier) ||
    nonEmptyToken(e.GANDALF_TIER) ||
    nonEmptyToken(e.FOUNDRY_TRIAGE_TIER) ||
    null
  );
}

/**
 * Production lock trigger (L1): locked iff any of explicit depth|tier or the four
 * env names is set (non-empty after trim). GANDALF_MAX_SHARDS is never a lock.
 *
 * @param {{ depth?: unknown, tier?: unknown, env?: NodeJS.ProcessEnv | Record<string, string|undefined> }} [opts]
 * @returns {boolean}
 */
export function isGandalfBandLocked({ depth = null, tier = null, env = process.env } = {}) {
  return Boolean(pickGandalfDepth({ depth, env }) || pickGandalfTier({ tier, env }));
}

/**
 * L4 exclusive unlock predicate — true iff ALL lock inputs are absent/empty:
 * no explicit depth|tier and none of the four lock envs. GANDALF_MAX_SHARDS is
 * never a lock input (unlocked may still carry a legacy env cap elsewhere).
 *
 * @param {{ depth?: unknown, tier?: unknown, env?: NodeJS.ProcessEnv | Record<string, string|undefined> }} [opts]
 * @returns {boolean}
 */
export function isGandalfBandUnlocked({ depth = null, tier = null, env = process.env } = {}) {
  return !isGandalfBandLocked({ depth, tier, env });
}

/**
 * Safety floor (L4/L5): seats must be present and non-empty. Refuse band-thin
 * knobs that zero or omit seats — never silently thin past the seats floor.
 *
 * @param {object | null | undefined} knobs
 * @returns {object} knobs (same reference) when valid
 * @throws {Error} when seats are missing, empty, or numeric zero
 */
export function assertGandalfSeatsFloor(knobs) {
  if (!knobs || typeof knobs !== 'object') {
    throw new Error('gandalf band-thin refused: knobs missing (seats floor)');
  }
  const seats = knobs.seats;
  if (seats == null) {
    throw new Error('gandalf band-thin refused: seats floor violated (seats missing)');
  }
  if (typeof seats === 'number' && (!Number.isFinite(seats) || seats <= 0)) {
    throw new Error('gandalf band-thin refused: seats floor violated (seats zeroed)');
  }
  if (typeof seats === 'string' && seats.trim() === '') {
    throw new Error('gandalf band-thin refused: seats floor violated (seats empty)');
  }
  if (Array.isArray(seats) && seats.length === 0) {
    throw new Error('gandalf band-thin refused: seats floor violated (seats empty)');
  }
  return knobs;
}

/**
 * Resolve Gandalf band knobs from CLI / env / explicit lock.
 * Precedence (L1): explicit depth/tier → GANDALF_* → FOUNDRY_TRIAGE_* → recommend+confirm when allowDefault.
 * When any lock input is set, resolveSkillLock failures hard-fail (no advisory soft-pick).
 *
 * @param {object} [opts]
 * @param {string} [opts.depth]
 * @param {string} [opts.tier]
 * @param {object} [opts.intake]
 * @param {boolean} [opts.allowDefault=true]  when true, confirm recommended band if unlocked
 * @param {object} [opts.env]
 * @returns {{ knobs: object, lock: object|null, recommendation: object, source: string }}
 */
export function resolveGandalfBand({
  depth = null,
  tier = null,
  intake = {},
  allowDefault = true,
  env = process.env,
} = {}) {
  const d = pickGandalfDepth({ depth, env });
  const t = pickGandalfTier({ tier, env });
  const hasLockInput = Boolean(d || t);

  const recommendation = recommendForSkill('gandalf', {
    ...intake,
    depth: d || undefined,
    tier: t || undefined,
  });

  if (hasLockInput || allowDefault) {
    try {
      const resolved = resolveSkillLock('gandalf', {
        inputs: intake,
        confirmedDepth: d || recommendation.depth,
        confirmedTier: t || recommendation.tier,
        decision: 'confirm',
        recommendation,
      });
      // Lock path: refuse thinning that zeros seats (L4/L5 safety floor).
      if (hasLockInput) assertGandalfSeatsFloor(resolved.knobs);
      return {
        knobs: resolved.knobs,
        lock: resolved.lock,
        recommendation,
        source: hasLockInput ? 'explicit' : 'recommend-confirm',
      };
    } catch (err) {
      // Fail-closed on lock input: never soft-pick advisory / invent FULL.
      if (hasLockInput || !allowDefault) throw err;
    }
  }

  // Last resort advisory knobs (not a lock) — stamped unlocked for honesty.
  const knobs = knobsForSkill('gandalf', recommendation.depth, recommendation.tier);
  return {
    knobs,
    lock: null,
    recommendation,
    source: 'advisory',
  };
}

export { knobsForSkill, recommendForSkill, resolveSkillLock, knobsAfterLock };

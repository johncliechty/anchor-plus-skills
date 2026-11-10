// Track B6 W1 — sole production seam for zombie-hunter depth-variable knobs.
//
// Pipeline (locked):
//   depth pick (confirmedDepth / intake lock > FOUNDRY_TRIAGE_DEPTH > ZOMBIE_DEPTH)
//     → resolveZombieHunterDepthKnobs only  ({ depth, reaperPasses, ceremonyLevel })
//     → safety from frozen ZOMBIE_HUNTER_SAFETY_FLOOR (depth-invariant, not knobs)
//
// Missing depth → FULL mapped default (explicit source 'default-full', not a soft lock).
// Unknown depth → refuse (normalizeDepthStrict / sole resolve hard-fail).
// No second depth→reaperPasses table; no silent Math.max clamp.
// Safety overrides (requireProofOfDeath / abstainByDefault) are refuse-coded, never applied.

import { getLockedBand } from 'fil<path>';
import {
  REAPER_PASSES_MIN,
  ZOMBIE_HUNTER_SAFETY_FLOOR,
  resolveZombieHunterDepthKnobs,
  zombieHunterKnobProfile,
} from 'fil<path>';

/** Named refuse when a caller tries to depth-write or override the safety floor. */
export const ZOMBIE_HUNTER_SAFETY_OVERRIDE_REFUSED = 'ZOMBIE_HUNTER_SAFETY_OVERRIDE_REFUSED';

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
 * Depth lock precedence (B6 W1):
 *   1. explicit opts.confirmedDepth / opts.depth
 *   2. triageLock / lock / intake.lock record depth
 *   3. FOUNDRY_TRIAGE_DEPTH
 *   4. ZOMBIE_DEPTH
 *
 * Missing → null (caller maps to FULL default).
 *
 * @param {{
 *   depth?: unknown,
 *   confirmedDepth?: unknown,
 *   triageLock?: unknown,
 *   lock?: unknown,
 *   intake?: unknown,
 *   env?: NodeJS.ProcessEnv | Record<string, string | undefined>,
 * }} [opts]
 * @returns {string | null}
 */
export function pickZombieHunterDepth({
  depth = null,
  confirmedDepth = null,
  triageLock = null,
  lock = null,
  intake = null,
  env = process.env,
} = {}) {
  const pin = nonEmptyToken(confirmedDepth) || nonEmptyToken(depth);
  if (pin) return pin;

  const explicit = triageLock ?? lock ?? null;
  if (explicit != null) {
    const band = getLockedBand(explicit);
    const lockedDepth = band && nonEmptyToken(band.depth);
    if (lockedDepth) return lockedDepth;
  }

  if (intake != null && typeof intake === 'object') {
    const bag = /** @type {Record<string, unknown>} */ (intake);
    if (bag.lock != null && typeof bag.lock === 'object') {
      const band = getLockedBand(bag.lock);
      const lockedDepth = band && nonEmptyToken(band.depth);
      if (lockedDepth) return lockedDepth;
    }
    const intakeDepth = nonEmptyToken(bag.confirmedDepth) || nonEmptyToken(bag.depth);
    if (intakeDepth) return intakeDepth;
  }

  const e = env && typeof env === 'object' ? env : {};
  // FOUNDRY_TRIAGE_DEPTH beats ZOMBIE_DEPTH (portfolio lock outranks skill alias).
  return (
    nonEmptyToken(e.FOUNDRY_TRIAGE_DEPTH) || nonEmptyToken(e.ZOMBIE_DEPTH) || null
  );
}

/**
 * Build the refuse error when safety floor overrides are attempted.
 * @param {string} field
 * @param {unknown} value
 * @returns {Error}
 */
export function zombieHunterSafetyOverrideError(field, value) {
  const err = new Error(
    `zombie-hunter safety floor field ${field} is depth-invariant and non-overridable ` +
      `(got ${JSON.stringify(value)}); use ZOMBIE_HUNTER_SAFETY_FLOOR only`,
  );
  err.name = 'ZombieHunterSafetyOverrideError';
  err.code = ZOMBIE_HUNTER_SAFETY_OVERRIDE_REFUSED;
  /** @type {any} */ (err).field = field;
  /** @type {any} */ (err).value = value;
  return err;
}

/**
 * Resolve zombie-hunter depth-variable knobs via the sole triage mapping path.
 *
 * Depth-variable: reaperPasses, ceremonyLevel (from resolveZombieHunterDepthKnobs).
 * Safety: always ZOMBIE_HUNTER_SAFETY_FLOOR (never depth-writable, never clamped).
 *
 * @param {object} [opts]
 * @param {string} [opts.depth]             explicit depth pin
 * @param {string} [opts.confirmedDepth]    intake/confirm pin (same rank as depth)
 * @param {string} [opts.tier]              accepted for ergonomics; ignored for knobs
 * @param {object} [opts.intake]            may carry lock / confirmedDepth
 * @param {object} [opts.triageLock]        existing lock record
 * @param {object} [opts.lock]              alias of triageLock
 * @param {object} [opts.env]               env surface (default process.env)
 * @param {unknown} [opts.requireProofOfDeath]  refuse if present (not overridable)
 * @param {unknown} [opts.abstainByDefault]     refuse if present (not overridable)
 * @returns {Readonly<{
 *   knobs: Readonly<{ depth: string, reaperPasses: number, ceremonyLevel: string, skill: string }>,
 *   resolved: Readonly<{ depth: string, reaperPasses: number, ceremonyLevel: string }>,
 *   reaperPasses: number,
 *   ceremonyLevel: string,
 *   depth: string,
 *   safety: Readonly<{ requireProofOfDeath: true, abstainByDefault: true }>,
 *   requireProofOfDeath: true,
 *   abstainByDefault: true,
 *   source: 'depth-lock' | 'default-full',
 * }>}
 */
export function resolveZombieHunterBand({
  depth = null,
  confirmedDepth = null,
  tier: _tier = null,
  intake = {},
  triageLock = null,
  lock = null,
  env = process.env,
  requireProofOfDeath,
  abstainByDefault,
} = {}) {
  // Safety overrides refuse-coded — never applied, never silently ignored when false.
  if (requireProofOfDeath !== undefined) {
    throw zombieHunterSafetyOverrideError('requireProofOfDeath', requireProofOfDeath);
  }
  if (abstainByDefault !== undefined) {
    throw zombieHunterSafetyOverrideError('abstainByDefault', abstainByDefault);
  }

  const picked = pickZombieHunterDepth({
    depth,
    confirmedDepth,
    triageLock,
    lock,
    intake,
    env,
  });
  // Explicit missing-depth policy: FULL mapped default (not a soft-lock claim).
  const source = picked ? 'depth-lock' : 'default-full';
  const depthToken = picked || 'FULL';

  // Sole knobs path — resolveZombieHunterDepthKnobs only (no second table, no Math.max clamp).
  const resolved = resolveZombieHunterDepthKnobs(depthToken);
  const knobs = Object.freeze({
    skill: 'zombie-hunter',
    depth: resolved.depth,
    reaperPasses: resolved.reaperPasses,
    ceremonyLevel: resolved.ceremonyLevel,
  });

  return Object.freeze({
    knobs,
    resolved,
    reaperPasses: resolved.reaperPasses,
    ceremonyLevel: resolved.ceremonyLevel,
    depth: resolved.depth,
    safety: ZOMBIE_HUNTER_SAFETY_FLOOR,
    // Floor readouts only — not depth-profile knobs (compat for callers expecting the name).
    requireProofOfDeath: ZOMBIE_HUNTER_SAFETY_FLOOR.requireProofOfDeath,
    abstainByDefault: ZOMBIE_HUNTER_SAFETY_FLOOR.abstainByDefault,
    source,
  });
}

export {
  REAPER_PASSES_MIN,
  ZOMBIE_HUNTER_SAFETY_FLOOR,
  resolveZombieHunterDepthKnobs,
  zombieHunterKnobProfile,
};

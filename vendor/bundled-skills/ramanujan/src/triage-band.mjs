// Track B4 — sole production seam for Ramanujan band knobs (verifyArms / certifier).
//
// Pipeline (locked):
//   depth lock (explicit pin | triageLock | FOUNDRY_TRIAGE_DEPTH | RAMANUJAN_DEPTH)
//     → resolveRamanujanDepthKnobs only
//     → Object.freeze({ depth, verifyArms, certifier })
//
// Unlocked (no depth from the precedence surface) → throw
// RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK — certifier never true; no default-full;
// tier env alone never unlocks. Honesty-law labels are never thinned by this module.

// Ship-safe foundry-triage resolution (2026-07-26): the previous absolute author-host
// file URLs were scrubbed to 'fil<path>' in the collaborator bundle, crashing EVERY
// vendored import of this module. Probe: (1) ANCHOR_FOUNDRY_DIR/SKILL_FOUNDRY_DIR env,
// (2) the vendored sibling layout (bundled-skills/foundry/triage), (3) the canonical
// Skill Foundry layout — then dynamic-import (no literal host path survives to scrub).
import { existsSync } from 'node:fs';
import { dirname, join, resolve as resolvePath } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

function resolveTriageRoot() {
  const env = process.env.ANCHOR_FOUNDRY_DIR || process.env.SKILL_FOUNDRY_DIR;
  if (env && existsSync(join(env, 'foundry', 'triage', 'mapping.mjs'))) return join(env, 'foundry', 'triage');
  const here = dirname(fileURLToPath(import.meta.url)); // <skill>/src
  for (const cand of [
    resolvePath(here, '..', '..', 'foundry', 'triage'),        // vendor/bundled-skills/foundry/triage (ship layout)
    resolvePath(here, '..', '..', '..', 'foundry', 'triage'),  // Skill Foundry/foundry/triage (canonical)
  ]) {
    if (existsSync(join(cand, 'mapping.mjs'))) return cand;
  }
  throw new Error('ramanujan triage-band: foundry/triage not resolvable (set ANCHOR_FOUNDRY_DIR to the Skill Foundry root)');
}
const _triage = resolveTriageRoot();
const { getLockedBand } = await import(pathToFileURL(join(_triage, 'lock.mjs')).href);
const { resolveRamanujanDepthKnobs } = await import(pathToFileURL(join(_triage, 'mapping.mjs')).href);

/** Named refuse code for unlocked certifier/knob resolve (B4 SC4). */
export const RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK = 'RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK';

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
 * Depth lock precedence (B4 / W2 ranks):
 *   1. explicit opts.depth
 *   2. triageLock / lock record depth
 *   3. FOUNDRY_TRIAGE_DEPTH
 *   4. RAMANUJAN_DEPTH
 *
 * Tier env (RAMANUJAN_TIER / FOUNDRY_TRIAGE_TIER) is intentionally ignored —
 * tier alone never unlocks certifier spend.
 *
 * @param {{
 *   depth?: unknown,
 *   triageLock?: unknown,
 *   lock?: unknown,
 *   env?: NodeJS.ProcessEnv | Record<string, string | undefined>,
 * }} [opts]
 * @returns {string | null}
 */
export function pickRamanujanDepth({
  depth = null,
  triageLock = null,
  lock = null,
  env = process.env,
} = {}) {
  const pin = nonEmptyToken(depth);
  if (pin) return pin;

  const explicit = triageLock ?? lock ?? null;
  if (explicit != null) {
    const band = getLockedBand(explicit);
    const lockedDepth = band && nonEmptyToken(band.depth);
    if (lockedDepth) return lockedDepth;
  }

  const e = env && typeof env === 'object' ? env : {};
  // FOUNDRY_TRIAGE_DEPTH beats RAMANUJAN_DEPTH (portfolio lock outranks skill alias).
  return (
    nonEmptyToken(e.FOUNDRY_TRIAGE_DEPTH) || nonEmptyToken(e.RAMANUJAN_DEPTH) || null
  );
}

/**
 * Build the named unlock refuse error (never returns certifier true).
 * @param {string} [detail]
 * @returns {Error}
 */
export function ramanujanDepthLockError(detail) {
  const err = new Error(
    detail ||
      'Ramanujan verifyArms/certifier require a depth lock ' +
        '(explicit pin, triageLock, FOUNDRY_TRIAGE_DEPTH, or RAMANUJAN_DEPTH). ' +
        'Tier env alone never unlocks certifier spend.',
  );
  err.name = 'RamanujanDepthLockError';
  err.code = RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK;
  return err;
}

/**
 * Production arm predicate — true only when frozen resolved knobs say certifier===true.
 * Never reads process.env. Never freelances true from tier or missing knobs.
 *
 * @param {unknown} knobsOrBand  resolveRamanujanDepthKnobs result, band.knobs, or band.resolved
 * @returns {boolean}
 */
export function isCertifierArmed(knobsOrBand) {
  if (knobsOrBand == null || typeof knobsOrBand !== 'object') return false;
  const o = /** @type {Record<string, unknown>} */ (knobsOrBand);
  const k =
    o.knobs && typeof o.knobs === 'object'
      ? /** @type {Record<string, unknown>} */ (o.knobs)
      : o.resolved && typeof o.resolved === 'object'
        ? /** @type {Record<string, unknown>} */ (o.resolved)
        : o;
  return k.certifier === true;
}

/**
 * Resolve Ramanujan band knobs only after a depth lock (B4 sole production path).
 *
 * Unlocked → throws code RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK (certifier never true).
 * Locked → resolveRamanujanDepthKnobs only (no knobsForSkill at arm sites, no default-full).
 *
 * @param {object} [opts]
 * @param {string} [opts.depth]           explicit depth pin
 * @param {string} [opts.tier]            accepted for ergonomics; ignored for knobs (depth-only)
 * @param {object} [opts.intake]          unused for knobs (recommend/advisory never counts as lock)
 * @param {object} [opts.triageLock]      existing lock record
 * @param {object} [opts.lock]            alias of triageLock
 * @param {object} [opts.env]             env surface (default process.env)
 * @returns {Readonly<{
 *   knobs: Readonly<{ depth: string, verifyArms: number, certifier: boolean, skill: string }>,
 *   resolved: Readonly<{ depth: string, verifyArms: number, certifier: boolean }>,
 *   certifierEnabled: boolean,
 *   verifyArms: number,
 *   depth: string,
 *   source: 'depth-lock',
 * }>}
 */
export function resolveRamanujanBand({
  depth = null,
  tier: _tier = null,
  intake: _intake = {},
  triageLock = null,
  lock = null,
  env = process.env,
} = {}) {
  const d = pickRamanujanDepth({ depth, triageLock, lock, env });
  if (!d) {
    throw ramanujanDepthLockError();
  }

  // Sole knobs path — resolveRamanujanDepthKnobs only (no generic skill-knobs arm, no freelanced true).
  const resolved = resolveRamanujanDepthKnobs(d);
  const knobs = Object.freeze({
    skill: 'ramanujan',
    depth: resolved.depth,
    verifyArms: resolved.verifyArms,
    certifier: resolved.certifier,
  });

  return Object.freeze({
    knobs,
    resolved,
    certifierEnabled: resolved.certifier === true,
    verifyArms: resolved.verifyArms,
    depth: resolved.depth,
    source: 'depth-lock',
  });
}

export { resolveRamanujanDepthKnobs };

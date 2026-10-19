// Lock record + getLockedBand for engine hosts (NS-01 / Wave 2).
//
// Intent: no dimension is readable without a validating lock.
// recommend() remains ADVISORY only — engines must call getLockedBand()
// (or establish a lock via lockFromInteractive / lockFromHeadless) before
// work proceeds. Unlocked headless → HALT, never a silent default.
//
// Non-goals (plan): DPAPI, sealer, forgery crypto.

import {
  isModelTier,
  isProcessDepth,
  canonicalizeDepth,
  normalizeDepth,
  normalizeTier,
} from './core.mjs';

/** @typedef {import('./core.mjs').ModelTier} ModelTier */
/** @typedef {import('./core.mjs').ProcessDepth} ProcessDepth */

/**
 * How the lock was established.
 * @typedef {'interactive' | 'config' | 'inherit'} LockSource
 */

/**
 * Validating lock record schema (both axes + provenance).
 * Frozen plain object; engines store this and pass it to getLockedBand.
 *
 * @typedef {{
 *   locked: true,
 *   tier: ModelTier,
 *   depth: ProcessDepth,
 *   rationale: string,
 *   source: LockSource,
 *   lockedAt: string,
 * }} TriageLockRecord
 */

/** Lock provenance vocabulary. */
export const LOCK_SOURCES = Object.freeze({
  INTERACTIVE: 'interactive',
  CONFIG: 'config',
  INHERIT: 'inherit',
});

export const LOCK_SOURCE_VALUES = Object.freeze([
  LOCK_SOURCES.INTERACTIVE,
  LOCK_SOURCES.CONFIG,
  LOCK_SOURCES.INHERIT,
]);

/**
 * True when `value` is a known lock source token.
 * @param {unknown} value
 * @returns {value is LockSource}
 */
export function isLockSource(value) {
  return LOCK_SOURCE_VALUES.includes(/** @type {LockSource} */ (value));
}

/**
 * Structural + vocabulary validation of a lock record (does not throw).
 * @param {unknown} value
 * @returns {value is TriageLockRecord}
 */
export function isLockRecord(value) {
  if (!value || typeof value !== 'object') return false;
  const r = /** @type {Record<string, unknown>} */ (value);
  if (r.locked !== true) return false;
  if (!isModelTier(r.tier)) return false;
  if (!isProcessDepth(r.depth)) return false;
  if (typeof r.rationale !== 'string' || r.rationale.length === 0) return false;
  if (!isLockSource(r.source)) return false;
  if (typeof r.lockedAt !== 'string' || r.lockedAt.length === 0) return false;
  return true;
}

/**
 * Resolve a lock candidate from a bare record or an engine-host bag that
 * stores the record under `.lock` (sole well-known host field).
 * @param {unknown} hostOrLock
 * @returns {unknown}
 */
function resolveLockCandidate(hostOrLock) {
  if (!hostOrLock || typeof hostOrLock !== 'object') return null;
  const o = /** @type {Record<string, unknown>} */ (hostOrLock);
  // Bare lock record (discriminant or full schema fields).
  if (o.locked === true) return o;
  if (
    o.tier != null &&
    o.depth != null &&
    o.source != null &&
    o.lockedAt != null &&
    o.rationale != null &&
    !('lock' in o)
  ) {
    return o;
  }
  // Engine host bag — single reader site field name: lock
  if (o.lock != null && typeof o.lock === 'object') return o.lock;
  return null;
}

/**
 * Build a validated, frozen lock record. Throws on invalid tokens / empty rationale.
 *
 * @param {object} input
 * @param {unknown} input.tier
 * @param {unknown} input.depth
 * @param {string}  [input.rationale]
 * @param {unknown} input.source
 * @param {string}  [input.lockedAt] ISO-8601; default now
 * @returns {Readonly<TriageLockRecord>}
 */
export function createLockRecord(input = {}) {
  const i = input && typeof input === 'object' ? input : {};
  const tier = isModelTier(i.tier) ? i.tier : normalizeTier(i.tier);
  // canonicalizeDepth maps legacy SPIKE-FIRST storage → SPIKE pin (B3).
  const depth = canonicalizeDepth(i.depth) ?? (isProcessDepth(i.depth) ? i.depth : normalizeDepth(i.depth));
  const source = isLockSource(i.source) ? i.source : null;
  const rationale =
    typeof i.rationale === 'string' && i.rationale.trim()
      ? i.rationale.trim()
      : '';
  const lockedAt =
    typeof i.lockedAt === 'string' && i.lockedAt.trim()
      ? i.lockedAt.trim()
      : new Date().toISOString();

  if (!tier || !depth || !source || !rationale) {
    const err = new Error(
      'triage createLockRecord: invalid lock — need pin-token tier + depth, ' +
        'non-empty rationale, and source ∈ {interactive, config, inherit}. ' +
        `Got tier=${String(i.tier)} depth=${String(i.depth)} source=${String(i.source)} ` +
        `rationale=${rationale ? 'set' : 'empty'}.`,
    );
    err.name = 'TriageLockSchemaError';
    err.code = 'TRIAGE_LOCK_SCHEMA';
    throw err;
  }

  /** @type {TriageLockRecord} */
  const record = {
    locked: true,
    tier,
    depth,
    rationale,
    source,
    lockedAt,
  };
  return Object.freeze(record);
}

/**
 * Sole reader of locked band for engine hosts.
 *
 * Accepts a lock record or a host object with `.lock` set to one.
 * Throws if unlocked / invalid — unlocked engine runs cannot proceed.
 *
 * @param {unknown} hostOrLock
 * @returns {{
 *   tier: ModelTier,
 *   depth: ProcessDepth,
 *   rationale: string,
 *   source: LockSource,
 *   lockedAt: string,
 *   locked: true,
 * }}
 */
export function getLockedBand(hostOrLock) {
  const candidate = resolveLockCandidate(hostOrLock);
  if (!isLockRecord(candidate)) {
    const err = new Error(
      'triage getLockedBand: unlocked — no validating lock record. ' +
        'Engine hosts must lock both dimensions (interactive confirm/edit, or ' +
        'headless config/inherit) before reading tier/depth. Unlocked headless HALTs.',
    );
    err.name = 'TriageUnlockedError';
    err.code = 'TRIAGE_UNLOCKED';
    throw err;
  }
  // Re-freeze a public slice so callers cannot mutate the stored record via return.
  return Object.freeze({
    locked: true,
    tier: candidate.tier,
    depth: candidate.depth,
    rationale: candidate.rationale,
    source: candidate.source,
    lockedAt: candidate.lockedAt,
  });
}

/**
 * Attach a validated lock to an engine-host bag under `.lock`.
 * @param {object} host
 * @param {TriageLockRecord | object} lockOrInput  record or createLockRecord input
 * @returns {Readonly<TriageLockRecord>}
 */
export function applyLock(host, lockOrInput) {
  if (!host || typeof host !== 'object') {
    const err = new Error('triage applyLock: host must be an object');
    err.name = 'TriageLockSchemaError';
    err.code = 'TRIAGE_LOCK_SCHEMA';
    throw err;
  }
  const record = isLockRecord(lockOrInput)
    ? Object.freeze({ ...lockOrInput })
    : createLockRecord(lockOrInput);
  host.lock = record;
  return record;
}

/**
 * Interactive confirm / edit / lock path for engine hosts.
 *
 * - decision `'confirm'`: lock the recommendation's tier+depth (advisory → lock).
 * - decision `'edit'`: lock explicit tier+depth (human override).
 *
 * Headless sessions must NOT call this — throws when `headless === true`
 * (North Star: no interactive prompt path in headless mode).
 *
 * @param {object} args
 * @param {object}  [args.recommendation]  from recommend(); required for confirm
 * @param {'confirm'|'edit'} args.decision
 * @param {unknown} [args.tier]   required when decision==='edit'
 * @param {unknown} [args.depth]  required when decision==='edit'
 * @param {string}  [args.rationale]
 * @param {boolean} [args.headless=false]
 * @returns {Readonly<TriageLockRecord>}
 */
export function lockFromInteractive(args = {}) {
  const a = args && typeof args === 'object' ? args : {};
  if (a.headless === true) {
    const err = new Error(
      'triage lockFromInteractive: interactive confirm/edit path is forbidden when headless=true. ' +
        'Use lockFromHeadless({ config, inherit }) — unlocked headless HALTs.',
    );
    err.name = 'TriageHeadlessHaltError';
    err.code = 'TRIAGE_HEADLESS_INTERACTIVE_FORBIDDEN';
    throw err;
  }

  const decision = a.decision;
  if (decision !== 'confirm' && decision !== 'edit') {
    const err = new Error(
      `triage lockFromInteractive: decision must be 'confirm' or 'edit', got ${String(decision)}`,
    );
    err.name = 'TriageLockSchemaError';
    err.code = 'TRIAGE_LOCK_SCHEMA';
    throw err;
  }

  let tier;
  let depth;
  let rationale;

  if (decision === 'confirm') {
    const rec = a.recommendation && typeof a.recommendation === 'object' ? a.recommendation : null;
    if (!rec || !isModelTier(rec.tier) || !isProcessDepth(rec.depth)) {
      const err = new Error(
        'triage lockFromInteractive: confirm requires a recommendation with pin-token tier + depth',
      );
      err.name = 'TriageLockSchemaError';
      err.code = 'TRIAGE_LOCK_SCHEMA';
      throw err;
    }
    tier = rec.tier;
    depth = canonicalizeDepth(rec.depth) ?? rec.depth;
    rationale =
      typeof a.rationale === 'string' && a.rationale.trim()
        ? a.rationale.trim()
        : typeof rec.rationale === 'string' && rec.rationale.trim()
          ? `interactive confirm: ${rec.rationale.trim()}`
          : `interactive confirm: tier=${tier} depth=${depth}`;
  } else {
    tier = isModelTier(a.tier) ? a.tier : normalizeTier(a.tier);
    depth = canonicalizeDepth(a.depth) ?? (isProcessDepth(a.depth) ? a.depth : normalizeDepth(a.depth));
    if (!tier || !depth) {
      const err = new Error(
        'triage lockFromInteractive: edit requires valid tier + depth (pin tokens or aliases)',
      );
      err.name = 'TriageLockSchemaError';
      err.code = 'TRIAGE_LOCK_SCHEMA';
      throw err;
    }
    rationale =
      typeof a.rationale === 'string' && a.rationale.trim()
        ? a.rationale.trim()
        : `interactive edit: tier=${tier} depth=${depth}`;
  }

  return createLockRecord({
    tier,
    depth,
    rationale,
    source: LOCK_SOURCES.INTERACTIVE,
  });
}

/**
 * Headless lock path: config-time lock and/or inherit only.
 * Prefer inherit (upstream handoff) over config when both present.
 * Missing/invalid both → HALT (not silent default).
 *
 * @param {object} [opts]
 * @param {{ tier?: unknown, depth?: unknown, rationale?: string } | null} [opts.config]
 * @param {{ tier?: unknown, depth?: unknown, rationale?: string } | null} [opts.inherit]
 * @returns {Readonly<TriageLockRecord>}
 */
export function lockFromHeadless(opts = {}) {
  const o = opts && typeof opts === 'object' ? opts : {};
  const inherit = o.inherit && typeof o.inherit === 'object' ? o.inherit : null;
  const config = o.config && typeof o.config === 'object' ? o.config : null;

  const pick = inherit || config;
  if (!pick) {
    const err = new Error(
      'triage lockFromHeadless: HALT — unlocked headless run (no config-time lock and no inherit). ' +
        'Headless may only proceed with a validating config or inherit lock; never auto-provision without a lock.',
    );
    err.name = 'TriageHeadlessHaltError';
    err.code = 'TRIAGE_HEADLESS_UNLOCKED';
    throw err;
  }

  const tier = isModelTier(pick.tier) ? pick.tier : normalizeTier(pick.tier);
  const depth =
    canonicalizeDepth(pick.depth) ??
    (isProcessDepth(pick.depth) ? pick.depth : normalizeDepth(pick.depth));
  if (!tier || !depth) {
    const err = new Error(
      'triage lockFromHeadless: HALT — config/inherit present but tier/depth failed validation ' +
        `(tier=${String(pick.tier)} depth=${String(pick.depth)}).`,
    );
    err.name = 'TriageHeadlessHaltError';
    err.code = 'TRIAGE_HEADLESS_UNLOCKED';
    throw err;
  }

  const source = inherit ? LOCK_SOURCES.INHERIT : LOCK_SOURCES.CONFIG;
  const rationale =
    typeof pick.rationale === 'string' && pick.rationale.trim()
      ? pick.rationale.trim()
      : `headless ${source}: tier=${tier} depth=${depth}`;

  return createLockRecord({ tier, depth, rationale, source });
}

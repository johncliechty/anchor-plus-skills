// Crucible Stage-0 wire + handoff emit (NS-01 / Wave 3).
//
// Closes the gap "runStage0 never calls assessComplexity": Stage-0 MUST call
// the shared triage core (recommend → lock → getLockedBand) and emit both
// dimensions into the Foreman handoff shape.
//
// Recon (Foreman consumer, trio/foreman/bin/run-live.mjs):
//   · `foreman.config.json.triage_track` is read as a STRING (FULL / LITE / LIGHT /
//     SPIKE-FIRST / HEAVY aliases) to size reviewer fan-out.
//   · Schema extension: keep `triage_track` = process-depth pin token (string) for
//     that consumer; ALSO emit `triage: { tier, depth, rationale, source, locked }`
//     so both axes travel. Documented in docs/DECISION-RECEIPT.md §7.
//
// Non-goals: DPAPI/sealer. Foreman inherit-only is Wave 4 (`foreman-wire.mjs`).
// Wave 5: band knobs consumed from mapping.mjs (named consumption site).

import {
  DEPTH_BANDS,
  DEPTH_BAND_VALUES,
  MODEL_TIERS,
  canonicalizeDepth,
  isModelTier,
  isProcessDepth,
  normalizeDepth,
  normalizeTier,
  recommend,
} from './core.mjs';
import {
  applyLock,
  createLockRecord,
  getLockedBand,
  lockFromHeadless,
  lockFromInteractive,
} from './lock.mjs';
import { crucibleKnobs } from './mapping.mjs';

/** Wave-3 surface stamp — asserted by the Stage-0 wire suite. */
export const NS01_WAVE3_STAMP = 'ns01-w3-stage0-wire';

/**
 * Legacy Crucible C3 band tokens (lowercase) — kept for assessComplexity back-compat
 * with existing Crucible unit tests. Live emit uses pin tokens (DEPTH_BANDS).
 */
export const COMPLEXITY_BANDS = Object.freeze({
  LITE: 'lite',
  FULL: 'full',
  SPIKE_FIRST: 'spike-first',
});

/**
 * Map NS pin depth → legacy lowercase band (Crucible C3 vocabulary).
 * @param {string} depth
 * @returns {string}
 */
export function depthToLegacyBand(depth) {
  const d = canonicalizeDepth(depth) ?? (isProcessDepth(depth) ? depth : normalizeDepth(depth));
  if (d === DEPTH_BANDS.LITE) return COMPLEXITY_BANDS.LITE;
  if (d === DEPTH_BANDS.SPIKE || d === DEPTH_BANDS.SPIKE_FIRST || d === 'SPIKE-FIRST') {
    return COMPLEXITY_BANDS.SPIKE_FIRST;
  }
  return COMPLEXITY_BANDS.FULL;
}

/**
 * Map legacy or free-form depth → NS pin token.
 * @param {unknown} value
 * @returns {import('./core.mjs').ProcessDepth | null}
 */
export function legacyBandToDepth(value) {
  const canon = canonicalizeDepth(value);
  if (canon) return canon;
  if (isProcessDepth(value)) return /** @type {import('./core.mjs').ProcessDepth} */ (value);
  const n = normalizeDepth(value);
  if (n) return n;
  if (typeof value !== 'string') return null;
  const key = value.trim().toLowerCase();
  if (key === 'lite' || key === 'light') return DEPTH_BANDS.LITE;
  if (key === 'spike-first' || key === 'spikefirst' || key === 'spike') return DEPTH_BANDS.SPIKE;
  if (key === 'full' || key === 'heavy') return DEPTH_BANDS.FULL;
  return null;
}

/**
 * Shared-core Stage-0 complexity triage (replaces the hand-rolled assessComplexity body).
 *
 * Calls `recommend()` (the single source of triage logic). Returns the Crucible C3
 * shape (lowercase `band`/`depth`, `defaultedToFull`, `halt`) PLUS pin-token fields
 * (`nsTier`, `nsDepth`, `recommendation`) so runStage0 can lock both axes.
 *
 * Right-sizing remains a USER judgment: the result carries a confirm-band HALT
 * payload; callers must lock (interactive confirm/edit or headless config/inherit)
 * before work proceeds — never auto-apply an unlocked recommend().
 *
 * @param {object} [intake]
 * @param {object} [opts]
 * @param {function} [opts.haltForHuman]  optional HaltError factory (Crucible injects)
 * @returns {object}
 */
export function assessComplexity(intake = {}, opts = {}) {
  const rec = recommend(intake || {});
  const band = depthToLegacyBand(rec.depth);
  const defaultedToFull =
    rec.depth === DEPTH_BANDS.FULL && !!(rec.defaultedDepth || rec.defaulted);

  const haltFactory =
    typeof opts.haltForHuman === 'function'
      ? opts.haltForHuman
      : (reason, pending) => {
          const err = new Error(reason);
          err.name = 'HaltError';
          err.halt_for_human = true;
          err.pending_action = pending;
          err.reason = reason;
          return err;
        };

  const halt = haltFactory(
    `Complexity triage recommends ${rec.depth} (tier=${rec.tier}) — ${rec.rationale} ` +
      `Right-sizing is your judgment; confirm the depth AND model tier ` +
      `(the North Star is locked + drift-checked in EVERY mode).`,
    'confirm-complexity-band',
  );

  // Wave 5 named site: mapping table knobs for this depth (additive field).
  const bandKnobs = crucibleKnobs(rec.depth, rec.tier);

  return {
    band,
    // Legacy C3 field: lowercase band string (stage0-complexity tests assert this).
    depth: band,
    // NS-01 pin tokens (Wave 3) — the only values that may be locked / emitted.
    nsTier: rec.tier,
    nsDepth: rec.depth,
    rationale: rec.rationale,
    defaultedToFull,
    signals: rec.signals,
    recommendation: rec,
    halt,
    bandKnobs,
  };
}

/**
 * Resolve a validating triage lock for Stage-0, or throw (unlocked → fail).
 *
 * Precedence:
 *   1. Explicit lock record / host.lock (`triageLock` / `lock`)
 *   2. Headless: config-time lock and/or inherit (`headless:true`)
 *   3. Interactive: confirmed depth (+ optional tier) or confirm recommendation
 *
 * Missing all of the above → throws the complexity confirm HALT (or TRIAGE_UNLOCKED).
 *
 * @param {object} args
 * @param {object}  [args.intake]           cheap Stage-0 signals (fed to recommend)
 * @param {object}  [args.complexity]      precomputed assessComplexity result
 * @param {unknown} [args.triageLock]      lock record or host bag with .lock
 * @param {unknown} [args.lock]            alias of triageLock
 * @param {boolean} [args.headless=false]
 * @param {object}  [args.triageConfig]    headless config-time lock
 * @param {object}  [args.triageInherit]   headless inherit (upstream handoff)
 * @param {unknown} [args.confirmedDepth]  user-confirmed depth (pin or legacy)
 * @param {unknown} [args.confirmedTier]   user-confirmed tier (pin or alias)
 * @param {unknown} [args.depth]           alias of confirmedDepth
 * @param {unknown} [args.tier]            alias of confirmedTier
 * @param {'confirm'|'edit'} [args.decision] interactive decision (default edit when both set)
 * @param {string}  [args.rationale]
 * @param {function}[args.haltForHuman]
 * @returns {{ lock: Readonly<object>, complexity: object, band: ReturnType<typeof getLockedBand> }}
 */
export function resolveStage0TriageLock(args = {}) {
  const a = args && typeof args === 'object' ? args : {};
  const complexity =
    a.complexity && typeof a.complexity === 'object'
      ? a.complexity
      : assessComplexity(a.intake || {}, { haltForHuman: a.haltForHuman });

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
    return { lock, complexity, band: getLockedBand(lock) };
  }

  if (a.headless === true) {
    const lock = lockFromHeadless({
      config: a.triageConfig ?? a.config ?? null,
      inherit: a.triageInherit ?? a.inherit ?? null,
    });
    return { lock, complexity, band: getLockedBand(lock) };
  }

  const confirmedDepth = legacyBandToDepth(a.confirmedDepth ?? a.depth ?? null);
  const confirmedTierRaw = a.confirmedTier ?? a.tier ?? null;
  const confirmedTier = isModelTier(confirmedTierRaw)
    ? confirmedTierRaw
    : normalizeTier(confirmedTierRaw);

  if (confirmedDepth && confirmedTier) {
    const lock = lockFromInteractive({
      decision: a.decision === 'confirm' ? 'confirm' : 'edit',
      recommendation:
        a.decision === 'confirm'
          ? {
              tier: confirmedTier,
              depth: confirmedDepth,
              rationale: a.rationale || complexity.rationale,
            }
          : undefined,
      tier: confirmedTier,
      depth: confirmedDepth,
      rationale:
        a.rationale ||
        `Stage-0 confirmed: tier=${confirmedTier} depth=${confirmedDepth}`,
    });
    return { lock, complexity, band: getLockedBand(lock) };
  }

  if (confirmedDepth) {
    // Depth confirmed; tier from shared recommendation (user accepted the rec's tier).
    const lock = lockFromInteractive({
      decision: 'confirm',
      recommendation: {
        tier: complexity.nsTier,
        depth: confirmedDepth,
        rationale: complexity.rationale,
      },
      rationale:
        a.rationale ||
        `Stage-0 confirm depth=${confirmedDepth} tier=${complexity.nsTier} (from shared recommend)`,
    });
    return { lock, complexity, band: getLockedBand(lock) };
  }

  // Unlocked — Stage-0 must not proceed. Prefer the complexity confirm HALT so
  // Crucible operators see the documented pending_action.
  if (complexity.halt) throw complexity.halt;
  const err = new Error(
    'triage Stage-0: unlocked — confirm complexity band (tier + depth) before framing. ' +
      'Pass confirmedDepth/tier, triageLock, or headless config/inherit.',
  );
  err.name = 'TriageUnlockedError';
  err.code = 'TRIAGE_UNLOCKED';
  err.halt_for_human = true;
  err.pending_action = 'confirm-complexity-band';
  throw err;
}

/**
 * Build the Foreman handoff emit shape from a validating lock / locked band.
 *
 * Shape (Wave 3 recon — string track kept for run-live consumer):
 * ```
 * {
 *   triage_track: 'FULL' | 'LITE' | 'SPIKE-FIRST',   // depth pin (string)
 *   triage: {
 *     locked: true,
 *     tier: 'Heavy' | 'Standard',
 *     depth: 'FULL' | 'LITE' | 'SPIKE-FIRST',
 *     rationale: string,
 *     source: 'interactive' | 'config' | 'inherit',
 *     lockedAt: string,
 *   }
 * }
 * ```
 *
 * Unlocked input → throws via getLockedBand (Stage-0 without lock fails).
 *
 * @param {unknown} hostOrLock
 * @returns {{ triage_track: string, triage: object }}
 */
export function buildHandoffTriageEmit(hostOrLock) {
  const band = getLockedBand(hostOrLock);
  // Foreman consumer: triage_track is the process-depth pin (not model tier).
  // HEAVY was a historical mis-emit (tier name stuffed into track) — pin depth only.
  if (!DEPTH_BAND_VALUES.includes(band.depth)) {
    const err = new Error(
      `triage handoff emit: depth ${String(band.depth)} is not a pin token ` +
        `(expected one of ${DEPTH_BAND_VALUES.join('|')})`,
    );
    err.name = 'TriageLockSchemaError';
    err.code = 'TRIAGE_LOCK_SCHEMA';
    throw err;
  }
  return Object.freeze({
    triage_track: band.depth,
    triage: Object.freeze({
      locked: true,
      tier: band.tier,
      depth: band.depth,
      rationale: band.rationale,
      source: band.source,
      lockedAt: band.lockedAt,
    }),
  });
}

/**
 * Merge triage emit into a foreman.config.json-shaped object (docs block preserved).
 * @param {object} [baseConfig]
 * @param {unknown} hostOrLock
 * @returns {object}
 */
export function mergeTriageIntoForemanConfig(baseConfig = {}, hostOrLock) {
  const emit = buildHandoffTriageEmit(hostOrLock);
  const base = baseConfig && typeof baseConfig === 'object' ? baseConfig : {};
  return {
    ...base,
    triage_track: emit.triage_track,
    triage: emit.triage,
  };
}

/**
 * True when a value is a Foreman-consumable triage_track string (depth pin or
 * known legacy alias). Wave 4 inherit (`foreman-wire.normalizeInheritedDepth`)
 * is the live fan-out mapper; this predicate stays compatible for emit checks.
 * @param {unknown} track
 * @returns {boolean}
 */
export function isForemanTriageTrack(track) {
  if (typeof track !== 'string' || !track.trim()) return false;
  const t = track.trim().toUpperCase().replace(/_/g, '-');
  // Pin depths + aliases accepted on inherit input (see foreman-wire.mjs).
  return (
    t === 'FULL' ||
    t === 'LITE' ||
    t === 'LIGHT' ||
    t === 'SPIKE' || // B3 operator pin (first-class)
    t === 'SPIKE-FIRST' ||
    t === 'SPIKEFIRST' ||
    t === 'HEAVY' || // legacy mis-emit still recognized on inherit input
    t === 'MID' ||
    t === 'STANDARD'
  );
}

/**
 * Assert emit shape matches the Foreman consumer contract (for tests + Stage-2).
 * @param {unknown} emitOrConfig
 * @returns {true}
 */
export function assertForemanConsumerShape(emitOrConfig) {
  if (!emitOrConfig || typeof emitOrConfig !== 'object') {
    const err = new Error('triage handoff: emit must be an object');
    err.code = 'TRIAGE_HANDOFF_SHAPE';
    throw err;
  }
  const o = /** @type {Record<string, unknown>} */ (emitOrConfig);
  if (!isForemanTriageTrack(o.triage_track)) {
    const err = new Error(
      `triage handoff: triage_track must be a Foreman-consumable depth string, got ${String(o.triage_track)}`,
    );
    err.code = 'TRIAGE_HANDOFF_SHAPE';
    throw err;
  }
  const triage = o.triage;
  if (!triage || typeof triage !== 'object') {
    const err = new Error('triage handoff: triage object with {tier, depth} is required (Wave 3)');
    err.code = 'TRIAGE_HANDOFF_SHAPE';
    throw err;
  }
  const t = /** @type {Record<string, unknown>} */ (triage);
  if (!isModelTier(t.tier) && !normalizeTier(t.tier)) {
    const err = new Error(`triage handoff: triage.tier invalid (${String(t.tier)})`);
    err.code = 'TRIAGE_HANDOFF_SHAPE';
    throw err;
  }
  if (!isProcessDepth(t.depth) && !normalizeDepth(t.depth)) {
    const err = new Error(`triage handoff: triage.depth invalid (${String(t.depth)})`);
    err.code = 'TRIAGE_HANDOFF_SHAPE';
    throw err;
  }
  // Pin: triage_track must equal pin depth (not model tier).
  const depthPin =
    canonicalizeDepth(t.depth) ??
    (isProcessDepth(t.depth) ? t.depth : normalizeDepth(t.depth));
  const trackPin = legacyBandToDepth(o.triage_track);
  if (depthPin && trackPin && depthPin !== trackPin) {
    // Allow legacy HEAVY track only when depth is FULL (historical mis-emit).
    const rawTrack = String(o.triage_track).toUpperCase();
    if (!(rawTrack === 'HEAVY' && depthPin === DEPTH_BANDS.FULL)) {
      const err = new Error(
        `triage handoff: triage_track (${String(o.triage_track)}) disagrees with triage.depth (${String(t.depth)})`,
      );
      err.code = 'TRIAGE_HANDOFF_SHAPE';
      throw err;
    }
  }
  return true;
}

export {
  DEPTH_BANDS,
  MODEL_TIERS,
  recommend,
  getLockedBand,
  applyLock,
  createLockRecord,
  lockFromHeadless,
  lockFromInteractive,
};

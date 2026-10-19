// src/run-config.mjs — Wave 5 (2026-09-04, journal 0010): source-level configuration
// defaults and operational handling for the relevance/honesty knobs.
//
// Waves 3 and 4 each own their default (DEFAULT_RELEVANCE_FLOOR, DEFAULT_CORPUS_
// RELEVANCE_MIN) and each REFUSES an out-of-bounds value at its own boundary. What the
// run itself lacked was ONE source-level place that resolves the operator's overrides
// into a single frozen config — so the CLI (and any other host) consumes resolved,
// validated numbers instead of scattering `opts.x ?? DEFAULT` at every call site.
// This module is that place:
//
//   - `relevance_floor` and `corpus_relevance_min` are NAMED numeric bounds on [0,1]
//     (the plan's boundedness gate). A value outside the bound — NaN, negative,
//     above 1, or a non-number — is REFUSED outright with a TypeError naming the
//     bound: an unnamed bound cannot be tested, and a silently-clamped one lies.
//   - seed exemption is BY CONSTRUCTION, not a knob: `seed_exemption` is always true
//     and an attempt to switch it off is refused. The 0010 run lost ten of twelve
//     seeds precisely because nothing made their retention non-negotiable.
//   - exclusions stay INSPECTABLE by construction: `inspectable_exclusions` is always
//     true (refusing the off switch), and combineInspectableExclusions merges the
//     run's PRISMA exclusion records (snowball + relevance screening) into the ONE
//     schema-validated record the run writes and PRISMA accounting consumes.
//
// Pure and deterministic: no network, no model, no clock, no new dependency.

import { DEFAULT_RELEVANCE_FLOOR } from './relevance.mjs';
import { DEFAULT_CORPUS_RELEVANCE_MIN } from './run-summary.mjs';
import { validateSchema } from './validateSchema.mjs';

export const RUN_CONFIG_VERSION = 'litreview-run-config/1';

/**
 * The source-level defaults — sourced from the module that OWNS each bound (Wave 3
 * owns the floor, Wave 4 owns the minimum), never re-declared as loose literals.
 */
export const DEFAULT_RUN_CONFIG = Object.freeze({
  version: RUN_CONFIG_VERSION,
  relevance_floor: DEFAULT_RELEVANCE_FLOOR,
  corpus_relevance_min: DEFAULT_CORPUS_RELEVANCE_MIN,
  seed_exemption: true,
  inspectable_exclusions: true,
});

/** Refuse a value outside the named [0,1] bound — the plan's boundedness refusal path. */
function resolveUnitInterval(name, value, fallback) {
  if (value === null || value === undefined) return fallback;
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    throw new TypeError(
      `resolveRunConfig: ${name} must be a number in the named bound [0,1], got ${JSON.stringify(value)} — refused (an unnamed bound cannot be tested)`,
    );
  }
  return value;
}

/** Refuse switching off an invariant that holds by construction. */
function resolveInvariantTrue(name, value, why) {
  if (value === null || value === undefined || value === true) return true;
  throw new TypeError(`resolveRunConfig: ${name} is not configurable — ${why}`);
}

/**
 * Resolve the operator's overrides into the one frozen run configuration.
 *
 * `relevanceFloor` / `corpusRelevanceMin`: null/undefined take the source-level
 * default; anything else must sit inside the named [0,1] bound or is refused with a
 * TypeError (never clamped, never NaN-propagated). `seedExemption` /
 * `inspectableExclusions` hold by construction: only true (or absent) is accepted.
 *
 * @param {object} [overrides]
 * @param {number|null} [overrides.relevanceFloor] Wave-3 hard relevance floor.
 * @param {number|null} [overrides.corpusRelevanceMin] Wave-4 honesty minimum.
 * @param {boolean|null} [overrides.seedExemption] Must be true/absent — seeds are exempt by construction.
 * @param {boolean|null} [overrides.inspectableExclusions] Must be true/absent — exclusions stay inspectable.
 * @returns {typeof DEFAULT_RUN_CONFIG} a frozen resolved config.
 */
export function resolveRunConfig({
  relevanceFloor = null,
  corpusRelevanceMin = null,
  seedExemption = null,
  inspectableExclusions = null,
} = {}) {
  return Object.freeze({
    version: RUN_CONFIG_VERSION,
    relevance_floor: resolveUnitInterval('relevance_floor', relevanceFloor, DEFAULT_RELEVANCE_FLOOR),
    corpus_relevance_min: resolveUnitInterval('corpus_relevance_min', corpusRelevanceMin, DEFAULT_CORPUS_RELEVANCE_MIN),
    seed_exemption: resolveInvariantTrue(
      'seed_exemption', seedExemption,
      'seeds are relevance-exempt by construction (the 0010 lesson); the exemption has no off switch',
    ),
    inspectable_exclusions: resolveInvariantTrue(
      'inspectable_exclusions', inspectableExclusions,
      'every exclusion is recorded with its reason and details; silent exclusion has no off switch',
    ),
  });
}

/**
 * Merge the run's PRISMA exclusion records — snowball's own exclusions and the
 * relevance screening's off-topic exclusions — into the ONE inspectable,
 * schema-validated record the run writes (prisma-exclusions.json) and PRISMA
 * accounting consumes. Order is preserved: records in argument order, entries in
 * record order. A malformed record is refused: an uninspectable exclusion log is
 * the exact silence 0010 shipped.
 *
 * @param {...{ exclusions: object[] }} records PRISMA exclusion records, in run order.
 * @returns {{ exclusions: object[] }} one combined, schema-valid record (new object).
 */
export function combineInspectableExclusions(...records) {
  const exclusions = [];
  for (const record of records) {
    if (record === null || typeof record !== 'object' || !Array.isArray(record.exclusions)) {
      throw new TypeError(
        'combineInspectableExclusions: every record must carry an exclusions array — refused (exclusions must stay inspectable)',
      );
    }
    for (const e of record.exclusions) exclusions.push({ ...e });
  }
  const combined = { exclusions };
  validateSchema(combined, 'PrismaExclusions');
  return combined;
}

/**
 * (2026-09-05, Grok review F7) `--max-papers 0` means zero non-seeds — not the default.
 * Any non-negative integer is honored; absent / unparsable falls back to the default.
 */
export function parseMaxPapers(raw, fallback = 6) {
  if (raw === undefined || raw === null || String(raw).trim() === '') return fallback;
  const n = Number(String(raw).trim());
  return Number.isInteger(n) && n >= 0 ? n : fallback;
}

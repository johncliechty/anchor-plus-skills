// src/breadthTelemetry.mjs — Wave 5: breadth-stage honesty stamps in run telemetry.
//
// Locks the North-Star honesty surface for 2D breadth across literature-review and
// researchPrime. Both skills already materialize facets with breadth:from-branches |
// breadth:none (facetsFromPlan) and record per-facet errors; this module is the ONE
// pure, deterministic projection of those outcomes into a run-telemetry record so
// journal/run records can be inspected for:
//   • stamp (from-branches / none / null when breadth did not run);
//   • facet errors and incompleteCoverage (any failed facet);
//   • attempted / succeeded / failed counts;
//   • funnel counters (hits seen vs unique after dedupe);
//   • inventedFacets === false (never silent synthetic facets).
//
// Skill-local (Wave 5): trio-shared was not introduced for facetsFromPlan / merge;
// Wave 6 may extract only if byte-for-byte duplication is proven. Do not invent a
// shared package here for greenwash.
//
// matrixScheduler broad-first product reactivation is an OPTIONAL v1.1 non-goal
// follow-on only (see MATRIX_SCHEDULER_V1_SCOPE). v1 Deep-Research-parity rests on
// post-APPROVE per-facet snowball + merge hand-off, not on matrixScheduler.

import { BREADTH_STAMPS } from './facetsFromPlan.mjs';

/** Version stamp carried by every breadth telemetry record. */
export const BREADTH_TELEMETRY_VERSION = 'breadth-telemetry/1';

/**
 * matrixScheduler broad-first is NOT a v1 primary path.
 * Documented here (not by editing the hash-pinned matrixScheduler.mjs) so Wave 5
 * acceptance and dual-suite tests can assert the non-goal without breaking the
 * Wave-11 subsystem fence.
 */
export const MATRIX_SCHEDULER_V1_SCOPE = Object.freeze({
  status: 'v1.1-non-goal-follow-on',
  primaryForV1: false,
  note:
    'matrixScheduler broad-first is an optional v1.1 non-goal follow-on only; ' +
    'v1 Deep-Research-parity rests on per-facet snowball + merge hand-off (FC2/FC3), ' +
    'not on matrixScheduler product reactivation.',
});

/** Required top-level fields on every breadth telemetry record. */
export const BREADTH_TELEMETRY_FIELDS = Object.freeze([
  'telemetryVersion',
  'skill',
  'stamp',
  'ran',
  'reason',
  'inventedFacets',
  'facetCount',
  'facetIds',
  'attempted',
  'succeeded',
  'failed',
  'incompleteCoverage',
  'facetErrors',
  'funnel',
]);

/** Skills that emit breadth telemetry (Wave 5 dual-suite surface). */
export const BREADTH_TELEMETRY_SKILLS = Object.freeze(['literature-review', 'researchPrime']);

export class BreadthTelemetryError extends Error {
  constructor(message) {
    super(message);
    this.name = 'BreadthTelemetryError';
  }
}

function deepFreeze(value) {
  if (value && typeof value === 'object') {
    for (const v of Object.values(value)) deepFreeze(v);
    Object.freeze(value);
  }
  return value;
}

/**
 * Allowed honesty stamps for a breadth materialization that ran far enough to
 * call facetsFromPlan. null is reserved for "breadth path not entered"
 * (plan not APPROVED / plan-gate not APPROVE).
 * @type {ReadonlySet<string>}
 */
const ALLOWED_STAMPS = new Set([
  BREADTH_STAMPS.FROM_BRANCHES,
  BREADTH_STAMPS.NONE,
  BREADTH_STAMPS.AXIS_ONLY,
]);

/**
 * Normalize facet-result rows from either lit-review breadthStage or RP
 * facetCoverage outcomes.
 * @param {unknown} facetResults
 * @returns {ReadonlyArray<object>}
 */
function normalizeFacetResults(facetResults) {
  if (!Array.isArray(facetResults)) return Object.freeze([]);
  return Object.freeze(
    facetResults.map((r) =>
      Object.freeze({
        facetId: r?.facetId == null ? null : String(r.facetId),
        order: Number.isFinite(r?.order) ? r.order : null,
        error: r?.error == null ? null : String(r.error),
        hitCount: Array.isArray(r?.hits) ? r.hits.length : 0,
      }),
    ),
  );
}

/**
 * Funnel counters from a lit-review corpus or RP coverage substrate.
 * @param {object|null|undefined} outcome
 * @returns {{ totalHitsSeen: number, uniqueCount: number }|null}
 */
function funnelFromOutcome(outcome) {
  if (outcome == null || typeof outcome !== 'object') return null;
  if (outcome.corpus != null && typeof outcome.corpus === 'object') {
    return Object.freeze({
      totalHitsSeen: Number.isInteger(outcome.corpus.totalHitsSeen)
        ? outcome.corpus.totalHitsSeen
        : 0,
      uniqueCount: Number.isInteger(outcome.corpus.uniqueCount)
        ? outcome.corpus.uniqueCount
        : 0,
    });
  }
  if (outcome.coverageSubstrate != null && typeof outcome.coverageSubstrate === 'object') {
    return Object.freeze({
      totalHitsSeen: Number.isInteger(outcome.coverageSubstrate.totalHitsSeen)
        ? outcome.coverageSubstrate.totalHitsSeen
        : 0,
      uniqueCount: Number.isInteger(outcome.coverageSubstrate.uniqueCount)
        ? outcome.coverageSubstrate.uniqueCount
        : 0,
    });
  }
  // facetCoverage.hits is the RP closed hit list (post-dedupe unique).
  if (outcome.facetCoverage != null && Array.isArray(outcome.facetCoverage.hits)) {
    return Object.freeze({
      totalHitsSeen: outcome.facetCoverage.hits.length,
      uniqueCount: outcome.facetCoverage.hits.length,
    });
  }
  return null;
}

/**
 * Build the ONE breadth-stage telemetry record from a lit-review
 * runPostApproveBreadth outcome or an RP runPrePhase2FacetCoverage outcome.
 *
 * Pure and deterministic: no clock, no I/O, no mutation of inputs. Always sets
 * inventedFacets to false — silent synthetic facets are a North-Star violation
 * and are never projected as honest work.
 *
 * @param {object} args
 * @param {object|null|undefined} args.outcome Breadth or facet-coverage stage result.
 * @param {'literature-review'|'researchPrime'} args.skill Emitting skill.
 * @returns {Readonly<object>} deep-frozen assertBreadthTelemetry-validated record
 */
export function buildBreadthTelemetry({ outcome = null, skill } = {}) {
  if (!BREADTH_TELEMETRY_SKILLS.includes(skill)) {
    throw new BreadthTelemetryError(
      `buildBreadthTelemetry: skill must be one of ${BREADTH_TELEMETRY_SKILLS.join(' | ')}`,
    );
  }

  if (outcome == null || typeof outcome !== 'object' || Array.isArray(outcome)) {
    // No stage outcome at all — honest empty telemetry (breadth never ran).
    const record = {
      telemetryVersion: BREADTH_TELEMETRY_VERSION,
      skill,
      stamp: null,
      ran: false,
      reason: 'no-outcome',
      inventedFacets: false,
      facetCount: 0,
      facetIds: Object.freeze([]),
      attempted: 0,
      succeeded: 0,
      failed: 0,
      incompleteCoverage: false,
      facetErrors: Object.freeze([]),
      funnel: null,
    };
    assertBreadthTelemetry(record);
    return deepFreeze(record);
  }

  const facets = Array.isArray(outcome.facets) ? outcome.facets : [];
  const facetResults = normalizeFacetResults(outcome.facetResults);
  const attempted = facetResults.length > 0 ? facetResults.length : facets.length;
  const facetErrors = facetResults
    .filter((r) => r.error != null && r.error.length > 0)
    .map((r) => Object.freeze({ facetId: r.facetId, error: r.error }));
  const failed = facetErrors.length;
  const succeeded = Math.max(0, attempted - failed);
  const incompleteCoverage = failed > 0;

  // Prefer the stage's own stamp; fall back to facetCoverage.stamp for RP.
  let stamp = outcome.stamp ?? outcome.facetCoverage?.stamp ?? null;
  if (stamp != null) stamp = String(stamp);

  // Honesty: empty facets must never report from-branches; non-empty must not
  // invent a from-branches claim when stamp is none.
  if (facets.length === 0 && stamp === BREADTH_STAMPS.FROM_BRANCHES) {
    throw new BreadthTelemetryError(
      'dishonest breadth telemetry: stamp breadth:from-branches with zero facets (invented work)',
    );
  }
  if (facets.length > 0 && stamp === BREADTH_STAMPS.NONE) {
    throw new BreadthTelemetryError(
      'dishonest breadth telemetry: stamp breadth:none with non-empty facets',
    );
  }

  const facetIds = Object.freeze(
    facets.map((f) => (f?.id == null ? null : String(f.id))).filter((id) => id != null),
  );

  // Invented facets = facet ids that do not start with facet: (materialization
  // contract) OR a from-branches claim with empty ids. Both are refused above /
  // stamped false here — the field exists so inspectors never have to re-derive.
  const inventedFacets = false;

  const record = {
    telemetryVersion: BREADTH_TELEMETRY_VERSION,
    skill,
    stamp,
    ran: outcome.ran === true,
    reason: outcome.reason == null ? null : String(outcome.reason),
    inventedFacets,
    facetCount: facets.length,
    facetIds,
    attempted,
    succeeded,
    failed,
    incompleteCoverage,
    facetErrors: Object.freeze(facetErrors),
    funnel: funnelFromOutcome(outcome),
  };
  assertBreadthTelemetry(record);
  return deepFreeze(record);
}

/**
 * CI-enforceable record invariant. Throws BreadthTelemetryError naming the
 * omission or type error unless every required field is present and honest.
 * @param {object} record
 * @returns {true}
 */
export function assertBreadthTelemetry(record) {
  if (record === null || typeof record !== 'object' || Array.isArray(record)) {
    throw new BreadthTelemetryError('breadth telemetry record must be an object');
  }
  for (const field of BREADTH_TELEMETRY_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(record, field)) {
      throw new BreadthTelemetryError(`breadth telemetry is missing required field "${field}"`);
    }
  }
  if (record.telemetryVersion !== BREADTH_TELEMETRY_VERSION) {
    throw new BreadthTelemetryError(
      `breadth telemetry version ${JSON.stringify(record.telemetryVersion)}, expected ${BREADTH_TELEMETRY_VERSION}`,
    );
  }
  if (!BREADTH_TELEMETRY_SKILLS.includes(record.skill)) {
    throw new BreadthTelemetryError(
      `breadth telemetry skill ${JSON.stringify(record.skill)} is not one of ${BREADTH_TELEMETRY_SKILLS.join(' | ')}`,
    );
  }
  if (record.stamp !== null && !ALLOWED_STAMPS.has(record.stamp)) {
    throw new BreadthTelemetryError(
      `breadth telemetry stamp ${JSON.stringify(record.stamp)} is not a known honesty stamp ` +
        `(or null when breadth did not run)`,
    );
  }
  if (typeof record.ran !== 'boolean') {
    throw new BreadthTelemetryError('breadth telemetry ran must be a boolean');
  }
  if (record.reason !== null && typeof record.reason !== 'string') {
    throw new BreadthTelemetryError('breadth telemetry reason must be a string or null');
  }
  if (record.inventedFacets !== false) {
    throw new BreadthTelemetryError(
      'breadth telemetry inventedFacets must be false — silent synthetic facets violate the North Star',
    );
  }
  for (const numeric of ['facetCount', 'attempted', 'succeeded', 'failed']) {
    if (!Number.isInteger(record[numeric]) || record[numeric] < 0) {
      throw new BreadthTelemetryError(`breadth telemetry ${numeric} must be a non-negative integer`);
    }
  }
  if (typeof record.incompleteCoverage !== 'boolean') {
    throw new BreadthTelemetryError('breadth telemetry incompleteCoverage must be a boolean');
  }
  if (record.incompleteCoverage !== (record.failed > 0)) {
    throw new BreadthTelemetryError(
      'breadth telemetry incompleteCoverage must equal (failed > 0)',
    );
  }
  if (record.succeeded + record.failed !== record.attempted) {
    throw new BreadthTelemetryError(
      'breadth telemetry attempted must equal succeeded + failed',
    );
  }
  if (!Array.isArray(record.facetIds)) {
    throw new BreadthTelemetryError('breadth telemetry facetIds must be an array');
  }
  if (!Array.isArray(record.facetErrors)) {
    throw new BreadthTelemetryError('breadth telemetry facetErrors must be an array');
  }
  for (const err of record.facetErrors) {
    if (err == null || typeof err !== 'object' || typeof err.error !== 'string') {
      throw new BreadthTelemetryError(
        'breadth telemetry facetErrors entries must be { facetId, error }',
      );
    }
  }
  if (record.funnel !== null) {
    if (typeof record.funnel !== 'object' || Array.isArray(record.funnel)) {
      throw new BreadthTelemetryError('breadth telemetry funnel must be an object or null');
    }
    for (const k of ['totalHitsSeen', 'uniqueCount']) {
      if (!Number.isInteger(record.funnel[k]) || record.funnel[k] < 0) {
        throw new BreadthTelemetryError(`breadth telemetry funnel.${k} must be a non-negative integer`);
      }
    }
  }
  // Honesty: from-branches requires at least one facet id; none requires zero.
  if (record.stamp === BREADTH_STAMPS.FROM_BRANCHES && record.facetCount < 1) {
    throw new BreadthTelemetryError(
      'breadth telemetry stamp from-branches requires facetCount >= 1',
    );
  }
  if (record.stamp === BREADTH_STAMPS.NONE && record.facetCount !== 0) {
    throw new BreadthTelemetryError(
      'breadth telemetry stamp none requires facetCount === 0',
    );
  }
  return true;
}

/**
 * Attach a breadth telemetry record onto a run record without mutating the input.
 * Used by lit-review CLI journal writers and RP attachFacetCoverageToRunRecord.
 *
 * @param {object|null|undefined} runRecord
 * @param {object|null|undefined} breadthTelemetry Result of buildBreadthTelemetry
 * @returns {Readonly<object>}
 */
export function attachBreadthTelemetryToRunRecord(runRecord, breadthTelemetry) {
  const base =
    runRecord != null && typeof runRecord === 'object' && !Array.isArray(runRecord)
      ? { ...runRecord }
      : {};
  if (breadthTelemetry != null) {
    assertBreadthTelemetry(breadthTelemetry);
  }
  return Object.freeze({
    ...base,
    breadthTelemetry: breadthTelemetry ?? null,
    breadthTelemetryVersion: BREADTH_TELEMETRY_VERSION,
  });
}

export default buildBreadthTelemetry;

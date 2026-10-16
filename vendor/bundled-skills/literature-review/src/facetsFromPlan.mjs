// src/facetsFromPlan.mjs — Wave 1: pure Facet materialization from an approved
// PlanArtifact (GAP C). Skill-local first home under lit-review src/; pure helper
// with zero I/O so researchPrime (and any other consumer) can import the same
// mapping without lit-review pipeline coupling.
//
// Wave 5–6 SHIP (2026-07-22): remains skill-local. Wave 6 audit: no byte-for-byte
// duplication to extract — researchPrime/bin/facet-coverage.mjs is a thin import
// surface that loads this module (and rpFacetCoverage) from lit-review; no
// trio-shared/breadth package. Breadth honesty stamps feed breadthTelemetry.mjs.
//
// Decision table (v1, fail-closed — never invent silent facets):
//   • N≥1 branches that yield a usable question → N Facet records, stamp
//     breadth:from-branches; each facet traces to a sourceBranchId.
//   • empty / missing / all-unusable branches → facets=[], stamp breadth:none.
//     Axis text (scope.axis) is NEVER reified as a Facet record (done-when:
//     never invents facets when branches are empty). The breadth:axis-only
//     token is exported for vocabulary completeness with the frozen plan stamp
//     list but is not emitted by this mapper in v1.
//
// Facet shape: { id, question, sourceBranchId, order }
// Result shape:  { facets, stamp }

/** @typedef {{ id: string, question: string, sourceBranchId: string, order: number }} Facet */

/**
 * Honesty stamps for the breadth facet-materialization stage.
 * @type {Readonly<{ FROM_BRANCHES: string, AXIS_ONLY: string, NONE: string }>}
 */
export const BREADTH_STAMPS = Object.freeze({
  FROM_BRANCHES: 'breadth:from-branches',
  /** Listed in the frozen plan stamp vocabulary; not emitted by v1 (no axis→facet). */
  AXIS_ONLY: 'breadth:axis-only',
  NONE: 'breadth:none',
});

/** Module identity stamp for consumers / telemetry. */
export const FACETS_FROM_PLAN_VERSION = 'facets-from-plan/1';

/**
 * Extract a usable facet question from a branch-like object. Prefer the
 * PlanArtifact field `question`; fall back to other common labels without
 * inventing free text.
 *
 * @param {unknown} branch
 * @returns {string|null} Non-empty trimmed question, or null when unusable.
 */
function branchQuestion(branch) {
  if (branch == null || typeof branch !== 'object' || Array.isArray(branch)) {
    return null;
  }
  const candidates = [branch.question, branch.text, branch.label];
  for (const c of candidates) {
    if (typeof c === 'string') {
      const q = c.trim();
      if (q.length > 0) return q;
    }
  }
  if (branch.id != null && typeof branch.id !== 'object') {
    const asId = String(branch.id).trim();
    if (asId.length > 0) return asId;
  }
  return null;
}

/**
 * Stable sourceBranchId for a branch at array index `index`.
 * Prefer an explicit branch.id when present; otherwise path-stable branch:${index}.
 *
 * @param {object} branch
 * @param {number} index
 * @returns {string}
 */
function sourceBranchIdFor(branch, index) {
  if (branch != null && typeof branch === 'object' && !Array.isArray(branch)) {
    if (typeof branch.id === 'string' && branch.id.trim().length > 0) {
      return branch.id.trim();
    }
    if (typeof branch.id === 'number' && Number.isFinite(branch.id)) {
      return String(branch.id);
    }
  }
  return `branch:${index}`;
}

/**
 * Stable facet order key: branch.order when it is a finite number; else array index.
 *
 * @param {object} branch
 * @param {number} index
 * @returns {number}
 */
function orderFor(branch, index) {
  if (
    branch != null &&
    typeof branch === 'object' &&
    !Array.isArray(branch) &&
    typeof branch.order === 'number' &&
    Number.isFinite(branch.order)
  ) {
    return branch.order;
  }
  return index;
}

/**
 * Materialize Facet records from an approved PlanArtifact (or any plan-shaped
 * object exposing `branches`). Pure: no I/O, does not mutate `plan`, returns
 * frozen structures, deterministic for the same plan shape.
 *
 * @param {object|null|undefined} plan PlanArtifact-like object (uses `.branches`).
 * @returns {{ facets: ReadonlyArray<Facet>, stamp: string }}
 */
export function facetsFromPlan(plan) {
  const rawBranches =
    plan != null && typeof plan === 'object' && !Array.isArray(plan) && Array.isArray(plan.branches)
      ? plan.branches
      : null;

  if (rawBranches == null || rawBranches.length === 0) {
    return Object.freeze({
      facets: Object.freeze([]),
      stamp: BREADTH_STAMPS.NONE,
    });
  }

  /** @type {Facet[]} */
  const built = [];
  for (let i = 0; i < rawBranches.length; i++) {
    const branch = rawBranches[i];
    const question = branchQuestion(branch);
    if (question == null) continue;

    const sourceBranchId = sourceBranchIdFor(branch, i);
    const order = orderFor(branch, i);
    const id = `facet:${sourceBranchId}`;

    built.push(
      Object.freeze({
        id,
        question,
        sourceBranchId,
        order,
      }),
    );
  }

  // Stable order: by order ascending, then by emission index (id) for ties.
  built.sort((a, b) => {
    if (a.order !== b.order) return a.order - b.order;
    if (a.id < b.id) return -1;
    if (a.id > b.id) return 1;
    return 0;
  });

  if (built.length === 0) {
    // Branches present but none usable — honest empty, never invent from axis.
    return Object.freeze({
      facets: Object.freeze([]),
      stamp: BREADTH_STAMPS.NONE,
    });
  }

  return Object.freeze({
    facets: Object.freeze(built),
    stamp: BREADTH_STAMPS.FROM_BRANCHES,
  });
}

export default facetsFromPlan;

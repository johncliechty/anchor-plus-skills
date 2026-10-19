// src/rpFacetCoverage.mjs — Wave 4: researchPrime pre-Phase-2 facet coverage stage.
//
// After the plan gate APPROVEs, gather evidence/context per plan facet (coverage
// axes derived from PlanArtifact.branches) into a coverage substrate — WITHOUT
// treating facets as answer-branches. Oranges foresight still prunes answer
// branches only (see answerPlanForOranges / runOrangesOnAnswerBranches).
//
// Skill-local first home under lit-review src/ (same pattern as facetsFromPlan);
// researchPrime re-exports via bin/facet-coverage.mjs. Pure orchestration: no
// LLM seats, no REVIEW_FAMILY changes; gather is injectable (reuse search /
// snowball primitives via inject or defaultScopedFacetGather).
//
// facetCoverage shape: { facets, hits, stamp }
// Events prove ordering: facets materialized → gather → coverage recorded →
// phase2-ready BEFORE any Phase-2 depth/verification marker.

import { facetsFromPlan, BREADTH_STAMPS } from './facetsFromPlan.mjs';
import { defaultScopedFacetGather } from './breadthStage.mjs';
import {
  buildBreadthTelemetry,
  attachBreadthTelemetryToRunRecord,
} from './breadthTelemetry.mjs';

export const FACET_COVERAGE_VERSION = 'rp-facet-coverage/1';

/** Plan-gate decision that unlocks pre-Phase-2 facet coverage. */
export const FACET_COVERAGE_REQUIRES_DECISION = 'APPROVE';

/**
 * Ordered event types for ordering/integration tests + run telemetry.
 * @type {Readonly<{
 *   FACETS_MATERIALIZED: string,
 *   FACET_GATHER_START: string,
 *   FACET_GATHER_DONE: string,
 *   COVERAGE_SKIPPED: string,
 *   COVERAGE_RECORDED: string,
 *   PHASE2_READY: string,
 * }>}
 */
export const FACET_COVERAGE_EVENTS = Object.freeze({
  FACETS_MATERIALIZED: 'facets-materialized',
  FACET_GATHER_START: 'facet-gather-start',
  FACET_GATHER_DONE: 'facet-gather-done',
  COVERAGE_SKIPPED: 'coverage-skipped',
  COVERAGE_RECORDED: 'coverage-recorded',
  PHASE2_READY: 'phase2-ready',
});

/**
 * Answer-branch plan view for Oranges foresight.
 *
 * Facets are coverage axes; answer branches are the plan's candidate research
 * branches (with economics when present). This helper NEVER projects
 * facetCoverage.facets into the oranges input — facets are not modeled or
 * pruned as answer branches.
 *
 * @param {object|null|undefined} plan PlanArtifact or RP plan-shaped object
 * @returns {{ branches: ReadonlyArray<object> }}
 */
export function answerPlanForOranges(plan) {
  const raw =
    plan != null && typeof plan === 'object' && !Array.isArray(plan) && Array.isArray(plan.branches)
      ? plan.branches
      : [];
  return Object.freeze({
    branches: Object.freeze(
      raw.map((b) => {
        if (b != null && typeof b === 'object' && !Array.isArray(b)) {
          return Object.freeze({ ...b });
        }
        return Object.freeze({ value: b });
      }),
    ),
  });
}

/**
 * Run Oranges foresight strictly on answer branches — never on facet records.
 * Callers pass the real runForesight from researchPrime/bin/oranges.mjs (or a
 * test double); this wrapper only supplies answerPlanForOranges(plan).
 *
 * @param {object|null|undefined} plan
 * @param {(plan: { branches: ReadonlyArray<object> }) => object} runForesight
 * @returns {object} foresight receipt
 */
export function runOrangesOnAnswerBranches(plan, runForesight) {
  if (typeof runForesight !== 'function') {
    throw new TypeError('runOrangesOnAnswerBranches requires runForesight(plan)');
  }
  return runForesight(answerPlanForOranges(plan));
}

/**
 * True when `candidate` looks like a Facet record (coverage axis), not an
 * answer-branch with oranges economics. Used by isolation tests.
 *
 * @param {unknown} candidate
 * @returns {boolean}
 */
export function isFacetRecord(candidate) {
  if (candidate == null || typeof candidate !== 'object' || Array.isArray(candidate)) {
    return false;
  }
  return (
    typeof candidate.id === 'string' &&
    candidate.id.startsWith('facet:') &&
    typeof candidate.question === 'string' &&
    typeof candidate.sourceBranchId === 'string' &&
    Number.isFinite(candidate.order)
  );
}

/**
 * Merge per-facet gather hits into one ordered hit list (coverage substrate hits).
 * Order: facet.order ascending, then paperId / fallback index. Exact paperId
 * dedupe (first wins). Failed facets contribute nothing.
 *
 * @param {ReadonlyArray<object>} facetResults
 * @returns {{
 *   hits: ReadonlyArray<object>,
 *   totalHitsSeen: number,
 *   uniqueCount: number,
 * }}
 */
export function mergeCoverageHits(facetResults) {
  const results = Array.isArray(facetResults) ? [...facetResults] : [];
  results.sort((a, b) => {
    const oa = Number.isFinite(a?.order) ? a.order : 0;
    const ob = Number.isFinite(b?.order) ? b.order : 0;
    if (oa !== ob) return oa - ob;
    const idA = a?.facetId == null ? '' : String(a.facetId);
    const idB = b?.facetId == null ? '' : String(b.facetId);
    return idA < idB ? -1 : idA > idB ? 1 : 0;
  });

  /** @type {object[]} */
  const ordered = [];
  let totalHitsSeen = 0;
  const seenPaperIds = new Set();

  for (const fr of results) {
    if (fr?.error) continue;
    const hits = Array.isArray(fr?.hits) ? fr.hits : [];
    const withKeys = hits.map((hit, idx) => {
      const paperId = hit?.paperId == null ? null : hit.paperId;
      const sortId =
        paperId != null && String(paperId).length > 0
          ? `paperId:${String(paperId)}`
          : `no-id:${fr.facetId}:${idx}`;
      return { hit, paperId, sortId, idx, facetId: fr.facetId, order: fr.order };
    });
    withKeys.sort((a, b) => {
      if (a.sortId < b.sortId) return -1;
      if (a.sortId > b.sortId) return 1;
      return a.idx - b.idx;
    });
    for (const row of withKeys) {
      totalHitsSeen += 1;
      if (row.paperId != null) {
        const key = `paperId:${String(row.paperId)}`;
        if (seenPaperIds.has(key)) continue;
        seenPaperIds.add(key);
      }
      ordered.push(
        Object.freeze({
          paperId: row.paperId,
          title: row.hit?.title ?? null,
          year: row.hit?.year ?? null,
          abstract: row.hit?.abstract ?? null,
          sourceFacetId: row.facetId,
          sourceFacetOrder: row.order,
          ...(row.hit && typeof row.hit === 'object'
            ? Object.fromEntries(
                Object.entries(row.hit).filter(
                  ([k]) => !['paperId', 'title', 'year', 'abstract'].includes(k),
                ),
              )
            : {}),
        }),
      );
    }
  }

  return Object.freeze({
    hits: Object.freeze(ordered),
    totalHitsSeen,
    uniqueCount: ordered.length,
  });
}

/**
 * Build the frozen facetCoverage record written into the RP run record.
 *
 * @param {ReadonlyArray<object>} facets
 * @param {ReadonlyArray<object>} hits
 * @param {string} stamp
 * @returns {{ facets: ReadonlyArray<object>, hits: ReadonlyArray<object>, stamp: string }}
 */
export function buildFacetCoverage(facets, hits, stamp) {
  return Object.freeze({
    facets: Object.freeze(Array.isArray(facets) ? [...facets] : []),
    hits: Object.freeze(Array.isArray(hits) ? [...hits] : []),
    stamp: stamp == null ? BREADTH_STAMPS.NONE : String(stamp),
  });
}

/**
 * Attach facetCoverage (+ optional merged substrate) onto a run record without
 * mutating the input. Phase-2+ consumers read `runRecord.facetCoverage` and
 * `runRecord.coverageSubstrate`.
 *
 * Wave 5: also projects a pure breadthTelemetry honesty stamp (from-branches /
 * none / facet errors / incompleteCoverage / funnel) so RP run records share
 * the same inspectable surface as lit-review journal/runs.
 *
 * @param {object|null|undefined} runRecord
 * @param {object} coverageOutcome Result of runPrePhase2FacetCoverage
 * @returns {object}
 */
export function attachFacetCoverageToRunRecord(runRecord, coverageOutcome) {
  const base =
    runRecord != null && typeof runRecord === 'object' && !Array.isArray(runRecord)
      ? { ...runRecord }
      : {};
  const withCoverage = Object.freeze({
    ...base,
    facetCoverage: coverageOutcome?.facetCoverage ?? null,
    coverageSubstrate: coverageOutcome?.coverageSubstrate ?? null,
    facetCoverageVersion: FACET_COVERAGE_VERSION,
  });
  // Wave 5: breadth honesty telemetry for dual-suite / run-record inspection.
  const breadthTelemetry = buildBreadthTelemetry({
    outcome: coverageOutcome ?? null,
    skill: 'researchPrime',
  });
  return attachBreadthTelemetryToRunRecord(withCoverage, breadthTelemetry);
}

/**
 * researchPrime pre-Phase-2 facet coverage stage.
 *
 * Gate: active only when planGateDecision === APPROVE (post plan gate).
 * Materializes facets via facetsFromPlan; gathers evidence/context per facet
 * (injectable gatherFacet; default = lit-review scoped snowball when seeds
 * present); writes facetCoverage into the returned outcome; marks Phase-2 ready
 * on the merged coverage substrate. Never calls oranges on facets.
 *
 * @param {object} args
 * @param {string|null|undefined} args.planGateDecision Gate-2 decision (`APPROVE` unlocks).
 * @param {object|null|undefined} args.plan Approved PlanArtifact / plan-shaped object.
 * @param {ReadonlyArray<object>|null|undefined} args.seeds Optional multi-seed set for default gather.
 * @param {(args: { facet: object, seeds: ReadonlyArray<object>, plan: object|null }) => Promise<object>} [args.gatherFacet]
 * @param {object} [args.options] Forwarded to defaultScopedFacetGather.
 * @param {(msg: string) => void} [args.log]
 * @returns {Promise<{
 *   version: string,
 *   ran: boolean,
 *   reason: string|null,
 *   stamp: string|null,
 *   facets: ReadonlyArray<object>,
 *   facetResults: ReadonlyArray<object>,
 *   facetCoverage: { facets: ReadonlyArray<object>, hits: ReadonlyArray<object>, stamp: string }|null,
 *   coverageSubstrate: { hits: ReadonlyArray<object>, totalHitsSeen: number, uniqueCount: number }|null,
 *   phase2Ready: boolean,
 *   events: ReadonlyArray<object>,
 * }>}
 */
export async function runPrePhase2FacetCoverage({
  planGateDecision,
  plan,
  seeds = [],
  gatherFacet,
  options = {},
  log = () => {},
} = {}) {
  const events = [];
  const push = (type, payload = {}) => {
    events.push(Object.freeze({ type, ...payload }));
  };

  const emptySubstrate = Object.freeze({
    hits: Object.freeze([]),
    totalHitsSeen: 0,
    uniqueCount: 0,
  });

  const skipBase = {
    version: FACET_COVERAGE_VERSION,
    ran: false,
    facets: Object.freeze([]),
    facetResults: Object.freeze([]),
    coverageSubstrate: emptySubstrate,
  };

  // Gate: pre-Phase-2 coverage does not run until the plan gate APPROVEs.
  if (planGateDecision !== FACET_COVERAGE_REQUIRES_DECISION) {
    push(FACET_COVERAGE_EVENTS.COVERAGE_SKIPPED, {
      reason: 'plan-gate-not-approved',
      planGateDecision: planGateDecision ?? null,
    });
    // Phase-2 path may still proceed without facet coverage (honest skip).
    push(FACET_COVERAGE_EVENTS.PHASE2_READY, {
      reason: 'plan-gate-not-approved',
      hasFacetCoverage: false,
    });
    log(
      `RP pre-Phase-2 facet coverage SKIPPED: planGateDecision is ${JSON.stringify(planGateDecision)} (requires ${FACET_COVERAGE_REQUIRES_DECISION}).`,
    );
    return Object.freeze({
      ...skipBase,
      reason: 'plan-gate-not-approved',
      stamp: null,
      facetCoverage: null,
      phase2Ready: true,
      events: Object.freeze(events),
    });
  }

  // facetsFromPlan first — never invent silent facets.
  const { facets, stamp } = facetsFromPlan(plan);
  push(FACET_COVERAGE_EVENTS.FACETS_MATERIALIZED, {
    stamp,
    facetCount: facets.length,
    facetIds: facets.map((f) => f.id),
  });
  log(`RP pre-Phase-2: facetsFromPlan → ${facets.length} facet(s), stamp ${stamp}.`);

  const seedList = Array.isArray(seeds) ? seeds : [];

  if (facets.length === 0) {
    // Honest no-breadth / axis stamp; no silent facets; existing Phase-2 proceeds.
    const facetCoverage = buildFacetCoverage([], [], stamp);
    push(FACET_COVERAGE_EVENTS.COVERAGE_SKIPPED, {
      reason: 'no-facets',
      stamp,
    });
    push(FACET_COVERAGE_EVENTS.COVERAGE_RECORDED, {
      stamp,
      facetCount: 0,
      hitCount: 0,
    });
    push(FACET_COVERAGE_EVENTS.PHASE2_READY, {
      reason: 'no-facets',
      hasFacetCoverage: true,
      stamp,
    });
    log(`RP pre-Phase-2: empty facets (${stamp}) — honest stamp; Phase-2 path proceeds unchanged.`);
    return Object.freeze({
      ...skipBase,
      reason: 'no-facets',
      stamp,
      facetCoverage,
      phase2Ready: true,
      events: Object.freeze(events),
    });
  }

  const gather =
    typeof gatherFacet === 'function'
      ? gatherFacet
      : (args) =>
          defaultScopedFacetGather({
            facet: args.facet,
            seeds: args.seeds,
            options,
          });

  log(`RP pre-Phase-2: per-facet evidence/context gather over ${facets.length} facet(s) (no oranges on facets).`);

  /** @type {object[]} */
  const facetResults = [];
  for (const facet of facets) {
    push(FACET_COVERAGE_EVENTS.FACET_GATHER_START, {
      facetId: facet.id,
      order: facet.order,
      question: facet.question,
    });
    log(
      `  coverage facet ${facet.id} (order ${facet.order}): gather; scope = ${JSON.stringify(facet.question)}`,
    );
    try {
      const gathered = await gather({ facet, seeds: seedList, plan });
      const hits = Array.isArray(gathered?.hits) ? gathered.hits : [];
      const record = Object.freeze({
        facetId: facet.id,
        order: facet.order,
        question: facet.question,
        sourceBranchId: facet.sourceBranchId,
        hits: Object.freeze([...hits]),
        error: null,
      });
      facetResults.push(record);
      push(FACET_COVERAGE_EVENTS.FACET_GATHER_DONE, {
        facetId: facet.id,
        hitCount: hits.length,
        error: null,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      const record = Object.freeze({
        facetId: facet.id,
        order: facet.order,
        question: facet.question,
        sourceBranchId: facet.sourceBranchId,
        hits: Object.freeze([]),
        error: message,
      });
      facetResults.push(record);
      push(FACET_COVERAGE_EVENTS.FACET_GATHER_DONE, {
        facetId: facet.id,
        hitCount: 0,
        error: message,
      });
      log(`  coverage facet ${facet.id} FAILED (honest): ${message}`);
    }
  }

  // Deterministic facetResults order by facet.order (not completion order).
  facetResults.sort((a, b) => {
    if (a.order !== b.order) return a.order - b.order;
    const idA = a.facetId == null ? '' : String(a.facetId);
    const idB = b.facetId == null ? '' : String(b.facetId);
    return idA < idB ? -1 : idA > idB ? 1 : 0;
  });

  const coverageSubstrate = mergeCoverageHits(facetResults);
  const facetCoverage = buildFacetCoverage(facets, coverageSubstrate.hits, stamp);

  push(FACET_COVERAGE_EVENTS.COVERAGE_RECORDED, {
    stamp,
    facetCount: facets.length,
    hitCount: coverageSubstrate.uniqueCount,
    totalHitsSeen: coverageSubstrate.totalHitsSeen,
  });
  // Phase-2 depth/verification starts only AFTER coverage is recorded.
  push(FACET_COVERAGE_EVENTS.PHASE2_READY, {
    reason: null,
    hasFacetCoverage: true,
    stamp,
    hitCount: coverageSubstrate.uniqueCount,
  });
  log(
    `RP pre-Phase-2 COMPLETE (${stamp}) — facetCoverage recorded (${facets.length} facet(s), ${coverageSubstrate.uniqueCount} hit(s)); Phase-2+ may proceed on merged substrate.`,
  );

  return Object.freeze({
    version: FACET_COVERAGE_VERSION,
    ran: true,
    reason: null,
    stamp,
    facets: Object.freeze([...facets]),
    facetResults: Object.freeze(facetResults),
    facetCoverage,
    coverageSubstrate,
    phase2Ready: true,
    events: Object.freeze(events),
  });
}

export default runPrePhase2FacetCoverage;

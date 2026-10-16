// bin/facet-coverage.mjs — Wave 4 (2D breadth): researchPrime pre-Phase-2 facet coverage seam.
//
// Inserts the post-plan-gate / pre-Phase-2 coverage stage into researchPrime's
// runtime surface without treating facets as answer-branches. Implementation
// lives skill-local in literature-review (src/rpFacetCoverage.mjs — same home as
// facetsFromPlan); this module is the RP-side import surface so Phase-2+ and
// oranges isolation can be driven from researchPrime without forking logic.
//
// Oranges (bin/oranges.mjs) continues to prune ANSWER branches only — call
// runOrangesOnAnswerBranches / answerPlanForOranges; never pass facet records
// into runForesight. REVIEW_FAMILY / verification seats are unchanged.
//
// Resolve literature-review via:
//   1. env LITREVIEW_ROOT (explicit checkout override), else
//   2. ~/.claude/skills/literature-review (deployed skill junction).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import { runForesight } from './oranges.mjs';

export const RP_FACET_COVERAGE_SEAM = 'researchPrime/facet-coverage/1';

/**
 * Resolve the literature-review skill root (realpath'd).
 * @returns {string}
 */
export function resolveLiteratureReviewRoot() {
  const candidate = process.env.LITREVIEW_ROOT
    ? path.resolve(process.env.LITREVIEW_ROOT)
    : path.join(os.homedir(), '.claude', 'skills', 'literature-review');
  let root = candidate;
  try {
    root = fs.realpathSync(candidate);
  } catch {
    // fall through with un-realpath'd candidate
  }
  const marker = path.join(root, 'src', 'rpFacetCoverage.mjs');
  if (!fs.existsSync(marker)) {
    throw new Error(
      `literature-review rpFacetCoverage not found at ${marker} — set LITREVIEW_ROOT ` +
        'to a literature-review checkout that includes Wave-4 src/rpFacetCoverage.mjs.',
    );
  }
  return root;
}

/** @type {Promise<object>|null} */
let _implPromise = null;

/**
 * Lazy-load the lit-review implementation (single import, cached).
 * @returns {Promise<object>}
 */
export async function loadFacetCoverageImpl() {
  if (_implPromise == null) {
    const root = resolveLiteratureReviewRoot();
    const href = pathToFileURL(path.join(root, 'src', 'rpFacetCoverage.mjs')).href;
    _implPromise = import(href);
  }
  return _implPromise;
}

/**
 * Pre-Phase-2 facet coverage after plan gate APPROVE.
 * @param {object} [args] See literature-review src/rpFacetCoverage.mjs runPrePhase2FacetCoverage
 */
export async function runPrePhase2FacetCoverage(args) {
  const impl = await loadFacetCoverageImpl();
  return impl.runPrePhase2FacetCoverage(args);
}

/** Answer-branch-only plan view for oranges (never facets). */
export async function answerPlanForOranges(plan) {
  const impl = await loadFacetCoverageImpl();
  return impl.answerPlanForOranges(plan);
}

/**
 * Run Oranges foresight on answer branches only, using researchPrime's real
 * runForesight. Facet coverage substrate is never supplied as branches.
 *
 * @param {object|null|undefined} plan
 * @returns {Promise<object>} foresight receipt
 */
export async function runOrangesOnAnswerBranches(plan) {
  const impl = await loadFacetCoverageImpl();
  return impl.runOrangesOnAnswerBranches(plan, runForesight);
}

/** Attach facetCoverage onto an RP run record. */
export async function attachFacetCoverageToRunRecord(runRecord, coverageOutcome) {
  const impl = await loadFacetCoverageImpl();
  return impl.attachFacetCoverageToRunRecord(runRecord, coverageOutcome);
}

/** Re-export constants via the implementation (after load). */
export async function getFacetCoverageConstants() {
  const impl = await loadFacetCoverageImpl();
  return Object.freeze({
    FACET_COVERAGE_VERSION: impl.FACET_COVERAGE_VERSION,
    FACET_COVERAGE_EVENTS: impl.FACET_COVERAGE_EVENTS,
    FACET_COVERAGE_REQUIRES_DECISION: impl.FACET_COVERAGE_REQUIRES_DECISION,
    BREADTH_STAMPS: (await import(
      pathToFileURL(path.join(resolveLiteratureReviewRoot(), 'src', 'facetsFromPlan.mjs')).href
    )).BREADTH_STAMPS,
    RP_FACET_COVERAGE_SEAM,
  });
}

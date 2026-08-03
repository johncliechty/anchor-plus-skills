// bin/dogfood.mjs — Wave 11 DOGFOOD SELF-RUN (Phase F).
//
// IMPLEMENTATION-PLAN Wave 11 / MASTER-PLAN Phase F done-when: "a dogfood self-run proves the dry +
// suspiciously-dry predicates." This module is that self-run: researchPrime drives its OWN Wave-7
// round-orchestration loop (bin/round.mjs) over a small, deterministic verification scenario — no live
// LLM, a scripted agent seam — and exercises, through the REAL source (never a re-implementation):
//   • the DRY-round predicate + the honest convergence tracker (G5/I7): a run that genuinely converges
//     after N consecutive NON-EMPTY dry rounds; and
//   • the SUSPICIOUSLY-DRY predicate (crit-7/I1): a HIGH-stakes run that reaches dry in < K rounds while
//     a high-severity finding is still unresolved fires the probe-or-dissent, and on a single-family
//     substrate emits the "shared-blind-spot UN-MITIGABLE" stamp (mitigated:false), never a mitigation
//     claim.
//
// REUSE, NOT FORK: every predicate comes from bin/round.mjs (orchestrateRound, makeConvergenceTracker,
// isDryRound/isEmptyRound, assessConvergenceHonesty, countUnresolvedHighSeverity) and every committed
// threshold (N/K/M) is read from the Wave-1 pre-registration via `loopThresholds` — this module chooses
// NO threshold of its own (I6). It is PURE except for that one threshold read; the scenario data is a
// fixed literal, so the self-run is deterministic and replayable.

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  orchestrateRound,
  makeConvergenceTracker,
  isDryRound,
  isEmptyRound,
  assessConvergenceHonesty,
  countUnresolvedHighSeverity,
  loopThresholds,
} from './round.mjs';

/** The North Star the dogfood loop verifies against (researchPrime verifying its own honest output). */
export const DOGFOOD_NORTH_STAR =
  'researchPrime returns an honestly-verified deliverable: every surviving claim is corroborated and ' +
  'no shared blind spot is presented as if it were closed';

/**
 * The single same-lineage substrate the default (non-Enhanced) dogfood runs on. One family ⇒ a
 * same-lineage probe reproduces a shared wrong consensus (I1), which is exactly what makes the
 * suspiciously-dry guard's un-mitigable stamp the HONEST outcome here.
 */
export const DOGFOOD_FAMILY = 'rp-default';

/**
 * The scripted adjudication agent — the injected seam standing in for the live sub-agents so the
 * self-run is deterministic (no clock, no randomness, no network). It mirrors the per-role contract the
 * round layer expects (Judge decides, Synthesizer steers, debate adjudicates a conflict), returning the
 * minimal valid shape for each role. A real run would pass a live `agent`; the default makes the dogfood
 * a true, hermetic self-run.
 */
export function dogfoodAgent() {
  return async (_prompt, opts = {}) => {
    const role = opts.role || 'other';
    if (role === 'judge') return { decision: 'NOT_CONVERGED', reasons: [] };
    if (role === 'synthesizer') return { lean: 'unknown', suggestions: [] };
    if (role === 'debate') return { survivor: DOGFOOD_FAMILY };
    return null;
  };
}

// A NON-EMPTY but DRY round: one same-lineage reviewer raises a single MINOR, AXIS-tracing nit — no new
// blocker (⇒ dry) and at least one finding (⇒ not empty). This is the convergence signal a genuine run
// emits once the substantive defects are resolved.
function dryReviews(round) {
  return [
    {
      reviewer: 'Skeptic',
      lineage: DOGFOOD_FAMILY,
      findings: [
        { topic: `residual wording nit r${round}`, severity: 'MINOR', traces_to_north_star: 'yes' },
      ],
    },
  ];
}

// The unresolved shared-blind-spot finding the single-family substrate CANNOT close (I1): a high-severity
// (BLOCKER) claim that every same-lineage reviewer co-misses the same way, so it survives to a fast dry.
function unresolvedBlindSpotFindings() {
  return [
    {
      topic: 'widely-repeated-but-false consensus claim',
      severity: 'BLOCKER',
      traces_to_north_star: 'yes',
      resolved: false,
    },
  ];
}

/**
 * Run the dogfood self-run and report what the real predicates did.
 *
 * @param {object} [o]
 * @param {Function} [o.agent]  the adjudication seam (default: the hermetic scripted agent)
 * @returns {Promise<{
 *   thresholds: {N:number,K:number,M:number},
 *   convergence: { converged:boolean, dryFired:boolean, rounds:number, dryStreak:number,
 *                  perRound:Array<{round:number,dry:boolean,empty:boolean}> },
 *   suspicious: { roundsToDry:number, unresolvedHighSeverity:number, fired:boolean,
 *                 singleFamily:?boolean, mitigated:?boolean, stamp:?string }
 * }>}
 */
export async function runDogfood({ agent = dogfoodAgent() } = {}) {
  const thresholds = loopThresholds(); // committed N/K/M (Wave-1 pre-registration; I6)

  // ── Self-run A — honest convergence: the DRY predicate + the I7 honest tracker ───────────────────
  // Drive real rounds until the tracker reports convergence after N consecutive non-empty dry rounds.
  const tracker = makeConvergenceTracker({ N: thresholds.N });
  const perRound = [];
  let converged = false;
  let dryFired = false;
  // Bound the loop generously above N so a regression that never converges terminates (and is then
  // visible as converged:false), rather than spinning.
  for (let r = 1; !converged && r <= thresholds.N + 3; r++) {
    const round = await orchestrateRound({
      agent,
      reviews: dryReviews(r),
      round: r,
      northStar: DOGFOOD_NORTH_STAR,
    });
    const dry = isDryRound(round);
    const empty = isEmptyRound(round);
    dryFired = dryFired || dry;
    perRound.push({ round: r, dry, empty });
    converged = tracker.observe(round).converged;
  }
  const trackerState = tracker.state();

  // ── Self-run B — suspiciously-dry: the probe-or-dissent predicate (crit-7/I1) ─────────────────────
  // A HIGH-stakes run reaches dry FAST (round 1, < K) while a high-severity finding is still unresolved
  // (> M). On the single-family substrate the only available probe is same-lineage, which by I1 cannot
  // recover a correlated blind spot — so the guard fires and emits the un-mitigable stamp, NOT a
  // mitigation claim.
  const dryRound = await orchestrateRound({
    agent,
    reviews: dryReviews(1),
    round: 1,
    northStar: DOGFOOD_NORTH_STAR,
  });
  const roundsToDry = 1; // dry on the first non-empty round
  const unresolvedHighSeverity = countUnresolvedHighSeverity(unresolvedBlindSpotFindings());
  const honesty = assessConvergenceHonesty({
    stakesTier: 'high',
    roundsToDry,
    unresolvedHighSeverity,
    substrateFamilies: [DOGFOOD_FAMILY],
    thresholds,
  });

  return {
    thresholds,
    convergence: {
      converged,
      dryFired,
      rounds: trackerState.rounds,
      dryStreak: trackerState.dryStreak,
      perRound,
    },
    suspicious: {
      roundsToDry,
      unresolvedHighSeverity,
      suspiciousDryRoundWasDry: isDryRound(dryRound),
      fired: honesty.fired,
      singleFamily: honesty.singleFamily,
      mitigated: honesty.mitigated,
      stamp: honesty.stamp,
    },
  };
}

// CLI: `node bin/dogfood.mjs` runs the self-run and prints the report (human inspection).
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runDogfood().then((r) => console.log(JSON.stringify(r, null, 2)));
}

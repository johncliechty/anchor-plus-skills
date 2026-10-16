// Track B7 W2 — sole final-adversarial compose entrypoint for literature-review.
//
// Contract 2 + 5:
//   · adversarialRounds is integer invocation count N of THIS entrypoint
//   · N <= 0 → skip honestly (invokeCount: 0); extraction floors stay full-strength
//   · N >= 1 → invoke exactly N times: each = RP intake (recommend + validating lock)
//     + one runGovernedRound (never runEngine)
//   · floor is always LIT_REVIEW_SAFETY_FLOOR (object identity)
//
// Injectible deps for hermetic stub counters; production loads real governor + wire.

import {
  LIT_REVIEW_SAFETY_FLOOR,
} from 'fil<path>';

const TRIAGE_RP_WIRE =
  'fil<path>';
const GOVERNOR_URL = 'fil<path>';

/**
 * Sole production entry for the literature-review final adversarial stage.
 *
 * @param {object} args
 * @param {object} [args.ledger]  synthesized assumptions ledger (opaque to count semantics)
 * @param {string} [args.band]    process-depth band (LITE|FULL|SPIKE)
 * @param {object} args.knobs     must carry adversarialRounds (sole N authority)
 * @param {Function} [args.agent] agent seam for runGovernedRound / review collection
 * @param {string|object} [args.stakes]
 * @param {string} [args.northStar]
 * @param {object} [args.researchPrimeIntake] inputs bag for RP intake recommend/lock
 * @param {Function} [args.runGovernedRound] inject for hermetic tests
 * @param {Function} [args.recommendResearchPrimeIntake] inject for hermetic tests
 * @param {Function} [args.resolveResearchPrimeIntakeLock] inject for hermetic tests
 * @param {Function} [args.collectReviews] optional async ({agent, ledger, band, knobs, stakes, northStar, round, intakeStamp}) => reviews[]
 * @returns {Promise<{
 *   skipped: boolean,
 *   invokeCount: number,
 *   rounds: object[],
 *   intakeStamps: object[],
 *   floor: typeof LIT_REVIEW_SAFETY_FLOOR,
 * }>}
 */
export async function composeLiteratureReviewAdversarialPass(args = {}) {
  const {
    ledger = null,
    band = null,
    knobs = null,
    agent = null,
    stakes = 'medium',
    northStar = null,
    researchPrimeIntake = null,
    collectReviews = null,
  } = args;

  const floor = LIT_REVIEW_SAFETY_FLOOR;
  const Nraw = knobs && typeof knobs === 'object' ? knobs.adversarialRounds : 0;
  const N = Number(Nraw);

  if (!Number.isFinite(N) || N <= 0) {
    return {
      skipped: true,
      invokeCount: 0,
      rounds: [],
      intakeStamps: [],
      floor,
    };
  }

  const invokeTarget = Math.trunc(N);

  // Resolve deps — production loads real modules; tests inject stubs.
  let recommendResearchPrimeIntake = args.recommendResearchPrimeIntake;
  let resolveResearchPrimeIntakeLock = args.resolveResearchPrimeIntakeLock;
  let runGovernedRound = args.runGovernedRound;

  if (
    typeof recommendResearchPrimeIntake !== 'function' ||
    typeof resolveResearchPrimeIntakeLock !== 'function'
  ) {
    const wire = await import(TRIAGE_RP_WIRE);
    if (typeof recommendResearchPrimeIntake !== 'function') {
      recommendResearchPrimeIntake = wire.recommendResearchPrimeIntake;
    }
    if (typeof resolveResearchPrimeIntakeLock !== 'function') {
      resolveResearchPrimeIntakeLock = wire.resolveResearchPrimeIntakeLock;
    }
  }
  if (typeof runGovernedRound !== 'function') {
    const gov = await import(GOVERNOR_URL);
    runGovernedRound = gov.runGovernedRound;
  }

  // Fail closed if a caller accidentally wires runEngine theater.
  if (typeof args.runEngine === 'function') {
    const err = new Error(
      'composeLiteratureReviewAdversarialPass forbids runEngine; use runGovernedRound only',
    );
    err.code = 'LIT_REVIEW_RUNENGINE_FORBIDDEN';
    throw err;
  }

  const intakeInputs =
    researchPrimeIntake && typeof researchPrimeIntake === 'object'
      ? researchPrimeIntake
      : {
          intent:
            typeof northStar === 'string' && northStar.trim()
              ? northStar
              : 'literature-review final adversarial pass',
          depth: band || undefined,
          scope: 'medium',
        };

  const rounds = [];
  const intakeStamps = [];
  let invokeCount = 0;

  for (let i = 0; i < invokeTarget; i++) {
    const roundIndex = i + 1;

    // Each invocation: RP intake recommend + validating lock (researchprime-wire only).
    const recommendation = recommendResearchPrimeIntake(intakeInputs);
    const locked = resolveResearchPrimeIntakeLock({
      inputs: intakeInputs,
      recommendation,
      confirmedDepth: band || intakeInputs.depth || undefined,
      decision: 'confirm',
    });

    const intakeStamp = Object.freeze({
      invokeIndex: roundIndex,
      recommendation: recommendation
        ? {
            tier: recommendation.tier,
            depth: recommendation.depth,
            rationale: recommendation.rationale,
            defaulted: !!recommendation.defaulted,
          }
        : null,
      lock: locked?.lock
        ? {
            tier: locked.lock.tier,
            depth: locked.lock.depth,
            source: locked.lock.source,
            lockedAt: locked.lock.lockedAt,
          }
        : null,
      knobs: locked?.knobs ?? null,
      band: band ?? locked?.lock?.depth ?? null,
    });
    intakeStamps.push(intakeStamp);

    let reviews = [];
    if (typeof collectReviews === 'function') {
      reviews = await collectReviews({
        agent,
        ledger,
        band,
        knobs,
        stakes,
        northStar,
        round: roundIndex,
        intakeStamp,
      });
      if (!Array.isArray(reviews)) reviews = [];
    }

    const roundResult = await runGovernedRound({
      agent,
      stakes,
      reviews,
      round: roundIndex,
      northStar,
    });
    rounds.push(roundResult);
    invokeCount += 1;
  }

  return {
    skipped: false,
    invokeCount,
    rounds,
    intakeStamps,
    floor,
  };
}

export { LIT_REVIEW_SAFETY_FLOOR };

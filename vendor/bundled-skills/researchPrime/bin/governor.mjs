// bin/governor.mjs — Wave 8 GOVERNOR WIRING + INCLUSION-TEST ENFORCEMENT (Phase D).
//
// MASTER-PLAN Phase D / IMPLEMENTATION-PLAN Wave 8 done-when: a LOW-stakes run fires ZERO
// Synthesizer/Judge/debate sub-agents (call-count 0 via the Wave-7 spy seam) AND a HIGH-stakes run
// fires call-count > 0 (positive control); a zero-AXIS-finding round is provably skipped/demoted.
//
// This module is the WIRING that the prior waves were built to drop into — it forks NOTHING:
//   - the stakes → governor tier comes from the Wave-4 adjudicated stakes vector (bin/stakes.mjs);
//   - the round's adjudication layer (G4 Judge · active Synthesizer · G9 debate) and its call-count
//     SPY SEAM come from the Wave-7 round orchestration (bin/round.mjs `orchestrateRound`);
//   - the INCLUSION TEST (a finding that does not trace to the North Star / AXIS is DEMOTED and
//     cannot hold the loop open) is the trio's own, reused through `tallyFindings` (bin/round.mjs →
//     crucible/shark-tank.mjs). A round whose every finding is demoted serves the AXIS not at all,
//     so it is the "zero-AXIS-finding round" the governor skips.
//
// Two honesty levers meet here, both straight from the locked North Star ("All scaled by the
// declared AXIS stakes" · "No element survives that doesn't serve the AXIS"):
//
//   (1) STAKES SCALING (crit-2/crit-4 cost discipline). The persistent ACTIVE Deep-Think Synthesizer
//       is a "medium+" instrument (MASTER-PLAN North Star) and the separate Judge + conditional
//       debate ride with it. At tier `low` the governor EXCLUDES all three, so a low-stakes run pays
//       zero high-tier sub-agent cost; at `medium`/`high` it INCLUDES them. The tier itself is the
//       Wave-4 ADJUDICATED value (irreversible ⇒ ≥ medium, I6) — never the author's casual word — so
//       the inclusion decision cannot be gamed down by under-declaring stakes.
//
//   (2) INCLUSION-TEST ENFORCEMENT (crit-4 "zero-AXIS-finding rounds skipped"). Independently of the
//       stakes tier, a round that surfaced NO finding tracing to the AXIS is SKIPPED — its expensive
//       adjudication never runs, because there is nothing AXIS-serving to adjudicate. This is the
//       load-bearing demotion: even a HIGH-stakes round is skipped when its findings are all
//       out-of-scope, so stakes can raise the ceiling but cannot manufacture work the AXIS doesn't
//       justify.
//
// PURITY: `governorPolicy`, `resolveTier`, and the AXIS predicates are deterministic, side-effect
// free functions of their inputs. `runGovernedRound` decides the skip from the PURE trio tally
// BEFORE any sub-agent fires, so a skipped round provably makes zero high-tier agent calls.

import { adjudicateStakes, TIERS, tierAtLeast, tierRank } from './stakes.mjs';
import { orchestrateRound, tallyFindings } from './round.mjs';
import { loadGate } from './gate-loader.mjs'; // satisfy static check
import { TRIO_SURFACE } from './engine.mjs';

const { HaltError } = TRIO_SURFACE['foreman-lib'];

// ── The inclusion policy: which high-tier sub-agents a tier admits ──────────────────────────────────
/**
 * The governor tier AT/ABOVE which the high-tier adjudication layer (Synthesizer/Judge/debate) is
 * INCLUDED. The Deep-Think Synthesizer is a "medium+" instrument per the locked North Star, and the
 * separate Judge + conditional debate ride with it. Below this floor (tier `low`) all three are
 * EXCLUDED — a low-stakes run fires zero of them (crit-4).
 */
export const ADJUDICATION_TIER_FLOOR = 'medium';

/** The high-tier sub-agent roles the governor scales by stakes (the Wave-7 spy-seam roles). */
export const HIGH_TIER_AGENTS = Object.freeze(['synthesizer', 'judge', 'debate']);

/** The literal stamp a round wears when the inclusion test demotes it (zero AXIS-serving findings). */
export const ZERO_AXIS_SKIP_STAMP =
  'round SKIPPED by the inclusion test — no finding traces to the North Star (AXIS), so nothing ' +
  'serves the objective and the high-tier adjudication is not run (crit-4: zero-AXIS-finding rounds skipped)';

/**
 * Decide, from a governor tier, WHICH high-tier sub-agents are included this run (the inclusion
 * policy). At/above the adjudication floor (`medium`+) the Synthesizer/Judge/debate are all admitted;
 * below it (`low`) all three are excluded. `debate` being admitted only means it MAY fire — G9 stays
 * conditional on an actual cross-origin conflict downstream (bin/round.mjs).
 *
 * @param {string} tier  a governor tier from bin/stakes.mjs TIERS ('low' | 'medium' | 'high')
 * @returns {{ tier:string, include:boolean, synthesize:boolean, judge:boolean, debate:boolean, reason:string }}
 */
export function governorPolicy(tier) {
  if (tierRank(tier) < 0) {
    throw new HaltError(
      `governorPolicy: unknown governor tier ${JSON.stringify(tier)} — expected one of ${TIERS.join(', ')}`,
    );
  }
  const include = tierAtLeast(tier, ADJUDICATION_TIER_FLOOR);
  const reason = include
    ? `tier=${tier} ≥ ${ADJUDICATION_TIER_FLOOR}: Synthesizer/Judge/debate INCLUDED (high-tier adjudication on)`
    : `tier=${tier} < ${ADJUDICATION_TIER_FLOOR}: Synthesizer/Judge/debate EXCLUDED (low-stakes fires zero high-tier agents, crit-4)`;
  return { tier, include, synthesize: include, judge: include, debate: include, reason };
}

// ── Resolving a run's governor tier from its stakes (vector OR a pre-projected tier) ────────────────
/**
 * Resolve a run's governor tier. Accepts either an already-projected tier string (a value in
 * bin/stakes.mjs TIERS) or a raw declared STAKES VECTOR object, which it adjudicates through the
 * Wave-4 governor (`adjudicateStakes`) — so the I6 under-call guard (irreversible ⇒ tier ≥ medium)
 * is enforced HERE too, not bypassable by handing the governor a bare tier.
 *
 * @param {string|object} stakes  a TIER string, or a declared stakes-vector object
 * @returns {string} the governor tier
 */
export function resolveTier(stakes) {
  if (typeof stakes === 'string') {
    if (tierRank(stakes) < 0) {
      throw new HaltError(
        `resolveTier: unknown tier string ${JSON.stringify(stakes)} — expected one of ${TIERS.join(', ')}`,
      );
    }
    return stakes;
  }
  if (stakes && typeof stakes === 'object' && !Array.isArray(stakes)) {
    return adjudicateStakes(stakes).tier; // Wave-4 adjudication (I6 floor applied)
  }
  throw new HaltError(
    'resolveTier requires a governor tier string OR a declared stakes-vector object (Wave-4)',
  );
}

// ── The inclusion test: which findings serve the AXIS (North Star) ──────────────────────────────────
/**
 * The AXIS-SERVING findings of a round: the tally's findings that PASSED the inclusion test (NOT
 * demoted). The trio tally marks a finding `demoted:true` exactly when it does not trace to the North
 * Star (`traces_to_north_star: 'no'`), so the non-demoted set is precisely the findings that serve
 * the AXIS. Reused, not re-derived — the same inclusion test the Sharks already apply.
 *
 * @param {{findings?:Array<{demoted?:boolean}>}} tally  a `tallyFindings` result
 * @returns {Array<object>}
 */
export function axisServingFindings(tally) {
  const findings = Array.isArray(tally?.findings) ? tally.findings : [];
  return findings.filter((f) => !f?.demoted);
}

/**
 * Is this a ZERO-AXIS-FINDING round? True when NO finding serves the AXIS — either no findings at all
 * (an empty round) or every finding failed the inclusion test (all demoted / out-of-scope). Such a
 * round cannot justify the high-tier adjudication, so the governor skips it (crit-4).
 *
 * @param {object} tally  a `tallyFindings` result
 */
export function isZeroAxisFindingRound(tally) {
  return axisServingFindings(tally).length === 0;
}

// ── The governed round: stakes scaling + inclusion-test enforcement, over the Wave-7 round ───────────
/**
 * Run ONE governed verification round: the Wave-8 wiring that gates the Wave-7 adjudication layer by
 * BOTH the stakes tier AND the inclusion test, exposing the same per-role call-count SPY SEAM.
 *
 * The decision order (and why):
 *   1. Resolve the governor tier (Wave-4 adjudication, I6 floor) and its inclusion policy.
 *   2. Compute the trio tally from the reviews — this is PURE (no sub-agent calls), so the skip
 *      decision is made BEFORE any high-tier agent could fire.
 *   3. INCLUSION TEST: if the round is zero-AXIS-finding, SKIP it — return counts {0,0,0} and the
 *      demotion stamp without invoking the adjudication layer at all (crit-4). This holds at EVERY
 *      tier, so even a high-stakes round is skipped when nothing serves the AXIS.
 *   4. Otherwise delegate to `orchestrateRound` with the tier's inclusion flags. At tier `low` all
 *      three flags are false ⇒ the spy seam reports {0,0,0}; at `medium`/`high` they are true ⇒ the
 *      Synthesizer + Judge fire (and debate fires iff there is a cross-origin conflict), so the spy
 *      seam reports a positive count (the positive control).
 *
 * @param {object} o
 * @param {Function}      o.agent                  the injected agent seam (the spy); required
 * @param {string|object} o.stakes                 a governor tier OR a declared stakes vector (Wave 4)
 * @param {Array}         o.reviews                lineage-tagged per-reviewer reviews (the AXIS findings)
 * @param {number}        [o.round=1]
 * @param {?string}       [o.northStar=null]
 * @param {string[]}      [o.priorBlockerIds=[]]
 * @param {object}        [o.g8={enabled:false}]   G8 fusion options (default inert)
 * @returns {Promise<object>} { tier, policy, skipped, demoted, counts:{synthesizer,judge,debate}, tally, axisFindingCount, ... }
 */
export async function runGovernedRound({
  agent,
  stakes,
  reviews,
  round = 1,
  northStar = null,
  priorBlockerIds = [],
  g8 = { enabled: false },
  // P0 2026-07-25: a TIGHTEN-ONLY band override (LITE triage's includeAdjudication knob).
  // `false` forces the G9 debate off even where the tier admits it; it can never turn ON
  // what the tier excludes (the && below), so the governor's cost ceiling is preserved.
  includeDebate = null,
} = {}) {
  if (typeof agent !== 'function') {
    throw new HaltError('runGovernedRound requires an agent() function', 'pass the injected seam: { agent }');
  }
  if (!Array.isArray(reviews)) {
    throw new HaltError("runGovernedRound requires a reviews[] array (the round's AXIS findings)");
  }

  const tier = resolveTier(stakes);
  const policy = governorPolicy(tier);

  // PURE pre-flight: the trio tally + AXIS inclusion, computed with NO sub-agent calls. The skip
  // decision is therefore provably made before any high-tier agent could fire.
  const tally = tallyFindings(reviews, { priorBlockerIds });
  const axisFindingCount = axisServingFindings(tally).length;

  // (3) Inclusion-test enforcement: a zero-AXIS-finding round is skipped/demoted at EVERY tier.
  if (isZeroAxisFindingRound(tally)) {
    return {
      round,
      tier,
      policy,
      skipped: true,
      demoted: true,
      reason: ZERO_AXIS_SKIP_STAMP,
      counts: { synthesizer: 0, judge: 0, debate: 0 },
      tally,
      axisFindingCount: 0,
      reviews,
    };
  }

  // (4) Stakes-scaled adjudication: delegate to the Wave-7 round with the tier's inclusion flags. The
  // returned `counts` ARE the spy seam — {0,0,0} at low stakes, positive at medium/high.
  const result = await orchestrateRound({
    agent,
    round,
    northStar,
    reviews,
    priorBlockerIds,
    synthesize: policy.synthesize,
    judge: policy.judge,
    debate: policy.debate && includeDebate !== false,
    g8,
  });

  return { tier, policy, skipped: false, demoted: false, reason: policy.reason, axisFindingCount, ...result };
}

// Re-export the composed pieces so a consumer/test reads the SAME governor + round surface the wiring
// uses (one canonical tier projection, one canonical round orchestrator).
export { adjudicateStakes, TIERS, tierAtLeast } from './stakes.mjs';
export { orchestrateRound, tallyFindings } from './round.mjs';

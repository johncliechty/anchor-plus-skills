// bin/trio-core/independence-accounting.mjs — the trio's SINGLE origin/quorum counter.
//
// Wave 2 (REQUIRED per the v6 amendment): the one true component that turns a set of
// reviewers into a count of INDEPENDENT ORIGINS and decides how many origins a corroboration
// needs (the quorum). It is the sole place either number is computed, so the independence
// rule cannot be re-implemented (and quietly weakened) per call site.
//
// ── Where this lives & why (scope decision, on the record) ────────────────────────────────
// IMPLEMENTATION-PLAN Wave 2's prose says "crucible-lib is split into -core/-stages … a shared
// independence-accounting module lives in the trio-core." The named SOURCE OF TRUTH
// (DESCRIPTION.md → MASTER-PLAN.md) scopes this plan precisely: "this plan builds the shared
// module + researchPrime's use of it, NOT the other two engines' rewrite" (MASTER-PLAN
// "Out of scope"); "Crucible/Foreman adoption is a gated fast-follow"; the Architecture is
// "imports, never forks." Crucible is a separate git repo and Foreman is not a git repo at all,
// so mutating their trees is both forbidden by the plan and unrecoverable here. Therefore the
// trio-core shared module is BUILT HERE — in researchPrime, the trio member this plan owns —
// as the single canonical copy (crit 6), and is published on the package's `exports` surface so
// the deferred Crucible/Foreman adoption (the fast-follow) can import THIS copy, never fork it.
//
// ── The invariants this module enforces ───────────────────────────────────────────────────
// I3 (origin integrity, generalized): only an attested DISTINCT lineage increments
//   `independent_origins`; agreement among reviewers of the SAME lineage adds 0. A same-family
//   `cross_model:true` is a heterogeneity proxy, never an independence guarantee.
// I7/I8 (monotone-tighten-only quorum): a learned reviewer-error correlation ρ̂ may only RAISE
//   the number of origins required — it can NEVER relax the quorum below the pre-registered
//   static ≥2 floor. ρ̂ changes the COUNT REQUIRED; it never reclassifies a same-lineage
//   agreement as an independent origin (the origin count is invariant under any ρ̂).
//
// This module is PURE (no I/O). The cross-run ρ-calibration ledger that PRODUCES ρ̂ is Wave 9;
// here ρ̂ is an injected input and the only thing Wave 2 locks is the SAFETY CONTRACT around it
// (monotone-tighten-only), so the floor the Wave-9 learner sits on top of exists and is tested
// before the learner is built.

/**
 * The pre-registered static quorum: a corroboration needs ≥ 2 independent origins. This is a
 * LOCKED architectural invariant (the North Star's "heterogeneous ≥2-agree reviewers"), not a
 * tunable pre-registered threshold — so it is a constant here, not read from preregistration.json.
 * Ratcheting THIS floor downward is a reserved human decision (MASTER-PLAN crit 7 / I8); ρ̂ may
 * only ratchet the effective quorum UP.
 */
export const STATIC_QUORUM_FLOOR = 2;

/**
 * The attested lineage of one reviewer: prefer an explicit `lineage`, else fall back to the
 * `family` field of a `stampRole(...)`-shaped object (judge.mjs), else null (unattested). A
 * blank string is treated as unattested, not as a distinct lineage named "".
 * @param {object} reviewer
 * @returns {?string}
 */
export function lineageOf(reviewer) {
  if (!reviewer || typeof reviewer !== 'object') return null;
  const raw = reviewer.lineage ?? reviewer.family ?? null;
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Count the INDEPENDENT ORIGINS among a set of reviewers, keyed by attested lineage.
 *
 * Rules (I3 generalized):
 *   - Each DISTINCT attested lineage contributes exactly +1, no matter how many reviewers share
 *     it — same-lineage agreement adds 0 (the load-bearing invariant).
 *   - Unattested reviewers (no/blank lineage, or — when an enum is supplied — a lineage OFF the
 *     committed enum) collapse to AT MOST +1 total (crit-5 "off-enum/absent ⇒ capped at +1").
 *
 * The closed attested-lineage enum is a reserved human decision committed later (Wave 7,
 * `test/lineage-enum.test.mjs` RED-until-committed). It is therefore INJECTED here, never
 * hard-coded. Supplying the enum can only TIGHTEN the count (it moves off-enum lineages out of
 * the distinct-origin pool and into the single capped bucket) — it never raises it. Omitting it
 * (the Wave-2 default, before the enum exists) counts each self-declared lineage as distinct,
 * which is exactly the Wave-2 acceptance rule.
 *
 * This function does NOT take ρ̂: the origin count is INVARIANT under any learned correlation.
 *
 * @param {Array<object>} reviewers   reviewers carrying `{ lineage }` or a stampRole `{ family }`
 * @param {object} [opts]
 * @param {Iterable<string>} [opts.attestedLineages]  the committed closed enum (Wave 7); when
 *        present, only lineages IN it count as distinct origins, all others share one capped bucket
 * @returns {number} the number of independent origins (≥ 0)
 */
export function countIndependentOrigins(reviewers, opts = {}) {
  if (!Array.isArray(reviewers)) {
    throw new TypeError('countIndependentOrigins(reviewers): reviewers must be an array');
  }
  const enum_ = opts.attestedLineages != null ? new Set(opts.attestedLineages) : null;

  const distinctAttested = new Set();
  let sawUnattested = false;

  for (const reviewer of reviewers) {
    const lineage = lineageOf(reviewer);
    const attested = lineage !== null && (enum_ === null || enum_.has(lineage));
    if (attested) {
      distinctAttested.add(lineage);
    } else {
      // No lineage, or (with an enum) a lineage not in the committed enum: cannot be claimed
      // as its own independent origin — these all share a single capped bucket.
      sawUnattested = true;
    }
  }
  return distinctAttested.size + (sawUnattested ? 1 : 0);
}

/**
 * Map a learned reviewer-error correlation ρ̂ to the number of independent origins a
 * corroboration requires — MONOTONE-TIGHTEN-ONLY.
 *
 * The only property Wave 2 LOCKS is the safety contract, not the exact curve (MASTER-PLAN
 * altitude note: "Stage 2 finalizes the encoding"): for EVERY ρ̂ the result is ≥ `staticFloor`,
 * and it is non-decreasing in ρ̂. Higher correlation ⇒ each agreement carries less independent
 * evidence ⇒ MORE origins needed to reach the same confidence; lower or absent correlation falls
 * back to the static floor and never below it. Because ρ̂ is a right-censored LOWER bound on the
 * true correlation (MASTER-PLAN A5), loosening the bar would chase the bias — so it is forbidden
 * by construction here, not merely by policy.
 *
 * Any non-finite / out-of-range / null ρ̂ degrades to the static floor (still ≥ floor — safe).
 *
 * @param {?number} rhoHat   estimated correlation in [0, 1); null/NaN ⇒ static floor
 * @param {number} [staticFloor=STATIC_QUORUM_FLOOR]
 * @returns {number} required independent origins (integer ≥ staticFloor)
 */
export function requiredQuorum(rhoHat = null, staticFloor = STATIC_QUORUM_FLOOR) {
  const floor = Number.isInteger(staticFloor) && staticFloor >= 1 ? staticFloor : STATIC_QUORUM_FLOOR;
  // Out-of-band ρ̂ ⇒ no tightening (but never loosening): fall back to the floor.
  if (typeof rhoHat !== 'number' || !Number.isFinite(rhoHat) || rhoHat <= 0) return floor;
  // Clamp into [0, 1); ρ̂ is a probability and ρ̂→1 would demand unboundedly many origins.
  const rho = Math.min(rhoHat, 0.999);
  // Inflate the floor by the variance-non-reduction factor 1/(1-ρ): at ρ=0 → floor, rising with ρ.
  const required = Math.ceil(floor / (1 - rho));
  // Belt-and-braces: the contract is "never below the floor", asserted regardless of the curve.
  return Math.max(floor, required);
}

/**
 * Does this set of reviewers MEET the quorum? Combines the two numbers above: the independent
 * origins present (invariant under ρ̂) vs the origins required (which ρ̂ may only raise).
 *
 * @param {Array<object>} reviewers
 * @param {object} [opts]
 * @param {?number} [opts.rhoHat=null]                 learned correlation (Wave 9 supplies it)
 * @param {number}  [opts.staticFloor=STATIC_QUORUM_FLOOR]
 * @param {Iterable<string>} [opts.attestedLineages]   committed closed enum (Wave 7)
 * @returns {{ origins:number, required:number, met:boolean }}
 */
export function meetsQuorum(reviewers, opts = {}) {
  const { rhoHat = null, staticFloor = STATIC_QUORUM_FLOOR, attestedLineages } = opts;
  const origins = countIndependentOrigins(reviewers, { attestedLineages });
  const required = requiredQuorum(rhoHat, staticFloor);
  return { origins, required, met: origins >= required };
}

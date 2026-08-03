// Gandalf advisor — the ADVISORY power-calc CODE for the elevation oracle (Wave 8).
//
// The dive's §5 residual: the non-additivity margin G and the oracle power-floor k are JOINTLY SET
// BY A POWER CALCULATION, not asserted. This module is that calculation, as deterministic CODE: the
// paired-test power / minimum-detectable-effect computation with the ICC-adjusted EFFECTIVE N that
// the dive pinned — "effective N tracks the fixture COUNT, not seeds×fixtures" — because the seeds
// drawn within one real-history fixture are CLUSTERED (an intraclass correlation ICC), so they do
// not each count as an independent observation.
//
// EXPLICIT SCOPE BOUNDARY (Wave 8 done-when): this is the INSTRUMENT — the arithmetic that, given
// (alpha, target power, ICC, fixture count k, seeds-per-fixture, the paired-difference SD, the
// margin G), computes the minimum detectable effect and the power at G, and reports whether the
// design is adequately powered AT THOSE INPUTS. It emits NO feasibility verdict and commits NO
// (G, k) or ICC — those require REAL-history fixtures and a human-dual-scored calibration and are
// owned by the HALT-gated increment H1 (`preregistration.json`). `assessPower(..)` is stamped to
// make that boundary unmistakable: it is arithmetic over HYPOTHETICAL inputs, never the H1 ruling.
//
// Like seam/oracle-harness.mjs this module is ADVISORY (PRINCIPLE-D): `test/harness.mjs`'s static
// import closure does NOT reach it (its companion test asserts that), so it can never gate
// `node --test`.
//
// Public surface:
//   normalCdf(x) / normalQuantile(p)             — standard-normal Φ and Φ⁻¹ (deterministic approxs)
//   designEffect(clusterSize, icc)               — Kish design effect 1 + (m−1)·ICC
//   effectiveN({fixtures, seedsPerFixture, icc}) — ICC-adjusted N (tracks the fixture count)
//   pairedPower({n, effect, sd, alpha, sides})   — power of a paired test at a given effect
//   minimumDetectableEffect({n, sd, alpha, power, sides}) — the MDE at a design
//   requiredFixtures({effect, sd, icc, seedsPerFixture, alpha, power, sides}) — k to detect `effect`
//   assessPower(spec)                            — compose: effective N + MDE + power@G + powered?

// === standard-normal Φ (CDF) and Φ⁻¹ (quantile) — deterministic, no dependencies ================
/** erf via Abramowitz & Stegun 7.1.26 (|error| < 1.5e-7). Odd function. */
function erf(x) {
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * ax);
  const y =
    1 -
    (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t *
      Math.exp(-ax * ax);
  return sign * y;
}

/** The standard-normal CDF Φ(x) = P(Z ≤ x). Deterministic; Φ(0)=0.5, Φ(1.95996…)≈0.975. */
export function normalCdf(x) {
  if (typeof x !== 'number' || Number.isNaN(x)) throw new Error('power-calc: normalCdf requires a number');
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

// Acklam's inverse-normal-CDF rational approximation (|error| ~ 1.15e-9 in the central region).
const A_ = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
const B_ = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
const C_ = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
const D_ = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];

/** The standard-normal quantile Φ⁻¹(p) for p ∈ (0,1): the z with P(Z ≤ z) = p. Deterministic;
 *  Φ⁻¹(0.975)≈1.95996, Φ⁻¹(0.8)≈0.84162. Throws outside the open interval (0,1). */
export function normalQuantile(p) {
  if (typeof p !== 'number' || Number.isNaN(p) || p <= 0 || p >= 1) {
    throw new Error(`power-calc: normalQuantile requires p ∈ (0,1), got ${JSON.stringify(p)}`);
  }
  const plow = 0.02425;
  const phigh = 1 - plow;
  let q;
  let r;
  if (p < plow) {
    q = Math.sqrt(-2 * Math.log(p));
    return (((((C_[0] * q + C_[1]) * q + C_[2]) * q + C_[3]) * q + C_[4]) * q + C_[5]) /
      ((((D_[0] * q + D_[1]) * q + D_[2]) * q + D_[3]) * q + 1);
  }
  if (p > phigh) {
    q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((C_[0] * q + C_[1]) * q + C_[2]) * q + C_[3]) * q + C_[4]) * q + C_[5]) /
      ((((D_[0] * q + D_[1]) * q + D_[2]) * q + D_[3]) * q + 1);
  }
  q = p - 0.5;
  r = q * q;
  return (((((A_[0] * r + A_[1]) * r + A_[2]) * r + A_[3]) * r + A_[4]) * r + A_[5]) * q /
    (((((B_[0] * r + B_[1]) * r + B_[2]) * r + B_[3]) * r + B_[4]) * r + 1);
}

// === the ICC-adjusted EFFECTIVE N (the dive's load-bearing residual) ===========================
/** The Kish DESIGN EFFECT for a clustered design: DEFF = 1 + (m − 1)·ICC, where m is the cluster
 *  size (seeds drawn within one fixture) and ICC the intraclass correlation. ICC=0 ⇒ DEFF=1 (no
 *  clustering penalty); ICC=1 ⇒ DEFF=m (the cluster counts as ONE observation). Throws on a bad ICC. */
export function designEffect(clusterSize, icc) {
  if (typeof clusterSize !== 'number' || clusterSize < 1) {
    throw new Error(`power-calc: designEffect requires clusterSize ≥ 1, got ${JSON.stringify(clusterSize)}`);
  }
  if (typeof icc !== 'number' || icc < 0 || icc > 1) {
    throw new Error(`power-calc: designEffect requires ICC ∈ [0,1], got ${JSON.stringify(icc)}`);
  }
  return 1 + (clusterSize - 1) * icc;
}

/** The ICC-ADJUSTED EFFECTIVE N. With `fixtures` real-history fixtures, `seedsPerFixture` seeds
 *  each, and intraclass correlation `icc`, the effective independent-observation count is
 *    N_eff = (fixtures · seedsPerFixture) / DEFF,   DEFF = 1 + (seedsPerFixture − 1)·ICC.
 *  The dive's pinned property: as ICC → 1 the seeds within a fixture collapse to one observation,
 *  so N_eff → `fixtures` — the effective N TRACKS THE FIXTURE COUNT, not seeds×fixtures. (At ICC=0
 *  it is the raw seeds×fixtures; the truth is in between, which is why k must be set by this calc.)
 *  Returns the effective N (a real number ≥ fixtures). Throws on bad inputs. */
export function effectiveN({ fixtures, seedsPerFixture = 1, icc } = {}) {
  if (typeof fixtures !== 'number' || fixtures < 1) {
    throw new Error(`power-calc: effectiveN requires fixtures ≥ 1, got ${JSON.stringify(fixtures)}`);
  }
  const deff = designEffect(seedsPerFixture, icc);
  return (fixtures * seedsPerFixture) / deff;
}

// === the paired-test power calculation ========================================================
function zAlpha(alpha, sides) {
  if (typeof alpha !== 'number' || alpha <= 0 || alpha >= 1) {
    throw new Error(`power-calc: alpha must be in (0,1), got ${JSON.stringify(alpha)}`);
  }
  if (sides !== 1 && sides !== 2) throw new Error(`power-calc: sides must be 1 or 2, got ${JSON.stringify(sides)}`);
  return normalQuantile(1 - alpha / sides);
}

/** The POWER of a paired test (one-sample z on the within-pair differences) to detect a true mean
 *  difference `effect` (the margin G, in the same units as the paired-difference SD `sd`) at
 *  effective sample size `n`, significance `alpha`, `sides` (1 or 2):
 *    power = Φ( effect·√n / sd − z_{1−alpha/sides} ).
 *  Returns a probability in (0,1). Throws on bad inputs (n ≥ 1, sd > 0). */
export function pairedPower({ n, effect, sd, alpha = 0.05, sides = 2 } = {}) {
  if (typeof n !== 'number' || n < 1) throw new Error(`power-calc: pairedPower requires n ≥ 1, got ${JSON.stringify(n)}`);
  if (typeof effect !== 'number') throw new Error('power-calc: pairedPower requires a numeric effect');
  if (typeof sd !== 'number' || sd <= 0) throw new Error(`power-calc: pairedPower requires sd > 0, got ${JSON.stringify(sd)}`);
  const za = zAlpha(alpha, sides);
  const ncp = (Math.abs(effect) * Math.sqrt(n)) / sd; // noncentrality (standardized effect · √n)
  return normalCdf(ncp - za);
}

/** The MINIMUM DETECTABLE EFFECT at a design: the smallest true mean paired-difference that the
 *  test detects with the target `power` at significance `alpha`, given effective N `n` and the
 *  paired-difference SD `sd`:
 *    MDE = sd · (z_{1−alpha/sides} + z_{power}) / √n.
 *  Returns the MDE in the SD's units. If MDE > G the design is UNDERPOWERED for margin G — the dive's
 *  rule "raise k or widen G." Throws on bad inputs. */
export function minimumDetectableEffect({ n, sd, alpha = 0.05, power = 0.8, sides = 2 } = {}) {
  if (typeof n !== 'number' || n < 1) throw new Error(`power-calc: minimumDetectableEffect requires n ≥ 1, got ${JSON.stringify(n)}`);
  if (typeof sd !== 'number' || sd <= 0) throw new Error(`power-calc: minimumDetectableEffect requires sd > 0, got ${JSON.stringify(sd)}`);
  if (typeof power !== 'number' || power <= 0 || power >= 1) {
    throw new Error(`power-calc: minimumDetectableEffect requires power ∈ (0,1), got ${JSON.stringify(power)}`);
  }
  const za = zAlpha(alpha, sides);
  const zb = normalQuantile(power);
  return (sd * (za + zb)) / Math.sqrt(n);
}

/** The number of FIXTURES k required to detect a true effect `effect` at the target `power` and
 *  `alpha`, accounting for the ICC clustering of `seedsPerFixture` seeds within each fixture:
 *  invert the paired-test sample-size formula for effective N, then back out k from the design
 *  effect. Returns k rounded UP to a whole fixture (you cannot run a fractional fixture). Throws on
 *  bad inputs. */
export function requiredFixtures({ effect, sd, icc, seedsPerFixture = 1, alpha = 0.05, power = 0.8, sides = 2 } = {}) {
  if (typeof effect !== 'number' || effect === 0) throw new Error('power-calc: requiredFixtures requires a non-zero effect');
  if (typeof sd !== 'number' || sd <= 0) throw new Error(`power-calc: requiredFixtures requires sd > 0, got ${JSON.stringify(sd)}`);
  if (typeof power !== 'number' || power <= 0 || power >= 1) {
    throw new Error(`power-calc: requiredFixtures requires power ∈ (0,1), got ${JSON.stringify(power)}`);
  }
  const za = zAlpha(alpha, sides);
  const zb = normalQuantile(power);
  const nEffNeeded = Math.pow((sd * (za + zb)) / Math.abs(effect), 2); // effective N to hit the MDE
  const deff = designEffect(seedsPerFixture, icc);
  // N_eff = k·seedsPerFixture / DEFF  ⇒  k = N_eff · DEFF / seedsPerFixture.
  const k = (nEffNeeded * deff) / seedsPerFixture;
  return Math.ceil(k);
}

/** Compose the full power assessment AT THE GIVEN INPUTS: the ICC-adjusted effective N, the MDE,
 *  the power at the proposed margin G, and whether the design is adequately powered (MDE ≤ G). This
 *  is ARITHMETIC over the supplied (hypothetical) inputs — it is the instrument, NOT the H1
 *  feasibility verdict: `feasibility_verdict` is fixed `null` and `not_a_ruling` is stamped, because
 *  the real (G, k) commit + the measured calibration ICC require real-history fixtures and a human,
 *  and live in `preregistration.json` (H1), never here. Returns the bundle; throws on bad inputs. */
export function assessPower({ fixtures, seedsPerFixture = 1, icc, marginG, sd, alpha = 0.05, targetPower = 0.8, sides = 2 } = {}) {
  if (typeof marginG !== 'number' || marginG <= 0) {
    throw new Error(`power-calc: assessPower requires a positive marginG, got ${JSON.stringify(marginG)}`);
  }
  const nEff = effectiveN({ fixtures, seedsPerFixture, icc });
  const mde = minimumDetectableEffect({ n: nEff, sd, alpha, power: targetPower, sides });
  const powerAtMargin = pairedPower({ n: nEff, effect: marginG, sd, alpha, sides });
  const adequatelyPowered = mde <= marginG;
  return {
    advisory: true,
    gating: false, // PRINCIPLE-D: never a gate
    inputs: { fixtures, seedsPerFixture, icc, marginG, sd, alpha, targetPower, sides },
    effective_n: nEff,
    design_effect: designEffect(seedsPerFixture, icc),
    mde,
    power_at_margin: powerAtMargin,
    adequately_powered: adequatelyPowered, // arithmetic: MDE ≤ G at these inputs
    recommendation: adequatelyPowered
      ? 'design detects margin G at these inputs'
      : 'UNDERPOWERED for margin G — raise k (fixtures) or widen G (the dive\'s rule)',
    feasibility_verdict: null, // NOT set here — the real ruling is H1 (preregistration.json)
    not_a_ruling:
      'arithmetic over hypothetical inputs; the real (G,k) commit + measured calibration ICC + the SHIP/UNPROVEN feasibility verdict are owned by the HALT-gated increment H1, never by this calc',
  };
}

// bin/power-calc.mjs — Wave 3 fixture power calc (FIXTURE-SPEC "Sizing deferred to Wave 3";
// MASTER-PLAN Phase 0 / crit 2: "G and X% are pre-registered with the fixture size set by a
// power calc so the target is statistically reachable").
//
// The fixture's job is to let two pre-registered proportions be MEASURED with a meaningful
// sample, not asserted:
//   • crit-1 gap-closure  — loop recall closes ≥ G% of the single-pass MISS rate. G is a
//     fraction of the single-pass-miss denominator, so that denominator must be big enough
//     that a 60%-ish closure estimate has a usable confidence interval.
//   • I2 CBS floor        — correlated-blind-spot recall ≥ C_min. CBS recall is its own
//     proportion (caught_cbs / planted_cbs) and must be comparable to C_min with a
//     meaningful sample (FIXTURE-SPEC §2: "large enough that CBS recall can be compared to
//     C_min with a meaningful sample").
//
// This module turns the COMMITTED pre-registration thresholds (G, C_min — Wave 1, now frozen)
// into the MINIMUM planted-defect counts the Wave-3 fixture must meet. It never invents a
// threshold: it reads the human-committed values and only chooses the fixture-precision the
// counts are sized to deliver (the DESIGN half-widths below — a sizing decision, not a gate).
// A run against a non-GREEN pre-registration throws (you cannot size a fixture to numbers a
// human has not yet committed — that would defeat the I6 pre-registration order).

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadPreregistration, validatePreregistration } from './preregistration.mjs';

// Two-sided 95% normal quantile (z_{0.975}). Used for the Wald sample-size formula.
export const Z_95 = 1.959963984540054;

/**
 * Wald (normal-approximation) sample size to estimate a proportion `p` to a given two-sided
 * `halfWidth` at confidence `z`: n = ⌈ z² · p(1−p) / halfWidth² ⌉. This is the standard
 * "sample size for a proportion" calc; p(1−p) is the variance of one Bernoulli trial.
 * @param {number} p          the proportion the fixture is sized AROUND (in (0,1))
 * @param {number} halfWidth  the half-width of the CI the fixture must deliver (in (0,1))
 * @param {number} [z=Z_95]
 * @returns {number} minimum sample size (integer ≥ 1)
 */
export function sampleForProportion(p, halfWidth, z = Z_95) {
  if (!(typeof p === 'number' && p > 0 && p < 1)) {
    throw new RangeError('sampleForProportion: p must be a number in (0, 1)');
  }
  if (!(typeof halfWidth === 'number' && halfWidth > 0 && halfWidth < 1)) {
    throw new RangeError('sampleForProportion: halfWidth must be a number in (0, 1)');
  }
  return Math.ceil((z * z * p * (1 - p)) / (halfWidth * halfWidth));
}

/**
 * Fixture-precision DESIGN constants: the CI half-width each sized proportion is built to
 * deliver. These are SIZING choices (how tight a measurement the fixture supports), NOT gate
 * thresholds — the gates (G, C_min) are the human-committed pre-registration. Tightening a
 * half-width only ever raises the required count.
 */
export const DESIGN = Object.freeze({
  cbsHalfWidth: 0.2, // CBS recall estimable to ±0.20 around C_min (I2)
  closureHalfWidth: 0.18, // gap-closure estimable to ±0.18 around G (crit-1)
});

/**
 * Compute the minimum fixture sizing from the COMMITTED pre-registration thresholds.
 * @param {object} [prereg=loadPreregistration()]
 * @returns {{
 *   minCbs: number,            // ≥ this many correlated-blind-spot defects (I2 sample)
 *   minSinglePassMisses: number, // ≥ this many single-pass MISSES (crit-1 gap denominator)
 *   C_min: number, G: number,  // the committed thresholds the sizing serves (echoed)
 *   design: typeof DESIGN
 * }}
 */
export function powerCalc(prereg = loadPreregistration()) {
  const { committed, pending, invalid } = validatePreregistration(prereg);
  if (!committed) {
    throw new Error(
      'power calc requires a GREEN pre-registration (sizing a fixture to un-committed thresholds ' +
        `would defeat the I6 pre-registration order). pending=[${pending.join(', ')}] ` +
        `invalid=[${invalid.map((i) => i.key).join(', ')}]`,
    );
  }
  const C_min = prereg.C_min; // I2 CBS recall floor, in [0,1]
  const G = prereg.G / 100; // crit-1 gap-closure target as a proportion
  return {
    minCbs: sampleForProportion(C_min, DESIGN.cbsHalfWidth),
    minSinglePassMisses: sampleForProportion(G, DESIGN.closureHalfWidth),
    C_min,
    G,
    design: DESIGN,
  };
}

// Convenience for human inspection / CLI: `node bin/power-calc.mjs`.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(JSON.stringify(powerCalc(), null, 2));
}

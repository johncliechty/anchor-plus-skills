// bin/fixture-counts.mjs — the FROZEN per-class planted-defect counts for the Wave-3 fixture.
//
// These are the sizing the fixture is built at. They are chosen to CLEAR the power calc
// (bin/power-calc.mjs) against the now-frozen pre-registration thresholds (G, C_min), and the
// Wave-3 test asserts they do — so a count that silently drops below the power-calc minimum is
// a HARD failure, not a quiet under-powering. Kept in their own module so both the generator
// (bin/fixture.mjs) and the gate (test/baseline.test.mjs) read ONE source.
//
// Sizing rationale (see power-calc DESIGN half-widths):
//   • cbs (24) ≥ minCbs (21 at C_min=0.3, ±0.20) — CBS recall is comparable to C_min with a
//     meaningful sample (I2; FIXTURE-SPEC §2).
//   • single-pass MISSES = ordinaryMissed (12) + cbs (24) = 36 ≥ minSinglePassMisses (29 at
//     G=0.60, ±0.18) — the gap-closure denominator G is a fraction of is well-powered (crit-1).
//   • ordinaryCaught (12) gives single-pass ordinary recall < 1 (a real, non-trivial baseline).
//   • pathDefect / irreversible are crit-3 / I6 probes (≥1 each required by FIXTURE-SPEC).
export const FIXTURE_COUNTS = Object.freeze({
  ordinaryCaught: 12, // ordinary, high/medium severity — single-pass CATCHES
  ordinaryMissed: 12, // ordinary, low severity — single-pass MISSES (loop closes)
  cbs: 24, // correlated-blind-spot — single-pass MISSES all (recoverable only cross-lineage)
  pathDefect: 3, // crit-3 foresight probes (not in recall denominator)
  irreversible: 2, // I6 under-call guard probes (not in recall denominator)
});

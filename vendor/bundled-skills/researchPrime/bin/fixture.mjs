// bin/fixture.mjs — Wave 3 planted-defect fixture (the ground truth for crit-1/3/7).
//
// FIXTURE-SPEC.md defines WHAT this corpus contains and HOW each class is scored; Wave 3
// produces the actual corpus + the machine-readable defect manifest at the power-calc size.
// This module is the SINGLE deterministic generator: same code ⇒ byte-identical corpus +
// manifest, so the on-disk fixture can be re-derived and a drift detected (Wave-3 done-when:
// "regeneration ⇒ RED"). It uses NO clock and NO randomness — every field is a pure function
// of the defect index — so the artifact is reproducible across machines and runs.
//
// It also owns the SINGLE-PASS reviewer MODEL (`singlePassCatches`): a faithful, deterministic
// stand-in for "current researchPrime Phase-3" = ONE same-lineage reviewer, ONE round, one
// fresh fetch. The baseline (bin/baseline.mjs) runs this model over the manifest to fill each
// record's `single_pass_caught` and compute the miss rate that G is a fraction of. Modelling
// (not invoking a live LLM) keeps the baseline a deterministic, hashable answer key; the
// catch rule is justified per class below and is the load-bearing honesty assumption (I1).

import { FIXTURE_COUNTS } from './fixture-counts.mjs';

// Re-export so callers have one import for both the generator and the agreed counts.
export { FIXTURE_COUNTS };

// The four planted-defect classes (FIXTURE-SPEC "Mandatory defect classes"). The first two
// are VERIFICATION-RECALL classes (recall = caught/planted is meaningful); the last two are
// PROBES scored by other criteria (crit-3 foresight branch-equality; I6 governor tier) and
// are NOT part of the recall denominator.
export const RECALL_CLASSES = Object.freeze(['ordinary', 'correlated-blind-spot']);
export const PROBE_CLASSES = Object.freeze(['path-defect', 'declared-low-but-irreversible']);

/**
 * The SINGLE-PASS reviewer model — "current researchPrime Phase-3" as a pure predicate.
 *
 * A single same-lineage reviewer, one round, one fresh fetch (a G1-style independent check),
 * WITHOUT the multi-round convergence loop, the ≥2-agree quorum, or a cross-lineage origin.
 * Such a reviewer:
 *   • CATCHES an OBVIOUS single-origin factual/citation defect — an `ordinary` defect that one
 *     fresh fetch (G1) resolves and that is salient enough (high/medium severity) to surface on
 *     a single pass. These establish that single-pass ordinary recall is < 1.
 *   • MISSES a SUBTLE (low-severity) ordinary defect — it needs a second reviewer / another
 *     round to surface; the loop (G3 ≥2-agree, G5 convergence-until-dry) is what closes these.
 *   • MISSES EVERY correlated-blind-spot — a same-lineage reviewer reproduces the wrong
 *     consensus by construction (I1/I2). Only a genuinely cross-lineage origin (G8, Enhanced)
 *     can recover a CBS defect, so single-pass CBS recall is 0 — the entire CBS gap is the
 *     loop's (Enhanced's) to close, and is reported as a measured ceiling by default (I1).
 *   • Does not apply to the probe classes (path-defect / irreversible): they are scored by
 *     crit-3 / I6, not by recall, so this predicate returns false for them and the baseline
 *     excludes them from the recall denominator.
 *
 * @param {{class:string, detectable_by?:string[], severity?:string}} defect
 * @returns {boolean} whether the single-pass baseline catches this defect
 */
export function singlePassCatches(defect) {
  if (!defect || defect.class !== 'ordinary') return false; // CBS/probes: never caught single-pass
  const gates = Array.isArray(defect.detectable_by) ? defect.detectable_by : [];
  if (!gates.includes('G1')) return false; // single pass relies on one fresh fetch (G1)
  return defect.severity === 'high' || defect.severity === 'medium';
}

// Pad an integer to a stable 3-wide id suffix so ids sort lexically in index order.
function n3(i) {
  return String(i).padStart(3, '0');
}

/**
 * Generate the full fixture deterministically.
 * @returns {{ corpus: object[], defects: object[] }}
 *   - `defects`: one manifest record per planted defect (FIXTURE-SPEC schema).
 *   - `corpus`: the research claims/sources the defects live in (one carrier per defect).
 */
export function generateFixture() {
  const defects = [];
  const corpus = [];

  const push = (defect, claimText) => {
    defects.push(defect);
    corpus.push({
      id: `claim-${n3(corpus.length + 1)}`,
      kind: 'claim',
      defect_id: defect.id,
      location: defect.location,
      text: claimText,
    });
  };

  // ── 1. Ordinary — single-pass CAUGHT (high/medium severity, G1) ───────────────────────────
  // Establish that single-pass ordinary recall is < 1 (these are the "caught" half).
  for (let i = 1; i <= FIXTURE_COUNTS.ordinaryCaught; i++) {
    const severity = i % 2 === 0 ? 'medium' : 'high';
    const id = `ord-c-${n3(i)}`;
    push(
      {
        id,
        class: 'ordinary',
        location: `claims/${id}.md`,
        ground_truth: `corrected single-origin fact #${i} (one fresh fetch resolves it)`,
        detectable_by: ['G1'],
        single_pass_caught: null, // filled by the baseline run (bin/baseline.mjs)
        severity,
      },
      `Salient claim #${i}: a single-origin factual assertion with a citable error a fresh fetch exposes.`,
    );
  }

  // ── 2. Ordinary — single-pass MISSED (low severity; needs another round/reviewer) ──────────
  // The closable ordinary gap: a second reviewer (G3 ≥2-agree) or another round (G5) catches it.
  for (let i = 1; i <= FIXTURE_COUNTS.ordinaryMissed; i++) {
    const id = `ord-m-${n3(i)}`;
    push(
      {
        id,
        class: 'ordinary',
        location: `claims/${id}.md`,
        ground_truth: `corrected subtle fact #${i} (surfaces only on a second look / second reviewer)`,
        detectable_by: ['G1', 'G3'],
        single_pass_caught: null,
        severity: 'low',
      },
      `Subtle claim #${i}: a low-salience error that a single pass overlooks but a second reviewer flags.`,
    );
  }

  // ── 3. Correlated-blind-spot (CBS) — single-pass MISSED, recoverable only cross-lineage ─────
  // MANDATORY, gating (I2). detectable_by ['G8'] = only a genuinely cross-lineage origin (Enhanced)
  // recovers it; a same-lineage single pass reproduces the wrong consensus (lineage_trap explains it).
  for (let i = 1; i <= FIXTURE_COUNTS.cbs; i++) {
    const severity = i % 3 === 0 ? 'medium' : 'high';
    const id = `cbs-${n3(i)}`;
    push(
      {
        id,
        class: 'correlated-blind-spot',
        location: `claims/${id}.md`,
        ground_truth: `the true value behind the widely-repeated-but-false consensus #${i}`,
        detectable_by: ['G8'],
        single_pass_caught: null,
        severity,
        lineage_trap: `same-lineage reviewers co-miss #${i}: a shared training-data artifact reproduced identically`,
      },
      `Consensus claim #${i}: a plausible, widely-repeated assertion that same-family reviewers all get wrong the same way.`,
    );
  }

  // ── 4. Planted-path-defect probe — crit-3 foresight (NOT a recall defect) ──────────────────
  // Answer key names the exact branch to drop/reorder + its counterfactual cost (FIXTURE-SPEC §4).
  for (let i = 1; i <= FIXTURE_COUNTS.pathDefect; i++) {
    const id = `path-${n3(i)}`;
    push(
      {
        id,
        class: 'path-defect',
        location: `plan/branch-${n3(i)}.md`,
        ground_truth: `drop or reorder research branch B${i} before spending on it`,
        detectable_by: ['Oranges'],
        single_pass_caught: null,
        severity: 'medium',
        wrong_branch: `B${i}`,
        counterfactual_cost: `${i} wasted research rounds if branch B${i} is not dropped/reordered`,
      },
      `Research plan with a deliberately wasteful branch B${i} that good foresight should drop or reorder.`,
    );
  }

  // ── 5. Declared-low-but-irreversible probe — I6 under-call guard (NOT a recall defect) ──────
  // declared_stakes:"low" but reversibility:"irreversible" ⇒ expected_tier ">= medium" (FIXTURE-SPEC §3).
  for (let i = 1; i <= FIXTURE_COUNTS.irreversible; i++) {
    const id = `irr-${n3(i)}`;
    push(
      {
        id,
        class: 'declared-low-but-irreversible',
        location: `recommendations/rec-${n3(i)}.md`,
        ground_truth: `the stakes governor must tier this >= medium despite the low declaration`,
        detectable_by: ['AXIS'],
        single_pass_caught: null,
        severity: 'high',
        declared_stakes: 'low',
        reversibility: 'irreversible',
        expected_tier: '>= medium',
      },
      `A "minor" recommendation #${i} declared low-stakes whose effect, if acted on, cannot be undone.`,
    );
  }

  return { corpus, defects };
}

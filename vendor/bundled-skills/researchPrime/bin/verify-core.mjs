// bin/verify-core.mjs — Wave 6 EVIDENCED VERIFICATION CORE (Phase C-1).
//
// IMPLEMENTATION-PLAN Wave 6 done-when: "G1 CoVe independence, G2 self-consistency (precision-only),
// G7 invariant — each a test; recall measured by LOADING the Wave-3 baseline by hash, broken out by
// source gate AND CBS class; origin counts come from the shared module (Wave 2)." Plus the two
// Given/Then locks:
//   - the audit tries to raise a ladder level without a new pointer ⇒ it throws (I4) in BOTH modes;
//   - a G2-only recall gain ⇒ the crit-1 accuracy number does not move (I5 attribution).
//
// This is the "cheap, measured-first" core (MASTER-PLAN Phase C-1): the three EVIDENCED levers whose
// recall is measured against the frozen single-pass baseline before the round-orchestration loop
// (G3–G9) is built in Wave 7. Each gate is a DETERMINISTIC model (a pure predicate over the planted
// fixture, exactly like fixture.mjs `singlePassCatches`) — no live LLM — so the measured recall is a
// reproducible, hashable answer-key comparison rather than an asserted one.
//
// ── The three levers and the invariant each one carries ───────────────────────────────────────────
// G1  CoVe fresh-fetch independence = ACCURACY. A dedicated Chain-of-Verification re-fetch per claim,
//     more thorough than a single salience-gated pass, so it recovers even the low-salience ordinary
//     defects the single pass overlooked. It is SAME-LINEAGE, so by I1 it can NEVER recover a
//     correlated-blind-spot (a same-lineage fresh fetch reproduces the shared wrong consensus) — CBS
//     recovery is Enhanced/G8 only. Each catch yields a FRESH fetched pointer (a new external bit),
//     which is what lets G1 raise the evidence ladder.
// G2  self-consistency = PRECISION-ONLY (I5). It re-samples the SAME reviewer and keeps a finding only
//     on a strict majority — it reduces variance / suppresses flaky findings, but injects NO new
//     external bits (it can never produce a finding absent from every sample) and yields NO fresh
//     pointer, so it cannot raise the ladder and a G2 recall gain is attributed to precision, never to
//     the crit-1 accuracy number.
// G7  invariant / evidence-ladder audit = DOWNGRADE-ONLY (I4). It audits the ladder and may RAISE a
//     level only with a NEW fetched pointer; a raise without one THROWS, identically in the engine AND
//     the degraded mode (the guard lives in the shared ladder primitive, so no mode can bypass it).
//
// This module is PURE except for reading the frozen fixture + baseline (loadFixture /
// loadBaselineByHash). It NEVER re-implements the origin count — every origin number routes through
// the Wave-2 shared independence-accounting module (the sole counter).

import { loadFixture, loadBaselineByHash } from './baseline.mjs';
import { RECALL_CLASSES } from './fixture.mjs';
// The SOLE origin/quorum counter (Wave 2), resolved via the package `imports` map (#trio-core/*) — the
// single canonical path (crit 6), the same route the engine uses, NOT a `../../` reach or a re-impl.
import { meetsQuorum, STATIC_QUORUM_FLOOR } from '#trio-core/independence-accounting.mjs';

// ── Gate taxonomy: which gates are ACCURACY (move crit-1) vs PRECISION (do not) ──────────────────────
/** Accuracy gates: fresh external evidence. Their recall IS the crit-1 trustworthiness number. */
export const ACCURACY_GATES = Object.freeze(['G1']);
/** Precision gates: variance reduction only. Their recall is precision, NEVER crit-1 accuracy (I5). */
export const PRECISION_GATES = Object.freeze(['G2']);
/** The evidenced core's gates, in C-1 scope. */
export const CORE_GATES = Object.freeze(['G1', 'G2', 'G7']);

/** The correlated-blind-spot class — reported as a measured ceiling by default (I1/I2). */
export const CBS_CLASS = 'correlated-blind-spot';

/** The two run modes the I4 audit guard must hold in (MASTER-PLAN I4: "engine AND degraded"). */
export const MODES = Object.freeze(['engine', 'degraded']);

/**
 * The single same-lineage reviewer family the DEFAULT evidenced core runs as: CoVe (G1) and
 * self-consistency (G2) are the same model, so the core contributes exactly ONE independent origin.
 * Reaching the ≥2 quorum needs the heterogeneous reviewers / cross-lineage origin of Wave 7.
 */
export const CORE_LINEAGE = 'rp-default';

/** The literal stamp the default mode puts on CBS recall (I1: a measured ceiling, never a closure). */
export const CBS_CEILING_STAMP =
  'measured ceiling — default (single-lineage) mode cannot close a correlated blind spot (I1)';

// ── G1 — CoVe fresh-fetch independence (ACCURACY) ───────────────────────────────────────────────────
/**
 * Run the G1 CoVe check over one defect.
 *
 * A Chain-of-Verification fresh re-fetch keyed to the claim's location. It catches an ORDINARY
 * (single-origin) defect that a fresh independent fetch (G1) resolves — at ANY severity, because a
 * dedicated verification question surfaces even the low-salience errors a single salience-gated pass
 * overlooks (that is the accuracy gain over the single-pass baseline). It does NOT catch a
 * correlated-blind-spot (I1: a same-lineage fetch reproduces the shared wrong consensus) and is not
 * defined over the probe classes.
 *
 * @param {{class:string, detectable_by?:string[], location?:string}} defect
 * @returns {{ caught:boolean, pointer:?string }} `pointer` is the FRESH fetched citation (the new
 *   external bit) on a catch — the thing that lets G1 raise the evidence ladder — and null on a miss.
 */
export function g1Verify(defect) {
  const isOrdinary = !!defect && defect.class === 'ordinary';
  const gates = isOrdinary && Array.isArray(defect.detectable_by) ? defect.detectable_by : [];
  const caught = isOrdinary && gates.includes('G1');
  const pointer = caught ? `g1:fresh-fetch:${defect.location ?? defect.id ?? 'claim'}` : null;
  return { caught, pointer };
}

/** Thin predicate: does the G1 CoVe check catch this defect? (the recall model). */
export function g1Catches(defect) {
  return g1Verify(defect).caught;
}

// ── G2 — self-consistency (PRECISION-ONLY, I5) ──────────────────────────────────────────────────────
/**
 * Run G2 self-consistency over K independent SAMPLES of the SAME (same-lineage) reviewer: keep a
 * finding only if it appears in a STRICT MAJORITY of samples (variance reduction). This is
 * precision-only by construction:
 *   - it can CONFIRM a finding the samples already produced and SUPPRESS a flaky minority finding;
 *   - it can NEVER introduce a finding absent from every sample (no new external bits) — such an id
 *     is in neither `confirmed` nor `suppressed`;
 *   - it yields NO fresh fetched pointer (`pointer:null`) — re-sampling fetches nothing new — so it
 *     CANNOT raise the evidence ladder (I4/I5). The null pointer IS that contract, machine-checkable.
 *
 * @param {Array<Array<string>>} samples one finding-id array per sample of the same reviewer
 * @returns {{ confirmed:string[], suppressed:string[], pointer:null }}
 */
export function g2SelfConsistency(samples) {
  if (!Array.isArray(samples) || samples.some((s) => !Array.isArray(s))) {
    throw new TypeError('g2SelfConsistency(samples): samples must be an array of finding-id arrays');
  }
  const k = samples.length;
  const counts = new Map();
  for (const sample of samples) {
    for (const id of new Set(sample)) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  const confirmed = [];
  const suppressed = [];
  for (const [id, c] of counts) {
    (c * 2 > k ? confirmed : suppressed).push(id); // strict majority: c > k/2
  }
  confirmed.sort();
  suppressed.sort();
  return { confirmed, suppressed, pointer: null };
}

// ── G7 — invariant / evidence-ladder audit (DOWNGRADE-ONLY, I4; BOTH modes) ─────────────────────────
/**
 * Audit the evidence ladder (the one the engine OWNS, Wave 5 `makeLadder`). The audit may:
 *   - 'raise': raise the ladder one level — REQUIRES a NEW fetched pointer (I4). A missing / blank /
 *     re-used pointer THROWS, identically in BOTH modes: the guard is inside the shared ladder
 *     primitive, so neither the engine nor the degraded host can bypass it.
 *   - 'lower': downgrade (no new pointer needed — an audit may always lower its claim).
 *   - 'audit' (default): inspect the level without changing it.
 *
 * @param {{raise:Function, lower:Function, level:Function}} ladder a Wave-5 `makeLadder()` instance
 * @param {{ mode?:string, action?:'raise'|'lower'|'audit', pointer?:?string }} [opts]
 * @returns {{ mode:string, action:string, level:number, raised:boolean }}
 */
export function runG7Audit(ladder, { mode = 'engine', action = 'audit', pointer = null } = {}) {
  if (!MODES.includes(mode)) {
    throw new RangeError(`runG7Audit: unknown mode ${JSON.stringify(mode)} (expected one of ${MODES.join(', ')})`);
  }
  if (!ladder || typeof ladder.raise !== 'function' || typeof ladder.level !== 'function') {
    throw new TypeError('runG7Audit requires a ladder (Wave-5 makeLadder instance)');
  }
  if (action === 'raise') {
    // I4 in BOTH modes: ladder.raise throws on a missing/blank/re-used pointer regardless of mode.
    const level = ladder.raise(pointer);
    return { mode, action, level, raised: true };
  }
  if (action === 'lower') {
    return { mode, action, level: ladder.lower(1), raised: false };
  }
  return { mode, action: 'audit', level: ladder.level(), raised: false };
}

// ── Recall ATTRIBUTION — the I5 load-bearing partition ──────────────────────────────────────────────
/**
 * Partition a set of per-defect catches into the crit-1 ACCURACY recall vs the precision-only
 * contribution (I5). Each catch names the defect id, its class, and the gate(s) that caught it.
 *
 *   - accuracy_caught       = defects caught by ≥1 ACCURACY gate (G1). THIS is the crit-1 number.
 *   - precision_only_caught = defects caught ONLY by a precision gate (G2), never by an accuracy gate.
 *
 * `crit1_accuracy_recall` is computed from accuracy_caught ALONE, so adding a G2-only catch raises the
 * blended recall but can NEVER move the crit-1 accuracy number (I5). A defect caught by BOTH an
 * accuracy and a precision gate counts as accuracy (the precision gate adds nothing to it).
 *
 * @param {Array<{id:string, class?:string, gates:string[]}>} catches
 * @param {{ planted:number }} opts  the recall denominator (planted recall-class defects)
 * @returns {{ accuracy_caught:number, precision_only_caught:number, blended_caught:number,
 *   crit1_accuracy_recall:number, blended_recall:number, by_gate:Record<string,number> }}
 */
export function attributeRecall(catches, { planted } = {}) {
  if (!Array.isArray(catches)) throw new TypeError('attributeRecall(catches): catches must be an array');
  if (!Number.isInteger(planted) || planted <= 0) {
    throw new RangeError('attributeRecall requires a positive integer `planted` denominator');
  }
  const acc = new Set(ACCURACY_GATES);
  const prec = new Set(PRECISION_GATES);
  const byGate = {};
  const accuracyCaught = new Set();
  const precisionOnlyCaught = new Set();

  for (const c of catches) {
    const gates = Array.isArray(c.gates) ? c.gates : [];
    for (const g of gates) byGate[g] = (byGate[g] ?? 0) + 1;
    const hitAccuracy = gates.some((g) => acc.has(g));
    const hitPrecision = gates.some((g) => prec.has(g));
    if (hitAccuracy) accuracyCaught.add(c.id);
    else if (hitPrecision) precisionOnlyCaught.add(c.id);
  }

  const blended = accuracyCaught.size + precisionOnlyCaught.size;
  return {
    accuracy_caught: accuracyCaught.size,
    precision_only_caught: precisionOnlyCaught.size,
    blended_caught: blended,
    crit1_accuracy_recall: accuracyCaught.size / planted,
    blended_recall: blended / planted,
    by_gate: byGate,
  };
}

// ── Measure the core's recall against the frozen Wave-3 baseline (by hash) ───────────────────────────
/**
 * Run the evidenced core over the frozen fixture and measure its recall against the single-pass
 * baseline LOADED BY HASH (Wave-3 frozen artifact), broken out BY SOURCE GATE and BY CLASS (incl. the
 * CBS class). The crit-1 accuracy number is attributed to accuracy gates only (I5); CBS recall is
 * reported as a measured ceiling (I1); independent origins come from the shared module (Wave 2).
 *
 * @param {{ baselineHash:string, gates?:string[] }} o
 *   - baselineHash: the frozen Wave-3 baseline hash the caller PINS (load-by-hash; a wrong/regenerated
 *     baseline throws — a later wave never measures against the wrong baseline).
 *   - gates: which core gates are active (default G1+G2; G2 originates no catch on real planted
 *     defects — no defect is detectable_by G2, I5 — so it appears only as precision).
 * @returns {object} the measured recall report.
 */
export function measureRecall({ baselineHash, gates = ['G1', 'G2'] } = {}) {
  if (typeof baselineHash !== 'string' || baselineHash.length === 0) {
    throw new TypeError('measureRecall requires the frozen baselineHash to load by (Wave-3 load-by-hash)');
  }
  const baseline = loadBaselineByHash(baselineHash); // loads + verifies the frozen Wave-3 baseline
  const { defects } = loadFixture();
  const recallDefects = defects.filter((d) => RECALL_CLASSES.includes(d.class));
  const planted = recallDefects.length;

  const useG1 = gates.includes('G1');

  // Per-defect catch list, each catch tagged with the gate(s) that caught it. (G2 catches nothing over
  // real planted defects — no defect is detectable_by G2; I5: it injects no new external bits.)
  const catches = [];
  for (const d of recallDefects) {
    const caughtGates = [];
    if (useG1 && g1Catches(d)) caughtGates.push('G1');
    if (caughtGates.length) catches.push({ id: d.id, class: d.class, gates: caughtGates });
  }

  const attribution = attributeRecall(catches, { planted });

  // Breakout BY CLASS (incl. the CBS class explicitly).
  const byClass = {};
  for (const cls of RECALL_CLASSES) {
    const inClass = recallDefects.filter((d) => d.class === cls).length;
    const caughtInClass = catches.filter((c) => c.class === cls).length;
    byClass[cls] = {
      planted: inClass,
      caught: caughtInClass,
      recall: inClass ? caughtInClass / inClass : 0,
    };
  }

  // Gap-closure vs the single-pass baseline (accuracy-attributed; crit-1): of the defects the single
  // pass MISSED, how many an accuracy gate now catches. The denominator is the baseline's frozen
  // single-pass miss count — i.e. G is a fraction of THIS (crit-1).
  const singlePassMisses = baseline.gap_closure_denominator.single_pass_misses;
  const accuracyCaughtIds = new Set(
    catches.filter((c) => c.gates.some((g) => ACCURACY_GATES.includes(g))).map((c) => c.id),
  );
  const closed = recallDefects.filter(
    (d) => d.single_pass_caught === false && accuracyCaughtIds.has(d.id),
  ).length;

  // Independent origins via the SHARED module (the sole counter, Wave 2). The default core is ONE
  // same-lineage reviewer family ⇒ exactly ONE origin ⇒ it does NOT meet the ≥2 quorum on its own.
  const quorum = meetsQuorum([{ lineage: CORE_LINEAGE }], { staticFloor: STATIC_QUORUM_FLOOR });

  return {
    baseline_hash: baselineHash,
    gates: [...gates],
    recall_class_planted: planted,
    loop: {
      caught: attribution.blended_caught,
      planted,
      recall: attribution.blended_recall,
      by_class: byClass,
      by_gate: attribution.by_gate,
    },
    accuracy: { caught: attribution.accuracy_caught, recall: attribution.crit1_accuracy_recall },
    precision: { precision_only_caught: attribution.precision_only_caught },
    crit1_accuracy_recall: attribution.crit1_accuracy_recall,
    blended_recall: attribution.blended_recall,
    gap_closure: {
      single_pass_misses: singlePassMisses,
      closed,
      fraction: singlePassMisses ? closed / singlePassMisses : 0,
    },
    // I1/I2 honesty: report CBS recall as a MEASURED CEILING, never a closed result.
    cbs: { recall: byClass[CBS_CLASS].recall, ceiling: true, stamp: CBS_CEILING_STAMP },
    quorum,
    cross_model: false, // default same-lineage core: no cross-lineage origin (I3). Enhanced = Wave 7.
    baseline_recall: {
      overall: baseline.single_pass.recall,
      by_class: {
        ordinary: baseline.single_pass.by_class.ordinary.recall,
        [CBS_CLASS]: baseline.single_pass.by_class[CBS_CLASS].recall,
      },
    },
  };
}

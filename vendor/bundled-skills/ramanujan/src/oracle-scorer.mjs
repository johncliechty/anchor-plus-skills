// Wave 25 — Gradeable oracle, part B: Metric-G scorer + canned baseline + ablation (E1b).
//
// THE HONESTY LAW (NS9) is only as trustworthy as the MEASUREMENT that grades it. Wave 24 built the
// labeled fixture CORPUS + the red-team set (src/oracle-corpus.mjs); this module is the SCORER half:
// a DETERMINISTIC grader that runs the REAL spine over the corpus and computes
//
//     Metric G = catch-rate − false-positive-rate
//
// where (DESCRIPTION §Residuals · R1 / Metric-G — the canonical SCORED-SUBSET token, used identically
// here and in the Wave-25 done-when):
//   • catch-rate          is over the SCORED SUBSET = the planted-defect computational/firewall
//                          fixtures (the 6 defect classes × ≥3 instances; subset === SUBSET.SCORED).
//                          The FIXED 6-fixture SOUND subset is EXCLUDED from the catch-rate denominator.
//   • false-positive-rate is over the FIXED 6-fixture SOUND subset ONLY (subset === SUBSET.SOUND); it
//                          supplies the k′ term (a single load-bearing cardinality shared by k′ and the
//                          G false-positive-rate — R1).
//
// A "scorer" here is a single load-bearing knob: the BATTERY — a predicate `flagged(fixture)` that
// answers "does the honesty-law machinery WITHHOLD this fixture (flag / abstain / abandon / refuse)?".
// G is then computed by the IDENTICAL formula for every scorer (the done-when's "G computed
// identically"); only the battery differs:
//
//   • BATTERY_ON          — the REAL spine. A defect fixture is flagged via its Wave-24 in-process
//                           probe (which drives the real firewall grammar / firewall builder / CONTROL /
//                           Step-0 classifier / exact re-execution); a sound fixture is flagged iff it
//                           is genuinely inconsistent (so a real sound fixture is NOT flagged ⇒ settles).
//   • ABLATION            — the battery DISABLED: `flagged` ≡ false, so nothing is withheld and every
//                           fixture is greened. This is the load-bearing demonstration: with the battery
//                           off the catch-rate collapses, so G collapses (battery is load-bearing).
//   • STUB_ALWAYS_ABSTAIN — a canned baseline that blanket-ABSTAINs: `flagged` ≡ true (withholds every
//                           fixture, content-blind).
//   • STUB_ALWAYS_FLAG    — a canned baseline that blanket-FLAGs every fixture as defective: `flagged`
//                           ≡ true. The two stubs name two distinct verdicts (ABSTAIN vs FLAG) but for
//                           the binary settle/withhold grading they coincide — NEITHER content-blind
//                           constant scorer can separate defects from sound, so each scores G = 0. That
//                           is the point of pinning BOTH: whichever trivial baseline you pick, the real
//                           battery must beat it by the epsilon.
//
// THE ORACLE GATE (the Wave-25 done-when, every constant pinned below):
//   • G(BATTERY_ON) > G(better stub) + 0.30 (STRICT)                         — beatsBaseline
//   • G(BATTERY_ON) − G(ABLATION) > 0.30 (the ablation arm drops measurably) — ablationLoadBearing
//   • per-class catch floors: derivation/dimensional/off-by-one = 100%,
//       convergence-stability/comprehension-narrative/firewall-inapplicable ≥ 2/3 each
//   • k′ = at most 1 false positive on the FIXED 6-fixture SOUND subset      — kPrimeMet
//   • ABSTAIN-correctness = 100% of proof/conceptual arms ABSTAIN            — abstainMet
//
// This module COMPOSES the Wave-24 corpus + its in-process probes and the real VERIFY router; it
// re-implements no spine logic. Pure node built-ins + the project's own modules. Runs under
// `node --test test/`.

import { ClaimLedger, compareRungs } from './claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from './verify-router.mjs';
import {
  loadCorpus,
  SUBSET,
  DEFECT_CLASSES,
  SOUND_SUBSET_CARDINALITY,
  computationalDefectIsReal,
  soundFixtureIsConsistent,
  dimensionalDefectIsCaught,
  convergenceDefectIsCaught,
  comprehensionDefectIsCaught,
  firewallInapplicableIsCaught,
  // Phase-F (Increment-2 / Wave 6) — the certifier categorical gate.
  loadPhaseFCorpus,
  runPhaseFFixture,
  plantedUnfaithfulIsNecessaryNotSufficient,
  PHASEF_OUTCOME,
  PHASEF_DEFECT_CLASSES,
  PHASEF_POSITIVE_CLASSES,
  PHASEF_BOUND_CLASSES,
  RUNG,
  OBSERVED_RUNG,
} from './oracle-corpus.mjs';

// ---------------------------------------------------------------------------
// PINNED CONSTANTS (the Wave-25 done-when cites each of these — DESCRIPTION §Residuals · R1 / Metric-G).
// ---------------------------------------------------------------------------

/** The strict epsilon: BATTERY_ON must beat the better stub (and the ablation drop must exceed) by this. */
export const G_EPSILON = 0.3;

/**
 * Per-class catch FLOORS as exact integer fractions {num, den} (compared by cross-multiplying counts —
 * no float, so 2/3 is exact). derivation/dimensional/off-by-one = 100%; the three harder narrative /
 * control / applicability classes ≥ 2/3 each.
 */
export const PER_CLASS_CATCH_FLOORS = Object.freeze({
  'derivation-error': Object.freeze({ num: 1, den: 1 }),
  dimensional: Object.freeze({ num: 1, den: 1 }),
  'off-by-one': Object.freeze({ num: 1, den: 1 }),
  'convergence-stability': Object.freeze({ num: 2, den: 3 }),
  'comprehension-narrative': Object.freeze({ num: 2, den: 3 }),
  'firewall-inapplicable': Object.freeze({ num: 2, den: 3 }),
});

/** k′ — at most ONE false positive (absolute integer) on the FIXED 6-fixture SOUND subset (R1). */
export const K_PRIME_MAX = 1;

/** ABSTAIN-correctness floor: 100% of the proof/conceptual arms must ABSTAIN + route. */
export const ABSTAIN_CORRECTNESS_FLOOR = 1;

/** The four pinned scorers (the battery-on system, the ablation arm, and the two canned stub baselines). */
export const SCORER = Object.freeze({
  BATTERY_ON: 'battery-on',
  ABLATION: 'ablation',
  STUB_ALWAYS_ABSTAIN: 'stub-always-abstain',
  STUB_ALWAYS_FLAG: 'stub-always-flag',
});

/** The two canned stub baselines (the pinned canned baseline — DESCRIPTION §Residuals · Metric-G). */
export const STUB_SCORERS = Object.freeze([SCORER.STUB_ALWAYS_ABSTAIN, SCORER.STUB_ALWAYS_FLAG]);

// ---------------------------------------------------------------------------
// THE BATTERIES — `flagged(fixture)` predicates. The ONLY thing that varies between scorers.
// ---------------------------------------------------------------------------

/**
 * The REAL battery. For a SCORED-subset defect fixture, dispatch to the Wave-24 in-process probe (each
 * drives the real spine: exact re-execution, the firewall builder, CONTROL's gap-function, the Step-0
 * applicability classifier, or the closed default-deny grammar). For a SOUND-subset fixture, flagged
 * iff it is genuinely INCONSISTENT — so a real (consistent) sound fixture is NOT flagged and settles.
 */
export function realBatteryFlags(fixture) {
  switch (fixture.class) {
    case 'derivation-error':
    case 'off-by-one':
      return computationalDefectIsReal(fixture);
    case 'dimensional':
      return dimensionalDefectIsCaught(fixture);
    case 'convergence-stability':
      return convergenceDefectIsCaught(fixture);
    case 'comprehension-narrative':
      return comprehensionDefectIsCaught(fixture);
    case 'firewall-inapplicable':
      return firewallInapplicableIsCaught(fixture);
    case 'sound':
      return !soundFixtureIsConsistent(fixture);
    default:
      throw new Error(`realBatteryFlags: fixture ${fixture.id} has a non-scored class ${fixture.class}`);
  }
}

/** name → battery predicate. The ablation disables the battery; both stubs are content-blind constants. */
const BATTERIES = Object.freeze({
  [SCORER.BATTERY_ON]: realBatteryFlags,
  [SCORER.ABLATION]: () => false, // battery OFF ⇒ nothing withheld ⇒ everything greened
  [SCORER.STUB_ALWAYS_ABSTAIN]: () => true, // blanket-ABSTAIN ⇒ withhold every fixture
  [SCORER.STUB_ALWAYS_FLAG]: () => true, // blanket-FLAG ⇒ withhold every fixture
});

/** The pinned scorer names, in a stable order. */
export const SCORER_NAMES = Object.freeze(Object.keys(BATTERIES));

// ---------------------------------------------------------------------------
// THE SCORED + SOUND SUBSETS — selected from the Wave-24 corpus (the canonical SCORED-SUBSET token).
// ---------------------------------------------------------------------------

/** The SCORED SUBSET: every planted-defect fixture (subset === SUBSET.SCORED), in a stable class order. */
export function scoredSubset(corpus = loadCorpus()) {
  const flat = [];
  for (const klass of DEFECT_CLASSES) {
    for (const f of corpus.defects[klass]) {
      if (f.subset !== SUBSET.SCORED) throw new Error(`scoredSubset: ${f.id} is not in the SCORED subset`);
      flat.push(f);
    }
  }
  return flat;
}

/** The FIXED 6-fixture SOUND subset (subset === SUBSET.SOUND) — the false-positive / k′ term ONLY. */
export function soundSubset(corpus = loadCorpus()) {
  const flat = corpus.sound.filter((f) => f.subset === SUBSET.SOUND);
  if (flat.length !== SOUND_SUBSET_CARDINALITY) {
    throw new Error(`soundSubset: expected ${SOUND_SUBSET_CARDINALITY} sound fixtures, got ${flat.length}`);
  }
  return flat;
}

// ---------------------------------------------------------------------------
// THE SCORER — Metric G, computed by the IDENTICAL formula for every battery.
// ---------------------------------------------------------------------------

/**
 * Score one scorer over the corpus. Returns a frozen report:
 *   {
 *     scorer,
 *     scored: { total, caught, catchRate },                 // catch-rate denominator = SCORED subset
 *     perClass: { <class>: { total, caught, rate } },       // per-class catch (battery-on floors)
 *     sound:  { total, falsePositives, fpRate, kPrime },    // FP / k′ over the SOUND subset ONLY
 *     G,                                                     // catchRate − fpRate (identical formula)
 *   }
 * A defect is CAUGHT iff the battery flags it (the oracle does NOT green it). A sound fixture is a
 * FALSE POSITIVE iff the battery flags it (the oracle wrongly withholds a genuinely-sound computation).
 *
 * @param {keyof typeof BATTERIES | string} scorerName
 */
export function scoreScorer(scorerName, { corpus = loadCorpus() } = {}) {
  const flagged = BATTERIES[scorerName];
  if (typeof flagged !== 'function') {
    throw new Error(`scoreScorer: unknown scorer ${JSON.stringify(scorerName)} (expected one of ${SCORER_NAMES.join(', ')})`);
  }

  const scored = scoredSubset(corpus);
  const sound = soundSubset(corpus);

  const perClass = {};
  for (const klass of DEFECT_CLASSES) {
    const fixtures = corpus.defects[klass];
    const caught = fixtures.reduce((n, f) => n + (flagged(f) ? 1 : 0), 0);
    perClass[klass] = Object.freeze({ total: fixtures.length, caught, rate: caught / fixtures.length });
  }

  const scoredCaught = scored.reduce((n, f) => n + (flagged(f) ? 1 : 0), 0);
  const catchRate = scoredCaught / scored.length;

  // On the SOUND subset, a flagged fixture is a FALSE POSITIVE (it should have settled). k′ = the
  // absolute count; the FP-RATE is the same observations expressed as a rate (R1's shared cardinality).
  const falsePositives = sound.reduce((n, f) => n + (flagged(f) ? 1 : 0), 0);
  const fpRate = falsePositives / sound.length;

  const G = catchRate - fpRate;

  return Object.freeze({
    scorer: scorerName,
    scored: Object.freeze({ total: scored.length, caught: scoredCaught, catchRate }),
    perClass: Object.freeze(perClass),
    sound: Object.freeze({ total: sound.length, falsePositives, fpRate, kPrime: falsePositives }),
    G,
  });
}

// ---------------------------------------------------------------------------
// ABSTAIN-CORRECTNESS — 100% of the proof/conceptual arms ABSTAIN + route through the REAL router.
// ---------------------------------------------------------------------------

/**
 * The proof/conceptual ABSTAIN arms: the dedicated abstain-payload fixture (a proof obligation) plus
 * the comprehension-narrative sub-claims whose underlying claim is proof-bearing or conceptual. Each
 * must route to ABSTAIN (no autonomous verifier in Increment-1).
 */
export function proofConceptualAbstainArms(corpus = loadCorpus()) {
  const arms = [];
  const ap = corpus.abstainPayload;
  arms.push(Object.freeze({ id: ap.claim.id, type: ap.claim.type, statement: ap.claim.statement, source: ap.id }));
  for (const f of corpus.defects['comprehension-narrative']) {
    const sc = f.subclaim;
    if (sc && (sc.type === 'proof-bearing' || sc.type === 'conceptual')) {
      arms.push(Object.freeze({ id: f.id, type: sc.type, statement: sc.statement, source: f.id }));
    }
  }
  return Object.freeze(arms);
}

/**
 * Measure ABSTAIN-correctness over the proof/conceptual arms by routing each through the REAL
 * VerifyRouter (no dispatcher ⇒ a proof/conceptual claim has no autonomous verifier ⇒ ABSTAIN+route).
 * Returns { total, abstained, rate, results }. rate = abstained / total (1 when there are no arms).
 */
export function measureAbstainCorrectness(corpus = loadCorpus()) {
  const arms = proofConceptualAbstainArms(corpus);
  const results = arms.map((arm) => {
    const ledger = new ClaimLedger();
    const router = new VerifyRouter({ ledger });
    const r = router.route({ id: arm.id, type: arm.type, statement: arm.statement });
    return Object.freeze({
      id: arm.id,
      source: arm.source,
      type: arm.type,
      abstained: r.verdict === ROUTE_VERDICT.ABSTAIN && r.routed === true && r.advisory !== null,
    });
  });
  const abstained = results.filter((r) => r.abstained).length;
  return Object.freeze({
    total: arms.length,
    abstained,
    rate: arms.length === 0 ? 1 : abstained / arms.length,
    results: Object.freeze(results),
  });
}

// ---------------------------------------------------------------------------
// THE ORACLE GATE — the full Wave-25 done-when, citing every pinned constant. HALT iff !pass.
// ---------------------------------------------------------------------------

/** A defect class meets its floor iff caught/total ≥ floor, compared as exact integers (no float). */
function classFloorMet(klass, perClass) {
  const { caught, total } = perClass[klass];
  const floor = PER_CLASS_CATCH_FLOORS[klass];
  return caught * floor.den >= floor.num * total;
}

/**
 * Run the WHOLE oracle gate: score battery-on, the ablation arm, and both canned stubs; measure
 * abstain-correctness; and evaluate every pinned acceptance check. Returns a frozen report whose
 * `pass` is the Wave-25 done-when (the orchestrator HALTs the wave on `pass === false`).
 *
 *   {
 *     pass,
 *     scores: { batteryOn, ablation, stubAbstain, stubFlag },
 *     betterStubG, abstain,
 *     checks: { beatsBaseline, ablationLoadBearing, perClassFloorsMet, kPrimeMet, abstainMet },
 *     perClassFloors,            // per-class { caught, total, rate, floor, met }
 *     epsilon,
 *   }
 */
export function runOracleGate({ corpus = loadCorpus() } = {}) {
  const batteryOn = scoreScorer(SCORER.BATTERY_ON, { corpus });
  const ablation = scoreScorer(SCORER.ABLATION, { corpus });
  const stubAbstain = scoreScorer(SCORER.STUB_ALWAYS_ABSTAIN, { corpus });
  const stubFlag = scoreScorer(SCORER.STUB_ALWAYS_FLAG, { corpus });

  // The "better stub" — the canned baseline the real battery must STILL beat by the epsilon.
  const betterStubG = Math.max(stubAbstain.G, stubFlag.G);

  const abstain = measureAbstainCorrectness(corpus);

  const beatsBaseline = batteryOn.G > betterStubG + G_EPSILON; // STRICT
  // The ablation arm scores MEASURABLY lower: the drop from battery-on must exceed the epsilon (the GWT
  // "G drops below battery-on by more than 0.30" — the battery is load-bearing).
  const ablationLoadBearing = batteryOn.G - ablation.G > G_EPSILON;

  const perClassFloors = {};
  for (const klass of DEFECT_CLASSES) {
    const pc = batteryOn.perClass[klass];
    perClassFloors[klass] = Object.freeze({
      caught: pc.caught,
      total: pc.total,
      rate: pc.rate,
      floor: PER_CLASS_CATCH_FLOORS[klass],
      met: classFloorMet(klass, batteryOn.perClass),
    });
  }
  const perClassFloorsMet = DEFECT_CLASSES.every((klass) => perClassFloors[klass].met);

  const kPrimeMet = batteryOn.sound.kPrime <= K_PRIME_MAX;
  const abstainMet = abstain.rate >= ABSTAIN_CORRECTNESS_FLOOR;

  const pass = beatsBaseline && ablationLoadBearing && perClassFloorsMet && kPrimeMet && abstainMet;

  return Object.freeze({
    pass,
    scores: Object.freeze({ batteryOn, ablation, stubAbstain, stubFlag }),
    betterStubG,
    abstain,
    checks: Object.freeze({ beatsBaseline, ablationLoadBearing, perClassFloorsMet, kPrimeMet, abstainMet }),
    perClassFloors: Object.freeze(perClassFloors),
    epsilon: G_EPSILON,
  });
}

// ===========================================================================
// PHASE-F ORACLE GATE (Increment-2 / Wave 6) — the certifiers are load-bearing, CATEGORICALLY.
//
// Unlike Metric-G (a delta over a SCORED subset), the Phase-F gate is a CATEGORICAL pass: EVERY fixture
// in each class must behave EXACTLY per its class with the certifiers ON, and the ABLATION (certifiers OFF
// ⇒ the deferred Increment-1 abstain arm) must revert EVERY fixture to ABSTAIN. It composes the Wave-6
// Phase-F corpus + its real-spine probes (src/oracle-corpus.mjs); it re-implements no certifier logic.
//
// THE DONE-WHEN (Wave 6, every clause an independent check below):
//   • EVERY planted-unfaithful case is OBSERVED-BLOCKED ON / ABSTAINED OFF;
//   • EVERY false-Lean case REJECTS ON / ABSTAINS OFF;
//   • EVERY cross-family-disagreement stays CONJECTURAL (no lift) ON and OFF;
//   • EVERY quarantine case has its lift DISABLED ON and OFF;
//   • forged/replayed/cross-claim artifacts are BLOCKED; a plausible-but-wrong proof earns no corroboration;
//   • the GENUINE positive arm LIFTS ON but only ABSTAINS OFF (the ablation is LOAD-BEARING);
//   • honest bounds: a correlated cross-family agreement stays SOFT (< OBSERVED); an out-of-z3-decidable
//     formalization fails-CLOSED (OBSERVED WITHHELD);
//   • ≥ PHASEF_MIN_PER_CLASS fixtures per defect/positive class.
// ===========================================================================

/** The ≥k floor: each Phase-F defect/positive class carries at least this many fixtures (the done-when's ≥k). */
export const PHASEF_MIN_PER_CLASS = 3;

/** Is a rung a SETTLED-class (OBSERVED or above) lift? */
function isSettledRung(rung) {
  return compareRungs(rung, OBSERVED_RUNG) >= 0;
}

/** Is a rung a LIFTED rung (anything above the UNVERIFIED floor)? */
function isLiftedRung(rung) {
  return compareRungs(rung, RUNG.UNVERIFIED) > 0;
}

/**
 * Run the WHOLE Phase-F oracle gate: drive every fixture through the certifier ON + the ablation OFF, then
 * evaluate every categorical clause of the Wave-6 done-when. Returns a frozen report whose `pass` is the
 * gate (the orchestrator HALTs the wave on `pass === false`). Async — it awaits the real adjudicators.
 *
 *   {
 *     pass,
 *     results: [ { id, class, verifier, expected_outcome, on:{outcome,rung}, off:{outcome,rung} }, … ],
 *     byClass: { <class>: { total, results } },
 *     checks: { plantedUnfaithfulBlocked, falseLeanRejects, xfamDisagreementConjectural,
 *               quarantineDisablesLift, forgedReplayedBlocked, plausibleButWrongRejected,
 *               positiveArmLifts, ablationLoadBearing, ablationRevertsAll, correlatedStaysSoft,
 *               outOfEnvelopeWithheld, necessaryNotSufficient, minPerClassMet },
 *     perClass: { <class>: { total, allOn, allOff, met } },
 *   }
 */
export async function runPhaseFOracleGate({ corpus = loadPhaseFCorpus() } = {}) {
  const O = PHASEF_OUTCOME;

  // Drive every fixture (certifier ON + ablation OFF) once.
  const results = [];
  for (const f of corpus.flat) results.push(await runPhaseFFixture(f));

  const byClass = {};
  for (const f of corpus.flat) {
    (byClass[f.class] ||= []).push(results.find((r) => r.id === f.id));
  }

  const inClass = (klass) => byClass[klass] || [];
  const everyOn = (klass, pred) => inClass(klass).every((r) => pred(r.on));
  const everyOff = (klass, pred) => inClass(klass).every((r) => pred(r.off));

  // (1) planted-unfaithful: BLOCKED ON (OBSERVED hard-faults, no lift) / ABSTAIN OFF.
  const plantedUnfaithfulBlocked =
    everyOn('phasef-planted-unfaithful', (on) => on.outcome === O.BLOCKED && !isSettledRung(on.rung)) &&
    everyOff('phasef-planted-unfaithful', (off) => off.outcome === O.ABSTAIN);

  // (2) false-Lean: REJECTED ON / ABSTAIN OFF.
  const falseLeanRejects =
    everyOn('phasef-false-lean', (on) => on.outcome === O.REJECTED && !isLiftedRung(on.rung)) &&
    everyOff('phasef-false-lean', (off) => off.outcome === O.ABSTAIN);

  // (3) cross-family-disagreement: no lift, stays CONJECTURAL (ABSTAIN) ON and OFF.
  const xfamDisagreementConjectural =
    everyOn('phasef-xfam-disagreement', (on) => on.outcome === O.ABSTAIN && !isLiftedRung(on.rung)) &&
    everyOff('phasef-xfam-disagreement', (off) => off.outcome === O.ABSTAIN);

  // (4) quarantine: the lift is DISABLED (no ≥2 trusted quorum) ON and OFF.
  const quarantineDisablesLift =
    everyOn('phasef-quarantine', (on) => on.outcome === O.ABSTAIN && !isLiftedRung(on.rung)) &&
    everyOff('phasef-quarantine', (off) => off.outcome === O.ABSTAIN);

  // (5) forged/replayed/cross-claim: BLOCKED ON (caught by the independent re-run / binding) / ABSTAIN OFF.
  const forgedReplayedBlocked =
    everyOn('phasef-forged-replayed', (on) => on.outcome === O.BLOCKED && !isLiftedRung(on.rung)) &&
    everyOff('phasef-forged-replayed', (off) => off.outcome === O.ABSTAIN);

  // (6) plausible-but-wrong: the cross-family verifier REJECTS it (no corroboration) ON / ABSTAIN OFF.
  const plausibleButWrongRejected =
    everyOn('phasef-plausible-but-wrong', (on) => on.outcome === O.ABSTAIN && !isLiftedRung(on.rung)) &&
    everyOff('phasef-plausible-but-wrong', (off) => off.outcome === O.ABSTAIN);

  // (7) the GENUINE positive arm LIFTS ON (OBSERVED / soft-CORROBORATED) but only ABSTAINS OFF.
  const positiveArmLifts = PHASEF_POSITIVE_CLASSES.every(
    (klass) =>
      everyOn(klass, (on) => (on.outcome === O.OBSERVED || on.outcome === O.CORROBORATED) && isLiftedRung(on.rung)) &&
      everyOff(klass, (off) => off.outcome === O.ABSTAIN && !isLiftedRung(off.rung)),
  );

  // (8) the ablation is LOAD-BEARING: every positive fixture LIFTS ON but its lift COLLAPSES to ABSTAIN
  // under the ablation (on.outcome ≠ off.outcome) — so the certifier is what does the lifting.
  const positiveResults = PHASEF_POSITIVE_CLASSES.flatMap((klass) => inClass(klass));
  const ablationLoadBearing =
    positiveResults.length > 0 &&
    positiveResults.every((r) => isLiftedRung(r.on.rung) && r.off.outcome === O.ABSTAIN && r.on.outcome !== r.off.outcome);

  // (9) the ablation reverts EVERY fixture (defect + positive + bound) to ABSTAIN (the Increment-1 arm).
  const ablationRevertsAll = results.every((r) => r.off.outcome === O.ABSTAIN);

  // (10) honest bound — a CORRELATED cross-family agreement stays SOFT (lifts, but strictly BELOW OBSERVED).
  const correlatedStaysSoft = everyOn(
    'phasef-correlated-failure',
    (on) => on.outcome === O.CORROBORATED && isLiftedRung(on.rung) && !isSettledRung(on.rung),
  );

  // (11) honest bound — an out-of-z3-decidable formalization fails-CLOSED (OBSERVED WITHHELD).
  const outOfEnvelopeWithheld = everyOn('phasef-out-of-envelope', (on) => on.outcome === O.WITHHELD);

  // (12) the §v2.1 NECESSARY-NOT-SUFFICIENT proof: each planted-unfaithful case PASSES the enumerated
  // instance battery yet the bounded DIFFERENTIAL catches the divergence (the bound is load-bearing).
  let necessaryNotSufficient = inClass('phasef-planted-unfaithful').length > 0;
  for (const f of corpus.byClass['phasef-planted-unfaithful']) {
    if (!(await plantedUnfaithfulIsNecessaryNotSufficient(f))) necessaryNotSufficient = false;
  }

  // (13) the ≥k floor per defect/positive class.
  const minPerClassMet = [...PHASEF_DEFECT_CLASSES, ...PHASEF_POSITIVE_CLASSES].every(
    (klass) => inClass(klass).length >= PHASEF_MIN_PER_CLASS,
  );

  const perClass = {};
  for (const klass of [...PHASEF_DEFECT_CLASSES, ...PHASEF_POSITIVE_CLASSES, ...PHASEF_BOUND_CLASSES]) {
    const rs = inClass(klass);
    const allOn = rs.every((r) => r.on.outcome === r.expected_outcome);
    const allOff = rs.every((r) => r.off.outcome === O.ABSTAIN);
    perClass[klass] = Object.freeze({ total: rs.length, allOn, allOff, met: rs.length > 0 && allOn && allOff });
  }

  const checks = Object.freeze({
    plantedUnfaithfulBlocked,
    falseLeanRejects,
    xfamDisagreementConjectural,
    quarantineDisablesLift,
    forgedReplayedBlocked,
    plausibleButWrongRejected,
    positiveArmLifts,
    ablationLoadBearing,
    ablationRevertsAll,
    correlatedStaysSoft,
    outOfEnvelopeWithheld,
    necessaryNotSufficient,
    minPerClassMet,
  });

  const pass = Object.values(checks).every(Boolean);

  const byClassReport = {};
  for (const klass of Object.keys(byClass)) {
    byClassReport[klass] = Object.freeze({ total: byClass[klass].length, results: Object.freeze(byClass[klass]) });
  }

  return Object.freeze({
    pass,
    results: Object.freeze(results),
    byClass: Object.freeze(byClassReport),
    checks,
    perClass: Object.freeze(perClass),
    minPerClass: PHASEF_MIN_PER_CLASS,
  });
}

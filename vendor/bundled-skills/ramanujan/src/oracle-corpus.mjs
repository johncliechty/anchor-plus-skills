// Wave 24 — Gradeable oracle, part A: fixture corpus + red-team set (E1a).
//
// THE HONESTY LAW (NS9) is only as trustworthy as the MEASUREMENT that grades it. This module is the
// CORPUS half of the gradeable oracle (DESCRIPTION §Residuals · R1 + the Metric-G gate): a labeled,
// loadable battery of fixtures the Wave-25 SCORER runs the real spine over to compute
//
//     Metric G = catch-rate (over the planted-defect SCORED SUBSET) − false-positive-rate (over the
//                FIXED 6-fixture SOUND subset).
//
// Wave 24 builds ONLY the corpus + the red-team set (the scorer, the canned baseline, and the ablation
// arm are Wave 25). Every fixture is LABELED with its `class` + `expected_verdict` so the scorer can
// grade each one, and the RED-TEAM set is each individually asserted MUST-reject against the REAL P9
// provenance spine (src/adjudication.mjs) — a forged artifact, a cross-claim replay, a same-claim
// replay, an across-restart replay, and a crash-mid-mint attempt are all rejected at the adjudication
// gate (the done-when / GWT).
//
// THE i–xiv UNION (the autonomous-tier fixtures, per the Wave-24 deliverable):
//   • the 6 PLANTED-DEFECT CLASSES × ≥3 instances each (the SCORED SUBSET — the catch-rate denominator):
//       derivation-error, dimensional, off-by-one, convergence-stability, comprehension-narrative,
//       firewall-inapplicable.
//   • the FIXED 6-fixture SOUND subset (separate from the union; supplies ONLY the false-positive / k′
//       term and is EXCLUDED from the catch-rate denominator — DESCRIPTION §Residuals · R1).
//   • the ref-fn-independence fixture (S4 — caps at CLAIMED, never OBSERVED).
//   • the A4 laundering / recall rosters (reused verbatim from Wave 8 / Wave 9 — composed, not re-built).
//   • the forged-unfaithful-definition fixture (P3 — stamps requires-Phase-F; example-stability is
//       advisory-only and is NOT faithfulness).
//   • the abstain-payload fixture (a proof/conceptual claim that ABSTAINs and emits an advisory payload).
//   • the RED-TEAM set (the five P9 attacks, each asserted MUST-reject by the spine).
//
// THE HONEST LABEL VOCABULARY (`expected_verdict`). The corpus does not invent a grading verdict — each
// label is the REAL spine outcome the scorer will observe:
//   • CATCH            — a planted defect: the oracle must NOT green it (it flags / abstains / abandons).
//   • SETTLE           — a sound literal computation: the autonomous firewall settles it VERIFIED.
//   • ABSTAIN          — a sound proof/conceptual claim: the router honestly abstains + routes out-of-model.
//   • CAP_CLAIMED      — the S4 same-family reference: capped at CLAIMED (belief CONJECTURAL), never OBSERVED.
//   • REQUIRES_PHASE_F — the forged-unfaithful definition: stamped requires-Phase-F, never auto-promoted.
//   • REJECT           — a red-team artifact attack: rejected at the P9 adjudication gate (ABSTAIN, no lift).
//
// This module COMPOSES the existing spine (Wave 3/4 ledger+adjudication, Wave 8/9 grammar+subprocess,
// Wave 11/12 firewall builder + coverage, Wave 17 CONTROL, Wave 20 FORMALIZE, Wave 7 router); it
// re-implements nothing. The planted-defect computational fixtures carry an in-grammar `expr` + an
// asserted (wrong) result, so the scorer can RE-EXECUTE and observe the disagreement. Pure node
// built-ins + the project's own spine modules. Runs under `node --test test/`.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { ClaimLedger, RUNG, BELIEF } from './claim-ledger.mjs';
import {
  DurableNonceStore,
  AdjudicationDispatcher,
  adjudicatedPromoteToVerified,
  canonicalStdoutHash,
  runtimeFingerprint,
  loadDurabilitySubstrate,
  VERDICT,
} from './adjudication.mjs';
import {
  int,
  neg,
  add,
  mul,
  div,
  pow,
  variable,
  sum,
  product,
  recognize,
  LAUNDERING_BATTERY,
} from './firewall-grammar.mjs';
import { evalExpr, POSITIVE_RECALL_ROSTER, FIREWALL_DOMAIN, FIREWALL_FAMILY } from './firewall-subprocess.mjs';
import {
  buildFirewall,
  FIREWALL_STATUS,
  GENUINE_NARRATIVE,
  PLANTED_SAME_FAMILY_NARRATIVE,
} from './firewall-builder.mjs';
import {
  ControlMachine,
  NON_CONVERGING_FIXTURE,
  ABANDON_REASON,
  CONTROL_STATE,
} from './control-machine.mjs';
import { classifyFirewallApplicability, FIREWALL_APPLICABILITY } from './comprehension.mjs';
import { runFormalizeAbstainFixture, FORMALIZE_STATUS } from './formalize-machine.mjs';
import { VerifyRouter, ROUTE_VERDICT } from './verify-router.mjs';

// --- Phase-F (Increment-2) certifier spine — composed verbatim, NOT re-implemented (Wave 6 oracle). ---
import { loadManifest } from './phasef-probe.mjs';
import {
  formalizeEquation,
  certifyLean,
  adjudicateObserved,
  OBSERVED_STATUS,
  OBSERVED_RUNG,
} from './lean-certifier.mjs';
import {
  certifyFaithfulness,
  computeFaithfulness,
  FAITHFULNESS_KIND,
  FAITHFULNESS_VERDICT,
  Z3_RESULT,
  OUT_OF_ENVELOPE_REASON,
} from './smt-faithfulness.mjs';
import {
  runCrossFamilyPanel,
  adjudicateCrossFamily,
  CROSS_FAMILY_STATUS,
  PLAUSIBILITY_CORROBORATED_RUNG,
} from './cross-family-verifier.mjs';

// ---------------------------------------------------------------------------
// The label vocabulary.
// ---------------------------------------------------------------------------

/** The honest per-fixture grading label — every value is a REAL spine outcome (see header). */
export const ORACLE_VERDICT = Object.freeze({
  CATCH: 'CATCH',
  SETTLE: 'SETTLE',
  ABSTAIN: 'ABSTAIN',
  CAP_CLAIMED: 'CAP_CLAIMED',
  REQUIRES_PHASE_F: 'REQUIRES_PHASE_F',
  REJECT: 'REJECT',
});

/** The values of ORACLE_VERDICT, as an array (introspection + exhaustiveness checks). */
export const ORACLE_VERDICT_VALUES = Object.freeze(Object.values(ORACLE_VERDICT));

/**
 * The 6 PLANTED-DEFECT CLASSES (DESCRIPTION §Residuals · R1). The first three are the deterministic
 * computational/firewall defects (per-class catch floor = 100%); the last three are the harder
 * narrative/control/applicability defects (per-class catch floor ≥ 2/3). All six are in the SCORED
 * SUBSET (the catch-rate denominator).
 */
export const DEFECT_CLASSES = Object.freeze([
  'derivation-error',
  'dimensional',
  'off-by-one',
  'convergence-stability',
  'comprehension-narrative',
  'firewall-inapplicable',
]);

/** The non-defect corpus classes (the SOUND subset + the named singletons + the A4 rosters). */
export const AUXILIARY_CLASSES = Object.freeze([
  'sound',
  'ref-fn-independence',
  'forged-unfaithful-definition',
  'abstain-payload',
  'firewall-laundering',
  'firewall-recall',
]);

/** Every class label a fixture may carry. */
export const CORPUS_CLASSES = Object.freeze([...DEFECT_CLASSES, ...AUXILIARY_CLASSES]);

/** The named red-team attacks (each individually asserted MUST-reject by the spine). */
export const RED_TEAM_ATTACKS = Object.freeze([
  'forged-artifact',
  'cross-claim-replay',
  'same-claim-replay',
  'across-restart-replay',
  'crash-mid-mint',
]);

/**
 * The Wave-25 scoring SUBSETS (pinned here so the scorer reads them from one place — DESCRIPTION
 * §Residuals · R1 / Metric-G). `scored` = the planted-defect fixtures (catch-rate denominator); `sound`
 * = the FIXED 6-fixture false-positive / k′ subset (EXCLUDED from the catch denominator); the rest are
 * graded but not part of the G computation in the same way (abstain-correctness floor, etc.).
 */
export const SUBSET = Object.freeze({
  SCORED: 'scored',
  SOUND: 'sound',
  ABSTAIN: 'abstain',
  REF_INDEPENDENCE: 'ref-independence',
  FORMALIZE: 'formalize',
  LAUNDERING: 'laundering',
  RECALL: 'recall',
  RED_TEAM: 'red-team',
});

// ---------------------------------------------------------------------------
// Exact-arithmetic helpers (reuse the ONE Wave-9 evaluator; NO float).
// ---------------------------------------------------------------------------

/** The exact value of an in-grammar `expr`, as decimal strings { num, den } (via the Wave-9 evaluator). */
export function trueResultOf(expr) {
  const r = evalExpr(expr);
  return { num: r.n.toString(), den: r.d.toString() };
}

/** Exact equality of two { num, den } rationals (cross-multiplied with bigint — no float). */
export function resultsEqual(a, b) {
  if (!a || !b) return false;
  try {
    return BigInt(a.num) * BigInt(b.den) === BigInt(b.num) * BigInt(a.den);
  } catch {
    return false;
  }
}

function comp(id, expr, asserted, defect_note) {
  return Object.freeze({ id, expr, asserted_result: Object.freeze(asserted), defect_note });
}

// ---------------------------------------------------------------------------
// (i) PLANTED-DEFECT CLASS — derivation-error (×3, catch floor 100%).
//
// An in-grammar literal computation whose ASSERTED result is a derivation slip (≠ the true value). The
// firewall re-executes the expression and the asserted result does not reproduce — so a same-family
// artifact forged for the asserted value cannot re-execute, and the claim never reaches VERIFIED.
// ---------------------------------------------------------------------------

const DERIVATION_ERROR = Object.freeze([
  comp('de::sum-of-products-wrong', add(mul(int(2), int(3)), int(4)), { num: '11', den: '1' }, 'true 2*3+4 = 10; asserts 11 (carry slip)'),
  comp('de::pow-transposed', pow(int(2), int(10)), { num: '1042', den: '1' }, 'true 2^10 = 1024; asserts 1042 (digit transposition)'),
  comp('de::product-wrong', mul(int(7), int(8)), { num: '54', den: '1' }, 'true 7*8 = 56; asserts 54 (times-table slip)'),
]);

// ---------------------------------------------------------------------------
// (ii) PLANTED-DEFECT CLASS — off-by-one (×3, catch floor 100%).
//
// A bounded sum/product whose ASSERTED value is the NEIGHBOURING boundary value (the sum to n±1). The
// expression as written is in grammar and exact; only the asserted total is off by one boundary term.
// ---------------------------------------------------------------------------

const OFF_BY_ONE = Object.freeze([
  comp('obo::sum-upper-plus-one', sum('k', int(1), int(3), variable('k')), { num: '10', den: '1' }, 'true sum_{1..3} k = 6; asserts 10 (= sum_{1..4})'),
  comp('obo::sum-extra-term', sum('k', int(1), int(5), variable('k')), { num: '21', den: '1' }, 'true sum_{1..5} k = 15; asserts 21 (= sum_{1..6})'),
  comp('obo::factorial-shift', product('k', int(1), int(4), variable('k')), { num: '120', den: '1' }, 'true 4! = 24; asserts 120 (= 5!)'),
]);

// ---------------------------------------------------------------------------
// (iii) PLANTED-DEFECT CLASS — dimensional (×3, catch floor 100%).
//
// A firewall narrative whose CLAIMED dimension contradicts the (dimensionless) literal ref-fn: the
// reading-independent dimensional anchor is VIOLATED, so the firewall builder REFUSES (rung_cap
// UNVERIFIED) — the claim cannot settle. (These are firewall fixtures, scored alongside the others.)
// ---------------------------------------------------------------------------

function dimensionalNarrative(claim_id, dimension) {
  return Object.freeze({
    ...GENUINE_NARRATIVE,
    claim_id,
    claimed: Object.freeze({ ...GENUINE_NARRATIVE.claimed, dimension }),
    anchors: Object.freeze({
      ...GENUINE_NARRATIVE.anchors,
      dimensional: Object.freeze({ available: true, expected: dimension }),
    }),
  });
}

const DIMENSIONAL = Object.freeze([
  Object.freeze({ id: 'dim::declared-length', dimension: 'length', narrative: dimensionalNarrative('oc::dim-length', 'length') }),
  Object.freeze({ id: 'dim::declared-time', dimension: 'time', narrative: dimensionalNarrative('oc::dim-time', 'time') }),
  Object.freeze({ id: 'dim::declared-energy', dimension: 'energy', narrative: dimensionalNarrative('oc::dim-energy', 'energy') }),
]);

// ---------------------------------------------------------------------------
// (iv) PLANTED-DEFECT CLASS — convergence-stability (×3, catch floor ≥ 2/3).
//
// A solution attempt whose progress-boolean stream NEVER stabilizes: CONTROL (the S1 gap-function)
// ABANDONs it, leaving the claim UNVERIFIED. A claim whose only support is such a non-converging attempt
// must NOT be settled — the oracle catches it as an ABANDON.
// ---------------------------------------------------------------------------

const CONVERGENCE_STABILITY = Object.freeze([
  Object.freeze({ id: 'cs::flat-no-progress', stream: NON_CONVERGING_FIXTURE, note: 'never makes progress — gap-function ABANDON at step 6' }),
  Object.freeze({ id: 'cs::six-flat', stream: Object.freeze([false, false, false, false, false, false]), note: 'two consecutive gap-switches => ABANDON' }),
  Object.freeze({ id: 'cs::single-spark-then-stall', stream: Object.freeze([true, false, false, false, false, false, false]), note: 'one progress step then a stall — still gap-function ABANDON' }),
]);

// ---------------------------------------------------------------------------
// (v) PLANTED-DEFECT CLASS — comprehension-narrative (×3, catch floor ≥ 2/3).
//
// A reading sub-claim whose NARRATIVE dresses a proof/conceptual obligation (or a non-literal "limit")
// up as a settled computation. The Step-0 firewall-applicability classifier resolves it to
// INAPPLICABLE / INDETERMINATE — never APPLICABLE — so it can never reach the autonomous-VERIFIED path
// (the honesty law catches the narrative's over-claim).
// ---------------------------------------------------------------------------

const COMPREHENSION_NARRATIVE = Object.freeze([
  Object.freeze({
    id: 'cn::limit-dressed-as-computation',
    subclaim: Object.freeze({
      type: 'computational',
      statement: 'the tail limit lim_{n->inf} a_n = 0, asserted as a finite computation',
      expr: Object.freeze({ type: 'limit', var: 'n', to: 'infinity', body: { type: 'var', name: 'n' } }),
    }),
    note: 'a non-literal limit narrated as computed — classifier => INDETERMINATE (firewall-inapplicable)',
  }),
  Object.freeze({
    id: 'cn::proof-narrated-as-verified',
    subclaim: Object.freeze({
      type: 'proof-bearing',
      statement: 'the series converges for all admissible parameters (narrated as "verified by the worked example")',
    }),
    note: 'a proof obligation narrated as settled — classifier => INAPPLICABLE',
  }),
  Object.freeze({
    id: 'cn::analogy-narrated-as-settled',
    subclaim: Object.freeze({
      type: 'conceptual',
      statement: 'this method IS the classical partial-fraction technique (narrated as an established identity)',
    }),
    note: 'a conceptual analogy narrated as settled — classifier => INAPPLICABLE',
  }),
]);

// ---------------------------------------------------------------------------
// (vi) PLANTED-DEFECT CLASS — firewall-inapplicable (×3, catch floor ≥ 2/3).
//
// A claim that ASSERTS computability but whose expression is NOT in the closed default-deny grammar (a
// non-literal "looks-computational" smuggle). The grammar front-end rejects it (ABSTAIN + route); no
// artifact is ever minted, so it cannot be laundered into the autonomous-VERIFIED path.
// ---------------------------------------------------------------------------

const FIREWALL_INAPPLICABLE = Object.freeze([
  Object.freeze({ id: 'fi::limit-smuggle', expr: Object.freeze({ type: 'limit', var: 'n', to: 'infinity', body: { type: 'var', name: 'n' } }), note: 'a limit (analysis, not finite arithmetic)' }),
  Object.freeze({ id: 'fi::symbolic-bound-sum', expr: sum('k', int(1), variable('n'), variable('k')), note: 'a sum with a symbolic upper bound (not a literal range)' }),
  Object.freeze({ id: 'fi::free-symbol', expr: add(int(1), variable('x')), note: 'a free symbolic variable dressed as arithmetic' }),
]);

// ---------------------------------------------------------------------------
// THE FIXED 6-FIXTURE SOUND SUBSET — supplies ONLY the false-positive / k′ term.
//
// Genuine in-class literal computations with the CORRECT asserted result. The oracle MUST settle these
// (VERIFIED) and must NOT flag any as defective (k′ = at most 1 false positive — DESCRIPTION §R1). This
// subset is SEPARATE from the i–xiv union and EXCLUDED from the catch-rate denominator.
// ---------------------------------------------------------------------------

const FIXED_SOUND_SUBSET = Object.freeze([
  comp('sound::integer-literal', int(6), { num: '6', den: '1' }, 'the literal 6'),
  comp('sound::nested-arithmetic', add(mul(int(2), int(3)), neg(int(4))), { num: '2', den: '1' }, '2*3 + (-4) = 2'),
  comp('sound::pow', pow(int(2), int(10)), { num: '1024', den: '1' }, '2^10 = 1024'),
  comp('sound::bounded-sum-of-products', sum('k', int(1), int(3), mul(variable('k'), int(2))), { num: '12', den: '1' }, 'sum_{1..3} (k*2) = 12'),
  comp('sound::factorial', product('k', int(1), int(4), variable('k')), { num: '24', den: '1' }, '4! = 24'),
  comp('sound::exact-rational', div(int(22), int(7)), { num: '22', den: '7' }, '22/7 (exact rational, no float)'),
]);

// The FIXED count the false-positive / k′ term is computed over (DESCRIPTION §R1 — a single load-bearing
// cardinality shared by k′ and the G false-positive-rate).
export const SOUND_SUBSET_CARDINALITY = 6;

// ---------------------------------------------------------------------------
// THE NAMED SINGLETONS — ref-fn-independence (S4) · forged-unfaithful-definition (P3) · abstain-payload.
// ---------------------------------------------------------------------------

/** S4 (ref-fn-independence): the planted same-family reference caps at CLAIMED (never OBSERVED). */
const REF_FN_INDEPENDENCE_FIXTURE = Object.freeze({
  id: 'ref-fn-independence::same-family',
  narrative: PLANTED_SAME_FAMILY_NARRATIVE,
  note: 'the ref-fn shares symbol-provenance with the comprehension narrative — capped at CLAIMED (S4)',
});

/** A proof/conceptual claim that ABSTAINs and carries a well-formed advisory (commission) payload. */
const ABSTAIN_PAYLOAD_FIXTURE = Object.freeze({
  id: 'abstain-payload::proof-conjecture',
  claim: Object.freeze({
    id: 'oc::abstain-payload',
    type: 'proof-bearing',
    statement: 'every even integer > 2 is the sum of two primes (a proof obligation with no autonomous verifier)',
  }),
  note: 'routes out-of-model: ABSTAIN + an advisory commission envelope (needs_verification:true)',
});

// ---------------------------------------------------------------------------
// THE A4 LAUNDERING / RECALL ROSTERS — composed verbatim from Wave 8 / Wave 9 (NOT re-built).
// ---------------------------------------------------------------------------

/** The Wave-8 laundering battery, wrapped as corpus fixtures (each MUST be rejected by the grammar). */
const LAUNDERING_FIXTURES = Object.freeze(
  LAUNDERING_BATTERY.map((c) =>
    Object.freeze({ id: `laundering::${c.name}`, smuggle: c.smuggle, expr: c.expr, expected_at: c.at ?? null }),
  ),
);

/** The Wave-9 positive-recall roster, wrapped as corpus fixtures (each MUST settle). */
const RECALL_FIXTURES = Object.freeze(
  POSITIVE_RECALL_ROSTER.map((c) =>
    Object.freeze({ id: `recall::${c.name}`, expr: c.expr, expected: c.expected, nested: Boolean(c.nested) }),
  ),
);

// ---------------------------------------------------------------------------
// THE CORPUS — assembled, labeled, loadable.
// ---------------------------------------------------------------------------

function labelComputational(fixtures, klass, expected_verdict, subset) {
  return fixtures.map((f) => Object.freeze({ ...f, class: klass, expected_verdict, subset }));
}

/**
 * LOAD the gradeable-oracle corpus. Returns a frozen, fully-labeled structure (the done-when's "the
 * corpus loads"). Every leaf fixture carries `class` + `expected_verdict` (+ `subset` for the Wave-25
 * scorer). Pure + deterministic — no I/O, no subprocess; safe to call at module load.
 */
export function loadCorpus() {
  const defects = Object.freeze({
    'derivation-error': labelComputational(DERIVATION_ERROR, 'derivation-error', ORACLE_VERDICT.CATCH, SUBSET.SCORED),
    dimensional: DIMENSIONAL.map((f) =>
      Object.freeze({ ...f, class: 'dimensional', expected_verdict: ORACLE_VERDICT.CATCH, subset: SUBSET.SCORED, expect_status: FIREWALL_STATUS.REFUSED }),
    ),
    'off-by-one': labelComputational(OFF_BY_ONE, 'off-by-one', ORACLE_VERDICT.CATCH, SUBSET.SCORED),
    'convergence-stability': CONVERGENCE_STABILITY.map((f) =>
      Object.freeze({ ...f, class: 'convergence-stability', expected_verdict: ORACLE_VERDICT.CATCH, subset: SUBSET.SCORED }),
    ),
    'comprehension-narrative': COMPREHENSION_NARRATIVE.map((f) =>
      Object.freeze({ ...f, class: 'comprehension-narrative', expected_verdict: ORACLE_VERDICT.CATCH, subset: SUBSET.SCORED }),
    ),
    'firewall-inapplicable': FIREWALL_INAPPLICABLE.map((f) =>
      Object.freeze({ ...f, class: 'firewall-inapplicable', expected_verdict: ORACLE_VERDICT.CATCH, subset: SUBSET.SCORED }),
    ),
  });

  const sound = labelComputational(FIXED_SOUND_SUBSET, 'sound', ORACLE_VERDICT.SETTLE, SUBSET.SOUND);

  const refFnIndependence = Object.freeze({
    ...REF_FN_INDEPENDENCE_FIXTURE,
    class: 'ref-fn-independence',
    expected_verdict: ORACLE_VERDICT.CAP_CLAIMED,
    subset: SUBSET.REF_INDEPENDENCE,
  });

  const forgedUnfaithfulDefinition = Object.freeze({
    id: 'forged-unfaithful-definition::regular-polygon',
    note: 'unfaithful but example-stable definition — stamps requires-Phase-F (P3 example-stability is advisory-only)',
    class: 'forged-unfaithful-definition',
    expected_verdict: ORACLE_VERDICT.REQUIRES_PHASE_F,
    subset: SUBSET.FORMALIZE,
  });

  const abstainPayload = Object.freeze({
    ...ABSTAIN_PAYLOAD_FIXTURE,
    class: 'abstain-payload',
    expected_verdict: ORACLE_VERDICT.ABSTAIN,
    subset: SUBSET.ABSTAIN,
  });

  const laundering = LAUNDERING_FIXTURES.map((f) =>
    Object.freeze({ ...f, class: 'firewall-laundering', expected_verdict: ORACLE_VERDICT.CATCH, subset: SUBSET.LAUNDERING }),
  );
  const recall = RECALL_FIXTURES.map((f) =>
    Object.freeze({ ...f, class: 'firewall-recall', expected_verdict: ORACLE_VERDICT.SETTLE, subset: SUBSET.RECALL }),
  );

  const redTeam = RED_TEAM_ATTACKS.map((name) =>
    Object.freeze({ id: `red-team::${name}`, attack: name, class: 'red-team', expected_verdict: ORACLE_VERDICT.REJECT, subset: SUBSET.RED_TEAM }),
  );

  return Object.freeze({
    defects: Object.freeze({
      'derivation-error': Object.freeze(defects['derivation-error']),
      dimensional: Object.freeze(defects.dimensional),
      'off-by-one': Object.freeze(defects['off-by-one']),
      'convergence-stability': Object.freeze(defects['convergence-stability']),
      'comprehension-narrative': Object.freeze(defects['comprehension-narrative']),
      'firewall-inapplicable': Object.freeze(defects['firewall-inapplicable']),
    }),
    sound: Object.freeze(sound),
    refFnIndependence,
    forgedUnfaithfulDefinition,
    abstainPayload,
    rosters: Object.freeze({ laundering: Object.freeze(laundering), recall: Object.freeze(recall) }),
    redTeam: Object.freeze(redTeam),
  });
}

/**
 * Flatten the corpus to a single labeled list (every leaf fixture, in a stable order). Each entry has
 * at least { id, class, expected_verdict, subset }. The Wave-25 scorer iterates this list.
 */
export function flattenCorpus(corpus = loadCorpus()) {
  const flat = [];
  for (const klass of DEFECT_CLASSES) flat.push(...corpus.defects[klass]);
  flat.push(...corpus.sound);
  flat.push(corpus.refFnIndependence, corpus.forgedUnfaithfulDefinition, corpus.abstainPayload);
  flat.push(...corpus.rosters.laundering, ...corpus.rosters.recall);
  flat.push(...corpus.redTeam);
  return Object.freeze(flat);
}

// ===========================================================================
// THE RED-TEAM SET — five P9 attacks, each rejected by the REAL adjudication spine.
//
// Every attack runs against the genuine src/adjudication.mjs gate (DurableNonceStore +
// AdjudicationDispatcher + adjudicatedPromoteToVerified) on the inherited durability substrate. A
// "rejected" attack returns the gate verdict ABSTAIN and leaves the target claim un-promoted (never
// OBSERVED). Each is non-vacuous where it can be: the replay attacks first prove the artifact was
// genuinely usable ONCE (verdict VERIFIED) before the replay is refused.
// ===========================================================================

let redTeamFileSeq = 0;

function redTeamCtx(substrate, scratchDir) {
  return { substrate, scratchDir };
}

function freshDispatcher(ctx, tag, file = null) {
  const f = file || path.join(ctx.scratchDir, `redteam-${tag}-${redTeamFileSeq++}.checkpoint.json`);
  const store = DurableNonceStore.load(ctx.substrate, f);
  return { dispatcher: new AdjudicationDispatcher({ store, family: FIREWALL_FAMILY }), file: f };
}

/** A genuine 64-hex stdout_hash (the gate never re-executes — Wave 4 — so any real digest is fine). */
const STDOUT_HASH = canonicalStdoutHash({ ok: true, computation: 'red-team' });

function rejectedResult(name, verdict, rung, detail) {
  const rejected = verdict.verdict === VERDICT.ABSTAIN && rung !== RUNG.OBSERVED;
  return Object.freeze({ name, rejected, verdict: verdict.verdict, reason: verdict.reason || null, detail });
}

/** (1) FORGED ARTIFACT — a wholesale-fabricated nonce that the dispatcher never minted. */
export function forgedArtifactAttack(ctx) {
  const { dispatcher } = freshDispatcher(ctx, 'forged');
  const ledger = new ClaimLedger();
  ledger.assert({ id: 'RT-forged', type: 'computational' });
  const forged = Object.freeze({
    claim_id: 'RT-forged',
    domain: FIREWALL_DOMAIN,
    nonce: 'f'.repeat(64), // structurally a 64-hex, but NEVER durably issued
    stdout_hash: STDOUT_HASH,
    exit_code: 0,
    runtime_fingerprint: runtimeFingerprint(),
  });
  const verdict = adjudicatedPromoteToVerified(ledger, 'RT-forged', { artifact: forged, dispatcher });
  return rejectedResult('forged-artifact', verdict, ledger.rungOf('RT-forged'), 'fabricated nonce — never minted by the out-of-model dispatcher');
}

/** (2) CROSS-CLAIM REPLAY — a genuine artifact for OTHER, relabeled to TARGET. */
export function crossClaimReplayAttack(ctx) {
  const { dispatcher } = freshDispatcher(ctx, 'cross');
  const minted = dispatcher.mintArtifact('RT-other', FIREWALL_DOMAIN, { stdout_hash: STDOUT_HASH, exit_code: 0 });
  const relabeled = Object.freeze({ ...minted, claim_id: 'RT-target' }); // forge the binding onto a different claim
  const ledger = new ClaimLedger();
  ledger.assert({ id: 'RT-target', type: 'computational' });
  const verdict = adjudicatedPromoteToVerified(ledger, 'RT-target', { artifact: relabeled, dispatcher });
  return rejectedResult('cross-claim-replay', verdict, ledger.rungOf('RT-target'), "nonce bound to RT-other re-presented for RT-target");
}

/** (3) SAME-CLAIM REPLAY — a genuine artifact consumed ONCE, then re-presented for the same claim. */
export function sameClaimReplayAttack(ctx) {
  const { dispatcher } = freshDispatcher(ctx, 'same');
  const artifact = dispatcher.mintArtifact('RT-same', FIREWALL_DOMAIN, { stdout_hash: STDOUT_HASH, exit_code: 0 });

  const ledgerFirst = new ClaimLedger();
  ledgerFirst.assert({ id: 'RT-same', type: 'computational' });
  const first = adjudicatedPromoteToVerified(ledgerFirst, 'RT-same', { artifact, dispatcher }); // legitimately VERIFIED

  const ledgerReplay = new ClaimLedger();
  ledgerReplay.assert({ id: 'RT-same', type: 'computational' });
  const replay = adjudicatedPromoteToVerified(ledgerReplay, 'RT-same', { artifact, dispatcher });
  const r = rejectedResult('same-claim-replay', replay, ledgerReplay.rungOf('RT-same'), 'the single-use nonce was already spent');
  return Object.freeze({ ...r, first_verdict: first.verdict, non_vacuous: first.verdict === VERDICT.VERIFIED });
}

/** (4) ACROSS-RESTART REPLAY — consume, RELOAD the store from disk, then replay the spent nonce. */
export function acrossRestartReplayAttack(ctx) {
  const file = path.join(ctx.scratchDir, `redteam-restart-${redTeamFileSeq++}.checkpoint.json`);
  const d1 = freshDispatcher(ctx, 'restart', file);
  const artifact = d1.dispatcher.mintArtifact('RT-restart', FIREWALL_DOMAIN, { stdout_hash: STDOUT_HASH, exit_code: 0 });

  const ledger1 = new ClaimLedger();
  ledger1.assert({ id: 'RT-restart', type: 'computational' });
  const first = adjudicatedPromoteToVerified(ledger1, 'RT-restart', { artifact, dispatcher: d1.dispatcher }); // VERIFIED + durably spent

  // RESTART: a fresh store over the SAME file reloads the spent set from disk (no in-memory carry-over).
  const d2 = freshDispatcher(ctx, 'restart', file);
  const ledger2 = new ClaimLedger();
  ledger2.assert({ id: 'RT-restart', type: 'computational' });
  const replay = adjudicatedPromoteToVerified(ledger2, 'RT-restart', { artifact, dispatcher: d2.dispatcher });
  const r = rejectedResult('across-restart-replay', replay, ledger2.rungOf('RT-restart'), 'the spent-nonce record reloaded from disk after the restart');
  return Object.freeze({ ...r, first_verdict: first.verdict, non_vacuous: first.verdict === VERDICT.VERIFIED });
}

/** (5) CRASH-MID-MINT — a process death AFTER the nonce is computed but BEFORE the durable flush. */
export function crashMidMintAttack(ctx) {
  const file = path.join(ctx.scratchDir, `redteam-crash-${redTeamFileSeq++}.checkpoint.json`);
  const d1 = freshDispatcher(ctx, 'crash', file);

  let capturedNonce = null;
  let crashed = false;
  try {
    d1.dispatcher.mintArtifact(
      'RT-crash',
      FIREWALL_DOMAIN,
      { stdout_hash: STDOUT_HASH, exit_code: 0 },
      { beforeFlush: ({ nonce }) => { capturedNonce = nonce; throw new Error('simulated crash before the durable flush'); } },
    );
  } catch {
    crashed = true; // the mint threw at the durability boundary — nothing was persisted
  }

  // RESTART: reload from disk. The crashed mint persisted no counter bump and no issued-nonce record.
  const d2 = freshDispatcher(ctx, 'crash', file);
  const ledger = new ClaimLedger();
  ledger.assert({ id: 'RT-crash', type: 'computational' });
  const replayArtifact = Object.freeze({
    claim_id: 'RT-crash',
    domain: FIREWALL_DOMAIN,
    nonce: capturedNonce || 'e'.repeat(64),
    stdout_hash: STDOUT_HASH,
    exit_code: 0,
    runtime_fingerprint: runtimeFingerprint(),
  });
  const verdict = adjudicatedPromoteToVerified(ledger, 'RT-crash', { artifact: replayArtifact, dispatcher: d2.dispatcher });
  const r = rejectedResult('crash-mid-mint', verdict, ledger.rungOf('RT-crash'), 'the nonce was computed but never durably issued (write-ordering: flush-before-publish)');
  return Object.freeze({ ...r, crashed, captured_nonce: Boolean(capturedNonce), non_vacuous: crashed && Boolean(capturedNonce) });
}

/** name -> attack runner (each takes the red-team ctx { substrate, scratchDir }). */
export const RED_TEAM_RUNNERS = Object.freeze({
  'forged-artifact': forgedArtifactAttack,
  'cross-claim-replay': crossClaimReplayAttack,
  'same-claim-replay': sameClaimReplayAttack,
  'across-restart-replay': acrossRestartReplayAttack,
  'crash-mid-mint': crashMidMintAttack,
});

/**
 * Run the WHOLE red-team set against the real spine. Resolves the inherited durability substrate +
 * an owned scratch dir if not supplied (and removes a self-created scratch dir afterwards). Returns
 *   { attacks: { <name>: result }, allRejected:boolean }
 * where each result has { name, rejected, verdict, ... }. `allRejected` is the done-when invariant.
 *
 * @param {{substrate?:object, scratchDir?:string}} [o]
 */
export async function runRedTeam({ substrate, scratchDir } = {}) {
  const sub = substrate || (await loadDurabilitySubstrate());
  const dir = scratchDir || fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-redteam-'));
  const created = !scratchDir;
  const ctx = redTeamCtx(sub, dir);
  try {
    const attacks = {};
    for (const name of RED_TEAM_ATTACKS) attacks[name] = RED_TEAM_RUNNERS[name](ctx);
    return Object.freeze({ attacks: Object.freeze(attacks), allRejected: RED_TEAM_ATTACKS.every((n) => attacks[n].rejected) });
  } finally {
    if (created) {
      try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* best-effort */ }
    }
  }
}

// ---------------------------------------------------------------------------
// Lightweight, dependency-free probes the Wave-25 scorer + the E1a assertions reuse to CONFIRM a
// fixture is genuinely what its label claims (non-vacuity), WITHOUT spawning the firewall subprocess.
// ---------------------------------------------------------------------------

/** A planted computational defect is real iff its asserted result ≠ the true (re-executed) value. */
export function computationalDefectIsReal(fixture) {
  return !resultsEqual(fixture.asserted_result, trueResultOf(fixture.expr));
}

/** A sound computational fixture is real iff its asserted result == the true (re-executed) value. */
export function soundFixtureIsConsistent(fixture) {
  return resultsEqual(fixture.asserted_result, trueResultOf(fixture.expr));
}

/** A dimensional defect is caught iff the firewall builder REFUSES it (rung_cap UNVERIFIED). */
export function dimensionalDefectIsCaught(fixture) {
  const build = buildFirewall(fixture.narrative);
  return build.firewall_status === FIREWALL_STATUS.REFUSED && build.rung_cap === RUNG.UNVERIFIED;
}

/** A convergence-stability defect is caught iff CONTROL ABANDONs the stream, leaving the claim UNVERIFIED. */
export function convergenceDefectIsCaught(fixture) {
  const ledger = new ClaimLedger();
  const out = new ControlMachine({ ledger }).run({ id: fixture.id, type: 'proof-bearing' }, fixture.stream);
  return out.state === CONTROL_STATE.ABANDONED && out.claimLeftUnverified === true;
}

/** A comprehension-narrative defect is caught iff Step-0 resolves it to NOT firewall-APPLICABLE. */
export function comprehensionDefectIsCaught(fixture) {
  const cls = classifyFirewallApplicability(fixture.subclaim);
  return cls.applicability !== FIREWALL_APPLICABILITY.APPLICABLE;
}

/** A firewall-inapplicable defect is caught iff the closed grammar rejects the expression. */
export function firewallInapplicableIsCaught(fixture) {
  return recognize(fixture.expr).inGrammar === false;
}

/** The forged-unfaithful definition is caught iff FORMALIZE stamps requires-Phase-F + never greens. */
export function forgedUnfaithfulIsCaught() {
  const { stub, ground_truth_faithful } = runFormalizeAbstainFixture();
  return (
    ground_truth_faithful === false &&
    stub.formalize_status === FORMALIZE_STATUS.REQUIRES_PHASE_F &&
    stub.green === false &&
    stub.gates_promotion === false
  );
}

/** The abstain-payload fixture ABSTAINs through the router with a well-formed advisory payload. */
export function abstainPayloadIsHonest(fixture) {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger }); // no dispatcher => proof-bearing claim ABSTAINs + routes
  const result = router.route({ id: fixture.claim.id, type: fixture.claim.type, statement: fixture.claim.statement });
  return (
    result.verdict === ROUTE_VERDICT.ABSTAIN &&
    result.routed === true &&
    result.belief !== BELIEF.VERIFIED &&
    result.advisory !== null &&
    result.advisory.needs_verification === true &&
    result.advisory.commission != null
  );
}

// ===========================================================================
// PHASE-F ORACLE (Increment-2 / Wave 6) — the certifiers are load-bearing, CATEGORICALLY.
//
// Increment-1's oracle (above) grades the AUTONOMOUS honesty law (no green proof; abstain+route). This
// section grades the INCREMENT-2 certifier arm: the cross-family soft check, the Lean+z3 OBSERVED lift,
// and (by composition) the human GROUNDED apex — RESTRICTED to the z3-DECIDABLE envelope (the HEADLINE
// ENVELOPE, DESCRIPTION-INC2 §v2.1). It re-implements NO spine logic — every probe drives the REAL
// adjudicators (lean-certifier / smt-faithfulness / cross-family-verifier) and the REAL VERIFY router.
//
// THE CATEGORICAL DONE-WHEN (Wave 6): with the certifiers ON vs the ABLATION (certifiers OFF ⇒ the
// claim reverts to Increment-1's honest ABSTAIN arm):
//   • EVERY planted-unfaithful formalization is OBSERVED-BLOCKED (FLAG) ON / ABSTAINED OFF;
//   • EVERY false-Lean theorem REJECTS ON / ABSTAINS OFF;
//   • EVERY cross-family-disagreement stays CONJECTURAL (no lift) ON and OFF;
//   • EVERY quarantine case has its lift DISABLED (no ≥2-family trusted quorum) ON and OFF;
//   • forged / replayed / cross-claim artifacts are FLAGged ON;
//   • a planted plausible-but-wrong proof is REJECTED by the cross-family verifier (no corroboration);
//   • the GENUINE positive arm LIFTS ON (OBSERVED / soft-corroborated) but only ABSTAINS OFF — so the
//     certifier is what is doing the lifting (the ablation is LOAD-BEARING).
// Plus the HONEST BOUNDS: a cross-family CORRELATED agreement stays SOFT (< OBSERVED, never settled),
// and an out-of-z3-decidable-envelope (quantified) formalization fails-CLOSED (OBSERVED WITHHELD).
//
// The fast tier drives the spine with INJECTED async lean/z3/panel stubs (NO tool, cannot hang — the
// same isolation contract the Wave-2…5 fast tiers use); the REAL tools run in the env-gated serial lane
// the Wave-2…5 tool-lane tests already own. Pure node built-ins + the project's own Phase-F modules.
// ===========================================================================

/** The Phase-F grading outcome alphabet — the normalized ADJUDICATOR status the gate keys on. */
export const PHASEF_OUTCOME = Object.freeze({
  OBSERVED: 'OBSERVED', // Lean exit-0 + bounded faithfulness PASS — the settled-class OBSERVED lift.
  CORROBORATED: 'CORROBORATED', // a trusted, re-run-agreeing cross-family quorum — the soft lift (< OBSERVED).
  REJECTED: 'REJECTED', // the Lean kernel rejected the theorem (exit non-zero) — an honest reject.
  BLOCKED: 'BLOCKED', // a DETECTED defect (FLAG): unfaithful / forged / replayed / cross-claim — the lift hard-faults.
  ABSTAIN: 'ABSTAIN', // no lift (disagreement / quarantine / proof-judging reject / deferred) — stays CONJECTURAL.
  WITHHELD: 'WITHHELD', // fail-closed: out of the z3-decidable envelope (the mathlib follow-on boundary).
});

/** The Phase-F DEFECT/attack classes (each ≥3 fixtures — the catch denominator of the categorical gate). */
export const PHASEF_DEFECT_CLASSES = Object.freeze([
  'phasef-planted-unfaithful', // a Lean-valid proof of a DIFFERENT statement ⇒ OBSERVED hard-faults (BLOCKED).
  'phasef-false-lean', // a false theorem (lean exit non-zero) ⇒ REJECTED.
  'phasef-xfam-disagreement', // a disagreeing cross-family panel ⇒ no lift (stays CONJECTURAL / ABSTAIN).
  'phasef-quarantine', // a certifier that failed F0 proof-judging ⇒ no ≥2 trusted quorum ⇒ lift DISABLED.
  'phasef-forged-replayed', // forged / cross-claim lean + cross-family artifacts ⇒ caught by the re-run (BLOCKED).
  'phasef-plausible-but-wrong', // a plausible-but-wrong proof the cross-family verifier REJECTS (no corroboration).
]);

/** The Phase-F POSITIVE (genuine) classes — the now-enabled lift arms (each ≥3). They prove the ablation. */
export const PHASEF_POSITIVE_CLASSES = Object.freeze([
  'phasef-observed-sound', // a true, faithful, decidable-arithmetic theorem ⇒ OBSERVED ON / ABSTAIN OFF.
  'phasef-xfam-sound', // a genuine, re-run-agreeing cross-family quorum ⇒ soft-CORROBORATED ON / ABSTAIN OFF.
]);

/** The Phase-F HONEST-BOUND singletons — the truth-in-labeling edges (graded, but not catch/positive). */
export const PHASEF_BOUND_CLASSES = Object.freeze([
  'phasef-correlated-failure', // a CORRELATED cross-family agreement stays SOFT (< OBSERVED) — never settled.
  'phasef-out-of-envelope', // a quantified (out-of-z3-decidable) formalization fails-CLOSED (OBSERVED WITHHELD).
]);

/** Every Phase-F class label a fixture may carry. */
export const PHASEF_CLASSES = Object.freeze([
  ...PHASEF_DEFECT_CLASSES,
  ...PHASEF_POSITIVE_CLASSES,
  ...PHASEF_BOUND_CLASSES,
]);

// ---------------------------------------------------------------------------
// Injected fast-tier stubs (pure async — NO lean, NO z3, NO server; cannot hang). These mirror the
// Wave-2…5 fast-tier seams verbatim so the oracle drives the SAME adjudicators the per-wave tests prove.
// ---------------------------------------------------------------------------

const PF_LEAN_VERSION = '4.31.0-oracle-stub';
const PF_Z3_VERSION = '4.16.0-oracle-stub';

let _pfBattery = null;
/** The pinned faithfulness battery shape (count + bounded domain) — read lazily from the manifest. */
function pfBatterySpec() {
  if (!_pfBattery) {
    const b = loadManifest().faithfulness_instance_battery;
    _pfBattery = Object.freeze({ count: b.default_count, domain: Object.freeze({ ...b.bounded_domain }) });
  }
  return _pfBattery;
}

const pfLeanCertifyStub = (exitCode) => async () => ({ exitCode, oleanHash: exitCode === 0 ? '0'.repeat(64) : null });
const pfLeanRerunStub = (exitCode) => async () => exitCode;

function pfKindOf(smt2) {
  const m = /ramanujan-faithfulness-kind:\s*(\S+)/.exec(smt2);
  return m ? m[1] : null;
}
/** A kind-keyed async z3 `solve` stub (the documented fast-tier seam — the SMT2 carries its kind marker). */
function pfMakeSolve(byKind) {
  return async (smt2) => {
    const k = pfKindOf(smt2);
    if (!(k in byKind)) throw new Error(`pf stub solve has no canned result for kind ${JSON.stringify(k)}`);
    return byKind[k];
  };
}
const _D = FAITHFULNESS_KIND.DIFFERENTIAL;
const _I = FAITHFULNESS_KIND.INSTANCE;
const _VT = FAITHFULNESS_KIND.VACUITY_TRUE;
const _VF = FAITHFULNESS_KIND.VACUITY_FALSE;
/** FAITHFUL: no disagreeing model, every battery instance agrees, contingent (non-vacuous). */
const PF_FAITHFUL_SOLVE = pfMakeSolve({ [_D]: 'unsat', [_I]: 'unsat', [_VT]: 'sat', [_VF]: 'sat' });
/**
 * UNFAITHFUL — the §v2.1 NECESSARY-NOT-SUFFICIENT case: every enumerated battery instance AGREES
 * ([_I]: unsat) yet the bounded DIFFERENTIAL finds a disagreeing model ([_D]: sat) the finite battery
 * missed. The formalization commits to a DIFFERENT statement; the OBSERVED lift hard-faults.
 */
const PF_UNFAITHFUL_SOLVE = pfMakeSolve({ [_D]: 'sat', [_I]: 'unsat', [_VT]: 'sat', [_VF]: 'sat' });

const pfFixedGen = (answer) => async () => answer;
function pfPanelOf(qwenAnswer, llamaAnswer) {
  return [
    { model: 'qwen2.5:7b-instruct-q4_K_M', family: 'qwen', generate: pfFixedGen(qwenAnswer) },
    { model: 'llama3:latest', family: 'llama', generate: pfFixedGen(llamaAnswer) },
  ];
}
const pfRerunOf = (qwenAnswer, llamaAnswer) => ({ qwen: pfFixedGen(qwenAnswer), llama: pfFixedGen(llamaAnswer) });
const PF_BOTH_TRUSTED = Object.freeze({ qwen: true, llama: true });

// ---------------------------------------------------------------------------
// Proof-certifier (Lean + z3) inputs — built from the REAL formalizeEquation translator (NOT pre-written
// Lean). A "launder" claim (statement vs meta.equation MISMATCH) yields an UNFAITHFUL formalization.
// ---------------------------------------------------------------------------

/** Build the F2+F3 OBSERVED adjudication inputs for `claim` via the injected stubs. */
async function pfProofInputs(claim, { exitCode = 0, producerSolve = PF_FAITHFUL_SOLVE, z3Rerun = PF_FAITHFUL_SOLVE, leanRerunExit = exitCode } = {}) {
  const { count, domain } = pfBatterySpec();
  const { leanSource, faithfulness } = formalizeEquation(claim, { domain, batteryCount: count });
  const leanRecord = await certifyLean({ claim, leanSource, leanVersion: PF_LEAN_VERSION }, { certify: pfLeanCertifyStub(exitCode) });
  const smtRecord = await certifyFaithfulness(
    { claim, query: faithfulness.query, battery: faithfulness.battery, z3Version: PF_Z3_VERSION, pinnedDefaultCount: count },
    { solve: producerSolve },
  );
  return { leanRecord, smtRecord, leanRerun: pfLeanRerunStub(leanRerunExit), z3Rerun, pinnedDefaultCount: count };
}

/** Normalize an OBSERVED adjudication status to a PHASEF_OUTCOME. */
function pfObservedOutcome(status) {
  switch (status) {
    case OBSERVED_STATUS.OBSERVED: return PHASEF_OUTCOME.OBSERVED;
    case OBSERVED_STATUS.REJECTED: return PHASEF_OUTCOME.REJECTED;
    case OBSERVED_STATUS.FLAG: return PHASEF_OUTCOME.BLOCKED;
    case OBSERVED_STATUS.WITHHELD: return PHASEF_OUTCOME.WITHHELD;
    default: return PHASEF_OUTCOME.ABSTAIN;
  }
}

/** Normalize a cross-family adjudication status to a PHASEF_OUTCOME. */
function pfCrossFamilyOutcome(status) {
  switch (status) {
    case CROSS_FAMILY_STATUS.CORROBORATED: return PHASEF_OUTCOME.CORROBORATED;
    case CROSS_FAMILY_STATUS.FLAG: return PHASEF_OUTCOME.BLOCKED;
    default: return PHASEF_OUTCOME.ABSTAIN; // ABSTAIN (disagreement / quarantine / proof-judging reject).
  }
}

// ---------------------------------------------------------------------------
// THE ABLATION — certifiers OFF ⇒ the claim reverts to Increment-1's honest ABSTAIN arm. Modeled by
// routing the SAME proof-bearing claim through the REAL router with NO certifier inputs (the deferred
// arm): ABSTAIN+route, the rung untouched at UNVERIFIED. This is a REAL spine call, not a constant.
// ---------------------------------------------------------------------------

function pfFreshRouterFor(claim) {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.decompose(claim);
  return { ledger, router };
}

/** Run a Phase-F fixture's claim through the ablation arm (certifier disabled). Returns { outcome, rung }. */
async function pfAblationRun(fixture) {
  const { ledger, router } = pfFreshRouterFor(fixture.claim);
  const seam = fixture.verifier === 'cross-family' ? 'routeCrossFamily' : 'routeProofCertifier';
  const r = await router[seam](fixture.claim.id, {}); // NO inputs ⇒ the deferred (Increment-1 abstain) arm.
  return Object.freeze({
    outcome: r.verdict === ROUTE_VERDICT.ABSTAIN ? PHASEF_OUTCOME.ABSTAIN : r.verdict,
    routed: r.routed === true,
    rung: ledger.rungOf(fixture.claim.id),
  });
}

// ---------------------------------------------------------------------------
// THE PHASE-F FIXTURE CORPUS — declarative descriptors; the async probe builds + drives the spine.
// EVERY computational claim stays inside the z3-DECIDABLE envelope (decidable-arithmetic equalities).
// ---------------------------------------------------------------------------

/** A structured ground-equation proof claim (the translator's supported decidable-arithmetic class). */
function pfEqClaim(id, a, op, b, c, statement) {
  return Object.freeze({ id, type: 'proof-bearing', statement: statement || `${a} ${op} ${b} = ${c}`, meta: { equation: { a, op, b, c } } });
}

/** An informal-proof claim for the cross-family soft-check path. */
function pfProofClaim(id, statement, proof) {
  return Object.freeze({ id, type: 'proof-bearing', statement, meta: { proof } });
}

/**
 * LOAD the Phase-F fixture corpus. Returns a frozen { byClass, flat } structure; every fixture carries
 * { id, class, verifier, expected_outcome, scenario } and the data its scenario needs. Pure + frozen.
 */
export function loadPhaseFCorpus() {
  const O = PHASEF_OUTCOME;

  // (1) PLANTED-UNFAITHFUL — a Lean-VALID proof (exit 0) of a DIFFERENT statement than the claim asserts.
  // The statement says X but meta.equation encodes a different (also-true) equation Y ⇒ F3's differential
  // disagrees ⇒ OBSERVED hard-faults (BLOCKED). Each is the §v2.1 necessary-not-sufficient case (the finite
  // battery agrees; only the bounded differential catches the divergence).
  const plantedUnfaithful = [
    { id: 'pf-unfaithful::says-1+1=2-proves-2+2=4', claim: pfEqClaim('pf-uf-1', 2, '+', 2, 4, '1 + 1 = 2'), scenario: 'unfaithful' },
    { id: 'pf-unfaithful::says-3+4=7-proves-5+5=10', claim: pfEqClaim('pf-uf-2', 5, '+', 5, 10, '3 + 4 = 7'), scenario: 'unfaithful' },
    { id: 'pf-unfaithful::says-2*3=6-proves-4*2=8', claim: pfEqClaim('pf-uf-3', 4, '*', 2, 8, '2 * 3 = 6'), scenario: 'unfaithful' },
  ].map((f) => ({ ...f, class: 'phasef-planted-unfaithful', verifier: 'proof', expected_outcome: O.BLOCKED }));

  // (2) FALSE-LEAN — a false theorem the translator emits `by decide` over; lean rejects (exit non-zero).
  const falseLean = [
    { id: 'pf-false-lean::1+1=3', claim: pfEqClaim('pf-fl-1', 1, '+', 1, 3), scenario: 'false-lean' },
    { id: 'pf-false-lean::2+2=5', claim: pfEqClaim('pf-fl-2', 2, '+', 2, 5), scenario: 'false-lean' },
    { id: 'pf-false-lean::3*3=10', claim: pfEqClaim('pf-fl-3', 3, '*', 3, 10), scenario: 'false-lean' },
  ].map((f) => ({ ...f, class: 'phasef-false-lean', verifier: 'proof', expected_outcome: O.REJECTED }));

  // (3) CROSS-FAMILY-DISAGREEMENT — the panel splits (one VALID, one INVALID); no ≥2 agreeing quorum ⇒ the
  // claim stays CONJECTURAL (ABSTAIN). The independence canary re-runs the SAME split.
  const xfamDisagreement = [
    { id: 'pf-xfam-disagree::split-a', claim: pfProofClaim('pf-xd-1', '1 + 2 + 3 = 6', 'grouping argument'), qwen: 'VALID', llama: 'INVALID' },
    { id: 'pf-xfam-disagree::split-b', claim: pfProofClaim('pf-xd-2', '2 + 2 = 4', 'doubling'), qwen: 'INVALID', llama: 'VALID' },
    { id: 'pf-xfam-disagree::split-c', claim: pfProofClaim('pf-xd-3', '5 = 2 + 3', 'partition'), qwen: 'VALID', llama: 'INVALID' },
  ].map((f) => ({ ...f, class: 'phasef-xfam-disagreement', verifier: 'cross-family', scenario: 'xfam-disagree', expected_outcome: O.ABSTAIN }));

  // (4) QUARANTINE — a certifier that did NOT pass F0's proof-judging sentinel is dropped; the panel
  // agrees (VALID/VALID) but only ONE family is trusted ⇒ no ≥2-family quorum ⇒ the lift is DISABLED.
  const quarantine = [
    { id: 'pf-quarantine::llama-untrusted', claim: pfProofClaim('pf-q-1', '1 + 2 + 3 = 6', 'grouping'), trust: { qwen: true, llama: false } },
    { id: 'pf-quarantine::qwen-untrusted', claim: pfProofClaim('pf-q-2', '2 + 2 = 4', 'doubling'), trust: { qwen: false, llama: true } },
    { id: 'pf-quarantine::both-untrusted', claim: pfProofClaim('pf-q-3', '5 = 2 + 3', 'partition'), trust: { qwen: false, llama: false } },
  ].map((f) => ({ ...f, class: 'phasef-quarantine', verifier: 'cross-family', scenario: 'quarantine', expected_outcome: O.ABSTAIN }));

  // (5) FORGED / REPLAYED — artifacts the INDEPENDENT re-run catches (BLOCKED). Two lean (forged exit /
  // cross-claim binding) + two cross-family (forged verdict / cross-claim artifact).
  const forgedReplayed = [
    { id: 'pf-forged::lean-exit', claim: pfEqClaim('pf-fr-1', 1, '+', 1, 2), verifier: 'proof', scenario: 'forged-lean' },
    { id: 'pf-forged::lean-cross-claim', claim: pfEqClaim('pf-fr-2', 1, '+', 1, 2), verifier: 'proof', scenario: 'cross-claim-lean' },
    { id: 'pf-forged::xfam-verdict', claim: pfProofClaim('pf-fr-3', '1 + 2 + 3 = 6', 'grouping'), verifier: 'cross-family', scenario: 'forged-xfam' },
    { id: 'pf-forged::xfam-cross-claim', claim: pfProofClaim('pf-fr-4', '2 + 2 = 4', 'doubling'), verifier: 'cross-family', scenario: 'cross-claim-xfam' },
  ].map((f) => ({ ...f, class: 'phasef-forged-replayed', expected_outcome: O.BLOCKED }));

  // (6) PLAUSIBLE-BUT-WRONG — a proof that LOOKS valid but is wrong; the cross-family panel, honestly
  // re-run, REJECTS it (a NO quorum) ⇒ no corroboration. This is the F0 proof-judging sentinel in action.
  const plausibleButWrong = [
    { id: 'pf-plausible-wrong::false-identity', claim: pfProofClaim('pf-pw-1', 'every even number > 2 is a sum of two primes (asserted as proven by small cases)', 'checked up to 100'), qwen: 'INVALID', llama: 'INVALID' },
    { id: 'pf-plausible-wrong::off-by-one-lemma', claim: pfProofClaim('pf-pw-2', 'the sum 1..n equals n*(n+1)/2 + 1 (a planted off-by-one)', 'induction sketch'), qwen: 'INVALID', llama: 'INVALID' },
    { id: 'pf-plausible-wrong::circular', claim: pfProofClaim('pf-pw-3', 'sqrt(2) is rational (circular argument)', 'assume rational, derive rational'), qwen: 'INVALID', llama: 'INVALID' },
  ].map((f) => ({ ...f, class: 'phasef-plausible-but-wrong', verifier: 'cross-family', scenario: 'plausible-wrong', expected_outcome: O.ABSTAIN }));

  // (7) OBSERVED-SOUND (positive) — a true, faithful, decidable-arithmetic theorem ⇒ OBSERVED ON / ABSTAIN
  // OFF. The load-bearing positive arm: the certifier is what lifts it.
  const observedSound = [
    { id: 'pf-observed::1+1=2', claim: pfEqClaim('pf-os-1', 1, '+', 1, 2), scenario: 'observed-sound' },
    { id: 'pf-observed::2+2=4', claim: pfEqClaim('pf-os-2', 2, '+', 2, 4), scenario: 'observed-sound' },
    { id: 'pf-observed::3*4=12', claim: pfEqClaim('pf-os-3', 3, '*', 4, 12), scenario: 'observed-sound' },
  ].map((f) => ({ ...f, class: 'phasef-observed-sound', verifier: 'proof', expected_outcome: O.OBSERVED }));

  // (8) XFAM-SOUND (positive) — a genuine, re-run-agreeing cross-family quorum ⇒ soft-CORROBORATED ON /
  // ABSTAIN OFF (the weak local-fallback tier, NEVER OBSERVED).
  const xfamSound = [
    { id: 'pf-xfam-sound::a', claim: pfProofClaim('pf-xs-1', '1 + 2 + 3 = 6', 'grouping'), qwen: 'VALID', llama: 'VALID' },
    { id: 'pf-xfam-sound::b', claim: pfProofClaim('pf-xs-2', '2 + 2 = 4', 'doubling'), qwen: 'VALID', llama: 'VALID' },
    { id: 'pf-xfam-sound::c', claim: pfProofClaim('pf-xs-3', '5 = 2 + 3', 'partition'), qwen: 'VALID', llama: 'VALID' },
  ].map((f) => ({ ...f, class: 'phasef-xfam-sound', verifier: 'cross-family', scenario: 'xfam-sound', expected_outcome: O.CORROBORATED }));

  // (9) CORRELATED-FAILURE (honest bound) — BOTH families agree the proof is VALID, but it is actually
  // wrong (a correlated blind spot). The soft check CANNOT detect this — which is EXACTLY why the rung is
  // a SOFT check strictly BELOW OBSERVED. The fixture asserts the lift never exceeds the soft rung.
  const correlatedFailure = [
    { id: 'pf-correlated::both-wrong-but-agree', claim: pfProofClaim('pf-cf-1', 'a plausible-but-false lemma both local models accept', 'shared blind spot'), qwen: 'VALID', llama: 'VALID', scenario: 'correlated-failure' },
  ].map((f) => ({ ...f, class: 'phasef-correlated-failure', verifier: 'cross-family', expected_outcome: O.CORROBORATED }));

  // (10) OUT-OF-ENVELOPE (honest bound) — a QUANTIFIED formalization (outside z3-decidable) ⇒ faithfulness
  // fails-CLOSED ⇒ OBSERVED WITHHELD with the envelope reason code (the mathlib follow-on boundary).
  const outOfEnvelope = [
    { id: 'pf-out-of-envelope::quantified', scenario: 'out-of-envelope' },
  ].map((f) => ({ ...f, class: 'phasef-out-of-envelope', verifier: 'proof', expected_outcome: O.WITHHELD }));

  const byClass = {
    'phasef-planted-unfaithful': plantedUnfaithful,
    'phasef-false-lean': falseLean,
    'phasef-xfam-disagreement': xfamDisagreement,
    'phasef-quarantine': quarantine,
    'phasef-forged-replayed': forgedReplayed,
    'phasef-plausible-but-wrong': plausibleButWrong,
    'phasef-observed-sound': observedSound,
    'phasef-xfam-sound': xfamSound,
    'phasef-correlated-failure': correlatedFailure,
    'phasef-out-of-envelope': outOfEnvelope,
  };
  const freeze = (arr) => Object.freeze(arr.map((f) => Object.freeze(f)));
  const frozen = {};
  for (const k of Object.keys(byClass)) frozen[k] = freeze(byClass[k]);
  const flat = Object.freeze(PHASEF_CLASSES.flatMap((k) => frozen[k]));
  return Object.freeze({ byClass: Object.freeze(frozen), flat });
}

// ---------------------------------------------------------------------------
// THE PHASE-F PROBES — drive the REAL adjudicators ON; return the normalized PHASEF_OUTCOME + the rung.
// ---------------------------------------------------------------------------

/** Run the proof certifier (Lean + bounded z3 faithfulness) ON for a fixture. Returns { outcome, rung }. */
async function pfRunProofOn(fixture) {
  const { claim, scenario } = fixture;
  if (scenario === 'cross-claim-lean') {
    // A genuine OBSERVED-candidate artifact for `claim`, adjudicated AGAINST a DIFFERENT claim (the
    // statement-hash binding catches it ⇒ FLAG).
    const inputs = await pfProofInputs(claim, { exitCode: 0 });
    const other = pfEqClaim('pf-other-claim', 7, '+', 8, 15, '7 + 8 = 15');
    const r = await adjudicateObserved({ claim: other, ...inputs });
    return Object.freeze({ outcome: pfObservedOutcome(r.status), rung: RUNG.UNVERIFIED });
  }

  let inputs;
  if (scenario === 'unfaithful') {
    inputs = await pfProofInputs(claim, { exitCode: 0, producerSolve: PF_UNFAITHFUL_SOLVE, z3Rerun: PF_UNFAITHFUL_SOLVE });
  } else if (scenario === 'false-lean') {
    inputs = await pfProofInputs(claim, { exitCode: 1 });
  } else if (scenario === 'forged-lean') {
    // RECORDS exit 0 but the INDEPENDENT lean re-run from the stored .lean exits non-zero (the forgery).
    inputs = await pfProofInputs(claim, { exitCode: 0, leanRerunExit: 1 });
  } else {
    inputs = await pfProofInputs(claim, { exitCode: 0 }); // observed-sound
  }

  const { ledger, router } = pfFreshRouterFor(claim);
  // The adjudicator gives the PRECISE status (REJECTED vs FLAG vs OBSERVED); the router applies the lift.
  const adj = await adjudicateObserved({ claim, ...inputs });
  await router.routeProofCertifier(claim.id, { proof: inputs });
  return Object.freeze({ outcome: pfObservedOutcome(adj.status), rung: ledger.rungOf(claim.id) });
}

/** Run the cross-family verifier ON for a fixture. Returns { outcome, rung }. */
async function pfRunCrossFamilyOn(fixture) {
  const { claim, scenario } = fixture;
  const panelAnswers = { qwen: fixture.qwen ?? 'VALID', llama: fixture.llama ?? 'VALID' };

  if (scenario === 'cross-claim-xfam') {
    // Mint a genuine, re-run-agreeing artifact for `claim`, then present it for a DIFFERENT claim.
    const artifact = await runCrossFamilyPanel(claim, pfPanelOf('VALID', 'VALID'));
    const other = pfProofClaim('pf-xfam-other', '9 + 1 = 10', 'distinct');
    const adj = await adjudicateCrossFamily({ artifact, claim: other, rerun: pfRerunOf('VALID', 'VALID'), probeTrust: PF_BOTH_TRUSTED });
    return Object.freeze({ outcome: pfCrossFamilyOutcome(adj.status), rung: RUNG.UNVERIFIED });
  }

  const { ledger, router } = pfFreshRouterFor(claim);
  const snap = ledger.get(claim.id);
  const artifact = await runCrossFamilyPanel(snap, pfPanelOf(panelAnswers.qwen, panelAnswers.llama));

  // The independence canary re-run + the F0 proof-judging trust.
  const rerun = scenario === 'forged-xfam'
    ? pfRerunOf('INVALID', 'INVALID') // recorded VALID, but the models re-run say INVALID (the forgery).
    : pfRerunOf(panelAnswers.qwen, panelAnswers.llama);
  const probeTrust = fixture.trust || PF_BOTH_TRUSTED;

  const adj = await adjudicateCrossFamily({ artifact, claim: snap, rerun, probeTrust });
  await router.routeCrossFamily(claim.id, { crossFamily: { artifact, rerun, probeTrust } });
  return Object.freeze({ outcome: pfCrossFamilyOutcome(adj.status), rung: ledger.rungOf(claim.id) });
}

/** Run the out-of-z3-decidable-envelope fixture ON: a QUANTIFIED faithfulness query fails-closed (WITHHELD). */
async function pfRunOutOfEnvelopeOn() {
  const { count, domain } = pfBatterySpec();
  const query = {
    vars: ['n'],
    smt_logic: 'QF_LIA',
    domain,
    informal: '(forall ((k Int)) (=> (> k 1) (> (* k k) k)))', // a quantifier ⇒ OUT of the decidable envelope.
    formal: '(forall ((k Int)) (=> (> k 1) (> (* k k) k)))',
  };
  const battery = makePrngBatteryForOutOfEnvelope(query, count);
  const faith = await computeFaithfulness(query, battery, PF_FAITHFUL_SOLVE);
  const withheld = faith.verdict === FAITHFULNESS_VERDICT.WITHHELD && faith.outOfEnvelope === true && faith.reason === OUT_OF_ENVELOPE_REASON;
  return Object.freeze({ outcome: withheld ? PHASEF_OUTCOME.WITHHELD : PHASEF_OUTCOME.OBSERVED, rung: RUNG.UNVERIFIED, reason: faith.reason });
}

// A tiny local battery for the out-of-envelope probe (computeFaithfulness short-circuits BEFORE the battery
// for a quantified query, so the instances are never consumed — any non-Claude provenance suffices).
function makePrngBatteryForOutOfEnvelope(query, count) {
  const instances = [];
  for (let i = 0; i < count; i += 1) instances.push(Object.freeze({ n: query.domain.min + (i % (query.domain.max - query.domain.min + 1)) }));
  return Object.freeze({ provenance: 'prng', count, instances: Object.freeze(instances) });
}

/**
 * Run ONE Phase-F fixture through BOTH arms: the certifier ON (the real adjudicator) and the ABLATION
 * OFF (the deferred Increment-1 abstain arm). Returns a frozen
 *   { id, class, verifier, expected_outcome, on:{outcome,rung}, off:{outcome,routed,rung} }
 */
export async function runPhaseFFixture(fixture) {
  let on;
  if (fixture.class === 'phasef-out-of-envelope') {
    on = await pfRunOutOfEnvelopeOn();
  } else if (fixture.verifier === 'cross-family') {
    on = await pfRunCrossFamilyOn(fixture);
  } else {
    on = await pfRunProofOn(fixture);
  }
  // The out-of-envelope fixture has no admitted claim object (it probes the faithfulness layer directly);
  // its ablation is trivially ABSTAIN (no certifier, no lift).
  const off = fixture.claim
    ? await pfAblationRun(fixture)
    : Object.freeze({ outcome: PHASEF_OUTCOME.ABSTAIN, routed: true, rung: RUNG.UNVERIFIED });
  return Object.freeze({
    id: fixture.id,
    class: fixture.class,
    verifier: fixture.verifier,
    expected_outcome: fixture.expected_outcome,
    on,
    off,
  });
}

/**
 * A non-vacuity confirmation for the §v2.1 NECESSARY-NOT-SUFFICIENT claim: the planted-unfaithful battery
 * genuinely PASSES every enumerated concrete instance (each instance query is `unsat` ⇒ they agree) yet the
 * bounded DIFFERENTIAL finds a disagreeing model (`sat`) ⇒ UNFAITHFUL. Proves the differential bound is
 * load-bearing (the finite battery alone would have greened a wrong formalization).
 */
export async function plantedUnfaithfulIsNecessaryNotSufficient(fixture) {
  const { count, domain } = pfBatterySpec();
  const { faithfulness } = formalizeEquation(fixture.claim, { domain, batteryCount: count });
  const faith = await computeFaithfulness(faithfulness.query, faithfulness.battery, PF_UNFAITHFUL_SOLVE);
  return (
    faith.verdict === FAITHFULNESS_VERDICT.UNFAITHFUL &&
    faith.differentialResult === Z3_RESULT.SAT // the DIFFERENTIAL (not an instance) is what caught it.
  );
}

// Re-export the Phase-F vocabulary so tests + the scorer can branch without a second import.
export {
  OBSERVED_STATUS,
  OBSERVED_RUNG,
  CROSS_FAMILY_STATUS,
  PLAUSIBILITY_CORROBORATED_RUNG,
  FAITHFULNESS_VERDICT,
  OUT_OF_ENVELOPE_REASON,
};

// Re-export the rung/belief + verdict vocabulary so tests can branch without a second import.
export { RUNG, BELIEF, VERDICT, ROUTE_VERDICT, FIREWALL_STATUS, ABANDON_REASON };

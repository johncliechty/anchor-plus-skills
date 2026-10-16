// Wave 10 — Comprehension protocol (B1).
//
// The UNDERSTAND pillar's autonomous reading spine (NS1 — "verified laddered comprehension"). A
// mathematical METHOD (a paper / proof / worked technique, here a structured fixture) is read into
// a set of TYPED sub-claims, each of which is routed through the shared VERIFY spine so it lands in
// the A1 ledger at its HONEST rung — a literal finite computation can settle OBSERVED-via-firewall,
// while a proof obligation or a conceptual connection ABSTAINS to CONJECTURAL and routes out-of-model
// (THE HONESTY LAW: no proof/conceptual object reaches a VERIFIED rung in Increment-1).
//
// Two deliverables, wired against the REAL spine (no reimplementation):
//
//   1. THE STEP-0 FIREWALL-APPLICABILITY CLASSIFIER (a 3-way enum). Before the spine routes a
//      sub-claim, Step-0 decides whether the autonomous firewall (the Wave-8 closed default-deny
//      grammar + Wave-9 out-of-model subprocess) could even APPLY to it:
//
//        - APPLICABLE     — a literal finite computation the closed grammar RECOGNIZES; only this
//                           class is eligible for the autonomous-VERIFIED path.
//        - INAPPLICABLE   — a proof-bearing or conceptual claim: structurally NO autonomous verifier
//                           exists (its verifier is the Increment-2 out-of-model certifier).
//        - INDETERMINATE  — a claim that ASSERTS computability but whose expression is missing or is
//                           NOT in the closed grammar (a non-literal "looks computational" smuggle).
//
//      The classifier is FAIL-SAFE / default-deny: a sub-claim is APPLICABLE ONLY when the closed
//      grammar confirms an in-class literal computation. Everything else (INAPPLICABLE AND
//      INDETERMINATE) routes out-of-model and can NEVER reach autonomous-VERIFIED — the conservative
//      escalation that keeps a dressed-up proof from being laundered into the firewall path.
//
//   2. THE STATELESS 5-STEP SPINE. comprehend() runs five pure steps; it holds NO state between
//      calls (the only persistence is the injected A1 ledger + the durable adjudication substrate):
//
//        1. PARSE     — normalize the method into typed sub-claims (id, statement, declared type, expr).
//        2. CLASSIFY  — run the Step-0 firewall-applicability classifier over each sub-claim and resolve
//                       the claim-type to emit.
//        3. EMIT      — DECOMPOSE each typed claim into the shared A1 ledger at the FLOOR rung
//                       (UNVERIFIED) — "every emitted claim is UNVERIFIED until the router verifies it".
//        4. ROUTE     — push each claim through the shared Wave-7 VERIFY router. An APPLICABLE claim
//                       (with a dispatcher present) first MINTS the re-executable Wave-9 firewall
//                       artifact, then the router's adjudication gate lifts it to OBSERVED. Every other
//                       claim routes BARE — proof/conceptual ABSTAIN to CONJECTURAL via their deferred
//                       out-of-model verifier; an out-of-grammar "computation" is rejected by the
//                       router's grammar front-end and ABSTAINS. No artifact is ever minted for a
//                       non-APPLICABLE claim, so the firewall path cannot be laundered.
//        5. LADDER    — collect the per-claim rung + projected belief + honest stamp into the laddered
//                       comprehension, with the Honesty-Law and no-silent-pass invariants computed.
//
// The spine NEVER calls promote() or mints a family-of-record itself — the rung only ever rises
// through the router's Wave-4 adjudication gate (the flip law). Pure node built-ins + the project's
// own spine modules. Runs under `node --test test/`.

import { CLAIM_TYPES, RUNG, BELIEF } from './claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from './verify-router.mjs';
import { recognize, int, mul, variable, sum } from './firewall-grammar.mjs';
import { mintFirewallArtifact, FIREWALL_DOMAIN } from './firewall-subprocess.mjs';

// ---------------------------------------------------------------------------
// The Step-0 firewall-applicability enum (3-way).
// ---------------------------------------------------------------------------

/**
 * Can the autonomous firewall apply to a sub-claim?
 *   APPLICABLE    — a closed-grammar-recognized literal finite computation (eligible for VERIFIED).
 *   INAPPLICABLE  — a proof-bearing / conceptual claim (no autonomous verifier — Increment-2 route).
 *   INDETERMINATE — asserts computability but is not a recognized literal computation (smuggle / gap).
 * Only APPLICABLE is ever eligible for the autonomous-VERIFIED path; the other two route out-of-model.
 */
export const FIREWALL_APPLICABILITY = Object.freeze({
  APPLICABLE: 'firewall-applicable',
  INAPPLICABLE: 'firewall-inapplicable',
  INDETERMINATE: 'firewall-indeterminate',
});

/** The three enum values, as an array (introspection + exhaustiveness checks). */
export const FIREWALL_APPLICABILITY_VALUES = Object.freeze(Object.values(FIREWALL_APPLICABILITY));

/** The 5 ordered steps of the comprehension spine (Step-0 classify is folded into step 2 CLASSIFY). */
export const COMPREHENSION_STEPS = Object.freeze(['PARSE', 'CLASSIFY', 'EMIT', 'ROUTE', 'LADDER']);

const { APPLICABLE, INAPPLICABLE, INDETERMINATE } = FIREWALL_APPLICABILITY;

// ---------------------------------------------------------------------------
// Step-0 — the firewall-applicability classifier.
// ---------------------------------------------------------------------------

function classification(applicability, claim_type, reason, inGrammar) {
  return Object.freeze({ applicability, claim_type, reason, inGrammar });
}

/**
 * STEP-0 — classify a sub-claim's firewall-applicability (the 3-way enum) AND resolve the claim-type
 * to emit. FAIL-SAFE: APPLICABLE is returned ONLY when the closed default-deny grammar recognizes an
 * in-class literal computation; anything else is INAPPLICABLE (proof/conceptual) or INDETERMINATE
 * (an unrecognized "computation"), both of which route out-of-model and can never reach VERIFIED.
 *
 * @param {{type?:string, expr?:object, statement?:string}} subclaim
 * @returns {{applicability:string, claim_type:string, reason:string, inGrammar:boolean}} frozen.
 */
export function classifyFirewallApplicability(subclaim) {
  if (!subclaim || typeof subclaim !== 'object') {
    return classification(INDETERMINATE, 'conceptual', 'sub-claim is not an object — cannot classify; conservatively route out-of-model', false);
  }
  const type = subclaim.type;
  const hasExpr = subclaim.expr !== undefined && subclaim.expr !== null;

  // Proof-bearing / conceptual: structurally NO autonomous verifier (the Increment-2 certifier route).
  if (type === 'proof-bearing' || type === 'conceptual') {
    return classification(INAPPLICABLE, type, `a ${type} claim has no autonomous verifier in Increment-1 — routes out-of-model (firewall inapplicable)`, false);
  }

  // A claim that asserts computability: APPLICABLE only if the CLOSED grammar recognizes it.
  if (type === 'computational') {
    if (!hasExpr) {
      return classification(INDETERMINATE, 'computational', 'computational claim carries no expression AST — cannot confirm a literal finite computation; conservatively route out-of-model', false);
    }
    const rec = recognize(subclaim.expr);
    if (rec.inGrammar) {
      return classification(APPLICABLE, 'computational', 'recognized as an in-class literal finite computation by the closed default-deny grammar', true);
    }
    return classification(INDETERMINATE, 'computational', `expression is NOT in the closed firewall grammar (${rec.reason} [at ${rec.path}]) — a non-literal smuggle; conservatively route out-of-model`, false);
  }

  // An untyped sub-claim that nonetheless carries a recognized literal computation IS firewall-
  // applicable (the grammar is the gate, not the declared label) — emit it as computational.
  if (hasExpr) {
    const rec = recognize(subclaim.expr);
    if (rec.inGrammar) {
      return classification(APPLICABLE, 'computational', 'untyped sub-claim recognized as an in-class literal computation by the closed grammar', true);
    }
  }

  // Unknown / missing type and no recognized computation: conservatively conceptual + route out-of-model.
  return classification(INDETERMINATE, 'conceptual', `sub-claim type ${JSON.stringify(type)} is not a recognized claim type and no in-grammar computation is present — conservatively route out-of-model`, false);
}

// ---------------------------------------------------------------------------
// Step 1 — PARSE the method into typed sub-claims.
// ---------------------------------------------------------------------------

/**
 * STEP 1 — normalize a method fixture into a list of sub-claim specs. A method is
 * { id?, title?, subclaims:[{ id?, statement?, type?, expr?, expected_rung?, expected_belief? }] }.
 * A missing sub-claim id is derived deterministically from the method id + position (no wall-clock).
 */
export function parseMethod(method) {
  if (!method || typeof method !== 'object') {
    throw new Error('comprehend(): method must be an object { id?, subclaims:[...] }');
  }
  const subclaims = Array.isArray(method.subclaims) ? method.subclaims : null;
  if (!subclaims || subclaims.length === 0) {
    throw new Error('comprehend(): method has no `subclaims` to comprehend');
  }
  const base = typeof method.id === 'string' && method.id ? method.id : 'method';
  return subclaims.map((sc, i) => {
    if (!sc || typeof sc !== 'object') {
      throw new Error(`comprehend(): subclaim #${i} must be an object { type, statement?, expr? }`);
    }
    const id = typeof sc.id === 'string' && sc.id.length > 0 ? sc.id : `${base}::sub-${i}`;
    return Object.freeze({
      id,
      statement: typeof sc.statement === 'string' ? sc.statement : '',
      type: sc.type,
      expr: sc.expr,
      expected_rung: sc.expected_rung ?? null,
      expected_belief: sc.expected_belief ?? null,
    });
  });
}

// ---------------------------------------------------------------------------
// The 5-step spine.
// ---------------------------------------------------------------------------

function isLedgerLike(l) {
  return l && typeof l.assert === 'function' && typeof l.promote === 'function' && typeof l.get === 'function' && typeof l.has === 'function';
}

function isRouterLike(r) {
  return r && typeof r.decompose === 'function' && typeof r.route === 'function';
}

/**
 * The router-shaped result for an ALREADY-SETTLED (OBSERVED) claim re-encountered on a second
 * comprehension. Reuses the stamp the first routing wrote into meta (sticky), so the held claim
 * still reports its artifact-backed VERIFIED provenance without a second mint/promote.
 */
function heldResult(snap) {
  const prior = (snap.meta && snap.meta.verify_router) || {};
  const stamp = prior.stamp || { verifier_family: null, artifact_backed: snap.belief === BELIEF.VERIFIED };
  return Object.freeze({
    verdict: prior.verdict || ROUTE_VERDICT.VERIFIED,
    settled: true,
    routed: false,
    stamp: Object.freeze({ ...stamp }),
    advisory: null,
    rung: snap.rung,
    belief: snap.belief,
  });
}

/**
 * The stateless comprehension protocol. Binds the injected spine (the shared A1 ledger, the VERIFY
 * router over that SAME ledger, and the optional out-of-model adjudication dispatcher) — but holds
 * NO per-run state: each comprehend() call is independent and re-entrant.
 */
export class ComprehensionProtocol {
  #ledger;
  #router;
  #dispatcher;

  /**
   * @param {{ledger:object, dispatcher?:object, router?:VerifyRouter}} o
   *   ledger     — the shared A1 ClaimLedger the comprehension emits into.
   *   dispatcher — the Wave-4 AdjudicationDispatcher; present => APPLICABLE computations can settle
   *                OBSERVED. Absent => even an APPLICABLE computation ABSTAINs (honest no-minter arm).
   *   router     — an optional pre-built VERIFY router; MUST be over the same ledger. Defaults to a
   *                fresh VerifyRouter({ ledger, dispatcher }).
   */
  constructor({ ledger, dispatcher = null, router = null } = {}) {
    if (!isLedgerLike(ledger)) {
      throw new Error('ComprehensionProtocol requires an A1 ClaimLedger ({assert, promote, get, has})');
    }
    if (router !== null && !isRouterLike(router)) {
      throw new Error('ComprehensionProtocol router must be a VerifyRouter ({decompose, route})');
    }
    this.#ledger = ledger;
    this.#dispatcher = dispatcher;
    this.#router = router || new VerifyRouter({ ledger, dispatcher });
  }

  /** The shared ledger this protocol emits into. */
  get ledger() {
    return this.#ledger;
  }

  /** The VERIFY router this protocol routes through. */
  get router() {
    return this.#router;
  }

  /**
   * Run the stateless 5-step comprehension spine over a method. Returns the frozen laddered
   * comprehension (see #ladder). PARSE -> CLASSIFY (Step-0) -> EMIT -> ROUTE -> LADDER.
   */
  comprehend(method) {
    const parsed = parseMethod(method); // 1. PARSE
    const classified = parsed.map((sc) => {
      // 2. CLASSIFY — Step-0 firewall-applicability + claim-type resolution.
      const cls = classifyFirewallApplicability(sc);
      return Object.freeze({ ...sc, applicability: cls.applicability, claim_type: cls.claim_type, classify_reason: cls.reason, inGrammar: cls.inGrammar });
    });

    // 3. EMIT — DECOMPOSE every typed claim into the shared ledger at the floor rung (UNVERIFIED).
    //    An attached expression rides into meta so the router's grammar front-end can see it.
    for (const c of classified) {
      const spec = { id: c.id, type: c.claim_type, statement: c.statement };
      if (c.expr !== undefined && c.expr !== null) spec.expr = c.expr;
      this.#router.decompose(spec);
    }

    // 4. ROUTE — push each claim through the shared VERIFY spine.
    const routed = classified.map((c) => {
      let result;
      // STICKY / idempotent: a claim already settled at OBSERVED is HELD — the spine does NOT mint a
      // fresh artifact to re-promote it (the adjudication gate is the sole rung-raiser and refuses a
      // non-raising promote). Re-comprehension thus never double-promotes (the flip law at the spine).
      if (this.#ledger.get(c.id).rung === RUNG.OBSERVED) {
        result = heldResult(this.#ledger.get(c.id));
      } else if (c.applicability === APPLICABLE && this.#dispatcher) {
        // The autonomous path: mint the re-executable Wave-9 firewall artifact for THIS claim, then
        // let the router's adjudication gate consume its single-use nonce and lift it to OBSERVED.
        const { artifact } = mintFirewallArtifact(this.#dispatcher, c.id, c.expr, { domain: FIREWALL_DOMAIN });
        result = this.#router.route(c.id, { dispatcher: this.#dispatcher, artifact });
      } else {
        // Every non-APPLICABLE claim (and an APPLICABLE one with no minter) routes BARE: proof/
        // conceptual ABSTAIN via their deferred verifier; an out-of-grammar "computation" is rejected
        // by the router's grammar front-end. NO artifact is minted, so the firewall cannot be laundered.
        result = this.#router.route(c.id, {});
      }
      return Object.freeze({ ...c, result });
    });

    // 5. LADDER — collect the honest per-claim rung/belief/stamp into the laddered comprehension.
    return this.#ladder(method, routed);
  }

  #ladder(method, routed) {
    const claims = routed.map((c) => {
      const snap = this.#ledger.get(c.id);
      const r = c.result;
      return Object.freeze({
        id: c.id,
        statement: c.statement,
        claim_type: c.claim_type,
        applicability: c.applicability,
        classify_reason: c.classify_reason,
        verdict: r.verdict,
        rung: snap.rung,
        belief: snap.belief,
        settled: r.settled,
        verifier_family: r.stamp.verifier_family,
        artifact_backed: r.stamp.artifact_backed,
        advisory: r.advisory,
        expected_rung: c.expected_rung,
        expected_belief: c.expected_belief,
        rung_matches_expected: c.expected_rung == null ? null : snap.rung === c.expected_rung,
        belief_matches_expected: c.expected_belief == null ? null : snap.belief === c.expected_belief,
      });
    });

    const byRung = {};
    for (const c of claims) (byRung[c.rung] ||= []).push(c.id);

    return Object.freeze({
      method_id: typeof method.id === 'string' ? method.id : null,
      steps: COMPREHENSION_STEPS,
      claims: Object.freeze(claims),
      ladder: Object.freeze(byRung),
      anyVerified: claims.some((c) => c.belief === BELIEF.VERIFIED),
      // THE HONESTY LAW: NO proof-bearing / conceptual claim is ever at OBSERVED / VERIFIED.
      honestyLawHeld: claims.every((c) => c.claim_type === 'computational' || (c.rung !== RUNG.OBSERVED && c.belief !== BELIEF.VERIFIED)),
      // NO SILENT PASS: each claim is either an artifact-backed VERIFIED, or routed with an advisory
      // payload and a non-settled (non-VERIFIED) belief.
      noSilentPass: claims.every((c) =>
        (c.settled && c.belief === BELIEF.VERIFIED && c.artifact_backed === true) ||
        (!c.settled && c.advisory !== null && c.belief !== BELIEF.VERIFIED),
      ),
      // The done-when: every claim with a pinned expectation landed at the EXPECTED rung + belief.
      expectationsMet: claims.every((c) => c.rung_matches_expected !== false && c.belief_matches_expected !== false),
    });
  }
}

/**
 * Convenience: build a ComprehensionProtocol over the given ledger (+ dispatcher) and comprehend a
 * method in one call. Returns the frozen laddered comprehension.
 */
export function comprehend(method, { ledger, dispatcher = null, router = null } = {}) {
  return new ComprehensionProtocol({ ledger, dispatcher, router }).comprehend(method);
}

// ---------------------------------------------------------------------------
// THE FIXTURE METHOD — a method carrying a computable AND a proof-bearing sub-claim (the done-when),
// plus a conceptual connection and an INDETERMINATE "looks-computational" smuggle, so a single
// comprehension exercises all three firewall-applicability enum values + the Honesty Law.
// ---------------------------------------------------------------------------

/** sum_{k=1}^{3} (k*2) = 2 + 4 + 6 = 12 — an in-class bounded sum of products (the computable sub-claim). */
const COMPUTABLE_EXPR = sum('k', int(1), int(3), mul(variable('k'), int(2)));

export const FIXTURE_METHOD = Object.freeze({
  id: 'fixture-method-laddered-comprehension',
  title: 'A worked method carrying a literal computation and a proof obligation',
  subclaims: Object.freeze([
    // APPLICABLE — a literal finite computation: settles OBSERVED-via-firewall (belief VERIFIED).
    Object.freeze({
      id: 'fm::partial-sum-equals-12',
      statement: 'The partial sum S = sum_{k=1}^{3} (k * 2) evaluates to 12.',
      type: 'computational',
      expr: COMPUTABLE_EXPR,
      expected_rung: RUNG.OBSERVED,
      expected_belief: BELIEF.VERIFIED,
    }),
    // INAPPLICABLE (proof) — a proof obligation: ABSTAIN to CONJECTURAL, route out-of-model. Never VERIFIED.
    Object.freeze({
      id: 'fm::series-converges',
      statement: 'The underlying series converges for all admissible parameters (a proof obligation).',
      type: 'proof-bearing',
      expected_rung: RUNG.UNVERIFIED,
      expected_belief: BELIEF.CONJECTURAL,
    }),
    // INAPPLICABLE (conceptual) — a structural connection: ABSTAIN to CONJECTURAL, route out-of-model.
    Object.freeze({
      id: 'fm::generalizes-partial-fractions',
      statement: 'This method is a generalization of the classical partial-fraction technique (a conceptual connection).',
      type: 'conceptual',
      expected_rung: RUNG.UNVERIFIED,
      expected_belief: BELIEF.CONJECTURAL,
    }),
    // INDETERMINATE — asserts a "computation" but is a non-literal limit (out of grammar). The firewall
    // front-end rejects it: ABSTAIN to CONJECTURAL. A dressed-up analysis claim is NEVER laundered to VERIFIED.
    Object.freeze({
      id: 'fm::tail-limit-is-zero',
      statement: 'The tail limit lim_{n->inf} a_n equals 0 (asserted as a computation, but not a literal finite one).',
      type: 'computational',
      expr: Object.freeze({ type: 'limit', var: 'n', to: 'infinity', body: { type: 'var', name: 'n' } }),
      expected_rung: RUNG.UNVERIFIED,
      expected_belief: BELIEF.CONJECTURAL,
    }),
  ]),
});

/**
 * Comprehend the FIXTURE_METHOD end-to-end through the real spine. `dispatcher` (the Wave-4
 * AdjudicationDispatcher over the durable substrate) is required for the computable sub-claim to
 * settle OBSERVED; the caller owns the substrate + temp files (mirrors the Wave-9 roster runner).
 */
export function runFixtureComprehension({ ledger, dispatcher } = {}) {
  return comprehend(FIXTURE_METHOD, { ledger, dispatcher });
}

// Re-exported so tests + later pillars can branch on the router verdict vocabulary without a second import.
export { ROUTE_VERDICT };

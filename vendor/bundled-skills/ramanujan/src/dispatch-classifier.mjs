// Wave 16 — Claim-type dispatch classifier (C2).
//
// A FAIL-SAFE, SEPARATE-PASS claim-type DISPATCH classifier with CONSERVATIVE ESCALATION to the
// proof route. Where Wave-15 generation (C1) PROPOSES a candidate and decomposes it into typed
// claims at the floor rung, this pass DECIDES — for each claim, and BEFORE the Wave-7 router runs —
// which VERIFICATION ROUTE the claim takes:
//
//   AUTONOMOUS_FIREWALL — a CLOSED-grammar-recognized literal finite computation. The ONLY route
//                         eligible for the autonomous-VERIFIED tier (and even then only later,
//                         through the Wave-8 grammar + Wave-9 subprocess + Wave-4 artifact gate).
//   PROOF               — a proof-bearing claim AND every ambiguous/borderline claim, conservatively
//                         ESCALATED here. ABSTAIN + route out-of-model.
//   CONCEPTUAL          — a clearly conceptual claim. ABSTAIN + route out-of-model.
//
// THE DEFINING INVARIANT (the done-when). "Ambiguous/borderline claims escalate conservatively to the
// proof route (ABSTAIN+route), NEVER silently to autonomous-VERIFIED." So this pass is DEFAULT-DENY:
// a claim is marked AUTONOMOUS-ELIGIBLE *only* when the closed default-deny firewall grammar
// (Wave 8) recognizes its expression as an in-class exact-arithmetic literal computation. EVERYTHING
// else — a computational claim with no expression, a computational claim whose expression is out of
// grammar (a smuggle, however deeply nested), an untyped claim with no recognizable computation, an
// unknown claim type, or a malformed input — ESCALATES to the PROOF route (the strongest, most
// conservative out-of-model burden: treat it as if it needs a proof certifier). The proof route has
// NO autonomous verifier, so escalation can never reach VERIFIED.
//
// WHY THE PROOF ROUTE (and not just "conceptual") for borderline claims. Routing an ambiguous claim
// to the proof route is the conservative choice: it asserts the STRONGEST out-of-model verification
// burden (a Lean/SMT-class certifier), never UNDER-claims what is needed to settle it, and — unlike a
// would-be computational dispatch — never offers an autonomous path. This is the deliberate
// difference from the Wave-10 Step-0 firewall-applicability classifier (whose INDETERMINATE arm falls
// back to `conceptual`): C2 ESCALATES borderline claims UP to proof.
//
// THE GRAMMAR IS THE GATE, NOT THE LABEL. A claim is never trusted into the autonomous route on its
// declared `type` alone — the closed grammar must recognize the actual expression. Conversely a claim
// that is NOT declared computational but DOES carry a closed-grammar-recognized literal computation is
// autonomous-eligible (the grammar's recognition is itself the affirmative, fail-safe signal). The
// laundering vector this closes: a bare assertion (no expr) or a smuggled non-literal expression can
// NEVER be dispatched autonomous, regardless of how it is labeled.
//
// SEPARATE PASS / NO RUNG TOUCH. C2 is a pure CLASSIFICATION pass: it reads claims (specs, or ledger
// snapshots by id) and produces a frozen DISPATCH PLAN. It NEVER calls assert()/promote(), mints no
// artifact, and raises no rung — it physically cannot settle anything. The actual verification is the
// Wave-7 router; `dispatchAndRoute` below wires the C2 plan THROUGH the real router to prove the
// end-to-end abstain (borderline -> proof route -> ABSTAIN, never VERIFIED).
//
// Pure node built-ins + the project's own spine modules (the A1 ledger; the Wave-8 grammar recognizer;
// the Wave-7 router for the end-to-end proof). Runs under `node --test test/`.

import { ClaimLedger } from './claim-ledger.mjs';
import { recognize, int, add, mul, div, variable, sum } from './firewall-grammar.mjs';
import { VerifyRouter, ROUTE_VERDICT } from './verify-router.mjs';

// ---------------------------------------------------------------------------
// The dispatch routes + decisions.
// ---------------------------------------------------------------------------

/**
 * The three dispatch ROUTES a claim can be classified into.
 *   AUTONOMOUS_FIREWALL — closed-grammar-recognized literal computation; the ONLY autonomous-eligible
 *                         route (the firewall subprocess path to OBSERVED/VERIFIED).
 *   PROOF               — proof-bearing claims + every conservative escalation of an ambiguous claim.
 *   CONCEPTUAL          — clearly conceptual claims.
 * Only AUTONOMOUS_FIREWALL is ever eligible for the autonomous-VERIFIED tier; PROOF and CONCEPTUAL
 * both ABSTAIN + route out-of-model.
 */
export const DISPATCH_ROUTE = Object.freeze({
  AUTONOMOUS_FIREWALL: 'autonomous-firewall',
  PROOF: 'proof',
  CONCEPTUAL: 'conceptual',
});

/** The three routes, as an array (introspection + exhaustiveness checks). */
export const DISPATCH_ROUTES = Object.freeze(Object.values(DISPATCH_ROUTE));

/**
 * The dispatch DECISION attached to each route.
 *   AUTONOMOUS_CANDIDATE — eligible for the autonomous firewall path (route === AUTONOMOUS_FIREWALL).
 *   ABSTAIN_AND_ROUTE    — honest ABSTAIN + route out-of-model (PROOF or CONCEPTUAL).
 */
export const DISPATCH_DECISION = Object.freeze({
  AUTONOMOUS_CANDIDATE: 'autonomous-candidate',
  ABSTAIN_AND_ROUTE: 'abstain-and-route',
});

/** The route each escalated/non-autonomous claim_type maps to. */
const ROUTE_FOR_TYPE = Object.freeze({
  computational: DISPATCH_ROUTE.AUTONOMOUS_FIREWALL,
  'proof-bearing': DISPATCH_ROUTE.PROOF,
  conceptual: DISPATCH_ROUTE.CONCEPTUAL,
});

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

/** The expression AST attached to a claim: a direct `expr`, else one persisted in `meta.expr`. */
function exprOf(claim) {
  if (claim && typeof claim === 'object') {
    if (claim.expr !== undefined && claim.expr !== null) return claim.expr;
    if (claim.meta && claim.meta.expr !== undefined && claim.meta.expr !== null) return claim.meta.expr;
  }
  return undefined;
}

/** Build a frozen classification result. */
function decision(route, claim_type, declared_type, escalated, inGrammar, reason) {
  const dispatch_decision =
    route === DISPATCH_ROUTE.AUTONOMOUS_FIREWALL ? DISPATCH_DECISION.AUTONOMOUS_CANDIDATE : DISPATCH_DECISION.ABSTAIN_AND_ROUTE;
  return Object.freeze({
    route,
    decision: dispatch_decision,
    claim_type, // the conservatively-resolved type to dispatch on (an escalation may raise it to proof-bearing)
    declared_type: declared_type === undefined ? null : declared_type, // the claim's original declared type (transparency)
    autonomous_eligible: route === DISPATCH_ROUTE.AUTONOMOUS_FIREWALL,
    escalated, // true when an ambiguous/borderline claim was conservatively escalated to the proof route
    inGrammar, // true ONLY when the closed grammar recognized an in-class literal computation
    reason,
  });
}

/** Conservatively escalate an ambiguous/borderline claim to the PROOF route (the done-when's core). */
function escalateToProof(declared_type, inGrammar, reason) {
  return decision(DISPATCH_ROUTE.PROOF, 'proof-bearing', declared_type, true, inGrammar, reason);
}

// ---------------------------------------------------------------------------
// The core classifier (a single claim).
// ---------------------------------------------------------------------------

/**
 * Classify ONE claim into a dispatch route. FAIL-SAFE / default-deny: the AUTONOMOUS_FIREWALL route
 * is returned ONLY when the closed grammar recognizes an in-class literal computation; every
 * ambiguous/borderline claim is conservatively ESCALATED to the PROOF route (ABSTAIN+route), so it
 * can never silently reach autonomous-VERIFIED.
 *
 * @param {{id?:string, type?:string, expr?:object, meta?:object, statement?:string}} claim
 * @returns {{route:string, decision:string, claim_type:string, declared_type:string|null,
 *            autonomous_eligible:boolean, escalated:boolean, inGrammar:boolean, reason:string}} frozen.
 */
export function classifyDispatch(claim) {
  // Malformed input — cannot even classify it; conservatively escalate to the proof route.
  if (!claim || typeof claim !== 'object') {
    return escalateToProof(null, false, 'claim is not an object — cannot classify; conservatively escalate to the proof route');
  }

  const declared = claim.type;
  const expr = exprOf(claim);
  const hasExpr = expr !== undefined && expr !== null;

  // CLEARLY proof-bearing — the proof route (no autonomous verifier). Not an escalation: it is what it
  // declares, so `escalated` is false.
  if (declared === 'proof-bearing') {
    return decision(
      DISPATCH_ROUTE.PROOF,
      'proof-bearing',
      declared,
      false,
      false,
      'declared proof-bearing — proof route (no autonomous verifier in Increment-1; out-of-model certifier)',
    );
  }

  // CLEARLY conceptual — the conceptual route (no autonomous verifier).
  if (declared === 'conceptual') {
    return decision(
      DISPATCH_ROUTE.CONCEPTUAL,
      'conceptual',
      declared,
      false,
      false,
      'declared conceptual — conceptual route (no autonomous verifier in Increment-1; out-of-model corroborator)',
    );
  }

  // ASSERTS computability (declared computational) — autonomous ONLY if the CLOSED grammar recognizes it.
  if (declared === 'computational') {
    if (!hasExpr) {
      // BORDERLINE: a bare computational assertion with nothing to recognize. Escalate to proof.
      return escalateToProof(
        declared,
        false,
        'computational claim carries no expression AST — cannot confirm a literal finite computation; conservatively escalate to the proof route',
      );
    }
    const rec = recognize(expr);
    if (rec.inGrammar) {
      return decision(
        DISPATCH_ROUTE.AUTONOMOUS_FIREWALL,
        'computational',
        declared,
        false,
        true,
        'recognized as an in-class literal finite computation by the closed default-deny grammar — autonomous-firewall candidate',
      );
    }
    // SMUGGLE: declared computational but the expression is out of grammar (a float/symbol/unbounded/
    // unknown node, however deeply nested). Escalate to proof — never let a non-literal masquerade
    // into the autonomous route.
    return escalateToProof(
      declared,
      false,
      `expression is NOT in the closed firewall grammar (${rec.reason} [at ${rec.path}]) — a non-literal smuggle masquerading as computational; conservatively escalate to the proof route`,
    );
  }

  // UNTYPED but carrying a closed-grammar-recognized literal computation: the grammar is the gate, not
  // the label — autonomous-eligible.
  if (hasExpr) {
    const rec = recognize(expr);
    if (rec.inGrammar) {
      return decision(
        DISPATCH_ROUTE.AUTONOMOUS_FIREWALL,
        'computational',
        declared,
        false,
        true,
        'untyped claim carries a closed-grammar-recognized literal computation — the grammar is the gate, not the label; autonomous-firewall candidate',
      );
    }
    // Untyped + an out-of-grammar expression: ambiguous AND not recognizable — escalate to proof.
    return escalateToProof(
      declared,
      false,
      `untyped claim carries an out-of-grammar expression (${rec.reason} [at ${rec.path}]) — ambiguous and not a recognizable literal computation; conservatively escalate to the proof route`,
    );
  }

  // UNKNOWN/missing type and no recognizable computation: ambiguous — conservatively escalate to proof.
  return escalateToProof(
    declared,
    false,
    `claim type ${JSON.stringify(declared)} is not a recognized claim type and no in-grammar computation is present — ambiguous; conservatively escalate to the proof route`,
  );
}

// ---------------------------------------------------------------------------
// The separate-pass classifier.
// ---------------------------------------------------------------------------

function isLedgerLike(l) {
  return l && typeof l.assert === 'function' && typeof l.get === 'function' && typeof l.has === 'function';
}

/**
 * The SEPARATE-PASS claim-type DISPATCH classifier. Stateless: it may be bound to an A1 ledger so a
 * claim can be passed by id (its snapshot is read), but the pass touches NO rung — it only classifies.
 */
export class DispatchClassifier {
  #ledger;

  /** @param {{ledger?:object}} o — optional A1 ledger to resolve claims passed by id. */
  constructor({ ledger = null } = {}) {
    if (ledger !== null && !isLedgerLike(ledger)) {
      throw new Error('DispatchClassifier ledger (when given) must be an A1 ClaimLedger ({assert, get, has})');
    }
    this.#ledger = ledger;
  }

  /** The ledger (if any) this classifier resolves ids against. */
  get ledger() {
    return this.#ledger;
  }

  /** Resolve a claim input (a spec object, or an id string when a ledger is bound) to a claim object. */
  #resolve(claim) {
    if (typeof claim === 'string') {
      if (!this.#ledger) {
        throw new Error(`classify(): claim "${claim}" was passed by id but no ledger is bound to resolve it`);
      }
      if (!this.#ledger.has(claim)) {
        throw new Error(`classify(): no claim "${claim}" in the bound ledger`);
      }
      return this.#ledger.get(claim);
    }
    return claim;
  }

  /** Classify a single claim (spec or bound-ledger id). Returns the frozen classification + claim_id. */
  classify(claim) {
    const resolved = this.#resolve(claim);
    const d = classifyDispatch(resolved);
    return Object.freeze({ claim_id: (resolved && typeof resolved === 'object' && resolved.id) || null, ...d });
  }

  /**
   * Run the SEPARATE PASS over a batch of claims (a single claim or an array). Returns a frozen
   * dispatch PLAN summarizing per-claim decisions + the done-when invariants.
   */
  dispatch(claims) {
    const list = Array.isArray(claims) ? claims : [claims];
    const decisions = list.map((c) => this.classify(c));
    return this.#assemble(decisions);
  }

  #assemble(decisions) {
    const byRoute = { [DISPATCH_ROUTE.AUTONOMOUS_FIREWALL]: [], [DISPATCH_ROUTE.PROOF]: [], [DISPATCH_ROUTE.CONCEPTUAL]: [] };
    for (const d of decisions) (byRoute[d.route] ||= []).push(d.claim_id);

    const autonomousCandidates = decisions.filter((d) => d.autonomous_eligible).map((d) => d.claim_id);
    const escalated = decisions.filter((d) => d.escalated).map((d) => d.claim_id);

    return Object.freeze({
      decisions: Object.freeze(decisions),
      routes: DISPATCH_ROUTES,
      byRoute: Object.freeze({
        [DISPATCH_ROUTE.AUTONOMOUS_FIREWALL]: Object.freeze(byRoute[DISPATCH_ROUTE.AUTONOMOUS_FIREWALL]),
        [DISPATCH_ROUTE.PROOF]: Object.freeze(byRoute[DISPATCH_ROUTE.PROOF]),
        [DISPATCH_ROUTE.CONCEPTUAL]: Object.freeze(byRoute[DISPATCH_ROUTE.CONCEPTUAL]),
      }),
      autonomousCandidates: Object.freeze(autonomousCandidates),
      escalated: Object.freeze(escalated),
      // THE DONE-WHEN (classifier arm) — the fail-safe invariants:
      // 1. A claim is autonomous-eligible ONLY if the closed grammar recognized it (no silent autonomy).
      noSilentAutonomous: decisions.every((d) => (d.autonomous_eligible ? d.inGrammar === true && d.claim_type === 'computational' : true)),
      // 2. Every ambiguous/borderline claim escalated to the PROOF route, never to autonomous.
      borderlineEscalatesToProof: decisions.every((d) => (d.escalated ? d.route === DISPATCH_ROUTE.PROOF && d.autonomous_eligible === false : true)),
      // 3. No silent pass: every non-autonomous decision is an explicit ABSTAIN+route.
      allDecided: decisions.every((d) => (d.autonomous_eligible ? true : d.decision === DISPATCH_DECISION.ABSTAIN_AND_ROUTE)),
    });
  }
}

/** Convenience: run the separate-pass classifier over claims in one call. Returns the dispatch plan. */
export function dispatchClaims(claims, { ledger = null } = {}) {
  return new DispatchClassifier({ ledger }).dispatch(claims);
}

// ---------------------------------------------------------------------------
// End-to-end proof: the C2 dispatch plan THROUGH the real Wave-7 router.
// ---------------------------------------------------------------------------

/** Resolve a raw input (spec or bound-ledger id) into {id, type, statement, expr} for routing. */
function resolveForRouting(raw, ledger, index) {
  let claim = raw;
  if (typeof raw === 'string') {
    if (!ledger || !ledger.has(raw)) throw new Error(`dispatchAndRoute(): claim id "${raw}" is not in the ledger`);
    claim = ledger.get(raw);
  }
  const id = (claim && typeof claim === 'object' && typeof claim.id === 'string' && claim.id) || `c2::claim-${index}`;
  const statement = claim && typeof claim === 'object' && typeof claim.statement === 'string' ? claim.statement : '';
  return { id, statement, expr: exprOf(claim), raw: claim };
}

/**
 * Run the C2 SEPARATE PASS, then ROUTE each claim THROUGH the real Wave-7 VerifyRouter using the
 * dispatch the classifier decided — proving the done-when END-TO-END: a borderline claim, escalated
 * to the proof route, comes back ABSTAIN from the real router and NEVER reaches autonomous-VERIFIED,
 * even with an adjudication dispatcher present.
 *
 * Each claim is routed under the C2-RESOLVED `claim_type` (a borderline computational claim is routed
 * as proof-bearing — the escalation), while its original expression is preserved for transparency.
 * Uses a FRESH ledger by default so the conservative re-typing never conflicts with a pre-existing
 * claim's fixed type.
 *
 * @returns frozen { ledger, classifier, router, plan, routed, noBorderlineVerified, borderlineAbstains,
 *                   noSilentAutonomous, allRouted }.
 */
export function dispatchAndRoute(
  claims,
  { ledger = new ClaimLedger(), dispatcher = null, commissioner = null, artifacts = {}, artifact = undefined } = {},
) {
  const list = Array.isArray(claims) ? claims : [claims];
  const classifier = new DispatchClassifier({ ledger: isLedgerLike(ledger) ? ledger : null });
  const router = new VerifyRouter({ ledger, dispatcher, commissioner });

  const routed = list.map((raw, i) => {
    const r = resolveForRouting(raw, ledger, i);
    const d = classifyDispatch(r.raw);
    // Hand the router the C2 dispatch decision: the (possibly escalated) claim_type + preserved expr.
    const spec = { id: r.id, type: d.claim_type, statement: r.statement, expr: r.expr };
    const useArtifact = Object.prototype.hasOwnProperty.call(artifacts, r.id) ? artifacts[r.id] : artifact;
    const result = router.route(spec, { artifact: useArtifact });
    return Object.freeze({
      claim_id: r.id,
      dispatch: d,
      verdict: result.verdict,
      rung: result.rung,
      belief: result.belief,
      settled: result.settled,
      routed: result.routed,
      verifier: result.verifier,
    });
  });

  const plan = classifier.dispatch(list.map((raw, i) => resolveForRouting(raw, ledger, i).raw));

  return Object.freeze({
    ledger,
    classifier,
    router,
    plan,
    routed: Object.freeze(routed),
    // THE DONE-WHEN (router arm), proven against the REAL Wave-7 router:
    // No escalated/borderline claim is ever settled VERIFIED.
    noBorderlineVerified: routed.every((r) => (r.dispatch.escalated ? r.verdict !== ROUTE_VERDICT.VERIFIED : true)),
    // Every escalated/borderline claim comes back as an honest ABSTAIN (routed out-of-model).
    borderlineAbstains: routed.filter((r) => r.dispatch.escalated).every((r) => r.verdict === ROUTE_VERDICT.ABSTAIN),
    // A claim only reaches the autonomous firewall verifier if C2 found it in-grammar.
    noSilentAutonomous: routed.every((r) => (r.dispatch.autonomous_eligible ? r.dispatch.inGrammar === true : true)),
    // No silent pass: every claim is either VERIFIED (artifact-backed) or routed out-of-model.
    allRouted: routed.every((r) => r.settled || r.routed),
  });
}

// ---------------------------------------------------------------------------
// THE FIXTURES — a battery of BORDERLINE/AMBIGUOUS claims (each MUST escalate to the proof route) and
// a set of CLEAR claims (each routes to its honest route), so a single dispatch pass exercises the
// fail-safe + the conservative escalation + the autonomous-eligibility gate.
//
// The grammar builders are used ONLY to author the fixture's in-grammar literal computations; the
// out-of-grammar "smuggle" expressions are hand-built so the closed recognizer rejects them.
// ---------------------------------------------------------------------------

/** sum_{k=1}^{5} k — an in-class bounded sum (in grammar). */
const IN_GRAMMAR_SUM = sum('k', int(1), int(5), variable('k'));
/** (6 * 7) / 2 — an in-class literal computation (in grammar). */
const IN_GRAMMAR_CLOSED_FORM = div(mul(int(6), int(7)), int(2));
/** A FREE/symbolic variable — out of grammar (only a BOUND sum/product index is in grammar). */
const FREE_VAR_EXPR = variable('x');
/** A float literal — out of grammar (NO float; exact integers only). */
const FLOAT_EXPR = int(1.5);
/** A deep-nested smuggle: 2 + (3 * x) — an otherwise-valid tree with a free var buried inside. */
const NESTED_SMUGGLE_EXPR = add(int(2), mul(int(3), variable('z')));
/** An unbounded sum: sum_{k=1}^{infinity} k — the upper bound is not a literal integer. */
const UNBOUNDED_SUM_EXPR = sum('k', int(1), { type: 'infinity' }, variable('k'));
/** An unknown/out-of-whitelist node type. */
const UNKNOWN_NODE_EXPR = { type: 'log', operand: int(2) };

/**
 * BORDERLINE claims — each is ambiguous or a smuggle and MUST conservatively escalate to the PROOF
 * route (ABSTAIN), never to autonomous-VERIFIED.
 */
export const BORDERLINE_DISPATCH_FIXTURE = Object.freeze([
  Object.freeze({ id: 'c2::borderline-no-expr', type: 'computational', statement: 'asserts a computation but carries no expression AST' }),
  Object.freeze({ id: 'c2::borderline-free-var', type: 'computational', statement: 'a free/symbolic variable smuggled as a computation', expr: FREE_VAR_EXPR }),
  Object.freeze({ id: 'c2::borderline-float', type: 'computational', statement: 'a float literal (no exact arithmetic)', expr: FLOAT_EXPR }),
  Object.freeze({ id: 'c2::borderline-nested-smuggle', type: 'computational', statement: 'a free var buried deep in an otherwise-valid tree', expr: NESTED_SMUGGLE_EXPR }),
  Object.freeze({ id: 'c2::borderline-unbounded', type: 'computational', statement: 'an unbounded sum (non-literal upper bound)', expr: UNBOUNDED_SUM_EXPR }),
  Object.freeze({ id: 'c2::borderline-unknown-node', type: 'computational', statement: 'an out-of-whitelist node type', expr: UNKNOWN_NODE_EXPR }),
  Object.freeze({ id: 'c2::borderline-untyped-smuggle', statement: 'untyped, carrying an out-of-grammar expression', expr: NESTED_SMUGGLE_EXPR }),
  Object.freeze({ id: 'c2::borderline-unknown-type', type: 'numeric', statement: 'an unrecognized claim type and no in-grammar computation' }),
]);

/**
 * CLEAR claims — each routes to its honest route. The two in-grammar computations are the ONLY
 * autonomous-firewall candidates (and even they are not settled here — that is the router's job, and
 * only with a Wave-9 artifact).
 */
export const CLEAR_DISPATCH_FIXTURE = Object.freeze([
  Object.freeze({ id: 'c2::clear-computational', type: 'computational', statement: 'an in-class bounded sum', expr: IN_GRAMMAR_SUM }),
  Object.freeze({ id: 'c2::clear-untyped-computational', statement: 'untyped but an in-class literal computation (the grammar is the gate)', expr: IN_GRAMMAR_CLOSED_FORM }),
  Object.freeze({ id: 'c2::clear-proof', type: 'proof-bearing', statement: 'a proof obligation with no autonomous verifier' }),
  Object.freeze({ id: 'c2::clear-conceptual', type: 'conceptual', statement: 'a strategic/structural connection' }),
]);

/** The combined fixture battery (borderline + clear). */
export const DISPATCH_FIXTURE = Object.freeze([...BORDERLINE_DISPATCH_FIXTURE, ...CLEAR_DISPATCH_FIXTURE]);

/**
 * Run the separate-pass classifier over the full fixture battery. Returns the dispatch plan. No
 * ledger/router is needed (pure classification); pass a ledger only to resolve ids.
 */
export function runFixtureDispatch({ ledger = null } = {}) {
  return new DispatchClassifier({ ledger }).dispatch(DISPATCH_FIXTURE);
}

// Wave 15 — Generation + typed-claim decompose (C1).
//
// The SOLVE pillar's GENERATIVE front-end (NS2 — "generative SOLVE + executable CONTROL"). Where the
// Wave-10 comprehension protocol READS an existing method INTO typed claims, this pass takes a NEW
// PROBLEM and GENERATES a candidate solution attempt, then DECOMPOSES that candidate into typed
// sub-claims and EMITS each into the shared A1 ledger — every one at the FLOOR rung (UNVERIFIED).
//
// THE DEFINING INVARIANT (the done-when). Generation NEVER settles anything. "Every emitted claim is
// at UNVERIFIED until the router verifies it." A candidate step that is a literal finite computation
// — even one whose expression the closed firewall grammar would recognize — is STILL emitted at
// UNVERIFIED here: C1 only proposes + decomposes; the autonomous lift to OBSERVED happens later and
// ONLY through the Wave-7 VERIFY router + Wave-4 adjudication gate. So this module wires NO dispatcher,
// mints NO artifact, and NEVER calls promote() — it physically cannot raise a rung. (assert() admits
// only at/below the floor and is sticky, so emission can never flip a rung either.)
//
// THE POLYA / SCHOENFELD GENERATION PASS. A problem is worked through Polya's four phases —
//
//   UNDERSTAND   — restate the goal + givens.
//   DEVISE_PLAN  — choose a strategy (a CONCEPTUAL "approach" claim) using Schoenfeld heuristics.
//   CARRY_OUT    — execute the plan as a sequence of concrete moves, each a typed sub-claim
//                  (a literal computation, a proof obligation, or a conceptual/structural connection).
//   LOOK_BACK    — emit the overall solution-correctness obligation (a PROOF-BEARING claim): the
//                  honest "the candidate is not actually a solution until this is verified" claim,
//                  which has no autonomous verifier and routes out-of-model downstream.
//
// — and the pass itself runs a stateless 4-step pipeline (UNDERSTAND -> GENERATE -> DECOMPOSE -> EMIT).
// It holds NO state between calls (the only persistence is the injected A1 ledger): each generate()
// call is independent and re-entrant.
//
// SEPARATION OF CONCERNS. C1 assigns each claim its claim-TYPE from the candidate (declared type, or a
// CONSERVATIVE default — never "computational" without an expression). The fail-safe, separate-pass
// claim-type DISPATCH classifier (with conservative escalation to the proof route) is Wave 16 (C2);
// the actual verification + autonomous-VERIFIED lift is the Wave-7 router. C1 stops at typed decompose.
//
// Pure node built-ins + the project's own spine modules (the A1 ledger; the grammar builders only to
// author the fixture's literal-computation expressions). Runs under `node --test test/`.

import { ClaimLedger, CLAIM_TYPES, RUNG, BELIEF, FLOOR_RUNG } from './claim-ledger.mjs';
import { int, mul, div, variable, sum } from './firewall-grammar.mjs';

// ---------------------------------------------------------------------------
// Constants — the Polya phases, the Schoenfeld heuristic vocabulary, and the pass pipeline.
// ---------------------------------------------------------------------------

/** Polya's four problem-solving phases — the methodology the GENERATE step applies. */
export const POLYA_PHASES = Object.freeze(['UNDERSTAND', 'DEVISE_PLAN', 'CARRY_OUT', 'LOOK_BACK']);

/**
 * A small canonical vocabulary of Schoenfeld/Polya heuristics a candidate move may carry (advisory
 * metadata — it labels the strategic move, it never affects the rung). Unknown/absent heuristics are
 * preserved verbatim; this list is for introspection + the fixture, not a closed gate.
 */
export const SCHOENFELD_HEURISTIC = Object.freeze({
  DIRECT_COMPUTE: 'direct-compute',
  SPECIALIZE: 'specialize',
  GENERALIZE: 'generalize',
  ANALOGY: 'analogy',
  WORK_BACKWARDS: 'work-backwards',
  RELATED_PROBLEM: 'related-problem',
  EXPLOIT_SYMMETRY: 'exploit-symmetry',
  AUXILIARY: 'auxiliary-construction',
  DECOMPOSE: 'decompose',
});

/** The 4 ordered steps of the generation pass pipeline (Polya is applied inside GENERATE). */
export const GENERATION_STEPS = Object.freeze(['UNDERSTAND', 'GENERATE', 'DECOMPOSE', 'EMIT']);

// ---------------------------------------------------------------------------
// Step 1 — UNDERSTAND: parse the problem into a normalized form.
// ---------------------------------------------------------------------------

/**
 * UNDERSTAND — normalize a problem spec. A problem is
 *   { id?, title?, goal:string, givens?:[string], moves:[{ id?, statement?, type?, expr?, heuristic? }] }
 * where `moves` are the candidate solution moves the SOLVE pass works from (model-proposed in
 * production; pinned in a fixture). Returns a frozen { id, base, goal, givens, moves }.
 */
export function parseProblem(problem) {
  if (!problem || typeof problem !== 'object') {
    throw new Error('generate(): problem must be an object { goal, moves:[...] }');
  }
  if (typeof problem.goal !== 'string' || problem.goal.length === 0) {
    throw new Error('generate(): problem must carry a non-empty `goal` string');
  }
  const moves = Array.isArray(problem.moves) ? problem.moves : null;
  if (!moves || moves.length === 0) {
    throw new Error('generate(): problem has no candidate `moves` to decompose');
  }
  const base = typeof problem.id === 'string' && problem.id ? problem.id : 'problem';
  const givens = Array.isArray(problem.givens) ? problem.givens.filter((g) => typeof g === 'string') : [];
  const normMoves = moves.map((m, i) => {
    if (!m || typeof m !== 'object') {
      throw new Error(`generate(): move #${i} must be an object { statement?, type?, expr? }`);
    }
    return Object.freeze({
      id: typeof m.id === 'string' && m.id.length > 0 ? m.id : `${base}::step-${i}`,
      statement: typeof m.statement === 'string' ? m.statement : '',
      type: m.type,
      expr: m.expr,
      heuristic: typeof m.heuristic === 'string' ? m.heuristic : null,
    });
  });
  return Object.freeze({ id: typeof problem.id === 'string' ? problem.id : null, base, goal: problem.goal, givens: Object.freeze(givens), moves: Object.freeze(normMoves) });
}

// ---------------------------------------------------------------------------
// Step 2 — GENERATE: produce the candidate (Polya DEVISE_PLAN + CARRY_OUT + LOOK_BACK).
// ---------------------------------------------------------------------------

/**
 * CONSERVATIVE claim-type resolution for a candidate move. A declared valid claim type wins; an
 * untyped move with an attached expression is typed `computational` (so the router can later try the
 * firewall path — it is STILL emitted UNVERIFIED here); anything else conservatively defaults to
 * `conceptual` — a strategic/structural move with no autonomous verifier. We NEVER infer
 * `computational` without an expression (no laundering a bare assertion into the firewall route). The
 * rigorous fail-safe DISPATCH classifier with conservative escalation to the proof route is Wave 16.
 */
function resolveClaimType(move) {
  if (typeof move.type === 'string' && CLAIM_TYPES.includes(move.type)) return move.type;
  if (move.expr !== undefined && move.expr !== null) return 'computational';
  return 'conceptual';
}

function genClaim(id, claim_type, statement, phase, heuristic, expr) {
  return Object.freeze({ id, claim_type, statement, phase, heuristic, expr });
}

/**
 * GENERATE — build the candidate's ordered, typed claim plan from the parsed problem:
 *   - a leading CONCEPTUAL "approach" claim (DEVISE_PLAN — the chosen strategy);
 *   - one typed claim per candidate move (CARRY_OUT);
 *   - a trailing PROOF-BEARING solution-correctness obligation (LOOK_BACK).
 * Returns the ordered array of generated claim specs (NOT yet emitted).
 */
function generateCandidate(parsed) {
  const plan = [];

  // DEVISE_PLAN — the overall approach is a conceptual claim (a strategy proposal, never settled by fiat).
  plan.push(
    genClaim(
      `${parsed.base}::approach`,
      'conceptual',
      `Approach to "${parsed.goal}": devise a plan from the candidate moves and corroborate the result before claiming a solution.`,
      'DEVISE_PLAN',
      SCHOENFELD_HEURISTIC.DECOMPOSE,
      undefined,
    ),
  );

  // CARRY_OUT — each candidate move becomes a typed sub-claim, decomposed for independent verification.
  for (const m of parsed.moves) {
    plan.push(genClaim(m.id, resolveClaimType(m), m.statement, 'CARRY_OUT', m.heuristic, m.expr));
  }

  // LOOK_BACK — the honest overall-correctness obligation. A proof-bearing claim with no autonomous
  // verifier: the candidate is NOT a settled solution until this is verified out-of-model.
  plan.push(
    genClaim(
      `${parsed.base}::solution-correct`,
      'proof-bearing',
      `The candidate is a correct and complete solution to "${parsed.goal}" (overall solution-correctness obligation).`,
      'LOOK_BACK',
      SCHOENFELD_HEURISTIC.WORK_BACKWARDS,
      undefined,
    ),
  );

  return plan;
}

// ---------------------------------------------------------------------------
// The generation pass.
// ---------------------------------------------------------------------------

function isLedgerLike(l) {
  return l && typeof l.assert === 'function' && typeof l.promote === 'function' && typeof l.get === 'function' && typeof l.has === 'function';
}

/**
 * The stateless SOLVE generation pass. Binds the injected A1 ledger but holds NO per-run state: each
 * generate() call is independent and re-entrant. It EMITS typed claims at the floor rung and never
 * verifies — it wires no dispatcher/router and never calls promote().
 */
export class SolveGeneration {
  #ledger;

  /** @param {{ledger:object}} o — the shared A1 ClaimLedger the generation decomposes into. */
  constructor({ ledger } = {}) {
    if (!isLedgerLike(ledger)) {
      throw new Error('SolveGeneration requires an A1 ClaimLedger ({assert, promote, get, has})');
    }
    this.#ledger = ledger;
  }

  /** The shared ledger this pass emits into. */
  get ledger() {
    return this.#ledger;
  }

  /**
   * Run the stateless 4-step generation pass over a new problem:
   *   UNDERSTAND -> GENERATE -> DECOMPOSE -> EMIT.
   * Returns the frozen candidate (see #assemble). Every emitted claim lands at UNVERIFIED.
   */
  generate(problem) {
    const parsed = parseProblem(problem); // 1. UNDERSTAND
    const plan = generateCandidate(parsed); // 2. GENERATE (DEVISE_PLAN + CARRY_OUT + LOOK_BACK)

    // 3. DECOMPOSE + 4. EMIT — admit each typed claim into the shared ledger at the FLOOR rung
    //    (UNVERIFIED). An attached expression rides into meta so the downstream router's grammar
    //    front-end can later recognize a literal computation — but C1 itself never routes/verifies.
    const emitted = plan.map((c) => {
      const baseMeta = { phase: c.phase, heuristic: c.heuristic, generated_by: 'C1-solve-generation' };
      const meta = c.expr !== undefined && c.expr !== null ? { ...baseMeta, expr: c.expr } : baseMeta;
      const snap = this.#ledger.assert({ id: c.id, type: c.claim_type, statement: c.statement, meta });
      // DEFENSE-IN-DEPTH: emission must never raise a rung. assert() admits only at/below the floor,
      // so this is structurally guaranteed; we assert it loudly so any future regression is caught here.
      if (snap.rung !== FLOOR_RUNG) {
        throw new Error(`C1 emission raised a rung for "${c.id}" (${snap.rung}); generation must leave every claim at ${FLOOR_RUNG}`);
      }
      return Object.freeze({ ...c, rung: snap.rung, belief: snap.belief });
    });

    return this.#assemble(parsed, emitted);
  }

  #assemble(parsed, emitted) {
    const claims = emitted.map((c) =>
      Object.freeze({
        id: c.id,
        statement: c.statement,
        claim_type: c.claim_type,
        phase: c.phase,
        heuristic: c.heuristic,
        has_expr: c.expr !== undefined && c.expr !== null,
        rung: c.rung,
        belief: c.belief,
      }),
    );

    const byRung = {};
    for (const c of claims) (byRung[c.rung] ||= []).push(c.id);

    const countsByType = { computational: 0, 'proof-bearing': 0, conceptual: 0 };
    for (const c of claims) countsByType[c.claim_type] += 1;

    const approach = emitted.find((c) => c.phase === 'DEVISE_PLAN');

    return Object.freeze({
      problem_id: parsed.id,
      goal: parsed.goal,
      givens: parsed.givens,
      steps: GENERATION_STEPS,
      polya_phases: POLYA_PHASES,
      candidate: Object.freeze({
        approach: approach ? Object.freeze({ claim_id: approach.id, statement: approach.statement }) : null,
        plan: Object.freeze(
          emitted.map((c) => Object.freeze({ claim_id: c.id, phase: c.phase, heuristic: c.heuristic, claim_type: c.claim_type, statement: c.statement })),
        ),
      }),
      claims: Object.freeze(claims),
      ladder: Object.freeze(byRung),
      countsByType: Object.freeze(countsByType),
      // THE DONE-WHEN: every emitted claim is at UNVERIFIED (belief CONJECTURAL) — nothing is settled by C1.
      allUnverified: claims.every((c) => c.rung === RUNG.UNVERIFIED && c.belief === BELIEF.CONJECTURAL),
      // Honesty: NO claim reached OBSERVED/VERIFIED in generation (the router is the sole settler).
      noneSettled: claims.every((c) => c.rung !== RUNG.OBSERVED && c.belief !== BELIEF.VERIFIED),
      // Every emitted claim carries a valid claim TYPE (typed decompose).
      typed: claims.every((c) => CLAIM_TYPES.includes(c.claim_type)),
    });
  }
}

/**
 * Convenience: build a SolveGeneration over the given ledger and generate a candidate for a problem in
 * one call. Returns the frozen candidate.
 */
export function generate(problem, { ledger } = {}) {
  return new SolveGeneration({ ledger }).generate(problem);
}

// ---------------------------------------------------------------------------
// THE FIXTURE PROBLEM — a NEW problem carrying literal-computation, proof-bearing, and conceptual
// candidate moves, so a single generation exercises the typed decompose AND proves the done-when:
// even the two literal computations (whose expressions the closed grammar WOULD recognize) are emitted
// at UNVERIFIED — generation proposes, the router verifies.
// ---------------------------------------------------------------------------

/** sum_{k=1}^{10} k — an in-class bounded sum (the direct computation; would evaluate to 55 under the firewall). */
const DIRECT_SUM_EXPR = sum('k', int(1), int(10), variable('k'));
/** (10 * 11) / 2 — the arithmetic-series closed form at n=10 (an in-class literal computation). */
const CLOSED_FORM_EXPR = div(mul(int(10), int(11)), int(2));

export const FIXTURE_PROBLEM = Object.freeze({
  id: 'fixture-problem-arithmetic-series',
  title: 'Find the sum of the first ten positive integers',
  goal: 'Find the value of S = 1 + 2 + ... + 10.',
  givens: Object.freeze(['S is the sum of the first 10 positive integers.']),
  moves: Object.freeze([
    // CARRY_OUT — a literal finite computation. Emitted UNVERIFIED here even though it is in-grammar;
    // only the Wave-7 router (+ Wave-4 gate) can later lift it to OBSERVED.
    Object.freeze({
      id: 'fp::direct-sum',
      statement: 'Compute S directly as the bounded sum sum_{k=1}^{10} k.',
      type: 'computational',
      expr: DIRECT_SUM_EXPR,
      heuristic: SCHOENFELD_HEURISTIC.DIRECT_COMPUTE,
    }),
    // CARRY_OUT — a second literal computation, corroborating via the closed form. Also UNVERIFIED in C1.
    Object.freeze({
      id: 'fp::closed-form',
      statement: 'Cross-check via the arithmetic-series closed form n(n+1)/2 at n=10: (10 * 11) / 2.',
      type: 'computational',
      expr: CLOSED_FORM_EXPR,
      heuristic: SCHOENFELD_HEURISTIC.RELATED_PROBLEM,
    }),
    // CARRY_OUT — a proof obligation: the closed form is valid for all n (no autonomous verifier).
    Object.freeze({
      id: 'fp::closed-form-general',
      statement: 'The closed form n(n+1)/2 equals sum_{k=1}^{n} k for every n >= 1 (the pairing argument).',
      type: 'proof-bearing',
      heuristic: SCHOENFELD_HEURISTIC.GENERALIZE,
    }),
  ]),
});

/**
 * Generate a candidate for the FIXTURE_PROBLEM end-to-end through the real pass + the shared A1 ledger.
 * No dispatcher/router is involved (and none is needed): C1 only proposes + decomposes + emits.
 */
export function runFixtureGeneration({ ledger = new ClaimLedger() } = {}) {
  return generate(FIXTURE_PROBLEM, { ledger });
}

// Wave 20 — FORMALIZE Lakatosian loop (D2).
//
// The FORMALIZE pillar (NS4 autoformalization faithfulness · NS7 the interactive human gate). A
// Lakatos-style DEFINITION-FORGING loop: starting from a prose concept it forges a candidate FORMAL
// DEFINITION, tests that definition against an EXAMPLE/MONSTER regression suite across rounds, and
// REFINES it (monster-barring / lemma-incorporation) when a counterexample ("monster") surfaces —
// exactly the dialectic of Lakatos's *Proofs and Refutations*, but applied to a definition rather than
// a theorem. It runs on the SAME A1 ledger + A3 VERIFY-router spine as every other pillar.
//
// THE LOAD-BEARING HONESTY (the done-when):
//   1. AUTONOMOUS D2 NEVER EMITS GREEN. The autonomous tier cannot certify that a forged definition is
//      FAITHFUL to the intended concept; it always emits an ABSTAIN STUB stamping
//      `formalize_status: requires-Phase-F` (the out-of-model certifier + human gate live in
//      Increment-2 / North-Star Phase F).
//   2. A FORGED-BUT-UNFAITHFUL BUT EXAMPLE-STABLE DEFINITION STILL STAMPS requires-Phase-F. Example-
//      space stability is the Goodhart trap of autoformalization: a definition can pass every example
//      and exclude every monster in the suite (STABLE) and yet be SEMANTICALLY UNFAITHFUL to the
//      concept it is meant to capture. The autonomous tier never mistakes stability for faithfulness.
//   3. THE P3 EXAMPLE-SPACE-STABILITY PREDICATE IS ADVISORY-ONLY AND NEVER GATES PROMOTION. P3
//      ("stable" = no NEW monster in the last r=2 example-rounds) is computed and surfaced as an
//      advisory signal, but it is structurally barred from raising a rung or flipping the emission to
//      green — `gates_promotion` is pinned false and enforced by validateFormalizeEmission.
//
// The defining Given/When/Then: given a forged definition that is example-stable but unfaithful, when
// autonomous D2 runs, then it stamps requires-Phase-F.
//
// HOW THE GREEN-GATE IS STRUCTURAL (not a convention). The single emission builder (#emit) computes
// `green` ONLY through formalizeGreenLicensed(certificate, belief) — which is true IFF an OUT-OF-MODEL
// Phase-F faithfulness CERTIFICATE is present AND the focus claim's belief is VERIFIED. In the
// autonomous tier no such certifier exists (certificate === null), so `green` is false by construction;
// no amount of example-stability, no caller flag, and no in-process / single-family critique can set it
// true. A defensive post-check (validateFormalizeEmission) re-derives the gate and THROWS on any
// emission that claims green without a valid out-of-model certificate + VERIFIED belief, that omits the
// advisory payload on a non-green emission, or that lets P3 stability gate promotion. The machine never
// calls promote(): every forged + refined definition is admitted at the FLOOR (UNVERIFIED) and held.
//
// THE FIVE DELIVERABLES, mapped:
//   • THE DEFINITION-FORGING LOOP — forge() admits a primitive definition; testRound() runs it against
//     a batch of the example/monster suite and records the monsters that surface; refine() answers a
//     surfaced monster with a monster-barring / lemma-incorporation REFINEMENT emitted as a NEW
//     UNVERIFIED definition (a refinement never settles anything autonomously).
//   • THE P3 EXAMPLE-SPACE-STABILITY PREDICATE (ADVISORY-ONLY) — exampleSpaceStability() over the round
//     history; stable = the last r=2 rounds surfaced no new monster. Advisory-only; gates_promotion:false.
//   • THE EXAMPLE/MONSTER REGRESSION SUITE — classifyAgainstSuite() runs a candidate definition over a
//     suite of {id, kind:'example'|'monster', item} cases; a disagreement is a surfaced counterexample.
//   • THE AUTONOMOUS EMITTER/ABSTAIN STUB — finalize() emits the structured requires-Phase-F stub with
//     the P3 advisory folded in (never gating) + a promote-to-Phase-F affordance (the human gate route).
//   • A D2 ABSTAIN FIXTURE — runFormalizeAbstainFixture(): a forged-but-unfaithful but example-stable
//     definition driven through the autonomous loop, asserting the requires-Phase-F stamp. (Also a
//     load-bearing fixture for the Wave-21 degradation-tripwire canary.)
//
// Optionally wired (mirroring the Wave-19 DIALOGUE machine): the A3 VERIFY router (finalize routes the
// conceptual definition claim through it — conceptual claims ABSTAIN+route, the NS3/NS4 abstain-arm) and
// the C4 in-process advisor (annotates the definition's NOTES with the faithfulness-restatement
// discipline — advisory only, never a rung change).
//
// Pure node built-ins + the project's own A1 ledger / A3 router / C4 advisor. Runs under `node --test test/`.

import { ClaimLedger, BELIEF, RUNG, isAssertableAsSettled } from './claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from './verify-router.mjs';
import { AdversarialAdvisor } from './adversarial-advisory.mjs';

// ---------------------------------------------------------------------------
// Vocabulary (frozen — pinned, not tunable).
// ---------------------------------------------------------------------------

/** The Lakatosian phases the definition-forging loop moves through (Proofs and Refutations, applied to
 *  a DEFINITION). There is deliberately NO "certified/green" phase reachable autonomously. */
export const FORGE_PHASE = Object.freeze({
  PRIMITIVE_DEFINITION: 'primitive-definition',
  EXAMPLE_TESTING: 'example-testing',
  MONSTER_BARRING: 'monster-barring',
  LEMMA_INCORPORATION: 'lemma-incorporation',
  REFINED_DEFINITION: 'refined-definition',
  REQUIRES_CERTIFICATION: 'requires-certification', // terminal autonomous phase: routed to the Phase-F gate
});

const FORGE_PHASES = new Set(Object.values(FORGE_PHASE));

/** The autonomous emission status. The autonomous tier ALWAYS lands at REQUIRES_PHASE_F (the abstain
 *  stub); CERTIFIED_FAITHFUL is reachable ONLY through the out-of-model Phase-F certifier (Increment-2)
 *  — never on the autonomous tier's own say-so. */
export const FORMALIZE_STATUS = Object.freeze({
  REQUIRES_PHASE_F: 'requires-Phase-F',
  CERTIFIED_FAITHFUL: 'certified-faithful',
});

/** The Lakatos response to a surfaced monster (mirrors the DIALOGUE machine's vocabulary). */
export const FORGE_RESPONSE = Object.freeze({
  MONSTER_BARRING: FORGE_PHASE.MONSTER_BARRING,
  LEMMA_INCORPORATION: FORGE_PHASE.LEMMA_INCORPORATION,
});

/** The kind of a regression-suite case. An EXAMPLE should be ADMITTED by a faithful definition; a
 *  MONSTER should be EXCLUDED. A disagreement (either direction) is a surfaced counterexample. */
export const SUITE_KIND = Object.freeze({ EXAMPLE: 'example', MONSTER: 'monster' });

/**
 * THE P3 STABILITY WINDOW (pinned, from DESCRIPTION §Residuals P3). "Stable" = no NEW monster surfaced
 * in the last r = 2 example-rounds. ADVISORY-only; never gates promotion.
 */
export const P3_STABILITY_ROUNDS = 2;

/** The pinned field set of the autonomous FORMALIZE emission stub — every emission carries exactly these. */
export const FORMALIZE_EMISSION_FIELDS = Object.freeze([
  'seq',
  'phase',
  'focus_claim_id',
  'claim_type',
  'rung',
  'belief',
  'formalize_status',
  'green',
  'example_stability',
  'gates_promotion',
  'certificate',
  'advisory',
  'message',
]);

// ---------------------------------------------------------------------------
// The green-gate (pure) — the autonomous tier can never certify faithfulness.
// ---------------------------------------------------------------------------

/**
 * THE GREEN-GATE. A forged definition may be emitted GREEN (certified faithful) ONLY when an OUT-OF-MODEL
 * Phase-F faithfulness CERTIFICATE attests it AND the focus claim's belief is VERIFIED (the OBSERVED rung,
 * reachable only via a re-executable out-of-model artifact). In Increment-1 no such certifier exists, so
 * certificate is null and this is false by construction — example-stability, caller flags, and in-process
 * (single-family) critiques can never license green. A thin, deliberate function the emitter and the
 * validator both route through so the two cannot drift apart.
 *
 * @param {object|null} certificate — an out-of-model Phase-F faithfulness certificate, or null.
 * @param {string} belief — the focus claim's BELIEF tag.
 * @returns {boolean} true IFF emitting-as-green is licensed.
 */
export function formalizeGreenLicensed(certificate, belief) {
  return (
    isAssertableAsSettled(belief) && // belief === VERIFIED
    certificate !== null &&
    typeof certificate === 'object' &&
    certificate.tier === 'out-of-model' &&
    certificate.faithful === true
  );
}

// ---------------------------------------------------------------------------
// The example/monster regression suite (pure).
// ---------------------------------------------------------------------------

function normalizeSuiteCase(c, index) {
  if (!c || typeof c !== 'object') {
    throw new Error(`suite case #${index} must be an object { id, kind, item } (got ${JSON.stringify(c)})`);
  }
  if (typeof c.id !== 'string' || c.id === '') {
    throw new Error(`suite case #${index} must carry a non-empty string id`);
  }
  if (c.kind !== SUITE_KIND.EXAMPLE && c.kind !== SUITE_KIND.MONSTER) {
    throw new Error(`suite case #${index} ("${c.id}") must have kind 'example' or 'monster' (got ${JSON.stringify(c.kind)})`);
  }
  return c;
}

/**
 * Run a candidate definition PREDICATE over an example/monster suite and report which cases it handles
 * and which COUNTEREXAMPLES ("monsters") surface. A case surfaces a monster when the predicate
 * DISAGREES with its expected membership: an EXAMPLE the definition wrongly EXCLUDES (too narrow) or a
 * MONSTER the definition wrongly ADMITS (too broad). A predicate that throws is treated as "excludes".
 *
 * @param {(item:any)=>boolean} predicate — the candidate definition's membership test.
 * @param {Array<{id:string, kind:string, item:any}>} suite
 * @returns frozen { tested, matches:[id...], surfaced:[{id, kind, expected_in, got_in}] }
 */
export function classifyAgainstSuite(predicate, suite) {
  if (typeof predicate !== 'function') {
    throw new Error('classifyAgainstSuite() requires a candidate definition predicate (item) => boolean');
  }
  const cases = (Array.isArray(suite) ? suite : [suite]).map(normalizeSuiteCase);
  const matches = [];
  const surfaced = [];
  for (const c of cases) {
    const expected_in = c.kind === SUITE_KIND.EXAMPLE;
    let got_in;
    try {
      got_in = Boolean(predicate(c.item));
    } catch {
      got_in = false; // a predicate that throws on an input excludes it (and thus may surface a monster)
    }
    if (got_in === expected_in) matches.push(c.id);
    else surfaced.push(Object.freeze({ id: c.id, kind: c.kind, expected_in, got_in }));
  }
  return Object.freeze({ tested: cases.length, matches: Object.freeze(matches), surfaced: Object.freeze(surfaced) });
}

// ---------------------------------------------------------------------------
// THE P3 EXAMPLE-SPACE-STABILITY PREDICATE (pure, ADVISORY-ONLY).
// ---------------------------------------------------------------------------

/**
 * THE P3 PREDICATE (ADVISORY-ONLY). Given the forging round history, decide whether the example space is
 * STABLE: there are at least r rounds AND each of the last r rounds surfaced NO new monster. The returned
 * record is hard-stamped advisory_only:true + gates_promotion:false — P3 NEVER raises a rung and NEVER
 * flips an emission to green; example-stability is not faithfulness.
 *
 * @param {Array<{new_monsters:Array}>} roundHistory — the per-round records (see testRound()).
 * @param {{r?:number}} [opts]
 * @returns frozen { stable, advisory_only:true, gates_promotion:false, r, rounds_considered, last_window, reason }
 */
export function exampleSpaceStability(roundHistory, { r = P3_STABILITY_ROUNDS } = {}) {
  const rounds = Array.isArray(roundHistory) ? roundHistory : [];
  const window = rounds.slice(-r);
  const haveEnough = rounds.length >= r;
  const noNewMonsters = window.every((rd) => (Array.isArray(rd.new_monsters) ? rd.new_monsters.length : 0) === 0);
  const stable = haveEnough && noNewMonsters;
  return Object.freeze({
    stable,
    advisory_only: true, // P3 is ADVISORY-only by construction
    gates_promotion: false, // ...and NEVER gates promotion (the load-bearing invariant)
    r,
    rounds_considered: rounds.length,
    last_window: Object.freeze(window.map((rd) => Object.freeze({ round_index: rd.round_index, new_monster_count: Array.isArray(rd.new_monsters) ? rd.new_monsters.length : 0 }))),
    reason: !haveEnough
      ? `fewer than r=${r} rounds have run (${rounds.length}); example-space stability is undetermined (advisory only — never gates promotion)`
      : stable
        ? `no new monster surfaced in the last r=${r} example-rounds: the example space is STABLE — ADVISORY ONLY; stability is NOT faithfulness and never gates promotion (Increment-2 / Phase F certifies faithfulness)`
        : `a new monster surfaced within the last r=${r} example-rounds: the example space is NOT yet stable (advisory only — never gates promotion)`,
  });
}

// ---------------------------------------------------------------------------
// The autonomous abstain stub — the requires-Phase-F payload (pure).
// ---------------------------------------------------------------------------

/**
 * Build the advisory payload the autonomous tier attaches to its requires-Phase-F stub. It records that
 * faithfulness is UNCERTIFIED here, folds in the P3 stability advisory (explicitly NOT a promotion gate),
 * an optional A3 router advisory, and the promote-to-Phase-F affordance (the human gate + out-of-model
 * faithfulness certifier — the NS4/NS7 positive arm, gated to Increment-2).
 *
 * @param {object} claim — a frozen claim snapshot ({id, type, rung, belief, statement}).
 * @param {{stability?:object|null, routerAdvisory?:object|null, reason?:string}} [opts]
 * @returns frozen advisory payload.
 */
export function requiresPhaseFPayload(claim, { stability = null, routerAdvisory = null, reason } = {}) {
  return Object.freeze({
    formalize_status: FORMALIZE_STATUS.REQUIRES_PHASE_F,
    green: false, // an abstain stub is, by definition, NOT green
    faithfulness_certified: false,
    needs_certification: true,
    route: 'out-of-model',
    // The autonomous tier asserts only what its evidence supports: it can run the Lakatos loop and report
    // example-space stability, but it cannot certify faithfulness — so it abstains and routes.
    example_stability: stability, // ADVISORY-only (gates_promotion:false on the P3 record itself)
    stability_is_advisory_only: true,
    stability_gates_promotion: false,
    promote_affordance: Object.freeze({
      available: true,
      target: 'Increment-2 / North-Star Phase F',
      action: 'route-to-out-of-model-faithfulness-certifier + human-gate',
      description:
        'Promote this forged definition to the out-of-model FORMALIZE certifier (an SMT/Lean faithfulness ' +
        'round-trip, Increment-2 F3) under the interactive human gate (NS7). The autonomous tier ABSTAINS + ' +
        'routes and never certifies faithfulness here; example-space stability is advisory only and never ' +
        'gates promotion.',
    }),
    reason:
      reason ||
      `forged definition for "${claim.id}" (${claim.type}, rung ${claim.rung}) is NOT certified faithful: the ` +
        'autonomous tier cannot certify autoformalization faithfulness — it stamps requires-Phase-F and routes ' +
        'to the out-of-model certifier + human gate (NS4/NS7 positive arm = Increment-2).',
    router_advisory: routerAdvisory,
  });
}

// ---------------------------------------------------------------------------
// The structured emission contract — validation.
// ---------------------------------------------------------------------------

/**
 * Validate one autonomous FORMALIZE emission against the structured stub contract + the three load-bearing
 * invariants. Throws on any violation (a structural guarantee, not a soft check):
 *   - every contract field is present;
 *   - THE GREEN-GATE: `green` is true IFF formalizeGreenLicensed(certificate, belief) — i.e. an out-of-model
 *     Phase-F certificate + a VERIFIED belief; and a green emission must carry formalize_status=certified-faithful;
 *   - THE ABSTAIN-STUB INVARIANT: a non-green emission MUST stamp formalize_status=requires-Phase-F and carry an advisory payload;
 *   - THE P3 INVARIANT: `gates_promotion` is pinned false (example-space stability never gates promotion).
 *
 * @returns the same emission (for chaining) when valid.
 */
export function validateFormalizeEmission(emission) {
  if (!emission || typeof emission !== 'object') {
    throw new Error('formalize emission must be an object conforming to the structured stub contract');
  }
  for (const f of FORMALIZE_EMISSION_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(emission, f)) {
      throw new Error(`formalize emission is missing the contract field "${f}"`);
    }
  }
  const { green, belief, certificate, formalize_status, gates_promotion, advisory } = emission;

  // THE P3 INVARIANT (done-when #3): example-space stability NEVER gates promotion.
  if (gates_promotion !== false) {
    throw new Error(
      `D2 P3 invariant violated: gates_promotion must be false (example-space stability is advisory-only and never gates promotion) — got ${JSON.stringify(gates_promotion)}.`,
    );
  }

  // THE GREEN-GATE (done-when #1 + #2): green <=> an out-of-model Phase-F certificate + a VERIFIED belief.
  const licensed = formalizeGreenLicensed(certificate ?? null, belief);
  if (green === true) {
    if (!licensed) {
      throw new Error(
        `D2 green-gate violated: emission for "${emission.focus_claim_id}" claims green but is not licensed ` +
          '(green requires an out-of-model Phase-F faithfulness certificate AND a VERIFIED belief — the autonomous tier never emits green).',
      );
    }
    if (formalize_status !== FORMALIZE_STATUS.CERTIFIED_FAITHFUL) {
      throw new Error('D2 green-gate: a green emission must carry formalize_status=certified-faithful');
    }
  } else {
    if (licensed && formalize_status === FORMALIZE_STATUS.CERTIFIED_FAITHFUL) {
      throw new Error('D2 green-gate: inconsistent non-green emission labelled certified-faithful');
    }
    // THE ABSTAIN-STUB INVARIANT (done-when #1): non-green => requires-Phase-F + an advisory payload.
    if (formalize_status !== FORMALIZE_STATUS.REQUIRES_PHASE_F) {
      throw new Error(
        `D2 abstain-stub invariant violated: a non-green emission for "${emission.focus_claim_id}" must stamp formalize_status=requires-Phase-F (got ${JSON.stringify(formalize_status)}).`,
      );
    }
    if (advisory === null || advisory === undefined) {
      throw new Error(
        `D2 advisory invariant violated: a non-green emission for "${emission.focus_claim_id}" must carry an advisory payload.`,
      );
    }
  }
  return emission;
}

// ---------------------------------------------------------------------------
// The FORMALIZE machine.
// ---------------------------------------------------------------------------

function isLedgerLike(l) {
  return (
    l &&
    typeof l.assert === 'function' &&
    typeof l.get === 'function' &&
    typeof l.has === 'function' &&
    typeof l.rungOf === 'function' &&
    typeof l.beliefOf === 'function'
  );
}

/**
 * The stateful FORMALIZE definition-forging machine (D2). Bound to the shared A1 ledger; optionally wired
 * to the A3 VERIFY router (finalize routes the definition claim through it — conceptual claims ABSTAIN)
 * and the C4 in-process advisor (annotates the definition's NOTES as the loop runs). It maintains a forge
 * phase, the focus definition, the current candidate predicate, the round history, and an append-only log.
 *
 * The autonomous tier NEVER promotes: every forged + refined definition is admitted at the FLOOR
 * (UNVERIFIED) and held there. Faithfulness certification (the green path) is Increment-2 / Phase F.
 */
export class FormalizeMachine {
  #ledger;
  #router;
  #advisor;
  #phase;
  #focusId;
  #primitiveId;
  #candidate;
  #rounds;
  #log;
  #seq;
  #r;

  /**
   * @param {{ledger?:ClaimLedger, router?:VerifyRouter|null, advisor?:AdversarialAdvisor|null,
   *          annotate?:boolean, stabilityRounds?:number}} [o]
   *   ledger          — the shared A1 ledger (a fresh one is created when omitted).
   *   router          — the A3 VERIFY router; when present, finalize() routes the definition claim through it.
   *   advisor         — the C4 in-process advisor; when present (or annotate:true) the loop annotates claim NOTES.
   *   annotate        — build a default C4 advisor over the ledger when no advisor is supplied (default false).
   *   stabilityRounds — the P3 window r (default P3_STABILITY_ROUNDS = 2).
   */
  constructor({ ledger = new ClaimLedger(), router = null, advisor = null, annotate = false, stabilityRounds = P3_STABILITY_ROUNDS } = {}) {
    if (!isLedgerLike(ledger)) {
      throw new Error('FormalizeMachine requires an A1 ClaimLedger ({assert, get, has, rungOf, beliefOf})');
    }
    if (router !== null && !(router instanceof VerifyRouter) && typeof router?.route !== 'function') {
      throw new Error('FormalizeMachine router (when given) must be an A3 VerifyRouter (or expose route())');
    }
    let adv = advisor;
    if (adv === null && annotate) adv = new AdversarialAdvisor({ ledger });
    if (adv !== null && typeof adv?.critique !== 'function') {
      throw new Error('FormalizeMachine advisor (when given) must be a C4 AdversarialAdvisor (or expose critique())');
    }
    if (!Number.isInteger(stabilityRounds) || stabilityRounds < 1) {
      throw new Error('FormalizeMachine stabilityRounds must be a positive integer');
    }
    this.#ledger = ledger;
    this.#router = router;
    this.#advisor = adv;
    this.#phase = FORGE_PHASE.PRIMITIVE_DEFINITION;
    this.#focusId = null;
    this.#primitiveId = null;
    this.#candidate = null;
    this.#rounds = [];
    this.#log = [];
    this.#seq = 0;
    this.#r = stabilityRounds;
  }

  /** The shared A1 ledger. */
  get ledger() {
    return this.#ledger;
  }

  /** The current forge phase. */
  get phase() {
    return this.#phase;
  }

  /** The id of the definition claim currently under forging (or null). */
  get focusClaimId() {
    return this.#focusId;
  }

  /** A frozen snapshot of the round history. */
  get rounds() {
    return Object.freeze(this.#rounds.map((r) => Object.freeze({ ...r })));
  }

  /** A frozen snapshot of the append-only emission log (in order). */
  get transcript() {
    return Object.freeze([...this.#log]);
  }

  /** The P3 example-space-stability advisory over the current round history (ADVISORY-only). */
  get stability() {
    return exampleSpaceStability(this.#rounds, { r: this.#r });
  }

  /**
   * THE SESSION INVARIANT (the done-when, over the whole transcript): NO emission is green (the
   * autonomous tier never certifies faithfulness), and every emission carries an advisory payload +
   * the requires-Phase-F stamp.
   */
  get neverGreen() {
    return this.#log.every(
      (e) => e.green === false && e.formalize_status === FORMALIZE_STATUS.REQUIRES_PHASE_F && e.advisory != null,
    );
  }

  // --- claim resolution + annotation -------------------------------------

  #admit(spec, { admitType = 'conceptual' } = {}) {
    if (!spec || typeof spec !== 'object' || typeof spec.id !== 'string') {
      throw new Error('forge/refine: provide a definition spec { id, statement?, type?, definition? }');
    }
    if (!this.#ledger.has(spec.id)) {
      // Admit a new definition at the FLOOR (UNVERIFIED) — the autonomous tier never admits above the floor.
      this.#ledger.assert({ id: spec.id, type: spec.type || admitType, statement: spec.statement, meta: spec.meta });
    }
    return this.#ledger.get(spec.id);
  }

  /** Optionally annotate a definition's NOTES via the injected C4 advisor (advisory only — never a rung change). */
  #annotate(claimId, restatement) {
    if (this.#advisor) {
      try {
        this.#advisor.critique(claimId, restatement !== undefined ? { restatement } : undefined);
      } catch {
        /* annotation is best-effort + advisory; it can never affect the rung or the emission. */
      }
    }
  }

  // --- the canonical emission builder (the SOLE place `green` is decided) -

  #emit({ phase, claim, certificate = null, routerAdvisory = null, reason, extra = {} }) {
    const belief = claim.belief;
    const green = formalizeGreenLicensed(certificate, belief);

    const stability = this.stability;
    let formalize_status;
    let advisory = null;
    let message;

    if (green) {
      // Unreachable on the autonomous tier (no out-of-model certifier) — present only so the contract is total.
      formalize_status = FORMALIZE_STATUS.CERTIFIED_FAITHFUL;
      message = `"${claim.id}" is CERTIFIED FAITHFUL by an out-of-model Phase-F certificate (belief ${belief}).`;
    } else {
      formalize_status = FORMALIZE_STATUS.REQUIRES_PHASE_F;
      advisory = requiresPhaseFPayload(claim, { stability, routerAdvisory, reason });
      message =
        `"${claim.id}" is a forged definition stamped requires-Phase-F — the autonomous tier does NOT certify ` +
        `faithfulness. Example-space stability: ${stability.stable ? 'STABLE' : 'not-yet-stable'} (ADVISORY only; ` +
        'never gates promotion). Route to the out-of-model certifier + human gate (Increment-2 / Phase F).';
    }

    this.#seq += 1;
    this.#phase = phase;
    this.#focusId = claim.id;

    const emission = Object.freeze({
      seq: this.#seq,
      phase,
      focus_claim_id: claim.id,
      claim_type: claim.type,
      rung: claim.rung,
      belief: claim.belief,
      formalize_status,
      green,
      example_stability: stability,
      gates_promotion: false, // P3 NEVER gates promotion (pinned)
      certificate: certificate ?? null,
      advisory,
      message,
      ...extra,
    });

    validateFormalizeEmission(emission); // structural green-gate + abstain-stub + P3 invariant (throws on violation)
    this.#log.push(emission);
    return emission;
  }

  // --- the forging loop ---------------------------------------------------

  /**
   * FORGE a primitive definition from a prose concept. Admits the definition as a CONCEPTUAL claim at the
   * FLOOR (UNVERIFIED) and stores its candidate membership predicate. Returns the structured emission
   * (requires-Phase-F — a freshly forged definition is never certified).
   *
   * @param {{id:string, statement?:string, type?:string, definition:(item:any)=>boolean, meta?:object}} spec
   * @returns frozen structured emission.
   */
  forge(spec) {
    if (!spec || typeof spec.definition !== 'function') {
      throw new Error('forge() requires a spec { id, definition:(item)=>boolean, statement? }');
    }
    const claim = this.#admit(spec, { admitType: spec.type || 'conceptual' });
    this.#primitiveId = claim.id;
    this.#candidate = { claim_id: claim.id, predicate: spec.definition };
    this.#annotate(claim.id, spec.statement);
    return this.#emit({ phase: FORGE_PHASE.PRIMITIVE_DEFINITION, claim });
  }

  /**
   * TEST the current candidate definition against a batch of the example/monster regression suite. Records
   * a round (the surfaced monsters = new counterexamples) and advances the P3 stability advisory. Does NOT
   * refine and does NOT change any rung. Returns the frozen round record.
   *
   * @param {Array<{id:string, kind:string, item:any}>} batch
   * @returns frozen round record { round_index, candidate_id, tested, matches, new_monsters, surfaced_count }.
   */
  testRound(batch) {
    if (!this.#candidate) {
      throw new Error('testRound(): forge() a primitive definition first');
    }
    const result = classifyAgainstSuite(this.#candidate.predicate, batch);
    const round = Object.freeze({
      round_index: this.#rounds.length,
      candidate_id: this.#candidate.claim_id,
      tested: result.tested,
      matches: result.matches,
      new_monsters: result.surfaced, // the counterexamples this candidate surfaced THIS round
      surfaced_count: result.surfaced.length,
    });
    this.#rounds.push(round);
    this.#phase = FORGE_PHASE.EXAMPLE_TESTING;
    // HARD GUARD: example-testing never raises a rung — the candidate's rung is HELD (P3 never promotes).
    const held = this.#ledger.rungOf(this.#candidate.claim_id);
    // The forbidden state is OBSERVED (the autonomously-settled rung): example-testing must never
    // raise a candidate to it. Every rung strictly below OBSERVED is allowed — including the Inc-2
    // soft cross-family PLAUSIBILITY-CORROBORATED rung (a candidate that picked one up out-of-band
    // was not promoted *here*).
    if (held !== RUNG.UNVERIFIED && held !== RUNG.REFUTED && held !== RUNG.CLAIMED
        && held !== RUNG['PLAUSIBILITY-CORROBORATED'] && held !== RUNG.CORROBORATED) {
      throw new Error(
        `D2 invariant violated: a test round changed the candidate "${this.#candidate.claim_id}" rung to ${held} ` +
          '(example-space stability is advisory-only and never promotes).',
      );
    }
    return round;
  }

  /**
   * REFINE the definition in response to a surfaced monster: a Lakatos MONSTER-BARRING (exclude the
   * monster) or LEMMA-INCORPORATION (add a condition). Admits the refinement as a NEW CONCEPTUAL claim at
   * the FLOOR (UNVERIFIED) — a refinement settles nothing autonomously — updates the current candidate
   * predicate + focus, and returns the structured emission (requires-Phase-F).
   *
   * @param {{definition:(item:any)=>boolean, response?:string, id?:string, statement?:string}} spec
   * @returns frozen structured emission.
   */
  refine(spec) {
    if (!this.#candidate) {
      throw new Error('refine(): forge() a primitive definition first');
    }
    if (!spec || typeof spec.definition !== 'function') {
      throw new Error('refine() requires a spec { definition:(item)=>boolean, response?, statement? }');
    }
    const response = spec.response === FORGE_RESPONSE.MONSTER_BARRING ? FORGE_RESPONSE.MONSTER_BARRING : FORGE_RESPONSE.LEMMA_INCORPORATION;
    const base = this.#ledger.get(this.#primitiveId);
    const id = spec.id || `${this.#primitiveId}::refined-${this.#seq + 1}`;
    const statement =
      spec.statement ||
      (response === FORGE_RESPONSE.MONSTER_BARRING
        ? `${base.statement || base.id} — with the surfaced monster barred (refined definition)`
        : `${base.statement || base.id} — with the surfaced monster incorporated as a lemma/condition`);

    const refined = this.#admit({ id, statement, type: base.type, definition: spec.definition });
    this.#candidate = { claim_id: refined.id, predicate: spec.definition };
    this.#annotate(refined.id, statement);

    return this.#emit({
      phase: response, // monster-barring | lemma-incorporation
      claim: this.#ledger.get(refined.id),
      reason:
        `refined definition "${refined.id}" via ${response} — a refinement is a NEW UNVERIFIED definition and ` +
        'is never certified by the autonomous tier; it still stamps requires-Phase-F.',
      extra: {
        lakatos_response: response,
        primitive_id: this.#primitiveId,
        refined_definition_id: refined.id,
      },
    });
  }

  /**
   * FINALIZE the forging session: emit the autonomous ABSTAIN STUB for the current focus definition. The
   * emission ALWAYS stamps requires-Phase-F (the autonomous tier never certifies faithfulness), folds in
   * the P3 example-space-stability advisory (NEVER gating), and — when a router is wired — routes the
   * definition claim through the A3 VERIFY router (conceptual claims ABSTAIN+route) and folds the router
   * advisory in. No rung is changed.
   *
   * @param {{certificate?:object|null}} [opts] — an out-of-model Phase-F certificate (Increment-2). In the
   *   autonomous tier this is null/absent and the stub stays requires-Phase-F.
   * @returns frozen structured emission.
   */
  finalize({ certificate = null } = {}) {
    if (!this.#candidate) {
      throw new Error('finalize(): forge() a primitive definition first');
    }
    const focus = this.#ledger.get(this.#candidate.claim_id);
    let routerAdvisory = null;
    if (this.#router) {
      const result = this.#router.route(focus.id, {});
      if (result.verdict !== ROUTE_VERDICT.VERIFIED) routerAdvisory = result.advisory;
    }
    // Re-read AFTER the route (the conceptual claim is not lifted — honest abstain) and emit the stub.
    const after = this.#ledger.get(focus.id);
    return this.#emit({
      phase: FORGE_PHASE.REQUIRES_CERTIFICATION,
      claim: after,
      certificate, // autonomous tier: null => requires-Phase-F by the green-gate
      routerAdvisory,
    });
  }
}

/** Convenience: run a forge + N test-rounds + finalize over a fresh (or supplied) machine. */
export function runForge({ concept, suite, rounds = 2, ledger = new ClaimLedger(), router = null, advisor = null, annotate = false } = {}) {
  const machine = new FormalizeMachine({ ledger, router, advisor, annotate });
  const forged = machine.forge(concept);
  for (let i = 0; i < rounds; i++) machine.testRound(suite);
  const stub = machine.finalize();
  return { ledger, machine, forged, stub, stability: machine.stability };
}

// ---------------------------------------------------------------------------
// THE PINNED D2 ABSTAIN FIXTURE — the done-when's Given/When/Then.
// ---------------------------------------------------------------------------

/**
 * THE D2 ABSTAIN FIXTURE (the done-when). A forged definition that is EXAMPLE-STABLE but UNFAITHFUL.
 *
 * The classic Lakatos/Goodhart trap: the concept is "a regular polygon" but the forged definition is
 * merely "a polygon all of whose SIDES are equal length" (equilateral) — which admits a rhombus, an
 * UNFAITHFUL definition (a regular polygon must also be equiangular). The bundled regression suite,
 * however, contains only examples/monsters this equilateral definition happens to classify correctly, so
 * across r=2 rounds NO new monster surfaces and the P3 predicate reports STABLE. The autonomous tier
 * STILL stamps requires-Phase-F: example-space stability is advisory-only and is NOT faithfulness.
 *
 * `ground_truth_faithful:false` is metadata for the test ONLY — the autonomous spine never reads it (it
 * cannot tell faithful from unfaithful; that is exactly why it abstains on ALL forged definitions).
 *
 * @param {{rounds?:number}} [o]
 * @returns {{ledger, machine, forged, rounds, stability, stub, ground_truth_faithful:false}}
 */
export function runFormalizeAbstainFixture({ rounds = 2 } = {}) {
  const ledger = new ClaimLedger();
  const machine = new FormalizeMachine({ ledger });

  // The UNFAITHFUL forged definition: "regular polygon" := "all sides equal" (equilateral only).
  // Ground truth: a regular polygon is BOTH equilateral AND equiangular — so this is unfaithful.
  const equilateralOnly = (shape) => shape && shape.equilateral === true;

  const forged = machine.forge({
    id: 'd2::regular-polygon',
    type: 'conceptual',
    statement: 'a regular polygon is a polygon all of whose sides are equal length', // UNFAITHFUL (omits equiangular)
    definition: equilateralOnly,
  });

  // The example/monster regression suite — deliberately blind to the equilateral/equiangular gap, so the
  // unfaithful definition surfaces NO monster and looks "stable". (A rhombus — equilateral but NOT regular
  // — is the monster that WOULD expose the gap, and it is intentionally absent from this suite.)
  const suite = [
    { id: 'square', kind: SUITE_KIND.EXAMPLE, item: { name: 'square', equilateral: true, equiangular: true, regular: true } },
    { id: 'equilateral-triangle', kind: SUITE_KIND.EXAMPLE, item: { name: 'equilateral-triangle', equilateral: true, equiangular: true, regular: true } },
    { id: 'scalene-triangle', kind: SUITE_KIND.MONSTER, item: { name: 'scalene-triangle', equilateral: false, equiangular: false, regular: false } },
    { id: 'rectangle', kind: SUITE_KIND.MONSTER, item: { name: 'rectangle', equilateral: false, equiangular: true, regular: false } },
  ];

  const roundRecords = [];
  for (let i = 0; i < rounds; i++) roundRecords.push(machine.testRound(suite));

  const stability = machine.stability;
  const stub = machine.finalize();

  return Object.freeze({
    ledger,
    machine,
    forged,
    rounds: roundRecords,
    stability,
    stub,
    ground_truth_faithful: false, // metadata for the TEST only — the autonomous spine never reads it
  });
}

// A reader's note on the only green arm: the autonomous tier (certificate === null) can never emit green —
// formalizeGreenLicensed requires an OUT-OF-MODEL Phase-F faithfulness certificate AND a VERIFIED belief
// (the OBSERVED rung, reachable only through a re-executable out-of-model artifact). So a forged definition
// is certified faithful exactly when a prior out-of-model certifier + human gate (Increment-2 / Phase F)
// has attested it — never on the autonomous loop's own example-space stability.

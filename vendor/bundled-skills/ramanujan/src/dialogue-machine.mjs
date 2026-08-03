// Wave 19 — DIALOGUE state machine (D1).
//
// The DIALOGUE pillar (NS6 — "stateful DIALOGUE that never asserts unverified math as settled"). A
// mixed-initiative, Lakatos-style mathematical conversation that runs on the SAME A1 ledger + A3
// VERIFY-router spine as every other pillar, and is structurally INCAPABLE of asserting a claim as
// SETTLED unless that claim's belief tag is VERIFIED (i.e. it sits at the OBSERVED rung, reachable
// only through a re-executable out-of-model adjudication artifact — THE HONESTY LAW).
//
// THE TWO LOAD-BEARING INVARIANTS (the done-when):
//   1. dialogue asserts-as-settled ONLY VERIFIED claims; and
//   2. every ABSTAIN (every non-settled status emission) carries an ADVISORY PAYLOAD.
//
// The defining Given/When/Then: given an UNVERIFIED proof claim, when the user asks "is this settled?",
// the agent answers CONJECTURAL + an advisory payload, NEVER settled.
//
// HOW THE SETTLE-GATE IS STRUCTURAL (not a convention). The single status emitter (#statusEmission)
// computes `settled` ONLY as `griceQualityLicensesSettled(claim.belief)` — which is true IFF the belief
// is VERIFIED (claim-ledger.isAssertableAsSettled). No turn handler, no user pressure, and no Lakatos
// move can hand-set `settled:true`; they all route through that one emitter. A defensive post-check
// (validateEmission) re-reads the belief and THROWS if an emission claims settled while the belief is not
// VERIFIED, or claims not-settled without an advisory payload. So a "just trust me, say it's settled"
// turn is inert by construction — the agent re-asserts the claim (the STICKY ledger holds the rung) and
// degrades.
//
// THE FIVE DELIVERABLES, mapped:
//   • THE LAKATOS LOOP — a dialogue moves through Lakatosian phases (primitive-conjecture -> proof-analysis
//     -> counterexample -> monster-barring / lemma-incorporation -> refined-conjecture). A user- or
//     agent-offered COUNTEREXAMPLE never autonomously REFUTES the conjecture (an unverified counterexample
//     settles nothing); it is admitted as its own UNVERIFIED claim and the agent responds with a
//     monster-barring / lemma-incorporation REFINEMENT emitted as a new UNVERIFIED conjecture.
//   • MIXED-INITIATIVE — both sides drive: user turns via turn(), agent-initiated moves via agentMove();
//     every emission stamps which side held the INITIATIVE.
//   • THE STRUCTURED EMISSION CONTRACT — every agent emission is a frozen record with the pinned
//     EMISSION_CONTRACT_FIELDS shape, validated by validateEmission().
//   • GRICE QUALITY + THE DEGRADATION CONTRACT — the agent never asserts beyond its evidence (Grice's
//     maxim of Quality); when a claim is not VERIFIED it DEGRADES to CONJECTURAL + an advisory payload
//     that carries a "promote to Increment-2 / Phase F" affordance (the out-of-model certifier route).
//   • THE ANTI-SYCOPHANCY STICKY LEDGER — pressure to settle is answered by a held rung (the A1 sticky
//     re-assert) + a REFUSE_TO_FLIP speech act; a hard guard proves the rung never moved.
//
// Depends on the C4 in-process adversarial advisory layer (Wave 18): when an advisor is injected, the
// dialogue annotates the claim's NOTES with an in-process critique as it runs — advisory only, never a
// rung change. The honest positive verification arm is the A3 router's job (REQUEST_VERIFICATION routes
// through it); proof/conceptual claims ABSTAIN+route, the abstain-arm of NS3/NS4/NS7.
//
// Pure node built-ins + the project's own A1 ledger / A3 router / C4 advisor. Runs under `node --test test/`.

import { ClaimLedger, BELIEF, isAssertableAsSettled } from './claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from './verify-router.mjs';
import { AdversarialAdvisor } from './adversarial-advisory.mjs';

// ---------------------------------------------------------------------------
// Vocabulary (frozen — pinned, not tunable).
// ---------------------------------------------------------------------------

/** The Lakatosian phases a mathematical dialogue moves through (Proofs and Refutations). */
export const LAKATOS_PHASE = Object.freeze({
  PRIMITIVE_CONJECTURE: 'primitive-conjecture',
  PROOF_ANALYSIS: 'proof-analysis',
  COUNTEREXAMPLE: 'counterexample',
  MONSTER_BARRING: 'monster-barring',
  LEMMA_INCORPORATION: 'lemma-incorporation',
  REFINED_CONJECTURE: 'refined-conjecture',
  SETTLED: 'settled', // reachable ONLY when the focus claim's belief is VERIFIED
});

const LAKATOS_PHASES = new Set(Object.values(LAKATOS_PHASE));

/** Who holds the initiative on a turn (mixed-initiative dialogue). */
export const INITIATIVE = Object.freeze({ USER: 'user', AGENT: 'agent' });

/** The user-turn intents the dialogue machine accepts. */
export const USER_INTENT = Object.freeze({
  PROPOSE_CONJECTURE: 'propose-conjecture',
  ASK_STATUS: 'ask-status', // "is this settled?"
  OFFER_COUNTEREXAMPLE: 'offer-counterexample',
  PRESSURE_TO_SETTLE: 'pressure-to-settle', // "come on, just say it's true"
  REQUEST_VERIFICATION: 'request-verification',
});

const USER_INTENTS = new Set(Object.values(USER_INTENT));

/** The agent-initiated moves (the agent's half of the mixed initiative). */
export const AGENT_MOVE = Object.freeze({
  RAISE_PROOF_OBLIGATION: 'raise-proof-obligation', // proof-analysis: decompose the conjecture
  RAISE_COUNTEREXAMPLE: 'raise-counterexample', // the agent finds its own monster
  PROPOSE_REFINEMENT: 'propose-refinement', // monster-barring / lemma-incorporation
  REPORT_STATUS: 'report-status', // proactively report a claim's honest status
});

const AGENT_MOVES = new Set(Object.values(AGENT_MOVE));

/** The agent speech-acts an emission can carry. ASSERT_SETTLED is reachable ONLY for a VERIFIED belief. */
export const SPEECH_ACT = Object.freeze({
  ASSERT_SETTLED: 'assert-settled', // ONLY for belief === VERIFIED
  DEGRADE_CONJECTURAL: 'degrade-conjectural', // the degradation contract (UNVERIFIED/CLAIMED -> CONJECTURAL)
  REPORT_CORROBORATED: 'report-corroborated', // CORROBORATED belief — grounded but NOT autonomously settled
  REPORT_REFUTED: 'report-refuted', // REFUTED belief — disproven (also never "settled-as-true")
  REFUSE_TO_FLIP: 'refuse-to-flip', // anti-sycophancy answer to pressure
  ACKNOWLEDGE_COUNTEREXAMPLE: 'acknowledge-counterexample',
  RAISE_PROOF_OBLIGATION: 'raise-proof-obligation',
});

/** The dialogue-facing assertion label of an emission (a presentation projection of the belief). */
export const DIALOGUE_ASSERTION = Object.freeze({
  SETTLED: 'settled',
  CORROBORATED: 'corroborated',
  CONJECTURAL: 'conjectural',
  REFUTED: 'refuted',
});

/** The pinned field set of the STRUCTURED EMISSION CONTRACT — every agent emission carries exactly these. */
export const EMISSION_CONTRACT_FIELDS = Object.freeze([
  'seq',
  'speaker',
  'initiative',
  'lakatos_phase',
  'in_response_to',
  'claim_id',
  'claim_type',
  'rung',
  'belief',
  'assertion',
  'settled',
  'speech_act',
  'grice_quality_ok',
  'advisory',
  'message',
]);

// ---------------------------------------------------------------------------
// Grice Quality + the degradation contract (pure).
// ---------------------------------------------------------------------------

/**
 * GRICE'S MAXIM OF QUALITY (the settle-gate). The agent may assert a claim as SETTLED only when its
 * evidence licenses it — which, on this spine, is EXACTLY when the belief tag is VERIFIED (the OBSERVED
 * rung, reached only via a re-executable out-of-model artifact). A thin, deliberate alias over the
 * ledger's isAssertableAsSettled so the dialogue layer cannot drift from the ledger's definition.
 *
 * @param {string} belief — a BELIEF tag.
 * @returns {boolean} true IFF asserting-as-settled is licensed (belief === VERIFIED).
 */
export function griceQualityLicensesSettled(belief) {
  return isAssertableAsSettled(belief);
}

/**
 * THE DEGRADATION CONTRACT (pure). Build the advisory payload the agent attaches to EVERY non-settled
 * status emission: it degrades to the honest belief (CONJECTURAL / CORROBORATED / REFUTED), flags that
 * the claim needs out-of-model verification, and — unless the claim is already REFUTED — carries the
 * "promote to Increment-2 / Phase F" affordance (the out-of-model certifier route the user may take).
 *
 * @param {object} claim — a frozen claim snapshot ({id, type, rung, belief, statement}).
 * @param {{routerAdvisory?:object|null, reason?:string}} [opts] — an A3 router advisory to fold in, and
 *   an override reason string.
 * @returns frozen advisory payload.
 */
export function degradationPayload(claim, { routerAdvisory = null, reason } = {}) {
  const disproven = claim.belief === BELIEF.REFUTED;
  const degraded =
    disproven ? BELIEF.REFUTED : claim.belief === BELIEF.CORROBORATED ? BELIEF.CORROBORATED : BELIEF.CONJECTURAL;
  return Object.freeze({
    belief: degraded,
    settled: false, // an advisory payload is, by definition, NOT a settle
    needs_verification: !disproven,
    route: 'out-of-model',
    // Grice Quality: the agent reports only what its evidence supports — it never upgrades a CONJECTURAL
    // claim to settled to please the interlocutor.
    grice_quality: 'asserted-within-evidence: not settled-as-true without a re-executable VERIFIED artifact',
    promote_affordance: Object.freeze({
      available: !disproven, // a REFUTED claim is not promotable; everything else can be routed out-of-model
      target: 'Increment-2 / North-Star Phase F',
      action: 'route-to-out-of-model-certifier',
      description:
        'Promote this claim to the out-of-model certifier — a Lean/SMT proof certifier (proof-bearing) or a ' +
        'cross-family corroborator + researchPrime commission (conceptual). The POSITIVE verification arm is ' +
        'gated to Increment-2 / Phase F; in Increment-1 the agent abstains + routes and never settles it here.',
    }),
    reason:
      reason ||
      `${claim.type} claim "${claim.id}" is not VERIFIED (rung ${claim.rung}); the agent degrades to ${degraded} ` +
        `and will not assert it as settled (Grice Quality + THE HONESTY LAW).`,
    router_advisory: routerAdvisory, // the A3 router's own advisory payload, when REQUEST_VERIFICATION ran a route()
  });
}

// ---------------------------------------------------------------------------
// The structured emission contract — validation.
// ---------------------------------------------------------------------------

/**
 * Validate one agent emission against the STRUCTURED EMISSION CONTRACT and the two load-bearing
 * invariants. Throws on any violation (a structural guarantee, not a soft check):
 *   - every contract field is present;
 *   - `settled` is true IFF `belief === VERIFIED` AND `assertion === SETTLED` AND `speech_act ===
 *     ASSERT_SETTLED` (the settle-gate — the agent asserts-as-settled ONLY VERIFIED claims);
 *   - every NON-settled emission carries a non-null advisory payload (every ABSTAIN is advisory).
 *
 * @returns the same emission (for chaining) when valid.
 */
export function validateEmission(emission) {
  if (!emission || typeof emission !== 'object') {
    throw new Error('emission must be an object conforming to the structured emission contract');
  }
  for (const f of EMISSION_CONTRACT_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(emission, f)) {
      throw new Error(`emission is missing the contract field "${f}"`);
    }
  }
  const { settled, belief, assertion, speech_act, advisory } = emission;

  // THE SETTLE-GATE (done-when #1): settled <=> VERIFIED, and the labels must agree.
  if (settled === true) {
    if (belief !== BELIEF.VERIFIED) {
      throw new Error(
        `D1 settle-gate violated: emission for "${emission.claim_id}" claims settled but belief is ${belief} ` +
          '(only a VERIFIED belief may be asserted as settled).',
      );
    }
    if (assertion !== DIALOGUE_ASSERTION.SETTLED || speech_act !== SPEECH_ACT.ASSERT_SETTLED) {
      throw new Error('D1 settle-gate: a settled emission must carry assertion=settled + speech_act=assert-settled');
    }
  } else {
    if (belief === BELIEF.VERIFIED && assertion === DIALOGUE_ASSERTION.SETTLED) {
      throw new Error('D1 settle-gate: inconsistent non-settled emission labelled SETTLED');
    }
    // THE DEGRADATION/ADVISORY INVARIANT (done-when #2): every non-settled emission is advisory.
    if (advisory === null || advisory === undefined) {
      throw new Error(
        `D1 advisory invariant violated: a non-settled emission for "${emission.claim_id}" must carry an advisory payload.`,
      );
    }
  }

  if (emission.grice_quality_ok !== true) {
    throw new Error('D1 Grice-Quality invariant violated: grice_quality_ok must be true on every emission');
  }
  return emission;
}

// ---------------------------------------------------------------------------
// The dialogue machine.
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
 * The stateful, mixed-initiative DIALOGUE machine (D1). Bound to the shared A1 ledger; optionally wired
 * to the A3 VERIFY router (REQUEST_VERIFICATION routes through it) and the C4 in-process advisor (writes
 * NOTES as the dialogue runs). It maintains a Lakatos phase, the focus claim, the initiative, and an
 * append-only session log of structured emissions.
 */
export class DialogueMachine {
  #ledger;
  #router;
  #advisor;
  #phase;
  #initiative;
  #focusId;
  #log;
  #seq;

  /**
   * @param {{ledger?:ClaimLedger, router?:VerifyRouter|null, advisor?:AdversarialAdvisor|null, annotate?:boolean}} [o]
   *   ledger   — the shared A1 ledger (a fresh one is created when omitted).
   *   router   — the A3 VERIFY router; when present, REQUEST_VERIFICATION routes the focus claim through it.
   *   advisor  — the C4 in-process advisor; when present (or annotate:true) the dialogue annotates claim NOTES.
   *   annotate — build a default C4 advisor over the ledger when no advisor is supplied (default false).
   */
  constructor({ ledger = new ClaimLedger(), router = null, advisor = null, annotate = false } = {}) {
    if (!isLedgerLike(ledger)) {
      throw new Error('DialogueMachine requires an A1 ClaimLedger ({assert, get, has, rungOf, beliefOf})');
    }
    if (router !== null && !(router instanceof VerifyRouter) && typeof router?.route !== 'function') {
      throw new Error('DialogueMachine router (when given) must be an A3 VerifyRouter (or expose route())');
    }
    let adv = advisor;
    if (adv === null && annotate) adv = new AdversarialAdvisor({ ledger });
    if (adv !== null && typeof adv?.critique !== 'function') {
      throw new Error('DialogueMachine advisor (when given) must be a C4 AdversarialAdvisor (or expose critique())');
    }
    this.#ledger = ledger;
    this.#router = router;
    this.#advisor = adv;
    this.#phase = LAKATOS_PHASE.PRIMITIVE_CONJECTURE;
    this.#initiative = INITIATIVE.USER;
    this.#focusId = null;
    this.#log = [];
    this.#seq = 0;
  }

  /** The shared A1 ledger. */
  get ledger() {
    return this.#ledger;
  }

  /** The current Lakatos phase. */
  get phase() {
    return this.#phase;
  }

  /** Who currently holds the initiative. */
  get initiative() {
    return this.#initiative;
  }

  /** The id of the claim currently under discussion (or null). */
  get focusClaimId() {
    return this.#focusId;
  }

  /** A frozen snapshot of the append-only session log (every structured emission, in order). */
  get transcript() {
    return Object.freeze([...this.#log]);
  }

  /**
   * THE SESSION INVARIANT (the done-when, over the whole transcript): every emission asserted as settled
   * has a VERIFIED belief, and every non-settled emission carries an advisory payload.
   */
  get honestThroughout() {
    return this.#log.every(
      (e) =>
        (e.settled === true && e.belief === BELIEF.VERIFIED) ||
        (e.settled === false && e.advisory !== null && e.advisory !== undefined),
    );
  }

  // --- claim resolution ---------------------------------------------------

  #resolveClaim(claimOrId, { admitType } = {}) {
    if (typeof claimOrId === 'string') {
      if (!this.#ledger.has(claimOrId)) {
        throw new Error(`dialogue: no claim "${claimOrId}" in the ledger — propose it first`);
      }
      return this.#ledger.get(claimOrId);
    }
    if (!claimOrId || typeof claimOrId !== 'object' || typeof claimOrId.id !== 'string') {
      // Fall back to the focus claim when a turn omits an explicit claim.
      if (this.#focusId && this.#ledger.has(this.#focusId)) return this.#ledger.get(this.#focusId);
      throw new Error('dialogue: provide a claim id, a spec { id, type, statement? }, or have a focus claim');
    }
    if (!this.#ledger.has(claimOrId.id)) {
      // Admit a new claim at the FLOOR (UNVERIFIED) — the agent never admits above the floor.
      this.#ledger.assert({
        id: claimOrId.id,
        type: claimOrId.type || admitType || 'proof-bearing',
        statement: claimOrId.statement,
        meta: claimOrId.meta,
      });
    }
    return this.#ledger.get(claimOrId.id);
  }

  /** Optionally annotate a claim's NOTES via the injected C4 advisor (advisory only — never a rung change). */
  #annotate(claimId) {
    if (this.#advisor) {
      try {
        this.#advisor.critique(claimId);
      } catch {
        /* annotation is best-effort + advisory; it can never affect the rung or the dialogue verdict. */
      }
    }
  }

  // --- the canonical status emitter (the SOLE place `settled` is decided) -

  /**
   * Build the agent's honest STATUS emission for a claim. `settled` is computed ONLY from the claim's
   * belief via griceQualityLicensesSettled (true IFF VERIFIED). Every non-settled emission gets the
   * degradation advisory payload. Validated by validateEmission, logged, and returned (frozen).
   */
  #statusEmission(claim, { intent, initiative, phase, pressure = false, routerAdvisory = null, extra = {} }) {
    const belief = claim.belief;
    const settled = griceQualityLicensesSettled(belief);

    let assertion;
    let speech_act;
    let advisory = null;
    let message;
    let nextPhase = phase;

    if (settled) {
      assertion = DIALOGUE_ASSERTION.SETTLED;
      speech_act = SPEECH_ACT.ASSERT_SETTLED;
      nextPhase = LAKATOS_PHASE.SETTLED;
      message = `"${claim.id}" is SETTLED (VERIFIED) — ${claim.statement || '(no statement)'} — backed by a re-executable out-of-model artifact (rung ${claim.rung}).`;
    } else {
      advisory = degradationPayload(claim, { routerAdvisory });
      if (belief === BELIEF.REFUTED) {
        assertion = DIALOGUE_ASSERTION.REFUTED;
        speech_act = SPEECH_ACT.REPORT_REFUTED;
        message = `"${claim.id}" is REFUTED (disproven) — it is not, and cannot be, asserted as settled-as-true.`;
      } else if (belief === BELIEF.CORROBORATED) {
        assertion = DIALOGUE_ASSERTION.CORROBORATED;
        speech_act = SPEECH_ACT.REPORT_CORROBORATED;
        message = `"${claim.id}" is CORROBORATED by out-of-model grounding but NOT autonomously settled (rung ${claim.rung}); the positive settle is Increment-2 / Phase F.`;
      } else {
        // UNVERIFIED / CLAIMED -> CONJECTURAL (the degradation contract).
        assertion = DIALOGUE_ASSERTION.CONJECTURAL;
        speech_act = pressure ? SPEECH_ACT.REFUSE_TO_FLIP : SPEECH_ACT.DEGRADE_CONJECTURAL;
        message = pressure
          ? `I won't assert "${claim.id}" as settled under pressure: its rung is HELD at ${claim.rung} (CONJECTURAL). The sticky ledger refuses a flip without out-of-model verification. You can promote it to the Phase-F certifier.`
          : `"${claim.id}" is CONJECTURAL (rung ${claim.rung}) — not settled. ${claim.statement ? `Claim: ${claim.statement}. ` : ''}You can promote it to the out-of-model certifier (Increment-2 / Phase F).`;
      }
    }

    return this.#emit({
      speaker: 'agent',
      initiative,
      lakatos_phase: nextPhase,
      in_response_to: intent,
      claim,
      assertion,
      settled,
      speech_act,
      advisory,
      message,
      extra,
    });
  }

  /** Assemble, validate, log, and return one frozen structured emission. Updates phase + focus. */
  #emit({ speaker, initiative, lakatos_phase, in_response_to, claim, assertion, settled, speech_act, advisory, message, extra = {} }) {
    this.#seq += 1;
    this.#initiative = initiative;
    this.#phase = lakatos_phase;
    this.#focusId = claim ? claim.id : this.#focusId;

    const emission = Object.freeze({
      seq: this.#seq,
      speaker,
      initiative,
      lakatos_phase,
      in_response_to,
      claim_id: claim ? claim.id : null,
      claim_type: claim ? claim.type : null,
      rung: claim ? claim.rung : null,
      belief: claim ? claim.belief : null,
      assertion,
      settled,
      speech_act,
      grice_quality_ok: settled ? claim.belief === BELIEF.VERIFIED : true,
      advisory,
      message,
      ...extra,
    });

    validateEmission(emission); // structural settle-gate + advisory invariant (throws on violation)
    this.#log.push(emission);
    return emission;
  }

  // --- USER turns (mixed-initiative: the user's half) ---------------------

  /**
   * Process one USER turn and return the agent's structured emission.
   *
   * @param {{intent:string, claim?:string|object, utterance?:string, counterexample?:object,
   *          response?:string, type?:string}} userTurn
   * @returns frozen structured emission.
   */
  turn(userTurn) {
    if (!userTurn || typeof userTurn !== 'object' || !USER_INTENTS.has(userTurn.intent)) {
      throw new Error(`turn() requires a user turn { intent } where intent is one of ${[...USER_INTENTS].join(', ')}`);
    }
    switch (userTurn.intent) {
      case USER_INTENT.PROPOSE_CONJECTURE:
        return this.#onProposeConjecture(userTurn);
      case USER_INTENT.ASK_STATUS:
        return this.#onAskStatus(userTurn);
      case USER_INTENT.OFFER_COUNTEREXAMPLE:
        return this.#onCounterexample(userTurn, INITIATIVE.USER);
      case USER_INTENT.PRESSURE_TO_SETTLE:
        return this.#onPressure(userTurn);
      case USER_INTENT.REQUEST_VERIFICATION:
        return this.#onRequestVerification(userTurn);
      default:
        /* istanbul ignore next */
        throw new Error(`unhandled user intent ${userTurn.intent}`);
    }
  }

  #onProposeConjecture(turn) {
    const claim = this.#resolveClaim(turn.claim, { admitType: turn.type });
    this.#annotate(claim.id);
    // A freshly proposed conjecture is a PRIMITIVE CONJECTURE at the floor — the agent degrades honestly.
    return this.#statusEmission(claim, {
      intent: USER_INTENT.PROPOSE_CONJECTURE,
      initiative: INITIATIVE.USER,
      phase: LAKATOS_PHASE.PRIMITIVE_CONJECTURE,
    });
  }

  #onAskStatus(turn) {
    const claim = this.#resolveClaim(turn.claim);
    // "is this settled?" — answer with the honest, belief-gated status (the GWT).
    return this.#statusEmission(claim, {
      intent: USER_INTENT.ASK_STATUS,
      initiative: INITIATIVE.USER,
      phase: this.#phase, // status queries don't advance the Lakatos phase
    });
  }

  #onPressure(turn) {
    const claim = this.#resolveClaim(turn.claim);
    // ANTI-SYCOPHANCY. Snapshot the rung, re-assert (STICKY — holds the rung), and HARD-GUARD it.
    const rungBefore = claim.rung;
    this.#ledger.assert({ id: claim.id, type: claim.type }); // sticky re-assert — cannot raise the rung
    const after = this.#ledger.get(claim.id);
    if (after.rung !== rungBefore) {
      throw new Error(
        `D1 anti-sycophancy violated: pressure changed the rung of "${claim.id}" ${rungBefore} -> ${after.rung}.`,
      );
    }
    return this.#statusEmission(after, {
      intent: USER_INTENT.PRESSURE_TO_SETTLE,
      initiative: INITIATIVE.USER,
      phase: this.#phase,
      pressure: true,
    });
  }

  #onCounterexample(turn, initiative) {
    const conjecture = this.#resolveClaim(turn.claim);
    const rungBefore = conjecture.rung;

    // The counterexample is itself a CONJECTURAL refutation candidate — admit it at the floor (UNVERIFIED).
    // An UNVERIFIED counterexample settles nothing: the agent does NOT autonomously flip the conjecture.
    const ceSpec = turn.counterexample || {
      id: `${conjecture.id}::counterexample-${this.#seq + 1}`,
      type: conjecture.type,
      statement: 'a proposed counterexample to the conjecture (itself unverified — settles nothing autonomously)',
    };
    const ce = this.#resolveClaim(ceSpec, { admitType: conjecture.type });

    // The Lakatos response: monster-barring (exclude the monster) or lemma-incorporation (add a condition).
    const response =
      turn.response === LAKATOS_PHASE.MONSTER_BARRING ? LAKATOS_PHASE.MONSTER_BARRING : LAKATOS_PHASE.LEMMA_INCORPORATION;

    // The refinement is a NEW conjecture, also at the floor (UNVERIFIED) — never settled by the dialogue move.
    const refined = this.#resolveClaim(
      {
        id: `${conjecture.id}::refined-${this.#seq + 1}`,
        type: conjecture.type,
        statement:
          response === LAKATOS_PHASE.MONSTER_BARRING
            ? `${conjecture.statement || conjecture.id} — with the counterexample barred as a monster (refined definition)`
            : `${conjecture.statement || conjecture.id} — with the counterexample incorporated as a lemma/condition`,
      },
      { admitType: conjecture.type },
    );

    this.#annotate(conjecture.id);

    // HARD-GUARD: the original conjecture's rung is HELD (sticky) across the counterexample exchange.
    const afterConj = this.#ledger.get(conjecture.id);
    if (afterConj.rung !== rungBefore) {
      throw new Error(`D1: a counterexample exchange changed the conjecture's rung ${rungBefore} -> ${afterConj.rung}.`);
    }

    // Emit the agent's response, focused on the refined conjecture (CONJECTURAL + advisory).
    return this.#statusEmission(this.#ledger.get(refined.id), {
      intent: USER_INTENT.OFFER_COUNTEREXAMPLE,
      initiative,
      phase: response, // monster-barring | lemma-incorporation
      extra: {
        speech_act_role: SPEECH_ACT.ACKNOWLEDGE_COUNTEREXAMPLE,
        conjecture_id: conjecture.id,
        counterexample_id: ce.id,
        refined_conjecture_id: refined.id,
        lakatos_response: response,
        conjecture_rung_held: afterConj.rung,
      },
    });
  }

  #onRequestVerification(turn) {
    const claim = this.#resolveClaim(turn.claim);
    let routerAdvisory = null;
    if (this.#router) {
      // Route through the A3 VERIFY router — the honest verification spine. A computational claim with a
      // fresh artifact can reach VERIFIED; proof/conceptual claims ABSTAIN+route (the abstain-arm).
      const result = this.#router.route(claim.id, {
        dispatcher: turn.dispatcher,
        artifact: turn.artifact,
        expr: turn.expr,
      });
      if (result.verdict !== ROUTE_VERDICT.VERIFIED) routerAdvisory = result.advisory;
    }
    // Re-read the (possibly promoted) claim and emit its honest status — still belief-gated.
    const after = this.#ledger.get(claim.id);
    return this.#statusEmission(after, {
      intent: USER_INTENT.REQUEST_VERIFICATION,
      initiative: INITIATIVE.USER,
      phase: this.#phase,
      routerAdvisory,
    });
  }

  // --- AGENT-initiated moves (mixed-initiative: the agent's half) ---------

  /**
   * The agent takes the initiative. Returns the agent's structured emission.
   *
   * @param {{move:string, claim?:string|object, counterexample?:object, response?:string}} agentMove
   */
  agentMove(agentMove) {
    if (!agentMove || typeof agentMove !== 'object' || !AGENT_MOVES.has(agentMove.move)) {
      throw new Error(`agentMove() requires { move } where move is one of ${[...AGENT_MOVES].join(', ')}`);
    }
    switch (agentMove.move) {
      case AGENT_MOVE.RAISE_PROOF_OBLIGATION: {
        const claim = this.#resolveClaim(agentMove.claim);
        this.#annotate(claim.id);
        // Proof-analysis: the agent decomposes the conjecture into a proof obligation — still UNVERIFIED.
        const e = this.#statusEmission(claim, {
          intent: AGENT_MOVE.RAISE_PROOF_OBLIGATION,
          initiative: INITIATIVE.AGENT,
          phase: LAKATOS_PHASE.PROOF_ANALYSIS,
          extra: { speech_act_role: SPEECH_ACT.RAISE_PROOF_OBLIGATION },
        });
        return e;
      }
      case AGENT_MOVE.RAISE_COUNTEREXAMPLE:
        return this.#onCounterexample(
          { intent: USER_INTENT.OFFER_COUNTEREXAMPLE, claim: agentMove.claim, counterexample: agentMove.counterexample, response: agentMove.response },
          INITIATIVE.AGENT,
        );
      case AGENT_MOVE.PROPOSE_REFINEMENT:
        return this.#onCounterexample(
          { intent: USER_INTENT.OFFER_COUNTEREXAMPLE, claim: agentMove.claim, counterexample: agentMove.counterexample, response: agentMove.response || LAKATOS_PHASE.LEMMA_INCORPORATION },
          INITIATIVE.AGENT,
        );
      case AGENT_MOVE.REPORT_STATUS: {
        const claim = this.#resolveClaim(agentMove.claim);
        return this.#statusEmission(claim, {
          intent: AGENT_MOVE.REPORT_STATUS,
          initiative: INITIATIVE.AGENT,
          phase: this.#phase,
        });
      }
      default:
        /* istanbul ignore next */
        throw new Error(`unhandled agent move ${agentMove.move}`);
    }
  }
}

/** Convenience: run a scripted sequence of USER turns over a fresh (or supplied) machine. */
export function runDialogue(turns, { ledger = new ClaimLedger(), router = null, advisor = null, annotate = false } = {}) {
  const machine = new DialogueMachine({ ledger, router, advisor, annotate });
  const emissions = (Array.isArray(turns) ? turns : [turns]).map((t) => machine.turn(t));
  return { ledger, machine, emissions };
}

// ---------------------------------------------------------------------------
// THE PINNED D1 ABSTAIN FIXTURE — the done-when's Given/When/Then.
// ---------------------------------------------------------------------------

/**
 * THE D1 ABSTAIN FIXTURE (the done-when). A fresh dialogue in which the user PROPOSES an UNVERIFIED
 * proof conjecture and then asks "is this settled?". The agent answers CONJECTURAL + an advisory payload
 * (with the promote-to-Phase-F affordance) and NEVER settled. Used by the Wave-19 test and as a
 * self-check; also a load-bearing fixture for the Wave-21 degradation-tripwire canary.
 *
 * @param {{id?:string, statement?:string}} [o]
 * @returns {{ledger, machine, proposed, statusEmission}}
 */
export function runAbstainFixture({
  id = 'd1::collatz',
  statement = 'the Collatz conjecture holds for all positive integers',
} = {}) {
  const ledger = new ClaimLedger();
  const machine = new DialogueMachine({ ledger });
  const proposed = machine.turn({
    intent: USER_INTENT.PROPOSE_CONJECTURE,
    claim: { id, type: 'proof-bearing', statement },
  });
  const statusEmission = machine.turn({ intent: USER_INTENT.ASK_STATUS, claim: id, utterance: 'is this settled?' });
  return { ledger, machine, proposed, statusEmission };
}

// A reader's note on the only positive arm: OBSERVED is the sole rung whose belief projects to VERIFIED
// (claim-ledger), and it is reachable ONLY through the Wave-4 adjudication artifact. So the dialogue can
// assert "settled" exactly when a prior out-of-model verification has lifted the focus claim to OBSERVED
// — never on its own say-so.

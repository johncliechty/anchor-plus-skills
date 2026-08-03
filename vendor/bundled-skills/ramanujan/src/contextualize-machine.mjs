// Wave 22 — CONTEXTUALIZE relation-classifier + commission canary (D3).
//
// The CONTEXTUALIZE pillar (NS8 — "CONTEXTUALIZE composes researchPrime/Gandalf without
// reimplementing"). It SITUATES a mathematical object in the landscape by proposing CONNECTIONS to
// other objects and classifying each connection's RELATION with a native math RELATION CLASSIFIER
//
//     { generalization | specialization | equivalence | instance | structural-analogy }
//
// — and then, crucially, REFUSES TO SETTLE the connection on the strength of that classification.
// The classifier names the PROPOSED structural relation (deterministically, from the two objects'
// descriptors); whether that relation actually HOLDS of the real mathematical objects is a
// CONCEPTUAL claim that no autonomous verifier can settle in Increment-1. So every connection is
// emitted as a CONCEPTUAL claim at the FLOOR (UNVERIFIED), routed through the A3 VERIFY router
// (conceptual claims ABSTAIN+route — the NS3/NS8 abstain-arm), and handed an out-of-model
// researchPrime/Gandalf COMMISSION envelope (EMITTED, never dispatched). The connection is NEVER
// settled by analogy.
//
// THE LOAD-BEARING HONESTY (the done-when):
//   1. EVERY PROPOSED CONNECTION IS A CONCEPTUAL CLAIM ROUTED TO VERIFY. The connection is admitted
//      as a `conceptual` claim and run through the A3 router; it can never be admitted as a
//      `computational` claim (the only autonomous-VERIFIED path), so the firewall subprocess can
//      never launder a "connection" to VERIFIED.
//   2. NEVER SETTLED BY ANALOGY. The single emission builder (#emit) computes `settled` ONLY through
//      contextualizeSettleLicensed(belief) — true IFF the belief is VERIFIED (the OBSERVED rung,
//      reachable only via a re-executable out-of-model artifact). No relation classification — not
//      even a clean `equivalence` or a compelling `structural-analogy` — can set `settled` true. A
//      defensive post-check (validateContextualizeEmission) re-derives the gate and THROWS on any
//      emission that claims settled without a VERIFIED belief, that mis-types a connection as
//      non-conceptual, that omits the advisory/commission on a routed connection, or that carries a
//      dispatched (non-emitted) commission. The machine never calls promote(): every connection is
//      admitted at the FLOOR and held.
//
// The defining Given/When/Then: given a proposed structural analogy, when D3 runs, then it is
// emitted as a CONCEPTUAL claim routed to VERIFY (not settled).
//
// HOW NS8 COMPOSITION WORKS. The advisory commission is built by the Wave-13 EMITTERS
// (emitResearchPrimeCommission / emitGandalfSituateCommission in commission-emitters.mjs), which
// delegate every honesty-bearing decision (independent-origin credit, the same-family rung cap, the
// needs-verification route-out) to the inherited Gandalf seam. This module defines NO research /
// situate logic of its own — the Wave-13 no-inline BOUNDARY CANARY's repo-wide forbidden-symbol arm
// keeps that true. On the single-family substrate (cross_model:false) every commission earns NO
// independent-origin credit — a connection can never be self-corroborated into a settled fact.
//
// Pure node built-ins + the project's own A1 ledger / A3 router / C4 advisor / Wave-13 emitters.
// Runs under `node --test test/`.

import { ClaimLedger, BELIEF, RUNG, isAssertableAsSettled } from './claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from './verify-router.mjs';
import { AdversarialAdvisor } from './adversarial-advisory.mjs';
import {
  emitResearchPrimeCommission,
  emitGandalfSituateCommission,
  isEmittedNotDispatched,
  gandalfSeam,
} from './commission-emitters.mjs';

// ---------------------------------------------------------------------------
// Vocabulary (frozen — pinned, not tunable).
// ---------------------------------------------------------------------------

/** The native math RELATION the classifier emits for a proposed connection. */
export const RELATION = Object.freeze({
  GENERALIZATION: 'generalization', // source has FEWER defining constraints => broader; source generalizes target
  SPECIALIZATION: 'specialization', // source has MORE defining constraints => narrower; source specializes target
  EQUIVALENCE: 'equivalence', // source and target share the SAME defining constraints (mutually characterizing)
  INSTANCE: 'instance', // one side is an OBJECT that satisfies the other (a CONCEPT)'s defining constraints
  STRUCTURAL_ANALOGY: 'structural-analogy', // a cross-domain / non-subsuming structural correspondence
});

/** The relation vocabulary as a frozen list (the classifier's closed output set). */
export const RELATIONS = Object.freeze(Object.values(RELATION));

/** Whether a descriptor names a CONCEPT (a definition with constraints) or a concrete OBJECT (an
 *  individual that may satisfy a concept's constraints). Drives the `instance` classification. */
export const OBJECT_KIND = Object.freeze({ CONCEPT: 'concept', OBJECT: 'object' });

/** The CONTEXTUALIZE phases a proposed connection moves through. There is deliberately NO autonomous
 *  "settled/established" phase — the terminal autonomous phase routes the connection to the gate. */
export const CONTEXTUALIZE_PHASE = Object.freeze({
  PROPOSE_CONNECTION: 'propose-connection',
  CLASSIFY_RELATION: 'classify-relation',
  ROUTE_TO_VERIFY: 'route-to-verify',
  REQUIRES_CERTIFICATION: 'requires-certification', // terminal autonomous phase: routed out-of-model
});

/** The pinned field set of a CONTEXTUALIZE connection emission — every emission carries exactly these. */
export const CONTEXTUALIZE_EMISSION_FIELDS = Object.freeze([
  'seq',
  'phase',
  'connection_id',
  'claim_type',
  'relation',
  'rung',
  'belief',
  'settled',
  'routed',
  'route_verdict',
  'classification',
  'commission',
  'advisory',
  'message',
]);

/** Every connection is admitted as exactly this claim type (never `computational` — the autonomous
 *  VERIFIED path — and never `proof-bearing`). A connection is a CONCEPTUAL claim, full stop. */
export const CONNECTION_CLAIM_TYPE = 'conceptual';

// ---------------------------------------------------------------------------
// The settle-gate (pure) — a connection is never settled by analogy.
// ---------------------------------------------------------------------------

/**
 * THE SETTLE-GATE. A proposed connection may be asserted as SETTLED only when the connection claim's
 * belief is VERIFIED (the OBSERVED rung, reachable only through a re-executable out-of-model
 * adjudication artifact). In Increment-1 a CONCEPTUAL claim can never reach VERIFIED autonomously, so
 * this is false by construction for every connection — the relation classification, however clean,
 * never licenses settling. A thin, deliberate alias over the ledger's isAssertableAsSettled so the
 * CONTEXTUALIZE layer cannot drift from the ledger's definition.
 *
 * @param {string} belief — a BELIEF tag.
 * @returns {boolean} true IFF asserting-the-connection-as-settled is licensed (belief === VERIFIED).
 */
export function contextualizeSettleLicensed(belief) {
  return isAssertableAsSettled(belief);
}

// ---------------------------------------------------------------------------
// The native math RELATION CLASSIFIER (pure).
// ---------------------------------------------------------------------------

function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}

function normalizeDescriptor(d, side) {
  if (!d || typeof d !== 'object') {
    throw new Error(`classifyRelation: the ${side} descriptor must be an object { id, kind, constraints }`);
  }
  if (!isNonEmptyString(d.id)) {
    throw new Error(`classifyRelation: the ${side} descriptor needs a non-empty string id`);
  }
  const kind = d.kind === OBJECT_KIND.OBJECT ? OBJECT_KIND.OBJECT : OBJECT_KIND.CONCEPT;
  const constraints = Array.isArray(d.constraints) ? d.constraints.map(String) : [];
  return Object.freeze({
    id: d.id,
    name: isNonEmptyString(d.name) ? d.name : d.id,
    kind,
    domain: isNonEmptyString(d.domain) ? d.domain : null,
    constraints: Object.freeze(constraints),
  });
}

function constraintSet(d) {
  return new Set(d.constraints);
}
function isSubset(a, b) {
  for (const x of a) if (!b.has(x)) return false;
  return true;
}
function setsEqual(a, b) {
  return a.size === b.size && isSubset(a, b);
}

/**
 * Classify the native math RELATION of a proposed connection between two mathematical descriptors.
 * DETERMINISTIC and total over well-formed descriptors. The output is one of the five RELATION values
 * — a STRUCTURAL classification of the PROPOSED relation, NOT an assertion that the relation holds.
 *
 * The decision procedure (defining constraints = a descriptor's axiom / property set):
 *   • exactly one side is an OBJECT (the other a CONCEPT) ............ INSTANCE
 *       (the object is proposed as an instance of the concept; `basis.satisfies` records whether the
 *        object's stated properties cover the concept's defining constraints).
 *   • both CONCEPTS, SAME domain:
 *       - equal constraint sets ................................. EQUIVALENCE
 *       - source ⊊ target (source has fewer constraints) ........ GENERALIZATION (source generalizes target)
 *       - target ⊊ source (source has more constraints) ......... SPECIALIZATION (source specializes target)
 *       - overlapping but neither subsumes ...................... STRUCTURAL_ANALOGY
 *   • both CONCEPTS, DIFFERENT domain ........................... STRUCTURAL_ANALOGY (cross-domain correspondence)
 *   • both OBJECTS: equal constraint sets ...................... EQUIVALENCE, else STRUCTURAL_ANALOGY
 *
 * @param {{source:object, target:object, correspondence?:object}} connection
 * @returns frozen { relation, source_id, target_id, source_kind, target_kind, same_domain,
 *                   cross_domain, orientation, has_correspondence, basis, reason }
 */
export function classifyRelation(connection) {
  if (!connection || typeof connection !== 'object') {
    throw new Error('classifyRelation requires a connection { source, target, correspondence? }');
  }
  const source = normalizeDescriptor(connection.source, 'source');
  const target = normalizeDescriptor(connection.target, 'target');
  const correspondence = connection.correspondence;
  const has_correspondence = gandalfSeam.isWellFormedStructureMap(correspondence);

  const sObj = source.kind === OBJECT_KIND.OBJECT;
  const tObj = target.kind === OBJECT_KIND.OBJECT;
  const sc = constraintSet(source);
  const tc = constraintSet(target);
  const same_domain = source.domain !== null && source.domain === target.domain;

  let relation;
  let orientation = 'symmetric';
  let basis;
  let reason;

  if (sObj !== tObj) {
    // Exactly one OBJECT + one CONCEPT => an INSTANCE connection.
    const objectD = sObj ? source : target;
    const conceptD = sObj ? target : source;
    const objC = sObj ? sc : tc;
    const conC = sObj ? tc : sc;
    const satisfies = isSubset(conC, objC); // the object exhibits all the concept's defining constraints
    relation = RELATION.INSTANCE;
    orientation = sObj ? 'source-instance-of-target' : 'target-instance-of-source';
    basis = Object.freeze({
      object_id: objectD.id,
      concept_id: conceptD.id,
      satisfies,
      missing_constraints: Object.freeze([...conC].filter((x) => !objC.has(x))),
    });
    reason =
      `"${objectD.name}" is proposed as an INSTANCE of the concept "${conceptD.name}"` +
      (satisfies
        ? ' (its stated properties cover the concept\'s defining constraints)'
        : ' (its stated properties do NOT cover every defining constraint — the instance claim is itself unverified)') +
      ' — a CONCEPTUAL claim to verify out-of-model, never settled by classification.';
  } else if (sObj && tObj) {
    // Two concrete OBJECTS: identical defining properties => equivalence (isomorphic descriptors), else analogy.
    if (setsEqual(sc, tc)) {
      relation = RELATION.EQUIVALENCE;
      basis = Object.freeze({ shared_constraints: Object.freeze([...sc]) });
      reason = `objects "${source.name}" and "${target.name}" carry the same defining properties (proposed EQUIVALENCE/isomorphism) — a CONCEPTUAL claim to verify out-of-model.`;
    } else {
      relation = RELATION.STRUCTURAL_ANALOGY;
      basis = Object.freeze({ correspondence: has_correspondence ? correspondence : null });
      reason = `objects "${source.name}" and "${target.name}" are connected by a STRUCTURAL ANALOGY (no defining-property identity) — a CONCEPTUAL claim to verify out-of-model, never settled by analogy.`;
    }
  } else if (same_domain) {
    // Two CONCEPTS in the same domain: compare defining-constraint sets.
    if (setsEqual(sc, tc)) {
      relation = RELATION.EQUIVALENCE;
      basis = Object.freeze({ shared_constraints: Object.freeze([...sc]) });
      reason = `concepts "${source.name}" and "${target.name}" share the same defining constraints (proposed EQUIVALENCE) — a CONCEPTUAL claim to verify out-of-model.`;
    } else if (isSubset(sc, tc)) {
      relation = RELATION.GENERALIZATION;
      orientation = 'source-generalizes-target';
      basis = Object.freeze({ added_by_target: Object.freeze([...tc].filter((x) => !sc.has(x))) });
      reason = `"${source.name}" GENERALIZES "${target.name}" (fewer defining constraints => broader extension; every ${target.name} is a ${source.name}) — a CONCEPTUAL claim to verify out-of-model.`;
    } else if (isSubset(tc, sc)) {
      relation = RELATION.SPECIALIZATION;
      orientation = 'source-specializes-target';
      basis = Object.freeze({ added_by_source: Object.freeze([...sc].filter((x) => !tc.has(x))) });
      reason = `"${source.name}" SPECIALIZES "${target.name}" (more defining constraints => narrower extension; every ${source.name} is a ${target.name}) — a CONCEPTUAL claim to verify out-of-model.`;
    } else {
      relation = RELATION.STRUCTURAL_ANALOGY;
      basis = Object.freeze({
        shared: Object.freeze([...sc].filter((x) => tc.has(x))),
        source_only: Object.freeze([...sc].filter((x) => !tc.has(x))),
        target_only: Object.freeze([...tc].filter((x) => !sc.has(x))),
      });
      reason = `concepts "${source.name}" and "${target.name}" overlap but neither subsumes the other — a STRUCTURAL ANALOGY (CONCEPTUAL claim to verify out-of-model, never settled by analogy).`;
    }
  } else {
    // Two CONCEPTS in DIFFERENT domains: subsumption is not meaningful => a cross-domain analogy.
    relation = RELATION.STRUCTURAL_ANALOGY;
    basis = Object.freeze({
      source_domain: source.domain,
      target_domain: target.domain,
      correspondence: has_correspondence ? correspondence : null,
    });
    reason = `concepts "${source.name}" (${source.domain || 'domain?'}) and "${target.name}" (${target.domain || 'domain?'}) live in different domains — a cross-domain STRUCTURAL ANALOGY (CONCEPTUAL claim to verify out-of-model, never settled by analogy).`;
  }

  return Object.freeze({
    relation,
    source_id: source.id,
    target_id: target.id,
    source_kind: source.kind,
    target_kind: target.kind,
    same_domain,
    cross_domain: !same_domain,
    orientation,
    has_correspondence,
    basis,
    reason,
  });
}

// ---------------------------------------------------------------------------
// The connection advisory payload (pure).
// ---------------------------------------------------------------------------

/**
 * Build the advisory payload the CONTEXTUALIZE pillar attaches to a routed connection. It records the
 * classified relation, degrades to CONJECTURAL, flags that the connection needs out-of-model
 * verification, stamps `not_settled_by_analogy:true` (the honesty marker), folds in an optional A3
 * router advisory + the emit-not-dispatch researchPrime/Gandalf commission, and carries the
 * promote-to-Phase-F affordance (the out-of-model cross-family corroborator the user may route to).
 *
 * @param {object} claim — a frozen connection-claim snapshot ({id, type, rung, belief, statement}).
 * @param {object} classification — the classifyRelation() record.
 * @param {{commission:object, routerAdvisory?:object|null, reason?:string}} opts
 * @returns frozen advisory payload.
 */
export function connectionRoutePayload(claim, classification, { commission, routerAdvisory = null, reason } = {}) {
  return Object.freeze({
    belief: BELIEF.CONJECTURAL,
    settled: false, // an advisory payload is, by definition, NOT a settle
    relation: classification.relation,
    classification,
    not_settled_by_analogy: true, // the load-bearing honesty marker: classification never settles a connection
    needs_verification: true,
    route: 'out-of-model',
    commission, // the Wave-13 emit-not-dispatch researchPrime/Gandalf envelope (single-family => no independent origin)
    promote_affordance: Object.freeze({
      available: true,
      target: 'Increment-2 / North-Star Phase F',
      action: 'route-to-out-of-model-cross-family-corroborator + researchPrime/Gandalf commission',
      description:
        'Promote this connection to the out-of-model CONTEXTUALIZE certifier — a cross-family corroborator ' +
        '+ researchPrime/Gandalf commission (Increment-2 F1) that independently checks whether the proposed ' +
        `${classification.relation} actually holds. The autonomous tier classifies the relation and ABSTAINS + ` +
        'routes; it never settles a connection by analogy (single-family substrate earns no independent-origin credit).',
    }),
    reason:
      reason ||
      `connection "${claim.id}" is classified as a ${classification.relation} but is NOT settled: the autonomous ` +
        'tier cannot certify that the proposed relation holds — it stamps the connection CONJECTURAL and routes ' +
        'to the out-of-model certifier (NS8 abstain-arm = Increment-2 / Phase F).',
    router_advisory: routerAdvisory,
  });
}

// ---------------------------------------------------------------------------
// The structured emission contract — validation.
// ---------------------------------------------------------------------------

/**
 * Validate one CONTEXTUALIZE connection emission against the structured contract + the two load-bearing
 * invariants. Throws on any violation (a structural guarantee, not a soft check):
 *   - every contract field is present;
 *   - the relation is one of the five RELATION values;
 *   - EVERY CONNECTION IS A CONCEPTUAL CLAIM: claim_type === 'conceptual' (done-when #1);
 *   - THE SETTLE-GATE (done-when #2): `settled` is true IFF belief === VERIFIED; a settled emission is
 *     never the autonomous outcome of a conceptual connection;
 *   - a NON-settled (routed) emission must carry an advisory payload AND an EMIT-not-dispatch commission,
 *     and its route verdict must not be VERIFIED (never settled by analogy).
 *
 * @returns the same emission (for chaining) when valid.
 */
export function validateContextualizeEmission(emission) {
  if (!emission || typeof emission !== 'object') {
    throw new Error('contextualize emission must be an object conforming to the structured contract');
  }
  for (const f of CONTEXTUALIZE_EMISSION_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(emission, f)) {
      throw new Error(`contextualize emission is missing the contract field "${f}"`);
    }
  }
  const { claim_type, relation, settled, belief, routed, route_verdict, advisory, commission } = emission;

  if (!RELATIONS.includes(relation)) {
    throw new Error(`D3 relation invariant violated: relation must be one of ${RELATIONS.join(' | ')} (got ${JSON.stringify(relation)}).`);
  }

  // DONE-WHEN #1: every connection is a CONCEPTUAL claim (never computational/proof-bearing).
  if (claim_type !== CONNECTION_CLAIM_TYPE) {
    throw new Error(
      `D3 conceptual invariant violated: a connection emission for "${emission.connection_id}" must be a ` +
        `'${CONNECTION_CLAIM_TYPE}' claim (got ${JSON.stringify(claim_type)}) — a connection is never admitted as ` +
        'the autonomous-VERIFIED computational type.',
    );
  }

  // DONE-WHEN #2: THE SETTLE-GATE — settled <=> VERIFIED belief.
  const licensed = contextualizeSettleLicensed(belief);
  if (settled === true) {
    if (!licensed) {
      throw new Error(
        `D3 settle-gate violated: connection "${emission.connection_id}" claims settled but belief is ${belief} ` +
          '(only a VERIFIED belief may be asserted as settled — a connection is never settled by analogy).',
      );
    }
  } else {
    if (licensed && belief === BELIEF.VERIFIED) {
      throw new Error('D3 settle-gate: inconsistent non-settled emission with a VERIFIED belief');
    }
    // A routed connection must be advisory + carry an emit-not-dispatch commission, and never report VERIFIED.
    if (routed !== true) {
      throw new Error(`D3 routing invariant violated: a non-settled connection "${emission.connection_id}" must be routed.`);
    }
    if (advisory === null || advisory === undefined) {
      throw new Error(`D3 advisory invariant violated: a routed connection "${emission.connection_id}" must carry an advisory payload.`);
    }
    if (!isEmittedNotDispatched(commission)) {
      throw new Error(
        `D3 commission invariant violated: a routed connection "${emission.connection_id}" must carry an EMITTED ` +
          '(emitted:true, dispatched:false) researchPrime/Gandalf commission — never a dispatched live spawn.',
      );
    }
    if (route_verdict === ROUTE_VERDICT.VERIFIED) {
      throw new Error(`D3 settle-gate: a routed connection "${emission.connection_id}" reported route verdict VERIFIED (never settled by analogy).`);
    }
  }
  return emission;
}

// ---------------------------------------------------------------------------
// The CONTEXTUALIZE machine.
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
 * The stateful CONTEXTUALIZE machine (D3). Bound to the shared A1 ledger; optionally wired to the A3
 * VERIFY router (contextualize() routes the connection claim through it — conceptual claims ABSTAIN)
 * and the C4 in-process advisor (annotates the connection's NOTES as it runs — advisory only, never a
 * rung change). It maintains the focus connection, an append-only emission log, and a monotone seq.
 *
 * The autonomous tier NEVER promotes: every connection is admitted at the FLOOR (UNVERIFIED) and held.
 * Settling a connection (the VERIFIED path) is Increment-2 / Phase F.
 */
export class ContextualizeMachine {
  #ledger;
  #router;
  #advisor;
  #log;
  #seq;
  #focusId;

  /**
   * @param {{ledger?:ClaimLedger, router?:VerifyRouter|null, advisor?:AdversarialAdvisor|null, annotate?:boolean}} [o]
   *   ledger   — the shared A1 ledger (a fresh one is created when omitted).
   *   router   — the A3 VERIFY router; when present, contextualize() routes the connection claim through it.
   *   advisor  — the C4 in-process advisor; when present (or annotate:true) the machine annotates claim NOTES.
   *   annotate — build a default C4 advisor over the ledger when no advisor is supplied (default false).
   */
  constructor({ ledger = new ClaimLedger(), router = null, advisor = null, annotate = false } = {}) {
    if (!isLedgerLike(ledger)) {
      throw new Error('ContextualizeMachine requires an A1 ClaimLedger ({assert, get, has, rungOf, beliefOf})');
    }
    if (router !== null && !(router instanceof VerifyRouter) && typeof router?.route !== 'function') {
      throw new Error('ContextualizeMachine router (when given) must be an A3 VerifyRouter (or expose route())');
    }
    let adv = advisor;
    if (adv === null && annotate) adv = new AdversarialAdvisor({ ledger });
    if (adv !== null && typeof adv?.critique !== 'function') {
      throw new Error('ContextualizeMachine advisor (when given) must be a C4 AdversarialAdvisor (or expose critique())');
    }
    this.#ledger = ledger;
    this.#router = router;
    this.#advisor = adv;
    this.#log = [];
    this.#seq = 0;
    this.#focusId = null;
  }

  /** The shared A1 ledger. */
  get ledger() {
    return this.#ledger;
  }

  /** The id of the connection currently in focus (or null). */
  get focusConnectionId() {
    return this.#focusId;
  }

  /** A frozen snapshot of the append-only emission log (every connection emission, in order). */
  get transcript() {
    return Object.freeze([...this.#log]);
  }

  /**
   * THE SESSION INVARIANT (the done-when, over the whole transcript): every emission is a CONCEPTUAL
   * claim, NONE is settled (the autonomous tier never settles a connection by analogy), and every
   * routed emission carries an advisory payload + an emit-not-dispatch commission.
   */
  get neverSettledByAnalogy() {
    return this.#log.every(
      (e) =>
        e.claim_type === CONNECTION_CLAIM_TYPE &&
        e.settled === false &&
        e.advisory != null &&
        isEmittedNotDispatched(e.commission),
    );
  }

  // --- helpers ------------------------------------------------------------

  #connectionId(spec, classification) {
    if (isNonEmptyString(spec.id)) return spec.id;
    return `${classification.source_id}::${classification.relation}::${classification.target_id}`;
  }

  #connectionStatement(classification) {
    return `proposed ${classification.relation}: ${classification.reason}`;
  }

  /** Optionally annotate a connection's NOTES via the injected C4 advisor (advisory only — never a rung change). */
  #annotate(claimId, restatement) {
    if (this.#advisor) {
      try {
        this.#advisor.critique(claimId, restatement !== undefined ? { restatement } : undefined);
      } catch {
        /* annotation is best-effort + advisory; it can never affect the rung or the emission. */
      }
    }
  }

  /**
   * Build the emit-not-dispatch researchPrime / Gandalf commission for a connection (NS8 composition).
   * A STRUCTURAL_ANALOGY that carries a well-formed structure-map gets a Gandalf SITUATE commission
   * (which itself composes researchPrime under the hood and caps at CLAIMED); every other connection
   * gets a researchPrime commission. Both are EMITTED (never dispatched) and single-family.
   */
  #buildCommission(connectionId, classification, correspondence) {
    const question =
      `Independently verify the proposed ${classification.relation} between "${classification.source_id}" and ` +
      `"${classification.target_id}" (CONTEXTUALIZE connection — does the relation actually hold?).`;
    if (classification.relation === RELATION.STRUCTURAL_ANALOGY && gandalfSeam.isWellFormedStructureMap(correspondence)) {
      return emitGandalfSituateCommission({
        id: connectionId,
        effort: `situate the structural analogy "${classification.source_id}" ~ "${classification.target_id}"`,
        question,
        structure_map: correspondence,
        outside_view_base_rate: 'most proposed cross-domain structural analogies fail to lift to a faithful functorial correspondence without an independent check',
        cross_model: false, // single-family substrate => no independent-origin credit (anti-laundering)
        facts_verified: false,
      });
    }
    return emitResearchPrimeCommission({
      question,
      claim_id: connectionId,
      claim_type: CONNECTION_CLAIM_TYPE,
      cross_model: false, // single-family => no independent-origin credit
      routed_to: 'out-of-model-cross-family corroborator + researchPrime commission (Increment-2 F1)',
    });
  }

  // --- the canonical emission builder (the SOLE place `settled` is decided) -

  #emit({ claim, classification, commission, routerAdvisory, routeVerdict }) {
    const belief = claim.belief;
    const settled = contextualizeSettleLicensed(belief); // true IFF VERIFIED — never for a conceptual connection

    let advisory = null;
    let message;
    if (settled) {
      // Unreachable on the autonomous tier (a conceptual claim never reaches VERIFIED) — present only so the
      // contract is total.
      message = `connection "${claim.id}" (${classification.relation}) is SETTLED (VERIFIED) by a re-executable out-of-model artifact.`;
    } else {
      advisory = connectionRoutePayload(claim, classification, { commission, routerAdvisory });
      message =
        `connection "${claim.id}" is classified as a ${classification.relation} and routed to VERIFY — ` +
        'CONJECTURAL, not settled. The autonomous tier never settles a connection by analogy; it emits a ' +
        'researchPrime/Gandalf commission and routes to the out-of-model certifier (Increment-2 / Phase F).';
    }

    this.#seq += 1;
    this.#focusId = claim.id;

    const emission = Object.freeze({
      seq: this.#seq,
      phase: CONTEXTUALIZE_PHASE.REQUIRES_CERTIFICATION,
      connection_id: claim.id,
      claim_type: claim.type,
      relation: classification.relation,
      rung: claim.rung,
      belief: claim.belief,
      settled,
      routed: !settled,
      route_verdict: routeVerdict,
      classification,
      commission,
      advisory,
      message,
    });

    validateContextualizeEmission(emission); // structural settle-gate + conceptual + commission invariants (throws)
    this.#log.push(emission);
    return emission;
  }

  // --- the public pillar surface ------------------------------------------

  /**
   * CONTEXTUALIZE a proposed connection: classify its native math RELATION, admit it as a CONCEPTUAL
   * claim at the FLOOR (UNVERIFIED), route it through the A3 VERIFY router (conceptual => ABSTAIN), build
   * the emit-not-dispatch researchPrime/Gandalf commission, and emit the structured connection record.
   * The connection is NEVER settled by the classification. No rung is changed.
   *
   * @param {{source:object, target:object, correspondence?:object, id?:string, statement?:string}} spec
   * @returns frozen structured connection emission.
   */
  contextualize(spec) {
    if (!spec || typeof spec !== 'object' || !spec.source || !spec.target) {
      throw new Error('contextualize() requires a connection spec { source, target, correspondence?, id? }');
    }
    const classification = classifyRelation(spec);
    const connectionId = this.#connectionId(spec, classification);

    // Admit the connection as a CONCEPTUAL claim at the FLOOR (UNVERIFIED) — never above the floor, never
    // the autonomous-VERIFIED computational type.
    if (!this.#ledger.has(connectionId)) {
      this.#ledger.assert({
        id: connectionId,
        type: CONNECTION_CLAIM_TYPE,
        statement: isNonEmptyString(spec.statement) ? spec.statement : this.#connectionStatement(classification),
        meta: { relation: classification.relation, source_id: classification.source_id, target_id: classification.target_id },
      });
    }
    this.#annotate(connectionId, this.#connectionStatement(classification));

    // Route through the A3 VERIFY router (the honest verification spine). A conceptual connection ABSTAINS +
    // routes; it is never lifted. Fold the router advisory in.
    let routerAdvisory = null;
    let routeVerdict = null;
    if (this.#router) {
      const result = this.#router.route(connectionId, {});
      routeVerdict = result.verdict;
      if (result.verdict !== ROUTE_VERDICT.VERIFIED) routerAdvisory = result.advisory;
    }

    // Build the NS8 commission (researchPrime / Gandalf) — emit, never dispatch.
    const commission = this.#buildCommission(connectionId, classification, spec.correspondence);

    // Re-read AFTER the route (the conceptual claim is not lifted — honest abstain) and emit the record.
    const after = this.#ledger.get(connectionId);
    return this.#emit({ claim: after, classification, commission, routerAdvisory, routeVerdict });
  }
}

/** Convenience: run a batch of connection specs through a fresh (or supplied) machine. */
export function runContextualize(connections, { ledger = new ClaimLedger(), router = null, advisor = null, annotate = false } = {}) {
  const machine = new ContextualizeMachine({ ledger, router, advisor, annotate });
  const emissions = (Array.isArray(connections) ? connections : [connections]).map((c) => machine.contextualize(c));
  return { ledger, machine, emissions };
}

// ---------------------------------------------------------------------------
// THE PINNED D3 ABSTAIN FIXTURE — the done-when's Given/When/Then.
// ---------------------------------------------------------------------------

/**
 * THE D3 ABSTAIN FIXTURE (the done-when). A proposed STRUCTURAL ANALOGY across two domains: the
 * Grothendieck/topology↔field-theory correspondence between the FUNDAMENTAL GROUP of a covering space
 * (algebraic topology) and the GALOIS GROUP of a field extension (field theory) — covers ↔ extensions,
 * deck transformations ↔ Galois automorphisms, the subgroup correspondence on both sides.
 *
 * The connection is the "most convincing" case for the pillar (a celebrated, real analogy), and yet the
 * autonomous tier STILL refuses to settle it: it classifies the relation as `structural-analogy`, emits
 * it as a CONCEPTUAL claim at the floor, routes it through the A3 router (ABSTAIN), and hands back an
 * emit-not-dispatch Gandalf/researchPrime commission. NEVER settled by analogy.
 *
 * @param {{withRouter?:boolean}} [o]
 * @returns {{ledger, machine, classification, emission}}
 */
export function runContextualizeAbstainFixture({ withRouter = true } = {}) {
  const ledger = new ClaimLedger();
  const router = withRouter ? new VerifyRouter({ ledger }) : null;
  const machine = new ContextualizeMachine({ ledger, router });

  const spec = {
    id: 'd3::pi1~galois',
    source: {
      id: 'fundamental-group',
      name: 'fundamental group of a covering space',
      kind: OBJECT_KIND.CONCEPT,
      domain: 'algebraic-topology',
      constraints: ['acts-on-fibers', 'subgroup-lattice', 'deck-transformations', 'universal-cover'],
    },
    target: {
      id: 'galois-group',
      name: 'Galois group of a field extension',
      kind: OBJECT_KIND.CONCEPT,
      domain: 'field-theory',
      constraints: ['acts-on-roots', 'subgroup-lattice', 'field-automorphisms', 'algebraic-closure'],
    },
    correspondence: {
      answer: 'covering-space theory and Galois theory share a group-acting-on-fibers structure (the Grothendieck analogy)',
      correspondences: [
        { source_relation: 'the deck-transformation group acts freely transitively on the fibers of a covering', target_relation: 'the Galois group acts simply transitively on the roots/embeddings of an extension' },
        { source_relation: 'subgroups of pi_1 correspond to intermediate covering spaces', target_relation: 'subgroups of the Galois group correspond to intermediate fields (the Galois correspondence)' },
        { source_relation: 'the universal cover is the "largest" connected covering', target_relation: 'the separable/algebraic closure is the "largest" extension' },
      ],
    },
  };

  const classification = classifyRelation(spec);
  const emission = machine.contextualize(spec);
  return Object.freeze({ ledger, machine, classification, emission });
}

// A reader's note on the only settled arm: OBSERVED is the sole rung whose belief projects to VERIFIED
// (claim-ledger), and it is reachable ONLY through a re-executable out-of-model adjudication artifact. A
// CONCEPTUAL connection claim cannot reach it autonomously, so the CONTEXTUALIZE pillar can assert a
// connection "settled" exactly when a prior out-of-model certifier has lifted it to OBSERVED — never on
// the strength of its own relation classification.

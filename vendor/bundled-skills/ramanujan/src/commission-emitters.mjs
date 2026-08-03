// Wave 13 — Commission emitters (B3).
//
// NS8: CONTEXTUALIZE composes researchPrime / Gandalf WITHOUT reimplementing them. This module is
// the single typed-commission-envelope EMITTER surface Ramanujan's pillars use to reach the
// best-in-class research/situate landscape. It is a COMPOSITION of the inherited Gandalf v1
// commission seam (`gandalf-commission-seam` in inherits.manifest.json) — it imports that seam and
// delegates every honesty-bearing decision to it. It defines NO research/situate logic of its own;
// the Wave-13 no-inline BOUNDARY CANARY (src/boundary-canary.mjs) enforces exactly that, by
// import-graph (this module MUST carry an edge to the inherited seam) + forbidden-symbol (this
// module MUST NOT locally re-define a seam-owned function).
//
// THE EMIT-NOT-DISPATCH BOUNDARY. An emitter MINTS a typed commission envelope — a pure value that
// records WHAT would be dispatched to researchPrime / Gandalf — and stops there. It NEVER runs the
// live `agent()` spawn (that integration point is owned by the orchestrator, never by the
// deterministic spine). Every envelope this module emits carries `emitted:true, dispatched:false`,
// and on the single-family substrate (cross_model:false) earns NO independent-origin credit — the
// anti-laundering rule the inherited seam owns and this module merely surfaces.
//
// Public surface:
//   RESEARCHPRIME_SKILL / GANDALF_SKILL          — the `skill` markers an envelope routes to
//   COMMISSION_KIND                              — the two envelope kinds this module emits
//   emitResearchPrimeCommission(spec)            — a typed researchPrime commission envelope
//   emitGandalfSituateCommission(spec)           — a typed Gandalf SITUATE commission envelope
//   isEmittedNotDispatched(envelope)             — the emit-not-dispatch predicate
//   assertEmitNotDispatch(envelope)              — throws if an envelope claims to be dispatched
//   gandalfSeam                                  — the inherited seam namespace (re-exposed, not re-defined)

import {
  commissionResearchPrime,
  composeSituate,
  abstractEffort,
  isWellFormedStructureMap,
  independentOriginCredit,
  needsVerificationHandoff,
  SITUATE_KIND,
  PERSONA_FAMILY,
} from '../../gandalf/seam/situate.mjs';

// Re-expose the inherited seam as a namespace for downstream composition (NS8). This is the
// inherited surface, not a reimplementation — the boundary canary's forbidden-symbol arm only
// flags LOCAL DEFINITIONS of seam-owned functions, never their import / re-export.
import * as gandalfSeam from '../../gandalf/seam/situate.mjs';
export { gandalfSeam };

/** The logical name of the inherited seam in inherits.manifest.json (the import-graph anchor the
 *  boundary canary requires this module to carry an edge to). */
export const COMMISSIONED_SEAM_LOGICAL_NAME = 'gandalf-commission-seam';

/** The `skill` an envelope routes to. researchPrime for the research/verification handoff; Gandalf
 *  for the SITUATE structure-map leg (which itself commissions researchPrime under the hood). */
export const RESEARCHPRIME_SKILL = 'researchPrime';
export const GANDALF_SKILL = 'gandalf';

/** The two typed commission-envelope kinds this module emits. */
export const COMMISSION_KIND = Object.freeze({
  RESEARCHPRIME: 'researchprime-commission',
  GANDALF_SITUATE: 'gandalf-situate-commission',
});

function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}

// ---------------------------------------------------------------------------
// researchPrime commission emitter.
// ---------------------------------------------------------------------------

/**
 * Emit (NEVER dispatch) a typed researchPrime commission ENVELOPE for a routed claim. The
 * honesty-bearing core (skill marker, origin family, and whether the commission earns
 * independent-origin credit) is DELEGATED to the inherited seam's `commissionResearchPrime`; this
 * emitter only wraps that core in the emit-not-dispatch transport envelope the spine routes.
 *
 * @param {{question:string, claim_id?:string|null, claim_type?:string|null,
 *          cross_model?:boolean, routed_to?:string|null}} spec
 * @returns frozen researchPrime commission envelope (emitted:true, dispatched:false)
 */
export function emitResearchPrimeCommission({
  question,
  claim_id = null,
  claim_type = null,
  cross_model = false,
  routed_to = null,
} = {}) {
  if (!isNonEmptyString(question)) {
    throw new Error('emitResearchPrimeCommission requires a non-empty question');
  }
  // Delegate the honesty-bearing fields to the inherited seam (no local research logic).
  const core = commissionResearchPrime({ question, cross_model, commission_id: claim_id });
  return Object.freeze({
    kind: COMMISSION_KIND.RESEARCHPRIME,
    skill: RESEARCHPRIME_SKILL,
    emitted: true,
    dispatched: false, // emit-not-dispatch: this is a typed value, not a live spawn
    question: core.question,
    claim_id,
    claim_type,
    routed_to,
    cross_model: core.cross_model,
    origin_family: core.origin_family,
    independent_origin: core.independent_origin, // single-family => false (anti-laundering)
    researchprime_commission_id: core.researchprime_commission_id,
  });
}

// ---------------------------------------------------------------------------
// Gandalf SITUATE commission emitter.
// ---------------------------------------------------------------------------

/**
 * Emit (NEVER dispatch) a typed Gandalf SITUATE commission ENVELOPE. This COMPOSES the inherited
 * seam end-to-end — `abstractEffort` (S0), `commissionResearchPrime` (the researchPrime leg),
 * `composeSituate` (the honesty-capped finding) — and re-uses `independentOriginCredit` /
 * `needsVerificationHandoff` to surface the seam's caps verbatim. It re-implements none of them.
 *
 * The composed finding carries the seam's load-bearing caps: a same-family situate cannot
 * self-CORROBORATE (rung caps at CLAIMED), and unverified facts attach a researchPrime
 * `needs_verification` route-out. The envelope wraps the finding with emit-not-dispatch transport.
 *
 * @param {{id:string, effort:string, question:string, structure_map:object,
 *          outside_view_base_rate:*, reasoning?:string, verdict?:string,
 *          cross_model?:boolean, facts_verified?:boolean}} spec
 * @returns frozen Gandalf SITUATE commission envelope (emitted:true, dispatched:false)
 */
export function emitGandalfSituateCommission({
  id,
  effort,
  question,
  structure_map,
  outside_view_base_rate,
  reasoning,
  verdict,
  cross_model = false,
  facts_verified = false,
} = {}) {
  if (!isNonEmptyString(id)) throw new Error('emitGandalfSituateCommission requires an id');
  if (!isWellFormedStructureMap(structure_map)) {
    throw new Error('emitGandalfSituateCommission requires a structure-map with ≥2 answer-first relational correspondences');
  }
  // Compose the inherited seam (no local situate logic of any kind). The researchPrime leg is the
  // typed emit-not-dispatch envelope from this module's own researchPrime emitter (which itself
  // delegates to the seam's commissionResearchPrime), so BOTH legs carry the emit-not-dispatch flags.
  const abstraction = abstractEffort(effort);
  const commission = emitResearchPrimeCommission({ question, claim_id: id, cross_model });
  const finding = composeSituate({
    id,
    abstraction,
    commission,
    structure_map,
    outside_view_base_rate,
    reasoning,
    verdict,
    facts_verified,
  });

  return Object.freeze({
    kind: COMMISSION_KIND.GANDALF_SITUATE,
    skill: GANDALF_SKILL,
    emitted: true,
    dispatched: false, // emit-not-dispatch
    situate_kind: SITUATE_KIND,
    origin_family: PERSONA_FAMILY,
    commission, // the wrapped researchPrime leg (also emit-not-dispatch)
    finding, // the honesty-capped SITUATE finding (rung capped per the seam)
    rung: finding.rung,
    independent_origin: independentOriginCredit(commission),
    needs_verification_handoff: needsVerificationHandoff(finding),
  });
}

// ---------------------------------------------------------------------------
// The emit-not-dispatch invariant.
// ---------------------------------------------------------------------------

/** True iff `envelope` is a properly EMITTED (never dispatched) commission. The load-bearing
 *  boundary: the deterministic spine emits typed values; it never runs the live spawn. Pure. */
export function isEmittedNotDispatched(envelope) {
  return (
    envelope !== null &&
    typeof envelope === 'object' &&
    envelope.emitted === true &&
    envelope.dispatched === false
  );
}

/** Throw unless `envelope` is emit-not-dispatch. A guard for any caller about to treat an envelope
 *  as a settled result (it never is — a commission is a routed advisory, not a verdict). */
export function assertEmitNotDispatch(envelope) {
  if (!isEmittedNotDispatched(envelope)) {
    throw new Error('commission envelope must be EMITTED (emitted:true) and NOT dispatched (dispatched:false)');
  }
  return envelope;
}

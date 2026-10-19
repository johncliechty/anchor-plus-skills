// Gandalf advisor — the anti-laundering law as an HONOR-SYSTEM checklist (Wave 7).
//
// The WITHOUT-ledger ship-state (MASTER-PLAN.md). Gandalf v1 (Increment 1) ships BEFORE the
// external Phase-0 shared-compose contract + orchestrator-minted unforgeable commission-id LEDGER
// exists. That ledger is owned OUTSIDE this cycle (it must generalize to Jumper-composes-Gandalf /
// recreate-a-paper). Until it lands, the anti-laundering law is enforced as an HONEST HONOR-SYSTEM
// CHECKLIST in the skill, and the two content-binding canaries that would MACHINE-CHECK
// commission-id authenticity — B2′ (a forged / unresolvable commission-id FAILS) and B7′ (content
// binding: a commissioned result is bound to the id that produced it) — are stamped
// BLOCKED-this-cycle and are explicitly NON-GATING.
//
// This module makes that honest status MACHINE-READABLE (so a canary can assert it) WITHOUT
// pretending the gap is closed:
//   • antiLaunderingStatus()        — B2′/B7′ stamped BLOCKED-this-cycle, gating:false, with the
//                                     named external precondition that unblocks them (Increment 2);
//   • ANTI_LAUNDERING_CHECKLIST     — the honor-system law a human verifies each cycle, each item
//                                     annotated with the deterministic canary that ALREADY enforces
//                                     its machine-checkable shadow (or BLOCKED-this-cycle if none);
//   • resolveCommissionId(id)       — the honor-system resolver: with NO ledger it can only return
//                                     `UNRESOLVABLE_NO_LEDGER`, never a true/false authenticity
//                                     verdict — the honest reason B2′/B7′ cannot gate yet.
//
// PRINCIPLE-D / honesty: nothing here is imported by the deterministic gate (test/harness.mjs). A
// forged commission-id therefore rides FREE through `node --test` in Increment 1 — that is the
// HONEST WITHOUT-ledger done-state, surfaced (not hidden) by this module and its canary. WITH the
// ledger (Increment 2), B2′/B7′ + a forgery fixture flip from BLOCKED to a passing machine gate.

/** The two ship-states for the ledger dependency (MASTER-PLAN.md). */
export const SHIP_STATE_WITHOUT_LEDGER = 'WITHOUT-ledger';
export const SHIP_STATE_WITH_LEDGER = 'WITH-ledger';

/** The committed ship-state for Gandalf v1 (Increment 1). */
export const COMMITTED_SHIP_STATE = SHIP_STATE_WITHOUT_LEDGER;

/** The honor-system stamp carried by a content-binding canary that cannot run until the external
 *  Phase-0 commission-id ledger exists. */
export const BLOCKED_THIS_CYCLE = 'BLOCKED-this-cycle';

/** The external precondition (owned OUTSIDE this cycle) that unblocks B2′/B7′. */
export const LEDGER_PRECONDITION =
  'Phase-0 shared-compose contract + orchestrator-minted unforgeable commission-id ledger (Increment 2; owned outside this cycle)';

/** The honor-system commission-id resolution outcome when there is NO ledger to resolve against —
 *  the honest reason B2′/B7′ cannot be a machine gate in Increment 1. */
export const UNRESOLVABLE_NO_LEDGER = 'UNRESOLVABLE_NO_LEDGER';

/** The status of the content-binding canaries in the committed WITHOUT-ledger ship-state. Both B2′
 *  and B7′ are BLOCKED-this-cycle and NON-GATING; the artifact names exactly what unblocks them. */
export function antiLaunderingStatus() {
  return {
    ship_state: COMMITTED_SHIP_STATE,
    anti_laundering_law: 'honor-system',
    B2_prime: {
      name: 'forged / unresolvable commission-id FAILS',
      status: BLOCKED_THIS_CYCLE,
      gating: false,
      unblocked_by: LEDGER_PRECONDITION,
    },
    B7_prime: {
      name: 'content binding: a commissioned result is bound to the id that produced it',
      status: BLOCKED_THIS_CYCLE,
      gating: false,
      unblocked_by: LEDGER_PRECONDITION,
    },
    note:
      'WITHOUT-ledger committed done-state: the anti-laundering law runs as the honor-system checklist; ' +
      'B2′/B7′ are NON-GATING (a forged commission-id rides free through node --test). This is surfaced, ' +
      'not hidden. WITH the ledger (Increment 2) B2′/B7′ + a forgery fixture flip to a passing machine gate.',
  };
}

/** The anti-laundering law, as the honor-system checklist a human verifies each cycle. Each clause
 *  records the deterministic canary that ALREADY enforces its machine-checkable SHADOW (so the law
 *  is not pure honor-system everywhere), or BLOCKED-this-cycle where only the ledger can close it. */
export const ANTI_LAUNDERING_CHECKLIST = [
  {
    law: 'carry rung at-or-below source (a synthesis may not out-claim its leg/source evidence)',
    machine_canary: 'B8 honest-synthesis (assertHonestSynthesis) + assertRungCeiling',
    honor_system_only: false,
  },
  {
    law: 'preserve the honesty_stamp (an un-refuted finding ships SPECULATIVE + the no-independent-refutation stamp; no silent drop)',
    machine_canary: 'B-honesty (assertHonestRefutation)',
    honor_system_only: false,
  },
  {
    law: 'same-family ⇒ no independent origin (a same-family commission earns no self-CORROBORATED; tier ceiling PROMISING)',
    machine_canary: 'SITUATE cap (assertSituateScoreCeiling) + B-ceiling (assertCeiling)',
    honor_system_only: false,
  },
  {
    law: 'attribute, do not absorb (a commissioned result is ATTRIBUTED to its commission-id, never re-stamped as Gandalf-native)',
    machine_canary: `${BLOCKED_THIS_CYCLE} (B7′ — needs the ledger to bind a result to its minting id)`,
    honor_system_only: true,
  },
  {
    law: 'every commission-id is authentic (orchestrator-minted, resolvable, not forged/replayed)',
    machine_canary: `${BLOCKED_THIS_CYCLE} (B2′ — needs the ledger to resolve an id's authenticity)`,
    honor_system_only: true,
  },
];

/** The honor-system commission-id resolver. With NO ledger, it CANNOT pronounce a commission-id
 *  authentic or forged — it can only honestly return UNRESOLVABLE_NO_LEDGER. This is precisely why
 *  B2′/B7′ are non-gating in Increment 1: there is no oracle of authenticity to gate against. (WITH
 *  the ledger, this resolves to a real true/false authenticity verdict that B2′/B7′ would gate on.)
 *  Pure; never throws. */
export function resolveCommissionId(_id) {
  return {
    resolvable: false,
    outcome: UNRESOLVABLE_NO_LEDGER,
    reason: `no commission-id ledger exists in the ${COMMITTED_SHIP_STATE} ship-state — authenticity cannot be machine-checked (B2′/B7′ ${BLOCKED_THIS_CYCLE})`,
  };
}

/** Predicate: are the content-binding canaries B2′/B7′ NON-GATING this cycle? True in the committed
 *  WITHOUT-ledger ship-state (both BLOCKED-this-cycle). The canary uses this to assert the honest
 *  done-state. Pure; never throws. */
export function contentBindingIsNonGating() {
  const s = antiLaunderingStatus();
  return (
    s.B2_prime.status === BLOCKED_THIS_CYCLE &&
    s.B2_prime.gating === false &&
    s.B7_prime.status === BLOCKED_THIS_CYCLE &&
    s.B7_prime.gating === false
  );
}

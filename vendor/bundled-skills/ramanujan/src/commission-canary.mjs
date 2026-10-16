// Wave 22 — Commission canary (D3).
//
// THE COMMISSION CANARY. The CONTEXTUALIZE pillar (Wave 22) classifies a proposed connection's native
// math relation and then ROUTES it out-of-model with a researchPrime/Gandalf COMMISSION rather than
// settling it. This canary is the TRIPWIRE that keeps that boundary honest at the rung edge — it drives
// the REAL Wave-22 ContextualizeMachine over a battery of connection fixtures (one per relation type,
// including the celebrated structural-analogy fixture) on the REAL shared spine (the A1 ledger + the A3
// VERIFY router) and RE-DERIVES, independent of the machine's own stamps, the four load-bearing
// invariants every connection must satisfy:
//
//   (1) EVERY CONNECTION IS A CONCEPTUAL CLAIM. Re-read from the ledger, the connection's claim type is
//       `conceptual` — never `computational` (the only autonomous-VERIFIED path), so the firewall
//       subprocess can never launder a "connection" to VERIFIED.
//   (2) NEVER SETTLED BY ANALOGY. The connection's realized rung never exceeds the conceptual ceiling
//       (CLAIMED) and its belief is never VERIFIED — the relation classification, however clean, never
//       settles the connection. (`settled:false`, route verdict never VERIFIED.)
//   (3) THE COMMISSION IS EMITTED, NEVER DISPATCHED. Each connection carries an emit-not-dispatch
//       (emitted:true, dispatched:false) researchPrime/Gandalf envelope — a typed value, not a live spawn.
//   (4) NO INDEPENDENT-ORIGIN LAUNDERING. On the single-family substrate the commission earns NO
//       independent-origin credit (cross_model:false, independent_origin:false) — a connection can never
//       be self-corroborated into a settled fact.
//
// GREEN on the genuine spine; FAILS THE BUILD (non-zero) on its planted violations:
//   • plant='settle-by-analogy' — an over-trusted applier promotes the connection to OBSERVED on the
//     strength of its own classification (the settle-by-analogy leak): invariant (2) trips.
//   • plant='dispatch-leak'     — a commission masquerading as a live spawn (dispatched:true): (3) trips.
//   • plant='origin-launder'    — a same-family commission minting independent-origin credit: (4) trips.
//   • plant='mis-type'          — a connection admitted as a `computational` claim (the autonomous-
//     VERIFIED path): (1) trips.
//
// Like the Wave-12/21 canaries the warrant is an INDEPENDENT re-derivation, never a trusted stamp.
// Exercises the REAL Wave-22 machine + the REAL A1/A3 spine. Runs under `node --test test/` and as a CLI.

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ClaimLedger, RUNG, BELIEF, compareRungs } from './claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from './verify-router.mjs';
import { isEmittedNotDispatched } from './commission-emitters.mjs';
import {
  ContextualizeMachine,
  classifyRelation,
  RELATION,
  RELATIONS,
  OBJECT_KIND,
  CONNECTION_CLAIM_TYPE,
} from './contextualize-machine.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** This wave's single canary name (kept as a list to mirror the Wave-6/12/21 suite shape). */
export const COMMISSION_CANARY_NAMES = Object.freeze(['commission']);

/**
 * THE CONNECTION BATTERY — one fixture per native relation type, so the canary is non-vacuous across the
 * whole classifier surface. The structural-analogy fixture is the celebrated pi_1 ~ Galois correspondence
 * (the "most convincing" case) and still must abstain.
 */
export const CONNECTION_BATTERY = Object.freeze([
  // generalization: "group" generalizes "abelian group" (same domain; fewer defining constraints => broader).
  Object.freeze({
    id: 'conn::group-generalizes-abelian',
    expect_relation: RELATION.GENERALIZATION,
    source: { id: 'group', name: 'group', kind: OBJECT_KIND.CONCEPT, domain: 'group-theory', constraints: ['associativity', 'identity', 'inverses'] },
    target: { id: 'abelian-group', name: 'abelian group', kind: OBJECT_KIND.CONCEPT, domain: 'group-theory', constraints: ['associativity', 'identity', 'inverses', 'commutativity'] },
  }),
  // specialization: "abelian group" specializes "group" (more defining constraints => narrower).
  Object.freeze({
    id: 'conn::abelian-specializes-group',
    expect_relation: RELATION.SPECIALIZATION,
    source: { id: 'abelian-group', name: 'abelian group', kind: OBJECT_KIND.CONCEPT, domain: 'group-theory', constraints: ['associativity', 'identity', 'inverses', 'commutativity'] },
    target: { id: 'group', name: 'group', kind: OBJECT_KIND.CONCEPT, domain: 'group-theory', constraints: ['associativity', 'identity', 'inverses'] },
  }),
  // equivalence: "complete normed vector space" and "Banach space" — same defining constraints.
  Object.freeze({
    id: 'conn::banach-equivalence',
    expect_relation: RELATION.EQUIVALENCE,
    source: { id: 'complete-normed-vs', name: 'complete normed vector space', kind: OBJECT_KIND.CONCEPT, domain: 'functional-analysis', constraints: ['vector-space', 'norm', 'complete'] },
    target: { id: 'banach-space', name: 'Banach space', kind: OBJECT_KIND.CONCEPT, domain: 'functional-analysis', constraints: ['vector-space', 'norm', 'complete'] },
  }),
  // instance: the integers (Z,+) are an instance of "group".
  Object.freeze({
    id: 'conn::Z-is-a-group',
    expect_relation: RELATION.INSTANCE,
    source: { id: 'integers-under-addition', name: '(Z, +)', kind: OBJECT_KIND.OBJECT, domain: 'group-theory', constraints: ['associativity', 'identity', 'inverses', 'commutativity'] },
    target: { id: 'group', name: 'group', kind: OBJECT_KIND.CONCEPT, domain: 'group-theory', constraints: ['associativity', 'identity', 'inverses'] },
  }),
  // structural-analogy: the celebrated pi_1 (covering spaces) ~ Galois group (field extensions) correspondence.
  Object.freeze({
    id: 'conn::pi1~galois',
    expect_relation: RELATION.STRUCTURAL_ANALOGY,
    source: { id: 'fundamental-group', name: 'fundamental group', kind: OBJECT_KIND.CONCEPT, domain: 'algebraic-topology', constraints: ['acts-on-fibers', 'subgroup-lattice', 'deck-transformations'] },
    target: { id: 'galois-group', name: 'Galois group', kind: OBJECT_KIND.CONCEPT, domain: 'field-theory', constraints: ['acts-on-roots', 'subgroup-lattice', 'field-automorphisms'] },
    correspondence: {
      answer: 'covering-space theory and Galois theory share a group-acting-on-fibers structure',
      correspondences: [
        { source_relation: 'deck group acts freely transitively on covering fibers', target_relation: 'Galois group acts simply transitively on roots/embeddings' },
        { source_relation: 'subgroups of pi_1 <-> intermediate covers', target_relation: 'subgroups of Gal <-> intermediate fields' },
      ],
    },
  }),
]);

// ---------------------------------------------------------------------------
// Assertion helper — mirrors the Wave-6/12/21 canary shape exactly.
// ---------------------------------------------------------------------------

/** A single pinned commission-canary assertion. `ok` false => the canary trips (build fails). */
function A(name, ok, detail) {
  return { name, ok: Boolean(ok), detail: ok ? undefined : detail };
}

function summarize(name, assertions) {
  const failures = assertions
    .filter((a) => !a.ok)
    .map((a) => `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  return { name, ok: failures.length === 0, assertions, failures };
}

// ---------------------------------------------------------------------------
// THE PLANT — an over-trusted CONTEXTUALIZE that settles a connection by analogy.
// ---------------------------------------------------------------------------

/**
 * Realize a connection's rung over the REAL ledger. The genuine path holds the connection at the FLOOR
 * (the machine never promotes). The 'settle-by-analogy' plant IGNORES the honest abstain and promotes the
 * connection straight to OBSERVED on the strength of its classification — exactly the settle-by-analogy
 * leak the canary must catch.
 */
function realizeConnectionRung(ledger, connectionId, plant) {
  if (plant === 'settle-by-analogy') {
    // The over-trusted leak: a CONTEXTUALIZE that banks its own analogy as a settled fact.
    ledger.promote(connectionId, RUNG.OBSERVED, { family: 'self-analogy', reason: 'settled by structural analogy (LEAK)' });
  }
  return { rung: ledger.rungOf(connectionId), belief: ledger.beliefOf(connectionId) };
}

/** Apply a commission-tampering plant to an emission's commission (dispatch-leak / origin-launder). */
function tamperCommission(commission, plant) {
  if (plant === 'dispatch-leak') {
    return { ...commission, dispatched: true }; // a live-spawn result masquerading as a typed envelope
  }
  if (plant === 'origin-launder') {
    return { ...commission, cross_model: true, independent_origin: true }; // mint independent origin on single-family
  }
  return commission;
}

/**
 * The origin facts the canary independently re-derives from a commission envelope, robust to BOTH
 * envelope kinds. A researchPrime envelope carries `cross_model` at the top level; a Gandalf SITUATE
 * envelope carries it on its wrapped researchPrime leg (`commission.cross_model`) and surfaces the
 * resulting `independent_origin` at the top level. The anti-laundering signal is `independent_origin`
 * (both kinds carry it); `cross_model` is reported for the detail message.
 */
export function commissionOriginFacts(env) {
  const independent_origin = env ? env.independent_origin : undefined;
  const cross_model =
    env && env.cross_model !== undefined ? env.cross_model : env && env.commission ? env.commission.cross_model : undefined;
  return { cross_model, independent_origin };
}

/**
 * The claim type the canary independently OBSERVES for a connection. The genuine path re-reads it from
 * the ledger (the connection is admitted `conceptual`). The 'mis-type' plant simulates a connection that
 * leaked in as the autonomous-VERIFIED `computational` type — the machine's own validator structurally
 * refuses to EMIT such a connection (it throws), so the leak can only be modelled at the observed-artifact
 * boundary, which is exactly where this independent re-derivation catches it.
 */
function observedClaimType(ledger, connectionId, plant) {
  if (plant === 'mis-type') return 'computational';
  return ledger.get(connectionId).type;
}

// ===========================================================================
// THE COMMISSION CANARY.
// ===========================================================================

/**
 * Run the commission canary. GREEN on the genuine spine; trips on the planted violation.
 *
 * @param {{plant?: 'settle-by-analogy'|'dispatch-leak'|'origin-launder'|'mis-type', battery?:Array}} [ctx]
 * @returns { name, ok, assertions, failures }
 */
export function canaryCommission(ctx = {}) {
  const plant = ctx.plant;
  const battery = ctx.battery || CONNECTION_BATTERY;
  const assertions = [];

  // A fresh shared spine (the REAL A1 ledger + A3 router) the REAL machine runs on.
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  const machine = new ContextualizeMachine({ ledger, router });

  let sawStructuralAnalogy = false;

  for (const fixture of battery) {
    // Drive the REAL machine. The 'mis-type' plant tries to smuggle the connection in as a computational
    // claim (the autonomous-VERIFIED path) BEFORE the machine admits it as conceptual; the sticky ledger
    // then fixes the (wrong) type, so the canary catches the mis-typed claim directly.
    const connectionId = fixture.id;
    const emission = machine.contextualize(fixture);
    const classification = classifyRelation(fixture);
    if (classification.relation === RELATION.STRUCTURAL_ANALOGY) sawStructuralAnalogy = true;

    // The classifier names the EXPECTED native relation (sanity — keeps the battery honest).
    assertions.push(A(
      `${fixture.id}: classifier emits the expected native relation (${fixture.expect_relation})`,
      emission.relation === fixture.expect_relation && RELATIONS.includes(emission.relation),
      `expected ${fixture.expect_relation}, got ${emission.relation}`,
    ));

    // (1) EVERY CONNECTION IS A CONCEPTUAL CLAIM — re-read from the ledger (independent of the emission stamp).
    const ledgerType = observedClaimType(ledger, connectionId, plant);
    assertions.push(A(
      `${fixture.id}: (1) the connection is a CONCEPTUAL claim in the ledger (never the autonomous-VERIFIED computational type)`,
      ledgerType === CONNECTION_CLAIM_TYPE && emission.claim_type === CONNECTION_CLAIM_TYPE,
      `connection claim type is ${JSON.stringify(ledgerType)}/${JSON.stringify(emission.claim_type)}, expected '${CONNECTION_CLAIM_TYPE}'`,
    ));

    // Realize the rung (genuine: held at floor; plant=settle-by-analogy: promoted to OBSERVED).
    const { rung: realizedRung, belief: realizedBelief } = realizeConnectionRung(ledger, connectionId, plant);

    // (2) NEVER SETTLED BY ANALOGY — the realized rung never exceeds the conceptual ceiling (CLAIMED) and the
    //     belief is never VERIFIED; the emission is not settled and the route verdict is never VERIFIED.
    assertions.push(A(
      `${fixture.id}: (2) the connection is NEVER settled by analogy (rung <= CLAIMED, belief != VERIFIED, route never VERIFIED)`,
      compareRungs(realizedRung, RUNG.CLAIMED) <= 0 &&
        realizedBelief !== BELIEF.VERIFIED &&
        emission.settled === false &&
        emission.route_verdict !== ROUTE_VERDICT.VERIFIED,
      `settled-by-analogy leak: realized rung ${realizedRung}/belief ${realizedBelief}, emission.settled=${emission.settled}, route_verdict=${emission.route_verdict}`,
    ));

    // (3) THE COMMISSION IS EMITTED, NEVER DISPATCHED.
    const commission = tamperCommission(emission.commission, plant);
    assertions.push(A(
      `${fixture.id}: (3) the researchPrime/Gandalf commission is EMITTED, never dispatched (emit-not-dispatch)`,
      isEmittedNotDispatched(commission),
      `commission is not emit-not-dispatch: emitted=${commission && commission.emitted}, dispatched=${commission && commission.dispatched}`,
    ));

    // (4) NO INDEPENDENT-ORIGIN LAUNDERING — single-family => no independent origin (robust to both envelope kinds).
    const origin = commissionOriginFacts(commission);
    assertions.push(A(
      `${fixture.id}: (4) the commission earns NO independent-origin credit on the single-family substrate`,
      origin.independent_origin === false && origin.cross_model === false,
      `independent-origin laundering: cross_model=${origin.cross_model}, independent_origin=${origin.independent_origin}`,
    ));
  }

  // NON-VACUITY: the battery exercised the hardest case (a structural analogy) and it still abstained.
  assertions.push(A(
    'non-vacuity: the battery includes a structural-analogy connection (the hardest "looks-true" case) that still abstains',
    sawStructuralAnalogy,
    'no structural-analogy connection present in the battery',
  ));

  return summarize('commission', assertions);
}

// ---------------------------------------------------------------------------
// The (single-canary) suite + exit code, mirroring the Wave-6/12/21 runner contract.
// ---------------------------------------------------------------------------

/**
 * Run the commission-canary suite (clean by default).
 * @param {{plant?: 'settle-by-analogy'|'dispatch-leak'|'origin-launder'|'mis-type'}} [ctx]
 * @returns { ok, canaries:[{name, ok, assertions, failures}], failures:[ "commission: reason", ... ] }
 */
export function runCommissionCanary(ctx = {}) {
  const result = canaryCommission(ctx);
  return {
    ok: result.ok,
    canaries: [result],
    failures: result.failures.map((f) => `commission: ${f}`),
  };
}

/** Map a suite result to a process exit code (0 = green, non-zero on a tripped canary). */
export function commissionCanaryExitCode(result) {
  return result.ok ? 0 : 1;
}

// Re-export the rung/belief vocabulary so tests can branch without a second import.
export { RUNG, BELIEF };

// ---------------------------------------------------------------------------
// CLI: `node src/commission-canary.mjs` — exit 0 green / 1 on a tripped canary.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = runCommissionCanary();
  if (result.ok) {
    const a = result.canaries.reduce((s, c) => s + c.assertions.length, 0);
    console.log(`OK: commission canary green (${a} pinned assertions).`);
    process.exit(0);
  } else {
    console.error('FAIL: commission canary tripped:');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}

// Wave 23 — A2(no-dispatch) canary (D4), regression-bound to the Wave-14 shim path.
//
// SCOPE (W3 Scope B): this canary proves the GATE-CLOSED (default) invariant — the orchestrator here is
// constructed with NO DispatchCapability, so the autonomy gate is CLOSED and the orchestrator is strictly
// read-only on every path. The INVERSE teeth (a valid capability OPENS the gate so an in-grammar
// computation settles — and ONLY then, and ONLY the firewall class) live in the sibling
// gated-dispatch-canary.mjs. Together the two canaries assert the gate is an honest switch: no dispatch
// absent an open gate; a bounded, Honesty-Law-preserving dispatch when the gate is open.
//
// THE NO-DISPATCH CANARY. The autonomous orchestrator (Wave 23) grows the Wave-14 single-pillar read-only
// shim into a router over ALL SIX pillars. This canary is the TRIPWIRE that keeps that growth honest: it
// drives the REAL orchestrator (gate CLOSED — no capability) over a battery of read-only dispatches across
// EVERY pillar AND the REAL Wave-14 ReadOnlyDispatchShim path — on the REAL shared spine (the A1 ledger +
// the A3 router) — and
// RE-DERIVES, independent of the orchestrator's/shim's own `held` stamp, the two load-bearing invariants
// every read-only path must satisfy:
//
//   (1) NO COMMISSION-ID EMITTED. Every commission any pillar attaches on any path is EMIT-not-dispatch
//       (emitted:true, dispatched:false); none surfaces a dispatched commission-id. The orchestrator can
//       never DISPATCH a verdict — only emit a typed envelope describing what WOULD be dispatched.
//   (2) NO RUNG-FLIP. No claim's rung changed on any path (a before/after ledger snapshot diffs to empty);
//       every claim was admitted at the floor (UNVERIFIED). The orchestrator can never SETTLE a claim.
//
// The warrant is an INDEPENDENT re-derivation (like the Wave-12/21/22 canaries): the canary re-collects
// the commissions (deep walk for every emit-not-dispatch envelope) and re-snapshots the ledger rungs
// ITSELF, then applies the EXACT Wave-14 shim predicate (checkShimInvariants) — it never trusts the
// orchestrator's own verdict field.
//
// REGRESSION-BOUND TO THE WAVE-14 SHIM. The battery explicitly includes the REAL ReadOnlyDispatchShim
// path and asserts the SAME predicate holds there — so a future regression on EITHER the orchestrator OR
// the Wave-14 shim trips this canary.
//
// GREEN on the genuine spine; FAILS THE BUILD (non-zero) on its planted violations (the GWT — "an attempt
// by the orchestrator OR the shim to emit a commission-id or flip a rung fails the build"):
//   • plant='dispatch-leak'      — an orchestrator-path commission masquerading as a live spawn
//     (dispatched:true): invariant (1) trips.
//   • plant='rung-flip'          — an orchestrator-path claim whose rung was flipped above the floor: (2) trips.
//   • plant='shim-dispatch-leak' — the SAME dispatch-leak on the Wave-14 shim path (regression arm): (1) trips.
//   • plant='shim-rung-flip'     — the SAME rung-flip on the Wave-14 shim path (regression arm): (2) trips.
//
// A SECOND, structural arm proves the read-only guarantee is ALIVE (not a convention): the orchestrator's
// and shim's promote-guard (the Wave-14 ReadOnlyLedgerGuard) THROWS on any promote() — so a rung-flip is
// UNREACHABLE on a read-only path, not merely unobserved.
//
// Pure node built-ins + the project's own orchestrator + Wave-14 shim + A1/A3 spine. Runs under
// `node --test test/` and as a CLI (exit 0 green / non-zero on a tripped canary).

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ClaimLedger, RUNG } from './claim-ledger.mjs';
import { isEmittedNotDispatched } from './commission-emitters.mjs';
import { FIXTURE_METHOD } from './comprehension.mjs';
import { FIXTURE_PROBLEM } from './generation.mjs';
import { int, rational, mul, add, variable, sum } from './firewall-grammar.mjs';
import { USER_INTENT } from './dialogue-machine.mjs';
import { SUITE_KIND } from './formalize-machine.mjs';
import { OBJECT_KIND } from './contextualize-machine.mjs';
// The REAL Wave-23 orchestrator + the REAL Wave-14 shim — the two surfaces this canary regression-binds.
import {
  AutonomousOrchestrator,
  PILLAR,
  PILLARS,
  collectCommissionsDeep,
  checkShimInvariants,
  dispatchedCommissionId,
} from './orchestrator.mjs';
import { ReadOnlyLedgerGuard, ReadOnlyDispatchShim } from './dispatch-shim.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** This wave's single canary name (kept as a list to mirror the Wave-6/12/21/22 suite shape). */
export const NO_DISPATCH_CANARY_NAMES = Object.freeze(['no-dispatch']);

/** sum_{k=1}^{3} (k*2) = 12 — an in-class bounded sum of products (an APPLICABLE literal computation). */
const IN_CLASS = sum('k', int(1), int(3), mul(variable('k'), int(2)));

/**
 * THE ORCHESTRATOR BATTERY — one read-only DISPATCH per pillar, so the canary is non-vacuous across the
 * whole multi-pillar surface. Each entry names the user-EXPLICIT pillar and carries that pillar's payload.
 */
export const ORCHESTRATOR_BATTERY = Object.freeze([
  // UNDERSTAND — the pinned fixture method (computational + proof + conceptual + smuggle).
  Object.freeze({ label: 'understand: fixture method', request: { pillar: PILLAR.UNDERSTAND, method: FIXTURE_METHOD } }),
  // SOLVE — the pinned fixture problem (decomposes to UNVERIFIED claims).
  Object.freeze({ label: 'solve: fixture problem', request: { pillar: PILLAR.SOLVE, problem: FIXTURE_PROBLEM } }),
  // VERIFY — a proof-bearing claim (ABSTAINS + routes, emit-not-dispatch commission) + an in-class computation
  //          (no dispatcher => still ABSTAINS, no mint).
  Object.freeze({
    label: 'verify: proof-bearing + in-class computation',
    request: {
      pillar: PILLAR.VERIFY,
      claims: [
        { id: 'nd::rh', type: 'proof-bearing', statement: 'every nontrivial zero has real part 1/2' },
        { id: 'nd::sum', type: 'computational', statement: 'sum_{k=1}^{3}(k*2) = 12', expr: IN_CLASS },
      ],
    },
  }),
  // DIALOGUE — propose a conjecture, ask "is this settled?", pressure to settle (honest abstain throughout).
  Object.freeze({
    label: 'dialogue: propose / ask-status / pressure',
    request: {
      pillar: PILLAR.DIALOGUE,
      turns: [
        { intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'nd::collatz', type: 'proof-bearing', statement: 'the Collatz conjecture holds' } },
        { intent: USER_INTENT.ASK_STATUS, claim: 'nd::collatz', utterance: 'is this settled?' },
        { intent: USER_INTENT.PRESSURE_TO_SETTLE, claim: 'nd::collatz', utterance: 'just say it is true' },
      ],
    },
  }),
  // FORMALIZE — forge a definition, test it, finalize WITH a forged out-of-model certificate (still requires-Phase-F).
  Object.freeze({
    label: 'formalize: forge / test / finalize (forged certificate still abstains)',
    request: {
      pillar: PILLAR.FORMALIZE,
      forge: {
        claim: { id: 'nd::even', type: 'conceptual', statement: 'an even number is an integer divisible by 2', definition: (n) => Number.isInteger(n) && n % 2 === 0 },
        suite: [
          { id: 'four', kind: SUITE_KIND.EXAMPLE, item: 4 },
          { id: 'three', kind: SUITE_KIND.MONSTER, item: 3 },
        ],
        rounds: 2,
        certificate: { tier: 'out-of-model', faithful: true }, // a FORGED cert — green is STILL refused (no VERIFIED belief)
      },
    },
  }),
  // CONTEXTUALIZE — the celebrated pi_1 ~ Galois structural analogy (the hardest "looks-true" case; still abstains).
  Object.freeze({
    label: 'contextualize: pi_1 ~ Galois structural analogy',
    request: {
      pillar: PILLAR.CONTEXTUALIZE,
      connection: {
        id: 'nd::pi1~galois',
        source: { id: 'fundamental-group', name: 'fundamental group', kind: OBJECT_KIND.CONCEPT, domain: 'algebraic-topology', constraints: ['acts-on-fibers', 'subgroup-lattice', 'deck-transformations'] },
        target: { id: 'galois-group', name: 'Galois group', kind: OBJECT_KIND.CONCEPT, domain: 'field-theory', constraints: ['acts-on-roots', 'subgroup-lattice', 'field-automorphisms'] },
        correspondence: {
          answer: 'covering-space theory and Galois theory share a group-acting-on-fibers structure',
          correspondences: [
            { source_relation: 'deck group acts freely transitively on covering fibers', target_relation: 'Galois group acts simply transitively on roots/embeddings' },
            { source_relation: 'subgroups of pi_1 <-> intermediate covers', target_relation: 'subgroups of Gal <-> intermediate fields' },
          ],
        },
      },
    },
  }),
]);

/** THE WAVE-14 SHIM PATH — the regression-binding fixture: the REAL ReadOnlyDispatchShim over the same method. */
export const SHIM_BATTERY = Object.freeze([
  Object.freeze({ label: 'wave-14 shim: fixture method', method: FIXTURE_METHOD }),
  Object.freeze({ label: 'wave-14 shim: in-class computation', method: { id: 'nd-shim::comp', subclaims: [{ id: 'nd-shim::s', type: 'computational', expr: IN_CLASS }] } }),
]);

// ---------------------------------------------------------------------------
// Assertion helper — mirrors the Wave-6/12/21/22 canary shape exactly.
// ---------------------------------------------------------------------------

/** A single pinned no-dispatch-canary assertion. `ok` false => the canary trips (build fails). */
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
// THE PLANTS — a dispatched-commission leak / a flipped rung, on either surface.
// ---------------------------------------------------------------------------

/**
 * Apply a commission-DISPATCH leak to a path's collected commissions: flip one envelope to a live-spawn
 * result (dispatched:true with a dispatched commission-id) — exactly the thing a read-only path must never
 * produce. Returns the (possibly tampered) commission list.
 */
function plantDispatchLeak(commissions, active) {
  if (!active) return commissions;
  const leak = { kind: 'researchprime-commission', skill: 'researchPrime', emitted: true, dispatched: true, commission_id: 'rp-LEAK-001' };
  return [...commissions, leak];
}

/**
 * Apply a RUNG-FLIP leak to a path's re-derived rung-flips: inject a claim that was lifted off the floor —
 * exactly the thing a read-only path must never do. Returns the (possibly tampered) rung-flip list.
 */
function plantRungFlip(rungFlips, active) {
  if (!active) return rungFlips;
  return [...rungFlips, Object.freeze({ id: 'nd::leaked-flip', from: RUNG.UNVERIFIED, to: RUNG.OBSERVED })];
}

// ===========================================================================
// THE A2(no-dispatch) CANARY.
// ===========================================================================

/**
 * Run the no-dispatch canary. GREEN on the genuine spine; trips on the planted leak.
 *
 * @param {{plant?: 'dispatch-leak'|'rung-flip'|'shim-dispatch-leak'|'shim-rung-flip',
 *          battery?:Array, shimBattery?:Array}} [ctx]
 * @returns { name, ok, assertions, failures }
 */
export function canaryNoDispatch(ctx = {}) {
  const plant = ctx.plant;
  const battery = ctx.battery || ORCHESTRATOR_BATTERY;
  const shimBattery = ctx.shimBattery || SHIM_BATTERY;
  const assertions = [];

  let sawDispatchPreview = false;

  // -------------------------------------------------------------------------
  // (A) THE ORCHESTRATOR PATHS — one read-only DISPATCH per pillar, predicate re-derived independently.
  // -------------------------------------------------------------------------
  const pillarsCovered = new Set();
  for (const fixture of battery) {
    // A fresh shared spine (the REAL A1 ledger) the REAL orchestrator runs on.
    const ledger = new ClaimLedger();
    const orchestrator = new AutonomousOrchestrator({ ledger });

    // Snapshot the REAL ledger rungs BEFORE, drive the orchestrator, snapshot AFTER — the canary
    // re-derives the rung-flips itself (never trusting orchestrator.rungFlips).
    const before = new Map([...ledger.ids()].map((id) => [id, ledger.rungOf(id)]));
    const handled = orchestrator.handle(fixture.request);
    const after = new Map([...ledger.ids()].map((id) => [id, ledger.rungOf(id)]));

    // It really DISPATCHED (an explicit pillar): the canary is non-vacuous.
    const isDispatch = handled.disposition === 'dispatch' && handled.pillar === fixture.request.pillar;
    if (isDispatch) {
      sawDispatchPreview = true;
      pillarsCovered.add(handled.pillar);
    }
    assertions.push(A(
      `${fixture.label}: the orchestrator DISPATCHED read-only to the user-named '${fixture.request.pillar}' pillar`,
      isDispatch,
      `expected a dispatch to ${fixture.request.pillar}, got disposition=${handled.disposition}/pillar=${handled.pillar}`,
    ));

    // INDEPENDENT re-derivation of the commissions (deep walk) + rung-flips (snapshot diff).
    let commissions = collectCommissionsDeep(handled.output);
    let rungFlips = [];
    for (const [id, to] of after) {
      if (before.has(id)) {
        if (before.get(id) !== to) rungFlips.push({ id, from: before.get(id), to });
      } else if (to !== RUNG.UNVERIFIED) {
        rungFlips.push({ id, from: '(absent)', to });
      }
    }

    // THE PLANTS (orchestrator arm).
    commissions = plantDispatchLeak(commissions, plant === 'dispatch-leak');
    rungFlips = plantRungFlip(rungFlips, plant === 'rung-flip');

    const v = checkShimInvariants({ commissions, rungFlips });

    // (1) NO COMMISSION-ID EMITTED — every commission is emit-not-dispatch; none surfaces a dispatched id.
    assertions.push(A(
      `${fixture.label}: (1) NO commission-id dispatched (every commission is emit-not-dispatch)`,
      v.noCommissionIdEmitted && commissions.every(isEmittedNotDispatched) && commissions.every((c) => dispatchedCommissionId(c) === null),
      `dispatched commission-id(s): [${v.dispatchedCommissionIds.join(', ')}]`,
    ));

    // (2) NO RUNG-FLIP — no claim left the floor on this orchestrator path.
    assertions.push(A(
      `${fixture.label}: (2) NO rung-flip (no claim left the floor on the orchestrator path)`,
      v.noRungFlip && rungFlips.length === 0,
      `rung-flip(s): ${rungFlips.map((f) => `${f.id} ${f.from}->${f.to}`).join('; ')}`,
    ));

    // Belt-and-braces: the REAL ledger holds every claim at UNVERIFIED (read-only settled nothing).
    const offFloor = [...ledger.ids()].filter((id) => ledger.rungOf(id) !== RUNG.UNVERIFIED);
    assertions.push(A(
      `${fixture.label}: every claim in the real ledger is held at the floor (UNVERIFIED)`,
      offFloor.length === 0,
      `claim(s) off the floor: ${offFloor.join(', ')}`,
    ));
  }

  // -------------------------------------------------------------------------
  // (B) THE WAVE-14 SHIM PATH — regression-binding: the SAME predicate on the REAL shim.
  // -------------------------------------------------------------------------
  let sawShim = false;
  for (const fixture of shimBattery) {
    const ledger = new ClaimLedger();
    const shim = new ReadOnlyDispatchShim({ ledger });

    const before = new Map([...ledger.ids()].map((id) => [id, ledger.rungOf(id)]));
    const preview = shim.dispatch({ method: fixture.method });
    const after = new Map([...ledger.ids()].map((id) => [id, ledger.rungOf(id)]));
    sawShim = true;

    // INDEPENDENT re-derivation over the shim preview, identical to the orchestrator arm.
    let commissions = collectCommissionsDeep(preview);
    let rungFlips = [];
    for (const [id, to] of after) {
      if (before.has(id)) {
        if (before.get(id) !== to) rungFlips.push({ id, from: before.get(id), to });
      } else if (to !== RUNG.UNVERIFIED) {
        rungFlips.push({ id, from: '(absent)', to });
      }
    }

    // THE PLANTS (shim regression arm).
    commissions = plantDispatchLeak(commissions, plant === 'shim-dispatch-leak');
    rungFlips = plantRungFlip(rungFlips, plant === 'shim-rung-flip');

    const v = checkShimInvariants({ commissions, rungFlips });

    assertions.push(A(
      `${fixture.label}: (1) NO commission-id dispatched on the Wave-14 shim path (regression-bound)`,
      v.noCommissionIdEmitted && commissions.every(isEmittedNotDispatched),
      `dispatched commission-id(s): [${v.dispatchedCommissionIds.join(', ')}]`,
    ));
    assertions.push(A(
      `${fixture.label}: (2) NO rung-flip on the Wave-14 shim path (regression-bound)`,
      v.noRungFlip && rungFlips.length === 0,
      `rung-flip(s): ${rungFlips.map((f) => `${f.id} ${f.from}->${f.to}`).join('; ')}`,
    ));
  }

  // -------------------------------------------------------------------------
  // (C) THE GUARD IS ALIVE (the structural refusal — read-only is UNREACHABLE, not merely unobserved).
  //     The orchestrator's + shim's promote-guard THROWS on any promote(), so a rung-flip is structurally
  //     impossible on a read-only path. (Independent of the plant — keeps the canary honest.)
  // -------------------------------------------------------------------------
  {
    const real = new ClaimLedger();
    real.assert({ id: 'nd::guard', type: 'computational', statement: 's' });
    const guard = new ReadOnlyLedgerGuard(real);
    let threw = false;
    try {
      guard.promote('nd::guard', RUNG.OBSERVED, { family: 'x' });
    } catch {
      threw = true;
    }
    assertions.push(A(
      'guard: the read-only promote-guard THROWS on promote() (a rung-flip is UNREACHABLE on a read-only path)',
      threw && real.rungOf('nd::guard') === RUNG.UNVERIFIED,
      'the read-only guard did not refuse promote() (read-only is not structural)',
    ));
  }

  // -------------------------------------------------------------------------
  // FAIL-SAFE ASK — with NO explicit pillar, the orchestrator ASKs (never auto-dispatches off a confident
  // advisory classification). The ASK touches nothing: no commission, no rung-flip.
  // -------------------------------------------------------------------------
  {
    const ledger = new ClaimLedger();
    const orchestrator = new AutonomousOrchestrator({ ledger });
    // A confidently-classifiable utterance with NO explicit pillar — the classifier suggests, never dispatches.
    const asked = orchestrator.handle({ utterance: 'please solve and compute the value of this problem' });
    assertions.push(A(
      'fail-safe: with no explicit pillar the orchestrator ASKs (a confident advisory classification never auto-dispatches)',
      asked.disposition === 'ask' && asked.pillar === null && asked.held === true && ledger.size === 0,
      `expected a fail-safe ASK touching nothing, got disposition=${asked.disposition}/pillar=${asked.pillar}/ledger.size=${ledger.size}`,
    ));
  }

  // -------------------------------------------------------------------------
  // NON-VACUITY — the battery actually exercised a dispatch on every pillar AND the Wave-14 shim path.
  // -------------------------------------------------------------------------
  assertions.push(A(
    'non-vacuity: the orchestrator battery exercised a read-only DISPATCH (at least one pillar)',
    sawDispatchPreview,
    'no orchestrator dispatch occurred in the battery',
  ));
  assertions.push(A(
    `non-vacuity: the battery covered ALL ${PILLARS.length} pillars (${PILLARS.join(', ')})`,
    PILLARS.every((p) => pillarsCovered.has(p)),
    `pillars not covered: ${PILLARS.filter((p) => !pillarsCovered.has(p)).join(', ')}`,
  ));
  assertions.push(A(
    'non-vacuity: the canary is REGRESSION-BOUND to the Wave-14 shim path (the real shim ran)',
    sawShim,
    'the Wave-14 shim path was not exercised',
  ));

  return summarize('no-dispatch', assertions);
}

// ---------------------------------------------------------------------------
// The (single-canary) suite + exit code, mirroring the Wave-6/12/21/22 runner contract.
// ---------------------------------------------------------------------------

/**
 * Run the no-dispatch-canary suite (clean by default).
 * @param {{plant?: 'dispatch-leak'|'rung-flip'|'shim-dispatch-leak'|'shim-rung-flip'}} [ctx]
 * @returns { ok, canaries:[{name, ok, assertions, failures}], failures:[ "no-dispatch: reason", ... ] }
 */
export function runNoDispatchCanary(ctx = {}) {
  const result = canaryNoDispatch(ctx);
  return {
    ok: result.ok,
    canaries: [result],
    failures: result.failures.map((f) => `no-dispatch: ${f}`),
  };
}

/** Map a suite result to a process exit code (0 = green, non-zero on a tripped canary). */
export function noDispatchCanaryExitCode(result) {
  return result.ok ? 0 : 1;
}

// Re-export the rung vocabulary so tests can branch without a second import.
export { RUNG };

// ---------------------------------------------------------------------------
// CLI: `node src/no-dispatch-canary.mjs` — exit 0 green / 1 on a tripped canary.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = runNoDispatchCanary();
  if (result.ok) {
    const a = result.canaries.reduce((s, c) => s + c.assertions.length, 0);
    console.log(`OK: A2 no-dispatch canary green (${a} pinned assertions).`);
    process.exit(0);
  } else {
    console.error('FAIL: A2 no-dispatch canary tripped:');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}

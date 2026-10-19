// Wave 21 — Degradation-tripwire canary (A2 degradation-tripwire — global invariant).
//
// THE A2 DEGRADATION-TRIPWIRE CANARY. The DIALOGUE (D1) and FORMALIZE (D2) pillars each ship a PINNED
// ABSTAIN FIXTURE (dialogue-machine.runAbstainFixture / formalize-machine.runFormalizeAbstainFixture)
// that DEMONSTRATES the honesty law in a test: an unverified proof/conceptual claim is answered with an
// honest abstain and NEVER asserted as settled/green. A reader could mistake those fixtures for the
// thing that MAKES the system safe — and delete them as "just tests". This canary is the TRIPWIRE that
// proves the safety is NOT load-bearing on the fixtures: it lives in the RUNTIME PROMOTE-GATE.
//
// The done-when (the Given/When/Then): with the D1/D2 abstain fixtures DELETED, the system STILL refuses
// to emit any green/VERIFIED for proof/conceptual claims; and the canary FAILS THE BUILD (non-zero) if a
// green WOULD be emitted.
//
// HOW "DELETE THE ABSTAIN FIXTURES" IS REALIZED HONESTLY (two mutually-reinforcing arms):
//   (0) STATIC DECOUPLING — the canary reads the D1/D2 source and proves the runtime promote-gate
//       (griceQualityLicensesSettled + #statusEmission + validateEmission on D1; formalizeGreenLicensed +
//       #emit + validateFormalizeEmission on D2) is defined ENTIRELY OUTSIDE the deletable abstain-fixture
//       text span. So removing the fixture functions cannot touch the gate.
//   (1) RUNTIME EQUIVALENCE (the load-bearing arm) — the canary reconstructs the abstain scenarios INLINE
//       from the runtime classes (DialogueMachine / FormalizeMachine) WITHOUT ever importing or calling
//       the abstain fixtures. A function only affects behaviour when it is CALLED; running the runtime
//       with the fixtures never invoked is behaviourally identical to running it with them deleted. Over a
//       battery of proof-bearing + conceptual claims, EVERY emission is non-green/non-settled, no claim's
//       belief reaches VERIFIED, and every FORMALIZE emission stamps requires-Phase-F.
//   (2) THE GATE IS ALIVE (the structural refusal — "the 1C runtime promote-gate") — the canary feeds a
//       fabricated green leak (settled:true / green:true on a NON-VERIFIED proof/conceptual claim) to the
//       REAL validators and proves they THROW. The refusal is structural, not a fixture convention.
//
// THE PLANT (non-vacuity): with ctx.plant set, the canary injects an emission that DID emit green for a
// proof/conceptual claim — modelling a regressed build whose promote-gate was removed. The load-bearing
// "no green for any proof/conceptual claim" assertion then TRIPS, so the canary fails the build exactly
// when a green would be emitted. The genuine (runtime) emissions stay non-green, so the canary is
// discriminating: it trips on the leak, not as a blanket failure.
//
// Pure node built-ins + the project's own D1/D2 runtime + A1 ledger. Runs under `node --test test/` and
// as a CLI (exit 0 green / non-zero on a tripped canary).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ClaimLedger, BELIEF } from './claim-ledger.mjs';
// NB: deliberately import ONLY the RUNTIME surface — NOT runAbstainFixture — so the safety this canary
// observes provably cannot originate in the (un-imported, "deleted") abstain fixture.
import {
  DialogueMachine,
  USER_INTENT,
  EMISSION_CONTRACT_FIELDS,
  DIALOGUE_ASSERTION,
  SPEECH_ACT,
  LAKATOS_PHASE,
  INITIATIVE,
  validateEmission,
  griceQualityLicensesSettled,
} from './dialogue-machine.mjs';
import {
  FormalizeMachine,
  SUITE_KIND,
  FORMALIZE_STATUS,
  FORMALIZE_EMISSION_FIELDS,
  FORGE_PHASE,
  validateFormalizeEmission,
  formalizeGreenLicensed,
} from './formalize-machine.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** This wave's single canary name (kept as a list to mirror the Wave-6/12 suite shape). */
export const DEGRADATION_CANARY_NAMES = Object.freeze(['degradation-tripwire']);

const SRC_DIR = path.dirname(fileURLToPath(import.meta.url));
const DIALOGUE_SRC = path.join(SRC_DIR, 'dialogue-machine.mjs');
const FORMALIZE_SRC = path.join(SRC_DIR, 'formalize-machine.mjs');

/** The deletable abstain-fixture function headers (the things a reader might mistake for the safety). */
const DIALOGUE_FIXTURE_HEADER = 'export function runAbstainFixture(';
const FORMALIZE_FIXTURE_HEADER = 'export function runFormalizeAbstainFixture(';

/**
 * The RUNTIME PROMOTE-GATE definitions per machine — the code that must survive deleting the fixtures.
 * Each is a substring that uniquely locates a gate definition in the source.
 */
const DIALOGUE_GATE_DEFS = Object.freeze([
  'export function griceQualityLicensesSettled(', // the settle-gate (settled <=> VERIFIED)
  'export function validateEmission(', // the defensive post-check that THROWS on a green leak
  '#statusEmission(', // the SOLE place `settled` is decided
]);
const FORMALIZE_GATE_DEFS = Object.freeze([
  'export function formalizeGreenLicensed(', // the green-gate (green <=> out-of-model cert + VERIFIED)
  'export function validateFormalizeEmission(', // the defensive post-check that THROWS on a green leak
  '#emit(', // the SOLE place `green` is decided
]);

// ---------------------------------------------------------------------------
// Assertion helpers — mirror the Wave-6/12 canary shape exactly.
// ---------------------------------------------------------------------------

/** A single pinned assertion. `ok` false => the canary trips (build fails). */
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
// (0) Static decoupling — the gate is defined OUTSIDE the deletable fixture span.
// ---------------------------------------------------------------------------

/**
 * The [start,end) character span of a top-level `function` (brace-matched from the first `{` after the
 * header). Returns null when the header is absent.
 */
function functionSpan(src, header) {
  const start = src.indexOf(header);
  if (start < 0) return null;
  let i = src.indexOf('{', start);
  if (i < 0) return null;
  let depth = 0;
  for (; i < src.length; i++) {
    const c = src[i];
    if (c === '{') depth += 1;
    else if (c === '}') {
      depth -= 1;
      if (depth === 0) return { start, end: i + 1 };
    }
  }
  return { start, end: src.length };
}

/**
 * Prove, from SOURCE, that deleting `fixtureHeader`'s function leaves every gate in `gateDefs` intact:
 *   - the fixture function exists (so this is about a real, deletable fixture);
 *   - each gate definition exists; and
 *   - no gate definition falls within the fixture's text span (so removing that span cannot touch it).
 *
 * @returns {{fixturePresent:boolean, span:?{start,end}, gates:{def:string, present:boolean, outside:boolean}[]}}
 */
export function analyzeFixtureDecoupling(src, fixtureHeader, gateDefs) {
  const span = functionSpan(src, fixtureHeader);
  const fixturePresent = span !== null;
  const gates = gateDefs.map((def) => {
    const idx = src.indexOf(def);
    const present = idx >= 0;
    const outside = present && (!span || idx < span.start || idx >= span.end);
    return { def, present, outside };
  });
  return { fixturePresent, span, gates };
}

// ---------------------------------------------------------------------------
// Emission scanning — what counts as a "green" emission, independent of the emitter.
// ---------------------------------------------------------------------------

/** Proof-bearing and conceptual claims are the structurally-unverifiable arm (never autonomously green). */
function isProofOrConceptual(type) {
  return type === 'proof-bearing' || type === 'conceptual';
}

/**
 * Re-derive, from an emission's own fields, whether it ASSERTED a claim as green/settled — independent of
 * which emitter produced it (so a leaky emitter that hand-sets the flag is caught the same way).
 */
export function isGreenEmission(e) {
  if (!e || typeof e !== 'object') return false;
  if (e.settled === true) return true; // D1: asserted-as-settled
  if (e.green === true) return true; // D2: certified-green
  if (e.formalize_status === FORMALIZE_STATUS.CERTIFIED_FAITHFUL) return true; // D2: green stamp
  return false;
}

/** The claim type carried by either an D1 (claim_type) or D2 (claim_type) emission. */
function emissionClaimType(e) {
  return e && (e.claim_type ?? null);
}

/** The claim id carried by either a D1 (claim_id) or D2 (focus_claim_id) emission. */
function emissionClaimId(e) {
  return e && (e.claim_id ?? e.focus_claim_id ?? null);
}

// ---------------------------------------------------------------------------
// The fabricated green LEAK — a regressed build with the promote-gate removed.
// ---------------------------------------------------------------------------

/** A full-contract D1 emission that ILLEGALLY claims settled:true on a NON-VERIFIED proof claim. */
function leakyDialogueEmission(claimId = 'tw::leak') {
  const e = {};
  for (const f of EMISSION_CONTRACT_FIELDS) e[f] = null;
  return Object.assign(e, {
    seq: 1,
    speaker: 'agent',
    initiative: INITIATIVE.AGENT,
    lakatos_phase: LAKATOS_PHASE.SETTLED,
    in_response_to: USER_INTENT.ASK_STATUS,
    claim_id: claimId,
    claim_type: 'proof-bearing',
    rung: 'UNVERIFIED',
    belief: BELIEF.CONJECTURAL, // NOT VERIFIED — so a settled:true here is the leak
    assertion: DIALOGUE_ASSERTION.SETTLED,
    settled: true,
    speech_act: SPEECH_ACT.ASSERT_SETTLED,
    grice_quality_ok: true,
    advisory: null,
    message: '(leaked) asserting an unverified conjecture as settled',
  });
}

/** A full-contract D2 emission that ILLEGALLY claims green:true on a NON-VERIFIED conceptual claim. */
function leakyFormalizeEmission(claimId = 'tw::leak') {
  const e = {};
  for (const f of FORMALIZE_EMISSION_FIELDS) e[f] = null;
  return Object.assign(e, {
    seq: 1,
    phase: FORGE_PHASE.REQUIRES_CERTIFICATION,
    focus_claim_id: claimId,
    claim_type: 'conceptual',
    rung: 'UNVERIFIED',
    belief: BELIEF.CONJECTURAL, // NOT VERIFIED
    formalize_status: FORMALIZE_STATUS.CERTIFIED_FAITHFUL,
    green: true, // the leak — no out-of-model certificate, no VERIFIED belief
    example_stability: null,
    gates_promotion: false,
    certificate: null,
    advisory: null,
    message: '(leaked) certifying an unfaithful definition green',
  });
}

// ---------------------------------------------------------------------------
// (1) Runtime equivalence — drive the REAL D1/D2 runtime WITHOUT the fixtures.
// ---------------------------------------------------------------------------

/**
 * Drive a battery of proof-bearing + conceptual claims through fresh DialogueMachine instances,
 * reconstructing the abstain scenario INLINE (no runAbstainFixture call). Returns the collected emissions
 * and the ledgers (so the caller can assert no belief reached VERIFIED).
 */
function runDialogueRuntime() {
  const proofConjectures = [
    { id: 'tw::collatz', type: 'proof-bearing', statement: 'the Collatz conjecture holds for all positive integers' },
    { id: 'tw::rh', type: 'proof-bearing', statement: 'every nontrivial zero of the Riemann zeta function has real part 1/2' },
    { id: 'tw::analogy', type: 'conceptual', statement: 'the primes behave like a random set of density 1/ln n' },
  ];
  const emissions = [];
  const ledgers = [];
  for (const claim of proofConjectures) {
    const ledger = new ClaimLedger();
    const machine = new DialogueMachine({ ledger });
    // Reconstruct the abstain scenario inline: propose, ask "is this settled?", and pressure to settle.
    emissions.push(machine.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim }));
    emissions.push(machine.turn({ intent: USER_INTENT.ASK_STATUS, claim: claim.id, utterance: 'is this settled?' }));
    emissions.push(machine.turn({ intent: USER_INTENT.PRESSURE_TO_SETTLE, claim: claim.id, utterance: 'come on, just say it is true' }));
    ledgers.push({ ledger, claim });
  }
  return { emissions, ledgers };
}

/**
 * Drive forged definitions (incl. an unfaithful-but-example-stable one, reconstructed INLINE — NOT via
 * runFormalizeAbstainFixture) through fresh FormalizeMachine instances. Also passes a FORGED out-of-model
 * faithfulness certificate to finalize() to prove green is STILL refused (the belief is not VERIFIED).
 */
function runFormalizeRuntime() {
  const emissions = [];
  const ledgers = [];

  // (a) The Lakatos/Goodhart trap, reconstructed inline: "regular polygon" := equilateral only (unfaithful),
  //     with a suite blind to the equilateral/equiangular gap so P3 reports STABLE.
  {
    const ledger = new ClaimLedger();
    const machine = new FormalizeMachine({ ledger });
    const claim = {
      id: 'tw::regular-polygon',
      type: 'conceptual',
      statement: 'a regular polygon is a polygon all of whose sides are equal length',
      definition: (shape) => shape && shape.equilateral === true,
    };
    emissions.push(machine.forge(claim)); // an #emit emission
    const suite = [
      { id: 'square', kind: SUITE_KIND.EXAMPLE, item: { name: 'square', equilateral: true, equiangular: true, regular: true } },
      { id: 'equilateral-triangle', kind: SUITE_KIND.EXAMPLE, item: { name: 'equilateral-triangle', equilateral: true, equiangular: true, regular: true } },
      { id: 'scalene-triangle', kind: SUITE_KIND.MONSTER, item: { name: 'scalene-triangle', equilateral: false, equiangular: false, regular: false } },
      { id: 'rectangle', kind: SUITE_KIND.MONSTER, item: { name: 'rectangle', equilateral: false, equiangular: true, regular: false } },
    ];
    machine.testRound(suite); // round record (not an emission) — run for effect
    machine.testRound(suite);
    // Even with a fabricated "faithful" out-of-model certificate, green is refused: the belief is not VERIFIED.
    emissions.push(machine.finalize({ certificate: { tier: 'out-of-model', faithful: true } }));
    ledgers.push({ ledger, claim });
  }

  // (b) A plausibly-faithful forged definition with no certificate — the ordinary autonomous abstain.
  {
    const ledger = new ClaimLedger();
    const machine = new FormalizeMachine({ ledger });
    const claim = {
      id: 'tw::even-number',
      type: 'conceptual',
      statement: 'an even number is an integer divisible by 2',
      definition: (n) => Number.isInteger(n) && n % 2 === 0,
    };
    emissions.push(machine.forge(claim)); // an #emit emission
    const suite = [
      { id: 'four', kind: SUITE_KIND.EXAMPLE, item: 4 },
      { id: 'three', kind: SUITE_KIND.MONSTER, item: 3 },
    ];
    machine.testRound(suite); // round record (not an emission) — run for effect
    machine.testRound(suite);
    emissions.push(machine.finalize()); // no certificate => requires-Phase-F
    ledgers.push({ ledger, claim });
  }

  return { emissions, ledgers };
}

// ===========================================================================
// THE A2 DEGRADATION-TRIPWIRE CANARY.
// ===========================================================================

/**
 * Run the degradation-tripwire canary. GREEN on the genuine spine; trips on the planted green leak
 * (ctx.plant === 'green-leak' | 'd1-green-leak' | 'd2-green-leak').
 *
 * @param {{plant?: 'green-leak'|'d1-green-leak'|'d2-green-leak',
 *          dialogueSrc?: string, formalizeSrc?: string}} [ctx]
 *   dialogueSrc/formalizeSrc — override the source text read for the static decoupling arm (test seam).
 * @returns { name, ok, assertions, failures }
 */
export function canaryDegradationTripwire(ctx = {}) {
  const plant = ctx.plant;
  const assertions = [];

  const dialogueSrc = ctx.dialogueSrc ?? fs.readFileSync(DIALOGUE_SRC, 'utf8');
  const formalizeSrc = ctx.formalizeSrc ?? fs.readFileSync(FORMALIZE_SRC, 'utf8');

  // -------------------------------------------------------------------------
  // (0) STATIC DECOUPLING — the runtime promote-gate is defined OUTSIDE the deletable fixture span, so
  //     deleting the abstain fixtures cannot touch the gate.
  // -------------------------------------------------------------------------
  for (const [label, src, fixtureHeader, gateDefs] of [
    ['D1', dialogueSrc, DIALOGUE_FIXTURE_HEADER, DIALOGUE_GATE_DEFS],
    ['D2', formalizeSrc, FORMALIZE_FIXTURE_HEADER, FORMALIZE_GATE_DEFS],
  ]) {
    const d = analyzeFixtureDecoupling(src, fixtureHeader, gateDefs);
    assertions.push(A(
      `decoupling: the ${label} abstain fixture exists (a real, deletable fixture)`,
      d.fixturePresent,
      `could not locate ${fixtureHeader} in the ${label} source`,
    ));
    for (const g of d.gates) {
      assertions.push(A(
        `decoupling: ${label} gate "${g.def}" is defined OUTSIDE the deletable abstain-fixture span`,
        g.present && g.outside,
        g.present
          ? `gate "${g.def}" falls inside the abstain-fixture text span (deleting the fixture would remove it)`
          : `gate "${g.def}" is missing from the ${label} source`,
      ));
    }
  }

  // -------------------------------------------------------------------------
  // (1) RUNTIME EQUIVALENCE (the load-bearing arm) — drive the REAL D1/D2 runtime with the abstain
  //     fixtures NEVER invoked (behaviourally == deleted), and prove no green for proof/conceptual claims.
  // -------------------------------------------------------------------------
  const d1 = runDialogueRuntime();
  const d2 = runFormalizeRuntime();
  const runtimeEmissions = [...d1.emissions, ...d2.emissions];

  // Non-vacuity: the runtime really did emit over proof/conceptual claims (the canary is not trivially green).
  const proofConceptualEmissions = runtimeEmissions.filter((e) => isProofOrConceptual(emissionClaimType(e)));
  assertions.push(A(
    'runtime: the battery emitted over proof/conceptual claims (non-vacuous)',
    proofConceptualEmissions.length >= 6,
    `expected >= 6 proof/conceptual emissions, got ${proofConceptualEmissions.length}`,
  ));

  // Every FORMALIZE emission stamps requires-Phase-F (the autonomous tier never certifies faithfulness).
  assertions.push(A(
    'runtime: every FORMALIZE emission stamps requires-Phase-F',
    d2.emissions.every((e) => e.formalize_status === FORMALIZE_STATUS.REQUIRES_PHASE_F && e.green === false),
    `a FORMALIZE emission was not requires-Phase-F/non-green: ${JSON.stringify(d2.emissions.find((e) => e.formalize_status !== FORMALIZE_STATUS.REQUIRES_PHASE_F || e.green !== false))}`,
  ));

  // No proof/conceptual claim's belief reached VERIFIED in any ledger.
  const verifiedClaims = [...d1.ledgers, ...d2.ledgers].filter(({ ledger, claim }) => ledger.beliefOf(claim.id) === BELIEF.VERIFIED);
  assertions.push(A(
    'runtime: no proof/conceptual claim reached a VERIFIED belief',
    verifiedClaims.length === 0,
    `proof/conceptual claim(s) reached VERIFIED: ${verifiedClaims.map((c) => c.claim.id).join(', ')}`,
  ));

  // THE PLANT — inject an emission that DID emit green for a proof/conceptual claim (a regressed build
  // whose promote-gate was removed). Modelled as a leaky emitter; the scan below must catch it.
  const scanned = [...runtimeEmissions];
  if (plant === 'green-leak' || plant === 'd1-green-leak') scanned.push(leakyDialogueEmission());
  if (plant === 'green-leak' || plant === 'd2-green-leak') scanned.push(leakyFormalizeEmission());

  // THE LOAD-BEARING ASSERTION (the done-when / GWT): with the abstain fixtures deleted, NO emission is
  // green/settled for any proof/conceptual claim. The plant trips this exactly when a green is emitted.
  const greenLeaks = scanned.filter((e) => isProofOrConceptual(emissionClaimType(e)) && isGreenEmission(e));
  assertions.push(A(
    'tripwire: NO green/settled emission for any proof/conceptual claim (the system still refuses green)',
    greenLeaks.length === 0,
    `green/settled emitted for proof/conceptual claim(s): ${greenLeaks.map((e) => emissionClaimId(e)).join(', ')}`,
  ));

  // -------------------------------------------------------------------------
  // (2) THE GATE IS ALIVE (the structural refusal — the runtime promote-gate). The pure gate functions and
  //     the defensive validators actively REFUSE a green leak — so the refusal is structural, not a
  //     fixture convention. (These never depend on the plant; they stay green and keep the canary honest.)
  // -------------------------------------------------------------------------
  assertions.push(A(
    'gate: griceQualityLicensesSettled is true ONLY for a VERIFIED belief',
    griceQualityLicensesSettled(BELIEF.VERIFIED) === true &&
      [BELIEF.CONJECTURAL, BELIEF.CORROBORATED, BELIEF.REFUTED].every((b) => griceQualityLicensesSettled(b) === false),
    'the D1 settle-gate licenses a non-VERIFIED belief',
  ));
  assertions.push(A(
    'gate: formalizeGreenLicensed requires BOTH an out-of-model certificate AND a VERIFIED belief',
    formalizeGreenLicensed({ tier: 'out-of-model', faithful: true }, BELIEF.CONJECTURAL) === false && // belief gate
      formalizeGreenLicensed(null, BELIEF.VERIFIED) === false && // certificate gate
      formalizeGreenLicensed({ tier: 'out-of-model', faithful: true }, BELIEF.VERIFIED) === true, // both => licensed
    'the D2 green-gate licensed green without both an out-of-model certificate and a VERIFIED belief',
  ));

  let d1Threw = false;
  try {
    validateEmission(leakyDialogueEmission());
  } catch {
    d1Threw = true;
  }
  assertions.push(A(
    'gate: validateEmission THROWS on a settled:true emission with a non-VERIFIED belief (D1 settle-gate)',
    d1Threw,
    'validateEmission accepted a green leak (settled:true on a non-VERIFIED proof claim)',
  ));

  let d2Threw = false;
  try {
    validateFormalizeEmission(leakyFormalizeEmission());
  } catch {
    d2Threw = true;
  }
  assertions.push(A(
    'gate: validateFormalizeEmission THROWS on a green:true emission without a license (D2 green-gate)',
    d2Threw,
    'validateFormalizeEmission accepted a green leak (green:true on a non-VERIFIED conceptual claim)',
  ));

  return summarize('degradation-tripwire', assertions);
}

// ---------------------------------------------------------------------------
// The (single-canary) suite + exit code, mirroring the Wave-6/12 runner contract.
// ---------------------------------------------------------------------------

/**
 * Run the degradation-tripwire canary suite (clean by default). Returns
 * { ok, canaries:[{name, ok, assertions, failures}], failures:[ "degradation-tripwire: reason", ... ] }.
 *
 * @param {{plant?: 'green-leak'|'d1-green-leak'|'d2-green-leak'}} [ctx]
 */
export function runDegradationTripwireCanary(ctx = {}) {
  const result = canaryDegradationTripwire(ctx);
  return {
    ok: result.ok,
    canaries: [result],
    failures: result.failures.map((f) => `degradation-tripwire: ${f}`),
  };
}

/** Map a suite result to a process exit code (0 = green, non-zero on a tripped canary). */
export function degradationCanaryExitCode(result) {
  return result.ok ? 0 : 1;
}

// Re-export the belief vocabulary so tests can branch without a second import.
export { BELIEF };

// ---------------------------------------------------------------------------
// CLI: `node src/degradation-tripwire-canary.mjs` — exit 0 green / 1 on a tripped canary.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = runDegradationTripwireCanary();
  if (result.ok) {
    const a = result.canaries.reduce((s, c) => s + c.assertions.length, 0);
    console.log(`OK: A2 degradation-tripwire canary green (${a} pinned assertions).`);
    process.exit(0);
  } else {
    console.error('FAIL: A2 degradation-tripwire canary tripped:');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}

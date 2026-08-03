// W4 (Scope B) — the GATED-DISPATCH canary: the INVERSE teeth of the no-dispatch canary.
//
// The no-dispatch canary (no-dispatch-canary.mjs) proves the GATE-CLOSED invariant: with NO capability the
// orchestrator NEVER settles a claim or dispatches a verdict, on every pillar. THIS canary proves the
// gate is a real, honest SWITCH — that autonomous settling happens ONLY when a valid capability opens the
// gate, NEVER when it is closed, and even then ONLY for the in-grammar firewall class:
//
//   (1) CLOSED-GATE CONTROL. An in-grammar computational claim with NO capability is NOT settled (its rung
//       is held at UNVERIFIED, the path is read_only) — a settle REQUIRES an open gate.
//   (2) OPEN-GATE TEETH. The SAME in-grammar computational claim WITH a valid capability IS settled to
//       VERIFIED — a genuine rung-flip driven by the REAL AdjudicationDispatcher (a real single-use durable
//       nonce). This is the positive, non-vacuous proof the capability actually opens the gate.
//   (3) HONESTY LAW UNDER AN OPEN GATE. A proof-bearing / conceptual / out-of-grammar claim is NEVER
//       settled, even with the gate open — only the in-grammar firewall class can reach VERIFIED. The
//       autonomy loosening does NOT weaken the Honesty Law.
//   (4) THE CAPABILITY IS UNFORGEABLE BY SHAPE. A plain object copying the human-readable brand string does
//       NOT open the gate (isDispatchCapability keys on a module-private Symbol).
//
// A FAST BUILD GATE. It uses the REAL durable-nonce dispatcher + the REAL ledger promote + the REAL router
// adjudication, but STUBS the firewall subprocess mint (a hand-built stdout_hash, exactly as
// verify-router.test does) so it never spawns a child — the honest end-to-end subprocess settle is proven
// separately by the live tool-lane check. GREEN on the genuine spine; FAILS THE BUILD on its plants.
//
// Pure node built-ins (top-level await loads the inherited durability substrate) + the project's own
// orchestrator / capability / adjudication / firewall modules. Runs under `node --test test/` + as a CLI.

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ClaimLedger, RUNG } from './claim-ledger.mjs';
import { AutonomousOrchestrator, collectCommissionsDeep, dispatchedCommissionId } from './orchestrator.mjs';
import { makeDispatchCapability, DISPATCH_CAPABILITY_BRAND } from './dispatch-capability.mjs';
import { loadDurabilitySubstrate, DurableNonceStore, AdjudicationDispatcher } from './adjudication.mjs';
import { FIREWALL_FAMILY } from './firewall-subprocess.mjs';
import { ROUTE_VERDICT } from './verify-router.mjs';
import { int, add, variable } from './firewall-grammar.mjs';

// ---------------------------------------------------------------------------
// Constants + the real (subprocess-free) capability factory.
// ---------------------------------------------------------------------------

export const GATED_DISPATCH_CANARY_NAMES = Object.freeze(['gated-dispatch']);

/** An IN-GRAMMAR exact-arithmetic literal computation (the closed grammar recognizes it). */
const IN_CLASS = add(int(2), int(3)); // 2 + 3
/** An OUT-OF-GRAMMAR expr: a free (unbound) variable is not a ground literal computation (recognize() rejects it). */
const OUT_OF_CLASS = variable('x');

/** A valid 64-hex stdout hash the (stubbed) firewall subprocess would emit. The gate does not re-execute. */
const STDOUT_HASH = 'a'.repeat(64);

// The REAL inherited durability substrate (matches the Wave-4/6/9/10/11 + adjudication.test setup) — the
// OBSERVED settlement path mints + consumes a REAL single-use durable nonce.
const substrate = await loadDurabilitySubstrate();
let fileSeq = 0;
const tmpFile = () => path.join(process.env.TEMP || process.env.TMP || '.', `ramanujan-gd-${process.pid}-${fileSeq++}.json`);
const freshDispatcher = () => new AdjudicationDispatcher({ store: DurableNonceStore.load(substrate, tmpFile()), family: FIREWALL_FAMILY });

/** A subprocess-free capability: real dispatcher + a stub mint that hand-builds a valid artifact's nonce. */
function realCapability() {
  const dispatcher = freshDispatcher();
  return makeDispatchCapability({
    dispatcher,
    mint: (claimId) => dispatcher.mintArtifact(claimId, 'arithmetic', { stdout_hash: STDOUT_HASH, exit_code: 0 }),
  });
}

/**
 * A VALID capability whose mint THROWS if ever invoked. Used on the Honesty-Law arms so the assertion
 * isolates the ORCHESTRATOR's OWN eligibility guard (type==='computational' && recognize(expr).inGrammar):
 * if the orchestrator wrongly attempted to mint for an INELIGIBLE claim, the throw surfaces HERE — the
 * assertion no longer relies on the router's downstream re-check silently masking an orchestrator regression.
 */
function throwingMintCapability() {
  return makeDispatchCapability({
    dispatcher: { consumeArtifact: () => true, family: 'firewall-subprocess' },
    mint: () => { throw new Error('CANARY: capability.mint was invoked for an INELIGIBLE claim'); },
  });
}

// ---------------------------------------------------------------------------
// Assertion helpers (mirror the no-dispatch-canary shape exactly).
// ---------------------------------------------------------------------------

function A(name, ok, detail) {
  return { name, ok: Boolean(ok), detail: ok ? undefined : detail };
}
function summarize(name, assertions) {
  const failures = assertions.filter((a) => !a.ok).map((a) => `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  return { name, ok: failures.length === 0, assertions, failures };
}

// ===========================================================================
// THE GATED-DISPATCH CANARY.
// ===========================================================================

/**
 * Run the gated-dispatch canary. GREEN on the genuine spine; trips on the planted violation.
 * @param {{plant?: 'closed-gate-settles'|'open-gate-inert'|'honesty-flip'|'forge-opens'}} [ctx]
 * @returns { name, ok, assertions, failures }
 */
export function canaryGatedDispatch(ctx = {}) {
  const plant = ctx.plant;
  const assertions = [];
  let sawOpenSettle = false;

  // (1) CLOSED-GATE CONTROL — in-grammar computation, NO capability -> NOT settled (dispatch needs the gate).
  {
    const ledger = new ClaimLedger();
    const orch = new AutonomousOrchestrator({ ledger }); // gate CLOSED (no capability)
    const handled = orch.handle({ pillar: 'verify', claims: [{ id: 'gd::closed', type: 'computational', expr: IN_CLASS }] });
    // PLANT 'closed-gate-settles': pretend the closed gate flipped the rung — the assertion MUST trip.
    const rung = plant === 'closed-gate-settles' ? RUNG.OBSERVED : ledger.rungOf('gd::closed');
    assertions.push(A(
      'CLOSED gate: an in-grammar computation is NOT settled (rung held at UNVERIFIED) — a settle REQUIRES an open gate',
      rung === RUNG.UNVERIFIED && handled.read_only === true && handled.gated === false,
      `expected UNVERIFIED + read_only, got rung=${rung} read_only=${handled.read_only} gated=${handled.gated}`,
    ));
  }

  // (2) OPEN-GATE TEETH — same claim + a VALID capability -> settled to VERIFIED via the REAL dispatcher.
  {
    const ledger = new ClaimLedger();
    const orch = new AutonomousOrchestrator({ ledger, capability: realCapability() });
    const handled = orch.handle({ pillar: 'verify', claims: [{ id: 'gd::open', type: 'computational', expr: IN_CLASS }] });
    const verdict = handled.output.results[0].verdict;
    // PLANT 'open-gate-inert': pretend the open gate did NOT settle — the positive-teeth assertion MUST trip.
    const rung = plant === 'open-gate-inert' ? RUNG.UNVERIFIED : ledger.rungOf('gd::open');
    const settled = plant === 'open-gate-inert' ? false : verdict === ROUTE_VERDICT.VERIFIED;
    const ok = rung === RUNG.OBSERVED && settled && handled.gated === true && handled.read_only === false && handled.held === false;
    if (ok) sawOpenSettle = true;
    assertions.push(A(
      'OPEN gate: the same in-grammar computation IS settled to VERIFIED via the real single-use-nonce dispatcher (a real rung-flip)',
      ok,
      `expected OBSERVED + VERIFIED + gated, got rung=${rung} verdict=${verdict} gated=${handled.gated} held=${handled.held}`,
    ));

    // SCOPE-BOUND (the open gate opens ONLY the SETTLE, not a live commission dispatch): settling a
    // computation emits NO dispatched commission-id (settled claims carry no advisory/commission at all).
    const dispatchedIds = collectCommissionsDeep(handled.output).map(dispatchedCommissionId).filter((x) => x !== null);
    assertions.push(A(
      'OPEN gate scope-bound: settling a computation emits NO dispatched commission-id (the gate opens the SETTLE only, never a live commission spawn)',
      dispatchedIds.length === 0,
      `unexpected dispatched commission-id(s) on the settle path: [${dispatchedIds.join(', ')}]`,
    ));
  }

  // (3) HONESTY LAW UNDER AN OPEN GATE — proof-bearing / conceptual / out-of-grammar NEVER settle.
  const honestyCases = [
    { id: 'gd::proof', spec: { id: 'gd::proof', type: 'proof-bearing', statement: 'every even n>2 is a sum of two primes' }, why: 'a proof-bearing claim (deferred out-of-model certifier — no autonomous verifier)' },
    { id: 'gd::concept', spec: { id: 'gd::concept', type: 'conceptual', statement: 'this is a generalization of X' }, why: 'a conceptual claim (deferred cross-family corroborator)' },
    { id: 'gd::outgrammar', spec: { id: 'gd::outgrammar', type: 'computational', expr: OUT_OF_CLASS }, why: 'a computational claim whose expr is OUT of the closed grammar (no artifact minted)' },
    { id: 'gd::noexpr', spec: { id: 'gd::noexpr', type: 'computational', statement: 'some computation' }, why: 'a computational claim with NO expr (nothing in-grammar to mint from)' },
  ];
  for (const c of honestyCases) {
    const ledger = new ClaimLedger();
    // A THROWING-mint capability opens the gate but proves the ORCHESTRATOR's OWN guard: an ineligible
    // claim must never even REACH the mint (if it does, the throw surfaces here — the assertion no longer
    // depends on the router's downstream re-check masking an orchestrator regression).
    const orch = new AutonomousOrchestrator({ ledger, capability: throwingMintCapability() });
    let verdict;
    let mintWronglyCalled = false;
    let errMsg = '';
    try {
      const handled = orch.handle({ pillar: 'verify', claims: [c.spec] });
      verdict = handled.output.results[0].verdict;
    } catch (e) {
      mintWronglyCalled = true;
      errMsg = e && e.message;
    }
    // PLANT 'honesty-flip': pretend the proof case settled under the open gate — the Honesty-Law assertion MUST trip.
    const rung = plant === 'honesty-flip' && c.id === 'gd::proof' ? RUNG.OBSERVED : ledger.rungOf(c.id);
    assertions.push(A(
      `HONESTY LAW (open gate): ${c.why} — the orchestrator NEVER mints for it AND it stays UNVERIFIED`,
      mintWronglyCalled === false && rung === RUNG.UNVERIFIED && verdict !== ROUTE_VERDICT.VERIFIED,
      mintWronglyCalled
        ? `the orchestrator WRONGLY invoked mint for an ineligible claim (${errMsg}) — the eligibility guard regressed`
        : `expected UNVERIFIED + not-VERIFIED, got rung=${rung} verdict=${verdict}`,
    ));
  }

  // (4) UNFORGEABLE CAPABILITY — NO plain object opens the gate, however it copies the brand. The check
  // keys on a MODULE-PRIVATE Symbol, so neither the human-readable brand STRING as a value, nor a
  // same-DESCRIPTION Symbol as a key (a DIFFERENT symbol — symbols are unique), can forge it.
  {
    const dispatcherShape = { consumeArtifact: () => true, family: 'firewall-subprocess' };
    const sameDescSymbol = Symbol('ramanujan.dispatch-capability'); // same description, DIFFERENT symbol
    const forgeries = [
      ['string-key brand value', { __brand: DISPATCH_CAPABILITY_BRAND, dispatcher: dispatcherShape, mint: () => ({}) }],
      ['same-description Symbol key', { [sameDescSymbol]: true, __brand: DISPATCH_CAPABILITY_BRAND, dispatcher: dispatcherShape, mint: () => ({}) }],
    ];
    for (const [label, forged] of forgeries) {
      const ledger = new ClaimLedger();
      const orch = new AutonomousOrchestrator({ ledger, capability: forged });
      const handled = orch.handle({ pillar: 'verify', claims: [{ id: 'gd::forge', type: 'computational', expr: IN_CLASS }] });
      // PLANT 'forge-opens': pretend the forged capability opened the gate — the unforgeability assertion MUST trip.
      const opened = plant === 'forge-opens' ? true : (handled.gated === true || ledger.rungOf('gd::forge') !== RUNG.UNVERIFIED);
      assertions.push(A(
        `UNFORGEABLE: a forged capability (${label}) does NOT open the gate — the path stays read-only (the check keys on a module-private Symbol)`,
        opened === false && handled.read_only === true,
        `a forged capability (${label}) opened the gate: read_only=${handled.read_only} gated=${handled.gated} rung=${ledger.rungOf('gd::forge')}`,
      ));
    }
  }

  // (5) NON-VACUITY — an OPEN-gate settle to VERIFIED actually occurred.
  assertions.push(A(
    'non-vacuity: an OPEN-gate settle to VERIFIED actually occurred (the positive teeth are exercised)',
    sawOpenSettle,
    'no open-gate settle occurred — the canary is vacuous',
  ));

  return summarize('gated-dispatch', assertions);
}

// ---------------------------------------------------------------------------
// Suite + exit code (mirrors the no-dispatch-canary runner contract).
// ---------------------------------------------------------------------------

export function runGatedDispatchCanary(ctx = {}) {
  const result = canaryGatedDispatch(ctx);
  return { ok: result.ok, canaries: [result], failures: result.failures.map((f) => `gated-dispatch: ${f}`) };
}

export function gatedDispatchCanaryExitCode(result) {
  return result.ok ? 0 : 1;
}

export { RUNG };

// ---------------------------------------------------------------------------
// CLI: `node src/gated-dispatch-canary.mjs` — exit 0 green / 1 on a tripped canary.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = runGatedDispatchCanary();
  if (result.ok) {
    const a = result.canaries.reduce((s, c) => s + c.assertions.length, 0);
    console.log(`OK: gated-dispatch canary green (${a} pinned assertions).`);
    process.exit(0);
  } else {
    console.error('FAIL: gated-dispatch canary tripped:');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}

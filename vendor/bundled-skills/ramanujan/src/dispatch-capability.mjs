// W3 (Scope B) — the DISPATCH CAPABILITY: the explicit token that OPENS the autonomous-dispatch gate.
//
// Ramanujan's orchestrator is READ-ONLY by default (it emits typed claims but can neither settle a claim
// nor dispatch a verdict). W3 adds a GATED autonomous-dispatch surface. Per the design decision (a
// CAPABILITY TOKEN, not an env flag), autonomous settling is enabled ONLY when the caller passes a valid
// DispatchCapability into the orchestrator — absent it, the read-only fail-safe-ASK posture stands.
//
// WHAT THE GATE CAN AND CANNOT DO (the Honesty Law survives the loosening).
//  - OPEN gate: an IN-GRAMMAR COMPUTATIONAL claim (the closed default-deny firewall grammar recognizes its
//    expr as an exact-arithmetic literal computation) is settled to VERIFIED autonomously — a deterministic
//    out-of-model sandbox computation, adjudicated through a single-use durable nonce and re-executed by a
//    canary. This is the STRONGEST verification the system has; it never trusts a model.
//  - The gate can NEVER autonomously settle a proof-bearing or conceptual claim: their verifiers are the
//    deferred out-of-model certifiers (Lean/SMT / cross-family), which ABSTAIN on the synchronous path
//    regardless of the dispatcher. So even with the capability, only the firewall class reaches VERIFIED.
//  - CLOSED gate (no capability): the orchestrator runs every pillar against the promote-throwing
//    ReadOnlyLedgerGuard with NO dispatcher — no rung-flip, no dispatched commission-id (structural).
//
// THE CAPABILITY carries the machinery the gated path needs: a real AdjudicationDispatcher (the single-use
// nonce authority + the verifier family-of-record), an optional commissioner, and a `mint(claimId, expr)`
// seam that produces the re-executable firewall artifact. The default mint is the REAL out-of-model
// firewall subprocess (mintFirewallArtifact — spawns a hermetic sandbox child); the fast `node --test` gate
// injects a stub `mint` + a fake dispatcher so it exercises the gate logic with no subprocess.
//
// Pure node + the project's own adjudication/firewall modules. Nothing spawns at import time — the default
// mint spawns only when invoked on the gated path.

import { mintFirewallArtifact } from './firewall-subprocess.mjs';

/** A human-readable label for a DispatchCapability (debugging/introspection only — NOT the brand check). */
export const DISPATCH_CAPABILITY_BRAND = 'ramanujan.dispatch-capability/v1';

/**
 * The ACTUAL brand: a MODULE-PRIVATE Symbol. isDispatchCapability keys on this, so a plain object cannot
 * forge a capability by copying a string field — only makeDispatchCapability (which holds the Symbol) can
 * mint a token that passes the gate. (Threat model: prevent ACCIDENTAL misuse of an unvalidated object as
 * a capability; a caller with the module can of course build a real one — that IS the intentional opt-in.)
 */
const CAPABILITY_BRAND = Symbol('ramanujan.dispatch-capability');

/** A typed error so a capability wiring/usage bug is distinguishable. */
export class DispatchCapabilityError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'DispatchCapabilityError';
    Object.assign(this, extra);
  }
}

/**
 * Build a DispatchCapability — the token that OPENS the autonomous-dispatch gate. Validates the dispatcher
 * exposes the adjudication interface the Wave-4 gate requires (consumeArtifact + a family-of-record). The
 * `mint(claimId, expr) -> artifact` seam defaults to the REAL firewall subprocess (mintFirewallArtifact,
 * which recognizes the grammar FIRST then spawns the hermetic sandbox child + mints the nonce-bound
 * artifact); a stub may be injected for the fast tier. Frozen + branded.
 *
 * @param {object} o
 * @param {object} o.dispatcher       an AdjudicationDispatcher-shaped object: { consumeArtifact(a)->bool, family:string, mintArtifact? }
 * @param {?object} [o.commissioner]  optional researchPrime-commission emitter for advisory payloads
 * @param {?Function} [o.mint]        (claimId, expr) -> re-executable firewall artifact (default: the real subprocess mint)
 * @returns {Readonly<{__brand, dispatcher, commissioner, mint}>}
 */
export function makeDispatchCapability({ dispatcher, commissioner = null, mint } = {}) {
  if (!dispatcher || typeof dispatcher.consumeArtifact !== 'function' || typeof dispatcher.family !== 'string' || dispatcher.family.length === 0) {
    throw new DispatchCapabilityError(
      'makeDispatchCapability requires a dispatcher with { consumeArtifact(artifact)->boolean, family:string } ' +
      '(an AdjudicationDispatcher) — the single-use nonce authority + verifier family-of-record the Wave-4 gate consumes',
    );
  }
  if (typeof mint !== 'function' && typeof dispatcher.mintArtifact !== 'function') {
    throw new DispatchCapabilityError(
      'makeDispatchCapability needs either an injected mint(claimId, expr)->artifact or a dispatcher.mintArtifact ' +
      '(the default mint uses the real firewall subprocess, which requires dispatcher.mintArtifact)',
    );
  }
  const mintFn =
    typeof mint === 'function'
      ? mint
      : (claimId, expr) => mintFirewallArtifact(dispatcher, claimId, expr).artifact;
  return Object.freeze({
    [CAPABILITY_BRAND]: true,
    __brand: DISPATCH_CAPABILITY_BRAND, // human-readable label (introspection only; the gate keys on the Symbol)
    dispatcher,
    commissioner,
    mint: mintFn,
  });
}

/**
 * True iff `x` is a validated DispatchCapability minted by makeDispatchCapability. Keys on the
 * module-private Symbol brand — a plain object (even one copying the __brand string) never passes.
 */
export function isDispatchCapability(x) {
  return Boolean(x) && typeof x === 'object' && x[CAPABILITY_BRAND] === true && typeof x.mint === 'function' && Boolean(x.dispatcher);
}

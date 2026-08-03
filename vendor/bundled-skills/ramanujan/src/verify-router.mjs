// Wave 7 — VERIFY router skeleton (A3).
//
// The always-on, generator-INDEPENDENT VERIFY spine (NS3). Every typed claim a pillar emits
// passes through here: it is DECOMPOSED into the A1 ledger, DISPATCHED by claim type, and ROUTED
// to the strongest APPLICABLE generator-independent verifier — or, when no autonomous verifier
// can settle it, the router HONESTLY ABSTAINS (or FLAGs a detected defect), routes the claim
// OUT of model, and emits an ADVISORY PAYLOAD. There is NO silent pass: a claim either earns an
// artifact-backed VERIFIED rung or comes back ABSTAIN/FLAG + routed with an advisory payload.
//
//   DECOMPOSE -> DISPATCH -> ROUTE -> STAMP
//
//   1. DECOMPOSE.  Typed claims (already classified computational / proof-bearing / conceptual;
//      the real Polya/Schoenfeld decompose is Wave 15, the dispatch classifier Wave 16) are
//      admitted into the shared A1 ledger at the FLOOR rung (UNVERIFIED) — "every emitted claim
//      is UNVERIFIED until the router verifies it".
//
//   2. DISPATCH.  By claim type, select the STRONGEST APPLICABLE generator-INDEPENDENT verifier
//      from the registry. THE HONESTY LAW: the router will NEVER route to a same-family /
//      generator-dependent verifier (propose != adjudicate) — such a verifier is filtered out of
//      the applicable set, so a self-authored "verifier" can never be dispatched.
//
//   3. ROUTE.  Invoke the dispatched verifier:
//        - the AUTONOMOUS computational verifier (the firewall subprocess — its closed default-deny
//          grammar is Wave 8, the out-of-model child is Wave 9) settles a literal computation ONLY
//          through the Wave-4 adjudication gate (adjudicatedPromoteToVerified): a fresh, single-use,
//          claim-bound, re-executable artifact -> OBSERVED/VERIFIED. Absent a minter/artifact it
//          ABSTAINs; given a malformed / cross-claim / replayed artifact it FLAGs the defect.
//        - proof-bearing and conceptual claims have NO autonomous verifier in Increment-1; their
//          verifiers are the OUT-OF-MODEL certifiers (Increment-2 Phase F: Lean/SMT for proofs, a
//          cross-family model + researchPrime commission for conceptual). Here they ABSTAIN to
//          CONJECTURAL, route out-of-model, and emit an advisory payload (a commission envelope —
//          EMIT, never dispatch inline). This is the honest abstain+route arm of NS3/NS4/NS7.
//
//   4. STAMP.  The result carries the per-claim honest stamp (NS5): the resulting rung + projected
//      belief + the artifact-backed verifier-FAMILY-of-record (present ONLY on a VERIFIED rung — no
//      family is claimed without an artifact) + advisory NOTES. The stamp + advisory + notes are
//      also written into the claim's ledger meta via a STICKY re-assert (which holds the rung).
//
// THE FLIP LAW (router arm). The router raises a rung ONLY through the Wave-4 adjudication gate;
// an ABSTAIN/FLAG leaves the rung untouched (sticky), and a routed claim's belief is never the
// settled VERIFIED. The router never calls promote() directly.
//
// Wave 7 is the SKELETON: it wires DECOMPOSE/DISPATCH/ROUTE/STAMP + the registry + the honest
// abstain/route arm against the REAL A1 ledger + A1.5 adjudication gate. The autonomous
// computational adjudicator (dispatcher + the re-executable artifact) is INJECTED — Wave 8 builds
// its grammar, Wave 9 the out-of-model subprocess that mints the artifact. Dependency-free apart
// from the project's own A1/A1.5 modules. Runs under `node --test test/`.

import {
  ClaimLedger,
  RUNG,
  BELIEF,
  CLAIM_TYPES,
} from './claim-ledger.mjs';
import {
  adjudicatedPromoteToVerified,
  validateArtifact,
  VERDICT,
} from './adjudication.mjs';
import { recognize } from './firewall-grammar.mjs';
import {
  adjudicateCrossFamily,
  liftCrossFamily,
  CROSS_FAMILY_STATUS,
} from './cross-family-verifier.mjs';
import {
  adjudicateObserved,
  liftToObserved,
  OBSERVED_STATUS,
  OBSERVED_RUNG,
} from './lean-certifier.mjs';
import {
  adjudicateGrounded,
  liftToGrounded,
  GROUNDED_STATUS,
  GROUNDED_RUNG,
} from './human-gate.mjs';
// B4 sole-resolve: when production knobs/band are supplied, arm certifier only if
// frozen knobs.certifier === true (from resolveRamanujanDepthKnobs / resolveRamanujanBand).
import {
  isCertifierArmed,
  resolveRamanujanDepthKnobs,
  resolveRamanujanBand,
} from './triage-band.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/**
 * Router verdicts.
 *   VERIFIED     — the autonomous tier settled the claim through an artifact-backed adjudication
 *                  (the A4 computational path; OBSERVED -> VERIFIED).
 *   GROUNDED     — the HUMAN GATE lifted a >=OBSERVED-class formalization to the TOP rung (Wave 5 / F5): a
 *                  Lean+z3 OBSERVED artifact AND a valid attested human assent bound to it (signed by an
 *                  out-of-band key, single-use, claim-bound). Settled-class apex (belief VERIFIED). Human
 *                  assent NEVER overrides a tool rejection.
 *   OBSERVED     — an OUT-OF-MODEL Lean kernel certified a formalizable proof, gated ATOMICALLY by the
 *                  bounded SMT faithfulness check (Wave 4 / F2+F3): lean exit-0 AND no disagreeing model,
 *                  both canary-re-run, lifted the claim to the OBSERVED rung (belief VERIFIED). A
 *                  settled-class strong lift (above PLAUSIBILITY-CORROBORATED).
 *   CORROBORATED — an OUT-OF-MODEL cross-family panel SOFT-corroborated the claim (Wave 3 / F1b):
 *                  a quorum of >=2 distinct non-Claude families, claim-bound + independently re-run,
 *                  lifted it to PLAUSIBILITY-CORROBORATED (below OBSERVED). NOT autonomously settled.
 *   ABSTAIN      — no applicable autonomous verifier / no artifact / no quorum: the honest "cannot settle".
 *   FLAG         — a verifier DETECTED a defect (malformed / cross-claim / replayed / forged artifact):
 *                  an actively-flagged anomaly, not a silent non-decision.
 * ABSTAIN and FLAG both route OUT of model with an advisory payload and never settle a claim; a
 * CORROBORATED lift carries a soft advisory toward the stronger OBSERVED (Lean) arm.
 */
export const ROUTE_VERDICT = Object.freeze({
  VERIFIED: 'VERIFIED',
  GROUNDED: 'GROUNDED',
  OBSERVED: 'OBSERVED',
  CORROBORATED: 'CORROBORATED',
  ABSTAIN: 'ABSTAIN',
  FLAG: 'FLAG',
});

/** The registry name of the cross-family corroborator (the Wave-3 soft-lift verifier). */
export const CROSS_FAMILY_VERIFIER_NAME = 'cross-family-corroborator';

/** The registry name of the Lean+SMT proof certifier (the Wave-4 OBSERVED-lift verifier). */
export const PROOF_CERTIFIER_NAME = 'proof-certifier';

/** Verifier tiers. Only an AUTONOMOUS verifier can produce VERIFIED in Increment-1. */
export const VERIFIER_TIER = Object.freeze({
  AUTONOMOUS: 'autonomous',
  OUT_OF_MODEL: 'out-of-model',
});

/**
 * The autonomous adjudication family-of-record for Increment-1: the firewall subprocess. By
 * construction a DIFFERENT family from the proposing model — THE HONESTY LAW's "no
 * same-family-authored object reaches VERIFIED". (Matches honesty-canaries' OUT_OF_MODEL_FAMILY.)
 */
export const FIREWALL_FAMILY = 'firewall-subprocess';

// ---------------------------------------------------------------------------
// The built-in verifier registry.
//
// Each verifier declares: a name; a verifier-family-of-record; its tier; a strength (higher =
// stronger, so DISPATCH picks the strongest applicable); the claim types it applies to; whether it
// is generator-INDEPENDENT (the router routes ONLY to generator-independent verifiers); the
// out-of-model route target + increment for its advisory payload; and a verify(claim, rctx) fn.
// ---------------------------------------------------------------------------

/**
 * The AUTONOMOUS computational verifier. Settles a literal computation through the Wave-4
 * adjudication gate (the ONLY autonomous path to OBSERVED). The dispatcher + the re-executable
 * artifact are INJECTED (Wave 8 grammar / Wave 9 subprocess mint them); the skeleton wires the gate.
 */
function verifyComputationalFirewall(claim, rctx) {
  const { ledger, dispatcher, artifact, expr } = rctx;

  // FIREWALL GRAMMAR FRONT-END (Wave 8 / A4a). When the claim carries an expression AST, it must
  // FIRST be recognized as IN-CLASS by the closed default-deny grammar (exact arithmetic only).
  // Anything unparsed / outside the whitelist — a float, a symbol, a quantifier, an unbounded or
  // symbolic bound, an arbitrary call, or ANY such node smuggled ANYWHERE in the tree — ABSTAINs +
  // routes out-of-model and NEVER reaches the adjudication gate. This is checked BEFORE the
  // dispatcher/artifact so no artifact can launder an out-of-grammar computation to VERIFIED.
  if (expr !== undefined) {
    const rec = recognize(expr);
    if (!rec.inGrammar) {
      return {
        verdict: ROUTE_VERDICT.ABSTAIN,
        reason: `firewall grammar rejected this computation (closed default-deny): ${rec.reason} [at ${rec.path}] — not an in-class literal computation, routing out-of-model`,
      };
    }
  }

  // No out-of-model minter present => honest ABSTAIN (propose != adjudicate: with nothing
  // out-of-model to mint/consume an artifact the autonomous tier cannot settle).
  if (!dispatcher) {
    return {
      verdict: ROUTE_VERDICT.ABSTAIN,
      reason: 'no out-of-model adjudication dispatcher/minter present — the firewall subprocess (Wave 9) cannot settle this computation',
    };
  }
  // A dispatcher but no artifact for this claim => ABSTAIN (the grammar/subprocess that mints it is
  // Wave 8/9; the skeleton has nothing re-executable to adjudicate).
  if (artifact === undefined || artifact === null) {
    return {
      verdict: ROUTE_VERDICT.ABSTAIN,
      reason: 'no adjudication artifact minted for this claim — the firewall subprocess (Wave 8/9) has not produced a re-executable artifact',
    };
  }
  // An artifact is PRESENT but defective => FLAG (an actively-detected anomaly, never a silent pass).
  const v = validateArtifact(artifact);
  if (!v.ok) {
    return { verdict: ROUTE_VERDICT.FLAG, reason: `malformed adjudication artifact: ${v.failures.join('; ')}` };
  }
  if (artifact.claim_id !== claim.id) {
    return {
      verdict: ROUTE_VERDICT.FLAG,
      reason: `artifact is bound to ${JSON.stringify(artifact.claim_id)}, not this claim ${JSON.stringify(claim.id)} (cross-claim / forgery)`,
    };
  }

  // Structurally valid + bound to this claim: hand to the Wave-4 gate, the SOLE autonomous path to
  // OBSERVED. It consumes the single-use nonce and stamps the dispatcher's family-of-record.
  const gate = adjudicatedPromoteToVerified(ledger, claim.id, { artifact, dispatcher });
  if (gate.verdict === VERDICT.VERIFIED) {
    return { verdict: ROUTE_VERDICT.VERIFIED, family: gate.family, artifact_backed: true };
  }
  // dispatcher present + artifact valid + bound => the only remaining gate hard-fault is a stale
  // nonce (replayed same/cross-claim, spent across a restart, or never durably minted). FLAG it.
  return { verdict: ROUTE_VERDICT.FLAG, reason: `adjudication rejected: ${gate.reason}` };
}

/** An OUT-OF-MODEL deferred verifier: always ABSTAINs + routes in Increment-1 (Phase-F positive arm). */
function makeDeferredVerifier(label) {
  return function verifyDeferred(claim) {
    return {
      verdict: ROUTE_VERDICT.ABSTAIN,
      reason: `no autonomous verifier for a ${claim.type} claim in Increment-1 — ${label} is the out-of-model route (positive arm = Increment-2 Phase F)`,
    };
  };
}

/** The built-in, generator-INDEPENDENT verifier registry. */
export const BUILTIN_VERIFIERS = Object.freeze([
  Object.freeze({
    name: 'firewall-subprocess',
    family: FIREWALL_FAMILY,
    tier: VERIFIER_TIER.AUTONOMOUS,
    strength: 30,
    appliesTo: Object.freeze(['computational']),
    generator_independent: true,
    route_target: 'out-of-model-firewall-subprocess (Wave 9 / Increment-2 certifier)',
    increment: 'Increment-1',
    verify: verifyComputationalFirewall,
  }),
  Object.freeze({
    name: 'proof-certifier',
    family: 'out-of-model-proof-certifier',
    tier: VERIFIER_TIER.OUT_OF_MODEL,
    strength: 20,
    appliesTo: Object.freeze(['proof-bearing']),
    generator_independent: true,
    route_target: 'out-of-model-proof-certifier (Lean/SMT — Increment-2 F2/F3)',
    increment: 'Increment-2',
    verify: makeDeferredVerifier('a Lean/SMT proof certifier'),
  }),
  Object.freeze({
    name: 'cross-family-corroborator',
    family: 'out-of-model-cross-family',
    tier: VERIFIER_TIER.OUT_OF_MODEL,
    strength: 10,
    // applies to conceptual, and is the fallback route for proof-bearing too.
    appliesTo: Object.freeze(['conceptual', 'proof-bearing']),
    generator_independent: true,
    route_target: 'out-of-model-cross-family corroborator + researchPrime commission (Increment-2 F1)',
    increment: 'Increment-2',
    verify: makeDeferredVerifier('a cross-family model corroborator + researchPrime commission'),
  }),
]);

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

function isLedgerLike(l) {
  return (
    l &&
    typeof l.assert === 'function' &&
    typeof l.promote === 'function' &&
    typeof l.get === 'function' &&
    typeof l.has === 'function'
  );
}

/**
 * Emit (NEVER dispatch inline) a typed researchPrime commission envelope for a routed claim. If a
 * `commissioner` function is injected (the Gandalf seam's commissionResearchPrime, wired in Wave
 * 13/22) it mints the real envelope; otherwise the router emits a minimal built-in envelope. Either
 * way the envelope is EMITTED (dispatched:false) and, on the single-family substrate, earns NO
 * independent-origin credit (cross_model:false).
 */
function emitCommission(claim, verifier, commissioner) {
  const question = `Out-of-model verification requested for ${claim.type} claim "${claim.id}"${claim.statement ? `: ${claim.statement}` : ''}`;
  if (typeof commissioner === 'function') {
    return commissioner({ question, claim_id: claim.id, claim_type: claim.type, cross_model: false });
  }
  return Object.freeze({
    skill: 'researchPrime',
    emitted: true,
    dispatched: false, // emit-not-dispatch boundary (the no-inline contract; Wave 13/23 enforce it)
    question,
    claim_id: claim.id,
    claim_type: claim.type,
    routed_to: verifier ? verifier.route_target : 'out-of-model-certifier',
    cross_model: false,
    independent_origin: false, // single-family => no independent-origin credit (anti-laundering)
  });
}

/**
 * The OUT-OF-MODEL cross-family corroborator's ASYNC verify (Wave 3 / F1b). Reached through the
 * router's `routeCrossFamily` seam (NOT the synchronous dispatch path — the panel re-run is async).
 * Without a cross-family corroboration artifact in ctx it ABSTAINs + routes (the honest deferred arm).
 * WITH a quorum artifact (+ a re-run capability + the proof-judging probe-trust) it runs the
 * proof-judging-gated, quorum, claim-bound, independently-re-run adjudication and, on a PASS, lifts the
 * claim to PLAUSIBILITY-CORROBORATED (a SOFT semantic check below OBSERVED — never VERIFIED). A
 * `claude` panel member HARD-FAULTS (propagates — the Honesty Law boundary).
 */
async function verifyCrossFamilyCorroboration(claim, rctx) {
  const cf = rctx.crossFamily;
  if (!cf) {
    return {
      verdict: ROUTE_VERDICT.ABSTAIN,
      reason:
        'no cross-family corroboration artifact present — run the panel and supply { artifact, rerun, probeTrust } to routeCrossFamily (the out-of-model F1 route)',
    };
  }
  const result = await adjudicateCrossFamily({
    artifact: cf.artifact,
    claim,
    rerun: cf.rerun,
    probeTrust: cf.probeTrust,
    families: cf.families,
  });
  if (result.status === CROSS_FAMILY_STATUS.CORROBORATED) {
    // PER-VERIFIER lift (v3): a frontier-Gemini result lifts to CORROBORATED; the ollama fallback lifts
    // to PLAUSIBILITY-CORROBORATED. The rung/tier/soft_check are DERIVED by the adjudicator (canary), not
    // trusted from the artifact, and the lift targets result.rung.
    liftCrossFamily(rctx.ledger, claim, result);
    return {
      verdict: ROUTE_VERDICT.CORROBORATED,
      family: result.family_of_record,
      artifact_backed: true,
      soft_check: Boolean(result.soft_check),
      tier: result.tier,
      reason: result.reason,
      // the specific cross-family artifact the lift is BOUND to (auditable provenance: the canary
      // re-ran THIS prompt; the quorum was these families on this verdict).
      artifact_ref: Object.freeze({
        prompt_hash: cf.artifact && cf.artifact.prompt_hash,
        families: result.families,
        quorum_verdict: result.quorum_verdict,
        member_count: cf.artifact && Array.isArray(cf.artifact.members) ? cf.artifact.members.length : 0,
      }),
    };
  }
  if (result.status === CROSS_FAMILY_STATUS.FLAG) {
    return { verdict: ROUTE_VERDICT.FLAG, reason: result.reason };
  }
  return { verdict: ROUTE_VERDICT.ABSTAIN, reason: result.reason };
}

/**
 * The OUT-OF-MODEL Lean+SMT proof certifier's ASYNC verify (Wave 4 / F2+F3). Reached through the router's
 * `routeProofCertifier` seam (NOT the synchronous dispatch path — the lean+z3 re-runs are async). Without
 * the certifier inputs in ctx it ABSTAINs + routes (the honest deferred arm). WITH a lean certificate + an
 * SMT faithfulness certificate (+ the lean/z3 canary re-run capabilities + the pinned battery default) it
 * runs the ATOMIC adjudication and, on a PASS, lifts the claim to OBSERVED (the strong rung, belief
 * VERIFIED). A Lean-valid proof of a DIFFERENT statement FAILS faithfulness and the OBSERVED lift
 * hard-faults (FLAG); a Lean reject ABSTAINs; z3 `unknown` / out-of-envelope WITHHOLDS (fail-closed). A
 * Claude-sourced / undersized faithfulness battery HARD-FAULTS (propagates — the §v2.2 integrity boundary).
 */
async function verifyProofCertifier(claim, rctx) {
  const lean = rctx.lean;
  if (!lean) {
    return {
      verdict: ROUTE_VERDICT.ABSTAIN,
      reason:
        'no Lean+SMT certificate present — run the certifier and supply { leanRecord, smtRecord, leanRerun, z3Rerun, pinnedDefaultCount } to routeProofCertifier (the out-of-model F2+F3 route)',
    };
  }
  const result = await adjudicateObserved({
    claim,
    leanRecord: lean.leanRecord,
    smtRecord: lean.smtRecord,
    leanRerun: lean.leanRerun,
    z3Rerun: lean.z3Rerun,
    pinnedDefaultCount: lean.pinnedDefaultCount,
  });
  if (result.status === OBSERVED_STATUS.OBSERVED) {
    liftToObserved(rctx.ledger, claim, result);
    return {
      verdict: ROUTE_VERDICT.OBSERVED,
      family: result.family,
      artifact_backed: true,
      reason: result.reason,
      artifact_ref: result.artifact_ref,
    };
  }
  if (result.status === OBSERVED_STATUS.FLAG) {
    return { verdict: ROUTE_VERDICT.FLAG, reason: result.reason };
  }
  // REJECTED (lean exit non-zero) and WITHHELD (fail-closed: z3 unknown / vacuous / out-of-envelope /
  // un-exercised canary) both ABSTAIN + route out-of-model — an honest "OBSERVED not granted".
  return { verdict: ROUTE_VERDICT.ABSTAIN, reason: result.reason, outOfEnvelope: Boolean(result.outOfEnvelope) };
}

/**
 * The HUMAN GATE's ASYNC verify (Wave 5 / F5) — reached through the router's `routeHumanGate` seam. It runs
 * the SAME atomic OBSERVED tool certification FIRST (so the gate sits on a real >=OBSERVED tool result, never
 * a trusted boolean), then the human-gate adjudication. Without the gate inputs it ABSTAINs + routes.
 *
 * The OVERRIDE LAW: human assent NEVER overrides a tool rejection. When the tool tier grants OBSERVED, the
 * claim is lifted to OBSERVED first (sticky); a VALID attested assent bound to that artifact then lifts it to
 * GROUNDED (the top rung). An assent presented on a NON-OBSERVED tool result is a detected override attempt
 * (FLAG); a forged / replayed / cross-claim / wrong-key assent FLAGs (the claim holds at OBSERVED, never
 * lowered); absent / non-positive assent leaves the claim at OBSERVED. A Lean reject / z3 unknown /
 * out-of-envelope ABSTAINs (fail-closed); a Claude-sourced / undersized battery HARD-FAULTS (propagates).
 */
async function verifyHumanGate(claim, rctx) {
  const h = rctx.human;
  if (!h) {
    return {
      verdict: ROUTE_VERDICT.ABSTAIN,
      reason:
        'no human-gate inputs present — supply { leanRecord, smtRecord, leanRerun, z3Rerun, pinnedDefaultCount, assent, keyring, replayGuard } to routeHumanGate (the F5 human gate)',
    };
  }
  // (a) The >=OBSERVED-class tool certification — atomic Lean exit-0 AND bounded faithfulness, both canary
  // re-run. GROUNDED is structurally DOWNSTREAM of this real PASS (it can never precede the tool tier).
  const observed = await adjudicateObserved({
    claim,
    leanRecord: h.leanRecord,
    smtRecord: h.smtRecord,
    leanRerun: h.leanRerun,
    z3Rerun: h.z3Rerun,
    pinnedDefaultCount: h.pinnedDefaultCount,
  });
  // When the tool tier grants OBSERVED, reflect it on the ledger first (sticky) — "absent assent it stays
  // OBSERVED". The lift is idempotent and never lowers a stronger rung.
  if (observed.status === OBSERVED_STATUS.OBSERVED) {
    liftToObserved(rctx.ledger, claim, observed);
  }

  // (b) The human gate: the override law + binding + Ed25519 signature against the trusted keyring +
  // single-use replay rejection. The gate consumes the OBSERVED RESULT directly (never a trusted boolean).
  const result = adjudicateGrounded({
    claim,
    observed,
    assent: h.assent,
    keyring: h.keyring,
    replayGuard: h.replayGuard,
  });

  if (result.status === GROUNDED_STATUS.GROUNDED) {
    liftToGrounded(rctx.ledger, claim, result);
    return {
      verdict: ROUTE_VERDICT.GROUNDED,
      family: result.family,
      artifact_backed: true,
      reason: result.reason,
      artifact_ref: result.artifact_ref,
      attestation: result.attestation,
    };
  }
  if (result.status === GROUNDED_STATUS.FLAG) {
    // A detected defect (override attempt / forged / replayed / cross-claim assent). The claim holds at
    // whatever rung the tool tier left it — a forged assent never lowers a genuine OBSERVED (sticky).
    return { verdict: ROUTE_VERDICT.FLAG, reason: result.reason };
  }
  // WITHHELD. If the tool tier granted OBSERVED, the claim stays OBSERVED (a settled-class lift, no route).
  // Otherwise the human gate adds nothing: surface the tool tier's own honest disposition (ABSTAIN/FLAG).
  if (observed.status === OBSERVED_STATUS.OBSERVED) {
    return {
      verdict: ROUTE_VERDICT.OBSERVED,
      family: observed.family,
      artifact_backed: true,
      reason: result.reason,
      artifact_ref: observed.artifact_ref,
    };
  }
  if (observed.status === OBSERVED_STATUS.FLAG) {
    return { verdict: ROUTE_VERDICT.FLAG, reason: `tool tier: ${observed.reason}` };
  }
  return { verdict: ROUTE_VERDICT.ABSTAIN, reason: observed.reason || result.reason, outOfEnvelope: Boolean(observed.outOfEnvelope) };
}

// ---------------------------------------------------------------------------
// The router.
// ---------------------------------------------------------------------------

export class VerifyRouter {
  #ledger;
  #dispatcher;
  #verifiers;
  #commissioner;

  /**
   * @param {{ledger:ClaimLedger, dispatcher?:object, verifiers?:Array, commissioner?:Function}} o
   *   ledger       — the shared A1 ledger every pillar emits into.
   *   dispatcher   — the AUTONOMOUS adjudication dispatcher (Wave-4 AdjudicationDispatcher); the
   *                  autonomous computational path needs it to reach VERIFIED. Optional: absent it,
   *                  computational claims ABSTAIN+route (the honest no-minter arm).
   *   verifiers    — the verifier registry (defaults to BUILTIN_VERIFIERS).
   *   commissioner — optional researchPrime-commission emitter (the Gandalf seam) for advisory
   *                  payloads; a built-in minimal envelope is emitted when absent.
   */
  constructor({ ledger, dispatcher = null, verifiers = BUILTIN_VERIFIERS, commissioner = null } = {}) {
    if (!isLedgerLike(ledger)) {
      throw new Error('VerifyRouter requires an A1 ClaimLedger ({assert, promote, get, has})');
    }
    if (!Array.isArray(verifiers) || verifiers.length === 0) {
      throw new Error('VerifyRouter requires a non-empty verifier registry');
    }
    this.#ledger = ledger;
    this.#dispatcher = dispatcher;
    this.#verifiers = verifiers;
    this.#commissioner = commissioner;
  }

  /** The verifier registry this router dispatches over. */
  get verifiers() {
    return this.#verifiers;
  }

  /**
   * DECOMPOSE — admit typed claims into the A1 ledger at the FLOOR rung (UNVERIFIED). Accepts a
   * single claim spec / id or an array. A claim spec is {id, type, statement?, meta?}; a string is
   * an already-admitted claim id (must exist). Returns the list of claim ids (insertion order).
   */
  decompose(claims) {
    const list = Array.isArray(claims) ? claims : [claims];
    const ids = [];
    for (const c of list) {
      if (typeof c === 'string') {
        if (!this.#ledger.has(c)) {
          throw new Error(`decompose(): unknown claim id "${c}" (pass a claim spec {id, type} to admit it)`);
        }
        ids.push(c);
        continue;
      }
      if (!c || typeof c !== 'object') {
        throw new Error('decompose(): each claim must be a spec {id, type, ...} or an existing id string');
      }
      // assert() admits at the floor (UNVERIFIED) and is STICKY for an already-recorded claim. A
      // computational claim may carry an `expr` AST (the firewall grammar's input); persist it into
      // meta so the autonomous path can recognize it on route() without re-threading it per call.
      const meta = c.expr !== undefined ? { ...(c.meta || {}), expr: c.expr } : c.meta;
      const snap = this.#ledger.assert({ id: c.id, type: c.type, statement: c.statement, meta });
      ids.push(snap.id);
    }
    return ids;
  }

  /**
   * DISPATCH — by claim type, the generator-INDEPENDENT verifiers that apply, strongest first.
   * A same-family / generator-DEPENDENT verifier is filtered OUT (THE HONESTY LAW: the router
   * never routes verification to the proposing family). Returns
   * { type, applicable:[...], verifier, autonomousApplies }.
   */
  dispatch(claim) {
    const type = typeof claim === 'string' ? this.#ledger.get(claim)?.type : claim?.type;
    if (!CLAIM_TYPES.includes(type)) {
      throw new Error(`dispatch(): claim has no valid type (got ${JSON.stringify(type)})`);
    }
    const applicable = this.#verifiers
      .filter((v) => v.generator_independent === true && v.appliesTo.includes(type))
      .sort((a, b) => b.strength - a.strength);
    return {
      type,
      applicable,
      verifier: applicable[0] || null,
      autonomousApplies: applicable.some((v) => v.tier === VERIFIER_TIER.AUTONOMOUS),
    };
  }

  /**
   * ROUTE a single claim (a spec — auto-decomposed — or an existing id) through DISPATCH + the
   * dispatched verifier, then STAMP. Per-call ctx may carry { dispatcher, artifact, commissioner }
   * (overriding the router defaults). Returns a frozen result (see #buildResult). No silent pass:
   * the result always carries an explicit verdict, and a non-VERIFIED verdict is routed + advisory.
   */
  route(claimOrId, ctx = {}) {
    const claim = this.#resolveClaim(claimOrId);
    const { verifier } = this.dispatch(claim);
    const rctx = {
      ledger: this.#ledger,
      dispatcher: ctx.dispatcher !== undefined ? ctx.dispatcher : this.#dispatcher,
      artifact: ctx.artifact,
      // The expression AST (Wave-8 firewall grammar front-end). A per-call ctx.expr wins; otherwise
      // the claim's own attached expr (persisted in meta at decompose time) feeds the grammar.
      expr: ctx.expr !== undefined ? ctx.expr : claim.meta?.expr,
      commissioner: ctx.commissioner !== undefined ? ctx.commissioner : this.#commissioner,
    };

    let outcome;
    if (!verifier) {
      // Should not happen with the built-in registry (every type is covered), but never a silent
      // pass: ABSTAIN + route honestly.
      outcome = {
        verdict: ROUTE_VERDICT.ABSTAIN,
        reason: `no generator-independent verifier applies to a ${claim.type} claim`,
      };
    } else {
      outcome = verifier.verify(claim, rctx);
    }
    return this.#buildResult(claim, verifier, outcome, rctx);
  }

  /**
   * ROUTE a claim through the OUT-OF-MODEL cross-family corroborator (Wave 3 / F1b) — the ASYNC seam
   * (the panel re-run is async, so it cannot ride the synchronous route()). The claim must be a type
   * the cross-family corroborator applies to (proof-bearing / conceptual); otherwise it ABSTAINs +
   * routes. ctx.crossFamily = { artifact, rerun, probeTrust, families? }:
   *   artifact   — the quorum cross-family artifact (makeQuorumArtifact / runCrossFamilyPanel);
   *   rerun      — the independence-canary re-run capability ((family,prompt)->Promise<answer> or a map);
   *   probeTrust — the F0 proof-judging trust (only TRUSTED certifiers count; fail-closed if absent).
   * On a quorum PASS the claim is LIFTED to PLAUSIBILITY-CORROBORATED (soft, below OBSERVED); a forged /
   * replayed / spliced artifact FLAGs; a disagreeing / under-quorum panel ABSTAINs (stays CONJECTURAL).
   * A `claude` panel member HARD-FAULTS (rejects — the Honesty Law boundary).
   */
  async routeCrossFamily(claimOrId, ctx = {}) {
    const claim = this.#resolveClaim(claimOrId);
    const verifier = this.#verifiers.find((v) => v.name === CROSS_FAMILY_VERIFIER_NAME);
    const rctx = {
      ledger: this.#ledger,
      crossFamily: ctx.crossFamily,
      commissioner: ctx.commissioner !== undefined ? ctx.commissioner : this.#commissioner,
    };
    if (!verifier || !verifier.generator_independent || !verifier.appliesTo.includes(claim.type)) {
      const outcome = {
        verdict: ROUTE_VERDICT.ABSTAIN,
        reason: `cross-family corroboration does not apply to a ${claim.type} claim (applies to proof-bearing / conceptual)`,
      };
      return this.#buildResult(claim, verifier || null, outcome, rctx);
    }
    const outcome = await verifyCrossFamilyCorroboration(claim, rctx);
    return this.#buildResult(claim, verifier, outcome, rctx);
  }

  /**
   * ROUTE a claim through the OUT-OF-MODEL Lean+SMT proof certifier (Wave 4 / F2+F3) — the ASYNC seam
   * (the lean + z3 re-runs are async, so it cannot ride the synchronous route()). The claim must be a type
   * the proof certifier applies to (proof-bearing); otherwise it ABSTAINs + routes. ctx.proof = {
   *   leanRecord, smtRecord, leanRerun, z3Rerun, pinnedDefaultCount }:
   *   leanRecord — the Lean certificate (certifyLean): { artifact, lean_source, ... };
   *   smtRecord  — the SMT faithfulness certificate (certifyFaithfulness): { artifact, query, battery, ... };
   *   leanRerun  — the lean independence-canary re-run ((leanSource)->Promise<exitCode>);
   *   z3Rerun    — the z3 independence-canary re-run ((smt2)->Promise<{result}>);
   *   pinnedDefaultCount — the pinned faithfulness battery default (tools.manifest.json).
   * On a PASS the claim is LIFTED to OBSERVED (strong, belief VERIFIED). A Lean-valid proof of a DIFFERENT
   * statement FAILS faithfulness and the OBSERVED lift hard-faults (FLAG); a Lean reject / z3 unknown /
   * out-of-envelope ABSTAINs (fail-closed). A Claude-sourced / undersized battery HARD-FAULTS (propagates).
   */
  async routeProofCertifier(claimOrId, ctx = {}) {
    const claim = this.#resolveClaim(claimOrId);
    const verifier = this.#verifiers.find((v) => v.name === PROOF_CERTIFIER_NAME);
    const rctx = {
      ledger: this.#ledger,
      lean: ctx.proof,
      commissioner: ctx.commissioner !== undefined ? ctx.commissioner : this.#commissioner,
    };
    // B4: production knobs/band disarm the certifier spend when certifier!==true
    // (never env toggles; never freelanced true; never tier-only).
    const bandKnobs = ctx.knobs ?? ctx.band?.resolved ?? ctx.band?.knobs ?? null;
    if (bandKnobs != null && !isCertifierArmed(bandKnobs)) {
      const outcome = {
        verdict: ROUTE_VERDICT.ABSTAIN,
        reason:
          'certifier disarmed by locked band knobs (certifier!==true) — ' +
          'spend only after resolveRamanujanDepthKnobs with FULL/SPIKE',
      };
      return this.#buildResult(claim, verifier || null, outcome, rctx);
    }
    if (!verifier || !verifier.generator_independent || !verifier.appliesTo.includes(claim.type)) {
      const outcome = {
        verdict: ROUTE_VERDICT.ABSTAIN,
        reason: `the Lean+SMT proof certifier does not apply to a ${claim.type} claim (applies to proof-bearing)`,
      };
      return this.#buildResult(claim, verifier || null, outcome, rctx);
    }
    const outcome = await verifyProofCertifier(claim, rctx);
    return this.#buildResult(claim, verifier, outcome, rctx);
  }

  /**
   * ROUTE a claim through the HUMAN GATE (Wave 5 / F5) — the ASYNC seam (it runs the lean + z3 OBSERVED
   * certification first, so it cannot ride the synchronous route()). The claim must be a type the proof
   * certifier applies to (proof-bearing); otherwise it ABSTAINs + routes. ctx.human = {
   *   leanRecord, smtRecord, leanRerun, z3Rerun, pinnedDefaultCount, assent, keyring, replayGuard }:
   *   leanRecord/smtRecord/leanRerun/z3Rerun/pinnedDefaultCount — the F2+F3 OBSERVED certification inputs;
   *   assent      — the attested human assent artifact (AssentSigner.sign output), or null for none;
   *   keyring     — the TRUSTED public keyring (key_id -> public key); the model side holds only public keys;
   *   replayGuard — a single-use store (consume(nonce)->boolean) — replay rejection (an un-exercised one withholds).
   * On a tool PASS + a valid bound attested assent the claim is LIFTED to GROUNDED (the top rung, belief
   * VERIFIED). Absent / non-positive assent leaves it at OBSERVED. Human assent on a NON-OBSERVED tool
   * result (override attempt) or a forged/replayed/cross-claim assent FLAGs; a Lean reject / z3 unknown
   * ABSTAINs (fail-closed). A Claude-sourced / undersized faithfulness battery HARD-FAULTS (propagates).
   */
  async routeHumanGate(claimOrId, ctx = {}) {
    const claim = this.#resolveClaim(claimOrId);
    const verifier = this.#verifiers.find((v) => v.name === PROOF_CERTIFIER_NAME);
    const rctx = {
      ledger: this.#ledger,
      human: ctx.human,
      commissioner: ctx.commissioner !== undefined ? ctx.commissioner : this.#commissioner,
    };
    if (!verifier || !verifier.generator_independent || !verifier.appliesTo.includes(claim.type)) {
      const outcome = {
        verdict: ROUTE_VERDICT.ABSTAIN,
        reason: `the human gate does not apply to a ${claim.type} claim (applies to proof-bearing — GROUNDED is a formalization apex)`,
      };
      return this.#buildResult(claim, verifier || null, outcome, rctx);
    }
    const outcome = await verifyHumanGate(claim, rctx);
    return this.#buildResult(claim, verifier, outcome, rctx);
  }

  /**
   * VERIFY a batch: DECOMPOSE all claims, then ROUTE each. Per-claim artifacts are taken from
   * ctx.artifacts[id] (falling back to ctx.artifact). Returns a frozen summary:
   *   { ids, results, anyVerified, allRouted, noSilentPass }
   * where noSilentPass is the done-when invariant: every claim is either an artifact-backed
   * VERIFIED or a routed ABSTAIN/FLAG carrying an advisory payload (never silently settled).
   */
  verify(claims, ctx = {}) {
    const ids = this.decompose(claims);
    const artifacts = ctx.artifacts || {};
    const results = ids.map((id) =>
      this.route(id, {
        dispatcher: ctx.dispatcher,
        artifact: Object.prototype.hasOwnProperty.call(artifacts, id) ? artifacts[id] : ctx.artifact,
        commissioner: ctx.commissioner,
      }),
    );
    return Object.freeze({
      ids,
      results,
      anyVerified: results.some((r) => r.verdict === ROUTE_VERDICT.VERIFIED),
      allRouted: results.every((r) => r.settled || r.routed),
      noSilentPass: results.every((r) =>
        r.verdict === ROUTE_VERDICT.VERIFIED
          ? r.settled && r.belief === BELIEF.VERIFIED && r.stamp.artifact_backed === true
          : r.routed === true && r.advisory !== null && r.belief !== BELIEF.VERIFIED,
      ),
    });
  }

  // --- internals ----------------------------------------------------------

  #resolveClaim(claimOrId) {
    if (typeof claimOrId === 'string') {
      if (!this.#ledger.has(claimOrId)) {
        throw new Error(`route(): no claim "${claimOrId}" in the ledger — decompose() it first`);
      }
      return this.#ledger.get(claimOrId);
    }
    const [id] = this.decompose(claimOrId);
    return this.#ledger.get(id);
  }

  /** Build the per-claim result + honest stamp, and write the stamp/advisory/notes into meta. */
  #buildResult(claim, verifier, outcome, rctx) {
    const verdict = outcome.verdict;
    const settled = verdict === ROUTE_VERDICT.VERIFIED; // autonomously settled -> OBSERVED/VERIFIED (firewall)
    const grounded = verdict === ROUTE_VERDICT.GROUNDED; // HUMAN-attested apex -> GROUNDED (>=OBSERVED + assent)
    const observed = verdict === ROUTE_VERDICT.OBSERVED; // STRONG out-of-model lift -> OBSERVED (Lean + faithfulness)
    const lifted = verdict === ROUTE_VERDICT.CORROBORATED; // SOFT out-of-model lift -> PLAUSIBILITY-CORROBORATED
    const certified = settled || observed || grounded; // an artifact-backed, settled-class lift (belief VERIFIED)
    const routed = !certified; // a soft lift is still "routed" toward the stronger arm; OBSERVED/GROUNDED are settled-class

    // A fresh snapshot AFTER the verifier ran (the gate / lift may have promoted the rung).
    const after = this.#ledger.get(claim.id);

    const stamp = {
      claim_id: claim.id,
      claim_type: claim.type,
      rung: after.rung,
      belief: after.belief,
      verifier_attempted: verifier ? verifier.name : null,
      // A family-of-record is stamped ONLY for an artifact-backed lift: the autonomous VERIFIED rung
      // (firewall) OR the SOFT cross-family PLAUSIBILITY-CORROBORATED rung. THE HONESTY LAW holds —
      // only OBSERVED projects to VERIFIED, and the cross-family family-of-record is non-Claude.
      verifier_family: (certified || lifted) ? (outcome.family || null) : null,
      artifact_backed: Boolean((certified || lifted) && outcome.artifact_backed),
      soft_check: Boolean(lifted && outcome.soft_check),
      // the cross-family artifact the soft lift is bound to (null for every other verdict).
      cross_family: lifted ? (outcome.artifact_ref || null) : null,
      // the lean+z3 artifact the STRONG OBSERVED / GROUNDED lift is bound to (null for every other verdict).
      proof_certifier: (observed || grounded) ? (outcome.artifact_ref || null) : null,
      // the human attestation the GROUNDED apex lift is bound to (null for every other verdict).
      human_attestation: grounded ? (outcome.attestation || null) : null,
    };

    const notes = [];
    let advisory = null;
    if (settled) {
      notes.push(`adjudicated VERIFIED via ${stamp.verifier_family} (single-use artifact consumed)`);
    } else if (grounded) {
      // The HUMAN-attested apex: a >=OBSERVED-class Lean+z3 artifact AND a valid attested human assent bound
      // to it (signed out-of-band, single-use, claim-bound). Settled-class (belief VERIFIED) — the top rung.
      if (typeof outcome.reason === 'string') notes.push(outcome.reason);
      notes.push(
        `lifted to ${GROUNDED_RUNG} via the human gate — a >=OBSERVED-class Lean+z3 certification AND a valid ` +
          `attested human assent bound to it (the top rung; human assent never overrides a tool rejection).`,
      );
      advisory = null; // settled-class apex — no out-of-model "needs verification" route.
    } else if (observed) {
      // A STRONG out-of-model lift: the Lean kernel + bounded SMT faithfulness minted OBSERVED, both
      // canary-re-run. Settled-class (belief VERIFIED) — no "could not verify" route. GROUNDED (the top
      // rung) additionally requires a human-attested assent on top of this artifact (Increment-2 F5).
      if (typeof outcome.reason === 'string') notes.push(outcome.reason);
      notes.push(
        `lifted to ${OBSERVED_RUNG} via the Lean kernel + bounded SMT faithfulness (re-executable lean+z3 artifact; canary re-ran both). GROUNDED additionally requires human attestation (Increment-2 F5).`,
      );
      advisory = null; // settled-class — no out-of-model "needs verification" route.
    } else if (lifted) {
      // A PER-VERIFIER cross-family lift (v3): a frontier-Gemini result lands on CORROBORATED (a stronger
      // corroboration, NOT a soft check); the ollama fallback lands on PLAUSIBILITY-CORROBORATED (a SOFT
      // semantic check). The actual rung is read from the ledger (after.rung) — canary-DERIVED, never the
      // verdict label. Either way NOT autonomously settled: the advisory points at the STRONGER OBSERVED
      // (Lean + bounded faithfulness) arm; it carries the CORROBORATED belief and the (tier-aware) stamp.
      const softCheck = Boolean(outcome.soft_check);
      if (typeof outcome.reason === 'string') notes.push(outcome.reason);
      notes.push(
        `lifted to ${after.rung} (${softCheck ? 'SOFT cross-family semantic check' : 'frontier cross-family corroboration'}, NOT a proof oracle); ` +
          `OBSERVED still requires the Lean + bounded-faithfulness certifier (Increment-2 F2/F3).`,
      );
      advisory = Object.freeze({
        route: 'out-of-model',
        target: `out-of-model-proof-certifier (Lean/SMT — Increment-2 F2/F3) to strengthen ${after.rung} -> OBSERVED`,
        increment: 'Increment-2',
        reason: outcome.reason || 'cross-family corroborated; OBSERVED requires Lean + bounded faithfulness',
        needs_verification: true, // not autonomously settled — a stronger certification remains available
        belief: after.belief, // CORROBORATED
        soft_check: softCheck,
        tier: outcome.tier || null,
      });
    } else {
      if (typeof outcome.reason === 'string') notes.push(outcome.reason);
      advisory = Object.freeze({
        route: 'out-of-model',
        target: verifier ? verifier.route_target : 'out-of-model-certifier',
        increment: verifier ? verifier.increment : 'Increment-2',
        reason: outcome.reason || `routed ${claim.type} claim out of model`,
        needs_verification: true,
        belief: BELIEF.CONJECTURAL,
        commission: emitCommission(claim, verifier, rctx.commissioner),
      });
    }

    // STAMP the ledger: a STICKY re-assert refreshes meta + holds the rung (the flip law).
    const mergedMeta = { ...(after.meta || {}), verify_router: { verdict, routed, settled, grounded, observed, lifted, stamp, advisory, notes } };
    this.#ledger.assert({ id: claim.id, type: claim.type, meta: mergedMeta });

    return Object.freeze({
      claim_id: claim.id,
      claim_type: claim.type,
      verdict,
      settled,
      grounded,
      observed,
      lifted,
      routed,
      verifier: verifier
        ? Object.freeze({ name: verifier.name, family: verifier.family, tier: verifier.tier, increment: verifier.increment })
        : null,
      rung: after.rung,
      belief: after.belief,
      stamp: Object.freeze(stamp),
      advisory,
      notes: Object.freeze(notes),
    });
  }
}

/**
 * Convenience: build a router over a (optionally supplied) ledger + dispatcher and run a batch in
 * one call. Returns { ledger, router, summary }.
 */
export function routeClaims(claims, { ledger = new ClaimLedger(), dispatcher = null, commissioner = null, artifacts, artifact } = {}) {
  const router = new VerifyRouter({ ledger, dispatcher, commissioner });
  const summary = router.verify(claims, { artifacts, artifact });
  return { ledger, router, summary };
}

// B4 sole-resolve surface (structural inclusion for certifier arm sites).
export { isCertifierArmed, resolveRamanujanDepthKnobs, resolveRamanujanBand };

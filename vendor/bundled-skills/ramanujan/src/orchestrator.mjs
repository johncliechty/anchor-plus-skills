// Wave 23 — Autonomous orchestrator + no-dispatch canary (D4).
//
// THE AUTONOMOUS ORCHESTRATOR. This is the multi-pillar dispatch surface that GROWS the Wave-14
// single-pillar read-only shim (src/dispatch-shim.mjs) into a router over ALL SIX pillars — UNDERSTAND,
// SOLVE, VERIFY, DIALOGUE, FORMALIZE, CONTEXTUALIZE — while preserving, verbatim, the two load-bearing
// shim invariants the Wave-23 no-dispatch canary asserts on EVERY path:
//
//   (1) NO RUNG-FLIP on any orchestrator path. Like the shim, the orchestrator runs each pillar against
//       a promote-GUARDED ledger view (the Wave-14 ReadOnlyLedgerGuard) — promote() (the sole rung-
//       raiser) is UNREACHABLE on an orchestrator path, not merely unobserved. It wires NO out-of-model
//       adjudication dispatcher, so the firewall path can never mint an artifact and the Wave-4
//       adjudication gate is never reached. Claims still EMIT at the floor (UNVERIFIED); that is not a flip.
//
//   (2) NO COMMISSION-ID EMITTED on any orchestrator path. The orchestrator wires NO commissioner, so
//       every commission any pillar attaches is the minimal built-in EMIT-not-dispatch envelope
//       (emitted:true, dispatched:false) — a typed value describing what WOULD be dispatched out-of-model,
//       never a live spawn that mints a dispatched commission-id.
//
// THE THREE WAVE-23 DELIVERABLES this module realizes:
//
//   • USER-EXPLICIT DISPATCH. The orchestrator dispatches to a pillar ONLY when the user EXPLICITLY names
//     a valid pillar (`request.pillar`). It never infers a dispatch from the utterance.
//   • AN ADVISORY CLASSIFIER (classifyPillar). Given an utterance it SUGGESTS a likely pillar — but this
//     is ADVISORY ONLY: it is surfaced as a suggestion in the ASK affordance and NEVER triggers a
//     dispatch on its own. A confident classification still routes to ASK absent an explicit pillar.
//   • FAIL-SAFE ASK. With no explicit pillar (or an unrecognized one), the orchestrator returns an ASK —
//     it asks the user which pillar to use (carrying the advisory suggestion) rather than guessing. ASK
//     touches nothing: no pillar runs, no claim is emitted, no commission, no rung-flip.
//
// "Read-only" therefore means exactly, on every orchestrator path: a pillar may EMIT typed claims +
// advisories into the ledger, but the orchestrator can neither SETTLE a claim (raise a rung) nor DISPATCH
// a verdict (mint a commission-id). The A2(no-dispatch) canary (src/no-dispatch-canary.mjs) re-derives
// (1)+(2) independently over a battery of orchestrator AND Wave-14 shim paths and fails the build on a
// planted dispatch-leak / rung-flip.
//
// Pure node built-ins + the project's own spine modules (the six pillars, the A1 ledger, the A3 router,
// the emit-not-dispatch predicate, and the Wave-14 shim primitives this module re-uses). Runs under
// `node --test test/`.

import { ClaimLedger, RUNG, FLOOR_RUNG, BELIEF } from './claim-ledger.mjs';
import { comprehend } from './comprehension.mjs';
import { generate } from './generation.mjs';
import { VerifyRouter } from './verify-router.mjs';
import { DialogueMachine } from './dialogue-machine.mjs';
import { FormalizeMachine, SUITE_KIND } from './formalize-machine.mjs';
import { ContextualizeMachine } from './contextualize-machine.mjs';
import { COMMISSION_KIND, isEmittedNotDispatched } from './commission-emitters.mjs';
// GROW THE WAVE-14 SHIM: re-use its read-only guard + its EXACT no-dispatch predicate verbatim, so the
// orchestrator's invariant is the SAME structural object the Wave-23 canary regression-binds to the shim.
import { ReadOnlyLedgerGuard, checkShimInvariants, dispatchedCommissionId } from './dispatch-shim.mjs';
// W3 (Scope B) — the GATED autonomous-dispatch surface. The capability token OPENS the gate; the closed
// grammar decides which computational claims are autonomous-eligible. Absent a capability the orchestrator
// is unchanged (read-only, fail-safe-ASK) — the gate defaults to CLOSED.
import { isDispatchCapability } from './dispatch-capability.mjs';
import { recognize } from './firewall-grammar.mjs';
// B4 sole-resolve: orchestrate never freelances certifier:true — arm decision is
// frozen knobs from resolveRamanujanDepthKnobs / resolveRamanujanBand only.
import {
  isCertifierArmed,
  resolveRamanujanBand,
  resolveRamanujanDepthKnobs,
} from './triage-band.mjs';

// ---------------------------------------------------------------------------
// Constants — the six pillars, the read-only mode marker, the dispatch disposition.
// ---------------------------------------------------------------------------

/** The six pillars the autonomous orchestrator can route a user request to (read-only). */
export const PILLAR = Object.freeze({
  UNDERSTAND: 'understand',
  SOLVE: 'solve',
  VERIFY: 'verify',
  DIALOGUE: 'dialogue',
  FORMALIZE: 'formalize',
  CONTEXTUALIZE: 'contextualize',
});

/** The pillars as a list (introspection + exhaustiveness). */
export const PILLARS = Object.freeze(Object.values(PILLAR));

/** The orchestrator's mode marker. Increment-1 is a READ-ONLY router: it emits, it never settles/dispatches. */
export const ORCHESTRATOR_MODE = 'read-only';

/** The mode marker for a GATED-OPEN dispatch path (W3): a valid capability enabled autonomous settling. */
export const ORCHESTRATOR_MODE_GATED = 'gated-dispatch';

/** The disposition of a handled request: a read-only DISPATCH to a user-named pillar, or a fail-safe ASK. */
export const DISPATCH_DISPOSITION = Object.freeze({ DISPATCH: 'dispatch', ASK: 'ask' });

// ---------------------------------------------------------------------------
// The ADVISORY pillar classifier — a SUGGESTION, never a dispatch.
// ---------------------------------------------------------------------------

/**
 * The per-pillar keyword cues the advisory classifier scores an utterance against. Deliberately simple
 * and deterministic: this is an ADVISORY heuristic that proposes a likely pillar, NEVER an authority that
 * dispatches one. The orchestrator surfaces the suggestion in its ASK affordance and acts on it only if
 * the user then explicitly names that pillar.
 */
const PILLAR_CUES = Object.freeze({
  [PILLAR.UNDERSTAND]: ['understand', 'comprehend', 'explain', 'read', 'what does', 'parse', 'method', 'walk me through'],
  [PILLAR.SOLVE]: ['solve', 'find', 'compute', 'evaluate', 'prove that', 'work out', 'problem', 'derive'],
  [PILLAR.VERIFY]: ['verify', 'check', 'is this correct', 'validate', 'confirm', 'certify', 'is it true'],
  [PILLAR.DIALOGUE]: ['discuss', 'dialogue', 'is this settled', 'conjecture', 'argue', 'talk through', 'counterexample'],
  [PILLAR.FORMALIZE]: ['formalize', 'define', 'definition', 'forge', 'precise', 'make rigorous', 'monster'],
  [PILLAR.CONTEXTUALIZE]: ['contextualize', 'relate', 'connection', 'analogy', 'generalize', 'specialize', 'similar to', 'like'],
});

/**
 * THE ADVISORY CLASSIFIER. Score an utterance against each pillar's keyword cues and SUGGEST the
 * highest-scoring pillar. Pure + deterministic. ADVISORY ONLY — the orchestrator never dispatches on this
 * result; it is surfaced as a suggestion in the fail-safe ASK and acted on only via an explicit pillar.
 *
 * @param {string|undefined|null} utterance
 * @returns frozen { suggestion: pillar|null, confident:boolean, scores:Record<pillar,number>, reason:string }
 */
export function classifyPillar(utterance) {
  const text = typeof utterance === 'string' ? utterance.toLowerCase() : '';
  const scores = {};
  for (const pillar of PILLARS) {
    const cues = PILLAR_CUES[pillar];
    scores[pillar] = cues.reduce((n, cue) => (text.includes(cue) ? n + 1 : n), 0);
  }
  // The best-scoring pillar, with a deterministic tie-break by PILLARS order (the first listed wins a tie).
  let best = null;
  let bestScore = 0;
  let tied = false;
  for (const pillar of PILLARS) {
    if (scores[pillar] > bestScore) {
      best = pillar;
      bestScore = scores[pillar];
      tied = false;
    } else if (scores[pillar] === bestScore && bestScore > 0 && pillar !== best) {
      tied = true;
    }
  }
  const suggestion = bestScore > 0 ? best : null;
  // "confident" only means the heuristic found an unambiguous single best cue-match — it STILL never
  // licenses a dispatch (advisory only); it merely flavours the ASK affordance's suggested option.
  const confident = suggestion !== null && !tied;
  const reason =
    suggestion === null
      ? 'no pillar cue matched the utterance — advisory suggestion is null (fail-safe ASK names no default)'
      : `advisory: the utterance best matches the ${suggestion} pillar (score ${bestScore}${tied ? ', tie' : ''}) — SUGGESTION ONLY, not a dispatch`;
  return Object.freeze({ suggestion, confident, scores: Object.freeze(scores), reason });
}

// ---------------------------------------------------------------------------
// Commission collection — deep walk for every emit-not-dispatch envelope, anywhere.
// ---------------------------------------------------------------------------

const COMMISSION_KINDS = new Set(Object.values(COMMISSION_KIND));

/**
 * Is `node` a commission ENVELOPE? Identified STRUCTURALLY by the emit-not-dispatch contract signature —
 * both an `emitted` and a `dispatched` boolean — which is exactly the granularity isEmittedNotDispatched /
 * dispatchedCommissionId operate on. This recognizes BOTH the typed COMMISSION_KIND envelopes
 * (researchPrime / Gandalf SITUATE) AND the router's minimal built-in envelope (which carries no `kind`),
 * so the collector never misses a commission the no-dispatch invariant must inspect. A `kind` in
 * COMMISSION_KIND is accepted too (belt-and-braces) for any future kinded-but-flagless envelope.
 */
function isCommissionEnvelope(node) {
  return (
    node !== null &&
    typeof node === 'object' &&
    ((typeof node.emitted === 'boolean' && typeof node.dispatched === 'boolean') ||
      (typeof node.kind === 'string' && COMMISSION_KINDS.has(node.kind)))
  );
}

/**
 * Collect EVERY commission envelope reachable from a pillar's output, wherever it is nested (a router
 * advisory's `commission`, a dialogue/formalize emission's advisory payload, a contextualize emission's
 * top-level commission, the researchPrime leg nested inside a Gandalf SITUATE envelope, …). Robust to each
 * pillar's distinct advisory shape — it never misses a commission the no-dispatch invariant must inspect.
 * Deduped by object identity. Pure.
 *
 * @param {*} root
 * @returns {Array<object>} every distinct commission envelope reachable from root
 */
export function collectCommissionsDeep(root) {
  const out = [];
  const seen = new Set();
  const stack = [root];
  while (stack.length) {
    const node = stack.pop();
    if (!node || typeof node !== 'object') continue;
    if (seen.has(node)) continue;
    seen.add(node);
    if (isCommissionEnvelope(node)) {
      out.push(node);
    }
    if (Array.isArray(node)) {
      for (const v of node) stack.push(v);
    } else {
      for (const k of Object.keys(node)) stack.push(node[k]);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Rung-flip detection (shared with the Wave-14 shim's semantics).
// ---------------------------------------------------------------------------

function rungSnapshot(ledger) {
  const m = new Map();
  for (const id of ledger.ids()) m.set(id, ledger.rungOf(id));
  return m;
}

/**
 * The rung-flips between a before/after snapshot: a claim whose rung CHANGED, or a newly-admitted claim
 * that landed ABOVE the floor (UNVERIFIED). Admission-at-floor is not a flip. (Same semantics as the
 * Wave-14 shim's diffRungFlips, kept local so the orchestrator carries no hidden coupling to test code.)
 */
function diffRungFlips(before, after) {
  const flips = [];
  for (const [id, to] of after) {
    if (before.has(id)) {
      const from = before.get(id);
      if (from !== to) flips.push(Object.freeze({ id, from, to }));
    } else if (to !== FLOOR_RUNG) {
      flips.push(Object.freeze({ id, from: '(absent)', to }));
    }
  }
  return flips;
}

// ---------------------------------------------------------------------------
// The per-pillar READ-ONLY adapters — each runs a pillar against the promote-guard.
// ---------------------------------------------------------------------------

/**
 * Run the requested pillar READ-ONLY against the promote-guarded ledger view. Each adapter wires NO
 * dispatcher and NO commissioner (the read-only contract), so no pillar can settle a claim or mint a
 * dispatched commission. Returns the pillar's native structured output. Throws (fail-safe) if the
 * request omits the pillar-specific payload.
 */
function runPillarReadOnly(pillar, request, guard) {
  switch (pillar) {
    case PILLAR.UNDERSTAND: {
      if (!request.method || typeof request.method !== 'object') {
        throw new Error('orchestrator: the understand pillar requires request.method = { id?, subclaims:[...] }');
      }
      // Read-only: no dispatcher, no commissioner (identical to the Wave-14 shim).
      return Object.freeze({ pillar, kind: 'comprehension', comprehension: comprehend(request.method, { ledger: guard }) });
    }
    case PILLAR.SOLVE: {
      if (!request.problem || typeof request.problem !== 'object') {
        throw new Error('orchestrator: the solve pillar requires request.problem = { id?, goal, moves:[...] }');
      }
      // Generation only ever emits at the floor (UNVERIFIED) — read-only by construction.
      return Object.freeze({ pillar, kind: 'candidate', candidate: generate(request.problem, { ledger: guard }) });
    }
    case PILLAR.VERIFY: {
      if (!Array.isArray(request.claims) || request.claims.length === 0) {
        throw new Error('orchestrator: the verify pillar requires request.claims = [{ id, type, statement?, expr? }, ...]');
      }
      const router = new VerifyRouter({ ledger: guard }); // no dispatcher => every route ABSTAINS/FLAGS
      const results = request.claims.map((spec) => router.route(spec, {}));
      return Object.freeze({ pillar, kind: 'route', steps: Object.freeze(['DECOMPOSE', 'ROUTE']), results: Object.freeze(results) });
    }
    case PILLAR.DIALOGUE: {
      if (!Array.isArray(request.turns) || request.turns.length === 0) {
        throw new Error('orchestrator: the dialogue pillar requires request.turns = [{ intent, ... }, ...]');
      }
      const machine = new DialogueMachine({ ledger: guard, router: new VerifyRouter({ ledger: guard }) });
      const emissions = request.turns.map((t) => machine.turn(t));
      return Object.freeze({ pillar, kind: 'dialogue', emissions: Object.freeze(emissions) });
    }
    case PILLAR.FORMALIZE: {
      const f = request.forge;
      if (!f || typeof f !== 'object' || !f.claim || typeof f.claim.definition !== 'function') {
        throw new Error('orchestrator: the formalize pillar requires request.forge = { claim:{ id, definition:(x)=>boolean }, suite?:[], certificate? }');
      }
      const machine = new FormalizeMachine({ ledger: guard });
      const emissions = [machine.forge(f.claim)];
      const suite = Array.isArray(f.suite) ? f.suite : [];
      const rounds = Number.isInteger(f.rounds) ? f.rounds : 2;
      if (suite.length > 0) for (let i = 0; i < rounds; i++) machine.testRound(suite);
      // Even a (forged) out-of-model certificate cannot mint green here: the belief is never VERIFIED (no
      // adjudication dispatcher), so finalize() stamps requires-Phase-F. Read-only holds.
      emissions.push(machine.finalize(f.certificate ? { certificate: f.certificate } : {}));
      return Object.freeze({ pillar, kind: 'formalize', emissions: Object.freeze(emissions) });
    }
    case PILLAR.CONTEXTUALIZE: {
      const conns = request.connections ?? (request.connection ? [request.connection] : null);
      if (!Array.isArray(conns) || conns.length === 0) {
        throw new Error('orchestrator: the contextualize pillar requires request.connection or request.connections = [{ source, target, correspondence? }, ...]');
      }
      const machine = new ContextualizeMachine({ ledger: guard, router: new VerifyRouter({ ledger: guard }) });
      const emissions = conns.map((c) => machine.contextualize(c));
      return Object.freeze({ pillar, kind: 'contextualize', emissions: Object.freeze(emissions) });
    }
    default:
      /* istanbul ignore next — unreachable: handle() validates the pillar before dispatching. */
      throw new Error(`orchestrator: unknown pillar ${JSON.stringify(pillar)}`);
  }
}

// ---------------------------------------------------------------------------
// The GATED VERIFY path (W3) — runs ONLY when a valid DispatchCapability opened the gate.
// ---------------------------------------------------------------------------

/**
 * Run the VERIFY pillar with the gate OPEN: route against the REAL (promote-capable) ledger with the
 * capability's real AdjudicationDispatcher + commissioner. ONLY an IN-GRAMMAR COMPUTATIONAL claim (the
 * closed default-deny firewall grammar recognizes its `expr` as an exact-arithmetic literal computation)
 * gets a minted firewall artifact — the router's verifyComputationalFirewall then settles it to VERIFIED
 * through the Wave-4 single-use adjudication gate. Every OTHER claim (out-of-grammar, proof-bearing,
 * conceptual) gets NO artifact and ABSTAINs: the Honesty Law holds — no autonomous verifier settles those,
 * even with the gate open. Only the VERIFY pillar is gated; all other pillars stay read-only.
 */
function runVerifyGated(request, ledger, capability) {
  if (!Array.isArray(request.claims) || request.claims.length === 0) {
    throw new Error('orchestrator: the verify pillar requires request.claims = [{ id, type, statement?, expr? }, ...]');
  }
  const router = new VerifyRouter({ ledger, dispatcher: capability.dispatcher, commissioner: capability.commissioner });
  const results = request.claims.map((spec) => {
    const [id] = router.decompose(spec);
    const claim = ledger.get(id);
    // The AUTHORITATIVE, CLAIM-BOUND expr: decompose() persists spec.expr into the claim's meta, so the
    // stored meta.expr is the value recorded on THIS claim (never a call-time expr divorced from the claim).
    const expr = claim.meta ? claim.meta.expr : undefined;
    let artifact;
    // AUTONOMOUS-ELIGIBLE iff a computational claim whose expr the closed grammar recognizes IN-CLASS.
    // recognize() is pure (no spawn); the mint (capability.mint) is what runs the out-of-model subprocess.
    if (claim.type === 'computational' && expr !== undefined && recognize(expr).inGrammar) {
      artifact = capability.mint(id, expr);
    }
    // Thread the SAME claim-bound expr to the router so verifyComputationalFirewall INDEPENDENTLY re-runs
    // the closed-grammar check on exactly the expr the artifact was minted from — the defense-in-depth
    // re-check is NEVER skipped (it does not rely on the router re-deriving expr from the ledger).
    return router.route(id, { artifact, expr });
  });
  return Object.freeze({
    pillar: PILLAR.VERIFY,
    kind: 'route',
    gated: true,
    steps: Object.freeze(['DECOMPOSE', 'MINT?', 'ROUTE']),
    results: Object.freeze(results),
  });
}

// ---------------------------------------------------------------------------
// The autonomous orchestrator.
// ---------------------------------------------------------------------------

export class AutonomousOrchestrator {
  #ledger;
  #capability;

  /**
   * @param {{ledger?:ClaimLedger, capability?:object|null}} o
   *   ledger     — the shared A1 ledger to emit into (a fresh ClaimLedger by default).
   *   capability — an optional DispatchCapability (W3). Absent/null => the gate is CLOSED (read-only,
   *                fail-safe-ASK — the default, unchanged behavior). A valid capability OPENS the gate so
   *                the VERIFY pillar can autonomously settle in-grammar computations. A per-call capability
   *                passed to handle() overrides this default.
   */
  constructor({ ledger = new ClaimLedger(), capability = null } = {}) {
    if (!ledger || typeof ledger.assert !== 'function' || typeof ledger.promote !== 'function' || typeof ledger.get !== 'function') {
      throw new Error('AutonomousOrchestrator requires an A1 ClaimLedger ({assert, promote, get, has})');
    }
    this.#ledger = ledger;
    this.#capability = capability;
  }

  /** The shared ledger this orchestrator emits into. */
  get ledger() {
    return this.#ledger;
  }

  /** The pillars this orchestrator can route to. */
  get pillars() {
    return PILLARS;
  }

  /**
   * HANDLE a user request. The orchestrator dispatches READ-ONLY to a pillar ONLY when the user
   * EXPLICITLY names a valid one (`request.pillar`); otherwise it FAIL-SAFE ASKs (carrying the advisory
   * classifier's suggestion) rather than guessing. The advisory classifier never triggers a dispatch.
   *
   * @param {{pillar?:string, utterance?:string, method?, problem?, claims?, turns?, forge?, connection?, connections?}} request
   * @returns frozen handled result — a DISPATCH preview or an ASK affordance (see #dispatch / #ask).
   */
  handle(request, { capability } = {}) {
    if (!request || typeof request !== 'object') {
      throw new Error('AutonomousOrchestrator.handle() requires a request object { pillar?, utterance?, ... }');
    }
    // The gate token: a per-call capability wins; else the constructor default; else null (CLOSED).
    const cap = capability !== undefined ? capability : this.#capability;
    const explicit = request.pillar;
    // FAIL-SAFE ASK: no explicit pillar named — the orchestrator never auto-dispatches off the utterance.
    if (explicit === undefined || explicit === null) {
      return this.#ask(request, 'no explicit pillar named: the orchestrator never auto-dispatches from the utterance — advisory suggestion only');
    }
    // FAIL-SAFE ASK: an explicit but UNRECOGNIZED pillar is refused (never silently re-routed/guessed).
    if (!PILLARS.includes(explicit)) {
      return this.#ask(request, `unrecognized pillar ${JSON.stringify(explicit)} (valid: ${PILLARS.join(', ')})`);
    }
    return this.#dispatch(explicit, request, cap);
  }

  /** The fail-safe ASK affordance. Touches NOTHING: no pillar runs, no claim/commission/rung-flip. */
  #ask(request, reason) {
    const advisory = classifyPillar(request.utterance);
    const invariants = checkShimInvariants({ commissions: [], rungFlips: [] });
    return Object.freeze({
      disposition: DISPATCH_DISPOSITION.ASK,
      mode: ORCHESTRATOR_MODE,
      read_only: true,
      pillar: null,
      ask: Object.freeze({
        question: 'Which pillar should I route this to?',
        options: PILLARS,
        // The advisory suggestion is surfaced — but it is a SUGGESTION the user must confirm, not a dispatch.
        suggestion: advisory.suggestion,
        advisory,
        reason,
      }),
      // An ASK produced no pillar output: no commissions, no rung-flips — the predicate holds vacuously.
      commissions: Object.freeze([]),
      rungFlips: Object.freeze([]),
      noCommissionIdEmitted: invariants.noCommissionIdEmitted,
      noRungFlip: invariants.noRungFlip,
      held: invariants.held,
      invariants,
    });
  }

  /**
   * The multi-pillar DISPATCH. Snapshots rungs off the REAL ledger, runs the pillar, re-snapshots, and
   * re-derives the shim invariants over the actual commissions + rung-flips.
   *
   * CLOSED gate (no valid capability, or any pillar other than VERIFY): routes READ-ONLY through the
   * promote-throwing ReadOnlyLedgerGuard with NO dispatcher — no rung-flip, no dispatched commission-id are
   * structurally possible (the unchanged default). `held` is true.
   *
   * OPEN gate (a valid DispatchCapability + the VERIFY pillar): routes against the REAL promote-capable
   * ledger with the capability's real dispatcher; an in-grammar computational claim settles to VERIFIED.
   * Here a rung-flip IS expected — so `held` is honestly false — but ONLY the firewall class can flip
   * (proof/conceptual still ABSTAIN). The returned `invariants` describe what actually happened; the
   * gated-dispatch canary (below) asserts the gate-open teeth, the no-dispatch canary the gate-closed ones.
   */
  #dispatch(pillar, request, capability) {
    const gated = isDispatchCapability(capability) && pillar === PILLAR.VERIFY;
    const before = rungSnapshot(this.#ledger);
    let output;
    if (gated) {
      // GATE OPEN: the REAL (promote-capable) ledger + the capability's dispatcher. Autonomous settling
      // is bounded to the in-grammar computational (firewall) class by runVerifyGated + the router.
      output = runVerifyGated(request, this.#ledger, capability);
    } else {
      // GATE CLOSED (default): route READ-ONLY through the promote-guard. Any promote() throws (structural).
      const guard = new ReadOnlyLedgerGuard(this.#ledger);
      output = runPillarReadOnly(pillar, request, guard);
    }
    const after = rungSnapshot(this.#ledger);

    const commissions = collectCommissionsDeep(output);
    const rungFlips = diffRungFlips(before, after);
    const invariants = checkShimInvariants({ commissions, rungFlips });

    return Object.freeze({
      disposition: DISPATCH_DISPOSITION.DISPATCH,
      pillar,
      mode: gated ? ORCHESTRATOR_MODE_GATED : ORCHESTRATOR_MODE,
      read_only: !gated,
      gated,
      output,
      commissions: Object.freeze(commissions),
      rungFlips: Object.freeze(rungFlips),
      // The EXACT Wave-23 / Wave-14 predicate, evaluated on this orchestrator path (honest either way:
      // true on a CLOSED-gate read-only path; false on an OPEN-gate path that settled a computation).
      noCommissionIdEmitted: invariants.noCommissionIdEmitted,
      noRungFlip: invariants.noRungFlip,
      held: invariants.held,
      invariants,
    });
  }
}

/**
 * Convenience: build an orchestrator over an (optional) ledger and handle a single request in one call.
 * Returns the frozen handled result (a DISPATCH preview or an ASK affordance).
 */
/**
 * @param {object} request
 * @param {{
 *   ledger?: object,
 *   capability?: object,
 *   band?: { resolved?: { certifier?: boolean }, knobs?: { certifier?: boolean }, certifier?: boolean },
 *   depth?: string,
 *   triageLock?: object,
 *   env?: object,
 * }} [opts]
 */
export function orchestrate(
  request,
  { ledger, capability, band = null, depth, triageLock, env } = {},
) {
  // B4: when a depth lock surface is supplied, resolve knobs solely via resolveRamanujanBand.
  // Certifier arm is knobs.certifier only — never freelanced true, never tier-only env.
  let resolvedBand = band;
  if (
    resolvedBand == null &&
    (depth != null ||
      triageLock != null ||
      (env &&
        typeof env === 'object' &&
        (env.FOUNDRY_TRIAGE_DEPTH || env.RAMANUJAN_DEPTH)))
  ) {
    resolvedBand = resolveRamanujanBand({ depth, triageLock, env });
  }
  if (resolvedBand != null) {
    // Sole-resolve touch for structural inclusion; arm decision is frozen knobs only.
    void isCertifierArmed(resolvedBand);
    void resolveRamanujanDepthKnobs(resolvedBand.depth);
  }
  const handled = new AutonomousOrchestrator({ ledger, capability }).handle(request);
  if (resolvedBand != null && handled && typeof handled === 'object') {
    return Object.freeze({ ...handled, band: resolvedBand, certifierArmed: isCertifierArmed(resolvedBand) });
  }
  return handled;
}

// Re-export the rung/belief vocabulary + the re-used shim predicate so tests + later waves can branch
// without a second import.
export { RUNG, FLOOR_RUNG, BELIEF, checkShimInvariants, dispatchedCommissionId, isEmittedNotDispatched, SUITE_KIND };
export { isCertifierArmed, resolveRamanujanBand, resolveRamanujanDepthKnobs };

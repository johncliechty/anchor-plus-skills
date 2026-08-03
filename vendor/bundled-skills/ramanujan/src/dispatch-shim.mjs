// Wave 14 — M1 read-only dispatch shim (B-shim) — closes Milestone M1 (comprehension-only preview).
//
// Milestone M1 is the FIRST end-user-visible slice of Ramanujan: a single pillar (UNDERSTAND), wired
// end-to-end through the real spine, but in a deliberately READ-ONLY "preview" mode. This shim is the
// thin dispatch surface that takes a user request and routes it to the UNDERSTAND pillar (the Wave-10
// comprehension protocol) — and NOTHING more. It is the seed the Wave-23 autonomous orchestrator
// grows into multi-pillar routing; here it is intentionally minimal and single-pillar.
//
// THE TWO LOAD-BEARING INVARIANTS (the EXACT predicate the Wave-23 no-dispatch canary will assert,
// checked wave-locally here and regression-bound by Wave 23):
//
//   (1) NO RUNG-FLIP on any shim path. The shim raises NO rung. It runs comprehension READ-ONLY — it
//       wires NO out-of-model adjudication dispatcher, so the firewall path can never mint an artifact
//       and the Wave-4 adjudication gate (the sole rung-raiser) is never reached. To make this a
//       STRUCTURAL guarantee rather than a mere observed outcome, the shim runs the spine against a
//       promote-GUARDED ledger view (ReadOnlyLedgerGuard) that THROWS on any promote() — so a rung-
//       flip on the shim path is not just absent, it is unreachable. Claims still EMIT into the real
//       ledger at the floor rung (UNVERIFIED); admission-at-floor is not a flip.
//
//   (2) NO COMMISSION-ID EMITTED on any shim path. The shim never DISPATCHES a commission. It wires NO
//       commissioner, so every advisory the router attaches is the minimal built-in EMIT-not-dispatch
//       envelope (emitted:true, dispatched:false) — a typed value describing what WOULD be dispatched
//       out-of-model, never a live spawn that mints a dispatched commission-id. The check collects
//       every commission the shim produced and proves none is dispatched (and none surfaces a
//       dispatched commission-id).
//
// "Read-only" therefore means exactly: the shim can EMIT typed claims + advisories into the ledger,
// but it can neither SETTLE a claim (raise a rung) nor DISPATCH a verdict (mint a commission-id). A
// proof/conceptual sub-claim ABSTAINs to CONJECTURAL and an APPLICABLE computation ABSTAINs too (the
// honest no-minter arm) — every claim stays at UNVERIFIED in the preview.
//
// Pure node built-ins + the project's own spine modules (comprehension, claim-ledger, the emit-not-
// dispatch predicate). Runs under `node --test test/`.

import { ClaimLedger, RUNG, FLOOR_RUNG } from './claim-ledger.mjs';
import { comprehend } from './comprehension.mjs';
import { isEmittedNotDispatched } from './commission-emitters.mjs';

// ---------------------------------------------------------------------------
// Constants — the single pillar M1 exposes, and the read-only mode marker.
// ---------------------------------------------------------------------------

/** The pillars the M1 shim can dispatch to. M1 is comprehension-only: UNDERSTAND, and only UNDERSTAND. */
export const SHIM_PILLAR = Object.freeze({ UNDERSTAND: 'understand' });

/** The single supported pillar, as a list (introspection + exhaustiveness). */
export const SHIM_PILLARS = Object.freeze([SHIM_PILLAR.UNDERSTAND]);

/** The shim's mode marker. M1 is a READ-ONLY preview: it emits, it never settles or dispatches. */
export const SHIM_MODE = 'read-only';

// ---------------------------------------------------------------------------
// The read-only ledger guard — makes "no rung-flip" a STRUCTURAL invariant.
// ---------------------------------------------------------------------------

/**
 * A pass-through view over an A1 ClaimLedger that delegates every READ + the floor-only assert(), but
 * THROWS on promote() — the sole rung-raiser. Running the comprehension spine against this guard makes
 * a rung-flip on the shim path UNREACHABLE (not merely unobserved): any attempt to raise a rung faults
 * loudly. assert() is still delegated because it only ever admits at/below the floor and is sticky — it
 * can never raise a rung — so claims + the router's sticky stamp still land in the real ledger.
 *
 * It is shaped as an A1 ledger (assert/promote/get/has/…) so VerifyRouter + ComprehensionProtocol's
 * isLedgerLike checks accept it.
 */
export class ReadOnlyLedgerGuard {
  #inner;

  constructor(inner) {
    if (!inner || typeof inner.assert !== 'function' || typeof inner.get !== 'function' || typeof inner.has !== 'function') {
      throw new Error('ReadOnlyLedgerGuard requires an A1 ClaimLedger to wrap');
    }
    this.#inner = inner;
  }

  /** The wrapped ledger (so callers can snapshot rungs off the real store). */
  get inner() {
    return this.#inner;
  }

  // floor-only admission + sticky stamp re-assert: delegated (never raises a rung).
  assert(claim) {
    return this.#inner.assert(claim);
  }

  // THE READ-ONLY GUARD: promote() is the sole rung-raiser; on the shim path it must never be called.
  promote() {
    throw new Error(
      'ReadOnlyDispatchShim is READ-ONLY: promote() (the sole rung-raiser) is forbidden on a shim path — ' +
        'no rung-flip is permitted (M1 comprehension-only preview)',
    );
  }

  // reads — straight delegation.
  has(id) { return this.#inner.has(id); }
  get(id) { return this.#inner.get(id); }
  rungOf(id) { return this.#inner.rungOf(id); }
  beliefOf(id) { return this.#inner.beliefOf(id); }
  ids() { return this.#inner.ids(); }
  all() { return this.#inner.all(); }
  get size() { return this.#inner.size; }
}

// ---------------------------------------------------------------------------
// Commission-id detection (the emit-not-dispatch boundary, dispatch side).
// ---------------------------------------------------------------------------

/**
 * The DISPATCHED commission-id carried by an envelope, or null if the envelope is not dispatched. An
 * emit-not-dispatch envelope (dispatched:false) is NOT a dispatched commission and yields null; only an
 * envelope that claims dispatched:true surfaces a dispatched commission-id (the thing the shim must
 * never produce). Pure.
 */
export function dispatchedCommissionId(envelope) {
  if (!envelope || typeof envelope !== 'object') return null;
  if (envelope.dispatched !== true) return null; // emit-not-dispatch => no dispatched id
  return (
    envelope.commission_id ??
    envelope.researchprime_commission_id ??
    envelope.id ??
    '<dispatched-commission-without-id>'
  );
}

/** Collect every commission envelope the comprehension's advisories carry (one per routed claim). */
function collectCommissions(comprehension) {
  const out = [];
  for (const c of comprehension.claims) {
    if (c.advisory && c.advisory.commission) out.push(c.advisory.commission);
  }
  return out;
}

// ---------------------------------------------------------------------------
// The wave-local check — the EXACT Wave-23 no-dispatch predicate.
// ---------------------------------------------------------------------------

/**
 * Apply the no-dispatch predicate to a shim preview's raw facts. Pure, and runnable on any object
 * carrying { commissions, rungFlips } — so it has teeth: hand it a preview with a dispatched commission
 * or a flipped rung and it reports held:false. This is the exact predicate Wave-23's A2(no-dispatch)
 * canary asserts, regression-bound to this shim path.
 *
 * @param {{commissions?:Array, rungFlips?:Array}} preview
 * @returns frozen { noCommissionIdEmitted, noRungFlip, held, dispatchedCommissionIds, rungFlips, violations }
 */
export function checkShimInvariants(preview) {
  const commissions = Array.isArray(preview?.commissions) ? preview.commissions : [];
  const rungFlips = Array.isArray(preview?.rungFlips) ? preview.rungFlips : [];

  // (2) NO COMMISSION-ID EMITTED — every commission must be emit-not-dispatch; none may surface a
  //     dispatched commission-id.
  const dispatched = commissions.filter((c) => !isEmittedNotDispatched(c));
  const dispatchedCommissionIds = commissions.map(dispatchedCommissionId).filter((x) => x !== null);
  const noCommissionIdEmitted = dispatched.length === 0 && dispatchedCommissionIds.length === 0;

  // (1) NO RUNG-FLIP — no claim's rung changed (and no claim was admitted above the floor).
  const noRungFlip = rungFlips.length === 0;

  const violations = [];
  if (!noCommissionIdEmitted) {
    violations.push(
      `commission(s) dispatched on a shim path: ${dispatchedCommissionIds.length} dispatched id(s) ` +
        `[${dispatchedCommissionIds.join(', ')}], ${dispatched.length} non-emit-not-dispatch envelope(s)`,
    );
  }
  if (!noRungFlip) {
    violations.push(`rung-flip(s) on a shim path: ${rungFlips.map((f) => `${f.id} ${f.from}->${f.to}`).join('; ')}`);
  }

  return Object.freeze({
    noCommissionIdEmitted,
    noRungFlip,
    held: noCommissionIdEmitted && noRungFlip,
    dispatchedCommissionIds: Object.freeze(dispatchedCommissionIds),
    rungFlips: Object.freeze(rungFlips),
    violations: Object.freeze(violations),
  });
}

// ---------------------------------------------------------------------------
// The shim.
// ---------------------------------------------------------------------------

function rungSnapshot(ledger) {
  const m = new Map();
  for (const id of ledger.ids()) m.set(id, ledger.rungOf(id));
  return m;
}

/**
 * Compute the rung-flips between a before/after rung snapshot. A flip is a claim whose rung CHANGED, or
 * a newly-admitted claim that landed ABOVE the floor (UNVERIFIED). Admission-at-floor is not a flip.
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

/**
 * The minimal READ-ONLY single-pillar dispatch shim (M1). Routes a user request to the UNDERSTAND
 * pillar (the Wave-10 comprehension protocol) read-only — emitting typed claims + advisories without
 * ever settling a claim or dispatching a commission.
 */
export class ReadOnlyDispatchShim {
  #ledger;

  /**
   * @param {{ledger?:ClaimLedger}} o — the shared A1 ledger to emit into (a fresh ClaimLedger by default).
   */
  constructor({ ledger = new ClaimLedger() } = {}) {
    if (!ledger || typeof ledger.assert !== 'function' || typeof ledger.promote !== 'function' || typeof ledger.get !== 'function') {
      throw new Error('ReadOnlyDispatchShim requires an A1 ClaimLedger ({assert, promote, get, has})');
    }
    this.#ledger = ledger;
  }

  /** The single pillar this M1 shim dispatches to. */
  get pillar() {
    return SHIM_PILLAR.UNDERSTAND;
  }

  /** The shared ledger this shim emits into. */
  get ledger() {
    return this.#ledger;
  }

  /**
   * Dispatch a user request to UNDERSTAND, READ-ONLY. A request is { pillar?, method } — `pillar`
   * defaults to (and must be) UNDERSTAND (M1 is single-pillar; any other pillar is fail-safe rejected),
   * and `method` is the comprehension method spec { id?, subclaims:[...] }.
   *
   * Runs comprehension against a promote-guarded ledger view with NO dispatcher and NO commissioner, so
   * the shim path can neither raise a rung nor dispatch a commission. Returns a frozen preview that
   * embeds the laddered comprehension, the emitted commissions, the (empty) rung-flips, and the
   * wave-local no-dispatch verdict.
   *
   * @param {{pillar?:string, method:object}} request
   */
  dispatch(request) {
    if (!request || typeof request !== 'object') {
      throw new Error('ReadOnlyDispatchShim.dispatch() requires a request { pillar?, method }');
    }
    const pillar = request.pillar === undefined || request.pillar === null ? SHIM_PILLAR.UNDERSTAND : request.pillar;
    // FAIL-SAFE single-pillar: M1 routes ONLY to UNDERSTAND. Anything else is refused (never silently
    // re-routed) — the orchestrator that grows multi-pillar routing is Wave 23.
    if (pillar !== SHIM_PILLAR.UNDERSTAND) {
      throw new Error(
        `ReadOnlyDispatchShim is the M1 comprehension-only preview: only the ${SHIM_PILLAR.UNDERSTAND} pillar is ` +
          `supported (got ${JSON.stringify(pillar)}); multi-pillar routing is Wave 23`,
      );
    }
    if (!request.method || typeof request.method !== 'object') {
      throw new Error('ReadOnlyDispatchShim.dispatch() requires request.method = { id?, subclaims:[...] }');
    }

    // Snapshot rungs off the REAL ledger, route READ-ONLY through the promote-guard (no dispatcher /
    // no commissioner), then re-snapshot. Any promote() attempt throws inside the guard.
    const before = rungSnapshot(this.#ledger);
    const guard = new ReadOnlyLedgerGuard(this.#ledger);
    const comprehension = comprehend(request.method, { ledger: guard /* read-only: no dispatcher, no commissioner */ });
    const after = rungSnapshot(this.#ledger);

    const commissions = collectCommissions(comprehension);
    const rungFlips = diffRungFlips(before, after);
    const invariants = checkShimInvariants({ commissions, rungFlips });

    return Object.freeze({
      pillar: SHIM_PILLAR.UNDERSTAND,
      mode: SHIM_MODE,
      read_only: true,
      method_id: comprehension.method_id,
      comprehension,
      commissions: Object.freeze(commissions),
      rungFlips: Object.freeze(rungFlips),
      // The EXACT Wave-23 predicate, evaluated on this shim path.
      noCommissionIdEmitted: invariants.noCommissionIdEmitted,
      noRungFlip: invariants.noRungFlip,
      held: invariants.held,
      invariants,
    });
  }
}

/**
 * Convenience: build a read-only shim over a (optional) ledger and dispatch a single request to
 * UNDERSTAND in one call. Returns the frozen preview.
 */
export function previewUnderstand(request, { ledger } = {}) {
  return new ReadOnlyDispatchShim({ ledger }).dispatch(request);
}

// Re-export the rung vocabulary so tests + later waves can branch without a second import.
export { RUNG, FLOOR_RUNG };

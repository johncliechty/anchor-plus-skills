// drivers/reliability-breaker.mjs — Foreman Wave 2 (Phase A, part 2): the three
// hardening primitives layered ON TOP OF the Wave-1 reliability wrapper. Each is a
// PURE, deterministic unit (injectable clock + injectable timers) so it is verifiable
// without a live model call, exactly like the Wave-7 transport taxonomy:
//
//   (1) a LIGHT PER-PROVIDER CIRCUIT BREAKER (`makePerProviderBreaker`). After N
//       CONSECUTIVE recoverable failures to ONE provider the breaker OPENS and the
//       wrapper FAILS FAST (a `BreakerOpenError`, non-recoverable, so it is never
//       retried) — it degrades that provider for the session instead of hammering a
//       sick backend. After a cooldown it goes HALF-OPEN to admit a single probe; a
//       success CLOSES it (recovered), a fresh failure RE-OPENS it. "Light" = the
//       Grasscatched heavy/persistent breaker is explicitly NOT built (in-memory,
//       per-session, no disk).
//
//   (2) an IDLE-NO-OUTPUT SLIVER (`runWithIdleWatchdog`) layered OVER the existing
//       wall-clock kill (proc-guard's per-call timeout). The wall-clock kill bounds
//       TOTAL runtime; the idle sliver bounds time-since-last-OUTPUT, so a wedged
//       call that has gone silent is detected + KILLED (its AbortSignal is raised)
//       well before the coarse wall-clock budget elapses. Output is signalled by the
//       wrapped agent calling the injected `heartbeat()`; each heartbeat re-arms the
//       idle window. An idle kill surfaces as a recoverable timeout-class fault, so
//       the Wave-1 typed-retry path retries it (and a chronically idle provider then
//       trips the breaker via (1)).
//
// The anti-laundering telemetry (every retry logged as its own validated record so
// the Judge SEES a retried call) lives in the wrapper itself (reliability.mjs), built
// from `makeTelemetryRecord` in foreman/bin/transport.mjs — this module stays pure of
// the agent seam.

import { EXIT_CLASSES } from '../foreman/bin/transport.mjs';

// ---------------------------------------------------------------------------
// (1) Per-provider circuit breaker.
// ---------------------------------------------------------------------------

/** The three breaker states. CLOSED = healthy, OPEN = failing-fast, HALF_OPEN = probing. */
export const BREAKER_STATES = Object.freeze({ CLOSED: 'closed', OPEN: 'open', HALF_OPEN: 'half-open' });

/**
 * Thrown when a call is refused because its provider's breaker is OPEN. It carries a
 * precomputed `{ class, recoverable:false }` classification so the Wave-1 wrapper
 * treats a fail-fast as NON-recoverable and never retries it (a degrade, not a fault
 * to grind on). `breakerOpen` flags it for callers that want to branch on a degrade.
 */
export class BreakerOpenError extends Error {
  constructor(provider, detail) {
    super(`circuit breaker OPEN for provider "${provider}" — failing fast (${detail})`);
    this.name = 'BreakerOpenError';
    this.provider = provider;
    this.breakerOpen = true;
    this.classification = { class: 'breaker-open', recoverable: false };
  }
}

/**
 * Build a light, in-memory, per-provider circuit breaker.
 *
 * @param {object}     [o]
 * @param {number}     [o.threshold=5]    consecutive recoverable failures that OPEN the breaker
 * @param {number}     [o.cooldownMs=30000] OPEN→HALF_OPEN dwell before a probe is admitted
 * @param {()=>number} [o.now=Date.now]   injectable clock (ms) for deterministic tests
 * @param {Function}   [o.log=()=>{}]
 * @returns {{
 *   beforeCall:(provider:string)=>void,          // throws BreakerOpenError iff OPEN + still cooling
 *   onSuccess:(provider:string)=>void,           // CLOSE + reset the consecutive count
 *   onRecoverableFailure:(provider:string)=>void,// count toward (or re-trip) the breaker
 *   stateOf:(provider:string)=>{state:string,fails:number,openedAt:number},
 * }}
 */
export function makePerProviderBreaker({ threshold = 5, cooldownMs = 30_000, now = Date.now, log = () => {} } = {}) {
  if (!Number.isInteger(threshold) || threshold < 1) {
    throw new TypeError('makePerProviderBreaker: threshold must be a positive integer');
  }
  // provider -> { state, fails, openedAt }
  const cells = new Map();
  const cell = (provider) => {
    let c = cells.get(provider);
    if (!c) { c = { state: BREAKER_STATES.CLOSED, fails: 0, openedAt: 0 }; cells.set(provider, c); }
    return c;
  };

  /** Admit-or-refuse a call. OPEN + still cooling ⇒ throw (fail fast); OPEN + cooled ⇒ HALF_OPEN probe. */
  function beforeCall(provider) {
    const c = cell(provider);
    if (c.state === BREAKER_STATES.OPEN) {
      const elapsed = now() - c.openedAt;
      if (elapsed < cooldownMs) {
        throw new BreakerOpenError(
          provider,
          `${c.fails} consecutive recoverable failures; ${cooldownMs - elapsed}ms until a probe is admitted`,
        );
      }
      // Cooldown elapsed: admit exactly ONE probe under HALF_OPEN.
      c.state = BREAKER_STATES.HALF_OPEN;
      log(`reliability/breaker: "${provider}" cooled down — admitting a HALF_OPEN probe`);
    }
    // CLOSED or HALF_OPEN: the call is admitted.
  }

  /** A clean call: the provider is healthy again — CLOSE and clear the streak. */
  function onSuccess(provider) {
    const c = cell(provider);
    if (c.state !== BREAKER_STATES.CLOSED || c.fails !== 0) {
      log(`reliability/breaker: "${provider}" recovered — CLOSED`);
    }
    c.state = BREAKER_STATES.CLOSED;
    c.fails = 0;
    c.openedAt = 0;
  }

  /**
   * A recoverable (transient transport) failure of a logical call. Increments the
   * consecutive streak; OPENS once it reaches the threshold, OR immediately RE-OPENS
   * a HALF_OPEN probe that failed (the provider is still sick).
   */
  function onRecoverableFailure(provider) {
    const c = cell(provider);
    c.fails += 1;
    if (c.state === BREAKER_STATES.HALF_OPEN || c.fails >= threshold) {
      const wasOpen = c.state === BREAKER_STATES.OPEN;
      c.state = BREAKER_STATES.OPEN;
      c.openedAt = now();
      if (!wasOpen) log(`reliability/breaker: "${provider}" OPENED after ${c.fails} consecutive recoverable failures`);
    }
  }

  return {
    beforeCall,
    onSuccess,
    onRecoverableFailure,
    stateOf: (provider) => { const c = cell(provider); return { state: c.state, fails: c.fails, openedAt: c.openedAt }; },
  };
}

// ---------------------------------------------------------------------------
// (2) Idle-no-output sliver (over the existing wall-clock kill).
// ---------------------------------------------------------------------------

/** Build the recoverable, timeout-class fault an idle kill surfaces as (so it is retried). */
export function makeIdleFault(idleMs) {
  // `exit:{timedOut:true}` routes through classifyExit ⇒ TIMEOUT_KILLED ⇒ recoverable,
  // so an idle kill is handled by the SAME typed-retry path as the wall-clock timeout.
  return Object.assign(
    new Error(`idle: no output for ${idleMs}ms — call killed by the idle sliver`),
    { exit: { timedOut: true }, idleKilled: true, idleMs },
  );
}

const defaultScheduleIdle = (cb, ms) => { const t = setTimeout(cb, ms); if (t && typeof t.unref === 'function') t.unref(); return t; };
const defaultCancelIdle = (h) => { if (h != null) clearTimeout(h); };

/**
 * Run one agent attempt under an idle (no-output) watchdog OVER the caller's existing
 * wall-clock kill. The watchdog hands the call an `AbortSignal` and a `heartbeat()`:
 * every `heartbeat()` re-arms a fresh `idleMs` window; if no heartbeat arrives within
 * the window the signal is ABORTED (the kill) and the attempt REJECTS with a
 * recoverable idle fault. The first settle (resolve OR reject, by the call OR the
 * watchdog) wins and disarms the timer — exactly one outcome.
 *
 * With `idleMs <= 0` the watchdog is INERT and fully transparent: the call runs with
 * no signal/heartbeat injection, so a wrapper that does not opt into the sliver keeps
 * Wave-1's byte-for-byte passthrough behavior.
 *
 * @param {(h:{signal?:AbortSignal, heartbeat:()=>void})=>Promise<any>} call
 * @param {object}   [o]
 * @param {number}   [o.idleMs=0]
 * @param {Function} [o.scheduleIdle]  `(cb, ms) => handle` (injectable timer for tests)
 * @param {Function} [o.cancelIdle]    `(handle) => void`
 * @param {Function} [o.onIdleKill]    observer invoked when the idle sliver fires
 * @returns {Promise<any>}
 */
export function runWithIdleWatchdog(call, {
  idleMs = 0,
  scheduleIdle = defaultScheduleIdle,
  cancelIdle = defaultCancelIdle,
  onIdleKill = () => {},
} = {}) {
  if (!idleMs || idleMs <= 0) {
    // Inert: transparent passthrough (no signal/heartbeat ⇒ unchanged opts upstream).
    return call({ signal: undefined, heartbeat: () => {} });
  }

  const controller = new AbortController();
  let handle = null;
  let settled = false;

  return new Promise((resolve, reject) => {
    const disarm = () => { if (handle != null) { cancelIdle(handle); handle = null; } };
    const arm = () => {
      if (settled) return;
      disarm();
      handle = scheduleIdle(() => {
        if (settled) return;
        settled = true;
        disarm();
        try { controller.abort(); } catch { /* AbortController.abort never throws, but be defensive */ }
        const fault = makeIdleFault(idleMs);
        try { onIdleKill(fault); } catch { /* an observer must never swallow the kill */ }
        reject(fault);
      }, idleMs);
    };
    const heartbeat = () => { if (!settled) arm(); }; // each output re-arms the window

    arm(); // start the first idle window before the call runs
    // Defer the call one microtask so a synchronous throw still routes through .catch.
    Promise.resolve()
      .then(() => call({ signal: controller.signal, heartbeat }))
      .then(
        (v) => { if (!settled) { settled = true; disarm(); resolve(v); } },
        (e) => { if (!settled) { settled = true; disarm(); reject(e); } },
      );
  });
}

export { EXIT_CLASSES };

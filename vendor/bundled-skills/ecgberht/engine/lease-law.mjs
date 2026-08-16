/**
 * Wave 13 — Lease law (TTL, STALE distinct from DEAD, mono/seq clock, anti-flap).
 *
 * Identical law is reused by Wave-20's in-session executor (S14). Status truth
 * never peeks at live pids inside the composer — only durable lease events
 * (via the host-agnostic status-ingestion seam) decide RUNNING / STALE / DEAD.
 *
 * Clock: monotonic or seq-anchored. Wall-clock skew cannot move lease TTL.
 * Anti-flap: edge-triggered state_since + hysteresis near the TTL boundary.
 *
 * Stdlib only. No host-absolute paths. Avoids STATUS-v1 bare `STALE` literal
 * (portfolio freshness axis) — run liveness uses lowercase `stale` / `dead`.
 */

/** Default lease TTL (ms) — past this without renew → dead immediately. */
export const LEASE_TTL_MS = 30_000;

/**
 * Soft-stale fraction of TTL. Between soft and hard TTL the run is `stale`
 * (distinct from dead). Default 0.8 → stale window = last 20% of TTL.
 */
export const LEASE_STALE_FRACTION = 0.8;

/** Hysteresis (ms) — state must hold past a boundary this long before flipping. */
export const LEASE_HYSTERESIS_MS = 2_000;

/** Default renew interval (ms) — wrapper renews well inside the soft-stale edge. */
export const LEASE_RENEW_INTERVAL_MS = 10_000;

/** Named durability: leases are S12 outbox records (or S14 in Wave 20). */
export const LEASE_STORE = 'S12';

/**
 * Run-liveness vocabulary (Wave 13). Lowercase values avoid STATUS-v1
 * CODE_LITERAL collisions (`STALE` is portfolio freshness only).
 */
export const RUN_LIVENESS = Object.freeze({
  RUNNING: 'running',
  STALE: 'stale',
  DEAD: 'dead',
  PARKED: 'parked',
  UNKNOWN: 'liveness_unknown',
  STRANDED: 'stranded',
});

/**
 * Soft-stale threshold (ms) derived from TTL.
 * @param {number} [ttlMs]
 * @returns {number}
 */
export function leaseStaleAfterMs(ttlMs = LEASE_TTL_MS) {
  const ttl = Number(ttlMs);
  if (!Number.isFinite(ttl) || ttl <= 0) return LEASE_TTL_MS * LEASE_STALE_FRACTION;
  return Math.floor(ttl * LEASE_STALE_FRACTION);
}

/**
 * Default monotonic clock (hrtime ms). Wall skew cannot move this.
 * @returns {number}
 */
export function defaultLeaseMonoMs() {
  return Number(process.hrtime.bigint() / 1_000_000n);
}

/**
 * @param {{ monoNow?: () => number, wallNow?: () => string|number }} [opts]
 */
export function resolveLeaseClocks(opts = {}) {
  const monoNow =
    typeof opts.monoNow === 'function' ? opts.monoNow : defaultLeaseMonoMs;
  const wallNow =
    typeof opts.wallNow === 'function'
      ? opts.wallNow
      : () => new Date().toISOString();
  return { monoNow, wallNow };
}

/**
 * Pure lease evaluation. TTL is mono/seq-anchored — pass `nowMono` from the
 * same clock family as `lease.last_renew_mono_ms` (or `lease.seq` + seq clock).
 *
 * Anti-flap: when `prev` is supplied with `state` + `state_since_mono` +
 * optional `pending_state` / `pending_since_mono`, hysteresis requires the
 * candidate state to hold for LEASE_HYSTERESIS_MS before committing a flip.
 * `state_since_mono` is edge-triggered (only moves on committed flips).
 *
 * @param {{
 *   last_renew_mono_ms?: number|null,
 *   seq?: number|null,
 *   seq_anchor_mono_ms?: number|null,
 *   parked?: boolean,
 * }} lease
 * @param {{
 *   nowMono: number,
 *   ttlMs?: number,
 *   staleAfterMs?: number,
 *   hysteresisMs?: number,
 *   prev?: {
 *     state: string,
 *     state_since_mono: number,
 *     pending_state?: string|null,
 *     pending_since_mono?: number|null,
 *   }|null,
 * }} opts
 * @returns {{
 *   state: string,
 *   state_since_mono: number,
 *   pending_state: string|null,
 *   pending_since_mono: number|null,
 *   age_ms: number|null,
 *   ttl_ms: number,
 *   stale_after_ms: number,
 *   cause: string|null,
 *   flipped: boolean,
 * }}
 */
export function evaluateLeaseState(lease, opts) {
  const nowMono = Number(opts.nowMono);
  const ttlMs = Number(opts.ttlMs ?? LEASE_TTL_MS);
  const staleAfterMs = Number(
    opts.staleAfterMs ?? leaseStaleAfterMs(ttlMs),
  );
  const hysteresisMs = Number(opts.hysteresisMs ?? LEASE_HYSTERESIS_MS);
  const prev = opts.prev ?? null;

  if (lease && lease.parked === true) {
    const state = RUN_LIVENESS.PARKED;
    const state_since_mono =
      prev && prev.state === state ? prev.state_since_mono : nowMono;
    return {
      state,
      state_since_mono,
      pending_state: null,
      pending_since_mono: null,
      age_ms: null,
      ttl_ms: ttlMs,
      stale_after_ms: staleAfterMs,
      cause: 'parked',
      flipped: !prev || prev.state !== state,
    };
  }

  // Seq-anchored mode: when last_renew_mono is absent but seq + seq_anchor exist
  let lastRenew = lease?.last_renew_mono_ms;
  if (
    (lastRenew == null || !Number.isFinite(Number(lastRenew))) &&
    lease?.seq != null &&
    lease?.seq_anchor_mono_ms != null
  ) {
    // Treat each seq unit as "still alive at anchor" — age 0 when seq present
    lastRenew = Number(lease.seq_anchor_mono_ms);
  }

  if (lastRenew == null || !Number.isFinite(Number(lastRenew))) {
    const state = RUN_LIVENESS.UNKNOWN;
    const state_since_mono =
      prev && prev.state === state ? prev.state_since_mono : nowMono;
    return {
      state,
      state_since_mono,
      pending_state: null,
      pending_since_mono: null,
      age_ms: null,
      ttl_ms: ttlMs,
      stale_after_ms: staleAfterMs,
      cause: 'no_lease_renewal',
      flipped: !prev || prev.state !== state,
    };
  }

  const age = Math.max(0, nowMono - Number(lastRenew));
  let candidate;
  let cause;
  if (age > ttlMs) {
    candidate = RUN_LIVENESS.DEAD;
    cause = 'lease_expired';
  } else if (age > staleAfterMs) {
    candidate = RUN_LIVENESS.STALE;
    cause = 'lease_soft_stale';
  } else {
    candidate = RUN_LIVENESS.RUNNING;
    cause = null;
  }

  // No prior sample — take candidate immediately (first observation)
  if (!prev || !prev.state) {
    return {
      state: candidate,
      state_since_mono: nowMono,
      pending_state: null,
      pending_since_mono: null,
      age_ms: age,
      ttl_ms: ttlMs,
      stale_after_ms: staleAfterMs,
      cause,
      flipped: true,
    };
  }

  if (candidate === prev.state) {
    // Holding current state — clear any pending contrary edge
    return {
      state: prev.state,
      state_since_mono: prev.state_since_mono,
      pending_state: null,
      pending_since_mono: null,
      age_ms: age,
      ttl_ms: ttlMs,
      stale_after_ms: staleAfterMs,
      cause: candidate === RUN_LIVENESS.DEAD ? 'lease_expired' : cause,
      flipped: false,
    };
  }

  // Hard TTL expiry is immediate: DEAD must not wait for anti-flap hysteresis.
  // (Hysteresis only gates recovery / non-terminal edges so jitter cannot
  // flap RUNNING↔DEAD; once age is past hard TTL the run is dead by law.)
  if (candidate === RUN_LIVENESS.DEAD) {
    return {
      state: RUN_LIVENESS.DEAD,
      state_since_mono: nowMono,
      pending_state: null,
      pending_since_mono: null,
      age_ms: age,
      ttl_ms: ttlMs,
      stale_after_ms: staleAfterMs,
      cause: 'lease_expired',
      flipped: true,
    };
  }

  // Candidate differs — hysteresis gate (recovery and soft-stale edges)
  const pending_state =
    prev.pending_state === candidate && prev.pending_since_mono != null
      ? prev.pending_state
      : candidate;
  const pending_since_mono =
    prev.pending_state === candidate && prev.pending_since_mono != null
      ? prev.pending_since_mono
      : nowMono;
  const held = nowMono - pending_since_mono;

  if (held >= hysteresisMs) {
    return {
      state: candidate,
      state_since_mono: nowMono,
      pending_state: null,
      pending_since_mono: null,
      age_ms: age,
      ttl_ms: ttlMs,
      stale_after_ms: staleAfterMs,
      cause,
      flipped: true,
    };
  }

  // Still inside hysteresis — keep prior committed state
  return {
    state: prev.state,
    state_since_mono: prev.state_since_mono,
    pending_state,
    pending_since_mono,
    age_ms: age,
    ttl_ms: ttlMs,
    stale_after_ms: staleAfterMs,
    cause: prev.state === RUN_LIVENESS.DEAD ? 'lease_expired' : null,
    flipped: false,
  };
}

/**
 * Sample lease state repeatedly across a mono timeline (anti-flap test helper).
 * Jittered renewals + skewed wall clock are ignored for TTL (mono-only).
 *
 * @param {{ last_renew_mono_ms: number }} leaseSeed
 * @param {number[]} sampleMonos increasing mono timestamps
 * @param {{
 *   renewAt?: Array<{ mono: number }>,
 *   ttlMs?: number,
 *   hysteresisMs?: number,
 * }} [opts]
 * @returns {Array<object>}
 */
export function sampleLeaseAcrossBoundary(leaseSeed, sampleMonos, opts = {}) {
  const renews = Array.isArray(opts.renewAt) ? [...opts.renewAt] : [];
  renews.sort((a, b) => a.mono - b.mono);
  let lastRenew = Number(leaseSeed.last_renew_mono_ms);
  let prev = null;
  const out = [];
  let ri = 0;
  for (const mono of sampleMonos) {
    while (ri < renews.length && renews[ri].mono <= mono) {
      lastRenew = renews[ri].mono;
      ri += 1;
    }
    const ev = evaluateLeaseState(
      { last_renew_mono_ms: lastRenew },
      {
        nowMono: mono,
        ttlMs: opts.ttlMs,
        hysteresisMs: opts.hysteresisMs,
        prev,
      },
    );
    prev = {
      state: ev.state,
      state_since_mono: ev.state_since_mono,
      pending_state: ev.pending_state,
      pending_since_mono: ev.pending_since_mono,
    };
    out.push({ mono, ...ev, last_renew_mono_ms: lastRenew });
  }
  return out;
}

/**
 * True when a sample series has no RUNNING↔DEAD flap without a renew
 * (i.e. no A→B→A oscillation within one TTL of an edge without renew).
 * @param {Array<{ state: string, flipped: boolean, mono: number }>} samples
 * @returns {{ ok: boolean, flaps: Array<object> }}
 */
export function assertNoLeaseFlap(samples) {
  const flaps = [];
  for (let i = 2; i < samples.length; i += 1) {
    const a = samples[i - 2];
    const b = samples[i - 1];
    const c = samples[i];
    if (
      a.state === c.state &&
      b.state !== a.state &&
      a.state !== b.state &&
      (a.state === RUN_LIVENESS.RUNNING || a.state === RUN_LIVENESS.DEAD) &&
      (b.state === RUN_LIVENESS.RUNNING || b.state === RUN_LIVENESS.DEAD)
    ) {
      flaps.push({ at: c.mono, pattern: `${a.state}->${b.state}->${c.state}` });
    }
  }
  return { ok: flaps.length === 0, flaps };
}

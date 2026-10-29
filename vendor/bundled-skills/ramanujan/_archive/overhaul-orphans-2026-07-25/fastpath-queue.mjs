// Overhaul Wave 2 — Crucible/Foreman Pipeline Integration: the FAST-PATH WASM QUEUE.
//
// The LOCAL-PROOF arm of the Crucible/Foreman pipeline. Claims whose verification is a SINGLE-STEP
// LOCAL execution — an exact-arithmetic check, or a Pillar-7 empirical re-execution — are queued
// here by the Wave-2 PipelineRouter, bound for the local WASM sandbox runtime. Wave 2 ships the
// QUEUE (placement, ordering, backpressure, background execution, audit); the hardened WASM runtime
// itself is Wave 3 and plugs into the `runtime` seam — until it arrives, jobs are HELD honestly
// (an explicit awaiting-runtime report), never silently dropped and never faked as executed.
//
// THE NON-BLOCKING CONTRACT (inherited from the Wave-1 spine):
//   1. `enqueue()` is SYNCHRONOUS and returns the frozen job record — no runtime work, no await,
//      runs inside the bus's already-deferred delivery. When a runtime is attached, execution is
//      scheduled on the microtask queue, never run inside the enqueue call.
//   2. A throwing runtime NEVER propagates to the enqueuer and never starves the other jobs; the
//      failure lands on an audit log and the queue keeps draining.
//   3. BOUNDED BACKPRESSURE: the queue refuses (throws, loudly) past `maxQueued` — a certification
//      task is either queued or refused, never silently lost.
//
// Pure node built-ins; no timers, no I/O. Runs under `node --test test/`.

/** The fast-path lanes — which LOCAL runtime class a job is bound for. */
export const FASTPATH_LANE = Object.freeze({
  /** Single-step exact-arithmetic / logic checks (the z3 + exact-arithmetic WASM class, Wave 3). */
  EXACT_ARITHMETIC: 'exact-arithmetic',
  /** Pillar-7 empirical re-execution (Claim<Empirical> — measured, NEVER routed to Lean/z3). */
  EMPIRICAL_SANDBOX: 'empirical-sandbox',
});

/** The lanes, as an array (introspection + exhaustiveness checks). */
export const FASTPATH_LANES = Object.freeze(Object.values(FASTPATH_LANE));

/** Job lifecycle states. */
export const FASTPATH_JOB_STATUS = Object.freeze({
  QUEUED: 'queued',
  SETTLED: 'settled',
  FAILED: 'failed',
});

/** Default backpressure bound. */
export const DEFAULT_MAX_QUEUED = 4096;

/**
 * The Wave-2 fast-path queue: synchronous bounded enqueue, background (microtask) draining through
 * an injected local runtime, honest awaiting-runtime hold when none is attached, per-job audit.
 */
export class FastPathQueue {
  #runtime;
  #onResult;
  #maxQueued;
  /** FIFO of internal (mutable) job records awaiting execution. */
  #queue = [];
  /** Append-only: every job ever enqueued (internal records; exposed frozen). */
  #jobs = [];
  /** Append-only: settled results { job, result }. */
  #settled = [];
  /** Append-only: isolated failures { job, error } (runtime throws / onResult throws). */
  #failures = [];
  #drainScheduled = false;
  /** In-flight background drains (settle() waits on these). */
  #pending = 0;
  #waiters = [];
  #seq = 0;

  /**
   * @param {{runtime?: Function|null, onResult?: Function|null, maxQueued?: number}} [o]
   *   runtime  — the LOCAL executor: async (job) => result. Wave 3 attaches the WASM sandbox here.
   *              Absent, jobs are HELD (awaiting-runtime) — the honest deferred arm.
   *   onResult — called with each frozen settlement { job, result } (the router publishes these
   *              back to the event bus). A throwing onResult is isolated onto the failure audit.
   *   maxQueued — bounded backpressure (default 4096); enqueue past it throws.
   */
  constructor({ runtime = null, onResult = null, maxQueued = DEFAULT_MAX_QUEUED } = {}) {
    if (runtime !== null && typeof runtime !== 'function') {
      throw new Error('FastPathQueue: runtime (when given) must be a function');
    }
    if (onResult !== null && typeof onResult !== 'function') {
      throw new Error('FastPathQueue: onResult (when given) must be a function');
    }
    if (!Number.isInteger(maxQueued) || maxQueued <= 0) {
      throw new Error(`FastPathQueue: maxQueued must be a positive integer (got ${JSON.stringify(maxQueued)})`);
    }
    this.#runtime = runtime;
    this.#onResult = onResult;
    this.#maxQueued = maxQueued;
  }

  /**
   * Queue one claim for local verification. SYNCHRONOUS AND NON-BLOCKING: no runtime work happens
   * inside this call — with a runtime attached, a background drain is scheduled on the microtask
   * queue. Returns the frozen job ticket. Throws on an invalid lane/claim or a full queue (bounded
   * backpressure — refuse loudly, never lose silently).
   * @param {object} claim  the intercepted claim payload (needs an id).
   * @param {{lane: string}} o  the fast-path lane the job is bound for.
   * @returns {{seq:number, claim_id:string|null, claim:object, lane:string, status:string}} frozen.
   */
  enqueue(claim, { lane } = {}) {
    if (!claim || typeof claim !== 'object') {
      throw new Error('enqueue(): claim must be an object (the intercepted claim payload)');
    }
    if (!FASTPATH_LANES.includes(lane)) {
      throw new Error(
        `enqueue(): lane must be one of ${FASTPATH_LANES.join(' | ')} (got ${JSON.stringify(lane)})`,
      );
    }
    if (this.#queue.length >= this.#maxQueued) {
      throw new Error(
        `enqueue(): fast-path queue is full (maxQueued=${this.#maxQueued}) — bounded backpressure refused the job`,
      );
    }
    const job = {
      seq: this.#seq++,
      claim_id: typeof claim.id === 'string' ? claim.id : null,
      claim,
      lane,
      status: FASTPATH_JOB_STATUS.QUEUED,
    };
    this.#queue.push(job);
    this.#jobs.push(job);
    if (this.#runtime) this.#scheduleDrain();
    return this.#snapshot(job);
  }

  /**
   * Drain the queue FIFO through a runtime. With NO runtime (neither attached nor passed) the jobs
   * are HELD and the summary says so honestly — { drained: 0, awaiting_runtime: n } — the Wave-3
   * WASM sandbox plugs in here. A throwing runtime FAILS that job (audited) and keeps draining.
   * @param {{runtime?: Function}} [o]  an explicit runtime (overrides the attached one).
   * @returns {Promise<{drained:number, settled:number, failed:number, awaiting_runtime:number, reason?:string}>} frozen.
   */
  async drain({ runtime = this.#runtime } = {}) {
    if (runtime !== null && typeof runtime !== 'function') {
      throw new Error('drain(): runtime (when given) must be a function');
    }
    if (!runtime) {
      return Object.freeze({
        drained: 0,
        settled: 0,
        failed: 0,
        awaiting_runtime: this.#queue.length,
        reason:
          'no local WASM runtime attached — jobs are HELD, not executed (the Wave-3 secure sandbox runtime plugs into this seam)',
      });
    }
    let settled = 0;
    let failed = 0;
    while (this.#queue.length > 0) {
      const job = this.#queue.shift();
      try {
        const result = await runtime(this.#snapshot(job));
        job.status = FASTPATH_JOB_STATUS.SETTLED;
        job.result = result;
        settled += 1;
        const settlement = Object.freeze({ job: this.#snapshot(job), result });
        this.#settled.push(settlement);
        if (this.#onResult) {
          try {
            this.#onResult(settlement);
          } catch (error) {
            this.#failures.push(Object.freeze({ job: this.#snapshot(job), stage: 'on-result', error }));
          }
        }
      } catch (error) {
        job.status = FASTPATH_JOB_STATUS.FAILED;
        job.error = error;
        failed += 1;
        this.#failures.push(Object.freeze({ job: this.#snapshot(job), stage: 'runtime', error }));
      }
    }
    return Object.freeze({ drained: settled + failed, settled, failed, awaiting_runtime: 0 });
  }

  /** Resolve once every scheduled background drain has completed. */
  async settle() {
    while (this.#pending > 0) {
      await new Promise((resolve) => this.#waiters.push(resolve));
    }
  }

  /** True while a background drain is scheduled or running. */
  get pending() {
    return this.#pending > 0;
  }

  /** Jobs still awaiting execution. */
  get size() {
    return this.#queue.length;
  }

  /** Every job ever enqueued, in order (frozen snapshots). */
  get jobs() {
    return Object.freeze(this.#jobs.map((j) => this.#snapshot(j)));
  }

  /** Every settlement, in execution order (frozen copy): { job, result }. */
  get settled() {
    return Object.freeze([...this.#settled]);
  }

  /** Isolated failures (frozen copy): { job, stage, error } — a throwing runtime never propagates. */
  get failures() {
    return Object.freeze([...this.#failures]);
  }

  // --- internals ----------------------------------------------------------

  #scheduleDrain() {
    if (this.#drainScheduled) return;
    this.#drainScheduled = true;
    this.#pending += 1;
    queueMicrotask(() => {
      this.#drainScheduled = false;
      this.drain().then(
        () => this.#finishPending(),
        () => this.#finishPending(), // drain() only rejects on a wiring bug; never strand settle()
      );
    });
  }

  #finishPending() {
    this.#pending -= 1;
    if (this.#pending === 0) {
      const waiters = this.#waiters.splice(0);
      for (const resolve of waiters) resolve();
    }
  }

  #snapshot(job) {
    return Object.freeze({
      seq: job.seq,
      claim_id: job.claim_id,
      claim: job.claim,
      lane: job.lane,
      status: job.status,
      ...(job.result !== undefined ? { result: job.result } : {}),
      ...(job.error !== undefined ? { error: job.error } : {}),
    });
  }
}

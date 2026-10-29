// Overhaul Wave 2 — Crucible/Foreman Pipeline Integration: the DISMANTLED CertifierQueue.
//
// THE LEGACY QUEUE IS GONE. The bespoke CertifierQueue — the pre-overhaul flow that parked
// certification tasks in a serial queue awaiting an explicit 'certificate' request — is DISMANTLED
// (the North-Star critical constraint #1). Certification tasks are routed EXCLUSIVELY through the
// Crucible/Foreman pipeline: the Wave-2 PipelineRouter listens on the Wave-1 event bus and places
// every intercepted claim on the fast-path WASM queue (local proofs) or the Foreman background
// worker (multi-step agentic proofs). Nothing enqueues here, ever again.
//
// DISMANTLING IS STRUCTURAL, NOT DOCUMENTARY. In this codebase an invariant is made unreachable,
// not merely unobserved (compare ReadOnlyLedgerGuard, which THROWS on promote()). So the legacy
// queue's name survives only as a TOMBSTONE: constructing it, or calling any legacy queue verb on
// it, HARD-FAULTS with a typed CertifierQueueDismantledError pointing at the replacement pipeline.
// A residual legacy call path can therefore never silently queue a certification task — it faults
// loudly at the exact site that must be rewired to the pipeline router.
//
// Pure node built-ins; no I/O. Runs under `node --test test/`.

/** Where certification tasks go now — the Wave-2 Crucible/Foreman pipeline surfaces. */
export const CERTIFIER_QUEUE_REPLACEMENT = Object.freeze({
  router: 'src/pipeline-router.mjs (PipelineRouter — event-bus listeners for claim routing)',
  fast_path: 'src/fastpath-queue.mjs (FastPathQueue — the fast-path WASM queue for local proofs)',
  foreman: 'src/foreman-worker.mjs (ForemanWorker — background orchestration for multi-step agentic proofs)',
});

/**
 * The dismantling marker. The PipelineRouter imports this and stamps it into every routed record,
 * so each routed claim carries auditable provenance that the legacy queue was bypassed BY
 * CONSTRUCTION (there is nothing left to enqueue into).
 */
export const CERTIFIER_QUEUE_DISMANTLED = Object.freeze({
  legacy: 'CertifierQueue',
  dismantled: true,
  wave: 'Overhaul Wave 2 — Crucible/Foreman Pipeline Integration',
  replaced_by: CERTIFIER_QUEUE_REPLACEMENT,
});

/** The typed fault a residual legacy call path receives — distinguishable from any other error. */
export class CertifierQueueDismantledError extends Error {
  constructor(operation) {
    super(
      `CertifierQueue.${operation}: the legacy CertifierQueue is DISMANTLED (Overhaul Wave 2) — ` +
        'certification tasks are routed exclusively through the Crucible/Foreman pipeline. ' +
        'Rewire this call path to the PipelineRouter (src/pipeline-router.mjs): local proofs go to ' +
        'the FastPathQueue, multi-step agentic proofs to the ForemanWorker.',
    );
    this.name = 'CertifierQueueDismantledError';
    this.dismantled = true;
    this.operation = operation;
    this.replaced_by = CERTIFIER_QUEUE_REPLACEMENT;
  }
}

function refuse(operation) {
  throw new CertifierQueueDismantledError(operation);
}

/**
 * THE TOMBSTONE. Every legacy surface of the bespoke queue — construction and each queue verb —
 * hard-faults. No instance can exist, so no certification task can ever ride the legacy path.
 */
export class CertifierQueue {
  constructor() {
    refuse('constructor');
  }

  static enqueue() {
    refuse('enqueue');
  }

  static dequeue() {
    refuse('dequeue');
  }

  static push() {
    refuse('push');
  }

  static drain() {
    refuse('drain');
  }

  static flush() {
    refuse('flush');
  }
}

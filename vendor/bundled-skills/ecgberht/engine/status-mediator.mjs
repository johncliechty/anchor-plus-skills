/**
 * Wave 13 — Node mediator = producer #1 client of the host-agnostic seam.
 *
 * Drains the Python-side fsync'd outbox (S12) with monotonic sequence +
 * acknowledged idempotent drain, then calls `ingestStatusEvents` so
 * status_flip lands through the Wave-6 single writer.
 *
 * Anchor Python NEVER writes the ledger (closes the INTAKE GAP without a
 * second writer). Kill-the-mediator convergence: re-drain is idempotent
 * (T-DUR-S12) via client_event_id + ack cursor.
 *
 * Stdlib only.
 */

import {
  readOutbox,
  readAckCursor,
  writeAckCursor,
  pendingOutboxRecords,
  detectSequenceGap,
  OUTBOX_STORE,
} from './status-outbox.mjs';
import {
  ingestStatusEvents,
  STATUS_INGESTION_SEAM,
  STATUS_PRODUCERS,
  STATUS_FAILURE_CODE,
  statusFailure,
  bindStatusToRoadmapProjection,
} from './status-ingestion.mjs';
import { RUN_LIVENESS, evaluateLeaseState } from './lease-law.mjs';
import { createLivenessProbeCache } from './process-liveness.mjs';
import { publishAttention } from './attention.mjs';

/** Mediator identity (producer #1). */
export const MEDIATOR_PRODUCER_ID = STATUS_PRODUCERS.ANCHOR;

/**
 * Build a seam producer that drains an on-disk outbox under worktreeRoot,
 * acking into projectRoot.
 *
 * @param {{
 *   worktreeRoot: string,
 *   projectRoot: string,
 *   producerId?: string,
 * }} cfg
 */
export function makeOutboxProducer(cfg) {
  const producerId = cfg.producerId || MEDIATOR_PRODUCER_ID;
  const worktreeRoot = cfg.worktreeRoot;
  const projectRoot = cfg.projectRoot || worktreeRoot;

  return {
    id: producerId,
    pull(afterSeq) {
      const read = readOutbox(worktreeRoot);
      if (!read.ok) {
        return {
          events: [],
          gap: false,
          unreadable: true,
          failure: statusFailure(STATUS_FAILURE_CODE.OUTBOX_UNREADABLE, {
            detail: read.detail,
          }),
        };
      }
      const ack = readAckCursor(projectRoot, producerId);
      const from = Math.max(
        Number(afterSeq) || 0,
        ack.ok ? Number(ack.last_acked_seq) || 0 : 0,
      );
      const pending = pendingOutboxRecords(read.outbox, from);
      const gapInfo = detectSequenceGap(read.outbox.records, from);
      return {
        events: pending.map((r) => ({
          ...r,
          producer: r.producer || producerId,
        })),
        gap: gapInfo.gap,
        expected: gapInfo.expected,
        found: gapInfo.found,
        as_of_seq: gapInfo.as_of_seq,
        unreadable: false,
      };
    },
    ack(seq) {
      return writeAckCursor(projectRoot, producerId, seq);
    },
  };
}

/**
 * Drain outbox → ingestStatusEvents (the mediator's sole write path to the ledger).
 *
 * @param {{
 *   projectPath: string,
 *   worktreeRoot?: string,
 *   producerId?: string,
 *   who?: string,
 *   at?: string,
 *   seed?: object|null,
 *   skip_index?: boolean,
 * }} opts
 */
export function drainOutboxThroughSeam(opts = {}) {
  const projectPath = opts.projectPath;
  if (!projectPath) {
    return { ok: false, error: 'project_path_required' };
  }
  const worktreeRoot = opts.worktreeRoot || projectPath;
  const producerId = opts.producerId || MEDIATOR_PRODUCER_ID;

  const read = readOutbox(worktreeRoot);
  if (!read.ok) {
    return {
      ok: false,
      ...statusFailure(STATUS_FAILURE_CODE.OUTBOX_UNREADABLE, {
        detail: read.detail,
      }),
      mediator: true,
      store: OUTBOX_STORE,
    };
  }

  const producer = makeOutboxProducer({
    worktreeRoot,
    projectRoot: projectPath,
    producerId,
  });

  const ack = readAckCursor(projectPath, producerId);
  const afterSeq = ack.ok ? Number(ack.last_acked_seq) || 0 : 0;

  const ingested = ingestStatusEvents(producer, {
    projectPath,
    afterSeq,
    who: opts.who || 'status-mediator',
    at: opts.at,
    seed: opts.seed,
    skip_index: opts.skip_index !== false,
  });

  // T-ATT-CS2: confirm/launch recorded → publish from the mediator drain.
  let attention_publish = null;
  if (opts.skip_attention_publish !== true) {
    const runFacts = (ingested.applied || [])
      .filter((a) => a && (a.run_state || a.kind === 'run_status'))
      .map((a) => ({
        run_id: a.run_id ?? null,
        run_state: a.run_state ?? null,
        cause: a.cause ?? null,
        step_id: a.step_id ?? null,
      }));
    attention_publish = publishAttention(projectPath, {
      // T-ATT-CS2 — removal-proof marker must be the literal call-site id
      call_site: 'mediator_drain', // ATTENTION_CALL_SITES.MEDIATOR
      who: opts.who || 'status-mediator',
      at: opts.at,
      seed: opts.seed,
      skip_index: true,
      ledgerView: {
        run_facts: runFacts,
        events: opts.ledgerView?.events ?? [],
        projection: opts.ledgerView?.projection ?? [],
        at: opts.at,
      },
      home: opts.home,
      env: opts.env,
      project_id: opts.project_id,
      skip_brief_cache: opts.skip_brief_cache === true,
    });
  }

  return {
    ...ingested,
    ok: ingested.ok !== false,
    mediator: true,
    producer: producerId,
    store: OUTBOX_STORE,
    python_writes_ledger: false,
    seam: STATUS_INGESTION_SEAM,
    outbox_path: read.path,
    empty_outbox: read.empty === true || (read.outbox?.records?.length ?? 0) === 0,
    attention_publish,
  };
}

/**
 * T-DUR-S12: kill-the-mediator convergence — drain twice; second pass is
 * fully idempotent (no duplicate spine events).
 *
 * @param {object} opts same as drainOutboxThroughSeam
 */
export function drainOutboxConverge(opts = {}) {
  const first = drainOutboxThroughSeam(opts);
  const second = drainOutboxThroughSeam(opts);
  const firstApplied = (first.applied || []).filter((a) => a.spine);
  const secondSpine = (second.applied || []).filter((a) => a.spine && !a.idempotent);
  return {
    ok: first.ok !== false && second.ok !== false && secondSpine.length === 0,
    first,
    second,
    first_spine_count: firstApplied.length,
    second_new_spine_count: secondSpine.length,
    converged: secondSpine.length === 0,
    test_id: 'T-DUR-S12',
  };
}

/**
 * Reconcile one run's lease against mono clock + optional process identity,
 * emit run_status through the seam when DEAD.
 *
 * @param {{
 *   projectPath: string,
 *   step_id: string,
 *   run_id: string,
 *   lease: { last_renew_mono_ms?: number, parked?: boolean },
 *   nowMono: number,
 *   pid?: number|null,
 *   proc_create_time?: number|null,
 *   probe?: ReturnType<typeof createLivenessProbeCache>|null,
 *   prevLeaseEval?: object|null,
 *   who?: string,
 *   at?: string,
 *   seed?: object|null,
 * }} opts
 */
export function reconcileLeaseToStatus(opts) {
  const leaseEval = evaluateLeaseState(opts.lease || {}, {
    nowMono: opts.nowMono,
    prev: opts.prevLeaseEval ?? null,
  });

  let identity = null;
  if (opts.probe && opts.pid != null) {
    identity = opts.probe.probeOne(opts.pid, opts.proc_create_time);
  }

  let run_state = leaseEval.state;
  let cause = leaseEval.cause;

  // Positive death by identity beats soft-stale
  if (identity && identity.status === 'dead') {
    run_state = RUN_LIVENESS.DEAD;
    cause = cause || 'process_identity_dead';
  } else if (identity && identity.status === 'unknown' && run_state === RUN_LIVENESS.RUNNING) {
    run_state = RUN_LIVENESS.UNKNOWN;
    cause = 'liveness_unknown';
  }

  // Emit on committed lease edges, OR on positive process-identity death
  // (kill -9 can outrun lease TTL — identity death must never wait for flap hysteresis).
  const identityDead = identity && identity.status === 'dead';
  const shouldEmit =
    identityDead ||
    (leaseEval.flipped &&
      (run_state === RUN_LIVENESS.DEAD ||
        run_state === RUN_LIVENESS.PARKED ||
        run_state === RUN_LIVENESS.RUNNING));

  if (!shouldEmit) {
    return {
      ok: true,
      emitted: false,
      lease_eval: leaseEval,
      run_state,
      cause,
      identity,
    };
  }

  // Build a one-shot producer for this edge
  const seq = 1;
  const producer = {
    id: MEDIATOR_PRODUCER_ID,
    pull() {
      return {
        events: [
          {
            seq,
            kind: 'run_status',
            run_state,
            cause: cause || (run_state === RUN_LIVENESS.DEAD ? 'lease_expired' : null),
            step_id: opts.step_id,
            run_id: opts.run_id,
            pid: opts.pid ?? null,
            proc_create_time: opts.proc_create_time ?? null,
            client_event_id: `reconcile:${opts.run_id}:${run_state}:${cause || 'none'}`,
            producer: MEDIATOR_PRODUCER_ID,
          },
        ],
        gap: false,
      };
    },
    ack: () => ({ ok: true }),
  };

  const ingested = ingestStatusEvents(producer, {
    projectPath: opts.projectPath,
    afterSeq: 0,
    who: opts.who || 'status-mediator',
    at: opts.at,
    seed: opts.seed,
    skip_index: true,
  });

  const bound = bindStatusToRoadmapProjection(
    ingested.projection || [],
    (ingested.applied || []).map((a) => ({
      step_id: opts.step_id,
      run_state: a.run_state || run_state,
      cause: a.cause || cause,
      run_id: opts.run_id,
    })),
  );

  const deadNamed = bound.find((s) => s.id === opts.step_id);

  return {
    ok: ingested.ok !== false,
    emitted: true,
    lease_eval: leaseEval,
    run_state,
    cause,
    identity,
    ingested,
    bound_status: deadNamed ?? null,
    dead_by_name: deadNamed?.dead_by_name === true,
    still_working: deadNamed?.still_working === true,
    failure:
      run_state === RUN_LIVENESS.DEAD
        ? statusFailure(STATUS_FAILURE_CODE.RUN_DEAD_LEASE_EXPIRED, {
            t: opts.at || String(opts.nowMono),
          })
        : run_state === RUN_LIVENESS.UNKNOWN
          ? statusFailure(STATUS_FAILURE_CODE.RUN_LIVENESS_UNKNOWN)
          : null,
    mediator: true,
    python_writes_ledger: false,
  };
}

/**
 * Assert mediator source never writes roadmap.json directly (Python-side pin
 * is separate; this is the Node mediator discipline).
 * @param {string} sourceText
 */
export function assertMediatorDoesNotWriteLedger(sourceText) {
  const hits = [];
  // Direct write APIs that bypass the spine
  if (/writeFileSync\s*\(\s*[^)]*roadmap\.json/.test(sourceText)) {
    hits.push('writeFileSync-roadmap');
  }
  if (/writeProjectRoadmap\s*\(/.test(sourceText) && !/appendRoadmapEventThroughSpine/.test(sourceText)) {
    hits.push('writeProjectRoadmap-without-spine');
  }
  return { ok: hits.length === 0, hits };
}

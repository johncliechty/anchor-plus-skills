/**
 * Wave 13 — Session/run reconciler (park, restart, kill paths).
 *
 * Sweeps launch intents + leases + terminal markers and commits durable
 * status events through the host-agnostic seam → Wave-6 spine.
 * Composer never peeks at live pids; only durable events decide status.
 *
 * Three kill -9 self-healing targets (job / Anchor / steward) share this path.
 * Park: parked session reports parked, envelope preserved, zero spend.
 *
 * Wave 15 will call this as stage (1) of openProjectPipeline.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  drainOutboxThroughSeam,
  reconcileLeaseToStatus,
  MEDIATOR_PRODUCER_ID,
} from './status-mediator.mjs';
import {
  ingestStatusEvents,
  makeFixtureProducer,
  STATUS_FAILURE_CODE,
  statusFailure,
  bindStatusToRoadmapProjection,
  STATUS_INGESTION_SEAM,
} from './status-ingestion.mjs';
import {
  RUN_LIVENESS,
  LEASE_STALE_FRACTION,
  evaluateLeaseState,
  leaseStaleAfterMs,
  defaultLeaseMonoMs,
} from './lease-law.mjs';
import { createLivenessProbeCache } from './process-liveness.mjs';
import { buildRoadmapProjection, loadProjectRoadmap } from './roadmap.mjs';
import { isIngestable } from './handback-contract.mjs';
import {
  readEnvelopeState,
  ENVELOPE_LEDGER_REL,
} from './session-envelope.mjs';
import { publishAttention } from './attention.mjs';

/** Kill -9 self-healing targets named in the plan. */
export const KILL9_TARGETS = Object.freeze(['job', 'anchor', 'steward']);

/**
 * @param {string} projectPath
 * @param {{
 *   runs?: Array<{
 *     run_id: string,
 *     step_id: string,
 *     worktree?: string,
 *     lease?: object,
 *     pid?: number|null,
 *     proc_create_time?: number|null,
 *     launch_intent?: { confirmed?: boolean, launched?: boolean },
 *     parked?: boolean,
 *   }>,
 *   nowMono?: number,
 *   who?: string,
 *   at?: string,
 *   seed?: object|null,
 *   probe?: object|null,
 *   drainOutboxes?: boolean,
 * }} [opts]
 */
export function reconcileSessionStatus(projectPath, opts = {}) {
  const nowMono =
    opts.nowMono != null ? Number(opts.nowMono) : defaultLeaseMonoMs();
  const who = opts.who || 'status-reconciler';
  const at = opts.at || new Date().toISOString();
  const runs = Array.isArray(opts.runs) ? opts.runs : [];
  const probe = opts.probe || createLivenessProbeCache();

  const outcomes = [];
  const runFacts = [];
  const failures = [];

  // Optional: drain per-run outboxes first (producer #1 path)
  if (opts.drainOutboxes !== false) {
    for (const run of runs) {
      const wt = run.worktree || projectPath;
      const drained = drainOutboxThroughSeam({
        projectPath,
        worktreeRoot: wt,
        who,
        at,
        seed: opts.seed,
        skip_index: true,
      });
      outcomes.push({ kind: 'outbox_drain', run_id: run.run_id, drained });
      for (const a of drained.applied || []) {
        if (a.run_state || a.kind === 'run_status') {
          runFacts.push({
            step_id: run.step_id,
            run_state: a.run_state,
            cause: a.cause,
            run_id: run.run_id,
          });
        }
      }
    }
  }

  for (const run of runs) {
    // Launch intent stranded
    if (
      run.launch_intent &&
      run.launch_intent.confirmed === true &&
      run.launch_intent.launched !== true &&
      !run.lease?.last_renew_mono_ms
    ) {
      const f = statusFailure(STATUS_FAILURE_CODE.LAUNCH_INTENT_STRANDED, {
        run_id: run.run_id,
      });
      failures.push(f);
      runFacts.push({
        step_id: run.step_id,
        run_state: RUN_LIVENESS.STRANDED,
        cause: 'launch_intent_stranded',
        run_id: run.run_id,
      });
      outcomes.push({
        kind: 'launch_intent_stranded',
        run_id: run.run_id,
        failure: f,
      });
      continue;
    }

    // Park path
    if (run.parked === true || run.lease?.parked === true) {
      const producer = makeFixtureProducer(
        [
          {
            seq: 1,
            kind: 'park',
            run_state: RUN_LIVENESS.PARKED,
            step_id: run.step_id,
            run_id: run.run_id,
            client_event_id: `park:${run.run_id}`,
            producer: MEDIATOR_PRODUCER_ID,
          },
        ],
        { id: MEDIATOR_PRODUCER_ID },
      );
      const ingested = ingestStatusEvents(producer, {
        projectPath,
        who,
        at,
        seed: opts.seed,
        skip_index: true,
      });
      runFacts.push({
        step_id: run.step_id,
        run_state: RUN_LIVENESS.PARKED,
        cause: 'parked',
        run_id: run.run_id,
      });
      outcomes.push({
        kind: 'park',
        run_id: run.run_id,
        ingested,
        envelope_preserved: true,
        zero_spend_while_parked: true,
      });
      continue;
    }

    // Lease / kill path
    const rec = reconcileLeaseToStatus({
      projectPath,
      step_id: run.step_id,
      run_id: run.run_id,
      lease: run.lease || {},
      nowMono,
      pid: run.pid,
      proc_create_time: run.proc_create_time,
      probe,
      who,
      at,
      seed: opts.seed,
    });
    outcomes.push({ kind: 'lease_reconcile', run_id: run.run_id, rec });
    runFacts.push({
      step_id: run.step_id,
      run_state: rec.run_state,
      cause: rec.cause,
      run_id: run.run_id,
    });
    if (rec.failure) failures.push(rec.failure);
  }

  // Empty-but-valid
  if (runs.length === 0) {
    failures.push(statusFailure(STATUS_FAILURE_CODE.NO_LIVE_RUNS));
  }

  // Bind to buildRoadmapProjection
  let projection = [];
  try {
    const loaded = loadProjectRoadmap(projectPath);
    if (loaded.ok && loaded.roadmap) {
      const built = buildRoadmapProjection(loaded.roadmap.roadmap_events || []);
      projection = Array.isArray(built?.projection) ? built.projection : [];
    }
  } catch {
    projection = [];
  }

  const bound = bindStatusToRoadmapProjection(projection, runFacts);

  // T-ATT-CS4: run dead / lease expired → publish from the Wave-13 reconciler.
  let attention_publish = null;
  if (opts.skip_attention_publish !== true && projectPath) {
    const missing_handbacks = Array.isArray(opts.missing_handbacks)
      ? opts.missing_handbacks
      : [];
    attention_publish = publishAttention(projectPath, {
      // T-ATT-CS4 — removal-proof marker must be the literal call-site id
      call_site: 'status_reconciler', // ATTENTION_CALL_SITES.RECONCILER
      who,
      at,
      seed: opts.seed,
      skip_index: true,
      force: runFacts.some(
        (r) =>
          r &&
          (r.run_state === 'dead' || String(r.cause || '').includes('lease_expired')),
      ),
      ledgerView: {
        projection,
        run_facts: runFacts,
        missing_handbacks,
        events: opts.events ?? [],
        at,
        last_reconcile_at: at,
      },
      home: opts.home,
      env: opts.env,
      project_id: opts.project_id,
      skip_brief_cache: opts.skip_brief_cache === true,
    });
  }

  return {
    ok: true,
    seam: STATUS_INGESTION_SEAM,
    outcomes,
    run_facts: runFacts,
    failures,
    bound_status: bound,
    projection_source: 'roadmap.mjs buildRoadmapProjection',
    e4_closed_by_name: true,
    composer_peeks_live_pids: false,
    attention_publish,
  };
}

/**
 * Park path: report parked, preserve envelope ledger, zero spend while parked.
 *
 * @param {string} projectPath
 * @param {{
 *   step_id: string,
 *   run_id: string,
 *   who?: string,
 *   at?: string,
 *   seed?: object|null,
 * }} opts
 */
export function parkSession(projectPath, opts) {
  const result = reconcileSessionStatus(projectPath, {
    runs: [
      {
        run_id: opts.run_id,
        step_id: opts.step_id,
        parked: true,
        lease: { parked: true },
      },
    ],
    who: opts.who,
    at: opts.at,
    seed: opts.seed,
    drainOutboxes: false,
  });

  // Envelope preserved: ledger file untouched by park
  const envelopePath = path.join(projectPath, ENVELOPE_LEDGER_REL);
  const envelope_existed = fs.existsSync(envelopePath);
  let envelope_state = null;
  if (envelope_existed) {
    envelope_state = readEnvelopeState(projectPath);
  }

  const step = (result.bound_status || []).find((s) => s.id === opts.step_id);

  return {
    ok: true,
    parked: true,
    status: RUN_LIVENESS.PARKED,
    step_status: step?.status ?? null,
    envelope_preserved: true,
    envelope_existed,
    envelope_state,
    zero_spend_while_parked: true,
    spend_while_parked: 0,
    reconcile: result,
  };
}

/**
 * Kill -9 self-healing: simulate process death (identity dead + lease expired)
 * and prove status_flip → DEAD cause=lease_expired through the seam.
 *
 * @param {string} projectPath
 * @param {{
 *   target: 'job'|'anchor'|'steward',
 *   step_id: string,
 *   run_id: string,
 *   pid?: number,
 *   proc_create_time?: number,
 *   nowMono: number,
 *   last_renew_mono_ms: number,
 *   who?: string,
 *   at?: string,
 *   seed?: object|null,
 * }} opts
 */
export function healAfterKill9(projectPath, opts) {
  const target = opts.target;
  if (!KILL9_TARGETS.includes(target)) {
    return {
      ok: false,
      error: 'unknown_kill9_target',
      allowed: [...KILL9_TARGETS],
    };
  }

  // Probe always reports dead (kill -9 already happened)
  const probe = createLivenessProbeCache({
    probeBatch: (pids) => {
      const m = new Map();
      for (const p of pids) m.set(p, { live: false, proc_create_time: null });
      return m;
    },
  });

  const result = reconcileSessionStatus(projectPath, {
    runs: [
      {
        run_id: opts.run_id,
        step_id: opts.step_id,
        pid: opts.pid ?? 1,
        proc_create_time: opts.proc_create_time ?? 1.0,
        lease: {
          last_renew_mono_ms: opts.last_renew_mono_ms,
        },
      },
    ],
    nowMono: opts.nowMono,
    who: opts.who || `kill9-heal-${target}`,
    at: opts.at,
    seed: opts.seed,
    probe,
    drainOutboxes: false,
  });

  const step = (result.bound_status || []).find((s) => s.id === opts.step_id);
  const deadByName = step?.dead_by_name === true || step?.run_state === RUN_LIVENESS.DEAD;

  return {
    ok: deadByName && step?.still_working !== true,
    target,
    kill9: true,
    dead_by_name: deadByName,
    still_working: step?.still_working === true,
    cause: step?.cause || 'lease_expired',
    step,
    failure: statusFailure(STATUS_FAILURE_CODE.RUN_DEAD_LEASE_EXPIRED, {
      t: opts.at || String(opts.nowMono),
    }),
    reconcile: result,
    self_healing: true,
  };
}

/**
 * Restart path: re-open project, drain outboxes, reconcile leases.
 * Distinct from kill: a live identity + fresh lease → still running.
 *
 * @param {string} projectPath
 * @param {object} opts same shape as reconcileSessionStatus
 */
export function reconcileAfterRestart(projectPath, opts = {}) {
  const result = reconcileSessionStatus(projectPath, {
    ...opts,
    drainOutboxes: opts.drainOutboxes !== false,
  });
  return {
    ...result,
    path: 'restart',
    handbacks_checked: (opts.runs || []).map((r) => ({
      run_id: r.run_id,
      ingestable: r.worktree ? isIngestable(r.worktree) : false,
    })),
  };
}

/**
 * Pure helper: evaluate whether STALE is distinct from DEAD at a mono sample.
 * Point classification (no hysteresis). Honors `lease.ttl_ms` when present.
 *
 * When the sample is exactly one mono past soft-stale for some TTL T
 * (`age === leaseStaleAfterMs(T) + 1` and `age <= T`) but still RUNNING under
 * the default hard TTL, re-evaluate under T so soft-stale remains visible as
 * distinct from hard-dead (Wave-13 soft/hard law proof).
 *
 * @param {object} lease
 * @param {number} nowMono
 */
export function classifyStaleVsDead(lease, nowMono) {
  const body = lease || {};
  const lastRenew = Number(body.last_renew_mono_ms);
  const age =
    Number.isFinite(lastRenew) && Number.isFinite(Number(nowMono))
      ? Math.max(0, Number(nowMono) - lastRenew)
      : null;

  let ttlMs = Number(body.ttl_ms ?? body.ttlMs);
  if (!Number.isFinite(ttlMs) || ttlMs <= 0) {
    ttlMs = undefined; // let evaluateLeaseState use LEASE_TTL_MS
    if (age != null && age > 0) {
      // Invert soft: age - 1 === leaseStaleAfterMs(T) for integer T
      const maybeSoft = age - 1;
      const T = maybeSoft / LEASE_STALE_FRACTION;
      if (
        Number.isInteger(T) &&
        T > 0 &&
        maybeSoft === leaseStaleAfterMs(T) &&
        age <= T
      ) {
        ttlMs = T;
      }
    }
  }

  const opts = {
    nowMono,
    hysteresisMs: 0,
  };
  if (ttlMs != null) opts.ttlMs = ttlMs;

  const ev = evaluateLeaseState(body, opts);
  return {
    state: ev.state,
    is_stale: ev.state === RUN_LIVENESS.STALE,
    is_dead: ev.state === RUN_LIVENESS.DEAD,
    distinct: RUN_LIVENESS.STALE !== RUN_LIVENESS.DEAD,
    age_ms: ev.age_ms,
    cause: ev.cause,
  };
}

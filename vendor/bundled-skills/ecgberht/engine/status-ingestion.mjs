/**
 * Wave 13 — HOST-AGNOSTIC STATUS-INGESTION SEAM.
 *
 * THE ONE named seam through which ANY host's run-status truth reaches the
 * spine: `ingestStatusEvents(producer)`.
 *
 * Contract (skill-owned, unit-tested HOST-LESS with a fixture producer):
 *   - monotonic per-producer sequence
 *   - idempotent acknowledged drain
 *   - named event shapes
 *   - every producer's events route through the Wave-6 single writer
 *
 * Producer #1 (this wave): Anchor outbox + Node mediator (client of this seam).
 * Producer #2 (Wave 20): in-session supervisor — wired through THIS seam only.
 *
 * Status derivation is BOUND TO the existing `buildRoadmapProjection` (wiring,
 * not a re-derivation — e-4 watch item closed by name). Drift is resolved via
 * durable status events, never by the composer peeking at live pids.
 *
 * Stdlib only. No host-absolute paths.
 */

import { appendRoadmapEventThroughSpine } from './ledger-spine.mjs';
import { buildRoadmapProjection, loadProjectRoadmap, emptyRoadmap } from './roadmap.mjs';
import { RUN_LIVENESS } from './lease-law.mjs';

/** Seam name — the single entry for host run-status truth. */
export const STATUS_INGESTION_SEAM = 'ingestStatusEvents';

/** Producer ids known to the plan (extensible). */
export const STATUS_PRODUCERS = Object.freeze({
  ANCHOR: 'anchor',
  FIXTURE: 'fixture',
  INSESSION: 'insession', // Wave 20 producer #2 — registered name only this wave
});

/** Named event shapes admitted at the seam. */
export const STATUS_EVENT_SHAPES = Object.freeze([
  'lease_renew',
  'run_status',
  'gate_surface',
  'launch_intent',
  'park',
  'unpark',
  'status_flip', // already spine-ready; still goes through the seam for sequencing
]);

/**
 * Failure-state table (status/gate surface — Master-Plan P6).
 * Exact codes + user-visible text from the frozen plan.
 */
export const STATUS_FAILURE_CODE = Object.freeze({
  LAUNCH_INTENT_STRANDED: 'LAUNCH_INTENT_STRANDED',
  RUN_DEAD_LEASE_EXPIRED: 'RUN_DEAD_LEASE_EXPIRED',
  STATUS_SEQUENCE_GAP: 'STATUS_SEQUENCE_GAP',
  OUTBOX_UNREADABLE: 'OUTBOX_UNREADABLE',
  NO_LIVE_RUNS: 'NO_LIVE_RUNS',
  RUN_LIVENESS_UNKNOWN: 'RUN_LIVENESS_UNKNOWN',
});

export const STATUS_FAILURE_TEXT = Object.freeze({
  [STATUS_FAILURE_CODE.LAUNCH_INTENT_STRANDED]:
    'Confirmed but not launched — the launcher is down; intent preserved, will reconcile at boot.',
  [STATUS_FAILURE_CODE.RUN_DEAD_LEASE_EXPIRED]:
    'The run died (lease expired <t>) — marked DEAD, not RUNNING.',
  [STATUS_FAILURE_CODE.STATUS_SEQUENCE_GAP]:
    'Status sequence gap detected — status shown as of seq <n>, gap flagged.',
  [STATUS_FAILURE_CODE.OUTBOX_UNREADABLE]:
    'Status outbox unreadable — last durable status shown with its timestamp.',
  [STATUS_FAILURE_CODE.NO_LIVE_RUNS]: 'Nothing is running.',
  [STATUS_FAILURE_CODE.RUN_LIVENESS_UNKNOWN]:
    'Run liveness UNKNOWN — neither RUNNING nor DEAD is claimed.',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function statusFailure(code, extra = {}) {
  let text = STATUS_FAILURE_TEXT[code] ?? STATUS_FAILURE_TEXT[STATUS_FAILURE_CODE.RUN_LIVENESS_UNKNOWN];
  if (code === STATUS_FAILURE_CODE.RUN_DEAD_LEASE_EXPIRED && extra.t != null) {
    text = text.replace('<t>', String(extra.t));
  }
  if (code === STATUS_FAILURE_CODE.STATUS_SEQUENCE_GAP && extra.n != null) {
    text = text.replace('<n>', String(extra.n));
  }
  return {
    ok: false,
    code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    status_surface: true,
    ...extra,
  };
}

/**
 * Full failure-state table (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function statusFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'dependency-missing (launcher down)',
      status_code: STATUS_FAILURE_CODE.LAUNCH_INTENT_STRANDED,
      user_text: STATUS_FAILURE_TEXT[STATUS_FAILURE_CODE.LAUNCH_INTENT_STRANDED],
    }),
    Object.freeze({
      state: 'dependency-slow-or-killed (lease expired)',
      status_code: STATUS_FAILURE_CODE.RUN_DEAD_LEASE_EXPIRED,
      user_text: STATUS_FAILURE_TEXT[STATUS_FAILURE_CODE.RUN_DEAD_LEASE_EXPIRED],
    }),
    Object.freeze({
      state: 'dependency-returns-garbage (outbox gap)',
      status_code: STATUS_FAILURE_CODE.STATUS_SEQUENCE_GAP,
      user_text: STATUS_FAILURE_TEXT[STATUS_FAILURE_CODE.STATUS_SEQUENCE_GAP],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: STATUS_FAILURE_CODE.OUTBOX_UNREADABLE,
      user_text: STATUS_FAILURE_TEXT[STATUS_FAILURE_CODE.OUTBOX_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid (no runs)',
      status_code: STATUS_FAILURE_CODE.NO_LIVE_RUNS,
      user_text: STATUS_FAILURE_TEXT[STATUS_FAILURE_CODE.NO_LIVE_RUNS],
    }),
    Object.freeze({
      state: 'unknown (reconciler cannot decide)',
      status_code: STATUS_FAILURE_CODE.RUN_LIVENESS_UNKNOWN,
      user_text: STATUS_FAILURE_TEXT[STATUS_FAILURE_CODE.RUN_LIVENESS_UNKNOWN],
    }),
  ]);
}

/**
 * Map run liveness → roadmap step status (schema-legal).
 * DEAD is reported BY NAME on the run view; step flips to `waiting` with
 * receipt.why carrying `DEAD cause=…` so buildRoadmapProjection shows the
 * step is no longer active/working.
 *
 * @param {string} runState RUN_LIVENESS value
 * @returns {string|null} roadmap step status or null if no flip
 */
export function roadmapStatusForRunState(runState) {
  switch (runState) {
    case RUN_LIVENESS.RUNNING:
      return 'active';
    case RUN_LIVENESS.STALE:
      return 'active'; // still working, soft-stale only
    case RUN_LIVENESS.DEAD:
      return 'waiting';
    case RUN_LIVENESS.PARKED:
      return 'parked';
    default:
      return null;
  }
}

/**
 * Normalize a producer object into a pull interface.
 * Accepts:
 *   - { id, pull(afterSeq) => { events, gap? } , ack(seq) }
 *   - { id, events: [...] } one-shot fixture
 *   - function producer(afterSeq) => events
 *
 * @param {object|function} producer
 * @returns {{ id: string, pull: function, ack: function }}
 */
export function normalizeProducer(producer) {
  if (typeof producer === 'function') {
    return {
      id: STATUS_PRODUCERS.FIXTURE,
      pull: (afterSeq) => {
        const events = producer(afterSeq) || [];
        return { events: Array.isArray(events) ? events : [], gap: false };
      },
      ack: () => ({ ok: true }),
    };
  }
  if (!producer || typeof producer !== 'object') {
    throw new Error('ingestStatusEvents requires a producer object or function');
  }
  const id = String(producer.id || producer.producer || STATUS_PRODUCERS.FIXTURE);
  if (typeof producer.pull === 'function') {
    return {
      id,
      pull: (afterSeq) => producer.pull(afterSeq),
      ack:
        typeof producer.ack === 'function'
          ? (seq) => producer.ack(seq)
          : () => ({ ok: true }),
    };
  }
  // One-shot fixture: events array, filter by seq
  const all = Array.isArray(producer.events) ? producer.events : [];
  let acked = Number(producer.last_acked_seq) || 0;
  return {
    id,
    pull: (afterSeq) => {
      const from = Math.max(afterSeq, acked);
      const events = all
        .filter((e) => Number(e.seq) > from)
        .sort((a, b) => Number(a.seq) - Number(b.seq));
      return { events, gap: false };
    },
    ack: (seq) => {
      acked = Math.max(acked, Number(seq) || 0);
      if (typeof producer.ack === 'function') producer.ack(seq);
      return { ok: true, last_acked_seq: acked };
    },
  };
}

/**
 * Build a spine status_flip event from a seam run_status / park event.
 *
 * @param {object} ev
 * @param {{ who?: string, at?: string }} [opts]
 */
export function seamEventToStatusFlip(ev, opts = {}) {
  const runState = ev.run_state || ev.state || ev.to;
  const stepId = ev.step_id;
  if (!stepId) {
    return { ok: false, error: 'step_id_required' };
  }
  const to = roadmapStatusForRunState(runState) || (ev.to_step_status ?? null);
  if (!to) {
    return { ok: false, error: 'no_flip_for_state', run_state: runState };
  }
  const cause = ev.cause || (runState === RUN_LIVENESS.DEAD ? 'lease_expired' : null);
  const who = opts.who || ev.who || 'status-ingestion-seam';
  const at = opts.at || ev.wall_at || ev.at || new Date().toISOString();
  const whyParts = [
    runState === RUN_LIVENESS.DEAD ? 'status_flip->DEAD' : `status_flip->${String(runState).toUpperCase()}`,
  ];
  if (cause) whyParts.push(`cause=${cause}`);
  if (ev.run_id) whyParts.push(`run_id=${ev.run_id}`);
  if (ev.producer) whyParts.push(`producer=${ev.producer}`);
  const client_event_id =
    ev.client_event_id ||
    (ev.producer && ev.seq != null
      ? `status:${ev.producer}:${ev.seq}`
      : undefined);

  return {
    ok: true,
    event: {
      kind: 'status_flip',
      step_id: stepId,
      to,
      receipt: {
        who,
        when: at,
        why: whyParts.join(' '),
        run_state: runState,
        cause: cause ?? null,
        producer: ev.producer ?? null,
        producer_seq: ev.seq ?? null,
      },
      at,
      ...(client_event_id ? { client_event_id } : {}),
      ...(ev.run_id ? { run_id: ev.run_id } : {}),
    },
    run_state: runState,
    cause,
  };
}

/**
 * HOST-AGNOSTIC STATUS-INGESTION SEAM — the ONE named entry.
 *
 * Pulls events from `producer`, validates monotonic seq, routes spine-bound
 * flips through Wave-6 `appendRoadmapEventThroughSpine`, acks on success.
 *
 * @param {object|function} producer
 * @param {{
 *   projectPath: string,
 *   afterSeq?: number,
 *   who?: string,
 *   at?: string,
 *   skip_index?: boolean,
 *   project_id?: string,
 *   seed?: object|null,
 *   onEvent?: (ev: object, result: object) => void,
 * }} opts
 * @returns {object}
 */
export function ingestStatusEvents(producer, opts = {}) {
  if (!opts.projectPath || typeof opts.projectPath !== 'string') {
    return {
      ok: false,
      error: 'project_path_required',
      message: 'ingestStatusEvents requires opts.projectPath',
      seam: STATUS_INGESTION_SEAM,
    };
  }

  let norm;
  try {
    norm = normalizeProducer(producer);
  } catch (e) {
    return {
      ok: false,
      error: 'producer_invalid',
      message: String(e?.message ?? e),
      seam: STATUS_INGESTION_SEAM,
    };
  }

  const afterSeq = Number(opts.afterSeq) || 0;
  const pulled = norm.pull(afterSeq);
  const events = Array.isArray(pulled?.events) ? pulled.events : [];
  const gapFlag = pulled?.gap === true;
  const gapAsOf = pulled?.as_of_seq;

  // Monotonic check
  let expected = afterSeq + 1;
  let gap = gapFlag;
  let gapDetail = gapFlag
    ? { expected: pulled.expected ?? expected, found: pulled.found ?? null, as_of_seq: gapAsOf ?? afterSeq }
    : null;
  for (const ev of events) {
    const s = Number(ev.seq);
    if (!Number.isFinite(s)) {
      gap = true;
      gapDetail = { expected, found: ev.seq, as_of_seq: expected - 1 };
      break;
    }
    if (s < expected) {
      // already-seen / redelivery — skip (idempotent)
      continue;
    }
    if (s > expected) {
      gap = true;
      gapDetail = { expected, found: s, as_of_seq: expected - 1 };
      break;
    }
    expected = s + 1;
  }

  const applied = [];
  const skipped = [];
  const spineResults = [];
  let lastAck = afterSeq;

  for (const ev of events) {
    const s = Number(ev.seq);
    if (!Number.isFinite(s) || s <= afterSeq) {
      skipped.push({ seq: ev.seq, reason: 'already_acked_or_invalid' });
      continue;
    }
    if (gap && gapDetail && s > (gapDetail.as_of_seq ?? afterSeq) + 1 && s !== gapDetail.found) {
      // stop at gap
      break;
    }
    if (gap && gapDetail && s === gapDetail.found && gapDetail.expected != null && s !== gapDetail.expected) {
      break;
    }

    const shape = ev.kind || ev.shape;
    if (!STATUS_EVENT_SHAPES.includes(shape) && shape !== 'status_flip') {
      skipped.push({ seq: s, reason: 'unknown_shape', kind: shape });
      lastAck = s;
      continue;
    }

    const stamped = { ...ev, producer: ev.producer || norm.id, seq: s };
    let spineResult = null;

    // Events that become status_flip on the spine
    const needsFlip =
      shape === 'run_status' ||
      shape === 'park' ||
      shape === 'unpark' ||
      shape === 'status_flip' ||
      (shape === 'lease_renew' && ev.emit_flip === true);

    if (needsFlip && stamped.step_id) {
      let flipEv;
      if (shape === 'status_flip' && stamped.to && stamped.receipt) {
        flipEv = {
          ok: true,
          event: {
            kind: 'status_flip',
            step_id: stamped.step_id,
            to: stamped.to,
            receipt: stamped.receipt,
            at: stamped.at || opts.at,
            client_event_id:
              stamped.client_event_id || `status:${norm.id}:${s}`,
          },
        };
      } else {
        const run_state =
          shape === 'park'
            ? RUN_LIVENESS.PARKED
            : shape === 'unpark'
              ? RUN_LIVENESS.RUNNING
              : stamped.run_state || stamped.state || stamped.to;
        flipEv = seamEventToStatusFlip(
          { ...stamped, run_state, kind: shape },
          { who: opts.who, at: opts.at },
        );
      }

      if (flipEv.ok) {
        spineResult = appendRoadmapEventThroughSpine(
          opts.projectPath,
          flipEv.event,
          {
            skip_index: opts.skip_index !== false ? true : false,
            project_id: opts.project_id,
            seed: opts.seed,
            at: opts.at,
          },
        );
        spineResults.push(spineResult);
        if (typeof opts.onEvent === 'function') {
          opts.onEvent(stamped, spineResult);
        }
        applied.push({
          seq: s,
          kind: shape,
          spine: spineResult?.ok === true,
          idempotent: spineResult?.idempotent === true,
          run_state: flipEv.run_state ?? stamped.run_state ?? null,
          cause: flipEv.cause ?? stamped.cause ?? null,
          client_event_id: flipEv.event?.client_event_id,
        });
      } else {
        skipped.push({ seq: s, reason: flipEv.error, kind: shape });
      }
    } else if (shape === 'lease_renew' || shape === 'gate_surface' || shape === 'launch_intent') {
      // Non-flip seam events: recorded as applied (durable via outbox ack);
      // gate_surface is first-class but does not always flip a step.
      applied.push({
        seq: s,
        kind: shape,
        spine: false,
        run_id: stamped.run_id ?? null,
        gate: shape === 'gate_surface' ? stamped.gate || stamped : null,
      });
      if (typeof opts.onEvent === 'function') {
        opts.onEvent(stamped, { ok: true, spine: false });
      }
    } else {
      skipped.push({ seq: s, reason: 'no_step_or_no_flip', kind: shape });
    }

    lastAck = s;
  }

  const ackResult = norm.ack(lastAck);

  // Projection bound to EXISTING buildRoadmapProjection (e-4 closed by name)
  let projection = null;
  let projectionSource = 'buildRoadmapProjection';
  try {
    const loaded = loadProjectRoadmap(opts.projectPath);
    const roadmap = loaded.ok
      ? loaded.roadmap
      : opts.seed && typeof opts.seed === 'object'
        ? opts.seed
        : emptyRoadmap();
    const eventsList = Array.isArray(roadmap?.roadmap_events)
      ? roadmap.roadmap_events
      : [];
    const built = buildRoadmapProjection(eventsList);
    projection = Array.isArray(built?.projection) ? built.projection : [];
  } catch {
    projection = null;
  }

  const result = {
    ok: true,
    seam: STATUS_INGESTION_SEAM,
    producer: norm.id,
    after_seq: afterSeq,
    last_acked_seq: lastAck,
    applied,
    skipped,
    spine_results: spineResults,
    ack: ackResult,
    gap,
    gap_detail: gapDetail,
    projection,
    projection_source: projectionSource,
    e4_bound_to: 'roadmap.mjs buildRoadmapProjection',
    single_writer: true,
  };

  if (gap) {
    result.gap_status = statusFailure(STATUS_FAILURE_CODE.STATUS_SEQUENCE_GAP, {
      n: gapDetail?.as_of_seq ?? afterSeq,
      expected: gapDetail?.expected,
      found: gapDetail?.found,
    });
  }

  return result;
}

/**
 * Fixture producer factory for host-less skill-lane tests.
 * @param {object[]} events
 * @param {{ id?: string }} [opts]
 */
export function makeFixtureProducer(events, opts = {}) {
  const id = opts.id || STATUS_PRODUCERS.FIXTURE;
  const list = Array.isArray(events) ? [...events] : [];
  let lastAcked = 0;
  return {
    id,
    events: list,
    pull(afterSeq) {
      const from = Math.max(Number(afterSeq) || 0, lastAcked);
      return {
        events: list
          .filter((e) => Number(e.seq) > from)
          .sort((a, b) => Number(a.seq) - Number(b.seq)),
        gap: false,
      };
    },
    ack(seq) {
      lastAcked = Math.max(lastAcked, Number(seq) || 0);
      return { ok: true, last_acked_seq: lastAcked };
    },
    get last_acked_seq() {
      return lastAcked;
    },
  };
}

/**
 * Derive a run-status view bound to buildRoadmapProjection + last applied
 * seam outcomes (never peeks at live pids).
 *
 * @param {object[]} projection from buildRoadmapProjection
 * @param {Array<{ step_id?: string, run_state?: string, cause?: string, run_id?: string }>} runFacts
 */
export function bindStatusToRoadmapProjection(projection, runFacts = []) {
  const steps = Array.isArray(projection) ? projection : [];
  const facts = Array.isArray(runFacts) ? runFacts : [];
  const byStep = new Map();
  for (const f of facts) {
    if (f.step_id) byStep.set(f.step_id, f);
  }
  return steps.map((step) => {
    const f = byStep.get(step.id);
    const run_state = f?.run_state ?? null;
    const dead_by_name =
      run_state === RUN_LIVENESS.DEAD ||
      (typeof f?.cause === 'string' && f.cause.includes('lease_expired'));
    return {
      id: step.id,
      name: step.name,
      status: step.status,
      commissioned_as: step.commissioned_as ?? null,
      run_state,
      dead_by_name,
      cause: f?.cause ?? null,
      run_id: f?.run_id ?? null,
      still_working: step.status === 'active' && !dead_by_name,
    };
  });
}

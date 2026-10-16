/**
 * Wave 16 — Attention contract (altitude / criterion 12).
 *
 * deriveAttention(ledgerView) — ONE pure engine function returning one of the
 * five published states (working | needs_you | deliverable_ready | blocked |
 * idle) with state_since, reason, provenance. PURE (write-trap testable).
 * Over a READABLE ledger always one of the five. `unknown` is the READ-SIDE
 * answer for an unreadable store only — never a sixth published state.
 *
 * publishAttention() — the single publisher, a Wave-6 spine caller. Persists
 * the typed attention cell + attention_projection_published event (allow-list
 * v5) edge-only; no-change republish appends nothing. On every real state
 * change: precomputeBriefCache (raise tier 1) + index bridge push.
 *
 * Call-site table (each removal-proof tested):
 *   T-ATT-CS1 propose verb
 *   T-ATT-CS2 mediator drain
 *   T-ATT-CS3 handback ingester
 *   T-ATT-CS4 Wave-13 reconciler
 *   T-ATT-CS5 NL-polish queue append
 *   T-ATT-CS6 openProjectPipeline stage 3
 *   T-ATT-CS7 High Seat NEVER publishes
 *
 * Raise tier 2: waiting_steps from buildRoadmapProjection → enrichForRaise.
 * Raise tier 1: precomputeBriefCache on attention-state change.
 * deliverable_ready is bundle-hash gated (provenance-unproven otherwise).
 * Anti-FLAP: edge-triggered state_since + hysteresis (shared with Wave 13).
 *
 * Stdlib only. No host-absolute paths.
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from './durable-write.mjs';
import {
  appendRoadmapEventThroughSpine,
  ROADMAP_EVENT_KINDS_VERSION,
  assertEventKindAllowed,
} from './ledger-spine.mjs';
import { emptyRoadmap, loadProjectRoadmap, buildRoadmapProjection } from './roadmap.mjs';
import { LEASE_HYSTERESIS_MS, defaultLeaseMonoMs } from './lease-law.mjs';
import { precomputeBriefCache } from './brief.mjs';
import { pushAttentionProjection } from './portfolio/anchor-contract.mjs';
import { HOME_ENV } from './portfolio/home.mjs';

// ── Published states (NS criterion 12) ─────────────────────────────────────

/** Five published projection states — complete enum for published cells. */
export const ATTENTION_STATES = Object.freeze([
  'working',
  'needs_you',
  'deliverable_ready',
  'blocked',
  'idle',
]);

/** Read-side only — never published as a sixth state. */
export const ATTENTION_READ_UNKNOWN = 'unknown';

/** Relative path of the typed attention cell (S9). */
export const ATTENTION_CELL_REL = path.join('.ecgberht', 'attention.json');

/** Named durable helpers (S9 removal-proof). */
export const ATTENTION_ATOMIC_WRITE = 'writeFileAtomicSync';
export const ATTENTION_LOCK_HELPER = 'withFileLock';

export const ATTENTION_CELL_SCHEMA = 'ecgberht-attention-cell-v0';

/** Spine event kind (allow-list v5). */
export const ATTENTION_EVENT_KIND = 'attention_projection_published';

/** Wave-16 event kinds admitted on allow-list v5. */
export const W16_EVENT_KINDS = Object.freeze([ATTENTION_EVENT_KIND]);

/** Anti-flap hysteresis — shared with Wave 13 lease law. */
export const ATTENTION_HYSTERESIS_MS = LEASE_HYSTERESIS_MS;

// ── Failure-state table (projection surface) ───────────────────────────────

export const ATTENTION_CODE = Object.freeze({
  ATTENTION_UNKNOWN: 'ATTENTION_UNKNOWN',
  ATTENTION_PROVENANCE_UNPROVEN: 'ATTENTION_PROVENANCE_UNPROVEN',
  ATTENTION_STALE: 'ATTENTION_STALE',
  ATTENTION_PUBLISH_REFUSED: 'ATTENTION_PUBLISH_REFUSED',
  ATTENTION_NONE_YET: 'ATTENTION_NONE_YET',
  ATTENTION_INPUT_UNKNOWN: 'ATTENTION_INPUT_UNKNOWN',
});

export const ATTENTION_TEXT = Object.freeze({
  [ATTENTION_CODE.ATTENTION_UNKNOWN]:
    '<project>: attention state unknown (store unreadable) — never rendered as idle.',
  [ATTENTION_CODE.ATTENTION_PROVENANCE_UNPROVEN]:
    'Deliverable claimed but bundle hash unverified — not shown as ready.',
  [ATTENTION_CODE.ATTENTION_STALE]:
    'Attention state predates last reconcile — republish pending.',
  [ATTENTION_CODE.ATTENTION_PUBLISH_REFUSED]:
    'Projection publish refused by the ledger — prior state stands, refusal named.',
  [ATTENTION_CODE.ATTENTION_NONE_YET]:
    'No campaign activity to project yet.',
  [ATTENTION_CODE.ATTENTION_INPUT_UNKNOWN]:
    'Projection inputs unreadable — state unknown, not guessed.',
});

/**
 * Failure-state table rows (code + user-visible text).
 * @returns {ReadonlyArray<{ state: string, status_code: string, user_text: string }>}
 */
export function attentionFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'store-unreadable (read side)',
      status_code: ATTENTION_CODE.ATTENTION_UNKNOWN,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_UNKNOWN],
    }),
    Object.freeze({
      state: 'provenance-unproven',
      status_code: ATTENTION_CODE.ATTENTION_PROVENANCE_UNPROVEN,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_PROVENANCE_UNPROVEN],
    }),
    Object.freeze({
      state: 'stale (edge older than lease truth)',
      status_code: ATTENTION_CODE.ATTENTION_STALE,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_STALE],
    }),
    Object.freeze({
      state: 'publish-refused (spine refusal)',
      status_code: ATTENTION_CODE.ATTENTION_PUBLISH_REFUSED,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_PUBLISH_REFUSED],
    }),
    Object.freeze({
      state: 'empty-but-valid (no campaign)',
      status_code: ATTENTION_CODE.ATTENTION_NONE_YET,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_NONE_YET],
    }),
    Object.freeze({
      state: 'unknown (derivation input unresolvable)',
      status_code: ATTENTION_CODE.ATTENTION_INPUT_UNKNOWN,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_INPUT_UNKNOWN],
    }),
  ]);
}

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function attentionFailure(code, extra = {}) {
  const text = ATTENTION_TEXT[code] ?? ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_INPUT_UNKNOWN];
  return {
    ok: false,
    code,
    status_code: code,
    user_text: text,
    message: text,
    ...extra,
  };
}

// ── Mandatory call-site table ──────────────────────────────────────────────

/**
 * Named publish call sites. Each production trigger MUST invoke publishAttention
 * with the matching call_site id; removal-proof tests bind to these markers.
 */
export const ATTENTION_CALL_SITES = Object.freeze({
  /** T-ATT-CS1 — commission proposed / awaiting confirm (propose verb). */
  PROPOSE: 'propose',
  /** T-ATT-CS2 — confirm/launch recorded (mediator drain). */
  MEDIATOR: 'mediator_drain',
  /** T-ATT-CS3 — validated handback ingested (Wave-14 ingester). */
  HANDBACK: 'handback_ingest',
  /** T-ATT-CS4 — run dead / lease expired (Wave-13 reconciler). */
  RECONCILER: 'status_reconciler',
  /** T-ATT-CS5 — queued NL-polish compile pending (queue append). */
  NL_POLISH_QUEUE: 'nl_polish_queue',
  /** T-ATT-CS6 — boot/open-project (openProjectPipeline stage 3). */
  OPEN_PROJECT: 'openProjectPipeline:publish',
  /** T-ATT-CS8 — a commissioned run stopped and John is needed (run ingest). */
  COMMISSION_RUN: 'commission_run',
});

export const ATTENTION_CALL_SITE_TABLE = Object.freeze([
  Object.freeze({
    id: 'T-ATT-CS1',
    call_site: ATTENTION_CALL_SITES.PROPOSE,
    trigger: 'commission proposed / awaiting confirm',
    module: 'engine/job-lifecycle.mjs',
    never: false,
  }),
  Object.freeze({
    id: 'T-ATT-CS2',
    call_site: ATTENTION_CALL_SITES.MEDIATOR,
    trigger: 'confirm / launch recorded (mediator drain)',
    module: 'engine/status-mediator.mjs',
    never: false,
  }),
  Object.freeze({
    id: 'T-ATT-CS3',
    call_site: ATTENTION_CALL_SITES.HANDBACK,
    trigger: 'validated handback ingested',
    module: 'engine/handback-ingest.mjs',
    never: false,
  }),
  Object.freeze({
    id: 'T-ATT-CS4',
    call_site: ATTENTION_CALL_SITES.RECONCILER,
    trigger: 'run dead / lease expired',
    module: 'engine/status-reconciler.mjs',
    never: false,
  }),
  Object.freeze({
    id: 'T-ATT-CS5',
    call_site: ATTENTION_CALL_SITES.NL_POLISH_QUEUE,
    trigger: 'queued NL-polish compile pending',
    module: 'engine/session-envelope.mjs',
    never: false,
  }),
  Object.freeze({
    id: 'T-ATT-CS6',
    call_site: ATTENTION_CALL_SITES.OPEN_PROJECT,
    trigger: 'boot / open-project pipeline stage 3',
    module: 'engine/session-open.mjs',
    never: false,
  }),
  Object.freeze({
    id: 'T-ATT-CS7',
    call_site: null,
    trigger: 'High Seat NEVER publishes',
    module: 'engine/high-seat.mjs',
    never: true,
  }),
  Object.freeze({
    id: 'T-ATT-CS8',
    call_site: ATTENTION_CALL_SITES.COMMISSION_RUN,
    trigger: 'commissioned run stopped (asked / quiet / died / timeout / unreviewed produce)',
    module: 'engine/steward-run-ingest.mjs',
    never: false,
  }),
]);

// ── Waiting steps (raise tier 2) ───────────────────────────────────────────

/**
 * Count waiting-on-John steps from an EXISTING buildRoadmapProjection result.
 * Pure over the projection array.
 *
 * @param {object[]|null|undefined} projection
 * @returns {number}
 */
export function countWaitingOnJohnSteps(projection) {
  if (!Array.isArray(projection)) return 0;
  let n = 0;
  for (const s of projection) {
    if (!s || typeof s !== 'object') continue;
    if (s.status === 'waiting' || s.status === 'waiting_on_john') {
      n += 1;
      continue;
    }
    if (s.waiting_on != null && String(s.waiting_on).length > 0) {
      n += 1;
    }
  }
  return n;
}

/**
 * Derive waiting_steps from roadmap events via buildRoadmapProjection.
 * Pure when events/projection are passed; disk load only when projectPath given
 * and projection not supplied (for enrichForRaise revival).
 *
 * @param {{
 *   projection?: object[],
 *   events?: object[],
 *   roadmap?: object|null,
 *   projectPath?: string,
 * }} [opts]
 * @returns {{ waiting_steps: number, projection: object[], source: string }}
 */
export function deriveWaitingSteps(opts = {}) {
  if (Array.isArray(opts.projection)) {
    return {
      waiting_steps: countWaitingOnJohnSteps(opts.projection),
      projection: opts.projection,
      source: 'projection',
    };
  }
  const events = Array.isArray(opts.events)
    ? opts.events
    : Array.isArray(opts.roadmap?.roadmap_events)
      ? opts.roadmap.roadmap_events
      : null;
  if (events) {
    try {
      const built = buildRoadmapProjection(events);
      const projection = Array.isArray(built?.projection) ? built.projection : [];
      return {
        waiting_steps: countWaitingOnJohnSteps(projection),
        projection,
        source: 'buildRoadmapProjection',
      };
    } catch {
      return { waiting_steps: 0, projection: [], source: 'build_failed' };
    }
  }
  if (opts.projectPath && typeof opts.projectPath === 'string') {
    try {
      const loaded = loadProjectRoadmap(opts.projectPath);
      if (loaded.ok && loaded.exists && loaded.roadmap) {
        return deriveWaitingSteps({ roadmap: loaded.roadmap });
      }
    } catch {
      /* fall through */
    }
  }
  return { waiting_steps: 0, projection: [], source: 'empty' };
}

// ── Bundle-hash provenance for deliverable_ready ───────────────────────────

/**
 * Provenance gate: deliverable_ready requires a matching bundle hash.
 * @param {object|null} ledgerView
 * @returns {{ proven: boolean, claimed: boolean, bundle_hash: string|null, expected: string|null }}
 */
export function deliverableProvenance(ledgerView) {
  const v = ledgerView && typeof ledgerView === 'object' ? ledgerView : {};
  const claimed =
    v.deliverable_ready === true ||
    v.deliverable_claimed === true ||
    (Array.isArray(v.events) &&
      v.events.some(
        (e) =>
          e &&
          (e.kind === 'reflection_receipt' ||
            e.kind === 'handback_validated' ||
            e.deliverable_ready === true),
      ));
  const bundle_hash =
    v.bundle_hash != null
      ? String(v.bundle_hash)
      : v.handback?.bundle_hash != null
        ? String(v.handback.bundle_hash)
        : v.handback?.content_hash != null
          ? String(v.handback.content_hash)
          : null;
  const expected =
    v.expected_bundle_hash != null
      ? String(v.expected_bundle_hash)
      : v.handback?.expected_bundle_hash != null
        ? String(v.handback.expected_bundle_hash)
        : v.dossier?.bundle_hash != null
          ? String(v.dossier.bundle_hash)
          : null;

  if (!claimed) {
    return { proven: false, claimed: false, bundle_hash, expected };
  }
  // Claimed without any hash material → unproven.
  if (!bundle_hash || !expected) {
    return { proven: false, claimed: true, bundle_hash, expected };
  }
  return {
    proven: bundle_hash === expected,
    claimed: true,
    bundle_hash,
    expected,
  };
}

// ── Pure derivation ────────────────────────────────────────────────────────

/**
 * Pure derivation over a ledger view.
 * Zero writes, zero model calls, zero I/O beyond the passed view.
 *
 * @param {object|null} ledgerView
 * @returns {{
 *   state: string,
 *   state_since: string|null,
 *   reason: string,
 *   provenance: object[],
 *   readable: boolean,
 *   failure_code: string|null,
 *   user_text: string|null,
 *   waiting_steps: number,
 *   bundle_hash: string|null,
 * }}
 */
export function deriveAttention(ledgerView) {
  // Pure: no fs, no network, no model. Callers write-trap this.
  if (ledgerView == null || ledgerView.unreadable === true) {
    return {
      state: ATTENTION_READ_UNKNOWN,
      state_since: null,
      reason: 'ledger_unreadable',
      provenance: [],
      readable: false,
      failure_code: ATTENTION_CODE.ATTENTION_UNKNOWN,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_UNKNOWN],
      waiting_steps: 0,
      bundle_hash: null,
    };
  }

  if (ledgerView.input_unknown === true || ledgerView.inputs_unresolvable === true) {
    return {
      state: ATTENTION_READ_UNKNOWN,
      state_since: null,
      reason: 'inputs_unresolvable',
      provenance: [],
      readable: false,
      failure_code: ATTENTION_CODE.ATTENTION_INPUT_UNKNOWN,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_INPUT_UNKNOWN],
      waiting_steps: 0,
      bundle_hash: null,
    };
  }

  const events = Array.isArray(ledgerView.events)
    ? ledgerView.events
    : Array.isArray(ledgerView.roadmap?.roadmap_events)
      ? ledgerView.roadmap.roadmap_events
      : [];
  const projection = Array.isArray(ledgerView.projection)
    ? ledgerView.projection
    : Array.isArray(ledgerView.roadmap?.roadmap_projection)
      ? ledgerView.roadmap.roadmap_projection
      : [];
  const runFacts = Array.isArray(ledgerView.run_facts) ? ledgerView.run_facts : [];
  const missingHandbacks = Array.isArray(ledgerView.missing_handbacks)
    ? ledgerView.missing_handbacks
    : [];
  const waiting = Array.isArray(ledgerView.waiting_on_john)
    ? ledgerView.waiting_on_john
    : [];

  const waitingSteps = countWaitingOnJohnSteps(projection);
  const deadRuns = runFacts.filter(
    (r) =>
      r &&
      (r.run_state === 'dead' ||
        r.dead === true ||
        String(r.cause || '').includes('lease_expired')),
  );
  const active = projection.find((s) => s && s.status === 'active');
  const liveRun = runFacts.some(
    (r) => r && (r.run_state === 'running' || r.run_state === 'live'),
  );
  const awaitingConfirm =
    ledgerView.awaiting_confirm === true ||
    ledgerView.commission_proposal_pending === true ||
    (ledgerView.commission_proposal &&
      ledgerView.commission_proposal.confirmed !== true &&
      ledgerView.commission_proposal.requires_confirm !== false);
  const nlPolishPending =
    ledgerView.nl_polish_queued === true ||
    ledgerView.nl_polish_pending === true ||
    events.some((e) => e && e.kind === 'nl_polish_reflection_compile_queued');

  const deliv = deliverableProvenance(ledgerView);

  let state;
  let reason;
  let failure_code = null;
  const provenance = [];

  if (missingHandbacks.length > 0 || deadRuns.length > 0) {
    state = 'needs_you';
    reason =
      deadRuns.length && missingHandbacks.length
        ? 'dead_run_and_missing_handback'
        : deadRuns.length
          ? 'dead_run_named'
          : 'missing_handback_named';
    for (const d of deadRuns) {
      provenance.push({
        kind: 'run_fact',
        run_id: d.run_id ?? null,
        run_state: d.run_state,
      });
    }
    for (const m of missingHandbacks) {
      provenance.push({
        kind: 'missing_handback',
        commission_id: m.commission_id ?? m.id ?? null,
      });
    }
  } else if (awaitingConfirm) {
    state = 'needs_you';
    reason = 'commission_awaiting_confirm';
    provenance.push({
      kind: 'commission_proposal',
      proposal_id: ledgerView.commission_proposal?.proposal_id ?? null,
    });
  } else if (waiting.length > 0 || waitingSteps > 0) {
    state = 'needs_you';
    reason = 'waiting_on_john';
    provenance.push({ kind: 'waiting_steps', count: waitingSteps || waiting.length });
  } else if (nlPolishPending) {
    state = 'needs_you';
    reason = 'nl_polish_compile_pending';
    provenance.push({ kind: 'nl_polish_queue' });
  } else if (deliv.claimed && deliv.proven) {
    state = 'deliverable_ready';
    reason = 'deliverable_bundle_hash_matched';
    provenance.push({
      kind: 'deliverable',
      bundle_hash: deliv.bundle_hash,
      proven: true,
    });
  } else if (deliv.claimed && !deliv.proven) {
    // Provenance gate: do NOT emit deliverable_ready.
    failure_code = ATTENTION_CODE.ATTENTION_PROVENANCE_UNPROVEN;
    if (active || liveRun) {
      state = 'working';
      reason = 'deliverable_unproven_active';
    } else if (
      projection.some((s) => s && (s.status === 'blocked' || s.status === 'failed'))
    ) {
      state = 'blocked';
      reason = 'deliverable_unproven_blocked';
    } else {
      state = 'needs_you';
      reason = 'provenance_unproven';
    }
    provenance.push({
      kind: 'provenance_unproven',
      bundle_hash: deliv.bundle_hash,
      expected: deliv.expected,
      code: failure_code,
    });
  } else if (active || liveRun) {
    state = 'working';
    reason = 'active_step_or_live_run';
    provenance.push({
      kind: 'active',
      step_id: active?.id ?? active?.step_id ?? null,
    });
  } else if (
    projection.some((s) => s && (s.status === 'blocked' || s.status === 'failed'))
  ) {
    state = 'blocked';
    reason = 'blocked_step';
    provenance.push({ kind: 'blocked_step' });
  } else if (
    ledgerView.empty === true ||
    (events.length === 0 && projection.length === 0 && runFacts.length === 0)
  ) {
    state = 'idle';
    reason = 'no_campaign_activity';
    failure_code = ATTENTION_CODE.ATTENTION_NONE_YET;
    provenance.push({ kind: 'empty_but_valid' });
  } else {
    state = 'idle';
    reason = 'campaign_quiet';
    provenance.push({ kind: 'quiet' });
  }

  // Stale edge: published state older than last reconcile truth.
  if (
    ledgerView.stale === true ||
    (ledgerView.last_reconcile_at &&
      ledgerView.attention_at &&
      String(ledgerView.attention_at) < String(ledgerView.last_reconcile_at))
  ) {
    failure_code = failure_code ?? ATTENTION_CODE.ATTENTION_STALE;
    provenance.push({ kind: 'stale', code: ATTENTION_CODE.ATTENTION_STALE });
  }

  // Never publish `unknown` — only the five.
  if (!ATTENTION_STATES.includes(state)) {
    state = 'idle';
    reason = 'fallback_idle';
  }

  const state_since =
    ledgerView.state_since ??
    ledgerView.at ??
    (events.length ? events[events.length - 1]?.at ?? null : null);

  return {
    state,
    state_since: state_since != null ? String(state_since) : null,
    reason,
    provenance,
    readable: true,
    failure_code,
    user_text: failure_code ? ATTENTION_TEXT[failure_code] ?? null : null,
    waiting_steps: waitingSteps,
    bundle_hash: deliv.bundle_hash,
  };
}

/**
 * Anti-FLAP: edge-triggered state_since + optional hysteresis.
 * Shared hysteresis bound with Wave 13 (LEASE_HYSTERESIS_MS).
 *
 * @param {object} derived from deriveAttention
 * @param {object|null} priorCell
 * @param {{ now?: string, nowMono?: number, force?: boolean }} [opts]
 * @returns {object} derived with state_since / anti-flap fields applied
 */
export function applyAttentionAntiFlap(derived, priorCell, opts = {}) {
  if (!derived || derived.readable === false) return derived;
  const now = opts.now != null ? String(opts.now) : new Date().toISOString();
  const nowMono =
    opts.nowMono != null ? Number(opts.nowMono) : defaultLeaseMonoMs();

  if (!priorCell || priorCell.state == null) {
    return {
      ...derived,
      state_since: derived.state_since ?? now,
      anti_flap: { flipped: true, held: false, hysteresis_ms: ATTENTION_HYSTERESIS_MS },
    };
  }

  if (priorCell.state === derived.state) {
    return {
      ...derived,
      state_since: priorCell.state_since ?? derived.state_since ?? now,
      anti_flap: { flipped: false, held: false, hysteresis_ms: ATTENTION_HYSTERESIS_MS },
    };
  }

  // Candidate differs — hysteresis unless forced (hard death / explicit force).
  if (opts.force !== true && priorCell.pending_state === derived.state) {
    const pendingSince = Number(priorCell.pending_since_mono ?? 0);
    const held = nowMono - pendingSince;
    if (Number.isFinite(held) && held < ATTENTION_HYSTERESIS_MS) {
      return {
        ...derived,
        state: priorCell.state,
        state_since: priorCell.state_since ?? derived.state_since ?? now,
        reason: priorCell.reason ?? derived.reason,
        anti_flap: {
          flipped: false,
          held: true,
          pending_state: derived.state,
          pending_since_mono: pendingSince,
          held_ms: held,
          hysteresis_ms: ATTENTION_HYSTERESIS_MS,
        },
      };
    }
  }

  // Commit flip — edge-triggered state_since moves only here.
  return {
    ...derived,
    state_since: now,
    anti_flap: {
      flipped: true,
      held: false,
      pending_state: null,
      pending_since_mono: null,
      hysteresis_ms: ATTENTION_HYSTERESIS_MS,
      from: priorCell.state,
      to: derived.state,
    },
  };
}

/**
 * Stable content hash of a projection edge (for edge-only idempotence).
 * @param {object} derived
 * @returns {string}
 */
export function attentionEdgeHash(derived) {
  const body = {
    state: derived?.state ?? null,
    reason: derived?.reason ?? null,
    // state_since intentionally excluded from edge identity so anti-flap
    // re-stamps do not force republish of an unchanged altitude.
    failure_code: derived?.failure_code ?? null,
    waiting_steps: derived?.waiting_steps ?? 0,
    bundle_hash: derived?.bundle_hash ?? null,
  };
  return crypto.createHash('sha256').update(JSON.stringify(body)).digest('hex');
}

/**
 * Absolute path of the attention cell for a project.
 * @param {string} projectPath
 */
export function attentionCellPath(projectPath) {
  return path.join(path.resolve(projectPath), ATTENTION_CELL_REL);
}

/**
 * Read the typed attention cell (absent → null).
 * @param {string} projectPath
 */
export function readAttentionCell(projectPath) {
  const p = attentionCellPath(projectPath);
  try {
    if (!fs.existsSync(p)) return { ok: true, exists: false, cell: null };
    const raw = fs.readFileSync(p, 'utf8');
    const cell = JSON.parse(raw);
    return { ok: true, exists: true, cell };
  } catch (e) {
    return {
      ok: false,
      exists: true,
      cell: null,
      error: 'attention_cell_unreadable',
      detail: String(e?.message ?? e),
      failure_code: ATTENTION_CODE.ATTENTION_UNKNOWN,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_UNKNOWN],
    };
  }
}

/**
 * Last event seq from a ledger view (for derived_from_event_seq).
 * @param {object|null} ledgerView
 * @returns {number|null}
 */
function derivedFromEventSeq(ledgerView) {
  const events = Array.isArray(ledgerView?.events)
    ? ledgerView.events
    : Array.isArray(ledgerView?.roadmap?.roadmap_events)
      ? ledgerView.roadmap.roadmap_events
      : [];
  if (!events.length) return null;
  const last = events[events.length - 1];
  const seq = last?.seq;
  return typeof seq === 'number' ? seq : seq != null ? Number(seq) : null;
}

/**
 * Edge-only publish of the typed attention projection.
 * Spine caller: appends attention_projection_published + writes the cell.
 * No-change republish appends nothing (byte-identical cell, published:false).
 * On real state change: precomputeBriefCache (raise tier 1) + index bridge.
 *
 * @param {string} projectPath
 * @param {{
 *   ledgerView?: object|null,
 *   derived?: object|null,
 *   who?: string,
 *   at?: string,
 *   client_event_id?: string,
 *   skip?: boolean,
 *   call_site?: string,
 *   seed?: object|null,
 *   skip_index?: boolean,
 *   skip_spine?: boolean,
 *   skip_brief_cache?: boolean,
 *   skip_index_bridge?: boolean,
 *   project_id?: string,
 *   force?: boolean,
 *   nowMono?: number,
 *   precomputeBriefCacheFn?: function,
 *   pushIndexFn?: function,
 * }} [opts]
 */
export function publishAttention(projectPath, opts = {}) {
  const call_site = opts.call_site || ATTENTION_CALL_SITES.OPEN_PROJECT;

  if (opts.skip === true) {
    return {
      ok: true,
      published: false,
      skipped: true,
      reason: 'publish_skipped',
      call_site,
    };
  }

  if (!projectPath || typeof projectPath !== 'string') {
    return {
      ok: false,
      error: 'project_path_required',
      message: 'publishAttention requires projectPath',
      call_site,
    };
  }

  const root = path.resolve(projectPath);
  let derived =
    opts.derived && typeof opts.derived === 'object'
      ? { ...opts.derived }
      : deriveAttention(opts.ledgerView ?? null);

  // Read-side unknown is never published as a sixth state.
  if (derived.readable === false || derived.state === ATTENTION_READ_UNKNOWN) {
    return {
      ok: true,
      published: false,
      reason: 'unreadable_not_published',
      derived,
      call_site,
      failure_code: derived.failure_code ?? ATTENTION_CODE.ATTENTION_UNKNOWN,
      user_text:
        derived.user_text ?? ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_UNKNOWN],
    };
  }

  const prior = readAttentionCell(root);
  const priorCell = prior.ok && prior.exists ? prior.cell : null;
  derived = applyAttentionAntiFlap(derived, priorCell, {
    now: opts.at,
    nowMono: opts.nowMono,
    force: opts.force === true,
  });

  const edgeHash = attentionEdgeHash(derived);
  const client_event_id =
    opts.client_event_id || `attention:${edgeHash.slice(0, 16)}`;

  if (
    prior.ok &&
    prior.exists &&
    prior.cell &&
    prior.cell.edge_hash === edgeHash &&
    prior.cell.state === derived.state
  ) {
    return {
      ok: true,
      published: false,
      reason: 'no_edge_change',
      edge_hash: edgeHash,
      client_event_id: prior.cell.client_event_id ?? client_event_id,
      cell: prior.cell,
      call_site,
      idempotent: true,
    };
  }

  const at = opts.at || new Date().toISOString();
  const fromSeq = derivedFromEventSeq(opts.ledgerView ?? null);

  // ── Spine event (allow-list v5) — journaled with the cell ────────────────
  let spine = null;
  if (opts.skip_spine !== true) {
    const event = {
      kind: ATTENTION_EVENT_KIND,
      state: derived.state,
      state_since: derived.state_since,
      derived_from_event_seq: fromSeq,
      bundle_hash: derived.bundle_hash ?? null,
      reason: derived.reason,
      edge_hash: edgeHash,
      client_event_id,
      call_site,
      who: opts.who || 'publishAttention',
      at,
    };
    spine = appendRoadmapEventThroughSpine(root, event, {
      at,
      seed: opts.seed ?? undefined,
      skip_index: opts.skip_index !== false,
      project_id: opts.project_id,
    });
    if (!spine || spine.ok === false) {
      // Prior cell stands; name the refusal.
      return {
        ...attentionFailure(ATTENTION_CODE.ATTENTION_PUBLISH_REFUSED, {
          published: false,
          spine,
          derived,
          call_site,
          edge_hash: edgeHash,
          client_event_id,
          prior_cell: priorCell,
        }),
      };
    }
    if (spine.idempotent === true && priorCell && priorCell.edge_hash === edgeHash) {
      return {
        ok: true,
        published: false,
        reason: 'no_edge_change',
        edge_hash: edgeHash,
        client_event_id,
        cell: priorCell,
        call_site,
        idempotent: true,
        spine,
      };
    }
  }

  const cell = {
    schema: ATTENTION_CELL_SCHEMA,
    state: derived.state,
    state_since: derived.state_since,
    reason: derived.reason,
    provenance: Array.isArray(derived.provenance) ? derived.provenance : [],
    failure_code: derived.failure_code ?? null,
    waiting_steps: derived.waiting_steps ?? 0,
    bundle_hash: derived.bundle_hash ?? null,
    edge_hash: edgeHash,
    client_event_id,
    derived_from_event_seq: fromSeq,
    who: opts.who || 'publishAttention',
    at,
    published_via: call_site,
    pending_state: derived.anti_flap?.pending_state ?? null,
    pending_since_mono: derived.anti_flap?.pending_since_mono ?? null,
    // THE BRIEFING (2026-08-06). A commissioned run that stops carries did /
    // question / next / session onto the cell, so the High Seat can answer
    // "what did it do, what would it do next" without John going in to ask.
    // Absent for every other publisher — never invented here.
    briefing: derived.briefing && typeof derived.briefing === 'object'
      ? derived.briefing
      : null,
  };

  const cellPath = attentionCellPath(root);
  try {
    withFileLock(
      cellPath,
      () => {
        fs.mkdirSync(path.dirname(cellPath), { recursive: true });
        writeFileAtomicSync(cellPath, `${JSON.stringify(cell, null, 2)}\n`);
      },
      { timeoutMs: LOCK_TIMEOUT_MS },
    );
  } catch (e) {
    return {
      ok: false,
      error: 'attention_publish_failed',
      detail: String(e?.message ?? e),
      call_site,
      spine,
      failure_code: ATTENTION_CODE.ATTENTION_PUBLISH_REFUSED,
      user_text: ATTENTION_TEXT[ATTENTION_CODE.ATTENTION_PUBLISH_REFUSED],
    };
  }

  // ── Raise tier 1: precomputeBriefCache on EVERY attention-state change ───
  let brief_cache = null;
  if (opts.skip_brief_cache !== true) {
    const precompute =
      typeof opts.precomputeBriefCacheFn === 'function'
        ? opts.precomputeBriefCacheFn
        : precomputeBriefCache;
    try {
      brief_cache = precompute(root, {
        project: root,
        ...(opts.brief_opts && typeof opts.brief_opts === 'object' ? opts.brief_opts : {}),
      });
    } catch (e) {
      brief_cache = {
        ok: false,
        error: 'precompute_brief_cache_failed',
        detail: String(e?.message ?? e),
      };
    }
  }

  // ── Index bridge: project pushes; index never walks ──────────────────────
  // Only when an index target is explicit (home / paths / HOME_ENV env key) or
  // a push function is injected — never ambient-write the operator's real home
  // from a test that forgot to set the index-home env. HOME_ENV is imported
  // from portfolio/home.mjs so this module never re-resolves the home name.
  let index_bridge = null;
  const hasIndexTarget =
    typeof opts.pushIndexFn === 'function' ||
    opts.home != null ||
    opts.paths != null ||
    (opts.env != null &&
      Object.prototype.hasOwnProperty.call(opts.env, HOME_ENV));
  if (opts.skip_index_bridge !== true && hasIndexTarget) {
    const push =
      typeof opts.pushIndexFn === 'function'
        ? opts.pushIndexFn
        : pushAttentionProjection;
    try {
      index_bridge = push({
        project_id: opts.project_id ?? null,
        project_path: root,
        attention: cell,
        home: opts.home,
        env: opts.env,
        paths: opts.paths,
      });
    } catch (e) {
      index_bridge = {
        ok: false,
        error: 'index_bridge_failed',
        detail: String(e?.message ?? e),
      };
    }
  } else if (opts.skip_index_bridge !== true) {
    index_bridge = {
      ok: true,
      pushed: false,
      skipped: true,
      reason: 'no_index_target',
      bridge: 'pushAttentionProjection',
    };
  }

  return {
    ok: true,
    published: true,
    edge_hash: edgeHash,
    client_event_id,
    cell,
    derived,
    spine,
    brief_cache,
    index_bridge,
    call_site,
    atomic_write: ATTENTION_ATOMIC_WRITE,
    lock: ATTENTION_LOCK_HELPER,
    raise_tier1_precompute: brief_cache?.ok === true,
  };
}

/**
 * Source-removal proof: attention module names durable helpers + derive/publish.
 * @param {string} sourceText
 */
export function assertAttentionDurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  if (!sourceText.includes('deriveAttention')) missing.push('deriveAttention');
  if (!sourceText.includes('publishAttention')) missing.push('publishAttention');
  if (!sourceText.includes('appendRoadmapEventThroughSpine')) {
    missing.push('appendRoadmapEventThroughSpine');
  }
  if (!sourceText.includes('precomputeBriefCache')) missing.push('precomputeBriefCache');
  return { ok: missing.length === 0, missing };
}

/**
 * Wave-16 allow-list admission proof.
 */
export function assertW16KindsAdmitted() {
  const missing = [];
  for (const k of W16_EVENT_KINDS) {
    const r = assertEventKindAllowed(k);
    if (!r.ok) missing.push(k);
  }
  return {
    ok: missing.length === 0 && ROADMAP_EVENT_KINDS_VERSION >= 5,
    version: ROADMAP_EVENT_KINDS_VERSION,
    w16_kinds: [...W16_EVENT_KINDS],
    missing,
  };
}

/**
 * Removal-proof: a module source must contain publishAttention for its call site.
 * @param {string} sourceText
 * @param {string} callSiteId e.g. ATTENTION_CALL_SITES.PROPOSE
 */
export function assertPublishCallSitePresent(sourceText, callSiteId) {
  const hasPublish = /publishAttention\s*\(/.test(sourceText);
  const hasMarker =
    sourceText.includes(callSiteId) ||
    sourceText.includes(`'${callSiteId}'`) ||
    sourceText.includes(`"${callSiteId}"`);
  return {
    ok: hasPublish && hasMarker,
    has_publish: hasPublish,
    has_marker: hasMarker,
    call_site: callSiteId,
  };
}

/**
 * T-ATT-CS7: High Seat source must NEVER call publishAttention.
 * Read-only imports (countWaitingOnJohnSteps / deriveWaitingSteps) are allowed;
 * only a publishAttention(...) call (or alias invocation) is forbidden.
 * @param {string} highSeatSourceText
 */
export function assertHighSeatNeverPublishes(highSeatSourceText) {
  const publishes = /publishAttention\s*\(/.test(highSeatSourceText);
  return {
    ok: !publishes,
    publishes,
    call_site: null,
    id: 'T-ATT-CS7',
  };
}

/**
 * Byte-identity helper for T-IDEM-16 (attention cell).
 * @param {string} projectPath
 * @returns {string|null}
 */
export function attentionCellBytes(projectPath) {
  const p = attentionCellPath(projectPath);
  try {
    if (!fs.existsSync(p)) return null;
    return fs.readFileSync(p, 'utf8');
  } catch {
    return null;
  }
}

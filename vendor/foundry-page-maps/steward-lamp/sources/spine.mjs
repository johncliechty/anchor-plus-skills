/**
 * Wave 6 — Ledger spine: ONE writer for roadmap_events IN PRODUCTION.
 *
 * Reality (named, not hidden): the campaign ledger is a whole-file JSON rewrite
 * of `roadmap.json` (roadmap_events[] + derived projection). Concurrent short-lived
 * Node bridge processes (Anchor `subprocess.run(timeout=20/30)`) used to
 * read-modify-write unlocked; a kill mid-write could tear the file and two
 * processes could silently drop each other's events.
 *
 * This module is the sole production append path:
 *   - NAMED lock: `withFileLock` on the roadmap.json path (durable-write.mjs)
 *   - NAMED atomic write: `writeFileAtomicSync` under that lock
 *   - Versioned event-kind allow-list (Master-Plan P2) — chat turns impossible
 *   - Typed-store allow-list — undeclared store writes refused by name
 *   - client_event_id append idempotence (T-IDEM-06)
 *   - ROADMAP_EVENTS_MAX bound with events-bound-exceeded refusal
 *
 * Pure in-memory law stays in roadmap.mjs (`appendRoadmapEvent`); production
 * persist ALWAYS re-loads under the lock so concurrent appenders serialise.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';
import { northStarRevision, FACE_FILE_NAME } from './face-strip.mjs';
import { overCap, missingSpine } from './write-authority.mjs';
import { prepareRefinementEvent, publishRefinementProjections, refinementProjectionStatus, refinementRoadmapStatus, refinementResult } from './refinement.mjs';
import { foldRefinements } from './refinement-state.mjs';

import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from './durable-write.mjs';
// NOTE: function-body imports from roadmap.mjs only — never top-level const
// reads of roadmap bindings (circular ESM: roadmap imports this module).
import {
  appendRoadmapEvent,
  loadProjectRoadmap,
  healRoadmap,
  emptyRoadmap,
  projectRoadmapBytes,
  roadmapEventCarrierRecord,
  roadmapEventBytes,
  roadmapIdFor,
  ROADMAP_EVENT_KINDS as ROADMAP_KINDS_FROM_MODULE,
} from './roadmap.mjs';
import { pathEntryFor } from './portfolio/commit-intent.mjs';
import { ingestWrite, relPathFor } from './portfolio/ingest.mjs';
import { CLASS } from './portfolio/inventory.mjs';
import { PROJECT_ID_PATTERN } from './portfolio/marker.mjs';

// ── Named durability helpers (removal-proof T-DUR-S1) ──────────────────────

/** Named lock helper — Durable-store map S1. */
export const SPINE_LOCK_HELPER = 'withFileLock';

/** Named atomic write — Durable-store map S1. */
export const SPINE_ATOMIC_WRITE = 'writeFileAtomicSync';

/**
 * The file the spine serialises under the lock (whole-file rewrite reality).
 * Literal — do not import ROADMAP_FILE_NAME at top level (circular ESM TDZ).
 */
export const SPINE_LEDGER_FILE = 'roadmap.json';
const ROADMAP_FILE_NAME = SPINE_LEDGER_FILE;

// ── Versioned event-kind allow-list (Master-Plan P2) ────────────────────────

/**
 * Allow-list VERSION. Admitting reflection_receipt / next_stage_proposal /
 * attention events requires an explicit VERSION BUMP + test — never a silent
 * kind add. This list IS the mechanical chat-turn detector.
 *
 * v1: step_* + commission_bind + scaffold_proposal (Wave 6/9)
 * v2: + face_assert / face_retract / face_refine / face_compile (Wave 10 — Face
 *     compile projection; Master-Plan P4)
 * v3: + elaboration_probe / elaboration_answer / elaboration_decline /
 *     elaboration_offer_refused (Wave 12 — progressive elaboration at stage START)
 * v4: + reflection_receipt / next_stage_proposal (Wave 14 — gate decision 4
 *     zero-model emit at validated handback)
 * v5: + attention_projection_published (Wave 16 — altitude contract / criterion 12)
 * v6: + goal_flip (Wave 17 — steward slice loop; re-read the North Star on close)
 * v7: + kickoff_proposal / kickoff_confirm (Wave 18 — conversational kickoff lineage)
 */
export const ROADMAP_EVENT_KINDS_VERSION = 9;

/**
 * Kinds admitted at the current version. Mirror of roadmap.mjs ROADMAP_EVENT_KINDS.
 * Wave 10 (v2): face_assert / face_retract / face_refine / face_compile.
 * Wave 12 (v3): elaboration_* progressive-elaboration events.
 * Wave 14 (v4): reflection_receipt / next_stage_proposal (gate decision 4).
 * Wave 16 (v5): attention_projection_published (altitude contract).
 * Wave 17 (v6): goal_flip (steward slice loop).
 * Wave 18 (v7): kickoff_proposal / kickoff_confirm (versioned human confirmation).
 * Steward revision W4 (v9, 2026-09-28): repair_proposal / repair_resolve (a repair shown, applied on his word) and
 * reorder (his own act on the plan's order).
 */
export const SPINE_EVENT_KINDS = Object.freeze([
  'step_create',
  'step_set',
  'status_flip',
  'commission_bind',
  'scaffold_proposal',
  'face_assert',
  'face_retract',
  'face_refine',
  'face_compile',
  'elaboration_probe',
  'elaboration_answer',
  'elaboration_decline',
  'elaboration_offer_refused',
  'reflection_receipt',
  'next_stage_proposal',
  'attention_projection_published',
  'goal_flip',
  'kickoff_proposal',
  'kickoff_confirm',
  'refinement_update',
  'repair_proposal',
  'repair_resolve',
  'reorder',
]);

// ── Typed-store allow-list ─────────────────────────────────────────────────

/** Stores the spine (and its strip / Face durable peers) may write. */
export const TYPED_STORES = Object.freeze([
  'roadmap_events',
  'strip_receipts',
  'strip_instruments',
  'face_events',
  'source_text',
]);

// ── Bound ──────────────────────────────────────────────────────────────────

/** Named bound — further appends refuse with events-bound-exceeded. */
export const ROADMAP_EVENTS_MAX = 50_000;

// ── Failure states (spine surface) ─────────────────────────────────────────

export const SPINE_CODE = Object.freeze({
  LOCK_TIMEOUT: 'SPINE_LOCK_TIMEOUT',
  STORE_REFUSED: 'SPINE_STORE_REFUSED',
  KIND_REFUSED: 'SPINE_KIND_REFUSED',
  EVENTS_BOUND: 'SPINE_EVENTS_BOUND',
  LEDGER_UNREADABLE: 'SPINE_LEDGER_UNREADABLE',
  LEDGER_EMPTY: 'SPINE_LEDGER_EMPTY',
  STATE_UNKNOWN: 'SPINE_STATE_UNKNOWN',
});

export const SPINE_TEXT = Object.freeze({
  [SPINE_CODE.LOCK_TIMEOUT]:
    'Ledger busy — write retried then refused; nothing partial was written.',
  [SPINE_CODE.STORE_REFUSED]:
    'Write aimed at an undeclared store — refused by name.',
  [SPINE_CODE.KIND_REFUSED]:
    'Event kind is not on the versioned allow-list — refused; no transcript sink.',
  [SPINE_CODE.EVENTS_BOUND]:
    'Ledger at its 50000-event bound — append refused by name, never truncated.',
  [SPINE_CODE.LEDGER_UNREADABLE]:
    'Campaign ledger unreadable — writes refused rather than guessed.',
  [SPINE_CODE.LEDGER_EMPTY]: 'No campaign events yet.',
  [SPINE_CODE.STATE_UNKNOWN]:
    'Ledger state unknown — reported as unknown, not healthy.',
});

/**
 * @param {string} code SPINE_CODE value
 * @param {object} [extra]
 */
export function spineFailure(code, extra = {}) {
  const kind = extra.kind;
  let text = SPINE_TEXT[code] ?? SPINE_TEXT[SPINE_CODE.STATE_UNKNOWN];
  if (code === SPINE_CODE.KIND_REFUSED && kind != null) {
    text = `Event kind ${kind} is not on the versioned allow-list — refused; no transcript sink.`;
  }
  return {
    ok: false,
    error: extra.error ?? code.toLowerCase().replace(/_/g, '-'),
    code,
    status: code,
    text,
    message: text,
    spine: true,
    kinds_version: ROADMAP_EVENT_KINDS_VERSION,
    ...extra,
  };
}

/**
 * Refuse an undeclared store by name.
 * @param {string} store
 */
export function assertStoreDeclared(store) {
  if (!TYPED_STORES.includes(store)) {
    return spineFailure(SPINE_CODE.STORE_REFUSED, {
      error: 'store-not-declared',
      store: store ?? null,
      declared: [...TYPED_STORES],
    });
  }
  return { ok: true, store };
}

/**
 * Refuse a kind outside the versioned allow-list.
 * @param {string} kind
 */
export function assertEventKindAllowed(kind) {
  if (!SPINE_EVENT_KINDS.includes(kind)) {
    return spineFailure(SPINE_CODE.KIND_REFUSED, {
      error: 'event-kind-not-allowed',
      kind: kind ?? null,
      allowed: [...SPINE_EVENT_KINDS],
      kinds_version: ROADMAP_EVENT_KINDS_VERSION,
    });
  }
  return { ok: true, kind, kinds_version: ROADMAP_EVENT_KINDS_VERSION };
}

/**
 * Portfolio index flush requires a minted project_id (RFC-4122). Logical names
 * on fixture roadmaps (`fixture-roadmap-minimal`, `w9-proj`, …) identify the
 * campaign ledger only — they must never reach ingestWrite, which throws
 * INGEST_PROJECT_ID_REQUIRED before any source-of-truth write.
 * @param {{ project_id?: string, skip_index?: boolean }} opts
 */
function shouldFlushPortfolioIndex(opts) {
  if (opts.skip_index === true) return false;
  const id = opts.project_id;
  if (typeof id !== 'string' || id.trim() === '') return false;
  return PROJECT_ID_PATTERN.test(id.trim());
}

/**
 * Absolute path of the campaign ledger file for a project root.
 * @param {string} projectPath
 */
export function roadmapLedgerPath(projectPath) {
  return path.join(path.resolve(projectPath), ROADMAP_FILE_NAME);
}

/**
 * Bounded read of roadmap_events (never returns more than ROADMAP_EVENTS_MAX).
 * Empty-but-valid and unreadable are SEPARATE named states.
 *
 * @param {string} projectPath
 * @param {{ limit?: number, offset?: number }} [opts]
 */
export function readRoadmapEventsBounded(projectPath, opts = {}) {
  const ledgerPath = roadmapLedgerPath(projectPath);
  if (!fs.existsSync(ledgerPath)) {
    return {
      ok: true,
      code: SPINE_CODE.LEDGER_EMPTY,
      status: SPINE_CODE.LEDGER_EMPTY,
      text: SPINE_TEXT[SPINE_CODE.LEDGER_EMPTY],
      message: SPINE_TEXT[SPINE_CODE.LEDGER_EMPTY],
      events: [],
      count: 0,
      bound: ROADMAP_EVENTS_MAX,
      exists: false,
    };
  }
  let raw;
  try {
    raw = fs.readFileSync(ledgerPath, 'utf8');
  } catch (e) {
    return spineFailure(SPINE_CODE.LEDGER_UNREADABLE, {
      error: 'backing-store-unreadable',
      detail: String(e?.message ?? e),
    });
  }
  let roadmap;
  try {
    roadmap = JSON.parse(raw);
  } catch (e) {
    return spineFailure(SPINE_CODE.LEDGER_UNREADABLE, {
      error: 'backing-store-unreadable',
      detail: String(e?.message ?? e),
    });
  }
  if (!roadmap || typeof roadmap !== 'object' || Array.isArray(roadmap)) {
    return spineFailure(SPINE_CODE.STATE_UNKNOWN, {
      error: 'unknown',
    });
  }
  const all = Array.isArray(roadmap.roadmap_events) ? roadmap.roadmap_events : [];
  if (all.length === 0) {
    return {
      ok: true,
      code: SPINE_CODE.LEDGER_EMPTY,
      status: SPINE_CODE.LEDGER_EMPTY,
      text: SPINE_TEXT[SPINE_CODE.LEDGER_EMPTY],
      message: SPINE_TEXT[SPINE_CODE.LEDGER_EMPTY],
      events: [],
      count: 0,
      bound: ROADMAP_EVENTS_MAX,
      exists: true,
      roadmap,
    };
  }
  const offset = Math.max(0, Number(opts.offset) || 0);
  const limit = Math.min(
    ROADMAP_EVENTS_MAX,
    Math.max(0, opts.limit != null ? Number(opts.limit) : ROADMAP_EVENTS_MAX),
  );
  const slice = all.slice(offset, offset + limit);
  return {
    ok: true,
    code: null,
    status: null,
    events: slice,
    count: all.length,
    offset,
    limit,
    bound: ROADMAP_EVENTS_MAX,
    exists: true,
    roadmap,
  };
}

/**
 * Find an existing event by caller-supplied client_event_id (idempotence key).
 * @param {object} roadmap
 * @param {string} clientEventId
 */
export function findEventByClientId(roadmap, clientEventId) {
  if (!clientEventId || typeof clientEventId !== 'string') return null;
  const events = Array.isArray(roadmap?.roadmap_events) ? roadmap.roadmap_events : [];
  return events.find((e) => e && e.client_event_id === clientEventId) ?? null;
}

/**
 * Pure append law used under the lock (and by pure callers via roadmap.mjs).
 * Re-exported for tests that assert the spine owns the production path.
 *
 * @param {object|string|null} roadmapInput
 * @param {object} event
 * @param {{ at?: string }} [opts]
 */
export function appendRoadmapEventSpineLaw(roadmapInput, event, opts = {}) {
  const storeGate = assertStoreDeclared('roadmap_events');
  if (!storeGate.ok) return storeGate;

  if (!event || typeof event !== 'object' || Array.isArray(event)) {
    return spineFailure(SPINE_CODE.STATE_UNKNOWN, {
      error: 'event_not_object',
    });
  }

  const kindGate = assertEventKindAllowed(event.kind);
  if (!kindGate.ok) return kindGate;

  // Seed / parse base
  const base =
    roadmapInput == null || roadmapInput === undefined
      ? emptyRoadmap()
      : roadmapInput;

  // Bound check before pure append (also enforced inside pure path)
  let eventCount = 0;
  if (typeof base === 'string') {
    try {
      const p = JSON.parse(base);
      eventCount = Array.isArray(p?.roadmap_events) ? p.roadmap_events.length : 0;
    } catch {
      eventCount = 0;
    }
  } else if (base && typeof base === 'object') {
    eventCount = Array.isArray(base.roadmap_events) ? base.roadmap_events.length : 0;
  }

  // Idempotence: same client_event_id → no-op, original seq
  if (typeof event.client_event_id === 'string' && event.client_event_id.trim()) {
    const parsed =
      typeof base === 'string'
        ? (() => {
            try {
              return JSON.parse(base);
            } catch {
              return null;
            }
          })()
        : base;
    const prior = findEventByClientId(parsed, event.client_event_id);
    if (prior) {
      if (event.kind === 'refinement_update' && (prior.kind !== event.kind || prior.request_digest !== event.request_digest)) {
        return {ok:false,error:'operation-id-collision',committed:false};
      }
      return {
        ok: true,
        idempotent: true,
        client_event_id: event.client_event_id,
        seq: prior.seq,
        event: prior,
        roadmap: parsed,
        projection: parsed?.roadmap_projection ?? [],
        spine: true,
        single_writer: SPINE_SINGLE_WRITER,
      };
    }
  }

  if (eventCount >= ROADMAP_EVENTS_MAX) {
    return spineFailure(SPINE_CODE.EVENTS_BOUND, {
      error: 'events-bound-exceeded',
      bound: ROADMAP_EVENTS_MAX,
      count: eventCount,
    });
  }

  const result = appendRoadmapEvent(base, event, opts);
  if (!result.ok) {
    // Preserve pure-law error identity (unknown_roadmap_event_kind,
    // status_flip_requires_receipt, …). Stamp spine code only for bound.
    if (result.error === 'events-bound-exceeded') {
      return spineFailure(SPINE_CODE.EVENTS_BOUND, {
        error: 'events-bound-exceeded',
        bound: ROADMAP_EVENTS_MAX,
        count: result.count,
      });
    }
    if (result.error === 'unknown_roadmap_event_kind') {
      return {
        ...result,
        spine: true,
        code: SPINE_CODE.KIND_REFUSED,
        status: SPINE_CODE.KIND_REFUSED,
        text: SPINE_TEXT[SPINE_CODE.KIND_REFUSED],
        allowed: [...SPINE_EVENT_KINDS],
        kinds_version: ROADMAP_EVENT_KINDS_VERSION,
      };
    }
    return { ...result, spine: true };
  }
  return {
    ...result,
    spine: true,
    idempotent: false,
    seq: result.event?.seq ?? null,
    single_writer: SPINE_SINGLE_WRITER,
  };
}

/** Single-writer contract stamped on every spine result. */
export const SPINE_SINGLE_WRITER = Object.freeze({
  writer: 'appendRoadmapEventThroughSpine',
  module: 'engine/ledger-spine.mjs',
  lock: SPINE_LOCK_HELPER,
  atomic_write: SPINE_ATOMIC_WRITE,
  ledger_file: SPINE_LEDGER_FILE,
  whole_file_rewrite: true,
  kinds_version: ROADMAP_EVENT_KINDS_VERSION,
  event_kinds: SPINE_EVENT_KINDS,
  bound: ROADMAP_EVENTS_MAX,
  dual_write_forbidden: true,
});

/**
 * THE production append: load under lock → append → atomic whole-file rewrite.
 *
 * When `opts.project_id` is set and `opts.skip_index` is not true, also writes
 * the inventory-v1 carrier and flushes the portfolio index (closing Wave-3's
 * pre-decided FAIL: appendRoadmapEventDurable gains production callers).
 *
 * @param {string} projectPath
 * @param {object} event
 * @param {{
 *   project_id?: string,
 *   home?: string,
 *   paths?: object,
 *   env?: object,
 *   at?: string,
 *   seed?: object|string|null,
 *   skip_index?: boolean,
 *   timeoutMs?: number,
 *   roadmap_id?: string,
 *   event_id?: string,
 *   beforeFlush?: Function,
 *   appendOpts?: object,
 * }} [opts]
 */
/** The step a close event closes (one not already done), with its goal re-read, else null. */
function closeOf(event, base) {
  let step_id = null, goal_reread = null;
  if (event?.kind === 'status_flip' && event.to === 'done') {
    step_id = event.step_id; goal_reread = event.goal_reread ?? null;
  } else if (event?.kind === 'refinement_update' && event.operation?.action === 'close') {
    step_id = event.operation.step_id; goal_reread = event.operation.goal_reread ?? null;
  } else return null;
  const steps = Array.isArray(base?.roadmap_projection) ? base.roadmap_projection : [];
  const step = steps.find((st) => st && st.id === step_id);
  if (step && step.status === 'done') return null;      // already closed: nothing to demand, no second flip
  return { step_id, goal_reread };
}

export const GOAL_REREAD = Object.freeze(['reaffirmed', 'rewritten']);

/** A steward's close: the strip must name the step that follows with its next and why (within the caps), and the close its goal re-read. */
export function demandClose(root, base, step_id, goal_reread) {
  const closing = closeOf({ kind: 'status_flip', to: 'done', step_id, goal_reread }, base);
  if (!closing) return { ok: true, demanded: false };
  const demand = demandSpineForClose(root, base, step_id);
  if (!demand.ok) return demand;
  if (!GOAL_REREAD.includes(goal_reread)) {
    return {
      ok: false, error: 'goal_reread_required', closing: step_id,
      message: 'Close refused: re-read the North Star and say so - --goal-reread reaffirmed|rewritten '
        + '(or goal_reread on the refinement close operation); the engine records the goal_flip.',
    };
  }
  return { ok: true, demanded: true };
}

/** No strip (legacy) or no open step left after the close: nothing to demand. */
export function demandSpineForClose(root, base, step_id) {
  const stripPath = path.join(root, 'strip.json');
  if (!fs.existsSync(stripPath)) return { ok: true, demanded: false };
  let strip;
  try { strip = JSON.parse(fs.readFileSync(stripPath, 'utf8')); } catch { return { ok: true, demanded: false }; }
  if (!strip || typeof strip !== 'object') return { ok: true, demanded: false };
  const steps = Array.isArray(base?.roadmap_projection) ? base.roadmap_projection : [];
  const open = steps.filter((st) => st && st.id !== step_id && !['done', 'parked'].includes(st.status));
  if (!open.length) return { ok: true, demanded: false, campaign_done: true };
  const pinned = typeof strip.current_step_id === 'string' ? strip.current_step_id.trim() : '';
  const stale = pinned === step_id;
  const missing = [...(pinned && !stale ? [] : ['current_step_id']), ...missingSpine(strip)];
  if (missing.length) {
    return {
      ok: false, error: 'spine_required', closing: step_id, missing,
      message: (stale ? 'current_step_id is still the step being closed. ' : '')
        + 'Close refused: first pin the step that follows and say what comes next - '
        + 'ecgberht update --current-step <id> --next-recommended "<up to 15 words>" --strip-why-next "<up to 20 words>" - then close. '
        + 'A campaign with no open step left needs no next.',
    };
  }
  for (const field of ['next_recommended', 'why_next']) {
    const over = overCap(field, strip[field]);
    if (over) return { ok: false, error: 'over_cap', ...over, closing: step_id, message: `${field} on the strip is ${over.words} words; the cap is ${over.cap}. Say it shorter, then close.` };
  }
  return { ok: true, demanded: true };
}

export function appendRoadmapEventThroughSpine(projectPath, event, opts = {}) {
  const storeGate = assertStoreDeclared('roadmap_events');
  if (!storeGate.ok) return storeGate;

  if (!event || typeof event !== 'object' || Array.isArray(event)) {
    return spineFailure(SPINE_CODE.STATE_UNKNOWN, { error: 'event_not_object' });
  }

  // Kind gate: keep SPINE_KIND_REFUSED + allow-list text, but preserve the pure
  // law's error identity (`unknown_roadmap_event_kind`) so durable callers
  // (appendRoadmapEventDurable / single-writer law) still see the authority
  // refusal they always refused — Wave 6 must not rename pure-law refusals.
  const kindGate = assertEventKindAllowed(event.kind);
  if (!kindGate.ok) {
    return {
      ...kindGate,
      error: 'unknown_roadmap_event_kind',
      event_kinds: [...SPINE_EVENT_KINDS],
    };
  }

  const root = path.resolve(projectPath);
  const ledgerPath = roadmapLedgerPath(root);
  const flushIndex = shouldFlushPortfolioIndex(opts);

  const timeoutMs = opts.timeoutMs ?? LOCK_TIMEOUT_MS;

  let lockedResult;
  try {
    lockedResult = withFileLock(
      ledgerPath,
      () => {
        // LOAD under the lock (whole-file RMW serialisation). Always prefer the
        // on-disk ledger when present so concurrent OS processes serialise
        // correctly; seed is only used to initialise a missing file.
        const loaded = loadProjectRoadmap(root);
        if (!loaded.ok && loaded.exists) {
          return spineFailure(SPINE_CODE.LEDGER_UNREADABLE, {
            error: 'backing-store-unreadable',
            detail: loaded.message ?? loaded.error,
          });
        }
        let base;
        if (loaded.exists) {
          base = loaded.roadmap;
        } else if (opts.seed != null && opts.seed !== undefined) {
          base = opts.seed;
        } else {
          base = emptyRoadmap(opts.project_id ?? null);
        }

        if (event.kind === 'refinement_update') {
          const prior = findEventByClientId(base,event.client_event_id);
          if (!prior) {
            if (event.operation?.expected_seq !== base.roadmap_events.length) return {ok:false,error:'sequence-conflict',expected_seq:event.operation?.expected_seq,actual_seq:base.roadmap_events.length};
            const prepared=prepareRefinementEvent(root,base,event);
            if(!prepared.ok) return prepared;
            event=prepared.event;
          }
        } else if (event.kind === 'status_flip' && event.to === 'done' && foldRefinements(base.roadmap_events).slices?.[event.step_id]) {
          return {ok:false,error:'managed-slice-requires-explicit-close'};
        }
        let law = appendRoadmapEventSpineLaw(base, event, { at: opts.at });
        if (!law.ok) return law;
        // an accepted close that carries its goal re-read gets its goal_flip from the one writer
        const closing = closeOf(event, base);
        let goalFlip = null;
        if (closing && GOAL_REREAD.includes(closing.goal_reread) && !law.idempotent) {
          let face = '';
          try { face = fs.readFileSync(path.join(root, FACE_FILE_NAME), 'utf8'); } catch { face = ''; }
          goalFlip = {
            kind: 'goal_flip', step_id: closing.step_id, verdict: closing.goal_reread,
            goal_revision: northStarRevision(face), scope: closing.step_id,
            receipt: { who: event.receipt?.who ?? event.operation?.human?.who ?? 'steward', why: 'close of ' + closing.step_id },
            ...(opts.at ? { at: opts.at } : {}),
          };
          const flipLaw = appendRoadmapEventSpineLaw(law.roadmap, goalFlip, { at: opts.at });
          if (!flipLaw.ok) return flipLaw;
          law = { ...law, roadmap: flipLaw.roadmap, projection: flipLaw.projection, goal_flip: flipLaw.event };
        }
        if (law.idempotent) {
          const publication=event.kind==='refinement_update' ? publishRefinementProjections(root,law.roadmap) : null;
          if(publication && !publication.ok) return {...publication,committed:true,operation_id:event.client_event_id};
          return {
            ...law,
            projection_status:publication,
            project_path: root,
            roadmap_path: ledgerPath,
            persisted: false,
            sot_written: false,
            locked: true,
          };
        }

        // Persist under the same lock
        fs.mkdirSync(root, { recursive: true });
        writeFileAtomicSync(ledgerPath, projectRoadmapBytes(law.roadmap));
        let publication=null;
        if(event.kind==='refinement_update') {
          try { publication=publishRefinementProjections(root,law.roadmap); }
          catch(e) { return {ok:false,error:'projection-lag',committed:true,operation_id:event.client_event_id,detail:e.message}; }
          if(!publication.ok) return {...publication,committed:true,operation_id:event.client_event_id};
        }

        let carrier = null;
        let carrierRel = null;
        let carrierBytes = null;
        if (flushIndex) {
          carrier = roadmapEventCarrierRecord(law.roadmap, law.event, opts);
          carrierRel = relPathFor(CLASS.ROADMAP_EVENT, carrier.event_id);
          carrierBytes = roadmapEventBytes(carrier);
          const carrierAbs = path.join(root, ...carrierRel.split('/'));
          fs.mkdirSync(path.dirname(carrierAbs), { recursive: true });
          writeFileAtomicSync(carrierAbs, carrierBytes);
        }

        return {
          ok: true,
          projection_status:publication,
          spelling: law.spelling,
          authority: law.authority,
          event: law.event,
          roadmap: law.roadmap,
          projection: law.projection,
          issues: law.issues,
          events_only: true,
          spine: true,
          idempotent: false,
          seq: law.event.seq,
          client_event_id: law.event.client_event_id ?? null,
          project_path: root,
          roadmap_path: ledgerPath,
          persisted: true,
          sot_written: true,
          locked: true,
          single_writer: SPINE_SINGLE_WRITER,
          carrier,
          carrier_rel: carrierRel,
          carrier_bytes: carrierBytes,
          container_bytes: projectRoadmapBytes(law.roadmap),
        };
      },
      {
        timeoutMs,
        onTimeout: (info) => {
          const err = new Error(SPINE_TEXT[SPINE_CODE.LOCK_TIMEOUT]);
          err.code = SPINE_CODE.LOCK_TIMEOUT;
          err.spine_info = info;
          return err;
        },
      },
    );
  } catch (e) {
    if (e && e.code === SPINE_CODE.LOCK_TIMEOUT) {
      return spineFailure(SPINE_CODE.LOCK_TIMEOUT, {
        error: 'lock-contended',
      });
    }
    if (e && e.code === 'ELOCKTIMEOUT') {
      return spineFailure(SPINE_CODE.LOCK_TIMEOUT, {
        error: 'lock-contended',
      });
    }
    return spineFailure(SPINE_CODE.STATE_UNKNOWN, {
      error: 'unknown',
      detail: String(e?.message ?? e),
    });
  }

  if (!lockedResult || !lockedResult.ok) return lockedResult;
  if (lockedResult.idempotent) return lockedResult;

  // Optional portfolio index flush OUTSIDE the roadmap lock (lock-order law:
  // never hold project + portfolio locks together). Carrier bytes were written
  // under the roadmap lock; ingestWrite re-writes the carrier (idempotent
  // atomic replace) and flushes the derived row. Only minted project_ids index.
  if (flushIndex && lockedResult.carrier && lockedResult.carrier_rel) {
    const containerBytes = lockedResult.container_bytes;
    let ingest;
    try {
      ingest = ingestWrite({
        class: CLASS.ROADMAP_EVENT,
        project_id: opts.project_id,
        root,
        rel: lockedResult.carrier_rel,
        bytes: lockedResult.carrier_bytes,
        intent_paths: [pathEntryFor(ROADMAP_FILE_NAME, containerBytes)],
        home: opts.home,
        paths: opts.paths,
        env: opts.env,
        appendOpts: opts.appendOpts,
        beforeFlush: opts.beforeFlush,
        // Carrier already durable under the spine lock; re-assert atomically.
        write: (target) => {
          fs.mkdirSync(path.dirname(target.abs), { recursive: true });
          writeFileAtomicSync(target.abs, target.bytes.toString('utf8'));
        },
      });
    } catch (e) {
      // SoT already stands; never throw past the durable path.
      return {
        ...lockedResult,
        ok: true,
        indexed: false,
        sot_written: true,
        index_error: e?.code ?? 'ingest_threw',
        message:
          `Spine append seq=${lockedResult.seq} durable; index flush refused: ${e?.message ?? e}`,
      };
    }

    return {
      ...lockedResult,
      ok: ingest.ok === true,
      code: ingest.code ?? null,
      status: ingest.status ?? null,
      text: ingest.text ?? '',
      ingest,
      indexed: ingest.ok === true,
      row: ingest.row ?? null,
      seq_indexed: ingest.seq ?? null,
      intent: ingest.intent ?? null,
      intent_seq: ingest.intent_seq ?? null,
      intent_emitted: ingest.intent_emitted === true,
      freshness: ingest.freshness,
      path: ingest.path ?? null,
      trace: ingest.trace ?? [],
      // SoT stands even when index fails
      sot_written: true,
      message:
        ingest.ok === true
          ? `Spine append seq=${lockedResult.seq} durable + indexed.`
          : `Spine append seq=${lockedResult.seq} durable; index flush: ${ingest.text || ingest.code}`,
    };
  }

  return {
    ...lockedResult,
    indexed: false,
    message: `Spine append seq=${lockedResult.seq} durable under ${SPINE_LOCK_HELPER}+${SPINE_ATOMIC_WRITE}.`,
  };
}

/**
 * Persist an already-computed roadmap container under the spine lock.
 * Used only when a pure multi-event fold finished in memory and must land
 * atomically (e.g. E7 multi-step record). Prefer appendRoadmapEventThroughSpine
 * for single-event production appends.
 *
 * @param {string} projectPath
 * @param {object} roadmap
 * @param {{ timeoutMs?: number }} [opts]
 */
export function writeRoadmapThroughSpine(projectPath, roadmap, opts = {}) {
  const storeGate = assertStoreDeclared('roadmap_events');
  if (!storeGate.ok) return storeGate;

  const root = path.resolve(projectPath);
  const ledgerPath = roadmapLedgerPath(root);

  try {
    withFileLock(
      ledgerPath,
      () => {
        const current=loadProjectRoadmap(root);
        if ((roadmap.roadmap_events || []).some(e=>e.kind==='refinement_update') ||
            (current.roadmap?.roadmap_events || []).some(e=>e.kind==='refinement_update')) {
          const error=new Error('Managed roadmap replacement requires the refinement append operation');
          error.code='managed-write-refused'; throw error;
        }
        fs.mkdirSync(root, { recursive: true });
        writeFileAtomicSync(ledgerPath, projectRoadmapBytes(roadmap));
      },
      {
        timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS,
        onTimeout: (info) => {
          const err = new Error(SPINE_TEXT[SPINE_CODE.LOCK_TIMEOUT]);
          err.code = SPINE_CODE.LOCK_TIMEOUT;
          err.spine_info = info;
          return err;
        },
      },
    );
  } catch (e) {
    if(e?.code==='managed-write-refused') return {ok:false,error:e.code};
    if (e && (e.code === SPINE_CODE.LOCK_TIMEOUT || e.code === 'ELOCKTIMEOUT')) {
      return spineFailure(SPINE_CODE.LOCK_TIMEOUT, { error: 'lock-contended' });
    }
    return spineFailure(SPINE_CODE.STATE_UNKNOWN, {
      error: 'unknown',
      detail: String(e?.message ?? e),
    });
  }

  return {
    ok: true,
    roadmap_path: ledgerPath,
    project_path: root,
    spine: true,
    single_writer: SPINE_SINGLE_WRITER,
    sot_written: true,
  };
}

/**
 * Supported managed repair. No caller-supplied replacement or event mutation:
 * reload and derive both cached projections under the existing writer lock.
 * Normal appends and container replacements retain their drift/refusal guards.
 */
export function repairRoadmapProjectionsThroughSpine(projectPath, opts = {}) {
  const storeGate=assertStoreDeclared('roadmap_events');
  if(!storeGate.ok) return storeGate;
  const root=path.resolve(projectPath),ledgerPath=roadmapLedgerPath(root);
  let repair;
  try {
    return withFileLock(ledgerPath,()=>{
      const loaded=loadProjectRoadmap(root);
      if(!loaded.ok || !loaded.exists) return {ok:false,error:'backing-store-unreadable'};
      const base=loaded.roadmap,state=foldRefinements(base.roadmap_events);
      if(!state.managed) return {ok:false,error:'unmanaged-campaign'};
      const healed=healRoadmap(base);
      if(!healed.ok) return healed;
      const roadmap={...healed.roadmap,refinement_projection:state};
      const valid=refinementRoadmapStatus(roadmap);
      if(!valid.consistent) return {ok:false,error:valid.error,issues:valid.issues,invalid_issues:valid.invalid_issues};
      // Authenticate every document before any repair write. An external edit
      // is a conflict, even when a cached roadmap projection also needs repair.
      const documents=refinementProjectionStatus(root,base);
      if(documents.error) return {ok:false,...documents};
      const changed=['roadmap_projection','refinement_projection'].filter(
        field=>JSON.stringify(base[field])!==JSON.stringify(roadmap[field]));
      repair={repaired_fields:[],
        events_rewritten:false,locked:true,persisted:false,updated_documents:[]};
      if(changed.length) {
        writeFileAtomicSync(ledgerPath,projectRoadmapBytes(roadmap));
        repair.persisted=true;
        repair.repaired_fields=changed;
      }
      const publication=publishRefinementProjections(root,roadmap);
      repair.updated_documents=publication.updated_documents || [];
      repair.finished=publication.finished || null;
      const saved=loadProjectRoadmap(root);
      if(!saved.ok || !saved.exists) return {ok:false,error:'backing-store-unreadable',repair};
      const view=refinementResult(root,saved.roadmap);
      return {...view,ok:publication.ok && publication.consistent && view.consistent,repair,
        ...(!publication.ok || !publication.consistent || !view.consistent ? {
          error:publication.error || publication.finished?.error || 'projection-lag',
          detail:publication.detail || publication.finished?.detail,
        } : {})};
    },{timeoutMs:opts.timeoutMs ?? LOCK_TIMEOUT_MS});
  } catch(e) {
    if(e?.code==='ELOCKTIMEOUT') return spineFailure(SPINE_CODE.LOCK_TIMEOUT,{error:'lock-contended'});
    return {ok:false,error:e.code || 'projection-repair-failed',detail:e.message,...(repair ? {repair} : {})};
  }
}

/**
 * Persist strip.json under a named lock (S2 companion path when portfolio
 * index is not in play). Production strip instruments/receipts prefer
 * write-authority durable paths when project_id is available.
 *
 * @param {string} projectPath
 * @param {object} strip
 * @param {{ timeoutMs?: number, fileName?: string }} [opts]
 */
export function writeStripThroughSpine(projectPath, strip, opts = {}) {
  const storeGate = assertStoreDeclared('strip_instruments');
  if (!storeGate.ok) return storeGate;

  const root = path.resolve(projectPath);
  const fileName = opts.fileName ?? 'strip.json';
  const stripPath = path.join(root, fileName);

  try {
    withFileLock(
      stripPath,
      () => {
        fs.mkdirSync(root, { recursive: true });
        writeFileAtomicSync(stripPath, `${JSON.stringify(strip, null, 2)}\n`);
      },
      {
        timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS,
        onTimeout: (info) => {
          const err = new Error(SPINE_TEXT[SPINE_CODE.LOCK_TIMEOUT]);
          err.code = SPINE_CODE.LOCK_TIMEOUT;
          err.spine_info = info;
          return err;
        },
      },
    );
  } catch (e) {
    if (e && (e.code === SPINE_CODE.LOCK_TIMEOUT || e.code === 'ELOCKTIMEOUT')) {
      return spineFailure(SPINE_CODE.LOCK_TIMEOUT, { error: 'lock-contended' });
    }
    return spineFailure(SPINE_CODE.STATE_UNKNOWN, {
      error: 'unknown',
      detail: String(e?.message ?? e),
    });
  }

  return {
    ok: true,
    strip_path: stripPath,
    project_path: root,
    spine: true,
    sot_written: true,
  };
}

/**
 * Source-removal proof: spine module text must still name the durable helpers.
 * @param {string} sourceText
 */
export function assertSpineDurableHelpersPresent(sourceText) {
  const missing = [];
  if (!sourceText.includes('writeFileAtomicSync')) missing.push('writeFileAtomicSync');
  if (!sourceText.includes('withFileLock')) missing.push('withFileLock');
  if (!sourceText.includes('appendRoadmapEventThroughSpine')) {
    missing.push('appendRoadmapEventThroughSpine');
  }
  return { ok: missing.length === 0, missing };
}

/**
 * Allow-list kinds must match the roadmap module's admitted set (current version).
 * scaffold_proposal (v1) + face_* (v2 / Wave 10) + elaboration_* (v3 / Wave 12)
 * + reflection_receipt / next_stage_proposal (v4 / Wave 14) are on both.
 */
export function assertKindsAligned() {
  const fromRoadmap = new Set(ROADMAP_KINDS_FROM_MODULE);
  const fromSpine = new Set(SPINE_EVENT_KINDS);
  const missingInRoadmap = SPINE_EVENT_KINDS.filter((k) => !fromRoadmap.has(k));
  const missingInSpine = ROADMAP_KINDS_FROM_MODULE.filter((k) => !fromSpine.has(k));
  return {
    ok: missingInRoadmap.length === 0 && missingInSpine.length === 0,
    missingInRoadmap,
    missingInSpine,
    version: ROADMAP_EVENT_KINDS_VERSION,
  };
}

export { roadmapIdFor };

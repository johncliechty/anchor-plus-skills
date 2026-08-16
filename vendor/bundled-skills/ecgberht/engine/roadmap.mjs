/**
 * TW1 — Campaign Roadmap: append-only roadmap_events[] + derived roadmap_projection.
 *
 * The Roadmap is engine truth. Face prose is never the only step list: when a
 * project has only prose, the projection is EMPTY with an honest gap — steps
 * are never invented from narrative.
 *
 * SINGLE WRITER PATH (TW3 hook — do not dual-write):
 * - The only writer is appendRoadmapEvent (via roadmap-propose / roadmap-set).
 * - roadmap_projection is derived-only: rebuilt from the full event list on
 *   every append; direct projection writes are rejected
 *   (mutateRoadmapProjectionInPlace always refuses).
 * - TW3 job lifecycle (commission propose/confirm, queued→running→done|failed|
 *   orphaned|reaped) must bind through this same writer: commission_bind to
 *   attach a step to a commissioned job, status_flip (receipt required) for
 *   step status changes. No second store, no UI-only state, no direct
 *   projection writes. See ROADMAP_SINGLE_WRITER.tw3_hook.
 *
 * Silent-rewrite law (mirrors Strip heal law):
 * - status flip without a receipt → refuse write (append) / reject (rebuild).
 * - stored projection that disagrees with the event fold → reject
 *   (roadmap_silent_rewrite); heal = rebuild projection from events.
 * - roadmap_events history is never rewritten — heal touches projection only.
 */

import fs from 'node:fs';
import { writeFileAtomicSync, withFileLock } from './durable-write.mjs';
import path from 'node:path';

import { SPELLING } from './verbs.mjs';
import { resolveProjectPath, loadProjectSurfaces } from './face-strip.mjs';
// Wave 6 spine — circular with ledger-spine (it imports pure law from here).
// Safe: both sides only call the other's exports from function bodies.
import { appendRoadmapEventThroughSpine } from './ledger-spine.mjs';

export const ROADMAP_FILE_NAME = 'roadmap.json';
export const ROADMAP_SCHEMA_ID = 'ecgberht-roadmap-v0';

/**
 * Append-only event kinds (versioned allow-list — Wave 6 / Master-Plan P2).
 * New kinds (reflection_receipt, next_stage_proposal, attention_*) require an
 * explicit allow-list VERSION BUMP in ledger-spine.mjs + a test. A chat-turn
 * kind is structurally impossible.
 *
 * Wave 10 (v2): face_assert / face_retract / face_refine / face_compile —
 * Face compile projection (Master-Plan P4). Project-level events (no step fold).
 * Wave 12 (v3): elaboration_probe / elaboration_answer / elaboration_decline /
 * elaboration_offer_refused — progressive elaboration at stage START (joined to
 * a step via step_id; no projection fold — detail reconstructed from events).
 * Wave 14 (v4): reflection_receipt / next_stage_proposal — gate decision 4
 * zero-model emit at validated handback (project-level; no step fold).
 * Wave 16 (v5): attention_projection_published — altitude contract (project-level).
 */
export const ROADMAP_EVENT_KINDS = Object.freeze([
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
]);

/** Project-level kinds that do not fold into roadmap_projection steps. */
export const ROADMAP_PROJECT_LEVEL_KINDS = Object.freeze([
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
]);

/** Named bound — appends beyond this refuse with events-bound-exceeded. */
export const ROADMAP_EVENTS_MAX = 50_000;

/** Step statuses in the derived projection. */
export const ROADMAP_STEP_STATUSES = Object.freeze([
  'proposed',
  'planned',
  'active',
  'waiting',
  'done',
  'parked',
]);

/** Derived projection fields per step. */
export const ROADMAP_PROJECTION_FIELDS = Object.freeze([
  'id',
  'name',
  'status',
  'done_when',
  'waiting_on',
  'commissioned_as',
]);

/**
 * Fields step_set may change. status requires status_flip (+ receipt);
 * commissioned_as requires commission_bind (TW3 single-writer hook).
 */
export const ROADMAP_SET_FIELDS = Object.freeze([
  'name',
  'done_when',
  'waiting_on',
]);

/** Receipt fields a status_flip event must carry (when defaults to event.at). */
export const FLIP_RECEIPT_FIELDS = Object.freeze(['who', 'why']);

/**
 * Single-writer contract, exported for later waves and docs.
 * Wave 6: production persist is the ledger spine (locked durable path);
 * pure appendRoadmapEvent remains the in-memory law the spine applies under lock.
 */
export const ROADMAP_SINGLE_WRITER = Object.freeze({
  writer: 'appendRoadmapEventThroughSpine',
  pure_law: 'appendRoadmapEvent',
  durable: 'appendRoadmapEventDurable',
  module: 'engine/ledger-spine.mjs',
  verbs: Object.freeze(['roadmap-propose', 'roadmap-set']),
  projection: 'derived_only',
  dual_write_forbidden: true,
  tw3_hook: Object.freeze({
    wave: 'TW3',
    contract:
      'Job lifecycle (commission propose/confirm; queued→running→done|failed|orphaned|reaped) must append Roadmap events via the spine (appendRoadmapEvent law under lock): commission_bind to bind a step to a commissioned job, status_flip (with receipt) for step status changes. No second store, no direct roadmap_projection writes, no UI-only state.',
    event_kinds: Object.freeze(['commission_bind', 'status_flip']),
  }),
});

/** ISO date (YYYY-MM-DD) for event stamps. */
function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function nonEmpty(v) {
  return typeof v === 'string' && v.trim() !== '';
}

/**
 * Normalize / validate a roadmap container (object or JSON string).
 * @param {object|string|null} input
 * @returns {{ ok: true, roadmap: object } | { ok: false, error: string, message?: string }}
 */
export function parseRoadmap(input) {
  let roadmap = input;
  if (typeof input === 'string') {
    try {
      roadmap = JSON.parse(input);
    } catch (e) {
      return { ok: false, error: 'roadmap_json_parse', message: String(e?.message ?? e) };
    }
  }
  if (!roadmap || typeof roadmap !== 'object' || Array.isArray(roadmap)) {
    return { ok: false, error: 'roadmap_not_object' };
  }
  const out = { ...roadmap };
  if (!out.schema) out.schema = ROADMAP_SCHEMA_ID;
  out.roadmap_events = Array.isArray(out.roadmap_events)
    ? out.roadmap_events.map((e) => ({ ...e }))
    : [];
  out.roadmap_projection = Array.isArray(out.roadmap_projection)
    ? out.roadmap_projection.map((s) => ({ ...s }))
    : [];
  return { ok: true, roadmap: out };
}

/** Empty roadmap container for a project without one yet. */
export function emptyRoadmap(project_id = null) {
  return {
    schema: ROADMAP_SCHEMA_ID,
    project_id: project_id ?? null,
    as_of: null,
    roadmap_events: [],
    roadmap_projection: [],
  };
}

/**
 * Normalize a projection step to the locked field set (stable order).
 * @param {object} step
 */
export function normalizeProjectionStep(step = {}) {
  return {
    id: step.id ?? null,
    name: step.name ?? null,
    status: step.status ?? null,
    done_when: step.done_when ?? null,
    waiting_on: step.waiting_on ?? null,
    commissioned_as: step.commissioned_as ?? null,
  };
}

/**
 * Fold the append-only event list into the derived projection.
 * A status_flip without a valid receipt is NOT applied (issue recorded) —
 * silent flips cannot enter the step list even from a hand-authored file.
 * @param {object[]} events
 * @returns {{ ok: true, projection: object[], issues: object[], clean: boolean }}
 */
export function buildRoadmapProjection(events = []) {
  const list = Array.isArray(events) ? events : [];
  const steps = new Map();
  const issues = [];

  list.forEach((ev, idx) => {
    if (!ev || typeof ev !== 'object') {
      issues.push({ code: 'event_not_object', at_index: idx });
      return;
    }
    if (typeof ev.seq === 'number' && ev.seq !== idx + 1) {
      issues.push({
        code: 'event_seq_break',
        at_index: idx,
        seq: ev.seq,
        expected: idx + 1,
        message: 'roadmap_events must be contiguous append-only history',
      });
    }
    const kind = ev.kind;
    const id = ev.step_id ?? ev.id ?? null;

    if (kind === 'step_create') {
      if (!nonEmpty(id) || !nonEmpty(ev.name)) {
        issues.push({ code: 'step_create_missing_fields', at_index: idx, step_id: id });
        return;
      }
      if (steps.has(id)) {
        issues.push({ code: 'duplicate_step_create', at_index: idx, step_id: id });
        return;
      }
      const status = ROADMAP_STEP_STATUSES.includes(ev.status) ? ev.status : 'planned';
      steps.set(id, {
        id,
        name: ev.name,
        status,
        done_when: ev.done_when ?? null,
        waiting_on: ev.waiting_on ?? null,
        commissioned_as: null,
      });
      return;
    }

    if (kind === 'step_set') {
      const step = steps.get(id);
      if (!step) {
        issues.push({ code: 'step_set_unknown_step', at_index: idx, step_id: id });
        return;
      }
      const fields =
        ev.fields && typeof ev.fields === 'object' ? ev.fields : {};
      for (const key of Object.keys(fields)) {
        if (!ROADMAP_SET_FIELDS.includes(key)) {
          issues.push({
            code: 'step_set_forbidden_field',
            at_index: idx,
            step_id: id,
            field: key,
            message:
              'status requires status_flip (+ receipt); commissioned_as requires commission_bind',
          });
          continue;
        }
        step[key] = fields[key];
      }
      return;
    }

    if (kind === 'status_flip') {
      const step = steps.get(id);
      if (!step) {
        issues.push({ code: 'status_flip_unknown_step', at_index: idx, step_id: id });
        return;
      }
      if (!isValidFlipReceipt(ev.receipt)) {
        issues.push({
          code: 'status_flip_missing_receipt',
          at_index: idx,
          step_id: id,
          message: 'status flip without receipt is rejected (not applied)',
        });
        return;
      }
      if (!ROADMAP_STEP_STATUSES.includes(ev.to)) {
        issues.push({ code: 'status_flip_invalid_to', at_index: idx, step_id: id, to: ev.to ?? null });
        return;
      }
      if (ev.from != null && ev.from !== step.status) {
        issues.push({
          code: 'status_flip_from_mismatch',
          at_index: idx,
          step_id: id,
          from: ev.from,
          current: step.status,
        });
        return;
      }
      step.status = ev.to;
      return;
    }

    if (kind === 'commission_bind') {
      const step = steps.get(id);
      if (!step) {
        issues.push({ code: 'commission_bind_unknown_step', at_index: idx, step_id: id });
        return;
      }
      if (!nonEmpty(ev.commissioned_as)) {
        issues.push({ code: 'commission_bind_missing_target', at_index: idx, step_id: id });
        return;
      }
      step.commissioned_as = ev.commissioned_as;
      return;
    }

    // Project-level kinds (scaffold_proposal, face_*, elaboration_*): ledger
    // history only — no roadmap_projection fold. Detail is reconstructed by
    // the owning surface (Face compile / progressive elaboration).
    if (ROADMAP_PROJECT_LEVEL_KINDS.includes(kind)) {
      return;
    }

    issues.push({ code: 'unknown_event_kind', at_index: idx, kind: kind ?? null });
  });

  return {
    ok: true,
    projection: [...steps.values()].map(normalizeProjectionStep),
    issues,
    clean: issues.length === 0,
  };
}

/**
 * @param {*} receipt
 */
export function isValidFlipReceipt(receipt) {
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)) return false;
  return FLIP_RECEIPT_FIELDS.every((k) => nonEmpty(receipt[k]));
}

function projectionsEqual(a, b) {
  const na = (Array.isArray(a) ? a : []).map(normalizeProjectionStep);
  const nb = (Array.isArray(b) ? b : []).map(normalizeProjectionStep);
  return JSON.stringify(na) === JSON.stringify(nb);
}

/**
 * Validate a roadmap: rebuild projection from events and compare with stored.
 * A stored projection that disagrees with the event fold is a silent rewrite
 * (e.g. a status flip with no receipt event) → reject.
 *
 * Read-path allowance (`allow_unevented_steps`): a stored step whose id no
 * event ever mentions rewrites no receipted history — the event fold stays
 * authoritative for every evented step, and the stored-only steps ride along
 * flagged (never silently dropped from the rail). Any drift on an evented
 * step (field_drift / step_missing_from_stored / reorder) still rejects.
 * Writers never pass the flag — appends onto a drifted roadmap heal first.
 * @param {object|string} input
 * @param {{ allow_unevented_steps?: boolean }} [opts]
 * @returns {object}
 */
export function validateRoadmap(input, opts = {}) {
  const parsed = parseRoadmap(input);
  if (!parsed.ok) return parsed;
  const roadmap = parsed.roadmap;

  const built = buildRoadmapProjection(roadmap.roadmap_events);
  const stored = roadmap.roadmap_projection;

  if (stored.length > 0 && !projectionsEqual(stored, built.projection)) {
    const drift = diffProjections(stored, built.projection);
    const onlyUnevented =
      drift.length > 0 && drift.every((d) => d.kind === 'step_without_events');

    if (!(onlyUnevented && opts.allow_unevented_steps === true)) {
      return {
        ok: false,
        error: 'roadmap_silent_rewrite',
        spelling: SPELLING,
        message:
          'Stored roadmap_projection disagrees with the append-only event fold (e.g. a status flip without a receipt event). Write refused; heal rebuilds the projection from events.',
        drift,
        projection_from_events: built.projection,
        stored_projection: stored,
        issues: built.issues,
        heal: 'healRoadmap',
        single_writer: ROADMAP_SINGLE_WRITER,
      };
    }

    const evented = new Set(built.projection.map((s) => s.id));
    const extra = stored
      .map(normalizeProjectionStep)
      .filter((s) => !evented.has(s.id));
    const projection = [...built.projection, ...extra];
    return {
      ok: true,
      spelling: SPELLING,
      projection,
      issues: [...built.issues, ...drift],
      clean: false,
      unevented_steps: extra.map((s) => s.id),
      events_count: roadmap.roadmap_events.length,
      steps_count: projection.length,
    };
  }

  return {
    ok: true,
    spelling: SPELLING,
    projection: built.projection,
    issues: built.issues,
    clean: built.clean,
    events_count: roadmap.roadmap_events.length,
    steps_count: built.projection.length,
  };
}

function diffProjections(stored, rebuilt) {
  const drift = [];
  const byId = new Map(rebuilt.map((s) => [s.id, s]));
  for (const raw of stored) {
    const s = normalizeProjectionStep(raw);
    const truth = byId.get(s.id);
    if (!truth) {
      drift.push({ step_id: s.id, kind: 'step_without_events' });
      continue;
    }
    for (const field of ROADMAP_PROJECTION_FIELDS) {
      if (JSON.stringify(s[field]) !== JSON.stringify(truth[field])) {
        drift.push({
          step_id: s.id,
          kind: 'field_drift',
          field,
          stored: s[field],
          from_events: truth[field],
        });
      }
    }
  }
  for (const truth of rebuilt) {
    if (!stored.some((s) => normalizeProjectionStep(s).id === truth.id)) {
      drift.push({ step_id: truth.id, kind: 'step_missing_from_stored' });
    }
  }
  return drift;
}

/**
 * Heal: rebuild roadmap_projection from roadmap_events.
 * Events are never rewritten — projection is derived-only.
 * @param {object|string} input
 */
export function healRoadmap(input) {
  const parsed = parseRoadmap(input);
  if (!parsed.ok) return parsed;
  const roadmap = parsed.roadmap;

  const priorEvents = roadmap.roadmap_events.map((e) => ({ ...e }));
  const built = buildRoadmapProjection(roadmap.roadmap_events);

  const healed = {
    ...roadmap,
    roadmap_events: priorEvents,
    roadmap_projection: built.projection,
  };

  return {
    ok: true,
    spelling: SPELLING,
    healed: true,
    roadmap: healed,
    projection: built.projection,
    issues: built.issues,
    events_rewritten: false,
    message:
      'roadmap_projection rebuilt from append-only roadmap_events; event history untouched',
  };
}

/**
 * Append a roadmap event — THE single writer path.
 * Refuses: unknown kinds, status_flip without receipt, step_set on
 * status/commissioned_as, unknown/duplicate steps, and appends onto a
 * roadmap whose stored projection already drifted (heal first).
 * Never mutates the input roadmap; projection is rebuilt from the full list.
 * @param {object|string} roadmapInput
 * @param {object} event
 * @param {{ at?: string }} [opts]
 */
export function appendRoadmapEvent(roadmapInput, event, opts = {}) {
  const parsed = parseRoadmap(roadmapInput ?? emptyRoadmap());
  if (!parsed.ok) return parsed;
  const roadmap = parsed.roadmap;

  if (!event || typeof event !== 'object' || Array.isArray(event)) {
    return { ok: false, error: 'event_not_object', spelling: SPELLING };
  }
  const kind = event.kind;
  if (!ROADMAP_EVENT_KINDS.includes(kind)) {
    return {
      ok: false,
      error: 'unknown_roadmap_event_kind',
      spelling: SPELLING,
      kind: kind ?? null,
      event_kinds: [...ROADMAP_EVENT_KINDS],
    };
  }

  // T-IDEM-06: caller-supplied client_event_id — re-append is a no-op, original seq.
  if (typeof event.client_event_id === 'string' && event.client_event_id.trim()) {
    const prior = roadmap.roadmap_events.find(
      (e) => e && e.client_event_id === event.client_event_id,
    );
    if (prior) {
      return {
        ok: true,
        spelling: SPELLING,
        authority: 'roadmap_append_only',
        idempotent: true,
        client_event_id: event.client_event_id,
        seq: prior.seq,
        event: prior,
        roadmap,
        projection: roadmap.roadmap_projection,
        events_only: true,
        single_writer: ROADMAP_SINGLE_WRITER,
      };
    }
  }

  // T-BND-06: refuse past the named bound — never truncate.
  if (roadmap.roadmap_events.length >= ROADMAP_EVENTS_MAX) {
    return {
      ok: false,
      error: 'events-bound-exceeded',
      spelling: SPELLING,
      bound: ROADMAP_EVENTS_MAX,
      count: roadmap.roadmap_events.length,
      message:
        'Ledger at its 50000-event bound — append refused by name, never truncated.',
    };
  }

  // Guard: a drifted stored projection means someone rewrote silently — refuse
  // the write until an explicit heal rebuilds from events.
  const validated = validateRoadmap(roadmap);
  if (!validated.ok) {
    return {
      ...validated,
      refused_write: true,
      message: `${validated.message} Append refused until heal.`,
    };
  }

  const current = new Map(
    validated.projection.map((s) => [s.id, s]),
  );
  const step_id = event.step_id ?? event.id ?? null;

  if (ROADMAP_PROJECT_LEVEL_KINDS.includes(kind)) {
    // Project-level events (Wave 9 scaffold_proposal; Wave 10 face_*;
    // Wave 12 elaboration_*). No step mutation — admitted so authoring /
    // Face compile / progressive elaboration cannot invent a parallel sink
    // outside the versioned allow-list. elaboration_* join a step via step_id
    // in the event body; reconstructStepDetail folds answers.
  } else if (kind === 'step_create') {
    if (!nonEmpty(step_id) || !nonEmpty(event.name)) {
      return {
        ok: false,
        error: 'step_create_missing_fields',
        spelling: SPELLING,
        required: ['step_id', 'name'],
      };
    }
    if (current.has(step_id)) {
      return { ok: false, error: 'duplicate_step_id', spelling: SPELLING, step_id };
    }
    if (event.status != null && !ROADMAP_STEP_STATUSES.includes(event.status)) {
      return {
        ok: false,
        error: 'invalid_step_status',
        spelling: SPELLING,
        status: event.status,
        statuses: [...ROADMAP_STEP_STATUSES],
      };
    }
  } else {
    if (!nonEmpty(step_id) || !current.has(step_id)) {
      return { ok: false, error: 'unknown_step', spelling: SPELLING, step_id: step_id ?? null };
    }
  }

  if (kind === 'status_flip') {
    if (!isValidFlipReceipt(event.receipt)) {
      return {
        ok: false,
        error: 'status_flip_requires_receipt',
        spelling: SPELLING,
        step_id,
        required: [...FLIP_RECEIPT_FIELDS],
        message:
          'Status flip without a receipt event is refused. Provide receipt { who, why } (when defaults to the event date).',
        single_writer: ROADMAP_SINGLE_WRITER,
      };
    }
    if (!ROADMAP_STEP_STATUSES.includes(event.to)) {
      return {
        ok: false,
        error: 'invalid_step_status',
        spelling: SPELLING,
        status: event.to ?? null,
        statuses: [...ROADMAP_STEP_STATUSES],
      };
    }
    const cur = current.get(step_id);
    if (event.from != null && event.from !== cur.status) {
      return {
        ok: false,
        error: 'status_flip_from_mismatch',
        spelling: SPELLING,
        step_id,
        from: event.from,
        current: cur.status,
      };
    }
  }

  if (kind === 'step_set') {
    const fields =
      event.fields && typeof event.fields === 'object' ? event.fields : {};
    const forbidden = Object.keys(fields).filter(
      (k) => !ROADMAP_SET_FIELDS.includes(k),
    );
    if (!Object.keys(fields).length) {
      return {
        ok: false,
        error: 'step_set_requires_fields',
        spelling: SPELLING,
        allowed: [...ROADMAP_SET_FIELDS],
      };
    }
    if (forbidden.length) {
      return {
        ok: false,
        error: 'step_set_forbidden_field',
        spelling: SPELLING,
        forbidden,
        allowed: [...ROADMAP_SET_FIELDS],
        message:
          'status requires status_flip (+ receipt); commissioned_as requires commission_bind (TW3 single-writer hook)',
      };
    }
  }

  if (kind === 'commission_bind' && !nonEmpty(event.commissioned_as)) {
    return {
      ok: false,
      error: 'commission_bind_missing_target',
      spelling: SPELLING,
      step_id,
    };
  }

  const at = event.at ?? opts.at ?? todayIso();
  const normalized = {
    ...event,
    seq: roadmap.roadmap_events.length + 1,
    kind,
    step_id: kind === 'scaffold_proposal' ? (step_id ?? null) : step_id,
    at,
  };
  if (typeof event.client_event_id === 'string' && event.client_event_id.trim()) {
    normalized.client_event_id = event.client_event_id;
  }
  if (kind === 'status_flip') {
    normalized.from = event.from ?? current.get(step_id).status;
    normalized.receipt = {
      who: event.receipt.who,
      when: event.receipt.when ?? at,
      why: event.receipt.why,
    };
  }
  delete normalized.id;

  const events = [...roadmap.roadmap_events.map((e) => ({ ...e })), normalized];
  const built = buildRoadmapProjection(events);

  return {
    ok: true,
    spelling: SPELLING,
    authority: 'roadmap_append_only',
    event: normalized,
    seq: normalized.seq,
    idempotent: false,
    roadmap: {
      ...roadmap,
      as_of: at,
      roadmap_events: events,
      roadmap_projection: built.projection,
    },
    projection: built.projection,
    issues: built.issues,
    events_only: true,
    single_writer: ROADMAP_SINGLE_WRITER,
  };
}

/**
 * Direct roadmap_projection writes are ALWAYS rejected (single writer path).
 * @param {object} roadmap
 * @param {object} [patch]
 */
export function mutateRoadmapProjectionInPlace(roadmap, patch = {}) {
  return {
    ok: false,
    error: 'roadmap_projection_write_rejected',
    spelling: SPELLING,
    message:
      'roadmap_projection is derived from append-only roadmap_events; direct writes are rejected. Use roadmap-propose / roadmap-set → appendRoadmapEvent (single writer), or healRoadmap to rebuild from events.',
    attempted_fields: Object.keys(patch || {}),
    single_writer: ROADMAP_SINGLE_WRITER,
    roadmap_unchanged: true,
  };
}

/**
 * Load a project's roadmap.json (N=1 path; no registry).
 * @param {string} projectPath
 */
export function loadProjectRoadmap(projectPath) {
  const root = path.resolve(projectPath);
  const roadmapPath = path.join(root, ROADMAP_FILE_NAME);
  if (!fs.existsSync(roadmapPath) || !fs.statSync(roadmapPath).isFile()) {
    return { ok: true, exists: false, roadmap: null, roadmap_path: roadmapPath };
  }
  try {
    const raw = fs.readFileSync(roadmapPath, 'utf8');
    const parsed = parseRoadmap(raw);
    if (!parsed.ok) {
      return { ok: false, exists: true, roadmap: null, roadmap_path: roadmapPath, ...parsed };
    }
    return { ok: true, exists: true, roadmap: parsed.roadmap, roadmap_path: roadmapPath };
  } catch (e) {
    return {
      ok: false,
      exists: true,
      roadmap: null,
      roadmap_path: roadmapPath,
      error: 'roadmap_read_failed',
      message: String(e?.message ?? e),
    };
  }
}

/**
 * The container's bytes, in ONE place.
 *
 * W15 needs these bytes twice - once to write the file and once to hash it into the
 * commit-intent that asks for it to be committed - and two spellings of the same
 * serialization is how a durability receipt ends up naming a hash the file on disk does not
 * have. So the writer below calls this, and so does the intent.
 *
 * @param {object} roadmap @returns {string}
 */
export function projectRoadmapBytes(roadmap) {
  return `${JSON.stringify(roadmap, null, 2)}\n`;
}

/**
 * Persist a roadmap container to the project root.
 *
 * Wave 6: whole-file rewrite is serialised under the SAME named lock as the
 * spine (`withFileLock` + `writeFileAtomicSync`). Production appends still go
 * through `appendRoadmapEventThroughSpine` / `appendRoadmapEventDurable`; this
 * helper is the fixture/heal container path — never an unlocked second writer.
 *
 * @param {string} projectPath
 * @param {object} roadmap
 * @param {{ timeoutMs?: number }} [opts]
 */
export function writeProjectRoadmap(projectPath, roadmap, opts = {}) {
  const root = path.resolve(projectPath);
  const roadmapPath = path.join(root, ROADMAP_FILE_NAME);
  fs.mkdirSync(root, { recursive: true });
  withFileLock(
    roadmapPath,
    () => {
      writeFileAtomicSync(roadmapPath, projectRoadmapBytes(roadmap));
    },
    { timeoutMs: opts.timeoutMs },
  );
  return {
    ok: true,
    roadmap_path: roadmapPath,
    locked: true,
    lock: 'withFileLock',
    atomic_write: 'writeFileAtomicSync',
  };
}

// -- W9: the durable, indexed half of the single writer -----------------------

/**
 * The id used when a roadmap container names neither a roadmap nor a project. Named rather
 * than inlined so the carrier path is predictable in the one case where nothing else is.
 */
export const ROADMAP_DEFAULT_ID = 'roadmap';

/**
 * The roadmap a carrier file belongs to.
 *
 * @param {object} roadmap @param {{roadmap_id?: string}} [opts] @returns {string}
 */
export function roadmapIdFor(roadmap, opts = {}) {
  const id = opts.roadmap_id ?? roadmap?.roadmap_id ?? roadmap?.project_id ?? null;
  return nonEmpty(id) ? String(id) : ROADMAP_DEFAULT_ID;
}

/**
 * The inventory-v1 roadmap-event record for one appended event.
 *
 * WHY A MAPPING EXISTS AT ALL. The engine's roadmap event and the index's roadmap-event
 * class are two vocabularies that happen to describe the same fact: the engine speaks
 * {kind, step_id, at, receipt}, and inventory-v1 plus the frozen `proj` field set ask for
 * {event_id, roadmap_id, kind, title, step_status}. This function is the ONE place they are
 * lined up, so the carrier a rebuild discovers and the row the write path emitted describe
 * the same event in the same words. It invents no authority: appendRoadmapEvent has already
 * decided what the event IS and what the projection became, and every value here is read
 * back out of that decision.
 *
 * `title` and `step_status` come from the PROJECTION rather than from the raw event, because
 * the projection is the fold the single writer already computed - reading the status off the
 * event would re-derive it, and a second derivation is a second answer.
 *
 * @param {object} roadmap the container AFTER the append
 * @param {object} event the normalized event appendRoadmapEvent produced
 * @param {{roadmap_id?: string, event_id?: string}} [opts]
 * @returns {object}
 */
export function roadmapEventCarrierRecord(roadmap, event, opts = {}) {
  const roadmap_id = roadmapIdFor(roadmap, opts);
  const steps = Array.isArray(roadmap?.roadmap_projection) ? roadmap.roadmap_projection : [];
  const step = steps.find((s) => s && s.id === event.step_id) ?? null;
  return {
    event_id: nonEmpty(opts.event_id) ? String(opts.event_id) : `${roadmap_id}-${event.seq}`,
    roadmap_id,
    kind: event.kind,
    title: step && step.name != null ? step.name : (event.name ?? null),
    step_status: step && step.status != null ? step.status : (event.to ?? null),
    step_id: event.step_id ?? null,
    seq: event.seq,
    // inventory-v1 declares {event_id, phase, ts} as this class's field set; `phase` is the
    // event's kind and `ts` its stamp, named here so the census reads the same values the
    // index does.
    phase: event.kind,
    ts: event.at,
  };
}

/**
 * The bytes one roadmap event is stored as: ONE JSONL line, one event per carrier file.
 *
 * inventory-v1 frames this class as `<root>/roadmap/*.jsonl (one event per line)`, which a
 * single-line file satisfies. Writing one event per file rather than accumulating them is
 * what makes a just-appended roadmap event findable: identity is the PATH, so a file holding
 * many events is one row projecting one of them, and the newest event would be invisible
 * behind its oldest sibling. One file per event makes roadmap-event a literal peer of
 * receipt - one item, one row, one `proj`.
 *
 * @param {object} record @returns {string}
 */
export function roadmapEventBytes(record) {
  return `${JSON.stringify(record)}\n`;
}

/**
 * appendRoadmapEvent, made durable and findable - the W9 write path for class
 * roadmap-event, and class-symmetry leg 4.
 *
 * Wave 6: production path is the ledger spine (named withFileLock on roadmap.json
 * + writeFileAtomicSync). The whole-file-rewrite of the campaign ledger is
 * serialised under that lock; when project_id is supplied the inventory carrier
 * + portfolio index flush still run (outside the roadmap lock, lock-order law).
 *
 * @param {string} projectPath the registered root
 * @param {object|string} roadmapInput @param {object} event
 * @param {{project_id?: string, home?: string, paths?: object, env?: object, at?: string,
 *          roadmap_id?: string, event_id?: string, beforeFlush?: Function,
 *          appendOpts?: object, skip_index?: boolean, timeoutMs?: number}} opts
 * @returns {object}
 */
export function appendRoadmapEventDurable(projectPath, roadmapInput, event, opts = {}) {
  return appendRoadmapEventThroughSpine(projectPath, event, {
    ...opts,
    seed: roadmapInput === undefined ? undefined : roadmapInput,
    at: opts.at,
    project_id: opts.project_id,
    home: opts.home,
    paths: opts.paths,
    env: opts.env,
    // Without project_id there is no portfolio index identity — locked SoT only.
    skip_index: opts.skip_index === true || !opts.project_id,
    roadmap_id: opts.roadmap_id,
    event_id: opts.event_id,
    beforeFlush: opts.beforeFlush,
    appendOpts: opts.appendOpts,
    timeoutMs: opts.timeoutMs,
  });
}

/** Slug id from a step name. */
function slugFromName(name) {
  const slug = String(name ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return slug || 'step';
}

function resolveRoadmapSurfaces(opts = {}) {
  const project_path = resolveProjectPath({ project: opts.project, cwd: opts.cwd });
  const loaded =
    opts.roadmap !== undefined
      ? {
          ok: true,
          exists: opts.roadmap != null,
          roadmap: opts.roadmap,
          roadmap_path: null,
          injected: true,
        }
      : loadProjectRoadmap(project_path);
  return { project_path, loaded };
}

/**
 * roadmap-show — status projection from the append-only events.
 * Face-only prose → empty projection + honest gap (never invented steps).
 * @param {object} opts
 */
export function verbRoadmapShow(opts = {}) {
  const { project_path, loaded } = resolveRoadmapSurfaces(opts);

  if (!loaded.ok) {
    return {
      ok: false,
      error: loaded.error ?? 'roadmap_read_failed',
      spelling: SPELLING,
      verb: 'roadmap-show',
      primary: 'roadmap-show',
      project_path,
      message: loaded.message ?? 'roadmap.json unreadable',
    };
  }

  if (!loaded.exists) {
    const surfaces = opts.surfaces ?? loadProjectSurfaces(project_path);
    const face_only = Boolean(surfaces && (surfaces.face || surfaces.strip));
    const gap = surfaces && surfaces.face ? 'face_prose_only' : 'no_roadmap';
    return {
      ok: true,
      spelling: SPELLING,
      verb: 'roadmap-show',
      primary: 'roadmap-show',
      project_path,
      roadmap_present: false,
      projection: [],
      steps_count: 0,
      events_count: 0,
      gap,
      honest_gap: true,
      invented_steps: false,
      face_prose_consulted: face_only && gap === 'face_prose_only',
      message:
        gap === 'face_prose_only'
          ? 'Face prose exists but there is no engine Roadmap; projection is empty (honest gap — steps are never invented from prose).'
          : 'No Roadmap for this project; projection is empty.',
    };
  }

  const validated = validateRoadmap(loaded.roadmap);
  if (!validated.ok) {
    return {
      ...validated,
      verb: 'roadmap-show',
      primary: 'roadmap-show',
      project_path,
      roadmap_present: true,
    };
  }

  return {
    ok: true,
    spelling: SPELLING,
    verb: 'roadmap-show',
    primary: 'roadmap-show',
    project_path,
    roadmap_present: true,
    projection: validated.projection,
    steps_count: validated.steps_count,
    events_count: validated.events_count,
    issues: validated.issues,
    gap: null,
    invented_steps: false,
    message: 'Roadmap projection derived from append-only events (engine truth).',
  };
}

/**
 * roadmap-propose — propose a step → step_create event only (status proposed).
 * @param {object} opts
 */
export function verbRoadmapPropose(opts = {}) {
  const name = opts.name ?? opts.rest?.[0] ?? null;
  if (!nonEmpty(name)) {
    return {
      ok: false,
      error: 'roadmap_propose_requires_name',
      spelling: SPELLING,
      verb: 'roadmap-propose',
      primary: 'roadmap-propose',
      message: 'roadmap-propose requires --name (step name).',
      required: ['name'],
    };
  }

  const { project_path, loaded } = resolveRoadmapSurfaces(opts);
  if (!loaded.ok) {
    return {
      ok: false,
      error: loaded.error ?? 'roadmap_read_failed',
      spelling: SPELLING,
      verb: 'roadmap-propose',
      primary: 'roadmap-propose',
      project_path,
      message: loaded.message ?? 'roadmap.json unreadable',
    };
  }

  const base = loaded.exists ? loaded.roadmap : emptyRoadmap(opts.project_id ?? null);
  const step_id = nonEmpty(opts.step) ? opts.step : slugFromName(name);

  const event = {
    kind: 'step_create',
    step_id,
    name,
    status: 'proposed',
    done_when: opts.done_when ?? null,
    waiting_on: opts.waiting_on ?? null,
    at: opts.as_of ?? undefined,
    ...(opts.client_event_id ? { client_event_id: opts.client_event_id } : {}),
  };

  const persist = opts.persist !== false && !opts.dry_run && !loaded.injected;
  const written = { roadmap: false };
  let appended;

  if (persist) {
    // Wave 6 live-writer migration (roadmap.mjs:1000): production persist via spine.
    // appendRoadmapEventDurable is the named durable entry (A5 production caller).
    appended = appendRoadmapEventDurable(project_path, base, event, {
      project_id: opts.project_id ?? base?.project_id ?? null,
      home: opts.home,
      paths: opts.paths,
      env: opts.env,
      at: opts.as_of,
      skip_index: !opts.project_id && !opts.home,
    });
    if (!appended.ok) {
      return {
        ...appended,
        verb: 'roadmap-propose',
        primary: 'roadmap-propose',
        project_path,
      };
    }
    written.roadmap = appended.sot_written === true || appended.persisted === true;
  } else {
    appended = appendRoadmapEvent(base, event);
    if (!appended.ok) {
      return {
        ...appended,
        verb: 'roadmap-propose',
        primary: 'roadmap-propose',
        project_path,
      };
    }
  }

  return {
    ok: true,
    spelling: SPELLING,
    verb: 'roadmap-propose',
    primary: 'roadmap-propose',
    project_path,
    event: appended.event,
    roadmap: appended.roadmap,
    projection: appended.projection,
    step_id,
    events_only: true,
    projection_written_directly: false,
    single_writer: ROADMAP_SINGLE_WRITER,
    persisted: written,
    dry_run: Boolean(opts.dry_run) || opts.persist === false,
    spine: persist ? true : undefined,
    message: `Step '${step_id}' proposed via step_create event (events only; projection derived).`,
  };
}

/**
 * roadmap-set — events only:
 * - --status <to> flips status (receipt --who/--reason required; refuse without)
 * - --commissioned-as binds a commission (TW3 hook path)
 * - --name/--done-when/--waiting-on emit step_set
 * @param {object} opts
 */
export function verbRoadmapSet(opts = {}) {
  const step_id = opts.step ?? null;
  if (!nonEmpty(step_id)) {
    return {
      ok: false,
      error: 'roadmap_set_requires_step',
      spelling: SPELLING,
      verb: 'roadmap-set',
      primary: 'roadmap-set',
      message: 'roadmap-set requires --step <id>.',
      required: ['step'],
    };
  }

  const { project_path, loaded } = resolveRoadmapSurfaces(opts);
  if (!loaded.ok) {
    return {
      ok: false,
      error: loaded.error ?? 'roadmap_read_failed',
      spelling: SPELLING,
      verb: 'roadmap-set',
      primary: 'roadmap-set',
      project_path,
      message: loaded.message ?? 'roadmap.json unreadable',
    };
  }
  if (!loaded.exists) {
    return {
      ok: false,
      error: 'no_roadmap',
      spelling: SPELLING,
      verb: 'roadmap-set',
      primary: 'roadmap-set',
      project_path,
      message:
        'No engine Roadmap for this project — nothing to set. Propose steps first (roadmap-propose); prose is not a step list.',
    };
  }

  let event;
  if (opts.status != null) {
    const receipt =
      opts.receipt && typeof opts.receipt === 'object'
        ? opts.receipt
        : { who: opts.who ?? null, when: opts.when ?? null, why: opts.reason ?? opts.why ?? null };
    if (!isValidFlipReceipt(receipt)) {
      return {
        ok: false,
        error: 'status_flip_requires_receipt',
        spelling: SPELLING,
        verb: 'roadmap-set',
        primary: 'roadmap-set',
        project_path,
        step_id,
        required: [...FLIP_RECEIPT_FIELDS],
        message:
          'Status flip refused without receipt: pass --who and --reason (who/why; when defaults to event date).',
        single_writer: ROADMAP_SINGLE_WRITER,
      };
    }
    event = {
      kind: 'status_flip',
      step_id,
      from: opts.from ?? null,
      to: opts.status,
      receipt,
      at: opts.as_of ?? undefined,
      ...(opts.client_event_id ? { client_event_id: opts.client_event_id } : {}),
    };
    if (event.from == null) delete event.from;
  } else if (nonEmpty(opts.commissioned_as)) {
    event = {
      kind: 'commission_bind',
      step_id,
      commissioned_as: opts.commissioned_as,
      at: opts.as_of ?? undefined,
      ...(opts.client_event_id ? { client_event_id: opts.client_event_id } : {}),
    };
  } else {
    const fields = {};
    if (opts.name != null) fields.name = opts.name;
    if (opts.done_when != null) fields.done_when = opts.done_when;
    if (opts.waiting_on != null) fields.waiting_on = opts.waiting_on;
    if (!Object.keys(fields).length) {
      return {
        ok: false,
        error: 'roadmap_set_requires_change',
        spelling: SPELLING,
        verb: 'roadmap-set',
        primary: 'roadmap-set',
        project_path,
        message:
          'roadmap-set needs a change: --status (+ --who/--reason), --commissioned-as, or --name/--done-when/--waiting-on.',
      };
    }
    event = {
      kind: 'step_set',
      step_id,
      fields,
      at: opts.as_of ?? undefined,
      ...(opts.client_event_id ? { client_event_id: opts.client_event_id } : {}),
    };
  }

  const persist = opts.persist !== false && !opts.dry_run && !loaded.injected;
  const written = { roadmap: false };
  let appended;

  if (persist) {
    // Wave 6 live-writer migration (roadmap.mjs:1139): production persist via spine.
    appended = appendRoadmapEventDurable(project_path, loaded.roadmap, event, {
      project_id: opts.project_id ?? loaded.roadmap?.project_id ?? null,
      home: opts.home,
      paths: opts.paths,
      env: opts.env,
      at: opts.as_of,
      skip_index: !opts.project_id && !opts.home,
    });
    if (!appended.ok) {
      return {
        ...appended,
        verb: 'roadmap-set',
        primary: 'roadmap-set',
        project_path,
      };
    }
    written.roadmap = appended.sot_written === true || appended.persisted === true;
  } else {
    appended = appendRoadmapEvent(loaded.roadmap, event);
    if (!appended.ok) {
      return {
        ...appended,
        verb: 'roadmap-set',
        primary: 'roadmap-set',
        project_path,
      };
    }
  }

  return {
    ok: true,
    spelling: SPELLING,
    verb: 'roadmap-set',
    primary: 'roadmap-set',
    project_path,
    event: appended.event,
    roadmap: appended.roadmap,
    projection: appended.projection,
    step_id,
    events_only: true,
    projection_written_directly: false,
    single_writer: ROADMAP_SINGLE_WRITER,
    persisted: written,
    dry_run: Boolean(opts.dry_run) || opts.persist === false,
    spine: persist ? true : undefined,
    message: `Roadmap event '${appended.event.kind}' appended for step '${step_id}' (events only; projection derived).`,
  };
}

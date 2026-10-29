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
import { validNavigation, navigationIssues } from './navigation.mjs';
import { foldRefinements } from './refinement-state.mjs';
import { writeFileAtomicSync, withFileLock } from './durable-write.mjs';
import path from 'node:path';

import { SPELLING } from './verbs.mjs';
import { resolveProjectPath, loadProjectSurfaces } from './face-strip.mjs';
// Wave 6 spine — circular with ledger-spine (it imports pure law from here).
// Safe: both sides only call the other's exports from function bodies.
import { appendRoadmapEventThroughSpine } from './ledger-spine.mjs';
import { demandClose } from './ledger-spine.mjs';

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
 * Wave 17 (v6): goal_flip — re-read the North Star when a step closes
 * (steward slice loop, 2026-08-28). part/gate ride on steps, not a new file.
 * Wave 18 (v7): kickoff_proposal / kickoff_confirm — one versioned,
 * hash-confirmed kickoff lineage. Both are project-level; confirmed plan
 * entries project onto ordinary roadmap steps with component references.
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
  'goal_flip',
  'kickoff_proposal',
  'kickoff_confirm',
  'refinement_update',
  // W4 of the steward revision (2026-09-28, v9): a repair PROPOSED after an acceptance and its resolution on his
  // word (project-level ledger events); a step moved in the plan's order on his word (folded)
  'repair_proposal',
  'repair_resolve',
  'reorder',
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
  'goal_flip',
  'kickoff_proposal',
  'kickoff_confirm',
  'refinement_update',
  'repair_proposal',
  'repair_resolve',
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
  'due',
  'ref',
  'tier',
  'area',
  'commissioned_as',
  'part',
  'gate',
  'component_ids',
  'end_to_end_slice',
  'kickoff_version',
  'kickoff_proposal_hash',
  'refinement',
  'navigation',
]);

/** Execution-phase tags. They are not the work-product component map. */
export const ROADMAP_PART_TAGS = Object.freeze([
  'research',
  'slice',
  'rigor',
  'integrate',
  'harden',
]);

/**
 * Fields step_set may change. status requires status_flip (+ receipt);
 * commissioned_as requires commission_bind (TW3 single-writer hook).
 */
export const ROADMAP_SET_FIELDS = Object.freeze([
  'navigation',
  'name',
  'done_when',
  'waiting_on',
  'due',
  'ref',
  'tier',
  'area',
  'part',
  'gate',
  'component_ids',
  'end_to_end_slice',
  'kickoff_version',
  'kickoff_proposal_hash',
  // the active set (2026-09-29, John: "the active group"): an initiative he works on now, its place in the set,
  // and the pace — the date he drives the effort toward. Set only by his act (receipted step_set); read by the
  // High Seat's head and tile. A part's own date stays `due`.
  'active',
  'active_order',
  'pace',
  // the seats (2026-09-30, John's three levels): a goal's component he works interactively — a project's cockpit,
  // one cockpit within a project (effort:), or a desk task — sits in its goal (no seat), ON DECK, or ACTIVE, in his
  // order. Set only by his act or his word (receipted step_set); read by the High Seat's head and shelves.
  'seat',
  'seat_order',
  // the Star Chart (the Campaign mode, 2026-10-03): a Tier-1 goal's one if-then next step, in his words ("If it is
  // Monday 9:00, then I send the trust questions"). Set only by his act or his word (receipted step_set).
  'if_then',
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
/** W0 (High Seat, 2026-09-26): an optional calendar date on a step — ISO YYYY-MM-DD only, nothing else. */
export const ROADMAP_DUE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
export function normalizeDue(v) {
  if (typeof v !== 'string') return null;
  const s = v.trim();
  if (!ROADMAP_DUE_PATTERN.test(s)) return null;
  const d = new Date(`${s}T00:00:00Z`);
  return Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== s ? null : s;
}

/**
 * W0b (High Seat, 2026-09-26): three more optional step fields, validated by value like `part`.
 *  ref  — a part that points at another record: project:<pid> · step:<pid>/<sid> · deliverable:<pid>/<row> · calendar:<id>.
 *         A step with a ref carries no due and is never flipped here (its own record owns date and state).
 *  tier — an initiative's priority tier, 1 · 2 · 3, on its heading step.
 *  area — an initiative's life area, one of six tags, on its heading step.
 */
export const ROADMAP_REF_PREFIXES = Object.freeze(['project', 'step', 'deliverable', 'calendar', 'effort']);   // effort:<pid>/<dir> — one cockpit within a project (2026-09-30)
export const ROADMAP_AREA_TAGS = Object.freeze(['family', 'professional', 'writing', 'research', 'tools', 'personal']);
export function normalizeRef(v) {
  if (typeof v !== 'string') return null;
  const s = v.trim();
  const m = /^([a-z]+):(\S+)$/.exec(s);
  if (!m || !ROADMAP_REF_PREFIXES.includes(m[1])) return null;
  if ((m[1] === 'step' || m[1] === 'deliverable' || m[1] === 'effort') && !/^[^/]+\/[^/]+$/.test(m[2])) return null;
  if (m[1] === 'effort') { const dir = m[2].split('/')[1]; if (dir === '.' || dir === '..' || /\\/.test(dir)) return null; }   // one directory inside the project, never a step out (Grok, W2b)
  return s;
}
export function normalizeTier(v) {
  const n = typeof v === 'string' && /^\s*[123]\s*$/.test(v) ? Number(v) : v;
  return Number.isInteger(n) && n >= 1 && n <= 3 ? n : null;
}
export function normalizeArea(v) {
  if (typeof v !== 'string') return null;
  const s = v.trim().toLowerCase();
  return ROADMAP_AREA_TAGS.includes(s) ? s : null;
}
const REF_FIELD_NORMALIZERS = Object.freeze({
  ref: [normalizeRef, 'invalid_ref'],
  tier: [normalizeTier, 'invalid_tier'],
  area: [normalizeArea, 'unknown_area_tag'],
});
function otherStepWithRef(steps, id, ref) {
  for (const [oid, os] of steps) if (oid !== id && os && os.ref === ref) return oid;
  return null;
}

export function normalizePartTag(raw) {
  const v = String(raw || '').trim().toLowerCase();
  return ROADMAP_PART_TAGS.includes(v) ? v : null;
}

export function normalizeProjectionStep(step = {}) {
  const gate = step.gate;
  const hasKickoffProjection = Array.isArray(step.component_ids)
    || step.end_to_end_slice != null
    || step.kickoff_version != null
    || step.kickoff_proposal_hash != null;
  const componentIds = Array.isArray(step.component_ids)
    ? [...new Set(step.component_ids.map(String).filter(Boolean))]
    : [];
  const normalized = {
    id: step.id ?? null,
    name: step.name ?? null,
    status: step.status ?? null,
    done_when: step.done_when ?? null,
    waiting_on: step.waiting_on ?? null,
    commissioned_as: step.commissioned_as ?? null,
    part: normalizePartTag(step.part),
    gate: typeof gate === 'string' && gate.trim() ? gate.trim() : null,
  };
  if (hasKickoffProjection) {
    normalized.component_ids = componentIds;
    normalized.end_to_end_slice = step.end_to_end_slice === true;
    normalized.kickoff_version = Number.isInteger(step.kickoff_version)
      ? step.kickoff_version : null;
    normalized.kickoff_proposal_hash = typeof step.kickoff_proposal_hash === 'string'
      && step.kickoff_proposal_hash.trim()
      ? step.kickoff_proposal_hash.trim()
      : null;
  }
  if (step.due != null) normalized.due = step.due;
  if (step.ref != null) normalized.ref = step.ref;
  if (step.tier != null) normalized.tier = step.tier;
  if (step.area != null) normalized.area = step.area;
  if (step.active === true) normalized.active = true;
  if (Number.isInteger(step.active_order)) normalized.active_order = step.active_order;
  if (step.pace != null) normalized.pace = step.pace;
  if (step.seat === 'active' || step.seat === 'deck') normalized.seat = step.seat;
  if (Number.isInteger(step.seat_order)) normalized.seat_order = step.seat_order;
  // the Star Chart (2026-10-03): a goal's if-then step survives the projection; null or blank clears it (Grok code R1 F1)
  if (typeof step.if_then === 'string' && step.if_then.trim()) normalized.if_then = step.if_then.trim();
  if (step.navigation != null) normalized.navigation = structuredClone(step.navigation);
  if (step.refinement) normalized.refinement = step.refinement;
  return normalized;
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
      if (ev.part != null && !normalizePartTag(ev.part)) {
        issues.push({ code: 'unknown_part_tag', at_index: idx, step_id: id, part: ev.part });
      }
      const created = {
        id,
        name: ev.name,
        status,
        done_when: ev.done_when ?? null,
        waiting_on: ev.waiting_on ?? null,
        commissioned_as: null,
        part: normalizePartTag(ev.part),
        gate: typeof ev.gate === 'string' && ev.gate.trim() ? ev.gate.trim() : null,
      };
      if (ev.due != null) {
        const due = normalizeDue(ev.due);
        if (due) created.due = due;
        else issues.push({ code: 'invalid_due', at_index: idx, step_id: id, due: ev.due });
      }
      for (const [key, [norm, bad]] of Object.entries(REF_FIELD_NORMALIZERS)) {
        if (ev[key] == null) continue;
        const val = norm(ev[key]);
        if (val == null) { issues.push({ code: bad, at_index: idx, step_id: id, [key]: ev[key] }); continue; }
        if (key === 'ref') {
          const dup = otherStepWithRef(steps, id, val);
          if (dup) { issues.push({ code: 'duplicate_ref', at_index: idx, step_id: id, ref: val, other_step_id: dup }); continue; }
          if (created.due != null) { issues.push({ code: 'due_on_ref_step', at_index: idx, step_id: id, ref: val }); delete created.due; }
        }
        created[key] = val;
      }
      if (Array.isArray(ev.component_ids)
          || ev.end_to_end_slice != null
          || ev.kickoff_version != null
          || ev.kickoff_proposal_hash != null) {
        created.component_ids = Array.isArray(ev.component_ids)
          ? [...new Set(ev.component_ids.map(String).filter(Boolean))]
          : [];
        created.end_to_end_slice = ev.end_to_end_slice === true;
        created.kickoff_version = Number.isInteger(ev.kickoff_version)
          ? ev.kickoff_version : null;
        created.kickoff_proposal_hash = typeof ev.kickoff_proposal_hash === 'string'
          && ev.kickoff_proposal_hash.trim()
          ? ev.kickoff_proposal_hash.trim()
          : null;
      }
      steps.set(id, created);
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
        if (key === 'navigation') {
          if (!validNavigation(fields.navigation)) { issues.push({code:'invalid_navigation',at_index:idx,step_id:id}); continue; }
          if (fields.navigation == null) delete step.navigation;
          else step.navigation = structuredClone(fields.navigation);
          continue;
        }
        if (key === 'due') {
          if (fields.due == null) { delete step.due; continue; }
          if (step.ref != null) { issues.push({ code: 'due_on_ref_step', at_index: idx, step_id: id, ref: step.ref }); continue; }
          const due = normalizeDue(fields.due);
          if (due) step.due = due;
          else issues.push({ code: 'invalid_due', at_index: idx, step_id: id, due: fields.due });
          continue;
        }
        if (key in REF_FIELD_NORMALIZERS) {
          if (fields[key] == null) { delete step[key]; continue; }
          const [norm, bad] = REF_FIELD_NORMALIZERS[key];
          const val = norm(fields[key]);
          if (val == null) { issues.push({ code: bad, at_index: idx, step_id: id, [key]: fields[key] }); continue; }
          if (key === 'ref') {
            const dup = otherStepWithRef(steps, id, val);
            if (dup) { issues.push({ code: 'duplicate_ref', at_index: idx, step_id: id, ref: val, other_step_id: dup }); continue; }
            if (step.due != null) { issues.push({ code: 'ref_on_dated_step', at_index: idx, step_id: id, ref: val }); continue; }
          }
          step[key] = val;
          continue;
        }
        if (key === 'part') {
          if (fields.part != null && !normalizePartTag(fields.part)) {
            issues.push({ code: 'unknown_part_tag', at_index: idx, step_id: id, part: fields.part });
          }
          step.part = normalizePartTag(fields.part);
          continue;
        }
        if (key === 'gate') {
          const g = fields.gate;
          step.gate = typeof g === 'string' && g.trim() ? g.trim() : null;
          continue;
        }
        if (key === 'component_ids') {
          step.component_ids = Array.isArray(fields.component_ids)
            ? [...new Set(fields.component_ids.map(String).filter(Boolean))]
            : [];
          continue;
        }
        if (key === 'end_to_end_slice') {
          step.end_to_end_slice = fields.end_to_end_slice === true;
          continue;
        }
        if (key === 'active') {
          // the active set: on or off, never a third state; off drops the order with it
          const on = fields.active === true || fields.active === 'on' || fields.active === 'true';
          if (on) step.active = true; else { delete step.active; delete step.active_order; }
          continue;
        }
        if (key === 'active_order') {
          const n = fields.active_order;
          if (n == null || n === '') { delete step.active_order; continue; }
          const v = typeof n === 'number' ? n : parseInt(String(n), 10);
          if (Number.isInteger(v) && v >= 0) step.active_order = v;
          else issues.push({ code: 'invalid_active_order', at_index: idx, step_id: id, active_order: n });
          continue;
        }
        if (key === 'pace') {
          if (fields.pace == null || fields.pace === '') { delete step.pace; continue; }
          const d = normalizeDue(fields.pace);
          if (d) step.pace = d;
          else issues.push({ code: 'invalid_pace', at_index: idx, step_id: id, pace: fields.pace });
          continue;
        }
        if (key === 'seat') {
          // the seat: active, deck, or none (back in its goal) — none drops the order with it
          const v = fields.seat;
          if (v == null || v === '' || v === 'none' || v === 'off') { delete step.seat; delete step.seat_order; continue; }
          if (v === 'active' || v === 'deck') { step.seat = v; continue; }
          issues.push({ code: 'invalid_seat', at_index: idx, step_id: id, seat: v });
          continue;
        }
        if (key === 'seat_order') {
          const n = fields.seat_order;
          if (n == null || n === '') { delete step.seat_order; continue; }
          const v = typeof n === 'number' ? n : parseInt(String(n), 10);
          if (Number.isInteger(v) && v >= 0) step.seat_order = v;
          else issues.push({ code: 'invalid_seat_order', at_index: idx, step_id: id, seat_order: n });
          continue;
        }
        if (key === 'kickoff_version') {
          step.kickoff_version = Number.isInteger(fields.kickoff_version)
            ? fields.kickoff_version : null;
          continue;
        }
        if (key === 'kickoff_proposal_hash') {
          step.kickoff_proposal_hash = typeof fields.kickoff_proposal_hash === 'string'
            && fields.kickoff_proposal_hash.trim()
            ? fields.kickoff_proposal_hash.trim() : null;
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
      if (step.ref != null) {
        issues.push({ code: 'status_flip_on_ref_step', at_index: idx, step_id: id, ref: step.ref,
          message: 'a referenced part is flipped in its own record, never here (not applied)' });
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

    // Project-level kinds (scaffold/kickoff proposal and confirm, face_*,
    // elaboration_*): ledger
    // history only — no roadmap_projection fold. Detail is reconstructed by
    // the owning surface (Face compile / progressive elaboration).
    if (kind === 'reorder') {
      // W4 (2026-09-28): his own act — a step moved before or after another in the plan's order; the projection
      // is the Map's insertion order, so the move is a re-insertion
      const step = steps.get(id);
      if (!step) { issues.push({ code: 'reorder_unknown_step', at_index: idx, step_id: id }); return; }
      const anchor = ev.before != null ? String(ev.before) : (ev.after != null ? String(ev.after) : null);
      if (!anchor || anchor === String(id) || !steps.has(anchor)) { issues.push({ code: 'reorder_bad_anchor', at_index: idx, step_id: id, anchor }); return; }
      const entries = [...steps.entries()].filter(([k]) => k !== id);
      const at = entries.findIndex(([k]) => k === anchor);
      entries.splice(ev.before != null ? at : at + 1, 0, [id, step]);
      steps.clear();
      for (const [k, v] of entries) steps.set(k, v);
      return;
    }
    if (ROADMAP_PROJECT_LEVEL_KINDS.includes(kind)) {
      return;
    }

    issues.push({ code: 'unknown_event_kind', at_index: idx, kind: kind ?? null });
  });

  try {
    const refinement=foldRefinements(list);
    for(const [id,slice] of Object.entries(refinement.slices || {})) {
      const step=steps.get(id);
      if(!step) { issues.push({code:'refinement_unknown_step',step_id:id}); continue; }
      step.refinement=slice;
      step.status=slice.phase==='done'?'done':['awaiting_review','waiting_foundation','needs_reconciliation'].includes(slice.phase)?'waiting':'active';
      step.waiting_on=slice.phase==='awaiting_review'?'Your review of the current presentation':slice.phase==='needs_reconciliation'?'Foundation changes need reconciliation':slice.phase==='waiting_foundation'?'Foundation acceptance':null;
    }
  } catch(e) { issues.push({code:e.code || 'invalid-refinement-operation',message:e.message}); }
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
  const navIssues = navigationIssues(built.projection);
  if (navIssues.length) return {ok:false,error:navIssues[0].code,issues:navIssues};

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
    if (event.due != null && !normalizeDue(event.due)) {
      return { ok: false, error: 'invalid_due', spelling: SPELLING, step_id, due: event.due, expected: 'YYYY-MM-DD' };
    }
    for (const [key, [norm, bad]] of Object.entries(REF_FIELD_NORMALIZERS)) {
      if (event[key] != null && norm(event[key]) == null) {
        return { ok: false, error: bad, spelling: SPELLING, step_id, [key]: event[key] };
      }
    }
    if (event.ref != null) {
      const dup = otherStepWithRef(current, step_id, normalizeRef(event.ref));
      if (dup) return { ok: false, error: 'duplicate_ref', spelling: SPELLING, step_id, ref: event.ref, other_step_id: dup };
      if (event.due != null) return { ok: false, error: 'due_on_ref_step', spelling: SPELLING, step_id, ref: event.ref, message: 'a referenced part takes its date from its own record' };
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
    if (cur && cur.ref != null) {
      return { ok: false, error: 'status_flip_on_ref_step', spelling: SPELLING, step_id, ref: cur.ref,
        message: 'a referenced part is flipped in its own record, never here' };
    }
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
    if ('navigation' in fields && !validNavigation(fields.navigation)) return {ok:false,error:'invalid_navigation'};
    if (fields.due != null && !normalizeDue(fields.due)) {
      return { ok: false, error: 'invalid_due', spelling: SPELLING, step_id, due: fields.due, expected: 'YYYY-MM-DD' };
    }
    if (fields.pace != null && fields.pace !== '' && !normalizeDue(fields.pace)) {
      return { ok: false, error: 'invalid_pace', spelling: SPELLING, step_id, pace: fields.pace, expected: 'YYYY-MM-DD or none' };
    }
    if (fields.active_order != null && fields.active_order !== '') {
      const v = typeof fields.active_order === 'number' ? fields.active_order : parseInt(String(fields.active_order), 10);
      if (!Number.isInteger(v) || v < 0) {
        return { ok: false, error: 'invalid_active_order', spelling: SPELLING, step_id, active_order: fields.active_order, expected: 'an integer from 0' };
      }
    }
    if (fields.active != null && ![true, false, 'on', 'off', 'true', 'false'].includes(fields.active)) {
      return { ok: false, error: 'invalid_active', spelling: SPELLING, step_id, active: fields.active, expected: 'on or off' };
    }
    if (fields.seat != null && fields.seat !== '' && !['none', 'off', 'active', 'deck'].includes(fields.seat)) {
      return { ok: false, error: 'invalid_seat', spelling: SPELLING, step_id, seat: fields.seat, expected: 'active, deck or none' };
    }
    if (fields.seat_order != null && fields.seat_order !== '') {
      const v = typeof fields.seat_order === 'number' ? fields.seat_order : parseInt(String(fields.seat_order), 10);
      if (!Number.isInteger(v) || v < 0) {
        return { ok: false, error: 'invalid_seat_order', spelling: SPELLING, step_id, seat_order: fields.seat_order, expected: 'an integer from 0' };
      }
    }
    for (const [key, [norm, bad]] of Object.entries(REF_FIELD_NORMALIZERS)) {
      if (fields[key] != null && norm(fields[key]) == null) {
        return { ok: false, error: bad, spelling: SPELLING, step_id, [key]: fields[key] };
      }
    }
    {
      const cur = current.get(step_id) || {};
      if (fields.ref != null) {
        const dup = otherStepWithRef(current, step_id, normalizeRef(fields.ref));
        if (dup) return { ok: false, error: 'duplicate_ref', spelling: SPELLING, step_id, ref: fields.ref, other_step_id: dup };
        if (cur.due != null || fields.due != null) return { ok: false, error: 'ref_on_dated_step', spelling: SPELLING, step_id, ref: fields.ref, message: 'a referenced part takes its date from its own record' };
      }
      if (fields.due != null && cur.ref != null && !('ref' in fields && fields.ref == null)) {
        return { ok: false, error: 'due_on_ref_step', spelling: SPELLING, step_id, ref: cur.ref, message: 'a referenced part takes its date from its own record' };
      }
    }
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

  if (kind === 'reorder') {
    const have = new Set(roadmap.roadmap_projection.map((s) => String(s.id)));
    const anchor = event.before != null ? String(event.before) : (event.after != null ? String(event.after) : null);
    if (!nonEmpty(step_id) || !have.has(String(step_id)) || !anchor || anchor === String(step_id) || !have.has(anchor)) {
      return { ok: false, error: 'reorder_invalid', spelling: SPELLING, step_id: step_id ?? null, anchor,
               message: 'reorder needs an existing step_id and an existing before/after step that is not itself.' };
    }
    if (!(event.receipt && typeof event.receipt === 'object' && nonEmpty(event.receipt.who))) {
      return { ok: false, error: 'reorder_needs_receipt', spelling: SPELLING, step_id, message: 'reorder is his act: it carries a receipt (who, why).' };
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

  if (kind === 'step_set' && event.fields && 'navigation' in event.fields && !validNavigation(event.fields.navigation)) return {ok:false,error:'invalid_navigation'};
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
  let refinement;
  try { refinement=foldRefinements(events); }
  catch(e) { return {ok:false,error:e.code || 'invalid-refinement-operation',detail:e.message}; }
  const built = buildRoadmapProjection(events);
  const navIssues = navigationIssues(built.projection);
  if (navIssues.length) return {ok:false,error:navIssues[0].code,issues:navIssues};

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
      ...(refinement.managed ? {refinement_projection:refinement} : {}),
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
    ...(opts.due != null ? { due: opts.due } : {}),
    ...(opts.ref != null ? { ref: opts.ref } : {}),
    ...(opts.tier != null ? { tier: opts.tier } : {}),
    ...(opts.area != null ? { area: opts.area } : {}),
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
 * - --name/--done-when/--waiting-on/--due/--ref/--tier/--area emit step_set
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
    if (opts.status === 'done') {
      // cockpit Wave B: the steward's close states the next act and the goal re-read first
      const demand = demandClose(project_path, loaded.roadmap, step_id, opts.goal_reread ?? null);
      if (!demand.ok) return { ...demand, spelling: SPELLING, verb: 'roadmap-set', primary: 'roadmap-set', project_path, step_id };
    }
    event = {
      kind: 'status_flip',
      step_id,
      from: opts.from ?? null,
      to: opts.status,
      receipt,
      at: opts.as_of ?? undefined,
      ...(opts.goal_reread ? { goal_reread: opts.goal_reread } : {}),
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
    if (opts.due != null) fields.due = (opts.due === 'none' || opts.due === '') ? null : opts.due;
    for (const key of ['ref', 'tier', 'area']) {
      if (opts[key] != null) fields[key] = (opts[key] === 'none' || opts[key] === '') ? null : opts[key];
    }
    // the active set (2026-09-29): --active on|off · --active-order N|none · --pace YYYY-MM-DD|none
    if (opts.active != null) fields.active = !(opts.active === 'off' || opts.active === 'false' || opts.active === false);
    if (opts.active_order != null) fields.active_order = (opts.active_order === 'none' || opts.active_order === '') ? null : opts.active_order;
    if (opts.pace != null) fields.pace = (opts.pace === 'none' || opts.pace === '') ? null : opts.pace;
    // the seats (2026-09-30): --seat-in active|deck|none · --seat-order N|none (--seat alone is the model seat)
    if (opts.seat_in != null) fields.seat = (opts.seat_in === 'none' || opts.seat_in === '' || opts.seat_in === 'off') ? null : opts.seat_in;
    if (opts.seat_order != null) fields.seat_order = (opts.seat_order === 'none' || opts.seat_order === '') ? null : opts.seat_order;
    if (!Object.keys(fields).length) {
      return {
        ok: false,
        error: 'roadmap_set_requires_change',
        spelling: SPELLING,
        verb: 'roadmap-set',
        primary: 'roadmap-set',
        project_path,
        message:
          'roadmap-set needs a change: --status (+ --who/--reason), --commissioned-as, or --name/--done-when/--waiting-on/--due/--ref/--tier/--area/--active/--active-order/--pace.',
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

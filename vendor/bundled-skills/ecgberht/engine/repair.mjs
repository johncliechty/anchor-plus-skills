// Repair as a proposal — the correction set after an acceptance, composed from the records and SHOWN, never applied
// before his word (W4 of the steward revision, 2026-09-28; the synthesis R4; his answer Q2: "propose the tidying too").
//
// After a presentation is accepted on a step, two kinds of correction follow from the records alone:
//   (a) a roadmap step that WAITED on the accepted step (its `waiting_on` names the step's id or name) no longer
//       waits on it — the proposal clears that wait (a `step_set` of `waiting_on: null`, applied only on accept);
//   (b) a refinement slice whose dependency pin on the accepted slice is `needs_reconciliation` needs a second
//       look — the proposal NAMES it (a row with no fields: the refinement fold owns a managed slice's wait and
//       would erase any sentence written there; the slice's own reconciliation stays the refinement engine's, on
//       his word). Grok W4: shown, never written.
// Scope, dates, priorities and commitments are never in a set. Nothing here reads a model; nothing here writes —
// the verb (`update --repair-propose --after-step <id>`; `update --repair-resolve <proposal> --disposition
// accepted|dismissed --who <name>`) appends the `repair_proposal` event and, on his word, the `repair_resolve` event
// and the corrections as receipted `step_set` events. Each correction remembers what the step's wait WAS when the
// set was composed; on accept a correction is applied only while that is still true (`planRepairApply`).
import { createHash } from 'node:crypto';

export const REPAIR_PROPOSAL_SCHEMA = 'ecgberht-repair-proposal-v1';

function norm(s) {
  return String(s ?? '').trim().toLowerCase();
}

function hasWord(text, needle) {
  // the needle as a whole token: nothing alphanumeric on either side ("lec3" is not in "lec30"; Grok W4)
  if (!needle) return false;
  const re = new RegExp('(^|[^a-z0-9])' + needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '($|[^a-z0-9])');
  return re.test(text);
}

function mentions(text, step) {
  const t = norm(text);
  if (!t) return false;
  const id = norm(step.id);
  const name = norm(step.name);
  return hasWord(t, id) || (name.length >= 4 && hasWord(t, name));
}

export function contentHash(obj) {
  return createHash('sha256').update(JSON.stringify(obj)).digest('hex').slice(0, 16);
}

/**
 * @param {object} o
 * @param {object[]} o.projection        the roadmap projection
 * @param {string}   o.accepted_step_id  the step whose presentation he accepted
 * @param {string|null} [o.accepted_presentation_id]
 * @param {object|null} [o.refinement_state]  the refinement fold's state ({slices:{id:{depends_on:[{slice_id,state}]}}})
 * @param {number|null} [o.after_seq]    the roadmap's last seq when composed (the proposal's anchor)
 * @returns {{ok:true, corrections:object[], empty:boolean, proposal:object} | {ok:false, reason:string}}
 */
export function composeRepairProposal({ projection, accepted_step_id, accepted_presentation_id = null, refinement_state = null, after_seq = null } = {}) {
  const steps = Array.isArray(projection) ? projection.filter((s) => s && typeof s === 'object') : [];
  const accepted = steps.find((s) => String(s.id) === String(accepted_step_id));
  if (!accepted) return { ok: false, reason: `accepted step ${accepted_step_id} names no step in the roadmap` };
  const closed = new Set(['done', 'cancelled', 'dropped']);
  const corrections = [];
  for (const s of steps) {
    if (String(s.id) === String(accepted.id) || closed.has(String(s.status || ''))) continue;
    if (mentions(s.waiting_on, accepted)) {
      corrections.push({ step_id: String(s.id), kind: 'clear_wait', fields: { waiting_on: null }, was: { waiting_on: s.waiting_on ?? null },
        why: `waited on ${accepted.name || accepted.id}, now accepted` });
    }
  }
  const slices = refinement_state && typeof refinement_state === 'object' && refinement_state.slices && typeof refinement_state.slices === 'object' ? refinement_state.slices : {};
  for (const [sid, slice] of Object.entries(slices)) {
    if (String(sid) === String(accepted.id) || !slice || typeof slice !== 'object') continue;
    const deps = Array.isArray(slice.depends_on) ? slice.depends_on : [];
    const stale = deps.some((d) => d && String(d.slice_id) === String(accepted.id) && d.state === 'needs_reconciliation');
    if (!stale) continue;
    const step = steps.find((s) => String(s.id) === String(sid));
    if (!step || closed.has(String(step.status || ''))) continue;   // a slice with no open step is not a row (Grok W4)
    if (corrections.some((c) => c.step_id === String(sid))) continue;
    corrections.push({ step_id: String(sid), kind: 'second_look', note: 'needs a second look — its foundation changed',
      was: { waiting_on: step.waiting_on ?? null }, why: `its foundation ${accepted.name || accepted.id} changed` });
  }
  const body = {
    schema: REPAIR_PROPOSAL_SCHEMA,
    kind: 'repair_proposal',
    after: { step_id: String(accepted.id), presentation_id: accepted_presentation_id ?? null, seq: after_seq ?? null },
    corrections,
    count: corrections.length,
    zero_model: true,
    deterministic: true,
    requires_confirm: true,
  };
  const proposal_id = `repair-${contentHash(body)}`;
  return { ok: true, corrections, empty: corrections.length === 0, proposal: { ...body, proposal_id } };
}

/** The open proposals in a roadmap's events: every repair_proposal with no repair_resolve naming it. */
export function openRepairProposals(events) {
  const list = Array.isArray(events) ? events : [];
  const resolved = new Set(list.filter((e) => e && e.kind === 'repair_resolve').map((e) => String(e.proposal_id)));
  return list.filter((e) => e && e.kind === 'repair_proposal' && !resolved.has(String(e.proposal_id)));
}

/**
 * What an ACCEPTED proposal applies now: each correction that carries fields (clear_wait), whose step still exists,
 * is still open and whose wait is still what the set was composed against. Anything that moved since is skipped
 * and named — never re-corrected over his or the turn's later word; a correction with no `was` is skipped as
 * `uncomposed` (the guard must not fail open; Grok W4). A row without fields (second_look) is noted, not written.
 * Pure.
 * @returns {{apply: object[], skipped: {step_id:string, reason:string}[], noted: string[]}}
 */
export function planRepairApply({ projection, proposal } = {}) {
  const steps = Array.isArray(projection) ? projection.filter((s) => s && typeof s === 'object') : [];
  const closed = new Set(['done', 'cancelled', 'dropped']);
  const apply = [];
  const skipped = [];
  const noted = [];
  for (const c of (proposal && Array.isArray(proposal.corrections) ? proposal.corrections : [])) {
    if (!c || typeof c !== 'object') continue;
    if (!c.fields || typeof c.fields !== 'object') { noted.push(String(c.step_id)); continue; }
    const step = steps.find((s) => String(s.id) === String(c.step_id));
    if (!step) { skipped.push({ step_id: String(c.step_id), reason: 'no_such_step' }); continue; }
    if (closed.has(String(step.status || ''))) { skipped.push({ step_id: String(c.step_id), reason: 'closed_since' }); continue; }
    if (!(c.was && typeof c.was === 'object' && 'waiting_on' in c.was)) { skipped.push({ step_id: String(c.step_id), reason: 'uncomposed' }); continue; }
    if (norm(step.waiting_on) !== norm(c.was.waiting_on)) { skipped.push({ step_id: String(c.step_id), reason: 'changed_since' }); continue; }
    apply.push({ step_id: String(c.step_id), kind: c.kind, fields: { ...c.fields }, why: String(c.why ?? c.kind ?? 'repair') });
  }
  return { apply, skipped, noted };
}

/** The same set: the same presentation and the same rows (step, kind, what the wait was). */
export function sameRepairSet(open, proposal) {
  if (!open || !proposal) return false;
  const pres = (e) => (e.after && typeof e.after === 'object' ? (e.after.presentation_id ?? null) : null);
  if (pres(open) !== pres(proposal)) return false;
  const rows = (e) => (Array.isArray(e.corrections) ? e.corrections : []).map((c) => [String(c.step_id), String(c.kind), norm(c.was?.waiting_on)].join('\u0000')).sort().join('\n');
  return rows(open) === rows(proposal);
}

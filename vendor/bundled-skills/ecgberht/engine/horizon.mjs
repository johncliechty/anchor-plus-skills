// The horizon — the line under a project that says what is next, DERIVED from the plan (W3 of the steward revision,
// 2026-09-28; the synthesis R3; his answer Q1: "yes, that one line only").
//
// A pure derivation over the roadmap's projection: the declared focus (current_step_id; else the one pinned step;
// else the one active step — never a guess among several), then the open steps that FOLLOW it in the plan's order,
// done/parked/cancelled/dropped skipped, at most `n`. The line fits the strip's word cap by dropping the tail
// entries first, never by inventing words. Nothing here reads a model; nothing here writes — `verbUpdate --horizon`
// writes the result as a stamped instrument (the source event's seq and the focus it derived from).
import { STRIP_WORD_CAPS } from './write-authority.mjs';

export const HORIZON_CLOSED = Object.freeze(['done', 'parked', 'cancelled', 'dropped']);

function words(s) {
  const t = String(s ?? '').trim();
  return t ? t.split(/\s+/) : [];
}

function label(step) {
  const nav = step && typeof step.navigation === 'object' && step.navigation ? step.navigation : {};
  return String(nav.label || step.name || step.id || '').trim();
}

/** The focus: current_step_id when it names a step; else the one pinned step; else the one active step; else none. */
export function focusOf(projection, currentStepId) {
  const steps = Array.isArray(projection) ? projection.filter((s) => s && typeof s === 'object') : [];
  const cur = currentStepId != null ? String(currentStepId) : '';
  if (cur) {
    const found = steps.find((s) => String(s.id) === cur);
    return found ? { focus: found, reason: '' } : { focus: null, reason: `current_step_id ${cur} names no step in the roadmap` };
  }
  const pinned = steps.filter((s) => s.navigation && typeof s.navigation === 'object' && (s.navigation.pin || s.navigation.current));
  if (pinned.length === 1) return { focus: pinned[0], reason: '' };
  const active = steps.filter((s) => s.status === 'active');
  if (active.length === 1) return { focus: active[0], reason: '' };
  if (active.length > 1) return { focus: null, reason: `${active.length} steps are active and no current_step_id is set` };
  if (steps.some((s) => !HORIZON_CLOSED.includes(String(s.status || '')))) return { focus: null, reason: 'no step is active and no current_step_id is set' };
  return { focus: null, reason: 'every step is closed' };
}

/**
 * @param {object} o
 * @param {object[]} o.projection   the roadmap projection (id, name, status, navigation, due …)
 * @param {string|null} [o.current_step_id]
 * @param {number} [o.n=3]
 * @param {object|null} [o.last_event]  the roadmap's last event (seq, kind, step_id) — what the line follows
 * @param {string} [o.reason]  the trigger's word (accepted · produced · answered · refined · closed · tick)
 * @returns {{ok:true, focus:string, steps:string[], line:string, why:string} | {ok:false, reason:string}}
 */
export function deriveHorizon({ projection, current_step_id = null, n = 3, last_event = null, reason = '' } = {}) {
  const steps = Array.isArray(projection) ? projection.filter((s) => s && typeof s === 'object') : [];
  const { focus, reason: why_not } = focusOf(steps, current_step_id);
  if (!focus) return { ok: false, reason: why_not };
  // a focus already closed is never "next": the line starts at the first open step after it (else nothing is written)
  const out = HORIZON_CLOSED.includes(String(focus.status || '')) ? [] : [focus];
  let seen = false;
  for (const s of steps) {
    if (s === focus || String(s.id) === String(focus.id)) { seen = true; continue; }
    if (!seen || HORIZON_CLOSED.includes(String(s.status || ''))) continue;
    out.push(s);
    if (out.length >= Math.max(1, n | 0)) break;
  }
  if (!out.length) return { ok: false, reason: 'the focus step is closed and no open step follows it' };
  const cap = STRIP_WORD_CAPS.next_recommended;
  const compose = (list) => {
    const [first, ...rest] = list;
    return rest.length ? `${first}; then ${rest.join(', then ')}` : first;
  };
  // the line: "<focus>; then <next>, then <next>" — drop the tail entries beyond the first successor first; then, so
  // the step AFTER the one in hand survives (Grok W3), shorten the focus's own trailing words until one successor
  // fits; the focus alone is cut to the cap only when nothing else can fit
  let chosen = out.slice();
  let line = compose(chosen.map(label));
  while (chosen.length > 2 && words(line).length > cap) {
    chosen = chosen.slice(0, -1);
    line = compose(chosen.map(label));
  }
  if (chosen.length === 2 && words(line).length > cap) {
    const succ = label(chosen[1]);
    const budget = cap - words(succ).length - 1;   // "then" is the one joining word
    if (budget >= 1) {
      line = `${words(label(chosen[0])).slice(0, budget).join(' ')}; then ${succ}`;
    } else {
      chosen = [chosen[0]];
      line = compose(chosen.map(label));
    }
  }
  if (chosen.length === 1 && words(line).length > cap) line = words(line).slice(0, cap).join(' ');
  // why: the last event's OWN why (his or the turn's words), else "<kind> <step>" — never a maintainer stamp; on a
  // bare tick with nothing new the existing why stands (null = keep)
  let why = null;
  if (String(reason || '').trim() !== 'tick' || last_event) {
    const stepName = last_event && last_event.step_id ? label(steps.find((s) => String(s.id) === String(last_event.step_id)) || { name: last_event.step_id }) : '';
    const own = last_event ? String(last_event.why ?? (last_event.receipt && typeof last_event.receipt === 'object' ? last_event.receipt.why : '') ?? '').trim() : '';
    if (own) why = own;
    else if (last_event && last_event.kind) why = `${String(last_event.kind).replace(/_/g, ' ')}${stepName ? ` ${stepName}` : ''}`;
    if (why && words(why).length > STRIP_WORD_CAPS.why_next) why = words(why).slice(0, STRIP_WORD_CAPS.why_next).join(' ');
    if (String(reason || '').trim() === 'tick') why = null;
  }
  return { ok: true, focus: String(focus.id), steps: chosen.map((s) => String(s.id)), line, why };
}

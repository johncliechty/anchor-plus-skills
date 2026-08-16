/**
 * Wave 12 — Progressive elaboration at stage START (Master-Plan P5 / criterion 5).
 *
 * Detail arrives when a stage starts, never at scaffold time:
 *   - PURE commissionability predicate: named deliverable + acceptance sentence
 *     + ≥1 Face-anchored constraint with a provenance pointer
 *   - Failing the predicate emits a typed elaboration event whose targeted
 *     questions NAME THE MISSING PREDICATE ELEMENT (anti-stub: Oranges echo fails)
 *   - Research-shaped gaps OFFER a researchPrime commission via propose → confirm
 *     (never auto-runs)
 *   - Scaffold authoring demands nothing at stage-detail grain
 *   - Answers recorded as typed elaboration events joined to the step
 *
 * Event kinds (allow-list v3): elaboration_probe, elaboration_answer,
 * elaboration_decline, elaboration_offer_refused.
 *
 * Stdlib only. No host-absolute path literals.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { SPELLING } from './verbs.mjs';
import {
  appendRoadmapEvent,
  emptyRoadmap,
  loadProjectRoadmap,
  ROADMAP_FILE_NAME,
} from './roadmap.mjs';
import {
  appendRoadmapEventThroughSpine,
  assertEventKindAllowed,
  ROADMAP_EVENT_KINDS_VERSION,
  SPINE_EVENT_KINDS,
  SPINE_CODE,
} from './ledger-spine.mjs';
import {
  proposeBoundCommission,
  makeSkillsTableFixture,
} from './commission-proposal.mjs';

// ── Schema / constants ─────────────────────────────────────────────────────

export const ELABORATION_SCHEMA = 'ecgberht-progressive-elaboration-v0';

/** Predicate element ids — questions MUST name these (anti-stub). */
export const PREDICATE_ELEMENTS = Object.freeze([
  'named_deliverable',
  'acceptance_sentence',
  'face_anchored_constraint',
]);

/** Human labels used inside targeted questions (must appear in the question text). */
export const PREDICATE_ELEMENT_LABELS = Object.freeze({
  named_deliverable: 'named deliverable',
  acceptance_sentence: 'acceptance sentence',
  face_anchored_constraint: 'Face-anchored constraint',
});

/** Wave-12 elaboration event kinds (allow-list v3). */
export const ELABORATION_EVENT_KINDS = Object.freeze([
  'elaboration_probe',
  'elaboration_answer',
  'elaboration_decline',
  'elaboration_offer_refused',
]);

/** Generic scaffold done_when shapes that do NOT count as an acceptance sentence. */
const GENERIC_ACCEPTANCE_RE =
  /^stage\s+['"].*['"]\s+meets\s+its\s+done-when\.?$/i;

/** Research-shaped gap signals (step type, skill, or language). */
const RESEARCH_SHAPE_RE =
  /\b(research|investigate|literature|survey|what\s+is\s+known|open\s+question|unknown\s+fact|explore\s+the\s+space)\b/i;

// ── Failure states (elaboration surface — plan table) ──────────────────────

export const ELAB_CODE = Object.freeze({
  NO_QUESTIONS: 'ELAB_NO_QUESTIONS',
  DECLINED: 'ELAB_DECLINED',
  OFFER_REFUSED: 'ELAB_OFFER_REFUSED',
  STORE_UNREADABLE: 'ELAB_STORE_UNREADABLE',
  NONE_YET: 'ELAB_NONE_YET',
  STATE_UNKNOWN: 'ELAB_STATE_UNKNOWN',
});

export const ELAB_TEXT = Object.freeze({
  [ELAB_CODE.NO_QUESTIONS]:
    'Stage passes the readiness predicate — no elaboration needed (named, not blank).',
  [ELAB_CODE.DECLINED]:
    'Elaboration declined — stage remains coarse; commission will re-check readiness.',
  [ELAB_CODE.OFFER_REFUSED]:
    'Offered research commission declined — recorded; stage can still be elaborated by hand.',
  [ELAB_CODE.STORE_UNREADABLE]:
    'Elaboration store unreadable — questions withheld rather than invented.',
  [ELAB_CODE.NONE_YET]: 'No stages started yet.',
  [ELAB_CODE.STATE_UNKNOWN]:
    'Stage readiness unknown — reported as unknown.',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function elabFailure(code, extra = {}) {
  const text = ELAB_TEXT[code] ?? ELAB_TEXT[ELAB_CODE.STATE_UNKNOWN];
  return {
    ok: false,
    error: extra.error ?? String(code).toLowerCase().replace(/_/g, '-'),
    code,
    status: code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    spelling: SPELLING,
    elaboration: true,
    run_started: false,
    processes_launched: 0,
    ...extra,
  };
}

/**
 * Full failure-state table (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function elaborationFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'no-questions-derivable',
      status_code: ELAB_CODE.NO_QUESTIONS,
      user_text: ELAB_TEXT[ELAB_CODE.NO_QUESTIONS],
    }),
    Object.freeze({
      state: 'elaboration-declined',
      status_code: ELAB_CODE.DECLINED,
      user_text: ELAB_TEXT[ELAB_CODE.DECLINED],
    }),
    Object.freeze({
      state: 'offered-commission-refused',
      status_code: ELAB_CODE.OFFER_REFUSED,
      user_text: ELAB_TEXT[ELAB_CODE.OFFER_REFUSED],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: ELAB_CODE.STORE_UNREADABLE,
      user_text: ELAB_TEXT[ELAB_CODE.STORE_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid',
      status_code: ELAB_CODE.NONE_YET,
      user_text: ELAB_TEXT[ELAB_CODE.NONE_YET],
    }),
    Object.freeze({
      state: 'unknown',
      status_code: ELAB_CODE.STATE_UNKNOWN,
      user_text: ELAB_TEXT[ELAB_CODE.STATE_UNKNOWN],
    }),
  ]);
}

// ── Pure helpers ───────────────────────────────────────────────────────────

function nonEmpty(v) {
  return typeof v === 'string' && v.trim() !== '';
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Allow-list version bump proof for Wave 12 tests.
 * @returns {{ ok: boolean, version: number, elaboration_kinds: string[], admitted: boolean, missing: string[] }}
 */
export function assertElaborationKindsAdmitted() {
  const missing = [];
  for (const k of ELABORATION_EVENT_KINDS) {
    const gate = assertEventKindAllowed(k);
    if (!gate.ok) missing.push(k);
  }
  return {
    ok: missing.length === 0 && ROADMAP_EVENT_KINDS_VERSION >= 3,
    version: ROADMAP_EVENT_KINDS_VERSION,
    elaboration_kinds: [...ELABORATION_EVENT_KINDS],
    admitted: missing.length === 0,
    missing,
    spine_kinds: [...SPINE_EVENT_KINDS],
  };
}

/**
 * Named deliverable present and non-blank (not merely the step title).
 * @param {object} detail
 */
export function hasNamedDeliverable(detail = {}) {
  return nonEmpty(detail.named_deliverable ?? detail.deliverable);
}

/**
 * Acceptance sentence present — excludes generic scaffold done_when placeholders.
 * @param {object} detail
 */
export function hasAcceptanceSentence(detail = {}) {
  const raw =
    detail.acceptance_sentence ??
    detail.acceptance ??
    null;
  if (nonEmpty(raw)) {
    const t = String(raw).trim();
    if (GENERIC_ACCEPTANCE_RE.test(t)) return false;
    return t.length >= 8;
  }
  // A non-generic done_when may stand in only when explicitly marked as acceptance.
  if (detail.done_when_is_acceptance === true && nonEmpty(detail.done_when)) {
    const t = String(detail.done_when).trim();
    return !GENERIC_ACCEPTANCE_RE.test(t) && t.length >= 8;
  }
  return false;
}

/**
 * ≥1 Face-anchored constraint with a provenance pointer into source_text.
 * @param {object} detail
 */
export function hasFaceAnchoredConstraint(detail = {}) {
  const list = Array.isArray(detail.face_constraints)
    ? detail.face_constraints
    : detail.face_anchored_constraint
      ? [detail.face_anchored_constraint]
      : [];
  for (const c of list) {
    if (!c || typeof c !== 'object') continue;
    const text = c.text ?? c.constraint ?? c.value;
    const prov = c.provenance ?? c.provenance_pointer ?? null;
    if (!nonEmpty(text)) continue;
    if (!prov || typeof prov !== 'object') continue;
    if (!nonEmpty(prov.source_hash)) continue;
    const start = Number(prov.start);
    const end = Number(prov.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) continue;
    return true;
  }
  return false;
}

/**
 * PURE commissionability predicate (Master-Plan P5).
 * Zero I/O, zero model, zero spend.
 *
 * @param {object} detail step detail (deliverable / acceptance / face constraints)
 * @returns {{
 *   ready: boolean,
 *   missing: Array<{ element: string, label: string, question: string }>,
 *   present: string[],
 *   pure: true,
 *   model_calls: 0
 * }}
 */
export function evaluateCommissionability(detail = {}) {
  const missing = [];
  const present = [];

  if (hasNamedDeliverable(detail)) {
    present.push('named_deliverable');
  } else {
    missing.push({
      element: 'named_deliverable',
      label: PREDICATE_ELEMENT_LABELS.named_deliverable,
      question: targetedQuestionFor('named_deliverable', detail),
    });
  }

  if (hasAcceptanceSentence(detail)) {
    present.push('acceptance_sentence');
  } else {
    missing.push({
      element: 'acceptance_sentence',
      label: PREDICATE_ELEMENT_LABELS.acceptance_sentence,
      question: targetedQuestionFor('acceptance_sentence', detail),
    });
  }

  if (hasFaceAnchoredConstraint(detail)) {
    present.push('face_anchored_constraint');
  } else {
    missing.push({
      element: 'face_anchored_constraint',
      label: PREDICATE_ELEMENT_LABELS.face_anchored_constraint,
      question: targetedQuestionFor('face_anchored_constraint', detail),
    });
  }

  return {
    ready: missing.length === 0,
    missing,
    present,
    pure: true,
    model_calls: 0,
    zero_model: true,
    predicate: 'commissionability-v0',
    schema: ELABORATION_SCHEMA,
  };
}

/**
 * Targeted question that NAMES the missing predicate element.
 * Must not merely echo Oranges annotation text.
 *
 * @param {string} element PREDICATE_ELEMENTS value
 * @param {object} [detail]
 * @returns {string}
 */
export function targetedQuestionFor(element, detail = {}) {
  const label = PREDICATE_ELEMENT_LABELS[element] ?? element;
  const stepName = nonEmpty(detail.name) ? String(detail.name).trim() : 'this stage';
  switch (element) {
    case 'named_deliverable':
      return (
        `What is the named deliverable for stage "${stepName}"? ` +
        `Name the concrete artifact or output (the missing named deliverable).`
      );
    case 'acceptance_sentence':
      return (
        `What is the acceptance sentence for stage "${stepName}"? ` +
        `State the missing acceptance sentence that decides when the stage is done ` +
        `(not a generic done-when placeholder).`
      );
    case 'face_anchored_constraint':
      return (
        `Which Face-anchored constraint binds stage "${stepName}"? ` +
        `Provide at least one Face-anchored constraint with a provenance pointer ` +
        `into source_text (the missing face-anchored constraint element).`
      );
    default:
      return `Stage "${stepName}" is missing predicate element: ${label}.`;
  }
}

/**
 * Anti-stub gate: a question must name the missing element; Oranges echo fails.
 *
 * @param {string} question
 * @param {string} element
 * @param {string[]} [oranges]
 * @returns {{ ok: boolean, names_element: boolean, is_oranges_echo: boolean, reason?: string }}
 */
export function assertQuestionNamesMissingElement(question, element, oranges = []) {
  const q = String(question ?? '');
  const label = PREDICATE_ELEMENT_LABELS[element] ?? element;
  const elementToken = String(element).replace(/_/g, ' ');
  const names_element =
    q.toLowerCase().includes(String(label).toLowerCase()) ||
    q.toLowerCase().includes(elementToken.toLowerCase()) ||
    q.toLowerCase().includes(String(element).toLowerCase());

  const orangeList = Array.isArray(oranges) ? oranges.map(String) : [];
  const is_oranges_echo =
    orangeList.length > 0 &&
    orangeList.some((o) => {
      const t = o.trim();
      return t.length > 0 && (q === t || q.trim() === t || q.includes(t) && t.length > 20 && q.trim() === t.trim());
    }) &&
    !names_element;

  // Exact generic echo of a single orange without naming the element
  const exactEcho =
    orangeList.some((o) => o.trim().length > 0 && q.trim() === o.trim()) && !names_element;

  if (!names_element || is_oranges_echo || exactEcho) {
    return {
      ok: false,
      names_element,
      is_oranges_echo: is_oranges_echo || exactEcho,
      reason: exactEcho
        ? 'question is a generic echo of an Oranges annotation without naming the missing predicate element'
        : 'question does not name the missing predicate element',
      element,
      label,
      question: q,
    };
  }
  return {
    ok: true,
    names_element: true,
    is_oranges_echo: false,
    element,
    label,
    question: q,
  };
}

/**
 * Research-shaped gap detection (offers researchPrime, never auto-runs).
 * @param {object} detail
 * @param {object} [predicateResult]
 */
export function isResearchShapedGap(detail = {}, predicateResult = null) {
  if (detail.research_shaped === true) return true;
  const stepType = String(detail.step_type ?? detail.type ?? '').toUpperCase();
  if (stepType === 'RESEARCH') return true;
  if (String(detail.skill ?? '').toLowerCase() === 'researchprime') return true;
  const blobs = [
    detail.name,
    detail.named_deliverable,
    detail.acceptance_sentence,
    detail.done_when,
    ...(Array.isArray(detail.oranges_annotations) ? detail.oranges_annotations : []),
    ...(Array.isArray(detail.oranges) ? detail.oranges : []),
  ]
    .filter((x) => x != null)
    .map(String)
    .join('\n');
  if (RESEARCH_SHAPE_RE.test(blobs)) return true;
  // Explicit research gap marker on missing elements
  if (predicateResult && Array.isArray(predicateResult.missing)) {
    if (detail.offer_research_on_gap === true && predicateResult.missing.length > 0) {
      return true;
    }
  }
  return false;
}

/**
 * Fold step_create + elaboration_* events into a commissionability detail object.
 * @param {object} roadmap
 * @param {string} stepId
 * @returns {{ ok: true, detail: object } | { ok: false, code: string, message: string }}
 */
export function reconstructStepDetail(roadmap, stepId) {
  if (!roadmap || typeof roadmap !== 'object') {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, { error: 'roadmap-missing' });
  }
  if (!nonEmpty(stepId)) {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, { error: 'step-id-required' });
  }
  const events = Array.isArray(roadmap.roadmap_events) ? roadmap.roadmap_events : [];
  const creates = events.filter(
    (e) => e && e.kind === 'step_create' && (e.step_id === stepId || e.id === stepId),
  );
  if (creates.length === 0) {
    // Projection-only step (unevented) — still reconstruct from projection
    const proj = (roadmap.roadmap_projection ?? []).find(
      (s) => s && (s.id === stepId || s.step_id === stepId),
    );
    if (!proj) {
      return elabFailure(ELAB_CODE.STATE_UNKNOWN, {
        error: 'step-not-found',
        step_id: stepId,
      });
    }
    return {
      ok: true,
      detail: {
        step_id: stepId,
        name: proj.name ?? null,
        done_when: proj.done_when ?? null,
        status: proj.status ?? null,
        oranges_annotations: [],
        named_deliverable: null,
        acceptance_sentence: null,
        face_constraints: [],
      },
    };
  }

  const base = creates[creates.length - 1];
  const detail = {
    step_id: stepId,
    name: base.name ?? null,
    done_when: base.done_when ?? null,
    status: base.status ?? null,
    step_type: base.step_type ?? null,
    oranges_annotations: Array.isArray(base.oranges_annotations)
      ? [...base.oranges_annotations]
      : [],
    named_deliverable: base.named_deliverable ?? base.deliverable ?? null,
    acceptance_sentence: base.acceptance_sentence ?? base.acceptance ?? null,
    face_constraints: Array.isArray(base.face_constraints)
      ? base.face_constraints.map((c) => ({ ...c }))
      : [],
    research_shaped: base.research_shaped === true,
    skill: base.skill ?? null,
  };

  for (const e of events) {
    if (!e || e.step_id !== stepId) continue;
    if (e.kind === 'elaboration_answer') {
      const answers = e.answers && typeof e.answers === 'object' ? e.answers : {};
      if (nonEmpty(answers.named_deliverable ?? answers.deliverable)) {
        detail.named_deliverable = String(
          answers.named_deliverable ?? answers.deliverable,
        ).trim();
      }
      if (nonEmpty(answers.acceptance_sentence ?? answers.acceptance)) {
        detail.acceptance_sentence = String(
          answers.acceptance_sentence ?? answers.acceptance,
        ).trim();
      }
      const fc =
        answers.face_constraints ??
        answers.face_anchored_constraint ??
        null;
      if (Array.isArray(fc)) {
        detail.face_constraints = fc.map((c) => ({ ...c }));
      } else if (fc && typeof fc === 'object') {
        detail.face_constraints = [{ ...fc }];
      }
      if (answers.research_shaped === true) detail.research_shaped = true;
      if (nonEmpty(answers.step_type)) detail.step_type = answers.step_type;
    }
  }

  return { ok: true, detail };
}

/**
 * Derive targeted questions from a predicate result (anti-stub validated).
 * @param {ReturnType<typeof evaluateCommissionability>} predicate
 * @param {object} [detail]
 */
export function deriveTargetedQuestions(predicate, detail = {}) {
  const oranges = detail.oranges_annotations ?? detail.oranges ?? [];
  const questions = [];
  for (const m of predicate.missing ?? []) {
    const q = m.question ?? targetedQuestionFor(m.element, detail);
    const gate = assertQuestionNamesMissingElement(q, m.element, oranges);
    if (!gate.ok) {
      // Rebuild from the canonical template — never pass an Oranges echo
      const rebuilt = targetedQuestionFor(m.element, detail);
      const recheck = assertQuestionNamesMissingElement(rebuilt, m.element, oranges);
      questions.push({
        element: m.element,
        label: m.label ?? PREDICATE_ELEMENT_LABELS[m.element],
        question: rebuilt,
        names_missing_element: recheck.ok,
        anti_stub: recheck,
      });
    } else {
      questions.push({
        element: m.element,
        label: m.label ?? PREDICATE_ELEMENT_LABELS[m.element],
        question: q,
        names_missing_element: true,
        anti_stub: gate,
      });
    }
  }
  return questions;
}

// ── Stage-start hook ───────────────────────────────────────────────────────

/**
 * Enter a scaffolded step: run the pure predicate and emit a typed probe event.
 * Research-shaped gaps OFFER researchPrime via propose → confirm (nothing runs).
 *
 * @param {string} projectPath
 * @param {{
 *   step_id: string,
 *   who?: string|object,
 *   client_event_id?: string,
 *   at?: string,
 *   skills_table?: object,
 *   prefs?: object,
 *   root?: string,
 *   skip_precondition?: boolean,
 *   offer_research?: boolean,
 * }} opts
 */
export function startStage(projectPath, opts = {}) {
  const step_id = opts.step_id;
  if (!nonEmpty(step_id)) {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, { error: 'step-id-required' });
  }

  let loaded;
  try {
    loaded = loadProjectRoadmap(projectPath);
  } catch (e) {
    return elabFailure(ELAB_CODE.STORE_UNREADABLE, {
      error: 'backing-store-unreadable',
      detail: String(e?.message ?? e),
    });
  }
  if (!loaded) {
    return elabFailure(ELAB_CODE.STORE_UNREADABLE, {
      error: 'backing-store-unreadable',
    });
  }
  if (loaded.ok === false) {
    // Unreadable / parse failure — never invent questions
    return elabFailure(ELAB_CODE.STORE_UNREADABLE, {
      error: 'backing-store-unreadable',
      detail: loaded.message ?? loaded.error,
    });
  }
  if (!loaded.exists || !loaded.roadmap) {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, {
      error: 'roadmap-missing',
      step_id,
    });
  }

  const roadmap = loaded.roadmap;
  const recon = reconstructStepDetail(roadmap, step_id);
  if (!recon.ok) return recon;

  // Allow stage-start callers to surface research shape / step type without a
  // prior write (e.g. host already knows the stage is RESEARCH).
  const detail = {
    ...recon.detail,
    ...(opts.step_type ? { step_type: opts.step_type } : {}),
    ...(opts.research_shaped != null
      ? { research_shaped: opts.research_shaped === true }
      : {}),
    ...(opts.skill ? { skill: opts.skill } : {}),
  };
  const predicate = evaluateCommissionability(detail);
  const at = opts.at ?? todayIso();
  const client_event_id =
    opts.client_event_id ??
    `elab-probe-${step_id}-${crypto.randomBytes(4).toString('hex')}`;

  // Ready → named no-questions state (not blank silence)
  if (predicate.ready) {
    const event = {
      kind: 'elaboration_probe',
      schema: ELABORATION_SCHEMA,
      step_id,
      stage_start: true,
      ready: true,
      status_code: ELAB_CODE.NO_QUESTIONS,
      questions: [],
      missing: [],
      present: predicate.present,
      offered_commission: null,
      who: opts.who ?? null,
      client_event_id,
      at,
    };
    const written = writeElaborationEvent(projectPath, event, opts);
    if (!written.ok) return written;
    return {
      ok: true,
      stage_start: true,
      step_id,
      ready: true,
      code: ELAB_CODE.NO_QUESTIONS,
      status_code: ELAB_CODE.NO_QUESTIONS,
      text: ELAB_TEXT[ELAB_CODE.NO_QUESTIONS],
      message: ELAB_TEXT[ELAB_CODE.NO_QUESTIONS],
      user_text: ELAB_TEXT[ELAB_CODE.NO_QUESTIONS],
      questions: [],
      missing: [],
      present: predicate.present,
      offered_commission: null,
      run_started: false,
      processes_launched: 0,
      event: written.event,
      roadmap: written.roadmap,
      predicate,
    };
  }

  const questions = deriveTargetedQuestions(predicate, detail);
  // Anti-stub: every question must name its missing element
  for (const q of questions) {
    if (!q.names_missing_element) {
      return elabFailure(ELAB_CODE.STATE_UNKNOWN, {
        error: 'anti-stub-question-failed',
        question: q,
      });
    }
  }

  const researchShaped =
    opts.offer_research !== false && isResearchShapedGap(detail, predicate);

  let offered_commission = null;
  if (researchShaped) {
    // OFFER only — proposeBoundCommission never launches
    const skills_table =
      opts.skills_table ??
      makeSkillsTableFixture(['researchPrime', 'Foreman', 'Crucible']);
    const proposal = proposeBoundCommission({
      roadmap,
      step_id,
      skill: 'researchPrime',
      step_type: 'RESEARCH',
      depth_cell: opts.depth_cell ?? 'LITE',
      prefs: opts.prefs ?? {
        coding_family: 'claude',
        review_family: 'gemini',
        default_cli: 'claude',
      },
      skills_table,
      skip_precondition: opts.skip_precondition !== false,
      root: opts.root,
      at,
      who: opts.who ?? 'ecgberht-steward',
    });
    if (proposal.ok) {
      offered_commission = {
        offered: true,
        skill: 'researchPrime',
        requires_confirm: true,
        confirmed: false,
        run_started: false,
        processes_launched: 0,
        proposal_hash: proposal.proposal_hash ?? null,
        proposal,
        path: 'propose-then-confirm',
        auto_run: false,
      };
    } else {
      // Still surface the offer intent even if proposal infrastructure refuses;
      // never invent a silent queue or auto-run.
      offered_commission = {
        offered: true,
        skill: 'researchPrime',
        requires_confirm: true,
        confirmed: false,
        run_started: false,
        processes_launched: 0,
        proposal_ok: false,
        proposal_error: proposal.code ?? proposal.error ?? 'proposal-refused',
        proposal,
        path: 'propose-then-confirm',
        auto_run: false,
      };
    }
  }

  const event = {
    kind: 'elaboration_probe',
    schema: ELABORATION_SCHEMA,
    step_id,
    stage_start: true,
    ready: false,
    status_code: researchShaped ? null : null,
    questions: questions.map((q) => ({
      element: q.element,
      label: q.label,
      question: q.question,
    })),
    missing: predicate.missing.map((m) => m.element),
    present: predicate.present,
    research_shaped: researchShaped,
    offered_commission: offered_commission
      ? {
          offered: true,
          skill: offered_commission.skill,
          requires_confirm: true,
          confirmed: false,
          run_started: false,
          proposal_hash: offered_commission.proposal_hash ?? null,
        }
      : null,
    who: opts.who ?? null,
    client_event_id,
    at,
  };

  const written = writeElaborationEvent(projectPath, event, opts);
  if (!written.ok) return written;

  return {
    ok: true,
    stage_start: true,
    step_id,
    ready: false,
    questions,
    missing: predicate.missing,
    present: predicate.present,
    research_shaped: researchShaped,
    offered_commission,
    run_started: false,
    processes_launched: 0,
    nothing_runs_until_confirmed: true,
    event: written.event,
    roadmap: written.roadmap,
    predicate,
    message: researchShaped
      ? 'Stage needs elaboration; researchPrime commission OFFERED via propose → confirm (nothing runs until confirmed).'
      : 'Stage needs elaboration; targeted questions name each missing predicate element.',
  };
}

/**
 * Record answers as a typed elaboration_answer event joined to the step.
 * @param {string} projectPath
 * @param {{
 *   step_id: string,
 *   answers: {
 *     named_deliverable?: string,
 *     acceptance_sentence?: string,
 *     face_constraints?: object[]|object,
 *     face_anchored_constraint?: object,
 *   },
 *   who?: string|object,
 *   client_event_id?: string,
 *   at?: string,
 * }} opts
 */
export function recordElaborationAnswers(projectPath, opts = {}) {
  const step_id = opts.step_id;
  if (!nonEmpty(step_id)) {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, { error: 'step-id-required' });
  }
  const answers = opts.answers && typeof opts.answers === 'object' ? opts.answers : {};
  const at = opts.at ?? todayIso();
  const client_event_id =
    opts.client_event_id ??
    `elab-answer-${step_id}-${crypto.randomBytes(4).toString('hex')}`;

  const event = {
    kind: 'elaboration_answer',
    schema: ELABORATION_SCHEMA,
    step_id,
    answers: {
      named_deliverable: answers.named_deliverable ?? answers.deliverable ?? null,
      acceptance_sentence:
        answers.acceptance_sentence ?? answers.acceptance ?? null,
      face_constraints: normalizeFaceConstraints(answers),
    },
    joined_to_step: true,
    who: opts.who ?? null,
    client_event_id,
    at,
  };

  const written = writeElaborationEvent(projectPath, event, opts);
  if (!written.ok) return written;

  // Re-evaluate readiness after answers land
  const recon = reconstructStepDetail(written.roadmap, step_id);
  const predicate = recon.ok
    ? evaluateCommissionability(recon.detail)
    : { ready: false, missing: [], present: [] };

  return {
    ok: true,
    step_id,
    answers: event.answers,
    joined_to_step: true,
    event: written.event,
    roadmap: written.roadmap,
    predicate,
    ready: predicate.ready === true,
    message: 'Elaboration answers recorded as typed event joined to the step.',
  };
}

/**
 * Decline elaboration — stage remains coarse; commission will re-check readiness.
 * @param {string} projectPath
 * @param {{ step_id: string, who?: string|object, client_event_id?: string, at?: string }} opts
 */
export function declineElaboration(projectPath, opts = {}) {
  const step_id = opts.step_id;
  if (!nonEmpty(step_id)) {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, { error: 'step-id-required' });
  }
  const at = opts.at ?? todayIso();
  const client_event_id =
    opts.client_event_id ??
    `elab-decline-${step_id}-${crypto.randomBytes(4).toString('hex')}`;
  const event = {
    kind: 'elaboration_decline',
    schema: ELABORATION_SCHEMA,
    step_id,
    status_code: ELAB_CODE.DECLINED,
    who: opts.who ?? null,
    client_event_id,
    at,
  };
  const written = writeElaborationEvent(projectPath, event, opts);
  if (!written.ok) return written;
  return {
    ok: true,
    declined: true,
    step_id,
    code: ELAB_CODE.DECLINED,
    status_code: ELAB_CODE.DECLINED,
    text: ELAB_TEXT[ELAB_CODE.DECLINED],
    message: ELAB_TEXT[ELAB_CODE.DECLINED],
    user_text: ELAB_TEXT[ELAB_CODE.DECLINED],
    event: written.event,
    roadmap: written.roadmap,
    run_started: false,
  };
}

/**
 * Refuse an offered researchPrime commission — recorded; hand elaboration still open.
 * @param {string} projectPath
 * @param {{ step_id: string, who?: string|object, client_event_id?: string, at?: string, proposal_hash?: string }} opts
 */
export function refuseOfferedCommission(projectPath, opts = {}) {
  const step_id = opts.step_id;
  if (!nonEmpty(step_id)) {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, { error: 'step-id-required' });
  }
  const at = opts.at ?? todayIso();
  const client_event_id =
    opts.client_event_id ??
    `elab-offer-refuse-${step_id}-${crypto.randomBytes(4).toString('hex')}`;
  const event = {
    kind: 'elaboration_offer_refused',
    schema: ELABORATION_SCHEMA,
    step_id,
    status_code: ELAB_CODE.OFFER_REFUSED,
    skill: 'researchPrime',
    proposal_hash: opts.proposal_hash ?? null,
    who: opts.who ?? null,
    client_event_id,
    at,
  };
  const written = writeElaborationEvent(projectPath, event, opts);
  if (!written.ok) return written;
  return {
    ok: true,
    offer_refused: true,
    step_id,
    code: ELAB_CODE.OFFER_REFUSED,
    status_code: ELAB_CODE.OFFER_REFUSED,
    text: ELAB_TEXT[ELAB_CODE.OFFER_REFUSED],
    message: ELAB_TEXT[ELAB_CODE.OFFER_REFUSED],
    user_text: ELAB_TEXT[ELAB_CODE.OFFER_REFUSED],
    event: written.event,
    roadmap: written.roadmap,
    run_started: false,
    processes_launched: 0,
  };
}

/**
 * Surface-level summary: which stages have been started (probe events).
 * empty-but-valid vs unknown are separate.
 *
 * @param {string} projectPath
 */
export function listStageStarts(projectPath) {
  let loaded;
  try {
    loaded = loadProjectRoadmap(projectPath);
  } catch (e) {
    return elabFailure(ELAB_CODE.STORE_UNREADABLE, {
      error: 'backing-store-unreadable',
      detail: String(e?.message ?? e),
    });
  }
  if (!loaded) {
    return elabFailure(ELAB_CODE.STORE_UNREADABLE, {
      error: 'backing-store-unreadable',
    });
  }
  if (loaded.ok === false) {
    return elabFailure(ELAB_CODE.STORE_UNREADABLE, {
      error: 'backing-store-unreadable',
      detail: loaded.message ?? loaded.error,
    });
  }
  if (!loaded.exists || !loaded.roadmap) {
    return {
      ok: true,
      code: ELAB_CODE.NONE_YET,
      status_code: ELAB_CODE.NONE_YET,
      text: ELAB_TEXT[ELAB_CODE.NONE_YET],
      message: ELAB_TEXT[ELAB_CODE.NONE_YET],
      user_text: ELAB_TEXT[ELAB_CODE.NONE_YET],
      starts: [],
      count: 0,
    };
  }
  const roadmap = loaded.roadmap;
  const events = Array.isArray(roadmap.roadmap_events) ? roadmap.roadmap_events : [];
  const starts = events.filter((e) => e && e.kind === 'elaboration_probe' && e.stage_start);
  if (starts.length === 0) {
    return {
      ok: true,
      code: ELAB_CODE.NONE_YET,
      status_code: ELAB_CODE.NONE_YET,
      text: ELAB_TEXT[ELAB_CODE.NONE_YET],
      message: ELAB_TEXT[ELAB_CODE.NONE_YET],
      user_text: ELAB_TEXT[ELAB_CODE.NONE_YET],
      starts: [],
      count: 0,
    };
  }
  return {
    ok: true,
    code: null,
    starts: starts.map((e) => ({
      step_id: e.step_id,
      ready: e.ready === true,
      missing: e.missing ?? [],
      offered_commission: e.offered_commission ?? null,
      seq: e.seq,
    })),
    count: starts.length,
  };
}

// ── Scaffold-time-demands-nothing ──────────────────────────────────────────

/**
 * Authoring must not raise stage-detail questions before stage start.
 * Call after propose/confirm scaffolding (or over any authoring result).
 *
 * @param {object} authoringResult propose/confirm/describeAndConfirm result
 * @param {object} [roadmap] optional roadmap to scan for premature elaboration events
 * @returns {{ ok: boolean, stage_detail_questions: number, premature_events: object[], message: string }}
 */
export function assertScaffoldingDemandsNoStageDetail(authoringResult = {}, roadmap = null) {
  const premature = [];
  const questions = [];

  // Result body must not carry stage-detail elaboration questions
  const resultQuestions = collectQuestionLike(authoringResult);
  for (const q of resultQuestions) {
    if (looksLikeStageDetailQuestion(q)) {
      questions.push(q);
    }
  }

  const rm =
    roadmap ??
    authoringResult.roadmap ??
    authoringResult.confirmation?.roadmap ??
    null;
  const events = Array.isArray(rm?.roadmap_events) ? rm.roadmap_events : [];
  for (const e of events) {
    if (!e) continue;
    if (ELABORATION_EVENT_KINDS.includes(e.kind)) {
      premature.push(e);
    }
  }

  // Proposal steps may carry oranges, never elaboration questions
  const proposal = authoringResult.proposal ?? null;
  if (proposal && Array.isArray(proposal.steps)) {
    for (const s of proposal.steps) {
      if (Array.isArray(s.elaboration_questions) && s.elaboration_questions.length) {
        questions.push(...s.elaboration_questions);
      }
      if (s.stage_detail_demanded === true) {
        questions.push('stage_detail_demanded');
      }
    }
  }

  const ok = premature.length === 0 && questions.length === 0;
  return {
    ok,
    stage_detail_questions: questions.length,
    premature_events: premature,
    premature_kinds: premature.map((e) => e.kind),
    questions,
    message: ok
      ? 'Scaffolding authoring demanded no stage-level detail (progressive elaboration deferred to stage start).'
      : 'Scaffolding authoring raised stage-level detail before stage start — criterion 5 violated.',
  };
}

/**
 * Structural proof: scaffolding source must not import progressive-elaboration
 * or emit stage-detail questions at compile time.
 * @param {string} scaffoldingSourceText
 */
export function assertScaffoldSourceDemandsNoStageDetail(scaffoldingSourceText) {
  const src = String(scaffoldingSourceText ?? '');
  const hits = [];
  if (/progressive-elaboration/.test(src)) {
    hits.push('imports-or-names-progressive-elaboration');
  }
  if (/startStage\s*\(/.test(src)) {
    hits.push('calls-startStage');
  }
  if (/evaluateCommissionability\s*\(/.test(src)) {
    hits.push('calls-evaluateCommissionability');
  }
  if (/elaboration_probe/.test(src)) {
    hits.push('emits-elaboration_probe');
  }
  return {
    ok: hits.length === 0,
    hits,
    message:
      hits.length === 0
        ? 'Scaffolding source does not demand stage detail at authoring time.'
        : `Scaffolding source demands stage detail: ${hits.join(', ')}`,
  };
}

// ── Internals ──────────────────────────────────────────────────────────────

function normalizeFaceConstraints(answers) {
  if (Array.isArray(answers.face_constraints)) {
    return answers.face_constraints.map((c) => ({ ...c }));
  }
  if (answers.face_anchored_constraint && typeof answers.face_anchored_constraint === 'object') {
    return [{ ...answers.face_anchored_constraint }];
  }
  if (
    answers.provenance &&
    nonEmpty(answers.constraint_text ?? answers.text)
  ) {
    return [
      {
        text: answers.constraint_text ?? answers.text,
        provenance: { ...answers.provenance },
      },
    ];
  }
  return [];
}

function writeElaborationEvent(projectPath, event, opts = {}) {
  const kindGate = assertEventKindAllowed(event.kind);
  if (!kindGate.ok) {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, {
      error: 'event-kind-not-allowed',
      kind: event.kind,
      spine: kindGate,
    });
  }

  // Prefer spine when a real project path is available
  if (nonEmpty(projectPath)) {
    try {
      const spine = appendRoadmapEventThroughSpine(projectPath, event, {
        at: event.at,
        project_id: opts.project_id,
        skip_index: opts.skip_index !== false,
      });
      if (!spine.ok) {
        if (
          spine.code === SPINE_CODE.LEDGER_UNREADABLE ||
          spine.error === 'backing-store-unreadable'
        ) {
          return elabFailure(ELAB_CODE.STORE_UNREADABLE, {
            error: 'backing-store-unreadable',
            spine,
          });
        }
        return elabFailure(ELAB_CODE.STATE_UNKNOWN, {
          error: spine.error ?? spine.code ?? 'spine-append-failed',
          spine,
        });
      }
      return {
        ok: true,
        event: spine.event,
        roadmap: spine.roadmap,
        spine: true,
      };
    } catch (e) {
      return elabFailure(ELAB_CODE.STORE_UNREADABLE, {
        error: 'backing-store-unreadable',
        detail: String(e?.message ?? e),
      });
    }
  }

  // Pure in-memory path (tests)
  const base = opts.roadmap ?? emptyRoadmap(opts.project_id ?? null);
  const pure = appendRoadmapEvent(base, event, { at: event.at });
  if (!pure.ok) {
    return elabFailure(ELAB_CODE.STATE_UNKNOWN, {
      error: pure.error ?? 'pure-append-failed',
      pure,
    });
  }
  return { ok: true, event: pure.event, roadmap: pure.roadmap, spine: false };
}

function collectQuestionLike(obj, out = [], depth = 0) {
  if (depth > 6 || obj == null) return out;
  if (typeof obj === 'string') {
    if (looksLikeStageDetailQuestion(obj)) out.push(obj);
    return out;
  }
  if (Array.isArray(obj)) {
    for (const v of obj) collectQuestionLike(v, out, depth + 1);
    return out;
  }
  if (typeof obj === 'object') {
    // Skip oranges_annotations — those are anticipatory prompts, not stage-detail demands
    for (const [k, v] of Object.entries(obj)) {
      if (k === 'oranges_annotations' || k === 'oranges' || k === 'default_prompts') {
        continue;
      }
      if (
        /elaboration_question|stage_detail|acceptance_sentence_question|named_deliverable_question/i.test(
          k,
        )
      ) {
        if (typeof v === 'string') out.push(v);
        else if (Array.isArray(v)) out.push(...v.map(String));
      }
      collectQuestionLike(v, out, depth + 1);
    }
  }
  return out;
}

function looksLikeStageDetailQuestion(s) {
  const t = String(s);
  // Heuristic: stage-detail grain names the three predicate elements as questions
  // raised during authoring (forbidden). Oranges stock prompts do not match.
  return (
    /\bnamed deliverable\b/i.test(t) ||
    /\bacceptance sentence\b/i.test(t) ||
    /\bFace-anchored constraint\b/i.test(t) ||
    /\bface.anchored constraint\b/i.test(t)
  );
}

export {
  ROADMAP_FILE_NAME,
  PREDICATE_ELEMENTS as COMMISSIONABILITY_ELEMENTS,
};

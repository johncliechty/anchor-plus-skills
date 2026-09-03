/**
 * TW7 — Standing up & honest states (wireframes v2.1 Screen 4).
 *
 * Three chambers, all spoken in the take-charge steward voice and all
 * write-nothing until John explicitly confirms:
 *
 *   S4-E1 New-ground chamber — "This project has no steward yet"; the
 *         steward asks for the goal and NEVER invents one. Face+Strip are
 *         created from the pack templates on confirm ONLY; "Not now" exits
 *         clean with zero writes.
 *   S4-E2 Capacity-unknown chamber — the hard-stop: unknown capacity can
 *         never silently admit a FULL run. Spoken refusal (no meters, no
 *         gauges) with EXACTLY three honest options:
 *         [LITE now] [Queue FULL] [Override (receipted)].
 *   S4-E3 Thin-evidence beat — missing evidence is spoken as the honest
 *         unknown plus a constructive offer (commission a fresh look),
 *         never padded into filler.
 *
 * Creation targets are checked realpath-first against the release freeze
 * trees (junction-aware — canary-pack runJunctionCanary law): standing up
 * a steward can never write into Anchor-release-v1.0/v1.1, even through
 * a junction alias.
 */

import fs from 'node:fs';
import { writeFileAtomicSync } from './durable-write.mjs';
import path from 'node:path';

import { SPELLING } from './verbs.mjs';
import { loadFaceTemplate, loadStripTemplate } from './load.mjs';
import {
  FACE_FILE_NAME,
  STRIP_FILE_NAME,
  loadProjectSurfaces,
  parseStrip,
} from './face-strip.mjs';
import {
  RECEIPT_SCHEMA_ID,
  buildOverrideReceipt,
  validateReceipt,
} from './receipt-validate.mjs';
import { UNKNOWN_ANSWER } from './brief.mjs';
import { realpathJunctionAware, freezeSegmentIn } from './canary-pack.mjs';
import { NOT_YET_COMMITTED, durabilityFor } from './portfolio/anchor-contract.mjs';

export const STAND_UP_SCHEMA_ID = 'ecgberht-stand-up-v0';

/** S4-E1 — the new-ground steward voice (mockup contract, verbatim intent). */
export const STAND_UP_VOICE =
  "This project has no steward yet. I can stand one up — but first, tell me " +
  "what you're trying to achieve here, in your own words. I won't invent a " +
  'goal for you.';

/** S4-E1 — exactly two actions; creation happens on confirm ONLY. */
export const STAND_UP_ACTIONS = Object.freeze([
  Object.freeze({ act: 'set_goal_with_me', label: 'Set the goal with me', primary: true }),
  Object.freeze({ act: 'not_now', label: 'Not now', primary: false }),
]);

/** S4-E2 — the three honest choices under unknown capacity. Closed set. */
export const CAPACITY_CHOICES = Object.freeze(['lite_now', 'queue_full', 'override']);

/** S4-E2 — locked labels (mockup contract: exactly these three options). */
export const CAPACITY_CHOICE_LABELS = Object.freeze({
  lite_now: 'Run a small version now',
  queue_full: 'Wait for a full run',
  override: 'Run it anyway (recorded)',
});

/** S4-E2 — the spoken refusal. No meter has ever existed here. */
export const CAPACITY_UNKNOWN_VOICE =
  "I don't actually know whether there is room for a full run right now — " +
  "capacity is unknown, and I won't guess or show you a made-up meter. " +
  'Your honest options:';

const nonEmpty = (v) => typeof v === 'string' && v.trim().length > 0;

// ---------------------------------------------------------------------------
// S4-E1 — new-ground chamber (empty project take-charge voice)
// ---------------------------------------------------------------------------

/**
 * True when the project already has a steward surface (Face or Strip).
 * @param {object|null} surfaces loadProjectSurfaces result (or injected)
 */
export function projectHasSteward(surfaces) {
  if (!surfaces || typeof surfaces !== 'object') return false;
  return Boolean(surfaces.face) || Boolean(surfaces.strip);
}

/**
 * S4-E1 — the new-ground chamber view model. Asks for the goal; invents
 * nothing; creates nothing (creation is confirmStandUp, on confirm only).
 * @param {{ project_id?: string|null, project_path?: string|null }} [opts]
 */
export function buildStandUpChamber(opts = {}) {
  const project =
    opts.project_id ??
    (nonEmpty(opts.project_path) ? path.basename(path.resolve(opts.project_path)) : null);
  return {
    schema: STAND_UP_SCHEMA_ID,
    spelling: SPELLING,
    screen: 'S4',
    chamber: 'new_ground',
    project_id: project,
    title: `${SPELLING} · new ground — ${project ?? 'this project'}`,
    voice: STAND_UP_VOICE,
    goal_prompt: 'What are you trying to achieve here? (your words become the North Star)',
    invented_goal: false,
    creates_on: 'confirm_only',
    creates: [FACE_FILE_NAME, STRIP_FILE_NAME],
    actions: STAND_UP_ACTIONS.map((a) => ({ ...a })),
    ledger_write: false,
  };
}

/**
 * Dispatcher: empty project → the stand-up chamber; a project with a
 * steward → null (the regular Seal chamber applies).
 * @param {{ project?: string|null, surfaces?: object|null }} [opts]
 */
export function assembleStandUp(opts = {}) {
  const surfaces =
    opts.surfaces !== undefined
      ? opts.surfaces
      : nonEmpty(opts.project)
        ? loadProjectSurfaces(opts.project)
        : null;
  // W15. Durability rides on BOTH branches, and that is the point rather than an oversight:
  // the branch with a standing steward is the branch that has receipts to lose, and a
  // surface that only mentioned durability when it had nothing to say would be silent in
  // exactly the state worth being loud about. Unacknowledged intents are never hidden.
  const durability = buildStandUpDurability(opts);
  if (projectHasSteward(surfaces)) {
    return { stand_up: false, chamber: null, has_steward: true, durability };
  }
  return {
    stand_up: true,
    has_steward: false,
    chamber: buildStandUpChamber({
      project_id: opts.project_id ?? null,
      project_path: opts.project ?? null,
    }),
    durability,
  };
}

/**
 * W15 — the stand-up's durability line.
 *
 * The stand-up says ONE thing about durability, in the same shape the High Seat says it, and
 * for an unacknowledged receipt that thing is the frozen phrase: state not yet committed. It
 * is not 'saving...', not 'pending', and not omitted, because each of those reads as "this
 * will be fine shortly" and none of them is a fact the engine is in a position to state.
 *
 * `opts.durability` is the read: events, a precomputed health object, or an index home. A
 * stand-up run with none of those gets the quiet block rather than an error - the screen
 * still renders in a project that was never registered.
 *
 * @param {{durability?: object}} [opts]
 * @returns {object} the durability block, with the stand-up's own one-line rendering
 */
export function buildStandUpDurability(opts = {}) {
  const block = durabilityFor(opts.durability ?? {});
  const pending = block.not_yet_committed ?? [];
  return {
    ...block,
    // One line for the stand-up to speak. The banner when durability is degraded; the phrase
    // when receipts are merely waiting; the honest all-clear otherwise.
    line: block.banner
      ?? (pending.length > 0
        ? `${NOT_YET_COMMITTED} - ${pending.length} project${pending.length === 1 ? '' : 's'} `
          + 'have receipts whose only copy is this disk.'
        : block.quiet_text),
  };
}

/**
 * "Not now" — the clean exit. Nothing is created, nothing is written,
 * no goal is remembered on the steward's behalf.
 */
export function standUpNotNow() {
  return {
    ok: true,
    applied: 'not_now',
    created: [],
    ledger_delta: [],
    invented_goal: false,
    voice: `Understood — no steward stands here yet. Say the word when you want one; I won't invent a goal in the meantime.`,
  };
}

/**
 * Fill the Face template's North star section with John's own words.
 * Only the placeholder blockquote + its replace-comment change; the rest of
 * the template (headings, section order) ships untouched.
 * @param {string} template templates/ECGBERHT.md text
 * @param {{ north_star: string, active_effort?: string|null }} fields
 */
export function fillFaceTemplate(template, fields = {}) {
  let out = String(template ?? '');
  out = out.replace(
    /> One paragraph: what this project is for when it is done\./,
    `> ${fields.north_star}`,
  );
  out = out.replace(/<!-- Replace with the whole-project concluding goal\. -->\r?\n?/, '');
  if (nonEmpty(fields.active_effort)) {
    out = out.replace(
      /- \*\*One-line pointer:\*\* <!-- what is live right now -->/,
      `- **One-line pointer:** ${fields.active_effort}`,
    );
  }
  return out;
}

/**
 * S4-E1 confirm — create Face+Strip from the pack templates. Confirm ONLY:
 * this is the single place stand-up creation happens, and it refuses when
 *   - the goal text is empty (the steward never invents one),
 *   - a Face or Strip already exists (never overwrite a standing steward),
 *   - the target's REALPATH lands in a release freeze tree (junction-aware
 *     — no v1.0 writes, even through an alias).
 * The new Strip carries a validated face_confirm receipt (who set the goal,
 * when) and honest defaults: capacity stays 'unknown' until proven.
 * @param {{
 *   project_path: string, north_star: string,
 *   project_id?: string|null, active_effort?: string|null,
 *   who?: string, when?: string,
 *   surfaces?: object|null, write?: boolean,
 *   face_template?: string, strip_template?: object,
 *   receipt_note?: string,
 * }} opts
 */
export function confirmStandUp(opts = {}) {
  if (!nonEmpty(opts.project_path)) {
    return { ok: false, error: 'missing_project_path', created: [] };
  }
  const goal = typeof opts.north_star === 'string' ? opts.north_star.trim() : '';
  if (!goal) {
    return {
      ok: false,
      error: 'empty_goal_refused',
      created: [],
      invented_goal: false,
      message: `No goal text — ${SPELLING} never invents a goal. Say what this project is for and I will stand the steward up.`,
    };
  }

  const target = path.resolve(opts.project_path);
  const rp = realpathJunctionAware(target);
  const frozenSegment = freezeSegmentIn(rp.path);
  if (frozenSegment) {
    return {
      ok: false,
      error: 'write_target_in_release_freeze',
      created: [],
      segment: frozenSegment,
      message:
        'Stand-up target resolves into a release freeze tree (realpath-before-prefix) — refusing to write.',
    };
  }

  const surfaces =
    opts.surfaces !== undefined ? opts.surfaces : loadProjectSurfaces(target);
  if (projectHasSteward(surfaces)) {
    return {
      ok: false,
      error: 'already_stood_up',
      created: [],
      message: 'A steward already stands here (Face or Strip present) — nothing overwritten.',
    };
  }

  const as_of = opts.when ?? new Date().toISOString().slice(0, 10);
  const who = nonEmpty(opts.who) ? opts.who : 'john';
  const project_id = nonEmpty(opts.project_id)
    ? opts.project_id
    : path.basename(target);

  const face_markdown = fillFaceTemplate(
    opts.face_template ?? loadFaceTemplate(),
    { north_star: goal, active_effort: opts.active_effort ?? null },
  );

  const receipt = {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'face_confirm',
    as_of,
    who,
    when: as_of,
    note: nonEmpty(opts.receipt_note)
      ? opts.receipt_note.trim()
      : 'stand-up: North Star set by the human, never invented',
  };
  const validated = validateReceipt(receipt);
  if (!validated.ok) {
    return { ...validated, created: [] };
  }

  const templateStrip = parseStrip(opts.strip_template ?? loadStripTemplate());
  const strip = {
    ...(templateStrip.ok ? templateStrip.strip : {}),
    project_id,
    as_of,
    phase: 'planning',
    active_effort: opts.active_effort ?? '',
    human_wait: 'none',
    // Honesty law: a freshly stood-up project has UNPROVEN capacity.
    capacity: 'unknown',
    receipts: [validated.receipt],
  };

  let written = false;
  if (opts.write !== false) {
    fs.mkdirSync(target, { recursive: true });
    writeFileAtomicSync(path.join(target, FACE_FILE_NAME), face_markdown);
    writeFileAtomicSync(
      path.join(target, STRIP_FILE_NAME),
      `${JSON.stringify(strip, null, 2)}\n`,
    );
    written = true;
  }

  return {
    ok: true,
    applied: 'set_goal_with_me',
    project_id,
    project_path: target,
    created: [FACE_FILE_NAME, STRIP_FILE_NAME],
    written,
    face_markdown,
    strip,
    receipt: validated.receipt,
    invented_goal: false,
    north_star: goal,
    voice: `Done — this project is set up. Your North Star is recorded in your own words. I still don't know how much capacity is free; the first run will tell us.`,
  };
}

// ---------------------------------------------------------------------------
// S4-E2 — capacity-unknown hard-stop (spoken, no meters, no silent FULL)
// ---------------------------------------------------------------------------

/**
 * S4-E2 — the capacity-unknown chamber view model: a spoken refusal with
 * EXACTLY the three honest options. No %-meter, no token gauge, ever.
 * @param {{ project_id?: string|null, projects?: string[], wants?: string }} [opts]
 */
export function buildCapacityUnknownChamber(opts = {}) {
  const projects = Array.isArray(opts.projects)
    ? opts.projects.filter(Boolean)
    : opts.project_id
      ? [opts.project_id]
      : [];
  return {
    schema: STAND_UP_SCHEMA_ID,
    spelling: SPELLING,
    screen: 'S4',
    chamber: 'capacity_unknown',
    capacity: 'unknown',
    hard_stop: true,
    silent_full_possible: false,
    projects,
    voice: CAPACITY_UNKNOWN_VOICE,
    options: CAPACITY_CHOICES.map((choice) => ({
      choice,
      label: CAPACITY_CHOICE_LABELS[choice],
      lands_as: choice === 'override' ? 'override_receipt' : null,
    })),
    fake_meters: false,
    percent_meter: false,
    token_gauge: false,
  };
}

/**
 * The hard-stop law itself: a FULL run is admitted only when capacity is
 * KNOWN, or when a schema-valid override receipt rides along. Unknown
 * capacity with no receipt is a structured refusal carrying the spoken
 * chamber — there is no code path that admits FULL silently.
 * @param {{ capacity?: string, override?: object|null, project_id?: string|null }} [opts]
 */
export function requestFullRun(opts = {}) {
  const capacity = opts.capacity === 'known' ? 'known' : 'unknown';
  if (capacity === 'known') {
    return { ok: true, admitted: 'FULL', capacity, silent: false, receipt: null };
  }

  const override = opts.override ?? null;
  if (override != null) {
    const v = validateReceipt(override);
    if (v.ok && v.receipt.kind === 'override') {
      return {
        ok: true,
        admitted: 'FULL',
        capacity,
        via: 'override_receipt',
        receipt: v.receipt,
        silent: false,
      };
    }
    return {
      ok: false,
      error: 'override_receipt_invalid',
      admitted: false,
      capacity,
      silent_full: false,
      issues: v.issues ?? [v.error],
      chamber: buildCapacityUnknownChamber(opts),
    };
  }

  return {
    ok: false,
    error: 'capacity_unknown_hard_stop',
    admitted: false,
    capacity,
    silent_full: false,
    spoken: true,
    chamber: buildCapacityUnknownChamber(opts),
  };
}

/**
 * Apply one of the three honest choices. Anything outside the closed set is
 * refused with the options restated — never quietly absorbed.
 *   lite_now   → a LITE run proceeds (allowed under unknown capacity).
 *   queue_full → the FULL demand queues; nothing admitted now.
 *   override   → who/why land as a validated override receipt, then FULL.
 * @param {string} choice
 * @param {{ who?: string, why?: string, when?: string, from?: string, to?: string, project_id?: string|null }} [fields]
 */
export function applyCapacityChoice(choice, fields = {}) {
  if (choice === 'lite_now') {
    return {
      ok: true,
      choice,
      admitted: 'LITE',
      receipt: null,
      voice: "A small run it is — safe even when capacity is unknown. A full run still waits until capacity is known, or until you choose to run it anyway.",
    };
  }
  if (choice === 'queue_full') {
    return {
      ok: true,
      choice,
      admitted: false,
      queued: 'FULL',
      receipt: null,
      voice: "Queued. The full run waits until capacity is known — I'll bring it up when there is honestly room for it.",
    };
  }
  if (choice === 'override') {
    if (!nonEmpty(fields.who) || !nonEmpty(fields.why)) {
      return {
        ok: false,
        choice,
        error: 'override_needs_who_and_why',
        admitted: false,
        message: 'Running it anyway gets recorded — I need to know who decided and why.',
      };
    }
    const receipt = buildOverrideReceipt({
      who: fields.who,
      when: fields.when ?? new Date().toISOString().slice(0, 10),
      why: fields.why,
      from: fields.from ?? 'blocked — capacity unknown',
      to: fields.to ?? 'FULL admit (human override)',
    });
    return requestFullRun({ ...fields, capacity: 'unknown', override: receipt });
  }
  return {
    ok: false,
    error: 'unknown_capacity_choice',
    admitted: false,
    choice: choice ?? null,
    options: [...CAPACITY_CHOICES],
    message: `Choose one of the three honest options: ${CAPACITY_CHOICES.map((c) => CAPACITY_CHOICE_LABELS[c]).join(' / ')}.`,
  };
}

// ---------------------------------------------------------------------------
// S4-E3 — thin-evidence beat (honest unknown + constructive offer)
// ---------------------------------------------------------------------------

/**
 * S4-E3 — missing evidence is spoken as unknown, with a constructive offer
 * (commission a fresh run through the compose-only commission path). Never
 * padded, never invented. When real evidence rides in, the beat simply
 * carries it and drops the offer.
 * @param {{ question?: string|null, answer?: *, unknown?: boolean }} [opts]
 */
export function buildThinEvidenceBeat(opts = {}) {
  const hasEvidence =
    opts.unknown === false && opts.answer != null && opts.answer !== UNKNOWN_ANSWER;
  if (hasEvidence) {
    return {
      beat: 'thin_evidence',
      screen: 'S4',
      question: opts.question ?? null,
      unknown: false,
      answer: opts.answer,
      padded: false,
      invented: false,
      offer: null,
      voice: 'This one is already on the record — no fresh run needed.',
    };
  }
  return {
    beat: 'thin_evidence',
    screen: 'S4',
    question: opts.question ?? null,
    unknown: true,
    answer: UNKNOWN_ANSWER,
    padded: false,
    invented: false,
    voice: `There is not much on record here — ${UNKNOWN_ANSWER}. I won't pad that into an answer. If you want one, I can start a fresh look.`,
    offer: {
      constructive: true,
      label: 'Start a fresh look',
      act: 'commission_propose',
      compiles_to: 'commission propose → confirm (compose-only; receipts on handback)',
    },
  };
}

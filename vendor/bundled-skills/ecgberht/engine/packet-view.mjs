/**
 * TW6 — Decision Packet view model (wireframes v2.1 Screen 3).
 *
 * Renders the TW2 brief packet (assembleBriefPacket / brief cache) as the
 * Screen 3 card stack: goal card ALWAYS first, position, since-you-looked
 * delta, the-thing-itself artifact card, and exactly ONE question whose
 * answer lands as a receipt that moves the Roadmap (single writer —
 * appendRoadmapEvent, never a projection rewrite).
 *
 * Mockup contract (MOCKUP-CONTRACT.md) element IDs implemented here:
 *   S3-E1 titlebar (seal icon · "Decision Packet · project — step" ·
 *         gathered-at stamp + coverage)
 *   S3-E2 "Remember the goal" card ALWAYS first (gold accent) — North Star +
 *         unchanged-since provenance
 *   S3-E3 "Where we are" (Roadmap position) + "Since you last looked"
 *         (post-seen delta) cards
 *   S3-E4 "The thing itself" — artifact display MVP: HTML best-effort inline;
 *         other artifacts open-in-viewer / walk-through; NEVER a bare path
 *         with no open action
 *   S3-E5 "What I need from you" — exactly ONE question + recommendation with
 *         reasons + [Lock it] [Lock with edits…] [Not yet — talk it through];
 *         answer = receipt that moves the Roadmap
 *   S3-E6 footer: deterministic gathering (W7) · provenance every card ·
 *         unknown cards when evidence missing
 */

import { SPELLING } from './verbs.mjs';
import { UNKNOWN_ANSWER } from './brief.mjs';
import { appendRoadmapEvent } from './roadmap.mjs';
import { appendRoadmapEventThroughSpine } from './ledger-spine.mjs';
import { SEAL_ICON_RELPATH } from './seal-chamber.mjs';

export const PACKET_VIEW_SCHEMA_ID = 'ecgberht-packet-view-v0';

/** S3-E6 footer stamp (verbatim intent from the v2.1 mockup). */
export const PACKET_FOOTER_STAMP =
  'everything here is gathered from the record · each card shows where it came from · missing evidence is shown as unknown, never guessed';

/** Artifact render modes — MVP set (later PE wave may widen inline types). */
export const ARTIFACT_RENDER_MODES = Object.freeze([
  'inline_html',
  'open_in_viewer',
  'walk_through',
]);

const nonEmpty = (v) => typeof v === 'string' && v.trim().length > 0;

// ---------------------------------------------------------------------------
// S3-E4 — artifact display MVP
// ---------------------------------------------------------------------------

/**
 * Classify an artifact reference for the display MVP: `.html`/`.htm` render
 * best-effort inline; everything else opens in a viewer or is walked through.
 * A bare path with no open action is NEVER a legal render.
 * @param {string|null} refPath artifact path (relative — never host-absolute)
 */
export function classifyArtifact(refPath) {
  if (!nonEmpty(refPath)) {
    return { kind: 'none', render: null, inline: false };
  }
  const lower = refPath.trim().toLowerCase();
  if (lower.endsWith('.html') || lower.endsWith('.htm')) {
    return { kind: 'html', render: 'inline_html', inline: true };
  }
  if (/\.(png|jpe?g|gif|svg|webp)$/.test(lower)) {
    return { kind: 'image', render: 'open_in_viewer', inline: false };
  }
  if (/\.(md|markdown|txt)$/.test(lower)) {
    return { kind: 'text', render: 'open_in_viewer', inline: false };
  }
  return { kind: 'other', render: 'open_in_viewer', inline: false };
}

/**
 * "The thing itself" card. No artifact on the record is an honest unknown
 * with a constructive offer — never invented filler, never a bare path-only
 * line with no way to open it.
 * @param {{ path?: string|null, title?: string|null, note?: string|null, provenance?: object[] }|null} artifact
 */
export function buildArtifactCard(artifact = null) {
  const refPath = artifact?.path ?? null;
  const classified = classifyArtifact(refPath);

  if (classified.kind === 'none') {
    return {
      card: 'the_thing_itself',
      house_subtitle: 'shown here, not just linked',
      unknown: true,
      voice: `${UNKNOWN_ANSWER} — nothing has been produced for this step yet. I can start a run to produce one.`,
      constructive_offer: 'commission_fresh_run',
      bare_path_only: false,
      actions: [],
      provenance: [],
    };
  }

  // MVP: html mockups best-effort inline; everything else opens in a viewer
  // or is walked through — the packet never strands John on a path string.
  return {
    card: 'the_thing_itself',
    house_subtitle: 'shown here, not just linked',
    unknown: false,
    title: artifact?.title ?? refPath,
    ref: refPath,
    note: artifact?.note ?? null,
    render: classified.render,
    inline:
      classified.render === 'inline_html'
        ? { mode: 'iframe', src: refPath, best_effort: true }
        : null,
    bare_path_only: false,
    actions: [
      { act: 'open_full', label: 'Open full', opens: refPath },
      { act: 'walk_me_through', label: 'Walk me through', mode: 'walk_through' },
    ],
    provenance: artifact?.provenance ?? [{ source: refPath, field: null }],
    mvp_note:
      'HTML files are shown inline where possible; other file types open in a viewer',
  };
}

// ---------------------------------------------------------------------------
// S3-E1 — titlebar
// ---------------------------------------------------------------------------

/**
 * Packet titlebar: seal icon · "Decision Packet · project — step" ·
 * gathered-at stamp + coverage ("N/M questions answerable").
 * @param {object} packet Phase-A brief packet
 * @param {{ project_id?: string|null, step?: string|null }} [opts]
 */
export function buildPacketTitlebar(packet, opts = {}) {
  const project =
    opts.project_id ?? packet?.goal_card?.project_id ?? packet?.project_path ?? 'this project';
  const step = opts.step ?? packet?.position?.current_step?.id ?? null;
  const coverage = packet?.coverage ?? null;
  return {
    icon: SEAL_ICON_RELPATH,
    title: `Decision summary · ${project}${nonEmpty(step) ? ` — ${step}` : ''}`,
    stamp: `gathered ${packet?.as_of ?? UNKNOWN_ANSWER}${
      coverage ? ` · ${coverage.answerable}/${coverage.total} questions answerable` : ''
    }`,
    coverage,
  };
}

// ---------------------------------------------------------------------------
// S3-E2 — goal card (ALWAYS first, gold accent)
// ---------------------------------------------------------------------------

/**
 * "Remember the goal" card — mandatory in every packet view; the packet's
 * goal_card is already honest (unknown when the Face is silent).
 * @param {object} packet
 */
export function buildGoalReminderCard(packet) {
  const card = packet?.goal_card ?? null;
  const unknown = card ? card.unknown === true : true;
  return {
    card: 'remember_the_goal',
    first: true,
    gold_accent: true,
    house_subtitle: 'North Star',
    goal: card && !unknown ? card.north_star : UNKNOWN_ANSWER,
    unknown,
    provenance: card?.provenance ?? [],
    unchanged_since: unknown ? null : (packet?.sources?.strip_as_of ?? null),
  };
}

// ---------------------------------------------------------------------------
// S3-E3 — "Where we are" + "Since you last looked"
// ---------------------------------------------------------------------------

/**
 * "Where we are" card from the packet's roadmap-aware position.
 * @param {object} packet
 */
export function buildWhereWeAreCard(packet) {
  const position = packet?.position ?? null;
  const unknown = !position || position.present !== true;
  const current = position?.current_step ?? null;
  return {
    card: 'where_we_are',
    house_subtitle: 'Project roadmap',
    unknown,
    position: unknown ? UNKNOWN_ANSWER : position,
    line: unknown
      ? UNKNOWN_ANSWER
      : `${current ? `${current.id ?? current.name} (${current.status})` : 'no current step'} · ${position.steps_done}/${position.steps_total} done`,
    provenance: unknown ? [] : [{ source: 'roadmap.json', field: 'roadmap_projection' }],
  };
}

/**
 * "Since you last looked" card from the packet's post-seen delta answer
 * (Q2 at project altitude). A silent record is honest unknown.
 * @param {object} packet
 */
export function buildSinceYouLookedCard(packet) {
  const answers = Array.isArray(packet?.answers) ? packet.answers : [];
  const q2 = answers.find((a) => a.id === 'Q2') ?? null;
  const unknown = !q2 || q2.unknown === true;
  return {
    card: 'since_you_last_looked',
    unknown,
    delta: unknown ? UNKNOWN_ANSWER : q2.answer,
    provenance: q2?.provenance ?? [],
    anchored_to_seen: !unknown,
  };
}

// ---------------------------------------------------------------------------
// S3-E5 — exactly ONE question
// ---------------------------------------------------------------------------

/**
 * "What I need from you" card — exactly ONE question, with the steward's
 * recommendation + reasons (honest unknown when Phase B never ran), and the
 * three closed responses. The answer lands as a receipt that moves the
 * Roadmap (see answerPacketQuestion).
 * @param {object} packet
 * @param {{ question?: string|null, step_id?: string|null }} [opts]
 */
export function buildQuestionCard(packet, opts = {}) {
  const step = opts.step_id ?? packet?.position?.current_step?.id ?? null;
  const question =
    nonEmpty(opts.question)
      ? opts.question.trim()
      : nonEmpty(step)
        ? `Does the gathered evidence settle ${step} well enough to lock it and move the Roadmap?`
        : 'Does the gathered evidence settle this decision well enough to lock it?';

  const rec = packet?.recommendation ?? null;
  const recommendation = nonEmpty(rec?.text)
    ? { text: rec.text, reasons: rec.reasons ?? [], unknown: false }
    : nonEmpty(rec)
      ? { text: rec, reasons: [], unknown: false }
      : {
          text: `recommendation: ${UNKNOWN_ANSWER}`,
          reasons: [],
          unknown: true,
        };

  return {
    card: 'what_i_need_from_you',
    question,
    question_count: 1,
    step_id: step,
    recommendation,
    reasons_available: recommendation.reasons.length > 0,
    actions: [
      { act: 'lock_it', label: 'Lock it', primary: true },
      { act: 'lock_with_edits', label: 'Lock with edits…' },
      { act: 'not_yet', label: 'Not yet — talk it through' },
    ],
    response_law: 'your answer lands as a decision receipt · roadmap advances or holds accordingly',
  };
}

/**
 * Apply John's answer: the response is a RECEIPT that moves the Roadmap via
 * the single writer (appendRoadmapEvent status_flip with { who, why }).
 * 'not_yet' holds — no event, no silent flip. UI state is never the store.
 * @param {{
 *   roadmap: object, step_id: string,
 *   decision: 'lock_it'|'lock_with_edits'|'not_yet',
 *   who: string, why?: string, to?: string, from?: string|null,
 *   edits?: string|null, at?: string,
 * }} opts
 */
export function answerPacketQuestion(opts = {}) {
  const decision = opts.decision;
  const who = opts.who ?? 'john';
  const why =
    opts.why ??
    (decision === 'lock_with_edits' && nonEmpty(opts.edits)
      ? `locked with edits: ${opts.edits}`
      : `decision packet response: ${decision}`);

  if (decision === 'not_yet') {
    return {
      ok: true,
      decision,
      moved: false,
      roadmap: opts.roadmap ?? null,
      receipt: null,
      message:
        'Not yet — the roadmap stays where it is. Nothing is saved until you decide.',
    };
  }

  if (decision !== 'lock_it' && decision !== 'lock_with_edits') {
    return {
      ok: false,
      error: 'unknown_packet_decision',
      spelling: SPELLING,
      decision: decision ?? null,
      allowed: ['lock_it', 'lock_with_edits', 'not_yet'],
    };
  }

  const receipt = { who, why };
  const flipEvent = {
    kind: 'status_flip',
    step_id: opts.step_id,
    from: opts.from ?? undefined,
    to: opts.to ?? 'done',
    at: opts.at,
    receipt,
    ...(opts.client_event_id ? { client_event_id: opts.client_event_id } : {}),
  };
  // Wave 6 live-writer migration (packet-view.mjs:304): production path uses spine
  // when project_path is supplied (high-seat-bridge --decide).
  const appended = opts.project_path
    ? appendRoadmapEventThroughSpine(opts.project_path, flipEvent, {
        seed: opts.roadmap,
        at: opts.at,
        project_id: opts.project_id,
        home: opts.home,
        skip_index: !opts.project_id,
      })
    : appendRoadmapEvent(opts.roadmap, flipEvent);
  if (!appended.ok) {
    return { ...appended, decision, moved: false };
  }
  return {
    ok: true,
    decision,
    moved: true,
    receipt: { kind: 'decision', ...receipt, step_id: opts.step_id, decision },
    roadmap: appended.roadmap,
    projection: appended.projection,
    single_writer: 'appendRoadmapEventThroughSpine',
    spine: Boolean(opts.project_path),
    sot_written: appended.sot_written === true,
    persisted: appended.persisted === true || appended.sot_written === true,
  };
}

// ---------------------------------------------------------------------------
// Assembly
// ---------------------------------------------------------------------------

/**
 * Assemble the whole Screen 3 packet view from an ALREADY-GATHERED packet.
 * This function does zero gathering of its own — the packet (live Phase A or
 * cached projection) arrives complete, which is what makes "opens with zero
 * further gathering" structural.
 * @param {object} packet Phase-A brief packet (or cache.packet)
 * @param {{ project_id?: string|null, step?: string|null, question?: string|null,
 *           artifact?: object|null, from_cache?: boolean }} [opts]
 */
export function assemblePacketView(packet, opts = {}) {
  const goal = buildGoalReminderCard(packet);
  const where = buildWhereWeAreCard(packet);
  const delta = buildSinceYouLookedCard(packet);
  const artifact = buildArtifactCard(opts.artifact ?? null);
  const question = buildQuestionCard(packet, {
    question: opts.question ?? null,
    step_id: opts.step ?? null,
  });

  const cards = [goal, where, delta, artifact, question];
  const unknown_cards = cards.filter((c) => c.unknown === true).map((c) => c.card);

  return {
    schema: PACKET_VIEW_SCHEMA_ID,
    spelling: SPELLING,
    screen: 'S3',
    titlebar: buildPacketTitlebar(packet, {
      project_id: opts.project_id ?? null,
      step: opts.step ?? null,
    }),
    cards,
    goal_card_present: true,
    goal_card_first: cards[0].card === 'remember_the_goal',
    question_count: 1,
    unknown_cards,
    padded_filler: false,
    further_gathering: false,
    from_cache: opts.from_cache === true,
    footer_stamp: PACKET_FOOTER_STAMP,
    write_authority: 'none',
  };
}

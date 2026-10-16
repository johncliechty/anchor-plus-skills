/**
 * TW5 — Seal chamber view model (wireframes v2.1 Screen 1, project altitude).
 *
 * The docked overlay on the Anchor-dev project dashboard renders THIS object;
 * the chamber never invents its own state. Everything is composed from the
 * same closed-verb bodies the CLI runs (status / brief / roadmap projection /
 * dialogue compile / seat hop), which is what makes CLI parity structural:
 * `ecgberht status --roots <proj>` and the overlay read the same pointer.
 *
 * Mockup contract (MOCKUP-CONTRACT.md) element IDs implemented here:
 *   S1-E1 titlebar (seal icon · steward-of title · seat switcher pill · quiet stamp)
 *   S1-E2 goal bar first (North Star + [Still the goal] [Refine it])
 *   S1-E3 Campaign Roadmap rail (✓ ◉ ⚑ ○ ⌂ from the typed ledger projection)
 *   S1-E4 ⏱ run block (about-line + run/now/last-green/seats rows)
 *   S1-E5 conversation main region — steward speaks first
 *   S1-E6 Grasscatcher offer beat (park it? → grasscatch receipt)
 *   S1-E7 seat-switch divider beat (receipted non-event)
 *   S1-E8 provenance recall beat (document chip + provenance, or honest unknown)
 *   S1-E9 saybox + footer stamp (talk → closed verbs + receipts · dialogue ephemeral)
 *   S1-N1 NEGATIVE: no verb menus / depth dials / rank tables / instrument
 *          card-sheets as the opening face (v1 instrument sheet is the
 *          superseded negative example).
 */

import { SPELLING } from './verbs.mjs';
import { verbStatus } from './verb-bodies.mjs';
import { assembleBriefPacket, UNKNOWN_ANSWER } from './brief.mjs';
import { compileUtterance, createDialogueStore } from './dialogue.mjs';
import { buildGrasscatchReceipt } from './receipt-validate.mjs';
import { titlebarSeatOptions, buildSeatHopReceipt } from './seat-hop.mjs';
import { ROADMAP_STEP_STATUSES } from './roadmap.mjs';

export const SEAL_CHAMBER_SCHEMA_ID = 'ecgberht-seal-chamber-v0';

/** Locked icon — relative to the Ecgberht skill root (never host-absolute). */
export const SEAL_ICON_RELPATH = 'assets/icons/ecgberht-project-seal.jpg';

/** Where the chamber mounts: docked overlay over the project dashboard. */
export const CHAMBER_MOUNT = Object.freeze({
  host: 'anchor-dev',
  surface: 'project_dashboard',
  presentation: 'docked_overlay',
  separate_window: false,
});

/**
 * Roadmap rail markers — Screen 1 legend, keyed by projection status.
 * Rendered ONLY from the typed ledger projection (roadmap.mjs), never from
 * Face prose or panel memory.
 */
export const ROADMAP_MARKERS = Object.freeze({
  done: '✓',
  active: '◉',
  waiting: '⚑',
  planned: '○',
  proposed: '○',
  parked: '⌂',
});

/** One-line substatus voice per state (house style, plain subtitles). */
export const ROADMAP_MARKER_LABELS = Object.freeze({
  done: 'done',
  active: 'running now',
  waiting: 'will need you',
  planned: 'upcoming',
  proposed: 'upcoming (proposed)',
  parked: 'parked idea',
});

/** S1-N1 — surfaces that must NOT appear as the opening face. */
export const CHAMBER_NEGATIVE_SURFACES = Object.freeze([
  'verb_menu',
  'depth_dial',
  'rank_table',
  'instrument_card_sheet',
]);

/** Footer stamp (verbatim intent from the v2.1 mockup). */
export const CHAMBER_FOOTER_STAMP =
  'your answers are saved · the chat itself is not kept · one shared history behind every view';

const nonEmpty = (v) => typeof v === 'string' && v.trim().length > 0;

// ---------------------------------------------------------------------------
// S1-E1 — titlebar
// ---------------------------------------------------------------------------

/**
 * Titlebar: real seal icon · "Ecgberht · steward of <project>" · seat
 * switcher pill (Anchor prefs) · quiet-since stamp.
 * @param {{ project_id?: string|null, strip?: object|null, prefs?: object|null, env?: object, prefsPath?: string|null }} [opts]
 */
export function buildTitlebar(opts = {}) {
  const strip = opts.strip ?? null;
  const project =
    opts.project_id ?? strip?.project_id ?? null;
  const seats = titlebarSeatOptions({
    prefs: opts.prefs,
    env: opts.env,
    prefsPath: opts.prefsPath,
  });
  // Honest quiet stamp: derived from the strip clock, never a fake timer.
  const quiet_since = strip?.as_of ?? null;
  return {
    icon: SEAL_ICON_RELPATH,
    title: `${SPELLING} · steward of ${nonEmpty(project) ? project : 'this project'}`,
    seat_switcher: {
      pill: `seat: ${seats.current ?? 'unknown'} ▾`,
      source: seats.source,
      current: seats.current,
      options: seats.options,
    },
    stamp: quiet_since
      ? `quiet since ${quiet_since} · everything receipted`
      : 'everything receipted',
  };
}

// ---------------------------------------------------------------------------
// S1-E2 — goal bar (first thing on the table)
// ---------------------------------------------------------------------------

/**
 * Goal bar from the brief packet's mandatory goal card. Unknown goal renders
 * as the honest unknown — never invented filler.
 * @param {object} packet Phase-A brief packet (assembleBriefPacket)
 */
export function buildGoalBar(packet) {
  const card = packet?.goal_card ?? null;
  return {
    first: true,
    label: 'North Star · the goal',
    goal: card && !card.unknown ? card.north_star : UNKNOWN_ANSWER,
    unknown: card ? card.unknown === true : true,
    provenance: card?.provenance ?? [],
    actions: [
      { act: 'still_the_goal', label: 'Still the goal', primary: true },
      { act: 'refine_goal', label: 'Refine it', primary: false },
    ],
  };
}

// ---------------------------------------------------------------------------
// S1-E3 — Campaign Roadmap rail (typed ledger projection only)
// ---------------------------------------------------------------------------

/**
 * One rail step from a typed projection step.
 * @param {object} step roadmap projection step
 */
export function railStepFromProjection(step = {}) {
  const status = ROADMAP_STEP_STATUSES.includes(step.status)
    ? step.status
    : 'proposed';
  const substatus =
    status === 'waiting' && nonEmpty(step.waiting_on)
      ? `${ROADMAP_MARKER_LABELS[status]} — ${step.waiting_on}`
      : status === 'active' && nonEmpty(step.commissioned_as)
        ? `${ROADMAP_MARKER_LABELS[status]} · ${step.commissioned_as}`
        : ROADMAP_MARKER_LABELS[status];
  return {
    id: step.id ?? null,
    name: step.name ?? null,
    status,
    marker: ROADMAP_MARKERS[status],
    substatus,
    done_when: step.done_when ?? null,
    waiting_on: step.waiting_on ?? null,
    commissioned_as: step.commissioned_as ?? null,
  };
}

/**
 * Roadmap rail from the status verb's roadmap block. Empty / invalid
 * projection is an HONEST GAP — the rail never invents steps ("my job to
 * track" is steward-tracked from the engine, not panel memory).
 * @param {{ present?: boolean, valid?: boolean|null, projection?: object[], gap?: string|null }} roadmap
 */
export function buildRoadmapRail(roadmap = {}) {
  const projection = Array.isArray(roadmap.projection) ? roadmap.projection : [];
  return {
    heading: 'Campaign Roadmap',
    house_subtitle: 'the major steps — my job to track',
    source: 'roadmap_projection',
    from_engine: true,
    panel_invented: false,
    steps: projection.map(railStepFromProjection),
    gap: roadmap.gap ?? null,
    honest_gap: projection.length === 0,
    provenance: 'roadmap: typed ledger object · status: Anchor job receipts',
  };
}

// ---------------------------------------------------------------------------
// S1-E4 — ⏱ run block
// ---------------------------------------------------------------------------

/**
 * ⏱ run block in the rail: about-line ("<step> is FOR: …") + run / now /
 * last-green / seats rows. Every row is sourced or honestly unknown — no
 * fabricated progress and no fake meters (capacity honesty law).
 * @param {{ roadmap_rail?: object, strip?: object|null, seats?: object|null }} [opts]
 */
export function buildRunBlock(opts = {}) {
  const steps = opts.roadmap_rail?.steps ?? [];
  const running = steps.find((s) => s.status === 'active') ?? null;
  const strip = opts.strip ?? null;
  const seats = opts.seats ?? null;

  const about = running
    ? `⏱ ${running.id ?? running.name} is FOR: ${
        nonEmpty(running.done_when) ? running.done_when : UNKNOWN_ANSWER
      }`
    : `⏱ nothing running — ${
        steps.length ? 'no active roadmap step' : 'no roadmap steps yet'
      }`;

  const rows = {
    run: running
      ? nonEmpty(running.commissioned_as)
        ? running.commissioned_as
        : (strip?.active_effort ?? UNKNOWN_ANSWER)
      : 'none',
    now: nonEmpty(strip?.next_recommended)
      ? strip.next_recommended
      : UNKNOWN_ANSWER,
    last_green: nonEmpty(strip?.as_of) ? strip.as_of : UNKNOWN_ANSWER,
    seats: seats?.current
      ? seats.options
          .map((o) => (o.selected ? `${o.family} (current)` : o.family))
          .join(' · ')
      : UNKNOWN_ANSWER,
  };

  return { about, running_step: running?.id ?? null, rows, fake_meters: false };
}

// ---------------------------------------------------------------------------
// S1-E5 — steward speaks first
// ---------------------------------------------------------------------------

/**
 * Opening steward message: position + run state + next summon +
 * nothing-needs-you — never a menu. Composed from status + brief position;
 * unknowns stay spoken and honest.
 * @param {{ status?: object, packet?: object, roadmap_rail?: object }} [opts]
 */
export function buildOpeningMessage(opts = {}) {
  const status = opts.status ?? {};
  const rail = opts.roadmap_rail ?? { steps: [], honest_gap: true };
  const packet = opts.packet ?? null;

  const running = rail.steps.find((s) => s.status === 'active') ?? null;
  const summon = rail.steps.find((s) => s.status === 'waiting') ?? null;
  const humanWait =
    nonEmpty(status.human_wait) && status.human_wait !== 'none'
      ? status.human_wait
      : null;

  const position = running
    ? `We're mid-${running.id ?? running.name}.`
    : rail.honest_gap
      ? "No roadmap steps are recorded yet — say the word and we'll set them together."
      : 'Nothing is running right now.';
  const run_state = running
    ? `${running.substatus}${nonEmpty(status.active_effort) ? ` · ${status.active_effort}` : ''}`
    : null;
  const next_summon = summon
    ? `Your next decision point is ${summon.id ?? summon.name} — ${summon.substatus}.`
    : humanWait
      ? `Waiting on you: ${humanWait}.`
      : null;
  const nothing_needs_you = !summon && !humanWait;

  const lines = [position];
  if (run_state) lines.push(run_state);
  if (next_summon) lines.push(next_summon);
  if (nothing_needs_you)
    lines.push("Nothing needs you yet — I'll bring the next decision to you.");

  return {
    who: SPELLING,
    steward_first: true,
    is_menu: false,
    position,
    run_state,
    next_summon,
    nothing_needs_you,
    text: lines.join(' '),
    coverage: packet?.coverage?.stamp ?? null,
    actions: [
      { act: 'carry_on', label: 'Fine — carry on' },
      { act: 'show_detail', label: 'Show me the detail anyway' },
    ],
  };
}

// ---------------------------------------------------------------------------
// S1-E6 — Grasscatcher offer beat
// ---------------------------------------------------------------------------

/**
 * Off-flow idea → "park it?" offer. Yes compiles to the grasscatch receipt;
 * "No, it matters now" leaves the flow to the conversation — no ledger write
 * either way until the act is applied.
 * @param {{ idea: string, active_effort?: string|null }} opts
 */
export function buildGrasscatcherOffer(opts = {}) {
  const idea = nonEmpty(opts.idea) ? opts.idea.trim() : null;
  return {
    beat: 'grasscatcher_offer',
    idea,
    question: idea
      ? `Good thought — but it doesn't serve the current goal. Shall I park it with your other ideas? I'll keep track of it and bring it back when it's ready.`
      : 'Shall I park that with your other ideas?',
    actions: [
      { act: 'park_that', label: 'Yes — park it', receipt_kind: 'grasscatch' },
      { act: null, label: 'No, it matters now', receipt_kind: null },
    ],
    on_yes: 'saved to your parked ideas · visible from the project and the High Seat · remembering it is my job',
    ledger_write: false,
  };
}

/**
 * Apply the "Yes — park it" branch: the offer exits the dialogue as a
 * grasscatch receipt (anything worth keeping exits as a receipt).
 * @param {{ idea: string, why?: string|null, active_effort?: string|null, as_of?: string }} opts
 */
export function acceptGrasscatcherOffer(opts = {}) {
  const receipt = buildGrasscatchReceipt({
    deferred: opts.idea ?? null,
    why: opts.why ?? 'off-flow idea parked from the Seal chamber',
    active_effort: opts.active_effort ?? null,
    as_of: opts.as_of,
  });
  return { ok: true, applied: 'park_that', receipt, dialogue_persisted: false };
}

// ---------------------------------------------------------------------------
// S1-E7 — seat-switch divider beat
// ---------------------------------------------------------------------------

/**
 * Conversation divider for a receipted seat hop — a non-event: same
 * Ecgberht, nothing lost, the ledger is the transition document.
 * @param {{ from: string, to: string, who?: string, when?: string, receipt?: object }} opts
 */
export function buildSeatSwitchDivider(opts = {}) {
  const receipt =
    opts.receipt ??
    buildSeatHopReceipt({
      who: opts.who ?? 'john',
      when: opts.when,
      from: opts.from,
      to: opts.to,
    });
  return {
    beat: 'seat_switch_divider',
    text: `— switched to ${receipt.to} (recorded) · same ${SPELLING}, nothing lost —`,
    receipt,
    non_event: true,
    re_brief_required: false,
  };
}

// ---------------------------------------------------------------------------
// S1-E8 — provenance recall beat
// ---------------------------------------------------------------------------

/**
 * "Remind me why…" answered from the record only: brief answers + their
 * provenance become the reply and document chip. A silent record is an
 * honest unknown — the steward never invents.
 * @param {{ question: string, packet?: object|null }} opts
 */
export function buildProvenanceRecall(opts = {}) {
  const packet = opts.packet ?? null;
  const answers = Array.isArray(packet?.answers) ? packet.answers : [];
  const terms = nonEmpty(opts.question)
    ? opts.question.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 3)
    : [];

  const hit = answers.find((a) => {
    if (a.unknown) return false;
    const hay = JSON.stringify(a.answer ?? '').toLowerCase();
    return terms.some((t) => hay.includes(t));
  });

  if (!hit) {
    return {
      beat: 'provenance_recall',
      question: opts.question ?? null,
      answer: UNKNOWN_ANSWER,
      unknown: true,
      invented: false,
      provenance: [],
      chip: null,
      voice:
        "I have nothing on record about that, so the honest answer is: I don't know. I won't make something up — say the word and I'll go look.",
    };
  }

  const source = hit.provenance?.[0] ?? null;
  return {
    beat: 'provenance_recall',
    question: opts.question ?? null,
    answer: hit.answer,
    unknown: false,
    invented: false,
    provenance: hit.provenance ?? [],
    chip: source
      ? {
          label: `📄 ${source.source}${source.field ? ` · ${source.field}` : ''}`,
          opens: source.source,
        }
      : null,
    voice: "From what's on record — the source is shown below. If I had nothing, I would tell you so.",
  };
}

// ---------------------------------------------------------------------------
// S1-E9 — saybox + talk compile wiring
// ---------------------------------------------------------------------------

/** Saybox descriptor — talk is the only free-form input, and it compiles. */
export function buildSaybox() {
  return {
    placeholder: `Talk to ${SPELLING} — ideas, questions, course changes…`,
    action: 'Send',
    compiles_to: 'closed_verbs_and_receipts',
    free_form_ledger_writes: false,
    dialogue_ephemeral: true,
  };
}

/**
 * Overlay Speak handler: compile the utterance against the closed act table.
 * Compiled acts carry their verb/receipt; anything else refuses-with-proposal.
 * Dialogue is never a second memory — the ephemeral store only.
 * @param {string} text
 * @param {{ session?: object, store?: object }} [ctx]
 */
export function chamberSpeak(text, ctx = {}) {
  const store = ctx.store ?? createDialogueStore();
  const compiled = compileUtterance(text, { session: ctx.session });
  store.note({ role: 'user', text });
  return {
    compiled,
    dialogue_persisted: false,
    store_policy: 'ephemeral',
    store_size: store.size(),
  };
}

// ---------------------------------------------------------------------------
// Assembly + CLI parity
// ---------------------------------------------------------------------------

/**
 * Assemble the whole Screen 1 chamber view model.
 * Same option surface as verbStatus/assembleBriefPacket (project, cwd,
 * surfaces, roadmap, env, prefs… all injectable for tests). Composes the
 * closed-verb bodies — the chamber has zero write authority of its own.
 * @param {object} [opts]
 * @returns {object} chamber view model
 */
export function assembleSealChamber(opts = {}) {
  const status = opts.status ?? verbStatus({ ...opts, roots: [] });
  const packet =
    opts.packet ?? assembleBriefPacket({ ...opts, roots: [], altitude: 'project' });
  const strip = opts.surfaces?.strip ?? null;

  const seats = titlebarSeatOptions({
    prefs: opts.prefs,
    env: opts.env,
    prefsPath: opts.prefsPath,
  });
  const titlebar = buildTitlebar({
    project_id: opts.project_id ?? strip?.project_id ?? null,
    strip,
    prefs: opts.prefs,
    env: opts.env,
    prefsPath: opts.prefsPath,
  });
  const goal_bar = buildGoalBar(packet);
  const roadmap_rail = buildRoadmapRail(status.roadmap ?? {});
  const run_block = buildRunBlock({ roadmap_rail, strip, seats });
  const opening = buildOpeningMessage({ status, packet, roadmap_rail });

  return {
    schema: SEAL_CHAMBER_SCHEMA_ID,
    spelling: SPELLING,
    screen: 'S1',
    mount: CHAMBER_MOUNT,
    titlebar,
    goal_bar,
    roadmap_rail,
    run_block,
    conversation: {
      main_region: true,
      steward_first: true,
      opening,
      saybox: buildSaybox(),
    },
    footer_stamp: CHAMBER_FOOTER_STAMP,
    // S1-N1 — the opening face carries none of the v1 instrument surfaces.
    negative: {
      verb_menu: false,
      depth_dial: false,
      rank_table: false,
      instrument_card_sheet: false,
      instrument_primary: false,
    },
    status_pointer: status.pointer ?? null,
    coverage: packet.coverage ?? null,
    write_authority: 'none',
  };
}

/**
 * CLI parity check — `ecgberht status` and the overlay must agree.
 * Compares the chamber's pointer + roadmap projection against a status verb
 * result (project mode, or a portfolio ranked entry from
 * `status --roots <proj>`). Used by the self-run smoke (annex A5) and tests.
 * @param {object} chamber assembled chamber view model
 * @param {object} status verbStatus result
 * @returns {{ agrees: boolean, mismatches: string[] }}
 */
export function chamberAgreesWithStatus(chamber, status) {
  const mismatches = [];
  const pointer = chamber?.status_pointer ?? {};

  if (status?.mode === 'portfolio') {
    const entry =
      status.portfolio?.ranked?.find(
        (r) =>
          r.project_id != null &&
          chamber?.titlebar?.title?.includes(r.project_id),
      ) ?? status.portfolio?.ranked?.[0] ?? null;
    if (!entry) {
      mismatches.push('portfolio_status_has_no_entry_for_project');
    } else {
      for (const field of ['active_effort', 'human_wait', 'next_recommended', 'why_next']) {
        const a = pointer[field] ?? null;
        const b = entry[field] ?? null;
        if (a !== b) mismatches.push(`pointer.${field}: overlay=${a} status=${b}`);
      }
    }
  } else {
    for (const field of ['active_effort', 'human_wait', 'next_recommended', 'why_next']) {
      const a = pointer[field] ?? null;
      const b = status?.pointer?.[field] ?? status?.[field] ?? null;
      if (a !== b) mismatches.push(`pointer.${field}: overlay=${a} status=${b}`);
    }
    const overlaySteps = (chamber?.roadmap_rail?.steps ?? []).map((s) => `${s.id}:${s.status}`);
    const statusSteps = (status?.roadmap?.projection ?? []).map((s) => `${s.id}:${s.status}`);
    if (overlaySteps.join('|') !== statusSteps.join('|')) {
      mismatches.push(
        `roadmap: overlay=[${overlaySteps.join(',')}] status=[${statusSteps.join(',')}]`,
      );
    }
  }

  return { agrees: mismatches.length === 0, mismatches };
}

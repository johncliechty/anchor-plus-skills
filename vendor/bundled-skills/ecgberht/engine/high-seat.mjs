/**
 * TW6 — High Seat view model (wireframes v2.1 Screens 0 + 2, portfolio
 * altitude) + the raise queue (Master Plan R2 §4.5) + spoken capacity
 * balancing (machine-contract annex A1/A3).
 *
 * The docked overlay on the live Anchor MAIN dashboard renders THIS object.
 * Everything composes the same closed read surfaces the CLI runs (status
 * --roots / rank / brief) — the High Seat has zero write authority; the only
 * ledger writes it can cause are receipts (seen on close, override on a
 * balancing override) through the closed builders.
 *
 * Mockup contract (MOCKUP-CONTRACT.md) element IDs implemented here:
 *   S0-E1 High Seat button on the live Anchor MAIN dashboard toolbar
 *         (locked icon ecgberht-portfolio-high-seat.jpg)
 *   S0-E2 ⚑ badge = raise-queue length; the ONLY ambient Ecgberht signal
 *   S0-E4 docked overlay (same component family as the Seal; no window)
 *   S0-E5 in-overlay altitude hop ("Bring it up" → project chamber/packet)
 *   S2-E1 titlebar (throne icon · "the High Seat — every campaign, one
 *         steward above them" · seat switcher · counts stamp)
 *   S2-E2 SINGLE raise block + [Bring it up] [Later today] [Tomorrow] +
 *         queue note ("N more behind it, raised one at a time")
 *   S2-E3 project tiles: seal mini-icon + name + goal-phrase + EXACTLY ONE
 *         state pill; quiet tiles dimmed
 *   S2-E4 capacity & focus conversation card: steward voice, named seat
 *         loads, ordered recommendation WITH reasons + [Do that] [Reorder…]
 *         [Why? show reasoning]; override → receipt
 *   S2-E5 High Seat saybox
 *   S2-N1 NEGATIVE: no master data table; no %-meters or token gauges;
 *         never more than one raised block
 */

import path from 'node:path';

import { SPELLING } from './verbs.mjs';
import { verbStatus } from './verb-bodies.mjs';
import {
  assembleBriefPacket,
  loadBriefCache,
  briefCacheStale,
  buildSeenReceipt,
  UNKNOWN_ANSWER,
} from './brief.mjs';
import { loadProjectSurfaces } from './face-strip.mjs';
import { loadProjectRoadmap } from './roadmap.mjs';
import { countWaitingOnJohnSteps, deriveWaitingSteps } from './attention.mjs';
import { buildOverrideReceipt, validateReceipt } from './receipt-validate.mjs';
import { titlebarSeatOptions } from './seat-hop.mjs';
import { compileUtterance, createDialogueStore } from './dialogue.mjs';
import { assemblePacketView } from './packet-view.mjs';
import { summarizeConversation } from './conversation-log.mjs';
import { summarizePortfolioEfforts } from './portfolio-ledger.mjs';
import { buildCapacityUnknownChamber } from './stand-up.mjs';
import { NOT_YET_COMMITTED, durabilityFor } from './portfolio/anchor-contract.mjs';

export const HIGH_SEAT_SCHEMA_ID = 'ecgberht-high-seat-v0';

/** Locked icon — relative to the Ecgberht skill root (never host-absolute). */
export const HIGH_SEAT_ICON_RELPATH = 'assets/icons/ecgberht-portfolio-high-seat.jpg';

/** Where the High Seat mounts: docked overlay over the MAIN dashboard. */
export const HIGH_SEAT_MOUNT = Object.freeze({
  host: 'anchor',
  surface: 'main_dashboard',
  presentation: 'docked_overlay',
  separate_window: false,
});

/**
 * Raise ranking — Master Plan R2 §4.5, descending severity:
 *   1. human_wait present AND packet ready
 *   2. waiting_on_john Roadmap steps
 *   3. anti_starvation_age_days (older first among equals)
 *   4. capacity conflict needing override
 *   5. everything else — ambient (never raised)
 */
export const RAISE_SEVERITY_TIERS = Object.freeze({
  human_wait_packet_ready: 1,
  waiting_on_john_step: 2,
  anti_starvation: 3,
  capacity_conflict: 4,
  ambient: 5,
});

/** Age-bump threshold T (config; R2 §4.5 default = 3 days). */
export const STARVE_THRESHOLD_DAYS_DEFAULT = 3;

/** One raised at a time — standing rule (S2-N1). */
export const MAX_RAISED_BLOCKS = 1;

/** S2-N1 — surfaces that must never appear on the High Seat. */
export const HIGH_SEAT_NEGATIVE_SURFACES = Object.freeze([
  'master_data_table',
  'percent_meter',
  'token_gauge',
]);

/** Footer stamp (verbatim intent from the v2.1 mockup). */
export const HIGH_SEAT_FOOTER_STAMP =
  'one decision at a time · one line per project · the ranking and capacity rules run in the background';

const nonEmpty = (v) => typeof v === 'string' && v.trim().length > 0;

// ---------------------------------------------------------------------------
// Raise queue — R2 §4.5
// ---------------------------------------------------------------------------

/**
 * Severity of one campaign for the raise queue. Input is a strip projection
 * (rank.mjs shape) optionally enriched with:
 *   packet_ready       — a Decision Packet is gathered/cached for it
 *   waiting_steps      — count of waiting(_on_john) Roadmap steps
 *   capacity_conflict  — this campaign needs a capacity override to proceed
 * @param {object} item enriched projection
 * @returns {{ tier: number, tier_name: string, reasons: string[] }}
 */
export function raiseSeverity(item = {}) {
  const reasons = [];
  const humanWait = nonEmpty(item.human_wait) && item.human_wait !== 'none';
  const waitingSteps =
    typeof item.waiting_steps === 'number' ? item.waiting_steps : 0;
  const age =
    typeof item.anti_starvation_age_days === 'number'
      ? item.anti_starvation_age_days
      : 0;

  if (humanWait && item.packet_ready === true) {
    reasons.push('human_wait_with_packet_ready');
    return { tier: RAISE_SEVERITY_TIERS.human_wait_packet_ready, tier_name: 'human_wait_packet_ready', reasons };
  }
  if (humanWait || waitingSteps > 0) {
    if (humanWait) reasons.push(`human_wait=${item.human_wait}`);
    if (waitingSteps > 0) reasons.push(`waiting_on_john_steps=${waitingSteps}`);
    return { tier: RAISE_SEVERITY_TIERS.waiting_on_john_step, tier_name: 'waiting_on_john_step', reasons };
  }
  if (age > 0) {
    reasons.push(`anti_starvation_age_days=${age}`);
    return { tier: RAISE_SEVERITY_TIERS.anti_starvation, tier_name: 'anti_starvation', reasons };
  }
  if (item.capacity_conflict === true) {
    reasons.push('capacity_conflict_needs_override');
    return { tier: RAISE_SEVERITY_TIERS.capacity_conflict, tier_name: 'capacity_conflict', reasons };
  }
  reasons.push('ambient');
  return { tier: RAISE_SEVERITY_TIERS.ambient, tier_name: 'ambient', reasons };
}

/**
 * Build the raise queue from enriched projections. One raised at a time;
 * the queue length drives the ⚑ badge — the ONLY ambient signal (S0-E2).
 *
 * Age bump (R2 §4.5): a campaign with human_wait or waiting_on_john that is
 * not currently raised and has starved ≥ T days MUST enter the queue even at
 * lower severity — the starve counter cannot be silently absorbed.
 * @param {object[]} items enriched projections
 * @param {{ starve_threshold_days?: number }} [opts]
 */
export function buildRaiseQueue(items = [], opts = {}) {
  const threshold =
    typeof opts.starve_threshold_days === 'number'
      ? opts.starve_threshold_days
      : STARVE_THRESHOLD_DAYS_DEFAULT;

  const scored = (Array.isArray(items) ? items : []).map((item) => {
    const severity = raiseSeverity(item);
    const age =
      typeof item.anti_starvation_age_days === 'number'
        ? item.anti_starvation_age_days
        : 0;
    const humanish =
      (nonEmpty(item.human_wait) && item.human_wait !== 'none') ||
      (typeof item.waiting_steps === 'number' && item.waiting_steps > 0);
    const age_bumped = humanish && age >= threshold;
    if (age_bumped) severity.reasons.push(`age_bump>=${threshold}d`);
    return { ...item, severity, age_bumped };
  });

  // Queue membership: anything below ambient severity, plus age-bumped
  // campaigns that must enter regardless of tier.
  const queue = scored
    .filter(
      (s) => s.severity.tier < RAISE_SEVERITY_TIERS.ambient || s.age_bumped,
    )
    .sort((a, b) => {
      if (a.severity.tier !== b.severity.tier) return a.severity.tier - b.severity.tier;
      const ageA = a.anti_starvation_age_days ?? 0;
      const ageB = b.anti_starvation_age_days ?? 0;
      if (ageB !== ageA) return ageB - ageA; // older first among equals
      return String(a.project_id ?? a.project_path ?? '').localeCompare(
        String(b.project_id ?? b.project_path ?? ''),
      );
    });

  return {
    queue,
    raised: queue[0] ?? null,
    queue_length: queue.length,
    max_raised: MAX_RAISED_BLOCKS,
    badge: {
      glyph: '⚑',
      count: queue.length,
      only_ambient_signal: true,
      law: '⚑ count equals raise queue length; no other ambient notification surfaces anywhere in Anchor',
    },
    starve_threshold_days: threshold,
  };
}

// ---------------------------------------------------------------------------
// S2-E1 — titlebar
// ---------------------------------------------------------------------------

/**
 * High Seat titlebar: throne icon · fixed title · seat switcher pill ·
 * honest counts stamp ("N campaigns · R running · W needs you").
 * @param {{ items?: object[], raiseQueue?: object, prefs?: object, env?: object, prefsPath?: string|null }} [opts]
 */
/**
 * W15 — the High Seat's durability block: ONE escalating banner, plus the projects whose
 * receipts have not been acknowledged, named rather than hidden.
 *
 * It renders even when nothing is wrong (`present` stays true, with the all-clear line),
 * because an absent block and a healthy one look identical to a reader, and "nobody checked"
 * is not the same fact as "everything is committed".
 *
 * @param {{durability?: object}} [opts]
 * @returns {object}
 */
export function buildHighSeatDurability(opts = {}) {
  const block = durabilityFor(opts.durability ?? {});
  const pending = block.not_yet_committed ?? [];
  return {
    ...block,
    heading: block.degraded ? '⚑ durability' : 'durability',
    // The frozen phrase, once, as the label the tiles' owners read.
    phrase: NOT_YET_COMMITTED,
    projects_not_yet_committed: pending.map((p) => p.project_id),
    // The negative surface this wave adds: never one warning per intent.
    per_intent_warnings: false,
  };
}

export function buildHighSeatTitlebar(opts = {}) {
  const items = Array.isArray(opts.items) ? opts.items : [];
  const seats = titlebarSeatOptions({
    prefs: opts.prefs,
    env: opts.env,
    prefsPath: opts.prefsPath,
  });
  const running = items.filter((i) => nonEmpty(i.active_effort)).length;
  const needsYou = opts.raiseQueue?.queue_length ?? 0;
  return {
    icon: HIGH_SEAT_ICON_RELPATH,
    title: `${SPELLING} · the High Seat — all your projects, one place to steer them`,
    seat_switcher: {
      pill: `seat: ${seats.current ?? 'unknown'} ▾`,
      source: seats.source,
      current: seats.current,
      options: seats.options,
    },
    stamp: `${items.length} project${items.length === 1 ? '' : 's'} · ${running} running · ${needsYou} need${needsYou === 1 ? 's' : ''} you`,
  };
}

// ---------------------------------------------------------------------------
// S2-E2 — the single raise block
// ---------------------------------------------------------------------------

/**
 * The SINGLE raised attention block. Time estimate is honest — shown only
 * when the record carries one, never invented.
 * @param {object} raiseQueue buildRaiseQueue result
 */
export function buildRaiseBlock(raiseQueue = {}) {
  const raised = raiseQueue.raised ?? null;
  if (!raised) {
    return {
      block: 'raise',
      present: false,
      at_most_one: true,
      voice: "Nothing needs you right now — every project is either running quietly or parked. I'll bring you the next decision as soon as it's ready.",
      actions: [],
      queue_note: null,
    };
  }
  const behind = Math.max(0, (raiseQueue.queue_length ?? 1) - 1);
  const summary = nonEmpty(raised.human_wait) && raised.human_wait !== 'none'
    ? raised.human_wait
    : nonEmpty(raised.next_recommended)
      ? raised.next_recommended
      : UNKNOWN_ANSWER;

  // ANSWER THE QUESTION BEFORE HE ASKS IT (John, 2026-08-06). The High Seat used to say
  // only "this one needs input" — so he had to open the project and ask what it had
  // done and what it would do next. Both facts are already on the projection; leading
  // with them is the difference between a nag and a briefing.
  const did = nonEmpty(raised.last_done) ? raised.last_done
    : nonEmpty(raised.active_effort) ? raised.active_effort
      : null;
  const next = nonEmpty(raised.next_recommended) ? raised.next_recommended : null;

  return {
    block: 'raise',
    present: true,
    at_most_one: true,
    heading: '⚑ This one needs a decision from you',
    project_id: raised.project_id ?? null,
    project_path: raised.project_path ?? null,
    /** The commissioned session that asked — so "bring it up" can open IT. */
    session_id: raised.session_id ?? null,
    summary,
    /** What it has done — so he does not have to go in and ask. */
    did,
    /** What it would do next — so he can approve rather than investigate. */
    next,
    briefing: [
      did ? `Done: ${did}` : null,
      `Waiting on you: ${summary}`,
      next ? `Next if you say go: ${next}` : null,
    ].filter(Boolean),
    time_estimate: nonEmpty(raised.time_estimate) ? raised.time_estimate : null,
    severity: raised.severity,
    actions: [
      { act: 'bring_it_up', label: 'Bring it up', primary: true },
      { act: 'later_today', label: 'Later today' },
      { act: 'tomorrow', label: 'Tomorrow' },
    ],
    queue_note: `opens the full decision summary · ${behind} more waiting behind it, one at a time`,
  };
}

// ---------------------------------------------------------------------------
// S2-E3 — project tiles (one line each — never a table)
// ---------------------------------------------------------------------------

/**
 * Exactly ONE state pill for a tile. Raised campaign shows the ⚑ line; a
 * running one shows its quiet line; parked-aging names its age; everything
 * else is quiet. Unknown stays spoken (capacity honesty), never a meter.
 * @param {object} item enriched projection
 * @param {object|null} raised the currently raised item
 */
export function tileStatePill(item = {}, raised = null) {
  const isRaised =
    raised != null &&
    (raised.project_id ?? raised.project_path) ===
      (item.project_id ?? item.project_path);
  if (isRaised) {
    const wait = nonEmpty(item.human_wait) && item.human_wait !== 'none'
      ? item.human_wait
      : 'a decision';
    return { pill: `⚑ waiting on you · ${wait}`, kind: 'raised', quiet: false };
  }
  if ((item.anti_starvation_age_days ?? 0) > 0) {
    return {
      pill: `parked ${item.anti_starvation_age_days}d · I'll flag it if it sits much longer`,
      kind: 'parked_aging',
      quiet: true,
    };
  }
  if (nonEmpty(item.active_effort)) {
    return {
      pill: `running quietly · ${item.active_effort}`,
      kind: 'running_quietly',
      quiet: true,
    };
  }
  if (item.capacity === 'unknown') {
    return {
      pill: "quiet · I don't know how much capacity is free",
      kind: 'quiet',
      quiet: true,
    };
  }
  return { pill: 'quiet · nothing needs you', kind: 'quiet', quiet: true };
}

/**
 * Project tiles: seal mini-icon + name + goal-in-a-phrase + exactly one
 * state pill. Quiet tiles are dimmed. NO master data table (S2-N1).
 * @param {object[]} items enriched projections
 * @param {object|null} raised
 */
export function buildProjectTiles(items = [], raised = null) {
  const tiles = (Array.isArray(items) ? items : []).map((item) => {
    const state = tileStatePill(item, raised);
    return {
      icon: 'assets/icons/ecgberht-project-seal.jpg',
      name: item.project_id ?? item.project_path ?? 'unnamed campaign',
      // The resolved path rides the tile so the HOST can map it to its own
      // project id (2026-08-07, John: click a High Seat row → straight into
      // that project's steward). Path-passport pattern — never the host id.
      project_path: item.project_path ?? null,
      goal_phrase: nonEmpty(item.goal_phrase)
        ? item.goal_phrase
        : nonEmpty(item.active_effort)
          ? item.active_effort
          : UNKNOWN_ANSWER,
      state_pill: state.pill,
      state_kind: state.kind,
      state_line_count: 1,
      dimmed: state.quiet,
    };
  });
  return {
    tiles,
    master_data_table: false,
    one_state_line_each: tiles.every((t) => t.state_line_count === 1),
  };
}

// ---------------------------------------------------------------------------
// S2-E4 — capacity & focus (spoken; annex A1/A3 underneath)
// ---------------------------------------------------------------------------

/**
 * The capacity & focus conversation card. Steward voice; named seat loads;
 * ordered recommendation WITH reasons; override path. Capacity is spoken as
 * known|unknown ONLY — no %-meters, no token gauges, ever (A3). Unknown
 * capacity blocks FULL admits without an override receipt (A3 hard-stop).
 * @param {{
 *   items?: object[], demands?: {project_id: string, wants: string}[],
 *   prefs?: object, env?: object, prefsPath?: string|null,
 *   recommendation?: { order: string[], reasons: string[] }|null,
 * }} [opts]
 */
export function buildBalancingCard(opts = {}) {
  const items = Array.isArray(opts.items) ? opts.items : [];
  const demands = Array.isArray(opts.demands) ? opts.demands : [];
  const seats = titlebarSeatOptions({
    prefs: opts.prefs,
    env: opts.env,
    prefsPath: opts.prefsPath,
  });

  const seat_loads = (seats.options ?? []).map((o) => ({
    seat: o.family,
    selected: o.selected === true,
    // Honest load: named demands only — never a % remaining figure (A3).
    demanded_by: demands
      .filter((d) => d.seat === o.family || d.seat == null)
      .map((d) => d.project_id),
  }));

  const unknownCapacity = items
    .filter((i) => i.capacity !== 'known')
    .map((i) => i.project_id ?? i.project_path);

  // Deterministic default recommendation when none injected: FULL demanders
  // in queue order, human-wait first — with the reasons spelled out.
  let recommendation = opts.recommendation ?? null;
  if (!recommendation) {
    const order = demands.map((d) => d.project_id);
    recommendation = {
      order,
      reasons: order.length
        ? [
            'ordered by how urgent each one is, then by how long it has waited',
            'only a few big runs can go at once',
            "anything that doesn't fit goes to parked ideas — nothing is dropped silently",
          ]
        : ['no big runs are queued — nothing to balance right now'],
    };
  }

  const voice = demands.length
    ? `${demands.length} project${demands.length === 1 ? '' : 's'} want${demands.length === 1 ? 's' : ''} a big run, and there is not room for all of them at once. I suggest: ${recommendation.order.join(', then ')}. Say the word and I will keep that order — or change it, and I will record who changed it and why.`
    : "Nothing is competing for capacity right now. When big runs collide I'll suggest an order and tell you why.";

  return {
    card: 'capacity_and_focus',
    steward_voice: voice,
    seat_loads,
    capacity_values_allowed: ['known', 'unknown'],
    capacity_unknown: unknownCapacity,
    full_admit_blocked_without_override: unknownCapacity.length > 0,
    recommendation: {
      order: recommendation.order,
      reasons: recommendation.reasons,
      has_reasons: recommendation.reasons.length > 0,
    },
    actions: [
      { act: 'do_that', label: 'Do that', primary: true },
      { act: 'reorder', label: 'Reorder…', lands_as: 'override_receipt' },
      { act: 'why_reasoning', label: 'Why this order?' },
    ],
    override_law: 'override = receipt (who/when/why/from→to) — A1 human-override row',
    mechanics_stamp:
      'your choice always wins · every change is recorded with who and why · no made-up progress meters',
    fake_meters: false,
    percent_meter: false,
    token_gauge: false,
  };
}

/**
 * Apply a balancing override: John's reorder/force lands as a structured
 * override receipt (who/when/why/from→to — A1/A3), validated against the
 * locked receipt schema. Monologue never lands.
 * @param {{ who: string, why: string, from: string, to: string, when?: string }} fields
 */
export function applyBalancingOverride(fields = {}) {
  const receipt = buildOverrideReceipt(fields);
  const validated = validateReceipt(receipt);
  if (!validated.ok) {
    return { ...validated, applied: false };
  }
  return {
    ok: true,
    applied: true,
    receipt: validated.receipt,
    law: 'human override wins (A1) — but only as a receipt, never a silent reorder',
  };
}

// ---------------------------------------------------------------------------
// S2-E5 — saybox
// ---------------------------------------------------------------------------

/** High Seat saybox — same closed-compile law as the Seal chamber. */
export function buildHighSeatSaybox() {
  return {
    placeholder: 'Ask about priorities, focus, or what matters today…',
    action: 'Send',
    compiles_to: 'closed_verbs_and_receipts',
    free_form_ledger_writes: false,
    dialogue_ephemeral: true,
  };
}

/**
 * High Seat Speak handler — compile against the closed act table
 * (refuse-with-proposal on anything else). Dialogue stays ephemeral.
 * @param {string} text
 * @param {{ session?: object, store?: object }} [ctx]
 */
export function highSeatSpeak(text, ctx = {}) {
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
// Bring it up — in-overlay altitude hop (S0-E5) + cached packet (Option P)
// ---------------------------------------------------------------------------

/**
 * "Bring it up": hop to the project chamber INSIDE the same overlay (no
 * second window) and open the Decision Packet with ZERO further gathering.
 *
 * Passport = Option P (annex A2): the resolved project path is the identity;
 * the hop must land on the same strip/Face the project Seal opens. Packet
 * source order: fresh brief cache (precomputed projection) → live Phase A
 * assembly (still deterministic, zero model calls). The packet handed to the
 * view is complete BEFORE the view renders — assemblePacketView gathers
 * nothing.
 * @param {{
 *   project_path: string, surfaces?: object, packet?: object,
 *   artifact?: object|null, question?: string|null, step?: string|null,
 *   cache?: object|null,
 * }} opts
 */
export function bringItUp(opts = {}) {
  if (!nonEmpty(opts.project_path)) {
    return { ok: false, error: 'missing_project_path', spelling: SPELLING };
  }
  const resolved = path.resolve(opts.project_path);

  const passport = {
    option: 'P',
    scheme: 'path_passport',
    project_path: resolved,
    law: 'high-seat expand and project seal open must resolve the same realpath → same strip/Face (annex A2)',
  };

  // Packet: injected → cached (fresh) → live Phase A. All deterministic.
  let packet = opts.packet ?? null;
  let from_cache = false;
  if (!packet) {
    const cached = opts.cache !== undefined
      ? { exists: opts.cache != null, cache: opts.cache }
      : loadBriefCache(resolved);
    if (cached.exists) {
      const surfaces = opts.surfaces ?? loadProjectSurfaces(resolved);
      // A3: content-anchored stale check needs face + roadmap, not strip counts alone.
      // Only include `roadmap` when the caller injected it or a live file exists.
      // Omitting the key (vs passing null) avoids a false-stale when inject mode
      // hands surfaces + cache without a roadmap file on disk — strip/face still
      // gate freshness; A3 mutation detection runs whenever a live roadmap is present.
      const live = {
        strip: surfaces?.strip ?? null,
        face: surfaces?.face ?? null,
      };
      if (opts.roadmap !== undefined) {
        live.roadmap = opts.roadmap;
      } else {
        const loaded = loadProjectRoadmap(resolved);
        if (loaded.ok && loaded.exists) {
          live.roadmap = loaded.roadmap;
        }
      }
      const staleness = briefCacheStale(cached.cache, live);
      if (!staleness.stale) {
        packet = cached.cache.packet;
        from_cache = true;
      }
    }
  }
  if (!packet) {
    packet = assembleBriefPacket({
      project: resolved,
      roots: [],
      altitude: 'project',
      ...(opts.surfaces !== undefined ? { surfaces: opts.surfaces } : {}),
      ...(opts.roadmap !== undefined ? { roadmap: opts.roadmap } : {}),
      ...(opts.journal !== undefined ? { journal: opts.journal } : {}),
      ...(opts.anchor_knowledge !== undefined
        ? { anchor_knowledge: opts.anchor_knowledge }
        : {}),
    });
  }

  const packet_view = assemblePacketView(packet, {
    project_id: opts.project_id ?? packet?.goal_card?.project_id ?? null,
    step: opts.step ?? null,
    question: opts.question ?? null,
    artifact: opts.artifact ?? null,
    from_cache,
  });

  // THE CONVERSATION RECORD (2026-08-05). "Bring it up" is the altitude hop that drops
  // John back into a project — so it is the right place for him to see how the plan got
  // here, not just what it currently is. Read-only and NON-AUTHORITATIVE: this summary
  // derives no status, no step and no next action; project state above still comes from
  // the packet (Face + roadmap + Strip), and the ledger always wins.
  const conversation = opts.conversation ?? summarizeConversation(resolved, { recent: 3 });

  return {
    ok: true,
    hop: {
      in_overlay: true,
      separate_window: false,
      altitude: 'project',
      returns_via: 'esc_or_breadcrumb',
      passport,
    },
    packet,
    packet_view,
    conversation,
    further_gathering: false,
    from_cache,
  };
}

// ---------------------------------------------------------------------------
// Close overlay — ledger gains a seen receipt at most (S0 falsify)
// ---------------------------------------------------------------------------

/**
 * Close the High Seat overlay. The ledger gains AT MOST a seen receipt
 * (altitude=portfolio) — nothing else; panel state evaporates (no dual
 * store, dialogue ephemeral). Returns the receipt for the caller to append
 * through the closed strip writer if mark_seen is requested.
 * @param {{ mark_seen?: boolean, who?: string, when?: string }} [opts]
 */
export function closeHighSeat(opts = {}) {
  const receipt = opts.mark_seen === true
    ? buildSeenReceipt({
        who: opts.who ?? 'john',
        when: opts.when,
        altitude: 'portfolio',
      })
    : null;
  return {
    ok: true,
    closed: true,
    ledger_delta: receipt ? ['seen'] : [],
    seen_receipt: receipt,
    dual_store: false,
    panel_state_persisted: false,
    dialogue_persisted: false,
  };
}

// ---------------------------------------------------------------------------
// Assembly
// ---------------------------------------------------------------------------

/**
 * Enrich rank projections for the raise queue: packet readiness comes from
 * the brief cache on disk (or injected). RAISE TIER 2 REVIVED (Wave 16):
 * waiting_steps DERIVED from the EXISTING buildRoadmapProjection step statuses
 * when not already supplied, so raiseSeverity → waiting_on_john_step fires.
 *
 * @param {object[]} ranked rankPortfolioStripFirst().ranked
 * @param {{
 *   enrich?: (item: object) => object,
 *   derive_waiting?: boolean,
 * }} [opts]
 */
export function enrichForRaise(ranked = [], opts = {}) {
  const enrich = typeof opts.enrich === 'function' ? opts.enrich : null;
  const deriveWaiting = opts.derive_waiting !== false;
  return (Array.isArray(ranked) ? ranked : []).map((r) => {
    let waiting_steps =
      typeof r.waiting_steps === 'number' ? r.waiting_steps : 0;
    // Revive tier 2: derive from buildRoadmapProjection when unset / zero and
    // a project path (or injected projection) is available.
    if (
      deriveWaiting &&
      waiting_steps === 0 &&
      (r.project_path || Array.isArray(r.roadmap_projection) || Array.isArray(r.projection))
    ) {
      if (Array.isArray(r.roadmap_projection) || Array.isArray(r.projection)) {
        waiting_steps = countWaitingOnJohnSteps(
          r.roadmap_projection ?? r.projection,
        );
      } else if (r.project_path) {
        const derived = deriveWaitingSteps({ projectPath: r.project_path });
        waiting_steps = derived.waiting_steps;
      }
    }
    const base = {
      ...r,
      packet_ready:
        r.packet_ready === true ||
        (r.project_path ? loadBriefCache(r.project_path).exists : false),
      waiting_steps,
      capacity_conflict: r.capacity_conflict === true,
    };
    return enrich ? { ...base, ...enrich(base) } : base;
  });
}

/**
 * Assemble the whole Screen 2 High Seat view model. Same injectable option
 * surface as verbStatus (roots, env, prefs, surfaces …) — composition over
 * the closed read bodies; zero write authority.
 * @param {{
 *   roots?: string[], items?: object[], status?: object,
 *   demands?: object[], recommendation?: object|null,
 *   prefs?: object, env?: object, prefsPath?: string|null,
 *   starve_threshold_days?: number, enrich?: (item: object) => object,
 * }} [opts]
 * @returns {object} high seat view model
 */
export function assembleHighSeat(opts = {}) {
  let items;
  if (Array.isArray(opts.items)) {
    items = opts.items;
  } else if (opts.status != null) {
    // Injected portfolio status (tests / explicit rank shape) — still no walk
    // when the caller already resolved projections.
    items = enrichForRaise(opts.status?.portfolio?.ranked ?? [], {
      enrich: opts.enrich,
    });
  } else if (opts.allow_legacy_status_walk === true) {
    // Explicit opt-in only. Wave 17 retires the ambient badge/high-seat walk;
    // production paths use assemblePortfolioGlance / buildBadgeFromIndex.
    const status = verbStatus({
      roots: Array.isArray(opts.roots) ? opts.roots : [],
      env: opts.env,
      envValue: opts.envValue ?? null,
    });
    items = enrichForRaise(status?.portfolio?.ranked ?? [], {
      enrich: opts.enrich,
    });
  } else {
    // Wave 17 default: no discoverStrips walk. Empty items when the caller
    // did not supply projections / glance fold (bridge passes glance.items).
    items = [];
  }

  const raiseQueue = buildRaiseQueue(items, {
    starve_threshold_days: opts.starve_threshold_days,
  });
  const raise_block = buildRaiseBlock(raiseQueue);
  const tiles = buildProjectTiles(items, raiseQueue.raised);
  const balancing = buildBalancingCard({
    items,
    demands: opts.demands ?? [],
    recommendation: opts.recommendation ?? null,
    prefs: opts.prefs,
    env: opts.env,
    prefsPath: opts.prefsPath,
  });

  return {
    schema: HIGH_SEAT_SCHEMA_ID,
    spelling: SPELLING,
    screen: 'S2',
    mount: HIGH_SEAT_MOUNT,
    titlebar: buildHighSeatTitlebar({
      items,
      raiseQueue,
      prefs: opts.prefs,
      env: opts.env,
      prefsPath: opts.prefsPath,
    }),
    raise_block,
    raised_block_count: raise_block.present ? 1 : 0,
    // W15 — durability, as ONE banner above the campaigns rather than a warning per receipt.
    // It sits outside the raise queue on purpose: the queue raises at most one campaign and
    // durability is not a campaign, it is a fact about all of them at once. A project whose
    // receipts have not been acknowledged is listed by name as 'state not yet committed',
    // never folded into a tile pill where it would compete with the work itself.
    durability: buildHighSeatDurability(opts),
    raise_queue: {
      queue_length: raiseQueue.queue_length,
      raised_project: raiseQueue.raised?.project_id ?? null,
      starve_threshold_days: raiseQueue.starve_threshold_days,
    },
    badge: raiseQueue.badge,
    tiles,
    // PORTFOLIO MEMORY (2026-08-05). Nothing anywhere recorded what the steward had
    // actually been DOING across projects — history left with a folder when it moved.
    // This is that record: efforts only (conversations held, scaffoldings proposed and
    // confirmed, questions raised), never project state. Project truth still comes from
    // the tiles above, read live, so this can never contradict a project.
    steward_efforts: opts.steward_efforts
      ?? summarizePortfolioEfforts({ env: opts.env, recent: 5 }),
    balancing,
    // TW7 S4-E2 — unknown capacity is a spoken hard-stop chamber (exactly
    // three honest options), never a silent FULL admit and never a meter.
    capacity_unknown_chamber: balancing.full_admit_blocked_without_override
      ? buildCapacityUnknownChamber({ projects: balancing.capacity_unknown })
      : null,
    saybox: buildHighSeatSaybox(),
    footer_stamp: HIGH_SEAT_FOOTER_STAMP,
    // S2-N1 — the High Seat carries none of the forbidden surfaces.
    negative: {
      master_data_table: false,
      percent_meter: false,
      token_gauge: false,
      raised_blocks_max: MAX_RAISED_BLOCKS,
    },
    ambient: {
      only_signal: 'badge',
      badge_count_equals_queue_length:
        raiseQueue.badge.count === raiseQueue.queue_length,
    },
    write_authority: 'none',
  };
}

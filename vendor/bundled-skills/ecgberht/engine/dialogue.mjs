/**
 * TW4 — Dialogue compile layer (Master Plan R2 §4.3 v1 act table).
 *
 * Talk compiles to closed acts only; anything else → refuse-with-proposal
 * (no ledger write). Destructive free-form ("delete all projects") never
 * compiles to a verb. Dialogue itself is EPHEMERAL: chat turns are never
 * persisted — E5 Strip receipts / roadmap events remain the sole ledger.
 * This module deliberately imports no filesystem API.
 */

import { SPELLING, isClosedVerb } from './verbs.mjs';
import {
  RECEIPT_SCHEMA_ID,
  validateReceipt,
} from './receipt-validate.mjs';
import { appendStripReceipt } from './write-authority.mjs';

function nonEmpty(v) {
  return v != null && v !== '';
}

/**
 * v1 act table — Master Plan R2 §4.3 (closes co-1).
 * Each act: id, human label (as in the plan), target closed verb (or null
 * when the act is a receipt/effect without a verb body), effect, receipt kind.
 */
export const ACT_TABLE = Object.freeze([
  Object.freeze({
    act: 'still_the_goal',
    label: 'Still the goal',
    verb: null,
    effect: 'face_confirm_receipt',
    receipt_kind: 'face_confirm',
    invariants: Object.freeze({
      face_only: true,
      roadmap_write: false,
      strip_instrument_write: false,
    }),
    patterns: Object.freeze([
      /^still the goal\b/i,
      /\bstill (?:the|our|my) goal\b/i,
      /\bgoal (?:unchanged|stands|still stands|is still right)\b/i,
      /^yes,? still the goal/i,
    ]),
  }),
  Object.freeze({
    act: 'refine_goal',
    label: 'Refine goal',
    verb: 'update',
    effect: 'face_rewrite_receipt',
    receipt_kind: null,
    invariants: Object.freeze({ face_narrative_rewrite: true }),
    patterns: Object.freeze([
      /\brefine (?:the )?goal\b/i,
      /\b(?:change|rewrite|update) (?:the )?goal\b/i,
      /^new goal[:\s]/i,
    ]),
  }),
  Object.freeze({
    act: 'carry_on',
    label: 'Carry on',
    verb: null,
    effect: 'continue_running_step',
    receipt_kind: null,
    invariants: Object.freeze({ no_new_human_wait: true }),
    patterns: Object.freeze([
      /^carry on\b/i,
      /^keep going\b/i,
      /^continue\b/i,
      /^press on\b/i,
      /^carry\b/i,
    ]),
  }),
  Object.freeze({
    act: 'show_detail',
    label: 'Show detail',
    verb: 'roadmap-show',
    effect: 'open_artifact_or_drilldown_projection',
    receipt_kind: null,
    invariants: null,
    patterns: Object.freeze([
      /\bshow (?:me )?(?:the )?detail/i,
      /\bopen (?:the )?artifact\b/i,
      /\bdrill (?:down|in)\b/i,
      /^show (?:me )?more\b/i,
    ]),
  }),
  Object.freeze({
    act: 'park_that',
    label: 'Park that',
    verb: 'soft-vet',
    effect: 'grasscatch',
    receipt_kind: 'grasscatch',
    invariants: null,
    patterns: Object.freeze([
      /^park (?:that|this|it)\b/i,
      /\bpark (?:that|this|the) (?:idea|thought)\b/i,
      /\bgrasscatch\b/i,
      /\bsoft[- ]vet\b/i,
      /\bput (?:that|this|it) aside\b/i,
    ]),
  }),
  Object.freeze({
    act: 'recall_park',
    label: 'Recall park',
    verb: null,
    effect: 'grasscatch_recall',
    receipt_kind: null,
    invariants: null,
    patterns: Object.freeze([
      /\brecall (?:the )?park(?:ed)?\b/i,
      /\bunpark\b/i,
      /\brecall (?:the )?grasscatch\b/i,
      /\bbring back (?:the )?parked\b/i,
    ]),
  }),
  Object.freeze({
    act: 'bring_it_up',
    label: 'Bring it up',
    verb: 'brief',
    effect: 'open_packet_high_seat_altitude_hop',
    receipt_kind: null,
    invariants: Object.freeze({ packet_pre_gathered: true }),
    patterns: Object.freeze([
      /^bring it up\b/i,
      /\bbring (?:that|this) up\b/i,
      /\bopen (?:the )?packet\b/i,
    ]),
  }),
  Object.freeze({
    act: 'confirm_commission',
    label: 'Confirm commission',
    verb: 'commission-confirm',
    effect: 'confirm_steward_proposed_commission',
    receipt_kind: null,
    invariants: Object.freeze({ requires_prior_proposal: true }),
    patterns: Object.freeze([
      /\bconfirm (?:the )?commission\b/i,
      /^yes,? commission\b/i,
      /\bgo ahead with the commission\b/i,
    ]),
  }),
  Object.freeze({
    act: 'override',
    label: 'Override order / capacity',
    verb: null,
    effect: 'override_receipt',
    receipt_kind: 'override',
    invariants: Object.freeze({ requires_who_when_why_from_to: true }),
    patterns: Object.freeze([
      /^override\b/i,
      /\boverride (?:the )?(?:order|capacity|ranking)\b/i,
    ]),
  }),
  Object.freeze({
    act: 'switch_seat',
    label: 'Switch seat',
    verb: 'seat-hop',
    effect: 'seat_hop_receipt',
    receipt_kind: 'seat_hop',
    invariants: Object.freeze({ non_event: true, no_rebrief: true }),
    patterns: Object.freeze([
      /\bswitch (?:the )?seat\b/i,
      /\bswitch (?:seat )?to (?:the )?(claude|gemini|grok)\b/i,
      /\bseat[- ]hop\b/i,
      /\bhop (?:the )?seat\b/i,
      /\buse (?:the )?(claude|gemini|grok) seat\b/i,
    ]),
  }),
  Object.freeze({
    act: 'seen_dismiss',
    label: 'Seen / dismiss',
    verb: 'brief',
    effect: 'seen_receipt',
    receipt_kind: 'seen',
    invariants: null,
    patterns: Object.freeze([
      /^seen\b/i,
      /^dismiss\b/i,
      /\bmark (?:as |it )?seen\b/i,
      /^got it\b/i,
    ]),
  }),
]);

/** Closed act ids in table order. */
export const DIALOGUE_ACT_IDS = Object.freeze(ACT_TABLE.map((a) => a.act));

/**
 * Free-form destruction never compiles to a verb — always refuse-with-proposal.
 * (There is no delete/drop verb on the closed list; this guard makes the
 * refusal explicit rather than an accidental pattern miss.)
 */
export const DESTRUCTIVE_PATTERNS = Object.freeze([
  /\bdelete\b/i,
  /\bdrop\b/i,
  /\bwipe\b/i,
  /\bdestroy\b/i,
  /\berase\b/i,
  /\bpurge\b/i,
  /\bremove all\b/i,
  /\brm\s+-rf\b/i,
  /\bkill all\b/i,
]);

/**
 * @param {*} text
 * @returns {boolean}
 */
export function matchesDestructive(text) {
  if (typeof text !== 'string') return false;
  return DESTRUCTIVE_PATTERNS.some((re) => re.test(text));
}

/**
 * Structured refuse-with-proposal. Compile refusal writes NOTHING:
 * no ledger entry, no receipt, no chat persistence.
 * @param {string} text the free-form utterance
 * @param {{ reason?: string }} [opts]
 */
export function refuseWithProposal(text, opts = {}) {
  const trimmed = typeof text === 'string' ? text.trim() : String(text ?? '');
  const destructive = matchesDestructive(trimmed);
  return {
    ok: false,
    error: 'refuse_with_proposal',
    spelling: SPELLING,
    compiled: false,
    act: null,
    utterance_kind: destructive
      ? 'destructive_free_form'
      : 'unrecognized_free_form',
    ledger_write: false,
    receipt_written: false,
    dialogue_persisted: false,
    proposal: {
      suggested_act: 'park_that',
      suggested_verb: 'soft-vet',
      message: destructive
        ? `${SPELLING} will not compile destructive free-form talk to a verb. Nothing was deleted and nothing was written to the ledger. Closed paths: park the request (soft-vet receipt), or let the steward propose a commission you then confirm.`
        : `${SPELLING} could not compile that to a closed act. Nothing was written to the ledger. Pick a closed act below, or park the thought (soft-vet receipt).`,
      closed_acts: [...DIALOGUE_ACT_IDS],
      acts: ACT_TABLE.map((a) => ({
        act: a.act,
        label: a.label,
        verb: a.verb,
        effect: a.effect,
      })),
      ...(opts.reason ? { reason: opts.reason } : {}),
    },
  };
}

/** Per-act argument extractors (closed — only what the act table needs). */
function extractActArgs(act, text) {
  const args = {};
  if (act === 'switch_seat') {
    const m = text.match(/\b(claude|gemini|grok)\b/i);
    if (m) args.seat = m[1].toLowerCase();
  }
  if (act === 'refine_goal') {
    const m = text.match(
      /(?:refine|change|rewrite|update)(?: the)? goal(?: to)?[:\s]+(.+)$/i,
    );
    if (m) args.goal = m[1].trim();
    const n = text.match(/^new goal[:\s]+(.+)$/i);
    if (n) args.goal = n[1].trim();
  }
  if (act === 'park_that') {
    args.deferred = text.trim();
  }
  if (act === 'bring_it_up') {
    args.altitude = 'portfolio';
  }
  if (act === 'seen_dismiss') {
    args.mark_seen = true;
  }
  return args;
}

/**
 * Compile a free-form utterance against the v1 act table.
 * Pure function: compiling never runs a verb, never writes a ledger entry,
 * never persists the utterance. Returns either a compiled closed act or
 * refuse-with-proposal.
 * @param {string} text
 * @param {{ session?: object }} [ctx]
 */
export function compileUtterance(text, ctx = {}) {
  if (typeof text !== 'string' || !text.trim()) {
    return refuseWithProposal(text ?? '', { reason: 'empty_utterance' });
  }
  const trimmed = text.trim();

  // Destructive free-form is refused before any act matching.
  if (matchesDestructive(trimmed)) {
    return refuseWithProposal(trimmed);
  }

  for (const entry of ACT_TABLE) {
    if (entry.patterns.some((re) => re.test(trimmed))) {
      return {
        ok: true,
        spelling: SPELLING,
        compiled: true,
        act: entry.act,
        label: entry.label,
        verb: entry.verb,
        verb_closed: entry.verb ? isClosedVerb(entry.verb) : null,
        args: extractActArgs(entry.act, trimmed),
        effect: entry.effect,
        receipt_kind: entry.receipt_kind ?? null,
        invariants: entry.invariants ?? null,
        // Compile is read-only; receipts land only when the act is APPLIED.
        ledger_write: false,
        dialogue_persisted: false,
        session_seat: ctx.session?.seat ?? null,
      };
    }
  }

  return refuseWithProposal(trimmed);
}

// ---------------------------------------------------------------------------
// "Still the goal" → Face confirm receipt only

/**
 * Build a Face confirm receipt (act: still_the_goal).
 * @param {{ who: string, when?: string, goal?: string|null, as_of?: string }} fields
 */
export function buildFaceConfirmReceipt(fields = {}) {
  const when = nonEmpty(fields.when)
    ? String(fields.when)
    : new Date().toISOString();
  return {
    schema: RECEIPT_SCHEMA_ID,
    kind: 'face_confirm',
    as_of: fields.as_of ?? when.slice(0, 10),
    who: fields.who ?? null,
    when,
    goal: fields.goal ?? null,
    confirmed: true,
    act: 'still_the_goal',
  };
}

/**
 * Apply "Still the goal": the ONLY artifact is a Face confirm receipt.
 * No roadmap event, no Strip instrument, no Face narrative rewrite, no chat
 * persistence. When a Strip is provided the receipt is appended to its
 * append-only receipts[] (E5 sole ledger); nothing else on the Strip moves.
 * @param {{ who: string, when?: string, goal?: string|null, strip?: object|null, roadmap?: object|null }} opts
 */
export function applyStillTheGoal(opts = {}) {
  if (!nonEmpty(opts.who)) {
    return {
      ok: false,
      error: 'face_confirm_requires_who',
      spelling: SPELLING,
      message: 'Face confirm receipt requires who (the confirming human).',
    };
  }

  const receipt = buildFaceConfirmReceipt(opts);
  const validated = validateReceipt(receipt);
  if (!validated.ok) {
    return {
      ok: false,
      error: 'face_confirm_receipt_invalid',
      issues: validated.issues ?? [],
      message: validated.message,
    };
  }

  let strip = opts.strip ?? null;
  let strip_receipts_appended = 0;
  if (strip && typeof strip === 'object') {
    const appended = appendStripReceipt(strip, receipt, {
      apply_to_projection: false,
    });
    if (!appended.ok) return { ok: false, ...appended };
    strip = appended.strip;
    strip_receipts_appended = 1;
  }

  return {
    ok: true,
    act: 'still_the_goal',
    receipt,
    face_only: true,
    receipts: [receipt],
    roadmap_events_appended: 0,
    strip_instruments_appended: 0,
    strip_receipts_appended,
    // Roadmap passes through untouched — confirm is not a status flip.
    roadmap: opts.roadmap ?? null,
    strip,
    dialogue_persisted: false,
    message:
      'Still the goal → Face confirm receipt only (no Roadmap event, no Strip instrument, no chat ledger).',
  };
}

// ---------------------------------------------------------------------------
// Ephemeral dialogue store policy — no durable chat ledger

/**
 * E5, AS AMENDED 2026-08-05 (John's decision — recorded here because this reverses a
 * law that was locked, and a quiet reversal would be worse than the change itself).
 *
 * WAS: dialogue is ephemeral; chat is NEVER persisted; no second memory.
 * NOW: the conversation IS kept per project, and is NEVER AUTHORITATIVE.
 *
 * The reason for the change: the append-only roadmap already records WHAT the
 * scaffolding was at every turn, but not WHY it changed — the reasoning, the push-back,
 * the question that moved a stage. John asked to keep that history so the steward can
 * show "how the plan got to where it is".
 *
 * The reason the law is NARROW: E5 existed to prevent two sources of truth for project
 * STATE drifting apart with no rule for which wins. That failure is still prevented —
 * `state_surfaces` is unchanged, the transcript can never mint a step or flip a status,
 * and where transcript and ledger disagree THE LEDGER WINS. See conversation-log.mjs.
 */
export const DIALOGUE_STORE_POLICY = Object.freeze({
  policy: 'durable_non_authoritative',
  durable_chat_ledger: true,
  /** The whole point of the amendment: kept, but never a source of state. */
  authoritative_for_state: false,
  memory: 'project_conversation_log',
  /** UNCHANGED from E5 — the only surfaces that carry project state. */
  state_surfaces: Object.freeze([
    'strip_receipts',
    'strip_instruments',
    'roadmap_events',
    'face_narrative',
  ]),
  persists: Object.freeze([
    'strip_receipts',
    'strip_instruments',
    'roadmap_events',
    'face_narrative',
    'conversation_log',
  ]),
  /** What the transcript may NEVER do, however it is read. */
  never: Object.freeze([
    'mint_step',
    'flip_status',
    'authorize_spend',
    'commission',
  ]),
});

/**
 * Structured refuse for any attempt to make the transcript AUTHORITATIVE.
 *
 * The conversation is now kept (see DIALOGUE_STORE_POLICY), but only through the
 * project conversation log, and only as history. This refusal is what stops the
 * in-process session store from becoming a second source of project state — the exact
 * failure E5 was written to prevent, which the amendment preserves.
 */
export function refuseDurableChatLedger() {
  return {
    ok: false,
    error: 'authoritative_chat_ledger_forbidden',
    spelling: SPELLING,
    policy: DIALOGUE_STORE_POLICY.policy,
    authoritative_for_state: false,
    message:
      'The conversation is kept per project as HISTORY (conversation-log.mjs), never as a '
      + 'source of state. Strip receipts, roadmap events and the Face remain the only '
      + 'surfaces that carry project state — where they disagree with the transcript, they win.',
  };
}

/**
 * In-process, session-scoped dialogue store. Turns live in memory only;
 * endSession() drops them; persistToDisk() is a structured refuse.
 * JSON serialization never leaks turns (toJSON hides them).
 */
export function createDialogueStore() {
  let turns = [];
  return {
    policy: DIALOGUE_STORE_POLICY.policy,
    durable: false,
    note(turn) {
      turns.push({
        role: turn?.role ?? 'user',
        text: typeof turn === 'string' ? turn : (turn?.text ?? ''),
        at: turn?.at ?? null,
      });
      return { ok: true, ephemeral: true, size: turns.length };
    },
    turns() {
      return [...turns];
    },
    size() {
      return turns.length;
    },
    endSession() {
      const cleared = turns.length;
      turns = [];
      return { ok: true, cleared, persisted: false };
    },
    persistToDisk() {
      return refuseDurableChatLedger();
    },
    toJSON() {
      return {
        policy: DIALOGUE_STORE_POLICY.policy,
        durable_chat_ledger: false,
        turns_not_serialized: true,
        size: turns.length,
      };
    },
  };
}

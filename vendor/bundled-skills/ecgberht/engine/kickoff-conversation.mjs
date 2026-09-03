/**
 * Gate 5 / Wave 3 - the CONVERSATION's kickoff law: what the existing free-talk flow
 * (engine/steward-conversation.mjs converse()) needs to synthesize, refine, show and
 * confirm ONE complete kickoff_proposal_v0 bundle on the one store
 * (<folder>/.ecgberht/kickoff/events.jsonl) without a form, a precondition prompt, or an
 * execution leak. The flow stays the flow John already has - free talk, quiet synthesis,
 * conversational refinement, one confirmation; what changes is what it synthesizes and
 * where that lands.
 *
 * WHAT LIVES HERE - pure rules first, then the verbs the flow and the bridge call:
 *
 *   THE QUESTION CAP. At most KICKOFF_QUESTION_CAP (= 1) natural question per turn - the
 *   North Star's letter. The seat may write more; the engine delivers one and reports the
 *   rest as held, so a sparse opening never turns into a questionnaire.
 *
 *   THE THIN-PROPOSAL BOUND. A sparse or ambiguous opening reaches a THIN proposal by
 *   turn KICKOFF_THIN_PROPOSAL_BY_TURN (= 2). On that turn, with nothing open or
 *   confirmed and the seat still only talking, the flow runs the planning tier under
 *   THIN_BUNDLE_INSTRUCTION - the smallest honest bundle from what he actually said (the
 *   compiler generates nothing; the seat authors the thin bundle). If the seat still has
 *   no bundle, the turn ends in the AMBIGUOUS row with NO question attached: a thin
 *   bundle, never a third question, is the answer to ambiguity.
 *
 *   THE SILENT BOOTSTRAP. A new effort has no Face, no session envelope, no budget. None
 *   is a precondition for brainstorming and none is asked for: the Face is created ON
 *   confirmation, the envelope is materialized INSIDE the confirmation receipt (Wave 2),
 *   and until then the turn's spend rides the turn result. settleKickoffBootstrap names
 *   what is missing and that nothing was prompted.
 *
 *   THE LANE. A stood-up campaign (a Face already on disk) keeps the pre-Gate-5
 *   roadmap-ledger kickoff path the WH4 lane proves, BESIDE the store; a NEW effort (no
 *   Face) writes only the store, so during proposal and refinement the execution-leak
 *   sentinel sees nothing but .ecgberht/kickoff/ and the conversation log.
 *
 *   CONFIRM, SPOKEN. One hash-bound confirmation lands the receipt on the store (record
 *   hash AND rendered-prose hash), then the Wave 4 projection writer re-derives the
 *   read-model of record (.ecgberht/kickoff/projection.json + face.md) from that receipt,
 *   and the confirmed bundle is mirrored into the pre-Gate-5 projections the chamber
 *   paints today (roadmap plan entries, Face, Strip) - a mirror of the receipt, kept
 *   beside the store until the Wave 5 precedence work retires it.
 *
 * Failure states carry a status code AND user-visible text; missing, empty, ambiguous and
 * unknown are SEPARATE rows (kickoffConversationFailureTable). Stdlib only; nothing here
 * imports child_process. Source is ASCII on purpose (the repo's mojibake sweep).
 */

import path from 'node:path';

import { CONVERSATION_LOG_REL } from './conversation-log.mjs';
import {
  KICKOFF_STATE,
  confirmKickoffProposal,
  openKickoffProposal,
  readKickoffLineage,
  reproposeKickoff,
} from './kickoff-lifecycle.mjs';
import { writeKickoffProjection } from './kickoff-projection.mjs';
import { KICKOFF_CODE, KICKOFF_TEXT, compileKickoffProposal } from './kickoff-record.mjs';
import { confirmKickoff, proposeKickoff, showKickoff } from './kickoff.mjs';

// -- the named bounds ----------------------------------------------------------------

/** At most this many natural questions per turn. The North Star's letter. */
export const KICKOFF_QUESTION_CAP = 1;

/** A sparse or ambiguous opening has a (thin) proposal by this turn, or the AMBIGUOUS row. */
export const KICKOFF_THIN_PROPOSAL_BY_TURN = 2;

/**
 * What a kickoff CONVERSATION may write before confirmation: the store, and the durable,
 * non-authoritative conversation log (E5 as amended). Everything else written while a
 * new effort is being proposed or refined is a leak, by name - this is the allow-list the
 * one sentinel (engine/execution-leak-sentinel.mjs) is armed with for conversational
 * no-execution assertions.
 */
export const KICKOFF_CONVERSATION_ALLOW = Object.freeze([
  '.ecgberht/kickoff/',
  CONVERSATION_LOG_REL.split(path.sep).join('/'),
]);

/** Where the two silent-bootstrap absences are settled. Named once, asserted by tests. */
export const KICKOFF_FACE_CREATED_ON = 'kickoff_confirm';
export const KICKOFF_ENVELOPE_MATERIALIZED_IN = 'kickoff_confirm';

// -- failure states (conversational inputs) ------------------------------------------

export const KICKOFF_TALK_CODE = Object.freeze({
  MISSING: 'KICKOFF_TALK_MISSING',
  EMPTY: 'KICKOFF_TALK_EMPTY',
  AMBIGUOUS: 'KICKOFF_TALK_AMBIGUOUS',
});

export const KICKOFF_TALK_TEXT = Object.freeze({
  [KICKOFF_TALK_CODE.MISSING]:
    'Nothing came through - there is no utterance to synthesize. Nothing written.',
  [KICKOFF_TALK_CODE.EMPTY]:
    'That came through empty. Say what the effort should produce and I will frame it. Nothing written.',
  [KICKOFF_TALK_CODE.AMBIGUOUS]:
    'I could not settle that into one bundle by turn <turn>, and I will not ask a third question. '
    + 'Say the one thing this effort must produce and I will frame the thin version. Nothing written.',
});

/**
 * A conversational-input failure, shaped like the flow's other failures (say / text /
 * user_text carry the same sentence; nothing written, nothing persisted).
 *
 * @param {string} code
 * @param {object} [extra]
 */
export function kickoffTalkFailure(code, extra = {}) {
  const known = Object.hasOwn(KICKOFF_TALK_TEXT, code);
  let text = known ? KICKOFF_TALK_TEXT[code] : KICKOFF_TEXT[KICKOFF_CODE.STATE_UNKNOWN];
  const resolvedCode = known ? code : KICKOFF_CODE.STATE_UNKNOWN;
  text = text.replace(/<turn>/g, String(extra.turn ?? '?'));
  return {
    ok: false,
    code: resolvedCode,
    status_code: resolvedCode,
    error: extra.error ?? String(resolvedCode).toLowerCase(),
    say: text,
    text,
    user_text: text,
    lane: 'converse',
    conversational: true,
    proposal: null,
    asks: [],
    authoritative: false,
    ledger_write: false,
    dialogue_persisted: false,
    ...extra,
  };
}

/**
 * Machine-readable failure-state table for the conversational surface. `missing`,
 * `empty-but-valid`, `ambiguous` and `unknown` are SEPARATE rows; every row is a state
 * converse() can actually end in (the unknown / store rows surface the store's own
 * codes through the flow). Seat rows (unreachable, garbage, empty reply) stay with the
 * flow's CONVERSE_TEXT, which already owns them.
 *
 * @returns {ReadonlyArray<{state: string, surface: string, status_code: string, user_text: string}>}
 */
export function kickoffConversationFailureTable() {
  const row = (state, code, text) => Object.freeze({
    state,
    surface: 'conversation',
    status_code: code,
    user_text: text,
  });
  return Object.freeze([
    row('missing', KICKOFF_TALK_CODE.MISSING, KICKOFF_TALK_TEXT[KICKOFF_TALK_CODE.MISSING]),
    row('empty-but-valid', KICKOFF_TALK_CODE.EMPTY, KICKOFF_TALK_TEXT[KICKOFF_TALK_CODE.EMPTY]),
    row('ambiguous', KICKOFF_TALK_CODE.AMBIGUOUS, KICKOFF_TALK_TEXT[KICKOFF_TALK_CODE.AMBIGUOUS]),
    row('unknown', KICKOFF_CODE.STATE_UNKNOWN, KICKOFF_TEXT[KICKOFF_CODE.STATE_UNKNOWN]),
    row('backing-store-unreadable', KICKOFF_CODE.EVENTS_UNREADABLE, KICKOFF_TEXT[KICKOFF_CODE.EVENTS_UNREADABLE]),
    row('backing-store-corrupt', KICKOFF_CODE.CORRUPT, KICKOFF_TEXT[KICKOFF_CODE.CORRUPT]),
  ]);
}

// -- the pure rules ------------------------------------------------------------------

/**
 * Which turn this is, from the EPHEMERAL turns the caller holds (the browser page or the
 * test): one more than the number of John's turns so far. Deterministic; no clock, no
 * disk. A fresh session with an open draft never needs the count (the draft is shown).
 *
 * @param {Array<{role?: string}>} [turns]
 * @returns {number}
 */
export function kickoffTurnNumber(turns) {
  const list = Array.isArray(turns) ? turns : [];
  return 1 + list.filter((turn) => turn && String(turn.role ?? '').trim().toLowerCase() === 'john').length;
}

/**
 * Deliver at most `cap` questions; report the rest as held. Pure.
 *
 * @param {Array<string>} [asks]
 * @param {number} [cap]
 * @returns {{asks: string[], held: string[], cap: number}}
 */
export function capKickoffQuestions(asks, cap = KICKOFF_QUESTION_CAP) {
  const list = (Array.isArray(asks) ? asks : [])
    .map((ask) => String(ask ?? '').trim())
    .filter(Boolean);
  const bound = Number.isInteger(cap) && cap >= 0 ? cap : KICKOFF_QUESTION_CAP;
  return { asks: list.slice(0, bound), held: list.slice(bound), cap: bound };
}

/**
 * Does this turn owe a THIN proposal? Yes when the turn has reached the bound and the
 * effort is still unframed: no kickoff confirmed, no proposal of any kind open, no
 * confirmed roadmap step (an established campaign is never re-kicked-off by a count).
 *
 * @param {{turn_number: number, open_proposal?: object|null, confirmed_kickoff?: object|null,
 *   step_count?: number}} input
 * @returns {boolean}
 */
export function kickoffNeedsThinProposal(input = {}) {
  return Number(input.turn_number) >= KICKOFF_THIN_PROPOSAL_BY_TURN
    && input.open_proposal == null
    && input.confirmed_kickoff == null
    && !(Number(input.step_count) > 0);
}

/**
 * The block the planning tier receives on a thin turn. Deliberately a SEPARATE block:
 * the standing instructions are bound to recorded tapes and stay byte-identical.
 */
export const THIN_BUNDLE_INSTRUCTION = [
  '--- THIN BUNDLE NOW (turn <turn> of a sparse opening) ---',
  'You have asked what you may ask. Do not ask another question in place of a bundle.',
  'Return the SMALLEST honest kickoff bundle from what he actually said: one goal, one',
  'component, one plan entry marked end_to_end_slice (first_slice_id names it),',
  'integration null. Leave success_signals empty and done_when out unless he stated',
  'them. Use only words he supplied or plainly implied; invent nothing to fill a field.',
  'If one question would still help, it may ride in "asks" beside the bundle - never',
  'instead of it.',
].join('\n');

/** @param {number} turnNumber @returns {string} */
export function thinBundleInstruction(turnNumber) {
  return THIN_BUNDLE_INSTRUCTION.replace(/<turn>/g, String(turnNumber));
}

/**
 * Settle the session-open bootstrap SILENTLY. Nothing here prompts and nothing here
 * writes: it names what a new effort lacks and where each absence is settled later.
 * The turn's spend is deferred (rides the result) exactly when there is no session
 * envelope at all; an envelope that exists keeps its own law (debit, stop at the cap).
 *
 * @param {{face?: object|null, envelope_state?: object|null}} [input]
 */
export function settleKickoffBootstrap(input = {}) {
  const missing = [];
  if (input.face == null) missing.push('face');
  const env = input.envelope_state;
  const envelopeAbsent = env == null || env.empty === true;
  if (envelopeAbsent) missing.push('envelope', 'budget');
  else if (env.live !== true) missing.push('budget');
  return Object.freeze({
    silent: true,
    prompted: false,
    missing: Object.freeze(missing),
    envelope_absent: envelopeAbsent,
    spend_deferred: envelopeAbsent,
    face_created_on: KICKOFF_FACE_CREATED_ON,
    envelope_materialized_in: KICKOFF_ENVELOPE_MATERIALIZED_IN,
  });
}

/**
 * The pre-Gate-5 lane: a stood-up campaign (a parsed Face on disk) keeps the roadmap-ledger
 * kickoff path beside the store. A NEW effort has no Face by definition (it is created on
 * confirmation) and writes only the store.
 *
 * @param {{narrative?: object|null}} [context] a loadStewardContext() result
 * @returns {boolean}
 */
export function usesLegacyRoadmapLane(context) {
  return context?.narrative != null;
}

// -- the verbs -----------------------------------------------------------------------

/**
 * Open the WHOLE bundle the seat authored on the store: v1 on an empty lineage, a
 * superseding proposal at the same version before a confirmation, v(n+1) after one -
 * the Wave 2 verbs, chosen by the lineage's state. The host asserts the seat lineage.
 *
 * @param {string} projectPath
 * @param {{bundle: object, seat_family?: string, driver?: string, client_event_id?: string,
 *   source_turn_id?: string|null, source_turn_at?: string|null, at?: string, timeoutMs?: number}} opts
 */
export function openKickoffBundle(projectPath, opts = {}) {
  const lineage = readKickoffLineage(projectPath);
  if (!lineage.ok) return lineage;
  const verb = lineage.state === KICKOFF_STATE.EMPTY ? openKickoffProposal : reproposeKickoff;

  // Repeat-idempotence, by CONTENT. The record hash carries its source turn, so the same
  // bundle re-authored on a later turn compiles to a new hash and would supersede itself
  // on the store. Compile the candidate under the OPEN record's own source turn: when it
  // IS that record, re-open under that source turn and the store's own idempotent branch
  // answers with the open proposal - the same bundle again IS the open proposal, and
  // nothing is appended. Anything else (new content, a new seat) stays a real re-proposal.
  let sourceTurnId = opts.source_turn_id ?? null;
  let sourceTurnAt = opts.source_turn_at;
  const openTurnId = lineage.open?.source_turn?.client_event_id;
  if (openTurnId) {
    const candidate = compileKickoffProposal(opts.bundle, {
      seat_family: opts.seat_family,
      driver: opts.driver,
      version: lineage.open.version,
      prior_confirmed_hash: lineage.open.prior_confirmed_hash ?? null,
      source_turn_id: openTurnId,
      source_turn_at: lineage.open.source_turn?.at,
    });
    if (candidate.ok && candidate.proposal_hash === lineage.open.proposal_hash) {
      sourceTurnId = openTurnId;
      sourceTurnAt = lineage.open.source_turn?.at;
    }
  }

  const opened = verb(projectPath, {
    proposal: opts.bundle,
    seat_family: opts.seat_family,
    driver: opts.driver,
    client_event_id: opts.client_event_id,
    source_turn_id: sourceTurnId,
    source_turn_at: sourceTurnAt,
    at: opts.at,
    timeoutMs: opts.timeoutMs,
  });
  if (!opened.ok) return opened;
  return {
    ...opened,
    lineage_state_before: lineage.state,
    confirmed_version_before: lineage.confirmed?.version ?? null,
  };
}

/** The bundle CONTENT of a stored record - what the seat authored, nothing of the envelope. */
function bundleContentOf(record) {
  return {
    goal: record.goal,
    success_signals: [...(record.success_signals ?? [])],
    work_product: {
      id: record.work_product.id,
      name: record.work_product.name,
      components: (record.work_product.components ?? []).map((component) => ({ ...component })),
    },
    integration: record.integration == null
      ? null
      : {
        summary: record.integration.summary,
        relationships: (record.integration.relationships ?? []).map((relationship) => ({
          kind: relationship.kind,
          component_ids: [...(relationship.component_ids ?? [])],
          description: relationship.description,
        })),
        proof: { ...record.integration.proof },
      },
    plan_entries: (record.plan_entries ?? []).map((entry) => ({
      ...entry,
      component_ids: [...(entry.component_ids ?? [])],
    })),
    first_slice_id: record.first_slice_id,
  };
}

/**
 * Mirror a store-confirmed bundle into the pre-Gate-5 projections (roadmap plan entries,
 * Face, Strip) through the existing roadmap verbs. A mirror, never a source of truth: the
 * receipt on the store is what was confirmed. When the roadmap already carries the same
 * open hash (the legacy lane wrote both), only the confirm is appended; when it carries a
 * different lineage, the mirror confirms the roadmap's own hash and says `diverged`.
 */
function mirrorConfirmedKickoffToRoadmap(root, record, opts = {}) {
  const shown = showKickoff(root);
  if (!shown.ok) {
    return { ok: false, written: false, code: shown.code, error: shown.error, detail: shown };
  }
  if (shown.confirmed?.proposal_hash === record.proposal_hash) {
    return {
      ok: true,
      written: false,
      already: true,
      diverged: false,
      roadmap_proposal_hash: record.proposal_hash,
      plan_entries_written: 0,
      projection: null,
    };
  }
  let roadmapHash = shown.open?.proposal_hash === record.proposal_hash ? record.proposal_hash : null;
  if (!roadmapHash) {
    // The roadmap lacks this bundle (a new effort wrote only the store): append it there
    // with the record's own seat lineage and source turn, so a fresh roadmap re-derives
    // the same hash.
    const proposed = proposeKickoff(root, {
      proposal: bundleContentOf(record),
      seat_family: record.provenance?.seat_family,
      driver: record.provenance?.driver,
      source_turn_id: record.source_turn?.client_event_id ?? '',
      source_turn_at: record.source_turn?.at ?? '',
      client_event_id: `${opts.client_event_id}#mirror-propose`,
      project_id: opts.project_id,
      at: opts.at,
    });
    if (!proposed.ok) {
      return { ok: false, written: false, code: proposed.code, error: proposed.error, detail: proposed };
    }
    roadmapHash = proposed.proposal_hash;
  }
  const confirmed = confirmKickoff(root, {
    proposal_hash: roadmapHash,
    who: opts.who,
    client_event_id: opts.client_event_id,
    project_id: opts.project_id,
    at: opts.at,
  });
  if (!confirmed.ok) {
    return { ok: false, written: false, code: confirmed.code, error: confirmed.error, detail: confirmed };
  }
  return {
    ok: true,
    written: confirmed.ledger_write === true,
    already: confirmed.idempotent === true,
    diverged: roadmapHash !== record.proposal_hash,
    roadmap_proposal_hash: roadmapHash,
    plan_entries_written: confirmed.plan_entries_written ?? 0,
    projection: confirmed.projection ?? null,
    projection_pending: confirmed.projection_pending === true,
  };
}

/**
 * THE SPOKEN CONFIRMATION - the bridge's `--kickoff-confirm` and the chamber's one "yes".
 *
 * The record hash names a proposal on the store: the receipt is appended there, bound to
 * BOTH hashes John saw. When the caller did not send the rendered-prose hash (the pre-Gate-5
 * chamber sends the record hash alone), it is resolved from the stored record whose hash
 * matched - the fidelity law already pins that prose to that record - and the result says
 * so by name. A hash the store does not know falls through to the roadmap-only lane (a
 * project whose kickoff pre-dates the store). Then the confirmed bundle is mirrored into
 * the pre-Gate-5 projections (roadmap plan entries, Face, Strip) unless `mirror: false`.
 *
 * Idempotent by content (a repeated matching confirmation appends nothing anywhere) and
 * stale-safe (a superseded hash refuses with the store's named row and writes nothing).
 *
 * @param {string} projectPath
 * @param {{who: string|object, proposal_hash: string, rendered_prose_hash?: string,
 *   prior_confirmed_hash?: string|null, client_event_id?: string, project_id?: string|null,
 *   at?: string, mirror?: boolean, timeoutMs?: number}} opts
 */
export function confirmKickoffSpoken(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const providedHash = String(opts.proposal_hash ?? '').trim();
  const lineage = readKickoffLineage(root);
  if (!lineage.ok) return { ...lineage, lane: 'store', mirror: null };

  const named = lineage.proposals.find((proposal) => proposal.proposal_hash === providedHash) ?? null;
  if (!named) {
    const legacy = confirmKickoff(root, {
      proposal_hash: providedHash,
      prior_confirmed_hash: opts.prior_confirmed_hash,
      who: opts.who,
      client_event_id: opts.client_event_id,
      project_id: opts.project_id,
      at: opts.at,
    });
    return { ...legacy, lane: 'roadmap', store_state: lineage.state, mirror: null };
  }

  let proseHash = String(opts.rendered_prose_hash ?? '').trim();
  const resolved = !proseHash;
  if (resolved) proseHash = named.rendered_prose_hash;
  const receipt = confirmKickoffProposal(root, {
    who: opts.who,
    proposal_hash: providedHash,
    rendered_prose_hash: proseHash,
    client_event_id: opts.client_event_id,
    at: opts.at,
    timeoutMs: opts.timeoutMs,
  });
  if (!receipt.ok) return { ...receipt, lane: 'store', mirror: null };

  // The Wave 4 writer: the Face and projection.json are re-derived from the receipt at
  // every matching confirmation - byte-identical on a repeat, so double-confirm is
  // harmless downstream. A refused receipt above never reaches this line, which is what
  // keeps the Face absent on open, rejected, and stale paths.
  const storeProjection = writeKickoffProjection(root, { timeoutMs: opts.timeoutMs });

  const mirror = opts.mirror === false
    ? null
    : mirrorConfirmedKickoffToRoadmap(root, receipt.proposal, {
      who: opts.who,
      client_event_id: receipt.receipt?.client_event_id ?? opts.client_event_id,
      project_id: opts.project_id,
      at: opts.at,
    });
  return {
    ...receipt,
    lane: 'store',
    rendered_prose_hash_resolved_from_store: resolved,
    mirror,
    face_created_on: KICKOFF_FACE_CREATED_ON,
    store_projection: storeProjection,
    projection_written: storeProjection.ok === true && storeProjection.projection_written === true,
    face_written: storeProjection.ok === true && storeProjection.face_written === true,
    projection: mirror?.projection ?? null,
    projection_pending: mirror ? mirror.ok !== true || mirror.projection_pending === true : false,
    plan_entries_written: mirror?.plan_entries_written ?? 0,
  };
}

/** A record as the chamber shows it: the prose John reads and the two hashes he confirms. */
function shownRecord(record) {
  if (!record) return null;
  return {
    version: record.version,
    proposal_id: record.proposal_id,
    proposal_hash: record.proposal_hash,
    rendered_prose: record.rendered_prose,
    rendered_prose_hash: record.rendered_prose_hash,
    prior_confirmed_hash: record.prior_confirmed_hash ?? null,
    goal: record.goal,
    supersedes: record.supersedes ?? null,
    appended_at: record.appended_at ?? null,
  };
}

/**
 * Read-only: what a session paints from the store alone - the confirmed kickoff and any
 * open (draft, not applied) proposal, each with its prose and hashes, plus the pre-Gate-5
 * roadmap view beside it for the chamber that still reads it.
 *
 * @param {string} projectPath
 */
export function showKickoffSpoken(projectPath) {
  const root = path.resolve(projectPath);
  const lineage = readKickoffLineage(root);
  if (!lineage.ok) return lineage;
  const legacy = showKickoff(root);
  return {
    ok: true,
    project_path: root,
    state: lineage.state,
    status_code: lineage.status_code,
    user_text: lineage.user_text,
    authoritative: lineage.authoritative,
    confirmed: shownRecord(lineage.confirmed),
    open: shownRecord(lineage.open),
    receipt: lineage.receipt
      ? { receipt_hash: lineage.receipt.receipt_hash, who: lineage.receipt.who, at: lineage.receipt.at }
      : null,
    receipt_count: lineage.receipt_count,
    proposal_count: lineage.proposal_count,
    superseded: lineage.superseded,
    next_version: lineage.next_version,
    legacy_roadmap: legacy.ok
      ? {
        ok: true,
        confirmed_hash: legacy.confirmed?.proposal_hash ?? null,
        open_hash: legacy.open?.proposal_hash ?? null,
        roadmap_exists: legacy.roadmap_exists === true,
      }
      : { ok: false, code: legacy.code, error: legacy.error },
  };
}

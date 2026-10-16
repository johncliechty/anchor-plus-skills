/**
 * Gate 5 / Wave 2 - the kickoff LIFECYCLE on the one store:
 *
 *     <folder>/.ecgberht/kickoff/events.jsonl
 *
 * Append-only. One LF-terminated line per event, sorted keys at every depth, UTF-8, no
 * floats (a float is refused by name before a byte is written). Two event kinds only:
 *
 *   kickoff_proposal  - an OPEN proposal: the model-authored record + its hash AND the prose
 *                       John reviewed + its hash. Non-authoritative. Any number may be
 *                       appended; the LATEST one at the next version is "the open proposal",
 *                       and every earlier one at that version is superseded - never edited.
 *   kickoff_confirm   - the receipt. The ONLY durable commit seam. Hash-bound to BOTH the
 *                       record hash and the rendered-prose hash, so what became authoritative
 *                       is exactly what was shown, byte for hash. The session envelope is
 *                       materialized INSIDE the receipt (its terms + terms hash), so nothing
 *                       envelope-shaped exists on disk before confirmation.
 *
 * WHY EVENTS AND NOT A DOCUMENT. A document that is rewritten on every proposal is a
 * document one interrupted rewrite can shorten, and a field that can be edited in place is
 * a field somebody will edit in place. The lineage law from engine/kickoff.mjs (optimistic
 * CAS on prior_confirmed_hash, corrupt-lineage naming) is kept; the store moves to a log
 * that is only ever appended to through the D-1 append primitive (engine/append-log.mjs:
 * open in append mode, ONE write, fsync, close) under the same cross-process lock every
 * other durable write in this engine uses. A correction - "merge those two", "that is not
 * the goal" - is a whole new bundle through the same verb: v(n+1) after a confirmation, a
 * superseding proposal at the same version before one. No verb here takes a field.
 *
 * A fresh session resolves the latest OPEN version from the store alone: nothing is held in
 * memory that the file does not carry, so a restart paints the same proposal.
 *
 * Idempotence is by content: a repeated matching confirmation finds its receipt and appends
 * nothing; every downstream output is re-derived from the receipt lineage by one pure
 * function (deriveConfirmedKickoff) and is therefore byte-identical on every re-derivation.
 * A stale confirmation (a hash that names a superseded proposal) refuses with a named row
 * and writes nothing - not a receipt, not a projection, not a Face, not an envelope.
 *
 * Failure states carry a status code AND user-visible text, with `unknown` and `empty` as
 * separate rows (kickoffLifecycleFailureTable). Reads are bounded by KICKOFF_EVENTS_MAX_BYTES
 * and refuse past it. Stdlib only. Source is ASCII on purpose (the repo's mojibake sweep).
 */

import fs from 'node:fs';
import path from 'node:path';

import { appendLineAt, readLogHead } from './append-log.mjs';
import { LOCK_TIMEOUT_MS, withFileLock } from './durable-write.mjs';
import { WHO_PROVENANCE, normalizeClaimedWho } from './identity-policy.mjs';
import {
  KICKOFF_CODE,
  KICKOFF_PROPOSAL_KIND,
  KICKOFF_TEXT,
  canonicalKickoffBytes,
  compileKickoffProposal,
  kickoffFailure,
  kickoffHashBody,
  recomputeKickoffHash,
  renderKickoffProposal,
  sha256Hex,
  validateKickoffProposal,
} from './kickoff-record.mjs';
import { ENVELOPE_TERMS_SCHEMA, currentBudgetTermsHash } from './session-envelope.mjs';

/** The store, relative to the effort folder. */
export const KICKOFF_DIR_REL = path.join('.ecgberht', 'kickoff');
export const KICKOFF_EVENTS_FILE = 'events.jsonl';
export const KICKOFF_EVENTS_REL = path.join(KICKOFF_DIR_REL, KICKOFF_EVENTS_FILE);

/** The named read bound: a store larger than this refuses to be read, by name. */
export const KICKOFF_EVENTS_MAX_BYTES = 16 * 1024 * 1024;

export const KICKOFF_RECEIPT_SCHEMA = 'ecgberht-kickoff-receipt-v0';

export const KICKOFF_EVENT_KIND = Object.freeze({
  PROPOSAL: KICKOFF_PROPOSAL_KIND,
  CONFIRM: 'kickoff_confirm',
});

export const KICKOFF_STATE = Object.freeze({
  EMPTY: 'empty',
  OPEN: 'open',
  CONFIRMED: 'confirmed',
  STALE: 'stale',
  UNKNOWN: 'unknown',
});

/** Named durability helpers (removal-proof, the S4 pattern). */
export const KICKOFF_APPEND_PRIMITIVE = 'appendLineAt';
export const KICKOFF_LOCK_HELPER = 'withFileLock';

const HEX64 = /^[a-f0-9]{64}$/;
const cleanText = (value) => String(value ?? '').trim();

function deepFreeze(value) {
  if (value && typeof value === 'object' && !ArrayBuffer.isView(value) && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

/** @param {string} projectPath @returns {string} absolute path of events.jsonl */
export function kickoffEventsPath(projectPath) {
  return path.join(path.resolve(projectPath), KICKOFF_EVENTS_REL);
}

/**
 * Machine-readable failure-state table for the lifecycle surface. `unknown` and
 * `empty-but-valid` are SEPARATE rows; every row is speakable by this module.
 *
 * @returns {ReadonlyArray<{state: string, surface: string, status_code: string, user_text: string}>}
 */
export function kickoffLifecycleFailureTable() {
  const row = (state, code) => Object.freeze({
    state,
    surface: 'lifecycle',
    status_code: code,
    user_text: KICKOFF_TEXT[code],
  });
  return Object.freeze([
    row('empty-but-valid', KICKOFF_CODE.NONE_YET),
    row('open', KICKOFF_CODE.OPEN_UNCONFIRMED),
    row('confirmed', KICKOFF_CODE.CONFIRMED),
    row('stale', KICKOFF_CODE.STALE),
    row('dependency-returns-garbage / hash-mismatch', KICKOFF_CODE.HASH_MISMATCH),
    row('who-required', KICKOFF_CODE.WHO_REQUIRED),
    row('backing-store-unreadable', KICKOFF_CODE.EVENTS_UNREADABLE),
    row('backing-store-corrupt', KICKOFF_CODE.CORRUPT),
    row('bound-exceeded', KICKOFF_CODE.EVENTS_BOUND_EXCEEDED),
    row('write-failed', KICKOFF_CODE.WRITE_FAILED),
    row('nothing-confirmed', KICKOFF_CODE.NOTHING_CONFIRMED),
    row('unknown', KICKOFF_CODE.STATE_UNKNOWN),
  ]);
}

// -- the store -------------------------------------------------------------------

/**
 * Read the store to its head, bounded. On the write path (under the lock) a torn tail is
 * quarantined beside the log; on the read path it is only reported, so a read writes nothing.
 */
function readEvents(eventsPath, opts = {}) {
  const maxBytes = Number.isInteger(opts.max_bytes) ? opts.max_bytes : KICKOFF_EVENTS_MAX_BYTES;
  let size = 0;
  try {
    size = fs.statSync(eventsPath).size;
  } catch (error) {
    if (error?.code !== 'ENOENT') {
      return kickoffFailure(KICKOFF_CODE.EVENTS_UNREADABLE, {
        error: error?.code ?? 'stat_failed',
        detail: String(error?.message ?? error),
      });
    }
  }
  if (size > maxBytes) {
    return kickoffFailure(KICKOFF_CODE.EVENTS_BOUND_EXCEEDED, {
      error: `${size}_bytes_over_${maxBytes}`,
      size,
      max_bytes: maxBytes,
    });
  }
  const write = opts.write === true;
  const head = readLogHead(eventsPath, { write, quarantine: write });
  if (!head.ok) {
    // The primitive keeps presence and integrity apart: bytes that could not be obtained
    // carry no integrity verdict at all (null). That is "unreadable"; a line that will not
    // parse is "corrupt". Two facts, two rows.
    const errno = head.recovery?.errno ?? null;
    if (errno || head.recovery?.integrity === null) {
      return kickoffFailure(KICKOFF_CODE.EVENTS_UNREADABLE, {
        error: errno ?? 'events_unreachable',
        detail: head.outcome?.text ?? null,
      });
    }
    const first = head.recovery?.interior_problems?.[0] ?? null;
    return kickoffFailure(KICKOFF_CODE.CORRUPT, {
      error: 'kickoff_events_line_unparseable',
      at_line: first?.line ?? null,
      detail: first?.reason ?? head.outcome?.text ?? null,
    });
  }
  return {
    ok: true,
    events: head.events,
    size: head.size,
    head_seq: head.head_seq,
    torn_quarantined: (head.recovery?.quarantined_count ?? 0) > 0,
  };
}

/** One canonical line: sorted keys, UTF-8, no floats, one trailing LF. Refuses by name. */
function eventLine(event) {
  const canonical = canonicalKickoffBytes(event);
  if (!canonical.ok) return canonical;
  return { ok: true, line: `${canonical.text}\n` };
}

/** Append one event through the D-1 primitive; the seq-conflict guard is the store's size. */
function appendEventLine(eventsPath, event, expectedSize) {
  const line = eventLine(event);
  if (!line.ok) return line;
  const result = appendLineAt(eventsPath, line.line, { expected_size: expectedSize });
  if (result.ok !== true) {
    return kickoffFailure(KICKOFF_CODE.WRITE_FAILED, {
      error: result.code ?? 'kickoff_append_failed',
      detail: result.text ?? null,
    });
  }
  return { ok: true, bytes_written: result.bytes_written, size_after: result.size_after };
}

function withEventsLock(eventsPath, opts, fn) {
  try {
    return withFileLock(eventsPath, fn, { timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS });
  } catch (error) {
    if (error?.code === 'ELOCKTIMEOUT') {
      // The state could not be read while another writer held it: unknown, not guessed.
      return kickoffFailure(KICKOFF_CODE.STATE_UNKNOWN, {
        error: 'kickoff_lock_contended',
        detail: String(error?.message ?? error),
      });
    }
    return kickoffFailure(KICKOFF_CODE.WRITE_FAILED, {
      error: 'kickoff_store_failed',
      detail: String(error?.message ?? error),
    });
  }
}

// -- the lineage (pure) ----------------------------------------------------------

function corrupt(error, event, extra = {}) {
  return kickoffFailure(KICKOFF_CODE.CORRUPT, {
    error,
    at_seq: event?.seq ?? null,
    ...extra,
  });
}

/**
 * Project the lineage from the events in seq order. Pure: no clock, no disk.
 *
 * The record law is applied on read (a tampered stored record refuses), and the fidelity
 * law too: the stored prose must be the renderer's prose of the stored record and must
 * re-hash to the stored prose hash. A confirm that names no proposal, a second receipt for
 * one hash, or a receipt off the lineage is CORRUPT, named by seq - never reinterpreted.
 *
 * @param {Array<object>} events
 * @returns {{ok: true, state: string, confirmed: object|null, receipt: object|null,
 *   receipts: ReadonlyArray<object>, open: object|null, proposals: ReadonlyArray<object>,
 *   superseded: ReadonlyArray<string>, next_version: number, prior_confirmed_hash: string|null,
 *   proposal_count: number, receipt_count: number} | object}
 */
export function projectKickoffLineage(events) {
  const byHash = new Map();
  const order = [];
  const receipts = [];
  const receipted = new Set();
  let confirmed = null;
  let receipt = null;

  for (const event of Array.isArray(events) ? events : []) {
    if (event?.kind === KICKOFF_EVENT_KIND.PROPOSAL) {
      const proposal = event.proposal;
      const valid = validateKickoffProposal(proposal);
      if (!valid.ok) return corrupt('kickoff_proposal_corrupt', event, { issue: valid });
      if (proposal.proposal_hash !== valid.expected_hash) {
        return corrupt('kickoff_proposal_hash_corrupt', event, { expected_hash: valid.expected_hash });
      }
      const rendered = renderKickoffProposal(proposal);
      if (!rendered.ok || event.rendered_prose !== rendered.prose
          || event.rendered_prose_hash !== rendered.prose_hash) {
        return corrupt('kickoff_prose_is_not_render_of_record', event);
      }
      const record = deepFreeze({
        ...proposal,
        rendered_prose: event.rendered_prose,
        rendered_prose_hash: event.rendered_prose_hash,
        event_seq: event.seq,
        appended_at: event.at ?? null,
        client_event_id: event.client_event_id ?? null,
        supersedes: event.supersedes ?? null,
      });
      const prior = byHash.get(proposal.proposal_hash);
      if (prior) {
        const same = canonicalKickoffBytes(kickoffHashBody(prior)).text
          === canonicalKickoffBytes(kickoffHashBody(record)).text;
        if (!same) return corrupt('kickoff_hash_reused_for_different_content', event);
        continue; // an identical re-append changes nothing
      }
      byHash.set(proposal.proposal_hash, record);
      order.push(record);
      continue;
    }
    if (event?.kind !== KICKOFF_EVENT_KIND.CONFIRM) {
      return corrupt('kickoff_event_kind_unknown', event, { kind: event?.kind ?? null });
    }
    const proposal = byHash.get(event.proposal_hash);
    if (!proposal) {
      return corrupt('kickoff_confirm_without_proposal', event, {
        proposal_hash: event.proposal_hash ?? null,
      });
    }
    if (receipted.has(proposal.proposal_hash)) {
      return corrupt('kickoff_duplicate_receipt', event, { proposal_hash: proposal.proposal_hash });
    }
    const priorHash = confirmed?.proposal_hash ?? null;
    if (proposal.prior_confirmed_hash !== priorHash
        || event.prior_confirmed_hash !== priorHash
        || event.version !== proposal.version
        || proposal.version !== (confirmed?.version ?? 0) + 1
        || event.rendered_prose_hash !== proposal.rendered_prose_hash) {
      return corrupt('kickoff_confirmation_lineage_invalid', event, {
        proposal_hash: proposal.proposal_hash,
        expected_prior_confirmed_hash: priorHash,
      });
    }
    confirmed = proposal;
    receipt = deepFreeze({ ...event });
    receipts.push(receipt);
    receipted.add(proposal.proposal_hash);
  }

  const nextVersion = (confirmed?.version ?? 0) + 1;
  const priorHash = confirmed?.proposal_hash ?? null;
  let open = null;
  for (const proposal of order) {
    if (!receipted.has(proposal.proposal_hash)
        && proposal.version === nextVersion
        && proposal.prior_confirmed_hash === priorHash) {
      open = proposal;
    }
  }
  const state = open ? KICKOFF_STATE.OPEN : confirmed ? KICKOFF_STATE.CONFIRMED : KICKOFF_STATE.EMPTY;
  return {
    ok: true,
    state,
    confirmed,
    receipt,
    receipts: Object.freeze(receipts),
    open,
    proposals: Object.freeze(order),
    superseded: Object.freeze(order
      .filter((proposal) => proposal !== open && !receipted.has(proposal.proposal_hash))
      .map((proposal) => proposal.proposal_hash)),
    next_version: nextVersion,
    prior_confirmed_hash: priorHash,
    proposal_count: order.length,
    receipt_count: receipts.length,
  };
}

function withStatus(lineage) {
  const code = lineage.state === KICKOFF_STATE.OPEN
    ? KICKOFF_CODE.OPEN_UNCONFIRMED
    : lineage.state === KICKOFF_STATE.CONFIRMED ? KICKOFF_CODE.CONFIRMED : KICKOFF_CODE.NONE_YET;
  return {
    ...lineage,
    code,
    status_code: code,
    user_text: KICKOFF_TEXT[code],
    authoritative: lineage.confirmed != null,
  };
}

/**
 * Read-only: the lineage as the store carries it. A fresh session calls this and nothing
 * else to find the latest OPEN version and the confirmed one.
 *
 * @param {string} projectPath @param {{max_bytes?: number}} [opts]
 */
export function readKickoffLineage(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const eventsPath = kickoffEventsPath(root);
  const read = readEvents(eventsPath, { ...opts, write: false });
  if (!read.ok) return read;
  const lineage = projectKickoffLineage(read.events);
  if (!lineage.ok) return lineage;
  return withStatus({
    ...lineage,
    project_path: root,
    events_path: eventsPath,
    event_count: read.events.length,
    events_bytes: read.size,
  });
}

// -- open (propose) ----------------------------------------------------------------

/**
 * Append one OPEN proposal: the whole bundle, compiled with the host-asserted seat lineage
 * (a provenance-less or zero_model input is refused BEFORE any directory exists), versioned
 * against the lineage under the lock. Non-authoritative: nothing downstream changes.
 *
 * @param {string} projectPath
 * @param {{proposal?: object, seat_family?: string, driver?: string, provenance?: object,
 *   client_event_id?: string, at?: string, timeoutMs?: number}} [opts]
 */
export function openKickoffProposal(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const eventsPath = kickoffEventsPath(root);
  const input = opts.proposal ?? opts;
  const host = {
    seat_family: opts.seat_family,
    driver: opts.driver,
    provenance: opts.provenance,
    source_turn_id: opts.source_turn_id ?? opts.client_event_id ?? null,
    source_turn_at: opts.source_turn_at ?? opts.at ?? null,
  };
  // Refusal before any write: with nothing on disk yet, provenance and content are judged.
  const preflight = compileKickoffProposal(input, { ...host, version: 1, prior_confirmed_hash: null });
  if (!preflight.ok) return preflight;

  return withEventsLock(eventsPath, opts, () => {
    const read = readEvents(eventsPath, { ...opts, write: true });
    if (!read.ok) return read;
    const lineage = projectKickoffLineage(read.events);
    if (!lineage.ok) return lineage;

    if (input.version != null && Number(input.version) !== lineage.next_version) {
      return kickoffFailure(KICKOFF_CODE.STALE, {
        error: 'proposal_version_stale',
        expected_version: lineage.next_version,
        provided_version: Number(input.version),
      });
    }
    if (input.prior_confirmed_hash !== undefined
        && input.prior_confirmed_hash !== lineage.prior_confirmed_hash) {
      return kickoffFailure(KICKOFF_CODE.STALE, {
        error: 'proposal_prior_confirmation_stale',
        expected_prior_confirmed_hash: lineage.prior_confirmed_hash,
        provided_prior_confirmed_hash: input.prior_confirmed_hash,
      });
    }
    const compiled = compileKickoffProposal(input, {
      ...host,
      version: lineage.next_version,
      prior_confirmed_hash: lineage.prior_confirmed_hash,
    });
    if (!compiled.ok) return compiled;

    const displayed = lineage.open ?? lineage.confirmed;
    const base = {
      events_path: eventsPath,
      project_path: root,
      phase: 'open',
      state: KICKOFF_STATE.OPEN,
      authoritative: false,
      applied: false,
      status_code: KICKOFF_CODE.OPEN_UNCONFIRMED,
      user_text: KICKOFF_TEXT[KICKOFF_CODE.OPEN_UNCONFIRMED],
      receipt: null,
      face_written: false,
      envelope_written: false,
    };
    if (lineage.open && lineage.open.proposal_hash === compiled.proposal_hash) {
      // The same bundle again: the open proposal already IS this one. Nothing appended.
      return {
        ok: true,
        ...base,
        idempotent: true,
        proposal: lineage.open,
        proposal_id: lineage.open.proposal_id,
        proposal_hash: lineage.open.proposal_hash,
        rendered_prose: lineage.open.rendered_prose,
        rendered_prose_hash: lineage.open.rendered_prose_hash,
        version: lineage.open.version,
        prior_confirmed_hash: lineage.open.prior_confirmed_hash,
        supersedes: lineage.open.supersedes,
        event: null,
      };
    }

    const at = cleanText(opts.at) || new Date().toISOString();
    const event = {
      seq: read.head_seq + 1,
      at,
      kind: KICKOFF_EVENT_KIND.PROPOSAL,
      client_event_id: cleanText(opts.client_event_id)
        || `kickoff-propose-${compiled.proposal_hash.slice(0, 16)}`,
      supersedes: displayed?.proposal_hash ?? null,
      proposal: compiled.proposal,
      rendered_prose: compiled.rendered_prose,
      rendered_prose_hash: compiled.rendered_prose_hash,
    };
    const appended = appendEventLine(eventsPath, event, read.size);
    if (!appended.ok) return appended;
    const record = deepFreeze({
      ...compiled.proposal,
      rendered_prose: compiled.rendered_prose,
      rendered_prose_hash: compiled.rendered_prose_hash,
      event_seq: event.seq,
      appended_at: at,
      client_event_id: event.client_event_id,
      supersedes: event.supersedes,
    });
    return {
      ok: true,
      ...base,
      idempotent: false,
      proposal: record,
      proposal_id: record.proposal_id,
      proposal_hash: record.proposal_hash,
      rendered_prose: record.rendered_prose,
      rendered_prose_hash: record.rendered_prose_hash,
      version: record.version,
      prior_confirmed_hash: record.prior_confirmed_hash,
      supersedes: record.supersedes,
      event: deepFreeze(event),
    };
  });
}

/**
 * A spoken correction is a WHOLE new bundle through the same verb - v(n+1) after a
 * confirmation, a superseding proposal at the same version before one. It requires a
 * lineage to correct; on an empty store there is nothing to re-propose.
 */
export function reproposeKickoff(projectPath, opts = {}) {
  const lineage = readKickoffLineage(projectPath, opts);
  if (!lineage.ok) return lineage;
  if (lineage.state === KICKOFF_STATE.EMPTY) {
    return kickoffFailure(KICKOFF_CODE.NONE_YET, { error: 'nothing_to_correct' });
  }
  const opened = openKickoffProposal(projectPath, opts);
  if (!opened.ok) return opened;
  return { ...opened, phase: 'reproposed', corrected_from: opened.supersedes };
}

// -- confirm (the one commit seam) -------------------------------------------------

/** The session envelope, materialized inside the receipt and nowhere else. */
function materializeEnvelope() {
  const { terms, terms_hash: termsHash } = currentBudgetTermsHash();
  return {
    schema: ENVELOPE_TERMS_SCHEMA,
    terms,
    terms_hash: termsHash,
    materialized_in: KICKOFF_EVENT_KIND.CONFIRM,
  };
}

/**
 * Every downstream output, re-derived from the receipt lineage by this ONE pure function:
 * the record's canonical bytes, the rendered prose, the receipt's canonical bytes, the
 * envelope block, and the open-draft summary. Byte-identical on every call for one lineage.
 *
 * @param {object} lineage a readKickoffLineage / projectKickoffLineage result
 */
export function deriveConfirmedKickoff(lineage) {
  if (!lineage || lineage.ok !== true) {
    return lineage ?? kickoffFailure(KICKOFF_CODE.STATE_UNKNOWN, { error: 'lineage_missing' });
  }
  if (!lineage.confirmed || !lineage.receipt) {
    return kickoffFailure(KICKOFF_CODE.NOTHING_CONFIRMED, {
      error: 'no_confirmed_kickoff',
      state: lineage.state,
    });
  }
  const proposal = lineage.confirmed;
  const receipt = lineage.receipt;
  const record = canonicalKickoffBytes(kickoffHashBody(proposal));
  if (!record.ok) return record;
  const rendered = renderKickoffProposal(proposal);
  if (!rendered.ok) return rendered;
  const { seq, receipt_hash: storedReceiptHash, ...body } = receipt;
  const receiptBytes = canonicalKickoffBytes(body);
  if (!receiptBytes.ok) return receiptBytes;
  const receiptHash = sha256Hex(receiptBytes.bytes);
  return Object.freeze({
    ok: true,
    version: proposal.version,
    proposal_id: proposal.proposal_id,
    proposal_hash: proposal.proposal_hash,
    record_bytes: record.bytes,
    record_hash: sha256Hex(record.bytes),
    rendered_prose: rendered.prose,
    rendered_prose_hash: rendered.prose_hash,
    receipt_seq: seq,
    receipt_bytes: receiptBytes.bytes,
    receipt_hash: receiptHash,
    receipt_hash_matches: receiptHash === storedReceiptHash,
    envelope: receipt.envelope,
    who: receipt.who,
    confirmed_at: receipt.at,
    open_draft: lineage.open
      ? Object.freeze({
        version: lineage.open.version,
        proposal_hash: lineage.open.proposal_hash,
        goal: lineage.open.goal,
      })
      : null,
  });
}

function confirmedResult(lineage, proposal, receipt, extra) {
  return {
    ok: true,
    phase: 'confirmed',
    state: lineage.state,
    authoritative: true,
    applied: true,
    status_code: KICKOFF_CODE.CONFIRMED,
    user_text: KICKOFF_TEXT[KICKOFF_CODE.CONFIRMED],
    idempotent: extra.idempotent,
    already_confirmed: extra.idempotent,
    receipt_written: !extra.idempotent,
    proposal,
    proposal_id: proposal.proposal_id,
    proposal_hash: proposal.proposal_hash,
    rendered_prose: proposal.rendered_prose,
    rendered_prose_hash: proposal.rendered_prose_hash,
    version: proposal.version,
    receipt,
    receipt_hash: receipt.receipt_hash,
    receipt_count: lineage.receipt_count,
    envelope: receipt.envelope,
    envelope_materialized_in: KICKOFF_EVENT_KIND.CONFIRM,
    envelope_written: false,
    face_written: false,
    outputs: deriveConfirmedKickoff(lineage),
    events_path: extra.events_path,
    project_path: extra.project_path,
  };
}

/**
 * Confirm the OPEN proposal by BOTH hashes John saw. Exactly one matching confirmation
 * appends exactly one receipt; a repeated matching confirmation finds it and appends
 * nothing; a stale or unknown hash refuses with a named row and writes nothing.
 *
 * @param {string} projectPath
 * @param {{who: string|object, proposal_hash: string, rendered_prose_hash: string,
 *   client_event_id?: string, at?: string, timeoutMs?: number}} opts
 */
export function confirmKickoffProposal(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const eventsPath = kickoffEventsPath(root);
  const who = normalizeClaimedWho(opts.who);
  if (!who) return kickoffFailure(KICKOFF_CODE.WHO_REQUIRED, { error: 'who_required' });
  const proposalHash = cleanText(opts.proposal_hash ?? opts.proposal?.proposal_hash);
  const proseHash = cleanText(opts.rendered_prose_hash ?? opts.proposal?.rendered_prose_hash);
  if (!HEX64.test(proposalHash)) {
    return kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, { error: 'proposal_hash_missing_or_invalid' });
  }
  if (!HEX64.test(proseHash)) {
    return kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, { error: 'rendered_prose_hash_missing_or_invalid' });
  }

  return withEventsLock(eventsPath, opts, () => {
    const read = readEvents(eventsPath, { ...opts, write: true });
    if (!read.ok) return read;
    const lineage = projectKickoffLineage(read.events);
    if (!lineage.ok) return lineage;
    const extra = { events_path: eventsPath, project_path: root };

    const already = lineage.receipts.find((entry) => entry.proposal_hash === proposalHash);
    if (already) {
      if (already.rendered_prose_hash !== proseHash) {
        return kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, {
          error: 'confirm_prose_hash_mismatch',
          expected_hash: already.rendered_prose_hash,
          provided_hash: proseHash,
        });
      }
      const proposal = lineage.proposals.find((entry) => entry.proposal_hash === proposalHash);
      return confirmedResult(lineage, proposal, already, { ...extra, idempotent: true });
    }

    const open = lineage.open;
    if (!open || open.proposal_hash !== proposalHash) {
      const known = lineage.proposals.some((entry) => entry.proposal_hash === proposalHash);
      const current = {
        current_open_hash: open?.proposal_hash ?? null,
        current_confirmed_hash: lineage.confirmed?.proposal_hash ?? null,
        provided_hash: proposalHash,
      };
      return known
        ? kickoffFailure(KICKOFF_CODE.STALE, { error: 'proposal_superseded', ...current })
        : kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, { error: 'proposal_hash_unknown', ...current });
    }
    // Bind BOTH hashes to the bytes that were reviewed: the stored record re-hashes to the
    // record hash, and the stored prose is the renderer's prose and re-hashes to the prose hash.
    if (recomputeKickoffHash(open) !== proposalHash) {
      return kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, {
        error: 'record_hash_mismatch',
        expected_hash: recomputeKickoffHash(open),
        provided_hash: proposalHash,
      });
    }
    const rendered = renderKickoffProposal(open);
    if (!rendered.ok) return rendered;
    if (rendered.prose_hash !== proseHash || open.rendered_prose_hash !== proseHash
        || sha256Hex(Buffer.from(open.rendered_prose, 'utf8')) !== proseHash) {
      return kickoffFailure(KICKOFF_CODE.HASH_MISMATCH, {
        error: 'prose_hash_mismatch',
        expected_hash: rendered.prose_hash,
        provided_hash: proseHash,
      });
    }

    const at = cleanText(opts.at) || new Date().toISOString();
    const body = {
      schema: KICKOFF_RECEIPT_SCHEMA,
      kind: KICKOFF_EVENT_KIND.CONFIRM,
      version: open.version,
      proposal_id: open.proposal_id,
      proposal_hash: proposalHash,
      rendered_prose_hash: proseHash,
      prior_confirmed_hash: lineage.prior_confirmed_hash,
      who: who.claimed,
      who_provenance: WHO_PROVENANCE,
      client_event_id: cleanText(opts.client_event_id) || `kickoff-confirm-${proposalHash.slice(0, 16)}`,
      at,
      envelope: materializeEnvelope(),
    };
    const bodyBytes = canonicalKickoffBytes(body);
    if (!bodyBytes.ok) return bodyBytes;
    const event = { seq: read.head_seq + 1, ...body, receipt_hash: sha256Hex(bodyBytes.bytes) };
    const appended = appendEventLine(eventsPath, event, read.size);
    if (!appended.ok) return appended;

    const after = projectKickoffLineage([...read.events, event]);
    if (!after.ok) return after;
    return confirmedResult(after, after.confirmed, after.receipt, { ...extra, idempotent: false });
  });
}

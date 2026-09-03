/**
 * Gate 5 / Wave 9 - Phase 4.3: OPEN-state read-model persistence - the last
 * integration piece between Ecgberht's store and Anchor's pass-through canary.
 *
 * WHY THIS EXISTS. The Wave 4 writer materializes projection.json ONLY from a
 * confirmed receipt (nothing unconfirmed may materialize a Face), so an effort
 * whose kickoff is still OPEN has no read-model file at all - and the Anchor
 * reader, pass-through by law (it never opens the store), can only answer
 * UNKNOWN about it. That is restart amnesia at the cockpit: the open proposal
 * IS persisted (events.jsonl), but the one file Anchor reads says nothing.
 * The Wave 7 reader already speaks the `state: "open"` document this module
 * writes; Waves 7 and 8 proved that branch on handcrafted bytes and deferred
 * the real writer to this wave's integrated canary.
 *
 * WHAT IT WRITES, AND WHAT IT NEVER WRITES. For an OPEN-only lineage this seam
 * persists projection.json as `{schema, state: 'open', open_draft: {version,
 * proposal_hash, goal (first line), applied: false}}` - a read-model summary,
 * never a second truth (the store stays authoritative; the doc carries no
 * prose, no envelope, no receipt). It NEVER writes face.md: the Face is
 * created on confirmation and is absent while a proposal is open - that law
 * (KICKOFF_FACE_SEMANTICS) is Wave 4's and this module keeps it. For a
 * confirmed lineage it DELEGATES to the Wave 4 writer unchanged, so there is
 * exactly one confirmed-projection code path in the engine.
 *
 * Durability: the same atomic write (temp + fsync + rename via
 * writeFileAtomicSync) under the same cross-process lock every kickoff write
 * takes (withFileLock on the events path). Byte-identical on every run for one
 * lineage (the repeat-invocation law). Bounded by the store's own read bound
 * (KICKOFF_EVENTS_MAX_BYTES) with the named refusal riding through. Failure
 * states carry a status code AND user-visible text with `unknown` and `empty`
 * as SEPARATE rows. Stdlib only; no child_process (the engine law). Source is
 * ASCII on purpose (the repo's mojibake sweep).
 */

import fs from 'node:fs';
import path from 'node:path';

import { LOCK_TIMEOUT_MS, withFileLock, writeFileAtomicSync } from './durable-write.mjs';
import { guardKickoffWriteTarget } from './kickoff-display.mjs';
import {
  KICKOFF_STATE,
  kickoffEventsPath,
  readKickoffLineage,
} from './kickoff-lifecycle.mjs';
import {
  KICKOFF_CODE,
  KICKOFF_TEXT,
  canonicalKickoffBytes,
  kickoffFailure,
  sha256Hex,
} from './kickoff-record.mjs';
import {
  KICKOFF_PROJECTION_CODE,
  KICKOFF_PROJECTION_SCHEMA,
  kickoffProjectionPath,
  writeKickoffProjection,
} from './kickoff-projection.mjs';

/** The state field of the document this seam writes; Anchor's reader keys off it. */
export const KICKOFF_OPEN_PROJECTION_STATE = 'open';

/** Named durability helpers (removal-proof, the S4/S5 pattern). */
export const KICKOFF_OPEN_PROJECTION_ATOMIC_WRITE = 'writeFileAtomicSync';
export const KICKOFF_OPEN_PROJECTION_LOCK_HELPER = 'withFileLock';

/** How this seam answers each lineage state - one delegation, one write, two refusals. */
export const KICKOFF_READ_MODEL_ANSWER = Object.freeze({
  confirmed: 'delegate_to_wave4_writer',
  open: 'write_open_state_projection',
  empty: 'refuse_write_nothing',
  unknown: 'refuse_write_nothing',
});

/** One-line goal, exactly as the Wave 4 open_draft summary trims it. */
function firstLine(text) {
  return String(text ?? '').split('\n', 1)[0];
}

/**
 * Pure derivation of the OPEN-state read-model document from an OPEN lineage.
 * Everything in it comes from the latest OPEN proposal on the store; nothing is
 * generated. A lineage in any other state is answered by its own named row.
 *
 * @param {object} lineage a readKickoffLineage() result
 * @returns {{ok: true, state: 'open', projection: object, projection_text: string,
 *   projection_hash: string, open_draft: object} | object}
 */
export function deriveKickoffOpenProjection(lineage) {
  if (!lineage || lineage.ok !== true) {
    return lineage ?? kickoffFailure(KICKOFF_CODE.STATE_UNKNOWN, { error: 'lineage_missing' });
  }
  if (lineage.state !== KICKOFF_STATE.OPEN || !lineage.open) {
    return kickoffFailure(KICKOFF_CODE.STATE_UNKNOWN, {
      error: 'lineage_not_open',
      state: lineage.state ?? KICKOFF_STATE.UNKNOWN,
    });
  }
  const openDraft = {
    version: lineage.open.version,
    proposal_hash: lineage.open.proposal_hash,
    goal: firstLine(lineage.open.goal),
    applied: false,
  };
  const projection = {
    schema: KICKOFF_PROJECTION_SCHEMA,
    state: KICKOFF_OPEN_PROJECTION_STATE,
    open_draft: openDraft,
  };
  const canonical = canonicalKickoffBytes(projection);
  if (!canonical.ok) return canonical;
  const projectionText = `${canonical.text}\n`;
  return Object.freeze({
    ok: true,
    state: KICKOFF_OPEN_PROJECTION_STATE,
    code: KICKOFF_PROJECTION_CODE.OPEN,
    status_code: KICKOFF_PROJECTION_CODE.OPEN,
    user_text: KICKOFF_TEXT[KICKOFF_PROJECTION_CODE.OPEN],
    authoritative: false,
    projection,
    projection_text: projectionText,
    projection_hash: sha256Hex(Buffer.from(projectionText, 'utf8')),
    open_draft: Object.freeze(openDraft),
  });
}

/**
 * Persist the kickoff read-model for WHATEVER state the store is in - the one
 * seam a canary or a staging pass calls without first asking which writer.
 *
 *   confirmed  -> delegate to writeKickoffProjection (Wave 4, unchanged: the
 *                 confirmed doc + the Face, byte-identical on repeat);
 *   open       -> write the open-state projection.json atomically under the
 *                 store lock; NEVER a Face; byte-identical on repeat;
 *   empty      -> refuse with the named empty row and write NOTHING (no file,
 *                 no directory) - a separate row from unknown, always;
 *   unreadable / corrupt / over-bound / lock-contended -> the store's own
 *                 named rows ride through; nothing is written.
 *
 * @param {string} projectPath
 * @param {{max_bytes?: number, timeoutMs?: number}} [opts]
 */
export function persistKickoffReadModel(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const eventsPath = kickoffEventsPath(root);
  // No store, nothing to persist - answered WITHOUT taking the lock, because
  // acquiring it would create the kickoff directory (the Wave 4 discipline).
  if (!fs.existsSync(eventsPath)) {
    return kickoffFailure(KICKOFF_PROJECTION_CODE.EMPTY, {
      error: 'nothing_to_persist',
      state: KICKOFF_STATE.EMPTY,
      projection_written: false,
      face_written: false,
    });
  }

  let outcome;
  try {
    outcome = withFileLock(eventsPath, () => {
      const lineage = readKickoffLineage(root, opts);
      if (!lineage.ok) return { ...lineage, projection_written: false, face_written: false };
      if (lineage.confirmed && lineage.receipt) return { delegate: true };
      const derived = deriveKickoffOpenProjection(lineage);
      if (!derived.ok) return { ...derived, projection_written: false, face_written: false };

      const projectionPath = kickoffProjectionPath(root);
      const guard = guardKickoffWriteTarget(projectionPath);
      if (!guard.ok) return { ...guard, projection_written: false, face_written: false };
      try {
        writeFileAtomicSync(projectionPath, derived.projection_text);
      } catch (error) {
        return kickoffFailure(KICKOFF_CODE.WRITE_FAILED, {
          error: error?.code ?? 'kickoff_open_projection_write_failed',
          detail: String(error?.message ?? error),
          projection_written: false,
          face_written: false,
        });
      }
      return {
        ...derived,
        project_path: root,
        events_path: eventsPath,
        projection_path: projectionPath,
        projection_written: true,
        // The Face law, kept out loud: an open proposal never materializes one.
        face_written: false,
        face_materialized: false,
      };
    }, { timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS });
  } catch (error) {
    if (error?.code === 'ELOCKTIMEOUT') {
      return kickoffFailure(KICKOFF_CODE.STATE_UNKNOWN, {
        error: 'kickoff_lock_contended',
        detail: String(error?.message ?? error),
        projection_written: false,
        face_written: false,
      });
    }
    return kickoffFailure(KICKOFF_CODE.WRITE_FAILED, {
      error: 'kickoff_read_model_store_failed',
      detail: String(error?.message ?? error),
      projection_written: false,
      face_written: false,
    });
  }

  // Confirmed lineage: exactly one confirmed-projection code path in the engine.
  // Delegation happens OUTSIDE the lock above - the Wave 4 writer takes it itself.
  if (outcome && outcome.delegate === true) {
    return writeKickoffProjection(root, opts);
  }
  return outcome;
}

/**
 * Machine-readable failure-state table for this surface. `unknown` and `empty`
 * are SEPARATE rows; the store's own rows are quoted by their owning codes so
 * one vocabulary spans the seam.
 *
 * @returns {ReadonlyArray<{state: string, surface: string, status_code: string, user_text: string}>}
 */
export function kickoffOpenProjectionFailureTable() {
  const row = (state, code, text) => Object.freeze({
    state,
    surface: 'kickoff_read_model_persist',
    status_code: code,
    user_text: text ?? KICKOFF_TEXT[code],
  });
  return Object.freeze([
    row('confirmed-delegated', KICKOFF_PROJECTION_CODE.CONFIRMED),
    row('open-written', KICKOFF_PROJECTION_CODE.OPEN),
    row('empty-but-valid', KICKOFF_PROJECTION_CODE.EMPTY),
    row('unknown', KICKOFF_CODE.STATE_UNKNOWN),
    row('dependency-slow-or-killed', KICKOFF_CODE.STATE_UNKNOWN,
      `${KICKOFF_TEXT[KICKOFF_CODE.STATE_UNKNOWN]} (lock contended: another writer holds the store)`),
    row('backing-store-unreadable', KICKOFF_CODE.EVENTS_UNREADABLE),
    row('dependency-returns-garbage', KICKOFF_CODE.CORRUPT),
    row('bound-exceeded', KICKOFF_CODE.EVENTS_BOUND_EXCEEDED),
    row('write-failed', KICKOFF_CODE.WRITE_FAILED),
  ]);
}

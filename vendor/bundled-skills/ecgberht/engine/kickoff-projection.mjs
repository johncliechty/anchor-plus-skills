/**
 * Gate 5 / Wave 4 - Phase 2.1: the CONFIRMED-LINEAGE projection writer and the Face.
 *
 * Two derived files live beside the one store (<folder>/.ecgberht/kickoff/events.jsonl):
 *
 *   projection.json - the read-model of record: the intent/work-product projection and
 *                     the execution projection (v0: coarse plan entries + the first-slice
 *                     marker + the confirmed version and hash), BOTH linked to the same
 *                     confirmed receipt by its seq and hash, plus an `open_draft` summary
 *                     (version + hash + one-line goal, applied: false) when a higher OPEN
 *                     version exists. Canonical sorted-key UTF-8/no-float bytes, so one
 *                     lineage produces one byte sequence, every time.
 *   face.md         - the Face FILE.
 *
 * THE FACE SEMANTICS, stated once (KICKOFF_FACE_SEMANTICS is this paragraph as data):
 * the Face FILE is written at confirmation and is a pure re-derivation of the receipt -
 * a cache, never a source of truth. A repeated matching confirmation rewrites it
 * byte-identically. It is absent while a proposal is open, rejected, or stale: nothing
 * unconfirmed ever materializes a Face. And an OPEN v(n+1) never displaces the last
 * confirmed Face - the Face derives ONLY from the confirmed receipt, so re-running the
 * writer while a draft is open rewrites the confirmed Face byte-for-byte and reports the
 * draft in projection.json alone, as draft-not-applied.
 *
 * RECEIPT-ONLY TRUTH. Everything authoritative in both files comes through ONE pure
 * function over the lineage (deriveConfirmedKickoff + deriveKickoffProjection here):
 * record bytes, rendered prose, receipt hash, envelope terms. No display surface
 * (roadmap.json, the campaign Face, strip.json, the chamber) is ever read, so deleting
 * display data cannot change a projection - a rebuild re-derives the same bytes from the
 * receipt lineage.
 *
 * Durability: atomic replacement (temp + fsync + rename via writeFileAtomicSync) under
 * the SAME cross-process lock every kickoff write takes (withFileLock on the events
 * path), so a reader never observes a torn cache and writers serialize. Failure states
 * carry a status code AND user-visible text with confirmed / open / absent / unknown /
 * empty as SEPARATE rows (kickoffProjectionFailureTable). Stdlib only. Source is ASCII
 * on purpose (the repo's mojibake sweep).
 */

import fs from 'node:fs';
import path from 'node:path';

import { LOCK_TIMEOUT_MS, withFileLock, writeFileAtomicSync } from './durable-write.mjs';
import { guardKickoffWriteTarget } from './kickoff-display.mjs';
import {
  KICKOFF_DIR_REL,
  KICKOFF_STATE,
  deriveConfirmedKickoff,
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

export const KICKOFF_PROJECTION_SCHEMA = 'ecgberht-kickoff-projection-v0';
export const KICKOFF_PROJECTION_FILE = 'projection.json';
export const KICKOFF_FACE_FILE = 'face.md';
export const KICKOFF_PROJECTION_REL = path.join(KICKOFF_DIR_REL, KICKOFF_PROJECTION_FILE);
export const KICKOFF_FACE_REL = path.join(KICKOFF_DIR_REL, KICKOFF_FACE_FILE);

/** Named durability helpers (removal-proof, the S4/S5 pattern). */
export const KICKOFF_PROJECTION_ATOMIC_WRITE = 'writeFileAtomicSync';
export const KICKOFF_PROJECTION_LOCK_HELPER = 'withFileLock';

/**
 * THE FACE SEMANTICS as data - the header's paragraph is the only prose statement and
 * this constant is its machine form; conversation and tests reference it, never restate it.
 */
export const KICKOFF_FACE_SEMANTICS = Object.freeze({
  written_on: 'kickoff_confirm',
  derived_from: 'kickoff_confirm_receipt',
  cache: true,
  source_of_truth: false,
  double_confirm: 'byte_identical_rewrite',
  absent_while: Object.freeze(['open', 'rejected', 'stale']),
  open_replacement: 'never_displaces_last_confirmed_face',
});

export const KICKOFF_PROJECTION_CODE = Object.freeze({
  CONFIRMED: KICKOFF_CODE.CONFIRMED,
  OPEN: KICKOFF_CODE.OPEN_UNCONFIRMED,
  ABSENT: 'KICKOFF_PROJECTION_ABSENT',
  EMPTY: KICKOFF_CODE.NONE_YET,
  UNKNOWN: KICKOFF_CODE.STATE_UNKNOWN,
  FILE_UNREADABLE: 'KICKOFF_PROJECTION_UNREADABLE',
  FILE_GARBAGE: 'KICKOFF_PROJECTION_GARBAGE',
});

/** User-visible text for the codes THIS surface adds; shared codes keep KICKOFF_TEXT. */
export const KICKOFF_PROJECTION_TEXT = Object.freeze({
  [KICKOFF_PROJECTION_CODE.ABSENT]:
    'A kickoff is confirmed on the receipt lineage but its projection cache is absent - re-derivable; run the projection writer.',
  [KICKOFF_PROJECTION_CODE.FILE_UNREADABLE]:
    'The kickoff projection cache is unreadable (<error>) - the receipt lineage stays authoritative; refused rather than guessed.',
  [KICKOFF_PROJECTION_CODE.FILE_GARBAGE]:
    'The kickoff projection cache does not parse as a projection (<error>) - the receipt lineage stays authoritative; rebuild it.',
});

/** @param {string} code @param {object} [extra] a failure row in this surface's voice */
export function kickoffProjectionFailure(code, extra = {}) {
  if (!Object.hasOwn(KICKOFF_PROJECTION_TEXT, code)) return kickoffFailure(code, extra);
  const error = extra.error ?? String(code).toLowerCase();
  const text = KICKOFF_PROJECTION_TEXT[code].replace(/<error>/g, String(error));
  return {
    ok: false,
    code,
    status_code: code,
    error,
    text,
    user_text: text,
    authoritative: false,
    ...extra,
  };
}

/**
 * Machine-readable failure-state table for the projection/Face surface. The wave's five
 * named states - confirmed, open, absent, unknown, empty - are SEPARATE rows with five
 * distinct codes; the store's own rows ride through unchanged.
 *
 * @returns {ReadonlyArray<{state: string, surface: string, status_code: string, user_text: string}>}
 */
export function kickoffProjectionFailureTable() {
  const textOf = (code) => KICKOFF_PROJECTION_TEXT[code] ?? KICKOFF_TEXT[code];
  const row = (state, code) => Object.freeze({
    state,
    surface: 'projection/face',
    status_code: code,
    user_text: textOf(code),
  });
  return Object.freeze([
    row('confirmed', KICKOFF_PROJECTION_CODE.CONFIRMED),
    row('open', KICKOFF_PROJECTION_CODE.OPEN),
    row('absent', KICKOFF_PROJECTION_CODE.ABSENT),
    row('empty-but-valid', KICKOFF_PROJECTION_CODE.EMPTY),
    row('unknown', KICKOFF_PROJECTION_CODE.UNKNOWN),
    row('backing-store-unreadable', KICKOFF_CODE.EVENTS_UNREADABLE),
    row('backing-store-corrupt', KICKOFF_CODE.CORRUPT),
    row('projection-file-unreadable', KICKOFF_PROJECTION_CODE.FILE_UNREADABLE),
    row('dependency-returns-garbage / projection-file-garbage', KICKOFF_PROJECTION_CODE.FILE_GARBAGE),
    row('write-failed', KICKOFF_CODE.WRITE_FAILED),
  ]);
}

/** @param {string} projectPath @returns {string} absolute path of projection.json */
export function kickoffProjectionPath(projectPath) {
  return path.join(path.resolve(projectPath), KICKOFF_PROJECTION_REL);
}

/** @param {string} projectPath @returns {string} absolute path of face.md */
export function kickoffFacePath(projectPath) {
  return path.join(path.resolve(projectPath), KICKOFF_FACE_REL);
}

// -- pure derivation ---------------------------------------------------------------

const firstLine = (value) => String(value ?? '').split('\n', 1)[0].trim();

function deepFreeze(value) {
  if (value && typeof value === 'object' && !ArrayBuffer.isView(value) && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
}

/** The open draft as projection.json carries it: a summary, marked draft-not-applied. */
function openDraftSummary(open) {
  if (!open) return null;
  return {
    version: open.version,
    proposal_hash: open.proposal_hash,
    goal: firstLine(open.goal),
    applied: false,
  };
}

/** The Face text: every line a fact of the receipt, so re-derivation is byte-stable. */
function faceTextOf(derived) {
  return [
    `# Kickoff Face - confirmed v${derived.version}`,
    '',
    derived.rendered_prose.replace(/\n+$/, ''),
    '',
    `Confirmed by ${derived.who} at ${derived.confirmed_at}.`,
    `Record sha256 ${derived.proposal_hash}.`,
    `Receipt sha256 ${derived.receipt_hash}.`,
    '',
    'This Face is a cache re-derived from the confirmation receipt; the receipt lineage',
    'is the source of truth. A repeated confirmation rewrites this file byte-identically.',
    '',
  ].join('\n');
}

/**
 * Derive BOTH files' contents from a lineage - pure: no clock, no disk, no display
 * surface. The intent projection and the execution projection carry the SAME receipt
 * link (version, proposal hash, receipt seq + hash); the Face derives from the confirmed
 * receipt alone, so an OPEN draft changes projection.json's `open_draft` and nothing else.
 *
 * @param {object} lineage a readKickoffLineage / projectKickoffLineage result
 * @returns {{ok: true, projection: object, projection_text: string, projection_hash: string,
 *   face_text: string, face_hash: string, version: number, proposal_hash: string,
 *   receipt_seq: number, receipt_hash: string, open_draft: object|null} | object}
 */
export function deriveKickoffProjection(lineage) {
  if (!lineage || lineage.ok !== true) {
    return lineage ?? kickoffFailure(KICKOFF_CODE.STATE_UNKNOWN, { error: 'lineage_missing' });
  }
  if (!lineage.confirmed || !lineage.receipt) {
    if (lineage.state === KICKOFF_STATE.OPEN) {
      return kickoffFailure(KICKOFF_PROJECTION_CODE.OPEN, {
        error: 'open_draft_not_applied',
        state: KICKOFF_STATE.OPEN,
        face_materialized: false,
        open_draft: openDraftSummary(lineage.open),
      });
    }
    return kickoffFailure(KICKOFF_PROJECTION_CODE.EMPTY, {
      error: 'nothing_confirmed_to_project',
      state: lineage.state ?? KICKOFF_STATE.EMPTY,
      face_materialized: false,
    });
  }

  const derived = deriveConfirmedKickoff(lineage);
  if (!derived.ok) return derived;
  if (derived.receipt_hash_matches !== true) {
    return kickoffFailure(KICKOFF_CODE.CORRUPT, {
      error: 'kickoff_receipt_hash_corrupt',
      at_seq: derived.receipt_seq,
    });
  }

  const record = lineage.confirmed;
  const link = {
    version: derived.version,
    proposal_hash: derived.proposal_hash,
    receipt_seq: derived.receipt_seq,
    receipt_hash: derived.receipt_hash,
  };
  const faceText = faceTextOf(derived);
  const faceHash = sha256Hex(Buffer.from(faceText, 'utf8'));

  const projection = {
    schema: KICKOFF_PROJECTION_SCHEMA,
    state: 'confirmed',
    confirmed: {
      ...link,
      proposal_id: derived.proposal_id,
      record_hash: derived.record_hash,
      rendered_prose: derived.rendered_prose,
      rendered_prose_hash: derived.rendered_prose_hash,
      prior_confirmed_hash: record.prior_confirmed_hash ?? null,
      who: derived.who,
      confirmed_at: derived.confirmed_at,
      envelope_terms_hash: derived.envelope?.terms_hash ?? null,
    },
    intent: {
      kind: 'intent_work_product',
      ...link,
      goal: record.goal,
      success_signals: [...(record.success_signals ?? [])],
      work_product: {
        id: record.work_product.id,
        name: record.work_product.name,
        components: (record.work_product.components ?? []).map((component) => ({
          id: component.id,
          name: component.name,
          done_when: component.done_when ?? null,
        })),
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
          proof: {
            observable: record.integration.proof?.observable,
            method: record.integration.proof?.method,
          },
        },
    },
    execution: {
      kind: 'execution',
      ...link,
      plan_entries: (record.plan_entries ?? []).map((entry) => ({
        id: entry.id,
        name: entry.name,
        component_ids: [...(entry.component_ids ?? [])],
        end_to_end_slice: entry.end_to_end_slice === true,
        first_slice: entry.id === record.first_slice_id,
        done_when: entry.done_when ?? null,
      })),
      first_slice_id: record.first_slice_id,
    },
    open_draft: openDraftSummary(lineage.open),
    face: {
      file: KICKOFF_FACE_FILE,
      face_hash: faceHash,
      written_on: KICKOFF_FACE_SEMANTICS.written_on,
      cache: true,
      source_of_truth: false,
    },
  };

  const canonical = canonicalKickoffBytes(projection);
  if (!canonical.ok) return canonical;
  const projectionText = `${canonical.text}\n`;
  return deepFreeze({
    ok: true,
    state: 'confirmed',
    code: KICKOFF_PROJECTION_CODE.CONFIRMED,
    status_code: KICKOFF_PROJECTION_CODE.CONFIRMED,
    user_text: KICKOFF_TEXT[KICKOFF_PROJECTION_CODE.CONFIRMED],
    authoritative: true,
    ...link,
    projection,
    projection_text: projectionText,
    projection_hash: sha256Hex(Buffer.from(projectionText, 'utf8')),
    face_text: faceText,
    face_hash: faceHash,
    open_draft: projection.open_draft,
  });
}

// -- the writer --------------------------------------------------------------------

/**
 * Rebuild projection.json and face.md from the store's confirmed lineage - the ONLY
 * writer of either file. Runs at confirmation and on demand; a lineage with nothing
 * confirmed refuses with its named row and creates NOTHING (no directory, no file), so
 * an open, rejected, or stale proposal never materializes a Face. Atomic (temp + fsync
 * + rename) under the store's own cross-process lock; byte-identical on every run for
 * one lineage, which is what makes a repeated confirmation harmless downstream.
 *
 * @param {string} projectPath
 * @param {{max_bytes?: number, timeoutMs?: number}} [opts]
 */
export function writeKickoffProjection(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const eventsPath = kickoffEventsPath(root);
  // No store, nothing to project - answered WITHOUT taking the lock, because acquiring
  // it would create the kickoff directory: a refusing row writes nothing, not even a dir.
  if (!fs.existsSync(eventsPath)) {
    return kickoffFailure(KICKOFF_PROJECTION_CODE.EMPTY, {
      error: 'nothing_confirmed_to_project',
      state: KICKOFF_STATE.EMPTY,
      face_materialized: false,
      projection_written: false,
      face_written: false,
    });
  }
  try {
    return withFileLock(eventsPath, () => {
      const lineage = readKickoffLineage(root, opts);
      if (!lineage.ok) return { ...lineage, projection_written: false, face_written: false };
      const derived = deriveKickoffProjection(lineage);
      if (!derived.ok) return { ...derived, projection_written: false, face_written: false };

      const projectionPath = kickoffProjectionPath(root);
      const facePath = kickoffFacePath(root);
      // Wave 5 anatomy guard: every kickoff write target passes the named refusal seam,
      // so a kickoff path aimed at anatomy.json refuses by name and writes nothing.
      for (const target of [projectionPath, facePath]) {
        const guard = guardKickoffWriteTarget(target);
        if (!guard.ok) return { ...guard, projection_written: false, face_written: false };
      }
      try {
        writeFileAtomicSync(projectionPath, derived.projection_text);
        writeFileAtomicSync(facePath, derived.face_text);
      } catch (error) {
        return kickoffFailure(KICKOFF_CODE.WRITE_FAILED, {
          error: error?.code ?? 'kickoff_projection_write_failed',
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
        face_path: facePath,
        projection_written: true,
        face_written: true,
        face_materialized: true,
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
      error: 'kickoff_projection_store_failed',
      detail: String(error?.message ?? error),
      projection_written: false,
      face_written: false,
    });
  }
}

// -- the readers (pass-through; a read writes nothing) ------------------------------

function readCacheFile(filePath) {
  try {
    return { ok: true, raw: fs.readFileSync(filePath, 'utf8') };
  } catch (error) {
    return {
      ok: false,
      errno: error?.code ?? 'read_failed',
      enoent: error?.code === 'ENOENT',
      detail: String(error?.message ?? error),
    };
  }
}

/**
 * The honest row for a missing cache file: consult the lineage so `absent` (confirmed
 * but cache gone - rebuildable), `open` (draft not applied - nothing materialized) and
 * `empty` (no kickoff at all) stay SEPARATE answers, never one guessed one.
 */
function missingCacheRow(root, opts, file) {
  const lineage = readKickoffLineage(root, opts);
  if (!lineage.ok) return lineage;
  if (lineage.confirmed) {
    return kickoffProjectionFailure(KICKOFF_PROJECTION_CODE.ABSENT, {
      error: `kickoff_${file}_cache_absent`,
      state: 'absent',
      rebuildable: true,
      confirmed_version: lineage.confirmed.version,
      confirmed_hash: lineage.confirmed.proposal_hash,
      face_materialized: false,
    });
  }
  if (lineage.state === KICKOFF_STATE.OPEN) {
    return kickoffFailure(KICKOFF_PROJECTION_CODE.OPEN, {
      error: 'open_draft_not_applied',
      state: KICKOFF_STATE.OPEN,
      face_materialized: false,
      open_draft: openDraftSummary(lineage.open),
    });
  }
  return kickoffFailure(KICKOFF_PROJECTION_CODE.EMPTY, {
    error: 'no_kickoff_yet',
    state: KICKOFF_STATE.EMPTY,
    face_materialized: false,
  });
}

/**
 * Read projection.json as the pass-through read-model it is. Never derives from events
 * and never writes; a missing, unreadable, or garbage cache answers with its own row
 * while the receipt lineage stays authoritative.
 *
 * @param {string} projectPath @param {{max_bytes?: number}} [opts]
 */
export function readKickoffProjection(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const projectionPath = kickoffProjectionPath(root);
  const read = readCacheFile(projectionPath);
  if (!read.ok) {
    if (read.enoent) return missingCacheRow(root, opts, 'projection');
    return kickoffProjectionFailure(KICKOFF_PROJECTION_CODE.FILE_UNREADABLE, {
      error: read.errno,
      detail: read.detail,
    });
  }
  let parsed;
  try {
    parsed = JSON.parse(read.raw);
  } catch {
    return kickoffProjectionFailure(KICKOFF_PROJECTION_CODE.FILE_GARBAGE, {
      error: 'projection_json_unparseable',
    });
  }
  // Wave 9: the OPEN-state read-model document (state 'open', an open_draft
  // summary, nothing authoritative) answers the honest OPEN row - the same row
  // a missing cache answers on an open lineage, and the same branch Anchor's
  // pass-through reader speaks. Anything shaped otherwise stays garbage.
  if (parsed?.schema === KICKOFF_PROJECTION_SCHEMA && parsed?.state === 'open') {
    const draft = parsed.open_draft;
    if (typeof draft !== 'object' || draft == null
        || draft.version == null || !draft.proposal_hash || draft.applied !== false) {
      return kickoffProjectionFailure(KICKOFF_PROJECTION_CODE.FILE_GARBAGE, {
        error: 'open_draft_shape_invalid',
      });
    }
    return kickoffFailure(KICKOFF_PROJECTION_CODE.OPEN, {
      error: 'open_draft_not_applied',
      state: KICKOFF_STATE.OPEN,
      face_materialized: false,
      open_draft: { ...draft },
      projection_path: projectionPath,
    });
  }
  if (parsed?.schema !== KICKOFF_PROJECTION_SCHEMA || parsed?.state !== 'confirmed'
      || typeof parsed?.confirmed !== 'object' || parsed.confirmed == null
      || typeof parsed?.intent !== 'object' || parsed.intent == null
      || typeof parsed?.execution !== 'object' || parsed.execution == null) {
    return kickoffProjectionFailure(KICKOFF_PROJECTION_CODE.FILE_GARBAGE, {
      error: 'projection_schema_unknown',
    });
  }
  return {
    ok: true,
    state: 'confirmed',
    code: KICKOFF_PROJECTION_CODE.CONFIRMED,
    status_code: KICKOFF_PROJECTION_CODE.CONFIRMED,
    user_text: KICKOFF_TEXT[KICKOFF_PROJECTION_CODE.CONFIRMED],
    authoritative: true,
    projection: parsed,
    projection_path: projectionPath,
    version: parsed.confirmed.version,
    proposal_hash: parsed.confirmed.proposal_hash,
    receipt_hash: parsed.confirmed.receipt_hash,
    open_draft: parsed.open_draft ?? null,
  };
}

/**
 * Read the Face FILE. While a proposal is open, rejected, or stale there is nothing to
 * read and nothing is materialized by reading - the answer is the state's own row.
 *
 * @param {string} projectPath @param {{max_bytes?: number}} [opts]
 */
export function readKickoffFace(projectPath, opts = {}) {
  const root = path.resolve(projectPath);
  const facePath = kickoffFacePath(root);
  const read = readCacheFile(facePath);
  if (!read.ok) {
    if (read.enoent) return missingCacheRow(root, opts, 'face');
    return kickoffProjectionFailure(KICKOFF_PROJECTION_CODE.FILE_UNREADABLE, {
      error: read.errno,
      detail: read.detail,
    });
  }
  return {
    ok: true,
    state: 'confirmed',
    code: KICKOFF_PROJECTION_CODE.CONFIRMED,
    status_code: KICKOFF_PROJECTION_CODE.CONFIRMED,
    user_text: KICKOFF_TEXT[KICKOFF_PROJECTION_CODE.CONFIRMED],
    face_materialized: true,
    face_text: read.raw,
    face_hash: sha256Hex(Buffer.from(read.raw, 'utf8')),
    face_path: facePath,
    cache: true,
    source_of_truth: false,
  };
}

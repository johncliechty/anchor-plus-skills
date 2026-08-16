/**
 * W14 - `steward verify`: tamper detection across the WHOLE object model.
 *
 * WHAT C5 ACTUALLY DEMANDS, AND WHY IT IS FOUR STORES RATHER THAN ONE. "Tamper is detected"
 * is easy to satisfy for whichever store somebody thought of first and false everywhere else.
 * The object model has four kinds of store, and each can be damaged out of band:
 *
 *   the SNAPSHOT   wholly derived, and therefore the one an operator is most likely to "fix"
 *                  by hand or restore from a backup, because it looks like a cache;
 *   the LOG        the ONE never-deletable store - an edited line here is a rewritten past;
 *   the MARKER     the in-root identity claim, the only git-free record of who a root is;
 *   the SoT FILES  the receipts, instruments and roadmap-event carriers themselves - the
 *                  actual source of truth, and literal peers of one another here (legs 7, 8).
 *
 * And each can be damaged in three DIFFERENT ways that call for three different reactions:
 * a HAND-EDIT (the content is something the system never wrote), a TRUNCATION (the content is
 * a prefix of what the system wrote), and a STALE RESTORE (the content is something the
 * system wrote EARLIER and has since replaced). Four stores times three modes is twelve
 * facts, and this verb names all twelve rather than collapsing them into "integrity failure",
 * because the operator's next action differs for every one: rebuild, recover, re-register,
 * or go and find out who overwrote the file.
 *
 * THE DISCRIMINATOR IS THE LINEAGE, NOT A CHECKSUM COLUMN. D-4 keeps every version of every
 * (project_id, class, path) in the log: a rewrite APPENDS a row pointing at the one it
 * superseded. That gives the three modes a mechanical test that needs no second store and no
 * guesswork:
 *
 *     bytes hash to the CURRENT row          -> intact
 *     bytes hash to an EARLIER row           -> STALE RESTORE (its own named status)
 *     bytes are short and do not close       -> TRUNCATION
 *     bytes hash to nothing in the lineage   -> HAND-EDIT
 *
 * The same shape answers the marker (the log records `marker_sha256` on registration and on
 * every reconcile, so the marker has a lineage too) and the snapshot (whose lineage position
 * is its `head_seq` plus the supersede chain the log carries after it).
 *
 * DETECTION STRENGTH, STATED RATHER THAN IMPLIED. The baseline is the log, and the log's
 * durable off-box baseline is the commit-intent lineage Anchor acknowledges. So detection is
 * exactly as strong as the LAST ACKNOWLEDGED COMMIT: content written after the newest
 * acknowledged intent is verified against a baseline that lives only on this disk, and this
 * verb says so on every run (`strength` in the receipt). That bound is a property of the
 * design, not a gap in this implementation - no amount of hashing makes a local-only baseline
 * an off-box one - and it is reported rather than papered over.
 *
 * WHAT VERIFY WRITES, AND THE ONE REGION IT MAY TOUCH. Verify updates the D-2 freshness block
 * and NOTHING else: `last_verified`, `presence` and `freshness` per project. `body` is left
 * byte-identical, because verify did not rebuild anything and a verb that quietly rewrote the
 * derived region would make W10's byte-equality claim depend on who ran last. That is also
 * why the mark PERSISTS: "verify marks drifted projects STALE in query output" is only true
 * if the next query, in another process, reads the mark - a return value nobody stored would
 * make the whole criterion a promise about one process's memory.
 *
 * THERE IS NO STRICT MODE. Re-verification is THIS verb, chained explicitly by the caller;
 * the query surface always reports the freshness it has and never re-checks behind the
 * operator's back. See QUERY_STRICT_MODE in engine/portfolio/query.mjs for the other half.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  INDEX_READ_CODE,
  ORDERING_FIELD,
  indexPathsFrom,
  logEventLine,
  replayEvents,
  seqIntegrity,
  withPortfolioLock,
} from '../append-log.mjs';
import { scanBytesForMojibake } from '../encoding.mjs';
import {
  SNAPSHOT_SCHEMA,
  serializeSnapshot,
  writeCanonicalSnapshot,
} from './canonical.mjs';
import { CAPS } from './caps.mjs';
import { hashBytes, validateCommitIntent } from './commit-intent.mjs';
import { contentHashFor, contentHashesFor, projectContentHash } from './content-hash.mjs';
import { DERIVABLE_CLASSES, derivedRowsInLog, isDerivedEvent, rowIdentity } from './derive.mjs';
import { SURFACE, rowOutcome, rowsForSurface } from './failure-tables.mjs';
import { CLASS, openablePath, toPosix } from './inventory.mjs';
import { MARKER_REFUSAL, markerPathFor, readMarker } from './marker.mjs';
import { containedPath, logHeadSha256, readRebuildInput } from './rebuild.mjs';
import { NATIVE_EVENT, materializeRegistry } from './registry.mjs';
import { foldTailIntoBody } from './rematerialize.mjs';
import { classifyRootStatus } from './root-status.mjs';
import { emptyFreshnessBlock, perProjectFreshness, validateSnapshotShape } from './snapshot-shape.mjs';
import { FRESHNESS, INTEGRITY, PRESENCE, assertStatusCode } from './status.mjs';

/** The verb's frozen version. Changing what the receipt carries means verify-v2. */
export const VERIFY_VERSION = 'verify-v1';

/** The receipt this verb hands its caller. */
export const VERIFY_RECEIPT_SCHEMA = 'verify-receipt-v1';

/** The verb's name, as an operator types it. */
export const VERIFY_VERB = 'verify';

/** The failure-table surface these rows belong to. */
export const VERIFY_SURFACE = SURFACE.VERIFY;

/**
 * The four stores the object model is made of. Closed: a fifth kind of store would be a
 * fifth way to be damaged silently, so adding one is an edit here rather than a new string
 * somewhere in a report.
 */
export const STORE = Object.freeze({
  SNAPSHOT: 'index-snapshot',
  LOG: 'index-log',
  MARKER: 'in-root-marker',
  SOURCE: 'source-of-truth-file',
});

/** @type {ReadonlyArray<string>} */
export const STORES = Object.freeze(Object.values(STORE));

/**
 * The three damage modes, named once. They are DISTINCT by contract: a stale restore that
 * rendered as a hand-edit would send the operator hunting for an intruder when what happened
 * was a backup tool doing its job at the wrong moment.
 */
export const DAMAGE = Object.freeze({
  HAND_EDIT: 'HAND_EDIT',
  TRUNCATION: 'TRUNCATION',
  STALE_RESTORE: 'STALE_RESTORE',
});

/** @type {ReadonlyArray<string>} */
export const DAMAGE_MODES = Object.freeze(Object.values(DAMAGE));

/**
 * Why a store was called damaged, in the verb's own words. These are DETAIL, carried in the
 * finding beside the frozen row's status and sentence - never a substitute for either.
 */
export const REASON = Object.freeze({
  NOT_CANONICAL: 'BYTES_ARE_NOT_THE_CANONICAL_RENDERING',
  SHAPE_REFUSED: 'SNAPSHOT_SHAPE_REFUSED',
  HEAD_HASH_MISMATCH: 'HEAD_HASH_DOES_NOT_MATCH_THE_LOG',
  SUPERSEDED_ROWS: 'BODY_DESCRIBES_SUPERSEDED_FILE_VERSIONS',
  SEQ_RUN_BROKEN: 'SEQUENCE_RUN_HAS_A_DUPLICATE_OR_A_GAP',
  ROW_MALFORMED: 'DERIVED_ROW_FIELDS_ARE_MALFORMED',
  INTENT_MALFORMED: 'COMMIT_INTENT_PAYLOAD_IS_MALFORMED',
  LINEAGE_BROKEN: 'SUPERSEDES_NAMES_A_SEQUENCE_NOT_IN_THE_LINEAGE',
  MARKER_UNKNOWN_HASH: 'MARKER_HASH_IS_IN_NO_RECORDED_LINEAGE',
  MARKER_REFUSED: 'MARKER_FAILED_ITS_OWN_VALIDATOR',
  CONTENT_HASH_DRIFT: 'PROJECT_CONTENT_HASH_DOES_NOT_MATCH_THE_INDEX',
  PATH_ESCAPE: 'RECORDED_PATH_RESOLVES_OUTSIDE_ITS_ROOT',
  UNREADABLE: 'BYTES_COULD_NOT_BE_READ',
});

// -- the rows -------------------------------------------------------------------

/** The class suffix a class-varying verify row carries. */
const CLASS_SUFFIX = Object.freeze({
  [CLASS.RECEIPT]: 'RECEIPT',
  [CLASS.INSTRUMENT]: 'INSTRUMENT',
  [CLASS.ROADMAP_EVENT]: 'ROADMAP_EVENT',
});

/** The class-varying verify row stems. */
export const VERIFY_CLASS_STEM = Object.freeze({
  TAMPERED: 'VERIFY_TAMPERED',
  TRUNCATED: 'VERIFY_TRUNCATED',
  STALE_RESTORE: 'VERIFY_STALE_RESTORE_SOURCE',
  SOURCE_ABSENT: 'VERIFY_SOURCE_ABSENT',
  EMPTY: 'VERIFY_EMPTY',
  UNKNOWN: 'VERIFY_UNKNOWN',
});

/** The verify rows that do not vary by class. */
export const VERIFY_CODE = Object.freeze({
  ROOT_UNREACHABLE: 'VERIFY_ROOT_UNREACHABLE',
  BOUND_EXCEEDED: 'VERIFY_BOUND_EXCEEDED',
  LOCK_TIMEOUT: 'VERIFY_LOCK_TIMEOUT',
  STALE_RESTORE: 'VERIFY_STALE_RESTORE',
  MARKER_TAMPERED: 'VERIFY_MARKER_TAMPERED',
  MARKER_TRUNCATED: 'VERIFY_MARKER_TRUNCATED',
  MARKER_STALE_RESTORE: 'VERIFY_MARKER_STALE_RESTORE',
  SNAPSHOT_TAMPERED: 'VERIFY_SNAPSHOT_TAMPERED',
  SNAPSHOT_TRUNCATED: 'VERIFY_SNAPSHOT_TRUNCATED',
  LOG_TORN: 'VERIFY_LOG_TORN',
  LOG_TAMPERED: 'VERIFY_LOG_TAMPERED',
  LOG_STALE_RESTORE: 'VERIFY_LOG_STALE_RESTORE',
  UNPARSEABLE: 'VERIFY_UNPARSEABLE',
  MOJIBAKE: 'VERIFY_MOJIBAKE',
  INDEX_UNREADABLE: 'VERIFY_INDEX_UNREADABLE',
  NOTHING_REGISTERED: 'VERIFY_NOTHING_REGISTERED',
  SKIPPED_REPARSE: 'VERIFY_SKIPPED_REPARSE',
  PATH_TOO_LONG: 'VERIFY_PATH_TOO_LONG',
  CASE_COLLISION: 'VERIFY_CASE_COLLISION',
});

/**
 * The success code. Not a failure-table row, for the same reason QUERY_OK is not one: the
 * tables describe failure STATES of a working surface, and "everything matched" is the
 * surface working.
 */
export const VERIFY_OK = 'VERIFY_OK';

/** @type {Readonly<Record<string, {status: string, text: string}>>} */
export const VERIFY_LOCAL_ROWS = Object.freeze({
  [VERIFY_OK]: Object.freeze({
    status: assertStatusCode(INTEGRITY.OK, 'verify OK'),
    text:
      'Verified {projects} project(s) and {files} file(s) against the index: {stores} store(s) '
      + 'intact, no drift. Detection is as strong as the last acknowledged commit '
      + '(intent seq {ack_seq}).',
  }),
});

/**
 * The frozen store x mode table, as data.
 *
 * This IS the done-when matrix: four stores, three damage modes, twelve named codes, and a
 * test can enumerate it rather than trusting that every cell was remembered. A cell whose
 * code is missing is a build failure in verifyMatrixIntegrity() below, not a discovery some
 * operator makes during an incident.
 */
export const DAMAGE_MATRIX = Object.freeze({
  [STORE.SNAPSHOT]: Object.freeze({
    [DAMAGE.HAND_EDIT]: VERIFY_CODE.SNAPSHOT_TAMPERED,
    [DAMAGE.TRUNCATION]: VERIFY_CODE.SNAPSHOT_TRUNCATED,
    [DAMAGE.STALE_RESTORE]: VERIFY_CODE.STALE_RESTORE,
  }),
  [STORE.LOG]: Object.freeze({
    [DAMAGE.HAND_EDIT]: VERIFY_CODE.LOG_TAMPERED,
    [DAMAGE.TRUNCATION]: VERIFY_CODE.LOG_TORN,
    [DAMAGE.STALE_RESTORE]: VERIFY_CODE.LOG_STALE_RESTORE,
  }),
  [STORE.MARKER]: Object.freeze({
    [DAMAGE.HAND_EDIT]: VERIFY_CODE.MARKER_TAMPERED,
    [DAMAGE.TRUNCATION]: VERIFY_CODE.MARKER_TRUNCATED,
    [DAMAGE.STALE_RESTORE]: VERIFY_CODE.MARKER_STALE_RESTORE,
  }),
  [STORE.SOURCE]: Object.freeze({
    [DAMAGE.HAND_EDIT]: VERIFY_CLASS_STEM.TAMPERED,
    [DAMAGE.TRUNCATION]: VERIFY_CLASS_STEM.TRUNCATED,
    [DAMAGE.STALE_RESTORE]: VERIFY_CLASS_STEM.STALE_RESTORE,
  }),
});

/**
 * The class-varying row code for a stem.
 *
 * @param {string} stem @param {string} className @returns {string}
 */
export function verifyClassCode(stem, className) {
  const suffix = CLASS_SUFFIX[className];
  if (suffix === undefined) {
    throw new Error(`verify: ${JSON.stringify(className)} is not a tracked content class`);
  }
  return `${stem}_${suffix}`;
}

/**
 * The frozen row code for one (store, damage mode, class) cell.
 *
 * @param {string} store @param {string} mode @param {string|null} [className]
 * @returns {string}
 */
export function damageCodeFor(store, mode, className = null) {
  const row = DAMAGE_MATRIX[store];
  if (row === undefined) throw new Error(`verify: ${JSON.stringify(store)} is not an object-model store`);
  const code = row[mode];
  if (code === undefined) throw new Error(`verify: ${JSON.stringify(mode)} is not a damage mode`);
  return store === STORE.SOURCE ? verifyClassCode(code, String(className)) : code;
}

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole,
  );
}

/**
 * An outcome for a verify row: read from the frozen table, or from the local success row.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function verifyOutcome(code, params = {}, extra = {}) {
  const local = VERIFY_LOCAL_ROWS[code];
  if (local !== undefined) {
    return Object.freeze({
      ok: extra.ok !== false,
      code,
      surface: VERIFY_SURFACE,
      status: local.status,
      text: fill(local.text, params),
      detail: Object.freeze({ ...params }),
    });
  }
  return rowOutcome(code, params, extra);
}

/** @returns {ReadonlyArray<string>} every frozen verify row code, for a test that enumerates */
export function verifyRowCodes() {
  return Object.freeze(rowsForSurface(VERIFY_SURFACE).map((r) => r.code));
}

/**
 * The rows this wave owns, READ from the table rather than restated - so a row a later wave
 * adds to the verify surface is that wave's to turn green, and one this wave forgot cannot
 * hide behind a hand-typed list.
 *
 * @returns {ReadonlyArray<string>}
 */
export function verifyRowsOwnedByThisWave() {
  return Object.freeze(
    rowsForSurface(VERIFY_SURFACE).filter((r) => r.wave === 'W14').map((r) => r.code),
  );
}

/**
 * Every done-when cell, checked mechanically: four stores, three modes, and for the source
 * store one code per tracked class. Returns the problems rather than throwing so a test can
 * print all of them at once.
 *
 * @returns {{ok: boolean, problems: string[], cells: number}}
 */
export function verifyMatrixIntegrity() {
  const problems = [];
  const known = new Set(verifyRowCodes());
  let cells = 0;

  for (const store of STORES) {
    for (const mode of DAMAGE_MODES) {
      const classes = store === STORE.SOURCE ? DERIVABLE_CLASSES : [null];
      for (const className of classes) {
        cells += 1;
        let code;
        try {
          code = damageCodeFor(store, mode, className);
        } catch (err) {
          problems.push(`${store}/${mode}${className ? `/${className}` : ''}: ${err.message}`);
          continue;
        }
        if (!known.has(code)) {
          problems.push(`${store}/${mode}${className ? `/${className}` : ''}: ${code} is not a frozen verify row`);
        }
      }
    }
    const codes = DAMAGE_MODES.map((mode) => DAMAGE_MATRIX[store][mode]);
    if (new Set(codes).size !== codes.length) {
      problems.push(
        `${store}: two damage modes share one code (${codes.join(', ')}); a stale restore that `
        + 'rendered as a hand-edit is exactly the conflation this matrix exists to prevent',
      );
    }
  }

  return { ok: problems.length === 0, problems, cells };
}

// -- byte-level classification --------------------------------------------------

/**
 * Are these bytes a document that was CUT SHORT, as opposed to one that is merely wrong?
 *
 * The test is structural rather than statistical: a JSON document whose braces never close,
 * or whose final string literal is never terminated, is a prefix of a longer document. That
 * is the exact shape a truncation leaves and is not the shape a hand-edit leaves, which is
 * why the two get different rows.
 *
 * @param {string} text @returns {boolean}
 */
export function looksTruncated(text) {
  const value = String(text ?? '');
  if (value.trim() === '') return true;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = 0; i < value.length; i += 1) {
    const ch = value[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') { inString = true; continue; }
    if (ch === '{' || ch === '[') depth += 1;
    else if (ch === '}' || ch === ']') depth -= 1;
  }
  return inString || depth > 0;
}

/**
 * Classify a file's bytes against the lineage the log records for it.
 *
 * This is THE discriminator, and it is deliberately a pure function of (bytes, lineage) so it
 * can be exercised directly - a rule this load-bearing should not be reachable only through a
 * verb that needs a temp directory and a registered project to run.
 *
 * @param {Buffer|null} bytes null when the file could not be read
 * @param {ReadonlyArray<object>} lineage the rows for this identity, oldest first
 * @returns {Readonly<{intact: boolean, mode: string|null, found_seq: number|null,
 *          current_seq: number|null, observed_len: number, recorded_len: number|null,
 *          sha256: string|null}>}
 */
export function classifyAgainstLineage(bytes, lineage) {
  const history = (Array.isArray(lineage) ? lineage : []).filter((row) => row && typeof row === 'object');
  const current = history.length === 0 ? null : history[history.length - 1];
  const currentSeq = current === null ? null : numberOrNull(current[ORDERING_FIELD]);
  const recordedLen = current === null ? null : numberOrNull(current.byte_len);

  const base = {
    intact: false,
    mode: null,
    found_seq: null,
    current_seq: currentSeq,
    observed_len: bytes === null ? 0 : bytes.length,
    recorded_len: recordedLen,
    sha256: bytes === null ? null : hashBytes(bytes),
  };

  if (bytes === null) return Object.freeze({ ...base, mode: null });
  if (current === null) return Object.freeze({ ...base, mode: DAMAGE.HAND_EDIT });

  const observed = base.sha256;
  if (observed === current.sha256) return Object.freeze({ ...base, intact: true, found_seq: currentSeq });

  // An EARLIER version of this exact file. D-4 is what makes this answerable: the whole
  // lineage is in the log, so "somebody put the old one back" is a fact rather than a guess.
  for (let i = history.length - 2; i >= 0; i -= 1) {
    if (history[i].sha256 === observed) {
      return Object.freeze({
        ...base,
        mode: DAMAGE.STALE_RESTORE,
        found_seq: numberOrNull(history[i][ORDERING_FIELD]),
      });
    }
  }

  // Shorter than what was written AND structurally unfinished: a prefix, not a rewrite.
  if (recordedLen !== null && bytes.length < recordedLen && looksTruncated(bytes.toString('utf8'))) {
    return Object.freeze({ ...base, mode: DAMAGE.TRUNCATION });
  }
  if (bytes.length === 0) return Object.freeze({ ...base, mode: DAMAGE.TRUNCATION });

  return Object.freeze({ ...base, mode: DAMAGE.HAND_EDIT });
}

/** @param {unknown} value @returns {number|null} */
function numberOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** @param {unknown} value @returns {boolean} */
function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** @param {object} fsx @param {string} abs @returns {{bytes: Buffer|null, errno: string|null}} */
function readBytes(fsx, abs) {
  try {
    // encoding-lint: raw-bytes - every verdict below is a BYTE verdict. A decoded read
    // replaces a truncated multi-byte sequence with U+FFFD and destroys the evidence, and it
    // erases MOJIBAKE outright - which is the one damage mode that parses perfectly.
    const raw = fsx.readFileSync(openablePath(abs));
    return { bytes: Buffer.isBuffer(raw) ? raw : Buffer.from(raw), errno: null };
  } catch (err) {
    return { bytes: null, errno: (err && err.code) || String(err) };
  }
}

// -- one finding ----------------------------------------------------------------

/**
 * A finding: the store, the mode, the frozen row, and the sentence the operator reads.
 *
 * @param {{store: string, mode: string|null, code: string, project_id?: string|null,
 *          class?: string|null, path?: string, params?: Record<string, unknown>,
 *          ok?: boolean}} parts
 * @returns {Readonly<object>}
 */
export function verifyFinding(parts) {
  const outcome = verifyOutcome(parts.code, parts.params ?? {}, { ok: parts.ok === true });
  return Object.freeze({
    store: parts.store,
    mode: parts.mode ?? null,
    code: parts.code,
    status: outcome.status,
    project_id: parts.project_id ?? null,
    class: parts.class ?? null,
    path: parts.path ?? null,
    text: outcome.text,
    detail: outcome.detail,
    ok: outcome.ok === true,
  });
}

// -- the snapshot store ---------------------------------------------------------

/**
 * Inspect the snapshot as a STORE: its bytes, its shape, its canonical form, and its position
 * in the log's lineage.
 *
 * The snapshot is read RAW here rather than through openIndexForRead, and that is the point:
 * the index reader refuses an unparseable snapshot, which is correct for every surface that
 * wants to USE it and useless for the one surface whose job is to say exactly HOW it is
 * broken. A verb that could only report "the index would not open" would collapse truncation,
 * hand-edit and encoding damage into one word.
 *
 * @param {{paths: object, fsx?: object, events: ReadonlyArray<object>, head_seq: number}} req
 * @returns {Readonly<object>}
 */
export function inspectSnapshotStore(req) {
  const fsx = req.fsx ?? fs;
  const snapshotPath = req.paths.snapshot;
  const events = replayEvents(req.events ?? []);
  const findings = [];

  const read = readBytes(fsx, snapshotPath);
  if (read.bytes === null) {
    if (read.errno === 'ENOENT') {
      // ABSENT is not damage. The snapshot is WHOLLY DERIVED and is in the deletable set by
      // design; `steward rebuild` makes another. Reporting it as tamper would teach operators
      // that the one safe recovery action looks like an attack.
      return Object.freeze({
        store: STORE.SNAPSHOT,
        path: snapshotPath,
        present: false,
        presence: assertStatusCode(PRESENCE.ABSENT, 'verify snapshot presence'),
        integrity: null,
        snapshot: null,
        head_seq: 0,
        findings: Object.freeze([]),
      });
    }
    findings.push(verifyFinding({
      store: STORE.SNAPSHOT,
      mode: null,
      code: VERIFY_CODE.INDEX_UNREADABLE,
      path: snapshotPath,
      params: { errno: read.errno },
    }));
    return frozenStore(STORE.SNAPSHOT, snapshotPath, PRESENCE.UNREACHABLE, null, findings);
  }

  const bytes = read.bytes;
  const text = bytes.toString('utf8');

  const scan = scanBytesForMojibake(bytes);
  if (!scan.clean) {
    findings.push(verifyFinding({
      store: STORE.SNAPSHOT,
      mode: DAMAGE.HAND_EDIT,
      code: VERIFY_CODE.MOJIBAKE,
      path: snapshotPath,
      params: { path: snapshotPath, offset: scan.first_offset ?? 0 },
    }));
    return frozenStore(STORE.SNAPSHOT, snapshotPath, PRESENCE.LIVE, INTEGRITY.MOJIBAKE, findings);
  }

  let parsed = null;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    const cut = looksTruncated(text);
    findings.push(verifyFinding({
      store: STORE.SNAPSHOT,
      mode: cut ? DAMAGE.TRUNCATION : DAMAGE.HAND_EDIT,
      code: cut ? VERIFY_CODE.SNAPSHOT_TRUNCATED : VERIFY_CODE.UNPARSEABLE,
      path: snapshotPath,
      params: {
        path: snapshotPath,
        observed_len: bytes.length,
        reason: String((err && err.message) || err),
      },
    }));
    return frozenStore(
      STORE.SNAPSHOT,
      snapshotPath,
      PRESENCE.LIVE,
      cut ? INTEGRITY.TORN : INTEGRITY.UNPARSEABLE,
      findings,
    );
  }

  const shape = validateSnapshotShape(parsed);
  if (!shape.ok) {
    findings.push(verifyFinding({
      store: STORE.SNAPSHOT,
      mode: DAMAGE.HAND_EDIT,
      code: VERIFY_CODE.SNAPSHOT_TAMPERED,
      path: snapshotPath,
      params: {
        path: snapshotPath,
        reason: `${REASON.SHAPE_REFUSED}: ${shape.problems.map((p) => p.code).join(', ')}`,
      },
    }));
    return frozenStore(STORE.SNAPSHOT, snapshotPath, PRESENCE.LIVE, INTEGRITY.TAMPERED, findings);
  }

  // The bytes must BE the canonical rendering of what they parse to. W6 makes the serializer
  // the only producer of snapshot bytes, so anything the serializer would not have emitted was
  // emitted by something else - which is the definition of an out-of-band edit, and it catches
  // a hand-edit that happens to leave valid JSON behind.
  let canonicalText = null;
  let canonicalProblem = null;
  try {
    canonicalText = serializeSnapshot(
      { schema: SNAPSHOT_SCHEMA, body: parsed.body, freshness: parsed.freshness },
      { hostname: req.hostname },
    ).text;
  } catch (err) {
    canonicalProblem = String((err && err.message) || err);
  }
  if (canonicalProblem !== null || canonicalText !== text) {
    findings.push(verifyFinding({
      store: STORE.SNAPSHOT,
      mode: DAMAGE.HAND_EDIT,
      code: VERIFY_CODE.SNAPSHOT_TAMPERED,
      path: snapshotPath,
      params: {
        path: snapshotPath,
        reason: canonicalProblem === null ? REASON.NOT_CANONICAL : `${REASON.NOT_CANONICAL}: ${canonicalProblem}`,
      },
    }));
    return frozenStore(STORE.SNAPSHOT, snapshotPath, PRESENCE.LIVE, INTEGRITY.TAMPERED, findings);
  }

  const freshness = isPlainObject(parsed.freshness) ? parsed.freshness : emptyFreshnessBlock();
  const headSeq = Number(freshness.head_seq ?? 0);
  const logHead = events.length === 0 ? 0 : Number(events[events.length - 1][ORDERING_FIELD]);

  // The head hash: the snapshot names a sequence, and the log's line at that sequence must
  // hash to what the snapshot recorded. A mismatch is a snapshot from a DIFFERENT history.
  if (headSeq > 0 && headSeq <= logHead) {
    const at = events.find((e) => Number(e[ORDERING_FIELD]) === headSeq) ?? null;
    const expected = at === null ? null : hashBytes(Buffer.from(logEventLine(at), 'utf8'));
    if (expected !== null && freshness.head_sha256 !== null && freshness.head_sha256 !== expected) {
      findings.push(verifyFinding({
        store: STORE.SNAPSHOT,
        mode: DAMAGE.HAND_EDIT,
        code: VERIFY_CODE.SNAPSHOT_TAMPERED,
        path: snapshotPath,
        params: { path: snapshotPath, reason: REASON.HEAD_HASH_MISMATCH },
      }));
    }
  }

  // THE STALE RESTORE. The log's events after the snapshot's head carry rows that SUPERSEDE
  // rows the snapshot still describes - so the snapshot's content is a version this system
  // has already replaced. That is the fingerprint of an older copy put back while the log
  // moved ahead, and it is distinct from a snapshot that is merely INCOMPLETE (a file written
  // since, with nothing superseded), which is an ordinary D-3 tail and no finding at all.
  const superseded = supersededByTail(events, headSeq);
  if (superseded.length > 0) {
    findings.push(verifyFinding({
      store: STORE.SNAPSHOT,
      mode: DAMAGE.STALE_RESTORE,
      code: VERIFY_CODE.STALE_RESTORE,
      path: snapshotPath,
      params: {
        path: snapshotPath,
        snapshot_seq: headSeq,
        log_seq: logHead,
        reason: `${REASON.SUPERSEDED_ROWS} (${superseded.length})`,
      },
    }));
  }

  return Object.freeze({
    store: STORE.SNAPSHOT,
    path: snapshotPath,
    present: true,
    presence: assertStatusCode(PRESENCE.LIVE, 'verify snapshot presence'),
    integrity: assertStatusCode(
      findings.length === 0 ? INTEGRITY.OK : INTEGRITY.TAMPERED,
      'verify snapshot integrity',
    ),
    snapshot: parsed,
    head_seq: headSeq,
    superseded: Object.freeze(superseded),
    findings: Object.freeze(findings),
  });
}

/**
 * The rows the log replaced AFTER a given head - i.e. the file versions a snapshot computed
 * at that head is still describing.
 *
 * @param {ReadonlyArray<object>} events @param {number} headSeq
 * @returns {Array<{identity: string, superseded_seq: number, by_seq: number}>}
 */
export function supersededByTail(events, headSeq) {
  const after = Number(headSeq ?? 0);
  const out = [];
  for (const event of replayEvents(events ?? [])) {
    if (!isDerivedEvent(event)) continue;
    const seq = Number(event[ORDERING_FIELD]);
    if (seq <= after) continue;
    const replaced = numberOrNull(event.supersedes);
    if (replaced === null || replaced > after) continue;
    out.push({ identity: rowIdentity(event), superseded_seq: replaced, by_seq: seq });
  }
  return out;
}

/** @param {string} store @param {string} p @param {string} presence @param {string|null} integrity
 *  @param {Array<object>} findings @returns {Readonly<object>} */
function frozenStore(store, p, presence, integrity, findings) {
  return Object.freeze({
    store,
    path: p,
    present: true,
    presence: assertStatusCode(presence, `verify ${store} presence`),
    integrity: integrity === null ? null : assertStatusCode(integrity, `verify ${store} integrity`),
    snapshot: null,
    head_seq: 0,
    findings: Object.freeze(findings),
  });
}

// -- the log store --------------------------------------------------------------

/**
 * Inspect the log as a STORE.
 *
 * The log cannot be checked against a hash of itself - it IS the baseline - so it is checked
 * for INTERNAL consistency instead: a total order with no duplicate and no gap, payloads that
 * still satisfy the validators that wrote them, and a supersede chain whose every link lands
 * on a sequence that exists. Each of those is something an append can never produce and a
 * hand-edit routinely does.
 *
 * @param {{paths: object, events: ReadonlyArray<object>, torn: object|null,
 *          snapshotHead: number, view: object}} req
 * @returns {Readonly<object>}
 */
export function inspectLogStore(req) {
  const events = replayEvents(req.events ?? []);
  const findings = [];
  const logPath = req.paths.log;

  if (req.torn !== null && req.torn !== undefined) {
    findings.push(verifyFinding({
      store: STORE.LOG,
      mode: DAMAGE.TRUNCATION,
      code: VERIFY_CODE.LOG_TORN,
      path: logPath,
      params: { log: logPath, path: logPath },
    }));
  }

  const run = seqIntegrity(events);
  if (!run.ok) {
    findings.push(verifyFinding({
      store: STORE.LOG,
      mode: DAMAGE.HAND_EDIT,
      code: VERIFY_CODE.LOG_TAMPERED,
      path: logPath,
      params: {
        path: logPath,
        seq: [...run.duplicates, ...run.gaps][0] ?? 0,
        reason: `${REASON.SEQ_RUN_BROKEN} (duplicates ${run.duplicates.length}, gaps ${run.gaps.length})`,
      },
    }));
  }

  const byIdentity = derivedRowsInLog(events);
  const seqs = new Set(events.map((e) => Number(e[ORDERING_FIELD])));

  for (const event of events) {
    if (isDerivedEvent(event)) {
      const badHash = typeof event.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(event.sha256);
      const badLen = !Number.isInteger(event.byte_len) || event.byte_len < 0;
      if (badHash || badLen) {
        findings.push(verifyFinding({
          store: STORE.LOG,
          mode: DAMAGE.HAND_EDIT,
          code: VERIFY_CODE.LOG_TAMPERED,
          path: logPath,
          params: {
            path: logPath,
            seq: Number(event[ORDERING_FIELD]),
            reason: `${REASON.ROW_MALFORMED} (${badHash ? 'sha256' : 'byte_len'})`,
          },
        }));
        continue;
      }
      const replaced = numberOrNull(event.supersedes);
      if (replaced !== null && !seqs.has(replaced)) {
        findings.push(verifyFinding({
          store: STORE.LOG,
          mode: DAMAGE.HAND_EDIT,
          code: VERIFY_CODE.LOG_TAMPERED,
          path: logPath,
          params: {
            path: logPath,
            seq: Number(event[ORDERING_FIELD]),
            reason: `${REASON.LINEAGE_BROKEN} (${replaced})`,
          },
        }));
      }
      continue;
    }
    if (isPlainObject(event) && event.t === NATIVE_EVENT.COMMIT_INTENT) {
      const check = validateCommitIntent(event.intent);
      if (!check.ok) {
        findings.push(verifyFinding({
          store: STORE.LOG,
          mode: DAMAGE.HAND_EDIT,
          code: VERIFY_CODE.LOG_TAMPERED,
          path: logPath,
          params: {
            path: logPath,
            seq: Number(event[ORDERING_FIELD]),
            reason: `${REASON.INTENT_MALFORMED}: ${check.problems.map((p) => p.code).join(', ')}`,
          },
        }));
      }
    }
  }

  // The log BEHIND the snapshot it produced can only mean one thing: the log on disk is an
  // older copy of itself. Everything after its head is gone, and saying so is the whole
  // difference between a recoverable incident and a silent one.
  const logHead = run.head_seq;
  if (Number(req.snapshotHead ?? 0) > logHead) {
    findings.push(verifyFinding({
      store: STORE.LOG,
      mode: DAMAGE.STALE_RESTORE,
      code: VERIFY_CODE.LOG_STALE_RESTORE,
      path: logPath,
      params: { path: logPath, log_seq: logHead, snapshot_seq: Number(req.snapshotHead ?? 0) },
    }));
  }

  return Object.freeze({
    store: STORE.LOG,
    path: logPath,
    present: true,
    presence: assertStatusCode(PRESENCE.LIVE, 'verify log presence'),
    integrity: assertStatusCode(
      findings.length > 0 ? INTEGRITY.TAMPERED : (events.length === 0 ? INTEGRITY.EMPTY : INTEGRITY.OK),
      'verify log integrity',
    ),
    head_seq: logHead,
    events: events.length,
    identities: byIdentity.size,
    findings: Object.freeze(findings),
  });
}

// -- the marker store -----------------------------------------------------------

/**
 * Every marker hash this log has ever recorded for a project, oldest first.
 *
 * Registration records one; every reconcile records the hash of the marker it bound. So the
 * marker HAS a lineage, exactly as a receipt does, and "somebody put the old marker back" is
 * answerable by the same rule rather than by a special case.
 *
 * @param {object} project a registry-view entry @returns {ReadonlyArray<string>}
 */
export function markerLineageFor(project) {
  const out = [];
  if (project && typeof project.marker_sha256 === 'string') out.push(project.marker_sha256);
  for (const move of project?.moves ?? []) {
    if (typeof move.marker_sha256 === 'string' && move.marker_sha256 !== out[out.length - 1]) {
      out.push(move.marker_sha256);
    }
  }
  return Object.freeze(out);
}

/**
 * Inspect one root's marker.
 *
 * @param {{project: object, root: string, fsx?: object}} req
 * @returns {Readonly<object>}
 */
export function inspectMarkerStore(req) {
  const fsx = req.fsx ?? fs;
  const markerPath = markerPathFor(req.root);
  const findings = [];
  const lineage = markerLineageFor(req.project);
  const current = lineage.length === 0 ? null : lineage[lineage.length - 1];

  const read = readMarker(req.root, { fs: fsx });

  if (!read.ok) {
    const raw = readBytes(fsx, markerPath);
    const text = raw.bytes === null ? '' : raw.bytes.toString('utf8');
    const code = read.code;

    if (code === MARKER_REFUSAL.ABSENT) {
      // Absence is a BINDING question, and W12's reconcile owns it. Verify records it, marks
      // the project STALE, and refuses to dress it up as an edit nobody made.
      return Object.freeze({
        store: STORE.MARKER,
        path: markerPath,
        project_id: req.project?.project_id ?? null,
        present: false,
        presence: assertStatusCode(PRESENCE.ABSENT, 'verify marker presence'),
        integrity: null,
        intact: false,
        findings: Object.freeze([]),
      });
    }

    let mode = DAMAGE.HAND_EDIT;
    let rowCode = VERIFY_CODE.MARKER_TAMPERED;
    let params = { path: markerPath, reason: REASON.MARKER_REFUSED };

    if (code === MARKER_REFUSAL.EMPTY || (code === MARKER_REFUSAL.NOT_JSON && looksTruncated(text))) {
      mode = DAMAGE.TRUNCATION;
      rowCode = VERIFY_CODE.MARKER_TRUNCATED;
      params = {
        path: markerPath,
        observed_len: raw.bytes === null ? 0 : raw.bytes.length,
        recorded_len: read.bytes_len ?? 0,
      };
    } else if (code === MARKER_REFUSAL.MOJIBAKE) {
      mode = DAMAGE.HAND_EDIT;
      rowCode = VERIFY_CODE.MOJIBAKE;
      params = { path: markerPath, offset: scanBytesForMojibake(raw.bytes ?? Buffer.alloc(0)).first_offset ?? 0 };
    } else if (code === MARKER_REFUSAL.INVALID_UTF8) {
      mode = DAMAGE.HAND_EDIT;
      rowCode = VERIFY_CODE.UNPARSEABLE;
      params = { path: markerPath, reason: String(code) };
    } else if (code === MARKER_REFUSAL.UNREADABLE) {
      mode = null;
      rowCode = VERIFY_CODE.ROOT_UNREACHABLE;
      params = { path: markerPath, errno: raw.errno ?? '' };
    }

    findings.push(verifyFinding({
      store: STORE.MARKER,
      mode,
      code: rowCode,
      project_id: req.project?.project_id ?? null,
      path: markerPath,
      params,
    }));
    return Object.freeze({
      store: STORE.MARKER,
      path: markerPath,
      project_id: req.project?.project_id ?? null,
      present: true,
      presence: assertStatusCode(PRESENCE.LIVE, 'verify marker presence'),
      integrity: assertStatusCode(
        mode === DAMAGE.TRUNCATION ? INTEGRITY.TORN : INTEGRITY.TAMPERED,
        'verify marker integrity',
      ),
      intact: false,
      findings: Object.freeze(findings),
    });
  }

  if (current !== null && read.hash !== current) {
    const earlier = lineage.indexOf(String(read.hash));
    const stale = earlier !== -1;
    findings.push(verifyFinding({
      store: STORE.MARKER,
      mode: stale ? DAMAGE.STALE_RESTORE : DAMAGE.HAND_EDIT,
      code: stale ? VERIFY_CODE.MARKER_STALE_RESTORE : VERIFY_CODE.MARKER_TAMPERED,
      project_id: req.project?.project_id ?? null,
      path: markerPath,
      params: stale
        ? { path: markerPath, found_seq: earlier, current_seq: lineage.length - 1 }
        : { path: markerPath, reason: REASON.MARKER_UNKNOWN_HASH },
    }));
  }

  return Object.freeze({
    store: STORE.MARKER,
    path: markerPath,
    project_id: req.project?.project_id ?? null,
    present: true,
    presence: assertStatusCode(PRESENCE.LIVE, 'verify marker presence'),
    integrity: assertStatusCode(
      findings.length === 0 ? INTEGRITY.OK : INTEGRITY.TAMPERED,
      'verify marker integrity',
    ),
    intact: findings.length === 0,
    findings: Object.freeze(findings),
  });
}

// -- the source-of-truth files --------------------------------------------------

/**
 * Re-hash one project's tracked files against the lineage.
 *
 * The three classes are handled by ONE loop over the lineage, which is the point rather than
 * an economy: a receipt-shaped branch with two copies bolted on is exactly how legs 7 and 8
 * went missing in round 1. Every class reaches this code by the same route, and the per-class
 * row codes come out of the frozen table by stem.
 *
 * @param {{project: object, root: string, events: ReadonlyArray<object>, fsx?: object,
 *          bound?: number}} req
 * @returns {Readonly<object>}
 */
export function verifyProjectSources(req) {
  const fsx = req.fsx ?? fs;
  const id = String(req.project.project_id);
  const root = req.root;
  const bound = Number.isInteger(req.bound) && req.bound > 0 ? req.bound : CAPS.walk_entries;

  const byIdentity = derivedRowsInLog(req.events ?? []);
  const findings = [];
  const observedRows = [];
  const perClass = Object.fromEntries(DERIVABLE_CLASSES.map((c) => [c, 0]));

  let checked = 0;
  let intact = 0;
  let truncatedAtBound = false;

  const identities = [...byIdentity.keys()].sort();
  for (const identity of identities) {
    const history = byIdentity.get(identity) ?? [];
    const current = history[history.length - 1];
    if (String(current.project_id) !== id) continue;
    if (!DERIVABLE_CLASSES.includes(current.class)) continue;

    if (checked >= bound) { truncatedAtBound = true; break; }
    checked += 1;
    perClass[current.class] += 1;

    const rel = toPosix(String(current.path));
    const contained = containedPath(root, rel);
    if (!contained.ok) {
      // A recorded path that escapes its root is refused BEFORE it is opened. Verifying it
      // would mean reading a file outside the project on the strength of the very record the
      // escape says cannot be trusted.
      findings.push(verifyFinding({
        store: STORE.SOURCE,
        mode: DAMAGE.HAND_EDIT,
        code: verifyClassCode(VERIFY_CLASS_STEM.TAMPERED, current.class),
        project_id: id,
        class: current.class,
        path: rel,
        params: { path: rel, project_id: id, reason: REASON.PATH_ESCAPE },
      }));
      continue;
    }

    const abs = path.join(root, ...rel.split('/'));
    const read = readBytes(fsx, abs);

    if (read.bytes === null && read.errno === 'ENOENT') {
      findings.push(verifyFinding({
        store: STORE.SOURCE,
        mode: null,
        code: verifyClassCode(VERIFY_CLASS_STEM.SOURCE_ABSENT, current.class),
        project_id: id,
        class: current.class,
        path: rel,
        params: { path: rel, project_id: id },
      }));
      // The ROW is retained: absence of a file never removes the fact that it was written.
      observedRows.push(current);
      continue;
    }
    if (read.bytes === null) {
      findings.push(verifyFinding({
        store: STORE.SOURCE,
        mode: null,
        code: VERIFY_CODE.UNPARSEABLE,
        project_id: id,
        class: current.class,
        path: rel,
        params: { path: rel, reason: `${REASON.UNREADABLE} (${read.errno})` },
      }));
      observedRows.push(current);
      continue;
    }

    const scan = scanBytesForMojibake(read.bytes);
    if (!scan.clean) {
      findings.push(verifyFinding({
        store: STORE.SOURCE,
        mode: DAMAGE.HAND_EDIT,
        code: VERIFY_CODE.MOJIBAKE,
        project_id: id,
        class: current.class,
        path: rel,
        params: { path: rel, offset: scan.first_offset ?? 0 },
      }));
    }

    const verdict = classifyAgainstLineage(read.bytes, history);
    observedRows.push({
      project_id: id,
      class: current.class,
      path: current.path,
      sha256: verdict.sha256,
      byte_len: verdict.observed_len,
    });

    if (verdict.intact) { intact += 1; continue; }

    if (verdict.observed_len === 0 && Number(current.byte_len) === 0) {
      // Valid and EMPTY, which is a state of a store that was READ - never UNKNOWN.
      findings.push(verifyFinding({
        store: STORE.SOURCE,
        mode: null,
        ok: true,
        code: verifyClassCode(VERIFY_CLASS_STEM.EMPTY, current.class),
        project_id: id,
        class: current.class,
        path: rel,
        params: { path: rel },
      }));
      intact += 1;
      continue;
    }

    findings.push(verifyFinding({
      store: STORE.SOURCE,
      mode: verdict.mode,
      code: damageCodeFor(STORE.SOURCE, verdict.mode ?? DAMAGE.HAND_EDIT, current.class),
      project_id: id,
      class: current.class,
      path: rel,
      params: {
        path: rel,
        project_id: id,
        found_seq: verdict.found_seq ?? '(none)',
        current_seq: verdict.current_seq ?? '(none)',
        observed_len: verdict.observed_len,
        recorded_len: verdict.recorded_len ?? 0,
      },
    }));
  }

  // EMPTY is asserted per class, and it is NOT the same output as UNKNOWN: the steward read
  // this live root and there genuinely are no files of that class.
  for (const className of DERIVABLE_CLASSES) {
    if (perClass[className] === 0) {
      findings.push(verifyFinding({
        store: STORE.SOURCE,
        mode: null,
        ok: true,
        code: verifyClassCode(VERIFY_CLASS_STEM.EMPTY, className),
        project_id: id,
        class: className,
        path: root,
        params: { path: root },
      }));
    }
  }

  if (truncatedAtBound) {
    findings.push(verifyFinding({
      store: STORE.SOURCE,
      mode: null,
      code: VERIFY_CODE.BOUND_EXCEEDED,
      project_id: id,
      params: { cap: bound },
    }));
  }

  return Object.freeze({
    project_id: id,
    root,
    checked,
    intact,
    complete: !truncatedAtBound,
    per_class: Object.freeze(perClass),
    observed_rows: Object.freeze(observedRows),
    content_sha256: projectContentHash(observedRows),
    findings: Object.freeze(findings),
  });
}

// -- the acknowledged-commit watermark ------------------------------------------

/**
 * The last acknowledged commit-intent sequence per project, and the portfolio's floor.
 *
 * THIS IS THE HONESTY BOUND, and it is computed rather than asserted. Everything at or before
 * the watermark is verifiable against a baseline that has left this machine; everything after
 * it is verifiable only against the local log. W15 lands the ack events themselves; until
 * they exist the watermark is the highest EMITTED intent, and the receipt says which of the
 * two it is rather than implying the stronger one.
 *
 * @param {Readonly<object>} view the registry view
 * @returns {Readonly<{per_project: Record<string, number|null>, floor: number|null,
 *          basis: string}>}
 */
export function acknowledgedWatermark(view) {
  const perProject = {};
  let floor = null;
  for (const project of view?.projects ?? []) {
    const seq = Number.isFinite(Number(project.commit_intent_seq))
      ? Number(project.commit_intent_seq)
      : null;
    perProject[project.project_id] = seq;
    if (seq !== null && (floor === null || seq < floor)) floor = seq;
  }
  return Object.freeze({
    per_project: Object.freeze(perProject),
    floor,
    basis: 'HIGHEST_EMITTED_COMMIT_INTENT_PENDING_ANCHOR_ACK',
  });
}

/** The sentence the receipt carries on every run, so the bound is never merely implied. */
export const STRENGTH_TEXT =
  'Detection strength equals the last acknowledged commit: content written after commit-intent '
  + 'seq {ack_seq} is checked against a baseline that exists only on this disk. Anything at or '
  + 'before it is checked against the lineage Anchor has been asked to honour.';

// -- the verb -------------------------------------------------------------------

/**
 * `steward verify`.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, now?: number|Date,
 *          write?: boolean, bound?: number, boundMs?: number, staleMs?: number,
 *          quarantine?: boolean, lockOpts?: object, retries?: number, pid?: number,
 *          hostname?: string}} [opts]
 * @returns {Readonly<object>} the verify-receipt-v1
 */
export function verifyIndex(opts = {}) {
  const paths = indexPathsFrom(opts);
  const fsx = opts.fsx ?? fs;
  const at = new Date(opts.now ?? Date.now()).toISOString();

  // The LOG only, and under the lock. openIndexForRead would refuse outright on a damaged
  // snapshot, and "the index would not open" is the one answer this verb may never give when
  // the whole question is which store is damaged and how.
  const input = readRebuildInput({ ...opts, paths });
  if (input.ok !== true) {
    const code = READ_CODE_ROW[input.outcome?.code] ?? VERIFY_CODE.INDEX_UNREADABLE;
    return Object.freeze({
      ok: false,
      schema: VERIFY_RECEIPT_SCHEMA,
      version: VERIFY_VERSION,
      home: paths.home,
      log: paths.log,
      snapshot: paths.snapshot,
      outcome: verifyOutcome(code, {
        home: paths.home,
        path: paths.log,
        errno: input.outcome?.detail?.errno ?? '',
        reason: input.outcome?.text ?? '',
      }),
      stores: Object.freeze([]),
      projects: Object.freeze([]),
      findings: Object.freeze([]),
      marked: Object.freeze({ FRESH: [], STALE: [], UNKNOWN: [] }),
      codes: Object.freeze([code]),
      strength: null,
      write: null,
    });
  }

  const events = replayEvents(input.events ?? []);
  const view = materializeRegistry(events);
  const watermark = acknowledgedWatermark(view);

  const snapshotStore = inspectSnapshotStore({
    paths,
    fsx,
    events,
    head_seq: input.head_seq,
    hostname: opts.hostname,
  });
  const logStore = inspectLogStore({
    paths,
    events,
    torn: input.torn ?? null,
    snapshotHead: snapshotStore.head_seq,
    view,
  });

  const body = snapshotStore.snapshot === null || !isPlainObject(snapshotStore.snapshot.body)
    ? null
    : snapshotStore.snapshot.body;
  const previousFreshness = snapshotStore.snapshot === null
    || !isPlainObject(snapshotStore.snapshot.freshness)
    ? emptyFreshnessBlock()
    : snapshotStore.snapshot.freshness;

  const findings = [...snapshotStore.findings, ...logStore.findings];
  const stores = [snapshotStore, logStore];
  const projects = [];
  const perProject = {};
  const marked = { [FRESHNESS.FRESH]: [], [FRESHNESS.STALE]: [], [FRESHNESS.UNKNOWN]: [] };

  let filesChecked = 0;
  let complete = true;

  for (const project of view.projects) {
    const id = project.project_id;
    const root = project.current_path;
    const probed = classifyRootStatus(root, { fsx });

    if (!probed.live) {
      // Nobody could look, so nothing is verified and nothing is claimed. UNKNOWN per class -
      // which is neither a pass nor an empty store, and is the distinction the whole enum
      // exists to keep.
      findings.push(verifyFinding({
        store: STORE.SOURCE,
        mode: null,
        code: VERIFY_CODE.ROOT_UNREACHABLE,
        project_id: id,
        path: root,
        params: { path: root, errno: probed.reason ?? '' },
      }));
      for (const className of DERIVABLE_CLASSES) {
        findings.push(verifyFinding({
          store: STORE.SOURCE,
          mode: null,
          code: verifyClassCode(VERIFY_CLASS_STEM.UNKNOWN, className),
          project_id: id,
          class: className,
          path: root,
          params: { path: root },
        }));
      }
      perProject[id] = perProjectFreshness({
        last_seen: null,
        last_verified: at,
        presence: probed.presence,
        freshness: FRESHNESS.UNKNOWN,
      });
      marked[FRESHNESS.UNKNOWN].push(id);
      projects.push(Object.freeze({
        project_id: id,
        root,
        presence: probed.presence,
        freshness: FRESHNESS.UNKNOWN,
        verified: false,
        checked: 0,
        intact: 0,
        drift: null,
        marker: null,
        findings: Object.freeze([]),
      }));
      continue;
    }

    const marker = inspectMarkerStore({ project, root, fsx });
    stores.push(marker);

    const sources = verifyProjectSources({ project, root, events, fsx, bound: opts.bound });
    filesChecked += sources.checked;
    if (!sources.complete) complete = false;

    const recorded = contentHashFor(body?.content_hashes, id);
    const drift = recorded === null
      ? null
      : Object.freeze({
        recorded: String(recorded.sha256),
        observed: sources.content_sha256,
        matches: String(recorded.sha256) === sources.content_sha256,
      });
    if (drift !== null && !drift.matches) {
      findings.push(verifyFinding({
        store: STORE.SNAPSHOT,
        mode: null,
        code: VERIFY_CODE.STALE_RESTORE,
        project_id: id,
        path: paths.snapshot,
        params: {
          path: paths.snapshot,
          snapshot_seq: snapshotStore.head_seq,
          log_seq: logStore.head_seq,
          reason: `${REASON.CONTENT_HASH_DRIFT} (${id})`,
        },
      }));
    }

    const projectFindings = [
      ...marker.findings,
      ...sources.findings,
    ];
    findings.push(...marker.findings, ...sources.findings);

    // Drift is ANY real finding on this project, or a content hash that no longer matches.
    // "Real" excludes the ok:true rows - an empty class is a state of a healthy project, and
    // marking it STALE would make the STALE mark mean nothing within a week.
    const damaged = projectFindings.some((f) => f.ok !== true)
      || (drift !== null && !drift.matches)
      || marker.presence === PRESENCE.ABSENT;
    const freshness = damaged ? FRESHNESS.STALE : FRESHNESS.FRESH;

    perProject[id] = perProjectFreshness({
      last_seen: at,
      last_verified: at,
      presence: probed.presence,
      freshness,
    });
    marked[freshness].push(id);
    projects.push(Object.freeze({
      project_id: id,
      root,
      presence: probed.presence,
      freshness,
      verified: true,
      checked: sources.checked,
      intact: sources.intact,
      content_sha256: sources.content_sha256,
      drift,
      marker: Object.freeze({
        path: marker.path,
        presence: marker.presence,
        integrity: marker.integrity,
        intact: marker.intact === true,
      }),
      findings: Object.freeze(projectFindings),
    }));
  }

  if (!complete) {
    findings.push(verifyFinding({
      store: STORE.SOURCE,
      mode: null,
      code: VERIFY_CODE.BOUND_EXCEEDED,
      params: { cap: opts.bound ?? CAPS.walk_entries },
    }));
  }

  if (view.projects.length === 0) {
    findings.push(verifyFinding({
      store: STORE.SOURCE,
      mode: null,
      ok: true,
      code: VERIFY_CODE.NOTHING_REGISTERED,
      path: paths.home,
      params: { home: paths.home },
    }));
  }

  // -- persist the marks ---------------------------------------------------------
  const write = writeFreshness({
    ...opts,
    paths,
    fsx,
    events,
    body,
    previous: previousFreshness,
    per_project: perProject,
    computed_at: at,
    write: opts.write !== false && snapshotStore.integrity !== INTEGRITY.TAMPERED
      && snapshotStore.integrity !== INTEGRITY.TORN
      && snapshotStore.integrity !== INTEGRITY.UNPARSEABLE,
  });

  const real = findings.filter((f) => f.ok !== true);
  const outcome = real.length === 0
    ? verifyOutcome(VERIFY_OK, {
      projects: view.projects.length,
      files: filesChecked,
      stores: stores.length,
      ack_seq: watermark.floor ?? 0,
    })
    : real[0];

  return Object.freeze({
    ok: real.length === 0,
    schema: VERIFY_RECEIPT_SCHEMA,
    version: VERIFY_VERSION,
    home: paths.home,
    log: paths.log,
    snapshot: paths.snapshot,
    outcome,
    complete,
    stores: Object.freeze(stores),
    projects: Object.freeze(projects),
    findings: Object.freeze(findings),
    marked: Object.freeze({
      [FRESHNESS.FRESH]: Object.freeze([...marked[FRESHNESS.FRESH]].sort()),
      [FRESHNESS.STALE]: Object.freeze([...marked[FRESHNESS.STALE]].sort()),
      [FRESHNESS.UNKNOWN]: Object.freeze([...marked[FRESHNESS.UNKNOWN]].sort()),
    }),
    files_checked: filesChecked,
    codes: Object.freeze([...new Set(findings.map((f) => f.code))].sort()),
    strength: Object.freeze({
      ...watermark,
      text: fill(STRENGTH_TEXT, { ack_seq: watermark.floor ?? 0 }),
    }),
    freshness: Object.freeze({ ...previousFreshness, per_project: Object.freeze(perProject) }),
    write,
  });
}

/**
 * How an index-read refusal is spoken on the verify surface. The two that have no verify
 * counterpart pass through as VERIFY_INDEX_UNREADABLE rather than being folded into a row
 * about a store this call never reached.
 */
export const READ_CODE_ROW = Object.freeze({
  [INDEX_READ_CODE.HOME_ABSENT]: VERIFY_CODE.INDEX_UNREADABLE,
  [INDEX_READ_CODE.HOME_UNREACHABLE]: VERIFY_CODE.INDEX_UNREADABLE,
  [INDEX_READ_CODE.SNAPSHOT_UNREADABLE]: VERIFY_CODE.INDEX_UNREADABLE,
  [INDEX_READ_CODE.LOCK_TIMEOUT]: VERIFY_CODE.LOCK_TIMEOUT,
  [INDEX_READ_CODE.LOG_TORN_TAIL]: VERIFY_CODE.LOG_TORN,
  [INDEX_READ_CODE.SNAPSHOT_UNPARSEABLE]: VERIFY_CODE.UNPARSEABLE,
  [INDEX_READ_CODE.SNAPSHOT_MOJIBAKE]: VERIFY_CODE.MOJIBAKE,
});

/**
 * Persist the freshness marks, and NOTHING else.
 *
 * The body handed back to the serializer is the body that was already on disk, unchanged - so
 * the D-2 byte-equality region is byte-identical across a verify, and the only difference in
 * the artifact is inside the one block D-2 permits to vary. When there is no snapshot at all,
 * a body is folded from the log (the D-3 re-materializer's own fold, imported rather than
 * re-derived) so that a first-ever verify still has somewhere to record its answer.
 *
 * @param {object} req @returns {Readonly<object>|null}
 */
function writeFreshness(req) {
  if (req.write !== true) return null;

  const events = replayEvents(req.events ?? []);
  const logHead = events.length === 0 ? 0 : Number(events[events.length - 1][ORDERING_FIELD]);

  let body = req.body;
  let headSeq = Number(req.previous?.head_seq ?? 0);
  let headSha = req.previous?.head_sha256 ?? null;
  if (body === null) {
    body = foldTailIntoBody(null, events, { head_seq: 0 }).body;
    headSeq = logHead;
    headSha = logHeadSha256(events);
  }
  // The content-hash baseline is refreshed only when this call MINTED the body. A body read
  // from disk keeps its own baseline: rewriting it here would make verify agree with whatever
  // it just found, which is the one thing a detector must never do.
  const next = emptyFreshnessBlock({
    head_seq: headSeq,
    head_sha256: headSha,
    computed_at: req.computed_at,
    per_project: req.per_project,
  });

  return withPortfolioLock(
    req.paths,
    () => writeCanonicalSnapshot(
      req.paths.snapshot,
      { schema: SNAPSHOT_SCHEMA, body, freshness: next },
      {
        fsx: req.fsx,
        seq: headSeq,
        pid: req.pid,
        retries: req.retries,
        hostname: req.hostname,
      },
    ),
    { boundMs: req.boundMs, staleMs: req.staleMs, lockOpts: req.lockOpts },
  );
}

// -- rendering ------------------------------------------------------------------

/**
 * Render a verify receipt for a terminal.
 *
 * @param {Readonly<object>} result @returns {string}
 */
export function renderVerify(result) {
  const lines = [];
  lines.push(`${VERIFY_VERB}: ${result.outcome?.text ?? ''}`);
  for (const store of result.stores ?? []) {
    const integrity = store.integrity === null ? store.presence : store.integrity;
    lines.push(`  [${store.store}] ${integrity} ${store.path}`);
  }
  for (const project of result.projects ?? []) {
    lines.push(`  ${project.project_id} ${project.presence}/${project.freshness} ${project.root}`);
  }
  for (const finding of (result.findings ?? []).filter((f) => f.ok !== true)) {
    lines.push(`  ! ${finding.code} ${finding.text}`);
  }
  if (result.strength !== null && result.strength !== undefined) {
    lines.push(`  ${result.strength.text}`);
  }
  return lines.join('\n');
}

/** The re-verification contract, as data: verify is a VERB, never a query-time mode. */
export const REVERIFICATION_CONTRACT = Object.freeze({
  verb: VERIFY_VERB,
  chained_by: 'the caller, explicitly',
  query_side_effect: false,
  why:
    'A query that silently re-verified would make its cost, and its answer, depend on state '
    + 'the caller never asked about. Freshness is REPORTED by query and DECIDED by verify, and '
    + 'the two verbs are chained by whoever wants both.',
});

/** The body region verify reads its baseline from. Named so a test can cite it rather than
 * hard-code the key, and so moving the baseline is a visible edit in one place. */
export const CONTENT_BASELINE_KEY = 'content_hashes';

/**
 * The baseline a body carries for a row set - the same function the rebuilder and the D-3
 * re-materializer call, re-exported here so a caller checking verify's arithmetic uses the
 * producer's own code rather than a second copy of it.
 *
 * @param {ReadonlyArray<object>} rows @returns {ReadonlyArray<object>}
 */
export function contentBaselineFor(rows) {
  return contentHashesFor(rows);
}

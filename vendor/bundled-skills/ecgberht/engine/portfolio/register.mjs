/**
 * W7 - `steward register <root>`: the ONE place a project_id is ever minted.
 *
 * WHAT THIS VERB PROMISES, in the order the promises are made durable:
 *
 *   1. a project_id is minted EXACTLY ONCE per root, by crypto.randomUUID and never from
 *      the path (identity.mjs refuses a derived id in code, not in review);
 *   2. the mint is recorded as a NATIVE event in the never-deletable live log, fsynced
 *      before this function returns anything at all;
 *   3. the same identity is mirrored into the root as a marker-v2, which is what makes
 *      recovery git-free when the log is gone (W17);
 *   4. a commit-intent-v1 receipt naming the marker's exact bytes is appended, which is
 *      what Anchor honors and what W14 later verifies tamper against.
 *
 * THE ORDER IS THE CONTRACT, AND IT IS LOG-FIRST. Writing the marker before the log event
 * looks equivalent and is not: a crash in that window leaves a root carrying an id the log
 * never minted, which is indistinguishable from a forged marker - exactly the claim
 * reconcile is built to refuse, so the operator would be left with a project the system is
 * required to disbelieve. Log-first fails the other way: the id exists, the root has no
 * mirror, and every surface can see that and say so. One window loses a project to a
 * refusal it cannot argue with; the other loses a mirror that can be rewritten. The marker
 * hash goes INTO the registration event, computed from the marker's canonical text before
 * a byte is written, so the log records what the mirror must contain rather than what it
 * happened to contain afterwards.
 *
 * WHAT IT REFUSES, AND WHY REFUSING IS THE FEATURE. Registering a root that already carries
 * a marker is REGISTER_ALREADY_MARKED. Not "re-register", not "adopt", not "overwrite":
 * either of those mints a second identity for one root or destroys the only git-free record
 * of the first. Both are unrecoverable in precisely the disaster the marker exists for. So
 * the verb refuses, names the id already on the root, and points at the two explicit routes
 * that CAN resolve it - `steward reconcile --moved` when the root moved, and the conflict
 * surface `steward reconcile --claim` when the same id turned up in two places. Nothing is
 * written on that path: no event, no marker, no id.
 *
 * THESE REFUSALS ARE NOT A W3 FAILURE TABLE. The seven tables W3 froze cover the seven
 * surfaces the plan names, and register is not one of them; inventing an eighth table here
 * would fork a frozen artifact for one wave's convenience. The rows below are this verb's
 * own refusal contract, in the same SHAPE (a code, a STATUS-v1 status read from status.mjs,
 * and the sentence the operator actually reads) and rendered through the same
 * fillRowText() the tables use, so the two can never render differently.
 *
 * THE RESIDUAL, NAMED RATHER THAN HIDDEN. The marker read and the log append are not one
 * atomic act, so two processes registering the SAME root at the same instant can both pass
 * the check. The arbiter is the marker file itself: writeMarker refuses an existing marker,
 * so the loser gets REGISTER_MARKER_RACE with its id durable-but-unbound in the log and is
 * told which explicit route resolves it. Loud and repairable, rather than two ids silently
 * bound to one directory. W8 hardens the surrounding concurrency; this window is stated
 * here because a residual nobody wrote down is a residual nobody fixes.
 *
 * Stdlib only.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { appendEvents, indexPathsFrom } from '../append-log.mjs';
import {
  COMMIT_REASON,
  makeCommitIntent,
  nextSeqFor,
  pathEntryFor,
} from './commit-intent.mjs';
import { fillRowText } from './failure-tables.mjs';
import { mintProjectIdForRoot } from './identity.mjs';
import {
  MARKER_DIR,
  MARKER_FILE,
  MARKER_REFUSAL,
  markerPathFor,
  markerText,
  newMarker,
  readMarker,
  writeMarker,
} from './marker.mjs';
import {
  lastCommitIntentSeq,
  makeCommitIntentEvent,
  makeRegistrationEvent,
  materializeRegistry,
  readRegistry,
  resolveRoot,
} from './registry.mjs';
import { FRESHNESS, INTEGRITY, PRESENCE, assertStatusCode } from './status.mjs';
import { openablePath } from './inventory.mjs';

/** The verb's surface name, used where an outcome reports which verb produced it. */
export const REGISTER_SURFACE = 'register';

/** The verb's frozen contract version. */
export const REGISTER_VERSION = 'register-v1';

/** The marker's path relative to its root, POSIX - the path a commit-intent may carry. */
export const MARKER_ROOT_REL_PATH = `${MARKER_DIR}/${MARKER_FILE}`;

/** Registration receipt ids are prefixed so one can never be mistaken for a project_id. */
export const RECEIPT_ID_PREFIX = 'reg-';

/** Every named refusal this verb can return. */
export const REGISTER_REFUSAL = Object.freeze({
  ALREADY_MARKED: 'REGISTER_ALREADY_MARKED',
  ALREADY_REGISTERED: 'REGISTER_ALREADY_REGISTERED',
  MARKER_DAMAGED: 'REGISTER_MARKER_DAMAGED',
  MARKER_RACE: 'REGISTER_MARKER_RACE',
  MARKER_UNWRITABLE: 'REGISTER_MARKER_UNWRITABLE',
  ROOT_ABSENT: 'REGISTER_ROOT_ABSENT',
  ROOT_UNREACHABLE: 'REGISTER_ROOT_UNREACHABLE',
  ROOT_NOT_A_DIRECTORY: 'REGISTER_ROOT_NOT_A_DIRECTORY',
  INDEX_UNREADABLE: 'REGISTER_INDEX_UNREADABLE',
  EVENT_APPEND_FAILED: 'REGISTER_EVENT_APPEND_FAILED',
  INTENT_APPEND_FAILED: 'REGISTER_INTENT_APPEND_FAILED',
});

/** The success code, so a caller can switch on one vocabulary rather than on `ok`. */
export const REGISTER_OK = 'REGISTER_OK';

/**
 * The rows. `{placeholders}` are filled by the call site exactly as a W3 table row is; an
 * unfilled one is LEFT VISIBLE, because a sentence with a gap in it reads as if the missing
 * fact had been reported.
 */
export const REGISTER_ROWS = Object.freeze({
  [REGISTER_OK]: Object.freeze({
    code: REGISTER_OK,
    status: INTEGRITY.OK,
    text:
      'project {project_id} is registered at {root}: one NATIVE registration event at log '
      + 'seq {seq}, one steward-marker-v2 written into the root, and one commit-intent-v1 '
      + 'receipt at log seq {intent_seq}. The id was minted once and will never be minted again.',
  }),
  [REGISTER_REFUSAL.ALREADY_MARKED]: Object.freeze({
    code: REGISTER_REFUSAL.ALREADY_MARKED,
    status: INTEGRITY.IDENTITY_CONFLICT,
    text:
      '{root} already carries a steward-marker-v2 for project {project_id}, so registering it '
      + 'again would mint a second identity for one root. Nothing was written: no event, no '
      + 'marker, no id. If this root MOVED, run steward reconcile --moved {registered_path} '
      + '{root}; if the same project has appeared in two places, only the conflict surface '
      + 'resolves it - steward reconcile --claim {project_id} {root}.',
  }),
  [REGISTER_REFUSAL.ALREADY_REGISTERED]: Object.freeze({
    code: REGISTER_REFUSAL.ALREADY_REGISTERED,
    status: INTEGRITY.IDENTITY_CONFLICT,
    text:
      '{root} is already registered as project {project_id} in the log (seq {seq}), even though '
      + 'the root carries no marker. No second id was minted and no marker was written, because '
      + 'registering again would fork the history that id already owns. Restore the mirror with '
      + 'steward reconcile --moved {root} {root}, or claim it explicitly with steward reconcile '
      + '--claim {project_id} {root}.',
  }),
  [REGISTER_REFUSAL.MARKER_DAMAGED]: Object.freeze({
    code: REGISTER_REFUSAL.MARKER_DAMAGED,
    status: INTEGRITY.UNPARSEABLE,
    text:
      'the marker at {path} exists but could not be read ({reason}); register refuses rather '
      + 'than overwriting it, because that file is the only record of the identity of this '
      + 'root that survives losing the log. Repair or move the marker aside by hand, then '
      + 'register.',
  }),
  [REGISTER_REFUSAL.MARKER_RACE]: Object.freeze({
    code: REGISTER_REFUSAL.MARKER_RACE,
    status: INTEGRITY.IDENTITY_CONFLICT,
    text:
      '{root} gained a marker between the check this registration made and the write it '
      + 'attempted, so another '
      + 'writer registered it first. Project {project_id} is durable in the log at seq {seq} and '
      + 'is bound to nothing; the marker on disk was NOT overwritten. Resolve it explicitly with '
      + 'steward reconcile --claim {project_id} {root}.',
  }),
  [REGISTER_REFUSAL.MARKER_UNWRITABLE]: Object.freeze({
    code: REGISTER_REFUSAL.MARKER_UNWRITABLE,
    status: FRESHNESS.STALE,
    text:
      'project {project_id} is registered in the log at seq {seq}, but its marker could not be '
      + 'written to {path} ({errno}). The identity stands and is not minted again; until the '
      + 'marker exists, this root cannot be recovered git-free if the log is lost. Fix the write '
      + 'failure, then rebind the mirror with steward reconcile --moved {root} {root}.',
  }),
  [REGISTER_REFUSAL.ROOT_ABSENT]: Object.freeze({
    code: REGISTER_REFUSAL.ROOT_ABSENT,
    status: PRESENCE.ABSENT,
    text:
      'there is no directory at {root}; the steward looked and it is not there, which is not the '
      + 'same as a root it could not reach. Nothing was registered and no id was minted.',
  }),
  [REGISTER_REFUSAL.ROOT_UNREACHABLE]: Object.freeze({
    code: REGISTER_REFUSAL.ROOT_UNREACHABLE,
    status: PRESENCE.UNREACHABLE,
    text:
      '{root} could not be read ({errno}); the steward could not look, which is deliberately a '
      + 'different report from a root that is gone. Nothing was registered and no id was minted.',
  }),
  [REGISTER_REFUSAL.ROOT_NOT_A_DIRECTORY]: Object.freeze({
    code: REGISTER_REFUSAL.ROOT_NOT_A_DIRECTORY,
    status: PRESENCE.UNREACHABLE,
    text:
      '{root} exists but is not a directory, so it cannot hold a marker or the files of a '
      + 'project. Nothing was registered and no id was minted.',
  }),
  [REGISTER_REFUSAL.INDEX_UNREADABLE]: Object.freeze({
    code: REGISTER_REFUSAL.INDEX_UNREADABLE,
    status: PRESENCE.UNREACHABLE,
    text:
      'the portfolio index could not be read to a known state ({reason}), so this root could not '
      + 'be checked against existing membership. Registering anyway could mint a second id for a '
      + 'project that already has one, so it was refused instead.',
  }),
  [REGISTER_REFUSAL.EVENT_APPEND_FAILED]: Object.freeze({
    code: REGISTER_REFUSAL.EVENT_APPEND_FAILED,
    status: FRESHNESS.UNKNOWN,
    text:
      'the registration event could not be made durable in the log ({reason}); no id was '
      + 'recorded, no marker was written, and {root} is NOT registered. Nothing was reported as '
      + 'succeeding, because the id would exist nowhere the next start could find it.',
  }),
  [REGISTER_REFUSAL.INTENT_APPEND_FAILED]: Object.freeze({
    code: REGISTER_REFUSAL.INTENT_APPEND_FAILED,
    status: FRESHNESS.STALE,
    text:
      'project {project_id} is registered at seq {seq} and its marker is written, but the '
      + 'commit-intent receipt could not be appended ({reason}). The registration stands; until '
      + 'an intent is recorded, nothing has asked for these bytes to be committed, so local disk '
      + 'is the only copy of the identity of this root.',
  }),
});

/** @type {ReadonlyArray<string>} every code this verb can return, for a test to enumerate. */
export const REGISTER_CODES = Object.freeze(Object.keys(REGISTER_ROWS));

/**
 * Build this verb's outcome for one of its frozen rows.
 *
 * The status and the sentence are READ from the row rather than typed at the call site, for
 * the same reason the W3 tables work that way: two copies of a sentence are two sentences,
 * and they diverge on the first edit.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function registerOutcome(code, params = {}, extra = {}) {
  const row = REGISTER_ROWS[code];
  if (row === undefined) throw new Error(`register: ${code} is not a frozen register row`);
  return Object.freeze({
    ok: code === REGISTER_OK,
    code,
    surface: REGISTER_SURFACE,
    status: assertStatusCode(row.status, `register row ${code}`),
    text: fillRowText(row.text, params),
    detail: Object.freeze({ ...params }),
    ...extra,
  });
}

/** @param {string} code @returns {string} the row's raw text, placeholders unfilled */
export function registerRowText(code) {
  const row = REGISTER_ROWS[code];
  if (row === undefined) throw new Error(`register: ${code} is not a frozen register row`);
  return row.text;
}

// -- the root ------------------------------------------------------------------

/**
 * Classify the directory being registered. ABSENT and UNREACHABLE stay distinct here for
 * the same reason they are distinct everywhere else: "you typed a path that does not exist"
 * and "your network share is down" call for different actions from the operator.
 *
 * @param {string} rootAbs @param {{fs?: object}} [opts]
 * @returns {Readonly<object>|null} a refusal, or null when the root is usable
 */
export function classifyRegisterRoot(rootAbs, opts = {}) {
  const fsx = opts.fs ?? fs;
  let stat;
  try {
    stat = fsx.statSync(openablePath(rootAbs));
  } catch (err) {
    const errno = err && err.code ? err.code : '';
    if (errno === 'ENOENT') {
      return registerOutcome(REGISTER_REFUSAL.ROOT_ABSENT, { root: rootAbs });
    }
    return registerOutcome(REGISTER_REFUSAL.ROOT_UNREACHABLE, { root: rootAbs, errno });
  }
  if (!stat || typeof stat.isDirectory !== 'function' || !stat.isDirectory()) {
    return registerOutcome(REGISTER_REFUSAL.ROOT_NOT_A_DIRECTORY, { root: rootAbs });
  }
  return null;
}

/**
 * Mint a registration receipt id.
 *
 * Deliberately NOT a project_id shape. The two ids travel together in the marker and in the
 * registration event, and a reader that mistook one for the other would be reading an
 * identity claim off a receipt number.
 *
 * @param {{randomUUID?: () => string}} [opts] @returns {string}
 */
export function mintRegistrationReceiptId(opts = {}) {
  const gen = typeof opts.randomUUID === 'function' ? opts.randomUUID : crypto.randomUUID;
  return `${RECEIPT_ID_PREFIX}${String(gen())}`;
}

// -- the verb ------------------------------------------------------------------

/**
 * `steward register <root>`.
 *
 * @param {string} rootPath the directory to register
 * @param {{home?: string, paths?: object, env?: object, now?: number|Date,
 *          randomUUID?: () => string, fs?: object, boundMs?: number, staleMs?: number,
 *          lockOpts?: object}} [opts]
 * @returns {Readonly<object>} an outcome carrying a named code and its user-visible text
 */
export function registerRoot(rootPath, opts = {}) {
  const root = path.resolve(String(rootPath));
  const paths = indexPathsFrom(opts);
  const at = new Date(opts.now ?? Date.now()).toISOString().replace(/\.\d{3}Z$/, 'Z');

  const rootProblem = classifyRegisterRoot(root, opts);
  if (rootProblem !== null) return rootProblem;

  // 1. The marker on the root is the first authority consulted, because it is the claim an
  //    operator can see with their own eyes, and refusing on it costs nothing.
  const existing = readMarker(root, opts);
  if (existing.ok) {
    return registerOutcome(REGISTER_REFUSAL.ALREADY_MARKED, {
      root,
      path: existing.path,
      project_id: existing.marker.project_id,
      registered_path: existing.marker.registered_path,
    }, { marker: existing.marker, minted: false });
  }
  if (existing.code !== MARKER_REFUSAL.ABSENT) {
    return registerOutcome(REGISTER_REFUSAL.MARKER_DAMAGED, {
      root,
      path: existing.path,
      reason: existing.problems[0] ? existing.problems[0].detail : existing.code,
    }, { marker_status: existing.status, minted: false });
  }

  // 2. Then the log, which is the authority the marker mirrors. A root registered here with
  //    no marker on disk is a real state (a crash between step 3 and step 4 of a previous
  //    run, or a hand-deleted marker) and it must NOT mint a second id.
  const read = readRegistry({ ...opts, home: paths.home });
  if (!read.ok) {
    const absent = read.outcome && read.outcome.status === PRESENCE.ABSENT;
    if (!absent) {
      return registerOutcome(REGISTER_REFUSAL.INDEX_UNREADABLE, {
        root,
        reason: read.outcome ? read.outcome.text : '',
      }, { index_outcome: read.outcome, minted: false });
    }
  }
  const view = read.ok ? read.view : materializeRegistry([]);

  const bound = resolveRoot(view, root);
  if (bound !== null) {
    return registerOutcome(REGISTER_REFUSAL.ALREADY_REGISTERED, {
      root,
      project_id: bound.project_id,
      seq: bound.registered_seq,
    }, { project: bound, minted: false });
  }

  // 3. Mint. Once, here, and nowhere else in the system.
  const projectId = mintProjectIdForRoot(root, { ...opts, existing_id: null });
  const receiptId = mintRegistrationReceiptId(opts);
  const marker = newMarker({
    project_id: projectId,
    registered_at: at,
    registered_path: root,
    registration_receipt_id: receiptId,
  });
  // The bytes are composed BEFORE anything is written, so the log can record the hash of
  // what the mirror must contain rather than of whatever it turned out to contain.
  const markerBytes = markerText(marker);
  const markerEntry = pathEntryFor(MARKER_ROOT_REL_PATH, markerBytes);

  // 4. Log first. Nothing below this line may report success unless this append is durable.
  const registration = makeRegistrationEvent({
    project_id: projectId,
    root,
    registered_at: at,
    registration_receipt_id: receiptId,
    marker_sha256: markerEntry.sha256,
  });
  const appended = appendEvents([registration], {
    ...opts,
    home: paths.home,
    now: opts.now,
  });
  if (appended.ok !== true) {
    return registerOutcome(REGISTER_REFUSAL.EVENT_APPEND_FAILED, {
      root,
      reason: appended.text ? appended.text : appended.code,
    }, { index_outcome: appended, minted: false });
  }
  const registrationSeq = appended.seq;

  // 5. The mirror.
  let written;
  try {
    written = writeMarker(root, marker);
  } catch (err) {
    if (err && err.code === MARKER_REFUSAL.ALREADY_PRESENT) {
      return registerOutcome(REGISTER_REFUSAL.MARKER_RACE, {
        root,
        path: markerPathFor(root),
        project_id: projectId,
        seq: registrationSeq,
      }, { project_id: projectId, registration_seq: registrationSeq, minted: true });
    }
    return registerOutcome(REGISTER_REFUSAL.MARKER_UNWRITABLE, {
      root,
      path: markerPathFor(root),
      project_id: projectId,
      seq: registrationSeq,
      errno: err && err.code ? err.code : String(err && err.message ? err.message : err),
    }, { project_id: projectId, registration_seq: registrationSeq, minted: true });
  }

  // 6. The receipt Anchor honors, over the bytes that are now on disk. The per-project
  //    sequence comes from the view rather than from a counter of this module's own: a
  //    counter would be a second store of exactly the fact the log already carries.
  const intent = makeCommitIntent({
    project_id: projectId,
    seq: nextSeqFor(lastCommitIntentSeq(view, projectId)),
    reason: COMMIT_REASON.REGISTER,
    paths: [markerEntry],
    written_at: at,
  });
  const intentAppended = appendEvents([makeCommitIntentEvent(intent)], {
    ...opts,
    home: paths.home,
    now: opts.now,
  });
  if (intentAppended.ok !== true) {
    return registerOutcome(REGISTER_REFUSAL.INTENT_APPEND_FAILED, {
      root,
      project_id: projectId,
      seq: registrationSeq,
      reason: intentAppended.text ? intentAppended.text : intentAppended.code,
    }, {
      project_id: projectId,
      registration_seq: registrationSeq,
      marker: Object.freeze({ ...written }),
      index_outcome: intentAppended,
      minted: true,
    });
  }

  return registerOutcome(REGISTER_OK, {
    root,
    project_id: projectId,
    seq: registrationSeq,
    intent_seq: intentAppended.seq,
  }, {
    project_id: projectId,
    root,
    registered_at: at,
    registration_receipt_id: receiptId,
    registration_seq: registrationSeq,
    registration_event: registration,
    marker: Object.freeze({ ...written, root_rel_path: MARKER_ROOT_REL_PATH }),
    intent,
    intent_seq: intentAppended.seq,
    head_seq: intentAppended.head_seq,
    home: paths.home,
    minted: true,
  });
}

/** The verb name a CLI dispatches on, so no surface spells it for itself. */
export const REGISTER_VERB = 'register';

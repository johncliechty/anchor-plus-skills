/**
 * W17 - recover-log: the bounded disaster path, with an honest loss report.
 *
 * WHY THIS VERB IS NOT `rebuild`. The rebuild equation (W10) says the snapshot is DERIVED and
 * deletable: throw it away, run rebuild, get the same bytes back. The live log is NOT in that
 * deletable set, and it never was - membership events (W7), acknowledgements (W15) and the
 * record that a copy left the box (W16) exist nowhere else. So losing the log is not a rebuild
 * with extra steps. It is a RECOVERY, it is bounded, and the bound is the whole subject of this
 * file: what comes back, what does not, and - the part every honest disaster tool gets wrong -
 * what cannot even be counted.
 *
 * THE TWO BYTE SOURCES, AND NOTHING ELSE. This verb reads plain working-tree bytes from exactly
 * two places:
 *
 *   1. marker-v2 files under operator-supplied SEARCH ROOTS. `<root>/.steward/project.json` is
 *      the one artifact that survives a lost log while still naming a project, which is
 *      precisely why marker.mjs froze its field set in W4 before anything wrote one.
 *
 *   2. the operator-RESTORED COPY of the index home - a backup, a bundle unpacked by hand, a
 *      file server's shadow copy. Whatever it is, by the time this verb sees it, it is a
 *      directory of ordinary files.
 *
 * There is no third source. In particular this engine does not consult the durability layer:
 * the whole Anchor contract (W15) is that the engine asks and something else honours, and a
 * recovery path that shelled out to read history would make the engine responsible for a tool
 * it cannot version - on the one day the machine is already broken. The rule is enforced rather
 * than promised: `recoverInputFs` refuses, at the call site, any byte read outside the declared
 * input set, and test/w5x-recover-log.test.mjs re-proves it from the outside.
 *
 * WHERE EACH RECONSTRUCTED FIELD COMES FROM (the W4 field-source table, as code - see
 * FIELD_SOURCE below):
 *
 *   project_id / registered_at / registered_path / registration_receipt_id  <- marker bytes
 *   current path                                                           <- the directory the
 *                                                                             marker was FOUND in
 *   ack watermark                                                          <- highest acknowledged
 *                                                                             commit-intent in the
 *                                                                             restored copy
 *   DERIVED rows                                                           <- the restored copy,
 *                                                                             cut at that watermark
 *
 * WHY MEMBERSHIP COMES FROM THE MARKERS AND NOT FROM THE COPY. The copy is old by definition -
 * it is a backup - and a project registered after it was taken exists in no restored event at
 * all. Its marker, however, is lying in its root right now. Reading membership from the markers
 * is therefore not a stylistic choice: it is the only reading under which a project registered
 * yesterday still exists tomorrow. The copy's own registration events are used for exactly the
 * projects the markers could NOT answer for - the ones whose roots are gone - because W11's
 * floor is that absence never removes a row, and dropping them would shrink the portfolio at
 * the worst possible moment.
 *
 * WHY THE CUT IS THE ACK WATERMARK. Below the watermark, something outside this machine
 * acknowledged these exact bytes, so the restored copy can be checked rather than believed.
 * Above it, the copy is simply the last thing somebody happened to snapshot: it may hold some,
 * all or none of what the live log held, and there is no artifact left that could say which. So
 * everything above the watermark is reported as the LOST window rather than carried in as
 * though it were the truth. That is the bound, and it is stated on every single run.
 *
 * THE PART THAT CANNOT BE FIXED, AND IS THEREFORE SAID OUT LOUD. If a root is ALSO gone, its
 * post-watermark content evaporated: the log that recorded it is lost and the files it
 * described are lost, so no byte source remains that could enumerate the items - not even to
 * count them. This receipt prints `null` there with UNKNOWABLE beside it, never a zero. A zero
 * would be a lie shaped exactly like good news. That residue is NS-Q2 in the plan; it is
 * surfaced to the user rather than argued away here.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  ORDERING_FIELD,
  WALL_CLOCK_FIELD,
  appendLineAt,
  ensureIndexHome,
  indexPathsFrom,
  logEventLine,
  makeLogEvent,
  parseLogRecords,
  readLogBytes,
  replayEvents,
  scanLogBytes,
  withPortfolioLock,
} from '../append-log.mjs';
import { commitAcksIn, intentLedger } from './anchor-contract.mjs';
import { CAPS } from './caps.mjs';
import {
  COMMIT_REASON,
  makeCommitIntent,
  nextSeqFor,
  pathEntryFor,
} from './commit-intent.mjs';
import { isDerivedEvent } from './derive.mjs';
import { INDEX_FILES, indexPathsFor, isInsideHome } from './home.mjs';
import { DEFAULT_WALK_CAP, HAZARD, walkRoot } from './inventory.mjs';
import { MARKER_DIR, MARKER_FILE, readMarker } from './marker.mjs';
import { GUARDED_READ_CALLS, rebuildIndex } from './rebuild.mjs';
import { markerCandidateRootFor } from './reconcile.mjs';
import { MARKER_ROOT_REL_PATH } from './register.mjs';
import {
  EVENT_TYPE_FIELD,
  NATIVE_EVENT,
  RECONCILE_MODE,
  makeCommitIntentEvent,
  makeReconcileEvent,
  makeRegistrationEvent,
  materializeRegistry,
} from './registry.mjs';
import { classifyRootStatus } from './root-status.mjs';
import { FRESHNESS, INTEGRITY, PRESENCE, assertStatusCode } from './status.mjs';

/** This module's frozen version. Changing what it reads or how it cuts means recover-log-v2. */
export const RECOVER_VERSION = 'recover-log-v1';

/** The input schema the plan names. */
export const RECOVER_INPUT_SCHEMA = 'recover-input-v1';

/** The receipt this verb hands its caller. */
export const RECOVER_RECEIPT_SCHEMA = 'recovery-receipt-v1';

/** The verb's name, as an operator types it. Spelled once; every surface reads it. */
export const RECOVER_VERB = 'recover-log';

/** The verb this one chains when it is done. */
export const CHAINED_VERB = 'rebuild';

/** One day in milliseconds - the unit the LOST window is reported in. */
export const MS_PER_DAY = 86_400_000;

/**
 * The strength this verb recovers to, as a name a caller can branch on.
 *
 * It is the SAME phrase anchor-contract.mjs uses for its watermark basis, because "how far did
 * durability get" and "how far can recovery reach" are one question asked from two sides.
 */
export const RECOVER_STRENGTH = 'LAST_ACKNOWLEDGED_COMMIT';

/**
 * The bound, in the operator's words. Carried on EVERY outcome this module returns - not only
 * the successful ones - because a recovery tool that mentions its limits when it feels like it
 * is a recovery tool whose limits nobody reads.
 */
export const RECOVERY_STRENGTH_SENTENCE =
  'This recovery is only as strong as the last acknowledgement. Everything at or before the '
  + 'last acknowledged commit-intent is here and can be checked; anything written after it is '
  + 'outside what these bytes can prove. Where the project root is still on disk, the rebuild '
  + 'that follows re-derives whatever its own files still hold. Where the root is gone too, '
  + 'that content went with the log and cannot even be counted.';

/**
 * The CLOSED input set, as data rather than as a call graph. Adding a source is a visible edit
 * here, which is the point: the claim "this verb reads only plain working-tree bytes" is one
 * anybody can check by reading eight lines instead of a module.
 */
export const BYTE_SOURCE = Object.freeze({
  MARKER: 'MARKER_V2_UNDER_SEARCH_ROOT',
  RESTORED_COPY: 'OPERATOR_RESTORED_INDEX_HOME_COPY',
  LIVE_HOME: 'THE_INDEX_HOME_BEING_RECOVERED_INTO',
});

/** @see BYTE_SOURCE */
export const RECOVER_INPUT = Object.freeze([
  Object.freeze({
    source: BYTE_SOURCE.MARKER,
    what: `${MARKER_DIR}/${MARKER_FILE} files under the operator-supplied search roots`,
    why: 'the only artifact that survives a lost log while still naming a project',
  }),
  Object.freeze({
    source: BYTE_SOURCE.RESTORED_COPY,
    what: `a directory holding a copy of ${INDEX_FILES.LOG}`,
    why: 'the only place an acknowledgement or a DERIVED row can be read from once the live log is gone',
  }),
  Object.freeze({
    source: BYTE_SOURCE.LIVE_HOME,
    what: 'the index home this recovery writes into',
    why: 'read only to prove it is empty; a live log here means this is not the disaster path',
  }),
]);

/**
 * What is deliberately NOT an input. Named so a reader does not have to infer the absence of a
 * thing from its absence.
 */
export const RECOVER_EXCLUDED_INPUT = Object.freeze([
  'the durability layer\'s history (this engine never invokes it - W15\'s line, and this is the '
  + 'day it matters most)',
  'the live log (it is what was lost; that is the premise, not an oversight)',
  'the snapshot inside the restored copy (it is DERIVED; the chained rebuild recomputes it)',
]);

/**
 * The field-source table from W4, in code. Every field this verb reconstructs names the byte
 * source it comes from, and there is no entry whose source is a tool.
 */
export const FIELD_SOURCE = Object.freeze({
  project_id: BYTE_SOURCE.MARKER,
  registered_at: BYTE_SOURCE.MARKER,
  registered_path: BYTE_SOURCE.MARKER,
  registration_receipt_id: BYTE_SOURCE.MARKER,
  current_path: 'THE_DIRECTORY_THE_MARKER_WAS_FOUND_IN',
  ack_watermark: BYTE_SOURCE.RESTORED_COPY,
  derived_rows: BYTE_SOURCE.RESTORED_COPY,
});

/** How an item count can be reported. `null` is never a zero here. */
export const COUNT_STATUS = Object.freeze({
  COUNTED: 'COUNTED',
  UNKNOWABLE: 'UNKNOWABLE',
});

/** The outcomes this verb reports. Every one is a named row, never a thrown surprise. */
export const RECOVER_CODE = Object.freeze({
  OK: 'RECOVER_LOG_OK',
  INPUT_MALFORMED: 'RECOVER_LOG_INPUT_MALFORMED',
  NO_SEARCH_ROOTS: 'RECOVER_LOG_NO_SEARCH_ROOTS',
  RESTORED_COPY_MISSING: 'RECOVER_LOG_RESTORED_COPY_MISSING',
  RESTORED_COPY_ABSENT: 'RECOVER_LOG_RESTORED_COPY_ABSENT',
  RESTORED_COPY_EMPTY: 'RECOVER_LOG_RESTORED_COPY_EMPTY',
  RESTORED_COPY_UNPARSEABLE: 'RECOVER_LOG_RESTORED_COPY_UNPARSEABLE',
  LIVE_LOG_PRESENT: 'RECOVER_LOG_LIVE_LOG_PRESENT',
  SEARCH_ROOT_ABSENT: 'RECOVER_LOG_SEARCH_ROOT_ABSENT',
  SEARCH_ROOT_UNREACHABLE: 'RECOVER_LOG_SEARCH_ROOT_UNREACHABLE',
  SEARCH_BOUND_EXCEEDED: 'RECOVER_LOG_SEARCH_BOUND_EXCEEDED',
  MARKER_DAMAGED: 'RECOVER_LOG_MARKER_DAMAGED',
  IDENTITY_CONFLICT: 'RECOVER_LOG_IDENTITY_CONFLICT',
  NOTHING_TO_RECOVER: 'RECOVER_LOG_NOTHING_TO_RECOVER',
  WRITE_FAILED: 'RECOVER_LOG_WRITE_FAILED',
  REBUILD_FAILED: 'RECOVER_LOG_REBUILD_FAILED',
  LOST_WINDOW_RECOVERABLE: 'RECOVER_LOG_LOST_WINDOW_RECOVERABLE',
  LOST_WINDOW_EVAPORATED: 'RECOVER_LOG_LOST_WINDOW_EVAPORATED',
});

/**
 * The user-visible sentence per row. Read, never composed at the call site - the same reason
 * bundle.mjs reads its own: a refusal worded where it is raised says something slightly
 * different on each surface, and the operator is reading it on the worst day of the month.
 */
export const RECOVER_ROWS = Object.freeze({
  [RECOVER_CODE.OK]: Object.freeze({
    status: INTEGRITY.OK,
    text:
      'Recovered {projects} project(s) into a new log at {log}: {markers} reconstructed from '
      + 'marker files under the search roots and {absent} carried from the restored copy because '
      + 'no marker could be found for them. {events} event(s) were written, {derived} of them '
      + 'DERIVED rows carried at last-acknowledged-commit strength.',
  }),
  [RECOVER_CODE.INPUT_MALFORMED]: Object.freeze({
    status: INTEGRITY.UNPARSEABLE,
    text:
      `the ${RECOVER_INPUT_SCHEMA} handed to ${RECOVER_VERB} could not be read ({reason}). `
      + 'Nothing was searched and nothing was written.',
  }),
  [RECOVER_CODE.NO_SEARCH_ROOTS]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      `${RECOVER_VERB} needs at least one search root to look for marker files under. No default `
      + 'is composed: a recovery that searched wherever it liked would bind this portfolio to '
      + 'whatever copy of a project root happened to be on the disk.',
  }),
  [RECOVER_CODE.RESTORED_COPY_MISSING]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      `${RECOVER_VERB} needs the path of the restored copy of the index home. Restore it first `
      + 'and then name it: recovering without it would reconstruct membership and silently '
      + 'report every project as having no history, which reads exactly like a portfolio that '
      + 'never wrote anything.',
  }),
  [RECOVER_CODE.RESTORED_COPY_ABSENT]: Object.freeze({
    status: PRESENCE.ABSENT,
    text:
      'there is no directory at {path}, so the restored copy named on the command line is not '
      + 'the one on this disk. Nothing was written. Check the path, or restore the copy there '
      + 'first - the runbook is planning/steward-tracking-2026-07/stage2/recover-log-runbook.md.',
  }),
  [RECOVER_CODE.RESTORED_COPY_EMPTY]: Object.freeze({
    status: INTEGRITY.EMPTY,
    text:
      `the restored copy at {path} carries no {file}, so it can supply neither an acknowledged `
      + 'watermark nor a single DERIVED row. Membership is still reconstructed from the markers, '
      + 'and EVERY project\'s content is inside the lost window rather than in the recovered log.',
  }),
  [RECOVER_CODE.RESTORED_COPY_UNPARSEABLE]: Object.freeze({
    status: INTEGRITY.UNPARSEABLE,
    text:
      'the log inside the restored copy at {path} has {count} line(s) this engine cannot parse '
      + '(first: line {line}, {reason}). They are counted and passed over rather than guessed '
      + 'at; everything they held is reported inside the lost window.',
  }),
  [RECOVER_CODE.LIVE_LOG_PRESENT]: Object.freeze({
    status: INTEGRITY.TAMPERED,
    text:
      'a live log is already present at {log} ({size} bytes, head sequence {head_seq}). Not one '
      + `byte was written. ${RECOVER_VERB} REPLACES a log that was lost; running it over one `
      + 'that is still here would fabricate a second history beside the real one. If this log is '
      + 'damaged rather than lost, move it aside by hand - do not delete it - and run this verb '
      + 'again against an empty index home.',
  }),
  [RECOVER_CODE.SEARCH_ROOT_ABSENT]: Object.freeze({
    status: PRESENCE.ABSENT,
    text:
      'the search root {path} does not exist, so nothing under it was looked at. Any project '
      + 'that lived there is reported through the restored copy or not at all.',
  }),
  [RECOVER_CODE.SEARCH_ROOT_UNREACHABLE]: Object.freeze({
    status: PRESENCE.UNREACHABLE,
    text:
      'the search root {path} could not be read ({errno}). This is not the same as it being '
      + 'empty: markers may be sitting under it right now, and this recovery did not see them.',
  }),
  [RECOVER_CODE.SEARCH_BOUND_EXCEEDED]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      'the walk of {path} stopped at its bound of {cap} entries, so the marker list under that '
      + 'root is a floor rather than a total. Narrow the search root and run again before '
      + 'treating the recovered portfolio as complete.',
  }),
  [RECOVER_CODE.MARKER_DAMAGED]: Object.freeze({
    status: INTEGRITY.UNPARSEABLE,
    text:
      'the marker at {path} could not be read as an identity claim ({reason}). It is reported '
      + 'rather than defaulted - a defaulted identity field is a forged claim about which '
      + 'project these bytes belong to - so this root is not bound by this recovery.',
  }),
  [RECOVER_CODE.IDENTITY_CONFLICT]: Object.freeze({
    status: INTEGRITY.IDENTITY_CONFLICT,
    text:
      'project {project_id} carries a marker at {path} AND at {other_path}. Neither is bound by '
      + 'this recovery and the project is counted exactly once. Resolve it after the recovery '
      + 'with steward reconcile --claim, which records both paths.',
  }),
  [RECOVER_CODE.NOTHING_TO_RECOVER]: Object.freeze({
    status: INTEGRITY.EMPTY,
    text:
      'no marker was found under any search root and the restored copy names no project either, '
      + 'so there is no membership to reconstruct. Nothing was written. This is EMPTY rather '
      + 'than a failure: it is what a recovery of a portfolio that never registered anything '
      + 'looks like, and it is reported as such rather than as a successful recovery of nothing.',
  }),
  [RECOVER_CODE.WRITE_FAILED]: Object.freeze({
    status: INTEGRITY.TORN,
    text:
      'the recovery stopped after writing {written} of {total} event(s) ({reason}). The events '
      + 'already written are durable and in order, but the log is short of the recovery and must '
      + 'be moved aside by hand before another attempt.',
  }),
  [RECOVER_CODE.REBUILD_FAILED]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      'the log was recovered but the {verb} that follows it did not complete ({reason}). The '
      + 'recovered log is intact; run that verb again once the reason is addressed.',
  }),
  [RECOVER_CODE.LOST_WINDOW_RECOVERABLE]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      '{root}: {ack_clause} The window from {from} to {to} - {days} day(s) - is not in the '
      + 'recovered log. This root is still on disk, so the rebuild that follows re-derives what '
      + 'its own files hold; how many items the lost log recorded in that window is not a number '
      + 'these bytes can produce, so it is reported as {count_status} rather than as a count.',
  }),
  [RECOVER_CODE.LOST_WINDOW_EVAPORATED]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      '{root}: {ack_clause} The window from {from} to {to} - {days} day(s) - is not in the '
      + 'recovered log, and this root is {presence} as well. Content written on it inside that '
      + 'window evaporated with the log: no byte source is left that could enumerate it, so the '
      + 'item count is {count_status} and is printed as nothing rather than as zero.',
  }),
});

/** The two ack clauses the loss rows are filled with. Frozen, so neither drifts. */
export const ACK_CLAUSE = Object.freeze({
  ACKED:
    'acknowledged through per-project commit-intent {ack_seq} at {acked_at}, and recovered to '
    + 'exactly there.',
  NEVER:
    'this root was never acknowledged, so the recovery reaches no further than the '
    + 'moment it was registered.',
});

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) => (
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole
  ));
}

/**
 * One outcome, worded from the frozen row - and carrying the strength bound.
 *
 * The bound rides on EVERY outcome, success and refusal alike. That is the "states the recovery
 * strength on every run" clause of the done-when, and it is a field rather than a habit so no
 * surface can render a recovery without it.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function recoverOutcome(code, params = {}, extra = {}) {
  const row = RECOVER_ROWS[code];
  if (row === undefined) throw new Error(`${RECOVER_VERB}: ${code} is not a frozen row`);
  return Object.freeze({
    ok: code === RECOVER_CODE.OK,
    code,
    verb: RECOVER_VERB,
    status: assertStatusCode(row.status, `${RECOVER_VERB} row ${code}`),
    text: `${fill(row.text, params)} ${RECOVERY_STRENGTH_SENTENCE}`,
    strength: RECOVER_STRENGTH,
    strength_text: RECOVERY_STRENGTH_SENTENCE,
    version: RECOVER_VERSION,
    detail: Object.freeze({ ...params }),
    ...extra,
  });
}

// -- the input schema --------------------------------------------------------------

/**
 * Validate a recover-input-v1.
 *
 * It is a schema rather than a pair of arguments because the two inputs are the whole safety
 * story of this verb: a caller that can pass them positionally can pass them the wrong way
 * round, and "the search root is the restored copy" is a mistake that ends with a recovery
 * reading nothing and reporting success.
 *
 * @param {unknown} value
 * @returns {Readonly<{ok: boolean, input: object|null, code: string|null, problems: ReadonlyArray<string>}>}
 */
export function validateRecoverInput(value) {
  const problems = [];
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return Object.freeze({
      ok: false,
      input: null,
      code: RECOVER_CODE.INPUT_MALFORMED,
      problems: Object.freeze([`a ${RECOVER_INPUT_SCHEMA} is a JSON object`]),
    });
  }
  const record = /** @type {Record<string, unknown>} */ (value);

  if (record.schema !== undefined && record.schema !== RECOVER_INPUT_SCHEMA) {
    problems.push(`expected schema ${RECOVER_INPUT_SCHEMA}, got ${JSON.stringify(record.schema)}`);
  }

  const rawRoots = record.search_roots === undefined ? [] : record.search_roots;
  const list = Array.isArray(rawRoots) ? rawRoots : [rawRoots];
  const roots = [];
  for (const entry of list) {
    if (typeof entry !== 'string' || entry.trim() === '') {
      problems.push(`search_roots carries ${JSON.stringify(entry)}, which is not a path`);
      continue;
    }
    roots.push(path.resolve(entry));
  }

  const copy = record.restored_copy;
  if (copy !== undefined && copy !== null && (typeof copy !== 'string' || copy.trim() === '')) {
    problems.push(`restored_copy is ${JSON.stringify(copy)}, which is not a path`);
  }

  if (problems.length > 0) {
    return Object.freeze({
      ok: false,
      input: null,
      code: RECOVER_CODE.INPUT_MALFORMED,
      problems: Object.freeze(problems),
    });
  }

  if (roots.length === 0) {
    return Object.freeze({
      ok: false,
      input: null,
      code: RECOVER_CODE.NO_SEARCH_ROOTS,
      problems: Object.freeze(['no search root was supplied']),
    });
  }
  if (copy === undefined || copy === null) {
    return Object.freeze({
      ok: false,
      input: null,
      code: RECOVER_CODE.RESTORED_COPY_MISSING,
      problems: Object.freeze(['no restored copy of the index home was supplied']),
    });
  }

  // Deduplicated and sorted: two spellings of one search root would walk it twice and report
  // every marker under it as an identity conflict with itself.
  const unique = [...new Set(roots.map((r) => path.resolve(r)))].sort();

  return Object.freeze({
    ok: true,
    code: null,
    problems: Object.freeze([]),
    input: Object.freeze({
      schema: RECOVER_INPUT_SCHEMA,
      search_roots: Object.freeze(unique),
      restored_copy: path.resolve(String(copy)),
    }),
  });
}

// -- the input-only filesystem facade ----------------------------------------------

/** The refusal raised when a read leaves the declared input set. */
export const RECOVER_REFUSAL = Object.freeze({
  OUT_OF_INPUT_SET: 'RECOVER_LOG_OUT_OF_INPUT_SET',
});

/** A refusal that names the rule it enforces, so a caller branches on the code. */
export class RecoverRefusal extends Error {
  /** @param {string} code @param {string} detail */
  constructor(code, detail) {
    super(`${code}: ${detail}`);
    this.name = 'RecoverRefusal';
    this.code = code;
    this.detail = detail;
  }
}

/**
 * An `fs` facade that can read the declared input set and NOTHING else, and journals what it
 * read.
 *
 * This is the mechanism behind "reads ONLY plain working-tree bytes from two sources". Stated
 * in a comment it would be true until the first convenient `readFileSync`; stated as a facade,
 * the convenient read throws at the call site with the rule in the message - which is exactly
 * how rebuild.mjs keeps the snapshot out of its own input set.
 *
 * @param {object|undefined} base the fs to delegate to
 * @param {{allowed: ReadonlyArray<string>}} scope the directories reads may come from
 * @param {{reads: Array<object>, refused: Array<object>, total: number}} journal
 * @returns {object}
 */
export function recoverInputFs(base, scope, journal) {
  const allowed = (scope.allowed ?? []).map((dir) => path.resolve(String(dir)));
  const facade = { ...(base ?? fs) };

  const note = (call, target) => {
    journal.total += 1;
    const bare = String(target).replace(/^\\\\\?\\/, '');
    const inside = allowed.some((dir) => isInsideHome(dir, bare));
    const entry = Object.freeze({ call, path: bare, allowed: inside });
    if (!inside) {
      journal.refused.push(entry);
      throw new RecoverRefusal(
        RECOVER_REFUSAL.OUT_OF_INPUT_SET,
        `${call}() was asked to read ${bare}, which is outside this recovery's input set `
        + `(${allowed.join(', ')}). ${RECOVER_VERB} reads marker files under the search roots and `
        + 'the operator-restored copy of the index home, and nothing else - a recovery that read '
        + 'a fourth thing would be a recovery nobody could reproduce from what they were told.',
      );
    }
    journal.reads.push(entry);
  };

  for (const call of GUARDED_READ_CALLS) {
    const original = facade[call];
    if (typeof original !== 'function') continue;
    facade[call] = (target, ...rest) => {
      note(call, target);
      return original(target, ...rest);
    };
  }
  return facade;
}

/** @returns {{reads: Array<object>, refused: Array<object>, total: number}} a fresh journal */
export function newRecoverJournal() {
  return { reads: [], refused: [], total: 0 };
}

// -- source 1: the markers ---------------------------------------------------------

/**
 * Find every marker-v2 under the operator's search roots.
 *
 * The walk is the W2 hazard-safe one, so a junction cycle cannot hang a recovery and a walk
 * that runs out of budget SAYS which root it stopped inside. The marker shape is recognised
 * through reconcile.mjs's own classifier rather than by matching strings here, because a second
 * copy of "what a marker path looks like" is a second place to be wrong.
 *
 * @param {ReadonlyArray<string>} searchRoots
 * @param {{fsx?: object, fs?: object, maxEntries?: number, readdir?: Function}} [opts]
 * @returns {Readonly<object>}
 */
export function findMarkers(searchRoots, opts = {}) {
  const fsx = opts.fsx ?? opts.fs ?? fs;
  const cap = Number.isInteger(opts.maxEntries) && opts.maxEntries > 0
    ? opts.maxEntries
    : (CAPS.walk_entries ?? DEFAULT_WALK_CAP);

  const notices = [];
  const walked = [];
  const claims = [];
  const damaged = [];
  let complete = true;

  for (const root of (searchRoots ?? []).map((r) => path.resolve(String(r)))) {
    const walk = walkRoot(root, {
      fs: fsx,
      readdir: opts.readdir,
      maxEntries: cap,
      label: path.basename(root),
    });

    if (walk.presence !== PRESENCE.LIVE) {
      complete = false;
      notices.push(recoverOutcome(
        walk.presence === PRESENCE.ABSENT
          ? RECOVER_CODE.SEARCH_ROOT_ABSENT
          : RECOVER_CODE.SEARCH_ROOT_UNREACHABLE,
        { path: root, errno: walk.reason ?? '' },
        { root },
      ));
      walked.push(Object.freeze({ root, presence: walk.presence, markers: 0, entries_seen: 0 }));
      continue;
    }

    let boundReported = false;
    for (const hazard of walk.hazards) {
      if (hazard.code !== HAZARD.WALK_CAP_REACHED) continue;
      boundReported = true;
      notices.push(recoverOutcome(
        RECOVER_CODE.SEARCH_BOUND_EXCEEDED,
        { path: root, cap },
        { root, hazard: Object.freeze({ ...hazard }) },
      ));
    }
    if (walk.truncated && !boundReported) {
      boundReported = true;
      notices.push(recoverOutcome(RECOVER_CODE.SEARCH_BOUND_EXCEEDED, { path: root, cap }, { root }));
    }
    if (boundReported) complete = false;

    let found = 0;
    for (const file of walk.files) {
      const candidate = markerCandidateRootFor(file);
      if (candidate === null) continue;
      found += 1;
      const read = readMarker(candidate, { fs: fsx });
      if (!read.ok) {
        damaged.push(Object.freeze({
          root: candidate,
          marker_path: read.path,
          code: read.code,
          status: read.status,
          detail: read.problems && read.problems[0] ? read.problems[0].detail : read.code,
        }));
        notices.push(recoverOutcome(
          RECOVER_CODE.MARKER_DAMAGED,
          {
            path: read.path,
            reason: read.problems && read.problems[0] ? read.problems[0].detail : read.code,
          },
          { root: candidate, marker_code: read.code },
        ));
        continue;
      }
      claims.push(Object.freeze({
        search_root: root,
        // The directory the marker was FOUND in - the field-source table's answer for the
        // current path, and deliberately not the registered_path the marker itself carries.
        found_in: candidate,
        marker_path: read.path,
        marker: read.marker,
        marker_sha256: read.hash,
        bytes_len: read.bytes_len,
        moved: path.resolve(read.marker.registered_path) !== path.resolve(candidate),
      }));
    }
    walked.push(Object.freeze({
      root,
      presence: walk.presence,
      markers: found,
      entries_seen: walk.entries_seen,
    }));
  }

  // One pass, so "the same id in two places" means two places seen at once. Across two separate
  // recoveries it would be an ordinary move; conflating them would raise a conflict every time
  // a project is relocated.
  /** @type {Map<string, object[]>} */
  const byId = new Map();
  for (const claim of claims) {
    const id = claim.marker.project_id;
    if (!byId.has(id)) byId.set(id, []);
    byId.get(id).push(claim);
  }

  const bound = [];
  const conflicts = [];
  for (const [id, group] of [...byId.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1))) {
    if (group.length === 1) {
      bound.push(group[0]);
      continue;
    }
    const paths = group.map((c) => c.found_in).sort();
    conflicts.push(Object.freeze({ project_id: id, paths: Object.freeze(paths) }));
    notices.push(recoverOutcome(
      RECOVER_CODE.IDENTITY_CONFLICT,
      { project_id: id, path: paths[0], other_path: paths[1] },
      { project_id: id, paths: Object.freeze(paths), bound: false },
    ));
  }

  return Object.freeze({
    claims: Object.freeze(claims),
    // Sorted by project_id so the reconstructed log's opening run is deterministic: two
    // recoveries of the same disk must produce the same events in the same order.
    bound: Object.freeze([...bound].sort((a, b) => (
      a.marker.project_id < b.marker.project_id ? -1 : 1
    ))),
    conflicts: Object.freeze(conflicts),
    damaged: Object.freeze(damaged),
    walked: Object.freeze(walked),
    notices: Object.freeze(notices),
    complete,
  });
}

// -- source 2: the restored copy ---------------------------------------------------

/**
 * Read the operator-restored copy of the index home. Plain bytes, read-only, no lock.
 *
 * No lock, and that is deliberate rather than lazy: a restored copy is not a live store. Taking
 * the portfolio lock inside it would CREATE a lock file in somebody's backup directory, which
 * is a write into the one artifact this whole verb depends on being untouched.
 *
 * @param {string} copyPath
 * @param {{fsx?: object}} [opts]
 * @returns {Readonly<object>}
 */
export function readRestoredCopy(copyPath, opts = {}) {
  const fsx = opts.fsx ?? fs;
  const dir = path.resolve(String(copyPath));
  const paths = indexPathsFor(dir);

  let exists = false;
  try {
    exists = fs.statSync(dir).isDirectory();
  } catch {
    exists = false;
  }
  if (!exists) {
    return Object.freeze({
      ok: false,
      path: dir,
      log: paths.log,
      code: RECOVER_CODE.RESTORED_COPY_ABSENT,
      events: Object.freeze([]),
      head_seq: 0,
      problems: Object.freeze([]),
      snapshot_present: false,
    });
  }

  const read = readLogBytes(paths.log, { fsx });
  if (!read.exists || read.size === 0) {
    return Object.freeze({
      ok: true,
      path: dir,
      log: paths.log,
      code: RECOVER_CODE.RESTORED_COPY_EMPTY,
      events: Object.freeze([]),
      head_seq: 0,
      problems: Object.freeze([]),
      snapshot_present: fs.existsSync(paths.snapshot),
    });
  }

  const scanned = scanLogBytes(read.bytes);
  const parsed = parseLogRecords(scanned.records);
  const ordered = replayEvents(parsed.events);
  const head = ordered.length === 0 ? 0 : Number(ordered[ordered.length - 1][ORDERING_FIELD]);

  // A trailing fragment in a COPY is not a torn tail to quarantine - quarantining would write
  // into the backup. It is counted as a line that could not be read, which is the same fact
  // reported without touching anything.
  const problems = [...parsed.problems];
  if (scanned.fragment !== null) {
    problems.push({
      line: scanned.records.length + 1,
      offset: scanned.fragment.start,
      byte_len: scanned.fragment.byte_len,
      reason: 'the copy ends in a line with no terminator',
      integrity: INTEGRITY.TORN,
    });
  }

  return Object.freeze({
    ok: true,
    path: dir,
    log: paths.log,
    code: problems.length > 0 ? RECOVER_CODE.RESTORED_COPY_UNPARSEABLE : null,
    events: Object.freeze(ordered),
    head_seq: head,
    problems: Object.freeze(problems),
    snapshot_present: fs.existsSync(paths.snapshot),
  });
}

// -- the cut -----------------------------------------------------------------------

/** @param {object} event @returns {string|null} the project an event speaks about */
export function projectOfEvent(event) {
  if (event === null || typeof event !== 'object') return null;
  const type = event[EVENT_TYPE_FIELD];
  if (isDerivedEvent(event)) return String(event.project_id);
  if (type === NATIVE_EVENT.REGISTRATION || type === NATIVE_EVENT.RECONCILE) {
    return event.project_id === undefined ? null : String(event.project_id);
  }
  if (type === NATIVE_EVENT.COMMIT_INTENT) {
    return event.intent && event.intent.project_id !== undefined
      ? String(event.intent.project_id)
      : null;
  }
  if (type === NATIVE_EVENT.COMMIT_ACK) {
    return event.ack && event.ack.project_id !== undefined ? String(event.ack.project_id) : null;
  }
  return null;
}

/**
 * The per-project recovery cut: how far the restored copy can be believed.
 *
 * Two numbers, not one, and they are different KINDS of number. `ack_intent_seq` is the
 * PER-PROJECT intent sequence something outside this machine acknowledged. `ack_log_seq` is
 * where that intent sits in the restored copy's own total order - and it is the one DERIVED
 * rows are cut against, because a row written before the acknowledged intent was part of the
 * state that intent asked to be committed.
 *
 * @param {ReadonlyArray<object>} events the restored copy's events
 * @returns {Readonly<Record<string, object>>} project_id -> cut
 */
export function ackCutsFor(events) {
  const list = Array.isArray(events) ? events : [];
  const ledger = intentLedger(list);
  const acks = commitAcksIn(list);

  /** @type {Record<string, object>} */
  const cuts = {};
  for (const id of Object.keys(ledger.per_project).sort()) {
    const entry = ledger.per_project[id];
    const ackSeq = entry.ack_seq;
    const intent = ackSeq === null
      ? null
      : ledger.intents.find((i) => i.project_id === id && i.intent_seq === ackSeq) ?? null;
    // The LAST ack naming that intent seq: an intent acknowledged twice was acknowledged, and
    // the later wall clock is the honest edge of the window.
    const ack = ackSeq === null
      ? null
      : acks.filter((a) => a.project_id === id && a.intent_seq === ackSeq).slice(-1)[0] ?? null;

    cuts[id] = Object.freeze({
      project_id: id,
      ack_intent_seq: ackSeq,
      ack_log_seq: intent === null ? 0 : Number(intent.log_seq),
      acked_at: ack === null ? null : ack.acked_at,
      last_intent_seq: entry.emitted_seq,
      intents_after_ack: entry.unacknowledged,
    });
  }
  return Object.freeze(cuts);
}

/**
 * Split the restored copy's events into what this recovery carries and what it does not.
 *
 * @param {ReadonlyArray<object>} events
 * @param {Readonly<Record<string, object>>} cuts
 * @param {ReadonlyArray<string>} markerBoundIds ids the markers already answered for
 * @returns {Readonly<object>}
 */
export function splitAtCut(events, cuts, markerBoundIds = []) {
  const bound = new Set(markerBoundIds.map((id) => String(id)));
  const carried = [];
  const dropped = [];
  /** @type {Record<string, {carried_rows: number, dropped_rows: number, dropped_intents: number}>} */
  const perProject = {};

  const tally = (id, field) => {
    if (id === null) return;
    const entry = perProject[id] ?? { carried_rows: 0, dropped_rows: 0, dropped_intents: 0 };
    entry[field] += 1;
    perProject[id] = entry;
  };

  for (const event of replayEvents(Array.isArray(events) ? events : [])) {
    const id = projectOfEvent(event);
    const cut = id === null ? null : cuts[id] ?? null;
    const seq = Number(event[ORDERING_FIELD]);
    const type = event[EVENT_TYPE_FIELD];

    // A bundle-exported event carries no project content and no per-project sequence: it is
    // the record that a copy of this store left the box (W16). Carrying it is what stops the
    // degradation banner reading 'never exported' the day after a recovery, which would be a
    // false alarm shouted at somebody already in a disaster.
    if (type === NATIVE_EVENT.BUNDLE_EXPORTED) {
      carried.push(event);
      continue;
    }

    if (type === NATIVE_EVENT.REGISTRATION || type === NATIVE_EVENT.RECONCILE) {
      // Membership the MARKERS answered for is reconstructed from the markers, per the W4
      // field-source table - the copy's version of it is older by construction. Membership the
      // markers could not answer for is carried from here, because W11's floor is that a root
      // going missing never removes its row.
      if (id !== null && bound.has(id)) {
        dropped.push(Object.freeze({ seq, reason: BYTE_SOURCE.MARKER, event }));
        continue;
      }
      carried.push(event);
      continue;
    }

    if (type === NATIVE_EVENT.COMMIT_INTENT) {
      const intentSeq = Number(event.intent?.seq);
      if (cut !== null && cut.ack_intent_seq !== null && intentSeq <= cut.ack_intent_seq) {
        carried.push(event);
      } else {
        dropped.push(Object.freeze({ seq, reason: RECOVER_STRENGTH, event }));
        tally(id, 'dropped_intents');
      }
      continue;
    }

    if (type === NATIVE_EVENT.COMMIT_ACK) {
      const intentSeq = Number(event.ack?.intent_seq);
      if (cut !== null && cut.ack_intent_seq !== null && intentSeq <= cut.ack_intent_seq) {
        carried.push(event);
      } else {
        dropped.push(Object.freeze({ seq, reason: RECOVER_STRENGTH, event }));
      }
      continue;
    }

    if (isDerivedEvent(event)) {
      if (cut !== null && cut.ack_log_seq > 0 && seq <= cut.ack_log_seq) {
        carried.push(event);
        tally(id, 'carried_rows');
      } else {
        dropped.push(Object.freeze({ seq, reason: RECOVER_STRENGTH, event }));
        tally(id, 'dropped_rows');
      }
      continue;
    }

    // An event shape this engine does not know is neither carried nor silently discarded: it
    // is reported, because a recovery that quietly dropped bytes it did not recognise would be
    // the exact silence this wave exists to break.
    dropped.push(Object.freeze({ seq, reason: INTEGRITY.UNCLASSIFIED, event }));
  }

  for (const id of Object.keys(perProject)) perProject[id] = Object.freeze(perProject[id]);

  return Object.freeze({
    carried: Object.freeze(carried),
    dropped: Object.freeze(dropped),
    per_project: Object.freeze(perProject),
  });
}

// -- the loss report ---------------------------------------------------------------

/** @param {number} ms @returns {number} whole days, floored, never negative */
export function daysOf(ms) {
  return Math.max(0, Math.floor(Number(ms) / MS_PER_DAY));
}

/**
 * The LOST window for one project: the bounded, wall-clock span this recovery does not cover.
 *
 * `item_count` is null and `item_count_status` is UNKNOWABLE - always, for every root with an
 * open window, not only for the evaporated ones. That is not defensive vagueness: on a live
 * root the count is knowable only AFTER the chained rebuild has read the root's own files, and
 * on an absent root it is knowable never. Printing a number here would mean printing the
 * restored copy's count, which is a count of the wrong log.
 *
 * @param {{project_id: string, root: string, presence: string, cut: object|null,
 *          registered_at: string|null, carried_rows: number, dropped_rows: number,
 *          dropped_intents: number, now: number}} req
 * @returns {Readonly<object>}
 */
export function lostWindowFor(req) {
  const presence = req.presence;
  const evaporated = presence !== PRESENCE.LIVE;
  const cut = req.cut ?? null;
  const acked = cut !== null && cut.ack_intent_seq !== null;

  const fromText = acked && cut.acked_at ? cut.acked_at : (req.registered_at ?? null);
  const fromMs = fromText === null ? null : Date.parse(fromText);
  const toMs = Number(req.now);
  const spanMs = fromMs === null || Number.isNaN(fromMs) ? null : Math.max(0, toMs - fromMs);

  const ackClause = acked
    ? fill(ACK_CLAUSE.ACKED, { ack_seq: cut.ack_intent_seq, acked_at: cut.acked_at ?? fromText })
    : ACK_CLAUSE.NEVER;

  const window = Object.freeze({
    from: fromText,
    to: new Date(toMs).toISOString(),
    span_ms: spanMs,
    span_days: spanMs === null ? null : daysOf(spanMs),
    // Never a zero. A zero here would be a lie shaped exactly like good news.
    item_count: null,
    item_count_status: COUNT_STATUS.UNKNOWABLE,
    enumerable: false,
    evaporated,
    // What the COPY happened to hold past the cut. A floor on what was lost, never the total -
    // the live log may have held more, and on an evaporated root nothing can say how much more.
    post_ack_rows_in_copy: Number(req.dropped_rows ?? 0),
    post_ack_intents_in_copy: Number(req.dropped_intents ?? 0),
  });

  const code = evaporated
    ? RECOVER_CODE.LOST_WINDOW_EVAPORATED
    : RECOVER_CODE.LOST_WINDOW_RECOVERABLE;

  return Object.freeze({
    project_id: req.project_id,
    root: req.root,
    presence: assertStatusCode(presence, `${RECOVER_VERB} loss row presence`),
    acked: Boolean(acked),
    last_acked_intent_seq: acked ? cut.ack_intent_seq : null,
    last_acked_log_seq: acked ? cut.ack_log_seq : null,
    acked_at: acked ? cut.acked_at : null,
    carried_rows: Number(req.carried_rows ?? 0),
    window,
    outcome: recoverOutcome(
      code,
      {
        root: req.root,
        ack_clause: ackClause,
        from: fromText ?? '(no recorded instant)',
        to: window.to,
        days: window.span_days ?? '(unmeasurable)',
        presence,
        count_status: COUNT_STATUS.UNKNOWABLE,
      },
      { project_id: req.project_id, root: req.root },
    ),
  });
}

// -- the reconstruction ------------------------------------------------------------

/** @param {object} event @returns {object} the payload, without the two fields the log owns */
function payloadOf(event) {
  const payload = {};
  for (const key of Object.keys(event)) {
    if (key === ORDERING_FIELD || key === WALL_CLOCK_FIELD) continue;
    payload[key] = event[key];
  }
  return payload;
}

/**
 * Build the event plan: what the recovered log will contain, in order.
 *
 * The order is the load-bearing part. Marker-sourced registrations come FIRST, so every
 * carried intent, ack and DERIVED row lands after the membership it belongs to - a view
 * materialized from a log whose intents precede their registrations reports them all as
 * orphans, which would turn a good recovery into a portfolio of nothing.
 *
 * @param {{markers: ReadonlyArray<object>, carried: ReadonlyArray<object>}} parts
 * @returns {ReadonlyArray<{payload: object, written_at: string|null, old_seq: number|null,
 *          source: string}>}
 */
export function eventPlanFor(parts) {
  /** @type {Array<object>} */
  const plan = [];

  for (const claim of parts.markers ?? []) {
    const marker = claim.marker;
    plan.push({
      payload: makeRegistrationEvent({
        project_id: marker.project_id,
        // The REGISTERED path, which is the historical fact the marker records. Where the
        // marker was actually found is the CURRENT path, and it is recorded below as the move
        // it is - so both facts survive instead of one overwriting the other.
        root: marker.registered_path,
        registered_at: marker.registered_at,
        registration_receipt_id: marker.registration_receipt_id,
        marker_sha256: claim.marker_sha256,
      }),
      // The marker's own registration instant: the wall clock recorded at registration, not the
      // instant this recovery happens to run. A recovered log dated today would make every
      // project look freshly registered.
      written_at: marker.registered_at,
      old_seq: null,
      source: BYTE_SOURCE.MARKER,
    });
    if (claim.moved) {
      plan.push({
        payload: makeReconcileEvent({
          project_id: marker.project_id,
          from_path: marker.registered_path,
          to_path: claim.found_in,
          mode: RECONCILE_MODE.MOVED,
          marker_sha256: claim.marker_sha256,
        }),
        written_at: null,
        old_seq: null,
        source: BYTE_SOURCE.MARKER,
      });
    }
  }

  for (const event of parts.carried ?? []) {
    plan.push({
      payload: payloadOf(event),
      written_at: typeof event[WALL_CLOCK_FIELD] === 'string' ? event[WALL_CLOCK_FIELD] : null,
      old_seq: Number(event[ORDERING_FIELD]),
      source: BYTE_SOURCE.RESTORED_COPY,
    });
  }

  return Object.freeze(plan);
}

/**
 * Remap a carried DERIVED row's `supersedes` into the recovered log's numbering.
 *
 * A recovered log is a NEW total order: the same rows sit at different sequences, so a
 * `supersedes` left pointing at the old numbering would name whatever event happens to have
 * landed there - which is worse than naming nothing.
 *
 * @param {object} payload @param {Map<number, number>} seqMap
 * @returns {{payload: object, remapped: boolean, orphaned: boolean}}
 */
export function remapSupersedes(payload, seqMap) {
  if (!isDerivedEvent(payload) || payload.supersedes === null || payload.supersedes === undefined) {
    return { payload, remapped: false, orphaned: false };
  }
  const old = Number(payload.supersedes);
  const mapped = seqMap.get(old);
  if (mapped === undefined) {
    // Its predecessor was not carried, so the row it superseded is not in this log. Null is the
    // honest answer: the lineage is shorter than it was, and saying so beats pointing at a
    // sequence that now means something else.
    return { payload: { ...payload, supersedes: null }, remapped: false, orphaned: true };
  }
  return { payload: { ...payload, supersedes: mapped }, remapped: true, orphaned: false };
}

// -- the verb ----------------------------------------------------------------------

/**
 * `steward recover-log` - reconstruct the ONE log from markers plus the restored copy, report
 * what was lost, and chain the rebuild.
 *
 * @param {{home?: string, paths?: object, env?: object, input?: object,
 *          search_roots?: ReadonlyArray<string>|string, restored_copy?: string,
 *          now?: number|Date, fsx?: object, maxEntries?: number, readdir?: Function,
 *          rebuild?: boolean, reassert?: boolean, boundMs?: number, staleMs?: number,
 *          lockOpts?: object}} opts
 * @returns {Readonly<object>}
 */
export function recoverLog(opts = {}) {
  const paths = indexPathsFrom(opts);
  const nowMs = new Date(opts.now ?? Date.now()).getTime();
  const nowText = new Date(nowMs).toISOString();

  const checked = validateRecoverInput(opts.input ?? {
    schema: RECOVER_INPUT_SCHEMA,
    search_roots: opts.search_roots,
    restored_copy: opts.restored_copy,
  });
  if (!checked.ok) {
    return recoverOutcome(
      checked.code,
      { reason: checked.problems.join('; '), path: '' },
      { schema: RECOVER_RECEIPT_SCHEMA, home: paths.home, written: false, events_written: 0 },
    );
  }
  const input = checked.input;

  // The one read of the live home, and it is a refusal check rather than an input: a live log
  // here means this is not the disaster path at all.
  const live = readLogBytes(paths.log, {});
  if (live.exists && live.size > 0) {
    const scanned = scanLogBytes(live.bytes);
    const parsed = parseLogRecords(scanned.records);
    const ordered = replayEvents(parsed.events);
    return recoverOutcome(
      RECOVER_CODE.LIVE_LOG_PRESENT,
      {
        log: paths.log,
        size: live.size,
        head_seq: ordered.length === 0 ? 0 : Number(ordered[ordered.length - 1][ORDERING_FIELD]),
      },
      {
        schema: RECOVER_RECEIPT_SCHEMA,
        home: paths.home,
        log: paths.log,
        written: false,
        events_written: 0,
      },
    );
  }

  // Everything from here reads through the facade, so a read outside the declared input set is
  // a throw at the call site rather than a line in a review comment.
  const journal = newRecoverJournal();
  const guarded = recoverInputFs(opts.fsx, {
    allowed: [...input.search_roots, input.restored_copy, paths.home],
  }, journal);

  const restored = readRestoredCopy(input.restored_copy, { fsx: guarded });
  if (!restored.ok) {
    return recoverOutcome(
      restored.code,
      { path: restored.path },
      {
        schema: RECOVER_RECEIPT_SCHEMA,
        home: paths.home,
        input,
        written: false,
        events_written: 0,
        byte_sources: Object.freeze([...journal.reads]),
      },
    );
  }

  const notices = [];
  if (restored.code === RECOVER_CODE.RESTORED_COPY_EMPTY) {
    notices.push(recoverOutcome(
      RECOVER_CODE.RESTORED_COPY_EMPTY,
      { path: restored.path, file: INDEX_FILES.LOG },
      { path: restored.path },
    ));
  }
  if (restored.code === RECOVER_CODE.RESTORED_COPY_UNPARSEABLE) {
    const first = restored.problems[0];
    notices.push(recoverOutcome(
      RECOVER_CODE.RESTORED_COPY_UNPARSEABLE,
      {
        path: restored.path,
        count: restored.problems.length,
        line: first.line,
        reason: first.reason,
      },
      { path: restored.path, problems: restored.problems },
    ));
  }

  const found = findMarkers(input.search_roots, {
    fsx: guarded,
    maxEntries: opts.maxEntries,
    readdir: opts.readdir,
  });
  notices.push(...found.notices);

  const markerIds = found.bound.map((c) => c.marker.project_id);
  const cuts = ackCutsFor(restored.events);
  const split = splitAtCut(restored.events, cuts, markerIds);

  // The projects the copy knows and the markers could not answer for: their roots are not where
  // a marker could be found, so they are the absent half of the portfolio - and W11's floor
  // says they keep their rows.
  const copyView = materializeRegistry(restored.events);
  const absentProjects = copyView.projects.filter((p) => !markerIds.includes(p.project_id));

  if (found.bound.length === 0 && absentProjects.length === 0) {
    return recoverOutcome(
      RECOVER_CODE.NOTHING_TO_RECOVER,
      {},
      {
        schema: RECOVER_RECEIPT_SCHEMA,
        home: paths.home,
        input,
        written: false,
        events_written: 0,
        notices: Object.freeze(notices),
        byte_sources: Object.freeze([...journal.reads]),
      },
    );
  }

  const plan = eventPlanFor({ markers: found.bound, carried: split.carried });

  const prepared = ensureIndexHome(paths, { fsx: opts.fsx });
  if (prepared.ok !== true) {
    return recoverOutcome(
      RECOVER_CODE.WRITE_FAILED,
      {
        written: 0,
        total: plan.length,
        reason: prepared.text ? prepared.text : String(prepared.code),
      },
      {
        schema: RECOVER_RECEIPT_SCHEMA,
        home: paths.home,
        input,
        written: false,
        events_written: 0,
        index_outcome: prepared,
        notices: Object.freeze(notices),
      },
    );
  }

  /** @type {Map<number, number>} old seq -> recovered seq */
  const seqMap = new Map();
  let orphanedLineage = 0;

  let result;
  try {
    result = withPortfolioLock(
      paths,
      () => {
        const written = [];
        let size = 0;
        let seq = 0;
        for (const item of plan) {
          const remapped = remapSupersedes(item.payload, seqMap);
          if (remapped.orphaned) orphanedLineage += 1;
          seq += 1;
          const event = makeLogEvent(remapped.payload, {
            seq,
            written_at: item.written_at ?? undefined,
            now: nowMs,
          });
          const wrote = appendLineAt(paths.log, logEventLine(event), {
            expected_size: size,
            fsx: opts.fsx,
          });
          if (wrote.ok !== true) {
            return { written, failed: wrote, head_seq: seq - 1 };
          }
          size += wrote.bytes_written;
          written.push(event);
          if (item.old_seq !== null) seqMap.set(item.old_seq, seq);
        }
        return { written, failed: undefined, head_seq: seq };
      },
      { boundMs: opts.boundMs, staleMs: opts.staleMs, lockOpts: opts.lockOpts },
    );
  } catch (err) {
    return recoverOutcome(
      RECOVER_CODE.WRITE_FAILED,
      { written: 0, total: plan.length, reason: String(err && err.message ? err.message : err) },
      {
        schema: RECOVER_RECEIPT_SCHEMA,
        home: paths.home,
        input,
        written: false,
        events_written: 0,
        notices: Object.freeze(notices),
      },
    );
  }

  if (result.failed !== undefined) {
    return recoverOutcome(
      RECOVER_CODE.WRITE_FAILED,
      {
        written: result.written.length,
        total: plan.length,
        reason: result.failed.text ? result.failed.text : String(result.failed.code),
      },
      {
        schema: RECOVER_RECEIPT_SCHEMA,
        home: paths.home,
        log: paths.log,
        input,
        written: true,
        events_written: result.written.length,
        index_outcome: result.failed,
        notices: Object.freeze(notices),
      },
    );
  }

  // The RECOVER_LOG intent, per project the markers bound. A recovered log has never been
  // acknowledged by anything, and the honest way to say so is to ASK again rather than to leave
  // the durability surface quiet: the banner would otherwise read healthy on a log nothing off
  // this box has ever seen. The intent's per-project sequence continues from the acknowledged
  // one, so an ack for the ORIGINAL intent at that number arrives against different bytes and
  // is caught by W15's hash join rather than believed.
  const reasserted = [];
  if (opts.reassert !== false) {
    const recoveredView = materializeRegistry(result.written);
    for (const claim of found.bound) {
      const id = claim.marker.project_id;
      const entry = recoveredView.projects.find((p) => p.project_id === id) ?? null;
      if (entry === null) continue;
      const intent = makeCommitIntent({
        project_id: id,
        seq: nextSeqFor(entry.commit_intent_seq),
        reason: COMMIT_REASON.RECOVER_LOG,
        paths: [pathEntryFor(MARKER_ROOT_REL_PATH, markerBytesOf(claim, guarded))],
        written_at: nowText,
      });
      reasserted.push({ project_id: id, intent });
    }
  }

  let reassertOutcome = null;
  if (reasserted.length > 0) {
    reassertOutcome = withPortfolioLock(
      paths,
      () => {
        const bytesBefore = readLogBytes(paths.log, { fsx: opts.fsx });
        let size = bytesBefore.size;
        let seq = result.head_seq;
        const appended = [];
        for (const item of reasserted) {
          seq += 1;
          const event = makeLogEvent(makeCommitIntentEvent(item.intent), {
            seq,
            written_at: nowText,
          });
          const wrote = appendLineAt(paths.log, logEventLine(event), {
            expected_size: size,
            fsx: opts.fsx,
          });
          if (wrote.ok !== true) return { ok: false, appended, failed: wrote, head_seq: seq - 1 };
          size += wrote.bytes_written;
          appended.push(event);
        }
        return { ok: true, appended, failed: undefined, head_seq: seq };
      },
      { boundMs: opts.boundMs, staleMs: opts.staleMs, lockOpts: opts.lockOpts },
    );
  }

  const headSeq = reassertOutcome && reassertOutcome.ok
    ? reassertOutcome.head_seq
    : result.head_seq;
  const allWritten = reassertOutcome && reassertOutcome.ok
    ? [...result.written, ...reassertOutcome.appended]
    : result.written;

  // -- the loss report, per root ---------------------------------------------------

  const lossRows = [];
  for (const claim of found.bound) {
    const id = claim.marker.project_id;
    const status = classifyRootStatus(claim.found_in);
    const tallies = split.per_project[id] ?? {};
    lossRows.push(lostWindowFor({
      project_id: id,
      root: claim.found_in,
      presence: status.presence,
      cut: cuts[id] ?? null,
      registered_at: claim.marker.registered_at,
      carried_rows: tallies.carried_rows ?? 0,
      dropped_rows: tallies.dropped_rows ?? 0,
      dropped_intents: tallies.dropped_intents ?? 0,
      now: nowMs,
    }));
  }
  for (const project of absentProjects) {
    const id = project.project_id;
    const status = classifyRootStatus(project.current_path);
    const tallies = split.per_project[id] ?? {};
    lossRows.push(lostWindowFor({
      project_id: id,
      root: project.current_path,
      // A root the markers could not answer for is not LIVE by construction, whatever a stat
      // says: if it were live and carried a marker, the search would have found it. A directory
      // that exists but holds no marker is reported through its classifier all the same, so an
      // operator who pointed the search at the wrong place sees a live root with no marker
      // rather than a confident lie about it being gone.
      presence: status.presence,
      cut: cuts[id] ?? null,
      registered_at: project.registered_at,
      carried_rows: tallies.carried_rows ?? 0,
      dropped_rows: tallies.dropped_rows ?? 0,
      dropped_intents: tallies.dropped_intents ?? 0,
      now: nowMs,
    }));
  }
  lossRows.sort((a, b) => (a.project_id < b.project_id ? -1 : 1));

  const evaporated = lossRows.filter((r) => r.window.evaporated);
  const loss = Object.freeze({
    rows: Object.freeze(lossRows),
    any_evaporated: evaporated.length > 0,
    unenumerable_roots: Object.freeze(evaporated.map((r) => r.root)),
    // Stated as a count of ROOTS, never of items: the items are the thing that cannot be
    // counted, and a total here would be a total of the wrong log.
    unenumerable_root_count: evaporated.length,
    item_count: null,
    item_count_status: COUNT_STATUS.UNKNOWABLE,
    strength: RECOVER_STRENGTH,
    text: RECOVERY_STRENGTH_SENTENCE,
  });

  // -- the chained rebuild ---------------------------------------------------------

  let rebuilt = null;
  if (opts.rebuild !== false) {
    // The RAW fs, not the facade: the rebuilder's input set is its own (the log plus the live
    // roots, W10), and it is wider than this verb's by design.
    rebuilt = rebuildIndex({
      home: paths.home,
      paths,
      boundMs: opts.boundMs,
      staleMs: opts.staleMs,
      lockOpts: opts.lockOpts,
    });
  }

  const common = {
    schema: RECOVER_RECEIPT_SCHEMA,
    home: paths.home,
    log: paths.log,
    snapshot: paths.snapshot,
    input: Object.freeze({
      ...input,
      byte_sources: RECOVER_INPUT,
      excluded: RECOVER_EXCLUDED_INPUT,
      field_source: FIELD_SOURCE,
      restored_head_seq: restored.head_seq,
      search_complete: found.complete,
    }),
    written: true,
    events_written: allWritten.length,
    head_seq: headSeq,
    derived_carried: split.carried.filter((e) => isDerivedEvent(e)).length,
    events_dropped: split.dropped.length,
    orphaned_lineage: orphanedLineage,
    recovered: Object.freeze({
      projects: Object.freeze(lossRows.map((r) => r.project_id)),
      project_count: lossRows.length,
      from_markers: found.bound.length,
      from_restored_copy: absentProjects.length,
      conflicts: found.conflicts,
      damaged_markers: found.damaged,
      reasserted: Object.freeze(reasserted.map((r) => Object.freeze({
        project_id: r.project_id,
        seq: r.intent.seq,
        reason: r.intent.reason,
      }))),
    }),
    loss,
    cuts: Object.freeze({ ...cuts }),
    notices: Object.freeze([...notices, ...lossRows.map((r) => r.outcome)]),
    // Every byte this recovery read, named. The closed-input claim is checkable from here
    // rather than takeable on trust.
    byte_sources: Object.freeze([...journal.reads]),
    refused_reads: Object.freeze([...journal.refused]),
    rebuilt,
  };

  if (rebuilt !== null && rebuilt.ok !== true) {
    return recoverOutcome(
      RECOVER_CODE.REBUILD_FAILED,
      {
        verb: CHAINED_VERB,
        reason: rebuilt.outcome?.text ?? String(rebuilt.outcome?.code ?? ''),
      },
      common,
    );
  }

  return recoverOutcome(
    RECOVER_CODE.OK,
    {
      projects: lossRows.length,
      log: paths.log,
      markers: found.bound.length,
      absent: absentProjects.length,
      events: allWritten.length,
      derived: common.derived_carried,
    },
    common,
  );
}

/**
 * The marker's exact bytes, re-read for the intent's hash.
 *
 * The HASH is what the intent carries, and it must be the hash of the bytes on disk rather than
 * of a re-serialization of the parsed fields: an intent whose hash names bytes nobody has is an
 * intent no acknowledgement can ever match.
 *
 * It goes through the SAME guarded facade as every other read in this verb, so the bytes it
 * hashes are journaled beside the rest: an un-journaled read would be a hole in the very claim
 * the journal exists to make.
 *
 * @param {{marker_path: string}} claim @param {object} fsx @returns {Buffer}
 */
function markerBytesOf(claim, fsx) {
  // encoding-lint: raw-bytes - the intent hashes the bytes as they sit on disk; decoding and
  // re-encoding on the way past would hash something nobody's file contains.
  const bytes = fsx.readFileSync(claim.marker_path);
  return Buffer.isBuffer(bytes) ? bytes : Buffer.from(String(bytes), 'utf8');
}

// -- rendering ---------------------------------------------------------------------

/**
 * The receipt as lines an operator reads. One place, so stand-up, the High Seat and the CLI
 * cannot word a disaster three ways.
 *
 * @param {Readonly<object>} receipt @returns {ReadonlyArray<string>}
 */
export function renderRecoveryReceipt(receipt) {
  const lines = [`${RECOVER_VERB}: ${receipt.code}`, receipt.text];
  if (receipt.loss === undefined || receipt.loss === null) return Object.freeze(lines);

  lines.push(`recovery strength: ${receipt.loss.strength}`);
  for (const row of receipt.loss.rows) {
    lines.push(row.outcome.text);
    lines.push(
      `  ${row.project_id}: last acknowledged intent `
      + `${row.last_acked_intent_seq === null ? 'none' : row.last_acked_intent_seq}, `
      + `items lost in the window: ${row.window.item_count_status}`,
    );
  }
  if (receipt.loss.any_evaporated) {
    lines.push(
      `${receipt.loss.unenumerable_root_count} root(s) are gone as well as the log, so what was `
      + 'written on them after their last acknowledgement cannot be enumerated at all.',
    );
  }
  return Object.freeze(lines);
}

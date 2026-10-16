/**
 * W13 - `steward query`: the no-walk find surface, and BQC-1's bounded pagination.
 *
 * THE ONE PROPERTY THIS FILE EXISTS TO ESTABLISH. C8 says a cross-project question is
 * answered from the ONE index without walking the portfolio. That is a claim about what the
 * code CANNOT do, and a claim of that shape is worth exactly as much as its enforcement: a
 * comment saying "we do not open project roots here" stays true until the first convenient
 * `readFileSync` in a helper three waves from now. So every read this verb performs goes
 * through `indexOnlyFs`, a facade that REFUSES a read outside the index home by name and
 * journals the reads it makes. "No project root is opened on the query path" is therefore a
 * property of the code, and the test that asserts it reads a journal rather than trusting a
 * sentence.
 *
 * That is also why an unreadable root cannot change the answer. A root that is renamed away,
 * or deny-ACL'd so the process cannot list it, contributes exactly what it contributed
 * before: its DERIVED rows, out of the index, marked with the freshness the last rebuild
 * recorded for it. The failure mode this forecloses is the quiet one - a query that walks,
 * hits EACCES, and returns a SHORTER list with no line of output being false. Omission is
 * indistinguishable from absence to the reader, which is why the rows are returned and
 * MARKED rather than dropped and mentioned.
 *
 * D-3, THE MERGE, AND WHY IT IS BOUNDED. The answer is `body` plus a replay of the log's
 * DERIVED events after `freshness.head_seq`, merged by row identity with the tail winning.
 * That is what makes a receipt written one second ago findable with no rebuild. It is
 * affordable only because the tail is bounded: past `caps.tail_events` this verb hands the
 * fold to engine/portfolio/rematerialize.mjs, which recomputes the snapshot and replaces it
 * atomically, and the merge cost returns to where it started.
 *
 * A CONTINUATION NEVER RE-MATERIALIZES. Re-materialization rewrites the snapshot, and a
 * cursor is bound to the snapshot it was issued against - so re-materializing mid-pagination
 * would invalidate the very cursor being served. The fold is therefore attempted only on a
 * first page. The tail cannot grow without bound as a result: the next first page folds it.
 *
 * PAGING, AND THE TOTAL ORDER IT RESTS ON. Rows are ordered by (project_id, class, path,
 * seq) - W6's frozen comparator, imported rather than re-derived - and a page is "the next N
 * rows strictly after the last row of the previous page". Because the order is TOTAL and
 * every identity appears once, the union of the pages is the full result set with no gap and
 * no duplicate; that is not a hope about the implementation, it is a property of a strict
 * order over a set. The full-scan oracle and the paged path share `selectRows`, so the two
 * cannot disagree about WHICH rows they are ordering, and both ask contains.mjs the same
 * question about each one.
 *
 * WHAT GOING PAST THE CAP DOES. It yields a further page. The caps table names the
 * disposition for the query surface, no query-surface row is triggered by sheer row count,
 * and test/w55-bqc1-single-source.test.mjs is what keeps that true; this module is the
 * implementation of that decision rather than a second statement of it.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  INDEX_READ_CODE,
  ORDERING_FIELD,
  WALL_CLOCK_FIELD,
  indexPathsFrom,
  openIndexForRead,
  replayEvents,
} from '../append-log.mjs';
import { canonicalJson, compareRows, snapshotSha256 } from './canonical.mjs';
import { CAPS, capStatusFor } from './caps.mjs';
import {
  CONTAINS_VERSION,
  containsMatch,
  describeContains,
  mojibakeInProj,
  normalizeNeedle,
} from './contains.mjs';
import { DERIVABLE_CLASSES, isDerivedEvent, rowIdentity } from './derive.mjs';
import { SURFACE, rowOutcome, rowsForSurface } from './failure-tables.mjs';
import { isInsideHome } from './home.mjs';
import { CLASS, EXTENDED_PREFIX, HAZARD } from './inventory.mjs';
import { bodyRow, containedPath } from './rebuild.mjs';
import { materializeRegistry } from './registry.mjs';
import {
  REMATERIALIZE_TRIGGER,
  rematerializeIndex,
  shouldRematerialize,
  tailAfter,
} from './rematerialize.mjs';
import { emptyFreshnessBlock, validateSnapshotShape } from './snapshot-shape.mjs';
import { AXIS, FRESHNESS, INTEGRITY, PRESENCE, assertStatusCode, isOnAxis } from './status.mjs';

/** The verb's frozen version. Changing what a result carries means query-v2. */
export const QUERY_VERSION = 'query-v1';

/** The result this verb hands its caller. */
export const QUERY_RESULT_SCHEMA = 'query-result-v1';

/** The verb's name, as an operator types it. */
export const QUERY_VERB = 'query';

/** The failure-table surface these rows belong to. */
export const QUERY_SURFACE = SURFACE.QUERY;

/** The cursor's frozen version. A cursor from another version is not addressed to this one. */
export const CURSOR_VERSION = 'query-cursor-v1';

// -- the frozen CLI UX ----------------------------------------------------------

/**
 * The flags, as data. A test can enumerate them and a help renderer can print them, so the
 * CLI surface has one definition rather than a parser and a paragraph that drift apart.
 */
export const QUERY_FLAG = Object.freeze({
  TYPE: '--type',
  PROJECT: '--project',
  SINCE: '--since',
  CONTAINS: '--contains',
  CURSOR: '--cursor',
  PAGE_SIZE: '--page-size',
  JSON: '--json',
});

/** @type {ReadonlyArray<string>} */
export const QUERY_FLAGS = Object.freeze(Object.values(QUERY_FLAG));

/** The flags that take a value. `--json` is the one that does not. */
export const VALUE_FLAGS = Object.freeze([
  QUERY_FLAG.TYPE,
  QUERY_FLAG.PROJECT,
  QUERY_FLAG.SINCE,
  QUERY_FLAG.CONTAINS,
  QUERY_FLAG.CURSOR,
  QUERY_FLAG.PAGE_SIZE,
]);

/** What each flag does, for the help renderer. One sentence, one home. */
export const QUERY_FLAG_HELP = Object.freeze({
  [QUERY_FLAG.TYPE]: `restrict to one tracked class (${DERIVABLE_CLASSES.join(' | ')})`,
  [QUERY_FLAG.PROJECT]: 'restrict to one project_id',
  [QUERY_FLAG.SINCE]: 'only rows at or after a log sequence, or after an ISO-8601 instant',
  [QUERY_FLAG.CONTAINS]: 'case-insensitive substring over the projection fields of each class',
  [QUERY_FLAG.CURSOR]: 'the value printed at the foot of the previous page',
  [QUERY_FLAG.PAGE_SIZE]: `rows per page, bounded by the ${CAPS.rows_per_query}-row page cap`,
  [QUERY_FLAG.JSON]: 'render the whole result as JSON instead of as a table',
});

// -- the rows -------------------------------------------------------------------

/** The class suffix a class-varying query row carries. */
const CLASS_SUFFIX = Object.freeze({
  [CLASS.RECEIPT]: 'RECEIPT',
  [CLASS.INSTRUMENT]: 'INSTRUMENT',
  [CLASS.ROADMAP_EVENT]: 'ROADMAP_EVENT',
});

/** The class-varying query row stems. */
export const QUERY_CLASS_STEM = Object.freeze({
  EMPTY: 'QUERY_EMPTY',
  UNKNOWN: 'QUERY_UNKNOWN',
});

/** The query rows that do not vary by class. */
export const QUERY_CODE = Object.freeze({
  INDEX_ABSENT: 'QUERY_INDEX_ABSENT',
  INDEX_UNREACHABLE: 'QUERY_INDEX_UNREACHABLE',
  INDEX_UNREADABLE: 'QUERY_INDEX_UNREADABLE',
  LOCK_TIMEOUT: 'QUERY_LOCK_TIMEOUT',
  CURSOR_STALE: 'QUERY_CURSOR_STALE',
  SNAPSHOT_UNPARSEABLE: 'QUERY_SNAPSHOT_UNPARSEABLE',
  PROJ_MOJIBAKE: 'QUERY_PROJ_MOJIBAKE',
  TAIL_TORN: 'QUERY_TAIL_TORN',
  ROW_TAMPERED: 'QUERY_ROW_TAMPERED',
  IDENTITY_CONFLICT: 'QUERY_IDENTITY_CONFLICT',
  UNCLASSIFIED: 'QUERY_UNCLASSIFIED',
  NO_MATCHES: 'QUERY_NO_MATCHES',
  ROOT_UNKNOWN: 'QUERY_ROOT_UNKNOWN',
  SKIPPED_REPARSE: 'QUERY_SKIPPED_REPARSE',
  PATH_TOO_LONG: 'QUERY_PATH_TOO_LONG',
  CASE_COLLISION: 'QUERY_CASE_COLLISION',
});

/** The success code, and the one usage refusal. Neither is a failure-table row: the tables
 * describe failure STATES of a working surface, and "you typed a class that does not exist"
 * is a conversation with the operator about their command line, not about the portfolio. */
export const QUERY_OK = 'QUERY_OK';
export const QUERY_USAGE = 'QUERY_USAGE';

/** @type {Readonly<Record<string, {status: string, text: string}>>} */
export const QUERY_LOCAL_ROWS = Object.freeze({
  [QUERY_OK]: Object.freeze({
    status: assertStatusCode(INTEGRITY.OK, 'query OK'),
    text:
      'Answered from the index alone: {returned} row(s) on this page of {matched} matched, '
      + 'out of {scanned} row(s) merged from the snapshot body and {tail} log event(s) after '
      + 'sequence {head_seq}. No project root was opened.',
  }),
  [QUERY_USAGE]: Object.freeze({
    status: assertStatusCode(FRESHNESS.UNKNOWN, 'query usage'),
    text: 'the query was not run: {reason}',
  }),
});

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole,
  );
}

/**
 * The class-varying row code for a stem.
 *
 * @param {string} stem @param {string} className @returns {string}
 */
export function queryClassCode(stem, className) {
  const suffix = CLASS_SUFFIX[className];
  if (suffix === undefined) {
    throw new Error(`query: ${JSON.stringify(className)} is not a tracked content class`);
  }
  return `${stem}_${suffix}`;
}

/**
 * An outcome for a query row: read from the frozen table, or from the two local codes.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function queryOutcome(code, params = {}, extra = {}) {
  const local = QUERY_LOCAL_ROWS[code];
  if (local !== undefined) {
    return Object.freeze({
      ok: extra.ok !== false,
      code,
      surface: QUERY_SURFACE,
      status: local.status,
      text: fill(local.text, params),
      detail: Object.freeze({ ...params }),
    });
  }
  return rowOutcome(code, params, extra);
}

/** @returns {ReadonlyArray<string>} every frozen query row code, for a test that enumerates */
export function queryRowCodes() {
  return Object.freeze(rowsForSurface(QUERY_SURFACE).map((r) => r.code));
}

/**
 * The rows this wave owns, READ from the table rather than restated - so a row a later wave
 * adds to the query surface is that wave's to turn green, and one this wave forgot cannot
 * hide behind a hand-typed list.
 *
 * @returns {ReadonlyArray<string>}
 */
export function queryRowsOwnedByThisWave() {
  return Object.freeze(
    rowsForSurface(QUERY_SURFACE).filter((r) => r.wave === 'W13').map((r) => r.code),
  );
}

/**
 * How an index-read failure is spoken on the query surface.
 *
 * The rows that have a query counterpart are re-spoken through it, because the operator is
 * running a query and the query table is where they will look. The two that do NOT have one -
 * a mojibake-damaged snapshot and a snapshot whose head hash disagrees with the log - are
 * passed through VERBATIM as their index-read rows rather than folded into the nearest query
 * row: MOJIBAKE and TAMPERED are distinct states by decision, and laundering either into
 * QUERY_SNAPSHOT_UNPARSEABLE would erase exactly the distinction the tables were split to keep.
 */
export const READ_CODE_ROW = Object.freeze({
  [INDEX_READ_CODE.HOME_ABSENT]: QUERY_CODE.INDEX_ABSENT,
  [INDEX_READ_CODE.HOME_UNREACHABLE]: QUERY_CODE.INDEX_UNREACHABLE,
  [INDEX_READ_CODE.SNAPSHOT_UNREADABLE]: QUERY_CODE.INDEX_UNREADABLE,
  [INDEX_READ_CODE.SNAPSHOT_UNPARSEABLE]: QUERY_CODE.SNAPSHOT_UNPARSEABLE,
  [INDEX_READ_CODE.LOCK_TIMEOUT]: QUERY_CODE.LOCK_TIMEOUT,
  [INDEX_READ_CODE.LOG_TORN_TAIL]: QUERY_CODE.TAIL_TORN,
  [INDEX_READ_CODE.UNKNOWN]: QUERY_CODE.ROOT_UNKNOWN,
});

/** @param {string} code @returns {string|null} */
export function queryCodeForReadCode(code) {
  return READ_CODE_ROW[code] ?? null;
}

// -- refusals that are defects rather than operator conditions ------------------

/** Not a failure-table row and carrying no STATUS-v1 status: an operator cannot act on it. */
export const QUERY_REFUSAL = Object.freeze({
  ROOT_READ: 'QUERY_ROOT_READ_ON_THE_QUERY_PATH',
  NO_FRESHNESS: 'QUERY_ROW_WITHOUT_A_FRESHNESS_STATUS',
  STRICT_MODE: 'QUERY_STRICT_MODE_WAS_REMOVED',
});

// -- W14: there is no strict mode, and that is enforced rather than announced ------

/**
 * The removal, as data.
 *
 * A "strict mode" on a find surface is a switch that decides whether the answer is checked.
 * Two things follow from having one, and both are worse than the cost it saves: the DEFAULT
 * answer is the unchecked one (nobody types the flag during an incident), and the same command
 * means two different things depending on a flag the reader of the output cannot see. So the
 * switch is gone in both directions - every row ALWAYS carries a STATUS-v1 freshness code, and
 * a query NEVER re-verifies. Re-verification is `steward verify`, a separate verb the caller
 * chains explicitly; see REVERIFICATION_CONTRACT in engine/portfolio/verify.mjs.
 *
 * The flag list above is the enforcement: `--strict` is not in QUERY_FLAGS, so parseQueryArgs
 * refuses it by name, and assertRowsCarryFreshness() refuses a row that reached the caller
 * without a freshness verdict - which is the same defect wearing the other hat.
 */
export const QUERY_STRICT_MODE = Object.freeze({
  removed: true,
  flag: '--strict',
  removed_by: 'W14',
  replacement: 'steward verify',
  every_row_carries_freshness: true,
  refusal_text:
    '--strict was removed in W14: every query row already carries a STATUS-v1 freshness code, '
    + 'and re-verification is `steward verify`, chained explicitly by the caller.',
  why:
    'A hidden query-time mode makes the honesty of an answer depend on a flag the reader of '
    + 'that answer never sees. Freshness is REPORTED here, always, and DECIDED by steward '
    + 'verify, which the caller chains when they want it re-checked.',
});

/**
 * Every returned row carries a STATUS-v1 freshness code - checked, not assumed.
 *
 * This throws rather than returning an outcome, and deliberately so: a row with no freshness
 * is a defect in this engine, not a state of the operator's portfolio, and dressing it up as a
 * failure-table row would put it in a table the operator cannot act on. The check is cheap and
 * runs on every page, because "always" is the whole claim.
 *
 * @param {ReadonlyArray<object>} rows @returns {ReadonlyArray<object>} the rows, unchanged
 */
export function assertRowsCarryFreshness(rows) {
  for (const row of rows ?? []) {
    if (!isOnAxis(row?.freshness, AXIS.FRESHNESS)) {
      throw new QueryRefusal(
        QUERY_REFUSAL.NO_FRESHNESS,
        `the row for ${row?.project_id ?? '(no project)'} at ${row?.path ?? '(no path)'} carries `
        + `freshness ${JSON.stringify(row?.freshness ?? null)}, which is not on the STATUS-v1 `
        + 'freshness axis. Strict mode was removed in W14 precisely so that no row can reach a '
        + 'caller unmarked; a row without a verdict is that mode returning by the back door.',
      );
    }
  }
  return rows;
}

/** A refusal that names the rule it enforces. */
export class QueryRefusal extends Error {
  /** @param {string} code @param {string} detail */
  constructor(code, detail) {
    super(`${code}: ${detail}`);
    this.name = 'QueryRefusal';
    this.code = code;
    this.detail = detail;
  }
}

// -- the index-only filesystem facade -------------------------------------------

/** The calls that can turn a path into bytes or into a directory listing. */
export const GUARDED_READ_CALLS = Object.freeze([
  'readFileSync',
  'readFile',
  'openSync',
  'open',
  'createReadStream',
  'readdirSync',
  'readdir',
  'opendirSync',
  'copyFileSync',
]);

/** @param {unknown} p @returns {string} the path as the guard compares it */
function comparablePath(p) {
  const raw = String(p ?? '');
  return raw.startsWith(EXTENDED_PREFIX) ? raw.slice(EXTENDED_PREFIX.length) : raw;
}

/**
 * An `fs` facade that can only reach the index home.
 *
 * This is the mechanism behind C8's no-walk property. A read of anything outside the home
 * throws AT THE CALL SITE with the rule in the message, so a helper that grows a project-root
 * read fails loudly in development rather than quietly turning the query surface into a walk
 * in production. Everything the query legitimately reads - the log, the snapshot, the lock,
 * the home's own entries - is inside the home by construction.
 *
 * @param {object|undefined} base @param {string} home
 * @param {{reads: Array<object>, outside: Array<object>, total: number}} journal
 * @returns {object}
 */
export function indexOnlyFs(base, home, journal) {
  const facade = { ...(base ?? fs) };
  const root = path.resolve(String(home));

  const note = (call, target) => {
    journal.total += 1;
    const candidate = comparablePath(target);
    if (!isInsideHome(root, candidate)) {
      const entry = Object.freeze({ call, path: String(target) });
      journal.outside.push(entry);
      throw new QueryRefusal(
        QUERY_REFUSAL.ROOT_READ,
        `${call}() was asked to read ${target}, which is outside the index home ${root}. `
        + 'The query surface answers from the ONE index and opens no project root: a root that '
        + 'has been renamed away or denied to this process must change the freshness of an '
        + 'answer, never its contents.',
      );
    }
    journal.reads.push(Object.freeze({ call, path: String(target) }));
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

/** @returns {{reads: Array<object>, outside: Array<object>, total: number}} a fresh journal */
export function newReadJournal() {
  return { reads: [], outside: [], total: 0 };
}

// -- filters ---------------------------------------------------------------------

/** An ISO-8601 instant, for the `--since` form that is a time rather than a sequence. */
export const INSTANT_PATTERN = /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?)?Z?$/;

/** @param {unknown} value @returns {boolean} */
function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Normalize the four filters, refusing what cannot be answered rather than guessing.
 *
 * `--since` is answered in SEQUENCE space, and that is a consequence of D-2 rather than a
 * preference: `body` carries no wall clock at all, so a row has no time to compare against.
 * An instant is therefore RESOLVED to a sequence through the log - whose events do carry
 * `written_at` for reporting - and the filter is then applied to `seq`, which NG-4 makes the
 * sole total order. A row the log never recorded has no position in that order and is
 * excluded by `--since`, which is stated rather than discovered.
 *
 * @param {{type?: unknown, project?: unknown, since?: unknown, contains?: unknown}} [input]
 * @returns {Readonly<{ok: boolean, filters: object, problems: ReadonlyArray<string>}>}
 */
export function normalizeFilters(input = {}) {
  const problems = [];

  let type = null;
  if (input.type !== undefined && input.type !== null && String(input.type) !== '') {
    const wanted = String(input.type);
    if (DERIVABLE_CLASSES.includes(wanted)) type = wanted;
    else {
      problems.push(
        `${QUERY_FLAG.TYPE} ${JSON.stringify(wanted)} is not a tracked class; `
        + `the classes are ${DERIVABLE_CLASSES.join(', ')}`,
      );
    }
  }

  const project = input.project === undefined || input.project === null || String(input.project) === ''
    ? null
    : String(input.project);

  let sinceSeq = null;
  let sinceInstant = null;
  if (input.since !== undefined && input.since !== null && String(input.since) !== '') {
    const raw = String(input.since).trim();
    if (/^\d+$/.test(raw)) {
      sinceSeq = Number(raw);
    } else if (INSTANT_PATTERN.test(raw) && !Number.isNaN(Date.parse(raw))) {
      sinceInstant = new Date(raw).toISOString();
    } else {
      problems.push(
        `${QUERY_FLAG.SINCE} ${JSON.stringify(raw)} is neither a log sequence nor an `
        + 'ISO-8601 instant',
      );
    }
  }

  return Object.freeze({
    ok: problems.length === 0,
    filters: Object.freeze({
      type,
      project,
      since_seq: sinceSeq,
      since_instant: sinceInstant,
      contains: normalizeNeedle(input.contains),
    }),
    problems: Object.freeze(problems),
  });
}

/**
 * Parse the frozen CLI shape.
 *
 * @param {ReadonlyArray<string>} argv
 * @returns {Readonly<{ok: boolean, filters: object, cursor: string|null,
 *          page_size: number|null, json: boolean, problems: ReadonlyArray<string>}>}
 */
export function parseQueryArgs(argv = []) {
  const args = (Array.isArray(argv) ? argv : [argv]).map((a) => String(a));
  const problems = [];
  const raw = { type: null, project: null, since: null, contains: null };
  let cursor = null;
  let pageSize = null;
  let json = false;

  for (let i = 0; i < args.length; i += 1) {
    const token = args[i];
    if (token === QUERY_FLAG.JSON) { json = true; continue; }
    if (token === QUERY_STRICT_MODE.flag) {
      // Named, rather than swept into "unknown flag". An operator typing it learned it
      // somewhere, and telling them WHICH verb replaced it is the difference between a
      // correction and a dead end.
      problems.push(QUERY_STRICT_MODE.refusal_text);
      continue;
    }
    if (!QUERY_FLAGS.includes(token)) {
      problems.push(`${JSON.stringify(token)} is not one of ${QUERY_FLAGS.join(' ')}`);
      continue;
    }
    const value = args[i + 1];
    if (value === undefined || QUERY_FLAGS.includes(value)) {
      problems.push(`${token} takes a value and was given none`);
      continue;
    }
    i += 1;
    if (token === QUERY_FLAG.CURSOR) { cursor = value; continue; }
    if (token === QUERY_FLAG.PAGE_SIZE) {
      if (!/^\d+$/.test(value) || Number(value) < 1) {
        problems.push(`${QUERY_FLAG.PAGE_SIZE} ${JSON.stringify(value)} is not a positive integer`);
        continue;
      }
      pageSize = Number(value);
      continue;
    }
    if (token === QUERY_FLAG.TYPE) raw.type = value;
    else if (token === QUERY_FLAG.PROJECT) raw.project = value;
    else if (token === QUERY_FLAG.SINCE) raw.since = value;
    else if (token === QUERY_FLAG.CONTAINS) raw.contains = value;
  }

  const normalized = normalizeFilters(raw);
  return Object.freeze({
    ok: problems.length === 0 && normalized.ok,
    filters: normalized.filters,
    cursor,
    page_size: pageSize,
    json,
    problems: Object.freeze([...problems, ...normalized.problems]),
  });
}

// -- the cursor -------------------------------------------------------------------

/**
 * The token a cursor is bound to: the whole snapshot artifact, hashed.
 *
 * Binding to the ARTIFACT rather than to a row count is what makes the stale case detectable
 * at all. A rebuild replaces the snapshot - even a rebuild that changes no row changes the
 * instant it was computed at - so a cursor issued against the old one no longer addresses the
 * rows it was issued against, and saying so is the difference between an honest refusal and a
 * page that silently skips whatever moved.
 *
 * @param {object|null} snapshotValue @returns {string}
 */
export function indexTokenFor(snapshotValue) {
  return snapshotSha256(canonicalJson({
    v: CURSOR_VERSION,
    snapshot: snapshotValue === undefined ? null : snapshotValue,
  }));
}

/** @param {object} filters @returns {string} the token that binds a cursor to its question */
export function filtersTokenFor(filters) {
  return snapshotSha256(canonicalJson({
    v: CURSOR_VERSION,
    contains_version: CONTAINS_VERSION,
    filters: filters ?? {},
  }));
}

/** @param {object} state @returns {string} */
export function encodeCursor(state) {
  return Buffer.from(canonicalJson(state), 'utf8').toString('base64url');
}

/** @param {unknown} text @returns {object|null} */
export function decodeCursor(text) {
  try {
    const value = JSON.parse(Buffer.from(String(text), 'base64url').toString('utf8'));
    return isPlainObject(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * Is this cursor addressed to this index and this question?
 *
 * @param {unknown} text @param {{index: string, filters: string}} tokens
 * @returns {Readonly<{ok: boolean, state: object|null, reason: string|null}>}
 */
export function validateCursor(text, tokens) {
  const state = decodeCursor(text);
  if (state === null) {
    return Object.freeze({ ok: false, state: null, reason: 'it is not a value this verb issued' });
  }
  if (state.v !== CURSOR_VERSION) {
    return Object.freeze({
      ok: false,
      state,
      reason: `it was issued by ${String(state.v)} and this engine issues ${CURSOR_VERSION}`,
    });
  }
  if (state.index !== tokens.index) {
    return Object.freeze({
      ok: false,
      state,
      reason: 'the snapshot it was issued against has been replaced since',
    });
  }
  if (state.filters !== tokens.filters) {
    return Object.freeze({
      ok: false,
      state,
      reason: 'the filters differ from the ones it was issued for',
    });
  }
  if (!isPlainObject(state.after)) {
    return Object.freeze({ ok: false, state, reason: 'it names no position to carry on from' });
  }
  return Object.freeze({ ok: true, state, reason: null });
}

// -- selection and paging ----------------------------------------------------------

/**
 * Merge the snapshot body's rows with the log tail, by row identity.
 *
 * The tail wins, because its rows are later in the ONE total order. Both sides are shaped by
 * `bodyRow` - the rebuilder's own shaping, imported - so a row is byte-identical whether the
 * caller reached it through the snapshot or through the merge, and a re-materialization
 * therefore cannot change an answer.
 *
 * @param {ReadonlyArray<object>} rows @param {ReadonlyArray<object>} tail
 * @returns {Readonly<{rows: ReadonlyArray<object>, from_body: number, from_tail: number,
 *          replaced: number}>}
 */
export function mergeTail(rows, tail) {
  /** @type {Map<string, object>} */
  const byIdentity = new Map();
  for (const row of rows ?? []) {
    if (!isPlainObject(row)) continue;
    byIdentity.set(rowIdentity(row), row);
  }
  const fromBody = byIdentity.size;
  let fromTail = 0;
  let replaced = 0;

  for (const event of tail ?? []) {
    if (!isDerivedEvent(event)) continue;
    const key = rowIdentity(event);
    if (byIdentity.has(key)) replaced += 1;
    else fromTail += 1;
    byIdentity.set(key, bodyRow(event, event[ORDERING_FIELD]));
  }

  return Object.freeze({
    rows: Object.freeze([...byIdentity.values()].sort(compareRows)),
    from_body: fromBody,
    from_tail: fromTail,
    replaced,
  });
}

/**
 * The freshness one row is answered with.
 *
 * It is a function of the PROJECT's recorded presence and of whether the log carries the row,
 * and of nothing else - deliberately not of which side of the merge the row arrived on. If it
 * varied by source, folding the tail into the body would change the answer, and "results are
 * unchanged across a re-materialization" would be false for a reason no operator could see.
 *
 * @param {object} row @param {object|null} entry the per-project freshness entry, if any
 * @returns {string} a STATUS-v1 freshness code
 */
export function rowFreshness(row, entry) {
  if (isPlainObject(entry)) {
    if (entry.presence !== PRESENCE.LIVE) return FRESHNESS.UNKNOWN;
    return typeof entry.freshness === 'string' ? entry.freshness : FRESHNESS.UNKNOWN;
  }
  // No rebuild has ever reported on this project. A row the log carries was hashed by the
  // write path at the moment its bytes became durable, which is the freshest evidence this
  // system has; a row only a walk ever saw has none, and says so.
  return Number.isFinite(Number(row?.[ORDERING_FIELD])) ? FRESHNESS.FRESH : FRESHNESS.UNKNOWN;
}

/**
 * Apply the filters. ONE implementation, called by both the paged path and the full scan.
 *
 * @param {ReadonlyArray<object>} rows already merged and sorted
 * @param {object} filters from normalizeFilters
 * @returns {Readonly<{rows: ReadonlyArray<object>, truncated_unmatched: ReadonlyArray<object>}>}
 */
export function selectRows(rows, filters) {
  const wanted = filters ?? {};
  const kept = [];
  const cut = [];
  for (const row of rows ?? []) {
    if (wanted.type !== null && wanted.type !== undefined && row.class !== wanted.type) continue;
    if (wanted.project !== null && wanted.project !== undefined
      && String(row.project_id) !== wanted.project) continue;
    if (wanted.since_seq !== null && wanted.since_seq !== undefined) {
      const seq = Number(row[ORDERING_FIELD]);
      if (!Number.isFinite(seq) || seq < wanted.since_seq) continue;
    }
    const verdict = containsMatch(row, wanted.contains ?? null);
    if (verdict.matched) kept.push(row);
    else if (verdict.truncated) cut.push(row);
  }
  return Object.freeze({ rows: Object.freeze(kept), truncated_unmatched: Object.freeze(cut) });
}

/**
 * One page of an ordered row list.
 *
 * Pure, and exported, so the paging property can be exercised over a row set larger than any
 * fixture wants to write to disk: with a strict total order and one entry per identity, "the
 * next N rows after this one" cannot skip a row or serve one twice, and that is checkable
 * directly rather than only through the verb.
 *
 * @param {ReadonlyArray<object>} rows sorted by compareRows
 * @param {{size?: number|null, after?: object|null}} [opts]
 * @returns {Readonly<object>}
 */
export function pageOf(rows, opts = {}) {
  const list = Array.isArray(rows) ? rows : [];
  const cap = CAPS.rows_per_query;
  const requested = Number.isInteger(opts.size) && opts.size > 0 ? opts.size : cap;
  // Bounded by the cap in code, not by an operator's good manners: a caller asking for more
  // than the page cap is served the page cap.
  const size = Math.min(requested, cap);
  const after = isPlainObject(opts.after) ? opts.after : null;

  let start = 0;
  if (after !== null) {
    const found = list.findIndex((row) => compareRows(row, after) > 0);
    start = found === -1 ? list.length : found;
  }
  const page = list.slice(start, start + size);
  const remaining = Math.max(0, list.length - (start + page.length));

  return Object.freeze({
    rows: Object.freeze(page),
    size,
    cap,
    requested,
    clamped: requested > cap,
    start,
    returned: page.length,
    remaining,
    complete: remaining === 0,
    last: page.length === 0 ? null : page[page.length - 1],
  });
}

/** @param {object} row @returns {Readonly<object>} the position a cursor carries */
export function positionOf(row) {
  return Object.freeze({
    project_id: String(row.project_id),
    class: String(row.class),
    path: String(row.path),
    seq: Number.isFinite(Number(row[ORDERING_FIELD])) ? Number(row[ORDERING_FIELD]) : null,
  });
}

// -- the verb -----------------------------------------------------------------------

/**
 * Read the index for a query: the log and the snapshot, and nothing outside the home.
 *
 * @param {object} opts @returns {Readonly<object>}
 */
function readIndex(opts) {
  const paths = indexPathsFrom(opts);
  const journal = newReadJournal();
  const guarded = indexOnlyFs(opts.fsx, paths.home, journal);
  const read = openIndexForRead({ ...opts, paths, fsx: guarded });
  return Object.freeze({ paths, journal, guarded, read });
}

/**
 * `steward query`.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, filters?: object,
 *          type?: string, project?: string, since?: string|number, contains?: string,
 *          cursor?: string|null, page_size?: number|null, now?: number|Date,
 *          rematerialize?: boolean, boundMs?: number, staleMs?: number, lockOpts?: object,
 *          quarantine?: boolean, pid?: number, hostname?: string}} [opts]
 * @returns {Readonly<object>} the query-result-v1
 */
export function queryIndex(opts = {}) {
  const normalized = normalizeFilters(opts.filters ?? opts);
  if (!normalized.ok) {
    return usageResult(indexPathsFrom(opts), normalized.filters, normalized.problems);
  }
  const filters = normalized.filters;
  const paths = indexPathsFrom(opts);

  // A read the facade refuses THROWS rather than returning an outcome, and that is the point:
  // a project-root read on this path is a defect in this engine, not a state of the operator's
  // portfolio, and dressing it up as one would put it in a table the operator cannot act on.
  let state = readIndex({ ...opts, paths });
  let { read, journal } = state;
  if (read.ok !== true) {
    return readFailureResult(paths, filters, read, journal);
  }

  let snapshot = isPlainObject(read.snapshot_value) ? read.snapshot_value : null;
  if (snapshot !== null) {
    const shape = validateSnapshotShape(snapshot);
    if (!shape.ok) {
      return Object.freeze({
        ...emptyResult(paths, filters),
        ok: false,
        outcome: queryOutcome(QUERY_CODE.SNAPSHOT_UNPARSEABLE, {
          path: paths.snapshot,
          reason: shape.problems.map((p) => p.code).join(', '),
        }),
        codes: Object.freeze([QUERY_CODE.SNAPSHOT_UNPARSEABLE]),
        no_walk: noWalkReceipt(journal),
      });
    }
  }

  let events = replayEvents(read.events);
  let freshness = snapshot === null
    ? emptyFreshnessBlock()
    : (isPlainObject(snapshot.freshness) ? snapshot.freshness : emptyFreshnessBlock());
  let headSeq = Number(freshness.head_seq ?? 0);
  let tail = tailAfter(events, headSeq);

  // D-3's bound, applied. Only on a first page: a continuation is served against the snapshot
  // its cursor was issued against, and replacing that snapshot underneath it would invalidate
  // the cursor this call was handed.
  let rematerialized = null;
  const wantsFold = opts.rematerialize !== false
    && (opts.cursor === undefined || opts.cursor === null || opts.cursor === '')
    && shouldRematerialize(tail.length);
  if (wantsFold) {
    rematerialized = rematerializeIndex({
      ...opts,
      paths,
      fsx: state.guarded,
      events,
      body: snapshot === null ? null : snapshot.body ?? null,
      freshness,
      head_seq: headSeq,
      trigger: REMATERIALIZE_TRIGGER.TAIL_CAP,
    });
    if (rematerialized.ok === true) {
      // Re-read, so the answer is served from the artifact that is now on disk rather than
      // from an in-memory copy nobody else can see.
      const again = readIndex({ ...opts, paths });
      if (again.read.ok === true) {
        state = again;
        read = again.read;
        journal = again.journal;
        snapshot = isPlainObject(read.snapshot_value) ? read.snapshot_value : null;
        events = replayEvents(read.events);
        freshness = snapshot === null
          ? emptyFreshnessBlock()
          : (isPlainObject(snapshot.freshness) ? snapshot.freshness : emptyFreshnessBlock());
        headSeq = Number(freshness.head_seq ?? 0);
        tail = tailAfter(events, headSeq);
      }
    }
  }

  const body = snapshot === null || !isPlainObject(snapshot.body) ? {} : snapshot.body;
  const perProject = isPlainObject(freshness.per_project) ? freshness.per_project : {};
  const view = materializeRegistry(events);
  const projectById = new Map(view.projects.map((p) => [p.project_id, p]));

  const merged = mergeTail(Array.isArray(body.rows) ? body.rows : [], tail);

  // --since given as an instant is resolved HERE, against the log's own written_at values,
  // and then answered in sequence space. The log is the only place a wall clock survives.
  const sinceSeq = filters.since_instant === null
    ? filters.since_seq
    : resolveInstantToSeq(events, filters.since_instant);
  const effectiveFilters = Object.freeze({ ...filters, since_seq: sinceSeq });

  const notices = [];
  const tampered = [];
  const damaged = [];
  const answerable = [];

  for (const row of merged.rows) {
    const project = projectById.get(String(row.project_id)) ?? null;
    const entry = Object.prototype.hasOwnProperty.call(perProject, String(row.project_id))
      ? perProject[String(row.project_id)]
      : null;

    // Containment is checked on the RESOLVED path, against the root the log records - a
    // string operation over data already in hand, so it costs no filesystem access. A row
    // that escapes its root is rendered as damage and its content is not served.
    if (project !== null && !containedPath(project.current_path, row.path).ok) {
      tampered.push(Object.freeze({
        project_id: row.project_id,
        class: row.class,
        path: row.path,
        seq: row[ORDERING_FIELD] ?? null,
        status: assertStatusCode(INTEGRITY.TAMPERED, 'query row containment'),
      }));
      notices.push(queryOutcome(QUERY_CODE.ROW_TAMPERED, {
        path: row.path,
        project_id: row.project_id,
      }));
      continue;
    }

    const mojibake = mojibakeInProj(row);
    if (mojibake.damaged) {
      damaged.push(Object.freeze({
        project_id: row.project_id,
        path: row.path,
        field: mojibake.field,
        offset: mojibake.offset,
      }));
      notices.push(queryOutcome(QUERY_CODE.PROJ_MOJIBAKE, {
        path: row.path,
        field: mojibake.field,
        offset: mojibake.offset,
      }));
    }

    answerable.push(Object.freeze({
      ...row,
      presence: isPlainObject(entry) ? entry.presence : null,
      freshness: rowFreshness(row, entry),
      root: project === null ? null : project.current_path,
      proj_mojibake: mojibake.damaged ? mojibake.field : null,
    }));
  }

  const selected = selectRows(answerable, effectiveFilters);
  const matched = selected.rows;

  // -- the unknown contributions, counted rather than described -------------------
  const unknownRows = Array.isArray(body.unknown) ? body.unknown : [];
  const unknownIds = new Set(unknownRows.map((r) => String(r.project_id)));
  for (const id of Object.keys(perProject)) {
    const entry = perProject[id];
    if (isPlainObject(entry) && entry.presence !== PRESENCE.LIVE) unknownIds.add(id);
  }
  const contributions = [];
  for (const id of [...unknownIds].sort()) {
    const entry = isPlainObject(perProject[id]) ? perProject[id] : null;
    const unknownRow = unknownRows.find((r) => String(r.project_id) === id) ?? null;
    const rowsHere = matched.filter((r) => String(r.project_id) === id);
    const classes = [...new Set(rowsHere.map((r) => r.class))].sort();
    contributions.push(Object.freeze({
      project_id: id,
      presence: entry === null ? (unknownRow?.presence ?? null) : entry.presence,
      freshness: FRESHNESS.UNKNOWN,
      last_known_path: unknownRow === null ? (projectById.get(id)?.current_path ?? null) : unknownRow.last_known_path,
      rows: rowsHere.length,
      classes: Object.freeze(classes),
      text: unknownRow === null ? null : unknownRow.text,
    }));
    notices.push(queryOutcome(QUERY_CODE.ROOT_UNKNOWN, {
      project_id: id,
      path: unknownRow === null ? '' : unknownRow.last_known_path,
    }));
    for (const className of classes) {
      notices.push(queryOutcome(queryClassCode(QUERY_CLASS_STEM.UNKNOWN, className), {}, { ok: true }));
    }
  }

  // -- everything else the body already knows and the answer must not hide ---------
  for (const conflict of Array.isArray(body.conflicts) ? body.conflicts : []) {
    notices.push(queryOutcome(QUERY_CODE.IDENTITY_CONFLICT, {
      project_id: conflict.project_id,
      path: (conflict.paths ?? [])[0] ?? '',
      other_path: (conflict.paths ?? [])[1] ?? '',
    }));
  }
  for (const stray of Array.isArray(body.unclassified) ? body.unclassified : []) {
    notices.push(queryOutcome(QUERY_CODE.UNCLASSIFIED, { path: stray.path }));
  }
  for (const hazard of Array.isArray(body.hazards) ? body.hazards : []) {
    const code = HAZARD_ROW[String(hazard.hazard)] ?? null;
    if (code === null) continue;
    notices.push(queryOutcome(code, {
      path: hazard.path,
      target: hazard.target ?? '',
      other_path: '',
    }));
  }
  if (read.torn !== null && read.torn !== undefined) {
    notices.push(queryOutcome(QUERY_CODE.TAIL_TORN, {
      log: paths.log,
      seq: read.head_seq,
    }));
  }

  // -- the page -------------------------------------------------------------------
  const tokens = {
    index: indexTokenFor(snapshot),
    filters: filtersTokenFor(effectiveFilters),
  };
  let after = null;
  let pageIndex = 1;
  if (opts.cursor !== undefined && opts.cursor !== null && opts.cursor !== '') {
    const check = validateCursor(opts.cursor, tokens);
    if (!check.ok) {
      return Object.freeze({
        ...emptyResult(paths, effectiveFilters),
        ok: false,
        outcome: queryOutcome(QUERY_CODE.CURSOR_STALE, { reason: check.reason }),
        codes: Object.freeze([QUERY_CODE.CURSOR_STALE]),
        cursor_reason: check.reason,
        no_walk: noWalkReceipt(journal),
        freshness: freshnessReceipt(freshness, headSeq, tail, events),
      });
    }
    after = check.state.after;
    pageIndex = Number(check.state.page ?? 1) + 1;
  }

  const page = pageOf(matched, { size: opts.page_size ?? null, after });
  // W14: no row leaves this verb unmarked. There is no strict mode to turn this on.
  assertRowsCarryFreshness(page.rows);
  const cursor = page.complete || page.last === null
    ? null
    : encodeCursor({
      v: CURSOR_VERSION,
      index: tokens.index,
      filters: tokens.filters,
      after: positionOf(page.last),
      page: pageIndex,
    });

  const warnings = [];
  for (const [id, observed] of [
    ['rows_per_query', matched.length],
    ['tail_events', tail.length],
    ['events_before_compaction', events.length],
  ]) {
    const status = capStatusFor(id, observed);
    if (status.warn) warnings.push(status);
  }

  let outcome;
  if (matched.length === 0) {
    outcome = effectiveFilters.type === null
      ? queryOutcome(QUERY_CODE.NO_MATCHES, {}, { ok: true })
      : queryOutcome(queryClassCode(QUERY_CLASS_STEM.EMPTY, effectiveFilters.type), {}, { ok: true });
  } else {
    outcome = queryOutcome(QUERY_OK, {
      returned: page.returned,
      matched: matched.length,
      scanned: merged.rows.length,
      tail: tail.length,
      head_seq: headSeq,
    });
  }
  notices.push(outcome);

  return Object.freeze({
    ok: true,
    schema: QUERY_RESULT_SCHEMA,
    version: QUERY_VERSION,
    home: paths.home,
    log: paths.log,
    snapshot: paths.snapshot,
    snapshot_present: snapshot !== null,
    outcome,
    filters: effectiveFilters,
    rows: page.rows,
    matched: matched.length,
    scanned: merged.rows.length,
    page: Object.freeze({
      index: pageIndex,
      size: page.size,
      cap: page.cap,
      requested: page.requested,
      clamped: page.clamped,
      returned: page.returned,
      remaining: page.remaining,
      complete: page.complete,
      cursor,
    }),
    unknown: Object.freeze(contributions),
    tampered: Object.freeze(tampered),
    mojibake: Object.freeze(damaged),
    truncated_unmatched: Object.freeze(
      selected.truncated_unmatched.map((r) => Object.freeze({ project_id: r.project_id, path: r.path })),
    ),
    merge: Object.freeze({
      from_body: merged.from_body,
      from_tail: merged.from_tail,
      replaced: merged.replaced,
    }),
    freshness: freshnessReceipt(freshness, headSeq, tail, events),
    rematerialized: rematerialized === null ? null : Object.freeze({
      ok: rematerialized.ok,
      trigger: rematerialized.trigger,
      fold: rematerialized.fold,
    }),
    warnings: Object.freeze(warnings),
    no_walk: noWalkReceipt(journal),
    notices: Object.freeze(notices),
    codes: Object.freeze([...new Set(notices.map((n) => n.code))].sort()),
  });
}

/**
 * How a body hazard is spoken on the query surface: the W2 hazard codes, imported, mapped to
 * the three query rows that carry a hazard with a returned row. A hazard with no query row -
 * SKIPPED_CYCLE, the walk cap - is deliberately absent rather than folded into the nearest
 * one, which is the laundering NG-2 forbids.
 */
const HAZARD_ROW = Object.freeze({
  [HAZARD.SKIPPED_REPARSE]: QUERY_CODE.SKIPPED_REPARSE,
  [HAZARD.PATH_TOO_LONG]: QUERY_CODE.PATH_TOO_LONG,
  [HAZARD.CASE_COLLISION]: QUERY_CODE.CASE_COLLISION,
});

/**
 * The first sequence at or after an instant, read from the log's `written_at` values.
 *
 * @param {ReadonlyArray<object>} events @param {string} instant
 * @returns {number} a sequence, or one past the head when nothing was written that late
 */
export function resolveInstantToSeq(events, instant) {
  const wanted = Date.parse(instant);
  let head = 0;
  for (const event of events ?? []) {
    const seq = Number(event?.[ORDERING_FIELD]);
    if (Number.isFinite(seq) && seq > head) head = seq;
    const at = Date.parse(String(event?.[WALL_CLOCK_FIELD] ?? ''));
    if (Number.isFinite(at) && at >= wanted) return seq;
  }
  return head + 1;
}

/** @param {object} journal @returns {Readonly<object>} */
function noWalkReceipt(journal) {
  return Object.freeze({
    roots_opened: journal.outside.length,
    refused: Object.freeze([...journal.outside]),
    reads: Object.freeze([...journal.reads]),
    total_reads: journal.total,
    // Stated as data so a test asserts it rather than reading a promise.
    index_home_only: journal.outside.length === 0,
  });
}

/** @param {object} freshness @param {number} headSeq @param {ReadonlyArray<object>} tail
 *  @param {ReadonlyArray<object>} events @returns {Readonly<object>} */
function freshnessReceipt(freshness, headSeq, tail, events) {
  return Object.freeze({
    head_seq: Number(headSeq),
    log_head_seq: events.length === 0 ? 0 : Number(events[events.length - 1][ORDERING_FIELD]),
    head_sha256: freshness.head_sha256 ?? null,
    computed_at: freshness.computed_at ?? null,
    tail_events: tail.length,
    tail_cap: CAPS.tail_events,
    per_project: freshness.per_project ?? {},
  });
}

/** @param {object} paths @param {object} filters @returns {object} */
function emptyResult(paths, filters) {
  return {
    schema: QUERY_RESULT_SCHEMA,
    version: QUERY_VERSION,
    home: paths.home,
    log: paths.log,
    snapshot: paths.snapshot,
    snapshot_present: false,
    filters,
    rows: Object.freeze([]),
    matched: 0,
    scanned: 0,
    page: Object.freeze({
      index: 1,
      size: CAPS.rows_per_query,
      cap: CAPS.rows_per_query,
      requested: CAPS.rows_per_query,
      clamped: false,
      returned: 0,
      remaining: 0,
      complete: false,
      cursor: null,
    }),
    unknown: Object.freeze([]),
    tampered: Object.freeze([]),
    mojibake: Object.freeze([]),
    truncated_unmatched: Object.freeze([]),
    merge: Object.freeze({ from_body: 0, from_tail: 0, replaced: 0 }),
    freshness: Object.freeze({
      head_seq: 0,
      log_head_seq: 0,
      head_sha256: null,
      computed_at: null,
      tail_events: 0,
      tail_cap: CAPS.tail_events,
      per_project: {},
    }),
    rematerialized: null,
    warnings: Object.freeze([]),
    no_walk: Object.freeze({
      roots_opened: 0,
      refused: Object.freeze([]),
      reads: Object.freeze([]),
      total_reads: 0,
      index_home_only: true,
    }),
    notices: Object.freeze([]),
    codes: Object.freeze([]),
  };
}

/** @param {object} paths @param {object} filters @param {ReadonlyArray<string>} problems */
function usageResult(paths, filters, problems) {
  const outcome = queryOutcome(QUERY_USAGE, { reason: problems.join('; ') }, { ok: false });
  return Object.freeze({
    ...emptyResult(paths, filters),
    ok: false,
    outcome,
    problems: Object.freeze([...problems]),
    notices: Object.freeze([outcome]),
    codes: Object.freeze([QUERY_USAGE]),
  });
}

/** @param {object} paths @param {object} filters @param {object} read @param {object} journal */
function readFailureResult(paths, filters, read, journal) {
  const mapped = queryCodeForReadCode(read.code);
  const outcome = mapped === null
    // No query counterpart: the index-read row is passed through as it stands, keeping its
    // own status and its own sentence.
    ? Object.freeze({ ...read, surface: read.surface ?? SURFACE.INDEX_READ })
    : queryOutcome(mapped, {
      home: paths.home,
      errno: read.detail?.errno ?? '',
      path: read.detail?.path ?? paths.snapshot,
      reason: read.detail?.reason ?? read.text ?? '',
      bound_s: read.detail?.bound_s ?? '',
      pid: read.detail?.pid ?? '',
    });
  return Object.freeze({
    ...emptyResult(paths, filters),
    ok: false,
    outcome,
    read_outcome: read,
    no_walk: noWalkReceipt(journal),
    notices: Object.freeze([outcome]),
    codes: Object.freeze([outcome.code]),
  });
}

/**
 * The full-scan oracle: every matching row, in order, with no page applied.
 *
 * It is the SAME selection the paged path performs - `queryIndex` with the page cap out of
 * the way - rather than a second implementation of the question. A test comparing the union
 * of the pages against a second implementation would be comparing two guesses.
 *
 * @param {object} [opts] @see queryIndex @returns {Readonly<object>}
 */
export function queryScan(opts = {}) {
  const first = queryIndex({ ...opts, cursor: null });
  if (first.ok !== true) return first;

  const rows = [...first.rows];
  let cursor = first.page.cursor;
  let guard = 0;
  while (cursor !== null) {
    guard += 1;
    if (guard > CAPS.events_before_compaction) {
      throw new Error('query: the full scan did not terminate within the event ceiling');
    }
    const next = queryIndex({ ...opts, cursor });
    if (next.ok !== true) return next;
    rows.push(...next.rows);
    cursor = next.page.cursor;
  }

  return Object.freeze({
    ...first,
    rows: Object.freeze(rows),
    page: Object.freeze({ ...first.page, returned: rows.length, remaining: 0, complete: true, cursor: null }),
    pages: guard + 1,
  });
}

/**
 * `steward query <flags...>` - the CLI shape.
 *
 * @param {ReadonlyArray<string>} argv @param {object} [opts]
 * @returns {Readonly<object>}
 */
export function query(argv = [], opts = {}) {
  const parsed = parseQueryArgs(argv);
  if (!parsed.ok) return usageResult(indexPathsFrom(opts), parsed.filters, parsed.problems);
  return queryIndex({
    ...opts,
    filters: parsed.filters,
    cursor: parsed.cursor,
    page_size: parsed.page_size,
  });
}

// -- rendering ---------------------------------------------------------------------

/** The columns a rendered row carries, in order. */
export const RENDER_COLUMNS = Object.freeze(['freshness', 'class', 'project_id', 'seq', 'path']);

/** @param {string} value @param {number} width @returns {string} */
function pad(value, width) {
  const text = String(value ?? '');
  return text.length >= width ? text : text + ' '.repeat(width - text.length);
}

/**
 * Render a result for a terminal.
 *
 * TTY and non-TTY differ in ONE way and it is deliberate: a terminal gets aligned columns,
 * and a pipe gets tab-separated fields with no padding, because padding is what makes the
 * output of a query unusable by the next program in the pipe. Nothing is omitted from either
 * form - a row present in one is present in the other.
 *
 * @param {object} result @param {{tty?: boolean, stream?: object}} [opts]
 * @returns {string}
 */
export function renderQuery(result, opts = {}) {
  const stream = opts.stream ?? (typeof process === 'undefined' ? null : process.stdout);
  const tty = opts.tty === undefined ? Boolean(stream && stream.isTTY) : Boolean(opts.tty);
  const lines = [];

  if (result.ok !== true) {
    lines.push(`${result.outcome.code}: ${result.outcome.text}`);
    return `${lines.join('\n')}\n`;
  }

  const rows = result.rows ?? [];
  const widths = RENDER_COLUMNS.map((column) =>
    Math.max(column.length, ...rows.map((row) => String(row[column] ?? '').length), 1));

  if (tty) {
    lines.push(RENDER_COLUMNS.map((c, i) => pad(c, widths[i])).join('  ').trimEnd());
    lines.push(RENDER_COLUMNS.map((c, i) => '-'.repeat(widths[i])).join('  '));
  }
  for (const row of rows) {
    const cells = RENDER_COLUMNS.map((column) => String(row[column] ?? ''));
    lines.push(tty ? cells.map((cell, i) => pad(cell, widths[i])).join('  ').trimEnd() : cells.join('\t'));
  }

  for (const contribution of result.unknown ?? []) {
    lines.push(
      `${contribution.project_id}: ${contribution.rows} row(s) carried at ${contribution.presence}`
      + `/${contribution.freshness} from ${contribution.last_known_path ?? '?'}`,
    );
  }
  for (const warning of result.warnings ?? []) lines.push(warning.text);
  for (const entry of result.mojibake ?? []) {
    lines.push(`${entry.path}: ${entry.field} carries damaged bytes at offset ${entry.offset}`);
  }

  lines.push(result.outcome.text);
  if (result.page.cursor !== null) {
    lines.push(
      `page ${result.page.index}: ${result.page.returned} of ${result.matched} row(s), `
      + `${result.page.remaining} not shown at a page size of ${result.page.size}. `
      + `Re-run with ${QUERY_FLAG.CURSOR} ${result.page.cursor}`,
    );
  } else {
    lines.push(`page ${result.page.index}: ${result.page.returned} row(s), and none remain.`);
  }

  return `${lines.join('\n')}\n`;
}

/** @returns {string} the frozen usage block, composed from the flag table */
export function queryUsage() {
  const lines = [`steward ${QUERY_VERB} [flags]`];
  for (const flag of QUERY_FLAGS) lines.push(`  ${pad(flag, 12)} ${QUERY_FLAG_HELP[flag]}`);
  lines.push(`  searched by ${QUERY_FLAG.CONTAINS}: ${describeContains()}`);
  return lines.join('\n');
}

/** Re-exported so a caller needs one import to ask the shared question. */
export { containsMatch };

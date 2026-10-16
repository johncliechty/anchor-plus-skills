/**
 * W18 - checkpoint-row-v1: how a DERIVED lineage survives compaction.
 *
 * WHY THIS SHAPE, AND WHY IT IS D-4 RATHER THAN THE OTHER BRANCH. The event ceiling (C6) says
 * the log cannot grow forever. The North Star says every receipt, instrument and roadmap event
 * the steward has EVER written stays findable and verifiable. Those two sentences meet exactly
 * here, and round 1 left the meeting unresolved. D-4 resolved it by choosing:
 *
 *     the compacted log keeps the LATEST version of a file verbatim, and keeps the IDENTITY,
 *     HASH and ORDER of every version before it.
 *
 * and by DELETING the other branch - "fold superseded DERIVED away entirely, keep only the
 * latest row" - because that branch contradicts the North Star sentence as written. So a
 * checkpoint row is not a summary. It is the latest row, unchanged, wearing a lineage:
 *
 *     {t:'checkpoint', v:1, class, row:<the latest DERIVED event, VERBATIM>,
 *      superseded:[{seq, sha256, byte_len, written_at}, ...], retired_seq}
 *
 * THE COST, STATED RATHER THAN BURIED. Only the latest BODY bytes are carried forward. A
 * superseded version stays findable (it has an identity, a path and a place in the total
 * order) and verifiable (it has its hash and its byte length), and it is NOT recoverable from
 * the index alone - its body was retired with the segment. That residual is NS-Q1 in the plan
 * and it is the user's call, not this module's. What this module guarantees is the half that
 * is inside its power: nothing that was ever written loses its LINEAGE.
 *
 * `row` IS THE EVENT, NOT A COPY OF ITS FIELDS. The inner row keeps its own `seq` and
 * `written_at` - the two fields the append primitive allocates - which is what makes
 * expandCheckpoints() below able to hand back the ORIGINAL event object rather than a
 * reconstruction of it. That is the whole mechanism behind "a rebuild from the compacted log
 * alone is byte-equivalent": the rebuilder is handed the same events it would have been handed
 * before compaction, so it cannot produce a different body even in principle.
 *
 * THE CHECKPOINT SITS AT THE LATEST ROW'S OWN SEQ. It is not appended at the head and it
 * allocates nothing: it replaces the latest DERIVED event in place, at that event's sequence
 * and with that event's wall clock. Two consequences, both wanted. The compacted log's total
 * order is the order it always had, with holes where retired bodies used to be (NG-4 tolerates
 * holes; `seq` still orders, it simply no longer counts). And compaction reads no clock, so it
 * is deterministic: compacting the same log twice produces the same bytes.
 *
 * BOUNDEDNESS, AND WHAT HAPPENS AT THE BOUND. `superseded` is capped at
 * caps.superseded_entries. Past the cap the OLDEST entries are the ones that go, because the
 * lineage nearest the surviving body is the lineage an operator is actually tracing, and the
 * omission is REPORTED - a count and the exact seq range that was dropped - so it is never a
 * silent shrink. A list sitting exactly at the cap is a floor rather than a total, and
 * `atCapCheckpoints()` is what lets `steward doctor` say so from the compacted log alone.
 *
 * A LEAF, ON PURPOSE. This module imports the two framing field names, the caps and the status
 * vocabulary, and nothing else - in particular it does NOT import derive.mjs, so derive.mjs
 * can import THIS one and fold checkpoints back into a DERIVED history for every consumer at a
 * single call site. Two modules that each unfolded checkpoints their own way would be the fork
 * derive.mjs exists to prevent, one layer up.
 *
 * Stdlib only.
 */

import { ORDERING_FIELD, WALL_CLOCK_FIELD } from '../append-log.mjs';
import { CAPS } from './caps.mjs';
import { INTEGRITY, assertStatusCode } from './status.mjs';

/** The frozen schema id. Changing a field below means checkpoint-row-v2 and a ratification. */
export const CHECKPOINT_SCHEMA = 'checkpoint-row-v1';

/** The event's type tag, as it sits in the log's `t` field. */
export const CHECKPOINT_EVENT_TYPE = 'checkpoint';

/** The row version, as it sits in `v`. */
export const CHECKPOINT_ROW_VERSION = 1;

/**
 * The closed field set, minus the two the append primitive owns (`seq`, `written_at`). Stated
 * as data so a test can enumerate the shape rather than restate it, and so a field added by a
 * later wave is a visible edit here.
 */
export const CHECKPOINT_FIELDS = Object.freeze([
  't',
  'v',
  'class',
  'row',
  'superseded',
  'retired_seq',
]);

/** One lineage entry: identity, hash and order for a version whose body was retired. */
export const SUPERSEDED_FIELDS = Object.freeze(['seq', 'sha256', 'byte_len', 'written_at']);

/** The fields a checkpoint's inner row must carry for the lineage to mean anything. */
export const REQUIRED_ROW_FIELDS = Object.freeze([
  ORDERING_FIELD,
  'class',
  'project_id',
  'path',
  'sha256',
]);

/** The refusals this module raises when handed something that is not a checkpoint row. */
export const CHECKPOINT_REFUSAL = Object.freeze({
  NOT_AN_OBJECT: 'CHECKPOINT_NOT_AN_OBJECT',
  TYPE_MISMATCH: 'CHECKPOINT_TYPE_MISMATCH',
  VERSION_MISMATCH: 'CHECKPOINT_VERSION_MISMATCH',
  UNKNOWN_FIELD: 'CHECKPOINT_UNKNOWN_FIELD',
  FIELD_MISSING: 'CHECKPOINT_FIELD_MISSING',
  ROW_MALFORMED: 'CHECKPOINT_ROW_MALFORMED',
  CLASS_DISAGREES: 'CHECKPOINT_CLASS_DISAGREES',
  SUPERSEDED_MALFORMED: 'CHECKPOINT_SUPERSEDED_MALFORMED',
  SUPERSEDED_UNORDERED: 'CHECKPOINT_SUPERSEDED_UNORDERED',
  SUPERSEDED_AFTER_ROW: 'CHECKPOINT_SUPERSEDED_AFTER_ROW',
  RETIRED_SEQ_MALFORMED: 'CHECKPOINT_RETIRED_SEQ_MALFORMED',
  EMPTY_HISTORY: 'CHECKPOINT_EMPTY_HISTORY',
});

/** @param {unknown} value @returns {boolean} */
function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** @param {string} code @param {string} field @param {string} detail @returns {Readonly<object>} */
function problem(code, field, detail) {
  return Object.freeze({
    code,
    field,
    detail,
    status: assertStatusCode(INTEGRITY.UNPARSEABLE, `checkpoint refusal ${code}`),
    text: `${code}: ${detail}`,
  });
}

// -- recognition ---------------------------------------------------------------

/**
 * Is this log event a checkpoint row?
 *
 * Shape only, deliberately: the same kind of predicate `isDerivedEvent` is, so the two can be
 * asked in either order about any event without one of them throwing on the other's input.
 *
 * @param {unknown} event @returns {boolean}
 */
export function isCheckpointEvent(event) {
  return (
    isPlainObject(event)
    && event.t === CHECKPOINT_EVENT_TYPE
    && Number(event.v) === CHECKPOINT_ROW_VERSION
    && isPlainObject(event.row)
    && Array.isArray(event.superseded)
  );
}

/**
 * The DERIVED event a checkpoint folds, verbatim, or null when this is not a checkpoint.
 *
 * The object returned is the one that was parsed out of the log line, not a rebuilt copy, so
 * every consumer downstream sees exactly the event the pre-compaction log carried.
 *
 * @param {unknown} event @returns {object|null}
 */
export function checkpointRowOf(event) {
  return isCheckpointEvent(event) ? /** @type {any} */ (event).row : null;
}

/**
 * The lineage a checkpoint carries, or an empty list for anything else.
 *
 * @param {unknown} event @returns {ReadonlyArray<object>}
 */
export function supersededOf(event) {
  return isCheckpointEvent(event)
    ? Object.freeze([.../** @type {any} */ (event).superseded])
    : Object.freeze([]);
}

/**
 * Replace every checkpoint in a stream with the DERIVED event it folds, leaving everything
 * else untouched and in place.
 *
 * This is the ONE unfolding in the system. derive.mjs calls it so that every consumer of a
 * DERIVED history - the rebuilder, the verifier, the write path's lineage lookup - sees a
 * compacted log exactly as it saw the log it replaced, without any of them knowing that
 * compaction happened.
 *
 * @param {ReadonlyArray<object>} events @returns {Array<object>}
 */
export function expandCheckpoints(events) {
  const out = [];
  for (const event of events ?? []) {
    const row = checkpointRowOf(event);
    out.push(row === null ? event : row);
  }
  return out;
}

/** @param {ReadonlyArray<object>} events @returns {ReadonlyArray<object>} the checkpoints */
export function checkpointsIn(events) {
  return Object.freeze((events ?? []).filter((event) => isCheckpointEvent(event)));
}

// -- building ------------------------------------------------------------------

/** @param {object} row @returns {Readonly<object>} one lineage entry, in the frozen field order */
export function supersededEntryFor(row) {
  return Object.freeze({
    seq: Number(row?.[ORDERING_FIELD]),
    sha256: String(row?.sha256 ?? ''),
    byte_len: Number(row?.byte_len ?? 0),
    written_at: row?.[WALL_CLOCK_FIELD] === undefined ? null : String(row[WALL_CLOCK_FIELD]),
  });
}

/**
 * Merge two lineage lists into one, in seq order, with no version named twice.
 *
 * RE-COMPACTION IS WHY THIS EXISTS. A log that has been compacted once already carries
 * checkpoints, and compacting it again must not throw away the lineage the first pass
 * preserved. So the prior list and the newly-retired versions are merged rather than replaced,
 * and the dedupe is on `seq` because `seq` is the sole total order and therefore the only
 * identity a retired version still has.
 *
 * @param {ReadonlyArray<object>} left @param {ReadonlyArray<object>} right
 * @returns {Array<object>}
 */
export function mergeSuperseded(left, right) {
  const bySeq = new Map();
  for (const entry of [...(left ?? []), ...(right ?? [])]) {
    const seq = Number(entry?.seq);
    if (!Number.isInteger(seq)) continue;
    if (!bySeq.has(seq)) bySeq.set(seq, Object.freeze({ ...entry, seq }));
  }
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/**
 * Build one checkpoint-row-v1 from a file's whole DERIVED history.
 *
 * @param {{history: ReadonlyArray<object>, retired_seq: number,
 *          prior_superseded?: ReadonlyArray<object>, cap?: number}} req
 *   `history` is the seq-ordered list of DERIVED events for ONE (project_id, path), oldest
 *   first. `cap` is an injection seam for the tests: the shipped bound is
 *   caps.superseded_entries, and a test that had to write 257 real files to reach it would
 *   never be written, which is how an overflow path ships unexercised.
 * @returns {Readonly<{event: object, overflow: Readonly<object>|null,
 *          superseded_total: number, superseded_kept: number}>}
 */
export function makeCheckpointRow(req) {
  const history = [...(req?.history ?? [])].sort(
    (a, b) => Number(a?.[ORDERING_FIELD]) - Number(b?.[ORDERING_FIELD]),
  );
  if (history.length === 0) {
    throw new Error(
      `${CHECKPOINT_REFUSAL.EMPTY_HISTORY}: a checkpoint row folds a file's versions and there `
      + 'must be at least one of them - the latest is carried verbatim and is not optional.',
    );
  }

  const cap = Number.isInteger(req?.cap) && req.cap >= 0
    ? Number(req.cap)
    : CAPS.superseded_entries;
  const latest = history[history.length - 1];

  const lineage = mergeSuperseded(
    req?.prior_superseded ?? [],
    history.slice(0, -1).map((row) => supersededEntryFor(row)),
  );

  const total = lineage.length;
  const omitted = Math.max(0, total - cap);
  // The OLDEST go first: the versions nearest the surviving body are the ones an operator is
  // tracing when they ask what this file used to be.
  const kept = omitted === 0 ? lineage : lineage.slice(omitted);
  const dropped = omitted === 0 ? [] : lineage.slice(0, omitted);

  const event = {
    // The framing fields FIRST and with the latest row's own values: the checkpoint takes the
    // place of that event in the total order rather than being appended after it, and it reads
    // no clock, so compacting the same log twice yields the same bytes.
    [ORDERING_FIELD]: Number(latest[ORDERING_FIELD]),
    [WALL_CLOCK_FIELD]: latest[WALL_CLOCK_FIELD] === undefined
      ? null
      : String(latest[WALL_CLOCK_FIELD]),
    t: CHECKPOINT_EVENT_TYPE,
    v: CHECKPOINT_ROW_VERSION,
    class: String(latest.class),
    // VERBATIM. Not projected, not re-derived, not re-hashed: the typed row with its `proj`
    // intact, so unfolding it hands the rebuilder the event the old log carried.
    row: latest,
    superseded: Object.freeze(kept),
    retired_seq: Number(req?.retired_seq ?? latest[ORDERING_FIELD]),
  };

  const overflow = omitted === 0 ? null : Object.freeze({
    project_id: String(latest.project_id),
    class: String(latest.class),
    path: String(latest.path),
    seq: Number(latest[ORDERING_FIELD]),
    cap,
    total,
    kept: kept.length,
    omitted,
    from_seq: dropped[0].seq,
    to_seq: dropped[dropped.length - 1].seq,
  });

  return Object.freeze({
    event,
    overflow,
    superseded_total: total,
    superseded_kept: kept.length,
  });
}

// -- validation ----------------------------------------------------------------

/**
 * Validate a candidate checkpoint row, reporting EVERY problem rather than the first.
 *
 * Same discipline as the commit-intent and commit-ack validators: an operator or a fixture
 * author repairing a hand-written row should learn everything wrong with it in one pass.
 *
 * @param {unknown} value
 * @returns {{ok: boolean, checkpoint: object|null, problems: ReadonlyArray<object>}}
 */
export function validateCheckpointRow(value) {
  const problems = [];

  if (!isPlainObject(value)) {
    problems.push(problem(
      CHECKPOINT_REFUSAL.NOT_AN_OBJECT,
      '',
      `a ${CHECKPOINT_SCHEMA} is a JSON object; got ${Array.isArray(value) ? 'an array' : typeof value}`,
    ));
    return { ok: false, checkpoint: null, problems: Object.freeze(problems) };
  }

  const record = /** @type {Record<string, unknown>} */ (value);
  const framing = new Set([ORDERING_FIELD, WALL_CLOCK_FIELD]);

  for (const key of Object.keys(record)) {
    if (framing.has(key) || CHECKPOINT_FIELDS.includes(key)) continue;
    problems.push(problem(
      CHECKPOINT_REFUSAL.UNKNOWN_FIELD,
      key,
      `${CHECKPOINT_SCHEMA} is a closed field set and carries no '${key}'`,
    ));
  }
  for (const key of CHECKPOINT_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(record, key) || record[key] === undefined) {
      problems.push(problem(CHECKPOINT_REFUSAL.FIELD_MISSING, key, `${key} is absent`));
    }
  }

  if (record.t !== undefined && record.t !== CHECKPOINT_EVENT_TYPE) {
    problems.push(problem(
      CHECKPOINT_REFUSAL.TYPE_MISMATCH,
      't',
      `expected ${CHECKPOINT_EVENT_TYPE}, got ${JSON.stringify(record.t)}`,
    ));
  }
  if (record.v !== undefined && Number(record.v) !== CHECKPOINT_ROW_VERSION) {
    problems.push(problem(
      CHECKPOINT_REFUSAL.VERSION_MISMATCH,
      'v',
      `this engine reads v${CHECKPOINT_ROW_VERSION}; got ${JSON.stringify(record.v)}`,
    ));
  }

  const row = record.row;
  let rowSeq = null;
  if (row !== undefined) {
    if (!isPlainObject(row)) {
      problems.push(problem(
        CHECKPOINT_REFUSAL.ROW_MALFORMED,
        'row',
        'the folded row must be the DERIVED event itself, carried verbatim',
      ));
    } else {
      for (const field of REQUIRED_ROW_FIELDS) {
        if (row[field] === undefined || row[field] === null) {
          problems.push(problem(
            CHECKPOINT_REFUSAL.ROW_MALFORMED,
            `row.${field}`,
            `the folded row carries no ${field}, so the version it preserves cannot be `
            + 'identified or verified - which is the whole of what a checkpoint is for',
          ));
        }
      }
      if (Number.isInteger(row[ORDERING_FIELD])) rowSeq = Number(row[ORDERING_FIELD]);
      if (record.class !== undefined && row.class !== undefined && record.class !== row.class) {
        problems.push(problem(
          CHECKPOINT_REFUSAL.CLASS_DISAGREES,
          'class',
          `the checkpoint says ${JSON.stringify(record.class)} and the row it folds says `
          + `${JSON.stringify(row.class)}; a checkpoint may not re-label the row it carries`,
        ));
      }
    }
  }

  if (record.superseded !== undefined) {
    if (!Array.isArray(record.superseded)) {
      problems.push(problem(
        CHECKPOINT_REFUSAL.SUPERSEDED_MALFORMED,
        'superseded',
        'the lineage is a list, even when it is empty - an absent list and an empty one would '
        + 'be two shapes of "this file was written once"',
      ));
    } else {
      let previous = null;
      record.superseded.forEach((entry, at) => {
        if (!isPlainObject(entry)) {
          problems.push(problem(
            CHECKPOINT_REFUSAL.SUPERSEDED_MALFORMED,
            `superseded[${at}]`,
            'each lineage entry is an object',
          ));
          return;
        }
        for (const key of Object.keys(entry)) {
          if (!SUPERSEDED_FIELDS.includes(key)) {
            problems.push(problem(
              CHECKPOINT_REFUSAL.SUPERSEDED_MALFORMED,
              `superseded[${at}].${key}`,
              `a lineage entry is {${SUPERSEDED_FIELDS.join(', ')}} and carries no '${key}'`,
            ));
          }
        }
        for (const key of SUPERSEDED_FIELDS) {
          if (!Object.prototype.hasOwnProperty.call(entry, key)) {
            problems.push(problem(
              CHECKPOINT_REFUSAL.SUPERSEDED_MALFORMED,
              `superseded[${at}].${key}`,
              `${key} is absent; without it this version is no longer identifiable by hash and `
              + 'order, which is the one thing compaction promised to keep',
            ));
          }
        }
        const seq = Number(entry.seq);
        if (!Number.isInteger(seq)) {
          problems.push(problem(
            CHECKPOINT_REFUSAL.SUPERSEDED_MALFORMED,
            `superseded[${at}].seq`,
            `${JSON.stringify(entry.seq)} is not an integer sequence`,
          ));
          return;
        }
        if (previous !== null && seq <= previous) {
          problems.push(problem(
            CHECKPOINT_REFUSAL.SUPERSEDED_UNORDERED,
            `superseded[${at}].seq`,
            `${seq} does not follow ${previous}. The lineage is in total order because the order `
            + 'is half of what it preserves',
          ));
        }
        if (rowSeq !== null && seq >= rowSeq) {
          problems.push(problem(
            CHECKPOINT_REFUSAL.SUPERSEDED_AFTER_ROW,
            `superseded[${at}].seq`,
            `${seq} is at or after the surviving row's ${rowSeq}; a superseded version comes `
            + 'BEFORE the version that superseded it',
          ));
        }
        previous = seq;
      });
    }
  }

  if (record.retired_seq !== undefined
    && (!Number.isInteger(record.retired_seq) || /** @type {number} */ (record.retired_seq) < 0)) {
    problems.push(problem(
      CHECKPOINT_REFUSAL.RETIRED_SEQ_MALFORMED,
      'retired_seq',
      `${JSON.stringify(record.retired_seq)} is not a sequence. retired_seq is the compaction `
      + 'boundary - the point at or below which superseded BODIES were retired - so a reader '
      + 'can tell which segment to go looking in.',
    ));
  }

  if (problems.length > 0) return { ok: false, checkpoint: null, problems: Object.freeze(problems) };
  return { ok: true, checkpoint: /** @type {any} */ (record), problems: Object.freeze([]) };
}

// -- what doctor reads ---------------------------------------------------------

/**
 * Checkpoints whose lineage list is sitting AT the cap.
 *
 * This is the honest signal available from a compacted log ALONE. The exact omission - how
 * many versions went and which seq range they occupied - is recorded in the compaction receipt
 * at the moment it happened, because the frozen checkpoint-row-v1 field set has nowhere to put
 * it and inventing a field would be a schema change dressed up as a bug fix. What the log can
 * still say by itself is "this list is a floor, not a total", and saying that is the
 * difference between a bounded lineage and a lineage that quietly lost its tail.
 *
 * @param {ReadonlyArray<object>} events @param {{cap?: number}} [opts]
 * @returns {ReadonlyArray<Readonly<object>>}
 */
export function atCapCheckpoints(events, opts = {}) {
  const cap = Number.isInteger(opts.cap) ? Number(opts.cap) : CAPS.superseded_entries;
  const out = [];
  for (const event of checkpointsIn(events)) {
    if (event.superseded.length < cap) continue;
    out.push(Object.freeze({
      project_id: String(event.row?.project_id ?? ''),
      class: String(event.class),
      path: String(event.row?.path ?? ''),
      seq: Number(event[ORDERING_FIELD]),
      cap,
      kept: event.superseded.length,
      retired_seq: Number(event.retired_seq),
    }));
  }
  return Object.freeze(out);
}

/**
 * Every version of every file the compacted log can still account for, by identity.
 *
 * Counting rather than describing, because "nothing ever written loses its lineage" is a claim
 * about a number: the versions a checkpoint accounts for is its lineage plus the one body it
 * kept, and a test can compare that against the count the pre-compaction log carried.
 *
 * @param {ReadonlyArray<object>} events
 * @returns {ReadonlyArray<Readonly<object>>} one entry per checkpoint, sorted by seq
 */
export function lineageIn(events) {
  return Object.freeze(
    checkpointsIn(events)
      .map((event) => Object.freeze({
        project_id: String(event.row?.project_id ?? ''),
        class: String(event.class),
        path: String(event.row?.path ?? ''),
        seq: Number(event[ORDERING_FIELD]),
        retired_seq: Number(event.retired_seq),
        superseded: Object.freeze([...event.superseded]),
        // The surviving body counts as a version: it is the one whose bytes are still here.
        versions: event.superseded.length + 1,
      }))
      .sort((a, b) => a.seq - b.seq),
  );
}

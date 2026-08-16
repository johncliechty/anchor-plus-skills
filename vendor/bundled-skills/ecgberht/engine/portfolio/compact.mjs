/**
 * W18 - `steward compact`: the event ceiling, paid for without burning the audit trail.
 *
 * THE TWO SENTENCES THIS VERB SITS BETWEEN. C6 says the log has a ceiling; C7 says the
 * durability contract is auditable, and the North Star says every item ever written stays
 * findable and verifiable. A compaction that folded the log down to "current state" would
 * satisfy the first and quietly refute the other two, and it would do so in the one artifact
 * that is append-only precisely so nobody can revise it. So this verb is built around a single
 * discipline: it never DECIDES anything away, it only moves bodies out of the head.
 *
 *   NATIVE events (registration, reconcile, commit-intents, acks, bundle-exports) are carried
 *   forward BYTE FOR BYTE. Not re-serialized from a parsed object - the original line, exactly
 *   as it sits on disk. They are the only record of membership and of what durability was
 *   promised and honoured, and there is no summary of them that is not a loss.
 *
 *   DERIVED events fold, per D-4, into ONE checkpoint-row-v1 per (project_id, path): the
 *   latest row verbatim, plus {seq, sha256, byte_len, written_at} for EVERY version before it.
 *   Identity, hash and total order survive; only superseded BODIES are retired. That residual
 *   is NS-Q1 and it is the user's call, stated on every run rather than discovered later.
 *
 *   An event this engine does not recognise is carried forward verbatim too. A compactor that
 *   dropped what it could not classify would be a compactor that gets less safe as the schema
 *   grows, which is the opposite of what a long-lived log needs.
 *
 * THE CHECKPOINT IS WRITTEN INTO THE HEAD, NOT INTO THE SNAPSHOT. The plan says this in so
 * many words and it is worth restating where the code is: the snapshot is DERIVED and
 * DELETABLE (C1), so a lineage that lived only there would be one `rm` from gone. The
 * checkpoint rows are log events, in the log, in the same total order as everything else.
 *
 * HOW THE BYTES MOVE, AND WHY NOTHING IS EVER MISSING. Compaction cannot be an append - it is
 * the one operation that shortens the log - so it is a REPLACEMENT, and the order of
 * operations is the whole safety argument:
 *
 *   1. the compacted head is assembled at `<log>.compacting-<seq>`, one line at a time through
 *      the D-1 append primitive, each line fsynced before the next is written;
 *   2. the live log is COPIED to `<log>.retired-<seq>` and that copy is fsynced;
 *   3. the staged head is renamed over the live log, which is atomic-replace on this platform.
 *
 * Crash after 1: an orphan staging file and an untouched log. Crash after 2: a duplicate of
 * the log beside the log. Crash after 3: done. At no instant is there no live log, and at no
 * instant have the old bytes gone anywhere. This is NOT the D-1 loser branch: that branch
 * proposed rewriting the whole log ONCE PER APPEND, which is O(log size) per event forever.
 * Compaction runs once per ceiling, is the only operation whose job is to replace the file,
 * and touches `writeFileAtomicSync` nowhere - test/w50-write-primitive-lint.test.mjs still
 * holds over this module.
 *
 * RETIRED SEGMENTS ARE NOT DELETED HERE. `compactLog` retires; `deleteRetiredSegment` deletes,
 * and only when all THREE frozen preconditions hold:
 *
 *   (a) the compacted head is fsynced and still hashes to what compaction wrote;
 *   (b) a verification rebuild FROM THE COMPACTED LOG ALONE passes;
 *   (c) the head's commit-intent has been ACKNOWLEDGED by Anchor.
 *
 * (c) is the one operators will meet: a DEGRADED portfolio has not got its last receipt off
 * the box, and deleting the segment that still holds the old bodies would make local disk the
 * only copy of a history nothing has confirmed. The refusal is a named row carrying the W15
 * banner, and the segment stays exactly where it was.
 *
 * DETERMINISM. This verb reads no clock. A checkpoint takes the seq and the wall clock of the
 * row it folds, so compacting the same log twice produces the same bytes, and a compaction can
 * be compared byte for byte against itself the way every other artifact in this system can.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  EMPTY_HEAD_SEQ,
  INDEX_READ_CODE,
  INDEX_WRITE_CODE,
  ORDERING_FIELD,
  appendLineAt,
  ensureIndexHome,
  indexPathsFrom,
  isIndexRefusal,
  logEventLine,
  readLogBytes,
  readLogHead,
  replayEvents,
  scanLogBytes,
  withPortfolioLock,
} from '../append-log.mjs';
import { commitIntentsIn, durabilityHealth, intentLedger } from './anchor-contract.mjs';
import { CAPS, capStatusFor, warningThreshold } from './caps.mjs';
import { SURFACE, rowOutcome, rowsForSurface } from './failure-tables.mjs';
import {
  CHECKPOINT_SCHEMA,
  atCapCheckpoints,
  checkpointsIn,
  isCheckpointEvent,
  lineageIn,
  makeCheckpointRow,
  supersededOf,
  validateCheckpointRow,
} from './checkpoint.mjs';
import { hashBytes } from './commit-intent.mjs';
import { isDerivedEvent, rowIdentity } from './derive.mjs';
import {
  compactStagingPathFor,
  retiredSegmentPathFor,
  retiredSegmentSeqOf,
} from './home.mjs';
import { openablePath } from './inventory.mjs';
import { rebuildIndex } from './rebuild.mjs';
import { isNativeEvent } from './registry.mjs';
import {
  COMPOSITE,
  FRESHNESS,
  INTEGRITY,
  PRESENCE,
  assertStatusCode,
} from './status.mjs';

/** The frozen version. Changing what compaction keeps or how it stages means compact-v2. */
export const COMPACT_VERSION = 'compact-v1';

/** The verb's name, as an operator types it. Spelled once; every surface reads it. */
export const COMPACT_VERB = 'compact';

/** The failure table this verb speaks from. W3 deferred it; W19 shipped it. */
export const COMPACT_SURFACE = SURFACE.COMPACT;

/** The receipt this verb hands its caller. */
export const COMPACT_RECEIPT_SCHEMA = 'compaction-receipt-v1';

/** The receipt the retirement verb hands its caller. */
export const RETIRED_DELETE_RECEIPT_SCHEMA = 'retired-segment-deletion-receipt-v1';

/** The cap whose ceiling triggers this verb. Read, never restated. */
export const COMPACT_TRIGGER_CAP = 'events_before_compaction';

/**
 * What compaction keeps, as data rather than as prose, so a reviewer can enumerate the policy
 * instead of reading the loop.
 */
export const COMPACT_POLICY = Object.freeze({
  NATIVE: 'carried forward BYTE FOR BYTE as the head of the compacted log',
  DERIVED_LATEST: `folded into a ${CHECKPOINT_SCHEMA}, verbatim, with its typed shape and proj intact`,
  DERIVED_SUPERSEDED:
    'kept as {seq, sha256, byte_len, written_at} lineage inside that checkpoint - identity, '
    + 'hash and order survive, only the BODY bytes are retired (NS-Q1)',
  UNRECOGNISED: 'carried forward verbatim; this engine never drops bytes it cannot classify',
});

/**
 * The residual D-4 accepts, in the operator's words. It rides on every outcome for the same
 * reason W17's strength sentence does: a bound that is mentioned when convenient is a bound
 * nobody was told about on the run that mattered.
 */
export const COMPACT_RESIDUAL_SENTENCE =
  'Every version ever written keeps its sequence, its hash and its place in the order; only '
  + 'superseded BODIES are retired with the segment, so a superseded version stays findable and '
  + 'verifiable but is not recoverable from the index alone.';

// -- the rows ------------------------------------------------------------------

/** The outcomes this verb reports. Every one is a named row, never a thrown surprise. */
export const COMPACT_CODE = Object.freeze({
  OK: 'COMPACT_OK',
  EMPTY: 'COMPACT_EMPTY',
  NOT_DUE: 'COMPACT_NOT_DUE',
  NOTHING_TO_FOLD: 'COMPACT_NOTHING_TO_FOLD',
  LOG_ABSENT: 'COMPACT_LOG_ABSENT',
  LOG_UNREADABLE: 'COMPACT_LOG_UNREADABLE',
  HEAD_WRITE_FAILED: 'COMPACT_HEAD_WRITE_FAILED',
  RETIRE_FAILED: 'COMPACT_RETIRE_FAILED',
  SEGMENT_EXISTS: 'COMPACT_SEGMENT_EXISTS',
  SUPERSEDED_OVERFLOW: 'COMPACT_SUPERSEDED_OVERFLOW',
  CHECKPOINT_MALFORMED: 'COMPACT_CHECKPOINT_MALFORMED',
  REBUILD_FAILED: 'COMPACT_REBUILD_FAILED',
  CEILING_WARNING: 'COMPACT_CEILING_WARNING',
});

/** The outcomes the retirement verb reports. */
export const RETIRED_CODE = Object.freeze({
  DELETED: 'COMPACT_RETIRED_SEGMENT_DELETED',
  ALREADY_DELETED: 'COMPACT_RETIRED_SEGMENT_ALREADY_DELETED',
  HEAD_NOT_DURABLE: 'COMPACT_RETIRED_DELETE_HEAD_NOT_DURABLE',
  REBUILD_FAILED: 'COMPACT_RETIRED_DELETE_REBUILD_FAILED',
  INTENT_UNACKED: 'COMPACT_RETIRED_DELETE_INTENT_UNACKED',
  NO_INTENT: 'COMPACT_RETIRED_DELETE_NO_INTENT',
  DELETE_FAILED: 'COMPACT_RETIRED_DELETE_FAILED',
});

/**
 * The three frozen preconditions, as data. A test enumerates this list rather than restating
 * it, so a precondition that is quietly dropped from the code fails a count instead of
 * disappearing into a diff.
 */
export const RETIRED_PRECONDITION = Object.freeze({
  HEAD_FSYNCED: 'HEAD_FSYNCED',
  REBUILD_PASSES: 'REBUILD_FROM_COMPACTED_LOG_ALONE_PASSES',
  HEAD_INTENT_ACKED: 'HEAD_COMMIT_INTENT_ANCHOR_ACKED',
});

/** @type {ReadonlyArray<string>} quietest first is meaningless here; this is the check ORDER. */
export const RETIRED_PRECONDITIONS = Object.freeze([
  RETIRED_PRECONDITION.HEAD_FSYNCED,
  RETIRED_PRECONDITION.HEAD_INTENT_ACKED,
  RETIRED_PRECONDITION.REBUILD_PASSES,
]);

/** Which named row a failed precondition becomes. One mapping, so neither side can drift. */
export const PRECONDITION_ROW = Object.freeze({
  [RETIRED_PRECONDITION.HEAD_FSYNCED]: RETIRED_CODE.HEAD_NOT_DURABLE,
  [RETIRED_PRECONDITION.HEAD_INTENT_ACKED]: RETIRED_CODE.INTENT_UNACKED,
  [RETIRED_PRECONDITION.REBUILD_PASSES]: RETIRED_CODE.REBUILD_FAILED,
});

/**
 * The user-visible sentence per row, read at the call site rather than composed there - the
 * same discipline recover-log.mjs and bundle.mjs keep, and for the same reason: a refusal
 * worded where it is raised says something slightly different on each surface.
 */
export const COMPACT_ROWS = Object.freeze({
  [COMPACT_CODE.OK]: Object.freeze({
    status: INTEGRITY.OK,
    text:
      'Compacted the log at {log}: {native} NATIVE event(s) carried forward verbatim, '
      + '{checkpoints} checkpoint row(s) - one per tracked file - folding {folded} DERIVED '
      + 'event(s), and {carried} unrecognised event(s) carried forward untouched. {events_before} '
      + 'event(s) became {events_after}. The pre-compaction log is retired to {retired}, not '
      + 'deleted: deleting it needs all three retirement preconditions.',
  }),
  [COMPACT_CODE.EMPTY]: Object.freeze({
    status: INTEGRITY.EMPTY,
    text:
      'the log at {log} carries no events, so there is nothing to compact and nothing was '
      + 'written. This is EMPTY rather than a failure - it is what a portfolio that has not '
      + 'written yet looks like, and it is reported as such rather than as a compaction of '
      + 'nothing.',
  }),
  [COMPACT_CODE.NOT_DUE]: Object.freeze({
    status: INTEGRITY.OK,
    text:
      'the log holds {observed} of the {cap} event ceiling (the warning fires at {threshold}), '
      + 'so compaction is not due and nothing was written. Run it anyway by not asking for the '
      + 'ceiling check - the check is a trigger, not a permission.',
  }),
  [COMPACT_CODE.NOTHING_TO_FOLD]: Object.freeze({
    status: INTEGRITY.OK,
    text:
      'the compacted head this run computed is byte-identical to the log at {log}, so there is '
      + 'nothing to fold and nothing to retire. Nothing was written: replacing a file with '
      + 'itself would retire a segment holding nothing the head does not already carry. This '
      + 'is what running compaction a second time looks like.',
  }),
  [COMPACT_CODE.LOG_ABSENT]: Object.freeze({
    status: PRESENCE.ABSENT,
    text:
      'there is no log at {log}. Compaction shortens a log; it cannot create one. If the log '
      + 'was lost rather than never written, the verb is steward recover-log.',
  }),
  [COMPACT_CODE.LOG_UNREADABLE]: Object.freeze({
    status: PRESENCE.UNREACHABLE,
    text:
      'the log at {log} could not be read to its head ({reason}). Not one byte was written: a '
      + 'compaction that proceeded from a partial read would carry forward a portfolio smaller '
      + 'than the one on disk.',
  }),
  [COMPACT_CODE.HEAD_WRITE_FAILED]: Object.freeze({
    status: INTEGRITY.TORN,
    text:
      'the compacted head stopped after {written} of {total} line(s) ({reason}). The live log '
      + 'is untouched and still authoritative; the incomplete staging file at {path} was '
      + 'removed. Address the reason and run the verb again.',
  }),
  [COMPACT_CODE.RETIRE_FAILED]: Object.freeze({
    status: INTEGRITY.TORN,
    text:
      'the compacted head was staged but the pre-compaction log could not be retired to '
      + '{retired} ({reason}). The live log is untouched and still authoritative - the head is '
      + 'never swapped in before the segment it replaces is safely copied aside.',
  }),
  [COMPACT_CODE.SEGMENT_EXISTS]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      'a retired segment already exists at {retired}. Nothing was written: overwriting it would '
      + 'destroy the only copy of the bodies an earlier compaction retired at this same '
      + 'boundary. Delete it through the retirement verb - which checks the three preconditions '
      + '- or move it aside by hand.',
  }),
  [COMPACT_CODE.SUPERSEDED_OVERFLOW]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      '{path} in project {project_id} has {total} superseded version(s), past the '
      + 'caps.superseded_entries bound of {cap}. The {kept} most recent are kept as lineage and '
      + '{omitted} were omitted - sequences {from_seq} through {to_seq}. They are reported here '
      + 'rather than dropped in silence, and the lineage list on that checkpoint is now a floor '
      + 'rather than a total.',
  }),
  [COMPACT_CODE.CHECKPOINT_MALFORMED]: Object.freeze({
    status: INTEGRITY.UNPARSEABLE,
    text:
      `a ${CHECKPOINT_SCHEMA} this compaction built does not validate ({reason}). Nothing was `
      + 'written. This is a defect in the engine rather than a state of the portfolio, and it '
      + 'refuses at the point of writing because an invalid checkpoint in an append-only log '
      + 'cannot be edited out afterwards.',
  }),
  [COMPACT_CODE.REBUILD_FAILED]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      'the log was compacted but the {verb} that follows it did not complete ({reason}). The '
      + 'compacted head is intact and the retired segment is still on disk; run that verb again '
      + 'once the reason is addressed.',
  }),
  [COMPACT_CODE.CEILING_WARNING]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      'the log holds {observed} event(s) against a ceiling of {cap}; the warning threshold is '
      + '{threshold}. Compaction is the disposition at that ceiling.',
  }),
  [RETIRED_CODE.DELETED]: Object.freeze({
    status: INTEGRITY.OK,
    text:
      'Deleted the retired segment at {retired} ({byte_len} bytes, boundary {retired_seq}). All '
      + 'three preconditions held: the compacted head is fsynced, a rebuild from the compacted '
      + 'log alone passed, and the head commit-intent {intent_seq} for project {project_id} is '
      + 'acknowledged.',
  }),
  [RETIRED_CODE.ALREADY_DELETED]: Object.freeze({
    status: PRESENCE.ABSENT,
    text:
      'there is no retired segment at {retired}; it has already been deleted or was never '
      + 'created at this boundary. Nothing was done and nothing is wrong: asking twice is how a '
      + 'retry looks.',
  }),
  [RETIRED_CODE.HEAD_NOT_DURABLE]: Object.freeze({
    status: INTEGRITY.TORN,
    text:
      'the compacted head at {log} is not durable as compaction left it ({reason}), so the '
      + 'retired segment was NOT deleted. The segment is the only remaining copy of the bodies '
      + 'the head replaced; it is kept until the head it depends on can be shown to be intact.',
  }),
  [RETIRED_CODE.REBUILD_FAILED]: Object.freeze({
    status: FRESHNESS.UNKNOWN,
    text:
      'a verification rebuild from the compacted log alone did not pass ({reason}), so the '
      + 'retired segment at {retired} was NOT deleted. Until the compacted head can rebuild the '
      + 'portfolio by itself, the segment is not redundant - it is the backup.',
  }),
  [RETIRED_CODE.INTENT_UNACKED]: Object.freeze({
    status: COMPOSITE.DEGRADED,
    text:
      "the compacted head's commit-intent {intent_seq} for project {project_id} has not been "
      + 'acknowledged, so the retired segment at {retired} was NOT deleted. {banner} Deleting '
      + 'the segment now would leave local disk as the only copy of a history nothing outside '
      + 'this machine has confirmed.',
  }),
  [RETIRED_CODE.NO_INTENT]: Object.freeze({
    status: COMPOSITE.DEGRADED,
    text:
      'the compacted head at {log} carries no commit-intent at all, so there is no '
      + 'acknowledgement that could make retiring its predecessor safe, and the segment at '
      + '{retired} was NOT deleted. An unacknowledged history is not a durable one.',
  }),
  [RETIRED_CODE.DELETE_FAILED]: Object.freeze({
    status: PRESENCE.UNREACHABLE,
    text:
      'all three preconditions held but the retired segment at {retired} could not be removed '
      + '({reason}). It is still on disk; nothing else changed.',
  }),
});

/**
 * A filesystem facade carrying every method this module uses, so a test can inject ONE
 * behaviour - an fsync that fails, a rename that is denied - without hand-building a whole fs.
 * The errno paths a failure row promises are handled are exactly the paths a normal host will
 * not produce on demand, so they must be drivable.
 *
 * @param {object|undefined} partial @returns {object}
 */
function fsFacade(partial) {
  return partial ? { ...fs, ...partial } : fs;
}

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) => (
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole
  ));
}

/**
 * One outcome, worded from the frozen row and carrying the D-4 residual.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function compactOutcome(code, params = {}, extra = {}) {
  const row = COMPACT_ROWS[code];
  if (row === undefined) {
    // W19's compaction failure table. The rows above are the dispositions of a compaction that
    // RAN; these are the 0080 states of the surface itself - missing, slow, garbage,
    // unreadable, empty-but-valid, unknown, path hazard - deferred by W3 because the verb did
    // not exist yet, and read from the ONE table rather than restated here.
    const spoken = rowsForSurface(COMPACT_SURFACE).some((r) => r.code === code);
    if (!spoken) throw new Error(`${COMPACT_VERB}: ${code} is not a frozen row`);
    const outcome = rowOutcome(code, params, extra);
    return Object.freeze({
      ...outcome,
      verb: COMPACT_VERB,
      version: COMPACT_VERSION,
      text: `${outcome.text} ${COMPACT_RESIDUAL_SENTENCE}`,
      residual: COMPACT_RESIDUAL_SENTENCE,
    });
  }
  const okByDefault = code === COMPACT_CODE.OK
    || code === COMPACT_CODE.EMPTY
    || code === COMPACT_CODE.NOT_DUE
    || code === COMPACT_CODE.NOTHING_TO_FOLD
    || code === COMPACT_CODE.SUPERSEDED_OVERFLOW
    || code === COMPACT_CODE.CEILING_WARNING
    || code === RETIRED_CODE.DELETED
    || code === RETIRED_CODE.ALREADY_DELETED;
  return Object.freeze({
    ok: extra.ok === undefined ? okByDefault : extra.ok === true,
    code,
    verb: COMPACT_VERB,
    version: COMPACT_VERSION,
    status: assertStatusCode(row.status, `${COMPACT_VERB} row ${code}`),
    text: `${fill(row.text, params)} ${COMPACT_RESIDUAL_SENTENCE}`,
    residual: COMPACT_RESIDUAL_SENTENCE,
    detail: Object.freeze({ ...params }),
  });
}

/** @returns {ReadonlyArray<string>} every frozen row code, for a test that enumerates */
export function compactRowCodes() {
  return Object.freeze(
    [...Object.keys(COMPACT_ROWS), ...rowsForSurface(COMPACT_SURFACE).map((r) => r.code)].sort(),
  );
}

/** @returns {ReadonlyArray<string>} the W19 surface-table codes alone, in table order */
export function compactSurfaceRowCodes() {
  return Object.freeze(rowsForSurface(COMPACT_SURFACE).map((r) => r.code));
}

/** @returns {ReadonlyArray<string>} the verb's own disposition codes alone, sorted */
export function compactVerbRowCodes() {
  return Object.freeze(Object.keys(COMPACT_ROWS).sort());
}

// -- the trigger ---------------------------------------------------------------

/**
 * Where a log's event count sits against the confirmed ceiling.
 *
 * The number and the 80% rule are READ from caps.mjs rather than restated: the warning has
 * been live since W13 and a second copy of the threshold here would be a second warning that
 * fires at a slightly different moment.
 *
 * @param {number} eventCount @returns {Readonly<object>}
 */
export function compactionDue(eventCount) {
  const cap = capStatusFor(COMPACT_TRIGGER_CAP, eventCount);
  return Object.freeze({
    ...cap,
    verb: COMPACT_VERB,
    due: cap.observed >= cap.value,
    warn: cap.warn,
    threshold: warningThreshold(COMPACT_TRIGGER_CAP),
  });
}

// -- the plan ------------------------------------------------------------------

/**
 * What compaction WOULD write, computed without touching a disk.
 *
 * Splitting the plan from the write is what makes the equivalence legs cheap to assert: the
 * same events must yield the same lines every time, and that is checkable without staging a
 * file, renaming anything, or retiring a segment.
 *
 * @param {ReadonlyArray<{event: object, text: string}>} records the log's lines, in seq order
 * @param {{retired_seq?: number, cap?: number}} [opts]
 * @returns {Readonly<object>}
 */
export function compactionPlanFor(records, opts = {}) {
  const list = [...(records ?? [])].sort(
    (a, b) => Number(a.event?.[ORDERING_FIELD]) - Number(b.event?.[ORDERING_FIELD]),
  );

  let boundary = Number.isInteger(opts.retired_seq) ? Number(opts.retired_seq) : EMPTY_HEAD_SEQ;
  if (!Number.isInteger(opts.retired_seq)) {
    for (const record of list) {
      const seq = Number(record.event?.[ORDERING_FIELD]);
      if (Number.isInteger(seq) && seq > boundary) boundary = seq;
    }
  }

  // Which line is the LATEST for each tracked file, and what lineage a prior compaction
  // already recorded for it. Both are decided in one pass up front, so the emit pass below is
  // a straight walk in seq order and the compacted head is in exactly the order the log was.
  /** @type {Map<string, object[]>} identity -> the DERIVED events, oldest first */
  const histories = new Map();
  /** @type {Map<string, object[]>} identity -> lineage a previous compaction preserved */
  const priorLineage = new Map();
  /** @type {Map<string, number>} identity -> the seq of the line that becomes the checkpoint */
  const latestSeq = new Map();

  for (const record of list) {
    const raw = record.event;
    const folded = isCheckpointEvent(raw) ? raw.row : raw;
    if (!isDerivedEvent(folded)) continue;
    const key = rowIdentity(folded);
    const history = histories.get(key);
    if (history === undefined) histories.set(key, [folded]);
    else history.push(folded);
    if (isCheckpointEvent(raw)) {
      priorLineage.set(key, [...(priorLineage.get(key) ?? []), ...supersededOf(raw)]);
    }
    latestSeq.set(key, Number(raw[ORDERING_FIELD]));
  }

  const lines = [];
  const events = [];
  const checkpoints = [];
  const overflows = [];
  const problems = [];
  let native = 0;
  let carried = 0;
  let folded = 0;
  let retiredBodies = 0;
  let supersededTotal = 0;

  for (const record of list) {
    const raw = record.event;
    const seq = Number(raw?.[ORDERING_FIELD]);
    const inner = isCheckpointEvent(raw) ? raw.row : raw;

    if (!isDerivedEvent(inner)) {
      // NATIVE and unrecognised alike: the ORIGINAL LINE, not a re-serialization of a parsed
      // object. "Verbatim" is a claim about bytes, and a round trip through JSON.parse and
      // JSON.stringify is a claim about a parser.
      lines.push(`${record.text}\n`);
      events.push(raw);
      if (isNativeEvent(raw)) native += 1;
      else carried += 1;
      continue;
    }

    const key = rowIdentity(inner);
    folded += 1;
    if (latestSeq.get(key) !== seq) {
      // A superseded version. Its identity, hash and order go into the checkpoint's lineage;
      // its BODY is what the retired segment keeps and the head does not.
      retiredBodies += 1;
      continue;
    }

    const built = makeCheckpointRow({
      history: histories.get(key) ?? [inner],
      prior_superseded: priorLineage.get(key) ?? [],
      retired_seq: boundary,
      cap: opts.cap,
    });
    const checked = validateCheckpointRow(built.event);
    if (!checked.ok) {
      problems.push(Object.freeze({
        identity: key,
        seq,
        reason: checked.problems.map((p) => p.text).join('; '),
      }));
      continue;
    }

    lines.push(logEventLine(built.event));
    events.push(built.event);
    checkpoints.push(built.event);
    supersededTotal += built.superseded_kept;
    if (built.overflow !== null) overflows.push(built.overflow);
  }

  return Object.freeze({
    version: COMPACT_VERSION,
    retired_seq: boundary,
    lines: Object.freeze(lines),
    // The compacted head as bytes, so the caller can ask the only question that decides
    // whether there is anything to do: would this replace the log with itself?
    text: lines.join(''),
    events: Object.freeze(events),
    checkpoints: Object.freeze(checkpoints),
    overflows: Object.freeze(overflows),
    problems: Object.freeze(problems),
    counts: Object.freeze({
      events_before: list.length,
      events_after: lines.length,
      native,
      carried_unrecognised: carried,
      checkpoints: checkpoints.length,
      derived_folded: folded,
      bodies_retired: retiredBodies,
      superseded_entries: supersededTotal,
    }),
    bodies_retired: retiredBodies,
  });
}

// -- reading the log's LINES ---------------------------------------------------

/**
 * The log as {parsed event, original line text} pairs.
 *
 * `readLogHead` has already quarantined any torn tail and refused any interior damage by the
 * time this runs, so every record here is a complete, parseable line - which is why the parse
 * below cannot be the place a compaction discovers the log is broken.
 *
 * @param {string} logPath @param {{fsx?: object}} [opts]
 * @returns {{ok: boolean, records: Array<{event: object, text: string}>, bytes: Buffer,
 *            reason: string|null}}
 */
export function readLogRecords(logPath, opts = {}) {
  const read = readLogBytes(logPath, { fsx: opts.fsx });
  if (read.error) {
    return { ok: false, records: [], bytes: read.bytes, reason: read.error.code ?? String(read.error) };
  }
  const { records, fragment } = scanLogBytes(read.bytes);
  if (fragment !== null) {
    // readLogHead quarantines a torn tail before this runs, so reaching here means the caller
    // turned quarantining off. Refusing is the only honest answer: compaction rebuilds the
    // file from complete records, and proceeding would delete the torn bytes without ever
    // having told anybody they existed.
    return {
      ok: false,
      records: [],
      bytes: read.bytes,
      reason:
        `${fragment.byte_len} byte(s) after the final line terminator are a torn tail that has `
        + 'not been quarantined; compaction will not rebuild a log over bytes nobody has '
        + 'accounted for',
    };
  }
  const out = [];
  for (const record of records) {
    if (record.text.trim() === '') continue;
    let event;
    try {
      event = JSON.parse(record.text);
    } catch (err) {
      return {
        ok: false,
        records: [],
        bytes: read.bytes,
        reason: `line ${record.line} does not parse (${(err && err.message) || err})`,
      };
    }
    out.push({ event, text: record.text });
  }
  return { ok: true, records: out, bytes: read.bytes, reason: null };
}

/** @param {object} fsx @param {string} dir best effort: a new entry is durable, not just bytes */
function fsyncDirBestEffort(dir, fsx) {
  let fd;
  try {
    fd = fsx.openSync(openablePath(dir), 'r');
    fsx.fsyncSync(fd);
  } catch {
    // Windows refuses a directory handle opened this way; the rename is still ordered by the
    // filesystem, and throwing here would fail an operation that actually succeeded.
  } finally {
    if (fd !== undefined) {
      try {
        fsx.closeSync(fd);
      } catch {
        /* already closed */
      }
    }
  }
}

/**
 * Copy the pre-compaction log aside and fsync the copy.
 *
 * A COPY rather than a rename, and this is the ordering that makes the whole operation safe:
 * renaming the live log away would leave the log path empty for as long as it takes to rename
 * the staged head into it, and a kill in that window leaves a portfolio with no log at all.
 * Copying costs one pass over a file that is being replaced anyway, once per ceiling.
 *
 * @param {string} target @param {Buffer} bytes @param {object} fsx
 * @returns {{ok: boolean, byte_len: number, reason: string|null}}
 */
function retireSegment(target, bytes, fsx) {
  let fd;
  try {
    fd = fsx.openSync(openablePath(target), 'wx');
    fsx.writeSync(fd, bytes, 0, bytes.length);
    try {
      fsx.fsyncSync(fd);
    } catch {
      /* a filesystem that refuses fsync still has the bytes in the segment */
    }
    fsx.closeSync(fd);
    fd = undefined;
    return { ok: true, byte_len: bytes.length, reason: null };
  } catch (err) {
    return { ok: false, byte_len: 0, reason: (err && err.code) || String(err && err.message) };
  } finally {
    if (fd !== undefined) {
      try {
        fsx.closeSync(fd);
      } catch {
        /* already closed */
      }
    }
  }
}

// -- the verb ------------------------------------------------------------------

/**
 * `steward compact`.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, cap?: number,
 *          only_when_due?: boolean, rebuild?: boolean, boundMs?: number, staleMs?: number,
 *          quarantine?: boolean, lockOpts?: object}} [opts]
 *   `cap` overrides caps.superseded_entries and exists so the overflow path can be exercised
 *   without writing 257 versions of one file; `only_when_due` makes the ceiling a gate rather
 *   than a report; `rebuild:false` skips the chained rebuild for callers testing the log alone.
 * @returns {Readonly<object>} the compaction-receipt-v1
 */
export function compactLog(opts = {}) {
  const paths = indexPathsFrom(opts);
  const fsx = fsFacade(opts.fsx);
  const notices = [];

  const prepared = ensureIndexHome(paths, { fsx });
  if (prepared.ok !== true) return failedReceipt(paths, prepared, notices);

  let staged;
  try {
    staged = withPortfolioLock(
      paths,
      () => stageCompaction(paths, fsx, opts, notices),
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        timeoutCode: INDEX_WRITE_CODE.LOCK_TIMEOUT,
        lockOpts: opts.lockOpts,
      },
    );
  } catch (err) {
    if (isIndexRefusal(err)) return failedReceipt(paths, err.outcome, notices);
    throw err;
  }

  if (staged.outcome.ok !== true || staged.compacted !== true) {
    return Object.freeze({
      ok: staged.outcome.ok === true,
      schema: COMPACT_RECEIPT_SCHEMA,
      version: COMPACT_VERSION,
      verb: COMPACT_VERB,
      home: paths.home,
      log: paths.log,
      retired_segment: null,
      retired_seq: staged.retired_seq ?? EMPTY_HEAD_SEQ,
      outcome: staged.outcome,
      policy: COMPACT_POLICY,
      residual: COMPACT_RESIDUAL_SENTENCE,
      plan: staged.plan ?? null,
      counts: staged.plan?.counts ?? null,
      cap_status: staged.cap_status ?? null,
      overflows: staged.plan?.overflows ?? Object.freeze([]),
      head_sha256: null,
      compacted: false,
      rebuild: null,
      notices: Object.freeze(notices),
    });
  }

  // The rebuild is chained OUTSIDE the lock, for the reason rebuildIndex itself states: holding
  // the portfolio lock across a full portfolio walk starves every writer past the W5 starvation
  // bound. The compacted head is already durable and already the live log by this point.
  let rebuilt = null;
  if (opts.rebuild !== false) {
    rebuilt = rebuildIndex({
      home: paths.home,
      fsx: opts.fsx,
      boundMs: opts.boundMs,
      staleMs: opts.staleMs,
      lockOpts: opts.lockOpts,
    });
    if (rebuilt.ok !== true) {
      notices.push(compactOutcome(COMPACT_CODE.REBUILD_FAILED, {
        verb: 'rebuild',
        reason: rebuilt.outcome?.text ?? String(rebuilt.outcome?.code ?? ''),
      }));
    }
  }

  return Object.freeze({
    ok: true,
    schema: COMPACT_RECEIPT_SCHEMA,
    version: COMPACT_VERSION,
    verb: COMPACT_VERB,
    home: paths.home,
    log: paths.log,
    retired_segment: staged.retired_segment,
    retired_seq: staged.retired_seq,
    outcome: staged.outcome,
    policy: COMPACT_POLICY,
    residual: COMPACT_RESIDUAL_SENTENCE,
    plan: staged.plan,
    counts: staged.plan.counts,
    cap_status: staged.cap_status,
    // Every omission, with the exact sequences that went. The frozen checkpoint-row-v1 field
    // set has nowhere to record this, so the receipt is where it lives - and doctor reads
    // atCapCheckpoints() from the log to say the same thing in the weaker form the log can
    // still support by itself.
    overflows: staged.plan.overflows,
    head_sha256: staged.head_sha256,
    // The length the hash above is taken over. Writes continue after a compaction, so the
    // retirement check needs to know where the head it is verifying ends.
    head_byte_len: staged.head_byte_len,
    head_line_count: staged.plan.lines.length,
    retired_byte_len: staged.retired_byte_len,
    compacted: true,
    rebuild: rebuilt,
    notices: Object.freeze(notices),
  });
}

/** @param {object} paths @param {object} outcome @param {Array<object>} notices */
function failedReceipt(paths, outcome, notices) {
  return Object.freeze({
    ok: false,
    schema: COMPACT_RECEIPT_SCHEMA,
    version: COMPACT_VERSION,
    verb: COMPACT_VERB,
    home: paths.home,
    log: paths.log,
    retired_segment: null,
    retired_seq: EMPTY_HEAD_SEQ,
    outcome,
    policy: COMPACT_POLICY,
    residual: COMPACT_RESIDUAL_SENTENCE,
    plan: null,
    counts: null,
    cap_status: null,
    overflows: Object.freeze([]),
    head_sha256: null,
    compacted: false,
    rebuild: null,
    notices: Object.freeze(notices),
  });
}

/**
 * Everything that happens under the portfolio lock: read, plan, stage, retire, swap.
 *
 * @param {object} paths @param {object} fsx @param {object} opts @param {Array<object>} notices
 * @returns {object}
 */
function stageCompaction(paths, fsx, opts, notices) {
  // ABSENT before EMPTY, and the two are different facts: a log that is not there is a
  // portfolio whose one non-deletable artifact has gone, and reporting it as "nothing to
  // compact" would be the collapse STATUS-v1 exists to forbid.
  if (!fsx.existsSync(openablePath(paths.log))) {
    return {
      compacted: false,
      retired_seq: EMPTY_HEAD_SEQ,
      outcome: compactOutcome(COMPACT_CODE.LOG_ABSENT, { log: paths.log }, { ok: false }),
    };
  }

  const head = readLogHead(paths.log, { fsx, write: false, quarantine: opts.quarantine });
  if (!head.ok) {
    return {
      compacted: false,
      retired_seq: EMPTY_HEAD_SEQ,
      outcome: compactOutcome(
        COMPACT_CODE.LOG_UNREADABLE,
        { log: paths.log, reason: head.outcome?.text ?? String(head.outcome?.code ?? '') },
        { ok: false },
      ),
    };
  }

  if (head.events.length === 0) {
    return {
      compacted: false,
      retired_seq: EMPTY_HEAD_SEQ,
      outcome: compactOutcome(COMPACT_CODE.EMPTY, { log: paths.log }),
    };
  }

  const capStatus = compactionDue(head.events.length);
  if (capStatus.warn) {
    notices.push(compactOutcome(COMPACT_CODE.CEILING_WARNING, {
      observed: capStatus.observed,
      cap: capStatus.value,
      threshold: capStatus.threshold,
    }));
  }
  if (opts.only_when_due === true && !capStatus.due) {
    return {
      compacted: false,
      cap_status: capStatus,
      retired_seq: head.head_seq,
      outcome: compactOutcome(COMPACT_CODE.NOT_DUE, {
        observed: capStatus.observed,
        cap: capStatus.value,
        threshold: capStatus.threshold,
      }),
    };
  }

  const read = readLogRecords(paths.log, { fsx });
  if (!read.ok) {
    return {
      compacted: false,
      cap_status: capStatus,
      outcome: compactOutcome(
        COMPACT_CODE.LOG_UNREADABLE,
        { log: paths.log, reason: read.reason ?? '' },
        { ok: false },
      ),
    };
  }

  const plan = compactionPlanFor(read.records, { retired_seq: head.head_seq, cap: opts.cap });
  if (plan.problems.length > 0) {
    return {
      compacted: false,
      cap_status: capStatus,
      plan,
      retired_seq: plan.retired_seq,
      outcome: compactOutcome(
        COMPACT_CODE.CHECKPOINT_MALFORMED,
        { reason: plan.problems.map((p) => `${p.identity}: ${p.reason}`).join('; ') },
        { ok: false },
      ),
    };
  }

  for (const overflow of plan.overflows) {
    notices.push(compactOutcome(COMPACT_CODE.SUPERSEDED_OVERFLOW, overflow));
  }

  // THE IDEMPOTENCE GATE, and it is a byte comparison rather than a count. Compacting an
  // already-compacted log re-derives the same checkpoints from the same rows with the same
  // lineage - this verb reads no clock, so it cannot help but produce the same bytes - and
  // replacing a file with itself would retire a segment that holds nothing the head does not.
  // Asking the question in bytes is what makes "run it twice" provably a no-op instead of
  // usually one.
  if (plan.text === read.bytes.toString('utf8')) {
    return {
      compacted: false,
      cap_status: capStatus,
      plan,
      retired_seq: plan.retired_seq,
      outcome: compactOutcome(COMPACT_CODE.NOTHING_TO_FOLD, { log: paths.log }),
    };
  }

  const retired = retiredSegmentPathFor(paths.log, plan.retired_seq);
  if (fsx.existsSync(openablePath(retired))) {
    return {
      compacted: false,
      cap_status: capStatus,
      plan,
      retired_seq: plan.retired_seq,
      outcome: compactOutcome(COMPACT_CODE.SEGMENT_EXISTS, { retired }, { ok: false }),
    };
  }

  // Step 1: assemble the compacted head beside the log, one fsynced line at a time.
  const staging = compactStagingPathFor(paths.log, plan.retired_seq);
  try {
    fsx.rmSync(openablePath(staging), { force: true });
  } catch {
    /* a staging file that will not go away is caught by the first append below */
  }

  let written = 0;
  for (const line of plan.lines) {
    const wrote = appendLineAt(staging, line, { fsx });
    if (wrote.ok !== true) {
      try {
        fsx.rmSync(openablePath(staging), { force: true });
      } catch {
        /* the orphan is named in the outcome either way */
      }
      return {
        compacted: false,
        cap_status: capStatus,
        plan,
        retired_seq: plan.retired_seq,
        outcome: compactOutcome(
          COMPACT_CODE.HEAD_WRITE_FAILED,
          {
            written,
            total: plan.lines.length,
            path: staging,
            reason: wrote.text ?? String(wrote.code ?? ''),
          },
          { ok: false },
        ),
      };
    }
    written += 1;
  }

  // Step 2: the pre-compaction log is copied aside and fsynced BEFORE anything replaces it.
  const kept = retireSegment(retired, read.bytes, fsx);
  if (!kept.ok) {
    try {
      fsx.rmSync(openablePath(staging), { force: true });
    } catch {
      /* the live log is untouched, which is the property that matters here */
    }
    return {
      compacted: false,
      cap_status: capStatus,
      plan,
      retired_seq: plan.retired_seq,
      outcome: compactOutcome(
        COMPACT_CODE.RETIRE_FAILED,
        { retired, reason: kept.reason ?? '' },
        { ok: false },
      ),
    };
  }

  // Step 3: the staged head replaces the live log in one atomic-replace rename.
  fsx.renameSync(openablePath(staging), openablePath(paths.log));
  fsyncDirBestEffort(paths.home, fsx);

  return {
    compacted: true,
    cap_status: capStatus,
    plan,
    retired_seq: plan.retired_seq,
    retired_segment: retired,
    retired_byte_len: kept.byte_len,
    head_sha256: hashBytes(Buffer.from(plan.text, 'utf8')),
    head_byte_len: Buffer.byteLength(plan.text, 'utf8'),
    outcome: compactOutcome(COMPACT_CODE.OK, {
      log: paths.log,
      retired,
      native: plan.counts.native,
      checkpoints: plan.counts.checkpoints,
      folded: plan.counts.derived_folded,
      carried: plan.counts.carried_unrecognised,
      events_before: plan.counts.events_before,
      events_after: plan.counts.events_after,
    }),
  };
}

// -- retired segments ----------------------------------------------------------

/**
 * Every retired segment sitting beside the log, oldest boundary first.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object}} [opts]
 * @returns {ReadonlyArray<Readonly<object>>}
 */
export function retiredSegmentsIn(opts = {}) {
  const paths = indexPathsFrom(opts);
  const fsx = fsFacade(opts.fsx);
  let names = [];
  try {
    names = fsx.readdirSync(openablePath(paths.home)).map((entry) => (
      typeof entry === 'string' ? entry : entry.name
    ));
  } catch {
    return Object.freeze([]);
  }
  const out = [];
  for (const name of names) {
    const abs = path.join(paths.home, name);
    const seq = retiredSegmentSeqOf(paths.log, abs);
    if (seq === null) continue;
    let size = 0;
    try {
      size = fsx.statSync(openablePath(abs)).size;
    } catch {
      continue;
    }
    out.push(Object.freeze({ path: abs, retired_seq: seq, byte_len: size }));
  }
  return Object.freeze(out.sort((a, b) => a.retired_seq - b.retired_seq));
}

/**
 * The head's commit-intent, and whether Anchor has acknowledged it.
 *
 * "The head's commit-intent" is the LAST one in the compacted log, because that is the newest
 * promise this history made. An older acknowledged intent does not make it safe to retire the
 * bodies behind a newer unacknowledged one - the newest promise is the one still only on this
 * disk.
 *
 * @param {ReadonlyArray<object>} events @returns {Readonly<object>}
 */
export function headIntentAckState(events) {
  const intents = commitIntentsIn(events);
  if (intents.length === 0) {
    return Object.freeze({ present: false, acked: false, intent: null });
  }
  const head = intents[intents.length - 1];
  const ledger = intentLedger(events);
  const acked = ledger.acknowledged.some(
    (intent) => intent.project_id === head.project_id
      && intent.intent_seq === head.intent_seq
      && intent.sha256 === head.sha256,
  );
  return Object.freeze({ present: true, acked, intent: head });
}

/**
 * Delete one retired segment, and only when all three frozen preconditions hold.
 *
 * THE LOCK IS TAKEN TWICE, ON PURPOSE, and the reason is the same one rebuildIndex gives: the
 * verification rebuild walks every live root, and holding the portfolio lock across that walk
 * would starve every writer past the W5 starvation bound. So the head is read and fsynced
 * under the first acquisition, the rebuild runs unlocked against bytes that are already
 * durable, and the unlink happens under the second - which re-checks that the segment is still
 * the file it decided about.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, retired_seq: number,
 *          head_sha256?: string|null, head_byte_len?: number|null, now?: number|Date,
 *          threshold_days?: number, boundMs?: number, staleMs?: number, lockOpts?: object}} req
 *   `head_sha256` and `head_byte_len` come straight off the compaction receipt; supplying them
 *   turns precondition (a) from "the head is readable" into "the head is the one compaction
 *   wrote, byte for byte, with whatever has been appended since sitting after it".
 * @returns {Readonly<object>} the retired-segment-deletion-receipt-v1
 */
export function deleteRetiredSegment(req) {
  const opts = req ?? {};
  const paths = indexPathsFrom(opts);
  const fsx = fsFacade(opts.fsx);
  const retiredSeq = Number(opts.retired_seq);
  const retired = retiredSegmentPathFor(paths.log, retiredSeq);
  /** @type {Array<Readonly<object>>} */
  const checked = [];

  const receipt = (outcome, extra = {}) => Object.freeze({
    ok: outcome.ok === true,
    schema: RETIRED_DELETE_RECEIPT_SCHEMA,
    version: COMPACT_VERSION,
    verb: COMPACT_VERB,
    home: paths.home,
    log: paths.log,
    retired_segment: retired,
    retired_seq: retiredSeq,
    outcome,
    residual: COMPACT_RESIDUAL_SENTENCE,
    preconditions: RETIRED_PRECONDITIONS,
    checked: Object.freeze([...checked]),
    deleted: false,
    ...extra,
  });

  const note = (precondition, held, detail) => {
    checked.push(Object.freeze({ precondition, held, detail: String(detail ?? '') }));
    return held;
  };

  if (!fsx.existsSync(openablePath(retired))) {
    return receipt(compactOutcome(RETIRED_CODE.ALREADY_DELETED, { retired }));
  }

  // -- first acquisition: the head, read and made durable ----------------------
  let phase;
  try {
    phase = withPortfolioLock(
      paths,
      () => {
        let fd;
        try {
          fd = fsx.openSync(openablePath(paths.log), 'r+');
          fsx.fsyncSync(fd);
        } catch (err) {
          return { fsynced: false, reason: (err && err.code) || String(err && err.message) };
        } finally {
          if (fd !== undefined) {
            try {
              fsx.closeSync(fd);
            } catch {
              /* already closed */
            }
          }
        }
        const read = readLogRecords(paths.log, { fsx });
        if (!read.ok) return { fsynced: false, reason: read.reason ?? '' };
        return {
          fsynced: true,
          reason: null,
          events: replayEvents(read.records.map((r) => r.event)),
          bytes: read.bytes,
        };
      },
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        timeoutCode: INDEX_READ_CODE.LOCK_TIMEOUT,
        lockOpts: opts.lockOpts,
      },
    );
  } catch (err) {
    if (isIndexRefusal(err)) return receipt(Object.freeze({ ...err.outcome, ok: false }));
    throw err;
  }

  if (!phase.fsynced) {
    note(RETIRED_PRECONDITION.HEAD_FSYNCED, false, phase.reason);
    return receipt(compactOutcome(
      RETIRED_CODE.HEAD_NOT_DURABLE,
      { log: paths.log, reason: phase.reason ?? '' },
      { ok: false },
    ));
  }
  // THE HASH IS CHECKED OVER A PREFIX, NOT OVER THE WHOLE FILE, and the reason is that the log
  // is still a log: writes continue after a compaction, and an acknowledgement is itself an
  // append - so the very act of satisfying precondition (c) lengthens the file. What must
  // still be true is that the bytes compaction wrote are the bytes that are there, unchanged,
  // at the front of the log. A whole-file hash would make this precondition unsatisfiable by
  // construction, which is a check that always fails rather than a check that means something.
  const expected = opts.head_sha256 === undefined || opts.head_sha256 === null
    ? null
    : String(opts.head_sha256);
  const headLen = Number.isInteger(opts.head_byte_len) ? Number(opts.head_byte_len) : null;
  if (expected !== null) {
    const length = headLen === null ? phase.bytes.length : headLen;
    if (phase.bytes.length < length) {
      note(
        RETIRED_PRECONDITION.HEAD_FSYNCED,
        false,
        `the log is ${phase.bytes.length} bytes, shorter than the ${length} compaction wrote`,
      );
      return receipt(compactOutcome(
        RETIRED_CODE.HEAD_NOT_DURABLE,
        {
          log: paths.log,
          reason: `the log is ${phase.bytes.length} bytes and the compacted head was ${length}`,
        },
        { ok: false },
      ));
    }
    const seen = hashBytes(phase.bytes.subarray(0, length));
    if (seen !== expected) {
      note(
        RETIRED_PRECONDITION.HEAD_FSYNCED,
        false,
        `the head prefix hashes to ${seen}, not to the ${expected} compaction recorded`,
      );
      return receipt(compactOutcome(
        RETIRED_CODE.HEAD_NOT_DURABLE,
        {
          log: paths.log,
          reason: `the compacted head no longer hashes to what compaction wrote (${seen})`,
        },
        { ok: false },
      ));
    }
    note(RETIRED_PRECONDITION.HEAD_FSYNCED, true, seen);
  } else {
    note(RETIRED_PRECONDITION.HEAD_FSYNCED, true, `${phase.bytes.length} byte(s), fsynced and parseable`);
  }

  // -- (c) the head's commit-intent, acknowledged ------------------------------
  const ack = headIntentAckState(phase.events);
  if (!ack.present) {
    note(RETIRED_PRECONDITION.HEAD_INTENT_ACKED, false, 'the compacted head carries no intent');
    return receipt(compactOutcome(
      RETIRED_CODE.NO_INTENT,
      { log: paths.log, retired },
      { ok: false },
    ));
  }
  if (!ack.acked) {
    const health = durabilityHealth({
      events: phase.events,
      now: opts.now,
      threshold_days: opts.threshold_days,
    });
    note(
      RETIRED_PRECONDITION.HEAD_INTENT_ACKED,
      false,
      `intent ${ack.intent.intent_seq} for ${ack.intent.project_id} is unacknowledged`,
    );
    return receipt(
      compactOutcome(
        RETIRED_CODE.INTENT_UNACKED,
        {
          retired,
          intent_seq: ack.intent.intent_seq,
          project_id: ack.intent.project_id,
          banner: health.banner?.text ?? '',
        },
        { ok: false },
      ),
      { degraded: health.degraded === true, banner: health.banner ?? null },
    );
  }
  note(
    RETIRED_PRECONDITION.HEAD_INTENT_ACKED,
    true,
    `intent ${ack.intent.intent_seq} for ${ack.intent.project_id}`,
  );

  // -- (b) a rebuild from the compacted log ALONE ------------------------------
  const verification = rebuildIndex({
    home: paths.home,
    fsx: opts.fsx,
    write: false,
    boundMs: opts.boundMs,
    staleMs: opts.staleMs,
    lockOpts: opts.lockOpts,
  });
  const rebuildReason = verification.ok !== true
    ? (verification.outcome?.text ?? String(verification.outcome?.code ?? ''))
    : verification.report.forks.length > 0
      ? `${verification.report.forks.length} row(s) disagree between the log and the disk`
      : verification.totality.balanced !== true
        ? verification.totality.text
        : null;
  if (rebuildReason !== null) {
    note(RETIRED_PRECONDITION.REBUILD_PASSES, false, rebuildReason);
    return receipt(
      compactOutcome(
        RETIRED_CODE.REBUILD_FAILED,
        { retired, reason: rebuildReason },
        { ok: false },
      ),
      { verification },
    );
  }
  note(
    RETIRED_PRECONDITION.REBUILD_PASSES,
    true,
    `${verification.body.rows.length} row(s) rebuilt from the compacted log alone`,
  );

  // -- second acquisition: the unlink ------------------------------------------
  let byteLen = 0;
  try {
    byteLen = fsx.statSync(openablePath(retired)).size;
  } catch {
    return receipt(compactOutcome(RETIRED_CODE.ALREADY_DELETED, { retired }));
  }

  let removed;
  try {
    removed = withPortfolioLock(
      paths,
      () => {
        try {
          fsx.rmSync(openablePath(retired), { force: true });
          fsyncDirBestEffort(paths.home, fsx);
          return { ok: true, reason: null };
        } catch (err) {
          return { ok: false, reason: (err && err.code) || String(err && err.message) };
        }
      },
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        timeoutCode: INDEX_WRITE_CODE.LOCK_TIMEOUT,
        lockOpts: opts.lockOpts,
      },
    );
  } catch (err) {
    if (isIndexRefusal(err)) return receipt(Object.freeze({ ...err.outcome, ok: false }));
    throw err;
  }

  if (removed.ok !== true) {
    return receipt(
      compactOutcome(
        RETIRED_CODE.DELETE_FAILED,
        { retired, reason: removed.reason ?? '' },
        { ok: false },
      ),
      { verification },
    );
  }

  return Object.freeze({
    ...receipt(
      compactOutcome(RETIRED_CODE.DELETED, {
        retired,
        byte_len: byteLen,
        retired_seq: retiredSeq,
        intent_seq: ack.intent.intent_seq,
        project_id: ack.intent.project_id,
      }),
      { verification },
    ),
    deleted: true,
  });
}

// -- what doctor reads ---------------------------------------------------------

/**
 * The compaction subsystem's one honest line, computed from the log the caller already read.
 *
 * W19 owns `steward doctor`; this is the function it calls, landed here beside the verb whose
 * state it reports so the two cannot drift. It answers three things and changes nothing: how
 * close the log is to its ceiling, which lineage lists are sitting at their bound, and which
 * retired segments are still on disk waiting for their preconditions.
 *
 * @param {{events?: ReadonlyArray<object>, home?: string, paths?: object, env?: object,
 *          fsx?: object, cap?: number}} [opts]
 * @returns {Readonly<object>}
 */
export function compactionHealth(opts = {}) {
  const events = Array.isArray(opts.events) ? opts.events : [];
  const cap = compactionDue(events.length);
  const atCap = atCapCheckpoints(events, { cap: opts.cap });
  const segments = opts.home === undefined && opts.paths === undefined && opts.env === undefined
    ? Object.freeze([])
    : retiredSegmentsIn(opts);
  return Object.freeze({
    version: COMPACT_VERSION,
    verb: COMPACT_VERB,
    cap_status: cap,
    checkpoints: checkpointsIn(events).length,
    lineage: lineageIn(events),
    at_cap: atCap,
    retired_segments: segments,
    status: assertStatusCode(
      atCap.length > 0 || cap.warn ? FRESHNESS.STALE : INTEGRITY.OK,
      'compaction health',
    ),
    text:
      `${cap.text} ${checkpointsIn(events).length} checkpoint row(s); ${atCap.length} lineage `
      + `list(s) at the ${CAPS.superseded_entries}-entry bound and therefore a floor rather than `
      + `a total; ${segments.length} retired segment(s) still on disk.`,
  });
}

/**
 * W9 - ingest.mjs: the write path that makes a just-written item findable.
 *
 * THE HOLE THIS CLOSES. Before this wave there was NO write path emitting DERIVED events at
 * all. Every row in the index arrived from a rebuild or from the W8 startup sweep, which
 * means "findable" was true only AFTER somebody ran a rebuild - a receipt written one second
 * ago was, by construction, invisible. Round 1 found that hole from three separate angles;
 * this module is the one place it is filled.
 *
 * THE FROZEN SUCCESS ORDERING, and every clause in it is load-bearing:
 *
 *   1. the source of truth is written and fsynced   (the existing project write primitive)
 *   2. the project lock is RELEASED
 *   3. the DERIVED event AND the W15 commit-intent are appended and fsynced to the ONE log,
 *      in ONE batch, in that order   (the W5 primitive)
 *   4. the D-3 find surface reflects it - tail merge, no snapshot rewrite required
 *   5. the verb returns success
 *
 * W15 ADDED THE INTENT TO STEP 3 RATHER THAN GIVING IT A FLUSH OF ITS OWN, and that is a
 * correctness choice rather than a saving. The row says "this file exists and here is its
 * hash"; the intent says "please make these exact bytes durable somewhere that is not this
 * disk". Two flushes could interleave with another writer's, leaving a log in which a row
 * exists whose intent does not - a receipt indexed and never asked to be committed, which is
 * precisely the silent local-only state the durability banner exists to make impossible.
 * One batch, one contiguous run of seqs, one ordering for both facts.
 *
 * Step 2 before step 3 is the W8 lock-order rule: the project lock and the ONE portfolio
 * lock are never held together, because two call sites that take them in opposite orders is
 * the ABBA deadlock, and a deadlock that only appears under contention is a defect nobody
 * can reproduce. The event is therefore BUFFERED while the project lock is held and flushed
 * after it is released - engine/portfolio/lock-order.mjs's withProjectLock() is what makes
 * that mechanical rather than remembered.
 *
 * Step 3 before step 5 is the honesty clause: the index append happens BEFORE the verb
 * returns success, so there is no operator-visible lag window in the success path. A verb
 * that returned first and indexed later would be telling the operator a thing that is not
 * yet true, and "eventually consistent" is a phrase that means "wrong for a while" when the
 * subject is whether your receipt exists.
 *
 * THE ONE FAILURE BRANCH, NAMED RATHER THAN HIDDEN. If the DERIVED append cannot be made
 * durable, the source-of-truth write STANDS - it IS the source of truth, and rolling it back
 * to keep an index tidy would destroy the only copy of the operator's work to preserve a
 * derived artifact. So the verb returns INGEST_APPEND_FAILED with its frozen user-visible
 * text ("the file was written but the index did not record it"), the project reads STALE,
 * and the W8 divergence sweep regenerates the row on the next start. Three facts, all true
 * at once, all said out loud.
 *
 * WHAT IS WRITTEN, AND WHERE. The bytes go to the inventory-v1 discovery path for the class
 * (`<root>/receipts/*.json`, `<root>/instruments/*.json`, `<root>/roadmap/*.jsonl`), because
 * that is the closed set the W10 rebuilder discovers. A file written anywhere else would
 * produce a row on the write path that no rebuild could reproduce, which is the fork the
 * single shared derive.mjs exists to prevent.
 *
 * EVERY REFUSAL IS A FROZEN W3 ROW. The status and the sentence are READ from the ingest
 * failure table, never composed here, so this module cannot drift from the operator's
 * documentation. The class-varying rows are looked up per class, which is what makes
 * instrument and roadmap-event literal peers of receipt at ingest rather than receipts with
 * a different noun.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  INDEX_WRITE_CODE,
  openIndexForRead,
} from '../append-log.mjs';
import { writeFileAtomicSync } from '../durable-write.mjs';
import { CAPS, capStatusFor } from './caps.mjs';
import {
  COMMIT_REASON,
  makeCommitIntent,
  nextSeqFor,
  pathEntryFor,
} from './commit-intent.mjs';
import {
  deriveRow,
  derivedRowsInLog,
  isDerivableClass,
  isDerivedEvent,
  rowIdentity,
  sourceRecordFor,
  supersedesSeqFor,
} from './derive.mjs';
import { rowOutcome } from './failure-tables.mjs';
import {
  CLASS,
  INVENTORY_V1,
  PARSE_REASON,
  detectCaseCollisions,
  inventoryEntryFor,
  isOverMaxPath,
  openablePath,
  toPosix,
} from './inventory.mjs';
import { LOCK_ORDER_CODE, withProjectLock } from './lock-order.mjs';
import { PROJECT_ID_PATTERN } from './marker.mjs';
import {
  lastCommitIntentSeq,
  makeCommitIntentEvent,
  materializeRegistry,
} from './registry.mjs';
import { FRESHNESS, INTEGRITY, PRESENCE } from './status.mjs';

/** The write path's frozen version. Changing the ordering means ingest-v2. */
export const INGEST_VERSION = 'ingest-v1';

/**
 * The class-varying failure rows are named `<STEM>_<SUFFIX>`. The suffix table lives here
 * rather than being spelled at each call site, so a fourth class (there will not be one
 * without an inventory-v2 ratification) is one edit rather than a search.
 */
const CLASS_SUFFIX = Object.freeze({
  [CLASS.RECEIPT]: 'RECEIPT',
  [CLASS.INSTRUMENT]: 'INSTRUMENT',
  [CLASS.ROADMAP_EVENT]: 'ROADMAP_EVENT',
});

/**
 * W15. The commit-intent reason each class's write asks for, from the closed W4 reason set.
 *
 * The reason is per CLASS rather than a single WRITE, because the acknowledging side is
 * meant to switch on it exhaustively; one flat reason would force it to re-derive from a
 * path what this engine already knew when it wrote the file.
 */
const COMMIT_REASON_FOR = Object.freeze({
  [CLASS.RECEIPT]: COMMIT_REASON.RECEIPT_WRITTEN,
  [CLASS.INSTRUMENT]: COMMIT_REASON.INSTRUMENT_WRITTEN,
  [CLASS.ROADMAP_EVENT]: COMMIT_REASON.ROADMAP_EVENT_WRITTEN,
});

/** The class-varying ingest row stems. */
export const INGEST_CLASS_STEM = Object.freeze({
  SOURCE_ABSENT: 'INGEST_SOURCE_ABSENT',
  SOURCE_UNPARSEABLE: 'INGEST_SOURCE_UNPARSEABLE',
  SOURCE_MOJIBAKE: 'INGEST_SOURCE_MOJIBAKE',
  SOURCE_EMPTY: 'INGEST_SOURCE_EMPTY',
  FRESHNESS_UNKNOWN: 'INGEST_FRESHNESS_UNKNOWN',
});

/** The ingest rows that do not vary by class. */
export const INGEST_CODE = Object.freeze({
  APPEND_FAILED: 'INGEST_APPEND_FAILED',
  ROOT_UNREACHABLE: 'INGEST_ROOT_UNREACHABLE',
  LOCK_TIMEOUT: 'INGEST_LOCK_TIMEOUT',
  UNCLASSIFIED: 'INGEST_UNCLASSIFIED',
  SKIPPED_REPARSE: 'INGEST_SKIPPED_REPARSE',
  PATH_TOO_LONG: 'INGEST_PATH_TOO_LONG',
  CASE_COLLISION: 'INGEST_CASE_COLLISION',
});

/**
 * The class-varying row code for a stem.
 *
 * @param {string} stem one of INGEST_CLASS_STEM @param {string} className
 * @returns {string}
 */
export function ingestClassCode(stem, className) {
  const suffix = CLASS_SUFFIX[className];
  if (suffix === undefined) {
    throw new Error(`ingest: ${JSON.stringify(className)} is not a tracked content class`);
  }
  return `${stem}_${suffix}`;
}

/**
 * Refusals that belong to the CALLER rather than to the operator.
 *
 * They are deliberately not failure-table rows and carry no STATUS-v1 status: a verb that
 * asks for an ingest without saying which project it belongs to is a defect that cannot be
 * correct on any host on any day, and putting it in the operator's failure table would tell
 * an operator to act on something they cannot act on. Same reasoning as the append
 * primitive's APPEND_REFUSAL and the lock-order rule's VIOLATION.
 */
export const INGEST_REFUSAL = Object.freeze({
  PROJECT_ID_REQUIRED: 'INGEST_PROJECT_ID_REQUIRED',
});

/**
 * Build an outcome for a frozen ingest row. The status and the sentence come from the table.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function ingestOutcome(code, params = {}, extra = {}) {
  return rowOutcome(code, params, extra);
}

/**
 * The item id a class's file name and `proj` identity are built from, or the frozen row that
 * says it is missing.
 *
 * Refusing HERE, before any byte is written, is the point: a receipt with no receipt_id
 * cannot be parsed by inventory-v1, so a file written for it would be an UNPARSEABLE source
 * of truth that every later rebuild trips over - a permanent consequence for a transient
 * mistake.
 *
 * @param {string} className @param {object} record
 * @returns {{ok: boolean, id: string|null, field: string, outcome: Readonly<object>|null}}
 */
export function requireItemId(className, record) {
  const entry = inventoryEntryFor(className);
  if (entry === null) {
    return {
      ok: false,
      id: null,
      field: '',
      outcome: ingestOutcome(INGEST_CODE.UNCLASSIFIED, { path: '', class: className }),
    };
  }
  const value = record === null || typeof record !== 'object' ? undefined : record[entry.id_field];
  if (typeof value === 'string' && value.trim() !== '') {
    return { ok: true, id: value, field: entry.id_field, outcome: null };
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return { ok: true, id: String(value), field: entry.id_field, outcome: null };
  }
  return {
    ok: false,
    id: null,
    field: entry.id_field,
    outcome: ingestOutcome(
      ingestClassCode(INGEST_CLASS_STEM.SOURCE_UNPARSEABLE, className),
      { path: entry.spec, reason: `${PARSE_REASON.MISSING_FIELD}: ${entry.id_field}` },
    ),
  };
}

// -- where a new item is written ----------------------------------------------

/** Characters a file name may carry. Everything else is folded to a dash. */
const SAFE_NAME = /[^A-Za-z0-9._-]+/g;

/**
 * The file name stem for an item id.
 *
 * The id is the operator's, so it can carry anything - a slash, a colon, a character
 * Windows refuses. Folding it is not a rename: the id itself lives INSIDE the file and in
 * `proj`, which is what a query matches on. The path is how the bytes are found, and a path
 * that cannot be created is a write that fails for a reason unrelated to the receipt.
 *
 * @param {string} id @returns {string}
 */
export function fileStemFor(id) {
  const safe = String(id).replace(SAFE_NAME, '-').replace(/^-+|-+$/g, '').slice(0, 120);
  return safe === '' ? 'item' : safe;
}

/**
 * The root-relative, POSIX discovery path a new item of this class is written to.
 *
 * Composed from the frozen inventory-v1 entry rather than typed, so the write path and the
 * discovery path cannot disagree about where a class lives. `depth: 2` in that table is why
 * this is exactly one directory and one file name - a nested path would be UNCLASSIFIED at
 * discovery, and an UNCLASSIFIED source of truth is a file the index can only report as a
 * problem.
 *
 * @param {string} className @param {string} id @returns {string}
 */
export function relPathFor(className, id) {
  const entry = inventoryEntryFor(className);
  if (entry === null || !isDerivableClass(className)) {
    throw new Error(`ingest: ${JSON.stringify(className)} has no inventory-v1 discovery path`);
  }
  const name = entry.file ?? `${fileStemFor(id)}${entry.extension}`;
  return toPosix(path.posix.join(entry.dir, name));
}

/** @returns {ReadonlyArray<string>} the discovery specs this module writes into */
export function writtenDiscoveryPaths() {
  return Object.freeze(
    INVENTORY_V1.filter((entry) => isDerivableClass(entry.class)).map((entry) => entry.spec),
  );
}

// -- pre-flight ----------------------------------------------------------------

/**
 * The reasons a parse failure maps to a row that is NOT plain UNPARSEABLE.
 *
 * MOJIBAKE and EMPTY are separate rows on purpose (W3): a mojibake document parses
 * perfectly and is silently wrong forever if it is called unparseable, and a valid-but-empty
 * file is a state the operator acts on differently from a damaged one.
 */
const PARSE_REASON_STEM = Object.freeze({
  [PARSE_REASON.MOJIBAKE]: INGEST_CLASS_STEM.SOURCE_MOJIBAKE,
  [PARSE_REASON.EMPTY_FILE]: INGEST_CLASS_STEM.SOURCE_EMPTY,
});

/**
 * Everything that must be true BEFORE any byte is written.
 *
 * Order matters and is the point: the bytes are validated FIRST, so a file the index could
 * never describe is never created. Writing it and then reporting the problem would leave an
 * UNPARSEABLE source of truth on disk for every later rebuild to trip over - a permanent
 * consequence for a transient mistake.
 *
 * @param {{class: string, project_id: string, root: string, rel: string, bytes: Buffer,
 *          fsx?: object}} req
 * @returns {Readonly<object>|null} a refusal outcome, or null when the write may proceed
 */
export function preflight(req) {
  const fsx = req.fsx ?? fs;
  const className = String(req.class);

  if (!isDerivableClass(className)) {
    return ingestOutcome(INGEST_CODE.UNCLASSIFIED, {
      path: req.rel,
      class: className,
    });
  }

  const abs = path.join(path.resolve(req.root), ...String(req.rel).split('/'));

  if (isOverMaxPath(abs) && openablePath(abs) === abs) {
    // Over MAX_PATH AND not rescuable by the extended-length prefix (a relative path, or a
    // host that has no such prefix). Its own row, never folded into a parse failure.
    return ingestOutcome(INGEST_CODE.PATH_TOO_LONG, { path: abs });
  }

  let rootStat;
  try {
    rootStat = fsx.statSync(openablePath(path.resolve(req.root)));
  } catch (err) {
    const errno = (err && err.code) || String(err);
    if (errno !== 'ENOENT') {
      // ENOENT is not a refusal here: the write path CREATES the class directory under a
      // registered root, and a root that has not been written to yet is the ordinary first
      // case. Anything else is a root the steward could not look at, which is UNREACHABLE
      // and is deliberately not the same fact as absent.
      return ingestOutcome(INGEST_CODE.ROOT_UNREACHABLE, { path: req.root, errno });
    }
    rootStat = null;
  }
  if (rootStat !== null && !rootStat.isDirectory()) {
    return ingestOutcome(INGEST_CODE.ROOT_UNREACHABLE, { path: req.root, errno: 'ENOTDIR' });
  }

  const hazard = targetHazard(abs, { fsx });
  if (hazard !== null) return hazard;

  const source = sourceProblem(className, req.bytes, abs);
  if (source !== null) return source;

  return null;
}

/**
 * The NG-2 hazards that can exist at the target path itself.
 *
 * A reparse point is not followed and a case collision is reported for BOTH paths, because
 * which of two entries differing only by case a case-insensitive filesystem serves is not
 * stable - and writing through either one would put the bytes somewhere the recorded path
 * does not name.
 *
 * @param {string} abs @param {{fsx?: object}} [opts] @returns {Readonly<object>|null}
 */
export function targetHazard(abs, opts = {}) {
  const fsx = opts.fsx ?? fs;
  const dir = path.dirname(abs);
  const base = path.basename(abs);

  let stat = null;
  try {
    stat = fsx.lstatSync(openablePath(abs));
  } catch {
    stat = null;
  }
  if (stat !== null && typeof stat.isSymbolicLink === 'function' && stat.isSymbolicLink()) {
    let target = '';
    try {
      target = fsx.readlinkSync(openablePath(abs));
    } catch {
      target = '';
    }
    return ingestOutcome(INGEST_CODE.SKIPPED_REPARSE, { path: abs, target });
  }

  let names = [];
  try {
    names = fsx
      .readdirSync(openablePath(dir))
      .map((entry) => (typeof entry === 'string' ? entry : entry.name));
  } catch {
    return null; // the directory does not exist yet: nothing can collide with the new file
  }
  const collisions = detectCaseCollisions([...names, base]);
  const group = collisions.get(base.toLowerCase());
  if (group !== undefined && group.some((name) => name !== base)) {
    const other = group.find((name) => name !== base);
    return ingestOutcome(INGEST_CODE.CASE_COLLISION, {
      path: abs,
      other_path: path.join(dir, String(other)),
    });
  }
  return null;
}

/**
 * Does this class's parse gate accept these bytes? Reported as the row the reason names.
 *
 * @param {string} className @param {Buffer} bytes @param {string} abs
 * @returns {Readonly<object>|null}
 */
export function sourceProblem(className, bytes, abs) {
  const parsed = sourceRecordFor(className, bytes, abs);
  if (parsed.ok) return null;
  const stem = PARSE_REASON_STEM[parsed.reason] ?? INGEST_CLASS_STEM.SOURCE_UNPARSEABLE;
  const params = { path: abs, reason: parsed.reason ?? '', offset: 0 };
  if (parsed.detail !== null && parsed.detail !== undefined) {
    params.reason = `${parsed.reason}: ${parsed.detail}`;
    const at = /byte (\d+)/.exec(String(parsed.detail));
    if (at !== null) params.offset = Number(at[1]);
  }
  return ingestOutcome(ingestClassCode(stem, className), params);
}

// -- the emitter ---------------------------------------------------------------

/**
 * How an append failure maps onto the ingest table.
 *
 * A lock timeout and an undetermined durability are NOT the same fact as a failed write, and
 * the operator acts on each differently: the first is contention that will pass, the second
 * is a state only the sweep can settle, the third is a store that would not take the bytes.
 * Collapsing all three into one code would be the laundering the whole table exists against.
 *
 * @param {object|null} appendOutcome @returns {string} the ingest row code
 */
export function ingestCodeForAppendFailure(appendOutcome) {
  const code = appendOutcome && appendOutcome.code ? appendOutcome.code : '';
  if (code === INDEX_WRITE_CODE.LOCK_TIMEOUT) return INGEST_CODE.LOCK_TIMEOUT;
  return INGEST_CODE.APPEND_FAILED;
}

/**
 * THE WRITE-PATH EMITTER.
 *
 * One durable source-of-truth write plus exactly one derived-row-v1, in the frozen order.
 * The caller supplies the bytes; this function owns the ordering, the derivation and the
 * flush, and it is the only place the three are put together.
 *
 * `opts.write` exists so a caller with a SECOND file to persist under the same project lock
 * (engine/roadmap.mjs writes the roadmap container alongside the event carrier) can do so
 * without either inventing its own lock or holding two. It is handed the resolved path and
 * bytes and must make them durable; the default does exactly that through the existing
 * project write primitive.
 *
 * `opts.beforeFlush` is the crash window, made drivable: between the project lock's release
 * and the flush the source of truth is durable and the index knows nothing about it. That
 * window cannot be closed - it is two files and one power cut - so it is named, reproducible,
 * and repaired by the W8 divergence sweep.
 *
 * `opts.intent_paths` lets such a caller NAME that second file in the W15 commit-intent, with
 * the hash of the bytes it actually persisted. Only the caller has those bytes, and an intent
 * that guessed a hash would be a durability receipt for a file nobody read.
 *
 * @param {{class: string, project_id: string, root: string, rel?: string, id?: string,
 *          bytes: Buffer|Uint8Array|string, home?: string, paths?: object, env?: object,
 *          write?: (target: {abs: string, rel: string, bytes: Buffer}) => void,
 *          beforeFlush?: Function, supersedes?: number|null, appendOpts?: object,
 *          fsx?: object, boundMs?: number, reason?: string, intent_seq?: number,
 *          intent_paths?: Array<{path: string, sha256: string, byte_len: number}>,
 *          written_at?: string, now?: number|Date}} req
 * @returns {Readonly<object>}
 */
export function ingestWrite(req) {
  const fsx = req.fsx ?? fs;
  const className = String(req.class);
  if (typeof req.project_id !== 'string'
    || req.project_id.trim() === ''
    || !PROJECT_ID_PATTERN.test(req.project_id)) {
    const err = new Error(
      `${INGEST_REFUSAL.PROJECT_ID_REQUIRED}: an ingest must name the project it belongs to. `
      + 'project_id is minted once by steward register and travels with the root in its '
      + 'marker; it is never derived from a path, so there is nothing to guess here. '
      + `Got ${JSON.stringify(req.project_id)}. This is checked BEFORE the source of truth is `
      + 'written, because W15 emits a commit-intent naming this id in the same flush as the '
      + 'row, and an id no receipt can carry must stop the write rather than land a file that '
      + 'nothing can ever ask to have committed.',
    );
    err.code = INGEST_REFUSAL.PROJECT_ID_REQUIRED;
    throw err;
  }
  const root = path.resolve(String(req.root));
  const rel = toPosix(
    String(req.rel ?? (isDerivableClass(className) ? relPathFor(className, req.id ?? '') : '')),
  );
  const bytes = Buffer.isBuffer(req.bytes)
    ? req.bytes
    : Buffer.from(String(req.bytes ?? ''), 'utf8');
  const abs = path.join(root, ...rel.split('/'));

  const refused = preflight({ class: className, project_id: req.project_id, root, rel, bytes, fsx });
  if (refused !== null) {
    return Object.freeze({
      ...refused,
      version: INGEST_VERSION,
      project_id: String(req.project_id),
      class: className,
      path: rel,
      abs_path: abs,
      sot_written: false,
      row: null,
      seq: null,
      trace: Object.freeze([]),
      freshness: FRESHNESS.UNKNOWN,
    });
  }

  // The supersedes lineage is read BEFORE the project lock is taken, because reading the
  // index takes the ONE portfolio lock and W8 forbids holding both. A row whose predecessor
  // moved between this read and the flush is not a correctness problem: `supersedes` records
  // which version this one replaced, and the append primitive's own seq guard is what
  // refuses a total order that has moved underneath the writer.
  const lineage = readLineage({ home: req.home, paths: req.paths, env: req.env });
  const supersedes = req.supersedes !== undefined
    ? req.supersedes
    : supersedesSeqFor(lineage.events, { project_id: req.project_id, class: className, path: rel });

  // W15. The commit-intent's PER-PROJECT sequence, read from the same lineage and for the
  // same reason: allocating it needs the log, reading the log needs the portfolio lock, and
  // W8 forbids taking that while the project lock is held. So it is allocated here, the
  // intent is built inside the lock beside the row it accompanies, and both ride the ONE
  // flush - which is what makes them share a total order rather than merely usually arrive
  // together.
  const intentSeq = req.intent_seq !== undefined
    ? req.intent_seq
    : nextSeqFor(lastCommitIntentSeq(materializeRegistry(lineage.events), req.project_id));
  const intentReason = req.reason ?? COMMIT_REASON_FOR[className] ?? null;
  // Paths the SAME durable write persisted beyond the class file itself - the roadmap
  // container is the one real case. They are supplied by the caller because only the caller
  // holds their bytes, and an intent naming a path whose hash it guessed would be worse than
  // one that named fewer paths honestly.
  const extraPaths = Array.isArray(req.intent_paths) ? req.intent_paths : [];
  const intentAt = req.written_at ?? new Date(req.now ?? Date.now()).toISOString();

  // BUILT BEFORE THE LOCK, and that ordering is the whole point: every field it validates -
  // the id, the root-relative paths, the sequence, the reason - is known before a single byte
  // is written, so an intent this engine could not construct stops the write instead of
  // leaving a file on disk that nothing will ever ask to have committed. Constructing it
  // inside the lock would put that refusal AFTER the source of truth was durable, which is
  // the one place a refusal is useless.
  const intent = intentReason === null ? null : makeCommitIntent({
    project_id: req.project_id,
    seq: intentSeq,
    reason: intentReason,
    paths: [pathEntryFor(rel, bytes), ...extraPaths],
    written_at: intentAt,
  });

  const writeSot = typeof req.write === 'function'
    ? req.write
    : (target) => {
      fsx.mkdirSync(openablePath(path.dirname(target.abs)), { recursive: true });
      writeFileAtomicSync(target.abs, target.bytes.toString('utf8'));
    };

  let row = null;
  const result = withProjectLock(
    abs,
    (buffer) => {
      // 1. The source of truth, durable, through the existing write authority's primitive.
      writeSot({ abs, rel, bytes });
      // 2. The row, derived through the ONE shared function, and BUFFERED - not appended.
      //    An append here would hold the project lock and the portfolio lock at once, which
      //    the runtime guard in lock-order.mjs refuses by name.
      row = deriveRow(className, req.project_id, rel, bytes, { supersedes });
      buffer.add(row);
      // 3. W15: the receipt asking that these exact bytes be made durable off this box.
      //    It is BUFFERED beside the row rather than appended separately, so the intent and
      //    the DERIVED row share one ordering: a reader can never see a row whose intent has
      //    not landed, and a crash cannot leave the log claiming a file was indexed but
      //    never asked to be committed. It names the bytes it hashed - not the file it hopes
      //    is there - which is what makes it W14's tamper baseline rather than a wish.
      if (intent !== null) buffer.add(makeCommitIntentEvent(intent));
      return { abs, rel, byte_len: bytes.length };
    },
    {
      label: `${className}:${rel}`,
      // 4. and 5. happen inside withProjectLock, in this order and no other: the project
      //    lock is released, THEN the buffer is flushed through the W5 append primitive in a
      //    SINGLE batch, and only then does this call return.
      appendOpts: { ...(req.appendOpts ?? {}), home: req.home, paths: req.paths, env: req.env },
      beforeFlush: req.beforeFlush,
    },
  );

  const appended = result.append;
  const durable = appended && appended.ok === true && Array.isArray(appended.appended)
    ? appended.appended
    : [];
  // Position, not search: the buffer was filled row-then-intent, the primitive appends a
  // batch in order, and reading them back by index is what keeps "they share one ordering"
  // a fact rather than a hope.
  const durableRow = durable[0] ?? null;
  const durableIntent = intent === null ? null : (durable[1] ?? null);

  if (result.ok !== true) {
    // The source of truth STANDS. It is the source of truth; discarding it to keep a derived
    // artifact tidy would destroy the only copy of the operator's work.
    const code = result.code === LOCK_ORDER_CODE.APPENDER_UNREGISTERED
      ? INGEST_CODE.APPEND_FAILED
      : ingestCodeForAppendFailure(appended);
    const reason = appended && appended.text
      ? appended.text
      : (result.flush && result.flush.text) || String(result.code);
    return Object.freeze({
      ...ingestOutcome(code, { path: abs, reason }),
      version: INGEST_VERSION,
      project_id: String(req.project_id),
      class: className,
      path: rel,
      abs_path: abs,
      sot_written: true,
      sot_intact: true,
      row,
      seq: null,
      supersedes,
      // The intent was BUILT and did not become durable. Reporting it as null rather than as
      // the object in hand is the same honesty the row gets: an intent that is not in the log
      // is not a receipt anybody can honour, and a caller that saw one here would report a
      // durability request that was never made.
      intent: null,
      intent_seq: null,
      intent_emitted: false,
      trace: Object.freeze([...result.trace]),
      buffered: result.buffered,
      // The project is behind its own files until the sweep catches up. That IS stale, and
      // saying so is what lets `steward doctor` and the next start act on it.
      freshness: FRESHNESS.STALE,
      append: appended,
      flush: result.flush,
    });
  }

  return Object.freeze({
    ok: true,
    code: null,
    status: INTEGRITY.OK,
    version: INGEST_VERSION,
    text: '',
    project_id: String(req.project_id),
    class: className,
    path: rel,
    abs_path: abs,
    sot_written: true,
    sot_intact: true,
    row: durableRow ?? row,
    derived: row,
    // The DERIVED row's OWN log seq, read off the event the primitive appended. The batch's
    // last seq belongs to the intent, and reporting that here would quietly renumber every
    // caller's row the day a second event joined the flush.
    seq: durableRow ? Number(durableRow.seq) : null,
    supersedes,
    // W15: exactly one intent per durable write, durable in the same batch as the row.
    intent,
    intent_seq: intent === null ? null : intent.seq,
    intent_log_seq: durableIntent ? Number(durableIntent.seq) : null,
    intent_emitted: durableIntent !== null,
    trace: Object.freeze([...result.trace]),
    buffered: result.buffered,
    freshness: FRESHNESS.FRESH,
    presence: PRESENCE.LIVE,
    append: appended,
    flush: result.flush,
  });
}

/**
 * Read the log's events so a new row can name the version it supersedes.
 *
 * A read that fails is NOT a refusal: an index that cannot be read yet (a first write on a
 * fresh machine) has no lineage, and refusing the write would make the very first receipt
 * unwritable. The flush is where an unreachable index becomes a reported failure, which is
 * the right place - by then the operator's file is safe.
 *
 * @param {object} opts @returns {{ok: boolean, events: Array<object>, head_seq: number}}
 */
export function readLineage(opts = {}) {
  const read = openIndexForRead(opts);
  const events = Array.isArray(read.events) ? read.events : [];
  return { ok: read.ok === true, events, head_seq: Number(read.head_seq ?? 0) };
}

// -- the D-3 find surface ------------------------------------------------------

/**
 * The rows the index can answer for RIGHT NOW: the snapshot body plus a replay of the log
 * tail after `freshness.head_seq`, merged before results are returned.
 *
 * This is D-3, and it is the reason step 4 of the ordering costs nothing: a row appended to
 * the log is visible to the very next read WITHOUT the snapshot being rewritten. The two
 * deleted branches are worth naming so nobody reintroduces them - snapshot-only would leave
 * a receipt written a second ago unfindable, and a full re-materialize per write would make
 * every write cost O(portfolio) and kill the flat-append guard.
 *
 * NO PROJECT ROOT IS OPENED. The answer comes from inside the ONE index home, which is what
 * keeps the C8 no-walk property true. `steward query` (W13) is the operator-facing surface
 * with its paging contract; this is the merge underneath it, stated once here so both cannot
 * disagree about what "the current rows" means.
 *
 * @param {{home?: string, paths?: object, env?: object, class?: string, project_id?: string,
 *          contains?: string}} [opts]
 * @returns {Readonly<{ok: boolean, rows: ReadonlyArray<object>, head_seq: number,
 *          tail_events: number, tail: object, outcome: object|null}>}
 */
export function findDerivedRows(opts = {}) {
  const read = openIndexForRead(opts);
  if (read.ok !== true) {
    return Object.freeze({
      ok: false,
      rows: Object.freeze([]),
      head_seq: 0,
      tail_events: 0,
      tail: capStatusFor('tail_events', 0),
      outcome: read,
    });
  }

  const stored = read.snapshot_value ?? null;
  const headSeq = Number(stored?.freshness?.head_seq ?? 0);
  const merged = new Map();

  // The snapshot's own rows first, so a tail row for the same identity replaces rather than
  // duplicates it. Identity is (project_id, class, path) - the same identity the rebuilder
  // and the sweep use, because three definitions of "the same row" is two too many.
  for (const stale of Array.isArray(stored?.body?.rows) ? stored.body.rows : []) {
    if (!isDerivedEvent(stale)) continue;
    merged.set(rowIdentity(stale), stale);
  }

  let tailCount = 0;
  for (const [, history] of derivedRowsInLog(read.events.filter((e) => Number(e.seq) > headSeq))) {
    tailCount += history.length;
    const latest = history[history.length - 1];
    merged.set(rowIdentity(latest), latest);
  }

  let rows = [...merged.values()];
  if (typeof opts.class === 'string' && opts.class !== '') {
    rows = rows.filter((r) => r.class === opts.class);
  }
  if (typeof opts.project_id === 'string' && opts.project_id !== '') {
    rows = rows.filter((r) => r.project_id === opts.project_id);
  }
  if (typeof opts.contains === 'string' && opts.contains !== '') {
    rows = rows.filter((r) => projContains(r, opts.contains));
  }
  rows.sort((a, b) => (rowIdentity(a) < rowIdentity(b) ? -1 : rowIdentity(a) > rowIdentity(b) ? 1 : 0));

  return Object.freeze({
    ok: true,
    rows: Object.freeze(rows),
    head_seq: read.head_seq ?? 0,
    tail_events: tailCount,
    // The tail is bounded by contract rather than by hope: past caps.tail_events the
    // disposition is to re-materialize the snapshot (D-3), which W13 wires to the query
    // surface. Reporting the level here is what lets that trigger be observed instead of
    // assumed.
    tail: capStatusFor('tail_events', tailCount),
    outcome: null,
  });
}

/**
 * The `--contains` predicate: a case-insensitive substring over a row's `proj` projection,
 * which is the only thing that is searched. Defined once here so the paged path and any
 * full-scan oracle cannot fork.
 *
 * @param {object} row @param {string} needle @returns {boolean}
 */
export function projContains(row, needle) {
  const want = String(needle).toLowerCase();
  const walk = (value) => {
    if (typeof value === 'string') return value.toLowerCase().includes(want);
    if (Array.isArray(value)) return value.some(walk);
    if (value !== null && typeof value === 'object') return Object.values(value).some(walk);
    return false;
  };
  return walk(row?.proj ?? {});
}

/**
 * The freshness of one project, computed rather than remembered.
 *
 * "The project reads STALE after a failed ingest flush" is only a real claim if something
 * can be ASKED. Storing a flag would make it a claim about this process's memory, which a
 * restart erases - and the state survives a restart, because it is a fact about two files
 * disagreeing. So it is derived: if the log carries no current row for a file that exists,
 * the project is behind its own bytes.
 *
 * The comparison is delegated to the W8 sweep's report, which is the module that owns
 * "what does the index say versus what is on disk". Passing the reporter in keeps this
 * module from importing the sweep and the sweep from importing this one.
 *
 * @param {string} projectId
 * @param {{report?: object, reporter?: Function, home?: string, paths?: object, env?: object}} opts
 * @returns {{freshness: string, project_id: string, missing: number, reason: string}}
 */
export function projectFreshness(projectId, opts = {}) {
  const id = String(projectId);
  const report = opts.report ?? (typeof opts.reporter === 'function' ? opts.reporter(opts) : null);
  if (report === null || report.ok !== true) {
    return {
      freshness: FRESHNESS.UNKNOWN,
      project_id: id,
      missing: 0,
      reason: 'the index could not be compared against the files on disk',
    };
  }
  const behind = (report.findings ?? []).filter(
    (f) => f.project_id === id && f.status === FRESHNESS.STALE,
  );
  if (behind.length > 0) {
    return {
      freshness: FRESHNESS.STALE,
      project_id: id,
      missing: behind.length,
      reason: `${behind.length} file(s) are durable on disk with no current row in the index`,
    };
  }
  return {
    freshness: FRESHNESS.FRESH,
    project_id: id,
    missing: 0,
    reason: 'every discovered file has a current row in the index',
  };
}

/** The caps this module is bound by, named so a test can cite the numbers it asserts. */
export const INGEST_CAPS = Object.freeze({
  proj_field_chars: CAPS.proj_field_chars,
  proj_array_entries: CAPS.proj_array_entries,
  tail_events: CAPS.tail_events,
});

/**
 * W5 - the D-1 append-only event log primitive.
 *
 * WHY THIS FILE EXISTS, AND WHY IT IS NOT writeFileAtomicSync. D-1 split the write
 * primitive BY PATH, and this is the half that owns the log. The loser branch - "route
 * every index write through writeFileAtomicSync" - is deleted from the plan, and it is
 * worth being explicit about what it would have cost, because a temp+rename looks like the
 * safer choice right up until you count: rename-per-append means reading the whole log,
 * writing the whole log, and renaming it, ONCE PER EVENT. That is O(log size) per event,
 * so a portfolio that grows gets slower per write forever, and the W8 flat-append guard
 * (bytes written per append stays flat) cannot hold by construction. Worse, it makes every
 * append a read-modify-write of the one file whose entire value is that it is never
 * rewritten - one interrupted rewrite and the ledger is shorter than it was.
 *
 * So the log is appended to, and only appended to:
 *
 *     openSync(log, 'a')  ->  ONE writeSync of ONE LF-terminated JSONL line
 *                         ->  fsyncSync  ->  closeSync
 *
 * all of it inside the portfolio lock. Every clause there is load-bearing:
 *
 *   'a' (O_APPEND)   the kernel places the bytes at the end atomically with respect to
 *                    other appenders, so two writers cannot interleave into one another's
 *                    offset even in the window between our fstat and our write.
 *   ONE writeSync    a line that reaches disk in two calls can be torn in the middle by a
 *                    kill; one call is the smallest window the platform offers.
 *   fsync BEFORE     success is a DURABILITY claim (criterion C2: no acknowledged event is
 *   success          lost). Reporting success from the page cache means the caller has
 *                    been told a thing that a power cut makes false. Everything in this
 *                    module is arranged so the return of `{ok: true}` happens after the
 *                    fsync returns, and never before.
 *
 * THE NG-4 ORDERING CONTRACT, in code rather than in a comment. `seq` is the SOLE total
 * order of this log. It is allocated as head_seq + 1 while the portfolio lock is held and
 * written into the same locked append, so allocation and use cannot be separated by
 * another writer. `written_at` is recorded because an operator reading a receipt wants to
 * know when it happened - and it is used for NOTHING else. It never orders, never
 * compares, never dedupes, and it never enters the snapshot `body` (D-2 confines wall
 * clock to the freshness block; engine/portfolio/snapshot-write.mjs refuses a body that
 * carries one). A clock that steps backwards over a DST boundary, a VM resumed from a
 * snapshot, an NTP correction - each of these reorders a wall-clock-ordered log and none
 * of them can reorder this one. replayEvents() is the single function anything replaying
 * this log calls, and it sorts by `seq` alone.
 *
 * TORN TAILS ARE MOVED, NEVER DROPPED. A process killed between writeSync and fsync can
 * leave a partial final line. The tempting fix - "ignore the last line if it does not
 * parse" - silently discards bytes the operator was told nothing about, which is the exact
 * dishonesty this whole plan is written against. Instead the torn bytes are COPIED to
 * <log>.torn-<seq>, fsynced there, and only then truncated off the live log, and the move
 * is counted in a recovery receipt. The quarantine file is the evidence; the receipt is
 * the report. An unparseable line in the MIDDLE of the log is a different fact - the log
 * cannot be read to its head - and it refuses rather than quarantining, because deleting
 * an interior line would renumber nothing and lose everything after it.
 *
 * NO PATH PROCEEDS WITHOUT THE LOCK, AND NO WAITER WAITS FOREVER. The portfolio lock is
 * taken through withFileLock() from engine/durable-write.mjs - the same lock every other
 * durable write in this engine uses, because a second lock implementation is how two
 * writers come to believe they both hold the same lock. W5 supplies it a stricter policy:
 * the lock file records pid + process start time + hostname, a waiter breaks a lock only
 * when the recorded pid is provably dead ON THIS HOST or the lock is older than the stale
 * bound, and a waiter that reaches the starvation bound fails with a NAMED status
 * (INDEX_WRITE_LOCK_TIMEOUT / INDEX_READ_LOCK_TIMEOUT) instead of blocking forever.
 * Failing loudly inside a bound is a behaviour; hanging is an absence of one.
 *
 * Every refusal in this module is a row from the frozen W3 failure tables, looked up by
 * code, so the status and the operator-visible sentence cannot drift from the table.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { withFileLock } from './durable-write.mjs';
import { scanBytesForMojibake } from './encoding.mjs';
// W8: the ABBA rule. lock-order.mjs deliberately does NOT import this module (the appender
// is registered at the bottom of this file instead), so the dependency runs one way only.
import {
  assertPortfolioLockPermitted,
  registerIndexAppender,
} from './portfolio/lock-order.mjs';
import { CAPS } from './portfolio/caps.mjs';
import { FRESHNESS, INTEGRITY, PATH_HAZARD, PRESENCE } from './portfolio/status.mjs';
import { fillRowText, rowOutcome } from './portfolio/failure-tables.mjs';
import {
  indexPathsFor,
  isInsideHome,
  resolveIndexPaths,
  tornLogPathFor,
} from './portfolio/home.mjs';
import { detectCaseCollisions, isOverMaxPath, openablePath } from './portfolio/inventory.mjs';

/** The primitive's frozen version. Changing the on-disk framing means append-log-v2. */
export const APPEND_LOG_VERSION = 'append-log-v1';

/** The ONE field that orders this log. Named here so no replayer invents a second one. */
export const ORDERING_FIELD = 'seq';

/** Recorded for reporting. Never used to order, compare, or dedupe. */
export const WALL_CLOCK_FIELD = 'written_at';

/** The two fields the primitive owns; a payload carrying either is refused, not merged. */
export const RESERVED_EVENT_FIELDS = Object.freeze([ORDERING_FIELD, WALL_CLOCK_FIELD]);

/** The seq of an empty log. The first event is therefore 1, never 0. */
export const EMPTY_HEAD_SEQ = 0;

/**
 * The width, in characters, of the column `seq` is written in.
 *
 * WHY THE ORDERING FIELD IS WRITTEN IN A COLUMN. The W8 guard is that the bytes written per
 * append do not grow with the log - flat, not "roughly flat", because a guard that tolerates
 * a slope cannot tell a gentle one from the O(log size) rewrite D-1 deleted. A decimal seq
 * is one character wider at every power of ten, so an unpadded line for event 2,001 is two
 * bytes longer than the line for event 1: a real, measurable slope in the exact quantity the
 * guard measures, produced by the log's own length. Padding the value out to a fixed column
 * removes it, so the cost of an append is a function of the PAYLOAD alone.
 *
 * The padding is whitespace between two JSON tokens, which is JSON (RFC 8259 section 2), so
 * the value on disk stays an ordinary integer: every reader parses it unchanged, nothing
 * decodes a string, and `seq` remains the numeric total order the rest of the module sorts
 * by. It also aligns the column for a human tailing the file, which is a side effect rather
 * than the reason.
 *
 * The width is the compaction ceiling's digit count, read from the frozen cap rather than
 * typed here: past that ceiling the disposition is WARN_THEN_COMPACT, so a log that outgrows
 * the column is a log that was already due to be compacted, and the flatness claim is stated
 * over exactly the range the caps say the log lives in.
 */
export const SEQ_COLUMN_WIDTH = String(CAPS.events_before_compaction).length;

/** The head of a primitive-shaped line: `{"seq":<digits>` and nothing assumed after it. */
const SEQ_COLUMN_HEAD = new RegExp(`^\\{"${ORDERING_FIELD}":(-?\\d+)`);

/**
 * The starvation bound: a waiter that has not acquired the portfolio lock within this many
 * milliseconds fails with a named status. This is the number the operator-visible text
 * reports as {bound_s}, and it is deliberately shorter than a human's patience.
 */
export const STARVATION_BOUND_MS = 10_000;

/** After this long with no liveness evidence, a lock is assumed orphaned. */
export const LOCK_STALE_MS = 30_000;

/** Bounded exponential backoff for a contended lock. */
export const LOCK_BACKOFF_BASE_MS = 8;
export const LOCK_BACKOFF_MAX_MS = 512;

/** The recovery receipt's schema id. */
export const RECOVERY_SCHEMA = 'log-recovery-v1';

/** The lock stamp's schema id, so a future field addition is detectable rather than guessed. */
export const LOCK_STAMP_SCHEMA = 'portfolio-lock-v1';

/**
 * Refusals that belong to the primitive rather than to a failure-table row: they are
 * PROGRAMMING errors (a caller handed the primitive something it may not append), not
 * operating states, and conflating the two would put a bug in the operator's failure table.
 */
export const APPEND_REFUSAL = Object.freeze({
  RESERVED_FIELD: 'APPEND_RESERVED_FIELD',
  NOT_SERIALIZABLE: 'APPEND_EVENT_NOT_SERIALIZABLE',
  EMBEDDED_NEWLINE: 'APPEND_EVENT_EMBEDDED_NEWLINE',
  NOT_AN_OBJECT: 'APPEND_EVENT_NOT_AN_OBJECT',
});

/** The failure-table codes this module can produce, named once so tests can enumerate them. */
export const INDEX_READ_CODE = Object.freeze({
  HOME_ABSENT: 'INDEX_READ_HOME_ABSENT',
  HOME_UNREACHABLE: 'INDEX_READ_HOME_UNREACHABLE',
  LOCK_TIMEOUT: 'INDEX_READ_LOCK_TIMEOUT',
  SNAPSHOT_UNPARSEABLE: 'INDEX_READ_SNAPSHOT_UNPARSEABLE',
  SNAPSHOT_MOJIBAKE: 'INDEX_READ_SNAPSHOT_MOJIBAKE',
  LOG_TORN_TAIL: 'INDEX_READ_LOG_TORN_TAIL',
  SNAPSHOT_UNREADABLE: 'INDEX_READ_SNAPSHOT_UNREADABLE',
  EMPTY: 'INDEX_READ_EMPTY',
  UNKNOWN: 'INDEX_READ_UNKNOWN',
  SKIPPED_REPARSE: 'INDEX_READ_SKIPPED_REPARSE',
  PATH_TOO_LONG: 'INDEX_READ_PATH_TOO_LONG',
  CASE_COLLISION: 'INDEX_READ_CASE_COLLISION',
});

/** @see INDEX_READ_CODE */
export const INDEX_WRITE_CODE = Object.freeze({
  HOME_ABSENT: 'INDEX_WRITE_HOME_ABSENT',
  HOME_UNREACHABLE: 'INDEX_WRITE_HOME_UNREACHABLE',
  LOCK_TIMEOUT: 'INDEX_WRITE_LOCK_TIMEOUT',
  TORN_APPEND: 'INDEX_WRITE_TORN_APPEND',
  SEQ_CONFLICT: 'INDEX_WRITE_SEQ_CONFLICT',
  LOG_UNPARSEABLE: 'INDEX_WRITE_LOG_UNPARSEABLE',
  DENIED: 'INDEX_WRITE_DENIED',
  EMPTY_BATCH: 'INDEX_WRITE_EMPTY_BATCH',
  MOJIBAKE_REFUSED: 'INDEX_WRITE_MOJIBAKE_REFUSED',
  UNKNOWN: 'INDEX_WRITE_UNKNOWN',
  SKIPPED_REPARSE: 'INDEX_WRITE_SKIPPED_REPARSE',
  PATH_TOO_LONG: 'INDEX_WRITE_PATH_TOO_LONG',
  CASE_COLLISION: 'INDEX_WRITE_CASE_COLLISION',
});

// -- outcomes ------------------------------------------------------------------

/**
 * Build the outcome for a frozen failure row.
 *
 * The status and the sentence are READ from the W3 table, never typed here, so this module
 * cannot drift from the operator's documentation - which is the entire reason the rows
 * live in code. The builder itself sits in failure-tables.mjs rather than here because the
 * OTHER half of the D-1 split (snapshot-write.mjs) needs the same builder, and the two
 * write primitives must not be able to reach each other: test/w50-write-primitive-lint
 * asserts that disjointness, and a shared helper parked in either one would break it.
 *
 * @param {string} code @param {Record<string, unknown>} [params]
 * @param {{ok?: boolean}} [extra]
 * @returns {Readonly<object>}
 */
export function indexOutcome(code, params = {}, extra = {}) {
  return rowOutcome(code, params, extra);
}

export { fillRowText };

/** An outcome as a throwable, for the call sites (the lock) that can only signal by throwing. */
export class IndexRefusal extends Error {
  /** @param {Readonly<object>} outcome */
  constructor(outcome) {
    super(`${outcome.code}: ${outcome.text}`);
    this.name = 'IndexRefusal';
    this.code = outcome.code;
    this.status = outcome.status;
    this.text = outcome.text;
    this.outcome = outcome;
  }
}

/** @param {unknown} err @returns {boolean} */
export function isIndexRefusal(err) {
  return err instanceof IndexRefusal;
}

/**
 * A filesystem facade with every method the module uses, so a test can inject ONE
 * behaviour (an fsync that fails, an open that is denied) without having to hand-build a
 * whole fs. Errno paths that a normal host will not produce on demand are exactly the
 * paths a failure table promises are handled, so they must be drivable.
 *
 * @param {object|undefined} partial @returns {object}
 */
function fsFacade(partial) {
  return partial ? { ...fs, ...partial } : fs;
}

// -- paths ---------------------------------------------------------------------

/**
 * Resolve the index paths a call is about. Every entry point takes the same shape so no
 * caller ever composes `join(home, 'portfolio.jsonl')` for itself - the file names are
 * frozen in home.mjs and read from there.
 *
 * @param {{paths?: object, home?: string, env?: Record<string, string|undefined>}} [opts]
 * @returns {{home: string, log: string, snapshot: string, lock: string}}
 */
export function indexPathsFrom(opts = {}) {
  if (opts.paths && typeof opts.paths === 'object') {
    return indexPathsFor(opts.paths.home ?? path.dirname(String(opts.paths.log ?? '.')));
  }
  if (typeof opts.home === 'string' && opts.home.trim() !== '') return indexPathsFor(opts.home);
  return indexPathsFor(resolveIndexPaths(opts.env ?? process.env).home);
}

// -- the lock ------------------------------------------------------------------

/**
 * What the holder records about itself.
 *
 * pid alone is not enough to decide liveness: pids are recycled, and a pid from ANOTHER
 * machine (a network-mounted index home) says nothing about this one. So the stamp carries
 * the hostname, which scopes the liveness question, and the holder's process start time,
 * which is what distinguishes "pid 1234, still running" from "pid 1234, recycled onto an
 * unrelated program".
 *
 * @param {{now?: number, pid?: number, hostname?: string, uptimeMs?: number}} [parts]
 * @returns {string} one LF-terminated JSON line
 */
export function lockStampText(parts = {}) {
  const now = Number.isFinite(parts.now) ? Number(parts.now) : Date.now();
  const uptimeMs = Number.isFinite(parts.uptimeMs)
    ? Number(parts.uptimeMs)
    : Math.round(process.uptime() * 1000);
  return `${JSON.stringify({
    schema: LOCK_STAMP_SCHEMA,
    pid: parts.pid ?? process.pid,
    hostname: parts.hostname ?? os.hostname(),
    started_at: new Date(now - uptimeMs).toISOString(),
    acquired_at: new Date(now).toISOString(),
  })}\n`;
}

/** @param {string} text @returns {object|null} the parsed stamp, or null if unreadable */
export function parseLockStamp(text) {
  try {
    const value = JSON.parse(String(text));
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * Is `pid` a live process on THIS host?
 *
 * signal 0 performs the permission and existence checks without delivering anything. EPERM
 * means the process exists and belongs to somebody else - which is liveness, so it must
 * NOT be read as death, or a lock held by another user's live steward would be broken.
 *
 * @param {number} pid @param {{kill?: Function}} [opts] @returns {boolean}
 */
export function isProcessAlive(pid, opts = {}) {
  const kill = typeof opts.kill === 'function' ? opts.kill : process.kill.bind(process);
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    kill(pid, 0);
    return true;
  } catch (err) {
    return Boolean(err && err.code === 'EPERM');
  }
}

/**
 * The portfolio lock's staleness policy: PID liveness first, age as the fallback.
 *
 * Age alone cannot tell a killed writer from a slow one, so an age-only policy must pick
 * between breaking live locks (data loss) and wedging forever (a hang). Liveness answers
 * the question directly whenever the holder is on this host. When it is not - a network
 * index home, another machine's pid - liveness is unanswerable and age is all there is,
 * which is stated here rather than pretended away.
 *
 * @param {string} lockPath @param {number} staleMs
 * @param {{now?: number, hostname?: string, kill?: Function, fsx?: object}} [opts]
 * @returns {boolean}
 */
export function portfolioLockIsStale(lockPath, staleMs, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  const hostname = opts.hostname ?? os.hostname();
  const now = Number.isFinite(opts.now) ? Number(opts.now) : Date.now();

  let stat;
  try {
    stat = fsx.statSync(openablePath(lockPath));
  } catch {
    return false; // vanished: the next acquire wins on its own
  }

  let stamp = null;
  try {
    stamp = parseLockStamp(fsx.readFileSync(openablePath(lockPath), 'utf8'));
  } catch {
    stamp = null;
  }

  if (stamp !== null && stamp.hostname === hostname && Number.isInteger(stamp.pid)) {
    if (!isProcessAlive(stamp.pid, opts)) return true;
    return false; // a live holder is never broken, however old the lock looks
  }

  // Age is the fallback, and it is measured across two clocks that do not agree: `now` comes
  // from the wall clock, `mtimeMs` from the filesystem's own stamp, which on Windows carries
  // sub-millisecond precision and can read slightly AHEAD of Date.now(). A raw subtraction
  // therefore goes negative on a lock that was just taken, which would make a bound the caller
  // meant as "anything at all is stale" behave as "nothing is stale". A lock cannot be younger
  // than nothing, so skew is floored at zero rather than allowed to invent negative age.
  const ageMs = Math.max(0, now - stat.mtimeMs);
  return ageMs > staleMs;
}

/** @param {number} attempt @returns {number} the bounded exponential wait, in ms */
export function lockBackoffFor(attempt) {
  const step = LOCK_BACKOFF_BASE_MS * 2 ** Math.max(0, Number(attempt) || 0);
  return Math.min(LOCK_BACKOFF_MAX_MS, step);
}

/**
 * Run `fn` holding the ONE portfolio lock.
 *
 * @param {{home: string, log: string, lock: string}} paths
 * @param {() => T} fn
 * @param {{boundMs?: number, staleMs?: number, timeoutCode?: string, lockOpts?: object}} [opts]
 * @returns {T}
 * @template T
 */
export function withPortfolioLock(paths, fn, opts = {}) {
  const boundMs = Number.isFinite(opts.boundMs) ? Number(opts.boundMs) : STARVATION_BOUND_MS;
  const timeoutCode = opts.timeoutCode ?? INDEX_WRITE_CODE.LOCK_TIMEOUT;
  // W8 lock-order rule, checked BEFORE the lock is taken rather than after: a call site
  // holding a project lock must buffer its events and flush them once the project lock is
  // released. Holding both is the ABBA deadlock, and it is refused where it is committed.
  assertPortfolioLockPermitted(opts.where ?? paths.log);
  return withFileLock(paths.log, fn, {
    lockPath: paths.lock,
    timeoutMs: boundMs,
    staleMs: Number.isFinite(opts.staleMs) ? Number(opts.staleMs) : LOCK_STALE_MS,
    stamp: () => lockStampText(),
    isStale: (lockPath, staleMs) => portfolioLockIsStale(lockPath, staleMs, opts.lockOpts ?? {}),
    backoffFor: lockBackoffFor,
    onTimeout: (info) => {
      const stamp = parseLockStamp(info.holder);
      return new IndexRefusal(
        indexOutcome(timeoutCode, {
          pid: stamp && stamp.pid !== undefined ? stamp.pid : '?',
          bound_s: Math.round(boundMs / 100) / 10,
          waited_ms: info.waited_ms,
          attempts: info.attempts,
          lock: info.lockPath,
        }),
      );
    },
  });
}

// -- the event shape -----------------------------------------------------------

/**
 * Compose a log event. The primitive owns `seq` and `written_at`; a payload carrying
 * either is REFUSED rather than overwritten, because silently winning that collision is
 * how a per-project sequence number (commit-intent-v1 has one) ends up masquerading as the
 * log's total order.
 *
 * @param {object} payload @param {{seq: number, written_at?: string, now?: number|Date}} parts
 * @returns {object}
 */
export function makeLogEvent(payload, parts) {
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
    const err = new Error(`${APPEND_REFUSAL.NOT_AN_OBJECT}: a log event must be a plain object`);
    err.code = APPEND_REFUSAL.NOT_AN_OBJECT;
    throw err;
  }
  for (const field of RESERVED_EVENT_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(payload, field)) {
      const err = new Error(
        `${APPEND_REFUSAL.RESERVED_FIELD}: the payload carries '${field}', which the append ` +
          'primitive allocates. Nest your own sequence or timestamp under a named key so the ' +
          "log's total order cannot be confused with a caller's counter.",
      );
      err.code = APPEND_REFUSAL.RESERVED_FIELD;
      throw err;
    }
  }
  const at =
    typeof parts.written_at === 'string'
      ? parts.written_at
      : new Date(parts.now ?? Date.now()).toISOString();

  const rest = {};
  for (const key of Object.keys(payload).sort()) rest[key] = payload[key];
  return { [ORDERING_FIELD]: Number(parts.seq), [WALL_CLOCK_FIELD]: at, ...rest };
}

/**
 * Widen the `seq` token to SEQ_COLUMN_WIDTH with the whitespace JSON already allows between
 * tokens, so one payload shape has one line length whatever the log's head is.
 *
 * An object that does not begin with the ordering field is returned untouched: this aligns
 * the primitive's own framing, and it may not invent a column in somebody else's bytes.
 *
 * @param {string} json @returns {string}
 */
function padSeqColumn(json) {
  const head = SEQ_COLUMN_HEAD.exec(json);
  if (head === null) return json;
  const pad = SEQ_COLUMN_WIDTH - head[1].length;
  if (pad <= 0) return json;
  return `${json.slice(0, head[0].length)}${' '.repeat(pad)}${json.slice(head[0].length)}`;
}

/**
 * Serialize one event to its on-disk line: exactly one JSON object, exactly one trailing
 * LF, and no interior newline - an event whose serialization contained one would become
 * two lines, one of which would parse and one of which would look like a torn tail.
 *
 * @param {object} event @returns {string}
 */
export function logEventLine(event) {
  let json;
  try {
    json = JSON.stringify(event);
  } catch (err) {
    const wrapped = new Error(`${APPEND_REFUSAL.NOT_SERIALIZABLE}: ${err.message}`);
    wrapped.code = APPEND_REFUSAL.NOT_SERIALIZABLE;
    throw wrapped;
  }
  if (typeof json !== 'string') {
    const err = new Error(`${APPEND_REFUSAL.NOT_SERIALIZABLE}: the event serialized to nothing`);
    err.code = APPEND_REFUSAL.NOT_SERIALIZABLE;
    throw err;
  }
  if (json.includes('\n') || json.includes('\r')) {
    const err = new Error(
      `${APPEND_REFUSAL.EMBEDDED_NEWLINE}: the serialized event carries a raw newline, which ` +
        'would split one event across two log lines',
    );
    err.code = APPEND_REFUSAL.EMBEDDED_NEWLINE;
    throw err;
  }
  // The column is applied AFTER the framing checks: it only ever adds spaces, so it cannot
  // introduce the newline those checks exist to refuse.
  return `${padSeqColumn(json)}\n`;
}

/**
 * The comparison the whole system orders by: `seq`, and nothing else.
 *
 * @param {{seq: number}} a @param {{seq: number}} b @returns {number}
 */
export function compareBySeq(a, b) {
  const left = Number(a?.[ORDERING_FIELD]);
  const right = Number(b?.[ORDERING_FIELD]);
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

/**
 * Replay order. The ONE function anything replaying this log calls.
 *
 * It does not look at `written_at`. That is the point: two events whose wall clocks run
 * backwards - a DST step, an NTP correction, a resumed VM - replay in exactly the order
 * they were appended, because the order was decided at append time under the lock and
 * written into the bytes.
 *
 * @param {Array<object>} events @returns {Array<object>}
 */
export function replayEvents(events) {
  return [...(events ?? [])].sort(compareBySeq);
}

/**
 * Is `seq` a clean total order over these events - no duplicate, no gap, strictly ascending
 * from 1? Reported rather than thrown, so a caller can render the damage.
 *
 * @param {Array<object>} events @returns {{ok: boolean, head_seq: number, duplicates: number[],
 *          gaps: number[], count: number}}
 */
export function seqIntegrity(events) {
  const ordered = replayEvents(events);
  const seen = new Set();
  const duplicates = [];
  const gaps = [];
  let expected = 1;
  for (const event of ordered) {
    const seq = Number(event?.[ORDERING_FIELD]);
    if (seen.has(seq)) duplicates.push(seq);
    seen.add(seq);
    while (expected < seq) {
      gaps.push(expected);
      expected += 1;
    }
    expected = seq + 1;
  }
  const head = ordered.length ? Number(ordered[ordered.length - 1][ORDERING_FIELD]) : EMPTY_HEAD_SEQ;
  return {
    ok: duplicates.length === 0 && gaps.length === 0,
    head_seq: head,
    duplicates,
    gaps,
    count: ordered.length,
  };
}

// -- reading the log bytes -----------------------------------------------------

/**
 * Read the log's raw bytes.
 *
 * @param {string} logPath @param {{fsx?: object}} [opts]
 * @returns {{exists: boolean, bytes: Buffer, size: number, error: object|null}}
 */
export function readLogBytes(logPath, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  try {
    // encoding-lint: raw-bytes - a torn tail is a BYTE fact. Decoding first would replace
    // the truncated multi-byte sequence with U+FFFD and destroy the evidence of the tear.
    const bytes = fsx.readFileSync(openablePath(logPath));
    const buf = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
    return { exists: true, bytes: buf, size: buf.length, error: null };
  } catch (err) {
    if (err && err.code === 'ENOENT') {
      return { exists: false, bytes: Buffer.alloc(0), size: 0, error: null };
    }
    return { exists: false, bytes: Buffer.alloc(0), size: 0, error: err };
  }
}

/**
 * Split log bytes into complete LF-terminated records plus any trailing fragment.
 *
 * The fragment is the interesting part: bytes after the final LF are, by definition, a
 * line whose terminator never reached disk - which is exactly the shape a kill between
 * writeSync and fsync leaves behind.
 *
 * @param {Buffer} bytes
 * @returns {{records: Array<{text: string, start: number, end: number, line: number}>,
 *            fragment: {text: string, start: number, byte_len: number}|null}}
 */
export function scanLogBytes(bytes) {
  const buf = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes ?? []);
  const records = [];
  let start = 0;
  let line = 0;
  for (let i = 0; i < buf.length; i += 1) {
    if (buf[i] !== 0x0a) continue;
    line += 1;
    records.push({
      text: buf.toString('utf8', start, i),
      start,
      end: i + 1,
      line,
    });
    start = i + 1;
  }
  const fragment =
    start < buf.length
      ? { text: buf.toString('utf8', start, buf.length), start, byte_len: buf.length - start }
      : null;
  return { records, fragment };
}

/**
 * Parse scanned records into events, keeping every failure addressable by line.
 *
 * @param {Array<{text: string, line: number, start: number, end: number}>} records
 * @returns {{events: Array<object>, problems: Array<object>, blanks: number}}
 */
export function parseLogRecords(records) {
  const events = [];
  const problems = [];
  let blanks = 0;
  for (const record of records ?? []) {
    if (record.text.trim() === '') {
      blanks += 1;
      continue;
    }
    let value;
    try {
      value = JSON.parse(record.text);
    } catch (err) {
      problems.push({
        line: record.line,
        offset: record.start,
        byte_len: record.end - record.start,
        reason: err.message,
        integrity: INTEGRITY.UNPARSEABLE,
      });
      continue;
    }
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      problems.push({
        line: record.line,
        offset: record.start,
        byte_len: record.end - record.start,
        reason: 'a log record must be a JSON object',
        integrity: INTEGRITY.UNPARSEABLE,
      });
      continue;
    }
    if (!Number.isInteger(value[ORDERING_FIELD])) {
      problems.push({
        line: record.line,
        offset: record.start,
        byte_len: record.end - record.start,
        reason: `a log record must carry an integer ${ORDERING_FIELD}`,
        integrity: INTEGRITY.UNPARSEABLE,
      });
      continue;
    }
    events.push(value);
  }
  return { events, problems, blanks };
}

// -- torn-tail quarantine ------------------------------------------------------

/**
 * Quarantine a torn final line, if there is one, and report what happened.
 *
 * Order of operations is the guarantee: the torn bytes are written to the sidecar and
 * FSYNCED there BEFORE the live log is truncated. Do it the other way round and a crash in
 * between destroys the very bytes the quarantine exists to preserve.
 *
 * The live log is truncated, never rewritten and never renamed - D-1 says the log is
 * append-only, and truncating a trailing fragment removes bytes that are already
 * quarantined without disturbing a single byte of any complete record before it.
 *
 * @param {string} logPath
 * @param {{fsx?: object, quarantine?: boolean}} [opts]
 * @returns {Readonly<object>} the recovery receipt
 */
export function recoverLogTail(logPath, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  const quarantine = opts.quarantine !== false;
  const read = readLogBytes(logPath, { fsx });
  if (read.error) {
    return Object.freeze({
      schema: RECOVERY_SCHEMA,
      log: logPath,
      ok: false,
      errno: read.error.code ?? null,
      quarantined: Object.freeze([]),
      quarantined_count: 0,
      bytes_quarantined: 0,
      blank_records: 0,
      head_seq: EMPTY_HEAD_SEQ,
      events_kept: 0,
      interior_problems: Object.freeze([]),
      // Presence and integrity are separate axes and stay separate here: a log whose bytes
      // could not be obtained has no integrity verdict at all, and inventing one would be
      // exactly the laundering status.mjs refuses in code.
      presence: PRESENCE.UNREACHABLE,
      integrity: null,
    });
  }

  const { records, fragment } = scanLogBytes(read.bytes);
  const parsed = parseLogRecords(records);

  // The torn tail is the LAST thing in the file and only the last thing: a trailing
  // fragment with no LF, or a final complete line that does not parse. An unparseable
  // line anywhere else is an interior problem and is reported, never quarantined.
  let tornStart = null;
  let tornBytes = null;
  let tornReason = null;

  if (fragment !== null) {
    tornStart = fragment.start;
    tornBytes = read.bytes.subarray(fragment.start, read.bytes.length);
    tornReason = 'the final line has no terminator - it was truncated mid-write';
  } else if (records.length > 0) {
    const lastRecord = records[records.length - 1];
    const lastProblem = parsed.problems.find((p) => p.line === lastRecord.line);
    if (lastProblem !== undefined) {
      tornStart = lastRecord.start;
      tornBytes = read.bytes.subarray(lastRecord.start, lastRecord.end);
      tornReason = `the final line does not parse: ${lastProblem.reason}`;
    }
  }

  const interior = parsed.problems.filter((p) => tornStart === null || p.offset < tornStart);
  // Events only ever come from COMPLETE, parseable records, so the torn tail is already
  // excluded from this set - nothing here needs to filter it out again.
  const survivors = parsed.events;
  const head = seqIntegrity(survivors).head_seq;

  if (tornStart === null) {
    return Object.freeze({
      schema: RECOVERY_SCHEMA,
      log: logPath,
      ok: true,
      errno: null,
      quarantined: Object.freeze([]),
      quarantined_count: 0,
      bytes_quarantined: 0,
      blank_records: parsed.blanks,
      head_seq: head,
      events_kept: survivors.length,
      interior_problems: Object.freeze(interior),
      presence: PRESENCE.LIVE,
      integrity: interior.length ? INTEGRITY.UNPARSEABLE : INTEGRITY.OK,
    });
  }

  // The seq the torn record would have occupied. Naming the quarantine after it is what
  // lets an operator line the sidecar up against the log's surviving head.
  const tornSeq = head + 1;
  const sidecar = tornLogPathFor(logPath, tornSeq);
  let moved = false;
  if (quarantine) {
    let fd;
    try {
      fd = fsx.openSync(openablePath(sidecar), 'w');
      fsx.writeSync(fd, tornBytes, 0, tornBytes.length);
      try {
        fsx.fsyncSync(fd);
      } catch {
        /* a filesystem that refuses fsync still has the bytes in the sidecar */
      }
      fsx.closeSync(fd);
      fd = undefined;
      fsx.truncateSync(openablePath(logPath), tornStart);
      moved = true;
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

  const entry = Object.freeze({
    path: sidecar,
    seq: tornSeq,
    byte_len: tornBytes.length,
    offset: tornStart,
    reason: tornReason,
    moved,
  });

  return Object.freeze({
    schema: RECOVERY_SCHEMA,
    log: logPath,
    ok: true,
    errno: null,
    quarantined: Object.freeze([entry]),
    quarantined_count: 1,
    bytes_quarantined: tornBytes.length,
    blank_records: parsed.blanks,
    head_seq: head,
    events_kept: survivors.length,
    interior_problems: Object.freeze(interior),
    presence: PRESENCE.LIVE,
    integrity: INTEGRITY.TORN,
  });
}

/**
 * The operator-visible sentence for a recovery receipt that quarantined something, taken
 * from the frozen row rather than composed here.
 *
 * @param {Readonly<object>} receipt @param {string} [code]
 * @returns {Readonly<object>|null}
 */
export function recoveryOutcome(receipt, code = INDEX_READ_CODE.LOG_TORN_TAIL) {
  if (!receipt || receipt.quarantined_count === 0) return null;
  const first = receipt.quarantined[0];
  return indexOutcome(code, { log: receipt.log, seq: first.seq, byte_len: first.byte_len }, { ok: true });
}

// -- the index home ------------------------------------------------------------

/**
 * The NG-2 hazards that can exist under the ONE index home, each resolved to its own named
 * row rather than to an exception or a silent skip.
 *
 * `readdirSync` and `lstatSync` are injectable because two of the three hazards cannot be
 * manufactured on a normal Windows host - it will not let two entries differ only by case,
 * and a junction may be refused - and a guard that is only ever exercised on a generous
 * host is a guard nobody has seen work.
 *
 * @param {{home: string, log: string, snapshot: string}} paths
 * @param {{fsx?: object, readdirSync?: Function, lstatSync?: Function, surface?: string}} [opts]
 * @returns {Array<Readonly<object>>}
 */
export function inspectIndexHome(paths, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  const readdirSync = opts.readdirSync ?? fsx.readdirSync ?? fs.readdirSync;
  const lstatSync = opts.lstatSync ?? fsx.lstatSync ?? fs.lstatSync;
  const write = opts.surface === 'write';
  const codes = write ? INDEX_WRITE_CODE : INDEX_READ_CODE;
  const found = [];

  for (const target of [paths.log, paths.snapshot]) {
    if (!isOverMaxPath(target)) continue;
    found.push(
      indexOutcome(codes.PATH_TOO_LONG, { path: target, prefix_used: true }, { ok: true }),
    );
  }

  let names = [];
  try {
    names = readdirSync(openablePath(paths.home)).map((entry) =>
      typeof entry === 'string' ? entry : entry.name,
    );
  } catch {
    return found; // the home's own presence is classified by the caller, not here
  }

  for (const collision of detectCaseCollisions(names)) {
    found.push(
      indexOutcome(codes.CASE_COLLISION, {
        path: path.join(paths.home, collision.names[0]),
        other_path: path.join(paths.home, collision.names[1]),
      }),
    );
  }

  for (const name of [...names].sort()) {
    const abs = path.join(paths.home, name);
    let stat;
    try {
      stat = lstatSync(openablePath(abs));
    } catch {
      continue;
    }
    if (!stat || typeof stat.isSymbolicLink !== 'function' || !stat.isSymbolicLink()) continue;
    let target = '';
    try {
      target = fsx.readlinkSync(openablePath(abs));
    } catch {
      target = '';
    }
    found.push(indexOutcome(codes.SKIPPED_REPARSE, { path: abs, target }));
  }

  return found;
}

/** @param {Array<Readonly<object>>} hazards @returns {Array<Readonly<object>>} the refusing ones */
export function refusingHazards(hazards) {
  return (hazards ?? []).filter((h) => h.ok !== true);
}

/**
 * Classify a home that could not be prepared. ENOENT is ABSENT - the steward looked and it
 * is not there; a permission failure is DENIED; anything else is UNREACHABLE, which is a
 * different fact and gets a different row.
 *
 * @param {object} err @param {boolean} write @returns {string} the failure-row code
 */
export function homeFailureCodeFor(err, write) {
  const code = err && err.code ? err.code : '';
  if (write) {
    if (code === 'EACCES' || code === 'EPERM') return INDEX_WRITE_CODE.DENIED;
    if (code === 'ENOENT') return INDEX_WRITE_CODE.HOME_ABSENT;
    return INDEX_WRITE_CODE.HOME_UNREACHABLE;
  }
  if (code === 'ENOENT') return INDEX_READ_CODE.HOME_ABSENT;
  return INDEX_READ_CODE.HOME_UNREACHABLE;
}

/**
 * Bring the index home into existence. This module is the only code that may - home.mjs
 * resolves and refuses to touch the disk, precisely so "where is it" and "does it exist"
 * stay separate questions.
 *
 * @param {{home: string}} paths @param {{fsx?: object}} [opts]
 * @returns {{ok: true}|Readonly<object>}
 */
export function ensureIndexHome(paths, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  try {
    fsx.mkdirSync(openablePath(paths.home), { recursive: true });
    return { ok: true };
  } catch (err) {
    return indexOutcome(homeFailureCodeFor(err, true), {
      home: paths.home,
      errno: err && err.code ? err.code : '',
    });
  }
}

/** Best effort: fsync the directory so a newly created entry is durable, not just its bytes. */
function fsyncDirBestEffort(dir, fsx = fs) {
  let fd;
  try {
    fd = fsx.openSync(openablePath(dir), 'r');
    fsx.fsyncSync(fd);
  } catch {
    // Windows refuses to open a directory handle this way; the rename/append is still
    // ordered by the filesystem, and pretending otherwise by throwing would fail a write
    // that actually succeeded.
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

// -- mojibake refusal ----------------------------------------------------------

/**
 * Find the first field whose text carries UTF-8-read-as-CP1252 damage.
 *
 * Refusing here rather than at read time is the only moment it can be refused: once the
 * damaged bytes are in the log, every hash taken over them is a faithful hash of damage,
 * and the log is append-only, so there is no later edit that removes it.
 *
 * @param {object} event @returns {{field: string, offset: number}|null}
 */
export function findMojibakeField(event) {
  const walk = (value, trail) => {
    if (typeof value === 'string') {
      const scan = scanBytesForMojibake(Buffer.from(value, 'utf8'));
      if (!scan.clean && scan.status === INTEGRITY.MOJIBAKE) {
        return { field: trail || '(root)', offset: scan.first_offset ?? 0 };
      }
      return null;
    }
    if (Array.isArray(value)) {
      for (let i = 0; i < value.length; i += 1) {
        const hit = walk(value[i], `${trail}[${i}]`);
        if (hit !== null) return hit;
      }
      return null;
    }
    if (value !== null && typeof value === 'object') {
      for (const key of Object.keys(value)) {
        const hit = walk(value[key], trail ? `${trail}.${key}` : key);
        if (hit !== null) return hit;
      }
    }
    return null;
  };
  return walk(event, '');
}

// -- the append primitive ------------------------------------------------------

/**
 * THE PRIMITIVE. One locked append is exactly this function: open in append mode, one
 * writeSync, fsync, close - and success returned only afterwards.
 *
 * `expected_size` is the seq-conflict guard. The seq was allocated from the log's head
 * while the lock was held; if the file has grown since, something appended without the
 * lock and the allocated seq is no longer head+1. Refusing is the only honest answer -
 * writing anyway would put two events in one log with the same total-order position.
 *
 * @param {string} logPath @param {string} line one LF-terminated line
 * @param {{expected_size?: number|null, fsx?: object}} [opts]
 * @returns {Readonly<object>} {ok:true, bytes_written, size_after} or a failure-row outcome
 */
export function appendLineAt(logPath, line, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  const expected = Number.isFinite(opts.expected_size) ? Number(opts.expected_size) : null;
  const bytes = Buffer.from(line, 'utf8');
  const isNew = !fsx.existsSync(openablePath(logPath));

  let fd;
  try {
    fd = fsx.openSync(openablePath(logPath), 'a');
  } catch (err) {
    const code = err && (err.code === 'EACCES' || err.code === 'EPERM')
      ? INDEX_WRITE_CODE.DENIED
      : INDEX_WRITE_CODE.HOME_UNREACHABLE;
    return indexOutcome(code, {
      home: path.dirname(logPath),
      path: logPath,
      errno: err && err.code ? err.code : '',
    });
  }

  let sizeBefore = expected ?? 0;
  try {
    try {
      sizeBefore = fsx.fstatSync(fd).size;
    } catch {
      sizeBefore = expected ?? 0;
    }
    if (expected !== null && sizeBefore !== expected) {
      return indexOutcome(INDEX_WRITE_CODE.SEQ_CONFLICT, {
        path: logPath,
        expected_size: expected,
        observed_size: sizeBefore,
      });
    }

    // ONE write. Not a loop, not a stream: the smallest window the platform offers between
    // "nothing" and "a whole line".
    let written;
    try {
      written = fsx.writeSync(fd, bytes, 0, bytes.length);
    } catch (err) {
      return indexOutcome(
        err && (err.code === 'EACCES' || err.code === 'EPERM')
          ? INDEX_WRITE_CODE.DENIED
          : INDEX_WRITE_CODE.UNKNOWN,
        { path: logPath, errno: err && err.code ? err.code : '', reason: String(err.message ?? err) },
      );
    }
    if (written !== bytes.length) {
      return indexOutcome(INDEX_WRITE_CODE.UNKNOWN, {
        path: logPath,
        reason: `the platform wrote ${written} of ${bytes.length} bytes in one call`,
      });
    }

    // The durability barrier. Everything before this is a promise; everything after it is
    // a fact, and only after it may this function say ok.
    try {
      fsx.fsyncSync(fd);
    } catch (err) {
      return indexOutcome(INDEX_WRITE_CODE.UNKNOWN, {
        path: logPath,
        reason: `fsync failed (${err && err.code ? err.code : String(err.message ?? err)})`,
      });
    }

    return Object.freeze({
      ok: true,
      code: null,
      path: logPath,
      bytes_written: bytes.length,
      size_before: sizeBefore,
      size_after: sizeBefore + bytes.length,
      durable: true,
    });
  } finally {
    if (fd !== undefined) {
      try {
        fsx.closeSync(fd);
      } catch {
        /* already closed */
      }
    }
    if (isNew) fsyncDirBestEffort(path.dirname(logPath), fsx);
  }
}

/**
 * Read the log to its head, under an already-held lock.
 *
 * @param {string} logPath @param {{fsx?: object, write?: boolean, quarantine?: boolean}} [opts]
 * @returns {{ok: boolean, head_seq: number, size: number, events: Array<object>,
 *            recovery: object, outcome: Readonly<object>|null}}
 */
export function readLogHead(logPath, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  const write = opts.write === true;
  const recovery = recoverLogTail(logPath, { fsx, quarantine: opts.quarantine });

  if (recovery.presence === PRESENCE.UNREACHABLE) {
    return {
      ok: false,
      head_seq: EMPTY_HEAD_SEQ,
      size: 0,
      events: [],
      recovery,
      outcome: indexOutcome(
        write ? INDEX_WRITE_CODE.HOME_UNREACHABLE : INDEX_READ_CODE.HOME_UNREACHABLE,
        { home: path.dirname(logPath), path: logPath, errno: recovery.errno ?? '' },
      ),
    };
  }

  if (recovery.interior_problems.length > 0) {
    const first = recovery.interior_problems[0];
    return {
      ok: false,
      head_seq: recovery.head_seq,
      size: 0,
      events: [],
      recovery,
      outcome: write
        ? indexOutcome(INDEX_WRITE_CODE.LOG_UNPARSEABLE, { line: first.line, reason: first.reason })
        : indexOutcome(INDEX_READ_CODE.UNKNOWN, {
            reason: `log line ${first.line} is unparseable (${first.reason})`,
          }),
    };
  }

  const after = readLogBytes(logPath, { fsx });
  const { records } = scanLogBytes(after.bytes);
  const parsed = parseLogRecords(records);
  const ordered = replayEvents(parsed.events);
  return {
    ok: true,
    head_seq: seqIntegrity(ordered).head_seq,
    size: after.size,
    events: ordered,
    recovery,
    outcome: null,
  };
}

/**
 * Append one or more events to the ONE log, and report success only once they are durable.
 *
 * The whole batch runs inside ONE lock acquisition, and each event is its own
 * open-append + fsync + close: a batch is a sequence of appends, not a bulk rewrite, so a
 * batch interrupted halfway leaves N durable events and no partial line - and the caller
 * is told exactly which seqs became durable.
 *
 * @param {Array<object>|object} events
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, now?: number,
 *          written_at?: string, boundMs?: number, staleMs?: number, quarantine?: boolean,
 *          lockOpts?: object, homeOpts?: object}} [opts]
 * @returns {Readonly<object>}
 */
export function appendEvents(events, opts = {}) {
  const list = Array.isArray(events) ? events : [events];
  const paths = indexPathsFrom(opts);
  const fsx = fsFacade(opts.fsx);

  if (list.length === 0) {
    return indexOutcome(INDEX_WRITE_CODE.EMPTY_BATCH, { count: 0 }, { ok: true });
  }

  // Damage is refused BEFORE the home is touched: an append that cannot legally happen
  // should not create a directory on the way to saying so.
  for (const payload of list) {
    const hit = findMojibakeField(payload);
    if (hit !== null) {
      return indexOutcome(INDEX_WRITE_CODE.MOJIBAKE_REFUSED, {
        field: hit.field,
        offset: hit.offset,
      });
    }
  }

  const prepared = ensureIndexHome(paths, { fsx });
  if (prepared.ok !== true) return prepared;

  const hazards = inspectIndexHome(paths, { ...(opts.homeOpts ?? {}), fsx, surface: 'write' });
  const blocking = refusingHazards(hazards);
  if (blocking.length > 0) return blocking[0];

  try {
    return withPortfolioLock(
      paths,
      () => {
        const head = readLogHead(paths.log, {
          fsx,
          write: true,
          quarantine: opts.quarantine,
        });
        if (!head.ok) return head.outcome;

        const appended = [];
        let seq = head.head_seq;
        let size = head.size;

        for (const payload of list) {
          seq += 1;
          const event = makeLogEvent(payload, {
            seq,
            written_at: opts.written_at,
            now: opts.now,
          });
          const line = logEventLine(event);
          const result = appendLineAt(paths.log, line, { expected_size: size, fsx });
          if (result.ok !== true) {
            return Object.freeze({
              ...result,
              appended: Object.freeze(appended),
              appended_count: appended.length,
              head_seq: seq - 1,
            });
          }
          size += result.bytes_written;
          appended.push(event);
        }

        return Object.freeze({
          ok: true,
          code: null,
          status: INTEGRITY.OK,
          log: paths.log,
          home: paths.home,
          appended: Object.freeze(appended),
          appended_count: appended.length,
          seqs: Object.freeze(appended.map((e) => e[ORDERING_FIELD])),
          seq: appended.length ? appended[appended.length - 1][ORDERING_FIELD] : head.head_seq,
          head_seq: seq,
          durable: true,
          recovery: head.recovery,
          // A tear found on the way in is reported on the WRITE surface too: the row that
          // owns the sentence is the one about a kill between writeSync and fsync, and the
          // writer that cleaned it up is the one who should say so.
          torn: recoveryOutcome(head.recovery, INDEX_WRITE_CODE.TORN_APPEND),
          hazards: Object.freeze(hazards),
        });
      },
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        timeoutCode: INDEX_WRITE_CODE.LOCK_TIMEOUT,
        lockOpts: opts.lockOpts,
      },
    );
  } catch (err) {
    if (isIndexRefusal(err)) return err.outcome;
    throw err;
  }
}

/**
 * Append exactly one event. This is the shape every caller from W7 onward uses.
 *
 * @param {object} event @param {object} [opts] @see appendEvents
 * @returns {Readonly<object>}
 */
export function appendEvent(event, opts = {}) {
  return appendEvents([event], opts);
}

// -- reading the index ---------------------------------------------------------

/**
 * Read the snapshot beside the log, classifying every way it can fail to be readable.
 *
 * @param {string} snapshotPath @param {{fsx?: object}} [opts]
 * @returns {{present: boolean, value: object|null, outcome: Readonly<object>|null}}
 */
export function readSnapshotFile(snapshotPath, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  let bytes;
  try {
    // encoding-lint: raw-bytes - the mojibake detector needs the bytes as they are on
    // disk; decoding first would hide the damage this read exists to find.
    const raw = fsx.readFileSync(openablePath(snapshotPath));
    bytes = Buffer.isBuffer(raw) ? raw : Buffer.from(raw);
  } catch (err) {
    if (err && err.code === 'ENOENT') return { present: false, value: null, outcome: null };
    return {
      present: true,
      value: null,
      outcome: indexOutcome(INDEX_READ_CODE.SNAPSHOT_UNREADABLE, {
        path: snapshotPath,
        errno: err && err.code ? err.code : '',
      }),
    };
  }

  const scan = scanBytesForMojibake(bytes);
  if (scan.status === INTEGRITY.MOJIBAKE) {
    return {
      present: true,
      value: null,
      outcome: indexOutcome(INDEX_READ_CODE.SNAPSHOT_MOJIBAKE, {
        path: snapshotPath,
        offset: scan.first_offset ?? 0,
      }),
    };
  }

  try {
    return { present: true, value: JSON.parse(bytes.toString('utf8')), outcome: null };
  } catch (err) {
    const at = /position (\d+)/.exec(String(err.message));
    return {
      present: true,
      value: null,
      outcome: indexOutcome(INDEX_READ_CODE.SNAPSHOT_UNPARSEABLE, {
        path: snapshotPath,
        reason: err.message,
        offset: at ? at[1] : 0,
      }),
    };
  }
}

/**
 * Open the ONE index for reading: hazards named, home classified, lock taken, torn tail
 * quarantined, log replayed in `seq` order, snapshot read if present.
 *
 * A read takes the lock for the same reason a write does - a reader that runs while an
 * appender is mid-append can observe a fragment, and "the index looked torn for a moment"
 * is indistinguishable from "the index is torn" to everything downstream.
 *
 * @param {{home?: string, paths?: object, env?: object, fsx?: object, boundMs?: number,
 *          staleMs?: number, quarantine?: boolean, lockOpts?: object, homeOpts?: object}} [opts]
 * @returns {Readonly<object>}
 */
export function openIndexForRead(opts = {}) {
  const paths = indexPathsFrom(opts);
  const fsx = fsFacade(opts.fsx);

  let stat;
  try {
    stat = fsx.statSync(openablePath(paths.home));
  } catch (err) {
    return indexOutcome(homeFailureCodeFor(err, false), {
      home: paths.home,
      errno: err && err.code ? err.code : '',
    });
  }
  if (!stat.isDirectory()) {
    return indexOutcome(INDEX_READ_CODE.HOME_UNREACHABLE, {
      home: paths.home,
      errno: 'ENOTDIR',
    });
  }

  const hazards = inspectIndexHome(paths, { ...(opts.homeOpts ?? {}), fsx });
  const blocking = refusingHazards(hazards);

  try {
    return withPortfolioLock(
      paths,
      () => {
        const head = readLogHead(paths.log, { fsx, write: false, quarantine: opts.quarantine });
        if (!head.ok) {
          return Object.freeze({ ...head.outcome, hazards: Object.freeze(hazards) });
        }

        const snapshot = readSnapshotFile(paths.snapshot, { fsx });
        if (snapshot.outcome !== null) {
          return Object.freeze({ ...snapshot.outcome, hazards: Object.freeze(hazards) });
        }

        const empty = head.events.length === 0 && snapshot.present === false;
        const base = empty
          ? indexOutcome(INDEX_READ_CODE.EMPTY, { home: paths.home }, { ok: true })
          : { ok: true, code: null, status: INTEGRITY.OK, text: '' };

        return Object.freeze({
          ...base,
          home: paths.home,
          log: paths.log,
          snapshot: paths.snapshot,
          events: Object.freeze(head.events),
          head_seq: head.head_seq,
          count: head.events.length,
          snapshot_present: snapshot.present,
          snapshot_value: snapshot.value,
          recovery: head.recovery,
          torn: recoveryOutcome(head.recovery),
          hazards: Object.freeze(hazards),
          blocking_hazards: Object.freeze(blocking),
          freshness: FRESHNESS.FRESH,
        });
      },
      {
        boundMs: opts.boundMs,
        staleMs: opts.staleMs,
        timeoutCode: INDEX_READ_CODE.LOCK_TIMEOUT,
        lockOpts: opts.lockOpts,
      },
    );
  } catch (err) {
    if (isIndexRefusal(err)) return err.outcome;
    throw err;
  }
}

/**
 * The read a replayer wants: every event in `seq` order, with the recovery receipt.
 *
 * @param {object} [opts] @see openIndexForRead @returns {Readonly<object>}
 */
export function readIndexLog(opts = {}) {
  return openIndexForRead(opts);
}

/** @param {string} home @param {string} candidate @returns {boolean} re-exported for callers */
export function isIndexPath(home, candidate) {
  return isInsideHome(home, candidate);
}

/**
 * W8: hand the appender to the lock-order rule.
 *
 * The direction matters. This module is the one that OWNS the append, so it is the one that
 * registers; lock-order.mjs never imports it back, and the two modules stay acyclic. A
 * process that imported lock-order.mjs alone would find no appender registered and its
 * flush would refuse BY NAME rather than silently dropping the events - which is why the
 * registration is a call somebody can find rather than an import somebody assumes.
 */
registerIndexAppender((events, opts) => appendEvents(events, opts ?? {}));

/** The path-hazard axis this module can report, for tests that enumerate the rows. */
export const REPORTED_HAZARD_AXIS = Object.freeze([
  PATH_HAZARD.SKIPPED_REPARSE,
  PATH_HAZARD.PATH_TOO_LONG,
  PATH_HAZARD.CASE_COLLISION,
]);

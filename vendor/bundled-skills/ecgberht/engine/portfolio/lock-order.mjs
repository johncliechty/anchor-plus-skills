/**
 * W8 - the lock-order rule, in code rather than in a review comment.
 *
 * THE DEADLOCK THIS FORBIDS. There are exactly two lock families in this engine: the
 * PROJECT lock (engine/durable-write.mjs, guarding one project's strip.json / roadmap.json
 * / receipt file) and the ONE PORTFOLIO lock (engine/append-log.mjs, guarding the index
 * home). The moment a call site holds one and reaches for the other, the acquisition ORDER
 * becomes part of the contract - and two call sites that disagree about the order is the
 * textbook ABBA deadlock:
 *
 *     verb A:  project lock on P  ->  wants the portfolio lock
 *     verb B:  portfolio lock     ->  wants the project lock on P
 *
 * Both waiters are inside their starvation bound, so neither hangs forever and neither is
 * wrong on its own; they just both fail, under contention, in production, at a rate nobody
 * can reproduce. The cure is not "always take them in the same order" - a rule of that
 * shape has to be remembered by every future wave, and W9 wires THREE more write
 * authorities into this path. The cure is to make holding both IMPOSSIBLE:
 *
 *     take the project lock -> write the source of truth -> BUFFER the index event in
 *     memory -> RELEASE the project lock -> flush the buffer through the portfolio lock ->
 *     only then return success.
 *
 * Two locks, never overlapping, and the operator still never sees a success whose index
 * event has not been made durable - the flush is BEFORE the return, not after it (that
 * ordering is W9's, frozen in the plan, and this module is where it becomes mechanical).
 *
 * HOW THE RULE IS ENFORCED, in two halves that fail differently:
 *
 *   RUNTIME  - this module keeps the process's project-lock depth, and
 *              engine/append-log.mjs calls assertPortfolioLockPermitted() before it takes
 *              the portfolio lock. A call site that appends while holding a project lock
 *              gets LOCK_ORDER_VIOLATION naming the held lock, in the process that did it,
 *              instead of a deadlock in somebody else's.
 *   STATIC   - test/helpers/lock-order-lint.mjs audits every durable-write call site in the
 *              tree and fails the build on a portfolio append lexically inside a project
 *              lock. The runtime guard only fires on a path that actually runs; the audit
 *              fires on a path that was merely written.
 *
 * WHY THE APPENDER IS REGISTERED RATHER THAN IMPORTED. append-log.mjs imports this module
 * (for the assertion), so this module importing append-log.mjs would be a cycle. Rather
 * than pretend a cycle is fine because ESM tolerates it, the direction is inverted: the
 * module that OWNS the appender registers it here on import, and a caller may always pass
 * its own `append` explicitly. A flush with no appender is a named refusal, never a silent
 * drop of the events a verb was about to report as durable.
 *
 * Stdlib only.
 */

import path from 'node:path';

import { withFileLock } from '../durable-write.mjs';
import { FRESHNESS, INTEGRITY, assertStatusCode } from './status.mjs';

/** The rule's frozen version. Changing the ordering contract means lock-order-v2. */
export const LOCK_ORDER_VERSION = 'lock-order-v1';

/** The two lock families, named once so no surface invents a third word for either. */
export const LOCK = Object.freeze({
  PROJECT: 'project-lock',
  PORTFOLIO: 'portfolio-lock',
});

/**
 * The phases a buffered write passes through, in their frozen order.
 *
 * Exported as data because "the flush happened after the release and before the return" is
 * a claim about ORDER, and a claim about order needs something ordered to check. Every
 * withProjectLock() call returns its own trace, so a test asserts the sequence rather than
 * asserting that some code was written.
 */
export const PHASE = Object.freeze({
  PROJECT_LOCK_ACQUIRED: 'project-lock-acquired',
  PROJECT_LOCK_RELEASED: 'project-lock-released',
  INDEX_FLUSH_STARTED: 'index-flush-started',
  INDEX_FLUSH_DURABLE: 'index-flush-durable',
  RETURNED: 'returned',
});

/** @type {ReadonlyArray<string>} the frozen phase order a compliant write follows */
export const PHASE_ORDER = Object.freeze([
  PHASE.PROJECT_LOCK_ACQUIRED,
  PHASE.PROJECT_LOCK_RELEASED,
  PHASE.INDEX_FLUSH_STARTED,
  PHASE.INDEX_FLUSH_DURABLE,
  PHASE.RETURNED,
]);

/**
 * The codes this module raises.
 *
 * VIOLATION is deliberately NOT a failure-table row and carries no STATUS-v1 code: it is a
 * PROGRAMMING error - code that cannot be correct on any host, on any day - and putting it
 * in the operator's failure table would tell an operator to act on a defect they cannot
 * act on. The flush codes ARE operating states and do carry a status.
 */
export const LOCK_ORDER_CODE = Object.freeze({
  VIOLATION: 'LOCK_ORDER_VIOLATION',
  BUFFER_SEALED: 'LOCK_ORDER_BUFFER_SEALED',
  APPENDER_UNREGISTERED: 'LOCK_ORDER_APPENDER_UNREGISTERED',
  FLUSH_FAILED: 'LOCK_ORDER_FLUSH_FAILED',
  FLUSHED: 'LOCK_ORDER_FLUSHED',
  NOT_AN_EVENT: 'LOCK_ORDER_BUFFERED_EVENT_NOT_AN_OBJECT',
});

/**
 * The flush outcomes, with the sentence an operator reads. FLUSH_FAILED carries STALE for
 * the same reason W9's INGEST_APPEND_FAILED does: the source of truth is written and the
 * index is behind it, which is precisely what stale means and is exactly the state the
 * W8 divergence sweep repairs on the next start.
 */
export const LOCK_ORDER_ROWS = Object.freeze({
  [LOCK_ORDER_CODE.FLUSHED]: Object.freeze({
    status: assertStatusCode(INTEGRITY.OK, 'lock-order FLUSHED'),
    text:
      '{count} buffered index event(s) were appended after the project lock was released '
      + 'and before this verb returned, so the two locks were never held together and the '
      + 'operator never saw an unindexed success.',
  }),
  [LOCK_ORDER_CODE.FLUSH_FAILED]: Object.freeze({
    status: assertStatusCode(FRESHNESS.STALE, 'lock-order FLUSH_FAILED'),
    text:
      'The file was written and is intact, but the index did not record it ({reason}). The '
      + "project reads STALE until the startup divergence sweep regenerates the row from the "
      + 'file that survived.',
  }),
  [LOCK_ORDER_CODE.APPENDER_UNREGISTERED]: Object.freeze({
    status: assertStatusCode(FRESHNESS.STALE, 'lock-order APPENDER_UNREGISTERED'),
    text:
      'The file was written and {count} index event(s) were buffered, but no index appender '
      + 'is registered in this process, so nothing could be made durable. The buffer is '
      + 'returned rather than dropped; the events are still in memory and still countable.',
  }),
  [LOCK_ORDER_CODE.BUFFER_SEALED]: Object.freeze({
    status: assertStatusCode(FRESHNESS.UNKNOWN, 'lock-order BUFFER_SEALED'),
    text:
      'An index event was buffered after its buffer had already been flushed. A sealed '
      + 'buffer never silently accepts an event nobody will append.',
  }),
});

/** @param {string} template @param {Record<string, unknown>} params @returns {string} */
function fill(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (whole, key) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : whole,
  );
}

/**
 * Build a flush outcome. Same shape as every other outcome in this engine: a named code, a
 * STATUS-v1 status, and the sentence the operator sees.
 *
 * @param {string} code @param {Record<string, unknown>} [params] @param {object} [extra]
 * @returns {Readonly<object>}
 */
export function lockOrderOutcome(code, params = {}, extra = {}) {
  const row = LOCK_ORDER_ROWS[code];
  if (row === undefined) throw new Error(`lock-order: ${code} is not a frozen lock-order row`);
  return Object.freeze({
    ok: extra.ok === true,
    code,
    status: row.status,
    text: fill(row.text, params),
    detail: Object.freeze({ ...params }),
    ...extra,
  });
}

/** The ABBA refusal, as a throwable: the call site that did it is the one that must see it. */
export class LockOrderRefusal extends Error {
  /**
   * @param {string} where the call site asking for the portfolio lock
   * @param {ReadonlyArray<string>} held the project locks currently held by this process
   */
  constructor(where, held) {
    super(
      `${LOCK_ORDER_CODE.VIOLATION}: ${where} asked for the ${LOCK.PORTFOLIO} while this `
      + `process holds ${held.length} ${LOCK.PROJECT}(s) (${held.join(', ')}). Holding both is `
      + 'the ABBA deadlock W8 forbids: buffer the index event, release the project lock, and '
      + 'flush the buffer before returning success - withProjectLock() in '
      + 'engine/portfolio/lock-order.mjs does exactly that.',
    );
    this.name = 'LockOrderRefusal';
    this.code = LOCK_ORDER_CODE.VIOLATION;
    this.where = where;
    this.held = Object.freeze([...held]);
  }
}

/** @param {unknown} err @returns {boolean} */
export function isLockOrderRefusal(err) {
  return err instanceof LockOrderRefusal;
}

// -- the held-lock registry ----------------------------------------------------

/**
 * The project locks this PROCESS holds, innermost last.
 *
 * A counter would be enough to enforce the rule and would tell the author nothing about
 * which lock they are holding, so the paths are kept: a refusal that names the file is a
 * refusal somebody can act on in one read.
 *
 * @type {string[]}
 */
const held = [];

/** @returns {ReadonlyArray<string>} the project locks held right now, in acquisition order */
export function heldProjectLocks() {
  return Object.freeze([...held]);
}

/** @returns {number} how many project locks this process holds */
export function projectLockDepth() {
  return held.length;
}

/**
 * Record that a project lock is held. Called around the ACQUISITION as well as the hold,
 * deliberately over-covering rather than under-covering: a waiter blocked on a project lock
 * is a call site that is about to hold one, and an append issued from inside that wait
 * would be the same ordering mistake one instruction earlier.
 *
 * @param {string} filePath the file the lock guards @returns {number} the new depth
 */
export function enterProjectLock(filePath) {
  held.push(path.resolve(String(filePath)));
  return held.length;
}

/**
 * Release the record of a project lock. Removes the innermost matching entry rather than
 * popping blindly, so an unbalanced call in one verb cannot silently un-hold another's.
 *
 * @param {string} filePath @returns {number} the new depth
 */
export function exitProjectLock(filePath) {
  const target = path.resolve(String(filePath));
  for (let i = held.length - 1; i >= 0; i -= 1) {
    if (held[i] === target) {
      held.splice(i, 1);
      return held.length;
    }
  }
  if (held.length > 0) held.pop();
  return held.length;
}

/** @returns {boolean} whether taking the portfolio lock is legal right now */
export function isPortfolioLockPermitted() {
  return held.length === 0;
}

/**
 * THE GUARD. engine/append-log.mjs calls this before it takes the portfolio lock.
 *
 * @param {string} [where] the call site, for the message
 * @returns {true}
 */
export function assertPortfolioLockPermitted(where = LOCK.PORTFOLIO) {
  if (held.length > 0) throw new LockOrderRefusal(where, held);
  return true;
}

/**
 * Drop every recorded project lock. For a test that drove the registry's FAILURE path and
 * must not leak a held lock into the next test - never for production code, which balances
 * its own enter/exit through withProjectLock's finally.
 *
 * @returns {number} how many records were dropped
 */
export function resetProjectLockRegistry() {
  const n = held.length;
  held.length = 0;
  return n;
}

// -- the in-process buffer -----------------------------------------------------

/**
 * The buffer a verb writes its index events into while it holds the project lock.
 *
 * It seals on flush. An event added after the flush would be an event the verb has already
 * reported as durable and which nobody will ever append - the exact silent loss C2 forbids
 * - so adding to a sealed buffer is a named refusal instead.
 *
 * @param {string} [label] a tag naming the verb, so a leaked buffer is traceable
 * @returns {{label: string, add: (event: object) => number, events: () => object[],
 *            size: () => number, seal: () => number, sealed: () => boolean}}
 */
export function newIndexEventBuffer(label = 'index-events') {
  /** @type {object[]} */
  const events = [];
  let sealed = false;

  return {
    label: String(label),

    add(event) {
      // SHAPE FIRST, THEN SEAL. The two refusals answer different questions - "this is not an
      // event" is a defect in the caller's argument, "this buffer is closed" is a fact about
      // when the call happened - and a caller who passed something that is not an event must
      // be told THAT, whichever side of the flush they were on. Checking the seal first would
      // hide every malformed argument raised after a flush behind the timing refusal.
      if (event === null || typeof event !== 'object' || Array.isArray(event)) {
        const err = new Error(
          `${LOCK_ORDER_CODE.NOT_AN_EVENT}: a buffered index event must be a plain object, `
          + `got ${Array.isArray(event) ? 'an array' : typeof event}`,
        );
        err.code = LOCK_ORDER_CODE.NOT_AN_EVENT;
        throw err;
      }
      if (sealed) {
        const outcome = lockOrderOutcome(LOCK_ORDER_CODE.BUFFER_SEALED, { label });
        const err = new Error(`${outcome.code}: ${outcome.text}`);
        err.code = outcome.code;
        err.outcome = outcome;
        throw err;
      }
      events.push(event);
      return events.length;
    },

    events() {
      return events.slice();
    },

    size() {
      return events.length;
    },

    seal() {
      sealed = true;
      return events.length;
    },

    sealed() {
      return sealed;
    },
  };
}

// -- the registered appender ---------------------------------------------------

/** @type {((events: object[], opts: object) => object)|null} */
let appender = null;

/**
 * Register the function that makes buffered events durable. engine/append-log.mjs calls
 * this with appendEvents on import; the inversion is what keeps the two modules acyclic.
 *
 * @param {(events: object[], opts: object) => object} fn @returns {boolean}
 */
export function registerIndexAppender(fn) {
  if (typeof fn !== 'function') throw new Error('lock-order: the index appender must be a function');
  appender = fn;
  return true;
}

/** @returns {((events: object[], opts: object) => object)|null} */
export function registeredIndexAppender() {
  return appender;
}

// -- the write shape everything from W9 onward uses ----------------------------

/**
 * Run one durable project-state write under the W8 ordering.
 *
 * `fn` receives the buffer and MUST NOT append to the index itself; the runtime guard will
 * refuse it if it tries, which is the point. Everything the write wants recorded goes into
 * the buffer, and the buffer is appended once, after the project lock is released and
 * before this function returns.
 *
 * The flush is a SINGLE appendEvents() call rather than one call per event: one lock
 * acquisition, one contiguous run of seqs, and a batch interrupted halfway reports exactly
 * which seqs became durable (the primitive's own contract).
 *
 * @param {string} filePath the project file being written (the lock guards it)
 * @param {(buffer: object) => T} fn
 * @param {{label?: string, append?: Function, appendOpts?: object, beforeFlush?: Function,
 *          timeoutMs?: number, staleMs?: number, lockPath?: string}} [opts]
 * @returns {Readonly<{ok: boolean, code: string, value: T, trace: string[], buffered: number,
 *                     events: object[], flush: object|null, append: object|null}>}
 * @template T
 */
export function withProjectLock(filePath, fn, opts = {}) {
  const buffer = newIndexEventBuffer(opts.label ?? filePath);
  const trace = [];
  // An EXPLICIT null means "this process has no appender", which is how the
  // APPENDER_UNREGISTERED branch is drivable in a process that has imported the primitive.
  // Omitting the option entirely takes the registered one, which is what every verb does.
  const append = opts.append === null
    ? null
    : (typeof opts.append === 'function' ? opts.append : appender);

  // The registry entry brackets the ACQUISITION too, so an append attempted while this call
  // is still waiting for the project lock is refused on the same rule as one attempted while
  // holding it.
  enterProjectLock(filePath);
  let value;
  try {
    value = withFileLock(
      filePath,
      () => {
        trace.push(PHASE.PROJECT_LOCK_ACQUIRED);
        return fn(buffer);
      },
      {
        timeoutMs: opts.timeoutMs,
        staleMs: opts.staleMs,
        lockPath: opts.lockPath,
      },
    );
  } finally {
    exitProjectLock(filePath);
    trace.push(PHASE.PROJECT_LOCK_RELEASED);
  }

  // THE CRASH WINDOW. Between here and the flush the source of truth is durable and the
  // index does not know about it. That window cannot be closed - it is two files and one
  // power cut - so it is named, made drivable (a killer injected here is how
  // test/w51-kill-window.test.mjs reproduces it exactly), and repaired by the W8 divergence
  // sweep on the next start.
  if (typeof opts.beforeFlush === 'function') opts.beforeFlush({ buffer, trace, value });

  const pending = buffer.events();
  if (pending.length === 0) {
    buffer.seal();
    trace.push(PHASE.INDEX_FLUSH_STARTED, PHASE.INDEX_FLUSH_DURABLE, PHASE.RETURNED);
    return Object.freeze({
      ok: true,
      code: LOCK_ORDER_CODE.FLUSHED,
      value,
      trace: Object.freeze(trace),
      buffered: 0,
      events: Object.freeze([]),
      flush: lockOrderOutcome(LOCK_ORDER_CODE.FLUSHED, { count: 0 }, { ok: true }),
      append: null,
    });
  }

  trace.push(PHASE.INDEX_FLUSH_STARTED);

  if (append === null) {
    buffer.seal();
    trace.push(PHASE.RETURNED);
    return Object.freeze({
      ok: false,
      code: LOCK_ORDER_CODE.APPENDER_UNREGISTERED,
      value,
      trace: Object.freeze(trace),
      buffered: pending.length,
      events: Object.freeze(pending),
      flush: lockOrderOutcome(LOCK_ORDER_CODE.APPENDER_UNREGISTERED, { count: pending.length }),
      append: null,
    });
  }

  const outcome = append(pending, opts.appendOpts ?? {});
  buffer.seal();

  if (!outcome || outcome.ok !== true) {
    trace.push(PHASE.RETURNED);
    return Object.freeze({
      ok: false,
      code: LOCK_ORDER_CODE.FLUSH_FAILED,
      value,
      trace: Object.freeze(trace),
      buffered: pending.length,
      events: Object.freeze(pending),
      flush: lockOrderOutcome(LOCK_ORDER_CODE.FLUSH_FAILED, {
        reason: outcome && outcome.text ? outcome.text : String(outcome && outcome.code),
        count: pending.length,
      }),
      append: outcome ?? null,
    });
  }

  trace.push(PHASE.INDEX_FLUSH_DURABLE, PHASE.RETURNED);
  return Object.freeze({
    ok: true,
    code: LOCK_ORDER_CODE.FLUSHED,
    value,
    trace: Object.freeze(trace),
    buffered: pending.length,
    events: Object.freeze(pending),
    flush: lockOrderOutcome(LOCK_ORDER_CODE.FLUSHED, { count: pending.length }, { ok: true }),
    append: outcome,
  });
}

/**
 * Did this trace obey the ordering? Exported so a test states the property once instead of
 * hand-comparing arrays, and so W9's three write authorities can assert it on themselves.
 *
 * @param {ReadonlyArray<string>} trace
 * @returns {{ok: boolean, reason: string|null}}
 */
export function traceObeysOrder(trace) {
  const seen = Array.isArray(trace) ? trace : [];
  const released = seen.indexOf(PHASE.PROJECT_LOCK_RELEASED);
  const started = seen.indexOf(PHASE.INDEX_FLUSH_STARTED);
  const returned = seen.indexOf(PHASE.RETURNED);

  if (released === -1) return { ok: false, reason: 'the project lock was never released' };
  if (started === -1) return { ok: false, reason: 'the index flush never started' };
  if (returned === -1) return { ok: false, reason: 'the verb never returned' };
  if (started < released) {
    return { ok: false, reason: 'the index flush started while the project lock was still held' };
  }
  if (returned < started) {
    return { ok: false, reason: 'the verb returned before the index flush started' };
  }
  return { ok: true, reason: null };
}

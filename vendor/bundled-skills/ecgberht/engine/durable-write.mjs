/**
 * Durable write: atomic replacement + cross-process locking for steward state.
 *
 * WHY (2026-07-27 hardening review). `write-authority.mjs` enforces "Strip is
 * append-only; receipts are never lost" as a VALIDATION rule — it rejects
 * silent in-place rewrite of protected fields. But every writer underneath it
 * was a bare `fs.writeFileSync`, and the whole act is a read-modify-write of
 * `strip.json`. So the guarantee was logical only:
 *
 *   1. NOT ATOMIC — `writeFileSync` truncates the target and then writes. Kill
 *      it in between and the receipt ledger is left truncated or empty. This is
 *      not hypothetical here: Anchor invokes the bridge via
 *      `subprocess.run(..., timeout=20)`, which KILLS THE CHILD on timeout, so
 *      the platform itself can kill a write mid-flight.
 *   2. NOT LOCKED — each act is a separate Node process, so an in-process mutex
 *      cannot help. Two concurrent acts both read, both modify, both write, and
 *      one set of receipts is silently gone. Append-only, and yet lossy.
 *
 * A module that VALIDATES append-only does not PROVIDE it. This provides it.
 *
 * Design notes:
 *   - Atomicity is temp-file + fsync + rename. `rename` is atomic on POSIX and
 *     is a replacing MoveFileEx on Windows; the fsync before it is what makes
 *     the *content* durable, not just the directory entry.
 *   - Windows can transiently fail the rename with EPERM/EACCES/EBUSY when an
 *     indexer or AV has the destination open. That is a retry, not an error.
 *   - Locks are `open(..., 'wx')`, which is O_EXCL and therefore atomic across
 *     processes. Because the caller can be KILLED (see above), a lock MUST be
 *     breakable or the steward deadlocks itself permanently after one timeout.
 *     Stale breaking is by mtime age, and the breaker re-verifies after
 *     removing so two racing breakers cannot both proceed.
 *   - The SAME Windows transients apply to lock acquire and release: after the
 *     holder unlinks, the directory entry can sit in delete-pending while another
 *     process still has a read handle (stat/read of the stamp). The next O_EXCL
 *     create then fails with EPERM/EACCES/EBUSY rather than EEXIST. Treating that
 *     as a hard throw is what made multi-process hammers report an uncaught errno
 *     instead of success-or-named-status. Acquire retries those codes under the
 *     same starvation bound; release retries the unlink a few times so a live
 *     process does not strand a lock stamped with its own still-alive pid.
 *
 * Stdlib only. No dependencies — this ships inside a skill bundle.
 */

import fs from 'node:fs';
import path from 'node:path';

/** Milliseconds after which a lock is assumed orphaned by a killed writer. */
export const STALE_LOCK_MS = 30_000;

/** Total time to wait for a contended lock before giving up. */
export const LOCK_TIMEOUT_MS = 10_000;

/** How long a waiter sleeps between acquire attempts when no backoff schedule is given. */
export const LOCK_POLL_MS = 25;

/** Retries for a transient Windows rename / lock-release failure. */
const RENAME_RETRIES = 10;
const RENAME_BACKOFF_MS = 25;

/**
 * Windows errnos that mean "try again shortly", not "this operation is impossible".
 * Shared by atomic rename, lock O_EXCL create, and lock unlink.
 */
const TRANSIENT = new Set(['EPERM', 'EACCES', 'EBUSY', 'ENOENT']);

function sleepSync(ms) {
  // Node has no sync sleep; Atomics.wait on a throwaway buffer is the standard
  // one. This runs in a short-lived CLI process, so blocking is correct here.
  const sab = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(sab), 0, 0, ms);
}

/**
 * Drop the lock file, retrying the Windows delete-pending / scanner races.
 * ENOENT is success (already gone). Other permanent errors are swallowed the way
 * the old single-shot unlink was — a stale-breaker may own the path now.
 *
 * @param {string} lockPath
 */
function releaseLockPath(lockPath) {
  for (let i = 0; i < RENAME_RETRIES; i += 1) {
    try {
      fs.unlinkSync(lockPath);
      return;
    } catch (err) {
      const code = err && err.code;
      if (code === 'ENOENT') return;
      if (!TRANSIENT.has(code) || i === RENAME_RETRIES - 1) return;
      sleepSync(RENAME_BACKOFF_MS * (i + 1));
    }
  }
}

/**
 * Write `text` to `filePath` so that a reader NEVER observes a partial file.
 *
 * The temp file is created beside the target (same directory) because `rename`
 * is only atomic within a filesystem — a temp in the OS temp dir could land on
 * a different volume and silently degrade to copy+delete.
 *
 * Accepts a string (UTF-8) or a Buffer / Uint8Array (raw bytes). Binary
 * payloads (content-hashed source_text blobs) must not be forced through a
 * string encoding path — that can empty or corrupt the write under concurrent
 * hammer tests.
 *
 * @param {string} filePath
 * @param {string|Buffer|Uint8Array} text
 */
export function writeFileAtomicSync(filePath, text) {
  const dir = path.dirname(filePath);
  const base = path.basename(filePath);
  const tmp = path.join(
    dir,
    `.${base}.tmp-${process.pid}-${Math.random().toString(36).slice(2, 10)}`,
  );

  let fd;
  try {
    fd = fs.openSync(tmp, 'wx');
    if (Buffer.isBuffer(text) || text instanceof Uint8Array) {
      fs.writeFileSync(fd, text);
    } else {
      fs.writeFileSync(fd, text, 'utf8');
    }
    // Durability: without the fsync, rename can land while the CONTENT is
    // still only in the page cache, so a crash yields an empty-but-present
    // file — the worst outcome for an append-only ledger.
    try {
      fs.fsyncSync(fd);
    } catch {
      /* some filesystems refuse fsync; the rename is still atomic */
    }
    fs.closeSync(fd);
    fd = undefined;

    let lastErr;
    for (let i = 0; i < RENAME_RETRIES; i++) {
      try {
        fs.renameSync(tmp, filePath);
        return;
      } catch (err) {
        lastErr = err;
        if (!TRANSIENT.has(err.code)) throw err;
        sleepSync(RENAME_BACKOFF_MS * (i + 1));
      }
    }
    throw lastErr;
  } finally {
    if (fd !== undefined) {
      try {
        fs.closeSync(fd);
      } catch {
        /* already closed */
      }
    }
    // Never leave a temp behind on a failed write.
    try {
      if (fs.existsSync(tmp)) fs.unlinkSync(tmp);
    } catch {
      /* best effort */
    }
  }
}

/** Path of the lock guarding `filePath`. */
export function lockPathFor(filePath) {
  return `${filePath}.lock`;
}

export function lockIsStale(lockPath, staleMs) {
  try {
    return Date.now() - fs.statSync(lockPath).mtimeMs > staleMs;
  } catch {
    return false; // vanished — treat as not-stale; the next acquire will win
  }
}

/** The default holder stamp: pid and acquisition time, one line, diagnostic only. */
function defaultLockStamp() {
  return `${process.pid} ${new Date().toISOString()}\n`;
}

/**
 * The default starvation failure. W5 replaces this with a named STATUS-v1 refusal via
 * `opts.onTimeout`; the shape stays the same so an existing caller sees no change.
 *
 * @param {{filePath: string, timeoutMs: number, holder: string}} info
 * @returns {Error}
 */
function defaultTimeoutError(info) {
  const err = new Error(
    `could not acquire lock on ${info.filePath} within ${info.timeoutMs}ms ` +
      `(held by ${info.holder}); refusing to write rather than risk clobbering a ` +
      'concurrent act',
  );
  err.code = 'ELOCKTIMEOUT';
  return err;
}

/**
 * Run `fn` holding an exclusive cross-process lock on `filePath`.
 *
 * Use this around the whole READ-MODIFY-WRITE, not just the write: locking only
 * the write still lets two processes read the same base state and have the
 * later one clobber the earlier one's receipts.
 *
 * W5 adds four INJECTION POINTS, all optional and all defaulted to today's behaviour, so
 * the portfolio lock can be a stricter policy without becoming a second lock
 * implementation — two lock implementations is how two writers end up believing they both
 * hold the same lock:
 *
 *   lockPath   - guard a file under a name the caller chooses (the frozen portfolio.lock)
 *                rather than `<file>.lock`.
 *   stamp      - what the holder records about itself (W5 writes pid + start-time +
 *                hostname, which is what makes PID-liveness checking possible at all).
 *   isStale    - how a waiter decides a holder is gone. Age alone cannot tell a killed
 *                writer from a slow one; PID liveness can, and only the caller knows
 *                whether the stamp it wrote is readable.
 *   backoffFor - the wait between attempts, so a waiter can back off exponentially instead
 *                of hammering the directory.
 *   onTimeout  - the error raised at the starvation bound, so the refusal can carry a
 *                named STATUS-v1 code instead of a bare errno.
 *
 * @param {string} filePath  the file being guarded (not the lock itself)
 * @param {() => T} fn
 * @param {{timeoutMs?: number, staleMs?: number, lockPath?: string,
 *          stamp?: () => string, isStale?: (lockPath: string, staleMs: number) => boolean,
 *          backoffFor?: (attempt: number) => number,
 *          onTimeout?: (info: object) => Error}} [opts]
 * @returns {T}
 * @template T
 */
export function withFileLock(filePath, fn, opts = {}) {
  const timeoutMs = opts.timeoutMs ?? LOCK_TIMEOUT_MS;
  const staleMs = opts.staleMs ?? STALE_LOCK_MS;
  const lockPath = opts.lockPath ?? lockPathFor(filePath);
  const stamp = typeof opts.stamp === 'function' ? opts.stamp : defaultLockStamp;
  const isStale = typeof opts.isStale === 'function' ? opts.isStale : lockIsStale;
  const backoffFor = typeof opts.backoffFor === 'function' ? opts.backoffFor : () => LOCK_POLL_MS;
  const onTimeout = typeof opts.onTimeout === 'function' ? opts.onTimeout : defaultTimeoutError;
  const startedAt = Date.now();
  const deadline = startedAt + timeoutMs;
  let attempt = 0;

  try {
    fs.mkdirSync(path.dirname(lockPath), { recursive: true });
  } catch {
    /* the directory usually exists already */
  }

  let fd;
  for (;;) {
    try {
      // 'wx' is O_CREAT|O_EXCL — atomic across processes, which an
      // exists()-then-create check would not be.
      fd = fs.openSync(lockPath, 'wx');
      break;
    } catch (err) {
      const code = err && err.code;
      // EEXIST = another holder (or our own stranded lock). TRANSIENT = Windows
      // delete-pending / AV / indexer race on the same path — not a programming
      // error, and not a reason to throw past the caller's named onTimeout.
      if (code !== 'EEXIST' && !TRANSIENT.has(code)) throw err;

      // The holder may have been KILLED (bridge timeout). A lock nobody can
      // release would wedge this project's steward state forever, so an aged
      // lock is broken — then re-verified, so two racing breakers cannot both
      // decide they won. Only attempt a break when the create said the name
      // still exists (EEXIST); a pending-delete EPERM is fixed by waiting.
      if (code === 'EEXIST' && isStale(lockPath, staleMs)) {
        try {
          fs.unlinkSync(lockPath);
        } catch {
          /* another breaker got there first */
        }
        continue;
      }

      if (Date.now() >= deadline) {
        throw onTimeout({
          filePath,
          lockPath,
          timeoutMs,
          staleMs,
          attempts: attempt,
          waited_ms: Date.now() - startedAt,
          holder: readHolder(lockPath),
        });
      }
      sleepSync(Math.max(1, Math.min(backoffFor(attempt), Math.max(1, deadline - Date.now()))));
      attempt += 1;
    }
  }

  try {
    fs.writeFileSync(fd, stamp(), 'utf8');
  } catch {
    /* the holder stamp is diagnostic only */
  }

  try {
    return fn();
  } finally {
    try {
      fs.closeSync(fd);
    } catch {
      /* already closed */
    }
    releaseLockPath(lockPath);
  }
}

function readHolder(lockPath) {
  try {
    return fs.readFileSync(lockPath, 'utf8').trim() || 'unknown';
  } catch {
    return 'unknown';
  }
}

/**
 * The common case: read-modify-write a JSON file under lock, atomically.
 *
 * `mutate` receives the parsed current value (or `fallback` when the file is
 * absent) and returns the value to persist. Both the read and the write happen
 * inside the lock, which is the entire point.
 *
 * @param {string} filePath
 * @param {(current: any) => any} mutate
 * @param {{fallback?: any, timeoutMs?: number, staleMs?: number}} [opts]
 */
export function updateJsonSync(filePath, mutate, opts = {}) {
  return withFileLock(
    filePath,
    () => {
      let current = opts.fallback ?? null;
      try {
        current = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      } catch (err) {
        if (err.code !== 'ENOENT') throw err;
      }
      const next = mutate(current);
      writeFileAtomicSync(filePath, `${JSON.stringify(next, null, 2)}\n`);
      return next;
    },
    opts,
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * SEMANTIC-IDEMPOTENT JSON WRITES (thrash fix, journal 0070/0074).
 *
 * Root cause of the W4/W5 delta-coverage thrash: artifact writers re-stamped
 * pure-timestamp fields (`updated_at`/`recorded_at`/pids/samples) on every
 * suite run, so semantically EMPTY changes appeared in the wave git delta and
 * gate 0091 demanded a test naming the file — a full review panel burned on
 * nothing. The law here: when a writer's SEMANTIC content (everything except
 * declared volatile fields) is unchanged from what is on disk, DO NOT WRITE
 * AT ALL — the file stays byte-identical and produces no git delta. Only a
 * genuine content change may advance a timestamp.
 * ──────────────────────────────────────────────────────────────────────────── */

/** Default volatile (pure-timestamp) keys shared by the artifact writers. */
export const DEFAULT_VOLATILE_JSON_KEYS = Object.freeze([
  'recorded_at',
  'updated_at',
  'sampled_at',
  'observed_at',
  'live_observed_at',
  'terminal_observed_at',
]);

/**
 * Deep-copy `value` with every property named in `volatileKeys` removed,
 * at any depth. Arrays are mapped; primitives returned as-is.
 *
 * @param {unknown} value
 * @param {readonly string[]} [volatileKeys]
 * @returns {unknown}
 */
export function stripVolatileDeep(value, volatileKeys = DEFAULT_VOLATILE_JSON_KEYS) {
  if (Array.isArray(value)) {
    return value.map((v) => stripVolatileDeep(v, volatileKeys));
  }
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      if (volatileKeys.includes(k)) continue;
      out[k] = stripVolatileDeep(v, volatileKeys);
    }
    return out;
  }
  return value;
}

/**
 * True when two JSON-serializable values are equal after stripping volatile
 * keys — i.e. a rewrite would be semantically EMPTY.
 *
 * @param {unknown} a
 * @param {unknown} b
 * @param {readonly string[]} [volatileKeys]
 * @returns {boolean}
 */
export function jsonSemanticallyEqual(a, b, volatileKeys = DEFAULT_VOLATILE_JSON_KEYS) {
  return (
    JSON.stringify(stripVolatileDeep(a, volatileKeys)) ===
    JSON.stringify(stripVolatileDeep(b, volatileKeys))
  );
}

/**
 * Write `payload` as pretty JSON to `filePath` ONLY when its semantic content
 * differs from what is already on disk. Unchanged content → no write at all
 * (byte-identical file, no mtime churn, no git delta). Changed content →
 * lock + atomic write, timestamps allowed to advance.
 *
 * @param {string} filePath
 * @param {object} payload
 * @param {{ volatileKeys?: readonly string[], lock?: boolean }} [opts]
 * @returns {{ written: boolean, path: string, reason: 'semantically-unchanged'|'written' }}
 */
export function writeJsonIdempotentSync(filePath, payload, opts = {}) {
  const volatileKeys = opts.volatileKeys ?? DEFAULT_VOLATILE_JSON_KEYS;
  let existing;
  try {
    existing = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    existing = undefined; // absent or torn → write
  }
  if (existing !== undefined && jsonSemanticallyEqual(existing, payload, volatileKeys)) {
    return { written: false, path: filePath, reason: 'semantically-unchanged' };
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const doWrite = () =>
    writeFileAtomicSync(filePath, `${JSON.stringify(payload, null, 2)}\n`);
  if (opts.lock === false) doWrite();
  else withFileLock(filePath, doWrite);
  return { written: true, path: filePath, reason: 'written' };
}

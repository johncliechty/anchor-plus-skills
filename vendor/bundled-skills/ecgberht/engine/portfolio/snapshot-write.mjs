/**
 * W5 - the OTHER half of the D-1 split: the snapshot write primitive.
 *
 * D-1 SPLIT THE WRITE PRIMITIVE BY PATH, and this file owns the half the append primitive
 * must never touch. The two halves are opposites on purpose:
 *
 *   the log       is APPEND-ONLY. It is never rewritten, never temp+renamed, and grows by
 *                 exactly one line per event (engine/append-log.mjs).
 *   the snapshot  is WHOLLY DERIVED. It carries no fact the log does not already carry, so
 *                 it is always replaced entire and never appended to:
 *
 *                     canonical bytes -> <snapshot>.tmp-<pid>-<seq> in the SAME directory
 *                                     -> fsync the temp fd
 *                                     -> rename over the target
 *                                     -> fsync the containing directory handle
 *
 * WHY EACH STEP. Same directory, because rename is only atomic WITHIN a filesystem - a
 * temp in the OS temp dir can land on another volume and silently degrade to copy+delete,
 * which has a window where the target does not exist at all. fsync the temp fd BEFORE the
 * rename, because rename makes the NAME visible, not the BYTES: without it a crash leaves
 * a present, empty, authoritative-looking snapshot, which is worse than no snapshot,
 * because "the index says zero projects" is a lie a reader will act on. fsync the
 * DIRECTORY after, because the rename itself is metadata and can outlive its own durability
 * on some filesystems. Every step is best-effort where the platform refuses it (Windows
 * will not hand out a directory handle this way) and never fails a write that succeeded.
 *
 * THE WINDOWS RENAME RETRY IS NOT OPTIMISM. An indexer, a backup agent or an AV scanner
 * holding the destination open makes MoveFileEx fail with EBUSY/EPERM/EACCES for a few
 * milliseconds. Treating that as a hard error would make the steward randomly fail on a
 * perfectly healthy machine; treating it as retry-forever would hang. So the retry is
 * BOUNDED and exponential, and past the bound it becomes the named row
 * INDEX_WRITE_RENAME_BLOCKED - with the previous snapshot intact and the temp file left
 * for the W8 sweep, never read as authoritative by anything.
 *
 * NO WALL CLOCK MAY ENTER `body`. This is the NG-4 ordering contract's other end. D-2 gives
 * the snapshot exactly ONE region permitted to carry clock- or host-varying values - the
 * named `freshness` block - and W6 asserts byte-equality over `body` alone. A timestamp
 * that leaks into `body` does not merely add noise: it makes the delete-and-rebuild
 * equality claim false forever, and it does so silently, because the artifact still looks
 * fine. So this module refuses to write a body carrying one. Refusing at the write is the
 * only place it can be caught cheaply; every later place it is a forensic exercise.
 *
 * This module is deliberately unable to reach the append primitive, and the append
 * primitive is deliberately unable to reach writeFileAtomicSync. That mutual unreachability
 * IS the D-1 enforcement, and test/w50-write-primitive-lint.test.mjs fails the build in
 * either direction, naming the offending call site.
 *
 * Stdlib only.
 */

import fs from 'node:fs';
import path from 'node:path';

import { rowOutcome } from './failure-tables.mjs';
import { snapshotTempPathFor } from './home.mjs';
import { isOverMaxPath, openablePath } from './inventory.mjs';
import { INTEGRITY, PRESENCE } from './status.mjs';
import { SNAPSHOT_KEYS, validateSnapshotShape } from './snapshot-shape.mjs';

/** The primitive's frozen version. */
export const SNAPSHOT_WRITE_VERSION = 'snapshot-write-v1';

/** Bounded exponential retry around the rename. Bounded is the point; forever is a hang. */
export const RENAME_RETRIES = 8;
export const RENAME_BACKOFF_BASE_MS = 8;
export const RENAME_BACKOFF_MAX_MS = 512;

/** The Windows transients a rename may legitimately hit while a scanner holds the target. */
export const RENAME_TRANSIENT_ERRNOS = Object.freeze(['EBUSY', 'EPERM', 'EACCES']);

/** The failure-table rows this module can produce. */
export const SNAPSHOT_WRITE_CODE = Object.freeze({
  HOME_ABSENT: 'INDEX_WRITE_HOME_ABSENT',
  HOME_UNREACHABLE: 'INDEX_WRITE_HOME_UNREACHABLE',
  DENIED: 'INDEX_WRITE_DENIED',
  RENAME_BLOCKED: 'INDEX_WRITE_RENAME_BLOCKED',
  PATH_TOO_LONG: 'INDEX_WRITE_PATH_TOO_LONG',
  UNKNOWN: 'INDEX_WRITE_UNKNOWN',
});

/**
 * Refusals that are contract violations by the CALLER rather than states of the machine.
 * They are not failure-table rows because an operator cannot act on them - a programmer can.
 */
export const SNAPSHOT_WRITE_REFUSAL = Object.freeze({
  BODY_WALL_CLOCK: 'SNAPSHOT_BODY_CARRIES_WALL_CLOCK',
  SHAPE_INVALID: 'SNAPSHOT_SHAPE_INVALID',
  NOT_SERIALIZABLE: 'SNAPSHOT_NOT_SERIALIZABLE',
});

/** Operator-visible text for the caller refusals. */
export const SNAPSHOT_WRITE_REFUSAL_TEXT = Object.freeze({
  [SNAPSHOT_WRITE_REFUSAL.BODY_WALL_CLOCK]:
    'the snapshot body carries a wall-clock value. D-2 confines every clock- and ' +
    'host-varying value to the named freshness block, because byte-equal rebuild is ' +
    'asserted over the body alone; a timestamp here would make that claim false for ' +
    'every future rebuild, and would do it silently.',
  [SNAPSHOT_WRITE_REFUSAL.SHAPE_INVALID]:
    'the value offered is not a valid snapshot. The shape is frozen as {schema, body, ' +
    'freshness} with a closed freshness field set; writing anything else would put bytes ' +
    'in the index home that no reader has a contract for.',
  [SNAPSHOT_WRITE_REFUSAL.NOT_SERIALIZABLE]:
    'the snapshot could not be serialized, so there are no bytes to make durable. Nothing ' +
    'was written and the previous snapshot is untouched.',
});

/** An error carrying its refusal code. */
export class SnapshotWriteRefusal extends Error {
  /** @param {string} code @param {string} [detail] */
  constructor(code, detail = '') {
    const text = SNAPSHOT_WRITE_REFUSAL_TEXT[code] ?? code;
    super(detail ? `${code}: ${text} (${detail})` : `${code}: ${text}`);
    this.name = 'SnapshotWriteRefusal';
    this.code = code;
    this.text = text;
    this.detail = detail;
  }
}

// -- the wall-clock guard ------------------------------------------------------

/**
 * ISO-8601 instants, and the two other shapes a clock leaks in as: an epoch-millisecond
 * integer large enough to be a real date, and a Date object.
 *
 * The integer bound is deliberately loose (anything at or past 2001-09-09) because the
 * cost of a false positive is a rejected write the author immediately sees, while the cost
 * of a false negative is a rebuild-equality claim that is quietly false forever.
 */
export const ISO_INSTANT_PATTERN = /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?/;

/** Epoch milliseconds at 2001-09-09T01:46:40Z: the floor for "this integer is a clock". */
export const EPOCH_MS_FLOOR = 1_000_000_000_000;

/**
 * Find the first wall-clock value inside a value, reported by its field path.
 *
 * @param {unknown} value @param {string} [trail]
 * @returns {{path: string, value: string}|null}
 */
export function findWallClock(value, trail = '') {
  if (value instanceof Date) return { path: trail || '(root)', value: value.toISOString() };
  if (typeof value === 'string') {
    return ISO_INSTANT_PATTERN.test(value) ? { path: trail || '(root)', value } : null;
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) && Math.abs(value) >= EPOCH_MS_FLOOR
      ? { path: trail || '(root)', value: String(value) }
      : null;
  }
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i += 1) {
      const hit = findWallClock(value[i], `${trail}[${i}]`);
      if (hit !== null) return hit;
    }
    return null;
  }
  if (value !== null && typeof value === 'object') {
    for (const key of Object.keys(value)) {
      const hit = findWallClock(value[key], trail ? `${trail}.${key}` : key);
      if (hit !== null) return hit;
    }
  }
  return null;
}

/**
 * Refuse a body that carries a wall clock. Returns the body so it can wrap an argument.
 *
 * @param {unknown} body @returns {unknown}
 */
export function assertBodyClockFree(body) {
  const hit = findWallClock(body);
  if (hit !== null) {
    throw new SnapshotWriteRefusal(
      SNAPSHOT_WRITE_REFUSAL.BODY_WALL_CLOCK,
      `body.${hit.path} = ${JSON.stringify(hit.value)}`,
    );
  }
  return body;
}

// -- the primitive -------------------------------------------------------------

/** @param {number} attempt @returns {number} the bounded exponential wait, in ms */
export function renameBackoffFor(attempt) {
  const step = RENAME_BACKOFF_BASE_MS * 2 ** Math.max(0, Number(attempt) || 0);
  return Math.min(RENAME_BACKOFF_MAX_MS, step);
}

/** Node has no sync sleep; Atomics.wait on a throwaway buffer is the standard one. */
function sleepSync(ms) {
  const sab = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(sab), 0, 0, Math.max(0, ms));
}

/** @param {object} err @returns {boolean} */
function isTransientRename(err) {
  return Boolean(err && RENAME_TRANSIENT_ERRNOS.includes(err.code));
}

/** Best effort: fsync the directory so the rename itself is durable, not only the bytes. */
function fsyncDirBestEffort(dir, fsx) {
  let fd;
  try {
    fd = fsx.openSync(openablePath(dir), 'r');
    fsx.fsyncSync(fd);
    return true;
  } catch {
    // Windows refuses a directory handle opened this way. Throwing here would fail a write
    // that actually succeeded, which is a worse lie than the missing barrier.
    return false;
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

/** @param {object|undefined} partial @returns {object} fs with the caller's overrides */
function fsFacade(partial) {
  return partial ? { ...fs, ...partial } : fs;
}

/**
 * Write `text` as the snapshot at `snapshotPath`, atomically and durably.
 *
 * A reader NEVER observes a partial snapshot: until the rename lands, the previous bytes
 * are what everyone sees, and after it, the whole new file is.
 *
 * @param {string} snapshotPath
 * @param {string} text the canonical bytes (W6 supplies these; this module never composes them)
 * @param {{fsx?: object, seq?: number, pid?: number, retries?: number,
 *          keepTempOnFailure?: boolean}} [opts]
 * @returns {Readonly<object>} {ok:true, path, temp, byte_len, rename_attempts} or a row outcome
 */
export function writeSnapshotBytes(snapshotPath, text, opts = {}) {
  const fsx = fsFacade(opts.fsx);
  const dir = path.dirname(snapshotPath);
  const pid = Number.isInteger(opts.pid) ? opts.pid : process.pid;
  const seq = Number.isInteger(opts.seq) ? opts.seq : 0;
  const retries = Number.isInteger(opts.retries) ? opts.retries : RENAME_RETRIES;
  const temp = snapshotTempPathFor(snapshotPath, pid, seq);
  const bytes = Buffer.from(String(text), 'utf8');
  const hazards = [];

  for (const candidate of [snapshotPath, temp]) {
    if (isOverMaxPath(candidate)) {
      hazards.push(
        rowOutcome(
          SNAPSHOT_WRITE_CODE.PATH_TOO_LONG,
          { path: candidate, prefix_used: true },
          { ok: true },
        ),
      );
    }
  }

  try {
    fsx.mkdirSync(openablePath(dir), { recursive: true });
  } catch (err) {
    const code = err && err.code;
    return rowOutcome(
      code === 'EACCES' || code === 'EPERM'
        ? SNAPSHOT_WRITE_CODE.DENIED
        : code === 'ENOENT'
          ? SNAPSHOT_WRITE_CODE.HOME_ABSENT
          : SNAPSHOT_WRITE_CODE.HOME_UNREACHABLE,
      { home: dir, errno: code ?? '' },
    );
  }

  // The temp is created with 'wx' (O_EXCL): if a name collides, that is another writer's
  // temp and taking it would let two writers rename over each other.
  let fd;
  try {
    fd = fsx.openSync(openablePath(temp), 'wx');
    fsx.writeSync(fd, bytes, 0, bytes.length);
    try {
      fsx.fsyncSync(fd);
    } catch {
      /* some filesystems refuse fsync; the rename is still atomic */
    }
    fsx.closeSync(fd);
    fd = undefined;
  } catch (err) {
    if (fd !== undefined) {
      try {
        fsx.closeSync(fd);
      } catch {
        /* already closed */
      }
    }
    try {
      fsx.unlinkSync(openablePath(temp));
    } catch {
      /* nothing to remove */
    }
    const code = err && err.code;
    return rowOutcome(
      code === 'EACCES' || code === 'EPERM'
        ? SNAPSHOT_WRITE_CODE.DENIED
        : SNAPSHOT_WRITE_CODE.UNKNOWN,
      {
        home: dir,
        path: temp,
        errno: code ?? '',
        reason: String((err && err.message) || err),
      },
    );
  }

  let attempts = 0;
  let lastErr = null;
  for (; attempts <= retries; attempts += 1) {
    try {
      fsx.renameSync(openablePath(temp), openablePath(snapshotPath));
      const dirSynced = fsyncDirBestEffort(dir, fsx);
      return Object.freeze({
        ok: true,
        code: null,
        status: INTEGRITY.OK,
        path: snapshotPath,
        temp,
        byte_len: bytes.length,
        rename_attempts: attempts + 1,
        dir_fsynced: dirSynced,
        hazards: Object.freeze(hazards),
      });
    } catch (err) {
      lastErr = err;
      if (!isTransientRename(err)) break;
      if (attempts === retries) break;
      sleepSync(renameBackoffFor(attempts));
    }
  }

  // Past the bound. The previous snapshot is untouched, and the temp is LEFT where it is:
  // the W8 sweep removes orphans, and deleting it here would destroy the only evidence of
  // what this process was trying to write.
  if (opts.keepTempOnFailure === false) {
    try {
      fsx.unlinkSync(openablePath(temp));
    } catch {
      /* best effort */
    }
  }
  return Object.freeze({
    ...rowOutcome(SNAPSHOT_WRITE_CODE.RENAME_BLOCKED, {
      path: snapshotPath,
      errno: (lastErr && lastErr.code) || '',
    }),
    temp,
    rename_attempts: attempts + 1,
    presence: PRESENCE.UNREACHABLE,
    hazards: Object.freeze(hazards),
  });
}

/**
 * Validate a snapshot value and write it.
 *
 * Serialization here is a plain key-order-preserving stringify because W6 owns
 * canonicalization; this module's contract is DURABILITY, not byte order, and the two are
 * kept apart so neither can quietly absorb the other's guarantee. W6 hands these bytes in
 * already canonical.
 *
 * @param {string} snapshotPath @param {object} snapshot
 * @param {{fsx?: object, seq?: number, pid?: number, retries?: number, bytes?: string}} [opts]
 * @returns {Readonly<object>}
 */
export function writeSnapshot(snapshotPath, snapshot, opts = {}) {
  const shape = validateSnapshotShape(snapshot);
  if (!shape.ok) {
    throw new SnapshotWriteRefusal(
      SNAPSHOT_WRITE_REFUSAL.SHAPE_INVALID,
      (shape.problems ?? []).map((p) => (typeof p === 'string' ? p : p.message ?? p.code)).join('; '),
    );
  }
  assertBodyClockFree(snapshot.body);

  let text = opts.bytes;
  if (typeof text !== 'string') {
    try {
      text = `${JSON.stringify(snapshot)}\n`;
    } catch (err) {
      throw new SnapshotWriteRefusal(
        SNAPSHOT_WRITE_REFUSAL.NOT_SERIALIZABLE,
        String((err && err.message) || err),
      );
    }
  }
  return writeSnapshotBytes(snapshotPath, text, opts);
}

/** The frozen top-level keys, re-exported so a caller need not import two modules to write one. */
export { SNAPSHOT_KEYS };

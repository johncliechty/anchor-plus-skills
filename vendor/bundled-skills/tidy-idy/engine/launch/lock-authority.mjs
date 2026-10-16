// engine/launch/lock-authority.mjs — Wave 5: CROSS-AGENT LOCK AUTHORITY.
//
// The R1 concurrency-blindness finding, stated plainly: a standalone `tidy-idy P`
// CLI run holds P's lock and is therefore safe against another TIDY run — but
// Anchor's Foreman/Gandalf launchers know nothing about that file, so a build can
// start mutating P's working tree while a tidy Apply is compiling against
// snapshot S. Nothing in Wave 3's lock prevents that, because nothing outside
// this tool was ever told to look.
//
// The refinement: the tidy lockfile at a WELL-KNOWN PATH is the single
// cross-agent source of truth for "a mutating hygiene run owns this root", and
// it is designed to be consulted by processes that are not this tool and are not
// even this language. So this module ships:
//
//   • the well-known path, as a constant, in one place;
//   • a READ-ONLY consult that takes nothing and mutates nothing, with the same
//     stale-PID semantics the writer uses (a dead owner's lock is not held);
//   • `guardMutatingLaunch()` — the decision function a launcher wraps its
//     mutation in: PROCEED or QUEUE, never "mutate anyway".
//
// The symmetric half lives in anchor-caller.mjs: a CLI run that detects it is
// inside an Anchor-managed workspace ALSO registers a best-effort job_runner
// resource claim. "Zero Anchor dependency" means a standalone run's CORRECTNESS
// on a non-Anchor folder never depends on Anchor — it does NOT mean the two
// stacks are mutually blind on a folder they share.
//
// The Python side of this consult is specified, from job_runner's actual source,
// in docs/anchor-job-runner-integration-contract.md.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { REPORT_DIR_NAME } from '../report-dir.mjs';
import { LOCK_FILE, LOCK_REFUSAL, acquireLock, defaultIsAlive } from '../apply/lock.mjs';

/**
 * The well-known path, relative to a project root. Any process in any language
 * can implement the consult with this constant and a JSON parse.
 */
export const TIDY_LOCK_REL = `${REPORT_DIR_NAME}/${LOCK_FILE}`;

export const DECISION = Object.freeze({ PROCEED: 'proceed', QUEUE: 'queue' });

/**
 * Apply entry-lock preflight codes (B5 P4 / SC4).
 * LOCK_HELD = foreign live holder; ENTRY_LOCK_REQUIRED = missing/unlocked when
 * acquire is not permitted (or an explicit invalid borrow with no holder).
 */
export const ENTRY_LOCK_CODE = Object.freeze({
  LOCK_HELD: LOCK_REFUSAL.HELD,
  ENTRY_LOCK_REQUIRED: 'ENTRY_LOCK_REQUIRED',
});

export function tidyLockPathFor(rootPath) {
  return path.join(path.resolve(rootPath), REPORT_DIR_NAME, LOCK_FILE);
}

/**
 * Read the tidy lock for a root WITHOUT taking anything.
 *
 * @param {{rootPath: string, fs?: object, isAlive?: Function}} opts
 * @returns {Promise<{held: boolean, stale: boolean, holder: object|null, path: string, reason: string}>}
 */
export async function consultTidyLock({ rootPath, fs = fsp, isAlive = defaultIsAlive } = {}) {
  const file = tidyLockPathFor(rootPath);
  let holder = null;
  try {
    holder = JSON.parse(String(await fs.readFile(file, 'utf8')));
  } catch (err) {
    if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) {
      return { held: false, stale: false, holder: null, path: file, reason: 'no tidy lockfile — no hygiene run owns this root' };
    }
    // An unreadable/corrupt lockfile is treated as NOT held, matching
    // acquireLock's own steal-the-corrupt-lock rule. The two must agree, or a
    // consulting launcher would queue forever behind a lock the writer would
    // happily steal.
    return { held: false, stale: true, holder: null, path: file, reason: 'tidy lockfile is unreadable/corrupt — treated as stale, exactly as the lock writer treats it' };
  }

  const alive = holder && isAlive(holder.pid);
  if (!alive) {
    return {
      held: false,
      stale: true,
      holder,
      path: file,
      reason: `a tidy lockfile exists but its owning process (pid ${holder && holder.pid}) is gone — stale, reclaimable, and NOT a reason to queue`,
    };
  }
  return {
    held: true,
    stale: false,
    holder,
    path: file,
    reason: `tidy-idy ${holder.purpose || 'run'} owns this root (pid ${holder.pid}${holder.jobId ? `, job ${holder.jobId}` : ''}, since ${holder.acquiredAt})`,
  };
}

/**
 * The decision a folder-mutating launcher (Foreman build, Gandalf run, another
 * tidy run) makes before it touches a root.
 *
 * Note what this function CANNOT return: there is no "mutate anyway" branch. A
 * held lock yields QUEUE, and the caller's only choices are to wait or to give
 * up — which is the property the mock-build test asserts.
 *
 * @param {{rootPath: string, launcher: string, fs?: object, isAlive?: Function}} opts
 */
export async function guardMutatingLaunch({ rootPath, launcher = 'unknown', fs = fsp, isAlive = defaultIsAlive } = {}) {
  const lock = await consultTidyLock({ rootPath, fs, isAlive });
  if (!lock.held) {
    return { decision: DECISION.PROCEED, launcher, lock, message: `${launcher}: ${lock.reason}` };
  }
  return {
    decision: DECISION.QUEUE,
    launcher,
    lock,
    holder: lock.holder,
    message:
      `${launcher} QUEUED behind an active tidy-idy run on '${path.resolve(rootPath)}': ${lock.reason}. `
      + 'A hygiene Apply compiles against a snapshot of this tree; mutating it concurrently is the R1 data-loss sequence.',
  };
}

/**
 * Wait for the tidy lock to clear, then run `fn`. The queueing half of the
 * guard, for a launcher that wants to proceed once the tidy run is done.
 *
 * @param {{rootPath: string, fn: Function, timeoutMs?: number, pollMs?: number,
 *          fs?: object, isAlive?: Function, sleep?: Function, now?: Function}} opts
 */
export async function queueBehindTidyLock({
  rootPath, fn, launcher = 'unknown', timeoutMs = 60000, pollMs = 100,
  fs = fsp, isAlive = defaultIsAlive,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
  now = () => Date.now(),
} = {}) {
  const deadline = now() + timeoutMs;
  for (;;) {
    const guard = await guardMutatingLaunch({ rootPath, launcher, fs, isAlive });
    if (guard.decision === DECISION.PROCEED) {
      return { ran: true, guard, result: await fn() };
    }
    if (now() >= deadline) {
      return { ran: false, guard, timedOut: true, message: `${guard.message} (still held after ${timeoutMs}ms)` };
    }
    await sleep(pollMs);
  }
}

/**
 * Single authoritative apply entry-lock preflight (B5 P4).
 *
 * Valid = borrowed launch/entry lock (`lock.ok === true`) OR successful
 * `acquireLock`. Unlocked / missing / foreign → structured refuse codes with
 * no mutation authority granted to the caller. Panel and library Apply paths
 * must call this (via applyApproved) so preflight cannot be bypassed.
 *
 * @param {{
 *   rootPath: string,
 *   reportDir: string,
 *   lock?: object|null,
 *   jobId?: string|null,
 *   purpose?: string,
 *   fs?: object,
 *   now?: Function,
 *   isAlive?: Function,
 *   allowAcquire?: boolean,
 * }} opts
 * @returns {Promise<
 *   | { ok: true, lock: object, borrowed: boolean, consult: object }
 *   | { ok: false, code: string, message: string, holder: object|null,
 *       lock: null, borrowed: false, consult: object }
 * >}
 */
export async function ensureApplyEntryLock({
  rootPath,
  reportDir,
  lock: borrowedLock = null,
  jobId = null,
  purpose = 'apply',
  fs = fsp,
  now = () => new Date(),
  isAlive = defaultIsAlive,
  /**
   * When true (default): acquire if no valid borrow (library path).
   * When false: missing borrow → ENTRY_LOCK_REQUIRED (strict entry gate for
   * callers that must already hold the launch lock).
   */
  allowAcquire = true,
} = {}) {
  const consult = await consultTidyLock({ rootPath, fs, isAlive });

  // Explicit non-ok borrow (caller passed a failed/foreign lock object).
  if (borrowedLock != null && borrowedLock.ok !== true) {
    const hasHolder = Boolean(borrowedLock.holder);
    const code = hasHolder || borrowedLock.code === LOCK_REFUSAL.HELD || borrowedLock.code === ENTRY_LOCK_CODE.LOCK_HELD
      ? ENTRY_LOCK_CODE.LOCK_HELD
      : ENTRY_LOCK_CODE.ENTRY_LOCK_REQUIRED;
    return {
      ok: false,
      code,
      message:
        borrowedLock.message
        || (code === ENTRY_LOCK_CODE.ENTRY_LOCK_REQUIRED
          ? 'Apply refuses: no valid entry/apply lock — establish lock via panel launch (borrowed) or acquireLock; unlocked apply is refused with zero mutation'
          : `Apply refuses: entry/apply lock is not held${borrowedLock.holder ? ` (holder pid ${borrowedLock.holder.pid})` : ''}`),
      holder: borrowedLock.holder || consult.holder || null,
      lock: null,
      borrowed: false,
      consult,
    };
  }

  // Valid borrowed launch/entry lock — still reject foreign on-disk authority.
  if (borrowedLock && borrowedLock.ok === true) {
    const borrowToken = borrowedLock.record && borrowedLock.record.token;
    if (
      consult.held
      && borrowToken
      && consult.holder
      && consult.holder.token
      && consult.holder.token !== borrowToken
    ) {
      return {
        ok: false,
        code: ENTRY_LOCK_CODE.LOCK_HELD,
        message:
          `Apply refuses: a foreign tidy-idy ${consult.holder.purpose || 'run'} holds the lock for this project `
          + `(pid ${consult.holder.pid}${consult.holder.jobId ? `, job ${consult.holder.jobId}` : ''}) — `
          + 'the borrowed lock token does not match the on-disk lock authority; zero mutation',
        holder: consult.holder,
        lock: null,
        borrowed: false,
        consult,
      };
    }
    return { ok: true, lock: borrowedLock, borrowed: true, consult };
  }

  // No borrow: strict entry gate refuses unlocked/missing without acquiring.
  if (!allowAcquire) {
    if (consult.held) {
      return {
        ok: false,
        code: ENTRY_LOCK_CODE.LOCK_HELD,
        message:
          `Apply refuses: ${consult.reason} — allowAcquire is false so Apply will not steal or re-acquire; `
          + 'pass the launch entry lock as a borrow, or release the foreign holder first',
        holder: consult.holder,
        lock: null,
        borrowed: false,
        consult,
      };
    }
    return {
      ok: false,
      code: ENTRY_LOCK_CODE.ENTRY_LOCK_REQUIRED,
      message:
        'Apply refuses: no valid entry/apply lock — establish lock via panel launch (borrowed) or acquireLock; '
        + 'unlocked apply is refused with zero mutation',
      holder: null,
      lock: null,
      borrowed: false,
      consult,
    };
  }

  // Library path: successful acquireLock is a valid entry/apply lock.
  const acquired = await acquireLock({
    reportDir,
    jobId,
    purpose,
    fs,
    now,
    isAlive,
  });
  if (!acquired.ok) {
    return {
      ok: false,
      code: ENTRY_LOCK_CODE.LOCK_HELD,
      message: acquired.message,
      holder: acquired.holder || null,
      lock: null,
      borrowed: false,
      consult: await consultTidyLock({ rootPath, fs, isAlive }),
    };
  }
  return {
    ok: true,
    lock: acquired,
    borrowed: false,
    consult: await consultTidyLock({ rootPath, fs, isAlive }),
  };
}

export default {
  consultTidyLock,
  guardMutatingLaunch,
  queueBehindTidyLock,
  ensureApplyEntryLock,
  tidyLockPathFor,
  TIDY_LOCK_REL,
  DECISION,
  ENTRY_LOCK_CODE,
};

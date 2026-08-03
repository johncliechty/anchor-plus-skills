// engine/apply/lock.mjs — Wave 3: the per-project-root advisory lock.
//
// One lock per PROJECT ROOT, honoured by scan runs AND by Apply. It is
// ADVISORY in the precise sense that it coordinates this tool's own processes
// (a CLI run, an Anchor-dispatched job, a panel-initiated Apply) and makes no
// claim about anyone else's editor — the tool's real defence against a
// concurrent human is snapshot-S revalidation, not this file.
//
// What it does buy is the thing revalidation cannot: two Applies interleaving
// inside the same lock window would each pass their own HEAD==S.head assertion
// and then race on `update-ref`, and the loser's compiled work would be silently
// discarded. So Apply takes the lock, asserts HEAD inside it, and only then
// commits.
//
// A lock whose owning process is GONE is stale, and a stale lock that survives a
// crash would wedge the project forever — which users fix by deleting files they
// do not understand. So a lock held by a dead PID is stolen, loudly, with the
// theft recorded in the returned record and in the run journal.

import fsp from 'node:fs/promises';
import crypto from 'node:crypto';
import os from 'node:os';
import path from 'node:path';

export const LOCK_FILE = 'tidy-idy.lock';

export const LOCK_REFUSAL = Object.freeze({ HELD: 'LOCK_HELD' });

export function lockPathFor(reportDir) {
  return path.join(reportDir, LOCK_FILE);
}

/** Is a PID still around? EPERM means "yes, and not ours to signal". */
export function defaultIsAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err && err.code === 'EPERM';
  }
}

/**
 * Take the project lock.
 *
 * @param {{reportDir: string, jobId?: string|null, purpose?: string, pid?: number,
 *   fs?: object, now?: Function, isAlive?: Function, stealStale?: boolean}} opts
 * @returns {Promise<{ok: true, record: object, stolenFrom: object|null, release: Function}
 *                  |{ok: false, code: string, holder: object|null, message: string}>}
 */
export async function acquireLock({
  reportDir,
  jobId = null,
  purpose = 'apply',
  pid = process.pid,
  fs = fsp,
  now = () => new Date(),
  isAlive = defaultIsAlive,
  stealStale = true,
} = {}) {
  const file = lockPathFor(reportDir);
  await fs.mkdir(reportDir, { recursive: true });

  const record = {
    version: 1,
    pid,
    jobId,
    purpose,
    host: os.hostname(),
    // Proof of ownership, so a release can never delete somebody else's lock
    // that happens to sit at the same path after a steal.
    token: crypto.randomBytes(16).toString('hex'),
    acquiredAt: now().toISOString(),
  };

  let stolenFrom = null;

  const write = async (flag) => fs.writeFile(file, `${JSON.stringify(record, null, 2)}\n`, { flag });

  try {
    await write('wx');
  } catch (err) {
    if (!err || err.code !== 'EEXIST') throw err;

    let holder = null;
    try {
      holder = JSON.parse(String(await fs.readFile(file, 'utf8')));
    } catch {
      holder = null; // unreadable/corrupt: treated as stale below
    }

    const holderAlive = holder && isAlive(holder.pid);
    if (holderAlive) {
      return {
        ok: false,
        code: LOCK_REFUSAL.HELD,
        holder,
        message: `another tidy-idy ${holder.purpose || 'run'} holds the lock for this project (pid ${holder.pid}${holder.jobId ? `, job ${holder.jobId}` : ''}, since ${holder.acquiredAt}) — one Apply at a time, per project root`,
      };
    }

    if (!stealStale) {
      return { ok: false, code: LOCK_REFUSAL.HELD, holder, message: 'a stale lock is present and stealing is disabled' };
    }

    stolenFrom = holder;
    record.stolenFrom = holder
      ? { pid: holder.pid, jobId: holder.jobId || null, acquiredAt: holder.acquiredAt || null, reason: 'owning process is gone' }
      : { pid: null, reason: 'lockfile was unreadable' };
    await write('w');
  }

  return {
    ok: true,
    record,
    stolenFrom,
    async release() {
      try {
        const current = JSON.parse(String(await fs.readFile(file, 'utf8')));
        // Only ever remove OUR lock. If someone stole it from us mid-run, the
        // correct action is to leave theirs alone.
        if (current && current.token !== record.token) return false;
      } catch {
        return false;
      }
      await fs.rm(file, { force: true });
      return true;
    },
  };
}

/** Run `fn` under the lock, releasing it on every exit path including throws. */
export async function withLock(opts, fn) {
  const lock = await acquireLock(opts);
  if (!lock.ok) return { lock, result: null };
  try {
    const result = await fn(lock);
    return { lock, result };
  } finally {
    await lock.release().catch(() => {});
  }
}

/** Read the current holder without taking anything. Used by scan-side gating. */
export async function readLock(reportDir, { fs = fsp } = {}) {
  try {
    return JSON.parse(String(await fs.readFile(lockPathFor(reportDir), 'utf8')));
  } catch {
    return null;
  }
}

export default { acquireLock, withLock, readLock, lockPathFor, LOCK_FILE, LOCK_REFUSAL, defaultIsAlive };

// proc-guard.mjs — Foreman Wave 7: per-call timeout + kill-on-exit + the run lock.
//
// The live runner spawns real `claude -p` children. Two durability invariants that
// the wave-7 induced-kill probe asserts live here, and are exercised against a
// dummy long-lived child (no model needed) by proc-guard.test.mjs:
//
//   - PER-CALL TIMEOUT + KILL-ON-EXIT: `spawnGuarded()` wraps a spawn with an
//     optional per-call timeout that SIGKILLs a hung child, and registers the
//     child with a `makeChildRegistry()` whose exit/SIGINT/SIGTERM handler
//     SIGKILLs every still-live child. So an orchestrator that is itself killed
//     mid-wave leaves ZERO surviving child PIDs (never a leaked, wedged child).
//
//   - THE RUN LOCK: `acquireLock()` writes a `{ pid, started_at }` lockfile that
//     a single Foreman run holds for its lifetime and RELEASES on exit. A lock
//     held by a LIVE pid refuses a concurrent run (HALT); a lock left by a DEAD
//     pid is stale and is reclaimed — so a crash/kill never wedges the next run
//     out (the resume path can re-acquire and re-enter at the gate).
//
// All process-control here is synchronous (the only thing safe in a 'exit'
// handler): SIGKILL via child.kill, lockfile removal via fs.rmSync.

import { spawn as nodeSpawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import { HaltError } from './foreman-lib.mjs';

// ---------------------------------------------------------------------------
// Tracked-child registry + kill-on-exit.
// ---------------------------------------------------------------------------

/**
 * Build a registry of live child processes with a kill-on-exit guard. `track`/
 * `untrack` are called around a child's lifetime; `killAll()` SIGKILLs every
 * still-tracked child (this is exactly what the installed exit/signal handlers
 * call). `install()` wires `process` 'exit'/'SIGINT'/'SIGTERM' so an orchestrator
 * teardown — clean OR signalled — drops no leaked child. Idempotent; `uninstall()`
 * removes the handlers (used by tests to avoid leaking listeners across cases).
 */
export function makeChildRegistry({ log = () => {} } = {}) {
  const children = new Set();
  let installed = false;

  function killAll() {
    let killed = 0;
    for (const c of [...children]) {
      try {
        if (c && c.pid && c.exitCode === null && !c.killed) { c.kill('SIGKILL'); killed++; }
      } catch { /* already gone — nothing to kill */ }
      children.delete(c);
    }
    return killed;
  }

  const onExit = () => { killAll(); };
  // On a terminating signal: kill children, then re-raise the default disposition
  // by exiting non-zero (the 'exit' handler also runs and is a no-op second pass).
  const onSignal = (sig) => {
    const n = killAll();
    if (n) log(`proc-guard: SIGKILLed ${n} leaked child process(es) on ${sig}`);
    process.exit(sig === 'SIGINT' ? 130 : 143);
  };

  return {
    track(child) { if (child) children.add(child); return child; },
    untrack(child) { children.delete(child); },
    killAll,
    size: () => children.size,
    install() {
      if (installed) return;
      installed = true;
      process.on('exit', onExit);
      process.on('SIGINT', onSignal);
      process.on('SIGTERM', onSignal);
    },
    uninstall() {
      if (!installed) return;
      installed = false;
      process.removeListener('exit', onExit);
      process.removeListener('SIGINT', onSignal);
      process.removeListener('SIGTERM', onSignal);
    },
  };
}

/**
 * Spawn a child under the per-call timeout + registry guard. Returns the live
 * child immediately (so the caller can attach its own stdout/stderr listeners)
 * plus a `done` promise that resolves with the typed-exit inputs once the child
 * closes. The child is auto-tracked in the registry for its lifetime and
 * auto-untracked on close.
 *
 * @param {object} o
 * @param {string}   o.command
 * @param {string[]} [o.args=[]]
 * @param {string}   [o.cwd]
 * @param {?number}  [o.timeoutMs=null]   per-call timeout; null/0 = no timeout
 * @param {object}   [o.registry=null]    a makeChildRegistry() to track this child
 * @param {Function} [o.spawnImpl]        injectable spawn (tests); default node:child_process spawn
 * @returns {{child: import('node:child_process').ChildProcess|null,
 *            done: Promise<{code:?number,signal:?string,timedOut:boolean,spawnError:Error|null}>,
 *            state: {timedOut:boolean}}}
 */
export function spawnGuarded({ command, args = [], cwd, timeoutMs = null, registry = null, spawnImpl = nodeSpawn }) {
  const state = { timedOut: false };
  let child = null;
  let spawnError = null;
  try {
    child = spawnImpl(command, args, cwd ? { cwd } : {});
  } catch (e) {
    spawnError = e;
  }

  if (child && registry) registry.track(child);

  let timer = null;
  if (child && timeoutMs != null && timeoutMs > 0) {
    timer = setTimeout(() => {
      state.timedOut = true;
      try { child.kill('SIGKILL'); } catch { /* already gone */ }
    }, timeoutMs);
    if (timer && typeof timer.unref === 'function') timer.unref(); // never keep the loop alive on the timer alone
  }

  const done = new Promise((resolve) => {
    if (!child) { resolve({ code: null, signal: null, timedOut: false, spawnError }); return; }
    // A spawn that fails asynchronously (e.g. ENOENT) emits 'error' then 'close'.
    child.on('error', (e) => { if (!spawnError) spawnError = e; });
    child.on('close', (code, signal) => {
      if (timer) clearTimeout(timer);
      if (registry) registry.untrack(child);
      resolve({ code, signal, timedOut: state.timedOut, spawnError });
    });
  });

  return { child, done, state };
}

// ---------------------------------------------------------------------------
// The run lock.
// ---------------------------------------------------------------------------

/** True iff `pid` is a live process. EPERM ⇒ it exists but isn't ours ⇒ alive. */
export function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; }
  catch (e) { return e && e.code === 'EPERM'; }
}

/** Read + parse a lockfile; null on missing/unreadable/garbage (treated as stale). */
export function readLock(lockPath) {
  try {
    const obj = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
    return (obj && typeof obj === 'object') ? obj : null;
  } catch { return null; }
}

/**
 * Acquire the single-run lock at `lockPath`.
 *
 *   - No lockfile           -> create it, return a handle.
 *   - Lock held by a LIVE,
 *     different pid          -> HaltError (refuse a concurrent run; §6 HALT).
 *   - Lock held by OUR pid   -> re-adopt it (idempotent within a run).
 *   - Lock left by a DEAD
 *     pid (or unreadable)    -> STALE: reclaim it and create a fresh lock.
 *
 * The handle's `release()` removes the lockfile, but only if it still belongs to
 * us (never clobbers a lock a later run legitimately re-took after we went away).
 *
 * @param {string} lockPath
 * @param {object} [o]
 * @param {number} [o.pid=process.pid]
 * @param {()=>number} [o.now=Date.now]
 * @param {string} [o.label='']
 * @returns {{lockPath:string, pid:number, release:()=>void}}
 */
export function acquireLock(lockPath, {
  pid = process.pid,
  now = Date.now,
  label = '',
  onStale = null, // 0082 P2.10: (prevLock) => void when reclaiming a dead-pid lock
} = {}) {
  const dest = path.resolve(lockPath);
  if (fs.existsSync(dest)) {
    const prev = readLock(dest);
    if (prev && Number.isInteger(prev.pid) && prev.pid !== pid && isPidAlive(prev.pid)) {
      throw new HaltError(
        'another Foreman run holds the lock',
        `${dest} is held by live pid ${prev.pid} (started ${prev.started_at ?? '?'}) — ` +
        `only one Foreman run may drive a project at a time; stop the other run or remove a stale lock`,
      );
    }
    // Stale (dead pid / unreadable / our own) — reclaim by removing it first.
    if (prev && Number.isInteger(prev.pid) && prev.pid !== pid && !isPidAlive(prev.pid)) {
      try {
        if (typeof onStale === 'function') onStale(prev);
      } catch { /* never block reclaim on forensics */ }
    }
    fs.rmSync(dest, { force: true });
  }

  const body = JSON.stringify({ pid, started_at: now(), label }, null, 0);
  // `wx` = create exclusively; fails (EEXIST) if a racing run beat us to it after
  // the stale-reclaim above — surfaced as a HALT rather than silently overwriting.
  let fd;
  try {
    fd = fs.openSync(dest, 'wx');
  } catch (e) {
    if (e && e.code === 'EEXIST') {
      throw new HaltError('lost a race to acquire the run lock',
        `${dest} appeared after the stale-reclaim — another run is starting concurrently; retry once`);
    }
    throw e;
  }
  try { fs.writeSync(fd, body); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }

  let released = false;
  return {
    lockPath: dest,
    pid,
    release() {
      if (released) return;
      released = true;
      try {
        const cur = readLock(dest);
        if (!cur || cur.pid === pid) fs.rmSync(dest, { force: true });
      } catch { /* best-effort: a missing/locked file on release is not fatal */ }
    },
  };
}

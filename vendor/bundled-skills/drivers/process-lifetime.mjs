// process-lifetime.mjs — fail-loud process guards for long-lived trio engines.
//
// Sleep ticket F-H (foreman 0072 / crucible 0064 / F036–F045): live Foreman and
// Crucible runs died mid-agent-call with empty stderr, orphan locks, and
// checkpoint stuck mid-wave. Root class: no process-level handlers + no durable
// progress stamp before long agent calls, so external kills / unhandled
// rejections / abrupt exits left zero forensics and forced full re-execute.
//
// This module is deliberately tiny and dependency-free (stdlib only). Install
// once at engine entry (run-live, Crucible launchers, self-run).

import fs from 'node:fs';
import path from 'node:path';

/**
 * @param {object} o
 * @param {(s:string)=>void} [o.log]
 * @param {string} [o.crashPath]  absolute path for last-crash.json
 * @param {string} [o.heartbeatPath]  absolute path for heartbeat.json (optional)
 * @param {string} [o.label='engine']
 * @param {(payload:object)=>void} [o.onFatal]  optional hook after last-crash write
 *   (Crucible Stage-2 uses this to stamp HALT.json — 2026-07-24 wave 3)
 * @returns {{ installed: true, beat: Function, note: Function, uninstall: Function, fatal: Function }}
 */
export function installProcessLifetimeGuards({
  log = () => {},
  crashPath = null,
  heartbeatPath = null,
  label = 'engine',
  onFatal = null,
} = {}) {
  let uninstalled = false;
  let exitArmed = false; // true after non-benign fatal schedules process.exit
  const startedAt = new Date().toISOString();
  const pid = process.pid;

  function writeJsonAtomic(file, obj) {
    if (!file) return;
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      const tmp = `${file}.${pid}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(obj, null, 2) + '\n', 'utf8');
      fs.renameSync(tmp, file);
    } catch (e) {
      try { log(`!! ${label} process-lifetime write failed: ${e.message}`); } catch { /* never throw from guard */ }
    }
  }

  function note(msg, extra = {}) {
    const line = `[process-lifetime] ${msg}`;
    try { log(line); } catch { /* */ }
    if (heartbeatPath) {
      writeJsonAtomic(heartbeatPath, {
        label, pid, startedAt,
        ts: new Date().toISOString(),
        note: msg,
        ...extra,
      });
    }
  }

  /** Parent closed stdout/stderr — must not kill long-lived engines (F-H residual / 0083). */
  function isBenignIoError(err) {
    if (!err) return false;
    const code = err.code || '';
    const msg = String(err.message || err);
    return code === 'EPIPE' || code === 'EIO' || /broken pipe/i.test(msg);
  }

  function fatal(kind, err, code = 2) {
    if (uninstalled) return;
    // Logging / pipe errors are never fatal: status file + heartbeat still work.
    if (isBenignIoError(err)) {
      note(`benign ${kind} ignored: ${err.code || err.message || err}`);
      return;
    }
    const message = err?.stack || err?.message || String(err);
    const payload = {
      label,
      pid,
      startedAt,
      kind,
      message: String(message).slice(0, 8000),
      ts: new Date().toISOString(),
      exit_code: code,
    };
    try { log(`!! FATAL ${kind}: ${String(err?.message || err).slice(0, 500)}`); } catch { /* */ }
    if (crashPath) writeJsonAtomic(crashPath, payload);
    if (heartbeatPath) {
      writeJsonAtomic(heartbeatPath, { ...payload, dead: true });
    }
    if (typeof onFatal === 'function') {
      try { onFatal(payload); } catch { /* never throw from guard */ }
    }
    // Prefer non-zero exit so supervisors see failure; avoid recursive fatal.
    try {
      uninstalled = true;
      exitArmed = true;
      process.exitCode = code;
      // Defer exit one tick so log appends flush when possible.
      setImmediate(() => {
        // uninstall({ disarm: true }) cancels deferred exit for unit tests.
        if (!exitArmed) return;
        try { process.exit(code); } catch { /* */ }
      });
    } catch { /* */ }
  }

  const onUncaught = (err) => fatal('uncaughtException', err, 2);
  const onRejection = (reason) => fatal('unhandledRejection', reason instanceof Error ? reason : new Error(String(reason)), 2);
  const onSigInt = () => {
    note('SIGINT');
    fatal('SIGINT', new Error('SIGINT'), 130);
  };
  const onSigTerm = () => {
    note('SIGTERM');
    fatal('SIGTERM', new Error('SIGTERM'), 143);
  };

  process.on('uncaughtException', onUncaught);
  process.on('unhandledRejection', onRejection);
  process.on('SIGINT', onSigInt);
  process.on('SIGTERM', onSigTerm);

  note('guards installed', { node: process.version });

  function beat(extra = {}) {
    if (heartbeatPath) {
      writeJsonAtomic(heartbeatPath, {
        label, pid, startedAt,
        ts: new Date().toISOString(),
        alive: true,
        ...extra,
      });
    }
  }

  // Lightweight heartbeat so operators can tell "hung agent" from "process dead".
  const hb = setInterval(() => beat({ tick: true }), 30_000);
  if (typeof hb.unref === 'function') hb.unref();

  /**
   * @param {{ disarm?: boolean }} [o]  disarm:true cancels a deferred fatal exit
   *   and clears process.exitCode (unit tests that invoke fatal() without dying).
   */
  function uninstall(o = {}) {
    const disarm = !!(o && o.disarm);
    if (disarm) {
      exitArmed = false;
      try { process.exitCode = 0; } catch { /* */ }
    }
    if (uninstalled && !disarm) return;
    if (!uninstalled) {
      uninstalled = true;
      clearInterval(hb);
      process.removeListener('uncaughtException', onUncaught);
      process.removeListener('unhandledRejection', onRejection);
      process.removeListener('SIGINT', onSigInt);
      process.removeListener('SIGTERM', onSigTerm);
      note('guards uninstalled (clean shutdown)');
    }
  }

  // Clean uninstall on normal exit path (does not fire on SIGKILL).
  process.once('beforeExit', () => {
    try { uninstall(); } catch { /* */ }
  });

  return { installed: true, beat, note, uninstall, fatal };
}

/**
 * Wrap a long async agent call so progress is stamped before/after and
 * rejections become logged Halt-shaped failures instead of silent process death.
 *
 * @template T
 * @param {object} o
 * @param {() => Promise<T>} o.fn
 * @param {string} o.phase
 * @param {(s:string)=>void} [o.log]
 * @param {string} [o.progressPath]  write {phase,ts,status} here
 * @param {ReturnType<typeof installProcessLifetimeGuards>|null} [o.guards]
 * @returns {Promise<T>}
 */
export async function withPhaseProgress({
  fn,
  phase,
  log = () => {},
  progressPath = null,
  guards = null,
} = {}) {
  const stamp = (status, extra = {}) => {
    const line = `phase ${phase}: ${status}`;
    try { log(line); } catch { /* */ }
    if (guards?.beat) guards.beat({ phase, status, ...extra });
    if (progressPath) {
      try {
        fs.mkdirSync(path.dirname(progressPath), { recursive: true });
        const tmp = `${progressPath}.tmp`;
        fs.writeFileSync(tmp, JSON.stringify({
          phase, status, ts: new Date().toISOString(), ...extra,
        }, null, 2) + '\n', 'utf8');
        fs.renameSync(tmp, progressPath);
      } catch { /* best-effort */ }
    }
  };
  stamp('start');
  try {
    const result = await fn();
    stamp('done');
    return result;
  } catch (e) {
    stamp('error', { error: String(e?.message || e).slice(0, 500) });
    throw e;
  }
}

export default { installProcessLifetimeGuards, withPhaseProgress };

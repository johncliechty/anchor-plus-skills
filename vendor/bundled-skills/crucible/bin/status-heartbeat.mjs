// status-heartbeat.mjs — the engine-emitted 10-minute Status table for Crucible
// (2026-07-11). Parity with Foreman's run-live status emitter, adapted to
// Crucible's stage-loop model.
//
// WHY: Crucible had NO status emitter at all, so a real run (a Shark-Tank stage
// loop can run 20-40 min) went completely dark. The locked global 10-minute rule
// needs a data source for the supervising session to relay to chat; this writes
// the LOCKED Status-table shape to a status log every ~10 min, plus at t=0 and on
// stop. Shell-free, best-effort (a logging failure never touches the run), and a
// no-op when no logPath is supplied (so tests and dogfood runs stay silent).
//
// The supervising session tails `<outputDir>/_crucible-status.log` and posts the
// latest table to chat (see crucible SKILL.md "How to run" — background + wakeup).

import fs from 'node:fs';

/**
 * Arm a status heartbeat. Returns { stop(tag?) } — call stop() when the loop
 * returns OR throws (a `finally` is the right place) so the final table lands and
 * the timer is cleared.
 *
 * @param {object}   o
 * @param {?string}  o.logPath              where to append the table (null ⇒ no-op)
 * @param {Function} o.snapshot             () => { effort, doing, status, tests, blocker, procs, eta, todo }
 * @param {string}   [o.label='Crucible plan']
 * @param {number}   [o.intervalMs=600000]  ~10 min
 * @param {Function} [o.now=()=>Date.now()] injectable clock (tests)
 */
export function startStatusHeartbeat({ logPath, snapshot, label = 'Crucible plan', intervalMs = 600000, now = () => Date.now() } = {}) {
  if (!logPath || typeof snapshot !== 'function') return { stop() {} };
  const t0 = now();
  const write = (tag) => {
    try {
      const s = snapshot() || {};
      const d = new Date(now());
      const hhmm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
      const elapsed = Math.round((now() - t0) / 60000);
      // Plain ASCII only (0075 / 0082) — unicode box-drawing garbles on some hosts.
      const bar = '---------------------------------';
      const table = [
        `[${hhmm}] ${label}${tag ? ` · ${tag}` : ''}`,
        bar,
        `Effort   ${s.effort ?? label}`,
        `Doing    ${s.doing ?? '...'}`,
        `Status   ${s.status ?? '-'} · elapsed ${elapsed}m`,
        `Tests    ${s.tests ?? '-'}`,
        `Blocker  ${s.blocker ?? 'none'}`,
        `Procs    ${s.procs ?? '-'}`,
        bar,
        `ETA      ${s.eta ?? 'estimating'}`,
        `To do    ${s.todo ?? '-'}`,
      ].join('\n');
      fs.appendFileSync(logPath, table + '\n');
    } catch { /* never crash a plan on logging */ }
  };
  write('t=0');
  const timer = setInterval(() => write(), intervalMs);
  if (timer && typeof timer.unref === 'function') timer.unref();
  return {
    stop(tag = 'final') {
      clearInterval(timer);
      write(tag);
    },
  };
}

import fs from 'node:fs';

// Shared swarm look-in — NOT a kill timer.
//
// John's rule (2026-08-27, restating the 2026-08-24 Foreman checkpoint-supervision
// design / Move 6): the orchestrator LOOKS IN on a long-running seat — trail +
// 3-line self-report vs the locked North Star, Rabbit-Catcher RC-6 + elegance —
// and lets a TALKING agent tidy itself. Time-since-start is not a kill reason
// when the seat is heartbeating. Silence is: spawned seats MUST respond; look
// in, then kill and respawn once. Self-report is never trusted without a trail.
//
// Consumed by researchPrime panel, Crucible Sharks, Foreman seats, Gandalf
// refuters, Jumper spheres. One module, no per-skill fork.

/** First "are you there?" — spawned seats MUST heartbeat. Silence is not work. */
export const DEFAULT_CHECKIN_MS = 90 * 1000;
/** After a look-in demand, still silent → kill and respawn. */
export const DEFAULT_SILENT_KILL_MS = 60 * 1000;
/** Idle since LAST heartbeat went quiet (a talking seat that died). */
export const DEFAULT_DEAD_IDLE_MS = 90 * 1000;
/** One restart. A seat that dies twice is not something we keep feeding. */
export const DEFAULT_MAX_RESPAWN = 1;

/**
 * Prompt fragment every swarm seat carries. The agent writes a heartbeat the
 * orchestrator can read; if it notices a rabbit hole it cuts itself.
 * @param {{ heartbeatPath?: string, northStar?: string }} [o]
 */
export function lookinAppendix({ heartbeatPath, northStar } = {}) {
  const hb = heartbeatPath || 'heartbeat.json';
  return [
    `LOOK-IN: you MUST write ${hb} as JSON {doing, why, next, load_bearing:true|false, rabbit:false, ts} within the first look-in window. Silence is treated as death — the orchestrator will kill and respawn you.`,
    `Keep refreshing that file every few actions while you work.`,
    `RC-6: if this step is not on the critical path to the North Star, STOP, return what you have, set rabbit:true.`,
    `Elegance: largest result carried by the least machinery. Do not add extra validation nobody asked for.`,
    `If you notice a rabbit hole, cut it and tidy — pull yourself together.`,
    northStar ? `NORTH STAR: ${northStar}` : null,
  ].filter(Boolean).join(' ');
}

/** Read a heartbeat file the seat was told to write. Missing → null (silence, then look-in, then death).
 *  Progress time is the file's PHYSICAL write time. The seat's self-reported `ts` is kept as data but
 *  never trusted as the clock: models write fake/ISO timestamps ("2026-09-01T00:00:00Z" was observed),
 *  which made `mtime` a non-finite value, so a heartbeating seat still read as silent and was killed
 *  mid-work (Gate 5 Foreman wave 1, 2026-09-01: 27 tool calls at 180 s, declared dead twice). */
export function trailFromFile(filePath) {
  if (!filePath) return null;
  try {
    const st = fs.statSync(filePath);
    const parsed = parseHeartbeat(fs.readFileSync(filePath, 'utf8'));
    if (!parsed) return { mtime: st.mtimeMs };
    return { ...parsed, mtime: st.mtimeMs };
  } catch {
    return null;
  }
}

export function parseHeartbeat(raw) {
  if (raw == null) return null;
  let obj = raw;
  if (typeof raw === 'string') {
    try { obj = JSON.parse(raw); } catch { return null; }
  }
  if (!obj || typeof obj !== 'object') return null;
  const load = obj.load_bearing;
  return {
    doing: typeof obj.doing === 'string' ? obj.doing : '',
    why: typeof obj.why === 'string' ? obj.why : '',
    next: typeof obj.next === 'string' ? obj.next : '',
    load_bearing: load === false || load === 'false' ? false : true,
    rabbit: obj.rabbit === true || obj.rabbit === 'true',
    ts: Number(obj.ts) || null,
  };
}

/**
 * @param {{ trail, idle: number, demanded?: boolean, checkInMs?: number, silentKillMs?: number, deadIdleMs?: number }} o
 * @returns {'keep'|'lookin'|'lookin-silent'|'dead'}
 */
export function verdictFromTrail({
  trail, idle, demanded = false,
  checkInMs = DEFAULT_CHECKIN_MS,
  silentKillMs = DEFAULT_SILENT_KILL_MS,
  deadIdleMs = DEFAULT_DEAD_IDLE_MS,
} = {}) {
  const checkMs = Number.isFinite(checkInMs) && checkInMs > 0 ? checkInMs : DEFAULT_CHECKIN_MS;
  const graceMs = Number.isFinite(silentKillMs) && silentKillMs > 0 ? silentKillMs : DEFAULT_SILENT_KILL_MS;
  const deadMs = Number.isFinite(deadIdleMs) && deadIdleMs > 0 ? deadIdleMs : DEFAULT_DEAD_IDLE_MS;
  if (trail && (trail.rabbit === true || trail.load_bearing === false)) return 'lookin';
  if (trail) {
    // Talking seats: only die if the heartbeat itself goes quiet.
    return idle >= deadMs ? 'dead' : 'keep';
  }
  // Silent seats MUST respond. Look in first, then kill.
  if (!demanded && idle >= checkMs) return 'lookin-silent';
  if (demanded && idle >= checkMs + graceMs) return 'dead';
  return 'keep';
}

export function composeLookinNudge({ northStar, task, trail, silent = false } = {}) {
  const doing = trail?.doing || 'unknown';
  if (silent) {
    return [
      `LOOK-IN — you have not responded. Spawned seats MUST heartbeat.`,
      `Write the heartbeat file NOW: {doing, why, next, load_bearing, rabbit:false, ts}.`,
      `If you cannot, stop and return what you have. Silence on the next look-in is death — you will be killed and respawned.`,
      northStar ? `North Star: ${northStar}` : null,
      task ? `Original task: ${task}` : null,
    ].filter(Boolean).join(' ');
  }
  return [
    `LOOK-IN — you have been running a while. This is not a kill (yet).`,
    `What you last reported: doing="${doing}"; why="${trail?.why || ''}"; next="${trail?.next || ''}".`,
    northStar ? `North Star: ${northStar}` : null,
    task ? `Original task: ${task}` : null,
    `RC-6: is the CURRENT step on the critical path, or a rabbit hole?`,
    `If it is extra validation / not load-bearing: CUT it, return what you already have, tidy.`,
    `If it is load-bearing: say so in one line, keep going, refresh the heartbeat.`,
    `Elegance yardstick: largest result, least machinery. Pull yourself together.`,
  ].filter(Boolean).join(' ');
}

function defaultSleep(ms) {
  return new Promise((r) => {
    const t = setTimeout(r, ms);
    if (typeof t.unref === 'function') t.unref();
  });
}

function deadError(idle, extra = '') {
  const err = new Error(
    `swarm seat DEAD: no response for ${idle}ms — silence is death${extra ? ` (${extra})` : ''}`,
  );
  err.classification = { class: 'timeout', recoverable: false };
  err.lookin_verdict = 'dead';
  return err;
}

/**
 * Supervise one attempt. Silent seats are looked into, then killed if they
 * still do not heartbeat. Talking seats KEEP even when wall-clock is long.
 */
async function superviseOnce({
  run, getTrail, checkInMs, silentKillMs, deadIdleMs,
  now, sleep, onCheckin, onLookin, northStar, task,
  strictAbortJoin = false, controller = null,
}) {
  const started = now();
  let lastProgress = started;
  let demanded = false;
  let settled = false;
  let result;
  let error;
  const p = Promise.resolve().then(() => run()).then(
    (v) => { settled = true; result = v; },
    (e) => { settled = true; error = e; },
  );
  const tick = Number.isFinite(checkInMs) && checkInMs > 0 ? checkInMs : 1000;
  while (!settled) {
    await Promise.race([p, sleep(tick)]);
    if (settled) break;
    const n = now();
    const trail = getTrail();
    if (trail && Number.isFinite(trail.mtime)) lastProgress = trail.mtime;
    const idle = n - lastProgress;
    const verdict = verdictFromTrail({
      trail, idle, demanded, checkInMs, silentKillMs, deadIdleMs,
    });
    onCheckin({ verdict, trail, idle, elapsed: n - started, demanded });
    if (verdict === 'dead') {
      const dead = deadError(idle);
      if (strictAbortJoin) {
        controller.abort(dead);
        await p;
        if (error?.receipt) dead.receipt = error.receipt;
        if (error) dead.cause = error;
      }
      throw dead;
    }
    if (verdict === 'lookin' || verdict === 'lookin-silent') {
      if (verdict === 'lookin-silent') demanded = true;
      const action = onLookin
        ? await onLookin({ trail, idle, elapsed: n - started, silent: verdict === 'lookin-silent', nudge: composeLookinNudge({ northStar, task, trail, silent: verdict === 'lookin-silent' }) })
        : (verdict === 'lookin' ? 'keep' : 'keep');
      if (action === 'cut') {
        const err = new Error(`swarm seat CUT: off the critical path (${trail?.doing || 'unspecified'}) — RC-6`);
        err.lookin_verdict = 'lookin-cut';
        throw err;
      }
    }
  }
  if (error) throw error;
  return result;
}

/**
 * Supervise a seat. `run` may be `(ctx?: { attempt, nudge }) => Promise`.
 * A silent seat is looked into, then killed and respawned once with the
 * look-in nudge. A second silence is fatal.
 */
export async function superviseSeat({
  run,
  getTrail = () => null,
  checkInMs = DEFAULT_CHECKIN_MS,
  silentKillMs = DEFAULT_SILENT_KILL_MS,
  deadIdleMs = DEFAULT_DEAD_IDLE_MS,
  maxRespawn = DEFAULT_MAX_RESPAWN,
  now = Date.now,
  sleep = defaultSleep,
  onCheckin = () => {},
  onLookin = null,
  northStar = null,
  task = null,
  strictAbortJoin = false,
} = {}) {
  if (typeof run !== 'function') throw new TypeError('superviseSeat requires run()');
  const cap = Number.isInteger(maxRespawn) && maxRespawn >= 0 ? maxRespawn : DEFAULT_MAX_RESPAWN;
  let lastErr = null;
  for (let attempt = 0; attempt <= cap; attempt++) {
    const nudge = attempt === 0 ? null : composeLookinNudge({
      northStar, task, trail: getTrail({ attempt: attempt - 1 }), silent: true,
    });
    const controller = strictAbortJoin ? new AbortController() : null;
    const getAttemptTrail = () => getTrail({ attempt, nudge });
    try {
      return await superviseOnce({
        run: () => run(strictAbortJoin
          ? { attempt, nudge, signal: controller.signal }
          : { attempt, nudge }),
        getTrail: getAttemptTrail, checkInMs, silentKillMs, deadIdleMs,
        now, sleep, onCheckin, onLookin, northStar, task,
        strictAbortJoin, controller,
      });
    } catch (err) {
      lastErr = err;
      if (err?.lookin_verdict !== 'dead' || attempt >= cap) throw err;
      onCheckin({ verdict: 'respawn', attempt: attempt + 1, err: err.message });
    }
  }
  throw lastErr;
}

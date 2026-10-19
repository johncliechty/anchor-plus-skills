// engine/panel/apply-state.mjs — Wave 6: the persisted Apply state machine.
//
//   pending ──begin──► applying ──settle──► done      (sealed forever)
//        ▲                  │                └──────► partial (retryable: the
//        └───refusal────────┘                          Trash move-set resumes)
//
// WHAT PERSISTS AND WHAT DOES NOT. The STATE persists; the TOKEN never does.
// That split is the whole design:
//
//   • the STATE must survive a crash, because "did the Apply that was in flight
//     when the process died actually land?" is a question only durable state
//     plus git can answer, and answering it wrong means either a lost change or
//     a double commit;
//   • the TOKEN must NOT survive anything, because a capability on disk is a
//     capability for every local process. Server restart therefore voids every
//     outstanding token STRUCTURALLY — there is nothing to reload.
//
// REPLAY IDEMPOTENCE. A duplicated tab pressing Apply twice is the ordinary
// case, not the adversarial one. The second POST does not re-execute: it reads
// the recorded result of the first and returns it verbatim, flagged `replay`.
// The recorded result is the ONLY thing a replay can produce — there is no code
// path from `done` back into the executor.
//
// CRASH RECOVERY. A state file stuck at `applying` means the process died mid
// Apply. The recovery is not a guess: Wave-3's executor writes its own summary
// at `<reportDir>/apply/<runId>/summary.json` as it completes, so recovery is a
// single observable fact — if that summary exists the Apply landed and this
// state machine adopts its result; if it does not, nothing was committed (the
// executor commits before it does anything irreversible) and the state returns
// to `pending` for an honest retry.

import fsp from 'node:fs/promises';
import path from 'node:path';

export const APPLY_STATE = Object.freeze({
  PENDING: 'pending',
  APPLYING: 'applying',
  DONE: 'done',
  PARTIAL: 'partial',
});

export const APPLY_STATE_REFUSAL = Object.freeze({
  IN_FLIGHT: 'APPLY_IN_FLIGHT',
  STALE_RUN: 'STALE_RUN_ID',
  SUPERSEDED: 'RUN_SUPERSEDED',
});

export const PANEL_DIRNAME = 'panel';
export const APPLY_STATE_FILENAME = 'apply-state.json';
export const APPLY_STATE_VERSION = 1;

/**
 * A runId derives from an ISO timestamp; a caller that supplies its own may hand
 * us one still carrying ':' (illegal in a Windows path segment — it means an NTFS
 * alternate data stream). The state directory is derived from the runId, so the
 * runId is encoded to a filesystem-safe segment before it ever becomes a path.
 * The engine's own generator already strips ':' and '.', so this is the identity
 * on every runId it mints and only bites a caller-supplied one.
 */
export function safeRunSegment(runId) {
  return String(runId).replace(/[^A-Za-z0-9._-]/g, '_');
}

export function applyStatePathFor(reportDir, runId) {
  return path.join(reportDir, PANEL_DIRNAME, safeRunSegment(runId), APPLY_STATE_FILENAME);
}

/** Wave-3's executor summary — the one observable fact crash recovery needs. */
export function executorSummaryPathFor(reportDir, runId) {
  return path.join(reportDir, 'apply', safeRunSegment(runId), 'summary.json');
}

async function readJsonOrNull(fs, file) {
  try { return JSON.parse(String(await fs.readFile(file, 'utf8'))); } catch { return null; }
}

async function writeState(fs, file, state) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  await fs.writeFile(tmp, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  await fs.rename(tmp, file);
  return state;
}

/** The current state, defaulting to a fresh `pending`. Never throws. */
export async function readApplyState({ reportDir, runId, fs = fsp } = {}) {
  const stored = await readJsonOrNull(fs, applyStatePathFor(reportDir, runId));
  if (!stored || stored.version !== APPLY_STATE_VERSION || stored.runId !== String(runId)) {
    return {
      version: APPLY_STATE_VERSION,
      runId: String(runId),
      state: APPLY_STATE.PENDING,
      attempts: 0,
      startedAt: null,
      settledAt: null,
      result: null,
      lastRefusal: null,
    };
  }
  return stored;
}

/**
 * Take the Apply slot for this run, or explain why it cannot be taken.
 *
 * @returns {Promise<{ok: boolean, replay?: boolean, code?: string, state: object,
 *                    result?: object|null, message?: string}>}
 */
export async function beginApply({ reportDir, runId, fs = fsp, now = () => new Date(), pid = process.pid } = {}) {
  const file = applyStatePathFor(reportDir, runId);
  let state = await readApplyState({ reportDir, runId, fs });

  // ---- already done: REPLAY, never re-execute ----------------------------
  if (state.state === APPLY_STATE.DONE) {
    return {
      ok: false,
      replay: true,
      state,
      result: state.result,
      message: `run ${runId} has already been applied — this is the recorded result of that Apply, replayed. One Apply per run: there is no code path from here back into the executor.`,
    };
  }

  // ---- stuck at `applying`: recover from one observable fact -------------
  if (state.state === APPLY_STATE.APPLYING) {
    const summary = await readJsonOrNull(fs, executorSummaryPathFor(reportDir, runId));
    if (!summary) {
      return {
        ok: false,
        code: APPLY_STATE_REFUSAL.IN_FLIGHT,
        state,
        message: `an Apply for run ${runId} is already in flight (started ${state.startedAt}, pid ${state.pid ?? 'unknown'}) — a second one is refused rather than raced`,
      };
    }
    // It landed (or terminated) while we were not looking. Adopt its verdict
    // rather than inventing one.
    state = await settleApply({ reportDir, runId, result: summary, fs, now, recovered: true });
    if (state.state === APPLY_STATE.DONE) {
      return {
        ok: false,
        replay: true,
        state,
        result: state.result,
        message: `run ${runId}'s Apply was in flight when the panel last stopped; the executor's own summary shows it completed, so this is that recorded result rather than a second Apply`,
      };
    }
    // PARTIAL recovers into a retryable state and falls through to the retry.
  }

  const next = {
    ...state,
    version: APPLY_STATE_VERSION,
    runId: String(runId),
    state: APPLY_STATE.APPLYING,
    attempts: Number(state.attempts || 0) + 1,
    startedAt: now().toISOString(),
    settledAt: null,
    pid,
    lastRefusal: null,
  };
  await writeState(fs, file, next);
  return { ok: true, state: next, retryOfPartial: state.state === APPLY_STATE.PARTIAL };
}

/**
 * Record the outcome. `applied` seals the run forever; `partial` stays
 * retryable (an interrupted Trash move-set is MEANT to be resumed, and Wave-4's
 * journal makes the retry idempotent rather than duplicative); anything else —
 * a refusal, a no-op — returns the slot to `pending`, because nothing happened
 * and refusing to let the user try again would be punishing them for the tool's
 * own preconditions.
 */
export async function settleApply({ reportDir, runId, result, fs = fsp, now = () => new Date(), recovered = false } = {}) {
  const file = applyStatePathFor(reportDir, runId);
  const prior = await readApplyState({ reportDir, runId, fs });
  const status = result && result.status ? String(result.status) : 'refused';

  let state;
  if (status === 'applied') state = APPLY_STATE.DONE;
  else if (status === 'partial') state = APPLY_STATE.PARTIAL;
  else state = APPLY_STATE.PENDING;

  const next = {
    ...prior,
    version: APPLY_STATE_VERSION,
    runId: String(runId),
    state,
    settledAt: now().toISOString(),
    recovered: Boolean(recovered) || Boolean(prior.recovered),
    // The recorded result IS what a replay returns. Stored for `done` and
    // `partial`; a refusal is recorded separately so it cannot masquerade as an
    // Apply that happened.
    result: state === APPLY_STATE.PENDING ? prior.result : sanitiseResult(result),
    lastRefusal: state === APPLY_STATE.PENDING
      ? { at: now().toISOString(), status, code: (result && result.code) || null, message: (result && result.message) || null }
      : null,
  };
  await writeState(fs, file, next);
  return next;
}

/** An Apply that THREW. Nothing is sealed: the executor is all-or-nothing. */
export async function failApply({ reportDir, runId, error, fs = fsp, now = () => new Date() } = {}) {
  const file = applyStatePathFor(reportDir, runId);
  const prior = await readApplyState({ reportDir, runId, fs });
  const next = {
    ...prior,
    version: APPLY_STATE_VERSION,
    runId: String(runId),
    state: APPLY_STATE.PENDING,
    settledAt: now().toISOString(),
    lastRefusal: {
      at: now().toISOString(),
      status: 'error',
      code: 'APPLY_THREW',
      message: error && error.message ? error.message : String(error),
    },
  };
  await writeState(fs, file, next);
  return next;
}

/**
 * Strip anything that must never reach disk before the result is persisted.
 *
 * There is no token in an Apply result today; this exists so that a future
 * field carrying one cannot be persisted by accident, and so the assertion
 * "no capability material is written by the state machine" has a single place
 * to be true.
 */
function sanitiseResult(result) {
  if (!result || typeof result !== 'object') return result ?? null;
  const out = {};
  for (const [k, v] of Object.entries(result)) {
    if (/token|secret|credential|nonce/i.test(k)) continue;
    if (typeof v === 'function') continue;
    out[k] = v;
  }
  return out;
}

export default {
  readApplyState, beginApply, settleApply, failApply,
  applyStatePathFor, executorSummaryPathFor,
  APPLY_STATE, APPLY_STATE_REFUSAL, APPLY_STATE_VERSION,
};

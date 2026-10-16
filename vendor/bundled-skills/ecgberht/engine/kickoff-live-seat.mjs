/**
 * Gate 5 / Wave 6 - the ONE authorized production-seat recording, as law.
 *
 * WHAT THIS MODULE OWNS. John authorized exactly one live Codex-seat recording for this
 * effort (2026-09-01; no further HALT-for-go). This module is the law around that single
 * spend, kept OUT of the transport (scripts/seat-call.mjs owns the wire) and OUT of the
 * test (which merely drives it):
 *
 *   THE FAILURE ROWS. A live seat fails three ways and each is a NAMED row the wave
 *   HALTs on: seat-unavailable (it could not be reached), seat-slow-or-killed (it ran
 *   past its named bound), seat-garbage-reply (it answered, but no usable kickoff bundle
 *   came back). classifyLiveSeatFailure maps a real converse() failure onto exactly one
 *   row; anything it cannot place is reported as unknown - never guessed into a row.
 *
 *   ONE RETRY, BOUNDED COST. recordKickoffLiveSession runs an injected attempt at most
 *   LIVE_SEAT_MAX_ATTEMPTS (= 2) times - one retry, no more - under a total wall-clock
 *   bound; when the bound is exceeded the refusal IS the slow-or-killed row. The numeric
 *   bounds are named constants so a test can assert them rather than trust prose.
 *
 *   NEVER A FABRICATED TAPE. On failure the session result says halt, names its row, and
 *   carries fabricated_tape: false; there is no code path here that writes reply bytes.
 *   The tape is written only by the real transport's recording hook during a real call.
 *
 *   HERMETIC REPLAY THEREAFTER. verifyKickoffTape is the replay side's honesty gate: a
 *   missing tape is the EMPTY row (not yet recorded - a separate fact from a broken
 *   one), an unreadable file is the backing-store row, a malformed or empty recording is
 *   the invalid row, and a tape past its named byte bound is refused rather than read
 *   unbounded. The prompt-hash drift guard itself lives with the transport
 *   (scripts/seat-call.mjs replaySeatCall) and is not re-implemented here.
 *
 * Engine law: stdlib only, no child_process - the attempt arrives INJECTED, exactly as
 * converse() takes its seatCall. Source is ASCII on purpose (the repo's mojibake sweep).
 */

import crypto from 'node:crypto';
import fs from 'node:fs';

import { CONVERSE_CODE } from './steward-conversation.mjs';
import { KICKOFF_TALK_CODE } from './kickoff-conversation.mjs';

/** Where the ONE authorized recording lives, repo-relative (the gate's replay fixture). */
export const KICKOFF_LIVE_TAPE_REL = 'test/fixtures/kickoff-codex-session.json';

// -- the frozen session facts ---------------------------------------------------------
// The recorder and every later replay MUST agree on these or the prompt-hash drift
// guard fails the gate (the intended behaviour - but shared constants make the drift
// impossible rather than loud, exactly as test/helpers/steward-fixture.mjs does for
// the WH4 lane). The clock is frozen because conversation-log dates ride the prompt.

/** John's opening for the recorded effort - a representative document effort, rich. */
export const LIVE_SEAT_OPENING =
  'I want to put together the one-page decision memo on whether the steward chamber '
  + 'runs the spring course planning cycle. It should say what we tried this summer, '
  + 'what it cost in hours, the two frictions that still bite, and my recommendation '
  + 'stated plainly at the top. Done means a reader decides in one read without asking '
  + 'me anything. First move is drafting the page from the run notes I already keep.';

/** The one follow-up a still-gathering seat gets before the thin bound forces a bundle. */
export const LIVE_SEAT_FOLLOWUP =
  'The memo itself is the whole deliverable - one page, drafted from the run notes I '
  + 'already keep, with the recommendation plainly at the top.';

/** Frozen clock for recording AND replay - a wall-clock tape rots at midnight. */
export const LIVE_SEAT_AS_OF = '2026-09-01T12:00:00.000Z';

/** Fixed source-turn ids: they ride the record hash, so replay must reuse them. */
export const LIVE_SEAT_TURN_IDS = Object.freeze(['live-t1', 'live-t2']);

/** The production seat: the Codex/ChatGPT subscription CLI family, asserted by the host. */
export const LIVE_SEAT_PRODUCTION_SEATS = Object.freeze({
  ok: true,
  coding_family: 'chatgpt',
  coding_driver: 'chatgpt-cli',
});

// -- the named bounds (boundedness law: a bound without a number cannot be tested) ----

/** Attempts, total. 2 = the first try plus ONE retry - the contract's letter. */
export const LIVE_SEAT_MAX_ATTEMPTS = 2;

/** Conversational turns one attempt may drive (opening, then at most one follow-up). */
export const LIVE_SEAT_MAX_TURNS_PER_ATTEMPT = 2;

/** Hard seat-call ceiling: attempts x turns x (talk + plan tiers). The cost bound. */
export const LIVE_SEAT_MAX_SEAT_CALLS = 8;

/** Wall-clock bound for ONE seat call. Above the transport default: the frontier
 * planning tier runs at ultra effort and a real call can pass three minutes without
 * being dead (journal 0097 measured the pair at ~3 minutes). Still a hard kill. */
export const LIVE_SEAT_CALL_TIMEOUT_MS = 300_000;

/** Wall-clock bound for the WHOLE recording session, both attempts included. */
export const LIVE_SEAT_MAX_TOTAL_MS = 1_200_000;

/** A committed tape larger than this is refused rather than read unbounded. */
export const LIVE_TAPE_MAX_BYTES = 2_000_000;

// -- the rows -------------------------------------------------------------------------

/** The three contract rows, plus the replay-side and unknown rows. */
export const KICKOFF_LIVE_CODE = Object.freeze({
  UNAVAILABLE: 'KICKOFF_LIVE_SEAT_UNAVAILABLE',
  SLOW_OR_KILLED: 'KICKOFF_LIVE_SEAT_SLOW_OR_KILLED',
  GARBAGE: 'KICKOFF_LIVE_SEAT_GARBAGE_REPLY',
  TAPE_MISSING: 'KICKOFF_LIVE_TAPE_MISSING',
  TAPE_UNREADABLE: 'KICKOFF_LIVE_TAPE_UNREADABLE',
  TAPE_INVALID: 'KICKOFF_LIVE_TAPE_INVALID',
  TAPE_BOUND_EXCEEDED: 'KICKOFF_LIVE_TAPE_BOUND_EXCEEDED',
  STATE_UNKNOWN: 'KICKOFF_LIVE_STATE_UNKNOWN',
});

/** The row name each code HALTs under - what the wave's halt message must carry. */
export const KICKOFF_LIVE_ROW = Object.freeze({
  [KICKOFF_LIVE_CODE.UNAVAILABLE]: 'seat-unavailable',
  [KICKOFF_LIVE_CODE.SLOW_OR_KILLED]: 'seat-slow-or-killed',
  [KICKOFF_LIVE_CODE.GARBAGE]: 'seat-garbage-reply',
  [KICKOFF_LIVE_CODE.TAPE_MISSING]: 'tape-not-yet-recorded',
  [KICKOFF_LIVE_CODE.TAPE_UNREADABLE]: 'tape-unreadable',
  [KICKOFF_LIVE_CODE.TAPE_INVALID]: 'tape-invalid',
  [KICKOFF_LIVE_CODE.TAPE_BOUND_EXCEEDED]: 'tape-bound-exceeded',
  [KICKOFF_LIVE_CODE.STATE_UNKNOWN]: 'unknown',
});

/** User-visible text per code. `<error>` is filled from the failure's error field. */
export const KICKOFF_LIVE_TEXT = Object.freeze({
  [KICKOFF_LIVE_CODE.UNAVAILABLE]:
    'The production seat could not be reached (<error>) - the wave HALTs on the seat-unavailable row; no tape is fabricated.',
  [KICKOFF_LIVE_CODE.SLOW_OR_KILLED]:
    'The production seat ran past its named bound or was killed (<error>) - the wave HALTs on the seat-slow-or-killed row; no tape is fabricated.',
  [KICKOFF_LIVE_CODE.GARBAGE]:
    'The production seat answered but no usable kickoff bundle came back (<error>) - the wave HALTs on the seat-garbage-reply row; no tape is fabricated.',
  [KICKOFF_LIVE_CODE.TAPE_MISSING]:
    'No live-seat recording exists yet - the ONE authorized recording has not been captured, and nothing is fabricated in its place.',
  [KICKOFF_LIVE_CODE.TAPE_UNREADABLE]:
    'The recorded live-seat tape cannot be read (<error>) - refused rather than guessed.',
  [KICKOFF_LIVE_CODE.TAPE_INVALID]:
    'The recorded live-seat tape is not a valid recording (<error>) - refused rather than replayed.',
  [KICKOFF_LIVE_CODE.TAPE_BOUND_EXCEEDED]:
    'The recorded live-seat tape is larger than its named read bound (<error>) - refused rather than read unbounded.',
  [KICKOFF_LIVE_CODE.STATE_UNKNOWN]:
    'The live-seat outcome could not be classified (<error>) - reported as unknown, not guessed into a row.',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function kickoffLiveSeatFailure(code, extra = {}) {
  const known = Object.hasOwn(KICKOFF_LIVE_TEXT, code);
  const resolved = known ? code : KICKOFF_LIVE_CODE.STATE_UNKNOWN;
  let text = KICKOFF_LIVE_TEXT[resolved];
  const error = extra.error ?? String(resolved).toLowerCase();
  if (text.includes('<error>')) text = text.replace(/<error>/g, String(error));
  return {
    ok: false,
    code: resolved,
    status_code: resolved,
    row: KICKOFF_LIVE_ROW[resolved],
    error,
    text,
    user_text: text,
    fabricated_tape: false,
    ...extra,
  };
}

/**
 * Machine-readable failure-state table for the live-recording and replay surfaces.
 * `unknown` and `empty-but-valid` (a tape not yet recorded) are SEPARATE rows; every
 * row is speakable by this module's own functions.
 *
 * @returns {ReadonlyArray<{state: string, surface: string, row: string, status_code: string, user_text: string}>}
 */
export function kickoffLiveSeatFailureTable() {
  const entry = (state, surface, code) => Object.freeze({
    state,
    surface,
    row: KICKOFF_LIVE_ROW[code],
    status_code: code,
    user_text: KICKOFF_LIVE_TEXT[code],
  });
  return Object.freeze([
    entry('dependency-missing / seat-unavailable', 'live-recording', KICKOFF_LIVE_CODE.UNAVAILABLE),
    entry('dependency-slow-or-killed', 'live-recording', KICKOFF_LIVE_CODE.SLOW_OR_KILLED),
    entry('dependency-returns-garbage', 'live-recording', KICKOFF_LIVE_CODE.GARBAGE),
    entry('backing-store-unreadable', 'replay', KICKOFF_LIVE_CODE.TAPE_UNREADABLE),
    entry('tape-invalid', 'replay', KICKOFF_LIVE_CODE.TAPE_INVALID),
    entry('bound-exceeded', 'replay', KICKOFF_LIVE_CODE.TAPE_BOUND_EXCEEDED),
    entry('empty-but-valid / not-yet-recorded', 'replay', KICKOFF_LIVE_CODE.TAPE_MISSING),
    entry('unknown', 'live-recording', KICKOFF_LIVE_CODE.STATE_UNKNOWN),
  ]);
}

// -- classification -------------------------------------------------------------------

const SLOW_SIGNATURE = /timeout|timed.?out|killed|too.?slow/i;
const GARBAGE_REASONS = /^(no_reply|seat_no_reply|codex_no_reply|gemini_no_reply|wrapper_no_result|empty_stdout)$/;

/**
 * Place ONE failed conversational turn on exactly one row. The mapping is total: a
 * result this function cannot place lands on the unknown row by name, never on a
 * guessed one.
 *
 * @param {object|null} turn a failed converse() result (ok !== true)
 * @returns {{row: string, code: string}}
 */
export function classifyLiveSeatFailure(turn) {
  if (!turn || typeof turn !== 'object') {
    return { row: KICKOFF_LIVE_ROW[KICKOFF_LIVE_CODE.STATE_UNKNOWN], code: KICKOFF_LIVE_CODE.STATE_UNKNOWN };
  }
  const code = String(turn.code ?? '');
  const reason = String(turn.reason ?? '');
  const signature = `${reason} ${String(turn.error ?? '')} ${String(turn.detail ?? '')}`;

  let resolved = KICKOFF_LIVE_CODE.STATE_UNKNOWN;
  if (code === CONVERSE_CODE.SEAT_UNREACHABLE) {
    if (GARBAGE_REASONS.test(reason)) resolved = KICKOFF_LIVE_CODE.GARBAGE;
    else if (SLOW_SIGNATURE.test(signature)) resolved = KICKOFF_LIVE_CODE.SLOW_OR_KILLED;
    else resolved = KICKOFF_LIVE_CODE.UNAVAILABLE;
  } else if (code === CONVERSE_CODE.SEAT_UNSAFE) {
    resolved = KICKOFF_LIVE_CODE.UNAVAILABLE;
  } else if (
    code === CONVERSE_CODE.REPLY_UNPARSEABLE
    || code === CONVERSE_CODE.REPLY_EMPTY
    || code === CONVERSE_CODE.PROPOSAL_INVALID
    || code === CONVERSE_CODE.ORANGES_GENERIC
    || code === KICKOFF_TALK_CODE.AMBIGUOUS
  ) {
    // The seat ANSWERED - the wire worked - but what came back yields no usable
    // kickoff bundle. That is the garbage-reply row, by the contract's own words.
    resolved = KICKOFF_LIVE_CODE.GARBAGE;
  }
  return { row: KICKOFF_LIVE_ROW[resolved], code: resolved };
}

// -- the session ----------------------------------------------------------------------

/**
 * Run the ONE authorized recording session: an injected attempt, at most one retry,
 * under the total wall-clock bound. Pure orchestration - this function performs no I/O
 * and writes no tape; the injected attempt owns the transport (and its recording hook).
 *
 * @param {{
 *   runAttempt: (attempt: number) => Promise<{ok: boolean, turn?: object|null}>,
 *   attempts?: number,
 *   maxTotalMs?: number,
 *   now?: () => number,
 * }} opts
 * @returns {Promise<object>} on success {ok: true, attempt, retried, attempts, result};
 *   on failure a kickoffLiveSeatFailure carrying {halt: true, attempts} - the wave
 *   HALTs naming result.row, and no tape exists.
 */
export async function recordKickoffLiveSession(opts = {}) {
  if (typeof opts.runAttempt !== 'function') {
    return {
      ...kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.STATE_UNKNOWN, { error: 'no_run_attempt_injected' }),
      halt: true,
      attempts: [],
    };
  }
  const maxAttempts = Number.isInteger(opts.attempts) && opts.attempts >= 1
    ? Math.min(opts.attempts, LIVE_SEAT_MAX_ATTEMPTS)
    : LIVE_SEAT_MAX_ATTEMPTS;
  const maxTotalMs = Number(opts.maxTotalMs) > 0 ? Number(opts.maxTotalMs) : LIVE_SEAT_MAX_TOTAL_MS;
  const now = typeof opts.now === 'function' ? opts.now : Date.now;

  const started = now();
  const tried = [];
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const elapsed = now() - started;
    if (elapsed > maxTotalMs) {
      // The refusal path for the named wall-clock bound IS the slow-or-killed row.
      return {
        ...kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.SLOW_OR_KILLED, {
          error: `recording_wall_clock_bound_exceeded:${elapsed}ms>${maxTotalMs}ms`,
        }),
        halt: true,
        bound_ms: maxTotalMs,
        attempts: tried,
        retried: tried.length > 1,
      };
    }
    let run;
    try {
      run = await opts.runAttempt(attempt);
    } catch (e) {
      run = { ok: false, turn: null, error: String(e?.message ?? e) };
    }
    if (run && run.ok === true) {
      return { ok: true, attempt, retried: attempt > 1, attempts: tried, result: run };
    }
    const placed = classifyLiveSeatFailure(run?.turn ?? null);
    tried.push({
      attempt,
      row: placed.row,
      code: placed.code,
      turn_code: run?.turn?.code ?? null,
      reason: run?.turn?.reason ?? null,
      error: run?.turn?.error ?? run?.error ?? null,
    });
  }
  const last = tried[tried.length - 1];
  return {
    ...kickoffLiveSeatFailure(last.code, { error: last.error ?? last.reason ?? 'live_attempts_exhausted' }),
    halt: true,
    attempts: tried,
    retried: tried.length > 1,
  };
}

// -- the tape's honesty gate ----------------------------------------------------------

const HEX64 = /^[a-f0-9]{64}$/;

/**
 * Verify a recorded tape before replaying or citing it. Missing, unreadable, invalid,
 * empty, and over-bound are SEPARATE named rows; a passing tape yields the facts the
 * completion journal cites (entry count, families, whole-file hash).
 *
 * @param {string} file absolute or repo-relative tape path
 * @param {{maxBytes?: number}} [opts]
 */
export function verifyKickoffTape(file, opts = {}) {
  const maxBytes = Number(opts.maxBytes) > 0 ? Number(opts.maxBytes) : LIVE_TAPE_MAX_BYTES;
  let stat;
  try {
    stat = fs.statSync(file);
  } catch {
    return kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.TAPE_MISSING, { error: 'tape_absent', file });
  }
  if (!stat.isFile()) {
    return kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.TAPE_UNREADABLE, { error: 'tape_not_a_file', file });
  }
  if (stat.size > maxBytes) {
    return kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.TAPE_BOUND_EXCEEDED, {
      error: `tape_bytes_over_bound:${stat.size}>${maxBytes}`,
      file,
    });
  }
  let bytes;
  try {
    bytes = fs.readFileSync(file, 'utf8');
  } catch (e) {
    return kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.TAPE_UNREADABLE, {
      error: String(e?.message ?? e),
      file,
    });
  }
  let raw;
  try {
    raw = JSON.parse(bytes);
  } catch {
    return kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.TAPE_INVALID, { error: 'tape_not_json', file });
  }
  if (!Array.isArray(raw)) {
    return kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.TAPE_INVALID, { error: 'tape_not_an_array', file });
  }
  if (raw.length === 0) {
    // An empty array is NOT "not yet recorded" - it is a recording that captured
    // nothing, which is exactly the shape a fabricated tape would take. Refused.
    return kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.TAPE_INVALID, { error: 'tape_empty', file });
  }
  const families = new Set();
  for (let i = 0; i < raw.length; i += 1) {
    const entry = raw[i];
    const replyOk = entry && typeof entry === 'object'
      && typeof entry.reply_text === 'string' && entry.reply_text.trim().length > 0;
    const hashOk = replyOk && HEX64.test(String(entry.prompt_sha256 ?? ''));
    const familyOk = replyOk && typeof entry.seat_family === 'string' && entry.seat_family.trim().length > 0;
    if (!replyOk || !hashOk || !familyOk) {
      return kickoffLiveSeatFailure(KICKOFF_LIVE_CODE.TAPE_INVALID, {
        error: `tape_entry_invalid:${i}`,
        file,
      });
    }
    families.add(entry.seat_family.trim().toLowerCase());
  }
  return {
    ok: true,
    file,
    entry_count: raw.length,
    families: [...families].sort(),
    prompt_hashes: raw.map((entry) => entry.prompt_sha256),
    tape_sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    bytes: stat.size,
  };
}

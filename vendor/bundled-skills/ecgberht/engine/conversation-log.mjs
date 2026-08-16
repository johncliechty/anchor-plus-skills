/**
 * THE PROJECT CONVERSATION LOG — durable, and deliberately NOT authoritative.
 *
 * WHY THIS EXISTS, AND WHAT IT CHANGES (John's decision, 2026-08-05).
 *
 * E5 said: chat is NEVER persisted; Strip receipts + roadmap events + the Face are the
 * sole ledger; no second memory. That law was written to prevent ONE specific failure:
 * two sources of truth for project state that drift apart, with no rule for which wins.
 *
 * John asked for the conversation to be kept, per project, so the steward can look back
 * at "the evolution ... how the scaffolding and plans and executions got to where they
 * are". The append-only roadmap already records WHAT the scaffolding was at each turn
 * (every re-proposal is its own scaffold_proposal event). What it cannot record is WHY it
 * changed — his reasoning, the steward's push-back, the question that moved a stage.
 *
 * So E5 is AMENDED, not abandoned, and the amendment is narrow:
 *
 *   the transcript is DURABLE  — you can read the whole history back
 *   the transcript is NEVER AUTHORITATIVE — project state still comes only from the
 *   Face, the roadmap and the Strip. When transcript and ledger disagree, THE LEDGER
 *   WINS, always, and the transcript can never mint a step or flip a status.
 *
 * That is enforced structurally, not by documentation:
 *   - this module exports NO function that derives state, status, or steps
 *   - the log is a SEPARATE store; the roadmap spine still refuses chat-shaped kinds,
 *     so roadmap_events stays exactly as clean as it was
 *   - `assertTranscriptNonAuthoritative` is asserted by the suite, not trusted
 *
 * Stdlib only. No host-absolute user homes in shipped strings.
 */

import fs from 'node:fs';
import path from 'node:path';

import { writeFileAtomicSync, withFileLock, LOCK_TIMEOUT_MS } from './durable-write.mjs';

export const CONVERSATION_LOG_SCHEMA = 'ecgberht-conversation-log-v0';
export const CONVERSATION_LOG_REL = path.join('.ecgberht', 'conversation-log.json');

/**
 * THE STEWARD-FEEDBACK JOURNAL (2026-08-06). John gives feedback about the
 * steward ITSELF mid-conversation ("this window is cramped", "you should have
 * shown me the roadmap"). The seat used to SAY "journaled" while having no
 * hands — a fabricated act, caught on his first real campaigns. Now the reply
 * carries a typed `journal` field and THIS writes it durably, per project, as
 * markdown a sleep cycle reads directly. "Journaled" is only ever said when
 * this ran.
 */
export const STEWARD_FEEDBACK_REL = path.join('.ecgberht', 'steward-feedback.md');

/**
 * Append steward-feedback entries. Best-effort append-only markdown.
 * @param {string} projectPath
 * @param {string[]} entries
 * @param {{ at?: string }} [opts]
 * @returns {{ ok: boolean, appended: number, path?: string, error?: string }}
 */
export function appendStewardFeedback(projectPath, entries, opts = {}) {
  const list = (Array.isArray(entries) ? entries : [])
    .map((e) => String(e ?? '').trim())
    .filter(Boolean);
  if (!list.length) return { ok: true, appended: 0 };
  const file = path.join(path.resolve(projectPath), STEWARD_FEEDBACK_REL);
  const at = opts.at ?? new Date().toISOString();
  const block = list.map((e) => `- ${at.slice(0, 10)} — ${e}`).join('\n');
  try {
    return withFileLock(
      file,
      () => {
        fs.mkdirSync(path.dirname(file), { recursive: true });
        const head = fs.existsSync(file)
          ? ''
          : '# Steward feedback journal — John\'s words about the steward itself\n\n';
        fs.appendFileSync(file, `${head}${block}\n`, 'utf8');
        return { ok: true, appended: list.length, path: file };
      },
      { timeoutMs: LOCK_TIMEOUT_MS },
    );
  } catch (e) {
    return { ok: false, appended: 0, error: String(e?.message ?? e) };
  }
}

/** Bound — a project's transcript is long-lived, not unbounded. */
export const CONVERSATION_MAX_TURNS = 5_000;

/**
 * The amended law, frozen so the canary and the tests assert an object rather than prose.
 */
export const TRANSCRIPT_POLICY = Object.freeze({
  policy: 'durable_non_authoritative',
  durable: true,
  authoritative_for_state: false,
  /** State comes ONLY from these — unchanged from E5. */
  state_surfaces: Object.freeze([
    'strip_receipts',
    'strip_instruments',
    'roadmap_events',
    'face_narrative',
  ]),
  /** The transcript may be read for recall, never for state. */
  read_for: Object.freeze(['human_recall', 'steward_context']),
  never: Object.freeze(['mint_step', 'flip_status', 'authorize_spend', 'commission']),
});

export const CONVERSATION_CODE = Object.freeze({
  UNREADABLE: 'CONVERSATION_LOG_UNREADABLE',
  BOUND_EXCEEDED: 'CONVERSATION_LOG_BOUND_EXCEEDED',
});

/**
 * @param {string} projectPath
 * @returns {string}
 */
export function conversationLogPath(projectPath) {
  return path.join(path.resolve(projectPath), CONVERSATION_LOG_REL);
}

/** Empty-but-valid log (distinct from unreadable). */
export function emptyConversationLog(project_id = null) {
  return {
    schema: CONVERSATION_LOG_SCHEMA,
    project_id,
    policy: TRANSCRIPT_POLICY.policy,
    authoritative_for_state: false,
    turns: [],
    next_seq: 1,
  };
}

/**
 * Read the log. Missing file is EMPTY-BUT-VALID; a corrupt file is UNREADABLE and says
 * so — an honest unknown is never reported as "no history".
 *
 * @param {string} projectPath
 * @param {{ limit?: number }} [opts]
 */
export function readConversationLog(projectPath, opts = {}) {
  const file = conversationLogPath(projectPath);
  if (!fs.existsSync(file)) {
    return { ok: true, exists: false, log: emptyConversationLog(), turns: [], path: file };
  }
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return {
      ok: false,
      exists: true,
      code: CONVERSATION_CODE.UNREADABLE,
      error: 'conversation-log-unreadable',
      detail: String(e?.message ?? e),
      message: 'The conversation history is unreadable — saying so rather than reporting none.',
      path: file,
    };
  }
  const turns = Array.isArray(parsed?.turns) ? parsed.turns : [];
  const limited = opts.limit ? turns.slice(-Math.max(0, opts.limit)) : turns;
  return { ok: true, exists: true, log: parsed, turns: limited, total: turns.length, path: file };
}

/**
 * Append turns. Append-only under a lock: nothing is ever rewritten, so the history of
 * how a plan got where it is cannot be quietly edited.
 *
 * @param {string} projectPath
 * @param {Array<{role: string, text: string}>} turns
 * @param {{ at?: string, project_id?: string, proposal_hash?: string|null, kind?: string }} [opts]
 */
export function appendConversationTurns(projectPath, turns, opts = {}) {
  const list = (Array.isArray(turns) ? turns : [])
    .map((t) => ({
      role: String(t?.role ?? 'john'),
      text: String(t?.text ?? '').trim(),
    }))
    .filter((t) => t.text);
  if (!list.length) return { ok: true, appended: 0, skipped: 'no_turns' };

  const root = path.resolve(projectPath);
  const file = conversationLogPath(root);
  const at = opts.at ?? new Date().toISOString();

  try {
    return withFileLock(
      file,
      () => {
        const current = readConversationLog(root);
        if (!current.ok) return current;
        const log = current.exists ? current.log : emptyConversationLog(opts.project_id ?? null);
        const existing = Array.isArray(log.turns) ? log.turns : [];

        if (existing.length + list.length > CONVERSATION_MAX_TURNS) {
          return {
            ok: false,
            code: CONVERSATION_CODE.BOUND_EXCEEDED,
            error: 'conversation-log-bound-exceeded',
            message:
              `The conversation history has reached its ${CONVERSATION_MAX_TURNS}-turn bound. `
              + 'Nothing was dropped and nothing was appended — archive it to carry on.',
            total: existing.length,
          };
        }

        let seq = Number(log.next_seq) || existing.length + 1;
        const added = list.map((t) => ({
          seq: seq++,
          role: t.role,
          text: t.text,
          at,
          // Ties a turn to the scaffolding version it produced, so the evolution of the
          // plan can be read alongside the reasoning that drove it.
          ...(opts.proposal_hash ? { proposal_hash: opts.proposal_hash } : {}),
          ...(opts.kind ? { kind: opts.kind } : {}),
        }));

        const next = {
          ...emptyConversationLog(log.project_id ?? opts.project_id ?? null),
          ...log,
          schema: CONVERSATION_LOG_SCHEMA,
          policy: TRANSCRIPT_POLICY.policy,
          authoritative_for_state: false,
          turns: [...existing, ...added],
          next_seq: seq,
        };

        fs.mkdirSync(path.dirname(file), { recursive: true });
        writeFileAtomicSync(file, `${JSON.stringify(next, null, 2)}\n`);
        return { ok: true, appended: added.length, total: next.turns.length, path: file };
      },
      { timeoutMs: opts.timeoutMs ?? LOCK_TIMEOUT_MS },
    );
  } catch (e) {
    return {
      ok: false,
      code: CONVERSATION_CODE.UNREADABLE,
      error: 'conversation-log-lock-failed',
      detail: String(e?.message ?? e),
    };
  }
}

/**
 * A compact, READ-ONLY summary of the project's conversation for the High Seat.
 *
 * Deliberately derives NOTHING about state — no status, no step, no next action. It
 * answers only "what has been talked about here, and when", which is what John asked the
 * High Seat to be able to show.
 *
 * @param {string} projectPath
 * @param {{ recent?: number }} [opts]
 */
export function summarizeConversation(projectPath, opts = {}) {
  const read = readConversationLog(projectPath);
  if (!read.ok) {
    return {
      ok: false,
      code: read.code,
      unknown: true,
      // Honest unknown ≠ "no conversation yet".
      headline: 'Conversation history unreadable',
      message: read.message,
    };
  }
  const turns = read.turns ?? [];
  if (!turns.length) {
    return {
      ok: true,
      exists: false,
      turn_count: 0,
      headline: 'No conversation yet',
      last_at: null,
      recent: [],
      proposal_versions: 0,
    };
  }

  const recentN = Math.max(1, Number(opts.recent) || 3);
  const hashes = new Set(turns.map((t) => t.proposal_hash).filter(Boolean));
  const last = turns[turns.length - 1];
  const johnTurns = turns.filter((t) => t.role === 'john').length;

  return {
    ok: true,
    exists: true,
    turn_count: turns.length,
    john_turns: johnTurns,
    steward_turns: turns.length - johnTurns,
    /** How many distinct scaffolding versions this conversation produced. */
    proposal_versions: hashes.size,
    first_at: turns[0].at ?? null,
    last_at: last.at ?? null,
    headline:
      `${turns.length} turns · ${hashes.size} scaffolding version`
      + `${hashes.size === 1 ? '' : 's'}`,
    recent: turns.slice(-recentN).map((t) => ({
      role: t.role,
      at: t.at ?? null,
      // Trimmed for a tile; the full text is always in the log.
      excerpt: t.text.length > 220 ? `${t.text.slice(0, 217)}…` : t.text,
    })),
    authoritative_for_state: false,
  };
}

/**
 * Structural proof that the transcript cannot become a second source of truth.
 *
 * Asserted by the suite rather than trusted: this module must export nothing that
 * derives project state, and the policy must still name the E5 surfaces as the ONLY
 * state surfaces. If someone later adds `stepsFromConversation()`, this fails.
 *
 * @param {object} moduleExports
 */
export function assertTranscriptNonAuthoritative(moduleExports = {}) {
  const forbidden = /^(steps?|status|roadmap|projection|state|rank|nextAction)/i;
  const offenders = Object.keys(moduleExports).filter(
    (k) => typeof moduleExports[k] === 'function' && forbidden.test(k),
  );
  return {
    ok:
      offenders.length === 0
      && TRANSCRIPT_POLICY.authoritative_for_state === false
      && TRANSCRIPT_POLICY.state_surfaces.length === 4,
    offenders,
    policy: TRANSCRIPT_POLICY,
    ledger_wins: true,
  };
}

/**
 * THE PORTFOLIO LEDGER — what the steward DID, across every project.
 *
 * WHY IT EXISTS (John, 2026-08-05). The High Seat finds projects by SCANNING for marker
 * files and reads each one's own records. That kept one source of truth per project, but
 * it left the portfolio itself with no memory: when a project folder moves or is
 * archived its history goes with it, and nothing anywhere records what the steward has
 * been doing across everything — "four conversations this week, three projects waiting
 * on you, this one hasn't moved in a month".
 *
 * WHAT IT RECORDS, AND THE LINE IT DOES NOT CROSS.
 *
 *   IT RECORDS   what the steward DID — a conversation held, a scaffolding proposed or
 *                confirmed, a commission run, a question raised. An EVENT, stamped with
 *                when and which project.
 *
 *   IT NEVER RECORDS   what a project IS — no status, no goal, no step list, no next
 *                action, no cached projection.
 *
 * That line is the whole design. A central store that caches project state will
 * eventually disagree with the project, and then there is no rule for which wins — the
 * exact failure E5 was written to prevent. Because this ledger only ever says "on this
 * date the steward did X", it cannot contradict a project: project state is still read
 * live from the Face, roadmap and Strip, every time.
 *
 * Enforced structurally by `assertRecordsNoProjectState`, asserted by the suite.
 *
 * Stdlib only. No host-absolute user homes in shipped strings (home comes from env).
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { writeFileAtomicSync, withFileLock, LOCK_TIMEOUT_MS } from './durable-write.mjs';

export const PORTFOLIO_LEDGER_SCHEMA = 'ecgberht-portfolio-ledger-v0';
export const PORTFOLIO_LEDGER_FILE = 'portfolio-ledger.json';

/** Bound — the portfolio ledger is long-lived, not unbounded. */
export const PORTFOLIO_MAX_EFFORTS = 20_000;

/**
 * The closed list of steward efforts. Closed on purpose: a new kind is a deliberate
 * decision, and nothing here may describe project STATE.
 */
export const EFFORT_KINDS = Object.freeze([
  'conversation',
  'scaffold_proposed',
  'scaffold_confirmed',
  'commission_run',
  'question_raised',
]);

/** The law, frozen so the suite asserts an object rather than prose. */
export const PORTFOLIO_POLICY = Object.freeze({
  records: 'steward_efforts',
  authoritative_for_project_state: false,
  /** Fields that would make this a state cache — forbidden on every record. */
  forbidden_fields: Object.freeze([
    'status', 'goal', 'north_star', 'steps', 'projection',
    'next_action', 'roadmap', 'state',
  ]),
  project_state_read_live_from: Object.freeze(['face', 'roadmap', 'strip']),
});

export const PORTFOLIO_CODE = Object.freeze({
  UNREADABLE: 'PORTFOLIO_LEDGER_UNREADABLE',
  BAD_KIND: 'PORTFOLIO_EFFORT_KIND_REFUSED',
  STATE_FIELD: 'PORTFOLIO_STATE_FIELD_REFUSED',
  BOUND_EXCEEDED: 'PORTFOLIO_LEDGER_BOUND_EXCEEDED',
});

/**
 * Where the ledger lives — outside any project, because it is ABOUT all of them.
 * Home resolves from env first so tests and scrubbed hosts stay isolated.
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {string}
 */
export function portfolioLedgerPath(env = process.env) {
  if (env.ECGBERHT_PORTFOLIO_LEDGER) return String(env.ECGBERHT_PORTFOLIO_LEDGER);
  const explicit = Object.prototype.hasOwnProperty.call(env, 'USERPROFILE')
    || Object.prototype.hasOwnProperty.call(env, 'HOME');
  const home = env.USERPROFILE || env.HOME || (explicit ? '' : (os.homedir?.() || ''));
  return path.join(home || '.', '.ecgberht', PORTFOLIO_LEDGER_FILE);
}

export function emptyPortfolioLedger() {
  return {
    schema: PORTFOLIO_LEDGER_SCHEMA,
    records: PORTFOLIO_POLICY.records,
    authoritative_for_project_state: false,
    efforts: [],
    next_seq: 1,
  };
}

/**
 * Read the ledger. Missing is EMPTY-BUT-VALID; corrupt is UNREADABLE and says so.
 * @param {{ env?: object, limit?: number }} [opts]
 */
export function readPortfolioLedger(opts = {}) {
  const file = portfolioLedgerPath(opts.env ?? process.env);
  if (!fs.existsSync(file)) {
    return { ok: true, exists: false, ledger: emptyPortfolioLedger(), efforts: [], path: file };
  }
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    return {
      ok: false,
      exists: true,
      code: PORTFOLIO_CODE.UNREADABLE,
      error: 'portfolio-ledger-unreadable',
      detail: String(e?.message ?? e),
      message: 'The portfolio ledger is unreadable — saying so rather than reporting no history.',
      path: file,
    };
  }
  const efforts = Array.isArray(parsed?.efforts) ? parsed.efforts : [];
  return {
    ok: true,
    exists: true,
    ledger: parsed,
    efforts: opts.limit ? efforts.slice(-Math.max(0, opts.limit)) : efforts,
    total: efforts.length,
    path: file,
  };
}

/**
 * Record one steward effort. Append-only.
 *
 * @param {{
 *   kind: string, project_path?: string, project_id?: string|null,
 *   summary?: string, at?: string, detail?: object, env?: object,
 * }} effort
 */
export function recordStewardEffort(effort = {}) {
  const kind = String(effort.kind ?? '');
  if (!EFFORT_KINDS.includes(kind)) {
    return {
      ok: false,
      code: PORTFOLIO_CODE.BAD_KIND,
      error: 'effort-kind-refused',
      message: `"${kind}" is not a steward effort. Allowed: ${EFFORT_KINDS.join(', ')}.`,
    };
  }

  // THE LINE. A record carrying project state would make this a second source of truth
  // about projects; refuse it at the door rather than letting it drift in later.
  const detail = effort.detail && typeof effort.detail === 'object' ? effort.detail : {};
  const stateField = Object.keys(detail)
    .find((k) => PORTFOLIO_POLICY.forbidden_fields.includes(k.toLowerCase()));
  if (stateField) {
    return {
      ok: false,
      code: PORTFOLIO_CODE.STATE_FIELD,
      error: 'project-state-refused',
      field: stateField,
      message:
        `The portfolio ledger records what the steward DID, never what a project IS — `
        + `"${stateField}" is project state and was refused. Read it live from the project.`,
    };
  }

  const file = portfolioLedgerPath(effort.env ?? process.env);
  const at = effort.at ?? new Date().toISOString();

  try {
    return withFileLock(
      file,
      () => {
        const current = readPortfolioLedger({ env: effort.env });
        if (!current.ok) return current;
        const ledger = current.exists ? current.ledger : emptyPortfolioLedger();
        const efforts = Array.isArray(ledger.efforts) ? ledger.efforts : [];

        if (efforts.length + 1 > PORTFOLIO_MAX_EFFORTS) {
          return {
            ok: false,
            code: PORTFOLIO_CODE.BOUND_EXCEEDED,
            error: 'portfolio-ledger-bound-exceeded',
            message:
              `The portfolio ledger has reached its ${PORTFOLIO_MAX_EFFORTS}-effort bound. `
              + 'Nothing was dropped and nothing was appended — archive it to carry on.',
          };
        }

        const seq = Number(ledger.next_seq) || efforts.length + 1;
        const record = {
          seq,
          kind,
          at,
          project_path: effort.project_path ? path.resolve(effort.project_path) : null,
          project_id: effort.project_id ?? null,
          summary: String(effort.summary ?? '').slice(0, 400) || null,
          ...(Object.keys(detail).length ? { detail } : {}),
        };

        const next = {
          ...emptyPortfolioLedger(),
          ...ledger,
          schema: PORTFOLIO_LEDGER_SCHEMA,
          authoritative_for_project_state: false,
          efforts: [...efforts, record],
          next_seq: seq + 1,
        };

        fs.mkdirSync(path.dirname(file), { recursive: true });
        writeFileAtomicSync(file, `${JSON.stringify(next, null, 2)}\n`);
        return { ok: true, recorded: record, total: next.efforts.length, path: file };
      },
      { timeoutMs: effort.timeoutMs ?? LOCK_TIMEOUT_MS },
    );
  } catch (e) {
    return {
      ok: false,
      code: PORTFOLIO_CODE.UNREADABLE,
      error: 'portfolio-ledger-lock-failed',
      detail: String(e?.message ?? e),
    };
  }
}

/**
 * Best-effort recording — the steward's own bookkeeping must never break a turn John
 * cares about. A failure to journal is reported, never thrown.
 * @param {object} effort
 */
export function noteStewardEffort(effort) {
  try {
    return recordStewardEffort(effort);
  } catch (e) {
    return { ok: false, error: 'effort-note-failed', detail: String(e?.message ?? e) };
  }
}

/**
 * The High Seat's portfolio memory: what the steward has been doing, and where it has
 * gone quiet. Derives NOTHING about any project's state.
 *
 * @param {{ env?: object, recent?: number, quiet_after_days?: number, now?: string }} [opts]
 */
export function summarizePortfolioEfforts(opts = {}) {
  const read = readPortfolioLedger({ env: opts.env });
  if (!read.ok) {
    return {
      ok: false,
      unknown: true,
      code: read.code,
      headline: 'Portfolio history unreadable',
      message: read.message,
    };
  }
  const efforts = read.efforts ?? [];
  if (!efforts.length) {
    return {
      ok: true, exists: false, effort_count: 0, headline: 'No steward activity recorded yet',
      by_project: [], recent: [], quiet: [],
    };
  }

  const now = opts.now ? new Date(opts.now) : new Date();
  const quietAfter = Number(opts.quiet_after_days) || 14;
  const byProject = new Map();

  for (const e of efforts) {
    const key = e.project_path ?? e.project_id ?? '(unattributed)';
    const entry = byProject.get(key) ?? {
      project_path: e.project_path ?? null,
      project_id: e.project_id ?? null,
      effort_count: 0,
      kinds: {},
      last_at: null,
    };
    entry.effort_count += 1;
    entry.kinds[e.kind] = (entry.kinds[e.kind] ?? 0) + 1;
    if (!entry.last_at || String(e.at) > String(entry.last_at)) entry.last_at = e.at ?? null;
    byProject.set(key, entry);
  }

  const projects = [...byProject.values()].sort((a, b) =>
    String(b.last_at ?? '').localeCompare(String(a.last_at ?? '')));

  const quiet = projects.filter((p) => {
    if (!p.last_at) return false;
    const days = (now - new Date(p.last_at)) / 86_400_000;
    return Number.isFinite(days) && days >= quietAfter;
  }).map((p) => ({
    ...p,
    days_quiet: Math.floor((now - new Date(p.last_at)) / 86_400_000),
  }));

  const recentN = Math.max(1, Number(opts.recent) || 5);
  return {
    ok: true,
    exists: true,
    effort_count: efforts.length,
    project_count: projects.length,
    headline:
      `${efforts.length} steward effort${efforts.length === 1 ? '' : 's'} across `
      + `${projects.length} project${projects.length === 1 ? '' : 's'}`,
    by_project: projects,
    quiet,
    recent: efforts.slice(-recentN).reverse().map((e) => ({
      kind: e.kind, at: e.at ?? null, project_id: e.project_id ?? null,
      project_path: e.project_path ?? null, summary: e.summary ?? null,
    })),
    // Said out loud on every read: this is activity, not project truth.
    authoritative_for_project_state: false,
  };
}

/**
 * Structural proof this ledger never becomes a project-state cache.
 *
 * Asserted by the suite, not trusted: no record may carry a state field, and the module
 * must export nothing that derives a project's status or next action.
 *
 * @param {object} moduleExports
 */
export function assertRecordsNoProjectState(moduleExports = {}) {
  const forbidden = /^(status|goal|steps?|projection|nextAction|rank|stateFor)/i;
  const offenders = Object.keys(moduleExports).filter(
    (k) => typeof moduleExports[k] === 'function' && forbidden.test(k),
  );
  const read = readPortfolioLedger({ env: moduleExports.__env });
  const leaked = [];
  for (const e of (read.ok ? read.efforts : [])) {
    for (const k of Object.keys(e.detail ?? {})) {
      if (PORTFOLIO_POLICY.forbidden_fields.includes(k.toLowerCase())) leaked.push(`${e.seq}.${k}`);
    }
  }
  return {
    ok: offenders.length === 0
      && leaked.length === 0
      && PORTFOLIO_POLICY.authoritative_for_project_state === false,
    offenders,
    leaked,
    policy: PORTFOLIO_POLICY,
  };
}

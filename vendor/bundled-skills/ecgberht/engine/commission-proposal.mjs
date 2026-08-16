/**
 * Wave 11 — Commission proposal surface (steward-handoff v3).
 *
 * Bound propose → hash-bound confirm → executor seam:
 *   - Free-floating commissions refused (named step ULID required).
 *   - Skill selection table-bound (commissionable: true only).
 *   - Seats law via resolveSeats — subscription CLIs only.
 *   - Seat-collision pure predicate refuses a live (family, driver) pair.
 *   - Confirm is hash-bound (TOCTOU), auth via injected authorize('confirm').
 *   - T-IDEM-11: double submit → one job_id, one launch, original returned.
 *   - executeCommission is the ONLY path to an executor (host-injected).
 *   - No executor + no in-session → named no-executor-host (never silent queue).
 *   - G4 + SC6 preconditions gate the surface.
 *
 * Stdlib only. No host-absolute path literals. No ANCHOR_TOKEN in the engine.
 */

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { SPELLING } from './verbs.mjs';
import {
  resolveSeats,
  isProductionSeatSafe,
  familyToSubscriptionDriver,
  normalizeFamily,
  PRODUCTION_SEAT_DRIVERS,
  SUBSCRIPTION_DRIVERS,
} from './seating.mjs';
import {
  normalizeCommissionSkill,
  buildCommission,
  COMMISSION_SKILLS,
} from './commission.mjs';
import { skillForStepType, STEP_TYPE_SKILL_MAP } from './step-type-map.mjs';
import {
  priceTokens,
  estimateTokens,
  COST_MODEL_DISCLAIMER,
} from './cost-model.mjs';
import {
  COMMISSIONABLE_SKILLS_REL,
  SC6_FEASIBILITY_REL,
  evaluateSc6Feasibility,
} from './commissionable-skills.mjs';
import {
  publishAttention,
  ATTENTION_CALL_SITES,
} from './attention.mjs';
import {
  assertG4Precondition,
  G4_HALT_NAME,
  readG4Verdict,
} from './g4-verdict.mjs';
import { authorize } from './authorize.mjs';
import {
  validateRoadmap,
  appendRoadmapEvent,
  ROADMAP_SINGLE_WRITER,
} from './roadmap.mjs';
import {
  confirmCommissionJournaled,
  upsertDossier,
  recordLaunchOnDossier,
  emptyDossier,
} from './commission-dossier.mjs';
import { appendStripInstrument } from './write-authority.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

// ── Schema / constants ─────────────────────────────────────────────────────

/** Wave 11 proposal schema (v1 adds hash + estimate + table-bound fields). */
export const COMMISSION_PROPOSAL_SCHEMA = 'ecgberht-commission-proposal-v1';
export const COMMISSION_IDEMPOTENCE_KEY = 'client_event_id';
export const COMMISSION_PRECONDITION_HALT = 'COMMISSION_PRECONDITION_HALT';
export const SC6_HALT_NAME = 'SC6_FEASIBILITY_HALT';

/** Job schema id (shared with job-lifecycle; inlined to avoid circular import). */
const JOB_SCHEMA_ID = 'ecgberht-job-v0';

/** Compose contract with Anchor's job_runner (shared constant). */
const ANCHOR_JOB_COMPOSE = Object.freeze({
  runner: 'anchor_job_runner',
  composes: true,
  reimplements_runner: false,
  in_process_foreman: false,
  in_process_shark_tank: false,
  in_process_wave_loop: false,
  orphan_reap_detection: 'out_of_process',
});

const COMMISSION_PRIMARY_UX = 'steward_proposal';

/** Depth → synthetic token budget for the deterministic cost model. */
export const DEPTH_TOKEN_BUDGET = Object.freeze({
  LITE: 8_000,
  STANDARD: 40_000,
  FULL: 120_000,
  HEAVY: 250_000,
});

// ── Failure states (plan table) ────────────────────────────────────────────

export const COMMISSION_CODE = Object.freeze({
  STEP_UNBOUND: 'COMMISSION_STEP_UNBOUND',
  SKILL_REFUSED: 'COMMISSION_SKILL_REFUSED',
  SEAT_COLLISION: 'COMMISSION_SEAT_COLLISION',
  SEAT_REFUSED: 'COMMISSION_SEAT_REFUSED',
  CONFIRM_HASH_MISMATCH: 'COMMISSION_CONFIRM_HASH_MISMATCH',
  UNCONFIRMED: 'EXEC_REFUSED_UNCONFIRMED',
  NO_EXECUTOR_HOST: 'COMMISSION_NO_EXECUTOR_HOST',
  PRECONDITION_HALT: 'COMMISSION_PRECONDITION_HALT',
  STORE_UNREADABLE: 'COMMISSION_STORE_UNREADABLE',
  NONE_YET: 'COMMISSION_NONE_YET',
  STATE_UNKNOWN: 'COMMISSION_STATE_UNKNOWN',
  AUTH_REFUSED: 'COMMISSION_AUTH_REFUSED',
  /** Launch seam (NS criterion 9 / Wave 19 auth outcome sweep / Wave 20). */
  EXEC_AUTH_REFUSED: 'EXEC_AUTH_REFUSED',
});

export const COMMISSION_TEXT = Object.freeze({
  [COMMISSION_CODE.STEP_UNBOUND]:
    'Commission must name an existing roadmap step — refused.',
  [COMMISSION_CODE.SKILL_REFUSED]:
    '<skill> is not commissionable (<excluded_reason>) — choose from the proven set.',
  [COMMISSION_CODE.SEAT_COLLISION]:
    'Seat <family/driver> is already driving a live run — refused.',
  [COMMISSION_CODE.SEAT_REFUSED]:
    'Seat does not resolve to a subscription CLI — refused by the seats law.',
  [COMMISSION_CODE.CONFIRM_HASH_MISMATCH]:
    'The proposal changed since it was shown — confirm refused; review it again.',
  [COMMISSION_CODE.UNCONFIRMED]:
    'Commission not confirmed — nothing launched, nothing spent.',
  [COMMISSION_CODE.NO_EXECUTOR_HOST]:
    'No executor is available on this host — commission confirmed but NOT launched; named, never silently queued.',
  [COMMISSION_CODE.PRECONDITION_HALT]:
    'Substrate or skill-feasibility verdict missing — commissioning is blocked, not degraded.',
  [COMMISSION_CODE.STORE_UNREADABLE]:
    'Proposal store unreadable — refused rather than guessed.',
  [COMMISSION_CODE.NONE_YET]: 'No commissions proposed yet.',
  [COMMISSION_CODE.STATE_UNKNOWN]:
    'Commission state unknown — reported as unknown.',
  [COMMISSION_CODE.AUTH_REFUSED]:
    'Confirm refused at the auth seam — nothing appended, nothing launched.',
  [COMMISSION_CODE.EXEC_AUTH_REFUSED]:
    'Launch refused — the injected authorizer said no; nothing started.',
});

/**
 * @param {string} code
 * @param {object} [extra]
 */
export function commissionFailure(code, extra = {}) {
  let text = COMMISSION_TEXT[code] ?? COMMISSION_TEXT[COMMISSION_CODE.STATE_UNKNOWN];
  if (extra.skill != null && text.includes('<skill>')) {
    text = text.replace(/<skill>/g, String(extra.skill));
  }
  if (extra.excluded_reason != null && text.includes('<excluded_reason>')) {
    text = text.replace(/<excluded_reason>/g, String(extra.excluded_reason));
  }
  if (extra.family != null || extra.driver != null) {
    const pair = `${extra.family ?? '?'}/${extra.driver ?? '?'}`;
    text = text.replace(/<family\/driver>/g, pair);
  }
  return {
    ok: false,
    error: extra.error ?? String(code).toLowerCase().replace(/_/g, '-'),
    code,
    status: code,
    status_code: code,
    text,
    message: text,
    user_text: text,
    spelling: SPELLING,
    launched: false,
    bind_appended: false,
    processes_launched: 0,
    ...extra,
  };
}

/**
 * Full failure-state table (honest unknown ≠ empty).
 * @returns {ReadonlyArray<{state: string, status_code: string, user_text: string}>}
 */
export function commissionFailureTable() {
  return Object.freeze([
    Object.freeze({
      state: 'step-not-found / free-floating',
      status_code: COMMISSION_CODE.STEP_UNBOUND,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.STEP_UNBOUND],
    }),
    Object.freeze({
      state: 'skill-not-commissionable',
      status_code: COMMISSION_CODE.SKILL_REFUSED,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.SKILL_REFUSED],
    }),
    Object.freeze({
      state: 'seat-collision',
      status_code: COMMISSION_CODE.SEAT_COLLISION,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.SEAT_COLLISION],
    }),
    Object.freeze({
      state: 'seat-not-subscription',
      status_code: COMMISSION_CODE.SEAT_REFUSED,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.SEAT_REFUSED],
    }),
    Object.freeze({
      state: 'confirm-hash-mismatch',
      status_code: COMMISSION_CODE.CONFIRM_HASH_MISMATCH,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.CONFIRM_HASH_MISMATCH],
    }),
    Object.freeze({
      state: 'unconfirmed-refused',
      status_code: COMMISSION_CODE.UNCONFIRMED,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.UNCONFIRMED],
    }),
    Object.freeze({
      state: 'no-executor-host',
      status_code: COMMISSION_CODE.NO_EXECUTOR_HOST,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.NO_EXECUTOR_HOST],
    }),
    Object.freeze({
      state: 'g4-halt / sc6-halt',
      status_code: COMMISSION_CODE.PRECONDITION_HALT,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.PRECONDITION_HALT],
    }),
    Object.freeze({
      state: 'backing-store-unreadable',
      status_code: COMMISSION_CODE.STORE_UNREADABLE,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.STORE_UNREADABLE],
    }),
    Object.freeze({
      state: 'empty-but-valid',
      status_code: COMMISSION_CODE.NONE_YET,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.NONE_YET],
    }),
    Object.freeze({
      state: 'unknown',
      status_code: COMMISSION_CODE.STATE_UNKNOWN,
      user_text: COMMISSION_TEXT[COMMISSION_CODE.STATE_UNKNOWN],
    }),
  ]);
}

// ── Precondition gate (G4 + SC6) ───────────────────────────────────────────

/**
 * Read sc6-feasibility.json from a project root.
 * @param {string} [root]
 * @returns {object|null}
 */
export function readSc6Feasibility(root = DEFAULT_ROOT) {
  const p = path.join(root, SC6_FEASIBILITY_REL);
  try {
    if (!fs.existsSync(p)) return null;
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * G4 + SC6 precondition. FAIL closed when either is not ready.
 *
 * @param {{ root?: string, fallback?: object|null, sc6?: object|null }} [opts]
 * @returns {{ ok: true, g4: object, sc6: object }
 *   | { ok: false, halt: string, code: string, message: string, g4?: object|null, sc6?: object|null }}
 */
export function assertCommissionPreconditions(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const g4 = assertG4Precondition({ root, fallback: opts.fallback ?? null });
  if (!g4.ok) {
    return {
      ok: false,
      halt: g4.halt ?? G4_HALT_NAME,
      code: COMMISSION_CODE.PRECONDITION_HALT,
      status_code: COMMISSION_CODE.PRECONDITION_HALT,
      text: COMMISSION_TEXT[COMMISSION_CODE.PRECONDITION_HALT],
      message: g4.message ?? COMMISSION_TEXT[COMMISSION_CODE.PRECONDITION_HALT],
      g4: g4.verdict ?? readG4Verdict(root),
      sc6: null,
      launched: false,
    };
  }

  const sc6 = opts.sc6 ?? readSc6Feasibility(root);
  if (!sc6 || sc6.verdict !== 'FEASIBLE') {
    const evaluated =
      sc6 && typeof sc6.commissionable_count === 'number'
        ? evaluateSc6Feasibility(sc6.commissionable_count)
        : evaluateSc6Feasibility(0);
    return {
      ok: false,
      halt: SC6_HALT_NAME,
      code: COMMISSION_CODE.PRECONDITION_HALT,
      status_code: COMMISSION_CODE.PRECONDITION_HALT,
      text: COMMISSION_TEXT[COMMISSION_CODE.PRECONDITION_HALT],
      message:
        evaluated.reason ||
        'sc6-feasibility.json not FEASIBLE — commissioning is blocked, not degraded.',
      g4: g4.verdict,
      sc6: sc6 ?? evaluated,
      launched: false,
    };
  }

  return { ok: true, g4: g4.verdict, sc6 };
}

// ── Skills table (commissionable: true only) ───────────────────────────────

/**
 * Load commissionable-skills table from root or accept an injected table.
 * @param {{ root?: string, skills_table?: object|null }} [opts]
 * @returns {{ ok: true, table: object } | { ok: false, code: string, message: string }}
 */
export function loadSkillsTable(opts = {}) {
  if (opts.skills_table && typeof opts.skills_table === 'object') {
    return { ok: true, table: opts.skills_table, source: 'inject' };
  }
  const root = opts.root ?? DEFAULT_ROOT;
  const p = path.join(root, COMMISSIONABLE_SKILLS_REL);
  try {
    if (!fs.existsSync(p)) {
      return {
        ok: false,
        code: COMMISSION_CODE.STORE_UNREADABLE,
        message: COMMISSION_TEXT[COMMISSION_CODE.STORE_UNREADABLE],
        path: COMMISSIONABLE_SKILLS_REL,
      };
    }
    const table = JSON.parse(fs.readFileSync(p, 'utf8'));
    return { ok: true, table, source: 'disk' };
  } catch (err) {
    return {
      ok: false,
      code: COMMISSION_CODE.STORE_UNREADABLE,
      message: COMMISSION_TEXT[COMMISSION_CODE.STORE_UNREADABLE],
      detail: String(err?.message ?? err),
    };
  }
}

/**
 * Resolve a skill against the commissionable table.
 * @param {string} skillName
 * @param {object} table
 * @returns {{ ok: true, skill: string, row: object }
 *   | { ok: false, code: string, skill: string, excluded_reason: string|null, message: string }}
 */
export function selectCommissionableSkill(skillName, table) {
  const skill = normalizeCommissionSkill(skillName);
  if (!skill) {
    return {
      ok: false,
      code: COMMISSION_CODE.SKILL_REFUSED,
      skill: skillName == null ? '' : String(skillName),
      excluded_reason: 'unknown_skill',
      message: `${skillName ?? '(empty)'} is not commissionable (unknown_skill) — choose from the proven set.`,
    };
  }
  const rows = Array.isArray(table?.rows) ? table.rows : [];
  const row = rows.find((r) => r && r.skill === skill) ?? null;
  if (!row) {
    return {
      ok: false,
      code: COMMISSION_CODE.SKILL_REFUSED,
      skill,
      excluded_reason: 'not_in_table',
      message: `${skill} is not commissionable (not_in_table) — choose from the proven set.`,
    };
  }
  if (row.commissionable !== true) {
    const reason = row.excluded_reason ?? 'not_commissionable';
    return {
      ok: false,
      code: COMMISSION_CODE.SKILL_REFUSED,
      skill,
      excluded_reason: reason,
      row,
      message: `${skill} is not commissionable (${reason}) — choose from the proven set.`,
    };
  }
  return { ok: true, skill, row };
}

// ── Seats law + mapping assertion ──────────────────────────────────────────

/**
 * Every `default_cli` value Anchor can emit (families + subscription drivers
 * + the bare `grok` HTTP driver name that must be refused).
 */
export const ANCHOR_DEFAULT_CLI_VALUES = Object.freeze([
  'claude',
  'gemini',
  'gemini-cli',
  'agy',
  'grok',
  'grok-cli',
]);

/**
 * Map a single default_cli value through the seats law.
 * Family names resolve via familyToSubscriptionDriver; driver names must be
 * subscription CLIs. Bare `grok` DRIVER is refused (family `grok` → grok-cli).
 *
 * @param {string} defaultCli
 * @returns {{ ok: true, default_cli: string, family: string|null, driver: string, subscription: true }
 *   | { ok: false, default_cli: string, code: string, error: string, message: string }}
 */
export function mapDefaultCliToSeat(defaultCli) {
  const raw = String(defaultCli ?? '').trim().toLowerCase();
  if (!raw) {
    return {
      ok: false,
      default_cli: raw,
      code: COMMISSION_CODE.SEAT_REFUSED,
      error: 'seat-not-subscription',
      message: COMMISSION_TEXT[COMMISSION_CODE.SEAT_REFUSED],
    };
  }

  // Bare grok DRIVER name is forbidden (raw xAI HTTP). Family grok maps below.
  if (raw === 'grok') {
    return {
      ok: false,
      default_cli: raw,
      code: COMMISSION_CODE.SEAT_REFUSED,
      error: 'bare-grok-driver-refused',
      message:
        'Seat does not resolve to a subscription CLI — refused by the seats law. (bare grok driver; use family grok → grok-cli)',
      bare_grok_driver: true,
    };
  }

  // Already a subscription driver
  if (PRODUCTION_SEAT_DRIVERS.includes(raw) || SUBSCRIPTION_DRIVERS.includes(raw)) {
    const family =
      raw === 'claude'
        ? 'claude'
        : raw === 'grok-cli'
          ? 'grok'
          : raw === 'gemini-cli' || raw === 'agy'
            ? 'gemini'
            : null;
    return {
      ok: true,
      default_cli: raw,
      family,
      driver: raw,
      subscription: true,
    };
  }

  // Family name → subscription driver
  const family = normalizeFamily(raw);
  if (family) {
    const driver = familyToSubscriptionDriver(family);
    if (driver && PRODUCTION_SEAT_DRIVERS.includes(driver)) {
      return {
        ok: true,
        default_cli: raw,
        family,
        driver,
        subscription: true,
        mapped_from_family: true,
      };
    }
  }

  return {
    ok: false,
    default_cli: raw,
    code: COMMISSION_CODE.SEAT_REFUSED,
    error: 'seat-not-subscription',
    message: COMMISSION_TEXT[COMMISSION_CODE.SEAT_REFUSED],
  };
}

/**
 * Mapping assertion: walk EVERY default_cli Anchor can emit.
 * Each resolves through resolveSeats (via family prefs) to a subscription CLI
 * seat, or is refused by name. Bare grok driver refused; family grok → grok-cli.
 *
 * @param {{ resolveSeatsFn?: Function }} [opts]
 * @returns {{ ok: boolean, results: object[], failures: object[] }}
 */
export function assertDefaultCliMapping(opts = {}) {
  const resolve = opts.resolveSeatsFn ?? resolveSeats;
  const results = [];
  const failures = [];

  for (const value of ANCHOR_DEFAULT_CLI_VALUES) {
    const mapped = mapDefaultCliToSeat(value);
    if (value === 'grok') {
      // Bare driver must refuse
      if (mapped.ok !== false || mapped.error !== 'bare-grok-driver-refused') {
        const fail = {
          default_cli: value,
          expected: 'bare-grok-driver-refused',
          got: mapped,
        };
        failures.push(fail);
        results.push({ default_cli: value, ok: false, ...fail });
        continue;
      }
      results.push({ default_cli: value, ok: true, refused: true, mapped });
      continue;
    }

    // For family/driver values, resolve seats with coding_family derived from the value
    const familyHint =
      mapped.family ??
      (value === 'claude'
        ? 'claude'
        : value === 'gemini' || value === 'gemini-cli' || value === 'agy'
          ? 'gemini'
          : value === 'grok-cli'
            ? 'grok'
            : null);

    if (!mapped.ok || !familyHint) {
      failures.push({ default_cli: value, mapped });
      results.push({ default_cli: value, ok: false, mapped });
      continue;
    }

    const seats = resolve({
      prefs: {
        coding_family: familyHint,
        review_family: familyHint === 'claude' ? 'gemini' : 'claude',
        default_cli: value,
      },
    });

    if (!seats.ok || !isProductionSeatSafe(seats)) {
      failures.push({ default_cli: value, seats, mapped });
      results.push({ default_cli: value, ok: false, seats, mapped });
      continue;
    }

    // Family grok must land on grok-cli
    if (familyHint === 'grok' && seats.coding_driver !== 'grok-cli') {
      failures.push({
        default_cli: value,
        expected_driver: 'grok-cli',
        got: seats.coding_driver,
      });
      results.push({ default_cli: value, ok: false, seats, mapped });
      continue;
    }

    results.push({
      default_cli: value,
      ok: true,
      family: familyHint,
      coding_driver: seats.coding_driver,
      review_driver: seats.review_driver,
      mapped,
      seats_ok: true,
    });
  }

  return {
    ok: failures.length === 0,
    results,
    failures,
    values: [...ANCHOR_DEFAULT_CLI_VALUES],
  };
}

// ── Seat-collision predicate (named pure function) ─────────────────────────

/**
 * Pure predicate: does the proposed (family, driver) collide with any live run seat?
 *
 * A "live run" is an entry with state in {queued, running} (or live:true) that
 * holds a seat with matching family AND driver on coding or review.
 *
 * @param {{ family?: string|null, driver?: string|null, coding_family?: string|null, coding_driver?: string|null, review_family?: string|null, review_driver?: string|null }} proposedSeat
 * @param {Array<object>|null|undefined} liveRuns
 * @returns {{ collision: boolean, family?: string, driver?: string, run?: object|null }}
 */
export function hasSeatCollision(proposedSeat, liveRuns) {
  const proposed = proposedSeat && typeof proposedSeat === 'object' ? proposedSeat : {};
  const pairs = [];
  const add = (family, driver) => {
    const f = family != null && family !== '' ? String(family) : null;
    const d = driver != null && driver !== '' ? String(driver) : null;
    if (f || d) pairs.push({ family: f, driver: d });
  };
  add(proposed.family ?? proposed.coding_family, proposed.driver ?? proposed.coding_driver);
  add(proposed.review_family, proposed.review_driver);

  const runs = Array.isArray(liveRuns) ? liveRuns : [];
  for (const run of runs) {
    if (!run || typeof run !== 'object') continue;
    const state = run.state ?? run.lifecycle_state ?? null;
    const live =
      run.live === true ||
      state === 'queued' ||
      state === 'running' ||
      state === 'live';
    if (!live) continue;

    const seat = run.seat ?? run.seats ?? run;
    const held = [
      {
        family: seat.coding_family ?? seat.family ?? null,
        driver: seat.coding_driver ?? seat.driver ?? null,
      },
      {
        family: seat.review_family ?? null,
        driver: seat.review_driver ?? null,
      },
    ];

    for (const p of pairs) {
      for (const h of held) {
        if (
          p.family &&
          h.family &&
          p.driver &&
          h.driver &&
          String(p.family) === String(h.family) &&
          String(p.driver) === String(h.driver)
        ) {
          return {
            collision: true,
            family: p.family,
            driver: p.driver,
            run,
          };
        }
      }
    }
  }
  return { collision: false, run: null };
}

// ── Hash / estimate ────────────────────────────────────────────────────────

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    const out = {};
    for (const k of Object.keys(value).sort()) {
      out[k] = sortKeys(value[k]);
    }
    return out;
  }
  return value;
}

/**
 * Content hash of the rendered proposal (skill + seat + depth + estimate).
 * @param {object} payload
 * @returns {string}
 */
export function hashCommissionProposal(payload) {
  const canonical = JSON.stringify(sortKeys(payload));
  return crypto.createHash('sha256').update(canonical).digest('hex');
}

/**
 * Hash body for TOCTOU: skill + seat + depth + estimate only.
 * @param {{ skill: string, seat: object, depth_cell: string|null, estimate: object }} body
 */
export function proposalHashBody(body) {
  return {
    skill: body.skill ?? null,
    seat: {
      coding_family: body.seat?.coding_family ?? null,
      review_family: body.seat?.review_family ?? null,
      coding_driver: body.seat?.coding_driver ?? null,
      review_driver: body.seat?.review_driver ?? null,
      default_cli: body.seat?.default_cli ?? null,
    },
    depth_cell: body.depth_cell ?? null,
    estimate: {
      cost_usd: body.estimate?.cost_usd ?? null,
      tokens: body.estimate?.tokens ?? null,
      rate_key: body.estimate?.rate_key ?? null,
    },
  };
}

/**
 * Deterministic spend estimate for a commission (tokens × rate table).
 * @param {{ skill: string, depth_cell?: string|null, step_name?: string|null }} opts
 */
export function estimateCommissionSpend(opts = {}) {
  const depth = String(opts.depth_cell ?? 'LITE').toUpperCase();
  const baseTokens =
    DEPTH_TOKEN_BUDGET[depth] ?? DEPTH_TOKEN_BUDGET.LITE;
  const label = `${opts.skill ?? 'skill'} ${opts.step_name ?? ''} ${depth}`;
  const labelTokens = estimateTokens(label);
  const tokens = baseTokens + labelTokens;
  const priced = priceTokens(tokens, { rate_key: 'coding' });
  return {
    ...priced,
    depth_cell: depth,
    synthetic: true,
    disclaimer: COST_MODEL_DISCLAIMER,
    shown_before_confirm: true,
  };
}

// ── Propose (bound to named step) ──────────────────────────────────────────

function nonEmpty(v) {
  return typeof v === 'string' && v.trim() !== '';
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Propose a commission FOR a named roadmap step (ULID / step id).
 * Renders skill + seat + depth + estimated spend BEFORE confirmation.
 * Nothing is written; nothing runs.
 *
 * @param {{
 *   roadmap: object|string,
 *   step_id?: string|null,
 *   step?: string|null,
 *   skill?: string|null,
 *   step_type?: string|null,
 *   depth_cell?: string|null,
 *   depth?: string|null,
 *   who?: string|null,
 *   seats?: object|null,
 *   prefs?: object|null,
 *   env?: object,
 *   prefsPath?: string|null,
 *   skills_table?: object|null,
 *   root?: string,
 *   live_runs?: object[],
 *   project_cwd?: string|null,
 *   commission_id?: string|null,
 *   at?: string,
 *   skip_precondition?: boolean,
 *   precondition_fallback?: object|null,
 * }} opts
 */
export function proposeBoundCommission(opts = {}) {
  if (opts.skip_precondition !== true) {
    const pre = assertCommissionPreconditions({
      root: opts.root ?? DEFAULT_ROOT,
      fallback: opts.precondition_fallback ?? null,
    });
    if (!pre.ok) {
      return commissionFailure(COMMISSION_CODE.PRECONDITION_HALT, {
        error: 'precondition-halt',
        halt: pre.halt,
        g4: pre.g4,
        sc6: pre.sc6,
        message: pre.message,
      });
    }
  }

  const step_id = opts.step_id ?? opts.step ?? null;
  if (!nonEmpty(step_id)) {
    return commissionFailure(COMMISSION_CODE.STEP_UNBOUND, {
      error: 'step-not-found',
      state: 'free-floating',
    });
  }

  const validated = validateRoadmap(opts.roadmap ?? null);
  if (!validated.ok) {
    return commissionFailure(COMMISSION_CODE.STORE_UNREADABLE, {
      error: validated.error ?? 'roadmap-unreadable',
      message: validated.message ?? COMMISSION_TEXT[COMMISSION_CODE.STORE_UNREADABLE],
      detail: validated,
    });
  }
  const step = validated.projection.find((s) => s.id === step_id) ?? null;
  if (!step) {
    return commissionFailure(COMMISSION_CODE.STEP_UNBOUND, {
      error: 'step-not-found',
      step_id,
    });
  }

  // Dispatch by locked step-type map when skill omitted or step_type given.
  let skillInput = opts.skill ?? null;
  let step_type = opts.step_type ?? step.step_type ?? step.type ?? null;
  if (!skillInput && step_type) {
    const mapped = skillForStepType(step_type);
    if (mapped.ok) skillInput = mapped.skill;
  }
  // BUILD default when name/status hints (GWT: BUILD step → Foreman)
  if (!skillInput && step_type) {
    const upper = String(step_type).toUpperCase();
    if (STEP_TYPE_SKILL_MAP[upper]) {
      skillInput = STEP_TYPE_SKILL_MAP[upper].skill;
    }
  }

  const tableLoad = loadSkillsTable({
    root: opts.root,
    skills_table: opts.skills_table,
  });
  if (!tableLoad.ok) {
    return commissionFailure(COMMISSION_CODE.STORE_UNREADABLE, {
      error: 'skills-table-unreadable',
      message: tableLoad.message,
    });
  }

  const selected = selectCommissionableSkill(skillInput, tableLoad.table);
  if (!selected.ok) {
    return commissionFailure(COMMISSION_CODE.SKILL_REFUSED, {
      error: 'skill-not-commissionable',
      skill: selected.skill,
      excluded_reason: selected.excluded_reason,
      message: selected.message,
    });
  }
  const skill = selected.skill;

  // Seats law: resolveSeats → subscription CLIs only
  // Forward exists/readFile so host-less callers (T-HOST-0) can force defaults
  // without silently reading the machine ~/.anchor store.
  const seats =
    opts.seats && typeof opts.seats === 'object'
      ? opts.seats
      : resolveSeats({
          prefs: opts.prefs ?? null,
          env: opts.env,
          prefsPath: opts.prefsPath,
          exists: opts.exists,
          readFile: opts.readFile,
        });

  if (!seats || seats.ok === false || !isProductionSeatSafe(seats)) {
    return commissionFailure(COMMISSION_CODE.SEAT_REFUSED, {
      error: 'seat-not-subscription',
      seats,
    });
  }

  // Seat-collision pure predicate
  const collision = hasSeatCollision(
    {
      coding_family: seats.coding_family,
      coding_driver: seats.coding_driver,
      review_family: seats.review_family,
      review_driver: seats.review_driver,
    },
    opts.live_runs,
  );
  if (collision.collision) {
    return commissionFailure(COMMISSION_CODE.SEAT_COLLISION, {
      error: 'seat-collision',
      family: collision.family,
      driver: collision.driver,
      live_run: collision.run,
    });
  }

  const depth_cell = opts.depth_cell ?? opts.depth ?? 'LITE';
  const estimate = estimateCommissionSpend({
    skill,
    depth_cell,
    step_name: step.name,
  });

  const seatStamp = {
    coding_family: seats.coding_family,
    review_family: seats.review_family,
    default_cli: seats.default_cli ?? null,
    coding_driver: seats.coding_driver,
    review_driver: seats.review_driver,
    cross_model: seats.cross_model,
    source: seats.prefs_source ?? seats.source ?? 'prefs_or_defaults',
    subscription_only: true,
  };

  const commission = buildCommission({
    skill,
    depth_cell,
    active_effort: step.name,
    project_cwd: opts.project_cwd ?? null,
    seats,
    prefs: opts.prefs ?? null,
    env: opts.env,
    prefsPath: opts.prefsPath,
    commission_id: opts.commission_id ?? null,
  });
  if (!commission.ok) {
    return commissionFailure(COMMISSION_CODE.SEAT_REFUSED, {
      error: commission.error ?? 'commission-build-failed',
      message: commission.message,
      commission,
    });
  }

  const hashBody = proposalHashBody({
    skill,
    seat: seatStamp,
    depth_cell,
    estimate,
  });
  const proposal_hash = hashCommissionProposal(hashBody);
  const at = opts.at ?? todayIso();

  const proposal = {
    ok: true,
    spelling: SPELLING,
    schema: COMMISSION_PROPOSAL_SCHEMA,
    kind: 'commission_proposal',
    proposal_id: `ecgberht-proposal-${step_id}-${proposal_hash.slice(0, 12)}`,
    proposal_hash,
    step_id,
    step,
    step_type: step_type ?? null,
    skill,
    depth_cell,
    seat: seatStamp,
    seats: seatStamp,
    estimate,
    rendering: {
      skill,
      seat: seatStamp.coding_driver ?? seatStamp.coding_family,
      depth: depth_cell,
      estimate_usd: estimate.cost_usd,
      estimate_tokens: estimate.tokens,
      summary: `Commission ${skill} at depth ${depth_cell} on seat ${seatStamp.coding_driver} (~$${estimate.cost_usd} synthetic) for step ${step_id}.`,
      disclaimer: COST_MODEL_DISCLAIMER,
    },
    proposed_by: opts.who ?? 'ecgberht-steward',
    at,
    commission,
    job_runner: ANCHOR_JOB_COMPOSE,
    requires_confirm: true,
    confirmed: false,
    run_started: false,
    primary_ux: COMMISSION_PRIMARY_UX,
    mode_picker_primary: false,
    single_writer: ROADMAP_SINGLE_WRITER,
    table_bound: true,
    seats_law: true,
    message: `Steward proposes commissioning ${skill} for step '${step_id}' (seat ${seatStamp.coding_driver}, depth ${depth_cell}, estimate $${estimate.cost_usd} synthetic). Confirm or refuse — nothing runs until confirm.`,
  };

  // T-ATT-CS1: commission proposed / awaiting confirm → publish at the propose verb.
  let attention_publish = null;
  const projectPath = opts.project_cwd ?? opts.project_path ?? opts.projectPath ?? null;
  if (projectPath && opts.skip_attention_publish !== true) {
    attention_publish = publishAttention(projectPath, {
      // T-ATT-CS1
      call_site: ATTENTION_CALL_SITES.PROPOSE,
      who: opts.who ?? 'ecgberht-steward',
      at,
      seed: opts.roadmap ?? opts.seed,
      skip_index: true,
      ledgerView: {
        events: opts.roadmap?.roadmap_events ?? [],
        projection: validated.projection ?? [],
        awaiting_confirm: true,
        commission_proposal: proposal,
        at,
      },
      home: opts.home,
      env: opts.env,
      project_id: opts.project_id,
      skip_brief_cache: opts.skip_brief_cache === true,
    });
  }

  return {
    ...proposal,
    attention_publish,
  };
}

// ── Executor seam (host-injected) ──────────────────────────────────────────

/** @type {((dossier: object, ctx: object) => object|Promise<object>)|null} */
let _injectedExecutor = null;

/** Wave-20 in-session executor availability (set by host / Wave 20 module). */
let _insessionExecutor = null;
let _insessionAvailable = false;

/**
 * Inject the host executor (Anchor Wave-4 is reference implementation #1).
 * Pass null to clear.
 * @param {((dossier: object, ctx: object) => object|Promise<object>)|null} fn
 */
export function setCommissionExecutor(fn) {
  _injectedExecutor = typeof fn === 'function' ? fn : null;
}

/** @returns {Function|null} */
export function getCommissionExecutor() {
  return _injectedExecutor;
}

/**
 * Register / clear the in-session executor (Wave 20 implementation #2).
 * @param {((dossier: object, ctx: object) => object|Promise<object>)|null} fn
 * @param {{ available?: boolean }} [opts]
 */
export function setInSessionExecutor(fn, opts = {}) {
  _insessionExecutor = typeof fn === 'function' ? fn : null;
  _insessionAvailable =
    opts.available !== undefined
      ? opts.available === true
      : typeof fn === 'function';
}

/** @returns {{ available: boolean, fn: Function|null }} */
export function getInSessionExecutor() {
  return {
    available: _insessionAvailable && typeof _insessionExecutor === 'function',
    fn: _insessionExecutor,
  };
}

/** Reset both executor hooks (tests). */
export function resetCommissionExecutors() {
  _injectedExecutor = null;
  _insessionExecutor = null;
  _insessionAvailable = false;
}

/**
 * THE ONLY way a confirmed commission reaches an executor.
 *
 * Resolution order:
 *   1. Host-injected executor (Anchor Wave-4)
 *   2. In-session executor when available (Wave 20)
 *   3. Named no-executor-host — confirmed-and-unlaunched, never silent queue
 *
 * @param {object} dossier  confirmed commission dossier / job payload
 * @param {object} [ctx]
 * @returns {object}
 */
export function executeCommission(dossier, ctx = {}) {
  if (!dossier || typeof dossier !== 'object') {
    return commissionFailure(COMMISSION_CODE.STATE_UNKNOWN, {
      error: 'dossier-required',
      message: 'executeCommission requires a confirmed commission dossier.',
    });
  }

  const confirmed =
    dossier.confirmed === true ||
    dossier.confirmation != null ||
    dossier.state === 'queued' ||
    dossier.state === 'confirmed' ||
    ctx.confirmed === true;

  if (!confirmed) {
    return commissionFailure(COMMISSION_CODE.UNCONFIRMED, {
      error: 'unconfirmed-refused',
    });
  }

  // Launch seam auth (NS criterion 9): authorize('launch', ctx) before any spawn.
  // Zero pid / zero process start on refusal (Wave 19 auth outcome sweep).
  const launchAuthCtx =
    ctx.authCtx ??
    ctx.auth ??
    (ctx.token != null || ctx.revoked != null || ctx.principal != null
      ? {
          token: ctx.token,
          principal: ctx.principal,
          revoked: ctx.revoked,
          expires_at: ctx.expires_at,
        }
      : null);
  if (launchAuthCtx != null) {
    const launchDecision = authorize('launch', launchAuthCtx);
    if (!launchDecision.ok) {
      return commissionFailure(COMMISSION_CODE.EXEC_AUTH_REFUSED, {
        error: launchDecision.code ?? 'auth-refused',
        message:
          launchDecision.message ??
          COMMISSION_TEXT[COMMISSION_CODE.EXEC_AUTH_REFUSED],
        auth: launchDecision,
        launched: false,
        processes_launched: 0,
        pid: null,
        proc_create_time: null,
      });
    }
  }

  // 1. Host-injected
  if (typeof _injectedExecutor === 'function') {
    try {
      const result = _injectedExecutor(dossier, ctx);
      return normalizeExecutorResult(result, { path: 'injected' });
    } catch (err) {
      return commissionFailure(COMMISSION_CODE.STATE_UNKNOWN, {
        error: 'executor-threw',
        message: String(err?.message ?? err),
        path: 'injected',
      });
    }
  }

  // 2. In-session (Wave 20)
  if (_insessionAvailable && typeof _insessionExecutor === 'function') {
    try {
      const result = _insessionExecutor(dossier, ctx);
      return normalizeExecutorResult(result, { path: 'insession' });
    } catch (err) {
      return commissionFailure(COMMISSION_CODE.STATE_UNKNOWN, {
        error: 'executor-threw',
        message: String(err?.message ?? err),
        path: 'insession',
      });
    }
  }

  // 3. Named refusal — never silent queue
  return commissionFailure(COMMISSION_CODE.NO_EXECUTOR_HOST, {
    error: 'no-executor-host',
    confirmed: true,
    launched: false,
    confirmed_and_unlaunched: true,
    silently_queued: false,
    job_id: dossier.job_id ?? null,
    commissioned_as: dossier.commissioned_as ?? null,
  });
}

function normalizeExecutorResult(result, meta = {}) {
  if (result && typeof result.then === 'function') {
    // Sync surface: executors used in tests are sync. Async callers await themselves.
    return {
      ok: true,
      async: true,
      promise: result,
      ...meta,
    };
  }
  if (!result || typeof result !== 'object') {
    return {
      ok: true,
      launched: true,
      result,
      ...meta,
    };
  }
  return {
    ok: result.ok !== false,
    launched: result.launched !== false && result.ok !== false,
    ...meta,
    ...result,
  };
}

// ── Confirm (hash-bound, auth, idempotent, executor seam) ──────────────────

/** In-memory idempotence map for pure (no project_path) confirms. */
const _idempotenceCache = new Map();

/** Clear T-IDEM-11 memory (tests). */
export function clearCommissionIdempotenceCache() {
  _idempotenceCache.clear();
}

/**
 * Confirm a bound commission proposal.
 *
 * - authorize('confirm', authCtx) via injected hook (never token in engine)
 * - proposal_hash must match recomputed content hash
 * - mints job_id / commissioned_as; appends commission_bind (spine / journal)
 * - T-IDEM-11 on client_event_id
 * - hands off via executeCommission; no executor → no-executor-host by name
 *
 * @param {{
 *   proposal: object,
 *   proposal_hash?: string,
 *   who: string|object,
 *   roadmap?: object|null,
 *   strip?: object|null,
 *   authCtx?: object|null,
 *   client_event_id?: string|null,
 *   job_id?: string|null,
 *   project_path?: string|null,
 *   project_id?: string|null,
 *   home?: string,
 *   at?: string,
 *   skip_executor?: boolean,
 *   executor_ctx?: object,
 * }} opts
 */
export function confirmBoundCommission(opts = {}) {
  const proposal = opts.proposal;
  if (
    !proposal ||
    typeof proposal !== 'object' ||
    proposal.kind !== 'commission_proposal' ||
    proposal.requires_confirm !== true
  ) {
    return commissionFailure(COMMISSION_CODE.STATE_UNKNOWN, {
      error: 'commission_confirm_requires_proposal',
      message:
        'Confirm needs a steward commission_proposal (propose/confirm path — not a mode picker).',
    });
  }

  const who = normalizeWho(opts.who);
  if (!who) {
    return commissionFailure(COMMISSION_CODE.STATE_UNKNOWN, {
      error: 'commission_confirm_requires_who',
      message: 'Commission confirm is a human decision — pass who confirmed.',
      required: ['who'],
    });
  }

  // Auth via injected authorizer — never a token check inside the engine
  const authCtx = opts.authCtx ?? { principal: who.claimed };
  const decision = authorize('confirm', authCtx);
  if (!decision.ok) {
    return commissionFailure(COMMISSION_CODE.AUTH_REFUSED, {
      error: decision.code ?? 'auth-refused',
      message: decision.message ?? COMMISSION_TEXT[COMMISSION_CODE.AUTH_REFUSED],
      auth: decision,
      bind_appended: false,
      processes_launched: 0,
    });
  }

  // Hash-bound TOCTOU
  const expectedHash = recomputeProposalHash(proposal);
  const providedHash =
    opts.proposal_hash ?? proposal.proposal_hash ?? '';
  if (!providedHash || providedHash !== expectedHash) {
    return commissionFailure(COMMISSION_CODE.CONFIRM_HASH_MISMATCH, {
      error: 'confirm-hash-mismatch',
      presented_hash: providedHash || null,
      expected_hash: expectedHash,
      processes_launched: 0,
      bind_appended: false,
    });
  }

  const client_event_id =
    opts.client_event_id ??
    `confirm-${proposal.proposal_id ?? proposal.proposal_hash ?? 'anon'}`;

  // T-IDEM-11: double submit → original job_id, no second bind/launch
  const idemKey = opts.project_path
    ? `${path.resolve(opts.project_path)}::${client_event_id}`
    : `mem::${client_event_id}`;
  if (_idempotenceCache.has(idemKey)) {
    const prior = _idempotenceCache.get(idemKey);
    return {
      ...prior,
      ok: true,
      idempotent: true,
      already_confirmed: true,
      skip_write: true,
      second_bind: false,
      second_launch: false,
      processes_launched: 0,
      message: `Commission already confirmed (client_event_id=${client_event_id}); original job_id returned, no second bind or launch.`,
    };
  }

  const at = opts.at ?? todayIso();
  const job_id =
    opts.job_id ??
    `ecgberht-job-${String(proposal.skill).toLowerCase()}-${proposal.proposal_hash.slice(0, 10)}`;
  const commissioned_as = `${proposal.skill}:${job_id}`;

  let roadmap = opts.roadmap ?? null;
  let roadmap_event = null;
  let projection = null;
  let strip = opts.strip ?? null;
  let strip_appended = false;
  let strip_instrument = null;
  let durable = false;
  let confirm_journal = false;
  let sot_written = false;

  if (opts.project_path) {
    // Wave 7 confirm journal (spine path)
    const journaled = confirmCommissionJournaled({
      project_path: opts.project_path,
      proposal: { ...proposal, requires_confirm: true },
      roadmap,
      strip,
      who: who.claimed,
      at,
      job_id,
      client_event_id,
      project_id: opts.project_id ?? null,
      home: opts.home,
    });
    if (!journaled.ok && !journaled.killed) {
      return commissionFailure(COMMISSION_CODE.STATE_UNKNOWN, {
        error: journaled.error ?? 'confirm-journal-failed',
        message: journaled.message,
        detail: journaled,
      });
    }
    roadmap = journaled.roadmap ?? roadmap;
    roadmap_event = journaled.roadmap_event ?? null;
    projection = journaled.projection ?? null;
    strip = journaled.strip ?? strip;
    strip_appended = journaled.strip_appended === true;
    strip_instrument = journaled.strip_instrument ?? null;
    durable = true;
    confirm_journal = true;
    sot_written = journaled.ok === true && journaled.killed !== true;
  } else {
    // In-memory bind for dry-run / fixtures
    const bindEvent = {
      kind: 'commission_bind',
      step_id: proposal.step_id,
      commissioned_as,
      at,
      client_event_id,
      proposal_hash: expectedHash,
    };
    if (roadmap) {
      const bound = appendRoadmapEvent(roadmap, bindEvent, { at });
      if (!bound.ok) {
        return commissionFailure(COMMISSION_CODE.STATE_UNKNOWN, {
          error: bound.error ?? 'bind-failed',
          message: bound.message,
          detail: bound,
        });
      }
      roadmap = bound.roadmap;
      roadmap_event = bound.event;
      projection = bound.projection;
    }
    if (strip) {
      strip_instrument = {
        _kind: 'instrument',
        kind: 'commission_confirm',
        as_of: at,
        job_id,
        commission_id: proposal.commission?.commission_id ?? null,
        step_id: proposal.step_id,
        skill: proposal.skill,
        depth_cell: proposal.depth_cell ?? null,
        state: 'queued',
        who: who.claimed,
        client_event_id,
        proposal_hash: expectedHash,
      };
      const appended = appendStripInstrument(strip, strip_instrument, {
        apply_to_projection: false,
      });
      if (!appended.ok) {
        return commissionFailure(COMMISSION_CODE.STATE_UNKNOWN, {
          error: 'strip-append-failed',
          message: appended.message,
        });
      }
      strip = appended.strip;
      strip_appended = true;
    }
  }

  const job = {
    schema: JOB_SCHEMA_ID,
    job_id,
    commission_id: proposal.commission?.commission_id ?? null,
    proposal_id: proposal.proposal_id ?? null,
    proposal_hash: expectedHash,
    step_id: proposal.step_id,
    skill: proposal.skill,
    depth_cell: proposal.depth_cell ?? null,
    seat: proposal.seat ?? proposal.seats ?? null,
    estimate: proposal.estimate ?? null,
    confirmed_by: who,
    confirmed: true,
    runner: ANCHOR_JOB_COMPOSE.runner,
    compose: ANCHOR_JOB_COMPOSE,
    spawn: proposal.commission ?? null,
    state: 'queued',
    commissioned_as,
    lifecycle_events: [
      {
        seq: 1,
        from: null,
        to: 'queued',
        at,
        observed: 'commission_confirm',
        who: who.claimed,
      },
    ],
  };

  // Dossier: confirmation recorded; launch identity filled by executor
  let dossier = null;
  if (opts.project_path) {
    const up = upsertDossier(opts.project_path, {
      job_id,
      commissioned_as,
      proposal: {
        proposal_id: proposal.proposal_id,
        proposal_hash: expectedHash,
        skill: proposal.skill,
        step_id: proposal.step_id,
        depth_cell: proposal.depth_cell,
        seat: proposal.seat,
        estimate: proposal.estimate,
      },
      confirmation: {
        who,
        at,
        client_event_id,
        proposal_hash: expectedHash,
        confirmed: true,
      },
    });
    if (up.ok) dossier = up.dossier;
  } else {
    dossier = {
      ...emptyDossier(job_id, commissioned_as),
      proposal: {
        proposal_id: proposal.proposal_id,
        proposal_hash: expectedHash,
        skill: proposal.skill,
        step_id: proposal.step_id,
      },
      confirmation: {
        who,
        at,
        client_event_id,
        proposal_hash: expectedHash,
        confirmed: true,
      },
    };
  }

  // Executor seam — ONLY path to launch
  let executor_result = null;
  let launched = false;
  let confirmed_and_unlaunched = false;
  let no_executor_host = false;
  let processes_launched = 0;
  let pid = null;
  let proc_create_time = null;

  if (opts.skip_executor !== true) {
    executor_result = executeCommission(
      {
        ...job,
        confirmed: true,
        confirmation: dossier?.confirmation ?? { confirmed: true, who },
        dossier,
      },
      {
        confirmed: true,
        who,
        project_path: opts.project_path ?? null,
        // Launch-seam revalidation is opt-in via executor_ctx.authCtx (or a
        // direct executeCommission call). Do NOT auto-forward confirm authCtx:
        // confirm already authorized; Wave 19 launch refusals are proven on
        // the executeCommission path (auth outcome sweep), and auto-forward
        // would re-hit authorize('launch') on every confirm+launch.
        ...(opts.executor_ctx ?? {}),
      },
    );

    if (
      executor_result &&
      executor_result.code === COMMISSION_CODE.NO_EXECUTOR_HOST
    ) {
      no_executor_host = true;
      confirmed_and_unlaunched = true;
      launched = false;
      processes_launched = 0;
      // Preserve confirmed state by name on dossier
      if (opts.project_path && dossier) {
        upsertDossier(opts.project_path, {
          job_id,
          commissioned_as,
          confirmation: {
            ...(dossier.confirmation ?? {}),
            confirmed: true,
            launch_state: 'confirmed-and-unlaunched',
            no_executor_host: true,
          },
          launch: {
            state: 'confirmed-and-unlaunched',
            no_executor_host: true,
            pid: null,
            proc_create_time: null,
            at,
          },
        });
      } else if (dossier) {
        dossier.launch = {
          state: 'confirmed-and-unlaunched',
          no_executor_host: true,
          pid: null,
          proc_create_time: null,
          at,
        };
        dossier.confirmation = {
          ...(dossier.confirmation ?? {}),
          launch_state: 'confirmed-and-unlaunched',
          no_executor_host: true,
        };
      }
    } else if (executor_result && executor_result.ok !== false) {
      launched = executor_result.launched !== false;
      processes_launched = launched ? 1 : 0;
      pid = executor_result.pid ?? null;
      proc_create_time = executor_result.proc_create_time ?? null;
      if (launched && (pid != null || proc_create_time != null)) {
        if (opts.project_path) {
          recordLaunchOnDossier(opts.project_path, {
            job_id,
            commissioned_as,
            pid,
            proc_create_time,
            intent: executor_result.intent ?? { kind: 'launch_intent', at },
            at,
          });
        } else if (dossier) {
          dossier.launch = {
            pid,
            proc_create_time,
            at,
            intent: executor_result.intent ?? null,
          };
        }
      }
    }
  }

  const success = {
    ok: true,
    spelling: SPELLING,
    job,
    job_id,
    commissioned_as,
    who,
    proposal_hash: expectedHash,
    client_event_id,
    roadmap,
    roadmap_event,
    projection,
    strip,
    strip_appended,
    strip_instrument,
    dossier,
    durable,
    confirm_journal,
    sot_written,
    bind_appended: true,
    launched,
    processes_launched,
    pid,
    proc_create_time,
    confirmed_and_unlaunched,
    no_executor_host,
    silently_queued: false,
    executor_result,
    single_writer: ROADMAP_SINGLE_WRITER,
    compose: ANCHOR_JOB_COMPOSE,
    runner: ANCHOR_JOB_COMPOSE.runner,
    idempotent: false,
    already_confirmed: false,
    message: no_executor_host
      ? COMMISSION_TEXT[COMMISSION_CODE.NO_EXECUTOR_HOST]
      : `Commission confirmed by ${who.claimed}: ${commissioned_as} bound to step '${proposal.step_id}'${launched ? ' and launched' : ' (queued)'}.`,
  };

  // When no-executor-host, surface the named code while keeping ok-ish confirmed state
  if (no_executor_host) {
    const named = {
      ...success,
      // Confirmed succeeded; launch refused by name — dual status
      ok: true,
      code: COMMISSION_CODE.NO_EXECUTOR_HOST,
      status: COMMISSION_CODE.NO_EXECUTOR_HOST,
      status_code: COMMISSION_CODE.NO_EXECUTOR_HOST,
      text: COMMISSION_TEXT[COMMISSION_CODE.NO_EXECUTOR_HOST],
      user_text: COMMISSION_TEXT[COMMISSION_CODE.NO_EXECUTOR_HOST],
      confirmed: true,
      launched: false,
    };
    _idempotenceCache.set(idemKey, named);
    return named;
  }

  _idempotenceCache.set(idemKey, success);
  return success;
}

/**
 * Recompute proposal_hash from a proposal object (post-render mutation detect).
 * @param {object} proposal
 * @returns {string}
 */
export function recomputeProposalHash(proposal) {
  const body = proposalHashBody({
    skill: proposal.skill,
    seat: proposal.seat ?? proposal.seats ?? {},
    depth_cell: proposal.depth_cell ?? proposal.depth ?? null,
    estimate: proposal.estimate ?? {},
  });
  return hashCommissionProposal(body);
}

function normalizeWho(who) {
  if (who == null) return null;
  if (typeof who === 'string' && who.trim()) {
    return {
      claimed: who.trim(),
      provenance: 'claimed_unauthenticated',
    };
  }
  if (typeof who === 'object' && who.claimed && String(who.claimed).trim()) {
    return {
      claimed: String(who.claimed).trim(),
      provenance: who.provenance ?? 'claimed_unauthenticated',
    };
  }
  return null;
}

/**
 * Build a skills table fixture with named skills commissionable (tests).
 * @param {string[]} skills
 * @param {{ nonCommissionable?: string[] }} [opts]
 */
export function makeSkillsTableFixture(skills, opts = {}) {
  const rows = [];
  for (const skill of COMMISSION_SKILLS) {
    const commissionable = skills.includes(skill);
    rows.push({
      skill,
      executor_proven: commissionable,
      executor_evidence: commissionable
        ? { pid: 1, proc_create_time: 1.0, handback_id: `fix-${skill}` }
        : null,
      evidence_class: commissionable ? 'live-skill' : null,
      halt_class: commissionable ? 'EXTERNALLY-OBSERVABLE' : 'INVISIBLE',
      excluded_reason: commissionable ? null : 'executor_not_proven',
      commissionable,
    });
  }
  for (const skill of opts.nonCommissionable ?? []) {
    const existing = rows.find((r) => r.skill === skill);
    if (existing) {
      existing.commissionable = false;
      existing.excluded_reason = existing.excluded_reason ?? 'test_excluded';
    }
  }
  return {
    schema: 'ecgberht-commissionable-skills-v0',
    generated_by: 'makeSkillsTableFixture',
    rows,
    commissionable_count: rows.filter((r) => r.commissionable).length,
  };
}

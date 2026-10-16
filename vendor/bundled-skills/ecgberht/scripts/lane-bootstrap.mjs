/**
 * Two-lane suite bootstrap (Wave 1 — criterion 14 groundwork + AUTH substrate).
 *
 * SKILL LANE: host-less. Scrub ANCHOR_TOKEN / ANCHOR_DATA_DIR / ANCHOR_PREFS_PATH.
 * No auth preflight. Ecgberht tests must never require Anchor.
 *
 * AUTH-ON LANE: mint ephemeral ANCHOR_TOKEN, set ANCHOR_AUTH_MODE=enforce, and
 * FAIL the whole lane if expected_token is empty or the pillar is not enforce
 * (closes paths.py silent auth-off fallback). Negative auth tests live here.
 */

import crypto from 'node:crypto';

export const LANE_SKILL = 'skill';
export const LANE_AUTH_ON = 'auth-on';
export const LANE_ALL = 'all';

/** Env vars scrubbed for the host-less skill lane. */
export const SKILL_SCRUB_ENV = Object.freeze([
  'ANCHOR_TOKEN',
  'ANCHOR_DATA_DIR',
  'ANCHOR_PREFS_PATH',
]);

/** Auth pillar env (Anchor pillar_flags.FLAG_AUTH). */
export const AUTH_MODE_ENV = 'ANCHOR_AUTH_MODE';
export const AUTH_TOKEN_ENV = 'ANCHOR_TOKEN';

/** Bypass flags that CI must refuse (never allow a silent auth-off green). */
export const AUTH_BYPASS_FLAGS = Object.freeze([
  'ECGBERHT_SKIP_AUTH_PREFLIGHT',
  'ECGBERHT_AUTH_OFF',
  'ANCHOR_AUTH_BYPASS',
]);

/**
 * Parse --lane from argv. Default: all.
 * @param {string[]} [argv]
 * @returns {'skill'|'auth-on'|'all'}
 */
export function parseLaneArg(argv = process.argv.slice(2)) {
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--lane' && argv[i + 1]) {
      return normalizeLane(argv[i + 1]);
    }
    if (a.startsWith('--lane=')) {
      return normalizeLane(a.slice('--lane='.length));
    }
  }
  return LANE_ALL;
}

/**
 * @param {string} raw
 * @returns {'skill'|'auth-on'|'all'}
 */
export function normalizeLane(raw) {
  const v = String(raw || '')
    .trim()
    .toLowerCase()
    .replace(/_/g, '-');
  if (v === 'skill' || v === 'host-less' || v === 'hostless') return LANE_SKILL;
  if (v === 'auth-on' || v === 'auth' || v === 'anchor') return LANE_AUTH_ON;
  if (v === 'all' || v === 'both' || v === 'default') return LANE_ALL;
  const err = new Error(
    `unknown --lane ${JSON.stringify(raw)}; expected skill | auth-on | all`,
  );
  err.code = 'LANE_UNKNOWN';
  throw err;
}

/**
 * Scrub Anchor host env for the skill lane. Mutates `env` in place.
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {NodeJS.ProcessEnv}
 */
export function scrubSkillEnv(env = process.env) {
  for (const key of SKILL_SCRUB_ENV) {
    delete env[key];
  }
  return env;
}

/**
 * Mint an ephemeral token and force auth pillar to enforce.
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {{ token: string, authMode: string }}
 */
export function mintAuthOnEnv(env = process.env) {
  const token = `ecg-w1-${crypto.randomBytes(16).toString('hex')}`;
  env[AUTH_TOKEN_ENV] = token;
  env[AUTH_MODE_ENV] = 'enforce';
  return { token, authMode: 'enforce' };
}

/**
 * AUTH SUBSTRATE GATE — fail closed before any test counts.
 * Closes the silent auth-off path where unset ANCHOR_TOKEN makes auth_ok True.
 *
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {{ ok: true, token: string, authMode: string } | { ok: false, code: string, message: string }}
 */
export function authPreflight(env = process.env) {
  for (const flag of AUTH_BYPASS_FLAGS) {
    if (env[flag] === '1' || env[flag] === 'true') {
      return {
        ok: false,
        code: 'AUTH_BYPASS_FLAG',
        message: `Auth bypass flag ${flag} is set — CI refuses an auth-off green.`,
      };
    }
  }

  const token = env[AUTH_TOKEN_ENV];
  if (token == null || String(token).trim() === '') {
    return {
      ok: false,
      code: 'AUTH_TOKEN_ABSENT',
      message:
        'AUTH-ON lane preflight: ANCHOR_TOKEN is unset/empty — expected_token() would be None; refusing before any test counts.',
    };
  }

  const mode = String(env[AUTH_MODE_ENV] || '')
    .trim()
    .toLowerCase();
  if (mode !== 'enforce') {
    return {
      ok: false,
      code: 'AUTH_PILLAR_NOT_ENFORCE',
      message: `AUTH-ON lane preflight: ${AUTH_MODE_ENV}=${JSON.stringify(mode || '(unset)')} is not "enforce" — refusing before any test counts.`,
    };
  }

  return { ok: true, token: String(token), authMode: mode };
}

/**
 * Bootstrap a lane. Skill → scrub. Auth-on → mint + preflight (throws on fail).
 * @param {'skill'|'auth-on'|'all'} lane
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {{ lane: string, preflight: object|null }}
 */
export function bootstrapLane(lane, env = process.env) {
  if (lane === LANE_SKILL) {
    scrubSkillEnv(env);
    return { lane, preflight: null };
  }
  if (lane === LANE_AUTH_ON) {
    mintAuthOnEnv(env);
    const preflight = authPreflight(env);
    if (!preflight.ok) {
      const err = new Error(preflight.message);
      err.code = preflight.code;
      err.preflight = preflight;
      throw err;
    }
    return { lane, preflight };
  }
  // all: do not scrub; mint for auth-on portion later
  return { lane: LANE_ALL, preflight: null };
}

/**
 * Node-side mirror of paths.expected_token — non-None only when set and non-empty.
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {string|null}
 */
export function expectedToken(env = process.env) {
  const tok = env[AUTH_TOKEN_ENV];
  if (tok && String(tok).trim()) return String(tok);
  return null;
}

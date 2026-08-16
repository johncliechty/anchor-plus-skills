/**
 * Anchor prefs → subscription seat resolution (W5).
 * Families map to subscription CLIs only (claude / gemini-cli|agy / grok-cli).
 * Never hardcodes product model IDs; never uses XAI_API_KEY HTTP for production seats.
 * Prefs load order: inject → env families → settings/model_prefs paths via env/home.
 * No host-absolute path string literals (home from USERPROFILE/HOME only).
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

/** Allowed family names (not product model IDs). */
export const SEAT_FAMILIES = Object.freeze(['claude', 'gemini', 'grok']);

/**
 * Subscription driver names only.
 * gemini → gemini-cli (agy is an accepted alias for the same transport).
 * grok → grok-cli (never raw "grok" HTTP + XAI_API_KEY).
 */
export const SUBSCRIPTION_DRIVERS = Object.freeze([
  'claude',
  'gemini-cli',
  'agy',
  'grok-cli',
]);

/** Drivers allowed on production seats (agy aliases gemini-cli). */
export const PRODUCTION_SEAT_DRIVERS = Object.freeze([
  'claude',
  'gemini-cli',
  'agy',
  'grok-cli',
]);

/**
 * Map coding/review family → subscription driver name.
 * @param {string} family
 * @returns {string|null}
 */
export function familyToSubscriptionDriver(family) {
  const f = String(family || '')
    .trim()
    .toLowerCase();
  if (f === 'claude') return 'claude';
  if (f === 'gemini') return 'gemini-cli';
  // Subscription Grok CLI only — never raw xAI HTTP driver name "grok"
  if (f === 'grok') return 'grok-cli';
  return null;
}

/**
 * Normalize family string; unknown → null.
 * @param {*} value
 * @returns {string|null}
 */
export function normalizeFamily(value) {
  const f = String(value || '')
    .trim()
    .toLowerCase();
  if (SEAT_FAMILIES.includes(f)) return f;
  return null;
}

/**
 * Resolve prefs file candidates without embedding host-absolute literals.
 * Uses env ANCHOR_PREFS_PATH / ANCHOR_DATA_DIR / ANCHOR_SETTINGS_PATH,
 * then home/.anchor/model_prefs.json and settings.json.
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {string[]}
 */
export function resolvePrefsCandidatePaths(env = process.env) {
  const out = [];
  const e = env || {};
  if (e.ANCHOR_PREFS_PATH) out.push(String(e.ANCHOR_PREFS_PATH));
  if (e.ANCHOR_SETTINGS_PATH) out.push(String(e.ANCHOR_SETTINGS_PATH));
  if (e.ANCHOR_DATA_DIR) {
    out.push(path.join(String(e.ANCHOR_DATA_DIR), 'model_prefs.json'));
    out.push(path.join(String(e.ANCHOR_DATA_DIR), 'settings.json'));
  }
  // If the caller explicitly supplied HOME/USERPROFILE (even empty), honor that
  // isolation and do NOT fall back to the real os.homedir — host-less / scrubbed
  // envs pass empty strings so seats resolve as `defaults`, not machine disk.
  const homeExplicit = Object.prototype.hasOwnProperty.call(e, 'USERPROFILE')
    || Object.prototype.hasOwnProperty.call(e, 'HOME');
  const home = e.USERPROFILE || e.HOME || (homeExplicit ? '' : (os.homedir?.() || ''));
  if (home) {
    out.push(path.join(home, '.anchor', 'model_prefs.json'));
    out.push(path.join(home, '.anchor', 'settings.json'));
  }
  return out;
}

/**
 * Read first existing prefs/settings JSON that carries family fields.
 * @param {{ env?: object, prefsPath?: string|null, readFile?: (p: string) => string, exists?: (p: string) => boolean }} [opts]
 * @returns {{ coding_family?: string, review_family?: string, default_cli?: string, source?: string }|null}
 */
export function loadAnchorPrefsFromDisk(opts = {}) {
  const env = opts.env ?? process.env;
  const exists = opts.exists ?? ((p) => fs.existsSync(p));
  const readFile = opts.readFile ?? ((p) => fs.readFileSync(p, 'utf8'));

  const candidates = [];
  if (opts.prefsPath) candidates.push(opts.prefsPath);
  candidates.push(...resolvePrefsCandidatePaths(env));

  for (const filePath of candidates) {
    if (!filePath || !exists(filePath)) continue;
    try {
      const raw = JSON.parse(readFile(filePath));
      if (!raw || typeof raw !== 'object') continue;
      const coding =
        raw.coding_family ?? raw.codingFamily ?? raw.coding ?? null;
      const review =
        raw.review_family ?? raw.reviewFamily ?? raw.review ?? null;
      const default_cli =
        raw.default_cli ?? raw.defaultCli ?? raw.default_cli_name ?? null;
      if (coding || review || default_cli) {
        return {
          coding_family: coding != null ? String(coding) : undefined,
          review_family: review != null ? String(review) : undefined,
          default_cli: default_cli != null ? String(default_cli) : undefined,
          source: filePath,
        };
      }
    } catch {
      // best-effort — never block seat resolution on prefs IO
    }
  }
  return null;
}

/**
 * Load Anchor model prefs (injectable for unit tests).
 * Resolve order: opts.prefs → env CODING_FAMILY/REVIEW_FAMILY → disk prefs → historical defaults.
 * @param {{ prefs?: object|null, env?: object, prefsPath?: string|null, readFile?: Function, exists?: Function }} [opts]
 * @returns {{ coding_family: string, review_family: string, default_cli: string|null, source: string, cross_model: boolean }}
 */
export function loadAnchorPrefs(opts = {}) {
  const env = opts.env ?? process.env;
  let coding = null;
  let review = null;
  let default_cli = null;
  // Honest source name when prefs/env/disk absent (Wave 22 T-HOST-0 / NS criterion 14).
  let source = 'defaults';

  if (opts.prefs && typeof opts.prefs === 'object') {
    coding = normalizeFamily(
      opts.prefs.coding_family ?? opts.prefs.codingFamily ?? opts.prefs.coding,
    );
    review = normalizeFamily(
      opts.prefs.review_family ?? opts.prefs.reviewFamily ?? opts.prefs.review,
    );
    const dc =
      opts.prefs.default_cli ?? opts.prefs.defaultCli ?? opts.prefs.default_cli;
    default_cli = dc != null && dc !== '' ? String(dc) : null;
    source = 'inject';
  }

  if (!coding) {
    coding = normalizeFamily(
      env.CODING_FAMILY || env.ANCHOR_CODING_FAMILY || '',
    );
    if (coding) source = source === 'inject' ? source : 'env';
  }
  if (!review) {
    review = normalizeFamily(
      env.REVIEW_FAMILY || env.ANCHOR_REVIEW_FAMILY || '',
    );
    if (review) source = source === 'inject' ? source : 'env';
  }
  if (!default_cli && (env.DEFAULT_CLI || env.ANCHOR_DEFAULT_CLI)) {
    default_cli = String(env.DEFAULT_CLI || env.ANCHOR_DEFAULT_CLI);
  }

  if (!coding || !review || default_cli == null) {
    const disk = loadAnchorPrefsFromDisk(opts);
    if (disk) {
      if (!coding && disk.coding_family) {
        coding = normalizeFamily(disk.coding_family);
      }
      if (!review && disk.review_family) {
        review = normalizeFamily(disk.review_family);
      }
      if (default_cli == null && disk.default_cli != null) {
        default_cli = String(disk.default_cli);
      }
      if (source === 'defaults' || source === 'default' || source === 'env') {
        source = disk.source ? 'disk' : source;
      }
    }
  }

  // Historical fallback DEFAULT when prefs absent (not a hard law)
  if (!coding) coding = 'claude';
  if (!review) review = 'gemini';

  const cross_model = coding !== review;
  return {
    coding_family: coding,
    review_family: review,
    default_cli,
    source,
    cross_model,
  };
}

/**
 * Patterns that look like vendor product model IDs (forbidden on seats).
 * Families (claude/gemini/grok) and drivers (claude/gemini-cli/grok-cli) are NOT matches.
 */
export const PRODUCT_MODEL_ID_PATTERNS = Object.freeze([
  // `fable` added 2026-08-04: the conversational seat's real reply carries
  // `modelUsage: {"claude-fable-5": …}`, and the list predated that family — so the
  // guard had a hole for the exact model in production use. Families ("claude") and
  // drivers ("claude") still do NOT match: a bare name has no `-<product>` suffix.
  /claude-(?:opus|sonnet|haiku|fable)[\w.-]*/i,
  /claude-3(?:\.\d)?[\w.-]*/i,
  /gemini-[\d.]+[\w.-]*/i,
  /models\/gemini/i,
  /grok-[234][\w.-]*/i,
  /grok-beta/i,
]);

/**
 * @param {*} value
 * @returns {string[]}
 */
export function findProductModelIds(value) {
  const hits = [];
  const walk = (v, trail) => {
    if (v == null) return;
    if (typeof v === 'string') {
      for (const re of PRODUCT_MODEL_ID_PATTERNS) {
        if (re.test(v)) {
          hits.push(trail ? `${trail}=${v}` : v);
          return;
        }
      }
      return;
    }
    if (Array.isArray(v)) {
      v.forEach((item, i) => walk(item, `${trail}[${i}]`));
      return;
    }
    if (typeof v === 'object') {
      for (const [k, child] of Object.entries(v)) {
        walk(child, trail ? `${trail}.${k}` : k);
      }
    }
  };
  walk(value, '');
  return hits;
}

/**
 * Resolve production seats from Anchor prefs.
 * @param {{ prefs?: object|null, env?: object, prefsPath?: string|null }} [opts]
 * @returns {object} seat stamp — subscription drivers only, honest cross_model
 */
export function resolveSeats(opts = {}) {
  const prefs = loadAnchorPrefs(opts);
  const coding_driver = familyToSubscriptionDriver(prefs.coding_family);
  const review_driver = familyToSubscriptionDriver(prefs.review_family);

  const seat = {
    coding_family: prefs.coding_family,
    review_family: prefs.review_family,
    default_cli: prefs.default_cli,
    coding_driver,
    review_driver,
    /** Honest stamp: false when same-family; true when families differ. */
    cross_model: prefs.coding_family !== prefs.review_family,
    prefs_source: prefs.source,
    subscription_only: true,
    /** Production seats never use raw xAI HTTP + API key. */
    xai_http_seat: false,
    xai_api_key_path: false,
    product_model_ids: [],
    drivers: {
      coding: coding_driver,
      review: review_driver,
    },
  };

  // Fail closed if a driver is missing or not a subscription CLI
  const drivers = [coding_driver, review_driver];
  for (const d of drivers) {
    if (!d || !PRODUCTION_SEAT_DRIVERS.includes(d)) {
      seat.ok = false;
      seat.error = 'non_subscription_driver';
      seat.message = `Seat driver must be subscription CLI only; got ${d}`;
      return seat;
    }
  }

  // Raw HTTP grok driver name is forbidden for production seats
  if (coding_driver === 'grok' || review_driver === 'grok') {
    seat.ok = false;
    seat.error = 'xai_http_seat_forbidden';
    seat.message =
      'Production seats must use grok-cli subscription transport, not raw grok HTTP';
    return seat;
  }

  const productHits = findProductModelIds(seat);
  if (productHits.length) {
    seat.ok = false;
    seat.error = 'product_model_id_forbidden';
    seat.message = `Seat stamp must not carry product model IDs: ${productHits.join(', ')}`;
    seat.product_model_ids = productHits;
    return seat;
  }

  seat.ok = true;
  return seat;
}

/**
 * True when a seat object is safe for production (subscription only, no product IDs, no XAI HTTP).
 * @param {object} seat
 */
export function isProductionSeatSafe(seat) {
  if (!seat || typeof seat !== 'object') return false;
  if (seat.xai_http_seat === true || seat.xai_api_key_path === true) return false;
  if (seat.coding_driver === 'grok' || seat.review_driver === 'grok') return false;
  if (findProductModelIds(seat).length) return false;
  const drivers = [seat.coding_driver, seat.review_driver].filter(Boolean);
  return drivers.every((d) => PRODUCTION_SEAT_DRIVERS.includes(d));
}

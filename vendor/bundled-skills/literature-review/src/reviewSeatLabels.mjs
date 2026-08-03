// src/reviewSeatLabels.mjs — Wave 5: review/check seat label hygiene.
//
// Operational (non-North-Star-security) policy: ban API-style Gemini *product*
// model ids (gemini-1.5-pro, gemini-2.0-flash, models/gemini-…, etc.) on review
// seats. Review seats resolve via subscription CLI / family labels only:
//   • driver: 'gemini-cli' (agy-dispatch path) — never raw product model strings
//   • family: 'gemini' | 'claude' | 'grok' (Anchor coding_family / review_family)
//   • lineage tags for multi-agree: 'gemini-cli:0', 'gemini-cli:1', …
//
// This is seating hygiene so a skill path cannot hard-code forever-product Gemini
// ids that drift off the Anchor prefs / trio driver ladder. It is NOT a substitute
// for worker isolation, PRISMA honesty, or RP convergent verification.

/** Subscription CLI driver label for Gemini review seats. */
export const GEMINI_CLI_DRIVER = 'gemini-cli';

/** Allowed family tokens (Anchor coding_family / review_family values). */
export const ALLOWED_FAMILIES = Object.freeze(['claude', 'gemini', 'grok']);

/** Allowed subscription CLI driver tokens for skill seats. */
export const ALLOWED_DRIVERS = Object.freeze(['claude', 'gemini-cli', 'grok-cli']);

/**
 * API-style Gemini product-id patterns (banned on review seats).
 * Matches Google AI Studio / Vertex product strings and bare model-id paths —
 * NOT the family name "gemini", NOT the driver "gemini-cli", NOT lineage tags
 * like "gemini-cli:0".
 */
const API_STYLE_GEMINI_RE = Object.freeze([
  // gemini-1.5-pro, gemini-2.0-flash, gemini-2.5-pro-preview-05-06, etc.
  /^gemini-\d/i,
  // gemini-pro, gemini-pro-vision, gemini-flash, gemini-ultra, gemini-nano
  /^gemini-(pro|flash|ultra|nano)(?:$|[-_.])/i,
  // models/gemini-1.5-pro (Vertex / Generative Language API path form)
  /^models\/gemini/i,
  // google/gemini-… provider-prefixed product ids
  /^google\/gemini-\d/i,
  // Bare "gemini-pro" without version still product-ish
  /^gemini-pro$/i,
  /^gemini-flash$/i,
  /^gemini-ultra$/i,
]);

export class ReviewSeatLabelError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ReviewSeatLabelError';
  }
}

/**
 * True when `label` looks like an API-style Gemini product model id.
 * Family ("gemini"), driver ("gemini-cli"), and lineage ("gemini-cli:N") are OK.
 *
 * @param {unknown} label
 * @returns {boolean}
 */
export function isApiStyleGeminiProductId(label) {
  if (typeof label !== 'string') return false;
  const s = label.trim();
  if (s.length === 0) return false;
  // Explicit allowlist of non-product labels that start with "gemini".
  if (s === 'gemini') return false;
  if (s === GEMINI_CLI_DRIVER) return false;
  if (s === 'REVIEW_FAMILY' || s === 'review_family') return false;
  if (s.startsWith(`${GEMINI_CLI_DRIVER}:`)) return false;
  if (s.startsWith('review_family:')) return false;
  if (s.startsWith('family:gemini')) return false;
  for (const re of API_STYLE_GEMINI_RE) {
    if (re.test(s)) return true;
  }
  return false;
}

/**
 * Stable multi-agree lineage tag for a review seat at panel index `i`.
 * Uses gemini-cli / family form only — never product model ids.
 *
 * @param {number} index
 * @param {{ driver?: string, family?: string }} [opts]
 * @returns {string}
 */
export function reviewSeatLineage(index, { driver = GEMINI_CLI_DRIVER, family = 'gemini' } = {}) {
  if (!Number.isInteger(index) || index < 0) {
    throw new ReviewSeatLabelError(`reviewSeatLineage index must be a non-negative integer, got ${index}`);
  }
  if (isApiStyleGeminiProductId(driver) || isApiStyleGeminiProductId(family)) {
    throw new ReviewSeatLabelError(
      `reviewSeatLineage refuses API-style Gemini product id in driver/family ` +
        `(driver=${JSON.stringify(driver)}, family=${JSON.stringify(family)})`,
    );
  }
  // Prefer the subscription CLI label; fall back to family:N when driver is non-gemini.
  if (driver === GEMINI_CLI_DRIVER || family === 'gemini') {
    return `${GEMINI_CLI_DRIVER}:${index}`;
  }
  return `${family}:${index}`;
}

/**
 * Assert that every label in `labels` is free of API-style Gemini product ids.
 * @param {Iterable<unknown>} labels
 * @returns {true}
 */
export function assertNoApiStyleGeminiIds(labels) {
  if (labels == null || typeof labels[Symbol.iterator] !== 'function') {
    throw new ReviewSeatLabelError('assertNoApiStyleGeminiIds requires an iterable of labels');
  }
  const offenders = [];
  for (const label of labels) {
    if (isApiStyleGeminiProductId(label)) offenders.push(String(label));
  }
  if (offenders.length > 0) {
    throw new ReviewSeatLabelError(
      `API-style Gemini product id(s) banned on review seats: ${offenders.map((s) => JSON.stringify(s)).join(', ')}. ` +
        `Use gemini-cli / family labels only (e.g. "${GEMINI_CLI_DRIVER}", "gemini", "${GEMINI_CLI_DRIVER}:0").`,
    );
  }
  return true;
}

/**
 * Validate a routes table (role → { driver, model? }) for review seats.
 * Review roles must not carry API-style Gemini product model fields; drivers
 * must be subscription CLI labels when present.
 *
 * @param {object|null|undefined} routes
 * @param {ReadonlyArray<string>} [reviewRoles]
 * @returns {true}
 */
export function assertReviewSeatRoutes(
  routes,
  reviewRoles = ['reviewer', 'shark', 'debate', 'judge'],
) {
  if (routes == null || typeof routes !== 'object' || Array.isArray(routes)) {
    throw new ReviewSeatLabelError('assertReviewSeatRoutes: routes must be an object');
  }
  const labels = [];
  for (const role of reviewRoles) {
    const entry = routes[role];
    if (entry == null) continue;
    if (typeof entry === 'string') {
      labels.push(entry);
      continue;
    }
    if (typeof entry === 'object') {
      if (entry.driver != null) labels.push(String(entry.driver));
      if (entry.model != null) labels.push(String(entry.model));
      if (entry.family != null) labels.push(String(entry.family));
      // Driver allowlist when present.
      if (entry.driver != null && !ALLOWED_DRIVERS.includes(String(entry.driver))) {
        // Still allow family-only tables; only hard-fail product-looking drivers.
        if (isApiStyleGeminiProductId(entry.driver)) {
          throw new ReviewSeatLabelError(
            `review role ${JSON.stringify(role)} uses banned API-style Gemini driver ${JSON.stringify(entry.driver)}`,
          );
        }
      }
    }
  }
  return assertNoApiStyleGeminiIds(labels);
}

/**
 * Scan free text (CLI source, config snippets) for banned API-style Gemini
 * product ids. Returns the list of matched tokens (empty = clean).
 *
 * @param {string} source
 * @returns {string[]}
 */
export function findApiStyleGeminiIdsInSource(source) {
  if (typeof source !== 'string' || source.length === 0) return [];
  // Token-ish matches: quoted strings and bare model ids.
  const candidates = new Set();
  const re =
    /['"`]((?:models\/)?gemini-[^'"`\s]+)['"`]|\b((?:models\/)?gemini-(?:\d[\w.-]*|pro(?:-[\w.-]+)?|flash(?:-[\w.-]+)?|ultra(?:-[\w.-]+)?|nano(?:-[\w.-]+)?))\b/gi;
  let m;
  while ((m = re.exec(source)) !== null) {
    const tok = (m[1] || m[2] || '').trim();
    if (tok && isApiStyleGeminiProductId(tok)) candidates.add(tok);
  }
  return [...candidates];
}

export default {
  isApiStyleGeminiProductId,
  reviewSeatLineage,
  assertNoApiStyleGeminiIds,
  assertReviewSeatRoutes,
  findApiStyleGeminiIdsInSource,
  GEMINI_CLI_DRIVER,
  ALLOWED_DRIVERS,
  ALLOWED_FAMILIES,
};

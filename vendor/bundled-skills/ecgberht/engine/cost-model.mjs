/**
 * Wave 5 — DETERMINISTIC COST MODEL (tokens × rate table).
 *
 * Production seats are subscription CLIs with no per-token billing. Every $
 * figure in calibration and envelope debits is SYNTHETIC-BUT-DETERMINISTIC,
 * computed by one named function — stated as such wherever rendered.
 *
 * Wave 8 imports this model + the calibration record and machine-checks:
 *   ENVELOPE_MAX_SPEND_USD >= 3 × p90(compile_cost)
 */

export const COST_MODEL_SCHEMA = 'ecgberht-cost-model-v0';
export const COST_MODEL_DISCLAIMER =
  'SYNTHETIC-BUT-DETERMINISTIC — production seats are subscription CLIs with no per-token billing; dollar figures are accounting units only';

/** Named envelope bound Wave 8 will enforce (recorded here for the relation). */
/**
 * Default session spend cap, in REAL dollars.
 *
 * Was 5.0 in synthetic accounting units, which John correctly called "way too low ...
 * it's really not priced well" — the unit was ~$0.00005 a compile, so the cap never
 * bound and meant nothing. Debits are now measured (see debitSessionEnvelope), and the
 * default is the number he set: $50 of real spend before the steward stops to check in.
 */
export const ENVELOPE_MAX_SPEND_USD = 50.0;

/**
 * Synthetic rate table (USD per 1k tokens). Deterministic accounting units —
 * not live vendor prices.
 */
export const RATE_TABLE_USD_PER_1K = Object.freeze({
  coding: 0.003,
  review: 0.0015,
  default: 0.002,
  compile: 0.0025,
});

/**
 * The ONE named pricing function. Pure: tokens × rate → synthetic USD.
 *
 * @param {number} tokens
 * @param {{ seat?: string, rate_key?: string, rates?: Record<string, number> }} [opts]
 * @returns {{
 *   tokens: number,
 *   rate_key: string,
 *   rate_usd_per_1k: number,
 *   cost_usd: number,
 *   synthetic: true,
 *   disclaimer: string,
 * }}
 */
export function priceTokens(tokens, opts = {}) {
  const n = Number(tokens);
  const safeTokens = Number.isFinite(n) && n >= 0 ? n : 0;
  const rates = opts.rates ?? RATE_TABLE_USD_PER_1K;
  const rate_key =
    opts.rate_key ??
    (opts.seat === 'review' || opts.seat === 'review_family'
      ? 'review'
      : opts.seat === 'coding' || opts.seat === 'coding_family'
        ? 'coding'
        : opts.seat === 'compile'
          ? 'compile'
          : 'default');
  const rate_usd_per_1k =
    rates[rate_key] ?? rates.default ?? RATE_TABLE_USD_PER_1K.default;
  const cost_usd = Math.round(((safeTokens / 1000) * rate_usd_per_1k) * 1e8) / 1e8;
  return {
    tokens: safeTokens,
    rate_key,
    rate_usd_per_1k,
    cost_usd,
    synthetic: true,
    disclaimer: COST_MODEL_DISCLAIMER,
  };
}

/**
 * Deterministic token estimate from text (whitespace-ish words × 1.3).
 * Not a real tokenizer — stable across hosts for synthetic accounting.
 *
 * @param {string} text
 * @returns {number}
 */
export function estimateTokens(text) {
  const s = text == null ? '' : String(text);
  if (!s.trim()) return 0;
  const words = s.trim().split(/\s+/).length;
  return Math.max(1, Math.ceil(words * 1.3));
}

/**
 * Price a compile (description / face / reflection text).
 * @param {string|object} compileInput
 * @param {{ seat?: string }} [opts]
 */
export function priceCompile(compileInput, opts = {}) {
  const text =
    typeof compileInput === 'string'
      ? compileInput
      : JSON.stringify(compileInput ?? {});
  const tokens = estimateTokens(text);
  return priceTokens(tokens, { ...opts, rate_key: opts.rate_key ?? 'compile' });
}

/**
 * Percentile of a sorted numeric array (linear interpolation).
 * @param {number[]} sorted
 * @param {number} p 0..100
 */
export function percentile(sorted, p) {
  if (!sorted.length) return 0;
  if (sorted.length === 1) return sorted[0];
  const rank = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(rank);
  const hi = Math.ceil(rank);
  if (lo === hi) return sorted[lo];
  const w = rank - lo;
  return sorted[lo] * (1 - w) + sorted[hi] * w;
}

/**
 * Median + p90 of compile costs. Pure.
 * @param {number[]} costs
 * @returns {{ n: number, median: number, p90: number, max: number, min: number }}
 */
export function summarizeCompileCosts(costs) {
  const nums = (costs || [])
    .map(Number)
    .filter((x) => Number.isFinite(x) && x >= 0)
    .sort((a, b) => a - b);
  if (!nums.length) {
    return { n: 0, median: 0, p90: 0, max: 0, min: 0 };
  }
  return {
    n: nums.length,
    median: percentile(nums, 50),
    p90: percentile(nums, 90),
    max: nums[nums.length - 1],
    min: nums[0],
  };
}

/**
 * Machine-checked envelope relation for Wave 8 (T-BND-08).
 * ENVELOPE_MAX_SPEND_USD >= 3 × p90(compile_cost)
 *
 * @param {number} p90
 * @param {number} [envelopeMax]
 * @returns {{ ok: boolean, relation: string, envelope_max: number, p90: number, required: number }}
 */
export function envelopeCoversP90(p90, envelopeMax = ENVELOPE_MAX_SPEND_USD) {
  const required = 3 * Number(p90);
  const ok = Number(envelopeMax) >= required;
  return {
    ok,
    relation: 'ENVELOPE_MAX_SPEND_USD >= 3 × p90(compile_cost)',
    envelope_max: Number(envelopeMax),
    p90: Number(p90),
    required,
  };
}

/**
 * Build the machine-readable cost-model artifact body.
 * @param {{ calibration?: object }} [extra]
 */
export function buildCostModelRecord(extra = {}) {
  return {
    schema: COST_MODEL_SCHEMA,
    synthetic: true,
    disclaimer: COST_MODEL_DISCLAIMER,
    pricing_function: 'priceTokens',
    rates_usd_per_1k_tokens: { ...RATE_TABLE_USD_PER_1K },
    envelope_max_spend_usd: ENVELOPE_MAX_SPEND_USD,
    envelope_relation: 'ENVELOPE_MAX_SPEND_USD >= 3 × p90(compile_cost)',
    production_seats: 'subscription_clis_no_per_token_billing',
    ...extra,
  };
}

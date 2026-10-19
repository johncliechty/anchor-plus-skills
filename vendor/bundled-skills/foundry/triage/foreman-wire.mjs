// Foreman inherit-only + band alignment (NS-01 / Wave 4).
//
// Foreman NEVER re-triages. It only reads the Stage-0 handoff
// (`foreman.config.json` → `triage_track` and/or `triage.{depth,tier}`) and maps
// process depth to reviewer fan-out.
//
// Closes portfolio finding: dark `triage_track: LIGHT` path that zeroed reviewers
// and the Crucible↔Foreman band mismatch (FULL unrecognized vs HEAVY-only).
//
// Contract:
//   · inherit only — never re-triage or re-recommend
//   · pin depths FULL | LITE | SPIKE-FIRST (+ documented legacy aliases on input)
//   · LITE / LIGHT never map to 0 reviewers (floor ≥ 1)
//   · FULL is recognized (reviewers = 2)
//
// Non-goals: DPAPI/sealer; prose skill blocks (Wave 6).
// Wave 5: reviewer counts are sourced from mapping.mjs (named consumption site).

import {
  DEPTH_BANDS,
  DEPTH_BAND_VALUES,
  canonicalizeDepth,
  isProcessDepth,
  normalizeDepth,
} from './core.mjs';
import { foremanKnobs } from './mapping.mjs';

/** Wave-4 surface stamp — asserted by the Foreman-inherit suite. */
export const NS01_WAVE4_STAMP = 'ns01-w4-foreman-inherit';

/** Hard floor — LITE/LIGHT (and every recognized band) never zeros the panel. */
export const MIN_REVIEWERS = 1;

/**
 * Reviewer fan-out by NS process-depth pin — consumed from Wave-5 mapping table.
 * LITE = lean panel (1); FULL + SPIKE-FIRST = full panel (2).
 * SPIKE-FIRST keeps full rigor: uncertain work must not under-review.
 */
export const REVIEWERS_BY_DEPTH = Object.freeze({
  [DEPTH_BANDS.LITE]: Math.max(MIN_REVIEWERS, foremanKnobs(DEPTH_BANDS.LITE).reviewers),
  [DEPTH_BANDS.FULL]: Math.max(MIN_REVIEWERS, foremanKnobs(DEPTH_BANDS.FULL).reviewers),
  [DEPTH_BANDS.SPIKE_FIRST]: Math.max(
    MIN_REVIEWERS,
    foremanKnobs(DEPTH_BANDS.SPIKE_FIRST).reviewers,
  ),
});

/**
 * Normalize a triage_track / free-form depth token to an NS pin depth.
 * Accepts pin tokens + legacy aliases Foreman historically branched on.
 *
 * @param {unknown} track
 * @returns {import('./core.mjs').ProcessDepth | null}
 */
export function normalizeInheritedDepth(track) {
  // canonicalizeDepth maps SPIKE-FIRST → SPIKE so REVIEWERS_BY_DEPTH hits the pin key.
  const canon = canonicalizeDepth(track);
  if (canon) return canon;
  if (isProcessDepth(track)) {
    return /** @type {import('./core.mjs').ProcessDepth} */ (canonicalizeDepth(track) ?? track);
  }
  const pin = normalizeDepth(track);
  if (pin) return pin;
  if (typeof track !== 'string' || !track.trim()) return null;
  const t = track.trim().toUpperCase().replace(/_/g, '-');
  // Historical mis-emit: model tier stuffed into triage_track → treat as FULL depth.
  if (t === 'HEAVY') return DEPTH_BANDS.FULL;
  // Legacy mid ceremony → lean panel (same fan-out as LITE).
  if (t === 'MID' || t === 'STANDARD') return DEPTH_BANDS.LITE;
  return null;
}

/**
 * True when a value is a recognized Foreman triage_track / depth token
 * (pin depths + documented legacy aliases accepted on inherit input).
 *
 * @param {unknown} track
 * @returns {boolean}
 */
export function isRecognizedTriageTrack(track) {
  return normalizeInheritedDepth(track) != null;
}

/**
 * Read process depth from a Stage-0 handoff / foreman.config shape.
 * INHERIT ONLY — never assesses or recommends.
 *
 * Precedence:
 *   1. `triage.depth` (Wave 3 structured both-axes emit)
 *   2. `triage_track` string (depth pin or legacy alias)
 *
 * @param {unknown} config  foreman.config.json object or handoff emit
 * @param {{ assess?: function }} [opts]
 *   Optional `assess` is accepted solely so tests can spy: this function MUST
 *   never call it (inherit call-count on assess stays 0).
 * @returns {import('./core.mjs').ProcessDepth | null}
 */
export function inheritDepthFromHandoff(config, opts = {}) {
  // INVARIANT (Wave 4): never re-triage. Deliberately ignore any assess hook.
  void opts;
  if (opts && typeof opts.assess === 'function') {
    // spy slot — do not invoke
  }

  if (!config || typeof config !== 'object') return null;
  const cfg = /** @type {Record<string, unknown>} */ (config);

  const triage = cfg.triage;
  if (triage && typeof triage === 'object') {
    const t = /** @type {Record<string, unknown>} */ (triage);
    const fromStructured = normalizeInheritedDepth(t.depth);
    if (fromStructured) return fromStructured;
  }

  return normalizeInheritedDepth(cfg.triage_track);
}

/**
 * Map a depth pin (or legacy track alias) → reviewer count, floored at MIN_REVIEWERS.
 * Unknown → null (caller keeps its default).
 *
 * @param {unknown} depthOrTrack
 * @returns {number | null}
 */
export function reviewersForDepth(depthOrTrack) {
  const depth = normalizeInheritedDepth(depthOrTrack);
  if (!depth) return null;
  const n = REVIEWERS_BY_DEPTH[depth];
  const count = typeof n === 'number' ? n : 2;
  return Math.max(MIN_REVIEWERS, count);
}

/**
 * Full inherit path for Foreman run-live: handoff → depth → reviewer fan-out.
 * Never re-triages. When no recognized handoff depth, returns `defaultCount`
 * (floored at MIN_REVIEWERS) with `applied: false`.
 *
 * @param {unknown} config
 * @param {{ defaultCount?: number, assess?: function }} [opts]
 * @returns {{
 *   applied: boolean,
 *   depth: import('./core.mjs').ProcessDepth | null,
 *   reviewers: number,
 *   source: 'inherit' | null,
 * }}
 */
export function inheritReviewerCount(config, opts = {}) {
  // INVARIANT: never call opts.assess (spy call-count stays 0).
  void opts?.assess;

  const rawDefault = Number(opts.defaultCount);
  const fallback =
    Number.isFinite(rawDefault) && rawDefault > 0
      ? Math.max(MIN_REVIEWERS, Math.floor(rawDefault))
      : 2;

  const depth = inheritDepthFromHandoff(config, opts);
  if (!depth) {
    return {
      applied: false,
      depth: null,
      reviewers: fallback,
      source: null,
    };
  }

  const reviewers = reviewersForDepth(depth);
  return {
    applied: true,
    depth,
    reviewers: reviewers == null ? fallback : Math.max(MIN_REVIEWERS, reviewers),
    source: 'inherit',
  };
}

export { DEPTH_BANDS, DEPTH_BAND_VALUES, MIN_REVIEWERS as REVIEWER_FLOOR };

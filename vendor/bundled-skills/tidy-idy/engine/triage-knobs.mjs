// engine/triage-knobs.mjs — Track B5 P1 sole path for tidy-idy ceremony knobs.
//
// Depth → debatePasses / maxRemovalsPerBatch is read ONLY from @foundry/triage
// tidyIdyKnobs → knobsForSkill('tidy-idy') → BAND_MAPPINGS['tidy-idy'].
// No path-local depth→number tables. Shared by debate, remove, and launch.

import { tidyIdyKnobs } from 'fil<path>';

/**
 * First non-empty string token (trim). Empty / whitespace → null.
 * @param {unknown} value
 * @returns {string | null}
 */
export function nonEmptyToken(value) {
  if (value == null) return null;
  const s = typeof value === 'string' ? value.trim() : String(value).trim();
  return s ? s : null;
}

/**
 * Depth chain for tidy-idy ceremony knobs (B5 P1 locked order):
 *   options.triageDepth → FOUNDRY_TRIAGE_DEPTH → TIDY_TRIAGE_DEPTH
 *
 * @param {{ triageDepth?: unknown, depth?: unknown, env?: NodeJS.ProcessEnv | Record<string, string|undefined> }} [options]
 * @returns {string | null}
 */
export function pickTidyIdyDepth(options = {}) {
  const env = options.env && typeof options.env === 'object' ? options.env : process.env;
  // options.triageDepth is the plan-locked field; options.depth accepted as synonym.
  return (
    nonEmptyToken(options.triageDepth) ||
    nonEmptyToken(options.depth) ||
    nonEmptyToken(env.FOUNDRY_TRIAGE_DEPTH) ||
    nonEmptyToken(env.TIDY_TRIAGE_DEPTH) ||
    null
  );
}

/**
 * Sole resolve path for tidy-idy ceremony knobs from locked/process depth.
 *
 * Pipeline:
 *   1. pick depth: options.triageDepth || FOUNDRY_TRIAGE_DEPTH || TIDY_TRIAGE_DEPTH
 *   2. no depth → null (legacy uncapped callers; no silent FULL)
 *   3. tidyIdyKnobs(depth) only — never a skill-local number table
 *
 * @param {{ triageDepth?: unknown, depth?: unknown, env?: NodeJS.ProcessEnv | Record<string, string|undefined> }} [options]
 * @returns {Readonly<object> | null}
 */
export function resolveTidyIdyKnobs(options = {}) {
  const depth = pickTidyIdyDepth(options);
  if (!depth) return null;
  return tidyIdyKnobs(depth);
}

export { tidyIdyKnobs };

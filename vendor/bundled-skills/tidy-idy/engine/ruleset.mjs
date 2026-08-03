// engine/ruleset.mjs — Wave 1: the ruleset-version stamp.
//
// Every report and every cache key carries a ruleset version derived from the
// three things that can change a verdict's meaning: the protected set, the
// exclusion set, and the prompt version. Change any of them and the stamp
// changes, so cached verdicts invalidate and old reports stay interpretable
// (you can always tell WHICH ruleset produced a report).

import crypto from 'node:crypto';

/** Bump whenever any LLM prompt text in the stage pipeline changes. */
// @3 (Wave 2): the debate gained an 'evidence-sufficiency' scope for heuristic
// mode, so a verdict cached under @2 was produced by a materially different
// question and must not be reused.
export const PROMPT_VERSION = 'tidy-idy/prompts@3';

/** Stamp format version — bump if the canonicalisation below ever changes. */
export const RULESET_STAMP_FORMAT = 'rs1';

/**
 * Deterministic ruleset stamp. Order-insensitive (both sets are sorted) so two
 * runs whose config lists the same patterns in a different order share a stamp.
 *
 * @param {{protectedPatterns: string[], exclusionPatterns: string[], promptVersion?: string}} parts
 * @returns {string} e.g. "rs1-3f9c1d0a2b4e5f60"
 */
export function computeRulesetVersion({ protectedPatterns = [], exclusionPatterns = [], promptVersion = PROMPT_VERSION } = {}) {
  const canonical = JSON.stringify({
    protected: [...new Set(protectedPatterns.map(String))].sort(),
    exclusions: [...new Set(exclusionPatterns.map(String))].sort(),
    prompts: String(promptVersion),
  });
  const digest = crypto.createHash('sha256').update(canonical, 'utf8').digest('hex').slice(0, 16);
  return `${RULESET_STAMP_FORMAT}-${digest}`;
}

/**
 * Cache key for a per-file verdict: (content hash, ruleset version) per the plan.
 * Wave 4 owns the cache itself; the key function lives with the stamp so both
 * sides can never disagree about what a key is.
 */
export function verdictCacheKey({ contentHash, rulesetVersion, kind = 'verdict' }) {
  if (!contentHash) throw new Error('verdictCacheKey requires a contentHash');
  if (!rulesetVersion) throw new Error('verdictCacheKey requires a rulesetVersion');
  return `${kind}:${rulesetVersion}:${contentHash}`;
}

/**
 * Wave 21 — named handback-contract conformance clauses (T-CONF-15).
 *
 * Each clause has a stable machine name used in failed_clauses[] and in
 * loud build failures ("executor X failed clause Y").
 *
 * Stdlib only. No host-absolute paths.
 */

/** @typedef {'path-convention'|'schema-validity'|'terminal-marker-semantics'|'write-discipline'|'write-interception'|'kill-mid-write'|'duplicate-delivery'|'no-token-in-child'|'single-writer'|'version-skew'} ClauseName */

/** @type {readonly ClauseName[]} */
export const CLAUSE_NAMES = Object.freeze([
  'path-convention',
  'schema-validity',
  'terminal-marker-semantics',
  'write-discipline',
  'write-interception',
  'kill-mid-write',
  'duplicate-delivery',
  'no-token-in-child',
  'single-writer',
  'version-skew',
]);

/**
 * Human-readable descriptions keyed by clause name.
 * @type {Readonly<Record<ClauseName, string>>}
 */
export const CLAUSE_DESCRIPTIONS = Object.freeze({
  'path-convention':
    'Handback pair lives at <worktree>/.ecgberht/handback/{handback.json,TERMINAL.marker}',
  'schema-validity':
    'Handback JSON body passes receipt-validate.mjs (kind=handback)',
  'terminal-marker-semantics':
    'Pair is ingestable only when both handback.json and TERMINAL.marker exist; marker after handback',
  'write-discipline':
    'S6 write discipline: temp + fsync + rename; handback written (and fsync complete) before marker',
  'write-interception':
    'Anti-stub: adapter must drive a real OS child through the real wrapper; canned files refuse',
  'kill-mid-write':
    'Kill mid-write (marker absent) → not ingestable',
  'duplicate-delivery':
    'Same client_event_id re-delivered → ingested exactly once',
  'no-token-in-child':
    'Child env/argv carry no ANCHOR_TOKEN / capability secrets (Descope D-1)',
  'single-writer':
    'Single writer per run dir by construction (one commissioned wrapper owns the dir)',
  'version-skew':
    'Executor contract_version must equal skill CONTRACT_VERSION; skew fails both until they agree',
});

/**
 * @param {string} name
 * @returns {name is ClauseName}
 */
export function isClauseName(name) {
  return CLAUSE_NAMES.includes(/** @type {ClauseName} */ (name));
}

/**
 * Stable failure token: "executor:<name> clause:<clause>".
 * @param {string} executor
 * @param {string} clause
 */
export function clauseFailureName(executor, clause) {
  return `executor:${executor} clause:${clause}`;
}

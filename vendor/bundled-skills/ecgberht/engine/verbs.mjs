/**
 * Closed verb surface for Ecgberht.
 * Unknown verbs refuse with structure — never open plugin dispatch.
 * Bodies: engine/verb-bodies.mjs (W3).
 */

/** Product spelling — always Ecgberht (never Expert / Egbert as product name). */
export const SPELLING = 'Ecgberht';

/**
 * Locked closed list.
 * Aliases: heartbeat ≡ update family; grasscatch ≡ soft-vet family.
 * All tokens below are accepted argv names; anything else is refuse.
 */
export const CLOSED_VERBS = Object.freeze([
  'status',
  'next',
  'update',
  'heartbeat',
  'depth-suggest',
  'soft-vet',
  'grasscatch',
  'receipt-validate',
  'roadmap-show',
  'roadmap-propose',
  'roadmap-set',
  'brief',
  'commission-propose',
  'commission-confirm',
  'seat-hop',
]);

/** Primary verbs (aliases map onto these for later waves). */
export const PRIMARY_VERBS = Object.freeze([
  'status',
  'next',
  'update',
  'depth-suggest',
  'soft-vet',
  'receipt-validate',
  'roadmap-show',
  'roadmap-propose',
  'roadmap-set',
  'brief',
  'commission-propose',
  'commission-confirm',
  'seat-hop',
]);

/** Alias → primary (routing). */
export const VERB_ALIASES = Object.freeze({
  heartbeat: 'update',
  grasscatch: 'soft-vet',
});

/**
 * W19 — the STEWARD portfolio verb surface, named in ONE place.
 *
 * WHY THIS IS NOT AN ADDITION TO THE CLOSED LIST ABOVE. CLOSED_VERBS is the Ecgberht
 * per-project talk surface: what a steward says to a project. The verbs below are the
 * portfolio/index surface built across W1–W19 — register, rebuild, reconcile, query, verify,
 * export-bundle, restore-bundle, recover-log, compact, doctor. They are operator plumbing for
 * the ONE index, not acts a Face compiles to, and folding them into the closed list would
 * widen a surface Stage-2 froze at fifteen. Two surfaces, named separately, each closed.
 *
 * WHY IT EXISTS AT ALL. Gate 0091's delta-coverage audit has to enumerate "every new CLI
 * verb" before it can prove each one is named by a test. Until this constant existed, that
 * list lived only in the plan's prose, so the audit's own input was the thing nobody could
 * check — and a verb that shipped without a test would also have shipped without ever
 * appearing in the list that would have caught it.
 *
 * @type {ReadonlyArray<string>}
 */
export const STEWARD_VERBS = Object.freeze([
  'register',
  'rebuild',
  'reconcile',
  'query',
  'verify',
  'export-bundle',
  'restore-bundle',
  'recover-log',
  'compact',
  'doctor',
]);

/**
 * Where each steward verb is implemented, and the constant that spells its name there.
 *
 * The audit cross-checks the two: this table is a list of STRINGS, and a string list can
 * drift from the modules it claims to name without anything failing. Naming the module and
 * its exported constant makes the drift checkable — rename `COMPACT_VERB`'s value and the
 * audit fails here rather than in an incident.
 */
export const STEWARD_VERB_SOURCE = Object.freeze({
  register: Object.freeze({ module: 'engine/portfolio/register.mjs', constant: 'REGISTER_VERB' }),
  rebuild: Object.freeze({ module: 'engine/portfolio/rebuild.mjs', constant: 'REBUILD_VERB' }),
  reconcile: Object.freeze({ module: 'engine/portfolio/reconcile.mjs', constant: 'RECONCILE_VERB' }),
  query: Object.freeze({ module: 'engine/portfolio/query.mjs', constant: 'QUERY_VERB' }),
  verify: Object.freeze({ module: 'engine/portfolio/verify.mjs', constant: 'VERIFY_VERB' }),
  'export-bundle': Object.freeze({ module: 'engine/portfolio/bundle.mjs', constant: 'EXPORT_VERB' }),
  'restore-bundle': Object.freeze({ module: 'engine/portfolio/bundle.mjs', constant: 'RESTORE_VERB' }),
  'recover-log': Object.freeze({ module: 'engine/portfolio/recover-log.mjs', constant: 'RECOVER_VERB' }),
  compact: Object.freeze({ module: 'engine/portfolio/compact.mjs', constant: 'COMPACT_VERB' }),
  doctor: Object.freeze({ module: 'engine/portfolio/doctor.mjs', constant: 'DOCTOR_VERB' }),
});

/** @param {string} verb @returns {boolean} whether this is a steward portfolio verb */
export function isStewardVerb(verb) {
  if (typeof verb !== 'string' || !verb) return false;
  return STEWARD_VERBS.includes(verb);
}

export function isClosedVerb(verb) {
  if (typeof verb !== 'string' || !verb) return false;
  return CLOSED_VERBS.includes(verb);
}

/**
 * Structured refuse for unknown verbs.
 * @param {string} verb
 * @returns {{ ok: false, error: 'unknown_verb', spelling: string, verb: string, message: string, closed_verbs: string[] }}
 */
export function refuseUnknownVerb(verb) {
  const name = typeof verb === 'string' ? verb : String(verb);
  return {
    ok: false,
    error: 'unknown_verb',
    spelling: SPELLING,
    verb: name,
    message: `${SPELLING} refuses unknown verb '${name}' (closed list only; no open plugin dispatch).`,
    closed_verbs: [...CLOSED_VERBS],
  };
}

/**
 * Resolve alias to primary when known; null when unknown.
 * @param {string} verb
 * @returns {string | null}
 */
export function resolvePrimaryVerb(verb) {
  if (!isClosedVerb(verb)) return null;
  return VERB_ALIASES[verb] ?? verb;
}

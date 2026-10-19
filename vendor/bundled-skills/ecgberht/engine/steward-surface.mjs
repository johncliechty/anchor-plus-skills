/**
 * The STEWARD PORTFOLIO surface — production dispatch for `STEWARD_VERBS`.
 *
 * WHY THIS EXISTS (2026-08-04 hardening).
 *
 * `engine/verbs.mjs` deliberately keeps TWO closed surfaces: `CLOSED_VERBS` (the
 * fifteen per-project talk acts a Face compiles to) and `STEWARD_VERBS` (the ten
 * portfolio/index operator verbs). That separation is right and is preserved here —
 * this module does NOT widen the closed list.
 *
 * What was missing is that the second surface had no ENTRY POINT. `STEWARD_VERBS`
 * and `isStewardVerb` were consumed only by the delta-coverage audit and its tests;
 * no production code path could invoke any of them. The consequence was not
 * cosmetic: `register` is the ONLY path that mints a project marker, a minted
 * project_id is the ONLY thing `shouldFlushPortfolioIndex` will index, and the
 * portfolio index is what the High Seat reads. With no caller, the index could
 * never be written, so the High Seat answered GLANCE_INDEX_MISSING permanently and
 * criteria 12-13 were unreachable in production. The failure text even directed the
 * operator to "run the index audit fix" — `doctor`, equally unreachable.
 *
 * SCOPE, STATED HONESTLY. Only `register` is WIRED here, because only some of the
 * ten modules expose a runner at all: `register.mjs` (registerRoot), `bundle.mjs`
 * (exportBundle/restoreBundle), `recover-log.mjs` (recoverLog) and `compact.mjs`
 * (compactLog) do; `rebuild`, `reconcile`, `query`, `verify` and `doctor` export
 * outcome/row vocabularies with no top-level run function — those verbs would have
 * to be BUILT, not merely wired. The mutating admin verbs that DO have runners
 * (compact, recover-log, restore-bundle) are deliberately left unwired rather than
 * shipped on an untested argv path.
 *
 * So the unwired verbs return a NAMED refusal that says which module and constant
 * would implement them. A gap that answers for itself is a gap an operator can act
 * on; silence is the thing that cost this build a working High Seat.
 */

import { registerRoot } from './portfolio/register.mjs';
import { SPELLING, STEWARD_VERBS, STEWARD_VERB_SOURCE, isStewardVerb } from './verbs.mjs';

/** Frozen name of this surface, so a drifting caller fails loudly. */
export const STEWARD_SURFACE = 'steward-portfolio-v1';

/** The verbs this surface can actually EXECUTE today. */
export const WIRED_STEWARD_VERBS = Object.freeze(['register']);

/** Declared in STEWARD_VERBS, implemented as vocabulary only or held back. */
export const UNWIRED_STEWARD_VERBS = Object.freeze(
  STEWARD_VERBS.filter((v) => !WIRED_STEWARD_VERBS.includes(v)),
);

/**
 * Unknown verb → structured refusal. Mirrors verbs.mjs refuseUnknownVerb, but names
 * the STEWARD surface so the two closed lists are never confused in a transcript.
 *
 * @param {unknown} verb
 * @returns {object}
 */
export function refuseUnknownStewardVerb(verb) {
  const name = typeof verb === 'string' ? verb : String(verb);
  return {
    ok: false,
    error: 'unknown_verb',
    surface: STEWARD_SURFACE,
    spelling: SPELLING,
    verb: name,
    message:
      `${SPELLING} refuses unknown steward verb '${name}' ` +
      '(closed portfolio surface; no open plugin dispatch).',
    steward_verbs: [...STEWARD_VERBS],
  };
}

/**
 * A declared verb with no production runner. NOT a crash and NOT a pretend success.
 *
 * @param {string} verb
 * @returns {object}
 */
export function refuseUnwiredStewardVerb(verb) {
  const source = STEWARD_VERB_SOURCE[verb] ?? null;
  return {
    ok: false,
    error: 'verb_not_wired',
    surface: STEWARD_SURFACE,
    spelling: SPELLING,
    verb,
    module: source?.module ?? null,
    constant: source?.constant ?? null,
    message:
      `${SPELLING} declares steward verb '${verb}' but no production runner is ` +
      `wired for it${source ? ` (${source.module})` : ''}. It is unavailable, not broken — ` +
      'nothing was read or written.',
    wired_verbs: [...WIRED_STEWARD_VERBS],
  };
}

/**
 * Run one steward portfolio verb.
 *
 * `register` is idempotent from the CALLER's point of view but not in its return
 * code: registering an already-marked root answers REGISTER_ALREADY_MARKED with
 * `ok:false` and the SAME project_id. That is correct for a verb (it refused to
 * mint a second identity) and wrong for a caller asking "is this root in the
 * portfolio?", so `already_registered` is surfaced as its own boolean and callers
 * are told to treat it as success. Anchor's host contract relies on this.
 *
 * @param {string} verb one of STEWARD_VERBS
 * @param {{root?: string, home?: string, paths?: object, env?: object, fs?: object,
 *          now?: number|Date, randomUUID?: () => string}} [opts]
 * @returns {object} structured outcome; never throws for a bad verb
 */
export function runStewardVerb(verb, opts = {}) {
  if (!isStewardVerb(verb)) return refuseUnknownStewardVerb(verb);
  if (!WIRED_STEWARD_VERBS.includes(verb)) return refuseUnwiredStewardVerb(verb);

  // register — the one wired verb.
  const root = opts.root ?? opts.project ?? null;
  if (typeof root !== 'string' || root.trim() === '') {
    return {
      ok: false,
      error: 'missing_root',
      surface: STEWARD_SURFACE,
      spelling: SPELLING,
      verb,
      message: `${SPELLING} register needs a project root path. Nothing was written.`,
    };
  }

  const outcome = registerRoot(root, opts);
  const code = outcome?.code ?? outcome?.outcome?.code ?? null;
  const alreadyMarked = code === 'REGISTER_ALREADY_MARKED';
  const projectId =
    outcome?.project_id ?? outcome?.marker?.project_id ?? outcome?.outcome?.project_id ?? null;

  return {
    ...outcome,
    ok: Boolean(outcome?.ok) || alreadyMarked,
    surface: STEWARD_SURFACE,
    verb,
    code,
    project_id: projectId,
    already_registered: alreadyMarked,
    registered: Boolean(outcome?.ok) || alreadyMarked,
  };
}

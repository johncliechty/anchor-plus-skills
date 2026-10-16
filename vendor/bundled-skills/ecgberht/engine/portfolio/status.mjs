/**
 * W3 - STATUS-v1: the ONE status vocabulary, as executable code.
 *
 * WHY THIS FILE EXISTS. Journal 0080's finding was not "the steward reported badly"; it
 * was that the surface whose entire purpose is honest signal was the surface that lied
 * under failure, because "unknown" was a string somebody typed rather than a value
 * something owned. A vocabulary that lives in prose drifts one ad-hoc literal at a time:
 * a 'missing' here, an 'n/a' there, and within a wave or two the difference between "the
 * steward looked and found nothing" and "the steward could not look" has been quietly
 * erased. That erasure is not cosmetic - it is the single most common honesty defect in
 * this codebase, and the whole loud-unknown claim rests on it not happening.
 *
 * So STATUS-v1 is frozen HERE, in code, and test/w49-status-enum-lint.test.mjs forbids the
 * literals anywhere else under engine/, tools/, bin/ and scripts/. The enum is not a
 * convenience; the lint is the deliverable and this module is what makes the lint possible.
 *
 * FOUR AXES, DELIBERATELY NOT THREE.
 *
 *  - presence     LIVE / ABSENT / UNREACHABLE. ABSENT means the steward looked and the
 *                 root is gone. UNREACHABLE means the steward could not look. Collapsing
 *                 them turns "your network share is down" into "your project is deleted".
 *
 *  - integrity    OK / EMPTY / UNPARSEABLE / MOJIBAKE / TORN / TAMPERED / UNCLASSIFIED /
 *                 IDENTITY_CONFLICT. EMPTY is a state of a store that was READ. UNKNOWN is
 *                 not on this axis at all, precisely so "empty" can never be reached by a
 *                 failure to read.
 *
 *  - path-hazard  SKIPPED_REPARSE / PATH_TOO_LONG / CASE_COLLISION, and it is its OWN axis
 *                 (NG-2) rather than three more integrity members. That separation is the
 *                 point: a junction that was not followed is not a corrupt file, and a
 *                 path over MAX_PATH is not bad JSON. Folding a hazard into UNPARSEABLE
 *                 would launder a walk decision into a content verdict, and the operator
 *                 would then go looking for damage in a file that is perfectly fine.
 *                 assertNotLaundered() below refuses that fold in code, not in review.
 *
 *  - freshness    FRESH / STALE / UNKNOWN. This is where UNKNOWN lives, and only here.
 *
 * THE TWO COMPOSITES ARE DEFINED ONCE. The 'unknown' ROW rendering (an absent-or-
 * unreachable root whose freshness is UNKNOWN) and DEGRADED (durability behind its
 * threshold) are renderings ACROSS axes. Every later wave that shows an unknown row or a
 * degradation banner calls the function here; none of them re-derives the rule. Two
 * surfaces that each decide for themselves what "unknown" looks like is how the honest
 * signal rots back into prose.
 *
 * Stdlib only - in fact no imports at all. Every other portfolio module depends on this
 * one, so this one depends on nothing, and no cycle is possible.
 */

/** The frozen vocabulary's version. Changing a member means status-v2 and a ratification. */
export const STATUS_VERSION = 'status-v1';

/**
 * The single occurrence of the UNKNOWN token in the whole tree. FRESHNESS.UNKNOWN is the
 * status meaning; inventory's "the OS gave us no errno" fallback is the same word for the
 * same reason, and it reads from here rather than typing it again.
 */
export const UNKNOWN_TOKEN = 'UNKNOWN';

// -- the four axes -------------------------------------------------------------

/** Presence of a registered root. ABSENT and UNREACHABLE are deliberately NOT the same. */
export const PRESENCE = Object.freeze({
  LIVE: 'LIVE',
  ABSENT: 'ABSENT',
  UNREACHABLE: 'UNREACHABLE',
});

/**
 * Integrity of a store or a file that was actually READ. Note what is absent: there is no
 * UNKNOWN here. A store whose bytes could not be obtained has no integrity verdict at all
 * - it has a presence verdict and a freshness verdict, and saying otherwise is the lie
 * this axis exists to prevent.
 */
export const INTEGRITY = Object.freeze({
  OK: 'OK',
  EMPTY: 'EMPTY',
  UNPARSEABLE: 'UNPARSEABLE',
  MOJIBAKE: 'MOJIBAKE',
  TORN: 'TORN',
  TAMPERED: 'TAMPERED',
  UNCLASSIFIED: 'UNCLASSIFIED',
  IDENTITY_CONFLICT: 'IDENTITY_CONFLICT',
});

/**
 * The NG-2 path-hazard axis. Its own axis on purpose: see assertNotLaundered().
 */
export const PATH_HAZARD = Object.freeze({
  SKIPPED_REPARSE: 'SKIPPED_REPARSE',
  PATH_TOO_LONG: 'PATH_TOO_LONG',
  CASE_COLLISION: 'CASE_COLLISION',
});

/** Freshness of a row or a project. The ONLY axis carrying UNKNOWN. */
export const FRESHNESS = Object.freeze({
  FRESH: 'FRESH',
  STALE: 'STALE',
  UNKNOWN: UNKNOWN_TOKEN,
});

/**
 * The two composite renderings, defined once for the whole system.
 *
 * UNKNOWN_ROW is lowercase because it is a RENDERING, not an axis member - it is the word
 * the operator reads on a portfolio row whose root the steward has lost track of. DEGRADED
 * is uppercase because it is a portfolio-level status code that surfaces carry.
 */
export const COMPOSITE = Object.freeze({
  UNKNOWN_ROW: 'unknown',
  DEGRADED: 'DEGRADED',
});

// -- axis registry -------------------------------------------------------------

/** Axis names, used by the lint and by every failure table. */
export const AXIS = Object.freeze({
  PRESENCE: 'presence',
  INTEGRITY: 'integrity',
  PATH_HAZARD: 'path-hazard',
  FRESHNESS: 'freshness',
  COMPOSITE: 'composite',
});

/** @type {Readonly<Record<string, Readonly<Record<string,string>>>>} */
export const AXES = Object.freeze({
  [AXIS.PRESENCE]: PRESENCE,
  [AXIS.INTEGRITY]: INTEGRITY,
  [AXIS.PATH_HAZARD]: PATH_HAZARD,
  [AXIS.FRESHNESS]: FRESHNESS,
  [AXIS.COMPOSITE]: COMPOSITE,
});

/** Every STATUS-v1 code, in axis order. This IS the lint's banned-literal list. */
export const STATUS_VOCABULARY = Object.freeze(
  Object.values(AXES).flatMap((axis) => Object.values(axis)),
);

/** code -> axis name. Built once; a code belonging to two axes would be a defect. */
const AXIS_OF = new Map();
for (const [axisName, members] of Object.entries(AXES)) {
  for (const code of Object.values(members)) {
    if (AXIS_OF.has(code) && AXIS_OF.get(code) !== axisName) {
      throw new Error(`STATUS-v1 defect: ${code} claimed by both ${AXIS_OF.get(code)} and ${axisName}`);
    }
    AXIS_OF.set(code, axisName);
  }
}

/**
 * The refusal codes this module itself raises. They are prefixed so they are not members
 * of the vocabulary they guard.
 */
export const STATUS_REFUSAL = Object.freeze({
  NOT_A_STATUS: 'STATUS_NOT_A_STATUS_V1_CODE',
  HAZARD_LAUNDERED: 'STATUS_HAZARD_LAUNDERED_AS_INTEGRITY',
  COMPOSITE_UNSUPPORTED: 'STATUS_COMPOSITE_INPUTS_UNSUPPORTED',
});

// -- membership ----------------------------------------------------------------

/** @param {unknown} code @returns {string|null} the axis name, or null if not STATUS-v1 */
export function axisOf(code) {
  return typeof code === 'string' && AXIS_OF.has(code) ? AXIS_OF.get(code) : null;
}

/** @param {unknown} code @returns {boolean} */
export function isStatusCode(code) {
  return axisOf(code) !== null;
}

/** @param {unknown} code @param {string} axisName @returns {boolean} */
export function isOnAxis(code, axisName) {
  return axisOf(code) === axisName;
}

/**
 * @param {unknown} code @param {string} [where] a call-site label for the message
 * @returns {string} the code, so this can wrap an argument inline
 */
export function assertStatusCode(code, where = 'status') {
  if (!isStatusCode(code)) {
    throw new Error(
      `${STATUS_REFUSAL.NOT_A_STATUS}: ${where} received ${JSON.stringify(code)}, which is not a ` +
        `${STATUS_VERSION} code. Use engine/portfolio/status.mjs; ad-hoc status strings are ` +
        'refused by test/w49-status-enum-lint.test.mjs.',
    );
  }
  return /** @type {string} */ (code);
}

/**
 * The NG-2 guard, in code rather than in a comment.
 *
 * A path hazard reaching an integrity slot is exactly the laundering the separate axis
 * exists to prevent - it turns "we did not follow that junction" into "that file is
 * corrupt", and sends the operator hunting damage that was never there. Any function
 * accepting an integrity code calls this first.
 *
 * @param {unknown} code @param {string} [where]
 * @returns {string} the code
 */
export function assertIntegrityCode(code, where = 'integrity') {
  if (isOnAxis(code, AXIS.PATH_HAZARD)) {
    throw new Error(
      `${STATUS_REFUSAL.HAZARD_LAUNDERED}: ${where} received the path hazard ${code}. A hazard is ` +
        'its own axis; reporting it as integrity would claim the file is damaged when only the ' +
        'walk declined to open it.',
    );
  }
  if (!isOnAxis(code, AXIS.INTEGRITY)) {
    throw new Error(
      `${STATUS_REFUSAL.NOT_A_STATUS}: ${where} received ${JSON.stringify(code)}, which is not a ` +
        `${STATUS_VERSION} integrity code.`,
    );
  }
  return /** @type {string} */ (code);
}

/** @param {unknown} code @returns {boolean} true when reporting it as integrity would lie */
export function isLaunderedHazard(code) {
  return isOnAxis(code, AXIS.PATH_HAZARD);
}

// -- the ad-hoc vocabulary the lint refuses ------------------------------------

/**
 * Literals that mean a status and are NOT one. Each maps to the STATUS-v1 code the author
 * should have reached for, so the lint's failure message is a fix rather than a scolding.
 *
 * The map is keyed lowercase and matched against the WHOLE literal, never a substring:
 * 'missing' is a defect, "the marker is missing its registration_receipt_id" is prose.
 */
export const BANNED_STATUS_SYNONYMS = Object.freeze({
  missing: PRESENCE.ABSENT,
  absent: PRESENCE.ABSENT,
  gone: PRESENCE.ABSENT,
  deleted: PRESENCE.ABSENT,
  'not found': PRESENCE.ABSENT,
  notfound: PRESENCE.ABSENT,
  unreachable: PRESENCE.UNREACHABLE,
  offline: PRESENCE.UNREACHABLE,
  unavailable: PRESENCE.UNREACHABLE,
  dead: PRESENCE.UNREACHABLE,
  live: PRESENCE.LIVE,
  ok: INTEGRITY.OK,
  okay: INTEGRITY.OK,
  good: INTEGRITY.OK,
  empty: INTEGRITY.EMPTY,
  blank: INTEGRITY.EMPTY,
  corrupt: INTEGRITY.UNPARSEABLE,
  corrupted: INTEGRITY.UNPARSEABLE,
  broken: INTEGRITY.UNPARSEABLE,
  unparseable: INTEGRITY.UNPARSEABLE,
  garbage: INTEGRITY.UNPARSEABLE,
  mojibake: INTEGRITY.MOJIBAKE,
  torn: INTEGRITY.TORN,
  truncated: INTEGRITY.TORN,
  tampered: INTEGRITY.TAMPERED,
  unclassified: INTEGRITY.UNCLASSIFIED,
  fresh: FRESHNESS.FRESH,
  stale: FRESHNESS.STALE,
  unknown: FRESHNESS.UNKNOWN,
  'n/a': FRESHNESS.UNKNOWN,
  na: FRESHNESS.UNKNOWN,
  lost: FRESHNESS.UNKNOWN,
  degraded: COMPOSITE.DEGRADED,
});

/**
 * @param {unknown} literal
 * @returns {string|null} the STATUS-v1 code the literal should have been, or null
 */
export function suggestedStatusFor(literal) {
  if (typeof literal !== 'string') return null;
  const key = literal.trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(BANNED_STATUS_SYNONYMS, key)
    ? BANNED_STATUS_SYNONYMS[key]
    : null;
}

// -- composite rendering, defined once -----------------------------------------

/**
 * Is this the 'unknown' ROW - the North Star's "a project the steward has lost track of
 * reports itself loudly"?
 *
 * Both halves are required. A LIVE root whose freshness is UNKNOWN is a verify problem,
 * not a lost project; an ABSENT root whose rows are known-good is still an absent root but
 * its content rows keep their own freshness. Only the pair renders as the unknown row.
 *
 * @param {{presence?: unknown, freshness?: unknown}} state
 * @returns {boolean}
 */
export function isUnknownRow(state = {}) {
  const presence = state.presence;
  const freshness = state.freshness;
  const lost = presence === PRESENCE.ABSENT || presence === PRESENCE.UNREACHABLE;
  return lost && freshness === FRESHNESS.UNKNOWN;
}

/**
 * The one place the unknown row's shape is decided. Every surface that shows a lost
 * project renders through here, so no two surfaces can disagree about what unknown means.
 *
 * @param {{presence: string, freshness: string, project_id?: string, last_known_path?: string}} state
 * @returns {{rendering: string, presence: string, freshness: string, project_id: string|null,
 *            last_known_path: string|null, text: string}}
 */
export function renderUnknownRow(state = /** @type {any} */ ({})) {
  assertStatusCode(state.presence, 'renderUnknownRow(presence)');
  assertStatusCode(state.freshness, 'renderUnknownRow(freshness)');
  if (!isUnknownRow(state)) {
    throw new Error(
      `${STATUS_REFUSAL.COMPOSITE_UNSUPPORTED}: presence=${state.presence} freshness=${state.freshness} ` +
        `is not the unknown row. The unknown row is (${PRESENCE.ABSENT} or ${PRESENCE.UNREACHABLE}) ` +
        `with freshness ${FRESHNESS.UNKNOWN}; rendering anything else as ${COMPOSITE.UNKNOWN_ROW} ` +
        'would hide a state that has a name.',
    );
  }
  const projectId = state.project_id ?? null;
  const lastKnown = state.last_known_path ?? null;
  const why = state.presence === PRESENCE.ABSENT ? 'root not found' : 'root could not be reached';
  return {
    rendering: COMPOSITE.UNKNOWN_ROW,
    presence: state.presence,
    freshness: state.freshness,
    project_id: projectId,
    last_known_path: lastKnown,
    text:
      `${COMPOSITE.UNKNOWN_ROW}: project ${projectId ?? '(unrecorded id)'} - ${why} ` +
      `(${state.presence}); last known at ${lastKnown ?? '(unrecorded path)'}. Its rows are ` +
      'retained and its identity is unchanged.',
  };
}

/**
 * W15's escalation ladder: how loud the ONE banner is, as a function of its age.
 *
 * It is a LADDER rather than a per-intent warning for a reason the operator feels rather
 * than reads about: a portfolio with forty unacknowledged intents produces forty warnings,
 * which is forty lines nobody finishes reading and therefore zero warnings. One line whose
 * volume rises with the age of the oldest unacknowledged receipt is a signal that still
 * means something on day fourteen.
 *
 * The rungs are lowercase because they describe how loudly to SAY a status; they are not
 * themselves status codes, and putting them on an axis would invite somebody to render
 * 'urgent' where a STATUS-v1 code belongs.
 */
export const DEGRADED_SEVERITY = Object.freeze({
  NOTICE: 'notice',
  WARNING: 'warning',
  URGENT: 'urgent',
  CRITICAL: 'critical',
});

/** @type {ReadonlyArray<string>} quietest first. */
export const DEGRADED_SEVERITY_ORDER = Object.freeze([
  DEGRADED_SEVERITY.NOTICE,
  DEGRADED_SEVERITY.WARNING,
  DEGRADED_SEVERITY.URGENT,
  DEGRADED_SEVERITY.CRITICAL,
]);

/**
 * Days degraded -> rung. Frozen here, beside the sentence it modifies, so a surface cannot
 * invent a fifth loudness or step at a different age from its neighbour.
 */
export const DEGRADED_SEVERITY_STEPS = Object.freeze([
  Object.freeze({ from_days: 14, severity: DEGRADED_SEVERITY.CRITICAL }),
  Object.freeze({ from_days: 7, severity: DEGRADED_SEVERITY.URGENT }),
  Object.freeze({ from_days: 3, severity: DEGRADED_SEVERITY.WARNING }),
  Object.freeze({ from_days: 0, severity: DEGRADED_SEVERITY.NOTICE }),
]);

/** @param {number} days @returns {string} the rung this age has reached */
export function degradedSeverityFor(days) {
  const value = Number.isFinite(days) ? Number(days) : 0;
  for (const step of DEGRADED_SEVERITY_STEPS) {
    if (value >= step.from_days) return step.severity;
  }
  return DEGRADED_SEVERITY.NOTICE;
}

/** @param {unknown} severity @returns {number} rung index, or 0 for anything unrecognised */
export function degradedSeverityRank(severity) {
  const at = DEGRADED_SEVERITY_ORDER.indexOf(/** @type {string} */ (severity));
  return at === -1 ? 0 : at;
}

/**
 * The one place DEGRADED is decided and worded. W15 escalates this banner by age and W16
 * adds export recency to it; both call here rather than composing their own sentence.
 *
 * `severity` is DERIVED from the age unless a caller states a louder one - which is exactly
 * what W16 does when a degraded portfolio has no bundle newer than the degradation start.
 * A caller may only ever raise it: a surface that could quieten the banner would be a
 * surface that could hide the fact.
 *
 * @param {{days_degraded?: number, receipts_at_risk?: number, last_export_days?: number|null,
 *          severity?: string}} inputs
 * @returns {{status: string, days_degraded: number, receipts_at_risk: number,
 *            last_export_days: number|null, severity: string, text: string}}
 */
export function renderDegraded(inputs = {}) {
  const days = Number.isFinite(inputs.days_degraded) ? Number(inputs.days_degraded) : 0;
  const atRisk = Number.isFinite(inputs.receipts_at_risk) ? Number(inputs.receipts_at_risk) : 0;
  const exportDays = Number.isFinite(inputs.last_export_days) ? Number(inputs.last_export_days) : null;
  const exportClause =
    exportDays === null ? 'last export-bundle: never' : `last export-bundle: ${exportDays} days ago`;
  const byAge = degradedSeverityFor(days);
  const asked = DEGRADED_SEVERITY_ORDER.includes(/** @type {any} */ (inputs.severity))
    ? /** @type {string} */ (inputs.severity)
    : byAge;
  const severity = degradedSeverityRank(asked) > degradedSeverityRank(byAge) ? asked : byAge;
  return {
    status: COMPOSITE.DEGRADED,
    days_degraded: days,
    receipts_at_risk: atRisk,
    last_export_days: exportDays,
    severity,
    text:
      `${COMPOSITE.DEGRADED}: durability degraded ${days} days, ${atRisk} receipts at risk - ` +
      `local disk is currently the only copy (${exportClause}) [${severity}].`,
  };
}

/**
 * Integrity + freshness -> the one line a surface prints for a store it did read.
 *
 * @param {{presence: string, integrity?: string|null, freshness: string}} state
 * @returns {{status: string, axis: string, text: string}}
 */
export function describeStatus(state = /** @type {any} */ ({})) {
  assertStatusCode(state.presence, 'describeStatus(presence)');
  assertStatusCode(state.freshness, 'describeStatus(freshness)');
  if (isUnknownRow(state)) {
    const row = renderUnknownRow(state);
    return { status: COMPOSITE.UNKNOWN_ROW, axis: AXIS.COMPOSITE, text: row.text };
  }
  if (state.integrity !== null && state.integrity !== undefined) {
    assertIntegrityCode(state.integrity, 'describeStatus(integrity)');
    return {
      status: state.integrity,
      axis: AXIS.INTEGRITY,
      text: `${state.integrity} (presence ${state.presence}, freshness ${state.freshness})`,
    };
  }
  return {
    status: state.presence,
    axis: AXIS.PRESENCE,
    text: `${state.presence} (freshness ${state.freshness})`,
  };
}

// -- the 0080 failure-state vocabulary -----------------------------------------

/**
 * Journal 0080's five required states, plus the two this plan adds by name.
 *
 * unknown is a SEPARATE state from empty-but-valid and always will be: collapsing them is
 * the defect 0080 was written about. path-hazard is separate because NG-2's hazards are
 * their own axis and a table that filed them under "returns garbage" would be repeating,
 * in prose, exactly the laundering assertIntegrityCode() refuses in code.
 */
export const FAILURE_STATE = Object.freeze({
  DEPENDENCY_MISSING: 'dependency-missing',
  DEPENDENCY_SLOW_OR_KILLED: 'dependency-slow-or-killed',
  DEPENDENCY_RETURNS_GARBAGE: 'dependency-returns-garbage',
  BACKING_STORE_UNREADABLE: 'backing-store-unreadable',
  EMPTY_BUT_VALID: 'empty-but-valid',
  UNKNOWN: COMPOSITE.UNKNOWN_ROW,
  PATH_HAZARD: AXIS.PATH_HAZARD,
});

/** The five journal-0080 states every surface-bearing wave must answer. */
export const REQUIRED_FAILURE_STATES = Object.freeze([
  FAILURE_STATE.DEPENDENCY_MISSING,
  FAILURE_STATE.DEPENDENCY_SLOW_OR_KILLED,
  FAILURE_STATE.DEPENDENCY_RETURNS_GARBAGE,
  FAILURE_STATE.BACKING_STORE_UNREADABLE,
  FAILURE_STATE.EMPTY_BUT_VALID,
]);

/** @type {ReadonlyArray<string>} every state a failure table may use */
export const FAILURE_STATES = Object.freeze(Object.values(FAILURE_STATE));

/** @param {unknown} state @returns {boolean} */
export function isFailureState(state) {
  return typeof state === 'string' && FAILURE_STATES.includes(state);
}

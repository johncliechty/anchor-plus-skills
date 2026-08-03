// Shared two-dimension triage core (NS-01 / Wave 1).
//
// One module owns the advisory recommendation for:
//   · model tier  {Heavy, Standard}
//   · process depth {FULL, LITE, SPIKE}  (operator / B3 NS pin set)
// plus a written rationale. This is ADVISORY only — engines must not treat an
// unlocked recommend() result as a band lock. Lock schema + getLockedBand live
// in lock.mjs (Wave 2); use getLockedBand / lockFromInteractive / lockFromHeadless.
//
// Depth heuristics deliberately mirror Crucible C3 `assessComplexity` intent
// (high-stakes never silently downgrades; SPIKE for novel+unknowns; LITE
// only for small/clear/low-stakes greenfield) but use the North-Star vocabulary
// (UPPERCASE depth tokens, Title-case tier tokens).
//
// B3 operator vocabulary: LITE | SPIKE | FULL. Legacy SPIKE-FIRST / SPIKE_FIRST /
// SPIKEFIRST normalize to the SPIKE pin. SPIKE_FIRST property is an alias of SPIKE.

/** @typedef {'Heavy' | 'Standard'} ModelTier */
/** @typedef {'FULL' | 'LITE' | 'SPIKE'} ProcessDepth */

/**
 * Wave-1 deliverable pin — public surface identity for the NS-01 shared core.
 * Asserted by the vocabulary suite; do not rename without a plan amendment.
 */
export const NS01_WAVE1_STAMP = 'ns01-w1';

/** Model-tier vocabulary (NS-01 axis 1). */
export const MODEL_TIERS = Object.freeze({
  HEAVY: 'Heavy',
  STANDARD: 'Standard',
});

/**
 * Process-depth vocabulary (NS-01 axis 2 / B3 operator pins).
 * SPIKE is first-class. SPIKE_FIRST is a property alias of the same pin string
 * so existing DEPTH_BANDS.SPIKE_FIRST readers keep working after the renorm.
 */
export const DEPTH_BANDS = Object.freeze({
  FULL: 'FULL',
  LITE: 'LITE',
  SPIKE: 'SPIKE',
  /** @deprecated Prefer SPIKE — same pin value as SPIKE (legacy property name). */
  SPIKE_FIRST: 'SPIKE',
});

/** Operator / stderr accepted set (B3 NS SC3 tokens). */
export const ACCEPTED_DEPTH_SET = Object.freeze(['LITE', 'SPIKE', 'FULL']);

/** Frozen lists for exhaustiveness checks / greps. */
export const MODEL_TIER_VALUES = Object.freeze([
  MODEL_TIERS.HEAVY,
  MODEL_TIERS.STANDARD,
]);

export const DEPTH_BAND_VALUES = Object.freeze([
  DEPTH_BANDS.FULL,
  DEPTH_BANDS.LITE,
  DEPTH_BANDS.SPIKE,
]);

/**
 * True when `value` is a valid model-tier token.
 * @param {unknown} value
 * @returns {value is ModelTier}
 */
export function isModelTier(value) {
  return MODEL_TIER_VALUES.includes(/** @type {ModelTier} */ (value));
}

/**
 * True when `value` is a valid process-depth token (pin or legacy SPIKE-FIRST storage).
 * @param {unknown} value
 * @returns {value is ProcessDepth | 'SPIKE-FIRST'}
 */
export function isProcessDepth(value) {
  if (DEPTH_BAND_VALUES.includes(/** @type {ProcessDepth} */ (value))) return true;
  // Historical locks / handoffs may still store the pre-B3 pin string.
  return value === 'SPIKE-FIRST';
}

/**
 * Build a hard-fail error for an unknown depth (accepted set named for operators).
 * @param {unknown} value
 * @returns {Error}
 */
export function unknownDepthError(value) {
  const accepted = ACCEPTED_DEPTH_SET.join(' | ');
  const err = new Error(
    `unknown process depth ${JSON.stringify(value)}; accepted: ${accepted}`,
  );
  err.name = 'UnknownDepthError';
  err.code = 'TRIAGE_UNKNOWN_DEPTH';
  /** @type {any} */ (err).accepted = [...ACCEPTED_DEPTH_SET];
  return err;
}

/**
 * Canonicalize a depth pin for table lookup (legacy SPIKE-FIRST → SPIKE).
 * @param {unknown} depth
 * @returns {ProcessDepth | null}
 */
export function canonicalizeDepth(depth) {
  if (depth === 'SPIKE-FIRST') return DEPTH_BANDS.SPIKE;
  if (DEPTH_BAND_VALUES.includes(/** @type {ProcessDepth} */ (depth))) {
    return /** @type {ProcessDepth} */ (depth);
  }
  return normalizeDepth(depth);
}

/**
 * Normalize a free-form depth token (legacy lowercase, underscore forms) to the
 * operator vocabulary LITE | SPIKE | FULL, or null if unknown.
 * SPIKE-FIRST / SPIKE_FIRST / SPIKEFIRST / SPIKE → SPIKE (first-class pin).
 *
 * @param {unknown} value
 * @param {{ hardFail?: boolean }} [opts]  when hardFail, unknown throws UnknownDepthError
 * @returns {ProcessDepth | null}
 */
export function normalizeDepth(value, opts = {}) {
  const hardFail = !!(opts && opts.hardFail);
  if (typeof value !== 'string' || !value.trim()) {
    if (hardFail) throw unknownDepthError(value);
    return null;
  }
  const key = value.trim().toUpperCase().replace(/_/g, '-');
  if (key === 'FULL') return DEPTH_BANDS.FULL;
  if (key === 'LITE' || key === 'LIGHT') return DEPTH_BANDS.LITE;
  // Aliases → SPIKE first-class pin (B3 operator vocabulary).
  if (key === 'SPIKE-FIRST' || key === 'SPIKEFIRST' || key === 'SPIKE') {
    return DEPTH_BANDS.SPIKE;
  }
  if (hardFail) throw unknownDepthError(value);
  return null;
}

/**
 * Normalize depth or throw naming the accepted set (LITE | SPIKE | FULL).
 * @param {unknown} value
 * @returns {ProcessDepth}
 */
export function normalizeDepthStrict(value) {
  return /** @type {ProcessDepth} */ (normalizeDepth(value, { hardFail: true }));
}

/**
 * Normalize a free-form tier token to the NS vocabulary, or null if unknown.
 * @param {unknown} value
 * @returns {ModelTier | null}
 */
export function normalizeTier(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const key = value.trim().toLowerCase();
  if (key === 'heavy' || key === 'frontier' || key === 'top') return MODEL_TIERS.HEAVY;
  if (key === 'standard' || key === 'regular' || key === 'mid' || key === 'normal') {
    return MODEL_TIERS.STANDARD;
  }
  return null;
}

/**
 * Cheap scope signal from intake (explicit scope wins; else intent length).
 * @param {object} i
 * @returns {'small' | 'medium' | 'large' | 'unknown'}
 */
function resolveScope(i) {
  const explicit = typeof i.scope === 'string' ? i.scope.trim().toLowerCase() : '';
  if (explicit === 'small' || explicit === 'medium' || explicit === 'large') return explicit;
  const intent = typeof i.intent === 'string' ? i.intent : '';
  if (!intent) return 'unknown';
  if (intent.length > 600) return 'large';
  if (intent.length > 180) return 'medium';
  return 'small';
}

/**
 * Recommend model tier + process depth from cheap intake signals.
 *
 * Empty / unknown intake NEVER produces a silent empty lock: it either fails
 * closed (throws when `opts.failClosed` is true) or returns a full recommendation
 * with an explicit non-empty rationale and `defaulted: true`.
 *
 * @param {object} [intake]
 * @param {string}  [intake.intent]          raw intent text (length is a weak scope signal)
 * @param {string}  [intake.scope]           'small' | 'medium' | 'large'
 * @param {number}  [intake.unknowns]        count of open unknowns at intake
 * @param {boolean} [intake.novel]           genuinely novel / unfamiliar territory
 * @param {boolean} [intake.highStakes]      high-impact outcome
 * @param {boolean} [intake.irreversible]    hard/impossible to undo if wrong
 * @param {boolean} [intake.brownfield]      existing project (raises the LITE floor)
 * @param {string}  [intake.tier]            explicit tier request (Heavy|Standard|aliases)
 * @param {string}  [intake.depth]           explicit depth request (FULL|LITE|SPIKE-FIRST|aliases)
 * @param {string}  [intake.skill]           skill id (legal-beagle / financial-analyst floor Heavy)
 * @param {object}  [opts]
 * @param {boolean} [opts.failClosed=false]  when true, empty/unknown intake throws
 * @returns {{
 *   tier: ModelTier,
 *   depth: ProcessDepth,
 *   rationale: string,
 *   defaulted: boolean,
 *   defaultedDepth: boolean,
 *   defaultedTier: boolean,
 *   signals: object,
 * }}
 */
export function recommend(intake = {}, opts = {}) {
  const i = intake && typeof intake === 'object' ? intake : {};
  const failClosed = !!(opts && opts.failClosed);

  const intent = typeof i.intent === 'string' ? i.intent : '';
  const scope = resolveScope(i);
  const unknowns = Number.isFinite(i.unknowns) ? Number(i.unknowns) : 0;
  const novel = !!i.novel;
  const highStakes = !!i.highStakes;
  const irreversible = !!i.irreversible;
  const brownfield = !!(i.brownfield || i.repoDir || i.projectDir || i.docs);
  const skill = typeof i.skill === 'string' ? i.skill.trim().toLowerCase() : '';
  const highStakesSkill =
    skill === 'legal-beagle' ||
    skill === 'financial-analyst' ||
    skill === 'legal_beagle' ||
    skill === 'financial_analyst';

  const explicitDepth = normalizeDepth(i.depth);
  const explicitTier = normalizeTier(i.tier);

  const emptyIntake =
    !intent &&
    scope === 'unknown' &&
    unknowns === 0 &&
    !novel &&
    !highStakes &&
    !irreversible &&
    !brownfield &&
    !explicitDepth &&
    !explicitTier &&
    !skill;

  if (emptyIntake && failClosed) {
    const err = new Error(
      'triage recommend: empty/unknown intake — fail-closed (no silent empty lock). ' +
        'Supply intake signals or confirm a band via the lock path (Wave 2).',
    );
    err.name = 'TriageFailClosedError';
    err.code = 'TRIAGE_EMPTY_INTAKE';
    throw err;
  }

  const signals = {
    scope,
    unknowns,
    novel,
    highStakes,
    irreversible,
    brownfield,
    skill: skill || null,
    highStakesSkill,
    explicitDepth,
    explicitTier,
    emptyIntake,
  };

  // --- depth axis -----------------------------------------------------------
  let depth;
  let defaultedDepth = false;
  let depthWhy;

  if (explicitDepth) {
    depth = explicitDepth;
    depthWhy = `explicit depth request ⇒ ${depth}`;
  } else if (highStakes || irreversible) {
    depth = DEPTH_BANDS.FULL;
    depthWhy =
      `High stakes${irreversible ? '/irreversibility' : ''} ⇒ FULL: rigor is never silently ` +
      `downgraded when the outcome is high-impact or hard to undo`;
  } else if (novel && unknowns >= 3) {
    depth = DEPTH_BANDS.SPIKE_FIRST;
    depthWhy =
      `Novel work with ${unknowns} open unknowns ⇒ SPIKE-FIRST: probe/experiment before ` +
      `planning so the plan is grounded rather than over-committed`;
  } else if (scope === 'small' && !novel && !brownfield && unknowns <= 1) {
    depth = DEPTH_BANDS.LITE;
    depthWhy =
      `Small, clear, low-novelty, low-stakes intake with ${unknowns} unknown(s) ⇒ LITE: ` +
      `single-pass plan, minimal ceremony (North Star still locked + drift-checked)`;
  } else {
    depth = DEPTH_BANDS.FULL;
    defaultedDepth = true;
    depthWhy =
      `No clear case for a lighter path (scope=${scope}, unknowns=${unknowns}` +
      `${novel ? ', novel' : ''}${brownfield ? ', brownfield' : ''}` +
      `${emptyIntake ? ', empty intake' : ''}) ⇒ FULL by default — when uncertain, the safe ` +
      `move is full machinery, never a silent downgrade`;
  }

  // --- tier axis ------------------------------------------------------------
  let tier;
  let defaultedTier = false;
  let tierWhy;

  if (explicitTier) {
    // High-stakes engine skills still surface the floor in rationale if caller
    // asked Standard; consumers validate/override in later waves (visible, not silent).
    tier = explicitTier;
    if (highStakesSkill && tier === MODEL_TIERS.STANDARD) {
      tierWhy =
        `explicit tier request ⇒ Standard; note skill "${skill}" has a Heavy stakes-class ` +
        `floor — consuming engines must validate-and-override visibly (not silent)`;
    } else {
      tierWhy = `explicit tier request ⇒ ${tier}`;
    }
  } else if (highStakes || irreversible || highStakesSkill) {
    tier = MODEL_TIERS.HEAVY;
    tierWhy = highStakesSkill
      ? `skill "${skill}" is high-stakes-class ⇒ Heavy (stakes-class floor)`
      : `High stakes${irreversible ? '/irreversibility' : ''} ⇒ Heavy: frontier seats for high-impact work`;
  } else if (depth === DEPTH_BANDS.SPIKE_FIRST || (depth === DEPTH_BANDS.FULL && (novel || scope === 'large'))) {
    tier = MODEL_TIERS.HEAVY;
    tierWhy =
      `Depth ${depth} with ${novel ? 'novel/' : ''}${scope} scope ⇒ Heavy: uncertain or large work ` +
      `warrants frontier coding/review seats`;
  } else if (depth === DEPTH_BANDS.LITE && scope === 'small' && !novel) {
    tier = MODEL_TIERS.STANDARD;
    tierWhy = `LITE + small/clear intake ⇒ Standard: regular-tier seats are enough for low-ceremony work`;
  } else {
    tier = MODEL_TIERS.HEAVY;
    defaultedTier = true;
    tierWhy =
      `No clear case for Standard (scope=${scope}, depth=${depth}` +
      `${emptyIntake ? ', empty intake' : ''}) ⇒ Heavy by default — when uncertain, prefer ` +
      `frontier seats; this is a recommendation with explicit rationale, not a silent lock`;
  }

  const defaulted = defaultedDepth || defaultedTier || emptyIntake;
  const rationale =
    `tier=${tier} (${tierWhy}). depth=${depth} (${depthWhy}).` +
    (emptyIntake
      ? ' Empty/unknown intake: recommendation is explicit (defaulted), not a silent empty lock — ' +
        'user or headless lock path must confirm before work proceeds.'
      : '');

  return {
    tier,
    depth,
    rationale,
    defaulted,
    defaultedDepth,
    defaultedTier,
    signals,
  };
}

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
/** @typedef {'FULL' | 'LITE' | 'SPIKE' | 'MATRIX-FAST-TRACK'} ProcessDepth */

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
 * Process-depth vocabulary (NS-01 axis 2 / B3 + Wave-4 operator pins).
 * SPIKE and MATRIX-FAST-TRACK are first-class. SPIKE_FIRST is a property alias
 * of the SPIKE pin string so existing DEPTH_BANDS.SPIKE_FIRST readers keep working.
 */
export const DEPTH_BANDS = Object.freeze({
  FULL: 'FULL',
  LITE: 'LITE',
  SPIKE: 'SPIKE',
  MATRIX_FAST_TRACK: 'MATRIX-FAST-TRACK',
  /** @deprecated Prefer SPIKE — same pin value as SPIKE (legacy property name). */
  SPIKE_FIRST: 'SPIKE',
});

/** Operator / stderr accepted set. */
export const ACCEPTED_DEPTH_SET = Object.freeze([
  'LITE',
  'MATRIX-FAST-TRACK',
  'SPIKE',
  'FULL',
]);

/** Frozen lists for exhaustiveness checks / greps. */
export const MODEL_TIER_VALUES = Object.freeze([
  MODEL_TIERS.HEAVY,
  MODEL_TIERS.STANDARD,
]);

export const DEPTH_BAND_VALUES = Object.freeze([
  DEPTH_BANDS.FULL,
  DEPTH_BANDS.LITE,
  DEPTH_BANDS.SPIKE,
  DEPTH_BANDS.MATRIX_FAST_TRACK,
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
  if (
    key === 'MATRIX-FAST-TRACK' ||
    key === 'MATRIX' ||
    key === 'FAST-TRACK' ||
    key === 'MATRIX-FAST' ||
    key === 'MFT'
  ) {
    return DEPTH_BANDS.MATRIX_FAST_TRACK;
  }
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

const FILE_TOKEN_RE =
  /\b[\w./\\-]+\.(?:m?js|cjs|tsx?|jsx?|py|rs|go|java|cs|rb|php|sql|json|ya?ml|toml|md|html?|css|scss|vue|svelte)\b/gi;

const IRREVERSIBLE_OR_SECURITY_TRIGGER_RE =
  /\b(schema[\s-]+migration|drop\s+table|destructive\s+migration|irreversible|auth(?:entication|orization)?\s+(?:overhaul|rewrite|bypass)|cryptograph(?:y|ic)|key\s+rotation|production\s+cutover|pii\s+exfiltration|security\s+boundary|cwe-\d+)\b/i;

const ARCHITECTURAL_MULTI_MODULE_RE =
  /\b(multi-file|multi-module|cross-cutting|re-?architect(?:ure)?|system-wide|monorepo-wide|across\s+all\s+\w+|whole-repo|migration\s+across|architectural\s+(?:overhaul|redesign|refactor))\b/i;

/**
 * Count explicit or intent-referenced target files when available.
 * @param {object} i
 * @param {string} intent
 * @returns {number | null}
 */
function extractTargetFileCount(i, intent) {
  if (Array.isArray(i.targetFiles)) return i.targetFiles.length > 0 ? i.targetFiles.length : null;
  if (Number.isFinite(i.targetFiles)) return Number(i.targetFiles) > 0 ? Number(i.targetFiles) : null;
  if (Array.isArray(i.files)) return i.files.length > 0 ? i.files.length : null;
  if (Number.isFinite(i.files)) return Number(i.files) > 0 ? Number(i.files) : null;
  if (Number.isFinite(i.fileCount)) return Number(i.fileCount) > 0 ? Number(i.fileCount) : null;
  if (!intent) return null;
  const matches = intent.match(FILE_TOKEN_RE);
  if (!matches || matches.length === 0) return null;
  const uniq = new Set(matches.map((m) => m.replace(/\\/g, '/').toLowerCase()));
  return uniq.size;
}

/**
 * Detect high-stakes irreversible / schema / security triggers in intake signals or intent.
 * @param {object} i
 * @param {string} intent
 * @returns {boolean}
 */
function detectIrreversibleTrigger(i, intent) {
  if (i.schemaMigration || i.securitySensitive) return true;
  if (!intent) return false;
  return IRREVERSIBLE_OR_SECURITY_TRIGGER_RE.test(intent);
}

/**
 * Cheap scope signal from intake (explicit scope wins; else target file count + intent length).
 * Localized tasks (<= 3 target files or clear localized intent <= 800 chars without
 * multi-module/architectural scope) resolve to 'small' rather than jumping to 'medium'/'large'
 * merely because intent.length > 180.
 *
 * @param {object} i
 * @param {number | null} [targetFileCount]
 * @returns {'small' | 'medium' | 'large' | 'unknown'}
 */
function resolveScope(i, targetFileCount = null) {
  const explicit = typeof i.scope === 'string' ? i.scope.trim().toLowerCase() : '';
  if (explicit === 'small' || explicit === 'medium' || explicit === 'large') return explicit;
  const intent = typeof i.intent === 'string' ? i.intent : '';
  const trimmed = intent.trim();
  if (!trimmed && targetFileCount == null) return 'unknown';

  const isArch = ARCHITECTURAL_MULTI_MODULE_RE.test(trimmed);
  if (targetFileCount != null && targetFileCount > 0) {
    if (targetFileCount <= 3 && trimmed.length <= 800 && !isArch) return 'small';
    if (targetFileCount <= 12 && trimmed.length <= 2400) return 'medium';
    return 'large';
  }

  if (trimmed.length > 2400) return 'large';
  if (trimmed.length > 800 || isArch) return 'medium';
  return 'small';
}

/**
 * Recommend model tier + process depth from cheap intake signals.
 *
 * Empty / unknown intake NEVER produces a silent empty lock: it either fails
 * closed (throws when `opts.failClosed` is true) or returns a full recommendation
 * with an explicit non-empty rationale and `defaulted: true`.
 *
 * Right-sizing rules:
 *   · Small/localized tasks (greenfield OR brownfield, <= 3 target files, clear intent
 *     <= 800 chars, low risk) ⇒ LITE
 *   · Novel / unconverged trade-offs ⇒ SPIKE (SPIKE-FIRST)
 *   · Medium / multi-file brownfield / architectural tasks ⇒ MATRIX-FAST-TRACK
 *   · Legacy multi-round FULL reserved for explicit `--depth FULL`, high-stakes /
 *     irreversible / schema-security triggers, or empty unsizable intake.
 *
 * @param {object} [intake]
 * @param {string}  [intake.intent]          raw intent text
 * @param {string}  [intake.scope]           'small' | 'medium' | 'large'
 * @param {number|string[]} [intake.targetFiles] target file paths or count
 * @param {number}  [intake.unknowns]        count of open unknowns at intake
 * @param {boolean} [intake.novel]           genuinely novel / unfamiliar territory
 * @param {boolean} [intake.unconverged]     competing designs / unconverged trade-offs
 * @param {boolean} [intake.highStakes]      high-impact outcome
 * @param {boolean} [intake.irreversible]    hard/impossible to undo if wrong
 * @param {boolean} [intake.brownfield]      existing project
 * @param {string}  [intake.tier]            explicit tier request (Heavy|Standard|aliases)
 * @param {string}  [intake.depth]           explicit depth request (FULL|LITE|MATRIX-FAST-TRACK|SPIKE-FIRST|aliases)
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
  const targetFileCount = extractTargetFileCount(i, intent);
  const scope = resolveScope(i, targetFileCount);
  const unknowns = Number.isFinite(i.unknowns) ? Number(i.unknowns) : 0;
  const novel = !!i.novel;
  const unconverged = !!(i.unconverged || (Number.isFinite(i.competingDesigns) && Number(i.competingDesigns) >= 2));
  const highStakes = !!i.highStakes;
  const irreversible = !!i.irreversible;
  const hasIrreversibleTrigger = detectIrreversibleTrigger(i, intent);
  const isArchitectural = ARCHITECTURAL_MULTI_MODULE_RE.test(intent);
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
    !intent.trim() &&
    targetFileCount == null &&
    scope === 'unknown' &&
    unknowns === 0 &&
    !novel &&
    !unconverged &&
    !highStakes &&
    !irreversible &&
    !hasIrreversibleTrigger &&
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
    targetFileCount,
    unknowns,
    novel,
    unconverged,
    highStakes,
    irreversible,
    hasIrreversibleTrigger,
    isArchitectural,
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

  const isLocalizedSmall =
    scope === 'small' &&
    (targetFileCount == null || targetFileCount <= 3) &&
    intent.length <= 800 &&
    !isArchitectural &&
    !novel &&
    !unconverged &&
    unknowns <= 1;

  if (explicitDepth) {
    depth = explicitDepth;
    depthWhy = `explicit depth request ⇒ ${depth}`;
  } else if (emptyIntake) {
    depth = DEPTH_BANDS.FULL;
    defaultedDepth = true;
    depthWhy =
      'Empty/unknown intake with no sizing signals ⇒ FULL by default — when unsizable, ' +
      'never silently downgrade';
  } else if (highStakes || irreversible || hasIrreversibleTrigger) {
    depth = DEPTH_BANDS.FULL;
    depthWhy =
      `High stakes${irreversible || hasIrreversibleTrigger ? '/irreversibility' : ''} ⇒ FULL: rigor is never silently ` +
      `downgraded when the outcome is high-impact, security-critical, or hard to undo`;
  } else if (novel || unconverged || unknowns >= 3) {
    depth = DEPTH_BANDS.SPIKE_FIRST;
    depthWhy =
      `Novel/unconverged work (${unknowns} open unknown(s)) ⇒ SPIKE-FIRST: probe/experiment and ` +
      `compare options before planning so the plan is grounded rather than over-committed`;
  } else if (isLocalizedSmall) {
    depth = DEPTH_BANDS.LITE;
    depthWhy =
      `Small, localized ${brownfield ? 'brownfield ' : ''}task (` +
      `${targetFileCount != null ? `${targetFileCount} target file(s), ` : ''}${unknowns} unknown(s), low risk) ⇒ LITE: ` +
      `compact fast-path plan (<=4 model calls; North Star still locked + drift-checked)`;
  } else {
    depth = DEPTH_BANDS.MATRIX_FAST_TRACK;
    depthWhy =
      `Multi-file / architectural ${brownfield ? 'brownfield ' : ''}scope (scope=${scope}` +
      `${targetFileCount != null ? `, files=${targetFileCount}` : ''}, unknowns=${unknowns}) ⇒ MATRIX-FAST-TRACK: ` +
      `lean 2-stage L0–L5 adversarial matrix (6–9 bounded calls; legacy FULL reserved for --depth FULL or irreversible triggers)`;
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
  } else if (highStakes || irreversible || hasIrreversibleTrigger || highStakesSkill) {
    tier = MODEL_TIERS.HEAVY;
    tierWhy = highStakesSkill
      ? `skill "${skill}" is high-stakes-class ⇒ Heavy (stakes-class floor)`
      : `High stakes${irreversible || hasIrreversibleTrigger ? '/irreversibility' : ''} ⇒ Heavy: frontier seats for high-impact work`;
  } else if (
    depth === DEPTH_BANDS.SPIKE_FIRST ||
    depth === DEPTH_BANDS.MATRIX_FAST_TRACK ||
    (depth === DEPTH_BANDS.FULL && (novel || scope === 'large' || brownfield))
  ) {
    tier = MODEL_TIERS.HEAVY;
    tierWhy =
      `Depth ${depth} with ${novel ? 'novel/' : ''}${scope} scope ⇒ Heavy: architectural or uncertain work ` +
      `warrants frontier coding/review seats`;
  } else if (depth === DEPTH_BANDS.LITE && scope === 'small' && !novel) {
    tier = MODEL_TIERS.STANDARD;
    tierWhy = `LITE + small/localized intake ⇒ Standard: regular-tier seats are enough for low-ceremony work`;
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

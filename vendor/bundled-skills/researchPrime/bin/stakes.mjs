// bin/stakes.mjs — Wave 4 Phase-1 seam: the adjudicated STAKES VECTOR → governor tier.
//
// MASTER-PLAN Phase A: "Emit a stakes vector (captures irreversibility; reviewer-checkable;
// irreversible ⇒ tier ≥ medium), projected to a governor tier." IMPLEMENTATION-PLAN Wave 4:
// "Given reversibility='irreversible', Then tier ≥ medium (I6); raw vector persisted (no schema
// break)."
//
// The honesty lever here is I6 ("no gamed gates"): the stakes that scale the whole verification
// loop must NOT be whatever the author casually declared — the vector is ADJUDICATED. The author's
// declaration is one axis among several, and an irreversible action forces the governor tier up to
// at least `medium` even when the author declared it `low` (the under-call guard the fixture's
// `declared-low-but-irreversible` probe exists to catch). Every upgrade is recorded in `overrides`
// so the adjudication is reviewer-checkable, not a black box.
//
// This module is PURE: `adjudicateStakes` is a deterministic function of its input (no clock, no
// randomness), and it NEVER mutates the caller's input — the raw declared vector is copied verbatim
// onto the result so a downstream consumer that only knows the declared axes still reads them
// unchanged (the "no schema break": adjudication is strictly ADDITIVE).

// ── Tier ladder (ordinal) ────────────────────────────────────────────────────────────────────
// The governor tier the rest of the engine scales by. Ordered low < medium < high.
export const TIERS = Object.freeze(['low', 'medium', 'high']);

/** Ordinal rank of a tier; -1 for an unknown tier (so unknowns never silently win a max). */
export function tierRank(tier) {
  return TIERS.indexOf(tier);
}

/** The higher of two tiers (the projection combinator). Throws on an unknown tier. */
export function maxTier(a, b) {
  const ra = tierRank(a);
  const rb = tierRank(b);
  if (ra < 0) throw new RangeError(`unknown tier: ${JSON.stringify(a)}`);
  if (rb < 0) throw new RangeError(`unknown tier: ${JSON.stringify(b)}`);
  return ra >= rb ? a : b;
}

/** Whether `tier` is at least `floor` on the ladder (the ≥ comparison crit-tests assert). */
export function tierAtLeast(tier, floor) {
  const rt = tierRank(tier);
  const rf = tierRank(floor);
  if (rt < 0) throw new RangeError(`unknown tier: ${JSON.stringify(tier)}`);
  if (rf < 0) throw new RangeError(`unknown floor: ${JSON.stringify(floor)}`);
  return rt >= rf;
}

// ── The stakes axes: each maps a declared value to the tier it justifies ───────────────────────
// Reviewer-checkable: a reviewer can read each axis's contribution and the projection rule.
// `reversibility` carries the I6 floor — `irreversible` justifies AT LEAST `medium` regardless of
// the author's declared stakes (it is the under-call guard, not merely another input).
const AXIS_TIER_MAPS = Object.freeze({
  declared_stakes: { low: 'low', medium: 'medium', high: 'high' },
  reversibility: { reversible: 'low', 'hard-to-reverse': 'medium', irreversible: 'medium' },
  blast_radius: { narrow: 'low', moderate: 'medium', wide: 'high' },
  magnitude: { minor: 'low', moderate: 'medium', major: 'high' },
});

/** The recognized stakes-vector axes, in a stable order (for reviewer-facing rationale). */
export const STAKES_AXES = Object.freeze(Object.keys(AXIS_TIER_MAPS));

// Irreversibility forces the governor tier to AT LEAST this (I6; IMPLEMENTATION-PLAN Wave 4).
export const IRREVERSIBLE_FLOOR = 'medium';

// High-stakes regulated / safety domains force the governor tier to AT LEAST 'high'.
export const REGULATED_DOMAIN_FLOOR = 'high';

const REGULATED_DOMAIN_PATTERNS = Object.freeze([
  {
    category: 'medical',
    re: /\b(?:medical|clinical(?:\s+trial|\s+guideline|\s+safety|\s+outcome|\s+protocol|\s+dosing)?|drug[- ]interaction|contraindicat(?:ion|ed)|dosage|pharmacology|patient[- ]safety|adverse[- ]event|anticoagulant|warfarin|pediatric\s+dose|oncology\s+regimen|toxicology)\b/i,
  },
  {
    category: 'legal',
    re: /\b(?:legal\s+liability|malpractice|fiduciary\s+(?:duty|breach|obligation|liability)|indemnif(?:y|ication)|statutory\s+(?:liability|compliance|violation)|litigation\s+risk|regulatory\s+(?:penalty|enforcement|violation|compliance)|tort\s+liability|hipaa\s+compliance|gdpr\s+compliance|contract(?:ual)?\s+liability)\b/i,
  },
  {
    category: 'financial',
    re: /\b(?:fiduciary|solvency|bankruptcy\s+risk|tax\s+liability|sec\s+(?:filing|enforcement|compliance)|securities\s+(?:law|fraud|regulation)|cap[- ]table\s+dilution|liquidation\s+preference|equity\s+waterfall|capital\s+adequacy|margin\s+call|pension\s+liability)\b/i,
  },
]);

const EXPLICIT_REGULATED_DOMAINS = Object.freeze({
  medical: 'medical',
  clinical: 'medical',
  healthcare: 'medical',
  pharmacology: 'medical',
  legal: 'legal',
  compliance: 'legal',
  regulatory: 'legal',
  financial: 'financial',
  fiduciary: 'financial',
});

/**
 * Detect whether a query / intake / stakes object touches a high-stakes safety or
 * regulated domain (medical/clinical/drug-interaction, legal liability, financial/fiduciary).
 * Pure, deterministic function of its input.
 *
 * @param {string|object} input
 * @returns {{ matched: boolean, category: ?string, trigger: ?string }}
 */
export function detectRegulatedDomain(input) {
  if (typeof input === 'string') {
    for (const { category, re } of REGULATED_DOMAIN_PATTERNS) {
      const m = re.exec(input);
      if (m) return { matched: true, category, trigger: m[0] };
    }
    return { matched: false, category: null, trigger: null };
  }
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return { matched: false, category: null, trigger: null };
  }
  const explicitDom = typeof input.domain === 'string' ? input.domain.trim().toLowerCase() : '';
  if (explicitDom && EXPLICIT_REGULATED_DOMAINS[explicitDom]) {
    return { matched: true, category: EXPLICIT_REGULATED_DOMAINS[explicitDom], trigger: `domain:${explicitDom}` };
  }
  const haystacks = [
    input.query,
    input.objective,
    input.intent,
    input.axis,
    input.topic,
    input.northStar,
    input.domain,
  ].filter((v) => typeof v === 'string' && v.trim().length > 0);
  for (const text of haystacks) {
    for (const { category, re } of REGULATED_DOMAIN_PATTERNS) {
      const m = re.exec(text);
      if (m) return { matched: true, category, trigger: m[0] };
    }
  }
  return { matched: false, category: null, trigger: null };
}

/**
 * Map one axis value to the tier it justifies. An unrecognized value for a known axis contributes
 * nothing (`low`) — it can never silently RAISE the tier, only the recognized scale words can — so
 * a typo'd or novel value fails safe (no spurious upgrade) and is left for a reviewer to catch.
 */
function axisTier(axis, value) {
  const map = AXIS_TIER_MAPS[axis];
  if (!map) return 'low';
  return map[value] ?? 'low';
}

/**
 * Adjudicate a declared stakes input into a governor tier (I6).
 *
 * @param {object} input the declared stakes vector — any of {declared_stakes, reversibility,
 *   blast_radius, magnitude}, plus an optional `id`/extra fields (preserved verbatim).
 * @returns {{
 *   id: string|undefined,
 *   raw: object,                       // the caller's declared vector, copied verbatim (no schema break)
 *   axis_tiers: Record<string,string>, // each recognized axis's tier contribution (reviewer-checkable)
 *   declared_tier: string,             // what the author's `declared_stakes` alone would have set
 *   tier: string,                      // the adjudicated governor tier (the projection)
 *   overrides: Array<{axis,from,to,reason}>, // every upgrade above the declared tier (auditable)
 *   rationale: string,
 * }}
 */
export function adjudicateStakes(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new TypeError('adjudicateStakes requires a stakes-vector object');
  }

  // Per-axis tier contributions (only for axes the caller actually declared).
  const axis_tiers = {};
  for (const axis of STAKES_AXES) {
    if (input[axis] !== undefined) axis_tiers[axis] = axisTier(axis, input[axis]);
  }

  // The author's self-declaration alone (the number the under-call guard must beat).
  const declared_tier = input.declared_stakes !== undefined
    ? axisTier('declared_stakes', input.declared_stakes)
    : 'low';

  // Projection: the highest tier any declared axis justifies.
  let tier = 'low';
  for (const t of Object.values(axis_tiers)) tier = maxTier(tier, t);

  // I6 under-call guard (defensive floor): irreversibility forces tier ≥ medium regardless of the
  // axis map (so the floor survives even if the reversibility scale is ever re-tuned).
  if (input.reversibility === 'irreversible') tier = maxTier(tier, IRREVERSIBLE_FLOOR);

  // Regulated / safety-critical auto-escalation: medical/clinical/drug-interaction, legal
  // liability, and financial/fiduciary queries escalate to at least 'high' so safety-critical
  // runs never slip through at stakesTier='low'.
  const regulated = detectRegulatedDomain(input);
  if (regulated.matched) {
    tier = maxTier(tier, REGULATED_DOMAIN_FLOOR);
  }

  // Record every axis (other than the author's own declaration) that pushed the governor tier ABOVE
  // the author's declared tier, so a reviewer sees exactly WHY the governor over-rode the author.
  // The canonical case is the irreversibility floor beating a `low` declaration (the under-call
  // guard); the same loop also catches e.g. a `wide` blast_radius beating a `low` declaration.
  const overrides = [];
  for (const axis of STAKES_AXES) {
    if (axis === 'declared_stakes') continue;
    const at = axis_tiers[axis];
    if (!at || tierRank(at) <= tierRank(declared_tier)) continue;
    const reason =
      axis === 'reversibility' && input.reversibility === 'irreversible'
        ? `reversibility='irreversible' forces tier ≥ ${IRREVERSIBLE_FLOOR} (I6 under-call guard)`
        : `${axis}='${input[axis]}' justifies tier ${at}, above the declared ${declared_tier}`;
    overrides.push({ axis, from: declared_tier, to: at, reason });
  }
  if (regulated.matched && tierRank(REGULATED_DOMAIN_FLOOR) > tierRank(declared_tier)) {
    overrides.push({
      axis: 'regulated_domain',
      from: declared_tier,
      to: REGULATED_DOMAIN_FLOOR,
      category: regulated.category,
      reason: `regulated/safety domain (${regulated.category}: "${regulated.trigger}") auto-escalates stakesTier to '${REGULATED_DOMAIN_FLOOR}'`,
    });
  }

  const rationale =
    `adjudicated governor tier=${tier} (declared=${declared_tier})` +
    (overrides.length ? `; upgraded by: ${overrides.map((o) => o.axis).join(', ')}` : '; no upgrade');

  return {
    id: input.id,
    raw: { ...input }, // verbatim copy — additive adjudication, never mutates the declared vector
    axis_tiers,
    declared_tier,
    tier,
    overrides,
    rationale,
  };
}

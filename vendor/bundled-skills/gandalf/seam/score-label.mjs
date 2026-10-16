// Gandalf advisor — the SCORE / LABEL / SYNTHESIS seam (Wave 6 / serves NS4, NS6).
//
// This is the seam that turns vetted findings into honestly-scored, honestly-labelled,
// honestly-synthesised output. Three jobs, each pinned to a locked North-Star boundary and a
// deterministic gate (label/semantic TRUTH staying the advisory layer's job — PRINCIPLE-D):
//
//   • SCORE — DUAL-AXIS, NEVER COLLAPSED. Every suggestion is scored on TWO independent ordinal
//     axes: value-if-true (low→high) × groundedness (the evidence rung). The two are NEVER
//     collapsed into a single scalar — a high-value/low-grounded suggestion and a low-value/
//     high-grounded one are NOT interchangeable, and collapsing them would launder the one into
//     the other. `scoreDualAxis` returns the two axes side by side; `isDualAxisScore` /
//     COLLAPSED_SCORE_FIELDS detect a collapsed scalar.
//
//   • LABEL — TIERED, HONEST. Tier = the refutation outcome. ONLY the REFUTED drops; everything
//     else is kept and labelled (nothing unverified is asserted as real, but nothing un-refuted
//     is silently discarded either). The single-family ceiling is PROMISING, never GROUNDED
//     (the deterministic B-ceiling embodiment lives in harness.mjs; `labelTier` honours it).
//
//   • SYNTHESIS — HONEST (B8). A leg the run actually reports (a diagnose/situate/anticipate
//     finding is present) MUST appear in `risk_labels`, and a leg's synthesis label may NOT claim
//     a rung above that leg's EVIDENTIAL ENVELOPE — the strongest rung any finding in the leg
//     reached. A synthesis that out-claims its own findings is laundering (carry rung at-or-below
//     source). `legEnvelopeRung` / `legsPresent` / `composeRiskLabels` are the surface; the
//     deterministic gate is harness.mjs `assertHonestSynthesis` (= B8).
//
// And the NS6 anti-drift boundary the wave makes machine-checkable:
//   • B1 — ZERO IDEATION. Gandalf's value is INSIGHT (understand + situate + anticipate), not the
//     open-ended generation of NEW ideas/extensions — that is Jumper's (a separate later skill).
//     An "ideate"-class finding (a divergent/brainstorm kind, or a finding carrying an idea-
//     generation field) FAILS B1. `IDEATION_KINDS` / `IDEATION_FIELDS` / `isIdeationFinding` are
//     the discriminator; the gate is harness.mjs `assertNoIdeation`.
//
//   • B6 — NO SILENT DEGRADATION. If any item ran degraded (`degraded:true`), the top-level output
//     MUST own that (`degraded:true`). A per-item `degraded:true` under a top-level `degraded:false`
//     is a silent degradation and FAILS B6. `degradedItems` / `hasSilentDegradation` are the
//     surface; the gate is harness.mjs `assertNoSilentDegradation`.
//
// Public surface:
//   VALUE_AXIS / GROUNDEDNESS_AXIS            — the two SCORE axes (ordinal, low→high)
//   COLLAPSED_SCORE_FIELDS                    — fields that would collapse the two axes into one
//   scoreDualAxis(item)                       — mint a {value_if_true, groundedness} dual-axis score
//   isDualAxisScore(score)                    — predicate: two separate axes, not collapsed
//   isCollapsedScore(score)                   — predicate: carries a single collapsed scalar
//   TIER_CEILING_SINGLE_FAMILY / DROP_RUNG    — the PROMISING ceiling / the only-dropped rung
//   dropsFromOutput(item)                     — predicate: rung REFUTED ⇒ the only drop
//   labelTier(item)                           — tier the refutation outcome (only REFUTED drops)
//   LEGS / legsPresent(output)                — the synthesis legs present in an output
//   legEnvelopeRung(output, leg)              — the strongest rung any finding in the leg reached
//   composeRiskLabels(output)                 — mint honest, envelope-bounded risk_labels
//   IDEATION_KINDS / IDEATION_FIELDS          — the B1 ideation discriminator
//   isIdeationFinding(item)                   — predicate: a divergent/brainstorm ideate-class item
//   degradedItems(output) / hasSilentDegradation(output) — the B6 surface

// --- self-contained helpers + ladders (the seam imports nothing; harness imports the seam) ----
function isNonEmpty(v) {
  if (v === undefined || v === null) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === 'string') return v.trim() !== '';
  if (typeof v === 'object') return Object.keys(v).length > 0;
  return true; // numbers, booleans
}

// Ladders local to the seam (low → high), identical to the harness ladders (no drift); the
// harness mirrors these and harness.test.mjs asserts the schema enums agree with them.
const RUNG_LADDER = ['REFUTED', 'UNVERIFIED', 'CLAIMED', 'CORROBORATED', 'OBSERVED'];
const TIER_LADDER = ['SPECULATIVE', 'PROMISING', 'GROUNDED'];

/** The value-if-true axis of the dual-axis score (low → high). */
export const VALUE_AXIS = ['low', 'medium', 'high'];
/** The groundedness axis of the dual-axis score = the evidence rung ladder (low → high). */
export const GROUNDEDNESS_AXIS = RUNG_LADDER.slice();

function rungIdx(rung) {
  return RUNG_LADDER.indexOf(rung);
}

// === SCORE — dual-axis, never collapsed =======================================================
/** Fields whose presence would COLLAPSE the two independent axes into a single scalar — a
 *  laundering move (a high-value/low-grounded suggestion and a low-value/high-grounded one must
 *  stay distinguishable). A dual-axis score must carry NONE of these. */
export const COLLAPSED_SCORE_FIELDS = [
  'score', 'combined_score', 'overall_score', 'priority', 'priority_score',
  'weighted_score', 'collapsed_score', 'rank_score', 'composite',
];

/** Mint a DUAL-AXIS score for a suggestion: value-if-true × groundedness, kept on two SEPARATE
 *  ordinal axes and NEVER collapsed into one scalar. `value_if_true` must be on VALUE_AXIS and
 *  `rung` on GROUNDEDNESS_AXIS. Returns a fresh `{ value_if_true, groundedness }`; throws on a
 *  missing/invalid axis (judging the magnitudes is the advisory layer's job — PRINCIPLE-D). */
export function scoreDualAxis(item) {
  if (item === null || typeof item !== 'object' || Array.isArray(item)) {
    throw new Error('score-label: scoreDualAxis target is not an object');
  }
  if (!VALUE_AXIS.includes(item.value_if_true)) {
    throw new Error(`score-label: scoreDualAxis requires value_if_true on the value axis [${VALUE_AXIS.join(', ')}], got ${JSON.stringify(item.value_if_true)}`);
  }
  if (!GROUNDEDNESS_AXIS.includes(item.rung)) {
    throw new Error(`score-label: scoreDualAxis requires a groundedness rung on [${GROUNDEDNESS_AXIS.join(', ')}], got ${JSON.stringify(item.rung)}`);
  }
  return { value_if_true: item.value_if_true, groundedness: item.rung };
}

/** Predicate: does `score` carry any field that COLLAPSES the two axes into a single scalar?
 *  Pure; never throws. */
export function isCollapsedScore(score) {
  if (score === null || typeof score !== 'object' || Array.isArray(score)) return false;
  return COLLAPSED_SCORE_FIELDS.some((f) => f in score && isNonEmpty(score[f]));
}

/** Predicate: is `score` a well-formed DUAL-AXIS score — both axes present on their ladders AND
 *  no collapsed scalar field? Pure; never throws. */
export function isDualAxisScore(score) {
  if (score === null || typeof score !== 'object' || Array.isArray(score)) return false;
  if (isCollapsedScore(score)) return false;
  return VALUE_AXIS.includes(score.value_if_true) && GROUNDEDNESS_AXIS.includes(score.groundedness);
}

// === LABEL — tiered, honest (only REFUTED drops; single-family ceiling PROMISING) =============
/** The single-family substrate tier ceiling: the max achievable tier on a `cross_model:false`
 *  run is PROMISING (GROUNDED is unreachable without a cross-family refuter). */
export const TIER_CEILING_SINGLE_FAMILY = 'PROMISING';
/** The ONLY rung that drops a finding from the output. Everything above REFUTED is kept and
 *  honestly labelled (nothing un-refuted is silently discarded). */
export const DROP_RUNG = 'REFUTED';

/** Predicate: does `item` drop from the output? TRUE iff its rung is REFUTED — the only rung that
 *  drops. A finding at any higher rung is kept and labelled. Pure; never throws. */
export function dropsFromOutput(item) {
  return item !== null && typeof item === 'object' && item.rung === DROP_RUNG;
}

/** Label a suggestion's tier from its refutation outcome, honouring the two label invariants:
 *    • only REFUTED drops — a REFUTED item returns `{ dropped:true, tier:null }`;
 *    • the single-family ceiling is PROMISING — when `cross_model` is false (default), a tier is
 *      capped at PROMISING; GROUNDED is unreachable.
 *  `requested_tier` (if on the tier ladder) is the advisory layer's proposed tier; this caps it.
 *  Returns `{ dropped, tier }`; pure, never throws on data (throws only on a non-object). */
export function labelTier(item, { cross_model = false } = {}) {
  if (item === null || typeof item !== 'object' || Array.isArray(item)) {
    throw new Error('score-label: labelTier target is not an object');
  }
  if (dropsFromOutput(item)) return { dropped: true, tier: null };
  const requested = TIER_LADDER.includes(item.tier) ? item.tier : TIER_CEILING_SINGLE_FAMILY;
  let tier = requested;
  if (cross_model === false && TIER_LADDER.indexOf(tier) > TIER_LADDER.indexOf(TIER_CEILING_SINGLE_FAMILY)) {
    tier = TIER_CEILING_SINGLE_FAMILY; // single-family ceiling
  }
  return { dropped: false, tier };
}

// === SYNTHESIS — honest (B8) ==================================================================
/** The synthesis legs — exactly the `risk_labels` leg enum and the finding kinds that map to a
 *  leg. (`nitpick` is not a leg; it is not synthesised into a risk label.) */
export const LEGS = ['diagnose', 'situate', 'anticipate'];

/** The set of legs the run actually REPORTS: a leg is present iff at least one finding carries
 *  that `kind`. Returns an array (LEGS order). Pure; never throws. */
export function legsPresent(output) {
  const findings = Array.isArray(output?.findings) ? output.findings : [];
  const kinds = new Set(findings.map((f) => (f && typeof f === 'object' ? f.kind : undefined)));
  return LEGS.filter((leg) => kinds.has(leg));
}

/** The EVIDENTIAL ENVELOPE rung of a leg: the STRONGEST rung any finding in the leg reached (the
 *  upper bound the leg's evidence supports). A synthesis label for the leg may not exceed it. Returns
 *  the rung string, or null if the leg has no rung-bearing finding. Pure; never throws. */
export function legEnvelopeRung(output, leg) {
  const findings = Array.isArray(output?.findings) ? output.findings : [];
  let best = -1;
  for (const f of findings) {
    if (f === null || typeof f !== 'object' || f.kind !== leg) continue;
    const i = rungIdx(f.rung);
    if (i > best) best = i;
  }
  return best === -1 ? null : RUNG_LADDER[best];
}

/** Mint HONEST risk_labels: one per present leg, with `rung` = the leg's evidential envelope and each
 *  leg's `tier` capped PER-LEG — NEVER off the run-level `cross_model` flag (that is the risk-label
 *  LAUNDERING hole: one genuine cross-family elevation would flip the global flag and lift EVERY
 *  unrelated leg to GROUNDED). A findings leg (diagnose/situate/anticipate) has NO commission-provenance
 *  surface, so it can never be cross-family; a leg is GROUNDED-eligible ONLY if some finding in it is
 *  ITSELF digest-bound cross-family (`cross_family_refuted:true`) — which findings never are — so every
 *  findings leg stays at the single-family PROMISING ceiling regardless of the run-level flag. The result
 *  passes the B8 honest-synthesis gate and the B-ceiling gate by construction. Returns a fresh array.
 *  Pure; never throws. */
export function composeRiskLabels(output) {
  const findings = Array.isArray(output?.findings) ? output.findings : [];
  return legsPresent(output).map((leg) => {
    const rung = legEnvelopeRung(output, leg);
    // PER-LEG cross-family eligibility — keyed off each finding's OWN derived `cross_family_refuted`,
    // never the global cross_model flag. Findings carry no commission provenance ⇒ this is always false
    // ⇒ findings legs never launder up to GROUNDED off an unrelated elevation's genuine refutation.
    const legCrossFamily = findings.some(
      (f) => f && typeof f === 'object' && f.kind === leg && f.cross_family_refuted === true
    );
    const label = { leg, tier: legCrossFamily ? 'GROUNDED' : TIER_CEILING_SINGLE_FAMILY };
    if (rung !== null) label.rung = rung;
    return label;
  });
}

// === B1 — zero ideation (NS6 anti-drift: ideation is Jumper's) =================================
/** Divergent/brainstorm `kind` markers — an "ideate"-class leg Gandalf does not run (the open-
 *  ended generation of new ideas/extensions is Jumper's). */
export const IDEATION_KINDS = ['ideate', 'ideation', 'brainstorm', 'divergent', 'jumper'];

/** Idea-generation FIELDS — a finding carrying one of these is doing open-ended ideation, not
 *  the grounded insight (understand/situate/anticipate) Gandalf delivers. */
export const IDEATION_FIELDS = [
  'brainstorm', 'brainstormed_ideas', 'new_idea', 'new_ideas', 'novel_idea', 'novel_ideas',
  'generated_ideas', 'idea_generation', 'divergent_options', 'invented', 'blue_sky', 'novel_extension',
];

/** Predicate (the B1 core): is `item` a divergent/brainstorm "ideate"-class finding — a finding
 *  whose `kind` is an ideation kind, OR which carries a populated idea-generation field? Pure;
 *  never throws. (Judging whether prose is "genuinely divergent" is the advisory layer's job —
 *  PRINCIPLE-D; the gate owns the structural ideate-class signal.) */
export function isIdeationFinding(item) {
  if (item === null || typeof item !== 'object' || Array.isArray(item)) return false;
  if (typeof item.kind === 'string' && IDEATION_KINDS.includes(item.kind.toLowerCase())) return true;
  return IDEATION_FIELDS.some((f) => isNonEmpty(item[f]));
}

// === B6 — no silent degradation ===============================================================
/** Collect the items that ran DEGRADED (`degraded:true`) across an output's finding/nitpick/
 *  elevation/risk_label arrays. Returns an array of `{ where, item }`. Pure; never throws. */
export function degradedItems(output) {
  const out = [];
  if (output === null || typeof output !== 'object') return out;
  for (const arr of ['findings', 'nitpicks', 'elevations', 'risk_labels']) {
    const items = Array.isArray(output[arr]) ? output[arr] : [];
    items.forEach((item, i) => {
      if (item && typeof item === 'object' && item.degraded === true) out.push({ where: `${arr}[${i}]`, item });
    });
  }
  return out;
}

/** Predicate (the B6 core): does `output` carry a SILENT degradation — at least one item ran
 *  `degraded:true` while the top-level output is NOT `degraded:true`? Pure; never throws. */
export function hasSilentDegradation(output) {
  if (output === null || typeof output !== 'object') return false;
  if (output.degraded === true) return false; // the top level owns the degradation ⇒ not silent
  return degradedItems(output).length > 0;
}

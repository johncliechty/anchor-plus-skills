// Gandalf advisor — canary harness foundation (Wave 1 / GATE-0).
//
// This is the SHAPE + RUNG-CONSISTENCY substrate every later wave's canary builds on.
// It owns deterministic, field-level assertions only; label/semantic TRUTH is the
// advisory layer's job (PRINCIPLE-D). Zero external dependencies — it ships a compact
// JSON-Schema-subset validator so `node --test` runs with no install step.
//
// Public surface (consumed by the wave test suites):
//   RUNG_LADDER, TIER_LADDER, VALUE_LADDER, SEVERITY_LADDER  — ordered low→high
//   rungIndex / tierIndex / rungAtLeast / tierAtMost          — ladder helpers
//   isPopulated                                               — "field carries a value"
//   validateShape(output)                                     — → string[] of errors
//   assertSchemaConformant(output)                            — throws on shape error
//   assertReasoningBeforeVerdict(obj, label)                  — key-order invariant
//   assertCaps(output)                                        — nitpick/elevation caps
//   assertRungCeiling(finding, {field, minRung})              — rung-gated field assertion
//   assertDiagnoseCoreProvenance(finding)                     — B5: diagnose exclusive to the core
//   assertDiagnoseSeam(output)                                — B5 over every finding in an output
//   assertTierCeiling(item, {cross_model, where})             — B-ceiling on one tier-bearing item
//   assertCeiling(output)                                     — B-ceiling over an output (W3)
//   assertSituateScoreCeiling(finding)                        — SITUATE no self-CORROBORATED (W3)
//   assertSituateSeam(output)                                 — SITUATE cap over every finding (W3)
//   assertHonestRefutation(elevation)                         — B-honesty on one elevation (W4)
//   assertRefutationSeam(output)                              — B-honesty over every elevation (W4)
//   assertBoundedPremortem(finding)                           — B3: premortem ≠ Oranges-engine (W5)
//   assertForwardLooking(finding)                             — B9: not-yet-present future-state (W5)
//   assertAnticipateSeam(output)                              — B3+B9 over every anticipate finding (W5)
//   assertNoIdeation(finding)                                 — B1: zero ideation (ideation is Jumper's) (W6)
//   assertNoSilentDegradation(output)                         — B6: no per-item degraded under top-level clean (W6)
//   assertHonestSynthesis(output)                             — B8: every leg labelled, rung ≤ envelope (W6)
//   assertScoreLabelSeam(output)                              — B1+B6+B8 over a whole output (W6)
//   assertIncrement1Conformant(output)                        — the FULL Increment-1 canary set (W7)
//   assertConformant(output)                                  — umbrella: shape + order + caps
//   SCHEMA, CONSTANTS                                         — the committed artifacts

import SCHEMA from '../schema/advisor-output.schema.json' with { type: 'json' };
import CONSTANTS from '../prereg-constants.json' with { type: 'json' };
import { GANDALF_CORE_PROTOCOL, EXTERNAL_COMMISSION_FIELDS } from '../seam/diagnose-core.mjs';
import { SITUATE_KIND, SITUATE_SELF_MAX_RUNG } from '../seam/situate.mjs';
import {
  firesRefuter,
  isNamedDefeater,
  hasNoIndependentRefutationStamp,
  NO_INDEPENDENT_REFUTATION_STAMP,
} from '../seam/refute.mjs';
import {
  ANTICIPATE_KIND,
  BOUNDED_SUBJECT_CARDINALITY,
  ORANGES_ENGINE_FIELDS,
  hasOrangesEngineField,
  isForwardLookingAnticipation,
} from '../seam/anticipate.mjs';
import {
  isIdeationFinding,
  hasSilentDegradation,
  degradedItems,
  legsPresent,
  legEnvelopeRung,
} from '../seam/score-label.mjs';

export { SCHEMA, CONSTANTS };

// --- Ladders (low → high). Schema enums mirror these; harness.test.mjs asserts agreement. ---
export const RUNG_LADDER = ['REFUTED', 'UNVERIFIED', 'CLAIMED', 'CORROBORATED', 'OBSERVED'];
export const TIER_LADDER = ['SPECULATIVE', 'PROMISING', 'GROUNDED'];
export const VALUE_LADDER = ['low', 'medium', 'high'];
export const SEVERITY_LADDER = ['minor', 'major', 'critical'];

export function rungIndex(rung) {
  const i = RUNG_LADDER.indexOf(rung);
  if (i === -1) throw new Error(`harness: unknown rung ${JSON.stringify(rung)}`);
  return i;
}
export function tierIndex(tier) {
  const i = TIER_LADDER.indexOf(tier);
  if (i === -1) throw new Error(`harness: unknown tier ${JSON.stringify(tier)}`);
  return i;
}
export function rungAtLeast(rung, minRung) {
  return rungIndex(rung) >= rungIndex(minRung);
}
export function tierAtMost(tier, maxTier) {
  return tierIndex(tier) <= tierIndex(maxTier);
}

// A field "carries a value" (is gated) when present and non-empty.
export function isPopulated(v) {
  if (v === undefined || v === null) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === 'string') return v.trim() !== '';
  if (typeof v === 'object') return Object.keys(v).length > 0;
  return true; // numbers, booleans
}

// --- Zero-dependency JSON-Schema-subset validator -------------------------------------
// Supports: type (string|array), required, properties, items, enum, const,
// minimum/maximum, minItems/maxItems, additionalProperties:false. No $ref (schema is inlined).
function typeOk(value, t) {
  switch (t) {
    case 'string': return typeof value === 'string';
    case 'boolean': return typeof value === 'boolean';
    case 'number': return typeof value === 'number';
    case 'integer': return typeof value === 'number' && Number.isInteger(value);
    case 'array': return Array.isArray(value);
    case 'object': return value !== null && typeof value === 'object' && !Array.isArray(value);
    case 'null': return value === null;
    default: throw new Error(`harness: unsupported schema type ${JSON.stringify(t)}`);
  }
}
function describe(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  return typeof v;
}
function validate(value, schema, path, errors) {
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((t) => typeOk(value, t))) {
      errors.push(`${path}: expected type ${types.join('|')}, got ${describe(value)}`);
      return; // type mismatch — deeper checks would be noise
    }
  }
  if (schema.const !== undefined && value !== schema.const) {
    errors.push(`${path}: expected const ${JSON.stringify(schema.const)}, got ${JSON.stringify(value)}`);
  }
  if (schema.enum !== undefined && !schema.enum.includes(value)) {
    errors.push(`${path}: ${JSON.stringify(value)} not in enum [${schema.enum.join(', ')}]`);
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${path}: ${value} < minimum ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(`${path}: ${value} > maximum ${schema.maximum}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) errors.push(`${path}: ${value.length} items < minItems ${schema.minItems}`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) errors.push(`${path}: ${value.length} items > maxItems ${schema.maxItems}`);
    if (schema.items) value.forEach((v, i) => validate(v, schema.items, `${path}[${i}]`, errors));
  }
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    if (schema.required) {
      for (const k of schema.required) if (!(k in value)) errors.push(`${path}: missing required key '${k}'`);
    }
    if (schema.properties) {
      for (const [k, sub] of Object.entries(schema.properties)) if (k in value) validate(value[k], sub, `${path}.${k}`, errors);
    }
    if (schema.additionalProperties === false && schema.properties) {
      for (const k of Object.keys(value)) if (!(k in schema.properties)) errors.push(`${path}: unexpected key '${k}'`);
    }
  }
}

/** Validate an advisor output against the committed typed schema. Returns an array of
 *  error strings (empty array ⇒ shape-conformant). Pure; never throws on data. */
export function validateShape(output, schema = SCHEMA) {
  const errors = [];
  validate(output, schema, '$', errors);
  return errors;
}

export function assertSchemaConformant(output) {
  const errors = validateShape(output);
  if (errors.length) {
    throw new Error(`schema-conformance FAILED:\n  - ${errors.join('\n  - ')}`);
  }
}

// --- reasoning-before-verdict invariant ------------------------------------------------
/** Assert that, in `obj`'s own key order, 'reasoning' appears before 'verdict' and both
 *  are present. JS preserves string-key insertion order, so this is deterministic. */
export function assertReasoningBeforeVerdict(obj, label = '$') {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new Error(`reasoning-before-verdict: ${label} is not an object`);
  }
  const keys = Object.keys(obj);
  const r = keys.indexOf('reasoning');
  const v = keys.indexOf('verdict');
  if (r === -1) throw new Error(`reasoning-before-verdict: ${label} missing 'reasoning'`);
  if (v === -1) throw new Error(`reasoning-before-verdict: ${label} missing 'verdict'`);
  if (r > v) throw new Error(`reasoning-before-verdict: ${label} has 'verdict' (pos ${v}) before 'reasoning' (pos ${r})`);
}

// --- nitpick / elevation caps ----------------------------------------------------------
export function assertCaps(output) {
  const { max_nitpicks, max_elevations } = CONSTANTS.output_caps;
  const nN = Array.isArray(output.nitpicks) ? output.nitpicks.length : 0;
  const nE = Array.isArray(output.elevations) ? output.elevations.length : 0;
  if (nN > max_nitpicks) throw new Error(`nitpick cap exceeded: ${nN} > ${max_nitpicks}`);
  if (nE > max_elevations) throw new Error(`elevation cap exceeded: ${nE} > ${max_elevations}`);
}

// --- rung-gated field assertion (the core Wave-1 capability) ----------------------------
/** Assert that a rung-gated field obeys its rung ceiling: if `finding[field]` carries a
 *  value, the finding's rung must be at or above `minRung` on the evidence ladder.
 *  A finding that asserts a higher-evidence field while sitting on a lower rung FAILS
 *  (this is the field-level, rung-gated assertion the harness is built to support). */
export function assertRungCeiling(finding, { field, minRung }) {
  if (finding === null || typeof finding !== 'object') {
    throw new Error(`rung-ceiling: target is not an object`);
  }
  rungIndex(minRung); // validate minRung is a known rung
  if (!isPopulated(finding[field])) return; // field absent ⇒ nothing gated
  const rung = finding.rung;
  if (rung === undefined) {
    throw new Error(`rung-ceiling: finding populates '${field}' but carries no rung`);
  }
  if (!rungAtLeast(rung, minRung)) {
    throw new Error(
      `rung-ceiling: finding '${finding.id ?? '?'}' populates '${field}' (requires rung ≥ ${minRung}) but is at rung ${rung}`
    );
  }
}

// --- B5: diagnose exclusive to the vetted core (the Wave-2 capability) -------------------
/** B5 (diagnose exclusive to core). Assert that a `kind:'diagnose'` finding came from the
 *  vetted diagnose core (PROTOCOL v2), not re-derived inline and not sourced from a
 *  commissioned skill. A diagnose finding FAILS when it: (a) carries no `gandalf_core`
 *  provenance, (b) carries a `gandalf_core` envelope that does not name the vetted-core
 *  protocol (re-derived inline / foreign source), or (c) carries an external commission id.
 *  Non-diagnose findings are not gated by B5 (their provenance is a later wave's seam). */
export function assertDiagnoseCoreProvenance(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) {
    throw new Error('B5 diagnose-provenance: target is not an object');
  }
  if (finding.kind !== 'diagnose') return; // only diagnose findings are gated by B5
  const id = finding.id ?? '?';
  const prov = finding.gandalf_core;
  if (!isPopulated(prov)) {
    throw new Error(`B5 diagnose-provenance: diagnose finding '${id}' carries no gandalf_core provenance (re-derived inline?)`);
  }
  const protocol = typeof prov === 'object' && !Array.isArray(prov) ? prov.protocol : prov;
  if (protocol !== GANDALF_CORE_PROTOCOL) {
    throw new Error(
      `B5 diagnose-provenance: diagnose finding '${id}' gandalf_core provenance is not the vetted core (${GANDALF_CORE_PROTOCOL}); got ${JSON.stringify(protocol)} (re-derived inline / foreign source)`
    );
  }
  for (const f of EXTERNAL_COMMISSION_FIELDS) {
    if (isPopulated(finding[f])) {
      throw new Error(`B5 diagnose-provenance: diagnose finding '${id}' carries external commission id '${f}' — diagnosis is exclusive to the vetted core`);
    }
  }
}

/** Apply B5 to every finding in an advisor output: the vetted diagnose core is the SOLE
 *  diagnosis source, so no `kind:'diagnose'` finding may exist without vetted-core
 *  provenance. Throws on the first violation. */
export function assertDiagnoseSeam(output) {
  const findings = Array.isArray(output?.findings) ? output.findings : [];
  findings.forEach((f) => assertDiagnoseCoreProvenance(f));
}

// --- B-ceiling: single-family ⇒ max tier PROMISING (the Wave-3 capability) ----------------
/** B-ceiling on a single tier-bearing item (elevation or risk_label). On a single-family run
 *  (`cross_model:false`) the max achievable tier is PROMISING — the deterministic embodiment
 *  of the CBS-5 re-stamp: a GROUNDED stamp is unreachable without a cross-family refuter, so
 *  it FAILS. When the run is NOT single-family (cross_model !== false) the ceiling does not
 *  bite. An item with no `tier` is not gated. `where` labels the failure site. */
export function assertTierCeiling(item, { cross_model, where = 'item' } = {}) {
  if (cross_model !== false) return; // ceiling only bites on a single-family substrate
  if (item === null || typeof item !== 'object') return;
  const tier = item.tier;
  if (tier === undefined) return;
  if (!tierAtMost(tier, 'PROMISING')) {
    throw new Error(
      `B-ceiling: ${where} is stamped ${tier} on a cross_model:false run — the single-family substrate ceiling is PROMISING (GROUNDED is unreachable without a cross-family refuter)`
    );
  }
}

/** B-ceiling over a whole advisor output: when the run is single-family
 *  (`output.cross_model === false`), NO elevation and NO risk_label may be stamped GROUNDED;
 *  the max achievable tier is PROMISING. Throws on the first violation. */
export function assertCeiling(output) {
  const cross_model = output?.cross_model;
  const elevations = Array.isArray(output?.elevations) ? output.elevations : [];
  elevations.forEach((e, i) =>
    assertTierCeiling(e, { cross_model, where: `elevations[${i}] '${e?.id ?? '?'}'` })
  );
  const riskLabels = Array.isArray(output?.risk_labels) ? output.risk_labels : [];
  riskLabels.forEach((r, i) =>
    assertTierCeiling(r, { cross_model, where: `risk_labels[${i}] leg '${r?.leg ?? '?'}'` })
  );
}

// --- SITUATE honesty cap: no self-CORROBORATED (the Wave-3 capability) ---------------------
/** The SITUATE scoring cap. A `kind:'situate'` finding's facts come from a commissioned
 *  researchPrime; on a single-family substrate that commission is same-family and earns NO
 *  independent-origin credit, so the finding may NOT self-corroborate. This asserts:
 *    (a) NO self-CORROBORATED — a situate finding at rung ≥ CORROBORATED must carry
 *        `independent_origin:true` (only a cross-family commission earns it); otherwise it is
 *        capped at SITUATE_SELF_MAX_RUNG (CLAIMED) and FAILS here; and
 *    (b) unverifiable ⇒ handoff — a situate finding whose `facts_verified` is false must carry
 *        a `needs_verification` researchPrime handoff (the unverifiable fact is routed out,
 *        never asserted as real).
 *  Non-situate findings are not gated (their provenance is another leg's seam). */
export function assertSituateScoreCeiling(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) {
    throw new Error('B-situate: target is not an object');
  }
  if (finding.kind !== SITUATE_KIND) return; // only situate findings are gated here
  const id = finding.id ?? '?';
  const independent = finding.independent_origin === true;
  const rung = finding.rung;
  // (a) no self-CORROBORATED: without independent origin, the rung is capped at CLAIMED.
  if (!independent && rung !== undefined && rungAtLeast(rung, 'CORROBORATED')) {
    throw new Error(
      `B-situate: situate finding '${id}' is stamped ${rung} with no independent-origin credit — no self-CORROBORATED (a same-family commission caps the rung at ${SITUATE_SELF_MAX_RUNG})`
    );
  }
  // (b) unverifiable ⇒ researchPrime needs_verification handoff.
  if (finding.facts_verified === false && !isPopulated(finding.needs_verification)) {
    throw new Error(
      `B-situate: situate finding '${id}' has unverified facts but carries no needs_verification handoff (an unverifiable correspondence must be routed to a researchPrime handoff, not asserted as real)`
    );
  }
}

/** Apply the SITUATE cap to every finding in an advisor output. Throws on the first
 *  violation; an output with no situate findings trivially passes. */
export function assertSituateSeam(output) {
  const findings = Array.isArray(output?.findings) ? output.findings : [];
  findings.forEach((f) => assertSituateScoreCeiling(f));
}

// --- B-honesty: the NS4 refutation-discipline spine (the Wave-4 capability) ----------------
/** B-honesty on a single elevation. NS4: a vetted suggestion above the SPECULATIVE floor must
 *  have survived an INDEPENDENT named-defeater refutation. This asserts, deterministically:
 *    • BELOW the refuter-firing threshold (value_if_true < high AND severity < major): the
 *      elevation gets no independent refuter, so it must ship SPECULATIVE carrying the
 *      "no independent refutation ran" stamp — being stamped above SPECULATIVE FAILS, and a
 *      SPECULATIVE one with no stamp FAILS (no silent drop);
 *    • FIRES the threshold and stamped SPECULATIVE: it is the honest un-refuted floor and must
 *      carry the stamp (else FAIL); and
 *    • FIRES the threshold and stamped above SPECULATIVE: it must carry a NAMED concrete
 *      defeater (`what_would_refute_it`, not a self-rated confidence word) AND a
 *      `refutation_provenance` envelope (an independent refuter ran) — else it FAILS
 *      (auto-downgrade to SPECULATIVE; see seam/refute.mjs `vetElevationRefutation`).
 *  An item with no `tier` is not gated (not a tier-bearing elevation). */
export function assertHonestRefutation(elevation) {
  if (elevation === null || typeof elevation !== 'object' || Array.isArray(elevation)) {
    throw new Error('B-honesty: target is not an object');
  }
  const tier = elevation.tier;
  if (tier === undefined) return; // not a tier-bearing elevation
  tierIndex(tier); // validate the tier is a known tier
  const id = elevation.id ?? '?';
  const fires = firesRefuter(elevation);
  const aboveFloor = !tierAtMost(tier, 'SPECULATIVE');

  if (!fires) {
    // Below the firing threshold: no independent refuter runs ⇒ ship SPECULATIVE + the stamp.
    if (aboveFloor) {
      throw new Error(
        `B-honesty: elevation '${id}' is below the refuter-firing threshold (value_if_true < high and severity < major) but is stamped ${tier} above SPECULATIVE — a below-threshold finding earns no independent refuter and must ship SPECULATIVE with the "${NO_INDEPENDENT_REFUTATION_STAMP}" stamp`
      );
    }
    if (!hasNoIndependentRefutationStamp(elevation)) {
      throw new Error(
        `B-honesty: elevation '${id}' ships SPECULATIVE (no independent refuter fired) but carries no "${NO_INDEPENDENT_REFUTATION_STAMP}" stamp (no silent drop)`
      );
    }
    return;
  }

  // Fires the threshold but stamped at the floor: the honest un-refuted floor must be stamped.
  if (!aboveFloor) {
    if (!hasNoIndependentRefutationStamp(elevation)) {
      throw new Error(
        `B-honesty: elevation '${id}' is SPECULATIVE but carries no "${NO_INDEPENDENT_REFUTATION_STAMP}" stamp (a high-value elevation that did not survive an independent refuter must be stamped, not silently dropped)`
      );
    }
    return;
  }

  // Fires the threshold and stamped above SPECULATIVE: requires a named defeater + provenance.
  if (!isNamedDefeater(elevation.what_would_refute_it)) {
    throw new Error(
      `B-honesty: elevation '${id}' is stamped ${tier} but its what_would_refute_it is a self-rated confidence word / empty, not a NAMED concrete defeater — FAILS (auto-downgrade to SPECULATIVE)`
    );
  }
  if (!isPopulated(elevation.refutation_provenance)) {
    throw new Error(
      `B-honesty: elevation '${id}' is stamped ${tier} but carries no refutation_provenance (no INDEPENDENT named-defeater refuter ran) — FAILS (auto-downgrade to SPECULATIVE)`
    );
  }
}

/** Apply B-honesty to every elevation in an advisor output. Throws on the first violation; an
 *  output with no elevations trivially passes. */
export function assertRefutationSeam(output) {
  const elevations = Array.isArray(output?.elevations) ? output.elevations : [];
  elevations.forEach((e) => assertHonestRefutation(e));
}

// --- B3: bounded premortem ≠ Crucible's Oranges-engine (the Wave-5 capability) -------------
/** B3 on a single anticipate finding. Gandalf's ANTICIPATE is a BOUNDED premortem on a SINGLE
 *  effort (subject_cardinality == 1), NOT Crucible's multi-plan counterfactual-cost engine. A
 *  `kind:'anticipate'` finding FAILS B3 when it carries a regret/counterfactual-cost field
 *  (ORANGES_ENGINE_FIELDS) OR `subject_cardinality > 1` — that work is Crucible's, so it routes to
 *  a Crucible commission (seam/anticipate.mjs `commissionCrucible`). Non-anticipate findings are
 *  not gated by B3. (Cross-path cost reasoning carried only in PROSE is the advisory layer's job —
 *  `flagCrossPathCostReasoning`, isolated from this gate by PRINCIPLE-D.) */
export function assertBoundedPremortem(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) {
    throw new Error('B3 bounded-premortem: target is not an object');
  }
  if (finding.kind !== ANTICIPATE_KIND) return; // only anticipate findings are gated by B3
  const id = finding.id ?? '?';
  if (finding.subject_cardinality !== undefined && finding.subject_cardinality !== BOUNDED_SUBJECT_CARDINALITY) {
    throw new Error(
      `B3 bounded-premortem: anticipate finding '${id}' has subject_cardinality ${JSON.stringify(finding.subject_cardinality)} (≠ ${BOUNDED_SUBJECT_CARDINALITY}) — a multi-path read is Crucible's Oranges-engine; route to a Crucible commission`
    );
  }
  for (const f of ORANGES_ENGINE_FIELDS) {
    if (isPopulated(finding[f])) {
      throw new Error(
        `B3 bounded-premortem: anticipate finding '${id}' carries the regret/counterfactual-cost field '${f}' — counterfactual-cost-across-paths is Crucible's engine, not Gandalf's bounded premortem; route to a Crucible commission`
      );
    }
  }
}

// --- B9: an anticipation is a not-yet-present future-state (the Wave-5 capability) ----------
/** B9 on a single anticipate finding. NS3: an anticipation surfaces a COMING problem — a
 *  not-yet-present `future_state_condition` plus the `enabling_assumption` that would bring it on.
 *  A `kind:'anticipate'` finding FAILS B9 when it is PRESENT-TENSE — it lacks a populated,
 *  well-formed future-state condition + enabling assumption (per seam/anticipate.mjs
 *  `isForwardLookingAnticipation`). Non-anticipate findings are not gated by B9. */
export function assertForwardLooking(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) {
    throw new Error('B9 forward-looking: target is not an object');
  }
  if (finding.kind !== ANTICIPATE_KIND) return; // only anticipate findings are gated by B9
  const id = finding.id ?? '?';
  if (!isForwardLookingAnticipation(finding)) {
    throw new Error(
      `B9 forward-looking: anticipate finding '${id}' is present-tense — it carries no populated, well-formed future_state_condition + enabling_assumption (an anticipation is a not-yet-present future state, never a present-tense observation)`
    );
  }
}

/** Apply B3 + B9 to every finding in an advisor output: every `kind:'anticipate'` finding must be
 *  a bounded premortem (B3) AND forward-looking (B9). Throws on the first violation; an output
 *  with no anticipate findings trivially passes. */
export function assertAnticipateSeam(output) {
  const findings = Array.isArray(output?.findings) ? output.findings : [];
  findings.forEach((f) => {
    assertBoundedPremortem(f);
    assertForwardLooking(f);
  });
}

// --- B1: zero ideation — Gandalf does not brainstorm (the Wave-6 capability) ---------------
/** B1 on a single item. NS6 anti-drift: Gandalf's value is INSIGHT (understand / situate /
 *  anticipate), NOT the open-ended generation of new ideas/extensions — that is Jumper's. An
 *  "ideate"-class item (a divergent/brainstorm `kind`, or a finding carrying an idea-generation
 *  field, per seam/score-label.mjs `isIdeationFinding`) FAILS B1. A grounded diagnose/situate/
 *  anticipate finding is not gated. (Judging whether prose is genuinely divergent is the advisory
 *  layer's job — PRINCIPLE-D; the gate owns the structural ideate-class signal.) */
export function assertNoIdeation(item) {
  if (item === null || typeof item !== 'object' || Array.isArray(item)) {
    throw new Error('B1 zero-ideation: target is not an object');
  }
  if (isIdeationFinding(item)) {
    throw new Error(
      `B1 zero-ideation: item '${item.id ?? '?'}' is a divergent/brainstorm ideate-class finding — open-ended idea generation is Jumper's, not Gandalf's (Gandalf delivers grounded insight: understand / situate / anticipate)`
    );
  }
}

/** Apply B1 to every finding AND elevation in an advisor output (the suggestion surfaces where an
 *  ideation drift would land). Throws on the first violation; an output with none trivially passes. */
export function assertNoIdeationSeam(output) {
  const findings = Array.isArray(output?.findings) ? output.findings : [];
  const elevations = Array.isArray(output?.elevations) ? output.elevations : [];
  findings.forEach((f) => assertNoIdeation(f));
  elevations.forEach((e) => assertNoIdeation(e));
}

// --- B6: no silent degradation (the Wave-6 capability) -------------------------------------
/** B6 on a whole output. If any item ran DEGRADED (`degraded:true`), the top-level output MUST own
 *  it (`degraded:true`). A per-item `degraded:true` under a top-level `degraded:false` is a SILENT
 *  degradation and FAILS (per seam/score-label.mjs `hasSilentDegradation`). Throws on the first
 *  offending item; an honest output (top-level owns it, or nothing degraded) passes. */
export function assertNoSilentDegradation(output) {
  if (output === null || typeof output !== 'object' || Array.isArray(output)) {
    throw new Error('B6 no-silent-degradation: target is not an object');
  }
  if (!hasSilentDegradation(output)) return;
  const first = degradedItems(output)[0];
  throw new Error(
    `B6 no-silent-degradation: ${first.where} ('${first.item.id ?? first.item.leg ?? '?'}') ran degraded:true but the top-level output is degraded:false — degradation must be surfaced at the top level, never silent`
  );
}

// --- B8: honest synthesis (the Wave-6 capability) ------------------------------------------
/** B8 on a whole output. Honest synthesis: (a) every leg the run REPORTS (a diagnose/situate/
 *  anticipate finding is present) MUST appear in `risk_labels`; and (b) a risk_label's rung may NOT
 *  exceed its leg's EVIDENTIAL ENVELOPE — the strongest rung any finding in the leg reached (a
 *  synthesis may not claim more evidence than its leg carries — carry rung at-or-below source). A
 *  missing leg OR an over-claiming risk_label FAILS. Throws on the first violation. */
export function assertHonestSynthesis(output) {
  if (output === null || typeof output !== 'object' || Array.isArray(output)) {
    throw new Error('B8 honest-synthesis: target is not an object');
  }
  const riskLabels = Array.isArray(output.risk_labels) ? output.risk_labels : [];
  const labelledLegs = new Set(riskLabels.map((r) => (r && typeof r === 'object' ? r.leg : undefined)));
  // (a) every present leg must be labelled.
  for (const leg of legsPresent(output)) {
    if (!labelledLegs.has(leg)) {
      throw new Error(
        `B8 honest-synthesis: leg '${leg}' is present in the findings but absent from risk_labels — honest synthesis must label every leg it reports (no silent omission)`
      );
    }
  }
  // (b) no risk_label may out-claim its leg's evidential envelope.
  riskLabels.forEach((r, i) => {
    if (r === null || typeof r !== 'object' || r.rung === undefined) return; // no rung ⇒ nothing to over-claim
    const envelope = legEnvelopeRung(output, r.leg);
    if (envelope === null) return; // a label for a leg with no rung-bearing finding — not gated here
    if (rungIndex(r.rung) > rungIndex(envelope)) {
      throw new Error(
        `B8 honest-synthesis: risk_labels[${i}] for leg '${r.leg}' is stamped rung ${r.rung} but the leg's evidential envelope is ${envelope} — a synthesis may not claim more evidence than its leg carries (carry rung at-or-below source)`
      );
    }
  });
}

/** Apply the Wave-6 seam (B1 + B6 + B8) over a whole advisor output. Throws on the first
 *  violation; an honest output passes all three. */
export function assertScoreLabelSeam(output) {
  assertNoIdeationSeam(output);
  assertNoSilentDegradation(output);
  assertHonestSynthesis(output);
}

// --- the Increment-1 integration umbrella (the Wave-7 capability) --------------------------
/** The FULL Increment-1 deterministic canary set over a WHOLE Gandalf v1 advisor output — the
 *  Wave-7 integration gate. This is "the canary set = the test suite" expressed as one call: a
 *  conformant Gandalf v1 output must pass EVERY Increment-1 canary at once. It composes, in order:
 *    • assertConformant      — schema shape + reasoning-before-verdict + nitpick/elevation caps
 *    • assertDiagnoseSeam    — B5  (diagnose exclusive to the vetted core)
 *    • assertSituateSeam     — SITUATE honesty cap (no self-CORROBORATED; unverifiable → handoff)
 *    • assertCeiling         — B-ceiling (single-family ⇒ max tier PROMISING)
 *    • assertRefutationSeam  — B-honesty (named-defeater + provenance, or stamped SPECULATIVE)
 *    • assertAnticipateSeam  — B3 + B9 (bounded premortem; forward-looking future-state)
 *    • assertScoreLabelSeam  — B1 + B6 + B8 (zero ideation; no silent degradation; honest synthesis)
 *  Throws on the FIRST canary a fixture violates. By construction this gate imports NOTHING from the
 *  ADVISORY layer (seam/oracle.mjs, seam/anti-laundering.mjs): the deterministic done-floor is
 *  provably independent of oracle/judge reachability and of the (BLOCKED-this-cycle) content-binding
 *  canaries — PRINCIPLE-D. */
export function assertIncrement1Conformant(output) {
  assertConformant(output);     // schema + reasoning-before-verdict + caps
  assertDiagnoseSeam(output);   // B5
  assertSituateSeam(output);    // SITUATE honesty cap
  assertCeiling(output);        // B-ceiling
  assertRefutationSeam(output); // B-honesty
  assertAnticipateSeam(output); // B3 + B9
  assertScoreLabelSeam(output); // B1 + B6 + B8
}

// --- umbrella conformance check (used by the schema-conformance suite) ------------------
export function assertConformant(output) {
  assertSchemaConformant(output);
  assertReasoningBeforeVerdict(output, '$');
  for (const [arr, name] of [[output.findings, 'findings'], [output.nitpicks, 'nitpicks'], [output.elevations, 'elevations']]) {
    if (Array.isArray(arr)) {
      arr.forEach((item, i) => {
        if (item && typeof item === 'object' && 'reasoning' in item && 'verdict' in item) {
          assertReasoningBeforeVerdict(item, `$.${name}[${i}]`);
        }
      });
    }
  }
  assertCaps(output);
}

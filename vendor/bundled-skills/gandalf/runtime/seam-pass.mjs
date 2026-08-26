// Gandalf runtime host — the deterministic SEAM-PASS composer (Tier-1).
//
// THE MISSING RUNTIME (journal/0001 + LESSONS.md). The first real Gandalf cycles proved the model
// produces excellent DIAGNOSE/SITUATE/ANTICIPATE *content* but, run as pure SKILL.md prose, keeps
// hand-approximating the tier stamps and failing the B-honesty canary. Root cause: the honest tiers +
// refutation stamps are meant to be APPLIED DETERMINISTICALLY by the shipped seams, not produced by
// the model. This module is that wiring: it takes the model's RAW draft (un-stamped findings /
// elevations / diagnosis) and runs it through the already-shipped `seam/*.mjs` to produce a
// canary-conformant, honestly-graded advisor output that passes `assertIncrement1Conformant` by
// construction.
//
// SCOPE = Tier 1 (deterministic), by design (planning/runtime-host/DESCRIPTION.md):
//   • ONE model run, the deterministic seam pass — NO live independent named-defeater refuters and NO
//     researchPrime SITUATE commission (that needs the `agent()` seam the repo flags as the integration
//     point the gate never runs). So every ELEVATION honestly lands at SPECULATIVE carrying the
//     NO_INDEPENDENT_REFUTATION_STAMP — the seam's own honest floor (`vetElevationRefutation`). The
//     live-refuter PROMISING tier is a sequenced follow-on (needs `agent()`). NOT in this effort.
//   • DIAGNOSE findings keep their evidence rungs + `gandalf_core` provenance; `risk_labels` are capped
//     at the single-family PROMISING ceiling (`composeRiskLabels`, cross_model:false). Only REFUTED drops.
//
// REUSES (never forks) the shipped engine — it invents NO grading logic. A malformed/partial raw draft
// produces an HONEST named error (`SeamPassInputError`), never a fabricated finding or a forged output.

import {
  vetElevationRefutation,
} from '../seam/refute.mjs';
import { createCommissionLedger } from '../seam/commission-ledger.mjs';
import {
  labelTier,
  composeRiskLabels,
  dropsFromOutput,
} from '../seam/score-label.mjs';
import { stampDiagnoseCoreProvenance } from '../seam/diagnose-core.mjs';
import { composeAnticipation } from '../seam/anticipate.mjs';
import { composeSituate } from '../seam/situate.mjs';

/** The committed schema version (prereg-constants.json / fixtures.mjs `emptyConformantOutput`). */
export const SCHEMA_VERSION = 'gandalf-advisor-1';

/** Thrown when the supplied raw draft is malformed/partial. A distinct, NAMED class so the host can
 *  fail HONESTLY (no fabricated finding, no forged conformant output) and the caller can discriminate
 *  an input problem from an internal seam failure. */
export class SeamPassInputError extends Error {
  constructor(message) {
    super(`SeamPassInputError: ${message}`);
    this.name = 'SeamPassInputError';
  }
}

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}
function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}

const _RUNGS = ['REFUTED', 'UNVERIFIED', 'CLAIMED', 'CORROBORATED', 'OBSERVED'];
const _VALUES = ['low', 'medium', 'high'];
const _SEVERITIES = ['minor', 'major', 'critical'];
const _KINDS = ['diagnose', 'situate', 'anticipate', 'nitpick'];
// Real models reach for reasonable SYNONYMS the committed enum doesn't list
// (e.g. severity "moderate"/"info"). Map the common ones to the nearest committed
// value; an unmappable value is dropped (the field is optional) rather than failing
// the whole read on a strict enum reject.
const _SEVERITY_SYNONYMS = {
  moderate: 'major', medium: 'major', med: 'major', high: 'critical',
  severe: 'critical', blocker: 'critical', fatal: 'critical',
  info: 'minor', informational: 'minor', note: 'minor', nit: 'minor',
  low: 'minor', trivial: 'minor', cosmetic: 'minor',
};
function _asString(v) {
  return typeof v === 'string' ? v : (v === undefined || v === null ? '' : String(v));
}

/** Coerce ONE item to the schema's required-key shape AND sanitize its enum fields, WITHOUT inventing
 *  content: a missing/blank id gets a stable positional id; a missing/invalid rung honestly defaults to
 *  UNVERIFIED; reasoning + verdict are guaranteed present as strings (preserving the reasoning-BEFORE-
 *  verdict key order the canary enforces); an out-of-enum `severity` is mapped from a known synonym
 *  (moderate→major, info→minor, …) or dropped; an out-of-enum `kind` is dropped (→ a generic finding).
 *  Every other key (gandalf_core, future_state_condition, tier, value_if_true, …) is kept. THIS is what
 *  makes the host robust to a real model run that omits a field OR uses an off-enum synonym on an item —
 *  the read survives instead of the whole run failing on a strict-validation reject. */
function ensureItemKeys(item, index, prefix) {
  const id = isNonEmptyString(item.id) ? item.id : `${prefix}${index}`;
  const rung = _RUNGS.includes(item.rung) ? item.rung : 'UNVERIFIED';
  const rest = { ...item };
  delete rest.id; delete rest.rung; delete rest.reasoning; delete rest.verdict;
  // Sanitize enum fields the committed schema would reject (preserve the item, not the bad value).
  if ('severity' in rest) {
    const s = typeof rest.severity === 'string' ? rest.severity.toLowerCase().trim() : '';
    if (_SEVERITIES.includes(s)) rest.severity = s;
    else if (_SEVERITY_SYNONYMS[s]) rest.severity = _SEVERITY_SYNONYMS[s];
    else delete rest.severity; // unknown → drop (optional field)
  }
  if ('kind' in rest && !_KINDS.includes(rest.kind)) delete rest.kind; // invalid kind → generic finding
  // id, rung, then the rest, then reasoning, then verdict (reasoning before verdict — load-bearing).
  return { id, rung, ...rest, reasoning: _asString(item.reasoning), verdict: _asString(item.verdict) };
}

/** Validate the RAW draft shape. We require only the structural minimum a read needs — a plain object
 *  with a non-empty `reasoning` + `verdict` (the headline a real model reliably emits). The three item
 *  arrays are COERCED to [] when absent (a model that emits no nitpicks is not an error) and each item
 *  is normalized per-item below, so an imperfect-but-real draft yields a graded read rather than a
 *  whole-run failure. Genuinely empty/garbage input still fails honestly (SeamPassInputError). */
function validateRawDraft(rawDraft) {
  if (!isPlainObject(rawDraft)) {
    throw new SeamPassInputError('the raw draft must be a plain object (got ' + (rawDraft === null ? 'null' : Array.isArray(rawDraft) ? 'array' : typeof rawDraft) + ')');
  }
  if (!isNonEmptyString(rawDraft.reasoning)) {
    throw new SeamPassInputError("the raw draft must carry a non-empty 'reasoning' string (reasoning-before-verdict)");
  }
  if (!isNonEmptyString(rawDraft.verdict)) {
    throw new SeamPassInputError("the raw draft must carry a non-empty 'verdict' string");
  }
}

/** True iff `item` ran degraded. */
function itemDegraded(item) {
  return isPlainObject(item) && item.degraded === true;
}

/** Turn ONE raw finding into its seam-stamped, schema-conformant finding by `kind`. Throws
 *  SeamPassInputError on a malformed finding (a non-object, or one the seam refuses) — never fabricates. */
function passFinding(raw, index) {
  if (!isPlainObject(raw)) {
    throw new SeamPassInputError(`findings[${index}] is not an object`);
  }
  const kind = raw.kind;
  try {
    if (kind === 'diagnose') {
      // The vetted-core diagnosis keeps its rung; the seam appends gandalf_core provenance.
      return stampDiagnoseCoreProvenance(raw);
    }
    if (kind === 'anticipate') {
      // composeAnticipation enforces subject_cardinality:1 + a populated future-state + enabling
      // assumption (B3 + B9), and refuses any Oranges-engine field. It mints a FRESH finding from
      // the raw stages, so we pass the raw fields straight through.
      const composed = composeAnticipation({
        id: raw.id,
        future_state_condition: raw.future_state_condition,
        enabling_assumption: raw.enabling_assumption,
        reasoning: raw.reasoning,
        verdict: raw.verdict,
        rung: raw.rung ?? 'UNVERIFIED',
        severity: raw.severity,
      });
      // Preserve an honest per-item degraded flag the seam does not carry (B6 rolls it up).
      if (raw.degraded === true) composed.degraded = true;
      return composed;
    }
    if (kind === 'situate') {
      // composeSituate runs the SITUATE honesty caps (no self-CORROBORATED; unverifiable → handoff).
      // Tier-1 has no live researchPrime commission, so facts_verified is false by construction and
      // the seam attaches the needs_verification handoff itself.
      const composed = composeSituate({
        id: raw.id,
        abstraction: raw.abstraction,
        commission: raw.commission,
        structure_map: raw.structure_map,
        outside_view_base_rate: raw.outside_view_base_rate,
        reasoning: raw.reasoning,
        verdict: raw.verdict,
        facts_verified: false, // Tier-1: no independent commission ran ⇒ never self-verified
      });
      if (raw.degraded === true) composed.degraded = true;
      return composed;
    }
    // Any other finding kind (incl. a bare nitpick-shaped finding) passes through untouched — the
    // schema only gates diagnose/situate/anticipate provenance.
    return { ...raw };
  } catch (err) {
    if (err instanceof SeamPassInputError) throw err;
    // The seam refused this item (e.g. an anticipate finding missing its future-state, or a situate
    // finding missing its structure map) — a real model draft will sometimes do this. Don't fail the
    // whole run: PRESERVE the content as a GENERIC finding (strip the leg `kind` + any half-formed
    // provenance so no leg-specific canary applies); it is normalized to the required keys downstream.
    const { kind: _k, gandalf_core: _gc, ...generic } = raw;
    return generic;
  }
}

/** Turn ONE raw elevation into its seam-graded elevation. Every elevation runs through
 *  `vetElevationRefutation`: an honestly-refuted elevation keeps its tier and gets its DERIVED
 *  `cross_family_refuted` flag (from the injected ledger resolver); an un-refuted one downgrades to
 *  SPECULATIVE + the no-independent-refutation stamp.
 *
 *  W2b: the tier ceiling is keyed off the DERIVED per-elevation cross-family eligibility, NOT any
 *  caller flag. `labelTier` is called with `cross_model: <the elevation's own derived eligibility>`,
 *  so ONLY an elevation with a genuine ledger-bound, family-distinct, digest-matched refutation may
 *  reach the cross-family (GROUNDED) tier; every other elevation is capped at PROMISING. Returns null
 *  when the elevation drops (rung REFUTED). Throws on a non-object. */
function passElevation(raw, index, resolveCommission) {
  if (!isPlainObject(raw)) {
    throw new SeamPassInputError(`elevations[${index}] is not an object`);
  }
  // Only REFUTED drops (the single drop condition).
  if (dropsFromOutput(raw)) return null;
  const degraded = raw.degraded === true;
  let vetted = vetElevationRefutation(raw, { resolveCommission });
  // DERIVED cross-family eligibility — the SOLE key to the GROUNDED ceiling (never the caller flag).
  const crossFamilyEligible = vetted.cross_family_refuted === true;
  const { dropped, tier } = labelTier(vetted, { cross_model: crossFamilyEligible });
  if (dropped) return null;
  const out = { ...vetted, tier };
  if (degraded) out.degraded = true;
  return out;
}

/**
 * applySeamPass — the deterministic Tier-1 host composer.
 *
 * Turn a model's RAW draft ({ reasoning, verdict, findings[], nitpicks[], elevations[] } with
 * un-stamped items) into a canary-conformant, honestly-graded advisor output by applying ONLY the
 * shipped seams. PURE (returns a fresh object; does not mutate `rawDraft`). Single-family by default
 * (cross_model:false) ⇒ the PROMISING ceiling.
 *
 * W2b ANTI-OVERCLAIM DERIVATION: the top-level `cross_model` stamp is DERIVED, never caller-set. It
 * is true IFF at least one shipped elevation carries a genuine ledger-bound, family-distinct,
 * digest-matched refutation (its DERIVED `cross_family_refuted` flag from vetElevationRefutation).
 * The incoming `cross_model` flag is an INTENT only — recorded as `cross_model_requested` — and can
 * NEVER by itself set the output stamp true or lift any tier ceiling.
 *
 * PER-RUN LEDGER (replay-hardening): when no `resolveCommission` is injected, this run instantiates a
 * FRESH ledger via createCommissionLedger() and threads ITS resolver — NEVER the module-default
 * singleton. This kills the cross-run state leak (an id minted on the shared singleton by one run can
 * never resolve inside another). The fresh ledger's minted-this-run set is empty until the live minter
 * lands (W3), so a Tier-1 run authenticates nothing — the honest single-family behavior — while W3's
 * minter will mint on THIS same per-run ledger. A test may inject a stub via `opts.resolveCommission`.
 *
 * @param {object} rawDraft
 * @param {{cross_model?: boolean, resolveCommission?: Function}} [opts]
 * @returns {object} a conformant output that passes `assertIncrement1Conformant`.
 * @throws {SeamPassInputError} on a malformed/partial draft — no partial output is returned.
 */
export function applySeamPass(rawDraft, { cross_model = false, resolveCommission } = {}) {
  validateRawDraft(rawDraft);
  const crossModelRequested = cross_model === true; // the caller INTENT — never the stamp itself
  // A FRESH per-run ledger (no module-default singleton state leak). The injection seam wins: tests and
  // future callers may pass an explicit resolver; otherwise this run resolves against its own ledger.
  const resolve = typeof resolveCommission === 'function'
    ? resolveCommission
    : createCommissionLedger().resolveCommission;

  // The three item arrays are coerced to [] when the model omitted them (lenient input).
  const rawFindings = Array.isArray(rawDraft.findings) ? rawDraft.findings : [];
  const rawNitpicks = Array.isArray(rawDraft.nitpicks) ? rawDraft.nitpicks : [];
  const rawElevations = Array.isArray(rawDraft.elevations) ? rawDraft.elevations : [];

  // --- findings: dispatch by kind through the shipped seams; drop only REFUTED -----------------
  // 2026-08-25 (John-ratified card — journals 0301/0303: killed/dropped items left NO record,
  // so a kill was indistinguishable from a silent omission — an honesty hole in an honesty
  // engine): every drop is RECORDED with its reason in output.kill_log (below the fold).
  const killLog = { findings: [], nitpicks: [], elevations: [] };
  const briefOf = (raw) => String(raw?.topic ?? raw?.claim ?? raw?.message ?? raw?.id ?? '(untitled)').slice(0, 120);
  const findings = [];
  let anyDegraded = false;
  rawFindings.forEach((raw, i) => {
    if (!isPlainObject(raw)) { killLog.findings.push({ index: i, reason: 'not an object' }); return; }
    if (dropsFromOutput(raw)) { killLog.findings.push({ index: i, brief: briefOf(raw), reason: 'REFUTED — rung refuted by its refutation record' }); return; }
    const passed = passFinding(raw, i); // never throws now (a seam refusal → a generic finding)
    if (itemDegraded(passed)) anyDegraded = true;
    findings.push(ensureItemKeys(passed, i, 'f'));
  });

  // --- nitpicks: normalize to the required keys; skip non-objects; drop REFUTED -----------------
  const nitpicks = [];
  rawNitpicks.forEach((raw, i) => {
    if (!isPlainObject(raw)) { killLog.nitpicks.push({ index: i, reason: 'not an object' }); return; }
    if (dropsFromOutput(raw)) { killLog.nitpicks.push({ index: i, brief: briefOf(raw), reason: 'REFUTED — rung refuted by its refutation record' }); return; }
    if (itemDegraded(raw)) anyDegraded = true;
    nitpicks.push(ensureItemKeys(raw, i, 'n'));
  });

  // --- elevations: vet refutation (SPECULATIVE floor) → label tier; drop REFUTED ----------------
  const elevations = [];
  let anyCrossFamily = false; // W2b: DERIVES the top-level cross_model — set only by a genuine refutation
  rawElevations.forEach((raw, i) => {
    if (!isPlainObject(raw)) { killLog.elevations.push({ index: i, reason: 'not an object' }); return; }
    let passed;
    try {
      passed = passElevation(raw, i, resolve);
    } catch (e) {
      // an un-salvageable elevation is dropped, never fatal to the run — but RECORDED
      killLog.elevations.push({ index: i, brief: briefOf(raw), reason: `un-salvageable: ${e?.message ?? e}` });
      return;
    }
    if (passed === null) {
      // dropped (REFUTED) — record WHY, incl. the refutation's named defeater when present
      const defeater = raw?.refutation_provenance?.defeater ?? null;
      killLog.elevations.push({ index: i, brief: briefOf(raw), reason: 'REFUTED — the named defeater landed', defeater });
      return;
    }
    if (passed.cross_family_refuted === true) anyCrossFamily = true; // a real ledger-bound refutation
    if (itemDegraded(passed)) anyDegraded = true;
    // Guarantee a valid value_if_true (required enum) before normalizing the rest.
    if (!_VALUES.includes(passed.value_if_true)) passed = { ...passed, value_if_true: 'low' };
    elevations.push(ensureItemKeys(passed, i, 'e'));
  });

  // --- assemble the partial output, then synthesize honest risk_labels over it ------------------
  // B6: if any item ran degraded, OR the draft itself declared degraded, the top level owns it.
  const degraded = anyDegraded || rawDraft.degraded === true;

  // W2b: cross_model is DERIVED — true IFF a shipped elevation earned a genuine cross-family
  // refutation. The caller's intent flag is recorded separately and never sets this true.
  const output = {
    schema_version: SCHEMA_VERSION,
    cross_model: anyCrossFamily === true,
    cross_model_requested: crossModelRequested,
    degraded,
    reasoning: rawDraft.reasoning, // reasoning BEFORE verdict (key order is load-bearing)
    verdict: rawDraft.verdict,
    findings,
    nitpicks,
    elevations,
    risk_labels: [], // filled below from the finalized findings
  };
  // composeRiskLabels reads the finalized findings: one label per present leg, envelope rung,
  // PROMISING ceiling on a single-family run.
  output.risk_labels = composeRiskLabels(output);

  // Kill log rides below the fold (additive; schema additionalProperties:true) — John sees
  // WHY each recommendation died, and a kill is never confusable with a silent omission.
  output.kill_log = killLog;

  return output;
}

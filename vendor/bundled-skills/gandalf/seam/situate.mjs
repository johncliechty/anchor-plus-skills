// Gandalf advisor — the SITUATE compose SEAM (Wave 3).
//
// NS2 SITUATE: Gandalf situates the effort in the best-in-class landscape by COMMISSIONING
// researchPrime "where warranted" — it does NOT re-implement research. This module is the
// single seam that runs (and provenances) the SITUATE pipeline:
//
//   S0-abstract → firing gate → commission researchPrime (the bare trio `agent()` seam)
//     → structure-map (≥2 relational correspondences, answer-first) → outside-view base rate
//
// Two honesty invariants are load-bearing here and are enforced at the deterministic gate
// (test/harness.mjs `assertSituateScoreCeiling` + `assertCeiling`), label/semantic TRUTH
// staying the advisory layer's job (PRINCIPLE-D):
//   • SAME-FAMILY ⇒ NO INDEPENDENT-ORIGIN CREDIT. On a single-family substrate
//     (cross_model:false / Fable 5), a researchPrime commission is same-family, so it earns
//     NO independent origin: a SITUATE finding may not SELF-CORROBORATE (cap = CLAIMED), and
//     unverifiable facts are routed to a researchPrime `needs_verification` handoff.
//   • Because the commission is same-family, the resulting elevation's tier ceiling is
//     PROMISING (the B-ceiling canary; GROUNDED is unreachable without a cross-family refuter).
//
// PRINCIPLE-D: the live `agent()` spawn is NOT in the gate. `commissionResearchPrime` mints
// the typed commission ENVELOPE (the seam's deterministic surface); actually dispatching it
// to the trio `agent()` seam is the integration point the deterministic gate never executes.
//
// Public surface:
//   SITUATE_KIND                                   — the finding `kind` for a situate leg
//   PERSONA_FAMILY                                 — single-family substrate marker (Fable 5)
//   FIRING_STAKES_LADDER / MIN_FIRING_STAKES       — firing-gate stakes ordering + floor
//   shouldFireSituate(context)                     — firing gate: commission "where warranted"
//   abstractEffort(effort)                         — S0: the structural skeleton (abstraction)
//   MIN_CORRESPONDENCES                            — structure-map minimum (=2)
//   isWellFormedStructureMap(map)                  — ≥2 answer-first relational correspondences
//   commissionResearchPrime({question, cross_model, commission_id})  — typed commission envelope
//   independentOriginCredit(commission)            — same-family ⇒ false (no independent origin)
//   SITUATE_SELF_MAX_RUNG                          — rung cap for a non-independent situate finding
//   composeSituate(stages)                         — assemble a provenanced, capped situate finding
//   needsVerificationHandoff(finding)              — predicate: carries a researchPrime handoff

/** The finding `kind` for the SITUATE leg. */
export const SITUATE_KIND = 'situate';

/** The single-family persona substrate (cross_model:false). A commission to a same-family
 *  skill earns NO independent-origin credit, which is what caps the SITUATE rung/tier. */
export const PERSONA_FAMILY = 'fable-5';

// --- self-contained helpers (the seam imports nothing; harness.mjs imports the seam) ------
function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}
function isNonEmpty(v) {
  if (v === undefined || v === null) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === 'string') return v.trim() !== '';
  if (typeof v === 'object') return Object.keys(v).length > 0;
  return true; // numbers, booleans
}

// --- the SITUATE firing gate ("where warranted") -----------------------------------------
/** Stakes ladder for the firing gate (low → high). DISTINCT from the refuter-firing
 *  threshold in prereg-constants.json (that gates the Wave-4 refuter, not the commission). */
export const FIRING_STAKES_LADDER = ['low', 'medium', 'high'];
export const MIN_FIRING_STAKES = 'medium';

/** The SITUATE firing gate (NORTH-STAR clause 2: commission researchPrime "where warranted").
 *  Fires only when ALL hold: a central, load-bearing claim is in play; a plausible
 *  better-in-class frame exists; and stakes ≥ medium. Otherwise SITUATE does NOT commission
 *  (no spawn, no elevation) — the cheap-default that keeps the per-run spawn cap honest. */
export function shouldFireSituate(context) {
  if (context === null || typeof context !== 'object') return false;
  const { central_load_bearing_claim, better_in_class_frame, stakes } = context;
  const stakesIdx = FIRING_STAKES_LADDER.indexOf(stakes);
  return (
    Boolean(central_load_bearing_claim) &&
    Boolean(better_in_class_frame) &&
    stakesIdx !== -1 &&
    stakesIdx >= FIRING_STAKES_LADDER.indexOf(MIN_FIRING_STAKES)
  );
}

// --- S0: abstraction ----------------------------------------------------------------------
/** S0-abstract: lift the concrete effort to a structural skeleton (the relational shape the
 *  structure-map will look for correspondences against). Returns a fresh abstraction record;
 *  throws on an empty effort. Kept deliberately thin — the abstraction CONTENT is advisory;
 *  the seam guarantees only that S0 ran and produced a populated skeleton. */
export function abstractEffort(effort) {
  if (!isNonEmptyString(effort)) {
    throw new Error('situate: abstractEffort requires a non-empty effort description');
  }
  return { stage: 'S0-abstract', skeleton: effort.trim() };
}

// --- structure-map (≥2 relational correspondences, answer-first) --------------------------
/** A structure-map must carry at least this many relational correspondences. */
export const MIN_CORRESPONDENCES = 2;

/** Predicate: is `map` a well-formed structure-map? Requires (a) ANSWER-FIRST key order —
 *  the `answer` (the load-bearing correspondence conclusion) precedes the `correspondences`
 *  elaboration; (b) ≥ MIN_CORRESPONDENCES correspondences; and (c) each correspondence is
 *  RELATIONAL — it maps a source RELATION to a target RELATION (`source_relation` →
 *  `target_relation`), not a surface-attribute match. Pure; never throws. */
export function isWellFormedStructureMap(map) {
  if (map === null || typeof map !== 'object' || Array.isArray(map)) return false;
  const keys = Object.keys(map);
  const answerIdx = keys.indexOf('answer');
  const corrIdx = keys.indexOf('correspondences');
  if (answerIdx === -1 || corrIdx === -1) return false;
  if (answerIdx > corrIdx) return false; // not answer-first
  if (!isNonEmptyString(map.answer)) return false;
  const corr = map.correspondences;
  if (!Array.isArray(corr) || corr.length < MIN_CORRESPONDENCES) return false;
  return corr.every(
    (c) =>
      c !== null &&
      typeof c === 'object' &&
      !Array.isArray(c) &&
      isNonEmptyString(c.source_relation) &&
      isNonEmptyString(c.target_relation)
  );
}

// --- commission researchPrime (the bare trio `agent()` seam) ------------------------------
/** Mint a typed researchPrime commission ENVELOPE. This is the deterministic surface of the
 *  bare `agent()` seam: it records WHAT would be dispatched and, crucially, whether the
 *  commission earns INDEPENDENT origin. A commission is independent ONLY when it crosses the
 *  model family (cross_model:true); on the single-family substrate (cross_model:false) it is
 *  same-family and earns no independent origin. `commission_id` is honor-system in
 *  Increment 1 (the unforgeable orchestrator-minted ledger is an external, later dependency).
 *  Throws on an empty question. */
export function commissionResearchPrime({ question, cross_model = false, commission_id = null } = {}) {
  if (!isNonEmptyString(question)) {
    throw new Error('situate: commissionResearchPrime requires a non-empty question');
  }
  const independent = cross_model === true;
  return {
    skill: 'researchPrime',
    question: question.trim(),
    cross_model: Boolean(cross_model),
    origin_family: PERSONA_FAMILY,
    independent_origin: independent,
    researchprime_commission_id: commission_id,
  };
}

/** Does `commission` earn independent-origin credit? True iff it explicitly crossed the model
 *  family. Same-family (cross_model:false) ⇒ false — the anti-laundering "same-family ⇒ no
 *  independent origin" rule, the thing that caps a SITUATE finding's rung/tier. Pure. */
export function independentOriginCredit(commission) {
  return commission !== null && typeof commission === 'object' && commission.independent_origin === true;
}

// --- compose a provenanced, honesty-capped SITUATE finding --------------------------------
/** The rung a SITUATE finding may reach on its OWN (same-family) evidence. Without an
 *  independent-origin commission it cannot self-corroborate, so it caps at CLAIMED. */
export const SITUATE_SELF_MAX_RUNG = 'CLAIMED';

/** Assemble a SITUATE finding from the pipeline stages, applying the honesty caps:
 *  the rung is CORROBORATED only when the commission earned independent origin, else it is
 *  capped at SITUATE_SELF_MAX_RUNG (CLAIMED) — NO self-CORROBORATED. When the underlying
 *  facts are not verified, a `needs_verification` researchPrime handoff is attached (an
 *  unverifiable correspondence is routed out, never asserted as real).
 *
 *  `reasoning` precedes `verdict` in the returned key order (reasoning-before-verdict). The
 *  structure-map and outside-view base rate are validated for well-formedness; throws if the
 *  pipeline is incomplete. Returns a FRESH object. */
export function composeSituate({
  id,
  abstraction,
  commission,
  structure_map,
  outside_view_base_rate,
  reasoning,
  verdict,
  facts_verified = false,
} = {}) {
  if (!isNonEmptyString(id)) throw new Error('situate: composeSituate requires an id');
  if (!isNonEmpty(abstraction)) throw new Error('situate: composeSituate requires an S0 abstraction');
  if (commission === null || typeof commission !== 'object') {
    throw new Error('situate: composeSituate requires a researchPrime commission envelope');
  }
  if (!isWellFormedStructureMap(structure_map)) {
    throw new Error('situate: composeSituate requires a structure-map with ≥2 answer-first relational correspondences');
  }
  if (!isNonEmpty(outside_view_base_rate)) {
    throw new Error('situate: composeSituate requires an outside-view base rate');
  }

  const independent = independentOriginCredit(commission);
  const verified = facts_verified === true;
  // No self-CORROBORATED: only an independent-origin commission lifts the rung above the cap.
  const rung = independent && verified ? 'CORROBORATED' : SITUATE_SELF_MAX_RUNG;

  const finding = {
    id,
    kind: SITUATE_KIND,
    rung,
    reasoning: isNonEmptyString(reasoning) ? reasoning : `SITUATE: structure-mapped against ${commission.question}.`,
    verdict: isNonEmptyString(verdict) ? verdict : structure_map.answer,
    s0_abstraction: abstraction,
    researchprime_commission_id: commission.researchprime_commission_id ?? null,
    independent_origin: independent,
    structure_map,
    outside_view_base_rate,
    facts_verified: verified,
  };
  // Unverifiable facts are routed to a researchPrime verification handoff (never asserted real).
  if (!verified) {
    finding.needs_verification = `route to researchPrime: independently verify the structure-map correspondences and outside-view base rate for '${id}' (single-family substrate earns no independent-origin credit)`;
  }
  return finding;
}

/** Predicate: does `finding` carry a researchPrime `needs_verification` handoff? Pure. */
export function needsVerificationHandoff(finding) {
  return finding !== null && typeof finding === 'object' && isNonEmpty(finding.needs_verification);
}

// Gandalf advisor — the REFUTATION-DISCIPLINE seam (Wave 4 / the NS4 honesty spine).
//
// NS4: a "vetted, value-adding suggestion" must survive an INDEPENDENT named-defeater
// refutation; only the REFUTED is dropped; nothing unverified is asserted as real. This
// module is the single seam that decides, deterministically:
//   • whether an elevation FIRES the refuter (value-if-true ≥ HIGH OR severity ≥ major, from
//     prereg-constants.json) — only those earn an INDEPENDENT named-defeater refuter;
//   • what counts as a NAMED CONCRETE DEFEATER vs a self-rated confidence word — the latter is
//     NOT a refutation, so the B-honesty canary FAILS / auto-downgrades it;
//   • the BOUNDED refuter budget R (=3): requesting independent refuters beyond R HALTs the run
//     for a human (no silent drop); and
//   • the honest un-refuted floor: a finding that did NOT earn an independent refutation ships
//     SPECULATIVE carrying the "no independent refutation ran" stamp.
//
// Two honesty invariants are load-bearing here and are enforced at the deterministic gate
// (test/harness.mjs `assertHonestRefutation` + `assertRefutationSeam`; the budget HALT is a
// NAMED canary over `assertRefuterBudget`), label/semantic TRUTH staying the advisory layer's
// job (PRINCIPLE-D):
//   • NAMED DEFEATER, NOT A CONFIDENCE WORD. An elevation stamped above SPECULATIVE must carry
//     a named concrete defeater (`what_would_refute_it`) plus a `refutation_provenance` proving
//     an independent refuter ran. A self-rated confidence word ("very confident") is not a
//     refutation — B-honesty FAILS it (auto-downgrade to SPECULATIVE + stamp).
//   • BOUNDED BUDGET, NO SILENT DROP. Requesting more than R independent refuters HALTs; it does
//     not silently take the first R. Below-threshold findings ship SPECULATIVE + the stamp.
//
// PRINCIPLE-D: the live refuter `agent()` spawn is NOT in the gate. This seam mints the typed
// refutation ENVELOPE + the budget guard (the deterministic surface); actually dispatching the
// independent refuter to the trio `agent()` seam is the integration point the gate never runs.
//
// Public surface:
//   REFUTER_BUDGET_R                       — the bounded budget (=3, from prereg-constants.json)
//   REFUTER_FIRING_THRESHOLD               — value-if-true / severity floor that fires a refuter
//   firesRefuter(item)                     — does this elevation/finding earn an independent refuter?
//   CONFIDENCE_WORDS / isConfidenceWord    — the self-rated confidence vocabulary (NOT a defeater)
//   isNamedDefeater(text)                  — a populated, non-confidence-word concrete defeater
//   REFUTATION_PROVENANCE_KIND             — the refutation_provenance envelope marker
//   elevationIdentity(elevation)           — the stable claim-binding identity (id + reasoning + defeater
//                                            + payload verdict/severity/value_if_true — every smuggle field)
//   computeResultDigest({elevation,...})   — stable SHA-256 CLAIM-BOUND to the elevation identity + the
//                                            refuter's defeater+verdict content (W2a; replay-hardened)
//   composeRefutationProvenance(stages)    — mint an independent named-defeater provenance envelope
//                                            (W2a: also carries drafter_family / refuter_family / result_digest)
//   isCrossFamilyRefutation(elev, resolve) — W2b: DERIVE cross-family (GROUNDED) eligibility from the
//                                            ledger — authentic + family-distinct + digest-matched
//   NOOP_COMMISSION_VERIFIER               — the inert default commission verifier for the W2a injection seam
//   NO_INDEPENDENT_REFUTATION_STAMP        — the honest un-refuted-floor stamp string
//   SPECULATIVE_TIER                       — the honest floor tier
//   stampNoIndependentRefutation(finding)  — downgrade a finding to the stamped SPECULATIVE floor
//   hasNoIndependentRefutationStamp(f)     — predicate: carries the honest un-refuted stamp
//   vetElevationRefutation(elevation)      — keep the tier if honestly refuted, else auto-downgrade
//   RefuterBudgetHalt                      — the HALT error class for an over-budget request
//   assertRefuterBudget(requested[, R])    — throws RefuterBudgetHalt when requested > R (no drop)

import crypto from 'node:crypto';
import CONSTANTS from '../prereg-constants.json' with { type: 'json' };

// --- self-contained helpers (the seam imports only the frozen constants) -------------------
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

// --- the refuter-firing threshold (only high-value elevations earn an independent refuter) --
/** The bounded refuter budget R, the single source of truth being prereg-constants.json. */
export const REFUTER_BUDGET_R = CONSTANTS.refuter_budget_R;

/** The refuter-firing threshold: an elevation earns an INDEPENDENT named-defeater refuter only
 *  when value-if-true ≥ HIGH OR severity ≥ major. Sourced from prereg-constants.json so the
 *  build-time frozen value is never re-typed (no drift). */
export const REFUTER_FIRING_THRESHOLD = CONSTANTS.refuter_firing_threshold;

// Ladders local to the seam (low → high); the harness mirrors these and asserts agreement.
const VALUE_LADDER = ['low', 'medium', 'high'];
const SEVERITY_LADDER = ['minor', 'major', 'critical'];

/** Does `item` (an elevation or finding) FIRE the refuter — i.e. earn an independent
 *  named-defeater refuter? True iff value_if_true ≥ the threshold floor OR severity ≥ the
 *  threshold floor (from REFUTER_FIRING_THRESHOLD). Below the threshold, no refuter runs and
 *  the finding ships SPECULATIVE with the no-independent-refutation stamp. Pure; never throws. */
export function firesRefuter(item) {
  if (item === null || typeof item !== 'object') return false;
  const vFloor = VALUE_LADDER.indexOf(REFUTER_FIRING_THRESHOLD.value_if_true_at_least);
  const sFloor = SEVERITY_LADDER.indexOf(REFUTER_FIRING_THRESHOLD.or_severity_at_least);
  const vIdx = VALUE_LADDER.indexOf(item.value_if_true);
  const sIdx = SEVERITY_LADDER.indexOf(item.severity);
  const valueFires = vIdx !== -1 && vFloor !== -1 && vIdx >= vFloor;
  const severityFires = sIdx !== -1 && sFloor !== -1 && sIdx >= sFloor;
  return valueFires || severityFires;
}

// --- named concrete defeater vs self-rated confidence word ---------------------------------
/** The self-rated confidence vocabulary. A `what_would_refute_it` whose WHOLE value (after
 *  case/punctuation normalization) is one of these is a confidence SELF-RATING, not a named
 *  concrete defeater — it names no falsifying observation, so it cannot vet an elevation. */
export const CONFIDENCE_WORDS = new Set([
  'likely', 'very likely', 'unlikely', 'very unlikely', 'probably', 'probably not',
  'possibly', 'plausibly', 'maybe', 'perhaps', 'confident', 'very confident',
  'fairly confident', 'high confidence', 'low confidence', 'medium confidence',
  'i am confident', 'i think', 'i believe', 'seems right', 'sounds right',
  'certain', 'uncertain', 'sure', 'not sure', 'doubtful', 'no doubt',
  'obviously', 'clearly', 'of course', 'trust me', 'nothing', 'none',
]);

function normalizeConfidence(text) {
  return String(text).toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
}

/** Is `text` a bare self-rated confidence word/phrase (and so NOT a refutation)? True iff the
 *  whole normalized value is in CONFIDENCE_WORDS. Pure; never throws. */
export function isConfidenceWord(text) {
  if (typeof text !== 'string') return false;
  const n = normalizeConfidence(text);
  if (n === '') return false;
  return CONFIDENCE_WORDS.has(n);
}

/** Is `text` a NAMED CONCRETE DEFEATER? True iff it is populated AND is not a bare self-rated
 *  confidence word. (Deterministic discriminator — judging the defeater's actual concreteness
 *  is the advisory layer's job, PRINCIPLE-D; the gate rejects the un-falsifiable confidence
 *  self-rating and requires the structural `refutation_provenance` alongside it.) Pure. */
export function isNamedDefeater(text) {
  if (!isNonEmptyString(text)) return false;
  return !isConfidenceWord(text);
}

// --- the independent named-defeater refutation provenance envelope -------------------------
/** The refutation_provenance envelope marker: an INDEPENDENT named-defeater refuter ran. */
export const REFUTATION_PROVENANCE_KIND = 'independent-named-defeater';

/** The STABLE identity of the elevation a refutation is bound to — the CLAIM-BINDING that closes the
 *  cross-elevation REPLAY hole. A commission's result_digest is bound to THIS identity, so a provenance
 *  legitimately minted for elevation A cannot authenticate a FABRICATED elevation B: B has a different
 *  `id` / `reasoning` / named defeater — OR a different SUBSTANTIVE PAYLOAD (`verdict` / `severity` /
 *  `value_if_true`) — ⇒ a different identity ⇒ the gate's recomputed digest no longer matches the ledger
 *  tuple. The identity binds the elevation `id` PLUS EVERY substantive field a drafter could vary to
 *  smuggle a false claim under a valid proof: its `reasoning`, its `what_would_refute_it` (the
 *  named-defeater SUBJECT the finding is about), AND its payload `verdict` + `severity` + `value_if_true`
 *  (the claim/rating a replay would try to fabricate under a genuine refutation's provenance). Trimmed +
 *  fixed key order so the SAME elevation yields the SAME identity at MINT and at GATE (any divergence
 *  would either reopen the hole or cause a false negative). A non-object elevation ⇒ null (a digest over
 *  "no bound elevation" — the pre-claim-binding shape, still self-consistent). Pure; never throws. */
export function elevationIdentity(elevation) {
  if (elevation === null || typeof elevation !== 'object' || Array.isArray(elevation)) return null;
  return {
    id: isNonEmptyString(elevation.id) ? elevation.id.trim() : '',
    reasoning: isNonEmptyString(elevation.reasoning) ? elevation.reasoning.trim() : '',
    what_would_refute_it: isNonEmptyString(elevation.what_would_refute_it)
      ? elevation.what_would_refute_it.trim()
      : '',
    verdict: isNonEmptyString(elevation.verdict) ? elevation.verdict.trim() : '',
    severity: isNonEmptyString(elevation.severity) ? elevation.severity.trim() : '',
    value_if_true: isNonEmptyString(elevation.value_if_true) ? elevation.value_if_true.trim() : '',
  };
}

/** Compute the stable `result_digest` a refutation carries: a SHA-256 over the CLAIM-BOUND tuple —
 *  the IDENTITY of the elevation being refuted (elevationIdentity: id + reasoning + named defeater) PLUS
 *  the refuter's CONTENT (its named defeater, its survived/broke verdict, and any verdict text).
 *  Canonicalized (fixed key order, trimmed) so the SAME refutation of the SAME elevation always yields
 *  the SAME digest — the value the unforgeable commission-id (seam/commission-ledger.mjs) is
 *  cryptographically BOUND to (W2a; claim-bound in the REPLAY-close hardening). Because the digest now
 *  binds the elevation identity, a commission minted for elevation A produces a digest bound to A; when
 *  that provenance is copied onto a different elevation B, the gate recomputes over B's identity and the
 *  digest MISMATCHES ⇒ the replay is rejected. Stdlib-only; pure. */
export function computeResultDigest({ elevation = null, defeater, survived = true, verdict = null } = {}) {
  const canonical = JSON.stringify({
    elevation: elevationIdentity(elevation),
    defeater: isNonEmptyString(defeater) ? defeater.trim() : '',
    survived: survived === true,
    verdict: verdict === undefined || verdict === null ? null : String(verdict),
  });
  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

/** Mint a typed refutation_provenance envelope — the deterministic surface of the bare refuter
 *  `agent()` seam. It records the named concrete defeater that was tried and whether the elevation
 *  survived it. W2a extends the envelope with the CROSS-FAMILY provenance the commission-id ledger
 *  binds: `drafter_family` (who authored the drafted claim), `refuter_family` (who ran the
 *  refutation), and `result_digest` (a stable hash of the refuter's defeater + verdict content —
 *  computeResultDigest). W2b also PERSISTS `verdict` so the digest re-derives faithfully from the
 *  envelope's own content (isCrossFamilyRefutation check (c)).
 *
 *  W2b: the envelope no longer HARDCODES `independent: true`. Independence in the cross-family sense
 *  (the drafter and refuter are DIFFERENT model families, established against the unforgeable ledger)
 *  is DERIVED at the vet seam (isCrossFamilyRefutation), never self-asserted here — a hardcoded
 *  `independent:true` was exactly the self-stamp the anti-overclaim runtime gate replaces.
 *  `commission_id` is the ledger id the orchestrator minted for this refutation; W2b resolves it.
 *  Throws when the defeater is missing or is a bare confidence word. */
export function composeRefutationProvenance({
  elevation = null,
  defeater,
  survived = true,
  verdict = null,
  drafter_family = null,
  refuter_family = null,
  commission_id = null,
} = {}) {
  if (!isNamedDefeater(defeater)) {
    throw new Error('refute: composeRefutationProvenance requires a NAMED concrete defeater (a self-rated confidence word is not a refutation)');
  }
  return {
    kind: REFUTATION_PROVENANCE_KIND,
    defeater: defeater.trim(),
    survived: survived === true,
    verdict: verdict === undefined || verdict === null ? null : verdict,
    drafter_family: drafter_family ?? null,
    refuter_family: refuter_family ?? null,
    // CLAIM-BOUND: the digest binds the IDENTITY of `elevation` (the finding being refuted) so this
    // provenance cannot be replayed onto a different elevation. The MINT path MUST pass the SAME
    // elevation whose id/reasoning/what_would_refute_it the GATE (isCrossFamilyRefutation) will read.
    result_digest: computeResultDigest({ elevation, defeater, survived, verdict }),
    refuter_commission_id: commission_id,
  };
}

// --- the honest un-refuted floor (ship SPECULATIVE + the stamp) ----------------------------
/** The stamp a finding carries when no independent refuter established it. */
export const NO_INDEPENDENT_REFUTATION_STAMP = 'no independent refutation ran';
/** The honest floor tier — an un-refuted finding may not rise above it. */
export const SPECULATIVE_TIER = 'SPECULATIVE';

/** Downgrade `finding` to the honest SPECULATIVE floor and stamp it "no independent refutation
 *  ran" — the explicit, non-silent route for a finding that did not earn an independent
 *  named-defeater refutation. Returns a FRESH finding (existing keys keep insertion order, so a
 *  reasoning-before-verdict finding stays reasoning-before-verdict). Throws on a non-object. */
export function stampNoIndependentRefutation(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) {
    throw new Error('refute: stampNoIndependentRefutation target is not an object');
  }
  return {
    ...finding,
    tier: SPECULATIVE_TIER,
    no_independent_refutation: true,
    refutation_stamp: NO_INDEPENDENT_REFUTATION_STAMP,
  };
}

/** Predicate: does `finding` carry the honest un-refuted-floor stamp? Pure; never throws. */
export function hasNoIndependentRefutationStamp(finding) {
  return (
    finding !== null &&
    typeof finding === 'object' &&
    finding.no_independent_refutation === true &&
    finding.refutation_stamp === NO_INDEPENDENT_REFUTATION_STAMP
  );
}

/** The default commission verifier: a NO-OP that resolves nothing (returns null). With it, an
 *  elevation can NEVER reach the cross-family tier (no ledger to authenticate its commission-id) —
 *  the safe, conservative default when no real resolver is injected. The RUNTIME entry
 *  (runtime/seam-pass.applySeamPass) injects the real ledger resolver
 *  (seam/commission-ledger.resolveCommission) so the W2b gate is ACTIVE in a real run. Pure. */
export const NOOP_COMMISSION_VERIFIER = () => null;

/** W2b — DERIVE whether an elevation's refutation is a GENUINE cross-family refutation, the SOLE gate
 *  to the cross-family (GROUNDED) tier. TRUE iff the elevation's `refutation_provenance` carries a
 *  commission-id that, resolved against the injected ledger `resolveCommission`, is ALL of:
 *    (a) AUTHENTIC     — resolveCommission(id) returns a non-null tuple (orchestrator-minted,
 *                        unforgeable; a forged / unminted / tampered id resolves to null);
 *    (b) FAMILY-DISTINCT — the resolved drafter_family !== refuter_family (a same-family "refutation"
 *                        earns no independent origin, so it can never cross the single-family ceiling);
 *    (c) DIGEST-MATCHED — the resolved result_digest === computeResultDigest over the elevation's OWN
 *                        IDENTITY (id + reasoning + named defeater) PLUS its refuter content (recomputed
 *                        from the envelope's defeater/survived/verdict — never a stored/self-reported
 *                        digest), so the ledger entry is CLAIM-BOUND to THIS elevation. A provenance
 *                        minted for elevation A, copied onto a fabricated elevation B, recomputes over
 *                        B's identity ⇒ mismatch ⇒ the cross-elevation REPLAY is rejected.
 *  ANY failure ⇒ FALSE ⇒ the elevation cannot exceed the single-family PROMISING ceiling. The caller's
 *  `--cross-model` intent flag NEVER enters here — cross-family is DERIVED from the ledger, never
 *  asserted. Pure; never throws (a throwing resolver is treated as a non-resolution ⇒ false). */
export function isCrossFamilyRefutation(elevation, resolveCommission = NOOP_COMMISSION_VERIFIER) {
  if (elevation === null || typeof elevation !== 'object' || Array.isArray(elevation)) return false;
  const prov = elevation.refutation_provenance;
  if (prov === null || typeof prov !== 'object' || Array.isArray(prov)) return false;
  // The commission-id the orchestrator minted for this refutation (accept either envelope spelling).
  const id = isNonEmptyString(prov.refuter_commission_id)
    ? prov.refuter_commission_id
    : (isNonEmptyString(prov.commission_id) ? prov.commission_id : null);
  if (id === null) return false;
  let resolved;
  try {
    resolved = typeof resolveCommission === 'function' ? resolveCommission(id) : null;
  } catch {
    return false; // a resolver that throws is a non-resolution — never a cross-family grant
  }
  // (a) AUTHENTIC — the ledger returned a well-formed tuple for this id.
  if (resolved === null || typeof resolved !== 'object' || Array.isArray(resolved)) return false;
  if (!isNonEmptyString(resolved.drafter_family) || !isNonEmptyString(resolved.refuter_family)) return false;
  // (b) FAMILY-DISTINCT — drafter and refuter are different model families.
  if (resolved.drafter_family === resolved.refuter_family) return false;
  // (c) DIGEST-MATCHED — the ledger's digest binds THIS refutation's actual content AND THIS elevation's
  //     identity (recomputed here; never a stored/self-reported digest). Passing `elevation` claim-binds
  //     the digest: a provenance minted for elevation A, copied onto elevation B, recomputes over B's
  //     identity (id + reasoning + named defeater) ⇒ mismatches the ledger tuple ⇒ the replay is rejected.
  const recomputed = computeResultDigest({
    elevation,
    defeater: prov.defeater,
    survived: prov.survived,
    verdict: prov.verdict ?? null,
  });
  if (resolved.result_digest !== recomputed) return false;
  return true;
}

/** Vet an elevation against the refutation discipline (the auto-downgrade path the "FAILS /
 *  auto-downgrades" done-when names). If the elevation carries a NAMED concrete defeater AND a
 *  `refutation_provenance` envelope, it earned its tier and is returned unchanged (fresh copy).
 *  Otherwise it is auto-downgraded to the SPECULATIVE floor + the no-independent-refutation
 *  stamp — never silently left over-claimed. Returns a FRESH object; throws on a non-object.
 *
 *  W2b GATE: a `resolveCommission` verifier is injected via `options` (the RUNTIME entry wires the
 *  real ledger resolver; tests pass a stub). An honestly-refuted elevation keeps its tier, and its
 *  CROSS-FAMILY eligibility is DERIVED here (isCrossFamilyRefutation) and stamped onto the returned
 *  elevation as `cross_family_refuted` — the ONLY signal downstream (passElevation/applySeamPass) may
 *  use to let the elevation reach the cross-family (GROUNDED) tier or to set the derived top-level
 *  `cross_model`. With the default NOOP resolver (or a resolver that rejects the id), the elevation is
 *  honestly refuted but NOT cross-family (`cross_family_refuted:false`) ⇒ capped at PROMISING. */
export function vetElevationRefutation(elevation, options = {}) {
  if (elevation === null || typeof elevation !== 'object' || Array.isArray(elevation)) {
    throw new Error('refute: vetElevationRefutation target is not an object');
  }
  const { resolveCommission = NOOP_COMMISSION_VERIFIER } = options;
  const honestlyRefuted = isNamedDefeater(elevation.what_would_refute_it) && isNonEmpty(elevation.refutation_provenance);
  if (honestlyRefuted) {
    // Cross-family (GROUNDED) eligibility is DERIVED from the unforgeable ledger — never asserted.
    const cross_family_refuted = isCrossFamilyRefutation(elevation, resolveCommission);
    return { ...elevation, cross_family_refuted };
  }
  return stampNoIndependentRefutation(elevation);
}

// --- the bounded refuter budget (HALT, never a silent drop) --------------------------------
/** Thrown when more independent refuters are requested than the bounded budget R allows. A
 *  distinct class so the budget canary can assert the run HALTS rather than silently dropping. */
export class RefuterBudgetHalt extends Error {
  constructor(requested, budget) {
    super(
      `refuter-budget HALT: ${requested} independent refuters requested but the bounded budget is R=${budget} — HALT for human (no silent drop; findings below the firing threshold ship SPECULATIVE with the "${NO_INDEPENDENT_REFUTATION_STAMP}" stamp)`
    );
    this.name = 'RefuterBudgetHalt';
    this.requested = requested;
    this.budget = budget;
  }
}

/** Assert a refuter request stays within the bounded budget R. Returns `requested` when it is
 *  within budget; throws RefuterBudgetHalt (the HALT path) when it exceeds R — the run HALTS,
 *  it does NOT silently take the first R. Throws a plain Error on a non-count argument. */
export function assertRefuterBudget(requested, R = REFUTER_BUDGET_R) {
  if (!Number.isInteger(requested) || requested < 0) {
    throw new Error(`refute: assertRefuterBudget requires a non-negative integer count, got ${JSON.stringify(requested)}`);
  }
  if (requested > R) throw new RefuterBudgetHalt(requested, R);
  return requested;
}

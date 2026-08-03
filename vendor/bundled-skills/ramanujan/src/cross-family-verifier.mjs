// Wave 3 — F1b: cross-family VERIFIER -> PER-VERIFIER cross-family rung (router-wired).
//
// LIFT AN INFORMAL PROOF TO ITS PER-VERIFIER cross-family rung (v3 substrate, DESCRIPTION-INC2 §Residuals
// "Cross-family rung = PER-VERIFIER" + §v3.1). The rung reflects the ACTUAL independent verifier whose
// verdict the canary reproduces — NEVER a producer-recorded field:
//   * a FRONTIER-Gemini verdict (the pinned agy LABEL "Gemini 3.1 Pro (High)") -> **CORROBORATED** (the stronger
//     locked cross-family rung);
//   * an ollama-FALLBACK >=2-DISTINCT-family agreement (Qwen + Llama) -> **PLAUSIBILITY-CORROBORATED**
//     (the weaker soft-check tier, "NOT a proof oracle").
// This is the honest positive arm for proof-bearing claims that are NOT (yet) Lean-formalizable: instead
// of settling them, a generator-INDEPENDENT verifier referees the proof, re-checked out-of-band by the
// independence canary. NEITHER rung reaches OBSERVED (that needs the Lean kernel + bounded faithfulness,
// Wave 4) and NEITHER reaches VERIFIED (the Honesty Law: no cross-family check is autonomously settled).
//
// THE GUARANTEES THIS MODULE ENFORCES (DESCRIPTION-INC2 §v2 / §v2.1 / §v3.1 + the Wave-3 done-when):
//
//   1. CROSS-FAMILY, NEVER CLAUDE.  Every panel member is a non-Claude family; a `claude` member
//      HARD-FAULTS (mirrors the F1a driver's mint-time fault) — a same-family verdict can never be
//      laundered into a corroboration.
//   2. PROOF-JUDGING-GATED.  Only a certifier that PASSED F0's proof-judging sentinel (TRUSTED in the
//      supplied probe-trust) may count; a QUARANTINED certifier is dropped. Absent an explicit trust map
//      NOTHING is trusted (fail-closed) — the gate cannot be stubbed away.
//   3. PER-VERIFIER QUORUM (verdict-level).  A single re-run-agreeing FRONTIER (pinned-model Gemini)
//      "YES" earns CORROBORATED; otherwise >=2 DISTINCT trusted FALLBACK families must AGREE for the soft
//      PLAUSIBILITY-CORROBORATED rung (a single fallback family never satisfies the >=2-agree gate). A
//      disagreeing panel earns NO lift (the claim stays CONJECTURAL). Reproducibility is keyed on the
//      parsed VERDICT (F1a's contract), never raw transcript bytes.
//   4. TIER IS CANARY-DERIVED (§v3.1).  The tier (frontier|fallback) is DERIVED from the reproduced
//      backend identity (verifier_family + model vs the pinned frontier model), NEVER trusted from a
//      recorded `tier` field; a member whose recorded tier disagrees with its derived tier HARD-FAULTS.
//   5. CLAIM-BOUND (anti-replay).  The artifact's stored prompt must be the prompt THIS claim's proof
//      generates (deterministic buildCorroborationPrompt) and be bound to the claim id — a replayed /
//      cross-claim artifact (minted for another claim) fails the binding.
//   6. INDEPENDENT RE-RUN (anti-forgery).  The independence canary RE-RUNS the panel from the stored
//      prompt and recomputes each verdict; a FORGED artifact (a recorded verdict the model would NOT
//      actually give) is caught when the re-executed verdict disagrees with the recorded one. An
//      un-exercised canary (no re-run capability) WITHHOLDS the lift — a stubbed canary is no canary.
//
// ROUTER-AGNOSTIC BY DESIGN. This module imports ONLY the A1 ledger constants + the F1a driver — never
// verify-router — so there is no import cycle. `verify-router` imports THIS module and wires the
// adjudication + lift behind its async `routeCrossFamily` seam + the `cross-family-corroborator`
// registry entry. The adjudication (adjudicateCrossFamily) is a pure async function over an artifact +
// a re-run capability + a probe-trust map; the lift (liftCrossFamily) is the sole promote() to the
// per-verifier cross-family rung. Pure node + the project's own A1 + F1a modules. Runs under `node --test`.

import { RUNG, compareRungs } from './claim-ledger.mjs';
import {
  promptHash,
  normalizeAnswer,
  parseVerdict,
  validateArtifact,
  driveCrossFamilyVerdict,
  TIER,
  FRONTIER_FAMILY,
} from './cross-family-driver.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** The soft cross-family rung (pinned in the A1 ladder, strictly below OBSERVED / above CLAIMED). */
export const PLAUSIBILITY_CORROBORATED_RUNG = RUNG['PLAUSIBILITY-CORROBORATED'];

/**
 * The FRONTIER cross-family rung (pinned in the A1 ladder, strictly between PLAUSIBILITY-CORROBORATED
 * and OBSERVED). Reached ONLY by a frontier-Gemini verdict whose canary-reproduced backend identity is
 * the pinned frontier model (the v3 per-verifier rung — DESCRIPTION-INC2 §Residuals "Cross-family rung
 * = PER-VERIFIER" + §v3.1 "Tier is canary-DERIVED, not artifact-trusted").
 */
export const CORROBORATED_RUNG = RUNG.CORROBORATED;

/**
 * The PINNED frontier model whose verdict earns the CORROBORATED rung (DESCRIPTION-INC2 §Tooling v3 /
 * tools.manifest.json tools.gemini.model). Tier is DERIVED from the canary-reproduced backend identity
 * vs THIS pinned model — never a producer-recorded `tier` field. A test binds it to the manifest so the
 * two cannot drift. `frontierModel` is overridable per call (the router passes the manifest value).
 */
export const FRONTIER_MODEL = 'Gemini 3.1 Pro (High)';

/** The minimum number of DISTINCT independent families for the FALLBACK quorum (DESCRIPTION-INC2: quorum >=2). */
export const MIN_QUORUM = 2;

/** The panel verdict that lifts a proof: a parsed YES (= the model judged the proof VALID). */
export const LIFT_VERDICT = 'YES';

/**
 * The allowed cross-family certifier families (the pinned non-Claude panel — DESCRIPTION-INC2 §Tooling
 * v3: the GEMINI-PRIMARY frontier family + the ollama-FALLBACK qwen/llama families). The independence
 * canary requires every re-run family ∈ this set and != claude. §v3.1: the quorum counts distinct
 * non-Claude FAMILIES (gemini / qwen / llama), not models.
 */
export const CROSS_FAMILY_FAMILIES = Object.freeze(new Set([FRONTIER_FAMILY, 'qwen', 'llama']));

/** The adjudication outcome alphabet. */
export const CROSS_FAMILY_STATUS = Object.freeze({
  CORROBORATED: 'CORROBORATED', // a PASS: lift to the per-verifier rung (result.rung: frontier->CORROBORATED, fallback->PLAUSIBILITY-CORROBORATED)
  ABSTAIN: 'ABSTAIN', // no artifact / insufficient trusted quorum / disagreeing panel — stays CONJECTURAL
  FLAG: 'FLAG', // a DETECTED defect: forged / replayed / malformed / spliced / out-of-panel artifact
});

/** A typed error so a verifier wiring/usage bug (or an Honesty-Law hard-fault) is distinguishable. */
export class CrossFamilyVerifierError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'CrossFamilyVerifierError';
    Object.assign(this, extra);
  }
}

// ---------------------------------------------------------------------------
// The corroboration prompt — deterministic from the claim (the binding payload).
//
// The verifier asks each family to REFEREE the proof; the canary rebuilds this EXACT prompt from the
// claim and hashes it, so a replayed/cross-claim artifact (whose prompt was generated by a DIFFERENT
// claim) fails the claim-binding. Keep it pure + stable: same claim -> same prompt -> same prompt_hash.
// ---------------------------------------------------------------------------

/** The strict-referee prompt this claim's (statement, proof) generates. Deterministic + total. */
export function buildCorroborationPrompt(claim) {
  if (!claim || typeof claim !== 'object') {
    throw new CrossFamilyVerifierError('buildCorroborationPrompt requires a claim object');
  }
  const statement = typeof claim.statement === 'string' ? claim.statement : '';
  const proof =
    typeof claim.meta?.proof === 'string'
      ? claim.meta.proof
      : typeof claim.proof === 'string'
        ? claim.proof
        : '';
  return [
    'You are a strict mathematical proof referee. Judge ONLY whether the PROOF below is a VALID proof of the CLAIM.',
    'Be skeptical: a plausible-looking but logically invalid proof MUST be rejected.',
    `CLAIM: ${statement}`,
    `PROOF: ${proof}`,
    'Answer with exactly one word: VALID or INVALID.',
  ].join('\n');
}

// ---------------------------------------------------------------------------
// The quorum artifact (the cross-family artifact the lift is bound to).
// ---------------------------------------------------------------------------

const lowerFamily = (f) => (typeof f === 'string' ? f.trim().toLowerCase() : f);

/**
 * The answering family of an F1a member artifact. The v3 driver records it as `verifier_family` (the
 * ACTUAL backend — gemini | qwen | llama); legacy `family` is tolerated for forward/back compatibility.
 */
const memberFamily = (m) => lowerFamily(m && (m.verifier_family != null ? m.verifier_family : m.family));

/**
 * DERIVE a member's tier from its REPRODUCED backend IDENTITY (verifier_family + model) vs the pinned
 * frontier model — NEVER from a producer-recorded `tier` field (§v3.1 "Tier is canary-DERIVED, not
 * artifact-trusted"). A member is FRONTIER iff its family is the frontier family (gemini) AND its model
 * is the pinned frontier model; everything else (the ollama qwen/llama fallback, or a gemini member on a
 * NON-pinned model) is FALLBACK. The adjudicator HARD-FAULTS (FLAG) when this derived tier disagrees
 * with the member's recorded `tier` — catching an ollama verdict whose artifact LIES `tier=frontier`.
 */
const derivedTier = (m, frontierModel) =>
  memberFamily(m) === FRONTIER_FAMILY && m && m.model === frontierModel ? TIER.FRONTIER : TIER.FALLBACK;

/** A stable family-of-record stamp for a set of agreeing families: `cross-family:llama+qwen`. */
export function familyOfRecord(families) {
  const distinct = [...new Set((families || []).map(lowerFamily))].sort();
  return `cross-family:${distinct.join('+')}`;
}

/**
 * Mint the cross-family QUORUM artifact from a panel of F1a verdict records (or bare F1a artifacts),
 * all driven on buildCorroborationPrompt(claim). The artifact carries the STORED prompt (the canary
 * re-runs from it), its hash (claim-binding), the per-family F1a artifacts, and a provenance-only
 * recorded quorum_verdict (the canary NEVER trusts this — it recomputes from the independent re-run).
 */
export function makeQuorumArtifact({ claim, members, frontierModel = FRONTIER_MODEL } = {}) {
  if (!claim || typeof claim.id !== 'string') {
    throw new CrossFamilyVerifierError('makeQuorumArtifact requires the claim being verified');
  }
  if (!Array.isArray(members) || members.length === 0) {
    throw new CrossFamilyVerifierError('makeQuorumArtifact requires >=1 panel member');
  }
  const prompt = buildCorroborationPrompt(claim);
  const ph = promptHash(prompt);
  const memberArtifacts = members.map((m) => (m && m.artifact ? m.artifact : m));

  // Recorded quorum verdict = the verdict >=MIN_QUORUM distinct families share (provenance only).
  const byVerdict = new Map();
  for (const a of memberArtifacts) {
    if (!byVerdict.has(a.verdict)) byVerdict.set(a.verdict, new Set());
    byVerdict.get(a.verdict).add(memberFamily(a));
  }
  let quorum_verdict = null;
  for (const [verdict, fams] of byVerdict) {
    if (fams.size >= MIN_QUORUM) {
      quorum_verdict = verdict;
      break;
    }
  }

  // PROVENANCE-ONLY tier/rung: a frontier (pinned-model Gemini) member would carry the frontier rung,
  // else the soft fallback rung. The adjudicator NEVER trusts these — it DERIVES the tier/rung from the
  // canary-reproduced backend identity (§v3.1). They are recorded only so the artifact is self-describing.
  const anyFrontier = memberArtifacts.some((a) => derivedTier(a, frontierModel) === TIER.FRONTIER);
  return Object.freeze({
    claim_id: claim.id,
    tier: anyFrontier ? TIER.FRONTIER : TIER.FALLBACK,
    rung: anyFrontier ? CORROBORATED_RUNG : PLAUSIBILITY_CORROBORATED_RUNG,
    soft_check: !anyFrontier,
    note: anyFrontier
      ? 'frontier cross-family corroboration by an independent non-Claude family (provenance — the rung is canary-DERIVED, not trusted from this field)'
      : 'soft semantic check by independent non-Claude families — NOT a proof oracle',
    prompt,
    prompt_hash: ph,
    families: [...new Set(memberArtifacts.map((a) => memberFamily(a)))].sort(),
    quorum_verdict,
    members: Object.freeze(memberArtifacts.map((a) => Object.freeze({ ...a }))),
  });
}

/**
 * Drive a cross-family panel and mint the quorum artifact. `panel` = [{ model, family, generate }]
 * where generate is async(prompt)->rawAnswer (an injected stub in the fast tier, or a
 * createOllamaGenerate bound to the persistent server in the tool lane). Each family is asked the SAME
 * deterministic corroboration prompt, so every member's F1a prompt_hash matches the artifact's.
 */
export async function runCrossFamilyPanel(claim, panel, { drive } = {}) {
  if (!Array.isArray(panel) || panel.length === 0) {
    throw new CrossFamilyVerifierError('runCrossFamilyPanel requires a non-empty panel');
  }
  const prompt = buildCorroborationPrompt(claim);
  const driver = typeof drive === 'function' ? drive : driveCrossFamilyVerdict;
  const members = [];
  for (const p of panel) {
    // The F1a driver HARD-FAULTS on a claude family at mint time — the seam stays non-Claude. The
    // member's tier is passed through (a frontier Gemini panel member stamps tier=frontier; an ollama
    // member defaults to fallback) so makeQuorumArtifact / the adjudicator see the right backend identity.
    const rec = await driver(null, { model: p.model, family: p.family, prompt, tier: p.tier }, { generate: p.generate });
    members.push(rec);
  }
  return makeQuorumArtifact({ claim, members });
}

// ---------------------------------------------------------------------------
// Trust + re-run capability adapters.
// ---------------------------------------------------------------------------

/**
 * Normalize the proof-judging probe-trust into (family)->boolean. Accepts a function, a plain map
 * ({ qwen:true }), or a Map. FAIL-CLOSED: absent/garbage trust => nothing is trusted (the
 * proof-judging gate cannot be stubbed away by omitting it).
 */
function makeTrustFn(probeTrust) {
  if (typeof probeTrust === 'function') return (fam) => Boolean(probeTrust(lowerFamily(fam)));
  if (probeTrust instanceof Map) return (fam) => Boolean(probeTrust.get(lowerFamily(fam)));
  if (probeTrust && typeof probeTrust === 'object') return (fam) => Boolean(probeTrust[lowerFamily(fam)]);
  return () => false;
}

/**
 * Normalize the re-run capability into async (family, prompt)->rawAnswer. Accepts a function, a plain
 * map ({ qwen: async()=>'INVALID' }), or a Map. Returns null when no re-run capability is supplied —
 * the caller WITHHOLDS the lift (an un-exercised canary is treated as a stubbed one).
 */
function makeRerunFn(rerun) {
  if (typeof rerun === 'function') return rerun;
  const get = rerun instanceof Map ? (f) => rerun.get(f) : rerun && typeof rerun === 'object' ? (f) => rerun[f] : null;
  if (!get) return null;
  return async (family, prompt) => {
    const g = get(lowerFamily(family));
    if (typeof g !== 'function') {
      throw new CrossFamilyVerifierError(`no re-run generate supplied for family ${JSON.stringify(family)}`);
    }
    return g(prompt);
  };
}

const abstain = (reason, extra = {}) =>
  Object.freeze({ status: CROSS_FAMILY_STATUS.ABSTAIN, ok: false, flagged: false, reason, ...extra });
const flag = (reason, extra = {}) =>
  Object.freeze({ status: CROSS_FAMILY_STATUS.FLAG, ok: false, flagged: true, reason, ...extra });

// ---------------------------------------------------------------------------
// The adjudication (the heart of F1b).
// ---------------------------------------------------------------------------

/**
 * Adjudicate a cross-family quorum artifact for `claim`. Returns a frozen result whose `status` is one
 * of CROSS_FAMILY_STATUS:
 *   CORROBORATED — a PASS (carries the DERIVED `tier` + `rung`): a proof-judging-TRUSTED, claim-bound
 *                  panel whose INDEPENDENT re-run from the stored prompt judges the proof VALID, via
 *                  EITHER a single frontier (pinned-model Gemini) family (rung CORROBORATED) OR
 *                  >=MIN_QUORUM distinct fallback families (rung PLAUSIBILITY-CORROBORATED).
 *   ABSTAIN      — no artifact / insufficient trusted quorum / disagreeing panel — the claim stays CONJECTURAL.
 *   FLAG         — a DETECTED defect: forged (re-run disagrees), replayed/cross-claim (binding fails),
 *                  tier/identity mismatch (a recorded tier the backend identity does not support),
 *                  malformed/spliced/out-of-panel member artifact.
 * HARD-FAULTS (throws CrossFamilyVerifierError) if any panel member is a `claude` family — a same-family
 * verdict can never corroborate (the Honesty Law at the panel boundary).
 *
 * The rung is PER-VERIFIER and CANARY-DERIVED (v3 / §v3.1): a frontier-Gemini member (the pinned
 * frontier model) whose verdict the canary reproduces lifts to CORROBORATED; an ollama-fallback
 * >=MIN_QUORUM family agreement lifts only to PLAUSIBILITY-CORROBORATED. The tier is DERIVED from the
 * reproduced backend identity vs `frontierModel`, never a producer-recorded `tier` field — a member
 * whose recorded `tier` disagrees with its derived tier HARD-FAULTS (FLAG).
 *
 * @param {{ artifact:object, claim:object, rerun?:Function|object, probeTrust?:Function|object, families?:Set<string>, frontierModel?:string }} o
 */
export async function adjudicateCrossFamily({ artifact, claim, rerun, probeTrust, families = CROSS_FAMILY_FAMILIES, frontierModel = FRONTIER_MODEL } = {}) {
  if (!claim || typeof claim.id !== 'string') {
    throw new CrossFamilyVerifierError('adjudicateCrossFamily requires the claim being verified');
  }
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) {
    return abstain('no cross-family corroboration artifact supplied — the panel was never run (deferred arm)');
  }
  const members = Array.isArray(artifact.members) ? artifact.members : null;
  if (!members || members.length === 0) {
    return flag('cross-family artifact carries no panel members');
  }

  // (1) HONESTY LAW boundary — a `claude` panel member HARD-FAULTS (a Claude-only verdict can never
  // be laundered into a cross-family corroboration). Checked first, before any trust/quorum logic.
  for (const m of members) {
    if (memberFamily(m) === 'claude') {
      throw new CrossFamilyVerifierError(
        'cross-family verifier refuses a `claude` panel member — a same-family verdict cannot corroborate (Honesty Law)',
        { family: memberFamily(m) },
      );
    }
  }

  // (4) CLAIM-BINDING (anti-replay). The stored prompt must self-hash to prompt_hash AND be the exact
  // prompt THIS claim's proof generates, and the artifact must name this claim. A replayed/cross-claim
  // artifact (minted for a different claim) generates a different prompt => a different hash => caught.
  if (typeof artifact.prompt !== 'string' || artifact.prompt.length === 0) {
    return flag('cross-family artifact has no stored prompt to independently re-run');
  }
  const storedHash = promptHash(artifact.prompt);
  if (artifact.prompt_hash !== storedHash) {
    return flag('cross-family artifact prompt_hash does not match its stored prompt (tampered prompt)');
  }
  const boundHash = promptHash(buildCorroborationPrompt(claim));
  if (artifact.claim_id !== claim.id || storedHash !== boundHash) {
    return flag(
      `cross-family artifact is not bound to claim "${claim.id}" (replayed / cross-claim — the stored prompt is not the one this claim's proof generates)`,
    );
  }

  // (3a) per-member STRUCTURAL validation (the F1a artifact contract) + same-prompt + allowed-panel.
  for (const m of members) {
    const v = validateArtifact(m);
    if (!v.ok) return flag(`malformed panel member artifact: ${v.failures.join('; ')}`);
    if (m.prompt_hash !== storedHash) {
      return flag(`panel member ${memberFamily(m)} was asked a DIFFERENT prompt than the bound one (spliced artifact)`);
    }
    if (!families.has(memberFamily(m))) {
      return flag(
        `panel member family ${JSON.stringify(memberFamily(m))} is not an allowed cross-family certifier (expected one of ${[...families].join(', ')})`,
      );
    }
    // (3c) TIER IS CANARY-DERIVED (§v3.1). The member's tier is DERIVED from its backend identity
    // (verifier_family + model vs the pinned frontier model), NOT trusted from the recorded `tier`
    // field. A member whose recorded tier LIES about its identity (e.g. an ollama qwen verdict whose
    // artifact claims tier=frontier) HARD-FAULTS — the frontier rung can never be reached by a lie.
    const dt = derivedTier(m, frontierModel);
    if (m.tier !== dt) {
      return flag(
        `panel member ${memberFamily(m)} recorded tier=${JSON.stringify(m.tier)} but its backend identity ` +
          `(family=${memberFamily(m)}, model=${JSON.stringify(m.model)}) derives tier=${dt} — a tier/identity mismatch ` +
          '(the frontier rung is canary-DERIVED, never trusted from the recorded tier field)',
      );
    }
  }

  // (2) PROOF-JUDGING GATE + PER-TIER FEASIBILITY. Only certifiers that PASSED F0's proof-judging
  // sentinel may count; a QUARANTINED certifier is dropped. Fail-closed: no trust map => nothing
  // trusted => no lift. A lift is FEASIBLE iff EITHER >=1 trusted FRONTIER family (the pinned-model
  // Gemini — a single frontier verdict earns the stronger CORROBORATED rung) OR >=MIN_QUORUM distinct
  // trusted FALLBACK families (the weaker ollama soft-check). A single fallback family never silently
  // satisfies the >=2-agree gate (§v3.1 "a single reachable family never satisfies a >=2-agree gate").
  const isTrusted = makeTrustFn(probeTrust);
  const trusted = members.filter((m) => isTrusted(memberFamily(m)));
  const trustedFrontier = trusted.filter((m) => derivedTier(m, frontierModel) === TIER.FRONTIER);
  const trustedFallbackFamilies = new Set(
    trusted.filter((m) => derivedTier(m, frontierModel) === TIER.FALLBACK).map((m) => memberFamily(m)),
  );
  if (trustedFrontier.length === 0 && trustedFallbackFamilies.size < MIN_QUORUM) {
    const distinctTrusted = new Set(trusted.map((m) => memberFamily(m)));
    return abstain(
      `insufficient proof-judging-TRUSTED quorum: ${distinctTrusted.size} distinct trusted ` +
        `${distinctTrusted.size === 1 ? 'family' : 'families'} (need a trusted FRONTIER family OR >=${MIN_QUORUM} ` +
        "trusted fallback families) — a certifier that did NOT pass F0's proof-judging sentinel cannot corroborate",
    );
  }

  // (5) INDEPENDENCE CANARY — re-run each trusted member's family on the STORED prompt and recompute
  // its verdict out-of-band. A forged artifact (recorded verdict the model would NOT give) disagrees.
  const rerunFn = makeRerunFn(rerun);
  if (!rerunFn) {
    return abstain(
      'independence canary could NOT run (no re-run capability supplied) — the lift is WITHHELD (an un-exercised canary is treated as stubbed)',
    );
  }
  const reexec = [];
  for (const m of trusted) {
    const fam = memberFamily(m);
    const reVerdict = parseVerdict(normalizeAnswer(await rerunFn(fam, artifact.prompt)));
    reexec.push({
      family: fam,
      tier: derivedTier(m, frontierModel),
      recorded: m.verdict,
      reexec: reVerdict,
      agrees: reVerdict === m.verdict,
    });
  }
  const forged = reexec.filter((r) => !r.agrees);
  if (forged.length > 0) {
    return flag(
      `forged cross-family artifact: the INDEPENDENT panel re-run from the stored prompt DISAGREES with the recorded verdict for ${forged
        .map((f) => `${f.family} (recorded ${f.recorded}, re-ran ${f.reexec})`)
        .join('; ')}`,
      { reexec: Object.freeze(reexec) },
    );
  }

  // (3b) PER-VERIFIER QUORUM (verdict-level, over the CANARY-REPRODUCED verdicts; the tier is DERIVED,
  // never trusted — §v3 / §v3.1). FRONTIER first: a single re-run-agreeing frontier (pinned-model
  // Gemini) "YES" earns the stronger CORROBORATED rung. Else >=MIN_QUORUM distinct re-run-agreeing
  // FALLBACK families earn the weaker PLAUSIBILITY-CORROBORATED rung. Neither => the claim stays
  // CONJECTURAL. BOTH rungs sit strictly below OBSERVED (never VERIFIED — the Honesty Law).
  const frontierYes = reexec.filter((r) => r.tier === TIER.FRONTIER && r.reexec === LIFT_VERDICT);
  const fallbackYesFamilies = new Set(
    reexec.filter((r) => r.tier === TIER.FALLBACK && r.reexec === LIFT_VERDICT).map((r) => r.family),
  );

  if (frontierYes.length > 0) {
    const agreeing = [...new Set(reexec.filter((r) => r.reexec === LIFT_VERDICT).map((r) => r.family))].sort();
    return Object.freeze({
      status: CROSS_FAMILY_STATUS.CORROBORATED,
      ok: true,
      flagged: false,
      tier: TIER.FRONTIER,
      rung: CORROBORATED_RUNG,
      soft_check: false,
      reason:
        `CORROBORATED (frontier cross-family): the frontier non-Claude family ` +
        `(${[...new Set(frontierYes.map((r) => r.family))].join(', ')}) re-ran the panel from the stored prompt ` +
        'and agrees the proof is VALID — a corroboration by the pinned frontier verifier (still strictly below OBSERVED; not a proof oracle)',
      family_of_record: familyOfRecord(agreeing),
      quorum_verdict: LIFT_VERDICT,
      families: agreeing,
      reexec: Object.freeze(reexec),
    });
  }

  if (fallbackYesFamilies.size >= MIN_QUORUM) {
    const agreeing = [...fallbackYesFamilies].sort();
    return Object.freeze({
      status: CROSS_FAMILY_STATUS.CORROBORATED,
      ok: true,
      flagged: false,
      tier: TIER.FALLBACK,
      rung: PLAUSIBILITY_CORROBORATED_RUNG,
      soft_check: true,
      reason:
        `PLAUSIBILITY-CORROBORATED: ${agreeing.length} independent non-Claude families (${agreeing.join(', ')}) ` +
        're-ran the panel from the stored prompt and agree the proof is plausibly VALID — a SOFT semantic check, NOT a proof oracle',
      family_of_record: familyOfRecord(agreeing),
      quorum_verdict: LIFT_VERDICT,
      families: agreeing,
      reexec: Object.freeze(reexec),
    });
  }

  return abstain(
    `cross-family panel did not reach a frontier OR >=${MIN_QUORUM}-fallback-family "${LIFT_VERDICT}" quorum ` +
      `(re-ran verdicts: ${reexec.map((r) => `${r.family}=${r.reexec}`).join(', ')}) — the claim stays CONJECTURAL`,
    { reexec: Object.freeze(reexec) },
  );
}

// ---------------------------------------------------------------------------
// The lift — the SOLE promote() to a cross-family rung (per-verifier).
// ---------------------------------------------------------------------------

/**
 * Lift `claim` to the PER-VERIFIER cross-family rung the adjudication DERIVED — CORROBORATED for a
 * frontier-Gemini result, PLAUSIBILITY-CORROBORATED for the ollama fallback (result.rung). promote() is
 * strictly-upward only; if the claim already sits at/above that rung (e.g. it was independently
 * Lean-OBSERVED, or already frontier-CORROBORATED and this is a fallback re-pass), the lift is a HOLD
 * (idempotent — never lowers a stronger rung). Returns the snapshot. This is the SOLE promote() to a
 * cross-family rung; neither rung ever reaches OBSERVED (the Lean+faithfulness arm) or VERIFIED.
 */
export function liftCrossFamily(ledger, claim, result) {
  if (!ledger || typeof ledger.promote !== 'function' || typeof ledger.rungOf !== 'function') {
    throw new CrossFamilyVerifierError('liftCrossFamily requires an A1 ClaimLedger');
  }
  if (!result || result.status !== CROSS_FAMILY_STATUS.CORROBORATED) {
    throw new CrossFamilyVerifierError('liftCrossFamily requires a CORROBORATED adjudication result');
  }
  const targetRung = result.rung || PLAUSIBILITY_CORROBORATED_RUNG;
  const id = claim.id;
  if (compareRungs(targetRung, ledger.rungOf(id)) <= 0) {
    return ledger.get(id); // already at/above the derived rung — HOLD (sticky), never lower it.
  }
  return ledger.promote(id, targetRung, {
    family: result.family_of_record,
    reason: result.reason,
    by: 'cross-family-verifier',
  });
}

/**
 * BACK-COMPAT: lift `claim` specifically to PLAUSIBILITY-CORROBORATED, bound to a CORROBORATED
 * adjudication result (the weaker fallback rung). Retained for callers that target the soft rung
 * explicitly; the router uses liftCrossFamily (the per-verifier lift). HOLD-on-stronger is preserved.
 */
export function liftToPlausibilityCorroborated(ledger, claim, result) {
  if (!ledger || typeof ledger.promote !== 'function' || typeof ledger.rungOf !== 'function') {
    throw new CrossFamilyVerifierError('liftToPlausibilityCorroborated requires an A1 ClaimLedger');
  }
  if (!result || result.status !== CROSS_FAMILY_STATUS.CORROBORATED) {
    throw new CrossFamilyVerifierError('liftToPlausibilityCorroborated requires a CORROBORATED adjudication result');
  }
  const id = claim.id;
  if (compareRungs(PLAUSIBILITY_CORROBORATED_RUNG, ledger.rungOf(id)) <= 0) {
    return ledger.get(id); // already at/above the soft rung — HOLD (sticky), never lower it.
  }
  return ledger.promote(id, PLAUSIBILITY_CORROBORATED_RUNG, {
    family: result.family_of_record,
    reason: result.reason,
    by: 'cross-family-verifier',
  });
}

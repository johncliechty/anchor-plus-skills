// crucible/bin/judge-panel.mjs — Wave 3 (Front 3): the CROSS-FAMILY judge-panel seam at
// the rubric gate.
//
// NET-NEW seam. The convergence Judge (`judge.mjs` `selectJudgeModel`) returns ONE judge
// and `gemini-cli` is a worker transport, not a two-judge aggregator. This panel fires ≥2
// judges across DISTINCT model FAMILIES over ONE rubric gate (the Wave-2 lit-review gate on
// the DEFAULT Claude host) and AGGREGATES + records every stamp.
//
// REUSE, NOT FORK (SR-6): each member scores through `scoreAgainstRubric` — the SAME rubric
// machinery the gate uses — which itself reuses `selectJudgeModel` + `stampRole`. `judge.mjs`
// is IMPORTED, never modified, so the convergence single-selection path stays byte-identical
// (asserted in judge-panel.test.mjs and pack-layer3-rubric.test.mjs).
//
// INDEPENDENCE IS COUNTED FROM DISPATCHER-ATTESTED STAMPS, NEVER ARGV (the load-bearing
// rule). A member's role stamp records the REQUESTED family (argv-side, from `selectJudgeModel`);
// its SR-5 attestation records the SERVED model READ FROM THE RESULT ENVELOPE (`drivers/attest.mjs`).
// Only the SERVED family enters the origin count, and only when `model_attested:true`. So a run
// whose argv requests {claude, gemini} but is SERVED {claude, claude} counts ONE origin and FAILS
// the two-family assertion — a Gemini-only "enhanced" judge, or a degraded second family, cannot
// masquerade as cross-family. The count is delegated to the trio's SINGLE origin counter
// (`countIndependentOrigins`) gated by the committed closed lineage enum (crit-5), so the
// ≥2-distinct-attested-family rule cannot be re-implemented (and quietly weakened) here.

import { HaltError } from './crucible-lib.mjs';
import { defaultProbeCrossModel } from './judge.mjs';
import { scoreAgainstRubric } from './packs/layer3-rubric.mjs';
import { attestStamp } from '../../drivers/attest.mjs';
import {
  countIndependentOrigins,
  STATIC_QUORUM_FLOOR,
} from '../../researchPrime/bin/trio-core/independence-accounting.mjs';
import { committedLineages } from '../../researchPrime/bin/lineage-enum.mjs';

export const PANEL_ROLE = 'RubricJudgePanel';

// Map a SERVED model id (read from the envelope) to its attested lineage/family. Prefix-keyed
// so 'claude-opus-4-8' -> 'claude', 'gemini-3.1-pro-preview' -> 'gemini'. This is the DISPATCHER
// family — derived from what actually ran, never from the requested ('-m auto') id.
const FAMILY_PREFIXES = [
  ['claude', 'claude'],
  ['gemini', 'gemini'],
  ['gpt', 'gpt'], ['o1', 'gpt'], ['o3', 'gpt'], ['o4', 'gpt'], ['o-', 'gpt'],
  ['grok', 'grok'],
];

/**
 * The attested lineage of a SERVED model id, or null when it cannot be mapped. Falls back to
 * the leading alphabetic segment so a never-seen attested family still reads as its own lineage
 * (the closed enum then decides whether it counts as a distinct origin).
 * @param {?string} served  served-model id READ FROM THE ENVELOPE (never argv)
 * @returns {?string}
 */
export function familyOfServedModel(served) {
  if (typeof served !== 'string') return null;
  const s = served.trim().toLowerCase();
  if (!s) return null;
  for (const [pfx, fam] of FAMILY_PREFIXES) if (s.startsWith(pfx)) return fam;
  const seg = s.match(/^[a-z]+/);
  return seg ? seg[0] : null;
}

/**
 * Resolve a member's DISPATCHER attestation (the SR-5 served-model stamp). A member supplies
 * EITHER an explicit `attest` (a stamp object, or a thunk returning one — the live wiring passes
 * the dispatcher's recorded served-model stamp for that member's call) OR a `servedModel` string
 * we normalize through `attestStamp`. Absent both => degraded (never fabricate a served model).
 */
function resolveAttestation(member) {
  if (member.attest != null) {
    const a = typeof member.attest === 'function' ? member.attest() : member.attest;
    // Trust a well-formed stamp; otherwise normalize whatever served id it carries.
    if (a && typeof a === 'object' && 'model_attested' in a && 'model_served' in a && 'degraded' in a) return a;
    return attestStamp(a && typeof a === 'object' ? a.model_served : a);
  }
  return attestStamp(member.servedModel ?? null);
}

/** Build the per-member cross-family probe for `scoreAgainstRubric` from its REQUESTED family. */
function memberProbe(member) {
  if (member.probeCrossModel) return member.probeCrossModel;
  if (member.family && member.family !== 'claude') {
    return () => ({ model: member.servedModel || member.family, family: member.family });
  }
  return defaultProbeCrossModel;
}

/**
 * Fire a cross-family judge PANEL over one rubric gate and aggregate every stamp.
 *
 * @param {object} o
 * @param {string} o.doc                       the deliverable judged at the rubric gate
 * @param {object} o.pack                      the governing pack (its frozen rubric)
 * @param {Array<object>} o.members            ≥2 judge members. Each: {
 *     family,                                 the REQUESTED family (argv-side, drives the probe)
 *     servedModel?,                           OR an explicit served-model id (tests)
 *     attest?,                                OR the SR-5 dispatcher stamp / a thunk to it (live)
 *     score? | agent?,                        the rubric scorer (test) OR the live agent seam
 *     probeCrossModel?,                       OR an explicit cross-family probe
 *   }
 * @param {Iterable<string>} [o.attestedLineages]  the committed closed enum (defaults to
 *     `committedLineages()` — crit-5); off-enum served families collapse to one capped bucket
 * @param {Function} [o.log=()=>{}]
 * @returns {Promise<object>} the panel result (see fields below)
 */
export async function runRubricPanel({ doc, pack, members, attestedLineages, log = () => {} }) {
  if (!Array.isArray(members) || members.length < STATIC_QUORUM_FLOOR) {
    throw new HaltError(
      `a cross-family judge panel needs at least ${STATIC_QUORUM_FLOOR} members`,
      'provision judges from DISTINCT model families (e.g. one claude + one gemini)',
    );
  }
  const enum_ = attestedLineages ?? committedLineages();

  const results = [];
  for (const member of members) {
    const rubric = await scoreAgainstRubric({
      doc, pack, score: member.score, agent: member.agent,
      probeCrossModel: memberProbe(member), log,
    });
    const attestation = resolveAttestation(member);
    const familyServed = attestation.model_attested ? familyOfServedModel(attestation.model_served) : null;
    results.push({
      requested_family: member.family ?? rubric.stamp.family,
      requested_model: member.servedModel ?? rubric.stamp.model,
      role_stamp: rubric.stamp,        // reused Judge attestation machinery (REQUESTED family)
      attestation,                     // SR-5 dispatcher stamp (SERVED model, never argv)
      family_served: familyServed,
      rubric: { verdict: rubric.verdict, aggregate_score: rubric.aggregate_score, criteria: rubric.criteria },
    });
  }

  // INDEPENDENCE FROM DISPATCHER-ATTESTED STAMPS ONLY. An unattested/degraded member is not a
  // dispatcher-attested origin, so it is excluded outright — it can neither be its own origin nor
  // borrow the capped "off-enum" bucket to manufacture a second family. This is what makes the
  // RED single-family probe FAIL honestly (a degraded or same-family second judge cannot pass).
  const attestedReviewers = results
    .filter((r) => r.attestation.model_attested === true)
    .map((r) => ({ lineage: r.family_served }));
  const independentOrigins = countIndependentOrigins(attestedReviewers, { attestedLineages: enum_ });
  const attestedFamilies = [...new Set(attestedReviewers.map((r) => r.lineage).filter(Boolean))].sort();

  // The two-family verdict: ≥ the static quorum floor of DISTINCT ATTESTED origins.
  const crossFamily = independentOrigins >= STATIC_QUORUM_FLOOR;
  const memberVerdicts = results.map((r) => r.rubric.verdict);
  const unanimousPass = memberVerdicts.every((v) => v === 'PASS');

  log(`rubric-panel: ${members.length} judge(s), ${attestedFamilies.length} attested famil${attestedFamilies.length === 1 ? 'y' : 'ies'} ` +
    `[${attestedFamilies.join(', ')}], origins=${independentOrigins}, cross-family=${crossFamily}`);

  return {
    role: PANEL_ROLE,
    contract: 'rubric-panel',
    members: results,
    stamps: results.map((r) => r.role_stamp),       // every role stamp recorded (SR-5)
    attestations: results.map((r) => r.attestation), // every dispatcher stamp recorded
    attestedFamilies,
    independentOrigins,
    crossFamily,
    member_verdicts: memberVerdicts,
    verdict: unanimousPass ? 'PASS' : 'FAIL',
  };
}

// ---------------------------------------------------------------------------
// Wave 3 (Phase C): the CROSS-FAMILY panel is the DEFAULT, with a degrade ladder.
//
// The gate no longer waits to be HANDED a cross-family roster — it TRIES for one by
// default and degrades HONESTLY down a fixed ladder when a second family cannot be
// reached or attested:
//   1. 'cross-family'      — a second model family is probed reachable -> a >=2-family panel.
//   2. 'same-family-fresh' — no second family reachable -> >=2 SAME-family FRESH-CONTEXT
//                            judges (each attested), recorded as a degrade (not cross-family).
//   3. 'attested-degrade'  — not even a same-family served model can be attested -> >=2
//                            UNATTESTED same-family judges, fully degraded + recorded.
// Every rung runs through `runRubricPanel`, so the independence count stays delegated to
// the single committed-enum counter and a degrade can never masquerade as cross-family.
// ---------------------------------------------------------------------------

/** The fixed degrade ladder, best-first. */
export const DEGRADE_LADDER = ['cross-family', 'same-family-fresh', 'attested-degrade'];

/**
 * Run the rubric gate with the cross-family panel as the DEFAULT, degrading honestly when
 * no second family is reachable/attested. With the default probe (no live cross-family key)
 * this records a same-family-fresh degrade + attestation — deterministically.
 *
 * @param {object} o
 * @param {string} o.doc
 * @param {object} o.pack
 * @param {Function} [o.probe=defaultProbeCrossModel]  cross-family capability probe (Wave-9 binds CLIs)
 * @param {Function} [o.score]  injected rubric scorer (test/oracle) OR
 * @param {Function} [o.agent]  the live agent seam
 * @param {string} [o.authorFamily='claude']
 * @param {?string} [o.authorServedModel=null]   the SERVED model id attesting same-family judges
 * @param {?string} [o.secondFamilyServedModel=null]  the SERVED model id for the second-family member
 * @param {Iterable<string>} [o.attestedLineages]
 * @param {Function} [o.log=()=>{}]
 * @returns {Promise<object>} the panel result plus { gate_tier, degraded, degrade_reason }
 */
export async function runDefaultRubricGate({
  doc, pack, probe = defaultProbeCrossModel,
  score, agent,
  authorFamily = 'claude', authorServedModel = null, secondFamilyServedModel = null,
  attestedLineages, log = () => {},
}) {
  const reachable = typeof probe === 'function' ? probe() : null;
  let gate_tier;
  let degrade_reason = null;
  let members;

  if (reachable && reachable.family && reachable.family !== authorFamily) {
    // RUNG 1: cross-family is the DEFAULT.
    gate_tier = 'cross-family';
    members = [
      { family: authorFamily, servedModel: authorServedModel, score, agent },
      {
        family: reachable.family,
        probeCrossModel: () => ({ model: reachable.model || reachable.family, family: reachable.family }),
        servedModel: secondFamilyServedModel || reachable.model || reachable.family,
        score, agent,
      },
    ];
  } else if (authorServedModel) {
    // RUNG 2: no second family reachable -> >=2 same-family FRESH-CONTEXT judges (attested).
    gate_tier = 'same-family-fresh';
    degrade_reason =
      `no cross-family model reachable (probe found ${reachable ? JSON.stringify(reachable) : 'none'}); ` +
      `fell back to ${STATIC_QUORUM_FLOOR} same-family fresh-context ${authorFamily} judge(s)`;
    members = Array.from({ length: STATIC_QUORUM_FLOOR }, () => ({
      family: authorFamily, servedModel: authorServedModel, score, agent,
    }));
  } else {
    // RUNG 3: cannot even attest a same-family served model -> fully degraded judges.
    gate_tier = 'attested-degrade';
    degrade_reason =
      'no cross-family model reachable AND no attested same-family served model; ' +
      'judges run UNATTESTED (fully degraded)';
    members = Array.from({ length: STATIC_QUORUM_FLOOR }, () => ({
      family: authorFamily, attest: attestStamp(null), score, agent,
    }));
  }

  const panel = await runRubricPanel({ doc, pack, members, attestedLineages, log });
  // Degraded unless we both AIMED for cross-family AND the DISPATCHER actually served two
  // attested families (a cross-family aim served same-family is still an honest degrade).
  const degraded = !(gate_tier === 'cross-family' && panel.crossFamily === true);
  if (gate_tier === 'cross-family' && degraded) {
    degrade_reason =
      `cross-family requested but the dispatcher served only ${panel.independentOrigins} ` +
      `attested origin(s) [${panel.attestedFamilies.join(', ')}]`;
  }

  log(`rubric-gate: tier=${gate_tier} degraded=${degraded} cross-family=${panel.crossFamily}` +
    (degrade_reason ? ` (${degrade_reason})` : ''));

  return {
    role: PANEL_ROLE,
    contract: 'rubric-gate',
    gate_tier,
    degraded,
    degrade_reason,
    cross_family: panel.crossFamily,
    independent_origins: panel.independentOrigins,
    attested_families: panel.attestedFamilies,
    attestations: panel.attestations,
    verdict: panel.verdict,
    panel,
  };
}

/**
 * The two-family ASSERTION (the gate Front 3 closes on). A SINGLE-family run — including a
 * Gemini-only enhanced run, an argv-claims-two-but-served-one run, or a degraded second family —
 * does NOT reach ≥2 distinct attested origins and therefore FAILS here (no false close).
 * @param {object} panel  a `runRubricPanel` result
 * @returns {{ok:true, independentOrigins:number, attestedFamilies:string[]}}
 * @throws {HaltError} when fewer than two distinct attested families judged the gate
 */
export function requireTwoFamilies(panel) {
  if (!panel || panel.crossFamily !== true) {
    throw new HaltError(
      `cross-family rubric panel did not reach two attested families ` +
        `(origins=${panel?.independentOrigins ?? 0}, attested=${JSON.stringify(panel?.attestedFamilies ?? [])})`,
      'provision a SECOND judge from a DISTINCT, ATTESTED family; a single-family / degraded / ' +
        'served-same run cannot close Front 3',
    );
  }
  return { ok: true, independentOrigins: panel.independentOrigins, attestedFamilies: panel.attestedFamilies };
}

/**
 * The recordable LIVE ARTIFACT: a compact, honest summary of which attested families judged the
 * one rubric gate (each member's REQUESTED vs SERVED family, its SR-5 stamp, and its rubric
 * verdict), plus the cross-family verdict. This is what the attended live run commits to show
 * "TWO attested families judging one rubric gate."
 * @param {object} panel  a `runRubricPanel` result
 */
export function summarizePanelArtifact(panel) {
  return {
    role: panel.role,
    contract: panel.contract,
    cross_family: panel.crossFamily,
    independent_origins: panel.independentOrigins,
    attested_families: panel.attestedFamilies,
    verdict: panel.verdict,
    members: panel.members.map((m) => ({
      requested_family: m.requested_family,
      family_served: m.family_served,
      model_served: m.attestation.model_served,
      model_attested: m.attestation.model_attested,
      degraded: m.attestation.degraded,
      role_stamp: { family: m.role_stamp.family, mode: m.role_stamp.mode, cross_model: m.role_stamp.cross_model },
      rubric_verdict: m.rubric.verdict,
      aggregate_score: m.rubric.aggregate_score,
    })),
  };
}

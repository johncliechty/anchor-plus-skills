// Wave 27 — Author SKILL.md (full) + invocation smoke test (E3) — project-DONE.
//
// This is the END-TO-END SKILL ENTRY POINT + the two project-DONE gates the Wave-27 done-when names:
//
//   1. THE INVOCATION SMOKE TEST (invokeSkill).  A canned user input is run end-to-end through the
//      REAL autonomous orchestrator (src/orchestrator.mjs) and its REAL VERIFY router
//      (src/verify-router.mjs) — no stubs, no mock router. For the canned proof-bearing input the
//      autonomous tier has NO applicable verifier (Increment-1), so the spine HONESTLY ABSTAINS to
//      CONJECTURAL, routes the claim out-of-model, and emits an advisory payload carrying an
//      emit-not-dispatch commission envelope. The result carries the honest per-claim stamp
//      (NS5): rung + projected belief + verifier-family (null — no family is claimed without an
//      artifact). This is the whole-system demonstration of THE HONESTY LAW's abstain+route arm.
//
//   2. THE 5-GATE PRODUCTIONIZATION CHECKLIST (runProductionizationChecklist).  Five concrete,
//      individually-failing gates that together certify the skill is production-honest:
//        G1 manifest          — SKILL.md exists + names all six pillars + THE HONESTY LAW (Wave-1 checker).
//        G2 usage-contract    — SKILL.md carries the tiered-scope headline + a per-pillar usage contract.
//        G3 acceptance-boundary — SKILL.md declares NS3-lift / NS4 / NS7 as Increment-2 (project-DONE wording).
//        G4 invocation-smoke  — the canned proof input ABSTAINs to CONJECTURAL + routes + advisory + honest stamp.
//        G5 honesty-law-no-green — no proof/conceptual claim reaches VERIFIED; no dispatch / no rung-flip.
//
// The checklist + the manifest checker are the machine gate of project-DONE. Pure node built-ins +
// the project's own spine modules. Runs under `node --test test/`.

import { orchestrate, PILLAR, DISPATCH_DISPOSITION } from './orchestrator.mjs';
import { makeDispatchCapability } from './dispatch-capability.mjs';
import { ROUTE_VERDICT } from './verify-router.mjs';
import { BELIEF, RUNG } from './claim-ledger.mjs';
import { checkManifest, DEFAULT_SKILL_PATH } from './manifest-checker.mjs';
import fs from 'node:fs';
// B4 sole-resolve entry surface: band knobs / certifier arm only via
// resolveRamanujanBand → resolveRamanujanDepthKnobs (never freelanced true / tier-only).
import {
  isCertifierArmed,
  resolveRamanujanBand,
  resolveRamanujanDepthKnobs,
} from './triage-band.mjs';

// ---------------------------------------------------------------------------
// The canned smoke input — a proof-bearing claim with NO autonomous verifier.
// ---------------------------------------------------------------------------

/**
 * THE CANNED INVOCATION INPUT. A proof-bearing claim (the kind Increment-1 can NEVER autonomously
 * settle): a user explicitly routes it to the VERIFY pillar. The honest outcome is ABSTAIN +
 * route-out-of-model + advisory — never a settled verdict. Frozen so a caller cannot mutate the
 * fixture between the smoke run and an assertion.
 */
export const CANNED_PROOF_INPUT = Object.freeze({
  pillar: PILLAR.VERIFY,
  utterance: 'Is the twin-prime conjecture settled?',
  claims: Object.freeze([
    Object.freeze({
      id: 'smoke-twin-primes',
      type: 'proof-bearing',
      statement: 'There are infinitely many primes p such that p + 2 is also prime.',
    }),
  ]),
});

// ---------------------------------------------------------------------------
// invokeSkill — the end-to-end entry point through the REAL orchestrator + router.
// ---------------------------------------------------------------------------

/**
 * Production band resolve for skill entry (B4 sole path).
 * Unlocked → throws RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK.
 * Certifier arm decision is knobs.certifier only.
 *
 * @param {Parameters<typeof resolveRamanujanBand>[0]} [opts]
 * @returns {ReturnType<typeof resolveRamanujanBand>}
 */
export function resolveSkillBand(opts = {}) {
  return resolveRamanujanBand(opts);
}

/**
 * Invoke the skill END-TO-END on a request, through the REAL autonomous orchestrator and its REAL
 * VERIFY router. Returns a frozen summary:
 *   { request, handled, results, settledAny, allRouted, allAdvisory, honestStamps, held }
 * where `results` is the per-claim route result list (verdict / rung / belief / stamp / advisory).
 *
 * The orchestrator wires NO out-of-model dispatcher and NO commissioner (the Increment-1 read-only
 * contract), so a proof-bearing claim has no autonomous path to VERIFIED: it ABSTAINs to CONJECTURAL
 * and routes. `invokeSkill` does NOT itself assert anything is honest — it just runs the spine and
 * surfaces the result; the smoke gate (G4) and the test make the assertions.
 *
 * Optional B4 band surface: when `depth` / `triageLock` / depth env is supplied, resolves knobs via
 * resolveRamanujanBand (sole path) and stamps `band` on the result. Certifier is never armed from
 * tier env alone; unlocked depth throws RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK.
 *
 * @param {object} [request] — defaults to CANNED_PROOF_INPUT. Must be a VERIFY-pillar request.
 * @param {{
 *   ledger?: object,
 *   capability?: object,
 *   depth?: string,
 *   triageLock?: object,
 *   env?: object,
 *   band?: object,
 * }} [opts]
 */
export function invokeSkill(
  request = CANNED_PROOF_INPUT,
  { ledger, capability, depth, triageLock, env, band } = {},
) {
  // Production band: only when caller supplies a lock surface (do not invent depth for smoke path).
  let resolvedBand = band ?? null;
  if (
    resolvedBand == null &&
    (depth != null ||
      triageLock != null ||
      (env &&
        typeof env === 'object' &&
        (env.FOUNDRY_TRIAGE_DEPTH || env.RAMANUJAN_DEPTH)))
  ) {
    resolvedBand = resolveRamanujanBand({ depth, triageLock, env });
  }
  // Structural sole-resolve touch: when band present, certifier arm is knobs-only (never freelanced).
  if (resolvedBand != null) {
    void isCertifierArmed(resolvedBand);
    void resolveRamanujanDepthKnobs(resolvedBand.depth);
  }

  const handled = orchestrate(request, {
    ledger,
    capability,
    band: resolvedBand ?? undefined,
  });
  // Prefer band stamped by orchestrate; fall back to local resolve.
  resolvedBand = handled?.band ?? resolvedBand;

  // The smoke input dispatches to the VERIFY pillar; its output carries the per-claim route results.
  const results =
    handled.disposition === DISPATCH_DISPOSITION.DISPATCH &&
    handled.output &&
    handled.output.kind === 'route' &&
    Array.isArray(handled.output.results)
      ? handled.output.results
      : [];

  const settledAny = results.some((r) => r.settled === true || r.verdict === ROUTE_VERDICT.VERIFIED);
  // Every non-settled result must be routed AND carry an advisory payload (the no-silent-pass arm).
  const allRouted = results.length > 0 && results.every((r) => r.settled === true || r.routed === true);
  const allAdvisory = results.length > 0 && results.every((r) => r.settled === true || r.advisory !== null);
  // An honest stamp: a family-of-record is present ONLY on a settled VERIFIED rung (NS5 — no family
  // is claimed without an artifact). A routed claim therefore carries verifier_family === null.
  const honestStamps = results.every((r) =>
    r.settled ? r.stamp.verifier_family !== null && r.stamp.artifact_backed === true : r.stamp.verifier_family === null,
  );

  return Object.freeze({
    request,
    handled,
    results: Object.freeze(results),
    settledAny,
    allRouted,
    allAdvisory,
    honestStamps,
    // The orchestrator's no-dispatch / no-rung-flip invariant (re-surfaced for the honesty gate).
    held: handled.held === true,
    // B4 band stamp when depth was locked (certifierArmed from frozen knobs only).
    band: resolvedBand,
    certifierArmed: resolvedBand != null ? isCertifierArmed(resolvedBand) : false,
  });
}

export {
  isCertifierArmed,
  resolveRamanujanBand,
  resolveRamanujanDepthKnobs,
};

// ---------------------------------------------------------------------------
// SKILL.md content gates — the markers the productionization checklist asserts.
// ---------------------------------------------------------------------------

/** The per-pillar usage-contract markers the full SKILL.md must carry (Wave-27 deliverable). */
const PILLAR_CONTRACT_TOKENS = Object.freeze([
  'understand',
  'solve',
  'verify',
  'dialogue',
  'formalize',
  'contextualize',
]);

function readSkill(skillPath) {
  if (!fs.existsSync(skillPath)) return null;
  return fs.readFileSync(skillPath, 'utf8');
}

// ---------------------------------------------------------------------------
// The 5-gate productionization checklist.
// ---------------------------------------------------------------------------

/**
 * Run the 5-gate productionization checklist. Each gate is a concrete, independently-failing check;
 * a gate carries { id, name, ok, detail }. Returns a frozen
 *   { ok, passed, total, gates, smoke }
 * where `ok` is true only when ALL FIVE gates pass. `smoke` is the invokeSkill summary G4/G5 share.
 *
 * @param {{skillPath?:string}} [opts]
 */
export function runProductionizationChecklist({ skillPath = DEFAULT_SKILL_PATH } = {}) {
  const gates = [];
  const content = readSkill(skillPath);

  // --- G1: the manifest gate (Wave-1 checker) — SKILL.md names all six pillars + THE HONESTY LAW.
  const manifest = checkManifest(skillPath);
  gates.push({
    id: 'G1-manifest',
    name: 'SKILL.md exists and names all six pillars + THE HONESTY LAW',
    ok: manifest.ok,
    detail: manifest.ok ? 'manifest checker passed' : `missing: ${manifest.missing.join(', ')}`,
  });

  // --- G2: the tiered-scope headline + a per-pillar usage contract.
  let g2ok = false;
  let g2detail = 'SKILL.md not found';
  if (content !== null) {
    const hasHeadline =
      /no autonomous proof verification/i.test(content) && /ACCEPT = computational sub-claim/i.test(content);
    const hasContractHeading = /per-pillar usage contract/i.test(content);
    const missingPillars = PILLAR_CONTRACT_TOKENS.filter((p) => !new RegExp(`\\b${p}\\b`, 'i').test(content));
    g2ok = hasHeadline && hasContractHeading && missingPillars.length === 0;
    g2detail = g2ok
      ? 'tiered-scope headline + per-pillar usage contract present'
      : [
          hasHeadline ? null : 'missing tiered-scope headline',
          hasContractHeading ? null : 'missing per-pillar usage contract heading',
          missingPillars.length ? `usage contract missing pillars: ${missingPillars.join(', ')}` : null,
        ]
          .filter(Boolean)
          .join('; ');
  }
  gates.push({ id: 'G2-usage-contract', name: 'Tiered-scope headline + per-pillar usage contract', ok: g2ok, detail: g2detail });

  // --- G3: the Increment-1 acceptance boundary — NS3-lift / NS4 / NS7 declared as Increment-2.
  let g3ok = false;
  let g3detail = 'SKILL.md not found';
  if (content !== null) {
    const declaresAbstainArms = /NS abstain-arms DONE/i.test(content);
    const declaresIncrement2 =
      /Increment-2/i.test(content) && /NS3/i.test(content) && /NS4/i.test(content) && /NS7/i.test(content);
    g3ok = declaresAbstainArms && declaresIncrement2;
    g3detail = g3ok
      ? 'acceptance boundary declares NS abstain-arms DONE; NS3-lift / NS4 / NS7 positive-arm = Increment-2'
      : [
          declaresAbstainArms ? null : 'missing "NS abstain-arms DONE"',
          declaresIncrement2 ? null : 'missing NS3/NS4/NS7 → Increment-2 declaration',
        ]
          .filter(Boolean)
          .join('; ');
  }
  gates.push({ id: 'G3-acceptance-boundary', name: 'Increment-1 acceptance boundary declared (NS3-lift/NS4/NS7 = Increment-2)', ok: g3ok, detail: g3detail });

  // --- G4 + G5 share ONE real end-to-end invocation through the REAL router.
  const smoke = invokeSkill();
  const proofResult = smoke.results.find((r) => r.claim_type === 'proof-bearing') || null;

  // G4: invocation smoke — the canned proof input ABSTAINs to CONJECTURAL + routes + advisory + honest stamp.
  const g4ok =
    proofResult !== null &&
    proofResult.verdict === ROUTE_VERDICT.ABSTAIN &&
    proofResult.routed === true &&
    proofResult.settled === false &&
    proofResult.belief === BELIEF.CONJECTURAL &&
    proofResult.rung === RUNG.UNVERIFIED &&
    proofResult.advisory !== null &&
    proofResult.advisory.commission != null &&
    proofResult.advisory.belief === BELIEF.CONJECTURAL &&
    smoke.allRouted &&
    smoke.allAdvisory &&
    smoke.honestStamps;
  gates.push({
    id: 'G4-invocation-smoke',
    name: 'Canned proof input → CONJECTURAL + routed + advisory payload + honest per-claim stamp (REAL router)',
    ok: g4ok,
    detail: g4ok
      ? `proof claim ABSTAINed to CONJECTURAL and routed out-of-model with an advisory commission (stamp verifier_family=${proofResult.stamp.verifier_family})`
      : 'the canned proof input did not produce a correctly-stamped abstain/route',
  });

  // G5: THE HONESTY LAW — no proof/conceptual claim reaches VERIFIED, in BOTH gate states (W3 Scope B).
  //   (a) GATE CLOSED (the default smoke, no capability): no green, no dispatch, no rung-flip (held).
  const g5ClosedOk = smoke.settledAny === false && smoke.honestStamps === true && smoke.held === true;
  //   (b) GATE OPEN (a VALID capability opens the gate): the SAME proof-bearing claim STILL does not settle
  //       — the autonomy loosening NEVER lets a proof/conceptual claim reach VERIFIED (only the in-grammar
  //       firewall class can). A fake dispatcher suffices here: a proof claim never reaches the minter, so
  //       no real subprocess/durable-nonce is needed to prove it stays UNVERIFIED under an open gate.
  const openCapability = makeDispatchCapability({
    dispatcher: { consumeArtifact: () => true, family: 'firewall-subprocess' },
    mint: () => ({}),
  });
  const openSmoke = invokeSkill(CANNED_PROOF_INPUT, { capability: openCapability });
  const g5OpenOk =
    openSmoke.handled.gated === true && // the gate genuinely OPENED (VERIFY pillar + valid capability)
    openSmoke.settledAny === false && // ...yet the proof claim still did not settle
    openSmoke.honestStamps === true;
  const g5ok = g5ClosedOk && g5OpenOk;
  gates.push({
    id: 'G5-honesty-law-no-green',
    name: 'No proof/conceptual claim reaches VERIFIED — gate CLOSED (no dispatch/no rung-flip) AND gate OPEN (still no green)',
    ok: g5ok,
    detail: g5ok
      ? 'closed gate: no green, invariants held; OPEN gate (valid capability): the proof claim STILL does not settle (Honesty Law survives the autonomy loosening)'
      : `honesty-law violation (closed: settledAny=${smoke.settledAny}, held=${smoke.held}; open: gated=${openSmoke.handled.gated}, settledAny=${openSmoke.settledAny})`,
  });

  const passed = gates.filter((g) => g.ok).length;
  return Object.freeze({
    ok: passed === gates.length,
    passed,
    total: gates.length,
    gates: Object.freeze(gates.map((g) => Object.freeze(g))),
    smoke,
  });
}

// CLI entry point: run the checklist + print each gate; exit non-zero on any failing gate.
if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1].replace(/\\/g, '/')}`).href) {
  const report = runProductionizationChecklist();
  for (const g of report.gates) {
    console.log(`${g.ok ? 'PASS' : 'FAIL'}  ${g.id}: ${g.name}\n        ${g.detail}`);
  }
  if (report.ok) {
    console.log(`\nOK: project-DONE — ${report.passed}/${report.total} productionization gates pass.`);
    process.exit(0);
  } else {
    console.error(`\nFAIL: ${report.passed}/${report.total} gates pass — ${report.total - report.passed} failing.`);
    process.exit(1);
  }
}

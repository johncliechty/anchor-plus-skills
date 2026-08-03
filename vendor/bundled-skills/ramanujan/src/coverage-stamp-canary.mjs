// Wave 12 — Coverage-stamp canary (B2b — A2 coverage-stamp).
//
// THE A2 COVERAGE-STAMP CANARY. Wave 11 builds a verification firewall and stamps an HONEST
// warranty derived from how much of its reading-independent anchor battery actually held
// (anchor_coverage + warranty_excludes[]). This canary is the TRIPWIRE that keeps that warranty
// honest at the rung boundary: it RE-DERIVES, from the firewall's own EXECUTION TRACE (the anchor
// cross-checks it built + ran), the coverage relation
//
//     predicate_domain ⊇ claim_domain
//
// where claim_domain = the reading-independent anchor checks the CLAIM is asserted over (the full
// battery) and predicate_domain = the anchors the verification PREDICATE actually ESTABLISHED
// (held) in the trace. When that containment FAILS — i.e. warranty_excludes[] is non-empty /
// anchor_coverage < full — the claim is only PARTIALLY covered, so the coverage stamp CAPS the rung
// ceiling at CLAIMED: a VERIFIED rung is refused. (This is the A2-coverage arm of THE HONESTY LAW:
// you may not bank a settled rung over a domain your predicate never covered.)
//
// The canary is GREEN on the genuine spine and FAILS THE BUILD (non-zero) on its planted violation —
// the done-when: an OVER-TRUSTED REDUCED-WARRANTY PASS, i.e. a firewall whose warranty_excludes[] is
// non-empty that is nonetheless settled to OBSERVED/VERIFIED. The load-bearing assertion is that the
// REALIZED rung never exceeds the re-derived coverage ceiling; the over-trust plant lifts a
// reduced-warranty build to OBSERVED, the realized rung overshoots the CLAIMED ceiling, and the
// canary trips.
//
// Like the Wave-6 honesty canaries, the warrant is an INDEPENDENT re-derivation (here: coverage
// re-computed from the execution trace), never a trusted stamp — so a build that LIES about its own
// coverage, or an applier that over-trusts a reduced warranty, is caught the same way. Exercises the
// REAL Wave-11 builder + the REAL shared spine (the A1 ledger, the Wave-9 firewall subprocess, the
// Wave-4 adjudication substrate). Runs under `node --test test/` and as a CLI (exit 0 / non-zero).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ClaimLedger, RUNG, BELIEF, compareRungs } from './claim-ledger.mjs';
import {
  buildFirewall,
  applyFirewallCap,
  ANCHOR_NAMES,
  ANCHOR_COVERAGE,
  GENUINE_NARRATIVE,
  REDUCED_WARRANTY_NARRATIVE,
} from './firewall-builder.mjs';
import {
  settleComputationViaFirewall,
  FIREWALL_FAMILY,
} from './firewall-subprocess.mjs';
import {
  VERDICT,
  DurableNonceStore,
  AdjudicationDispatcher,
  loadDurabilitySubstrate,
} from './adjudication.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** This wave's single canary name (kept as a list to mirror the Wave-6 suite shape). */
export const COVERAGE_CANARY_NAMES = Object.freeze(['coverage-stamp']);

// A monotone scratch-file counter so each durability exercise gets its own "disk".
let canaryFileSeq = 0;

// ---------------------------------------------------------------------------
// Assertion helper — mirrors the Wave-6 honesty-canary shape exactly.
// ---------------------------------------------------------------------------

/** A single pinned coverage-stamp assertion. `ok` false => the canary trips (build fails). */
function A(name, ok, detail) {
  return { name, ok: Boolean(ok), detail: ok ? undefined : detail };
}

function summarize(name, assertions) {
  const failures = assertions
    .filter((a) => !a.ok)
    .map((a) => `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  return { name, ok: failures.length === 0, assertions, failures };
}

/** Order-insensitive membership equality of two string lists. */
function sameMembers(a, b) {
  const sa = [...a].sort();
  const sb = [...b].sort();
  return sa.length === sb.length && sa.every((x, i) => x === sb[i]);
}

// ---------------------------------------------------------------------------
// THE COVERAGE STAMP — predicate_domain ⊇ claim_domain, re-derived from the execution trace.
// ---------------------------------------------------------------------------

/**
 * Re-derive the A2 coverage stamp from a firewall build's EXECUTION TRACE (build.tests — the anchor
 * cross-checks the firewall built + ran). Independent of the build's OWN warranty stamps, so a build
 * that mis-reports its coverage is caught by the cross-check below.
 *
 *   claim_domain     = the reading-independent anchor checks the CLAIM is asserted over (the full battery).
 *   predicate_domain = the anchors the verification predicate actually ESTABLISHED (held) in the trace.
 *   covered          = predicate_domain ⊇ claim_domain (every required anchor held).
 *   warranty_excludes= claim_domain \ predicate_domain.
 *   rung_ceiling     = covered ? OBSERVED : CLAIMED   (caps at CLAIMED when not fully covered).
 *
 * @param {object} build  a Wave-11 firewall build (with .tests / .claim_id).
 * @returns frozen { claim_id, claim_domain[], predicate_domain[], warranty_excludes[], covered, anchor_coverage, rung_ceiling }
 */
export function coverageStamp(build) {
  if (!build || typeof build !== 'object') throw new Error('coverageStamp: a firewall build is required');
  const trace = Array.isArray(build.tests) ? build.tests : [];
  const held = new Set(trace.filter((t) => t && t.holds === true).map((t) => t.anchor));

  const claim_domain = ANCHOR_NAMES.slice();
  const predicate_domain = ANCHOR_NAMES.filter((n) => held.has(n));
  const warranty_excludes = claim_domain.filter((n) => !held.has(n)); // claim_domain \ predicate_domain
  const covered = warranty_excludes.length === 0; // predicate_domain ⊇ claim_domain

  let anchor_coverage;
  if (predicate_domain.length === claim_domain.length) anchor_coverage = ANCHOR_COVERAGE.FULL;
  else if (predicate_domain.length === 0) anchor_coverage = ANCHOR_COVERAGE.NONE;
  else anchor_coverage = ANCHOR_COVERAGE.PARTIAL;

  // The honest ceiling: a fully-covered claim may reach OBSERVED; anything less caps at CLAIMED.
  const rung_ceiling = covered ? RUNG.OBSERVED : RUNG.CLAIMED;

  return Object.freeze({
    claim_id: build.claim_id,
    claim_domain: Object.freeze(claim_domain),
    predicate_domain: Object.freeze(predicate_domain),
    warranty_excludes: Object.freeze(warranty_excludes),
    covered,
    anchor_coverage,
    rung_ceiling,
  });
}

// ---------------------------------------------------------------------------
// Spine setup (mirrors the Wave-6/11 durability harness).
// ---------------------------------------------------------------------------

async function ensureCtx(ctx = {}) {
  const substrate = ctx.substrate || (await loadDurabilitySubstrate());
  const scratchDir = ctx.scratchDir || fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w12-'));
  return { substrate, scratchDir };
}

function freshDispatcher(substrate, scratchDir) {
  const store = DurableNonceStore.load(substrate, path.join(scratchDir, `coverage-${canaryFileSeq++}.checkpoint.json`));
  return new AdjudicationDispatcher({ store, family: FIREWALL_FAMILY });
}

/**
 * THE PLANT — an OVER-TRUSTED applier. It IGNORES the coverage stamp / the build's rung_cap and
 * settles the firewall's ref-fn straight through the Wave-9 positive path to OBSERVED/VERIFIED. On a
 * reduced-warranty build (warranty_excludes != ∅) that is exactly the over-trusted reduced-warranty
 * pass the canary must catch.
 */
function overTrustedApply(build, ledger, { dispatcher }) {
  if (!ledger.has(build.claim_id)) ledger.assert({ id: build.claim_id, type: 'computational' });
  const settle = settleComputationViaFirewall(ledger, dispatcher, build.claim_id, build.ref_fn, { domain: build.domain });
  return Object.freeze({ verdict: settle.verdict === VERDICT.VERIFIED ? 'VERIFIED' : 'ABSTAIN', settle });
}

// ===========================================================================
// THE A2 COVERAGE-STAMP CANARY.
// ===========================================================================

/**
 * Run the coverage-stamp canary. GREEN on the genuine spine; trips on the planted over-trusted
 * reduced-warranty pass (ctx.plant === 'over-trust').
 *
 * @param {{substrate?, scratchDir?, plant?: 'over-trust'}} [ctx]
 * @returns { name, ok, assertions, failures }
 */
export async function canaryCoverageStamp(ctx = {}) {
  const { substrate, scratchDir } = await ensureCtx(ctx);
  const plant = ctx.plant;
  const assertions = [];

  // -------------------------------------------------------------------------
  // (1) GENUINE (full-coverage) firewall: predicate_domain ⊇ claim_domain; ceiling OBSERVED. This
  //     keeps the canary NON-VACUOUS — a fully-covered claim is allowed to settle.
  // -------------------------------------------------------------------------
  {
    const build = buildFirewall(GENUINE_NARRATIVE);
    const stamp = coverageStamp(build);

    // the re-derived coverage agrees with the build's OWN honest stamps (no silent divergence).
    assertions.push(A(
      'genuine: re-derived coverage matches the build stamp (no silent divergence)',
      stamp.anchor_coverage === build.anchor_coverage && sameMembers(stamp.warranty_excludes, build.warranty_excludes),
      `re-derived ${stamp.anchor_coverage}/${JSON.stringify(stamp.warranty_excludes)} != build ${build.anchor_coverage}/${JSON.stringify(build.warranty_excludes)}`,
    ));
    assertions.push(A(
      'genuine: predicate_domain ⊇ claim_domain => full coverage, empty warranty_excludes, ceiling OBSERVED',
      stamp.covered && stamp.warranty_excludes.length === 0 && stamp.rung_ceiling === RUNG.OBSERVED,
      `genuine firewall not fully covered: ${JSON.stringify(stamp)}`,
    ));

    const ledger = new ClaimLedger();
    const verdict = applyFirewallCap(build, ledger, { dispatcher: freshDispatcher(substrate, scratchDir) });
    const rung = ledger.rungOf(build.claim_id);
    assertions.push(A(
      'genuine: a fully-covered firewall legitimately settles OBSERVED/VERIFIED, within its ceiling (not vacuous)',
      rung === RUNG.OBSERVED && verdict.belief === BELIEF.VERIFIED && compareRungs(rung, stamp.rung_ceiling) <= 0,
      `genuine firewall did not legitimately reach OBSERVED: rung=${rung}, belief=${verdict.belief}`,
    ));
  }

  // -------------------------------------------------------------------------
  // (2) REDUCED-WARRANTY firewall (warranty_excludes != ∅): predicate_domain does NOT ⊇ claim_domain,
  //     so the coverage ceiling is CLAIMED and a VERIFIED rung must be refused. The 'over-trust' plant
  //     settles it to OBSERVED anyway — the over-trusted reduced-warranty pass.
  // -------------------------------------------------------------------------
  {
    const build = buildFirewall(REDUCED_WARRANTY_NARRATIVE);
    const stamp = coverageStamp(build);

    assertions.push(A(
      'reduced: warranty_excludes != ∅ and anchor_coverage < full (the over-trust risk surface exists)',
      stamp.warranty_excludes.length > 0 && stamp.anchor_coverage !== ANCHOR_COVERAGE.FULL,
      `the reduced-warranty fixture is unexpectedly fully covered: ${JSON.stringify(stamp)}`,
    ));
    assertions.push(A(
      'reduced: predicate_domain does NOT ⊇ claim_domain => the coverage stamp caps the ceiling at CLAIMED',
      !stamp.covered && stamp.rung_ceiling === RUNG.CLAIMED,
      `coverage stamp failed to cap a partially-covered claim at CLAIMED: ${JSON.stringify(stamp)}`,
    ));
    // and the re-derived stamp still agrees with the build's own honest warranty stamps.
    assertions.push(A(
      'reduced: re-derived coverage matches the build stamp (no silent divergence)',
      stamp.anchor_coverage === build.anchor_coverage && sameMembers(stamp.warranty_excludes, build.warranty_excludes),
      `re-derived ${stamp.anchor_coverage}/${JSON.stringify(stamp.warranty_excludes)} != build ${build.anchor_coverage}/${JSON.stringify(build.warranty_excludes)}`,
    ));

    // Realize the rung. The PLANT over-trusts the reduced warranty and settles to OBSERVED.
    const ledger = new ClaimLedger();
    if (plant === 'over-trust') {
      overTrustedApply(build, ledger, { dispatcher: freshDispatcher(substrate, scratchDir) });
    } else {
      applyFirewallCap(build, ledger, { dispatcher: freshDispatcher(substrate, scratchDir) });
    }
    const realizedRung = ledger.rungOf(build.claim_id);
    const realizedBelief = ledger.beliefOf(build.claim_id);

    // THE LOAD-BEARING ASSERTION (the done-when): a build with warranty_excludes != ∅ may NEVER
    // realize a rung ABOVE its coverage ceiling. The over-trust plant lifts it to OBSERVED => trips.
    assertions.push(A(
      'reduced: the realized rung never exceeds the coverage ceiling (no over-trusted reduced-warranty pass)',
      compareRungs(realizedRung, stamp.rung_ceiling) <= 0,
      `over-trusted reduced-warranty pass: realized rung ${realizedRung} exceeds the coverage ceiling ${stamp.rung_ceiling} despite warranty_excludes=${JSON.stringify(stamp.warranty_excludes)}`,
    ));
    // ...and the VERIFIED rung is refused on a reduced-warranty claim (the GWT).
    assertions.push(A(
      'reduced: a VERIFIED rung is refused (capped at CLAIMED) — the GWT',
      realizedBelief !== BELIEF.VERIFIED && realizedRung !== RUNG.OBSERVED,
      `a reduced-warranty claim reached VERIFIED/OBSERVED: rung=${realizedRung}, belief=${realizedBelief}`,
    ));
  }

  return summarize('coverage-stamp', assertions);
}

// ---------------------------------------------------------------------------
// The (single-canary) suite + exit code, mirroring the Wave-6 runner contract.
// ---------------------------------------------------------------------------

/**
 * Run the coverage-stamp canary suite (clean by default). Returns
 * { ok, canaries:[{name, ok, assertions, failures}], failures:[ "coverage-stamp: reason", ... ] }.
 *
 * @param {{substrate?, scratchDir?, plant?: 'over-trust'}} [ctx]
 */
export async function runCoverageStampCanary(ctx = {}) {
  const { substrate, scratchDir } = await ensureCtx(ctx);
  const created = !ctx.scratchDir;
  try {
    const result = await canaryCoverageStamp({ substrate, scratchDir, plant: ctx.plant });
    return {
      ok: result.ok,
      canaries: [result],
      failures: result.failures.map((f) => `coverage-stamp: ${f}`),
    };
  } finally {
    if (created) {
      try { fs.rmSync(scratchDir, { recursive: true, force: true }); } catch { /* best-effort */ }
    }
  }
}

/** Map a suite result to a process exit code (0 = green, non-zero on a tripped canary). */
export function coverageCanaryExitCode(result) {
  return result.ok ? 0 : 1;
}

// Re-export the rung/belief vocabulary so tests can branch without a second import.
export { RUNG, BELIEF };

// ---------------------------------------------------------------------------
// CLI: `node src/coverage-stamp-canary.mjs` — exit 0 green / 1 on a tripped canary.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = await runCoverageStampCanary();
  if (result.ok) {
    const a = result.canaries.reduce((s, c) => s + c.assertions.length, 0);
    console.log(`OK: A2 coverage-stamp canary green (${a} pinned assertions).`);
    process.exit(0);
  } else {
    console.error('FAIL: A2 coverage-stamp canary tripped:');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}

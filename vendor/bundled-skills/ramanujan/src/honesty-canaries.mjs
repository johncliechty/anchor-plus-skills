// Wave 6 — Honesty-Law canary suite, core (A2-core).
//
// THE HONESTY LAW's tripwires. Four canaries that each EXERCISE the real A1 ledger + the A1.5
// adjudication substrate and assert a load-bearing honesty invariant by VERIFYING THE
// RE-EXECUTED ARTIFACT (propose != adjudicate). Each canary is GREEN on the genuine spine and
// FAILS THE BUILD (non-zero) on its planted violation:
//
//   (1) INDEPENDENCE.            A claim reaches a VERIFIED rung ONLY through an artifact minted
//       by an OUT-OF-MODEL adjudicator (family-of-record != the proposing/same-family) whose
//       recorded stdout_hash RE-EXECUTES to the same hash. Plant: a same-family object that
//       self-adjudicates with a self-authored stamp (propose == adjudicate) — or fabricates the
//       stdout_hash. Either way independence catches it.
//   (2) INVERTED-COMPLETENESS.  The law is deliberately INCOMPLETE: for EVERY input it cannot
//       reproduce (no artifact / malformed / a fabricated stdout_hash that does NOT re-execute /
//       cross-claim), the honest verdict is ABSTAIN — a green is emitted IFF the artifact is
//       valid, fresh, AND re-executes. Plant: an over-trusting verifier that skips re-execution
//       and emits VERIFIED on a fabricated-result artifact (a reduced-warranty pass).
//   (3) TRANSITIONS-INVARIANT.  The ONLY rung transition into OBSERVED is an adjudicated one
//       backed by a re-executing artifact, and no transition lowers a rank. Plant: a raw
//       promote() straight to OBSERVED that bypasses the adjudication gate (no artifact).
//   (4) FLIP-LAW.               The sticky ledger refuses to FLIP a rung on mere re-assertion or
//       a same-family self-authored VERIFIED stamp; a single-use (spent) artifact cannot re-flip;
//       the only rung-raise is a fresh adjudicated re-executed promote. Plant: a non-sticky
//       ledger that flips the rung up on a self-authored re-assertion.
//
// RE-EXECUTION in Wave 6. The CLOSED default-deny grammar is Wave 8 and the OUT-OF-MODEL firewall
// SUBPROCESS that runs it is Wave 9. Wave 6 re-executes IN-PROCESS over the SAME exact-arithmetic
// canonicalization the Wave-4 substrate exposes: the canary RE-COMPUTES the literal result
// (bigint only — NO float — deterministic by construction) and RE-HASHES it via
// canonicalStdoutHash, then compares against the artifact's recorded stdout_hash. So a same-family
// proposer that LIES about a result (fabricated stdout_hash) is caught by the canary's independent
// re-execution — the warrant is the re-execution, never a trusted stamp. (Wave 9 swaps the
// in-process re-compute for a re-run of the real child on the same input; the canary contract is
// identical.)
//
// Dependency-free apart from the project's own A1 / A1.5 modules and the inherited durability
// substrate (resolved via the pinned inherits.manifest.json). Runs under `node --test test/` and
// as a CLI (exit 0 green / non-zero on any planted violation).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  ClaimLedger,
  RUNG,
  BELIEF,
  rungRank,
  compareRungs,
} from './claim-ledger.mjs';
import {
  DurableNonceStore,
  AdjudicationDispatcher,
  adjudicatedPromoteToVerified,
  canonicalStdoutHash,
  VERDICT,
  loadDurabilitySubstrate,
} from './adjudication.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/**
 * The pinned OUT-OF-MODEL adjudication family-of-record for the autonomous (Increment-1) tier:
 * the firewall subprocess. It is, by construction, a DIFFERENT family from the proposing model —
 * that distinctness is THE HONESTY LAW's "no same-family-authored object reaches VERIFIED". The
 * independence canary checks every VERIFIED rung's family-of-record is in this set.
 */
export const OUT_OF_MODEL_FAMILY = 'firewall-subprocess';
export const OUT_OF_MODEL_FAMILIES = Object.freeze(new Set([OUT_OF_MODEL_FAMILY]));

/** The four core canary names (order is informational). */
export const CANARY_NAMES = Object.freeze([
  'independence',
  'inverted-completeness',
  'transitions-invariant',
  'flip-law',
]);

// A monotone scratch-file counter so each durability exercise gets its own "disk".
let canaryFileSeq = 0;

// ---------------------------------------------------------------------------
// Assertion helper — every canary returns a flat list of these (mirrors the Wave-5 gate).
// ---------------------------------------------------------------------------

/** A single pinned honesty-law assertion. `ok` false => the canary trips (build fails). */
function A(name, ok, detail) {
  return { name, ok: Boolean(ok), detail: ok ? undefined : detail };
}

function summarize(name, assertions) {
  const failures = assertions
    .filter((a) => !a.ok)
    .map((a) => `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  return { name, ok: failures.length === 0, assertions, failures };
}

// ---------------------------------------------------------------------------
// The in-process exact-arithmetic RE-EXECUTOR (bigint only — NO float).
//
// A tiny literal-computation form, just enough to drive the canaries with a real
// re-executable computation incl. a NESTED COMPOSITION (a bounded sum of products of literals).
// The CLOSED default-deny grammar (Wave 8) and the out-of-model subprocess (Wave 9) supersede
// this; Wave 6 only needs a deterministic re-compute to RE-HASH against an artifact.
//
//   node := bigint                                   (a literal)
//         | { var: string }                          (a bound sum-variable)
//         | { op:'add'|'sub'|'mul', args: node[] }   (finite arithmetic)
//         | { op:'sum', var, from:bigint, to:bigint, term: node }   (bounded finite sum)
//
// Anything else — a JS float/number, a symbolic/unbounded/unknown node — THROWS, and the canary
// treats a throw as "not re-executable".
// ---------------------------------------------------------------------------

export function evalLiteral(node, env = {}) {
  if (typeof node === 'bigint') return node;
  if (typeof node === 'number') {
    throw new Error('out-of-grammar: a JS float/number literal (exact bigint arithmetic only)');
  }
  if (node && typeof node === 'object' && !Array.isArray(node)) {
    // A bare variable-reference LEAF — only when it is not an `op` node (a sum node also carries a
    // `var` field naming its bound variable, so `op` must be matched first).
    if (!('op' in node) && 'var' in node) {
      if (!(node.var in env)) throw new Error(`unbound variable: ${JSON.stringify(node.var)}`);
      return env[node.var];
    }
    if (node.op === 'add' || node.op === 'sub' || node.op === 'mul') {
      if (!Array.isArray(node.args) || node.args.length === 0) {
        throw new Error(`out-of-grammar: ${node.op} requires a non-empty args[]`);
      }
      const vals = node.args.map((a) => evalLiteral(a, env));
      if (node.op === 'add') return vals.reduce((a, b) => a + b);
      if (node.op === 'sub') return vals.reduce((a, b) => a - b);
      return vals.reduce((a, b) => a * b);
    }
    if (node.op === 'sum') {
      const { var: v, from, to, term } = node;
      if (typeof v !== 'string' || typeof from !== 'bigint' || typeof to !== 'bigint') {
        throw new Error('out-of-grammar: sum needs { var:string, from:bigint, to:bigint, term } (bounded literal range)');
      }
      let acc = 0n;
      for (let k = from; k <= to; k += 1n) acc += evalLiteral(term, { ...env, [v]: k });
      return acc;
    }
  }
  throw new Error('out-of-grammar node (symbolic/unbounded/unknown)');
}

/** Re-execute a literal computation to its canonical stdout object { computation, result }. */
export function reexecute(computation) {
  return { computation, result: evalLiteral(computation) };
}

/** The out-of-band RE-HASH of a re-executed literal computation (SHA-256 of canonical stdout). */
export function reexecHash(computation) {
  return canonicalStdoutHash(reexecute(computation));
}

/**
 * Does this artifact's recorded stdout_hash RE-EXECUTE? Re-compute the literal result
 * independently and compare hashes. A computation that does not re-execute (out-of-grammar) or a
 * fabricated/mismatched stdout_hash => false. This is the canary's warrant (propose != adjudicate).
 */
export function reexecutionAgrees(artifact, computation) {
  if (!artifact || typeof artifact.stdout_hash !== 'string') return false;
  let recomputed;
  try {
    recomputed = reexecHash(computation);
  } catch {
    return false; // not re-executable — the honest verdict can never be VERIFIED
  }
  return artifact.stdout_hash === recomputed;
}

// A canonical in-class literal computation = sum_{k=1}^{3} k = 6 (a bounded sum; NESTED variants
// below multiply the term to make a bounded sum of products of literals).
export const SAMPLE_SUM = Object.freeze({ op: 'sum', var: 'k', from: 1n, to: 3n, term: { var: 'k' } });
export const SAMPLE_NESTED = Object.freeze({
  op: 'sum', var: 'k', from: 1n, to: 3n, term: { op: 'mul', args: [{ var: 'k' }, 2n] },
}); // = 2+4+6 = 12

/**
 * Mint a computational adjudication artifact for a literal computation. By default the stdout_hash
 * is the GENUINE re-execution hash; `fabricateHash:true` records a LIE (a result the computation
 * does not actually produce) — the same-family forgery the canaries must catch.
 */
function mintComputationalArtifact(dispatcher, claim_id, computation, { domain = 'arithmetic', fabricateHash = false } = {}) {
  const stdout_hash = fabricateHash
    ? canonicalStdoutHash({ computation, result: '___FORGED___' }) // will NOT re-execute
    : reexecHash(computation);
  return dispatcher.mintArtifact(claim_id, domain, { stdout_hash, exit_code: 0 });
}

// ---------------------------------------------------------------------------
// Per-canary spine setup.
// ---------------------------------------------------------------------------

async function ensureCtx(ctx = {}) {
  const substrate = ctx.substrate || (await loadDurabilitySubstrate());
  const scratchDir = ctx.scratchDir || fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w6-'));
  return { substrate, scratchDir };
}

function freshStore(substrate, scratchDir) {
  return DurableNonceStore.load(substrate, path.join(scratchDir, `canary-${canaryFileSeq++}.checkpoint.json`));
}

// ===========================================================================
// (1) INDEPENDENCE — propose != adjudicate; the VERIFIED stamp is an out-of-model family's.
// ===========================================================================

/**
 * @param {{substrate?, scratchDir?, plant?: 'self-adjudicate' | 'fabricated-stdout'}} [ctx]
 */
export async function canaryIndependence(ctx = {}) {
  const { substrate, scratchDir } = await ensureCtx(ctx);
  const plant = ctx.plant;
  const assertions = [];

  // The SAME-FAMILY proposer (the model that authored the claim). A VERIFIED rung must NOT be
  // stamped by this family — that is the law.
  const PROPOSER_FAMILY = 'same-family:model';

  // PLANT 'self-adjudicate': the proposer constructs the adjudicator with ITS OWN family and
  // self-stamps (propose == adjudicate). Otherwise the adjudicator is the out-of-model firewall.
  const adjudFamily = plant === 'self-adjudicate' ? PROPOSER_FAMILY : OUT_OF_MODEL_FAMILY;

  const store = freshStore(substrate, scratchDir);
  const dispatcher = new AdjudicationDispatcher({ store, family: adjudFamily });
  const ledger = new ClaimLedger();
  ledger.assert({ id: 'IND', type: 'computational' });

  const computation = SAMPLE_SUM;
  // PLANT 'fabricated-stdout': the proposer lies about the computed result.
  const artifact = mintComputationalArtifact(dispatcher, 'IND', computation, {
    fabricateHash: plant === 'fabricated-stdout',
  });

  // (a) RE-EXECUTION: the artifact's stdout_hash must reproduce by independent re-computation.
  const reAgrees = reexecutionAgrees(artifact, computation);
  assertions.push(A(
    'the VERIFIED artifact re-executes to its recorded stdout_hash (independent re-compute)',
    reAgrees,
    'the recorded stdout_hash does not reproduce — a fabricated/same-family-authored result',
  ));

  const verdict = adjudicatedPromoteToVerified(ledger, 'IND', { artifact, dispatcher });

  // (b) INDEPENDENCE: a VERIFIED rung's family-of-record must be an OUT-OF-MODEL family, distinct
  //     from the proposer. (The gate stamps ONLY the dispatcher family — Wave 4 — so a self-
  //     adjudicating dispatcher surfaces the proposer's own family here, and the canary trips.)
  if (verdict.verdict === VERDICT.VERIFIED) {
    const family = verdict.family;
    assertions.push(A(
      'the VERIFIED family-of-record is an out-of-model family, NOT the proposer (no self-authored stamp)',
      OUT_OF_MODEL_FAMILIES.has(family) && family !== PROPOSER_FAMILY,
      `family-of-record ${JSON.stringify(family)} is the same-family proposer / not out-of-model (propose == adjudicate)`,
    ));
    // and the ledger's recorded promote stamp agrees (sole-writer = the dispatcher).
    const promoteEvent = ledger.get('IND').history.find((h) => h.event === 'promote');
    assertions.push(A(
      'the ledger promote stamp records the out-of-model family-of-record',
      promoteEvent && OUT_OF_MODEL_FAMILIES.has(promoteEvent.family) && promoteEvent.family !== PROPOSER_FAMILY,
      `ledger stamped family ${JSON.stringify(promoteEvent && promoteEvent.family)}`,
    ));
  } else {
    // A genuine (un-planted) independence run MUST reach VERIFIED — otherwise the canary is vacuous.
    // The fabricated-stdout plant trips assertion (a) above; the gate still emits VERIFIED (Wave-4
    // does not re-execute), so we only land here if the substrate itself failed to adjudicate.
    assertions.push(A(
      'a genuine adjudicated computation reaches VERIFIED (the canary is not vacuous)',
      plant === 'fabricated-stdout', // expected non-VERIFIED only under a plant that pre-trips (a)
      `the genuine adjudication did not reach VERIFIED: ${verdict.reason || verdict.verdict}`,
    ));
  }

  return summarize('independence', assertions);
}

// ===========================================================================
// (2) INVERTED-COMPLETENESS — a green IFF valid+fresh+re-executes; everything else ABSTAINS.
// ===========================================================================

/**
 * The honest verdict overlays RE-EXECUTION on the Wave-4 gate: VERIFIED iff the gate adjudicated
 * AND the artifact re-executes. The PLANT 'skip-reexecution' drops the re-execution conjunct (an
 * over-trusting reduced-warranty verifier) — so a fabricated-result artifact (which the Wave-4
 * gate alone promotes) is over-trusted to VERIFIED, and the canary trips.
 *
 * @param {{substrate?, scratchDir?, plant?: 'skip-reexecution'}} [ctx]
 */
export async function canaryInvertedCompleteness(ctx = {}) {
  const { substrate, scratchDir } = await ensureCtx(ctx);
  const useReexec = ctx.plant !== 'skip-reexecution';
  const assertions = [];

  const store = freshStore(substrate, scratchDir);
  const dispatcher = new AdjudicationDispatcher({ store, family: OUT_OF_MODEL_FAMILY });
  const computation = SAMPLE_NESTED;

  // The honest verifier under test: a fresh throwaway ledger per probe (so the Wave-4 gate's
  // nonce-consume / OBSERVED side effects never leak across probes).
  function honestVerdict({ withDispatcher, artifact }) {
    const led = new ClaimLedger();
    led.assert({ id: 'IC', type: 'computational' });
    const gate = adjudicatedPromoteToVerified(led, 'IC', {
      artifact,
      dispatcher: withDispatcher ? dispatcher : undefined,
    });
    if (gate.verdict !== VERDICT.VERIFIED) return VERDICT.ABSTAIN;
    if (!useReexec) return VERDICT.VERIFIED; // PLANT: trust the gate without re-execution
    return reexecutionAgrees(artifact, computation) ? VERDICT.VERIFIED : VERDICT.ABSTAIN;
  }

  // The battery: every entry that the spine cannot REPRODUCE must come back ABSTAIN. Only the
  // genuine, re-executing artifact may come back VERIFIED. (Each probe mints its own claim/nonce.)
  const battery = [
    {
      label: 'genuine re-executing artifact',
      expected: VERDICT.VERIFIED,
      make: () => ({ withDispatcher: true, artifact: mintComputationalArtifact(dispatcher, 'IC', computation) }),
    },
    {
      label: 'no adjudicator/artifact present',
      expected: VERDICT.ABSTAIN,
      make: () => ({ withDispatcher: false, artifact: undefined }),
    },
    {
      label: 'malformed artifact',
      expected: VERDICT.ABSTAIN,
      make: () => ({ withDispatcher: true, artifact: { claim_id: 'IC' } }),
    },
    {
      label: 'fabricated stdout_hash (does NOT re-execute)',
      expected: VERDICT.ABSTAIN, // the discriminating probe — the Wave-4 gate alone would pass it
      make: () => ({ withDispatcher: true, artifact: mintComputationalArtifact(dispatcher, 'IC', computation, { fabricateHash: true }) }),
    },
    {
      label: 'cross-claim nonce (artifact minted for another claim)',
      expected: VERDICT.ABSTAIN,
      make: () => {
        const forOther = mintComputationalArtifact(dispatcher, 'OTHER', computation);
        return { withDispatcher: true, artifact: { ...forOther, claim_id: 'IC' } };
      },
    },
  ];

  for (const probe of battery) {
    const got = honestVerdict(probe.make());
    assertions.push(A(
      `inverted-completeness: "${probe.label}" => ${probe.expected}`,
      got === probe.expected,
      `expected ${probe.expected}, got ${got} (a green was emitted without a re-executing artifact)`,
    ));
  }

  return summarize('inverted-completeness', assertions);
}

// ===========================================================================
// (3) TRANSITIONS-INVARIANT — OBSERVED is reachable ONLY via an adjudicated, re-executing artifact.
// ===========================================================================

function auditTransitions(ledger, log) {
  const observedWithoutWarrant = [];
  for (const id of ledger.ids()) {
    if (ledger.rungOf(id) !== RUNG.OBSERVED) continue;
    const warranted = log.some(
      (t) => t.id === id && t.to === RUNG.OBSERVED && t.via === 'adjudicated' && t.reexecAgrees === true,
    );
    if (!warranted) observedWithoutWarrant.push(id);
  }
  const nonMonotone = log.filter((t) => rungRank(t.to) < rungRank(t.from));
  return { observedWithoutWarrant, nonMonotone };
}

/**
 * @param {{substrate?, scratchDir?, plant?: 'bypass-gate'}} [ctx]
 */
export async function canaryTransitionsInvariant(ctx = {}) {
  const { substrate, scratchDir } = await ensureCtx(ctx);
  const plant = ctx.plant;
  const assertions = [];

  const store = freshStore(substrate, scratchDir);
  const dispatcher = new AdjudicationDispatcher({ store, family: OUT_OF_MODEL_FAMILY });
  const ledger = new ClaimLedger();
  const log = [];

  // A genuine adjudicated transition, recorded with its re-execution warrant.
  ledger.assert({ id: 'A', type: 'computational' });
  {
    const from = ledger.rungOf('A');
    const artifact = mintComputationalArtifact(dispatcher, 'A', SAMPLE_SUM);
    adjudicatedPromoteToVerified(ledger, 'A', { artifact, dispatcher });
    log.push({ id: 'A', from, to: ledger.rungOf('A'), via: 'adjudicated', reexecAgrees: reexecutionAgrees(artifact, SAMPLE_SUM) });
  }

  // PLANT 'bypass-gate': a raw promote() straight to OBSERVED that NEVER went through the
  // adjudication gate (no artifact, no re-execution) — the laundering the invariant must catch.
  if (plant === 'bypass-gate') {
    ledger.assert({ id: 'B', type: 'computational' });
    const from = ledger.rungOf('B');
    ledger.promote('B', RUNG.OBSERVED, { family: 'same-family:model', reason: 'bypass', by: 'same-family' });
    log.push({ id: 'B', from, to: ledger.rungOf('B'), via: 'raw-promote', reexecAgrees: false });
  }

  const { observedWithoutWarrant, nonMonotone } = auditTransitions(ledger, log);

  assertions.push(A(
    'every OBSERVED rung is backed by an adjudicated, re-executing artifact transition',
    observedWithoutWarrant.length === 0,
    `OBSERVED reached without a re-executing adjudication for: ${observedWithoutWarrant.join(', ')}`,
  ));
  assertions.push(A(
    'no transition lowered a rung (transitions are monotone-up)',
    nonMonotone.length === 0,
    `non-monotone transition(s): ${JSON.stringify(nonMonotone)}`,
  ));
  assertions.push(A(
    'the genuine adjudicated transition reached OBSERVED and re-executes (not vacuous)',
    log.some((t) => t.via === 'adjudicated' && t.to === RUNG.OBSERVED && t.reexecAgrees === true),
    'no genuine adjudicated OBSERVED transition was recorded',
  ));

  return summarize('transitions-invariant', assertions);
}

// ===========================================================================
// (4) FLIP-LAW — sticky: no rung flip on re-assertion / self-authored stamp; single-use holds.
// ===========================================================================

/**
 * A NON-STICKY ledger double that VIOLATES the flip-law: a re-assertion carrying a higher
 * self-authored `rung` actually RAISES the rung (a same-family object self-promoting). Delegates
 * everything else to a real ClaimLedger. Used only by the planted-violation path.
 */
function flippingLedgerDouble() {
  const real = new ClaimLedger();
  return {
    assert(claim) {
      if (real.has(claim.id) && claim.rung && compareRungs(claim.rung, real.rungOf(claim.id)) > 0) {
        // VIOLATION: launder a same-family re-assertion into a rung-raise.
        return real.promote(claim.id, claim.rung, {
          family: 'same-family:self', reason: 'self-authored stamp', by: 'same-family',
        });
      }
      return real.assert(claim);
    },
    promote: (...a) => real.promote(...a),
    rungOf: (id) => real.rungOf(id),
    beliefOf: (id) => real.beliefOf(id),
    get: (id) => real.get(id),
    has: (id) => real.has(id),
    ids: () => real.ids(),
  };
}

/**
 * @param {{substrate?, scratchDir?, plant?: 'flip-on-reassert'}} [ctx]
 */
export async function canaryFlipLaw(ctx = {}) {
  const { substrate, scratchDir } = await ensureCtx(ctx);
  const plant = ctx.plant;
  const assertions = [];

  const ledger = plant === 'flip-on-reassert' ? flippingLedgerDouble() : new ClaimLedger();
  const store = freshStore(substrate, scratchDir);
  const dispatcher = new AdjudicationDispatcher({ store, family: OUT_OF_MODEL_FAMILY });

  // (a) STICKY: a fresh UNVERIFIED claim re-asserted with a self-authored OBSERVED/VERIFIED stamp
  //     must NOT flip. (This is the headline GWT plant: a same-family object asserting VERIFIED
  //     with a self-authored stamp — the flipping double raises it; the real ledger holds.)
  ledger.assert({ id: 'F', type: 'computational' });
  const beforeReassert = ledger.rungOf('F');
  ledger.assert({ id: 'F', type: 'computational', rung: RUNG.OBSERVED, meta: { self_stamp: 'VERIFIED by me' } });
  assertions.push(A(
    'a self-authored VERIFIED re-assertion does NOT flip the rung (sticky)',
    ledger.rungOf('F') === beforeReassert && beforeReassert === RUNG.UNVERIFIED,
    `rung flipped on re-assertion: ${beforeReassert} -> ${ledger.rungOf('F')}`,
  ));

  // Steps (b)-(d) drive the GENUINE promote path. A flip-plant has already corrupted the rung in
  // (a), so promote() may now throw (it refuses a non-upward target) — a throw is a tripped
  // assertion, never an uncaught canary crash.
  try {
    // (b) The ONLY rung-raise is a fresh adjudicated re-executed promote.
    const artifact = mintComputationalArtifact(dispatcher, 'F', SAMPLE_SUM);
    const reAgrees = reexecutionAgrees(artifact, SAMPLE_SUM);
    const promoted = adjudicatedPromoteToVerified(ledger, 'F', { artifact, dispatcher });
    assertions.push(A(
      'a fresh adjudicated, re-executing artifact raises the rung to OBSERVED',
      reAgrees && promoted.verdict === VERDICT.VERIFIED && ledger.rungOf('F') === RUNG.OBSERVED,
      `genuine adjudication did not reach OBSERVED (reAgrees=${reAgrees}, verdict=${promoted.verdict})`,
    ));

    // (c) SINGLE-USE: re-presenting the SAME (now spent) artifact ABSTAINs and does NOT re-flip.
    const rungAtObserved = ledger.rungOf('F');
    const replay = adjudicatedPromoteToVerified(ledger, 'F', { artifact, dispatcher });
    assertions.push(A(
      'a spent single-use artifact cannot re-flip the rung (replay ABSTAINs, rung held)',
      replay.verdict === VERDICT.ABSTAIN && ledger.rungOf('F') === rungAtObserved,
      `spent-artifact replay flipped/changed the rung: verdict=${replay.verdict}, rung=${ledger.rungOf('F')}`,
    ));

    // (d) STICKY both ways: a post-OBSERVED self-authored re-assertion still does not move the rung.
    ledger.assert({ id: 'F', type: 'computational', rung: RUNG.CLAIMED, meta: { self_stamp: 'downgrade me' } });
    assertions.push(A(
      'a post-OBSERVED self-authored re-assertion does not move the rung',
      ledger.rungOf('F') === RUNG.OBSERVED,
      `rung moved off OBSERVED on re-assertion: ${ledger.rungOf('F')}`,
    ));
  } catch (e) {
    assertions.push(A(
      'the genuine flip-law promote path runs without corruption',
      false,
      `the rung was already corrupted before the genuine promote path (flip-law violated): ${e.message}`,
    ));
  }

  return summarize('flip-law', assertions);
}

// ---------------------------------------------------------------------------
// The suite.
// ---------------------------------------------------------------------------

/** logical name -> canary runner. */
export const CANARIES = Object.freeze({
  'independence': canaryIndependence,
  'inverted-completeness': canaryInvertedCompleteness,
  'transitions-invariant': canaryTransitionsInvariant,
  'flip-law': canaryFlipLaw,
});

/**
 * Run all four core Honesty-Law canaries (clean — no plants). Returns
 * { ok, canaries:[{name, ok, assertions, failures}], failures:[ "canary: reason", ... ] };
 * `ok` is true iff EVERY canary is green. Every failure is prefixed with the canary name.
 *
 * @param {{substrate?, scratchDir?}} [ctx]
 */
export async function runHonestyCanarySuite(ctx = {}) {
  const { substrate, scratchDir } = await ensureCtx(ctx);
  const created = !ctx.scratchDir;
  const canaries = [];
  const failures = [];
  try {
    for (const name of CANARY_NAMES) {
      const result = await CANARIES[name]({ substrate, scratchDir });
      canaries.push(result);
      for (const f of result.failures) failures.push(`${name}: ${f}`);
    }
  } finally {
    if (created) {
      try { fs.rmSync(scratchDir, { recursive: true, force: true }); } catch { /* best-effort */ }
    }
  }
  return { ok: failures.length === 0, canaries, failures };
}

/** Map a suite result to a process exit code (0 = green, non-zero on any tripped canary). */
export function canarySuiteExitCode(result) {
  return result.ok ? 0 : 1;
}

// ---------------------------------------------------------------------------
// CLI: `node src/honesty-canaries.mjs` — exit 0 green / 1 on any tripped canary.
// ---------------------------------------------------------------------------
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = await runHonestyCanarySuite();
  if (result.ok) {
    const a = result.canaries.reduce((s, c) => s + c.assertions.length, 0);
    console.log(`OK: ${result.canaries.length} Honesty-Law canaries green (${a} pinned assertions).`);
    process.exit(0);
  } else {
    console.error('FAIL: Honesty-Law canary suite tripped:');
    for (const f of result.failures) console.error(`  - ${f}`);
    process.exit(1);
  }
}

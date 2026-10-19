// Wave 4 — F2 (+F3 atomic): Lean CERTIFIER -> OBSERVED, gated by SMT bounded faithfulness.
//
// LIFT A FORMALIZABLE PROOF TO **OBSERVED** — the strong rung above PLAUSIBILITY-CORROBORATED — minted by
// the LEAN KERNEL as an OUT-OF-MODEL subprocess and gated ATOMICALLY by the F3 bounded-faithfulness check.
// This is the honest strong positive arm for proof-bearing claims that ARE formalizable in core Lean and
// whose faithfulness is z3-decidable. Two gates, both required, NO unguarded window:
//
//   F2 — the Lean kernel.  Emit the `.lean`, run `lean` as an OUT-OF-MODEL subprocess: exit 0 ⇒ the
//        formalization typechecks (a candidate); non-zero ⇒ REJECTED. Artifact (frozen plan):
//          { statement_hash, lean_version, exit_code, olean_hash }.
//   F3 — bounded faithfulness (smt-faithfulness.mjs).  The formalization must AGREE with the informal
//        claim on a bounded, z3-decidable metamorphic/differential check (no disagreeing model + a
//        provenance-stamped non-Claude instance battery + non-vacuity), FAIL-CLOSED on z3 `unknown`.
//
// THE ATOMICITY GUARANTEE (DESCRIPTION-INC2 §v2 point 4 + Wave-4 done-when). OBSERVED is STRUCTURALLY
// UNREACHABLE unless BOTH the Lean exit-0 AND the bounded-faithfulness PASS: `liftToObserved` HARD-FAULTS
// (throws) on anything other than an OBSERVED adjudication result, so there is no code path that promotes
// to OBSERVED with only one gate. A Lean-valid proof of a statement that does NOT match the informal
// claim FAILS faithfulness and the OBSERVED lift hard-faults — no green proof of a wrong statement.
//
// THE CANARY (P9-F). The adjudication INDEPENDENTLY RE-RUNS lean from the stored `.lean` (recompute the
// exit code) and z3 from the stored `.smt2` (recompute the differential), and decides on the RE-RUN — it
// never trusts the producer-recorded `exit_code` / `result`. A FORGED Lean artifact (recorded exit 0, the
// re-run exits non-zero) or a forged SMT artifact is caught. An un-exercised canary WITHHOLDS the lift.
//
// THE ENVELOPE (HEADLINE, §v2.2). OBSERVED is reachable ONLY inside the z3-DECIDABLE envelope. A
// quantified / number-theoretic formalization ABSTAINS with the envelope reason code
// ("out of z3-decidable envelope → mathlib follow-on"), never a bare reject — the mathlib follow-on.
//
// ROUTER-AGNOSTIC BY DESIGN. This module imports ONLY the A1 ledger constants + the F3 faithfulness module
// — never verify-router — so there is no import cycle. `verify-router` imports THIS module and wires the
// adjudication + lift behind its async `routeProofCertifier` seam. The fast Foreman `node --test` gate
// drives the certifier with INJECTED async lean/z3 stubs (no tool); the real lean + z3 run only in the
// env-gated serial tool lane (RAMANUJAN_TOOL_TESTS=1). Pure node built-ins + the project's own modules.

import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { RUNG, compareRungs } from './claim-ledger.mjs';
import { runExecutable } from './phasef-probe.mjs';
import {
  certifyFaithfulness,
  adjudicateFaithfulness,
  makePrngBattery,
  FAITHFULNESS_STATUS,
  OUT_OF_ENVELOPE_REASON,
  SmtFaithfulnessError,
} from './smt-faithfulness.mjs';
// B4 sole-resolve: production callers arm Lean certifier spend only from frozen knobs
// (resolveRamanujanDepthKnobs / resolveRamanujanBand).isCertifierArmed — never process.env
// certifier toggles and never freelanced true mid-call.
import {
  isCertifierArmed,
  resolveRamanujanDepthKnobs,
  resolveRamanujanBand,
} from './triage-band.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** A 64-char lowercase hex (a SHA-256 digest). */
export const HEX64 = /^[0-9a-f]{64}$/;

/** The strong rung the Lean kernel + bounded faithfulness mint (the locked top arithmetic rung). */
export const OBSERVED_RUNG = RUNG.OBSERVED;

/** The EXACT field set of the re-executable Lean artifact (frozen plan, Wave 4). */
export const LEAN_ARTIFACT_FIELDS = Object.freeze(['statement_hash', 'lean_version', 'exit_code', 'olean_hash']);

/** The OBSERVED adjudication outcome alphabet. */
export const OBSERVED_STATUS = Object.freeze({
  OBSERVED: 'OBSERVED', // PASS: lean exit-0 AND faithfulness PASS AND the canary re-runs agree -> lift granted
  REJECTED: 'REJECTED', // the Lean kernel rejected the proof (exit non-zero) — an honest reject, no OBSERVED
  WITHHELD: 'WITHHELD', // fail-closed: z3 unknown, vacuous, out-of-envelope, or an un-exercised canary
  FLAG: 'FLAG', // a DETECTED defect: UNFAITHFUL (different statement), forged/replayed/cross-claim/malformed
});

/** Re-export the envelope reason code (the router's out-of-envelope advisory uses it). */
export { OUT_OF_ENVELOPE_REASON };

/** A typed error so a certifier wiring/usage bug (or an atomicity hard-fault) is distinguishable. */
export class LeanCertifierError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'LeanCertifierError';
    Object.assign(this, extra);
  }
}

/**
 * Production arm gate for Lean certifier spend (B4 SC4).
 * Refuses when frozen knobs are absent or knobs.certifier !== true.
 * Does not read process.env; does not freelance true from tier.
 *
 * @param {unknown} knobsOrBand  resolveRamanujanDepthKnobs / resolveRamanujanBand result
 * @returns {true}
 */
export function assertLeanCertifierArmed(knobsOrBand) {
  if (!isCertifierArmed(knobsOrBand)) {
    throw new LeanCertifierError(
      'lean certifier spend refused: frozen knobs.certifier must be true ' +
        '(depth lock FULL/SPIKE via resolveRamanujanDepthKnobs / resolveRamanujanBand)',
      { code: 'RAMANUJAN_CERTIFIER_DISARMED' },
    );
  }
  return true;
}

export { isCertifierArmed, resolveRamanujanDepthKnobs, resolveRamanujanBand };

// ---------------------------------------------------------------------------
// Hashing.
// ---------------------------------------------------------------------------

const sha256Hex = (text) => crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');

/** SHA-256 of the INFORMAL claim statement — binds the Lean artifact to the claim it certifies. */
export function statementHash(statement) {
  if (typeof statement !== 'string') {
    throw new LeanCertifierError('statementHash requires the claim statement as a string');
  }
  return sha256Hex(statement);
}

// ---------------------------------------------------------------------------
// The informal -> Lean TRANSLATION (NOT pre-written Lean) + the matching faithfulness query.
//
// A deterministic, in-repo (human-authored) translator for the supported decidable-arithmetic class:
// a ground Nat equation `a (+|*) b = c`. It EMITS the `.lean` from `claim.meta.equation` (the
// FORMALIZATION — so the wave exercises ≥1 informal->Lean translation, not a pre-written proof) AND emits
// the matching faithfulness query. THE TWO SIDES OF THAT QUERY COME FROM INDEPENDENT SOURCES, which is
// what makes the F3 gate LOAD-BEARING (non-tautological) and INDEPENDENT of the F2 lean gate for the
// translated class:
//   - the INFORMAL predicate is parsed from `claim.statement` (the CLAIM side) — what the claim SAYS;
//   - the FORMAL predicate is built from `claim.meta.equation` (the FORMALIZATION side, == the `.lean`) —
//     what the formalization ENCODES.
// Each side is the full ground equation rendered as a CONTINGENT predicate over a free Int `probe`:
//   `(and (= (op a b) c) (= probe c))` — true (at probe=c) iff the equation holds, false everywhere else.
// Faithful ⇔ the two predicates AGREE for every `probe` in the bounded box ⇔ the formalization encodes the
// SAME equation the claim states. A Lean-valid proof of a DIFFERENT (even also-true) equation than the
// statement — e.g. a `2+2=4` formalization stapled to a `1+1=2` claim — makes informal ≠ formal and is
// CAUGHT by the differential (the OBSERVED lift then hard-faults: no green proof of a wrong statement).
// (When the claim and its formalization genuinely agree the two predicates render identically — that is
// the CORRECT result of agreement, not a tautology: they are built from independent sources and diverge
// the moment those sources disagree.)
// ---------------------------------------------------------------------------

const SMT_OP = Object.freeze({ '+': '+', '*': '*' });

/**
 * Parse the INFORMAL claim statement (`a (+|*) b = c`, integers) into its asserted ground equation. This
 * is the CLAIM side, parsed INDEPENDENTLY of `claim.meta.equation` (the formalization side). Throws a
 * LeanCertifierError on anything outside the in-repo translator's supported decidable ground-equation form.
 */
export function parseGroundEquationStatement(statement) {
  if (typeof statement !== 'string') {
    throw new LeanCertifierError('parseGroundEquationStatement requires the claim statement as a string');
  }
  const m = /^\s*(-?\d+)\s*([+*])\s*(-?\d+)\s*=\s*(-?\d+)\s*$/.exec(statement);
  if (!m) {
    throw new LeanCertifierError(
      `claim.statement ${JSON.stringify(statement)} is not in the supported decidable ground-equation form ` +
        '"a (+|*) b = c" (out of the in-repo translator\'s class — mathlib follow-on)',
    );
  }
  return Object.freeze({ a: Number(m[1]), op: m[2], b: Number(m[3]), c: Number(m[4]) });
}

/** Render a ground equation as the CONTINGENT faithfulness predicate `(and (= (op a b) c) (= probe c))`. */
function equationPredicate(eq) {
  return `(and (= (${SMT_OP[eq.op]} ${eq.a} ${eq.b}) ${eq.c}) (= probe ${eq.c}))`;
}

/**
 * Translate a structured ground Nat-equation claim into a Lean proof + a faithfulness query + battery.
 * `claim.meta.equation = { a, op:'+'|'*', b, c }` (the FORMALIZATION) AND `claim.statement` (the informal
 * CLAIM, parsed independently). Returns { leanSource, faithfulness:{ query, battery }, translated:true }.
 * The Lean is GENERATED here from meta.equation (not supplied); `by decide` discharges the ground Nat goal.
 * The faithfulness query pairs an INFORMAL predicate (from claim.statement) with a FORMAL predicate (from
 * meta.equation) so F3 actually checks "does the formalization say what the claim says" — see the block
 * comment above. A statement outside the supported ground-equation form throws (LeanCertifierError).
 */
export function formalizeEquation(claim, { domain = { min: -64, max: 64 }, batteryCount = 16, seed = 1, provenance = 'prng' } = {}) {
  const eq = claim && claim.meta && claim.meta.equation; // the FORMALIZATION (becomes the `.lean`)
  if (!eq || !Number.isInteger(eq.a) || !Number.isInteger(eq.b) || !Number.isInteger(eq.c) || !SMT_OP[eq.op]) {
    throw new LeanCertifierError('formalizeEquation requires claim.meta.equation = { a:int, op:"+"|"*", b:int, c:int }');
  }
  const stmtEq = parseGroundEquationStatement(claim && claim.statement); // the CLAIM side (independent source)
  const leanSource = `example : (${eq.a} : Nat) ${eq.op} ${eq.b} = ${eq.c} := by decide\n`;
  const query = {
    vars: ['probe'],
    smt_logic: 'QF_LIA',
    domain,
    informal: equationPredicate(stmtEq), // what the CLAIM states (parsed from claim.statement)
    formal: equationPredicate(eq), // what the FORMALIZATION encodes (== the `.lean`, from meta.equation)
  };
  const battery = makePrngBattery(query, { count: batteryCount, seed, provenance });
  return Object.freeze({ leanSource, faithfulness: Object.freeze({ query, battery }), translated: true });
}

// ---------------------------------------------------------------------------
// The Lean artifact + the producer (certifyLean).
// ---------------------------------------------------------------------------

/** Mint the EXACT-field-set Lean artifact (frozen plan, Wave 4). */
export function makeLeanArtifact({ claim, leanVersion, exitCode, oleanHash }) {
  if (!claim || typeof claim.statement !== 'string') {
    throw new LeanCertifierError('makeLeanArtifact requires the claim (with a statement to bind)');
  }
  if (typeof leanVersion !== 'string' || leanVersion.length === 0) {
    throw new LeanCertifierError('makeLeanArtifact requires a lean_version string');
  }
  if (!Number.isInteger(exitCode)) {
    throw new LeanCertifierError('makeLeanArtifact requires an integer exit_code');
  }
  return Object.freeze({
    statement_hash: statementHash(claim.statement),
    lean_version: leanVersion,
    exit_code: exitCode,
    olean_hash: typeof oleanHash === 'string' && oleanHash.length > 0 ? oleanHash : null,
  });
}

/** Shape-check a Lean artifact. STRUCTURAL only (it does not re-invoke lean — that is the canary's job). */
export function validateLeanArtifact(artifact) {
  const failures = [];
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) {
    return { ok: false, failures: ['artifact is not an object'] };
  }
  for (const f of LEAN_ARTIFACT_FIELDS) if (!(f in artifact)) failures.push(`missing field: ${f}`);
  for (const k of Object.keys(artifact)) if (!LEAN_ARTIFACT_FIELDS.includes(k)) failures.push(`unexpected field: ${k}`);
  if (typeof artifact.statement_hash !== 'string' || !HEX64.test(artifact.statement_hash)) failures.push('statement_hash must be a 64-hex SHA-256');
  if (typeof artifact.lean_version !== 'string' || artifact.lean_version.length === 0) failures.push('lean_version must be a non-empty string');
  if (!Number.isInteger(artifact.exit_code)) failures.push('exit_code must be an integer');
  if (artifact.olean_hash !== null && (typeof artifact.olean_hash !== 'string' || !HEX64.test(artifact.olean_hash))) {
    failures.push('olean_hash must be a 64-hex SHA-256 or null');
  }
  return { ok: failures.length === 0, failures };
}

/**
 * Mint a Lean RECORD for `claim`: run the formalization through `certify(leanSource) -> { exitCode,
 * oleanHash }` (the out-of-model lean subprocess — injected in the fast tier, real lean in the tool
 * lane) and freeze { artifact, lean_source, statement, claim_id }. Does NOT decide acceptance (the canary
 * re-runs lean and decides). exit 0 ⇒ a CANDIDATE; non-zero ⇒ the proof will be REJECTED at adjudication.
 */
export async function certifyLean({ claim, leanSource, leanVersion }, { certify } = {}) {
  if (!claim || typeof claim.id !== 'string' || typeof claim.statement !== 'string') {
    throw new LeanCertifierError('certifyLean requires the claim (with id + statement) being certified');
  }
  if (typeof leanSource !== 'string' || leanSource.length === 0) {
    throw new LeanCertifierError('certifyLean requires a non-empty .lean source');
  }
  if (typeof certify !== 'function') {
    throw new LeanCertifierError('certifyLean requires an async certify(leanSource) -> { exitCode, oleanHash }');
  }
  const out = await certify(leanSource);
  const exitCode = out && Number.isInteger(out.exitCode) ? out.exitCode : 1;
  const artifact = makeLeanArtifact({ claim, leanVersion, exitCode, oleanHash: out && out.oleanHash });
  return Object.freeze({ artifact, lean_source: leanSource, statement: claim.statement, claim_id: claim.id });
}

// ---------------------------------------------------------------------------
// The Lean canary (independent re-run of lean from the stored .lean).
// ---------------------------------------------------------------------------

/** Lean adjudication statuses (the F2 half). */
const LEAN_STATUS = Object.freeze({ CANDIDATE: 'CANDIDATE', REJECTED: 'REJECTED', WITHHELD: 'WITHHELD', FLAG: 'FLAG' });

/**
 * Adjudicate the Lean half: re-run lean from the stored `.lean` via the INDEPENDENT `leanRerun` and
 * decide on the RE-RUN exit code (never the recorded one). Returns { status:LEAN_STATUS, reExit, reason }.
 *   - cross-claim (statement_hash != this claim's) -> FLAG
 *   - no leanRerun -> WITHHELD (un-exercised canary)
 *   - recorded exit_code != re-run exit_code -> FLAG (forged)
 *   - re-run exit non-zero -> REJECTED (honest reject)
 *   - re-run exit 0 -> CANDIDATE
 */
async function adjudicateLean({ record, claim, leanRerun }) {
  const v = validateLeanArtifact(record && record.artifact);
  if (!v.ok) return { status: LEAN_STATUS.FLAG, reason: `malformed Lean artifact: ${v.failures.join('; ')}` };
  if (record.claim_id !== claim.id || record.artifact.statement_hash !== statementHash(claim.statement)) {
    return { status: LEAN_STATUS.FLAG, reason: `Lean artifact is not bound to claim ${JSON.stringify(claim.id)} (cross-claim / replay — statement_hash mismatch)` };
  }
  if (typeof record.lean_source !== 'string' || record.lean_source.length === 0) {
    return { status: LEAN_STATUS.FLAG, reason: 'Lean record has no stored .lean source to independently re-run' };
  }
  if (typeof leanRerun !== 'function') {
    return { status: LEAN_STATUS.WITHHELD, reason: 'lean independence canary could NOT run (no lean re-run capability supplied) — OBSERVED withheld (an un-exercised canary is treated as stubbed)' };
  }
  const reExit = Number(await leanRerun(record.lean_source));
  const recorded = record.artifact.exit_code;
  if (Number.isInteger(recorded) && recorded !== reExit) {
    return { status: LEAN_STATUS.FLAG, reExit, reason: `FORGED Lean artifact: recorded exit_code ${recorded} but the INDEPENDENT lean re-run from the stored .lean exits ${reExit}` };
  }
  if (reExit !== 0) {
    return { status: LEAN_STATUS.REJECTED, reExit, reason: `the Lean kernel REJECTED the formalization (re-run exit ${reExit}) — the proof does not typecheck` };
  }
  return { status: LEAN_STATUS.CANDIDATE, reExit, reason: 'the Lean kernel accepted the formalization (re-run exit 0)' };
}

// ---------------------------------------------------------------------------
// The ATOMIC OBSERVED adjudication (F2 AND F3 — both required, no unguarded window).
// ---------------------------------------------------------------------------

const observedWithheld = (reason, extra = {}) => Object.freeze({ status: OBSERVED_STATUS.WITHHELD, ok: false, flagged: false, reason, ...extra });
const observedReject = (reason, extra = {}) => Object.freeze({ status: OBSERVED_STATUS.REJECTED, ok: false, flagged: false, reason, ...extra });
const observedFlag = (reason, extra = {}) => Object.freeze({ status: OBSERVED_STATUS.FLAG, ok: false, flagged: true, reason, ...extra });

/** The OBSERVED family-of-record: the two out-of-model certifiers that minted the lift (non-Claude). */
export const OBSERVED_FAMILY = 'lean-kernel+z3-bounded-faithfulness';

/**
 * Adjudicate the ATOMIC OBSERVED lift for `claim`. BOTH the Lean exit-0 AND the bounded-faithfulness PASS
 * are required; the canary INDEPENDENTLY re-runs lean (from the stored `.lean`) and z3 (from the stored
 * `.smt2`). Returns a frozen result whose `status` is one of OBSERVED_STATUS:
 *   OBSERVED — lean candidate + faithful + both canaries agree (the lift is granted).
 *   REJECTED — the Lean kernel rejected the proof (exit non-zero) — an honest reject.
 *   WITHHELD — fail-closed: z3 unknown, vacuous, out-of-envelope, or an un-exercised canary.
 *   FLAG     — a DETECTED defect: an UNFAITHFUL formalization (a different statement), or a forged /
 *              replayed / cross-claim / malformed lean or SMT artifact.
 * HARD-FAULTS (throws SmtFaithfulnessError) if the faithfulness battery is Claude-sourced or undersized.
 *
 * @param {{ claim:object, leanRecord:object, smtRecord:object, leanRerun?:Function, z3Rerun?:Function, pinnedDefaultCount:number }} o
 */
export async function adjudicateObserved({ claim, leanRecord, smtRecord, leanRerun, z3Rerun, pinnedDefaultCount } = {}) {
  if (!claim || typeof claim.id !== 'string' || typeof claim.statement !== 'string') {
    throw new LeanCertifierError('adjudicateObserved requires the claim (with id + statement) being certified');
  }
  if (!leanRecord || typeof leanRecord !== 'object') {
    return observedWithheld('no Lean certificate supplied — the formalization was never run (deferred arm)');
  }
  if (!smtRecord || typeof smtRecord !== 'object') {
    return observedWithheld('no SMT faithfulness certificate supplied — OBSERVED requires the bounded-faithfulness gate (atomic F2+F3)');
  }

  // (F2) The Lean kernel half — re-run from the stored `.lean`.
  const lean = await adjudicateLean({ record: leanRecord, claim, leanRerun });
  if (lean.status === LEAN_STATUS.FLAG) return observedFlag(`lean: ${lean.reason}`);
  if (lean.status === LEAN_STATUS.WITHHELD) return observedWithheld(lean.reason);
  if (lean.status === LEAN_STATUS.REJECTED) return observedReject(lean.reason);
  // lean.status === CANDIDATE (exit 0). Proceed to the ATOMIC faithfulness gate.

  // (F3) The bounded-faithfulness half — re-run z3 from the stored `.smt2`. (May throw on a Claude /
  // undersized battery — the §v2.2 artifact-keyed hard-fault propagates as a structural integrity fault.)
  const faith = await adjudicateFaithfulness({ record: smtRecord, claim, z3Rerun, pinnedDefaultCount });
  if (faith.status === FAITHFULNESS_STATUS.FLAG) return observedFlag(`faithfulness: ${faith.reason}`);
  if (faith.status === FAITHFULNESS_STATUS.UNFAITHFUL) {
    // A Lean-valid proof of a statement that does NOT match the informal claim — OBSERVED hard-faults.
    return observedFlag(`faithfulness FAILED: ${faith.reason} — the OBSERVED lift hard-faults (no green proof of a wrong statement)`);
  }
  if (faith.status === FAITHFULNESS_STATUS.WITHHELD) {
    return observedWithheld(`faithfulness withheld: ${faith.reason}`, { outOfEnvelope: Boolean(faith.outOfEnvelope) });
  }

  // BOTH gates passed atomically: lean exit-0 AND bounded faithfulness, both canary-re-run.
  return Object.freeze({
    status: OBSERVED_STATUS.OBSERVED,
    ok: true,
    flagged: false,
    family: OBSERVED_FAMILY,
    reason:
      'OBSERVED: the Lean kernel accepted the formalization (re-run exit 0) AND the bounded SMT faithfulness check passed ' +
      '(re-run z3 from the stored .smt2) — a re-executable lean+z3 artifact, canary-verified',
    artifact_ref: Object.freeze({
      statement_hash: leanRecord.artifact.statement_hash,
      lean_version: leanRecord.artifact.lean_version,
      lean_exit_code: leanRecord.artifact.exit_code,
      olean_hash: leanRecord.artifact.olean_hash,
      smt2_hash: smtRecord.artifact.smt2_hash,
      z3_version: smtRecord.artifact.z3_version,
      differential_result: smtRecord.artifact.result,
      battery_provenance: smtRecord.artifact.battery_provenance,
      battery_count: smtRecord.artifact.battery_count,
      bounded_domain: smtRecord.artifact.bounded_domain,
    }),
    faithfulness: faith,
    lean: { exit_code: lean.reExit },
  });
}

// ---------------------------------------------------------------------------
// The lift — the SOLE promote() to OBSERVED (structurally unreachable without BOTH gates).
// ---------------------------------------------------------------------------

/**
 * Lift `claim` to OBSERVED, bound to an OBSERVED adjudication result. HARD-FAULTS (throws
 * LeanCertifierError) on anything other than an OBSERVED result — so the OBSERVED rung is STRUCTURALLY
 * UNREACHABLE unless BOTH the Lean exit-0 AND the bounded-faithfulness passed (the atomicity guarantee).
 * promote() is strictly-upward only; if the claim already sits at/above OBSERVED the lift is a HOLD
 * (idempotent — never lowers a stronger rung). Returns the snapshot.
 */
export function liftToObserved(ledger, claim, result) {
  if (!ledger || typeof ledger.promote !== 'function' || typeof ledger.rungOf !== 'function') {
    throw new LeanCertifierError('liftToObserved requires an A1 ClaimLedger');
  }
  if (!result || result.status !== OBSERVED_STATUS.OBSERVED) {
    throw new LeanCertifierError(
      'liftToObserved HARD-FAULT: OBSERVED is structurally unreachable without an OBSERVED adjudication result ' +
        '(BOTH the Lean exit-0 AND the bounded-faithfulness must pass)',
      { status: result && result.status },
    );
  }
  const id = claim.id;
  if (compareRungs(OBSERVED_RUNG, ledger.rungOf(id)) <= 0) {
    return ledger.get(id); // already at/above OBSERVED — HOLD (sticky), never lower it.
  }
  return ledger.promote(id, OBSERVED_RUNG, {
    family: result.family || OBSERVED_FAMILY,
    reason: result.reason,
    by: 'lean-certifier',
  });
}

// ---------------------------------------------------------------------------
// Convenience: run the full F2+F3 certification end to end (producer mints + atomic adjudication).
// ---------------------------------------------------------------------------

/**
 * Mint BOTH certificates (lean + smt) and adjudicate the atomic OBSERVED lift in one call. The producer
 * `certify` (lean) + `solve` (z3) mint the records; the canary `leanRerun` + `z3Rerun` independently
 * re-run them. Returns { leanRecord, smtRecord, result } (result = the OBSERVED adjudication).
 */
export async function certifyObserved({ claim, leanSource, leanVersion, faithfulness, z3Version, pinnedDefaultCount }, { certify, solve, leanRerun, z3Rerun } = {}) {
  const leanRecord = await certifyLean({ claim, leanSource, leanVersion }, { certify });
  const smtRecord = await certifyFaithfulness(
    { claim, query: faithfulness.query, battery: faithfulness.battery, z3Version, pinnedDefaultCount },
    { solve },
  );
  const result = await adjudicateObserved({ claim, leanRecord, smtRecord, leanRerun, z3Rerun, pinnedDefaultCount });
  return Object.freeze({ leanRecord, smtRecord, result });
}

// ---------------------------------------------------------------------------
// The tool-lane lean subprocess (real lean by manifest absolute path — NEVER invoked at import time).
// ---------------------------------------------------------------------------

/**
 * Build an async `certify(leanSource) -> { exitCode, oleanHash }` bound to the real lean at `leanPath`.
 * Writes the `.lean` to a hermetic temp dir and runs `lean -o <olean> <file>` by absolute path (no
 * shell); exit 0 ⇒ typechecks. `olean_hash` is the SHA-256 of the produced `.olean` (provenance; null if
 * none). Tool-lane only — the fast tier injects a stub `certify`.
 */
export function createLeanCertify(leanPath, { exec = runExecutable, timeoutMs = 120000 } = {}) {
  if (typeof leanPath !== 'string' || leanPath.length === 0) {
    throw new LeanCertifierError('createLeanCertify requires the lean absolute path');
  }
  return async function certify(leanSource) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-f2-'));
    const file = path.join(dir, 'proof.lean');
    const olean = path.join(dir, 'proof.olean');
    try {
      fs.writeFileSync(file, leanSource, 'utf8');
      const obs = exec(leanPath, ['-o', olean, file], { timeoutMs, cwd: dir });
      const exitCode = obs.timedOut ? 124 : obs.exitCode;
      let oleanHash = null;
      if (exitCode === 0) {
        try { oleanHash = sha256Hex(fs.readFileSync(olean)); } catch { /* no olean produced */ }
      }
      return { exitCode, oleanHash, stdout: obs.stdout, stderr: obs.stderr };
    } finally {
      try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* best-effort */ }
    }
  };
}

/** Build an async `leanRerun(leanSource) -> exitCode` (the canary's independent lean re-run). */
export function createLeanRerun(leanPath, opts = {}) {
  const certify = createLeanCertify(leanPath, opts);
  return async function leanRerun(leanSource) {
    const out = await certify(leanSource);
    return out.exitCode;
  };
}

// Re-export the F3 hard-fault error so router-side callers can distinguish an integrity fault.
export { SmtFaithfulnessError };

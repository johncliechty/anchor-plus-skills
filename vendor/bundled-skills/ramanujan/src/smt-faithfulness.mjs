// Wave 4 — F3: SMT BOUNDED-FAITHFULNESS (z3, the second half of the ATOMIC OBSERVED lift).
//
// THE HONEST BOUND (DESCRIPTION-INC2 §v2 point 2 / HEADLINE ENVELOPE). A Lean kernel exit-0 proves the
// formalization is a THEOREM — it does NOT prove the formalization SAYS WHAT THE INFORMAL CLAIM SAYS. A
// green Lean proof of a DIFFERENT (also-true) statement would otherwise launder a wrong statement to
// OBSERVED. This module is the faithfulness gate that closes that hole, HONESTLY BOUNDED to what z3 can
// actually decide:
//
//   BOUNDED METAMORPHIC / DIFFERENTIAL FAITHFULNESS over z3-DECIDABLE theories (LIA / LRA / BV):
//     (a) DIFFERENTIAL no-disagreeing-model search — z3 finds NO assignment within a BOUNDED integer
//         domain where the informal claim's predicate and the formalization's predicate DISAGREE
//         (the differential SMT2 asserts `(xor informal formal)`; z3 `unsat` ⇒ they agree everywhere
//         in the box). This is a NAMED BOUNDED GUARANTEE, *not* a general "claim ⇔ formalization"
//         equivalence proof.
//     (b) METAMORPHIC concrete-instance battery — a provenance-stamped, NON-CLAUDE battery of concrete
//         instances (PRNG / tool / cross-family / human) on which the two predicates must AGREE. The
//         battery's concrete witnesses are necessary-not-sufficient (the differential subsumes them);
//         their role is provenance + non-vacuity.
//     (c) NON-VACUITY — the informal predicate must be CONTINGENT over the bounded domain (z3 finds an
//         assignment making it true AND one making it false). A constant predicate would let ANY
//         same-constant formalization "match" — a vacuous, non-discriminating check.
//
//   FAIL-CLOSED. z3 `unknown` / timeout on ANY of these queries ⇒ faithfulness is WITHHELD ⇒ the
//   OBSERVED lift is withheld. A formalization OUTSIDE the z3-decidable envelope (a quantified /
//   number-theoretic logic) ABSTAINS with an envelope-explaining REASON CODE ("out of z3-decidable
//   envelope → mathlib follow-on"), never a bare reject.
//
// THE ARTIFACT (P9-F, extended by §v2.2). The re-executable SMT artifact is
//   { smt2_hash, z3_version, result, battery_provenance, battery_count, bounded_domain }
// — the battery PROVENANCE + COUNT + DOMAIN are bound INTO the artifact the build keys on, so the
// non-Claude-battery requirement is a STRUCTURAL hard-fault, not prose: `validateBatteryIntegrity`
// THROWS when `battery_provenance === 'claude'` or `battery_count < the pinned default`. The canary
// (Wave-4 `adjudicateFaithfulness`) RE-RUNS the differential from the stored `.smt2` via an INDEPENDENT
// z3 and recomputes the verdict — it never trusts the producer-recorded `result` field (a forged
// `result:'unsat'` whose independent re-run is `sat` is caught).
//
// THE BUILD-GATE ISOLATION CONTRACT (§v2.1/§v2.2): this module starts NOTHING and touches NO tool at
// import time — every z3 spawn happens only inside a `solve` the caller invokes. The fast Foreman
// `node --test test/` gate drives the faithfulness logic with an INJECTED async `solve(smt2)` stub (no
// z3); the real z3 runs only in the env-gated serial tool lane (RAMANUJAN_TOOL_TESTS=1).
//
// Pure node built-ins (crypto, fs, os, path) + the F0 runExecutable it reuses for the tool-lane solve.

import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { runExecutable } from './phasef-probe.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** A 64-char lowercase hex (a SHA-256 digest). */
export const HEX64 = /^[0-9a-f]{64}$/;

/** The EXACT field set of the re-executable SMT faithfulness artifact (frozen plan §v2.2). */
export const SMT_ARTIFACT_FIELDS = Object.freeze([
  'smt2_hash',
  'z3_version',
  'result',
  'battery_provenance',
  'battery_count',
  'bounded_domain',
]);

/** The allowed NON-CLAUDE battery provenances (§v2.2: source ∈ {tool,cross-family,human,prng} ≠ claude). */
export const BATTERY_PROVENANCE_SOURCES = Object.freeze(new Set(['tool', 'cross-family', 'human', 'prng']));

/** The z3 check-sat result alphabet. */
export const Z3_RESULT = Object.freeze({ SAT: 'sat', UNSAT: 'unsat', UNKNOWN: 'unknown' });

/** The faithfulness verdict alphabet (consumed by the Wave-4 atomic OBSERVED lift). */
export const FAITHFULNESS_VERDICT = Object.freeze({
  FAITHFUL: 'FAITHFUL', // bounded guarantee holds: no disagreeing model, battery agrees, non-vacuous
  UNFAITHFUL: 'UNFAITHFUL', // a disagreeing model / instance exists — a DIFFERENT statement
  WITHHELD: 'WITHHELD', // fail-closed: z3 unknown/timeout, vacuous, or out of the z3-decidable envelope
});

/** Faithfulness adjudication statuses (verdicts + a DETECTED-defect FLAG). */
export const FAITHFULNESS_STATUS = Object.freeze({
  FAITHFUL: 'FAITHFUL',
  UNFAITHFUL: 'UNFAITHFUL',
  WITHHELD: 'WITHHELD',
  FLAG: 'FLAG', // forged (recorded result disagrees with the independent re-run) / malformed / cross-claim
});

/** The z3-DECIDABLE (quantifier-free arithmetic / BV) logics this increment's OBSERVED arm permits. */
export const DECIDABLE_LOGICS = Object.freeze(new Set(['QF_LIA', 'QF_LRA', 'QF_BV', 'QF_IDL', 'QF_RDL']));

/** The envelope-explaining reason code for an out-of-z3-decidable (quantified) formalization (§v2.2). */
export const OUT_OF_ENVELOPE_REASON = 'out of z3-decidable envelope → mathlib follow-on';

/** SMT2 kind markers (embedded as a comment so a tool-lane stub / the canary can tell the queries apart). */
export const FAITHFULNESS_KIND = Object.freeze({
  DIFFERENTIAL: 'differential',
  INSTANCE: 'instance',
  VACUITY_TRUE: 'vacuity-true',
  VACUITY_FALSE: 'vacuity-false',
});

/** A typed error so a faithfulness wiring/usage bug (or an integrity hard-fault) is distinguishable. */
export class SmtFaithfulnessError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'SmtFaithfulnessError';
    Object.assign(this, extra);
  }
}

// ---------------------------------------------------------------------------
// Hashing.
// ---------------------------------------------------------------------------

const sha256Hex = (text) => crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');

/** SHA-256 of the SMT2 text VERBATIM (the canary re-runs z3 from the stored `.smt2`). */
export function smt2Hash(smt2) {
  if (typeof smt2 !== 'string' || smt2.length === 0) {
    throw new SmtFaithfulnessError('smt2Hash requires a non-empty SMT2 string');
  }
  return sha256Hex(smt2);
}

// ---------------------------------------------------------------------------
// The faithfulness query + the z3-decidable envelope.
//
// A query pairs the INFORMAL claim's predicate with the FORMALIZATION's predicate (both SMT-LIB boolean
// expressions over a shared set of Int variables), a bounded integer domain, and the SMT logic. Faithful
// ⇔ the two predicates AGREE for every assignment in the box. Keep the predicates side strings (so they
// go straight to z3) — this module never trusts a model-evaluated truth value.
// ---------------------------------------------------------------------------

function assertQuery(query) {
  if (!query || typeof query !== 'object') {
    throw new SmtFaithfulnessError('faithfulness requires a query object { vars, informal, formal, domain, smt_logic }');
  }
  if (!Array.isArray(query.vars) || query.vars.length === 0 || !query.vars.every((v) => typeof v === 'string' && v.length > 0)) {
    throw new SmtFaithfulnessError('query.vars must be a non-empty array of variable-name strings');
  }
  if (typeof query.informal !== 'string' || query.informal.length === 0) {
    throw new SmtFaithfulnessError('query.informal must be a non-empty SMT-LIB boolean predicate');
  }
  if (typeof query.formal !== 'string' || query.formal.length === 0) {
    throw new SmtFaithfulnessError('query.formal must be a non-empty SMT-LIB boolean predicate');
  }
  const d = query.domain;
  if (!d || !Number.isInteger(d.min) || !Number.isInteger(d.max) || d.min > d.max) {
    throw new SmtFaithfulnessError('query.domain must be { min:int, max:int } with min <= max (the bounded box)');
  }
  return query;
}

/**
 * Whether `query` is inside this increment's z3-DECIDABLE envelope: a quantifier-free decidable-arithmetic
 * / BV logic AND no quantifier token (`forall` / `exists`) smuggled into either predicate. Anything else
 * is OUT OF ENVELOPE (a quantified number-theory/analysis formalization → the mathlib follow-on).
 */
export function isDecidableEnvelope(query) {
  if (!query || typeof query !== 'object') return false;
  const logic = query.smt_logic || 'QF_LIA';
  if (!DECIDABLE_LOGICS.has(logic)) return false;
  const quantified = /\b(forall|exists)\b/;
  if (quantified.test(query.informal || '') || quantified.test(query.formal || '')) return false;
  return true;
}

// ---------------------------------------------------------------------------
// SMT2 builders (the .smt2 the canary re-runs). All bounded, all QF — decidable by construction.
// ---------------------------------------------------------------------------

function smtHeader(query, kind) {
  return [`(set-logic ${query.smt_logic || 'QF_LIA'})`, `; ramanujan-faithfulness-kind: ${kind}`];
}

function declareVars(query, lines) {
  for (const v of query.vars) lines.push(`(declare-const ${v} Int)`);
}

function boundVars(query, lines) {
  for (const v of query.vars) {
    lines.push(`(assert (>= ${v} ${query.domain.min}))`);
    lines.push(`(assert (<= ${v} ${query.domain.max}))`);
  }
}

/**
 * The DIFFERENTIAL no-disagreeing-model query: declare + bound the vars, assert the two predicates
 * DISAGREE `(xor informal formal)`, check-sat. z3 `unsat` ⇒ no disagreement in the box (faithful);
 * `sat` ⇒ a disagreeing model exists (UNFAITHFUL); `unknown` ⇒ fail-closed (WITHHELD).
 */
export function buildDifferentialSmt2(query) {
  assertQuery(query);
  const lines = smtHeader(query, FAITHFULNESS_KIND.DIFFERENTIAL);
  declareVars(query, lines);
  boundVars(query, lines);
  lines.push(`(assert (xor ${query.informal} ${query.formal}))`);
  lines.push('(check-sat)');
  return `${lines.join('\n')}\n`;
}

/**
 * A concrete-INSTANCE query: pin every var to the instance's value and assert the predicates DISAGREE.
 * z3 `unsat` ⇒ they AGREE on this concrete instance; `sat` ⇒ they DISAGREE on it.
 */
export function buildInstanceSmt2(query, instance) {
  assertQuery(query);
  if (!instance || typeof instance !== 'object') {
    throw new SmtFaithfulnessError('buildInstanceSmt2 requires an instance assignment { var: value }');
  }
  const lines = smtHeader(query, FAITHFULNESS_KIND.INSTANCE);
  declareVars(query, lines);
  for (const v of query.vars) {
    if (!Number.isInteger(instance[v])) {
      throw new SmtFaithfulnessError(`instance is missing an integer value for variable ${JSON.stringify(v)}`);
    }
    lines.push(`(assert (= ${v} ${instance[v]}))`);
  }
  lines.push(`(assert (xor ${query.informal} ${query.formal}))`);
  lines.push('(check-sat)');
  return `${lines.join('\n')}\n`;
}

/**
 * A NON-VACUITY probe: declare + bound the vars, assert the informal predicate (polarity true) or its
 * negation (polarity false), check-sat. The informal predicate is CONTINGENT over the box ⇔ BOTH probes
 * are `sat` (it can be made true AND made false). A constant predicate fails one probe ⇒ vacuous.
 */
export function buildVacuitySmt2(query, polarityTrue) {
  assertQuery(query);
  const kind = polarityTrue ? FAITHFULNESS_KIND.VACUITY_TRUE : FAITHFULNESS_KIND.VACUITY_FALSE;
  const lines = smtHeader(query, kind);
  declareVars(query, lines);
  boundVars(query, lines);
  lines.push(`(assert ${polarityTrue ? query.informal : `(not ${query.informal})`})`);
  lines.push('(check-sat)');
  return `${lines.join('\n')}\n`;
}

// ---------------------------------------------------------------------------
// The concrete-instance battery (PRNG-sourced — NEVER Claude-enumerated).
// ---------------------------------------------------------------------------

/** A tiny deterministic LCG (no Math.random) so the PRNG battery is reproducible + non-Claude-sourced. */
function lcg(seed) {
  let s = (seed >>> 0) || 1;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s;
  };
}

/**
 * Build a PROVENANCE-STAMPED concrete-instance battery: `count` assignments of every query var to a value
 * drawn (deterministic LCG, fixed seed) from the bounded domain. Provenance defaults to 'prng' (an
 * out-of-model PRNG — NEVER Claude). Returns { provenance, count, instances:[{var:value,...}], seed }.
 */
export function makePrngBattery(query, { count = 16, seed = 1, provenance = 'prng' } = {}) {
  assertQuery(query);
  if (!Number.isInteger(count) || count <= 0) {
    throw new SmtFaithfulnessError('makePrngBattery requires a positive integer count');
  }
  const span = query.domain.max - query.domain.min + 1;
  const rnd = lcg(seed);
  const instances = [];
  for (let i = 0; i < count; i += 1) {
    const inst = {};
    for (const v of query.vars) inst[v] = query.domain.min + (rnd() % span);
    instances.push(Object.freeze(inst));
  }
  return Object.freeze({ provenance, count, instances: Object.freeze(instances), seed });
}

// ---------------------------------------------------------------------------
// Battery integrity — the §v2.2 artifact-keyed HARD-FAULT (cannot be stubbed away).
// ---------------------------------------------------------------------------

/**
 * Validate the battery's provenance + size. HARD-FAULTS (throws SmtFaithfulnessError) if the battery is
 * Claude-sourced (the Honesty Law at the faithfulness boundary) or smaller than the pinned default
 * (`tools.manifest.json` faithfulness_instance_battery.default_count). Binding the non-Claude-battery
 * requirement into a throw the build keys on — not prose. Returns the normalized { provenance, count }.
 */
export function validateBatteryIntegrity(battery, pinnedDefaultCount) {
  if (!battery || typeof battery !== 'object') {
    throw new SmtFaithfulnessError('faithfulness requires a concrete-instance battery { provenance, count, instances }');
  }
  const provenance = typeof battery.provenance === 'string' ? battery.provenance.trim().toLowerCase() : battery.provenance;
  if (provenance === 'claude') {
    throw new SmtFaithfulnessError(
      'battery provenance is `claude` — the metamorphic concrete-instance battery MUST be NON-Claude-sourced ' +
        '(Honesty Law / §v2.2 artifact-keyed hard-fault)',
      { provenance: battery.provenance },
    );
  }
  if (!BATTERY_PROVENANCE_SOURCES.has(provenance)) {
    throw new SmtFaithfulnessError(
      `battery provenance must be one of ${[...BATTERY_PROVENANCE_SOURCES].join(', ')} (got ${JSON.stringify(battery.provenance)})`,
      { provenance: battery.provenance },
    );
  }
  if (!Array.isArray(battery.instances) || battery.instances.length === 0) {
    throw new SmtFaithfulnessError('battery has no concrete instances');
  }
  const count = Number.isInteger(battery.count) ? battery.count : battery.instances.length;
  if (count !== battery.instances.length) {
    throw new SmtFaithfulnessError(`battery_count ${count} does not match the number of instances ${battery.instances.length}`);
  }
  if (!Number.isInteger(pinnedDefaultCount) || pinnedDefaultCount <= 0) {
    throw new SmtFaithfulnessError('validateBatteryIntegrity requires the pinned default count (tools.manifest.json)');
  }
  if (!(count >= pinnedDefaultCount)) {
    throw new SmtFaithfulnessError(
      `battery_count ${count} < pinned default ${pinnedDefaultCount} — the bounded-faithfulness battery is too small ` +
        '(§v2.2 artifact-keyed hard-fault)',
      { count, pinnedDefaultCount },
    );
  }
  return { provenance, count };
}

// ---------------------------------------------------------------------------
// The artifact.
// ---------------------------------------------------------------------------

/** Mint the EXACT-field-set SMT faithfulness artifact (frozen plan §v2.2). */
export function makeSmtArtifact({ smt2, z3Version, result, batteryProvenance, batteryCount, boundedDomain }) {
  if (typeof z3Version !== 'string' || z3Version.length === 0) {
    throw new SmtFaithfulnessError('makeSmtArtifact requires a z3_version string');
  }
  return Object.freeze({
    smt2_hash: smt2Hash(smt2),
    z3_version: z3Version,
    result: result === null || result === undefined ? null : result,
    battery_provenance: batteryProvenance,
    battery_count: batteryCount,
    bounded_domain: Object.freeze({ min: boundedDomain.min, max: boundedDomain.max }),
  });
}

/** Shape-check an SMT artifact. STRUCTURAL only (it does not re-invoke z3 — that is the canary's job). */
export function validateSmtArtifact(artifact) {
  const failures = [];
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) {
    return { ok: false, failures: ['artifact is not an object'] };
  }
  for (const f of SMT_ARTIFACT_FIELDS) if (!(f in artifact)) failures.push(`missing field: ${f}`);
  for (const k of Object.keys(artifact)) if (!SMT_ARTIFACT_FIELDS.includes(k)) failures.push(`unexpected field: ${k}`);
  if (typeof artifact.smt2_hash !== 'string' || !HEX64.test(artifact.smt2_hash)) failures.push('smt2_hash must be a 64-hex SHA-256');
  if (typeof artifact.z3_version !== 'string' || artifact.z3_version.length === 0) failures.push('z3_version must be a non-empty string');
  if (artifact.result !== null && !Object.values(Z3_RESULT).includes(artifact.result)) {
    failures.push('result must be one of sat|unsat|unknown|null');
  }
  if (typeof artifact.battery_provenance !== 'string' || artifact.battery_provenance.toLowerCase() === 'claude') {
    failures.push('battery_provenance must be a non-Claude string');
  }
  if (!Number.isInteger(artifact.battery_count) || artifact.battery_count <= 0) failures.push('battery_count must be a positive integer');
  const d = artifact.bounded_domain;
  if (!d || !Number.isInteger(d.min) || !Number.isInteger(d.max)) failures.push('bounded_domain must be { min:int, max:int }');
  return { ok: failures.length === 0, failures };
}

// ---------------------------------------------------------------------------
// The faithfulness computation (the shared full check — driven by an injected z3 `solve`).
// ---------------------------------------------------------------------------

function normalizeSolveResult(out) {
  // Accept a bare result string or { result } object; default unknown (fail-closed) on anything else.
  const r = typeof out === 'string' ? out : out && out.result;
  if (r === Z3_RESULT.SAT || r === Z3_RESULT.UNSAT || r === Z3_RESULT.UNKNOWN) return r;
  return Z3_RESULT.UNKNOWN;
}

/**
 * Run the FULL bounded faithfulness check for `query` over `battery` using an injected async
 * `solve(smt2) -> 'sat'|'unsat'|'unknown' | { result }`. Returns
 *   { verdict:FAITHFULNESS_VERDICT, reason, differentialResult, vacuous?, disagreements? }
 *
 * Order (each step fail-CLOSED on z3 `unknown`):
 *   0. out of envelope          -> WITHHELD (the envelope reason code)
 *   1. differential sat         -> UNFAITHFUL (a disagreeing model exists in the box)
 *   2. battery instance disagree-> UNFAITHFUL (a concrete witness disagrees)
 *   3. informal not contingent  -> WITHHELD (vacuous — no discriminating power)
 *   ELSE                        -> FAITHFUL (the NAMED bounded guarantee holds)
 */
export async function computeFaithfulness(query, battery, solve) {
  assertQuery(query);
  if (typeof solve !== 'function') {
    throw new SmtFaithfulnessError('computeFaithfulness requires an async solve(smt2) function');
  }
  if (!isDecidableEnvelope(query)) {
    return Object.freeze({ verdict: FAITHFULNESS_VERDICT.WITHHELD, reason: OUT_OF_ENVELOPE_REASON, outOfEnvelope: true, differentialResult: null });
  }

  // (1) DIFFERENTIAL no-disagreeing-model search.
  const diff = normalizeSolveResult(await solve(buildDifferentialSmt2(query)));
  if (diff === Z3_RESULT.UNKNOWN) {
    return Object.freeze({
      verdict: FAITHFULNESS_VERDICT.WITHHELD,
      reason: 'z3 returned `unknown`/timeout on the bounded differential faithfulness query — OBSERVED withheld (fail-closed)',
      differentialResult: Z3_RESULT.UNKNOWN,
    });
  }
  if (diff === Z3_RESULT.SAT) {
    return Object.freeze({
      verdict: FAITHFULNESS_VERDICT.UNFAITHFUL,
      reason:
        'a DISAGREEING model exists within the bounded domain — the Lean formalization is NOT faithful to the informal claim ' +
        '(no green proof of a wrong statement)',
      differentialResult: Z3_RESULT.SAT,
    });
  }

  // (2) METAMORPHIC concrete-instance battery agreement.
  const disagreements = [];
  for (const inst of battery.instances) {
    const r = normalizeSolveResult(await solve(buildInstanceSmt2(query, inst)));
    if (r === Z3_RESULT.UNKNOWN) {
      return Object.freeze({
        verdict: FAITHFULNESS_VERDICT.WITHHELD,
        reason: 'z3 returned `unknown` on a battery instance — OBSERVED withheld (fail-closed)',
        differentialResult: Z3_RESULT.UNSAT,
      });
    }
    if (r === Z3_RESULT.SAT) disagreements.push(inst); // sat on the instance query ⇒ they disagree on it
  }
  if (disagreements.length > 0) {
    return Object.freeze({
      verdict: FAITHFULNESS_VERDICT.UNFAITHFUL,
      reason: `${disagreements.length} concrete battery instance(s) DISAGREE — the formalization is NOT faithful`,
      differentialResult: Z3_RESULT.UNSAT,
      disagreements: Object.freeze(disagreements),
    });
  }

  // (3) NON-VACUITY: the informal predicate must be CONTINGENT (true-able AND false-able) in the box.
  const canBeTrue = normalizeSolveResult(await solve(buildVacuitySmt2(query, true)));
  const canBeFalse = normalizeSolveResult(await solve(buildVacuitySmt2(query, false)));
  if (canBeTrue === Z3_RESULT.UNKNOWN || canBeFalse === Z3_RESULT.UNKNOWN) {
    return Object.freeze({
      verdict: FAITHFULNESS_VERDICT.WITHHELD,
      reason: 'z3 returned `unknown` on the non-vacuity probe — OBSERVED withheld (fail-closed)',
      differentialResult: Z3_RESULT.UNSAT,
    });
  }
  if (!(canBeTrue === Z3_RESULT.SAT && canBeFalse === Z3_RESULT.SAT)) {
    return Object.freeze({
      verdict: FAITHFULNESS_VERDICT.WITHHELD,
      reason:
        'VACUOUS faithfulness query — the informal predicate is constant over the bounded domain (no discriminating power); ' +
        'OBSERVED withheld',
      differentialResult: Z3_RESULT.UNSAT,
      vacuous: true,
    });
  }

  return Object.freeze({
    verdict: FAITHFULNESS_VERDICT.FAITHFUL,
    reason:
      'bounded faithfulness PASS: no disagreeing model within the bounded domain, every concrete battery instance agrees, ' +
      'and the informal predicate is contingent (non-vacuous) — a NAMED BOUNDED guarantee, NOT general equivalence',
    differentialResult: Z3_RESULT.UNSAT,
  });
}

// ---------------------------------------------------------------------------
// certifyFaithfulness — the PRODUCER (mints the re-executable record + artifact).
// ---------------------------------------------------------------------------

/**
 * Mint a faithfulness RECORD for `claim`: validate the battery integrity (HARD-FAULTS on a Claude /
 * undersized battery), run the DIFFERENTIAL once via the producer `solve` to record `result` (provenance
 * only — the canary recomputes), and freeze the { artifact, query, battery, differential_smt2, claim_id }
 * record the Wave-4 adjudication re-runs. Does NOT decide faithfulness (that is the canary's job).
 */
export async function certifyFaithfulness({ claim, query, battery, z3Version, pinnedDefaultCount }, { solve } = {}) {
  if (!claim || typeof claim.id !== 'string') {
    throw new SmtFaithfulnessError('certifyFaithfulness requires the claim being certified');
  }
  assertQuery(query);
  validateBatteryIntegrity(battery, pinnedDefaultCount); // throws on a Claude / undersized battery
  const differentialSmt2 = buildDifferentialSmt2(query);

  let result = null;
  if (isDecidableEnvelope(query)) {
    if (typeof solve !== 'function') {
      throw new SmtFaithfulnessError('certifyFaithfulness requires an async solve(smt2) to record the differential result');
    }
    result = normalizeSolveResult(await solve(differentialSmt2));
  }

  const artifact = makeSmtArtifact({
    smt2: differentialSmt2,
    z3Version,
    result,
    batteryProvenance: battery.provenance,
    batteryCount: battery.count ?? battery.instances.length,
    boundedDomain: query.domain,
  });

  return Object.freeze({
    artifact,
    claim_id: claim.id,
    query: Object.freeze({ ...query, vars: Object.freeze([...query.vars]), domain: Object.freeze({ ...query.domain }) }),
    battery,
    differential_smt2: differentialSmt2,
    smt2_hash: artifact.smt2_hash,
  });
}

// ---------------------------------------------------------------------------
// adjudicateFaithfulness — the CANARY (independent z3 re-run + the decision).
// ---------------------------------------------------------------------------

/**
 * Adjudicate a faithfulness record for `claim`. RE-RUNS the full bounded check from the stored query via
 * an INDEPENDENT `z3Rerun` (it never trusts the producer-recorded `result`) and decides:
 *   FAITHFUL   — the bounded guarantee holds on the independent re-run.
 *   UNFAITHFUL — a disagreeing model/instance exists (a DIFFERENT statement).
 *   WITHHELD   — fail-closed: z3 unknown, vacuous, out of the z3-decidable envelope, or no canary supplied.
 *   FLAG       — a DETECTED defect: cross-claim binding, malformed artifact, or a FORGED `result`
 *                (the producer recorded `unsat` but the independent re-run is not `unsat`).
 * HARD-FAULTS (throws) if the battery is Claude-sourced or undersized (re-checked here, not just at mint).
 *
 * @param {{ record:object, claim:object, z3Rerun?:Function, pinnedDefaultCount:number }} o
 */
export async function adjudicateFaithfulness({ record, claim, z3Rerun, pinnedDefaultCount } = {}) {
  if (!claim || typeof claim.id !== 'string') {
    throw new SmtFaithfulnessError('adjudicateFaithfulness requires the claim being certified');
  }
  if (!record || typeof record !== 'object') {
    return faithFlag('no SMT faithfulness record supplied');
  }
  const v = validateSmtArtifact(record.artifact);
  if (!v.ok) return faithFlag(`malformed SMT artifact: ${v.failures.join('; ')}`);

  // Battery integrity HARD-FAULT (re-checked at adjudication so a forged record can't smuggle a Claude
  // battery past the build) — throws on Claude / undersized.
  validateBatteryIntegrity(record.battery, pinnedDefaultCount);

  // Claim binding (anti cross-claim / replay).
  if (record.claim_id !== claim.id) {
    return faithFlag(`SMT record is bound to ${JSON.stringify(record.claim_id)}, not this claim ${JSON.stringify(claim.id)} (cross-claim / replay)`);
  }
  // The stored differential SMT2 must self-hash to the artifact's smt2_hash (anti-tamper).
  if (typeof record.differential_smt2 !== 'string' || smt2Hash(record.differential_smt2) !== record.artifact.smt2_hash) {
    return faithFlag('SMT record differential_smt2 does not match its artifact smt2_hash (tampered query)');
  }

  // CANARY RE-RUN SOURCE BINDING (contract: "the canary re-runs the differential from the stored `.smt2`").
  // computeFaithfulness rebuilds the queries from `record.query`; bind that rebuild to the STORED,
  // hash-verified `.smt2` so the source z3 actually re-runs is provably the stored differential — not a
  // record whose `query` and `differential_smt2` were forged to diverge (each self-consistent, but the
  // query encoding a DIFFERENT differential than the stored/hashed one).
  let rebuiltDifferential;
  try {
    rebuiltDifferential = buildDifferentialSmt2(record.query);
  } catch (e) {
    return faithFlag(`SMT record query is malformed (cannot rebuild the differential to re-run): ${e.message}`);
  }
  if (rebuiltDifferential !== record.differential_smt2) {
    return faithFlag(
      'SMT record query does not rebuild to its stored differential_smt2 — the canary re-run source would ' +
        'differ from the hash-verified `.smt2` (canary re-run source mismatch)',
    );
  }

  // Out-of-envelope ⇒ WITHHELD with the reason code (never run z3 on it).
  if (!isDecidableEnvelope(record.query)) {
    return Object.freeze({ status: FAITHFULNESS_STATUS.WITHHELD, ok: false, reason: OUT_OF_ENVELOPE_REASON, outOfEnvelope: true });
  }

  // The independence canary MUST be exercised (an un-exercised canary is treated as stubbed ⇒ WITHHELD).
  if (typeof z3Rerun !== 'function') {
    return Object.freeze({
      status: FAITHFULNESS_STATUS.WITHHELD,
      ok: false,
      reason: 'z3 independence canary could NOT run (no z3 re-run capability supplied) — OBSERVED withheld (an un-exercised canary is treated as stubbed)',
    });
  }

  // Re-run the full faithfulness check via the INDEPENDENT z3.
  const recomputed = await computeFaithfulness(record.query, record.battery, z3Rerun);

  // FORGERY: the producer recorded a `result` that the independent differential re-run DISAGREES with.
  const recorded = record.artifact.result;
  if (recorded !== null && recomputed.differentialResult !== null && recorded !== recomputed.differentialResult) {
    return faithFlag(
      `FORGED SMT artifact: the producer recorded differential result ${JSON.stringify(recorded)} but the INDEPENDENT z3 re-run ` +
        `from the stored .smt2 is ${JSON.stringify(recomputed.differentialResult)}`,
      { recorded, reexec: recomputed.differentialResult },
    );
  }

  if (recomputed.verdict === FAITHFULNESS_VERDICT.FAITHFUL) {
    return Object.freeze({ status: FAITHFULNESS_STATUS.FAITHFUL, ok: true, reason: recomputed.reason, differentialResult: recomputed.differentialResult });
  }
  if (recomputed.verdict === FAITHFULNESS_VERDICT.UNFAITHFUL) {
    return Object.freeze({ status: FAITHFULNESS_STATUS.UNFAITHFUL, ok: false, reason: recomputed.reason });
  }
  return Object.freeze({ status: FAITHFULNESS_STATUS.WITHHELD, ok: false, reason: recomputed.reason, outOfEnvelope: Boolean(recomputed.outOfEnvelope), vacuous: Boolean(recomputed.vacuous) });
}

const faithFlag = (reason, extra = {}) => Object.freeze({ status: FAITHFULNESS_STATUS.FLAG, ok: false, flagged: true, reason, ...extra });

// ---------------------------------------------------------------------------
// The tool-lane z3 solve (real z3 by manifest absolute path — NEVER invoked at import time).
// ---------------------------------------------------------------------------

/**
 * Build an async `solve(smt2) -> { result, raw }` bound to the real z3 at `z3Path`. Writes the SMT2 to a
 * hermetic temp file and spawns z3 by absolute path (no shell). Parses `unsat` / `sat` / `unknown` from
 * stdout (checking `unsat` BEFORE `sat`, since 'unsat' contains 'sat'); a timeout / unparsed output ⇒
 * `unknown` (fail-closed). Tool-lane only — the fast tier injects a stub `solve`.
 */
export function createZ3Solve(z3Path, { exec = runExecutable, timeoutMs = 60000 } = {}) {
  if (typeof z3Path !== 'string' || z3Path.length === 0) {
    throw new SmtFaithfulnessError('createZ3Solve requires the z3 absolute path');
  }
  return async function solve(smt2) {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-f3-'));
    const file = path.join(dir, 'faithfulness.smt2');
    try {
      fs.writeFileSync(file, smt2, 'utf8');
      const obs = exec(z3Path, [file], { timeoutMs, cwd: dir });
      const out = `${obs.stdout || ''}`;
      let result = Z3_RESULT.UNKNOWN;
      if (obs.timedOut) result = Z3_RESULT.UNKNOWN;
      else if (/\bunsat\b/.test(out)) result = Z3_RESULT.UNSAT;
      else if (/\bsat\b/.test(out)) result = Z3_RESULT.SAT;
      else if (/\bunknown\b/.test(out)) result = Z3_RESULT.UNKNOWN;
      return { result, raw: out.trim() };
    } finally {
      try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* best-effort */ }
    }
  };
}

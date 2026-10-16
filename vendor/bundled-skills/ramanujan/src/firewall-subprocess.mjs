// Wave 9 — Autonomous-VERIFIED gate, part B: firewall subprocess + artifact-mint + recall roster (A4b).
//
// THE FIREWALL AS AN OUT-OF-MODEL EXECUTION SUBPROCESS. Wave 8 built the CLOSED default-deny
// GRAMMAR (the front-end recognizer). This module is the back-end: the only autonomous path to a
// VERIFIED rung runs a recognized literal computation in a CHILD `node` process — a genuinely
// out-of-model executor, distinct from the proposing model (THE HONESTY LAW: propose != adjudicate)
// — and binds its result into a re-executable Wave-4 adjudication ARTIFACT.
//
//   1. THE SUBPROCESS (the win32 §Build-host contract).  The sandbox is a child
//      `node test/sandbox-runner.mjs <input-file>` spawned via child_process.execFileSync on the
//      SAME node binary (process.execPath) — NO shell, so no quoting/injection surface. Each call
//      gets its OWN HERMETIC TEMP DIR `os.tmpdir()/ramanujan-fw-<token>` (created + removed per
//      call); the literal-computation AST is written there as JSON (bigint-tagged so arbitrary-
//      magnitude integers survive the JSON round-trip). The child evaluates over EXACT ARITHMETIC
//      (bigint rationals — NO float) so re-execution is deterministic BY CONSTRUCTION, and prints
//      the canonical (sorted-key, exact-number) stdout the Wave-4 re-hash primitive digests.
//
//   2. THE RUNTIME FINGERPRINT.  The child stamps { node_major, canonicalization_version } INTO the
//      hashed stdout, so a node-major / canonicalization skew changes the content hash and is
//      DETECTED on re-execution (not silently hashed-around). The minted artifact also records the
//      parent's runtimeFingerprint() (same node binary), per the P9 artifact contract.
//
//   3. THE MINT.  mintFirewallArtifact runs the subprocess for a RECOGNIZED (in-grammar) expression
//      and asks the Wave-4 AdjudicationDispatcher (the sole writer of family-of-record) to mint a
//      single-use, claim-bound artifact carrying the subprocess's stdout_hash + exit_code. An
//      OUT-OF-GRAMMAR expression is REFUSED before any child is spawned — the grammar firewall runs
//      first, so a non-literal claim can never be laundered into the autonomous-VERIFIED path.
//
//   4. THE WAVE-4 CANARY POSITIVE PATH.  firewallReexecute / firewallReexecutionAgrees RE-RUN the
//      same child on the same input and compare the SHA-256 of canonical stdout against the
//      artifact's recorded stdout_hash — the canary's warrant. settleComputationViaFirewall wires
//      the whole positive path: recognize -> run -> mint -> adjudicatedPromoteToVerified -> OBSERVED,
//      proving the Wave-4 gate's POSITIVE arm (deferred from Wave 4) with a real re-executable
//      artifact.
//
//   5. THE P7 POSITIVE-RECALL ROSTER (POSITIVE_RECALL_ROSTER).  The dual of Wave-8's laundering
//      battery: in-class literal computations (incl. NESTED COMPOSITIONS — a bounded sum of products
//      of literals, nested bounded sums, a bounded sum of exact rationals) the firewall MUST settle.
//      runPositiveRecallRoster settles each through the full positive path and checks the result, the
//      VERIFIED verdict, and that the canary re-executes to the artifact's hash.
//
// Pure node built-ins + the project's own Wave-4 / Wave-8 modules (no new dependency). The evaluator
// (evalExpr / runSandboxChild) is SHARED with the child entry (test/sandbox-runner.mjs imports it),
// so there is exactly ONE exact-arithmetic evaluator. Runs under `node --test test/`.

import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  canonicalize,
  canonicalStdoutHash,
  runtimeFingerprint,
  CANONICALIZATION_VERSION,
  adjudicatedPromoteToVerified,
  VERDICT,
} from './adjudication.mjs';
import { recognize, GRAMMAR_NODE } from './firewall-grammar.mjs';
import { ClaimLedger } from './claim-ledger.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/**
 * The pinned out-of-model child entry (the win32 §Build-host & subprocess contract names exactly
 * `test/sandbox-runner.mjs`). Resolved relative to THIS module (repo-root/test/sandbox-runner.mjs).
 * test/index.js only imports `*.test.mjs`, so the runner is never executed by the test gate — it is
 * only ever invoked as the spawned child.
 */
export const SANDBOX_RUNNER = fileURLToPath(new URL('../test/sandbox-runner.mjs', import.meta.url));

/** The default adjudication domain for the autonomous arithmetic firewall. */
export const FIREWALL_DOMAIN = 'arithmetic';

/** The firewall verifier-family-of-record (matches verify-router's FIREWALL_FAMILY). */
export const FIREWALL_FAMILY = 'firewall-subprocess';

/** Screen decisions mirrored from the grammar front-end. */
export const SUBPROCESS_DECISION = Object.freeze({ ABSTAIN: 'ABSTAIN', PROCEED: 'PROCEED' });

/** A 64-char lowercase hex (a SHA-256 digest). */
const HEX64 = /^[0-9a-f]{64}$/;

/** A typed error so callers can distinguish a firewall refusal/crash from a programming error. */
export class FirewallSubprocessError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'FirewallSubprocessError';
    Object.assign(this, extra);
  }
}

// ---------------------------------------------------------------------------
// Bigint-safe AST serialization (the JSON the child reads).
//
// JSON cannot carry a BigInt, and in-grammar int literals may be arbitrary-magnitude bigints. We
// tag a bigint as { "__bigint__": "<decimal>" } on the way out and revive it on the way in, so an
// exact integer of any size survives the round-trip through the hermetic input file.
// ---------------------------------------------------------------------------

const BIGINT_TAG = '__bigint__';

/** Serialize an AST to a JSON string, tagging every bigint so it survives JSON. */
export function serializeAst(ast) {
  return JSON.stringify(ast, (_k, v) => (typeof v === 'bigint' ? { [BIGINT_TAG]: v.toString() } : v));
}

/** Parse the child-input JSON string back into an AST, reviving tagged bigints. */
export function parseAst(text) {
  return JSON.parse(text, (_k, v) => {
    if (v && typeof v === 'object' && !Array.isArray(v) && typeof v[BIGINT_TAG] === 'string' && Object.keys(v).length === 1) {
      return BigInt(v[BIGINT_TAG]);
    }
    return v;
  });
}

// ---------------------------------------------------------------------------
// EXACT rational arithmetic (bigint only — NO float ever).
//
// A rational is { n: bigint, d: bigint } kept in lowest terms with d > 0. Determinism is by
// construction: identical input => identical reduced result => identical canonical stdout => identical
// SHA-256. This is the contract that makes "mint TWICE on the same input => identical hash" hold.
// ---------------------------------------------------------------------------

function bigAbs(a) {
  return a < 0n ? -a : a;
}

function bigGcd(a, b) {
  a = bigAbs(a);
  b = bigAbs(b);
  while (b) {
    [a, b] = [b, a % b];
  }
  return a;
}

/** Build a reduced rational n/d with d > 0. Throws on a zero denominator (division by zero). */
function makeRat(n, d) {
  if (d === 0n) throw new FirewallSubprocessError('exact-arithmetic error: division by zero');
  if (d < 0n) {
    n = -n;
    d = -d;
  }
  const g = bigGcd(n, d) || 1n;
  return { n: n / g, d: d / g };
}

const ratAdd = (a, b) => makeRat(a.n * b.d + b.n * a.d, a.d * b.d);
const ratSub = (a, b) => makeRat(a.n * b.d - b.n * a.d, a.d * b.d);
const ratMul = (a, b) => makeRat(a.n * b.n, a.d * b.d);
const ratDiv = (a, b) => makeRat(a.n * b.d, a.d * b.n);
const ratNeg = (a) => makeRat(-a.n, a.d);

/** base^exp for a non-negative integer exponent (finite repeated multiplication). */
function ratPow(base, exp) {
  if (exp < 0n) throw new FirewallSubprocessError('exact-arithmetic error: negative exponent (non-literal inverse)');
  return makeRat(base.n ** exp, base.d ** exp);
}

/**
 * Coerce an EXACT integer literal to a bigint, or throw. Accepts a bigint, a SAFE-integer JS number,
 * or a canonical decimal-integer string /^-?\d+$/. Anything else (a float, NaN, ±Infinity, a >2^53
 * double, '0x..', '1.0', '1e3', a boolean) throws — mirroring the Wave-8 grammar's asIntegerLiteral.
 */
function coerceIntLiteral(value) {
  if (typeof value === 'bigint') return value;
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new FirewallSubprocessError(`out-of-grammar int literal (not an exact integer): ${value}`);
    return BigInt(value);
  }
  if (typeof value === 'string' && /^-?\d+$/.test(value)) return BigInt(value);
  throw new FirewallSubprocessError(`out-of-grammar int literal: ${JSON.stringify(value)}`);
}

/** Evaluate a sum/product bound — a literal int node, or a neg of one — to a bigint integer. */
function evalBound(node) {
  if (node && typeof node === 'object' && !Array.isArray(node)) {
    if (node.type === GRAMMAR_NODE.INT) return coerceIntLiteral(node.value);
    if (node.type === GRAMMAR_NODE.NEG && node.operand && node.operand.type === GRAMMAR_NODE.INT) {
      return -coerceIntLiteral(node.operand.value);
    }
  }
  throw new FirewallSubprocessError('out-of-grammar sum/product bound (must be a literal integer)');
}

/**
 * Evaluate an in-grammar AST node to an EXACT rational { n, d }. `env` maps a bound sum/product index
 * name to its current integer value (a rational with d = 1). Throws on any out-of-grammar node — the
 * subprocess only ever executes computations the Wave-8 firewall already recognized, but the
 * evaluator is defensively closed (an unrecognized node throws, exiting the child non-zero).
 */
export function evalExpr(node, env = Object.create(null)) {
  if (!node || typeof node !== 'object' || Array.isArray(node)) {
    throw new FirewallSubprocessError(`out-of-grammar node (not an object): ${JSON.stringify(node)}`);
  }
  switch (node.type) {
    case GRAMMAR_NODE.INT:
      return makeRat(coerceIntLiteral(node.value), 1n);
    case GRAMMAR_NODE.RATIONAL:
      return makeRat(coerceIntLiteral(node.num), coerceIntLiteral(node.den));
    case GRAMMAR_NODE.NEG:
      return ratNeg(evalExpr(node.operand, env));
    case GRAMMAR_NODE.ADD:
      return ratAdd(evalExpr(node.left, env), evalExpr(node.right, env));
    case GRAMMAR_NODE.SUB:
      return ratSub(evalExpr(node.left, env), evalExpr(node.right, env));
    case GRAMMAR_NODE.MUL:
      return ratMul(evalExpr(node.left, env), evalExpr(node.right, env));
    case GRAMMAR_NODE.DIV:
      return ratDiv(evalExpr(node.left, env), evalExpr(node.right, env));
    case GRAMMAR_NODE.POW: {
      const base = evalExpr(node.left, env);
      if (!node.right || node.right.type !== GRAMMAR_NODE.INT) {
        throw new FirewallSubprocessError('out-of-grammar pow exponent (must be a literal int node)');
      }
      return ratPow(base, coerceIntLiteral(node.right.value));
    }
    case GRAMMAR_NODE.SUM:
    case GRAMMAR_NODE.PRODUCT: {
      if (typeof node.index !== 'string' || node.index.length === 0) {
        throw new FirewallSubprocessError(`${node.type} requires a non-empty string index`);
      }
      const lo = evalBound(node.lower);
      const hi = evalBound(node.upper);
      const isSum = node.type === GRAMMAR_NODE.SUM;
      let acc = isSum ? makeRat(0n, 1n) : makeRat(1n, 1n);
      for (let k = lo; k <= hi; k += 1n) {
        const inner = Object.assign(Object.create(null), env, { [node.index]: makeRat(k, 1n) });
        const term = evalExpr(node.body, inner);
        acc = isSum ? ratAdd(acc, term) : ratMul(acc, term);
      }
      return acc;
    }
    case GRAMMAR_NODE.VAR: {
      if (typeof node.name !== 'string' || node.name.length === 0) {
        throw new FirewallSubprocessError('out-of-grammar var (missing name)');
      }
      const v = env[node.name];
      if (v === undefined) throw new FirewallSubprocessError(`unbound/free variable ${JSON.stringify(node.name)} (only a bound index is in grammar)`);
      return v;
    }
    default:
      throw new FirewallSubprocessError(`out-of-grammar node type ${JSON.stringify(node && node.type)}`);
  }
}

/** The child's own runtime fingerprint, stamped INTO the hashed stdout so a skew is detected. */
function childFingerprint() {
  return {
    node_major: Number(String(process.versions.node).split('.')[0]),
    canonicalization_version: CANONICALIZATION_VERSION,
  };
}

/**
 * The canonical stdout for a recognized AST: a sorted-key, exact-number serialization of
 * { computation, result:{ num, den }, runtime_fingerprint }. Bigints render as decimal strings (no
 * float ever). This is exactly what the child writes and what the canary re-hashes.
 */
export function computeChildStdout(ast) {
  const r = evalExpr(ast);
  return canonicalize({
    computation: ast,
    result: { num: r.n, den: r.d },
    runtime_fingerprint: childFingerprint(),
  });
}

/**
 * The child entry point (called by test/sandbox-runner.mjs). Reads the hermetic input file named in
 * argv, evaluates the AST, and writes canonical stdout. On any error it writes to stderr and sets a
 * non-zero exit code (the parent treats that as a non-settling run). With NO input path (e.g. a bare
 * `node` import) it is a no-op, so it can never register or fail a test.
 */
export function runSandboxChild(args) {
  const inputPath = args && args[0];
  if (!inputPath) return; // no-op when invoked without an input file
  try {
    const ast = parseAst(fs.readFileSync(inputPath, 'utf8'));
    process.stdout.write(computeChildStdout(ast));
  } catch (e) {
    process.stderr.write(`firewall-sandbox error: ${e && e.message ? e.message : String(e)}\n`);
    process.exitCode = 1;
  }
}

// ---------------------------------------------------------------------------
// The parent: spawn the hermetic child + hash its stdout.
// ---------------------------------------------------------------------------

/**
 * Run a RECOGNIZED literal computation in the out-of-model child. Creates a per-call hermetic temp
 * dir, writes the bigint-tagged AST, spawns `node sandbox-runner.mjs <input>` (NO shell, same node
 * binary), captures stdout, hashes it with the Wave-4 re-hash primitive, then removes the temp dir.
 *
 * @param {object} expr  an in-grammar AST (caller is expected to recognize() first; this is the
 *                       executor, not the firewall gate).
 * @returns {{stdout:string, stdout_hash:string, exit_code:number, hermeticDir:string}}
 */
export function runSubprocess(expr) {
  const token = crypto.randomBytes(12).toString('hex');
  const dir = path.join(os.tmpdir(), `ramanujan-fw-${token}`);
  fs.mkdirSync(dir, { recursive: true });
  try {
    const inputPath = path.join(dir, 'input.json');
    fs.writeFileSync(inputPath, serializeAst(expr), 'utf8');
    let stdout;
    try {
      // execFileSync — NOT a shell. process.execPath is THIS node binary (a genuine child `node`).
      stdout = execFileSync(process.execPath, [SANDBOX_RUNNER, inputPath], { encoding: 'utf8', cwd: dir });
    } catch (e) {
      const exit_code = typeof e.status === 'number' ? e.status : 1;
      const stderr = e && e.stderr ? String(e.stderr).trim() : '';
      throw new FirewallSubprocessError(`firewall subprocess exited ${exit_code}: ${stderr}`, {
        exit_code,
        stdout: e && e.stdout ? String(e.stdout) : '',
        hermeticDir: dir,
      });
    }
    if (typeof stdout !== 'string' || stdout.length === 0) {
      throw new FirewallSubprocessError('firewall subprocess produced no stdout', { exit_code: 0, hermeticDir: dir });
    }
    return { stdout, stdout_hash: canonicalStdoutHash(stdout), exit_code: 0, hermeticDir: dir };
  } finally {
    // hermetic: the per-call temp dir never outlives the call.
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* best-effort */ }
  }
}

/** Parse the { computation, result, runtime_fingerprint } object out of a child's canonical stdout. */
export function parseStdout(stdout) {
  return JSON.parse(stdout);
}

/** The exact-rational result { num, den } (decimal strings) the child computed. */
export function resultOf(stdout) {
  return parseStdout(stdout).result;
}

/**
 * SCREEN + run: the firewall front-end + executor in one. An OUT-OF-GRAMMAR expression returns an
 * ABSTAIN decision and NEVER spawns a child (the grammar firewall runs first). An in-grammar
 * expression runs the subprocess and returns PROCEED + the run.
 */
export function screenAndRun(expr) {
  const grammar = recognize(expr);
  if (!grammar.inGrammar) {
    return Object.freeze({
      decision: SUBPROCESS_DECISION.ABSTAIN,
      route: 'out-of-model',
      inGrammar: false,
      reason: `firewall grammar rejected this input (closed default-deny): ${grammar.reason} [at ${grammar.path}]`,
      grammar,
    });
  }
  const run = runSubprocess(expr);
  return Object.freeze({ decision: SUBPROCESS_DECISION.PROCEED, route: null, inGrammar: true, grammar, ...run });
}

// ---------------------------------------------------------------------------
// The mint + the Wave-4 canary positive path.
// ---------------------------------------------------------------------------

function assertDispatcher(dispatcher) {
  if (!dispatcher || typeof dispatcher.mintArtifact !== 'function' || typeof dispatcher.consumeArtifact !== 'function') {
    throw new FirewallSubprocessError('mintFirewallArtifact requires a Wave-4 AdjudicationDispatcher');
  }
}

/**
 * Run the subprocess for a RECOGNIZED computation and mint a single-use, claim-bound Wave-4 artifact
 * carrying its stdout_hash + exit_code. The grammar firewall runs FIRST: an out-of-grammar expression
 * is REFUSED (FirewallSubprocessError) before any child is spawned — no out-of-grammar computation can
 * be laundered into an artifact. Returns { artifact, run }.
 */
export function mintFirewallArtifact(dispatcher, claim_id, expr, { domain = FIREWALL_DOMAIN } = {}) {
  assertDispatcher(dispatcher);
  const grammar = recognize(expr);
  if (!grammar.inGrammar) {
    throw new FirewallSubprocessError(
      `firewall refused to mint: out-of-grammar computation (${grammar.reason} [at ${grammar.path}])`,
      { grammar },
    );
  }
  const run = runSubprocess(expr);
  const artifact = dispatcher.mintArtifact(claim_id, domain, { stdout_hash: run.stdout_hash, exit_code: run.exit_code });
  return { artifact, run };
}

/**
 * The canary's RE-EXECUTION: re-run the same child on the same input and return its hash. (A fresh
 * hermetic run — deterministic by construction, so it reproduces the mint's hash on an unchanged
 * runtime.)
 */
export function firewallReexecute(expr) {
  return runSubprocess(expr);
}

/**
 * Does this artifact's recorded stdout_hash RE-EXECUTE? Re-run the subprocess on `expr` and compare.
 * This is the Wave-4/Wave-6 canary warrant carried over to the REAL out-of-model child: a fabricated
 * stdout_hash (a same-family lie about the result), or a runtime skew, fails to reproduce. A
 * computation that does not even run (out-of-grammar / crash) => false.
 */
export function firewallReexecutionAgrees(artifact, expr) {
  if (!artifact || typeof artifact.stdout_hash !== 'string' || !HEX64.test(artifact.stdout_hash)) return false;
  let r;
  try {
    r = runSubprocess(expr);
  } catch {
    return false;
  }
  return r.stdout_hash === artifact.stdout_hash;
}

/**
 * THE FULL POSITIVE PATH (Wave-4 canary positive arm). For a recognized literal computation:
 * recognize -> run the out-of-model child -> mint a claim-bound artifact -> adjudicatedPromoteToVerified
 * -> OBSERVED. Also re-executes the child to confirm the artifact reproduces (the canary). An
 * out-of-grammar expression ABSTAINs with NO child spawned and NO rung raised.
 *
 * @returns frozen { verdict, settled, reexecutes, artifact?, stdout_hash?, family?, reason?, gate? }
 */
export function settleComputationViaFirewall(ledger, dispatcher, claim_id, expr, { domain = FIREWALL_DOMAIN } = {}) {
  if (!ledger || typeof ledger.promote !== 'function') {
    throw new FirewallSubprocessError('settleComputationViaFirewall requires a ClaimLedger');
  }
  const grammar = recognize(expr);
  if (!grammar.inGrammar) {
    return Object.freeze({
      verdict: VERDICT.ABSTAIN,
      settled: false,
      reexecutes: false,
      reason: `firewall grammar rejected this computation (closed default-deny): ${grammar.reason} [at ${grammar.path}] — routing out-of-model`,
    });
  }
  const { artifact, run } = mintFirewallArtifact(dispatcher, claim_id, expr, { domain });
  const gate = adjudicatedPromoteToVerified(ledger, claim_id, { artifact, dispatcher });
  const reexecutes = firewallReexecutionAgrees(artifact, expr);
  return Object.freeze({
    verdict: gate.verdict,
    settled: gate.verdict === VERDICT.VERIFIED,
    reexecutes,
    artifact,
    stdout_hash: run.stdout_hash,
    result: resultOf(run.stdout), // the exact-rational { num, den } the child computed
    family: gate.family || null,
    gate,
  });
}

// ---------------------------------------------------------------------------
// THE P7 POSITIVE-RECALL ROSTER — in-class computations the firewall MUST settle.
//
// The dual of Wave-8's LAUNDERING_BATTERY. Built from the Wave-8 grammar AST builders; each entry
// pins the EXACT expected result so the roster checks correctness, not merely determinism. Includes
// several NESTED COMPOSITIONS (a bounded sum of products of literals, nested bounded sums, a bounded
// sum of exact rationals) — the done-when's required nested-composition expression.
// ---------------------------------------------------------------------------

const I = (v) => ({ type: GRAMMAR_NODE.INT, value: v });
const RAT = (num, den) => ({ type: GRAMMAR_NODE.RATIONAL, num, den });
const NEG = (operand) => ({ type: GRAMMAR_NODE.NEG, operand });
const ADD = (left, right) => ({ type: GRAMMAR_NODE.ADD, left, right });
const SUB = (left, right) => ({ type: GRAMMAR_NODE.SUB, left, right });
const MUL = (left, right) => ({ type: GRAMMAR_NODE.MUL, left, right });
const DIV = (left, right) => ({ type: GRAMMAR_NODE.DIV, left, right });
const POW = (left, right) => ({ type: GRAMMAR_NODE.POW, left, right });
const VAR = (name) => ({ type: GRAMMAR_NODE.VAR, name });
const SUM = (index, lower, upper, body) => ({ type: GRAMMAR_NODE.SUM, index, lower, upper, body });
const PRODUCT = (index, lower, upper, body) => ({ type: GRAMMAR_NODE.PRODUCT, index, lower, upper, body });

export const POSITIVE_RECALL_ROSTER = Object.freeze([
  Object.freeze({ name: 'integer-literal', expr: I(6), expected: { num: '6', den: '1' } }),
  Object.freeze({ name: 'nested-finite-arithmetic', expr: ADD(MUL(I(2), I(3)), NEG(I(4))), expected: { num: '2', den: '1' } }),
  Object.freeze({ name: 'exact-division-rational', expr: DIV(I(22), I(7)), expected: { num: '22', den: '7' } }),
  Object.freeze({ name: 'sum-of-exact-rationals', expr: ADD(RAT(1, 2), RAT(1, 3)), expected: { num: '5', den: '6' } }),
  Object.freeze({ name: 'pow-literal-exponent', expr: POW(I(2), I(10)), expected: { num: '1024', den: '1' } }),
  Object.freeze({ name: 'pow-zero-exponent', expr: POW(I(5), I(0)), expected: { num: '1', den: '1' } }),
  // --- NESTED COMPOSITIONS (the done-when's required class) -------------------------------------
  // sum_{k=1}^{3} (k * 2) = 2 + 4 + 6 = 12 — a bounded sum of products of literals.
  Object.freeze({ name: 'bounded-sum-of-products', nested: true, expr: SUM('k', I(1), I(3), MUL(VAR('k'), I(2))), expected: { num: '12', den: '1' } }),
  // product_{k=1}^{4} k = 4! = 24 — a bounded product.
  Object.freeze({ name: 'bounded-product-factorial', expr: PRODUCT('k', I(1), I(4), VAR('k')), expected: { num: '24', den: '1' } }),
  // sum_{i=1}^{2} sum_{j=1}^{3} (i*j) = 6 + 12 = 18 — nested bounded sums.
  Object.freeze({
    name: 'nested-bounded-sums',
    nested: true,
    expr: SUM('i', I(1), I(2), SUM('j', I(1), I(3), MUL(VAR('i'), VAR('j')))),
    expected: { num: '18', den: '1' },
  }),
  // sum_{k=-2}^{2} k = 0 — a negative literal bound.
  Object.freeze({ name: 'negative-literal-bound-sum', expr: SUM('k', NEG(I(2)), I(2), VAR('k')), expected: { num: '0', den: '1' } }),
  // sum_{k=1}^{3} (1/k) = 1 + 1/2 + 1/3 = 11/6 — a bounded sum of exact rationals (division by the bound index).
  Object.freeze({ name: 'bounded-harmonic-sum', nested: true, expr: SUM('k', I(1), I(3), DIV(I(1), VAR('k'))), expected: { num: '11', den: '6' } }),
  // a big-integer literal (arbitrary magnitude, exact).
  Object.freeze({ name: 'big-integer-literal', expr: I('999999999999999999999999999999'), expected: { num: '999999999999999999999999999999', den: '1' } }),
  // 2^3 + 3 * sum_{k=1}^{2} k = 8 + 3*3 = 17 — composition of pow + arithmetic + a bounded sum.
  Object.freeze({
    name: 'pow-plus-scaled-bounded-sum',
    nested: true,
    expr: ADD(POW(I(2), I(3)), MUL(I(3), SUM('k', I(1), I(2), VAR('k')))),
    expected: { num: '17', den: '1' },
  }),
]);

/**
 * Settle the WHOLE positive-recall roster through the full firewall positive path. `makeDispatcher`
 * mints a fresh Wave-4 AdjudicationDispatcher per entry (the caller owns the durability substrate +
 * temp files); `makeLedger` defaults to a fresh A1 ClaimLedger per entry. Returns a report whose
 * done-when invariant is allVerified && allReexecute && allResultsMatch.
 *
 * @param {{makeDispatcher:(entry:object,i:number)=>object, makeLedger?:(entry:object,i:number)=>object}} o
 */
export function runPositiveRecallRoster({ makeDispatcher, makeLedger } = {}) {
  if (typeof makeDispatcher !== 'function') {
    throw new FirewallSubprocessError('runPositiveRecallRoster requires a makeDispatcher() factory');
  }
  const results = POSITIVE_RECALL_ROSTER.map((entry, i) => {
    const dispatcher = makeDispatcher(entry, i);
    const ledger = makeLedger ? makeLedger(entry, i) : new ClaimLedger();
    const claim_id = `recall-${i}-${entry.name}`;
    ledger.assert({ id: claim_id, type: 'computational' });
    const settle = settleComputationViaFirewall(ledger, dispatcher, claim_id, entry.expr);
    const got = settle.result || null;
    const resultMatches = got != null && got.num === entry.expected.num && got.den === entry.expected.den;
    return {
      name: entry.name,
      nested: Boolean(entry.nested),
      claim_id,
      verdict: settle.verdict,
      settled: settle.settled,
      reexecutes: settle.reexecutes,
      family: settle.family,
      expected: entry.expected,
      got,
      resultMatches,
      rung: ledger.rungOf(claim_id),
    };
  });
  return {
    total: results.length,
    nestedCount: results.filter((r) => r.nested).length,
    results,
    allVerified: results.every((r) => r.verdict === VERDICT.VERIFIED && r.settled),
    allReexecute: results.every((r) => r.reexecutes === true),
    allResultsMatch: results.every((r) => r.resultMatches === true),
  };
}

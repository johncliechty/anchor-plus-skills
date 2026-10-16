// Wave 8 — Autonomous-VERIFIED gate, part A: default-deny grammar + laundering battery (A4a).
//
// THE LITERAL-EXECUTION RECOGNIZER. The autonomous tier (THE HONESTY LAW) settles ONLY a literal
// finite computation bound to a re-executable out-of-model artifact. Before any such artifact may
// be minted (Wave 9), the candidate expression must first be recognized as IN-CLASS by a CLOSED,
// DEFAULT-DENY whitelist GRAMMAR over EXACT arithmetic. This module is that grammar — the firewall's
// front-end. It does NOT execute, mint, or raise a rung; it only RECOGNIZES, so a non-computational
// claim can never be "laundered" into the autonomous-VERIFIED path by dressing it up as arithmetic.
//
// THE GRAMMAR (the whitelist — everything else is denied by construction):
//   - int        — an EXACT integer literal: a bigint, a safe JS integer, or a /^-?\d+$/ string.
//   - rational   — an EXACT rational literal {num, den}: both integer literals, den != 0. (NO float.)
//   - neg        — unary negation of an in-grammar node.
//   - add/sub/mul/div — binary EXACT arithmetic over in-grammar operands (div is exact rational).
//   - pow        — base^exponent where the exponent is a LITERAL non-negative integer (finite
//                  repeated multiplication; a symbolic/float/negative exponent is OUT of grammar).
//   - sum/product — a BOUNDED finite sum/product with LITERAL integer bounds and a bound index whose
//                  name is in scope inside the body (the ONLY legal symbol).
//   - var        — a reference to a BOUND sum/product index. A FREE var is symbolic ⇒ DENIED.
//
// DEFAULT-DENY (the closure property). The recognizer walks the WHOLE tree. A node is in-grammar
// ONLY if its `type` is on the whitelist AND every child is in-grammar. ANY other node type
// (float, symbol, forall/exists, limit, integral, derivative, an arbitrary function call, infinity,
// a raw string/number/array, a node with no `type`) — ANYWHERE in the tree, however deeply nested —
// makes the ENTIRE expression out-of-grammar. There is no "mostly valid": one smuggled node denies
// the whole composition. Anything unparsed / outside ⇒ ABSTAIN + route (the honest no-autonomous-
// verifier arm), raising NO rung.
//
// THE P7 LAUNDERING BATTERY (LAUNDERING_BATTERY) is the adversarial fixture set: every entry is an
// input that TRIES to smuggle an out-of-grammar node past the recognizer, including DEEP-NESTED
// SMUGGLES (an out-of-grammar leaf buried inside an otherwise-valid tree). The done-when: the
// grammar rejects (ABSTAIN+route) 100% of the battery, and — with no minter — raises no VERIFIED
// rung. IN_GRAMMAR_EXAMPLES is the dual: genuine literal computations the grammar ACCEPTS (their
// positive settlement is Wave 9; here they still ABSTAIN+route absent a minter).
//
// Node built-ins only (pure, dependency-free). Imported by the VERIFY router (Wave 7) as the
// computational path's front-end and re-used by the Wave-24 gradeable-oracle corpus. Runs under
// `node --test test/`.

// ---------------------------------------------------------------------------
// The whitelist — the CLOSED set of in-grammar node types.
// ---------------------------------------------------------------------------

/** The grammar's node-type vocabulary. Any `type` outside this set is denied (default-deny). */
export const GRAMMAR_NODE = Object.freeze({
  INT: 'int',
  RATIONAL: 'rational',
  NEG: 'neg',
  ADD: 'add',
  SUB: 'sub',
  MUL: 'mul',
  DIV: 'div',
  POW: 'pow',
  SUM: 'sum',
  PRODUCT: 'product',
  VAR: 'var',
});

/** The whitelisted node types, as an array (for error messages + introspection). */
export const WHITELIST = Object.freeze(Object.values(GRAMMAR_NODE));

const BINARY_OPS = Object.freeze([GRAMMAR_NODE.ADD, GRAMMAR_NODE.SUB, GRAMMAR_NODE.MUL, GRAMMAR_NODE.DIV]);

/** Screen decisions. ABSTAIN routes out-of-model; PROCEED hands an in-grammar node to the minter. */
export const SCREEN_DECISION = Object.freeze({ ABSTAIN: 'ABSTAIN', PROCEED: 'PROCEED' });

// ---------------------------------------------------------------------------
// Literal validation — EXACT integers only; NO float ever.
// ---------------------------------------------------------------------------

/**
 * Coerce a value to an EXACT integer literal, or report it out-of-grammar. Accepts:
 *   - a bigint (any magnitude);
 *   - a JS number that is a SAFE integer (so a float, NaN, ±Infinity, or a >2^53 double — which
 *     could not be exact — is rejected: pass those as a bigint or a decimal string instead);
 *   - a canonical decimal-integer string /^-?\d+$/ (arbitrary magnitude, no '0x', '1.0', '1e3', etc.).
 * Returns { ok:true, big:<bigint> } or { ok:false }.
 */
function asIntegerLiteral(value) {
  if (typeof value === 'bigint') return { ok: true, big: value };
  if (typeof value === 'number') {
    // Number.isSafeInteger rejects floats, NaN, ±Infinity, and unsafe (>2^53) integers in one check.
    if (!Number.isSafeInteger(value)) return { ok: false };
    return { ok: true, big: BigInt(value) };
  }
  if (typeof value === 'string') {
    if (!/^-?\d+$/.test(value)) return { ok: false };
    return { ok: true, big: BigInt(value) };
  }
  return { ok: false };
}

/** Best-effort, bigint-safe stringify for diagnostics. */
function show(value) {
  if (typeof value === 'bigint') return `${value}n`;
  if (typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') return Object.is(value, -0) ? '-0' : String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function reject(reason, path, nodeType) {
  return { reason, path, nodeType: nodeType === undefined ? null : nodeType };
}

// ---------------------------------------------------------------------------
// The recursive recognizer (default-deny).
// ---------------------------------------------------------------------------

/**
 * Recognize a sum/product BOUND: it must be a LITERAL integer node — an `int` literal, or a `neg`
 * of an `int` literal. This denies an unbounded bound ({type:'infinity'}), a symbolic bound
 * ({type:'var'}), and a COMPUTED bound (any expression node) — only literal bounds are in grammar.
 */
function recognizeBound(node, path) {
  if (node && typeof node === 'object' && !Array.isArray(node)) {
    if (node.type === GRAMMAR_NODE.INT) {
      return asIntegerLiteral(node.value).ok
        ? null
        : reject(`sum/product bound is not an exact integer literal (got ${show(node.value)})`, path, GRAMMAR_NODE.INT);
    }
    if (node.type === GRAMMAR_NODE.NEG && node.operand && node.operand.type === GRAMMAR_NODE.INT) {
      return asIntegerLiteral(node.operand.value).ok
        ? null
        : reject(`sum/product bound is not an exact integer literal (got ${show(node.operand.value)})`, `${path}.operand`, GRAMMAR_NODE.INT);
    }
  }
  return reject(
    'sum/product bound must be a LITERAL integer (no unbounded, symbolic, or computed bound)',
    path,
    node && typeof node === 'object' ? node.type ?? null : null,
  );
}

/**
 * Walk a node under `scope` (the set of in-scope bound index names). Returns null if the whole
 * subtree is in grammar, or the FIRST violation {reason, path, nodeType}. `||` short-circuits to
 * the first failing child, so the reported path points at the smuggled node.
 */
function walk(node, scope, path) {
  if (node === null || typeof node !== 'object' || Array.isArray(node)) {
    return reject(`a grammar node must be a non-null, non-array object (got ${show(node)})`, path, null);
  }
  const t = node.type;
  if (typeof t !== 'string') {
    return reject('node is missing a string `type` (default-deny: an untyped node is out of grammar)', path, null);
  }

  switch (t) {
    case GRAMMAR_NODE.INT:
      return asIntegerLiteral(node.value).ok
        ? null
        : reject(
            `int literal is not an EXACT integer (got ${show(node.value)}; allowed: bigint, safe integer, or /^-?\\d+$/ string — NO float)`,
            path,
            t,
          );

    case GRAMMAR_NODE.RATIONAL: {
      const num = asIntegerLiteral(node.num);
      if (!num.ok) return reject(`rational numerator is not an exact integer (got ${show(node.num)})`, `${path}.num`, t);
      const den = asIntegerLiteral(node.den);
      if (!den.ok) return reject(`rational denominator is not an exact integer (got ${show(node.den)})`, `${path}.den`, t);
      if (den.big === 0n) return reject('rational has a zero denominator (not a finite exact value)', `${path}.den`, t);
      return null;
    }

    case GRAMMAR_NODE.NEG:
      return walk(node.operand, scope, `${path}.operand`);

    case GRAMMAR_NODE.ADD:
    case GRAMMAR_NODE.SUB:
    case GRAMMAR_NODE.MUL:
    case GRAMMAR_NODE.DIV:
      return walk(node.left, scope, `${path}.left`) || walk(node.right, scope, `${path}.right`);

    case GRAMMAR_NODE.POW: {
      const base = walk(node.left, scope, `${path}.left`);
      if (base) return base;
      // The exponent must be a LITERAL non-negative integer — finite repeated multiplication. A
      // symbolic, float, expression, or negative exponent (an inverse / root) is out of grammar.
      const e = node.right;
      if (!e || typeof e !== 'object' || Array.isArray(e) || e.type !== GRAMMAR_NODE.INT) {
        return reject(
          'pow exponent must be a LITERAL int node (no symbolic, float, expression, or negative exponent)',
          `${path}.right`,
          e && typeof e === 'object' ? e.type ?? null : null,
        );
      }
      const exp = asIntegerLiteral(e.value);
      if (!exp.ok) return reject(`pow exponent is not an exact integer literal (got ${show(e.value)})`, `${path}.right`, GRAMMAR_NODE.INT);
      if (exp.big < 0n) {
        return reject(`pow exponent must be non-negative (got ${exp.big}; a negative exponent is a non-literal inverse)`, `${path}.right`, GRAMMAR_NODE.INT);
      }
      return null;
    }

    case GRAMMAR_NODE.SUM:
    case GRAMMAR_NODE.PRODUCT: {
      if (typeof node.index !== 'string' || node.index.length === 0) {
        return reject(`${t} requires a non-empty string \`index\` (the bound variable name)`, path, t);
      }
      const lo = recognizeBound(node.lower, `${path}.lower`);
      if (lo) return lo;
      const hi = recognizeBound(node.upper, `${path}.upper`);
      if (hi) return hi;
      // The index is bound ONLY inside the body. Shadow-safe: a fresh scope per binder.
      const inner = new Set(scope);
      inner.add(node.index);
      return walk(node.body, inner, `${path}.body`);
    }

    case GRAMMAR_NODE.VAR:
      if (typeof node.name !== 'string' || node.name.length === 0) {
        return reject('var requires a non-empty string `name`', path, t);
      }
      return scope.has(node.name)
        ? null
        : reject(`free/symbolic variable ${JSON.stringify(node.name)} (only a BOUND sum/product index is in grammar)`, path, t);

    default:
      return reject(`out-of-grammar node type ${JSON.stringify(t)} (closed default-deny whitelist: ${WHITELIST.join(', ')})`, path, t);
  }
}

/**
 * RECOGNIZE — is `node` an in-grammar literal computation? Returns a frozen
 *   { inGrammar:boolean, reason:string|null, path:string|null, nodeType:string|null }.
 * inGrammar is true ONLY when the ENTIRE tree is in grammar; otherwise reason/path/nodeType point
 * at the FIRST out-of-grammar node (the smuggled node, however deeply nested).
 */
export function recognize(node) {
  const violation = walk(node, new Set(), 'root');
  if (violation) {
    return Object.freeze({ inGrammar: false, reason: violation.reason, path: violation.path, nodeType: violation.nodeType });
  }
  return Object.freeze({ inGrammar: true, reason: null, path: null, nodeType: null });
}

/** Convenience boolean: is `node` in grammar? */
export function isInGrammar(node) {
  return recognize(node).inGrammar;
}

// ---------------------------------------------------------------------------
// SCREEN — the firewall front-end decision the VERIFY router consults.
// ---------------------------------------------------------------------------

/**
 * SCREEN a candidate computation for the autonomous firewall path. This NEVER executes and NEVER
 * raises a rung — it only DECIDES:
 *   - out of grammar           => ABSTAIN + route out-of-model (the closed default-deny boundary).
 *   - in grammar, no minter    => ABSTAIN + route: recognized, but with no out-of-model minter
 *                                 present (Wave 9 builds the subprocess) the autonomous tier has no
 *                                 re-executable artifact, so it honestly cannot settle. (Wave-8 has
 *                                 NO minter, so an in-grammar input still ABSTAINs — no VERIFIED rung.)
 *   - in grammar, minter given => PROCEED (hand the recognized node to the Wave-9 minter).
 * Returns a frozen decision { decision, route, inGrammar, reason, grammar }.
 */
export function screen(node, { minter = null } = {}) {
  const grammar = recognize(node);
  if (!grammar.inGrammar) {
    return Object.freeze({
      decision: SCREEN_DECISION.ABSTAIN,
      route: 'out-of-model',
      inGrammar: false,
      reason: `firewall grammar rejected this input (closed default-deny): ${grammar.reason} [at ${grammar.path}]`,
      grammar,
    });
  }
  if (typeof minter !== 'function') {
    return Object.freeze({
      decision: SCREEN_DECISION.ABSTAIN,
      route: 'out-of-model',
      inGrammar: true,
      reason:
        'recognized in-grammar, but no firewall minter is present (Wave 9 builds the out-of-model subprocess); ' +
        'with no re-executable artifact the autonomous tier ABSTAINs (no VERIFIED rung)',
      grammar,
    });
  }
  return Object.freeze({ decision: SCREEN_DECISION.PROCEED, route: null, inGrammar: true, reason: null, grammar });
}

// ---------------------------------------------------------------------------
// Tiny AST builders (used by the fixtures + by callers constructing expressions).
// ---------------------------------------------------------------------------

export const int = (value) => ({ type: GRAMMAR_NODE.INT, value });
export const rational = (num, den) => ({ type: GRAMMAR_NODE.RATIONAL, num, den });
export const neg = (operand) => ({ type: GRAMMAR_NODE.NEG, operand });
export const add = (left, right) => ({ type: GRAMMAR_NODE.ADD, left, right });
export const sub = (left, right) => ({ type: GRAMMAR_NODE.SUB, left, right });
export const mul = (left, right) => ({ type: GRAMMAR_NODE.MUL, left, right });
export const div = (left, right) => ({ type: GRAMMAR_NODE.DIV, left, right });
export const pow = (left, right) => ({ type: GRAMMAR_NODE.POW, left, right });
export const variable = (name) => ({ type: GRAMMAR_NODE.VAR, name });
export const sum = (index, lower, upper, body) => ({ type: GRAMMAR_NODE.SUM, index, lower, upper, body });
export const product = (index, lower, upper, body) => ({ type: GRAMMAR_NODE.PRODUCT, index, lower, upper, body });

// ---------------------------------------------------------------------------
// IN-GRAMMAR EXAMPLES — genuine literal computations the grammar ACCEPTS.
//
// (Their positive autonomous settlement is Wave 9; in Wave 8, with no minter, they still ABSTAIN +
// route — recognition is necessary but not sufficient.)
// ---------------------------------------------------------------------------

export const IN_GRAMMAR_EXAMPLES = Object.freeze([
  Object.freeze({ name: 'integer-literal', expr: int(6) }),
  Object.freeze({ name: 'big-integer-literal-bigint', expr: int(123456789012345678901234567890n) }),
  Object.freeze({ name: 'big-integer-literal-string', expr: int('999999999999999999999999999999') }),
  Object.freeze({ name: 'exact-rational-literal', expr: rational(1, 3) }),
  Object.freeze({ name: 'negated-integer', expr: neg(int(7)) }),
  Object.freeze({ name: 'nested-finite-arithmetic', expr: add(mul(int(2), int(3)), neg(int(4))) }),
  Object.freeze({ name: 'exact-division', expr: div(int(22), int(7)) }),
  Object.freeze({ name: 'pow-literal-exponent', expr: pow(int(2), int(10)) }),
  Object.freeze({ name: 'pow-zero-exponent', expr: pow(int(5), int(0)) }),
  // bounded sum of products of literals — the canonical "sum_{k=1}^{3} (k*2)" shape.
  Object.freeze({ name: 'bounded-sum-of-products', expr: sum('k', int(1), int(3), mul(variable('k'), int(2))) }),
  // bounded product — 4! = product_{k=1}^{4} k.
  Object.freeze({ name: 'bounded-product', expr: product('k', int(1), int(4), variable('k')) }),
  // a negative LITERAL bound is fine (still literal).
  Object.freeze({ name: 'negative-literal-bound-sum', expr: sum('k', neg(int(2)), int(2), variable('k')) }),
  // nested binders — the inner index is in scope inside the inner body.
  Object.freeze({
    name: 'nested-bounded-sums',
    expr: sum('i', int(1), int(2), sum('j', int(1), int(3), mul(variable('i'), variable('j')))),
  }),
]);

// ---------------------------------------------------------------------------
// THE P7 LAUNDERING BATTERY — every entry MUST be rejected (ABSTAIN + route).
//
// Each tries to smuggle an out-of-grammar node past the recognizer. `smuggle` documents the attack;
// `at` (when set) is the expected violation path, proving the smuggle is caught where it hides —
// including DEEP-NESTED cases where the out-of-grammar node is buried inside an otherwise-valid tree.
// ---------------------------------------------------------------------------

export const LAUNDERING_BATTERY = Object.freeze([
  // --- bare out-of-grammar leaves ----------------------------------------------------------------
  Object.freeze({ name: 'bare-float-node', smuggle: 'a non-whitelisted float node type', expr: { type: 'float', value: 3.14 }, at: 'root' }),
  Object.freeze({ name: 'int-node-with-float-value', smuggle: 'a float smuggled as an int literal value', expr: int(2.5), at: 'root' }),
  Object.freeze({ name: 'int-node-with-nan', smuggle: 'NaN as an int value', expr: int(NaN), at: 'root' }),
  Object.freeze({ name: 'int-node-with-infinity', smuggle: 'Infinity as an int value', expr: int(Infinity), at: 'root' }),
  Object.freeze({ name: 'int-node-unsafe-double', smuggle: 'a >2^53 double that cannot be exact', expr: int(9007199254740993), at: 'root' }),
  Object.freeze({ name: 'int-node-boolean-value', smuggle: 'a boolean coerced as an int value', expr: int(true), at: 'root' }),
  Object.freeze({ name: 'int-string-with-junk', smuggle: 'a non-numeric string int value', expr: int('12a'), at: 'root' }),
  Object.freeze({ name: 'int-string-hex', smuggle: 'a hex string int value (not canonical decimal)', expr: int('0x10'), at: 'root' }),
  Object.freeze({ name: 'int-string-decimal-point', smuggle: 'a decimal-point string int value', expr: int('1.0'), at: 'root' }),
  Object.freeze({ name: 'int-string-exponent', smuggle: 'scientific-notation string int value', expr: int('1e3'), at: 'root' }),
  Object.freeze({ name: 'free-symbolic-variable', smuggle: 'a free (unbound) symbolic variable', expr: variable('x'), at: 'root' }),
  Object.freeze({ name: 'symbol-leaf', smuggle: 'a named symbol leaf (e.g. pi)', expr: { type: 'symbol', name: 'pi' }, at: 'root' }),
  Object.freeze({ name: 'infinity-leaf', smuggle: 'an infinity leaf', expr: { type: 'infinity' }, at: 'root' }),

  // --- non-node / malformed inputs ---------------------------------------------------------------
  Object.freeze({ name: 'raw-string-input', smuggle: 'a raw string instead of an AST node', expr: '6', at: 'root' }),
  Object.freeze({ name: 'raw-number-input', smuggle: 'a raw number instead of an AST node', expr: 6, at: 'root' }),
  Object.freeze({ name: 'null-input', smuggle: 'null instead of a node', expr: null, at: 'root' }),
  Object.freeze({ name: 'array-input', smuggle: 'an array instead of a node', expr: [int(1), int(2)], at: 'root' }),
  Object.freeze({ name: 'node-without-type', smuggle: 'an object with no `type`', expr: { value: 5 }, at: 'root' }),
  Object.freeze({ name: 'rational-zero-denominator', smuggle: 'division by zero dressed as a rational', expr: rational(1, 0), at: 'root.den' }),
  Object.freeze({ name: 'rational-with-float', smuggle: 'a float inside a rational', expr: rational(1.5, 2), at: 'root.num' }),

  // --- symbolic / unbounded / quantified (the "looks mathematical" laundering) -------------------
  Object.freeze({ name: 'forall-quantifier', smuggle: 'a universal quantifier', expr: { type: 'forall', index: 'n', body: int(0) }, at: 'root' }),
  Object.freeze({ name: 'exists-quantifier', smuggle: 'an existential quantifier', expr: { type: 'exists', index: 'n', body: int(0) }, at: 'root' }),
  Object.freeze({ name: 'limit-node', smuggle: 'a limit (analysis, not finite arithmetic)', expr: { type: 'limit', var: 'n', to: 'infinity', body: variable('n') }, at: 'root' }),
  Object.freeze({ name: 'integral-node', smuggle: 'an integral', expr: { type: 'integral', var: 'x', body: variable('x') }, at: 'root' }),
  Object.freeze({ name: 'derivative-node', smuggle: 'a derivative', expr: { type: 'derivative', var: 'x', body: variable('x') }, at: 'root' }),
  Object.freeze({ name: 'arbitrary-function-call', smuggle: 'an arbitrary (possibly transcendental) function call', expr: { type: 'call', fn: 'sin', args: [int(0)] }, at: 'root' }),
  Object.freeze({ name: 'unbounded-sum', smuggle: 'a sum to infinity (a series, not a finite sum)', expr: sum('k', int(1), { type: 'infinity' }, variable('k')), at: 'root.upper' }),
  Object.freeze({ name: 'symbolic-bound-sum', smuggle: 'a sum with a symbolic upper bound', expr: sum('k', int(1), variable('n'), variable('k')), at: 'root.upper' }),
  Object.freeze({ name: 'computed-bound-sum', smuggle: 'a sum whose bound is a computed expression, not a literal', expr: sum('k', int(1), add(int(2), int(3)), variable('k')), at: 'root.upper' }),
  Object.freeze({ name: 'pow-symbolic-exponent', smuggle: 'an exponentiation with a symbolic exponent', expr: pow(int(2), variable('n')), at: 'root.right' }),
  Object.freeze({ name: 'pow-float-exponent', smuggle: 'a fractional exponent (a root) smuggled into pow', expr: pow(int(2), int(0.5)), at: 'root.right' }),
  Object.freeze({ name: 'pow-negative-exponent', smuggle: 'a negative exponent (an inverse) smuggled into pow', expr: pow(int(2), int(-1)), at: 'root.right' }),
  Object.freeze({ name: 'pow-expression-exponent', smuggle: 'a computed (non-literal) exponent', expr: pow(int(2), add(int(1), int(1))), at: 'root.right' }),

  // --- DEEP-NESTED SMUGGLES — an out-of-grammar node buried inside an otherwise-valid tree --------
  Object.freeze({
    name: 'deep-float-in-arithmetic',
    smuggle: 'a float leaf buried under nested add/mul (≈4 levels deep)',
    expr: add(mul(int(2), int(3)), add(int(4), { type: 'float', value: 0.001 })),
    at: 'root.right.right',
  }),
  Object.freeze({
    name: 'deep-float-in-sum-body',
    smuggle: 'a float buried in a bounded-sum body',
    expr: sum('k', int(1), int(4), mul(variable('k'), add(int(1), int(2.5)))),
    at: 'root.body.right.right',
  }),
  Object.freeze({
    name: 'deep-free-var-in-sum-body',
    smuggle: 'a sibling FREE variable smuggled beside the bound index, deep in the body',
    expr: sum('k', int(1), int(3), add(variable('k'), variable('j'))),
    at: 'root.body.right',
  }),
  Object.freeze({
    name: 'deep-out-of-scope-index',
    smuggle: 'an inner body referencing an OUTER binder that is not actually in scope',
    expr: sum('i', int(1), int(2), sum('j', int(1), int(3), mul(variable('j'), variable('m')))),
    at: 'root.body.body.right',
  }),
  Object.freeze({
    name: 'deep-call-under-product',
    smuggle: 'an arbitrary function call buried in a product body',
    expr: product('k', int(1), int(3), mul(variable('k'), { type: 'call', fn: 'gamma', args: [variable('k')] })),
    at: 'root.body.right',
  }),
  Object.freeze({
    name: 'deep-limit-under-pow-base',
    smuggle: 'a limit smuggled as a pow base, several levels in',
    expr: add(int(1), pow({ type: 'limit', var: 'n', body: variable('n') }, int(2))),
    at: 'root.right.left',
  }),
  Object.freeze({
    name: 'deep-unbounded-sum-inside-valid-sum',
    smuggle: 'an inner UNBOUNDED sum nested inside an outer bounded sum',
    expr: sum('i', int(1), int(2), sum('j', int(1), { type: 'infinity' }, variable('j'))),
    at: 'root.body.upper',
  }),
  Object.freeze({
    name: 'deep-symbolic-bound-inside-valid-tree',
    smuggle: 'a symbolic bound on a sum nested under arithmetic',
    expr: add(int(10), mul(int(2), sum('k', int(1), variable('N'), variable('k')))),
    at: 'root.right.right.upper',
  }),
  Object.freeze({
    name: 'deep-untyped-node',
    smuggle: 'an untyped object buried as a deep operand',
    expr: add(int(1), mul(int(2), { value: 99 })),
    at: 'root.right.right',
  }),
]);

/**
 * Run the laundering battery through `recognize`. Returns
 *   { total, rejected, accepted, results:[{name, smuggle, inGrammar, reason, path, expectedAt, pathMatched}] }
 * The done-when invariant is `accepted === 0` (every smuggle is denied).
 */
export function runLaunderingBattery(battery = LAUNDERING_BATTERY) {
  const results = battery.map((c) => {
    const rec = recognize(c.expr);
    return {
      name: c.name,
      smuggle: c.smuggle,
      inGrammar: rec.inGrammar,
      reason: rec.reason,
      path: rec.path,
      expectedAt: c.at ?? null,
      pathMatched: c.at == null ? null : rec.path === c.at,
    };
  });
  return {
    total: results.length,
    rejected: results.filter((r) => r.inGrammar === false).length,
    accepted: results.filter((r) => r.inGrammar === true).length,
    results,
  };
}

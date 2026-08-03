// Wave 11 — Firewall builder + anchors + stamps + S4 invariant (B2a).
//
// The SOLVE/UNDERSTAND-adjacent VERIFICATION FIREWALL builder. Wave 10's comprehension protocol
// reads a method's prose into typed sub-claims; for a computational sub-claim, the autonomous tier
// must not simply TRUST the narrative's own arithmetic (that would be propose == adjudicate — THE
// HONESTY LAW forbids it). Instead it BUILDS A FIREWALL around the claim: an INDEPENDENT reference
// computation, a spec, and a battery of reading-independent anchor TESTS, then stamps an HONEST
// warranty derived from how much of that battery actually held.
//
// FOUR deliverables, all default-deny and forward-compatible with the Wave-12 coverage-stamp canary:
//
//   1. prose -> ref-fn + spec + tests.  buildFirewall(narrative) runs the independent reconstruction
//      (prose -> ref-fn — a CLOSED-grammar literal computation re-derived from the reading), then the
//      builder ITSELF produces the spec (claim_id/domain/claimed-quantity/dimension/provenance) and
//      the anchor TESTS (the cross-checks below). The reconstruction is a pluggable step so the
//      planted same-family fixture can launder the narrative's OWN derivation in (S4 catches it).
//
//   2. THE NECESSARY-9 TRUST GATE.  Nine NECESSARY conditions for a firewall to earn full warranty:
//        (1) spec-well-formed   (2) ref-fn-present   (3) ref-fn-in-grammar (closed default-deny)
//        (4) ref-fn-executes-exactly (exact bigint/rational — NO float)   (5) ref-fn-independent  <- S4
//        (6) anchor-available   (7) dimensional-anchor   (8) quoted-number-anchor   (9) closed-form-anchor
//      Each condition is pass / fail / n-a. ANY fail means the firewall is NOT fully trusted; the cap
//      below degrades accordingly. (7)-(9) are n-a when their anchor is unavailable — that reduces
//      COVERAGE (a warranty exclusion) without being a hard fail; an available anchor that is VIOLATED
//      IS a hard fail (the ref-fn actively contradicts a reading-independent invariant => REFUSED).
//
//   3. THE THREE READING-INDEPENDENT ANCHORS + the ANCHOR-AVAILABILITY gate. Each anchor cross-checks
//      the ref-fn against something the reader did NOT author:
//        - dimensional       — the ref-fn's inferred dimension matches the claim's declared dimension.
//        - the paper's OWN quoted numbers — the ref-fn's exact value matches the number the prose
//                              itself quotes (exact rational equality, or relative 1e-9 for a decimal).
//        - closed-form/limit/conservation — the ref-fn agrees with an INDEPENDENT closed-form/limit/
//                              conservation expression (a DISTINCT AST, not the ref-fn's own form).
//      The ANCHOR-AVAILABILITY gate tallies which anchors are available and which hold, yielding
//      anchor_coverage = full | partial | none and the warranty_excludes[] (the anchors NOT covered).
//
//   4. THE STAMPS.  firewall_status, anchor_coverage, warranty_excludes[], reduced_warranty (+ the
//      S4 independence flag and the honest rung_cap). The cap is the strongest rung this firewall may
//      ever earn:
//        - structural fail / a VIOLATED anchor / zero anchors  => firewall_status REFUSED,  cap UNVERIFIED
//        - NOT ref-fn-independent (S4)                          => firewall_status capped-same-family, cap CLAIMED
//        - partial coverage (warranty_excludes[] != [])         => firewall_status reduced-warranty,  cap CLAIMED
//        - all nine hold, full coverage, S4 independent         => firewall_status full-warranty,     cap OBSERVED
//
// THE S4 INVARIANT (this wave's headline; DESCRIPTION §Residuals S4). A firewall ref-fn whose AST
// shares symbol-PROVENANCE with the comprehension narrative is NOT an independent reference — it is
// the same family adjudicating its own claim. S4 default-denies: independence must be PROVABLE (a
// declared, non-empty reconstruction provenance distinct from the narrative's, AND no ref-fn node
// carrying the narrative's provenance tag). Otherwise the firewall caps at CLAIMED (belief
// CONJECTURAL — the single-family ceiling), NEVER OBSERVED/VERIFIED. The done-when: the
// planted-wrong-same-family-reference fixture caps at CLAIMED.
//
// Pure node built-ins + the project's own spine modules (the Wave-8 grammar, the Wave-9 exact
// evaluator + firewall positive path, the Wave-3 ledger). The provenance tag rides as an inert
// `prov` field that the grammar recognizer + the exact evaluator both ignore, so a tagged ref-fn is
// recognized, executed, and re-executed deterministically just like an untagged one. Runs under
// `node --test test/`.

import { RUNG, BELIEF, compareRungs } from './claim-ledger.mjs';
import { recognize, int, mul, variable, sum } from './firewall-grammar.mjs';
import {
  evalExpr,
  settleComputationViaFirewall,
  FIREWALL_DOMAIN,
  FIREWALL_FAMILY,
} from './firewall-subprocess.mjs';
import { VERDICT } from './adjudication.mjs';

// ---------------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------------

/** The firewall warranty status — the honest summary of how much trust the firewall earned. */
export const FIREWALL_STATUS = Object.freeze({
  FULL_WARRANTY: 'full-warranty',        // all nine hold, full anchor coverage, S4 independent.
  REDUCED_WARRANTY: 'reduced-warranty',  // S4 ok but a covered anchor is missing (partial coverage).
  CAPPED_SAME_FAMILY: 'capped-same-family', // S4 failed — the ref-fn is not independent of the reading.
  REFUSED: 'refused',                    // structurally broken / a violated anchor / zero anchors.
});

/** anchor_coverage stamp values. */
export const ANCHOR_COVERAGE = Object.freeze({ FULL: 'full', PARTIAL: 'partial', NONE: 'none' });

/** The three reading-independent anchor names (the stamp/warranty vocabulary). */
export const ANCHOR_NAMES = Object.freeze(['dimensional', 'quoted-number', 'closed-form']);

/** Per-condition status in the NECESSARY-9 gate. */
export const CONDITION_STATUS = Object.freeze({ PASS: 'pass', FAIL: 'fail', NA: 'n/a' });

/** The NECESSARY-9 trust-gate conditions, in order (condition 5 is the S4 invariant). */
export const NECESSARY_9 = Object.freeze([
  'spec-well-formed',
  'ref-fn-present',
  'ref-fn-in-grammar',
  'ref-fn-executes-exactly',
  'ref-fn-independent', // <- S4
  'anchor-available',
  'dimensional-anchor',
  'quoted-number-anchor',
  'closed-form-anchor',
]);

/** Relative tolerance for a DECIMAL quoted-number anchor (DESCRIPTION §Residuals R1: relative 1e-9). */
export const NUMERIC_ANCHOR_REL_TOL = 1e-9;

const { PASS, FAIL, NA } = CONDITION_STATUS;

// ---------------------------------------------------------------------------
// Symbol-provenance: tag + collect (the substrate of the S4 invariant).
//
// A provenance tag is an inert `prov` string stamped on every object node. The Wave-8 grammar
// recognizer + the Wave-9 exact evaluator switch on `type` and read only known children, so a `prov`
// field is ignored by both — a tagged ref-fn is recognized, executed, and re-executed identically.
// ---------------------------------------------------------------------------

/** Deep-clone `node`, stamping `prov` onto every object node (arrays are walked element-wise). */
export function tagProvenance(node, prov) {
  if (node === null || typeof node !== 'object') return node;
  if (Array.isArray(node)) return node.map((n) => tagProvenance(n, prov));
  const out = {};
  for (const [k, v] of Object.entries(node)) out[k] = tagProvenance(v, prov);
  out.prov = prov;
  return out;
}

/** Collect every distinct `prov` tag present anywhere in `node` (into `acc`). */
export function collectProvenance(node, acc = new Set()) {
  if (node === null || typeof node !== 'object') return acc;
  if (Array.isArray(node)) {
    for (const n of node) collectProvenance(n, acc);
    return acc;
  }
  if (typeof node.prov === 'string' && node.prov.length > 0) acc.add(node.prov);
  for (const v of Object.values(node)) collectProvenance(v, acc);
  return acc;
}

// ---------------------------------------------------------------------------
// THE S4 INVARIANT — ref-fn independence by symbol-provenance.
// ---------------------------------------------------------------------------

/**
 * Is the ref-fn an INDEPENDENT reference (shares no symbol-provenance with the comprehension
 * narrative)? Default-deny: independence must be PROVABLE — a declared, non-empty reconstruction
 * provenance DISTINCT from the narrative's family, AND no ref-fn node carrying the narrative's
 * provenance tag. A missing/empty/same-family reconstruction provenance, or any narrative-tagged
 * node smuggled into the ref-fn, fails (=> cap at CLAIMED).
 *
 * @param {string} narrativeProvenance       the comprehension narrative's authoring family.
 * @param {object} refFn                      the reconstructed ref-fn AST (possibly prov-tagged).
 * @param {string} reconstructionProvenance   the declared authoring family of the reconstruction.
 * @returns frozen { independent, narrative_provenance, reconstruction_provenance, ref_provenance[], shared[], reason }
 */
export function s4RefFnIndependence(narrativeProvenance, refFn, reconstructionProvenance) {
  const narrProv = typeof narrativeProvenance === 'string' && narrativeProvenance.length > 0 ? narrativeProvenance : null;
  const refSet = collectProvenance(refFn);
  if (typeof reconstructionProvenance === 'string' && reconstructionProvenance.length > 0) refSet.add(reconstructionProvenance);
  const shared = [...refSet].filter((p) => p === narrProv);

  const hasIndependentProv =
    typeof reconstructionProvenance === 'string' &&
    reconstructionProvenance.length > 0 &&
    reconstructionProvenance !== narrProv;
  const independent = Boolean(narrProv) && hasIndependentProv && shared.length === 0;

  let reason;
  if (!narrProv) {
    reason = 'comprehension narrative carries no provenance tag — independence cannot be established (fail-safe: not independent)';
  } else if (!hasIndependentProv) {
    reason = `reconstruction provenance ${JSON.stringify(reconstructionProvenance)} is missing/empty or equals the narrative family ${JSON.stringify(narrProv)} (a same-family reference — propose == adjudicate)`;
  } else if (shared.length > 0) {
    reason = `ref-fn AST shares symbol-provenance with the comprehension narrative (${JSON.stringify(narrProv)}) — a laundered same-family derivation`;
  } else {
    reason = 'ref-fn provenance is disjoint from the comprehension narrative (an independent reconstruction)';
  }
  return Object.freeze({
    independent,
    narrative_provenance: narrProv,
    reconstruction_provenance: typeof reconstructionProvenance === 'string' ? reconstructionProvenance : null,
    ref_provenance: Object.freeze([...refSet]),
    shared: Object.freeze(shared),
    reason,
  });
}

// ---------------------------------------------------------------------------
// Exact-arithmetic helpers (reuse the ONE Wave-9 evaluator; NO float).
// ---------------------------------------------------------------------------

/** Evaluate the ref-fn to an exact rational { n, d }, or report the throw. */
function evalRef(refFn) {
  try {
    return { ok: true, result: evalExpr(refFn) };
  } catch (e) {
    return { ok: false, error: e && e.message ? e.message : String(e) };
  }
}

/** Exact equality of two reduced rationals { n, d } (d > 0). */
function ratEq(a, b) {
  return a.n * b.d === b.n * a.d;
}

/** Render an exact rational as decimal strings for the stamp/tests. */
function ratStr(r) {
  return { num: r.n.toString(), den: r.d.toString() };
}

/**
 * Does the ref-fn's exact value match the paper's OWN quoted number? Accepts an EXACT rational
 * { num, den } (exact equality) or a DECIMAL (number / string / { decimal }) compared at relative
 * tolerance NUMERIC_ANCHOR_REL_TOL.
 */
function quotedMatches(refResult, quoted) {
  if (quoted && typeof quoted === 'object' && quoted.num !== undefined && quoted.den !== undefined) {
    let num;
    let den;
    try {
      num = BigInt(quoted.num);
      den = BigInt(quoted.den);
    } catch {
      return false;
    }
    if (den === 0n) return false;
    return ratEq(refResult, { n: num, d: den });
  }
  let target;
  if (typeof quoted === 'number') target = quoted;
  else if (typeof quoted === 'string') target = Number(quoted);
  else if (quoted && typeof quoted === 'object' && quoted.decimal !== undefined) target = Number(quoted.decimal);
  else return false;
  if (!Number.isFinite(target)) return false;
  const approx = Number(refResult.n) / Number(refResult.d);
  if (target === 0) return Math.abs(approx) <= NUMERIC_ANCHOR_REL_TOL;
  return Math.abs(approx - target) / Math.abs(target) <= NUMERIC_ANCHOR_REL_TOL;
}

/**
 * The closed-form/limit/conservation anchor: an INDEPENDENT expression (a distinct in-grammar AST,
 * or a pinned expected value) the ref-fn must agree with.
 */
function closedFormMatches(refResult, anchor) {
  if (anchor.expr !== undefined) {
    const rec = recognize(anchor.expr);
    if (!rec.inGrammar) return { holds: false, got: null, note: `closed-form expr is out of grammar: ${rec.reason} [at ${rec.path}]` };
    let cf;
    try {
      cf = evalExpr(anchor.expr);
    } catch (e) {
      return { holds: false, got: null, note: `closed-form expr did not evaluate: ${e && e.message ? e.message : String(e)}` };
    }
    return { holds: ratEq(refResult, cf), got: ratStr(cf), note: null };
  }
  if (anchor.expected !== undefined) {
    return { holds: quotedMatches(refResult, anchor.expected), got: null, note: null };
  }
  return { holds: false, got: null, note: 'closed-form anchor declares neither `expr` nor `expected`' };
}

/** A pure in-grammar literal computation is dimensionless by construction (only numeric literals). */
function inferDimension() {
  return 'dimensionless';
}

// ---------------------------------------------------------------------------
// The three anchors + the ANCHOR-AVAILABILITY gate.
// ---------------------------------------------------------------------------

function evaluateAnchors(narrative, refFn, refEval) {
  const a = narrative.anchors || {};
  const claimed = narrative.claimed || {};
  const out = {};

  // (1) dimensional — the ref-fn's inferred dimension vs the claim's declared dimension.
  {
    const spec = a.dimensional || {};
    const available = spec.available === true;
    let holds = false;
    let got = null;
    let note = null;
    if (available) {
      const expected = spec.expected ?? claimed.dimension ?? 'dimensionless';
      got = inferDimension(refFn);
      holds = got === expected;
      note = holds ? null : `ref-fn dimension ${JSON.stringify(got)} != declared ${JSON.stringify(expected)}`;
    }
    out.dimensional = { name: 'dimensional', available, holds: available && holds, got, note };
  }

  // (2) quoted-number — the ref-fn's exact value vs the paper's OWN quoted number.
  {
    const spec = a.quoted_number || a['quoted-number'] || {};
    const quoted = spec.value ?? claimed.quoted_value;
    const available = spec.available === true && quoted !== undefined && refEval.ok;
    let holds = false;
    let got = null;
    let note = null;
    if (available) {
      got = ratStr(refEval.result);
      holds = quotedMatches(refEval.result, quoted);
      note = holds ? null : `ref-fn value ${got.num}/${got.den} != the paper's quoted ${JSON.stringify(quoted)}`;
    }
    out['quoted-number'] = { name: 'quoted-number', available, holds: available && holds, got, note };
  }

  // (3) closed-form / limit / conservation — vs an INDEPENDENT closed-form expression/value.
  {
    const spec = a.closed_form || a['closed-form'] || {};
    const available = spec.available === true && refEval.ok && (spec.expr !== undefined || spec.expected !== undefined);
    let holds = false;
    let got = null;
    let note = null;
    if (available) {
      const r = closedFormMatches(refEval.result, spec);
      holds = r.holds;
      got = r.got;
      note = r.note || (holds ? null : 'closed-form anchor disagrees with the ref-fn');
    }
    out['closed-form'] = { name: 'closed-form', available, holds: available && holds, got, note };
  }

  return out;
}

/** Tally availability/holding/violation across the three anchors -> coverage + warranty_excludes[]. */
function gateAnchorAvailability(anchors) {
  const holding = ANCHOR_NAMES.filter((n) => anchors[n].holds);
  const available = ANCHOR_NAMES.filter((n) => anchors[n].available);
  const violated = ANCHOR_NAMES.filter((n) => anchors[n].available && !anchors[n].holds);
  // warranty_excludes[] = the reading-independent anchors NOT covered by this warranty.
  const warranty_excludes = ANCHOR_NAMES.filter((n) => !anchors[n].holds);

  let coverage;
  if (holding.length === ANCHOR_NAMES.length) coverage = ANCHOR_COVERAGE.FULL;
  else if (holding.length === 0) coverage = ANCHOR_COVERAGE.NONE;
  else coverage = ANCHOR_COVERAGE.PARTIAL;

  return { coverage, holding, available, violated, warranty_excludes };
}

// ---------------------------------------------------------------------------
// THE NECESSARY-9 TRUST GATE.
// ---------------------------------------------------------------------------

function condition(name, status, detail) {
  return { name, status, detail: detail ?? null };
}

function runNecessary9({ specOk, refPresent, inGrammar, executes, s4, anchorGate, anchors }) {
  const c = [];
  c.push(condition('spec-well-formed', specOk ? PASS : FAIL, specOk ? null : 'spec is missing a required field (claim_id / domain / claimed quantity or dimension / narrative provenance)'));
  c.push(condition('ref-fn-present', refPresent ? PASS : FAIL, refPresent ? null : 'the reconstruction produced no ref-fn AST'));
  c.push(condition('ref-fn-in-grammar', inGrammar.ok ? PASS : FAIL, inGrammar.ok ? null : inGrammar.reason));
  c.push(condition('ref-fn-executes-exactly', executes.ok ? PASS : FAIL, executes.ok ? null : executes.error));
  c.push(condition('ref-fn-independent', s4.independent ? PASS : FAIL, s4.independent ? null : s4.reason)); // S4
  c.push(condition('anchor-available', anchorGate.available.length >= 1 ? PASS : FAIL, anchorGate.available.length >= 1 ? null : 'no reading-independent anchor is available — nothing cross-checks the ref-fn'));
  for (const an of ANCHOR_NAMES) {
    const a = anchors[an];
    const status = !a.available ? NA : a.holds ? PASS : FAIL;
    const condName = `${an === 'quoted-number' ? 'quoted-number' : an}-anchor`;
    c.push(condition(condName, status, status === NA ? 'anchor unavailable (warranty exclusion)' : a.note));
  }
  return c;
}

/** Map the gate + S4 + coverage to the firewall_status + the honest rung_cap. */
function classify(conditions, s4, anchorGate) {
  const fails = conditions.filter((c) => c.status === FAIL).map((c) => c.name);
  const trusted = fails.length === 0;

  // Conditions 1-4 are STRUCTURAL (spec / present / grammar / executes); a fail there means there is
  // nothing safe to settle. A VIOLATED anchor or zero anchors is likewise fatal.
  const structuralFail = conditions.slice(0, 4).some((c) => c.status === FAIL);
  const anchorViolated = anchorGate.violated.length > 0;
  const noAnchors = anchorGate.available.length === 0;

  let firewall_status;
  let rung_cap;
  if (structuralFail || anchorViolated || noAnchors) {
    firewall_status = FIREWALL_STATUS.REFUSED;
    rung_cap = RUNG.UNVERIFIED;
  } else if (!s4.independent) {
    firewall_status = FIREWALL_STATUS.CAPPED_SAME_FAMILY;
    rung_cap = RUNG.CLAIMED;
  } else if (anchorGate.coverage !== ANCHOR_COVERAGE.FULL) {
    firewall_status = FIREWALL_STATUS.REDUCED_WARRANTY;
    rung_cap = RUNG.CLAIMED;
  } else {
    firewall_status = FIREWALL_STATUS.FULL_WARRANTY;
    rung_cap = RUNG.OBSERVED;
  }
  return { trusted, fails, firewall_status, rung_cap };
}

// ---------------------------------------------------------------------------
// THE BUILDER — prose -> ref-fn + spec + tests, then gate + anchors + stamps.
// ---------------------------------------------------------------------------

/** The default reconstruction step: use the independent reconstruction supplied on the narrative. */
function defaultReconstruct(narrative) {
  const r = narrative.reconstruction;
  if (!r || typeof r !== 'object') {
    throw new Error('buildFirewall: narrative.reconstruction { ref_fn, provenance } is required (or pass opts.reconstruct)');
  }
  return { ref_fn: r.ref_fn, provenance: r.provenance };
}

/**
 * BUILD a verification firewall for a comprehension narrative's computational claim.
 *
 * @param {object} narrative  { claim_id, domain?, provenance, text?, symbols?, claimed:{ quoted_value?,
 *                              dimension? }, anchors:{ dimensional?, quoted_number?, closed_form? },
 *                              reconstruction:{ ref_fn, provenance } }
 * @param {{reconstruct?:(narrative)=>{ref_fn:object, provenance:string}}} [opts]
 * @returns frozen FirewallBuild (ref_fn, spec, tests, s4, anchors, stamps, necessary9, rung_cap, ...).
 */
export function buildFirewall(narrative, { reconstruct = defaultReconstruct } = {}) {
  if (!narrative || typeof narrative !== 'object') throw new Error('buildFirewall: narrative must be an object');
  const claim_id = narrative.claim_id;
  if (typeof claim_id !== 'string' || claim_id.length === 0) throw new Error('buildFirewall: narrative.claim_id is required');
  const domain = typeof narrative.domain === 'string' && narrative.domain.length > 0 ? narrative.domain : FIREWALL_DOMAIN;

  // prose -> ref-fn (the INDEPENDENT reconstruction step).
  const reconstruction = reconstruct(narrative) || {};
  const ref_fn = reconstruction.ref_fn !== undefined ? reconstruction.ref_fn : null;
  const refProv = typeof reconstruction.provenance === 'string' ? reconstruction.provenance : null;
  const refPresent = ref_fn !== null && typeof ref_fn === 'object';

  // -> spec (the builder authors it from the narrative + the reconstructed ref-fn).
  const claimed = narrative.claimed || {};
  const spec = Object.freeze({
    claim_id,
    domain,
    claimed_quantity: claimed.quoted_value ?? null,
    dimension: claimed.dimension ?? null,
    narrative_provenance: typeof narrative.provenance === 'string' ? narrative.provenance : null,
    ref_fn_provenance: refProv,
  });
  const specOk =
    claim_id.length > 0 &&
    typeof domain === 'string' && domain.length > 0 &&
    (claimed.dimension !== undefined || claimed.quoted_value !== undefined) &&
    typeof narrative.provenance === 'string' && narrative.provenance.length > 0;

  // grammar front-end + exact execution.
  const rec = refPresent ? recognize(ref_fn) : { inGrammar: false, reason: 'no ref-fn produced', path: null };
  const inGrammar = { ok: Boolean(rec.inGrammar), reason: rec.inGrammar ? null : `${rec.reason} [at ${rec.path}]` };
  const refEval = refPresent && inGrammar.ok ? evalRef(ref_fn) : { ok: false, error: inGrammar.reason || 'ref-fn absent/out-of-grammar' };

  // S4 — the ref-fn-independence invariant.
  const s4 = s4RefFnIndependence(narrative.provenance, ref_fn, refProv);

  // the three anchors + the ANCHOR-AVAILABILITY gate.
  const anchors = evaluateAnchors(narrative, ref_fn, refEval);
  const anchorGate = gateAnchorAvailability(anchors);

  // -> tests (the reading-independent anchor cross-checks the firewall built + ran).
  const tests = Object.freeze(ANCHOR_NAMES.map((n) => Object.freeze({ anchor: n, ...anchors[n] })));

  // the NECESSARY-9 trust gate + classification.
  const conditions = runNecessary9({ specOk, refPresent, inGrammar, executes: refEval, s4, anchorGate, anchors });
  const { trusted, fails, firewall_status, rung_cap } = classify(conditions, s4, anchorGate);

  const stamps = Object.freeze({
    firewall_status,
    anchor_coverage: anchorGate.coverage,
    warranty_excludes: Object.freeze([...anchorGate.warranty_excludes]),
    reduced_warranty: anchorGate.coverage === ANCHOR_COVERAGE.PARTIAL,
    s4_independent: s4.independent,
    rung_cap,
  });

  return Object.freeze({
    claim_id,
    domain,
    ref_fn,
    spec,
    tests,
    s4,
    anchors: Object.freeze(anchors),
    anchor_coverage: anchorGate.coverage,
    warranty_excludes: stamps.warranty_excludes,
    reduced_warranty: stamps.reduced_warranty,
    necessary9: Object.freeze(conditions.map((c) => Object.freeze(c))),
    trust: Object.freeze({ trusted, fails: Object.freeze(fails) }),
    firewall_status,
    rung_cap,
    stamps,
  });
}

// ---------------------------------------------------------------------------
// Realize the firewall's cap on the shared A1 ledger.
// ---------------------------------------------------------------------------

function frozenVerdict(verdict, ledger, claim_id, reason, build, extra = {}) {
  const snap = ledger.get(claim_id);
  return Object.freeze({
    verdict,
    claim_id,
    rung: snap.rung,
    belief: snap.belief,
    firewall_status: build.firewall_status,
    rung_cap: build.rung_cap,
    anchor_coverage: build.anchor_coverage,
    warranty_excludes: build.warranty_excludes,
    reduced_warranty: build.reduced_warranty,
    s4_independent: build.s4.independent,
    reason,
    ...extra,
  });
}

/**
 * Realize a firewall build's honest cap on a shared A1 ledger (the claim is asserted at the floor if
 * absent). The cap is the CEILING the firewall earned — never exceeded:
 *   - OBSERVED  : run the Wave-9 firewall positive path (mint + adjudicate) -> OBSERVED/VERIFIED. With
 *                 NO dispatcher present it honestly ABSTAINs at UNVERIFIED (the no-minter arm).
 *   - CLAIMED   : promote to CLAIMED (belief CONJECTURAL) — the single-family / reduced-warranty ceiling.
 *                 NEVER OBSERVED. (Sticky: an already-higher rung is held.)
 *   - UNVERIFIED: REFUSED — leave at the floor and route out-of-model.
 *
 * @returns frozen verdict { verdict, rung, belief, firewall_status, rung_cap, ... }.
 */
export function applyFirewallCap(build, ledger, { dispatcher = null } = {}) {
  if (!build || typeof build !== 'object') throw new Error('applyFirewallCap: a firewall build is required');
  if (!ledger || typeof ledger.assert !== 'function' || typeof ledger.promote !== 'function') {
    throw new Error('applyFirewallCap: an A1 ClaimLedger is required');
  }
  const { claim_id, domain, ref_fn, rung_cap } = build;
  if (!ledger.has(claim_id)) ledger.assert({ id: claim_id, type: 'computational', statement: build.spec?.narrative_provenance ? '' : '' });

  if (rung_cap === RUNG.OBSERVED) {
    if (!dispatcher) {
      return frozenVerdict('ABSTAIN', ledger, claim_id, 'firewall earned full warranty, but no out-of-model dispatcher is present — cannot settle (honest no-minter arm)', build);
    }
    const settle = settleComputationViaFirewall(ledger, dispatcher, claim_id, ref_fn, { domain });
    const settled = settle.verdict === VERDICT.VERIFIED;
    return frozenVerdict(settled ? 'VERIFIED' : 'ABSTAIN', ledger, claim_id, settle.reason || 'firewall positive path', build, {
      artifact_backed: settled,
      family: settle.family || null,
      reexecutes: settle.reexecutes,
    });
  }

  if (rung_cap === RUNG.CLAIMED) {
    if (compareRungs(ledger.rungOf(claim_id), RUNG.CLAIMED) < 0) {
      ledger.promote(claim_id, RUNG.CLAIMED, {
        family: null,
        reason: build.s4.independent
          ? `firewall ${build.firewall_status} — reduced anchor coverage (${build.warranty_excludes.join(', ')}); capped at CLAIMED`
          : 'firewall ref-fn is not independent of the comprehension narrative (S4) — same-family reference; capped at CLAIMED',
        by: 'firewall-builder',
      });
    }
    return frozenVerdict('CAPPED', ledger, claim_id, `capped at CLAIMED (${build.firewall_status})`, build);
  }

  // REFUSED — leave the claim at the floor (UNVERIFIED) and route out-of-model.
  return frozenVerdict('REFUSED', ledger, claim_id, `firewall refused: ${build.trust.fails.join('; ') || 'no anchor / structural fault'}`, build);
}

// ---------------------------------------------------------------------------
// FIXTURES — a genuine firewall + the planted same-family reference (the done-when), plus the
// reduced-warranty / anchor-violation / out-of-grammar / no-anchor cases that exercise the stamps,
// the ANCHOR-AVAILABILITY gate, and the NECESSARY-9 trust gate.
// ---------------------------------------------------------------------------

/** The comprehension narrative's authoring family (the same family that read the paper). */
export const NARRATIVE_PROVENANCE = 'comprehension-narrative';
/** An INDEPENDENT reconstruction's authoring family (a different provenance — the firewall's). */
export const REFERENCE_PROVENANCE = 'reference-reconstruction';

// The ref computation: S = sum_{k=1}^{3} (k * 2) = 2 + 4 + 6 = 12 — a bounded sum of products.
const refSumTagged = (prov) => tagProvenance(sum('k', int(1), int(3), mul(variable('k'), int(2))), prov);
// An INDEPENDENT closed form for the same value: n*(n+1) at n = 3 = 3*4 = 12 (a DISTINCT AST).
const CLOSED_FORM_12 = mul(int(3), int(4));

/** A GENUINE firewall: an independent ref-fn, all three anchors available + holding => OBSERVED cap. */
export const GENUINE_NARRATIVE = Object.freeze({
  claim_id: 'fb::partial-sum-equals-12',
  domain: FIREWALL_DOMAIN,
  provenance: NARRATIVE_PROVENANCE,
  text: 'The partial sum S = sum_{k=1}^{3} (k * 2) equals 12.',
  symbols: Object.freeze(['S', 'k']),
  claimed: Object.freeze({ quoted_value: Object.freeze({ num: '12', den: '1' }), dimension: 'dimensionless' }),
  anchors: Object.freeze({
    dimensional: Object.freeze({ available: true, expected: 'dimensionless' }),
    quoted_number: Object.freeze({ available: true }),
    closed_form: Object.freeze({ available: true, expr: CLOSED_FORM_12, kind: 'closed-form' }),
  }),
  reconstruction: Object.freeze({ ref_fn: refSumTagged(REFERENCE_PROVENANCE), provenance: REFERENCE_PROVENANCE }),
});

/**
 * THE DONE-WHEN FIXTURE: a ref-fn whose AST shares symbol-provenance with the comprehension narrative
 * (the same-family reference). Everything else is identical to GENUINE — all anchors hold, full
 * coverage — so the ONLY reason the cap drops is S4. It MUST cap at CLAIMED (never OBSERVED).
 */
export const PLANTED_SAME_FAMILY_NARRATIVE = Object.freeze({
  ...GENUINE_NARRATIVE,
  claim_id: 'fb::partial-sum-equals-12::same-family',
  reconstruction: Object.freeze({ ref_fn: refSumTagged(NARRATIVE_PROVENANCE), provenance: NARRATIVE_PROVENANCE }),
});

/** Reduced warranty: an independent ref-fn but the closed-form anchor is unavailable => partial => CLAIMED. */
export const REDUCED_WARRANTY_NARRATIVE = Object.freeze({
  ...GENUINE_NARRATIVE,
  claim_id: 'fb::partial-sum-equals-12::reduced',
  anchors: Object.freeze({
    dimensional: Object.freeze({ available: true, expected: 'dimensionless' }),
    quoted_number: Object.freeze({ available: true }),
    closed_form: Object.freeze({ available: false }),
  }),
});

/** A VIOLATED dimensional anchor (the claim declares a dimension the dimensionless ref-fn can't match) => REFUSED. */
export const ANCHOR_VIOLATION_NARRATIVE = Object.freeze({
  ...GENUINE_NARRATIVE,
  claim_id: 'fb::dim-violation',
  claimed: Object.freeze({ quoted_value: Object.freeze({ num: '12', den: '1' }), dimension: 'length' }),
  anchors: Object.freeze({
    dimensional: Object.freeze({ available: true, expected: 'length' }),
    quoted_number: Object.freeze({ available: true }),
    closed_form: Object.freeze({ available: true, expr: CLOSED_FORM_12 }),
  }),
});

/** The ref-fn disagrees with the paper's OWN quoted number (12 != 13) => quoted-number violated => REFUSED. */
export const QUOTED_MISMATCH_NARRATIVE = Object.freeze({
  ...GENUINE_NARRATIVE,
  claim_id: 'fb::quoted-mismatch',
  claimed: Object.freeze({ quoted_value: Object.freeze({ num: '13', den: '1' }), dimension: 'dimensionless' }),
});

/** An out-of-grammar ref-fn (a non-literal limit) => ref-fn-in-grammar FAILS => REFUSED. */
export const OUT_OF_GRAMMAR_REF_NARRATIVE = Object.freeze({
  ...GENUINE_NARRATIVE,
  claim_id: 'fb::out-of-grammar',
  reconstruction: Object.freeze({
    ref_fn: tagProvenance({ type: 'limit', var: 'n', to: 'infinity', body: variable('n') }, REFERENCE_PROVENANCE),
    provenance: REFERENCE_PROVENANCE,
  }),
});

/** No anchor available at all => the ANCHOR-AVAILABILITY gate refuses (nothing cross-checks) => REFUSED. */
export const NO_ANCHORS_NARRATIVE = Object.freeze({
  ...GENUINE_NARRATIVE,
  claim_id: 'fb::no-anchors',
  anchors: Object.freeze({
    dimensional: Object.freeze({ available: false }),
    quoted_number: Object.freeze({ available: false }),
    closed_form: Object.freeze({ available: false }),
  }),
});

/** The labelled fixture set (for a one-call sweep). */
export const FIREWALL_FIXTURES = Object.freeze([
  Object.freeze({ label: 'genuine', expect_status: FIREWALL_STATUS.FULL_WARRANTY, expect_cap: RUNG.OBSERVED, narrative: GENUINE_NARRATIVE }),
  Object.freeze({ label: 'planted-same-family', expect_status: FIREWALL_STATUS.CAPPED_SAME_FAMILY, expect_cap: RUNG.CLAIMED, narrative: PLANTED_SAME_FAMILY_NARRATIVE }),
  Object.freeze({ label: 'reduced-warranty', expect_status: FIREWALL_STATUS.REDUCED_WARRANTY, expect_cap: RUNG.CLAIMED, narrative: REDUCED_WARRANTY_NARRATIVE }),
  Object.freeze({ label: 'dimensional-violation', expect_status: FIREWALL_STATUS.REFUSED, expect_cap: RUNG.UNVERIFIED, narrative: ANCHOR_VIOLATION_NARRATIVE }),
  Object.freeze({ label: 'quoted-mismatch', expect_status: FIREWALL_STATUS.REFUSED, expect_cap: RUNG.UNVERIFIED, narrative: QUOTED_MISMATCH_NARRATIVE }),
  Object.freeze({ label: 'out-of-grammar', expect_status: FIREWALL_STATUS.REFUSED, expect_cap: RUNG.UNVERIFIED, narrative: OUT_OF_GRAMMAR_REF_NARRATIVE }),
  Object.freeze({ label: 'no-anchors', expect_status: FIREWALL_STATUS.REFUSED, expect_cap: RUNG.UNVERIFIED, narrative: NO_ANCHORS_NARRATIVE }),
]);

/** Build every fixture firewall and pair it with its expectation. */
export function buildFixtureFirewalls(opts = {}) {
  return FIREWALL_FIXTURES.map((f) => Object.freeze({ ...f, build: buildFirewall(f.narrative, opts) }));
}

// Re-exported so tests + later pillars can branch on the rung/belief vocabulary without a second import.
export { RUNG, BELIEF };

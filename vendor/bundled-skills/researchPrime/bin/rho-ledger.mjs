// bin/rho-ledger.mjs — Wave 9 ρ-CALIBRATION LEDGER + LEARNED QUORUM (NEW per v6; MONOTONE-SAFE).
//
// MASTER-PLAN crit-7 / I8 · IMPLEMENTATION-PLAN Wave 9: the cross-run learning layer that estimates
// reviewer-error correlation (ρ̂) from a PERSISTENT ledger and feeds it to the quorum — where, by the
// Wave-2 safety contract, it may only ever TIGHTEN the bar, never loosen it below the static ≥2 floor.
//
// ── Why this wave is GATED behind Waves 6–8 ────────────────────────────────────────────────────────
// The learning layer sits ON TOP of the floor it learns from: you cannot learn a correlation among
// reviewers until the evidenced core (Wave 6), the round loop (Wave 7) and the governor (Wave 8) exist
// to produce the catch/miss events the ledger records. So Wave 9 is the last behavioral layer, and it
// adds the LEARNED tightening WITHOUT being able to weaken the static guarantees underneath it.
//
// ── The two numbers, and the one place each is computed (REUSE, not fork) ───────────────────────────
// This module NEVER re-implements either half of the quorum decision:
//   • origins present  → `countIndependentOrigins` (the Wave-2 shared module — the sole origin counter).
//   • origins required → `requiredQuorum(ρ̂)` (the Wave-2 shared module — the sole ρ̂→quorum map, which is
//     MONOTONE-TIGHTEN-ONLY by construction: ≥ the static floor for EVERY ρ̂, lowering the floor itself
//     is a reserved human code change).
// Wave 9 owns ONLY: (1) the persistent ledger that accumulates the events, (2) the ρ̂ ESTIMATOR over
// those events, (3) the cold-start N_min gate, and (4) the I8 reproducibility stamping. The honesty
// guarantee (a learned ρ̂ can only raise the bar) is therefore enforced in ONE place — the shared
// module — and Wave 9 cannot route around it.
//
// ── A5: ρ̂ is a CENSORED LOWER BOUND ─────────────────────────────────────────────────────────────────
// Co-miss events are only observable on defects the loop EVENTUALLY caught (via a cross-lineage origin
// or the fixture answer key); defects that every lineage missed and were never discovered are invisible,
// so the observed co-miss rate UNDER-counts the true one. ρ̂ is therefore a right-censored LOWER bound on
// the true correlation, and is stamped as such in every run output (done-when d). Loosening the quorum on
// a lower bound would chase the censoring bias — which is exactly why the shared module forbids loosening.
//
// ── Calibration vs the live ledger (the honesty line, done-when b) ──────────────────────────────────
// The estimator's ARITHMETIC round-trip (recovering a seeded ρ from synthetic counts within tolerance T)
// only proves the estimator inverts its own definition. It does NOT validate ρ̂ against real reviewer
// correlation. The real calibration target is the planted-CBS fixture's KNOWN co-miss events (FIXTURE-SPEC
// §2), never the live ledger's self-reported catches (A5: the ledger's own catches are exactly the
// censored, optimistic quantity ρ̂ must not be calibrated against).
//
// PURITY: every compute function here is a deterministic, side-effect-free function of its inputs (no
// clock, no randomness). The ONLY I/O is `loadLedger` / `saveLedger` (the cross-run persistence) — kept
// in named helpers so the rest stays a pure, replayable function of (inputs + ledger), which is what the
// I8 reproducibility guarantee (done-when e) rests on.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// The SOLE origin counter and the SOLE ρ̂→quorum map (Wave 2). Wave 9 routes both numbers through here
// and computes neither itself — so the monotone-tighten-only safety contract cannot be bypassed.
import {
  requiredQuorum,
  countIndependentOrigins,
  meetsQuorum,
  STATIC_QUORUM_FLOOR,
  lineageOf,
} from '#trio-core/independence-accounting.mjs';
// HALT-for-human signalling — the single upstream class, via the canonical trio-core specifier (no fork).
import { HaltError } from '#trio-core/contract-core.mjs';
// REUSE the baseline's canonical-JSON hash for the I8 ledger hash — one content-hash routine across the
// engine, not a second fork of canonicalize/sha256.
import { canonicalize, sha256Hex } from './baseline.mjs';
// The committed N_min / T come from the Wave-1 pre-registration (I6: the gate cannot be gamed by a
// locally-chosen sample floor or tolerance).
import { loadPreregistration } from './preregistration.mjs';

/** Default on-disk location of the persistent cross-run ρ-calibration ledger. */
export const RHO_LEDGER_FILE = new URL('../ledger/rho-calibration.json', import.meta.url);

/** Bump when the on-disk ledger shape changes (cross-run compatibility guard). */
export const LEDGER_SCHEMA_VERSION = 1;

/** The two ledger event kinds (done-when a: "co-miss vs independent-catch events"). */
export const EVENT_KINDS = Object.freeze(['co-miss', 'independent-catch']);

/** ρ̂ is a right-censored LOWER bound on the true reviewer-error correlation (A5, done-when d). */
export const RHO_CENSORED_STAMP =
  'ρ̂ is a CENSORED LOWER BOUND on the true reviewer-error correlation (A5): co-misses are observable ' +
  'only on defects eventually caught, so the observed rate under-counts the true one — ρ̂ may only TIGHTEN ' +
  'the quorum, never loosen it';

/** The stamp a run wears when there are too few samples to estimate ρ̂ (cold start, crit-7). */
export const RHO_UNESTIMATED_STAMP = 'ρ unestimated (n<N_min)';

/**
 * The overhead the learning layer is allowed to add (done-when: "added overhead ≤ a stated bound").
 *
 * Stated as a DETERMINISTIC, structural bound rather than a wall-clock number — wall-clock is flaky on a
 * loaded CI and would make the gate non-reproducible, the opposite of what Wave 9 (I8 reproducibility)
 * stands for. The load-bearing fact is that the learning layer fires ZERO sub-agents (it is pure
 * arithmetic over a small persisted JSON) and touches the ledger at most once per run each way. That is
 * the cost that actually matters (LLM calls), and it is asserted to be zero.
 */
export const LEARNED_QUORUM_OVERHEAD = Object.freeze({
  maxAgentCalls: 0, // the learning layer invokes NO sub-agent — it is pure arithmetic + small file IO
  maxLedgerReads: 1, // at most one ledger read per run
  maxLedgerWrites: 1, // at most one ledger append/write per run
});

// ── Pre-registered calibration thresholds (committed in Wave 1; read, never re-declared) ────────────
/**
 * The Wave-9 calibration thresholds the estimator + tests read from the committed pre-registration
 * (preregistration.json), mirroring how round.mjs reads N/K/M — reading them HERE (never choosing a
 * number locally) keeps the gate honest (I6).
 *   • N_min — the minimum informative-sample count below which ρ̂ is NOT estimated (cold-start floor).
 *   • T     — the estimator round-trip tolerance (the arithmetic round-trip must land within ±T).
 * @returns {{ N_min:number, T:number }}
 */
export function calibrationThresholds(prereg = loadPreregistration()) {
  const N_min = prereg?.N_min;
  const T = prereg?.T;
  if (!Number.isInteger(N_min) || N_min < 1) {
    throw new HaltError(
      `ρ-calibration needs the committed N_min (Wave-1 preregistration). Got ${JSON.stringify(N_min)} — ` +
        `commit it before learning a quorum (I6).`,
    );
  }
  if (typeof T !== 'number' || !Number.isFinite(T) || T <= 0 || T > 1) {
    throw new HaltError(
      `ρ-calibration needs the committed round-trip tolerance T in (0,1] (Wave-1 preregistration). ` +
        `Got ${JSON.stringify(T)} — commit it before learning a quorum (I6).`,
    );
  }
  return { N_min, T };
}

// ── The ledger data model (per-lineage-pair co-miss vs independent-catch counts) ────────────────────
/** A pair key that is INVARIANT to lineage order ({a,b} === {b,a}); a same-lineage pair is rejected. */
export function pairKey(a, b) {
  const x = typeof a === 'string' ? a.trim() : '';
  const y = typeof b === 'string' ? b.trim() : '';
  if (!x || !y) throw new HaltError('pairKey requires two non-empty lineage names');
  if (x === y) throw new HaltError(`pairKey requires two DISTINCT lineages — a same-lineage pair (${x}) carries no independence signal`);
  return [x, y].sort().join(' '); // NUL join: unambiguous even if a lineage name contains a delimiter char
}

/** A fresh, empty ledger (a pure value — no I/O). */
export function emptyLedger() {
  return { schema_version: LEDGER_SCHEMA_VERSION, pairs: {} };
}

/**
 * Append ONE event to the ledger, in place, returning it. An event is a `{ lineages:[a,b], kind }`
 * where `kind` is 'co-miss' (both lineages missed a defect — correlated failure) or 'independent-catch'
 * (exactly one caught what the other missed — independence manifested). These are the two event types
 * the ledger accumulates across runs (done-when a).
 */
export function appendEvent(ledger, { lineages, kind } = {}) {
  if (!ledger || typeof ledger !== 'object' || !ledger.pairs) {
    throw new HaltError('appendEvent requires a ledger object (use emptyLedger() / loadLedger())');
  }
  if (!Array.isArray(lineages) || lineages.length !== 2) {
    throw new HaltError('appendEvent requires lineages:[a,b] (two distinct lineages)');
  }
  if (!EVENT_KINDS.includes(kind)) {
    throw new HaltError(`appendEvent: kind must be one of ${EVENT_KINDS.join(' | ')}, got ${JSON.stringify(kind)}`);
  }
  const key = pairKey(lineages[0], lineages[1]);
  const rec = ledger.pairs[key] ?? { co_miss: 0, independent_catch: 0 };
  if (kind === 'co-miss') rec.co_miss += 1;
  else rec.independent_catch += 1;
  ledger.pairs[key] = rec;
  return ledger;
}

/**
 * Derive the ledger events of ONE run from its per-defect observations and append them.
 *
 * Each observation is `{ defectId, byLineage:{ <lineage>:'catch'|'miss', ... } }`. For every UNORDERED
 * pair of lineages that examined the defect:
 *   • both missed                  → a 'co-miss' event (the correlated-failure signal).
 *   • exactly one caught the other → an 'independent-catch' event (independence manifested).
 *   • both caught                  → SKIPPED — two catches say nothing about error correlation.
 * This is the bridge from a Wave-6/7/8 round's outcomes to the cross-run ledger; the "two simulated
 * runs" of done-when (a) call it once each, persisting + reloading + appending between them.
 *
 * @returns {ledger} the same ledger, mutated.
 */
export function recordRun(ledger, observations = []) {
  if (!Array.isArray(observations)) throw new HaltError('recordRun requires an observations[] array');
  for (const obs of observations) {
    const by = obs && typeof obs.byLineage === 'object' && obs.byLineage ? obs.byLineage : {};
    const lineages = Object.keys(by).filter((l) => typeof l === 'string' && l.trim().length > 0);
    for (let i = 0; i < lineages.length; i++) {
      for (let j = i + 1; j < lineages.length; j++) {
        const a = lineages[i];
        const b = lineages[j];
        const aMiss = by[a] === 'miss';
        const bMiss = by[b] === 'miss';
        const aCatch = by[a] === 'catch';
        const bCatch = by[b] === 'catch';
        if (aMiss && bMiss) appendEvent(ledger, { lineages: [a, b], kind: 'co-miss' });
        else if ((aMiss && bCatch) || (aCatch && bMiss)) appendEvent(ledger, { lineages: [a, b], kind: 'independent-catch' });
        // both catch (or any unknown verdict) → not an informative correlation event → skipped.
      }
    }
  }
  return ledger;
}

// ── Persistence (the ONLY I/O; ENOENT ⇒ empty, corruption ⇒ surfaced) ───────────────────────────────
/**
 * Load the persistent ledger. An ABSENT file means "nothing learned yet" → an empty ledger (the
 * cold-start state). A file that is PRESENT but unreadable/malformed is corruption, NOT an empty
 * ledger — surfaced loudly (same discipline as bin/preregistration.mjs), so a broken ledger can never
 * silently read as a clean cold start and fabricate a fallback.
 */
export function loadLedger(file = RHO_LEDGER_FILE) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (err) {
    if (err && err.code === 'ENOENT') return emptyLedger();
    throw err;
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new Error(`ρ-calibration ledger is present but is not valid JSON (${file}): ${err.message}`);
  }
  if (!parsed || typeof parsed !== 'object' || typeof parsed.pairs !== 'object' || !parsed.pairs) {
    throw new Error(`ρ-calibration ledger has an unexpected shape (${file}) — expected { pairs: {...} }`);
  }
  return parsed;
}

/** Persist the ledger durably (parent dir created on demand). */
export function saveLedger(ledger, file = RHO_LEDGER_FILE) {
  const p = file instanceof URL ? fileURLToPath(file) : file;
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(ledger, null, 2) + '\n');
  return p;
}

/** The I8 content hash of a ledger: sha256 of its canonical (key-sorted) JSON (reused from baseline). */
export function ledgerHash(ledger) {
  return sha256Hex(canonicalize(ledger));
}

// ── The ρ̂ ESTIMATOR (pure arithmetic over the ledger; cold-start safe) ──────────────────────────────
/**
 * Estimate ρ̂ from the ledger's pooled co-miss vs independent-catch counts.
 *
 * ρ̂ = Σ co_miss / (Σ co_miss + Σ independent_catch), pooled across all lineage pairs; n is that
 * denominator (the count of INFORMATIVE events — those where at least one lineage erred). The estimate
 * is a fraction in [0,1]: at ρ̂→0 nearly every miss is independently caught (origins really are
 * independent); at ρ̂→1 misses co-occur (a shared blind spot). This is the quantity the round-trip check
 * (done-when b) inverts arithmetically.
 *
 * COLD START (crit-7): with n < N_min (or none), ρ̂ is NOT estimated — `{ rhoHat:null, estimated:false }`
 * with the "ρ unestimated (n<N_min)" stamp. The layer NEVER fabricates a ρ̂ from too-few samples; the
 * caller falls back to the static ≥2 rule.
 *
 * @param {object} ledger
 * @param {object} [o]
 * @param {number} [o.N_min]  the committed cold-start floor (default: read from pre-registration)
 * @returns {{ rhoHat:?number, n:number, coMiss:number, independentCatch:number, estimated:boolean, reason:?string, kind:?string, stamp:?string, byPair:object }}
 */
export function estimateRho(ledger, { N_min = calibrationThresholds().N_min } = {}) {
  if (!ledger || typeof ledger !== 'object' || !ledger.pairs) {
    throw new HaltError('estimateRho requires a ledger object (use emptyLedger() / loadLedger())');
  }
  let coMiss = 0;
  let independentCatch = 0;
  const byPair = {};
  for (const [key, rec] of Object.entries(ledger.pairs)) {
    const cm = Number.isFinite(rec?.co_miss) ? rec.co_miss : 0;
    const ic = Number.isFinite(rec?.independent_catch) ? rec.independent_catch : 0;
    coMiss += cm;
    independentCatch += ic;
    const pn = cm + ic;
    byPair[key] = { co_miss: cm, independent_catch: ic, n: pn, rhoHat: pn === 0 ? null : cm / pn };
  }
  const n = coMiss + independentCatch;

  if (n < N_min) {
    // Cold start: too few informative samples to estimate honestly — fall back, never fabricate.
    return {
      rhoHat: null,
      n,
      coMiss,
      independentCatch,
      estimated: false,
      reason: RHO_UNESTIMATED_STAMP,
      kind: null,
      stamp: RHO_UNESTIMATED_STAMP,
      byPair,
    };
  }
  return {
    rhoHat: coMiss / n,
    n,
    coMiss,
    independentCatch,
    estimated: true,
    reason: null,
    kind: 'censored-lower-bound',
    stamp: RHO_CENSORED_STAMP,
    byPair,
  };
}

// ── The LEARNED QUORUM (ρ̂ → required origins, MONOTONE-TIGHTEN-ONLY via the shared module) ──────────
/**
 * The learned origins-required for a set of reviewers, given the ledger. ρ̂ is estimated (or cold-start
 * null), then routed through the shared module's `requiredQuorum` — the SOLE place ρ̂ becomes a number of
 * origins, and it is monotone-tighten-only by construction (≥ the static floor for EVERY ρ̂, including a
 * null/NaN/out-of-range one). Wave 9 NEVER computes the required count itself.
 *
 * @returns {{ origins:number, required:number, staticRequired:number, met:boolean, rho:object }}
 *   `required` is the LEARNED (possibly tightened) bar; `staticRequired` is what the static ≥2 rule alone
 *   would have demanded (always the floor) — the I8 "what the static rule would have required" stamp.
 */
export function learnedQuorum(reviewers = [], { ledger = emptyLedger(), N_min, staticFloor = STATIC_QUORUM_FLOOR, attestedLineages = null } = {}) {
  const rho = estimateRho(ledger, N_min != null ? { N_min } : undefined);
  const origins = countIndependentOrigins(reviewers, { attestedLineages });
  // THE SOLE ρ̂→quorum MAP: the shared module. A null (cold-start) ρ̂ degrades to the static floor there.
  const required = requiredQuorum(rho.rhoHat, staticFloor);
  const staticRequired = requiredQuorum(null, staticFloor); // == the static floor (the baseline bar)
  return { origins, required, staticRequired, met: origins >= required, rho };
}

// ── The CALIBRATION VERDICT (I8 reproducible; default mode = pure function of inputs) ────────────────
/**
 * Produce ONE run's calibration verdict, with the I8 reproducibility stamp.
 *
 * DEFAULT MODE (`useLedger:false`): the ledger is DISABLED — ρ̂ is never read, the required quorum is the
 * static floor, and the verdict is a PURE function of the inputs (the reviewers). No file is touched.
 * This is the honest default the deliverable runs in unless the learning layer is explicitly enabled.
 *
 * LEDGER MODE (`useLedger:true`): ρ̂ is estimated from the supplied ledger and may TIGHTEN the bar. The
 * verdict carries the I8 stamps — the ledger hash, the derived (learned) threshold, and what the static
 * rule would have required — so a replay with the SAME (inputs + ledger) yields a byte-identical verdict
 * (the ledger hash binds the ledger into the replay key), and the censored-lower-bound stamp (A5/d).
 *
 * NB: this is PURE — it takes an already-loaded `ledger` object and performs NO I/O, so it is trivially
 * replayable. The I/O (loading the ledger, counting the overhead) lives in `runCalibration` below.
 *
 * @param {object} o
 * @param {Array<object>} o.reviewers                lineage-tagged reviewers
 * @param {boolean}       [o.useLedger=false]        enable the learned (ledger) quorum
 * @param {object}        [o.ledger]                 the loaded ledger (required iff useLedger)
 * @param {number}        [o.N_min]                  cold-start floor (default: pre-registration)
 * @param {number}        [o.staticFloor]
 * @param {?Iterable<string>} [o.attestedLineages]
 * @returns {object} the verdict + I8 stamps
 */
export function calibrationVerdict({ reviewers = [], useLedger = false, ledger = null, N_min, staticFloor = STATIC_QUORUM_FLOOR, attestedLineages = null } = {}) {
  if (!Array.isArray(reviewers)) throw new HaltError('calibrationVerdict requires a reviewers[] array');

  if (!useLedger) {
    // Default mode: ledger DISABLED ⇒ pure function of inputs. ρ̂ is not consulted; the static floor rules.
    const origins = countIndependentOrigins(reviewers, { attestedLineages });
    const required = requiredQuorum(null, staticFloor); // == static floor
    return {
      mode: 'default',
      ledger_used: false,
      origins,
      required,
      static_would_require: required,
      met: origins >= required,
      rho_hat: null,
      rho_hat_kind: null,
      ledger_hash: null,
      stamp: 'ledger DISABLED — quorum is the static ≥' + staticFloor + ' rule, a pure function of inputs',
    };
  }

  if (!ledger || typeof ledger !== 'object' || !ledger.pairs) {
    throw new HaltError('calibrationVerdict: useLedger:true requires a loaded ledger object');
  }
  const lq = learnedQuorum(reviewers, { ledger, N_min, staticFloor, attestedLineages });
  return {
    mode: 'ledger',
    ledger_used: true,
    origins: lq.origins,
    required: lq.required, // the LEARNED (possibly tightened) bar
    static_would_require: lq.staticRequired, // what the static rule alone would have required (I8 stamp)
    met: lq.met,
    rho_hat: lq.rho.rhoHat,
    rho_hat_kind: lq.rho.kind, // 'censored-lower-bound' (d), or null at cold start
    rho_n: lq.rho.n,
    estimated: lq.rho.estimated,
    ledger_hash: ledgerHash(ledger), // I8: binds the exact ledger into the replay key
    stamp: lq.rho.stamp, // censored-lower-bound (A5/d) OR "ρ unestimated (n<N_min)" (crit-7) at cold start
  };
}

/**
 * Run ONE calibration over a ledger LOADED FROM DISK, measuring the learning layer's overhead.
 *
 * This is the I/O wrapper around `calibrationVerdict`: in ledger mode it reads the persistent ledger
 * exactly once (and writes zero times — reading does not mutate it); in default mode it touches no file
 * at all. The returned `overhead` proves the done-when bound — the learning layer fires ZERO sub-agents
 * and performs at most one ledger read/write per run (LEARNED_QUORUM_OVERHEAD).
 *
 * @param {object} o
 * @param {Array<object>} o.reviewers
 * @param {boolean}  [o.useLedger=false]
 * @param {string|URL} [o.ledgerFile=RHO_LEDGER_FILE]
 * @param {number}   [o.N_min]
 * @param {number}   [o.staticFloor]
 * @param {?Iterable<string>} [o.attestedLineages]
 * @returns {{ verdict:object, overhead:{ agentCalls:number, ledgerReads:number, ledgerWrites:number } }}
 */
export function runCalibration({ reviewers = [], useLedger = false, ledgerFile = RHO_LEDGER_FILE, N_min, staticFloor = STATIC_QUORUM_FLOOR, attestedLineages = null } = {}) {
  const overhead = { agentCalls: 0, ledgerReads: 0, ledgerWrites: 0 };
  let ledger = null;
  if (useLedger) {
    ledger = loadLedger(ledgerFile);
    overhead.ledgerReads += 1;
  }
  const verdict = calibrationVerdict({ reviewers, useLedger, ledger, N_min, staticFloor, attestedLineages });
  return { verdict, overhead };
}

// Re-export the shared-module primitives the learning layer routes through, so a consumer/test reads the
// SAME monotone-tighten-only map + origin counter the engine/round use (one canonical counter, I3/I8).
export { requiredQuorum, countIndependentOrigins, meetsQuorum, STATIC_QUORUM_FLOOR, lineageOf };

// CLI: `node bin/rho-ledger.mjs` prints the live ledger's ρ̂ estimate (human inspection).
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const ledger = loadLedger();
  console.log(JSON.stringify({ hash: ledgerHash(ledger), estimate: estimateRho(ledger) }, null, 2));
}

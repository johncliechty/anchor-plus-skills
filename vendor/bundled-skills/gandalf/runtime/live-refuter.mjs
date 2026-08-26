// Gandalf runtime host — the LIVE cross-family REFUTER orchestration (Wave W3).
//
// THE INTEGRATION POINT the deterministic gate never runs (seam/refute.mjs PRINCIPLE-D): the Tier-1
// host (runtime/seam-pass.applySeamPass) can only ever floor every elevation to SPECULATIVE because
// no INDEPENDENT named-defeater refuter actually ran — there was no live `agent()` seam and no minter.
// This module is that missing seam: for each high-value elevation that FIRES the refuter, it dispatches
// a REAL cross-family refuter (a Gemini `agy -p` sub-agent, drafter family = Claude) and, per genuine
// refutation, MINTS a claim-bound commission into the SAME per-run ledger applySeamPass resolves against.
// The result: a genuinely cross-family-refuted, surviving elevation reaches GROUNDED with cross_model:true
// — DERIVED from the unforgeable ledger, never self-asserted.
//
// THE FIVE LOAD-BEARING INVARIANTS (build task W3):
//   1. ONE SHARED PER-RUN LEDGER. The minter mints into `ledger.mintCommission` and applySeamPass
//      resolves via the SAME `ledger.resolveCommission`. A split ledger ⇒ every mint is a false
//      negative (the gate can never authenticate an id it did not see minted). The host constructs
//      ONE `createCommissionLedger()` and threads its resolver into applySeamPass.
//   2. MINT/GATE IDENTITY MATCH. The commission's result_digest is CLAIM-BOUND (seam/refute.mjs
//      elevationIdentity = id + reasoning + what_would_refute_it). We mint on the EXACT elevation
//      object we place into the returned draft — the SAME object applySeamPass hands to the gate
//      (isCrossFamilyRefutation) BEFORE ensureItemKeys runs — so the two identities are byte-identical.
//   3. ROUTING GUARD (never self-review). The refuter role MUST resolve to a NON-drafter family. If it
//      would resolve to the drafter family (claude) or to routes.default=claude, we HALT — a drafter
//      grading its own draft earns no independent origin and can never cross the single-family ceiling.
//   4. HONEST-HALT. If the refuter errors / returns empty / agy is down (the W0 seam throws HaltError on
//      a non-attested / substituted rec), the elevation gets NO provenance ⇒ it stays SPECULATIVE and
//      cross_model is NOT lifted. `survived` must be an EXPLICIT refuter boolean, never defaulted true.
//   5. BOUNDED BUDGET. More firing elevations than the pre-registered budget R ⇒ HALT (assertRefuterBudget;
//      no silent drop of the excess).
//
// Stdlib + the shipped gandalf seams only. The trio role-routed agent is a LAZY dynamic import (live
// path only), so importing THIS module never loads the trio and never spawns a subprocess — the
// deterministic test injects a stub agent + a fixture ledger and exercises the full mint→gate path with
// zero live calls.

import {
  firesRefuter,
  REFUTER_BUDGET_R,
  assertRefuterBudget,
  isNamedDefeater,
  computeResultDigest,
  composeRefutationProvenance,
} from '../seam/refute.mjs';

/** The drafter family (who authored the drafted claims) and the refuter family (who runs the
 *  independent refutation) for the reference W3 topology: Claude drafts, Gemini refutes. */
export const DRAFTER_FAMILY = 'claude';
export const REFUTER_FAMILY = 'gemini';

/** Test/fixture only: historical Claude+Gemini table. Live production MUST omit routes
 *  (or call `buildDefaultRefuterRoutes`) so seats follow coding/review prefs — never pin Claude in launchers. */
export const DEFAULT_REFUTER_ROUTES = Object.freeze({
  refuter: { driver: 'gemini-cli', model: 'Gemini 3.1 Pro (High)' },
  default: { driver: 'claude' },
});

/**
 * Prefs-aware Gandalf/Jumper route table: refuter → REVIEW_FAMILY; default/drafter → CODING_FAMILY.
 * Review model left unpinned so the gemini-cli TRIO_TIER ladder applies when family is gemini.
 * @param {object} [env=process.env]
 */
export async function buildDefaultRefuterRoutes(env = process.env) {
  const { buildRoutesFromFamilies } = await import('fil<path>');
  return buildRoutesFromFamilies({
    env,
    codingRoles: [],
    reviewRoles: ['refuter'],
  });
}

/** The JSON-schema the refuter reply is asked to conform to: the NAMED defeater it attempted and an
 *  EXPLICIT survived verdict (never defaulted). `verdict` (free prose) is optional. */
export const REFUTER_REPLY_SCHEMA = {
  type: 'object',
  required: ['defeater', 'survived'],
  properties: {
    defeater: { type: 'string' },
    survived: { type: 'boolean' },
    verdict: { type: 'string' },
  },
};

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** Thrown by the routing guard when the refuter role would resolve to the DRAFTER family (self-review).
 *  A distinct, NAMED class so the caller/test can assert the run HALTS rather than silently self-reviewing
 *  on the drafter's own model (which earns no independent cross-family origin). */
export class SelfRefutationHalt extends Error {
  constructor(refuterFamily, drafterFamily, driver) {
    super(
      `self-refutation HALT: the refuter role resolves to driver ${JSON.stringify(driver)} (family ` +
      `${JSON.stringify(refuterFamily)}) which is the DRAFTER family ${JSON.stringify(drafterFamily)} — a ` +
      `verification/refuter role MUST resolve to a NON-drafter family (never self-review). Route the ` +
      `refuter role to a different model family (e.g. driver 'gemini-cli') or fix routes.default.`
    );
    this.name = 'SelfRefutationHalt';
    this.refuter_family = refuterFamily;
    this.drafter_family = drafterFamily;
    this.driver = driver;
  }
}

/** Map a trio driver name to its model FAMILY (the leading token — STRICT prefix, never a substring, so
 *  a label like 'claude-...-gemini-fallback' stamps claude, not gemini). Returns null for an
 *  empty/unknown driver so the routing guard fails CLOSED (an unverifiable family is treated as unsafe). */
export function familyFromDriver(driver) {
  const t = String(driver ?? '').trim().toLowerCase();
  if (!t) return null;
  if (t.startsWith('gemini')) return 'gemini';
  if (t.startsWith('claude')) return 'claude';
  if (t.startsWith('openai') || t.startsWith('gpt')) return 'openai';
  if (t.startsWith('grok')) return 'grok';
  return t.split(/[\s\-_]/)[0] || null;
}

/**
 * ROUTING GUARD (invariant 3). Assert the refuter role resolves to a NON-drafter family. The refuter role
 * resolves to `routes.refuter` (else `routes.default`); its driver's family MUST differ from
 * `drafterFamily`. HALTs (SelfRefutationHalt) when it resolves to the drafter family OR to an
 * unverifiable/empty driver (fail closed) — never self-review. Returns the resolved refuter family on pass.
 * @param {{routes?:object, drafterFamily?:string}} [o]
 * @returns {string} the resolved refuter family
 */
export function assertCrossFamilyRouting({ routes = {}, drafterFamily = DRAFTER_FAMILY } = {}) {
  const route = (routes && (routes.refuter || routes.default)) || {};
  const driver = route.driver || null;
  const refuterFamily = familyFromDriver(driver);
  const drafter = String(drafterFamily ?? '').trim().toLowerCase();
  if (!refuterFamily || refuterFamily === drafter) {
    throw new SelfRefutationHalt(refuterFamily, drafter, driver);
  }
  return refuterFamily;
}

/** The default refuter prompt: ask the independent (cross-family) refuter to ATTEMPT the elevation's
 *  own named defeater and report, honestly, whether the claim SURVIVED it. Small by design (agy delivers
 *  the prompt via ARGV; keep it well under the ~32KB limit and let the refuter read files itself). */
export function defaultRefutePrompt(elevation) {
  const claim = String(elevation?.verdict ?? elevation?.reasoning ?? '').trim();
  const namedDefeater = String(elevation?.what_would_refute_it ?? '').trim();
  return (
    `You are an INDEPENDENT cross-family refuter. A drafter (a different model family) elevated this ` +
    `suggestion as high-value:\n\n  CLAIM: ${claim}\n  REASONING: ${String(elevation?.reasoning ?? '').trim()}\n\n` +
    `The drafter named ONE concrete defeater that would falsify it:\n\n  NAMED DEFEATER: ${namedDefeater}\n\n` +
    `Genuinely ATTEMPT that named defeater against the claim. Do NOT rubber-stamp it. Then answer, as a ` +
    `single raw JSON object, with:\n` +
    `  - "defeater": the concrete named defeater you actually attempted (a falsifying observation, NOT a ` +
    `confidence word like "likely"/"unlikely"),\n` +
    `  - "survived": a boolean — true iff the claim SURVIVED your attempted defeater; false iff the ` +
    `defeater LANDED and breaks the claim,\n` +
    `  - "verdict": one sentence explaining the outcome.\n` +
    `Report survived HONESTLY — never default it to true.`
  );
}

/** Read the refuter's structured reply into `{ defeater, survived, verdict }`. Tolerant of the
 *  gemini-cli ABSTAIN shape (`{answerable:'no',...}`) and of plain text — anything without an explicit
 *  boolean `survived` + a named `defeater` is rejected downstream (⇒ no provenance ⇒ SPECULATIVE). */
export function extractRefuterVerdict(reply) {
  if (!isPlainObject(reply)) return { defeater: undefined, survived: undefined, verdict: undefined };
  return { defeater: reply.defeater, survived: reply.survived, verdict: reply.verdict };
}

/**
 * runLiveRefutation — dispatch a live cross-family refuter for each FIRING elevation and MINT a
 * claim-bound commission per genuine refutation into the SHARED per-run ledger.
 *
 * Returns a FRESH draft (the caller feeds it to applySeamPass with the SAME `ledger.resolveCommission`)
 * plus a per-elevation dispatch log. PURE w.r.t. the input `rawDraft` (never mutates it — every touched
 * elevation is a fresh copy). Each elevation the refuter genuinely runs on:
 *   • survived:true  ⇒ mint a cross-family commission, attach the refutation_provenance carrying its id,
 *     and REQUEST the GROUNDED tier (the gate still decides eligibility — labelTier only CAPS, so the
 *     request is required to reach GROUNDED, and the derived ledger check governs whether it is granted);
 *   • survived:false ⇒ the defeater LANDED ⇒ set rung REFUTED so the host drops it (only-REFUTED-drops);
 *   • refuter error / empty / no explicit survived / non-named defeater ⇒ NO provenance ⇒ the host floors
 *     it to SPECULATIVE (honest un-refuted floor). `survived` is NEVER defaulted true.
 *
 * @param {object} rawDraft                         the model's raw draft ({reasoning, verdict, ..., elevations[]})
 * @param {object} o
 * @param {Function} o.agent                        the role-routed `agent(prompt, {role,label,schema})`
 * @param {object}   o.ledger                       the SHARED per-run commission ledger (createCommissionLedger())
 * @param {?object}  [o.routes]                     the route table — when present the routing guard runs
 * @param {string}   [o.drafterFamily='claude']
 * @param {string}   [o.refuterFamily='gemini']
 * @param {number}   [o.budget=REFUTER_BUDGET_R]    the bounded refuter budget R
 * @param {Function} [o.refutePrompt]               (elevation)=>string prompt builder
 * @param {string}   [o.role='refuter']
 * @param {Function} [o.log]
 * @returns {Promise<{draft:object, dispatch:object[]}>}
 */
export async function runLiveRefutation(rawDraft, {
  agent,
  ledger,
  routes = null,
  drafterFamily = DRAFTER_FAMILY,
  refuterFamily = REFUTER_FAMILY,
  budget = REFUTER_BUDGET_R,
  refutePrompt = defaultRefutePrompt,
  role = 'refuter',
  log = () => {},
} = {}) {
  if (!isPlainObject(rawDraft)) {
    throw new TypeError('runLiveRefutation: rawDraft must be a plain object');
  }
  if (!ledger || typeof ledger.mintCommission !== 'function' || typeof ledger.resolveCommission !== 'function') {
    throw new TypeError('runLiveRefutation: a shared commission ledger { mintCommission, resolveCommission } is required (invariant 1)');
  }
  if (typeof agent !== 'function') {
    throw new TypeError('runLiveRefutation: an injected role-routed agent(prompt, opts) is required');
  }
  // INVARIANT 3 — routing guard: a refuter role must resolve to a NON-drafter family (never self-review).
  if (routes) assertCrossFamilyRouting({ routes, drafterFamily });

  const rawElevations = Array.isArray(rawDraft.elevations) ? rawDraft.elevations : [];

  // Which elevations FIRE the refuter (value-if-true ≥ HIGH OR severity ≥ major).
  const firing = [];
  rawElevations.forEach((e, i) => { if (isPlainObject(e) && firesRefuter(e)) firing.push(i); });
  // INVARIANT 5, revised 2026-08-25 (John's ruling — elegance card + cost amendment; journals
  // 0296/0298-0301: the frozen R=3 HALT fired on nearly every real read, was twice misread as
  // "agy down", and shipped two avoidably-degraded deliverables). Cost is a PRE-FLIGHT
  // conversation, never a mid-run wall: excess firing elevations no longer HALT the run — the
  // top-R by value/severity get refuters; the excess ships UN-REFUTED and floors to SPECULATIVE
  // by the existing honest-floor invariant, each named in the dispatch log. Nothing is silently
  // dropped; paid-for output is never withheld (Gandalf's own locked law). The runaway ceiling
  // (>4×R) also finishes-and-stamps — it only escalates the log line.
  let toRefute = firing;
  let floored = [];
  if (firing.length > budget) {
    const rank = (i) => {
      const e = rawElevations[i];
      const v = String(e?.value_if_true ?? '').toLowerCase() === 'high' ? 2 : 1;
      // 2026-08-25 review fix: 'critical' outranks 'major' (it scored 0 — criticals
      // were floored BEFORE majors under budget pressure, inverted priority).
      const sev = String(e?.severity ?? '').toLowerCase();
      const s = sev === 'critical' ? 2 : sev === 'major' ? 1 : 0;
      return v * 10 + s;
    };
    const sorted = [...firing].sort((a, b) => rank(b) - rank(a) || a - b);
    toRefute = sorted.slice(0, budget).sort((a, b) => a - b);
    floored = sorted.slice(budget).sort((a, b) => a - b);
    const nameOf = (i) => rawElevations[i]?.id ?? `e${i}`;
    const ceiling = firing.length > Math.max(12, 4 * budget) ? ' RUNAWAY CEILING TRIPPED —' : '';
    log(`refuter budget PRE-FLIGHT:${ceiling} ${firing.length} firing elevation(s) exceed budget ${budget} — FLOORING, not halting: refuting top ${budget} (${toRefute.map(nameOf).join(', ')}); ${floored.length} ship SPECULATIVE un-refuted (${floored.map(nameOf).join(', ')}). Re-run with --budget ${firing.length} to cover all.`);
  }
  const firingSet = new Set(toRefute);
  const flooredSet = new Set(floored);

  // B3 (2026-07-11): firing elevations are INDEPENDENT — each gets its own refuter
  // call, its own mint, its own provenance — so they dispatch CONCURRENTLY under a
  // bounded cap instead of the old for-await serialization (which made the refuter
  // leg the second-longest stage of every real run: N × tens of seconds, serial).
  // Cap default 2 (agy OOMs above ~3 concurrent — the crucible/researchPrime caps
  // encode the same host fact); GANDALF_REFUTER_CONCURRENCY overrides, ceiling 3.
  // Determinism: results are placed by INDEX, dispatch is sorted by index, and the
  // ledger mints in-process — output is order-independent of completion order.
  const capEnv = Number(process.env.GANDALF_REFUTER_CONCURRENCY);
  const cap = Math.min(3, Number.isFinite(capEnv) && capEnv > 0 ? capEnv : 2);

  const refuteOne = async (i) => {
    const raw = rawElevations[i];
    // INVARIANT 2 — the object the GATE will read. We mint on THIS exact object and place it in the
    // returned draft, so elevationIdentity(bound) at mint === elevationIdentity(bound) at the gate.
    const bound = { ...raw };
    const label = `refuter:${raw.id ?? `e${i}`}`;
    try {
      const reply = await agent(refutePrompt(raw), { role, label, schema: REFUTER_REPLY_SCHEMA });
      const { defeater, survived, verdict } = extractRefuterVerdict(reply);

      // INVARIANT 4 — survived must be an EXPLICIT boolean and defeater a NAMED concrete defeater;
      // anything else ⇒ NO provenance ⇒ the host floors the elevation to SPECULATIVE (honest floor).
      if (typeof survived !== 'boolean' || !isNamedDefeater(defeater)) {
        return { index: i, bound, entry: { index: i, id: raw.id ?? null, minted: false, reason: 'refuter returned no explicit survived boolean and/or no named concrete defeater' } };
      }

      const v = (verdict === undefined || verdict === null || verdict === '') ? null : String(verdict);
      // The digest the commission is bound to — computed over THIS bound elevation's identity + the
      // refuter content. composeRefutationProvenance recomputes the SAME digest from the SAME args
      // (field parity: {defeater, survived, verdict} hashed == what the envelope stores), so the ledger
      // tuple's result_digest === the provenance's result_digest === the gate's recomputed digest.
      const result_digest = computeResultDigest({ elevation: bound, defeater, survived, verdict: v });
      const commission_id = ledger.mintCommission({
        drafter_family: drafterFamily,
        refuter_family: refuterFamily,
        result_digest,
      });
      const provenance = composeRefutationProvenance({
        elevation: bound,
        defeater,
        survived,
        verdict: v,
        drafter_family: drafterFamily,
        refuter_family: refuterFamily,
        commission_id,
      });
      bound.refutation_provenance = provenance;

      if (survived === false) {
        // The named defeater LANDED — the claim is refuted. Only-REFUTED-drops: the host will drop it.
        bound.rung = 'REFUTED';
      } else {
        // A surviving, cross-family refutation REQUESTS the GROUNDED tier; the gate (derived cross_family
        // eligibility from the shared ledger) is the sole authority that grants or caps it.
        bound.tier = 'GROUNDED';
      }
      return { index: i, bound, entry: { index: i, id: raw.id ?? null, minted: true, survived, commission_id } };
    } catch (err) {
      // INVARIANT 4 (honest-HALT): the refuter errored / agy is down (W0 seam throws HaltError on a
      // non-attested / substituted rec) / empty reply. The elevation gets NO provenance ⇒ SPECULATIVE ⇒
      // cross_model NOT lifted. We NEVER fabricate a survived:true to manufacture a cross-family grant.
      log(`!! ${label}: refuter failed (${err?.message ?? err}) — elevation stays SPECULATIVE (no provenance minted)`);
      return { index: i, bound, entry: { index: i, id: raw.id ?? null, minted: false, reason: `refuter failed: ${err?.message ?? err}` } };
    }
  };

  // Bounded pool: `cap` workers drain the firing queue; per-elevation failures are
  // handled INSIDE refuteOne (it never rejects), so one bad refuter cannot sink the batch.
  const queue = [...toRefute];
  const results = new Map(); // index -> { bound, entry }
  await Promise.all(Array.from({ length: Math.min(cap, queue.length) }, async () => {
    while (queue.length) {
      const i = queue.shift();
      const r = await refuteOne(i);
      results.set(r.index, r);
    }
  }));

  const outElevations = [];
  const dispatch = [];
  for (let i = 0; i < rawElevations.length; i++) {
    const raw = rawElevations[i];
    if (!isPlainObject(raw)) { outElevations.push(raw); continue; }
    // Budget-floored elevations: fired but not refuted this run — recorded, never silent.
    if (flooredSet.has(i)) {
      outElevations.push({ ...raw });
      dispatch.push({ index: i, id: raw.id ?? null, minted: false, reason: `budget floor (pre-flight): fired but not refuted this run — ships SPECULATIVE; re-run with --budget ${firing.length} to cover` });
      continue;
    }
    // Below-threshold elevations earn no refuter — pass a fresh copy through (the host floors them).
    if (!firingSet.has(i)) { outElevations.push({ ...raw }); continue; }
    const r = results.get(i);
    outElevations.push(r.bound);
    dispatch.push(r.entry);
  }

  return { draft: { ...rawDraft, elevations: outElevations }, dispatch };
}

/**
 * Build the LIVE role-routed agent from coding/review family prefs
 * (refuter → REVIEW_FAMILY, drafter/default → CODING_FAMILY). Omit `routes` to honor prefs;
 * pass an explicit table to pin. Runs the routing guard FIRST so a self-review route can never
 * be built. ENV: forces CRUCIBLE_AGENT_LIVE=1. NOT called by the deterministic test.
 * @param {{routes?:object, drafterFamily?:string, env?:object}} [o]
 * @returns {Promise<Function>} the role-routed agent(prompt, opts)
 */
export async function buildLiveRefuterAgent({ routes, drafterFamily, env = process.env } = {}) {
  const { makeRoleRoutedAgent, buildRoutesFromFamilies } = await import('fil<path>');
  const built = buildRoutesFromFamilies({
    env,
    codingRoles: [],
    reviewRoles: ['refuter'],
  });
  const resolvedRoutes = routes ?? built.routes;
  const resolvedDrafter = drafterFamily ?? built.drafterFamily;
  // Fail-closed unless Anchor prefs set coding_family === review_family (honest single-family).
  const singleFamilyPrefs = !routes && built.families.coding === built.families.review;
  if (!singleFamilyPrefs) {
    assertCrossFamilyRouting({ routes: resolvedRoutes, drafterFamily: resolvedDrafter });
  }
  return makeRoleRoutedAgent({ routes: resolvedRoutes, env: { ...env, CRUCIBLE_AGENT_LIVE: '1' } });
}

// bin/live-round-agent.mjs — Wave W5 LIVE CROSS-FAMILY ROUND AGENT (the 5:1 verification split).
//
// THE MISSING SEAM. bin/round.mjs's `orchestrateRound` takes an INJECTED `agent(prompt, opts)` and
// dispatches its adjudication roles (reviewer / debate / judge / synthesizer) through it. Until now the
// only live wiring (run-ramanujan-round.mjs) replayed a SINGLE-family Claude stub and HARD-CODED
// `substrateFamilies: ['claude']` — so a run could never honestly reach a second family, and the
// suspiciously-dry guard (assessConvergenceHonesty) + the deliverable's `cross_model` proxy were fed a
// fabricated substrate list. This module is that missing wiring: it builds the round's live `agent` via
// the trio's `makeRoleRoutedAgent` so the VERIFICATION roles route to a real cross-family (Gemini `agy
// -p`) seat while the drafter/synthesizer/default stay on Claude — the machine-wide 5:1 split — and it
// DERIVES `substrateFamilies` from the families ACTUALLY REACHED, never a hard-coded list.
//
// Reference topology proven live in Gandalf W3 (skills/gandalf/runtime/live-refuter.mjs): Claude drafts,
// Gemini verifies; the verification role MUST resolve to a NON-drafter family (never self-review), and if
// the cross-family backend is unavailable the W0 gemini-cli seam throws HaltError (non-attested /
// substituted) so the round HALTs honestly instead of silently self-reviewing on Claude.
//
// THE FOUR LOAD-BEARING BEHAVIORS (build task W5):
//   1. ROLE-ROUTED AGENT via makeRoleRoutedAgent — reviewer/shark/debate/judge → gemini-cli (model
//      resolved by TRIO_TIER in the driver ladder), synthesizer/default → claude. The injected-agent
//      SEAM is preserved: instrumentRoundAgent wraps ANY agent (a stub in tests, the live role-routed
//      agent in production), so no live call is required to exercise the tracking + cap logic.
//   2. substrateFamilies FROM REACHED BACKENDS — a per-run tracker records the distinct family of every
//      dispatch that ACTUALLY RETURNED (attested). A run that genuinely reaches a Gemini reviewer/judge
//      reports ['claude','gemini']; a Gemini-absent (single-family) run honestly reports ['claude'].
//   3. CONCURRENCY CAP — a counting semaphore bounds concurrent LIVE-GEMINI (agy) dispatches to
//      RESEARCHPRIME_GEMINI_MAX_CONCURRENCY (default 2, hard ceiling 3: agy OOMs above ~3 concurrent).
//      Only gemini-family calls are gated; Claude dispatches run unbounded.
//   4. HONEST DEGRADE — a failed/unattested Gemini call throws (the W0 seam's HaltError-on-non-attested)
//      and is NOT recorded as reached and NOT retried onto Claude; it propagates so the round HALTs. The
//      routing guard additionally refuses to even BUILD an agent whose verification role would resolve to
//      the drafter family (fail-closed against self-review).
//
// Stdlib + the shipped researchPrime/trio seams only. The trio role-routed agent is a LAZY dynamic import
// (live path only), so importing THIS module never loads the trio and never spawns a subprocess — the
// deterministic test injects a stub agent and exercises the full routing / tracking / cap path with zero
// live calls.

import { TRIO_SURFACE } from './engine.mjs';
const { HaltError } = TRIO_SURFACE['foreman-lib'];

/** Historical default drafter family (Claude). Live runs resolve drafter from CODING_FAMILY. */
export const DRAFTER_FAMILY = 'claude';

/** The VERIFICATION roles — round adversarial seats (bin/round.mjs): reviewer panel, Shark roster,
 *  G9 debate, and context-free Judge. Prefs route these to REVIEW_FAMILY; Synthesizer steers on CODING_FAMILY. */
export const VERIFICATION_ROLES = Object.freeze(['reviewer', 'shark', 'debate', 'judge']);

/** Test/fixture only: historical Claude+Gemini 5:1 table. Live production MUST omit
 *  routes (or call `buildDefaultRoundRoutes`) so seats follow coding/review prefs. */
export const DEFAULT_ROUND_ROUTES = Object.freeze({
  reviewer: { driver: 'gemini-cli' },
  shark: { driver: 'gemini-cli' },
  debate: { driver: 'gemini-cli' },
  judge: { driver: 'gemini-cli' },
  synthesizer: { driver: 'claude' },
  default: { driver: 'claude' },
});

/**
 * Prefs-aware researchPrime route table: verification seats → REVIEW_FAMILY; synthesizer/default → CODING_FAMILY.
 * @param {object} [env=process.env]
 */
export async function buildDefaultRoundRoutes(env = process.env) {
  const { buildRoutesFromFamilies } = await import('../../drivers/index.mjs');
  return buildRoutesFromFamilies({
    env,
    codingRoles: ['synthesizer'],
    reviewRoles: ['reviewer', 'shark', 'debate', 'judge'],
  });
}

/** The SINGLE-FAMILY (replay / degraded) route table: every role → Claude. Used by the offline replay
 *  runner so its `substrateFamilies` is DERIVED (['claude']) from the reached backend, not hard-coded. */
export const SINGLE_FAMILY_ROUTES = Object.freeze({ default: { driver: 'claude' } });

/** The env var + safe default + hard ceiling for the live-Gemini concurrency cap. agy OOMs above ~3
 *  concurrent `agy -p` children, so the ceiling is 3 and the default is a conservative 2. */
export const GEMINI_CAP_ENV = 'RESEARCHPRIME_GEMINI_MAX_CONCURRENCY';
export const DEFAULT_GEMINI_CAP = 2;
export const MAX_GEMINI_CAP = 3;

/** Thrown when a VERIFICATION role would resolve to the DRAFTER family (self-review). A named HaltError
 *  subclass so the engine treats it as a HALT-for-human and the caller/test can assert the run HALTs
 *  rather than silently self-reviewing on the drafter's own model (which earns no cross-family origin). */
export class SelfReviewHalt extends HaltError {
  constructor(role, resolvedFamily, drafterFamily, driver) {
    super(
      `self-review HALT: verification role ${JSON.stringify(role)} resolves to driver ${JSON.stringify(driver)} ` +
        `(family ${JSON.stringify(resolvedFamily)}) which is the DRAFTER family ${JSON.stringify(drafterFamily)} — ` +
        `a verification seat MUST resolve to a NON-drafter family (never self-review).`,
      `route ${JSON.stringify(role)} to a cross-family backend (e.g. driver 'gemini-cli') or fix routes.default.`,
    );
    this.name = 'SelfReviewHalt';
    this.role = role;
    this.resolved_family = resolvedFamily;
    this.drafter_family = drafterFamily;
    this.driver = driver;
  }
}

/** Map a trio driver name to its model FAMILY (the leading token — STRICT prefix, never a substring, so a
 *  label like 'claude-…-gemini-fallback' stamps claude, not gemini). Returns null for an empty/unknown
 *  driver so the routing guard fails CLOSED (an unverifiable family is treated as unsafe). */
export function familyFromDriver(driver) {
  const t = String(driver ?? '').trim().toLowerCase();
  if (!t) return null;
  if (t.startsWith('gemini')) return 'gemini';
  if (t.startsWith('claude')) return 'claude';
  if (t.startsWith('openai') || t.startsWith('gpt')) return 'openai';
  if (t.startsWith('grok')) return 'grok';
  return t.split(/[\s\-_]/)[0] || null;
}

/** The role KEY for an `agent(prompt, opts)` call — identical resolution to makeRoleRoutedAgent: `opts.role`
 *  else the label prefix before ':' / '#' / '.' / whitespace, lowercased. */
export function resolveRoleKey(opts = {}) {
  return String(opts.role || opts.label || '').split(/[:#.\s]/)[0].toLowerCase();
}

/** The FAMILY a given role resolves to under a route table (route[role] else route.default), via
 *  familyFromDriver. Mirrors makeRoleRoutedAgent's own selection so the wrapper's bookkeeping matches the
 *  backend actually chosen. Returns null when neither the role nor default names a resolvable driver. */
export function familyFromRoute(routes = {}, role = '') {
  const route = routes[role] || routes.default || {};
  return familyFromDriver(route.driver || null);
}

/**
 * ROUTING GUARD (behavior 4, fail-closed). Assert EVERY verification role resolves to a NON-drafter
 * family under `routes`. HALTs (SelfReviewHalt) the moment any verification seat would resolve to the
 * drafter family OR to an unverifiable/empty driver — so a self-review agent can never even be built.
 * @param {{routes?:object, drafterFamily?:string, roles?:string[]}} [o]
 * @returns {Object<string,string>} role → resolved cross-family, on pass
 */
export function assertCrossFamilyRouting({ routes = {}, drafterFamily = DRAFTER_FAMILY, roles = VERIFICATION_ROLES } = {}) {
  const drafter = String(drafterFamily ?? '').trim().toLowerCase();
  const resolved = {};
  for (const role of roles) {
    const route = routes[role] || routes.default || {};
    const driver = route.driver || null;
    const family = familyFromDriver(driver);
    if (!family || family === drafter) {
      throw new SelfReviewHalt(role, family, drafter, driver);
    }
    resolved[role] = family;
  }
  return resolved;
}

/** Resolve the live-Gemini concurrency cap: `RESEARCHPRIME_GEMINI_MAX_CONCURRENCY` clamped to [1, 3]
 *  (agy OOMs above ~3), default 2. A non-integer / out-of-range env value falls back to the default. */
export function resolveGeminiCap(env = process.env) {
  const raw = Number.parseInt(env[GEMINI_CAP_ENV], 10);
  if (!Number.isInteger(raw) || raw < 1) return DEFAULT_GEMINI_CAP;
  return Math.min(raw, MAX_GEMINI_CAP);
}

/**
 * A minimal in-process counting semaphore (behavior 3). `acquire()` resolves once a slot is free (FIFO
 * for waiters); `release()` frees a slot and admits the next waiter. No timers, no I/O — purely
 * deterministic, so the concurrency cap is testable without any real subprocess.
 * @param {number} max  slots (integer >= 1)
 */
export function makeSemaphore(max) {
  if (!Number.isInteger(max) || max < 1) {
    throw new TypeError('makeSemaphore(max): max must be an integer >= 1');
  }
  let active = 0;
  const waiters = [];
  return {
    acquire() {
      return new Promise((resolve) => {
        if (active < max) { active += 1; resolve(); }
        else waiters.push(resolve);
      });
    },
    release() {
      if (active <= 0) return;
      const next = waiters.shift();
      if (next) next(); // hand the just-freed slot straight to the next waiter (active unchanged)
      else active -= 1;
    },
    get active() { return active; },
    get max() { return max; },
  };
}

/**
 * A per-run REACHED-FAMILY tracker (behavior 2). Records the distinct model families that ACTUALLY ran
 * (an agent dispatch that returned attested). `families()` is the honest `substrateFamilies` the round /
 * deliverable / suspiciously-dry guard consume — never a hard-coded list.
 * @param {Iterable<string>} [seed=[]]  optional pre-seeded families (e.g. a known drafter)
 */
export function makeReachedFamilyTracker(seed = []) {
  const reached = new Set();
  const add = (f) => { if (f) reached.add(String(f).trim().toLowerCase()); };
  for (const f of seed || []) add(f);
  return {
    note(family) { add(family); },
    families() { return [...reached].sort(); },
    has(family) { return reached.has(String(family ?? '').trim().toLowerCase()); },
    get size() { return reached.size; },
  };
}

/**
 * Wrap ANY injected `agent(prompt, opts)` so that, per dispatch:
 *   • the call's role → family is resolved from `routes` (matching makeRoleRoutedAgent's own choice);
 *   • a GEMINI-family call acquires a slot from the shared gemini semaphore BEFORE dispatch and releases
 *     it after (the concurrency cap — behavior 3); Claude calls are ungated;
 *   • on a SUCCESSFUL return the family is recorded as REACHED (behavior 2). A THROW (the W0 seam's
 *     HaltError on a non-attested / down Gemini) is NEVER recorded and NEVER caught — it propagates so the
 *     round HALTs honestly, and the slot is released in `finally` (behavior 4).
 *
 * This is the injected-agent SEAM: `agent` can be a deterministic stub (tests) or the live role-routed
 * agent (production). Nothing here spawns a process.
 *
 * @param {object} o
 * @param {Function} o.agent                       the underlying agent(prompt, opts) (stub or live)
 * @param {object}   [o.routes=DEFAULT_ROUND_ROUTES]
 * @param {object}   o.tracker                      a makeReachedFamilyTracker()
 * @param {object}   [o.geminiSemaphore]            a makeSemaphore(cap); built from o.geminiCap if omitted
 * @param {number}   [o.geminiCap]                  cap for the internally-built semaphore
 * @returns {(prompt:string, opts?:object)=>Promise<any>}
 */
export function instrumentRoundAgent({
  agent,
  routes = DEFAULT_ROUND_ROUTES,
  tracker,
  geminiSemaphore = null,
  geminiCap,
} = {}) {
  if (typeof agent !== 'function') {
    throw new TypeError('instrumentRoundAgent: an injected agent(prompt, opts) is required');
  }
  if (!tracker || typeof tracker.note !== 'function' || typeof tracker.families !== 'function') {
    throw new TypeError('instrumentRoundAgent: a reached-family tracker (makeReachedFamilyTracker()) is required');
  }
  const sem = geminiSemaphore
    || makeSemaphore(Number.isInteger(geminiCap) && geminiCap >= 1 ? Math.min(geminiCap, MAX_GEMINI_CAP) : DEFAULT_GEMINI_CAP);

  return async (prompt, opts = {}) => {
    const role = resolveRoleKey(opts);
    const family = familyFromRoute(routes, role);
    const gated = family === 'gemini';
    if (gated) await sem.acquire();
    try {
      const out = await agent(prompt, opts);
      // Reached ONLY on a successful (attested) return — a thrown HaltError below is never recorded, so a
      // failed/unavailable Gemini call can never inflate substrateFamilies (honest degrade).
      tracker.note(family);
      return out;
    } finally {
      if (gated) sem.release();
    }
  };
}

/**
 * Build the LIVE role-routed round agent from coding/review family prefs
 * (reviewer/shark/debate/judge → REVIEW_FAMILY, synthesizer/default → CODING_FAMILY).
 * Omit `routes` to honor prefs; pass an explicit table to pin. Instrumented with the
 * reached-family tracker + live-Gemini concurrency cap. LAZY dynamic import of the trio
 * registry. Runs the routing guard FIRST so a self-review route can never be built.
 * @param {object} o
 * @param {object}   [o.routes]                     omit → prefs; pass to pin
 * @param {object}   o.tracker                      a makeReachedFamilyTracker() (its families() become substrateFamilies)
 * @param {string}   [o.drafterFamily]              omit → CODING_FAMILY from prefs
 * @param {object}   [o.env=process.env]
 * @param {number}   [o.geminiCap]                  override the env-resolved cap
 * @param {string}   [o.target]                     cwd / edit scope threaded to the backend
 * @param {Function} [o.log]
 * @returns {Promise<(prompt:string, opts?:object)=>Promise<any>>}
 */
export async function buildLiveRoundAgent({
  routes,
  tracker,
  drafterFamily,
  env = process.env,
  geminiCap,
  target,
  log,
} = {}) {
  if (!tracker) throw new TypeError('buildLiveRoundAgent: a reached-family tracker is required (its families() → substrateFamilies)');
  const { makeRoleRoutedAgent, buildRoutesFromFamilies } = await import('../../drivers/index.mjs');
  const built = buildRoutesFromFamilies({
    env,
    codingRoles: ['synthesizer'],
    reviewRoles: ['reviewer', 'shark', 'debate', 'judge'],
  });
  const resolvedRoutes = routes ?? built.routes;
  const resolvedDrafter = drafterFamily ?? built.drafterFamily;
  // Fail-closed against accidental self-review, unless Anchor prefs set
  // coding_family === review_family (honest single-family; cross_model:false).
  const singleFamilyPrefs = !routes && built.families.coding === built.families.review;
  if (!singleFamilyPrefs) {
    assertCrossFamilyRouting({ routes: resolvedRoutes, drafterFamily: resolvedDrafter });
  }
  const cap = Number.isInteger(geminiCap) ? Math.min(geminiCap, MAX_GEMINI_CAP) : resolveGeminiCap(env);
  const routed = makeRoleRoutedAgent({
    routes: resolvedRoutes,
    env: { ...env, CRUCIBLE_AGENT_LIVE: '1' },
    ...(target !== undefined ? { target } : {}),
    ...(log !== undefined ? { log } : {}),
  });
  return instrumentRoundAgent({ agent: routed, routes: resolvedRoutes, tracker, geminiCap: cap });
}

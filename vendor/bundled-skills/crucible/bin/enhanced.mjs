// enhanced.mjs — Crucible's CROSS-FAMILY verification seam (Wave W6 — RETIRED shim).
//
// HISTORY / RETIREMENT. Through Wave 9 this module was a COMPETING cross-model path: a
// hardcoded model registry whose Gemini entry was a non-current, API-style id, provisioned
// via an API-key env probe + a child-process capability spawn. That violated two
// standing rules — the no-phantom-model rule (never name an API-style / non-current id;
// `agy` silently degrades those to Flash) and the single-seam rule (one shared role
// router, never a bespoke per-module backend). It was ALSO never wired into the live
// path (only its own test imported it). Wave W6 RETIRES it: this file is now a thin shim
// over the trio's shared `makeRoleRoutedAgent` (drivers/index.mjs) + the gemini-cli tier
// ladder (`resolveGeminiModel`), building Crucible's live agent from coding/review family
// prefs (CODING_FAMILY / REVIEW_FAMILY or ~/.anchor/model_prefs.json) — verification seats
// (shark / judge) on REVIEW_FAMILY, steering / drafting (synthesizer / default) on
// CODING_FAMILY. Historical machine default remains Claude codes + Gemini checks.
//
// The model for the Gemini seats is left UNPINNED so the gemini-cli driver's TRIO_TIER
// ladder resolves it (heavy → "Gemini 3.1 Pro (High)", standard → "Gemini 3.5 Flash
// (Medium)") — NEVER an API-style id. There is no hardcoded model registry, no API-key env
// probe, and no child-process capability spawn here anymore.
//
// Reference topology (JUST-BUILT, mirrored): researchPrime/bin/live-round-agent.mjs (the
// W5 live cross-family round agent). The four load-bearing behaviors are identical:
//   1. ROLE-ROUTED AGENT via makeRoleRoutedAgent — shark/judge → gemini-cli (tier-resolved
//      model), synthesizer/default → claude. The injected-agent SEAM is preserved:
//      instrumentCrucibleAgent wraps ANY agent (a stub in tests, the live role-routed
//      agent in production), so no live call is needed to exercise tracking + the cap.
//   2. REACHED-FAMILY TRACKER — records the distinct family of every dispatch that
//      ACTUALLY returned (attested), so a run's substrate provenance is DERIVED from what
//      was reached, never a hardcoded list.
//   3. CONCURRENCY CAP — a counting semaphore bounds concurrent LIVE-GEMINI (agy)
//      dispatches to CRUCIBLE_GEMINI_MAX_CONCURRENCY (default 2, hard ceiling 3: agy OOMs
//      above ~3). Only gemini-family calls are gated; Claude dispatches run unbounded.
//   4. HONEST DEGRADE — a failed / unattested Gemini call throws (the W0 gemini-cli seam's
//      HaltError on non-attested) and is NEVER recorded as reached and NEVER retried onto
//      Claude; it propagates so the run HALTs. The routing guard additionally refuses to
//      even BUILD an agent whose verification role would resolve to the drafter family
//      (fail-closed against self-review).
//
// Stdlib + the shipped crucible/trio seams only. The trio role-routed agent is a LAZY
// dynamic import (live path only), so importing THIS module never loads the trio and never
// spawns a subprocess — the deterministic test injects a stub through instrumentCrucibleAgent.

import { HaltError } from './crucible-lib.mjs';

/** Historical default drafter family (Claude). Live runs resolve drafter from CODING_FAMILY
 *  via `buildDefaultCrucibleRoutes` / `buildLiveCrucibleAgent` — do not treat this constant
 *  as the live seat when prefs differ. */
export const DRAFTER_FAMILY = 'claude';

/** The VERIFICATION roles — adversarial seats: Shark roster (role:'shark') and context-free
 *  Judge (role:'judge'). Under family prefs these route to REVIEW_FAMILY; the Synthesizer is
 *  the STEERING seat on CODING_FAMILY (it steers + anti-anchoring fresh-eyes; it never verifies). */
export const VERIFICATION_ROLES = Object.freeze(['shark', 'judge']);

/** Test/fixture only: historical Claude+Gemini 5:1 table. Live production MUST omit
 *  routes (or call `buildDefaultCrucibleRoutes`) so seats follow coding/review prefs —
 *  never hardcode Claude in launchers. */
export const DEFAULT_CRUCIBLE_ROUTES = Object.freeze({
  shark: { driver: 'gemini-cli' },
  judge: { driver: 'gemini-cli' },
  synthesizer: { driver: 'claude' },
  default: { driver: 'claude' },
});

/**
 * Prefs-aware Crucible route table: shark/judge → REVIEW_FAMILY driver; synthesizer/default
 * → CODING_FAMILY driver. Lazy-imports the trio registry so this module stays trio-free at
 * import time for pure unit tests that never call it.
 * @param {object} [env=process.env]
 * @returns {Promise<{ routes: object, families: object, drafterFamily: string }>}
 */
export async function buildDefaultCrucibleRoutes(env = process.env) {
  const { buildRoutesFromFamilies } = await import('../../drivers/index.mjs');
  const built = buildRoutesFromFamilies({
    env,
    codingRoles: ['synthesizer'],
    reviewRoles: ['shark', 'judge'],
  });
  return built;
}

/** The SINGLE-FAMILY (replay / Gemini-absent) route table: every role → Claude. A run wired
 *  with this honestly reaches only ['claude']; the routing guard REJECTS it for verification
 *  (all-Claude verification is self-review), so it is only for a non-adversarial replay. */
export const SINGLE_FAMILY_ROUTES = Object.freeze({ default: { driver: 'claude' } });

/** The env var + safe default + hard ceiling for the live-Gemini concurrency cap. agy OOMs
 *  above ~3 concurrent `agy -p` children, so the ceiling is 3 and the default is a
 *  conservative 2 (within Crucible's ≤2–3 verification-seat budget). */
export const GEMINI_CAP_ENV = 'CRUCIBLE_GEMINI_MAX_CONCURRENCY';
export const DEFAULT_GEMINI_CAP = 2;
export const MAX_GEMINI_CAP = 3;

/** Thrown when a VERIFICATION role would resolve to the DRAFTER family (self-review). A named
 *  HaltError subclass so the engine treats it as a HALT-for-human and the caller/test can
 *  assert the run HALTs rather than silently self-reviewing on the drafter's own model. */
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

/** Map a trio driver name to its model FAMILY (the leading token — STRICT prefix, never a
 *  substring, so 'claude-…-gemini-fallback' stamps claude, not gemini). Returns null for an
 *  empty/unknown driver so the routing guard fails CLOSED (an unverifiable family is unsafe). */
export function familyFromDriver(driver) {
  const t = String(driver ?? '').trim().toLowerCase();
  if (!t) return null;
  if (t.startsWith('gemini')) return 'gemini';
  if (t.startsWith('claude')) return 'claude';
  if (t.startsWith('openai') || t.startsWith('gpt')) return 'openai';
  if (t.startsWith('grok')) return 'grok'; // grok + grok-cli
  return t.split(/[\s\-_]/)[0] || null;
}

/** The role KEY for an `agent(prompt, opts)` call — identical resolution to makeRoleRoutedAgent:
 *  `opts.role` else the label prefix before ':' / '#' / '.' / whitespace, lowercased. */
export function resolveRoleKey(opts = {}) {
  return String(opts.role || opts.label || '').split(/[:#.\s]/)[0].toLowerCase();
}

/** The FAMILY a given role resolves to under a route table (route[role] else route.default),
 *  via familyFromDriver. Mirrors makeRoleRoutedAgent's own selection. Returns null when neither
 *  the role nor default names a resolvable driver. */
export function familyFromRoute(routes = {}, role = '') {
  const route = routes[role] || routes.default || {};
  return familyFromDriver(route.driver || null);
}

/**
 * ROUTING GUARD (behavior 4, fail-closed). Assert EVERY verification role resolves to a
 * NON-drafter family under `routes`. HALTs (SelfReviewHalt) the moment any verification seat
 * would resolve to the drafter family OR to an unverifiable/empty driver — so a self-review
 * agent can never even be built.
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

/** Resolve the live-Gemini concurrency cap: `CRUCIBLE_GEMINI_MAX_CONCURRENCY` clamped to
 *  [1, 3] (agy OOMs above ~3), default 2. A non-integer / out-of-range env value falls back. */
export function resolveGeminiCap(env = process.env) {
  const raw = Number.parseInt(env[GEMINI_CAP_ENV], 10);
  if (!Number.isInteger(raw) || raw < 1) return DEFAULT_GEMINI_CAP;
  return Math.min(raw, MAX_GEMINI_CAP);
}

/**
 * A minimal in-process counting semaphore (behavior 3). `acquire()` resolves once a slot is
 * free (FIFO for waiters); `release()` frees a slot and admits the next waiter. No timers, no
 * I/O — purely deterministic, so the concurrency cap is testable without any real subprocess.
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
 * A per-run REACHED-FAMILY tracker (behavior 2). Records the distinct model families that
 * ACTUALLY ran (an agent dispatch that returned attested). `families()` is the honest
 * substrate provenance — never a hardcoded list.
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
 *   • the call's role → family is resolved from `routes` (matching makeRoleRoutedAgent's choice);
 *   • a GEMINI-family call acquires a slot from the shared gemini semaphore BEFORE dispatch and
 *     releases it after (the concurrency cap — behavior 3); Claude calls are ungated;
 *   • on a SUCCESSFUL return the family is recorded as REACHED (behavior 2). A THROW (the W0
 *     seam's HaltError on a non-attested / down Gemini) is NEVER recorded and NEVER caught — it
 *     propagates so the run HALTs honestly, and the slot is released in `finally` (behavior 4).
 *
 * This is the injected-agent SEAM: `agent` can be a deterministic stub (tests) or the live
 * role-routed agent (production). Nothing here spawns a process.
 *
 * @param {object} o
 * @param {Function} o.agent                       the underlying agent(prompt, opts) (stub or live)
 * @param {object}   [o.routes=DEFAULT_CRUCIBLE_ROUTES]
 * @param {object}   o.tracker                      a makeReachedFamilyTracker()
 * @param {object}   [o.geminiSemaphore]            a makeSemaphore(cap); built from o.geminiCap if omitted
 * @param {number}   [o.geminiCap]                  cap for the internally-built semaphore
 * @returns {(prompt:string, opts?:object)=>Promise<any>}
 */
export function instrumentCrucibleAgent({
  agent,
  routes = DEFAULT_CRUCIBLE_ROUTES,
  tracker,
  geminiSemaphore = null,
  geminiCap,
} = {}) {
  if (typeof agent !== 'function') {
    throw new TypeError('instrumentCrucibleAgent: an injected agent(prompt, opts) is required');
  }
  if (!tracker || typeof tracker.note !== 'function' || typeof tracker.families !== 'function') {
    throw new TypeError('instrumentCrucibleAgent: a reached-family tracker (makeReachedFamilyTracker()) is required');
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
      // Reached ONLY on a successful (attested) return — a thrown HaltError below is never
      // recorded, so a failed/unavailable Gemini call can never inflate the reached families.
      tracker.note(family);
      return out;
    } finally {
      if (gated) sem.release();
    }
  };
}

/**
 * Resolve the tier-selected Gemini model LABEL for the verification seats — a thin passthrough
 * to the gemini-cli driver's TRIO_TIER ladder (`resolveGeminiModel`). Exposed so a caller / log
 * can PREVIEW which agy label the shark/judge seats will run under, WITHOUT ever pinning an
 * API-style id. LAZY import so this module stays trio-free at import time.
 * @param {object} [o]
 * @returns {Promise<string>} the resolved agy model LABEL (e.g. "Gemini 3.5 Flash (Medium)")
 */
export async function resolveGeminiModel({ role = 'judge', env = process.env } = {}) {
  const { resolveGeminiModel: resolve } = await import('../../drivers/gemini-cli.mjs');
  return resolve({ role, env });
}

/**
 * Build the LIVE role-routed Crucible agent from coding/review family prefs
 * (shark/judge → REVIEW_FAMILY, synthesizer/default → CODING_FAMILY), instrumented with the
 * reached-family tracker + live-Gemini concurrency cap. Omit `routes` to honor prefs; pass
 * an explicit table (e.g. DEFAULT_CRUCIBLE_ROUTES) to pin. LAZY dynamic import of the trio
 * registry. Runs the routing guard FIRST so a self-review route can never be built. ENV:
 * forces CRUCIBLE_AGENT_LIVE=1. NOT called by the deterministic test (stub via instrumentCrucibleAgent).
 * @param {object} o
 * @param {object}   [o.routes]                     omit → prefs; pass to pin
 * @param {object}   [o.tracker]                    a makeReachedFamilyTracker() (built if omitted)
 * @param {string}   [o.drafterFamily]              omit → CODING_FAMILY from prefs
 * @param {object}   [o.env=process.env]
 * @param {number}   [o.geminiCap]                  override the env-resolved cap
 * @param {string}   [o.target]                     cwd / edit scope threaded to the backend
 * @param {Function} [o.log]
 * @returns {Promise<{agent:Function, tracker:object, routes:object, families:object, drafterFamily:string}>}
 */
export async function buildLiveCrucibleAgent({
  routes,
  tracker,
  drafterFamily,
  env = process.env,
  geminiCap,
  target,
  log,
} = {}) {
  const { makeRoleRoutedAgent, buildRoutesFromFamilies } = await import('../../drivers/index.mjs');
  const built = buildRoutesFromFamilies({
    env,
    codingRoles: ['synthesizer'],
    reviewRoles: ['shark', 'judge'],
  });
  const resolvedRoutes = routes ?? built.routes;
  const resolvedDrafter = drafterFamily ?? built.drafterFamily;
  const resolvedTracker = tracker ?? makeReachedFamilyTracker([resolvedDrafter]);
  // Behavior 4: fail-closed against accidental self-review. When the user sets
  // coding_family === review_family (honest single-family prefs), allow same
  // family on every seat and stamp cross_model:false via loadModelFamilies.
  // Explicit caller-supplied routes still go through the hard guard.
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
  const agent = instrumentCrucibleAgent({
    agent: routed,
    routes: resolvedRoutes,
    tracker: resolvedTracker,
    geminiCap: cap,
  });
  return {
    agent,
    tracker: resolvedTracker,
    routes: resolvedRoutes,
    families: built.families,
    drafterFamily: resolvedDrafter,
  };
}

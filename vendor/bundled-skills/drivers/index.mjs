// drivers/index.mjs — the pluggable model-backend registry + the single `runAgent`
// seam the trio engines call. One interface, swappable backends:
//
//   runAgent({ prompt, schema, freshContext, driver })
//
// The backend is selected by (in order): an explicit `driver` argument, the
// `TRIO_DRIVER` env var, else the default `'claude'`. Wave 4 ships only the Claude
// backend (the existing `claude -p` behavior, untouched — the non-regression
// guarantee); Wave 5 adds gemini/openai/grok by calling `registerDriver(...)`.
//
// A driver is `{ name, subAgentCapable, runAgent({ prompt, schema, freshContext }) }`.
// `runAgent` returns the model's text by default, or a schema-validated object when
// `schema` is supplied (the Claude backend retries once then ABSTAINs).

import fs from 'node:fs';
import path from 'node:path';
import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { makeReliableAgent } from './reliability.mjs';
import { claudeDriver, belowFrontierClaudeModel } from './claude.mjs';
import { geminiCliDriver } from './gemini-cli.mjs';
import { geminiDriver } from './gemini.mjs';
import { openaiDriver } from './openai.mjs';
import { grokDriver } from './grok.mjs';
import { grokCliDriver } from './grok-cli.mjs';
import { defaultRunGemini, extractJson } from '../foreman/bin/drivers/driver-gemini.mjs';

export const geminiCliNativeDriver = {
  name: 'gemini-cli-native',
  subAgentCapable: true,
  structuredOutput: 'cli-subagent (prompt-suffix)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, log = () => {} } = opts;
    const run = opts.runGemini || ((p, l) => defaultRunGemini(p, l, opts));
    
    const schemaSuffix = schema
      ? `\n\nRespond with ONLY a single raw JSON object (no markdown fences, no prose) ` +
        `that conforms to this JSON Schema:\n${JSON.stringify(schema)}`
      : '';
      
    const { text } = await run(prompt + schemaSuffix, label);
    if (!schema) return text;
    
    let obj = extractJson(text);
    if (!obj) {
      log(`   !! ${label} reply was not valid JSON — retrying once (strict reprompt)`);
      const strict = `${prompt}\n\nYour previous reply was NOT valid JSON. Respond with ONLY a single raw JSON ` +
        `object conforming to this JSON Schema — no prose, no fences:\n${JSON.stringify(schema)}`;
      obj = extractJson((await run(strict, `${label}#retry`)).text);
    }
    if (!obj) {
      log(`   !! ${label} still unparseable — ABSTAIN (answerable:no) → engine HALTs for human review`);
      return {
        answerable: 'no',
        transport_failed: true,
        note: `reviewer ${label} response was not parseable JSON after one retry (transport failure, not a plan problem)`,
        findings: []
      };
    }
    return obj;
  }
};

const DEFAULT_DRIVER = process.env.ANTIGRAVITY_AGENT ? 'gemini-cli' : 'claude';

// Roles whose seats are filled by REVIEW_FAMILY (adversarial / judge / check).
// Everything else defaults to CODING_FAMILY (code / reason / orchestrate).
export const REVIEW_ROLES = new Set([
  'review', 'shark', 'reviewer', 'debate', 'refuter', 'gate3', 'verify',
  'judge', 'attacker', 'analysis',
]);

/** Map a model family name (claude|gemini|grok) → registered trio driver name. */
export function familyToDriverName(family) {
  const f = String(family || '').trim().toLowerCase();
  if (f === 'gemini') return 'gemini-cli';
  // Subscription Grok Build CLI (`grok -p`) — NOT the raw xAI HTTP API (`grok` driver).
  if (f === 'grok') return 'grok-cli';
  if (f === 'claude' || !f) return 'claude';
  return null;
}

/**
 * Read coding/review families from env, else ~/.anchor/model_prefs.json (Anchor
 * mirror for non-Anchor hosts). Returns { coding, review, cross_model }.
 */
export function loadModelFamilies(env = process.env) {
  let coding = String(env.CODING_FAMILY || env.ANCHOR_CODING_FAMILY || '').trim().toLowerCase();
  let review = String(env.REVIEW_FAMILY || env.ANCHOR_REVIEW_FAMILY || '').trim().toLowerCase();
  if (!coding || !review) {
    try {
      const home = env.USERPROFILE || env.HOME || '';
      const mirror = path.join(home, '.anchor', 'model_prefs.json');
      if (home && fs.existsSync(mirror)) {
        const raw = JSON.parse(fs.readFileSync(mirror, 'utf8'));
        if (!coding && raw.coding_family) coding = String(raw.coding_family).toLowerCase();
        if (!review && raw.review_family) review = String(raw.review_family).toLowerCase();
      }
    } catch {
      // best-effort — never block a seat on prefs IO
    }
  }
  if (!coding) coding = 'claude';
  if (!review) review = 'gemini';
  return {
    coding,
    review,
    cross_model: coding !== review,
  };
}

/**
 * Resolve driver name from Anchor coding/review family prefs for a role.
 * Explicit TRIO_DRIVER / opts.driver still win over this (callers apply order).
 * @returns {?string} registered driver name or null
 */
export function resolveDriverFromFamilies(role, env = process.env) {
  const r = String(role || '').trim().toLowerCase();
  const fams = loadModelFamilies(env);
  const family = REVIEW_ROLES.has(r) ? fams.review : fams.coding;
  return familyToDriverName(family);
}

/**
 * Build an explicit role→{driver} route table from coding/review family prefs.
 * Used by live Crucible / researchPrime / Gandalf builders so seats honor the
 * dashboard knobs (and ~/.anchor/model_prefs.json) instead of hardcoding Claude.
 *
 * @param {object} [o]
 * @param {string[]} [o.codingRoles]  seats on CODING_FAMILY (plus `default`)
 * @param {string[]} [o.reviewRoles]  seats on REVIEW_FAMILY
 * @param {object}   [o.env]
 * @param {?string}  [o.reviewModel]  optional model pin on every review seat
 * @returns {{ routes: object, families: object, codingDriver: string, reviewDriver: string, drafterFamily: string, refuterFamily: string }}
 */
export function buildRoutesFromFamilies({
  codingRoles = ['synthesizer'],
  reviewRoles = ['shark', 'judge', 'review', 'reviewer', 'debate', 'refuter'],
  env = process.env,
  reviewModel = null,
} = {}) {
  const families = loadModelFamilies(env);
  const codingDriver = familyToDriverName(families.coding) || 'claude';
  const reviewDriver = familyToDriverName(families.review) || 'gemini-cli';
  const routes = { default: { driver: codingDriver } };
  for (const role of codingRoles) {
    const r = String(role || '').trim().toLowerCase();
    if (!r || r === 'default') continue;
    routes[r] = { driver: codingDriver };
  }
  for (const role of reviewRoles) {
    const r = String(role || '').trim().toLowerCase();
    if (!r) continue;
    const entry = { driver: reviewDriver };
    if (reviewModel) entry.model = reviewModel;
    routes[r] = entry;
  }
  return {
    routes: Object.freeze({ ...routes }),
    families,
    codingDriver,
    reviewDriver,
    drafterFamily: families.coding,
    refuterFamily: families.review,
  };
}

/**
 * Stamp TRIO_DRIVER_<ROLE> (and CODING_FAMILY / REVIEW_FAMILY) from prefs when
 * unset — so Foreman run-live and other env-driven seats pick up dashboard knobs
 * without a per-project models block. Never overwrites an explicit operator env.
 * @param {object} [env=process.env]
 * @returns {{ coding, review, cross_model }}
 */
export function applyFamilyPrefsToEnv(env = process.env) {
  const fams = loadModelFamilies(env);
  const codingDrv = familyToDriverName(fams.coding) || 'claude';
  const reviewDrv = familyToDriverName(fams.review) || 'gemini-cli';
  const roleMap = {
    EXECUTE: codingDrv,
    FIX: codingDrv,
    SYNTHESIZER: codingDrv,
    DEFAULT: codingDrv,
    REVIEW: reviewDrv,
    SHARK: reviewDrv,
    REVIEWER: reviewDrv,
    JUDGE: reviewDrv,
    DEBATE: reviewDrv,
    REFUTER: reviewDrv,
    GATE3: reviewDrv,
    VERIFY: reviewDrv,
    ATTACKER: reviewDrv,
    ANALYSIS: reviewDrv,
  };
  // Always stamp from Anchor prefs (overwrite stale setx TRIO_DRIVER_* pins).
  for (const [R, drv] of Object.entries(roleMap)) {
    env[`TRIO_DRIVER_${R}`] = drv;
  }
  env.CODING_FAMILY = fams.coding;
  env.REVIEW_FAMILY = fams.review;
  env.CROSS_MODEL = fams.cross_model ? 'true' : 'false';
  return fams;
}

/** name -> driver object. Seeded with the always-present Claude default. */
const REGISTRY = new Map([[claudeDriver.name, claudeDriver]]);

/**
 * Register (or replace) a backend. Wave 5's gemini/openai/grok modules call this.
 * @param {{name:string, subAgentCapable?:boolean, runAgent:Function}} driver
 */
export function registerDriver(driver) {
  if (!driver || typeof driver.name !== 'string' || typeof driver.runAgent !== 'function') {
    throw new TypeError('registerDriver requires a { name, runAgent } driver object');
  }
  REGISTRY.set(driver.name, driver);
  return driver;
}

// Wave 5: register the additive non-Claude backends. They live behind the same
// `runAgent` interface and are selected by `TRIO_DRIVER` (the Claude default is
// unaffected). Registering here (rather than self-registering on import) keeps the
// registry's contents explicit and order-stable for the capability matrix.
// `gemini-cli` is the sub-agent-capable Gemini HOST backend (login-based `gemini -p`);
// `gemini` remains the raw-HTTP API worker. Both register; they never collide on name.
registerDriver(geminiCliDriver);
registerDriver(geminiDriver);
registerDriver(openaiDriver);
registerDriver(grokDriver); // optional API-key HTTP backend (name: 'grok')
registerDriver(grokCliDriver); // subscription CLI backend (name: 'grok-cli') — coding/review family default
registerDriver(geminiCliNativeDriver);

/** The backend names currently registered (default `claude` always present). */
export function listDrivers() {
  return [...REGISTRY.keys()];
}

/**
 * The capability matrix: one row per registered backend describing whether it can
 * spawn real fresh sub-agent contexts (`subAgentCapable` — true only for the
 * CLI-spawning Claude backend; the raw-API backends approximate isolation with a
 * fresh stateless request) and HOW it produces structured output (CLI sub-agent
 * prompt vs JSON-mode / function-calling). Derived from the registered drivers so
 * a newly registered backend appears automatically.
 * @returns {{name:string, subAgentCapable:boolean, structuredOutput:string}[]}
 */
export function capabilityMatrix() {
  return [...REGISTRY.values()].map((d) => ({
    name: d.name,
    subAgentCapable: !!d.subAgentCapable,
    structuredOutput: d.structuredOutput ?? 'unknown',
  }));
}

/**
 * Resolve the active backend. Selection order: explicit `name` arg, then
 * `TRIO_DRIVER`, then the `claude` default. HALTs on an unknown name rather than
 * silently falling back, so a typo never quietly bills the wrong backend.
 * @param {?string} [name]
 * @param {object}  [env=process.env]
 */
export function getDriver(name = null, env = process.env) {
  const key = name || env.TRIO_DRIVER || DEFAULT_DRIVER;
  const driver = REGISTRY.get(key);
  if (!driver) {
    throw new HaltError(
      `unknown trio driver "${key}"`,
      `registered drivers: ${listDrivers().join(', ')}. Set TRIO_DRIVER to one of these (or leave it unset for the default "${DEFAULT_DRIVER}").`,
    );
  }
  return driver;
}

/**
 * The single engine seam. Dispatches to the selected backend's `runAgent`.
 * @param {object}  opts
 * @param {string}  opts.prompt
 * @param {object}  [opts.schema]        JSON Schema; when present the reply is parsed/validated
 * @param {boolean} [opts.freshContext]  request an isolated context (native for sub-agent-capable backends)
 * @param {string}  [opts.driver]        explicit backend name (overrides TRIO_DRIVER)
 * @returns {Promise<any>} model text, or the schema-validated object
 */
export async function runAgent(opts = {}) {
  // Driver selection order (2026-07-22 — Anchor prefs are universal source of truth):
  //   1. explicit opts.driver (per-call pin)
  //   2. CODING_FAMILY / REVIEW_FAMILY or ~/.anchor/model_prefs.json by role
  //   3. TRIO_DRIVER_<ROLE> (legacy setx — only if prefs did not resolve)
  //   4. TRIO_DRIVER / default claude
  // Stale TRIO_DRIVER_SHARK=gemini-cli setx must NOT outrank Anchor coding/review knobs.
  // Same-family coding+review is allowed; stamp cross_model from loadModelFamilies().
  let name = opts.driver;
  // Hermeticity guard (2026-07-25): an injected stub transport pins the matching
  // backend. Host model-prefs (~/.anchor/model_prefs.json) must NEVER re-route a
  // stubbed call to a live CLI — observed: driver-interface tests spawning real
  // billable sessions when prefs resolved coding=grok (usage-leak class, 07-14).
  if (!name) {
    if (opts.runClaude) name = 'claude';
    else if (opts.runGemini) name = 'gemini-cli';
    else if (opts.runGrokCli) name = 'grok-cli';
  }
  const role = String(opts.role || opts.label || '').split(/[:#.\s]/)[0];
  if (!name) {
    name = resolveDriverFromFamilies(role, process.env) || null;
  }
  if (!name && role) {
    const key = `TRIO_DRIVER_${role.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`;
    name = process.env[key] || null;
  }
  const driver = getDriver(name);
  return dispatchWithFailover(driver, opts);
}

/**
 * Dispatch to a backend, applying the universal MODEL-INTEGRITY FAILOVER (John 2026-07-17):
 * a NON-Claude seat that cannot deliver its ATTESTED requested model — silently substituted to a
 * fallback (e.g. GPT-OSS, how a rate-limited OR auth-degraded agy manifests) or a transport
 * failure — fails OVER to Claude ONE-NOTCH-BELOW-FRONTIER, honestly single-family
 * (`cross_model:false`), with a loud flag, rather than running the seat BLIND on the wrong model.
 * Used by BOTH `runAgent` AND `makeRoleRoutedAgent`, so EVERY trio+foundry call path inherits it.
 * A Claude seat has nowhere better to fail over to, so it re-throws.
 */
async function dispatchWithFailover(driver, opts) {
  try {
    return await driver.runAgent(opts);
  } catch (e) {
    if (e && e.seat_unavailable && driver.name !== 'claude') {
      const failoverModel = belowFrontierClaudeModel();
      const log = typeof opts.log === 'function' ? opts.log : () => {};
      log(`⚠ ${opts.label ?? opts.role ?? 'seat'}: ${driver.name} did NOT serve its attested model (requested="${e.requested_model ?? '?'}" served="${e.served_model ?? '?'}") — FAILING OVER to Claude ${failoverModel} (cross_model:false).`);
      return await getDriver('claude').runAgent({
        ...opts, driver: 'claude', model: failoverModel,
        cross_model: false, failed_over_from: { driver: driver.name, served: e.served_model ?? null },
      });
    }
    throw e;
  }
}

/**
 * Build a role-routed `agent(prompt, opts)` — the single missing primitive for mixed
 * per-role model routing (2026-07): dispatch each call to a backend+model chosen by
 * its role (from `opts.role`, else the label prefix before ':' / '#' / '.').
 *
 *   makeRoleRoutedAgent({ routes: {
 *     synthesizer: { driver: 'claude',     model: 'claude-fable-5' },
 *     judge:       { driver: 'claude',     model: 'claude-fable-5' },
 *     review:      { driver: 'gemini-cli', model: 'gemini-3.1-pro' },
 *     default:     { driver: 'claude' },
 *   }})
 *
 * Unrouted roles fall to `routes.default`, else the registry default. Extra opts
 * (env/target/log/runClaude stubs) thread through to the backend's runAgent.
 * @param {object} [o]
 * @param {Object<string,{driver?:string,model?:string}>} [o.routes]
 * @returns {(prompt:string, opts?:object)=>Promise<any>}
 */
export function makeRoleRoutedAgent({ routes = {}, ...baseOpts } = {}) {
  return (prompt, o = {}) => {
    const role = String(o.role || o.label || '').split(/[:#.\s]/)[0].toLowerCase();
    const route = routes[role] || routes.default || {};
    // Prefs-first: coding/review family (Anchor) wins unless the route table was
    // deliberately prefs-built (route.driver matches family) or caller pins model only.
    // Explicit empty routes {} → pure prefs. Explicit routes with drivers (tests / same-family
    // tables) still honor route.driver when present.
    const fromFamily = resolveDriverFromFamilies(role, process.env);
    const backend = getDriver(route.driver || fromFamily || null);
    return dispatchWithFailover(backend, {
      ...baseOpts, prompt, schema: o.schema, label: o.label,
      role: o.role ?? role ?? null, model: o.model ?? route.model ?? null, freshContext: true,
    });
  };
}

/**
 * Build Foreman's `{ execute, review, fix }` driver routed through the registry —
 * i.e. the foreman driver seam on top of the selected backend (default `claude`).
 * Foreman's `makeAgentDriver` already wraps an injected `agent()`; this is the
 * registry-level way to obtain that seam so the foreman build path goes through the
 * driver registry rather than calling `makeAgentDriver` directly.
 *
 * Two modes:
 *   - inject `agent`  — route an existing, already-instrumented `agent()` through
 *     the seam unchanged (used by `run-live.mjs`, whose live `claude -p` transport
 *     carries bespoke status logging that must stay byte-for-byte equivalent).
 *   - omit `agent`    — build the agent from the registry-selected backend, so
 *     `TRIO_DRIVER` (or an explicit `driver`) chooses the model the build sub-agents
 *     run on. Extra opts (e.g. an injected `runClaude` stub, `env`, `target`, `log`)
 *     thread through to the backend's `runAgent`.
 * @param {object}   [opts]
 * @param {string}   [opts.driver]      explicit backend name (overrides TRIO_DRIVER)
 * @param {Function} [opts.agent]       pre-built `agent(prompt, opts)` to route as-is
 * @param {object|false} [opts.reliability]  Wave-1 reliability-wrapper opts, or `false` to opt out
 * @returns {Promise<{execute:Function, review:Function, fix:Function}>}
 */
export async function makeForemanDriver({ driver, agent, reliability, ...opts } = {}) {
  const { makeAgentDriver } = await import('../foreman/bin/wave-workflow.js');
  let seamAgent = agent;
  // Provider key for the Wave-2 per-provider breaker: the selected backend's name when
  // we build the seam, else 'injected' for an already-instrumented agent. A sick backend
  // is then degraded under its OWN bucket, never globally.
  let providerName = 'injected';
  if (!seamAgent) {
    const backend = getDriver(driver);
    providerName = backend.name;
    // Forward role + model to the backend so the per-role model tier (e.g.
    // TRIO_MODEL_<ROLE>/TRIO_DRIVER_<ROLE>, resolved in the driver ladder) is actually
    // reachable on the Foreman build path. A DESIGNATED role/model on makeForemanDriver
    // (its own `opts`) WINS over the per-call wave step (`o`): when a caller builds a
    // Foreman driver pinned to a seat — e.g. { driver, role:'judge', model:'m' } — that
    // designation must reach the backend, not be shadowed by the wave step's own
    // 'execute'/'review'/'fix' role. Only when no designation is set does the per-call
    // value flow through (the normal Foreman build path passes neither, so wave-step
    // role/model behave exactly as before). Backends that ignore role/model (e.g. the
    // Claude session-default driver) are unaffected either way.
    seamAgent = (prompt, o = {}) =>
      backend.runAgent({
        ...opts, prompt, schema: o.schema, label: o.label,
        role: opts.role ?? o.role, model: opts.model ?? o.model, freshContext: true,
      });
  }
  // Wave 1: apply the reliability wrapper at THIS agent-injection boundary (both the
  // injected-agent and built-backend modes), so the Foreman build path gets typed
  // retry + round-aware idempotency. Transparent on the success path; pass
  // `reliability:false` to opt out.
  //
  // Wave 2: default a LIGHT per-provider breaker (keyed by the backend name) on so a
  // sick provider degrades for the session instead of being hammered — still inert
  // until N consecutive recoverable failures, so a healthy build is unaffected. The
  // idle sliver + anti-laundering telemetry stay opt-in via the `reliability` config
  // (live wiring of stdout-heartbeat / a telemetry sink is the runner's job). Any of
  // these can be overridden — or the breaker disabled with `reliability:{breaker:false}`.
  const reliableSeam = reliability === false
    ? seamAgent
    : makeReliableAgent({ agent: seamAgent, provider: providerName, breaker: {}, ...(reliability || {}) });
  return makeAgentDriver({ agent: reliableSeam });
}

export { claudeDriver, geminiCliDriver, geminiDriver, openaiDriver, grokDriver };

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
// `schema` is supplied (every backend retries once, then fails honestly).

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
import { chatgptCliDriver } from './chatgpt-cli.mjs';
import { normalizeRole, isVerificationRole, VERIFICATION_ROLES } from './roles.mjs';
import { PHYSICAL_RECEIPT_HOOK } from './seat-contract.mjs';
const DEFAULT_DRIVER = process.env.ANTIGRAVITY_AGENT ? 'gemini-cli' : 'claude';

// Roles whose seats are filled by REVIEW_FAMILY (adversarial / judge / check).
// Everything else defaults to CODING_FAMILY (code / reason / orchestrate).
export const REVIEW_ROLES = VERIFICATION_ROLES;
export { normalizeRole, isVerificationRole, VERIFICATION_ROLES } from './roles.mjs';

/** Map a model family name (claude|gemini|grok|chatgpt) → registered trio driver name. */
export function familyToDriverName(family) {
  const f = String(family || '').trim().toLowerCase();
  if (f === 'gemini') return 'gemini-cli';
  // Subscription Grok Build CLI (`grok -p`) — NOT the raw xAI HTTP API (`grok` driver).
  if (f === 'grok') return 'grok-cli';
  // Subscription Codex CLI (`codex exec`) — NOT the raw OpenAI HTTP API (`openai` driver).
  if (f === 'chatgpt' || f === 'codex') return 'chatgpt-cli';
  if (f === 'claude' || !f) return 'claude';
  return null;
}

/**
 * Read coding/review families from Anchor's durable settings/mirror only.
 * Legacy process family variables are outputs for child compatibility, never
 * an input that may outrank or replace the user's saved preference.
 */
const VALID_MODEL_FAMILIES = new Set(['claude', 'gemini', 'grok', 'chatgpt']);

function readPrefsFile(file) {
  if (!file || !fs.existsSync(file)) return null;
  let raw;
  try {
    raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    throw new HaltError(
      `Anchor model preferences are unreadable: ${file}`,
      `repair the JSON preference store (${error.message}); family routing will not guess`,
    );
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new HaltError(
      `Anchor model preferences are invalid: ${file}`,
      'expected a JSON object; family routing will not guess',
    );
  }
  for (const key of ['coding_family', 'review_family']) {
    const value = raw[key];
    if (value !== undefined && !VALID_MODEL_FAMILIES.has(String(value).trim().toLowerCase())) {
      throw new HaltError(
        `unknown ${key} "${value}" in ${file}`,
        `expected one of ${[...VALID_MODEL_FAMILIES].join('|')}`,
      );
    }
  }
  return raw;
}

export function loadModelFamilies(env = process.env) {
  const home = env.USERPROFILE || env.HOME || '';
  const mirrorPath = home ? path.join(home, '.anchor', 'model_prefs.json') : null;
  const settingsPath = String(env.ANCHOR_DATA_DIR || '').trim()
    ? path.join(String(env.ANCHOR_DATA_DIR).trim(), 'settings.json')
    : null;
  const settings = readPrefsFile(settingsPath);
  const needsMirror = !settings
    || settings.coding_family === undefined
    || settings.review_family === undefined;
  // `primary_path` in the mirror is informational. It never redirects this read.
  const mirror = needsMirror ? readPrefsFile(mirrorPath) : null;
  const selected = (key, historicalDefault) => {
    const value = settings?.[key] ?? mirror?.[key] ?? historicalDefault;
    return String(value).trim().toLowerCase();
  };
  const coding = selected('coding_family', 'claude');
  // (2026-09-04, John) no prefs anywhere ⇒ single-family Claude, honestly stamped — never a Gemini
  // seat nobody selected (the dashboard is the source; this default only covers a host with
  // no Anchor settings and no mirror).
  const review = selected('review_family', 'claude');
  const source = settings
    ? settingsPath
    : mirror
      ? mirrorPath
      : 'historical-default';
  return {
    coding,
    review,
    cross_model: coding !== review,
    source,
  };
}

/**
 * Resolve driver name from Anchor coding/review family prefs for a role.
 * Explicit TRIO_DRIVER / opts.driver still win over this (callers apply order).
 * @returns {?string} registered driver name or null
 */
export function resolveDriverFromFamilies(role, env = process.env) {
  const r = normalizeRole(
    role && typeof role === 'object' ? role : { role },
  );
  const fams = loadModelFamilies(env);
  const family = isVerificationRole({ role: r }) ? fams.review : fams.coding;
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
  reviewRoles = [...VERIFICATION_ROLES],
  env = process.env,
  reviewModel = null,
} = {}) {
  const families = loadModelFamilies(env);
  const codingDriver = familyToDriverName(families.coding) || 'claude';
  const reviewDriver = familyToDriverName(families.review) || 'claude';
  const routes = { default: { driver: codingDriver } };
  for (const role of codingRoles) {
    const r = normalizeRole({ role });
    if (!r || r === 'default') continue;
    routes[r] = { driver: codingDriver };
  }
  for (const role of reviewRoles) {
    const r = normalizeRole({ role });
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
  const reviewDrv = familyToDriverName(fams.review) || 'claude';
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
registerDriver(chatgptCliDriver); // subscription Codex CLI (name: 'chatgpt-cli') — ChatGPT login, never OPENAI_API_KEY

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

const RECEIPT_FAMILIES = new Set(['claude', 'gemini', 'grok', 'chatgpt']);

function bounded(value, fallback = '', max = 240) {
  const clean = String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim();
  return (clean || fallback).slice(0, max);
}

function errorInfo(code, message = '') {
  return {
    code: bounded(code, 'seat_unavailable'),
    message: bounded(message, '', 500),
  };
}

function requestedFamilyForDriver(name) {
  const driverName = String(name || '').trim().toLowerCase();
  if (driverName === 'claude') return 'claude';
  if (driverName === 'gemini' || driverName.startsWith('gemini-cli')) return 'gemini';
  if (driverName === 'grok' || driverName === 'grok-cli') return 'grok';
  if (driverName === 'openai' || driverName === 'chatgpt-cli') return 'chatgpt';
  return 'unknown';
}

function requestedFor(driver, opts, entries = []) {
  const rawRequested = entries
    .map((entry) => entry?.receipt?.requested_model)
    .find((value) => typeof value === 'string' && value.trim());
  const explicit = typeof opts.model === 'string' && opts.model.trim() ? opts.model : null;
  return {
    driver: bounded(driver.name, 'unknown-driver'),
    family: requestedFamilyForDriver(driver.name),
    model: bounded(rawRequested ?? explicit, '', 240) || null,
  };
}

function servedFromRaw(raw, driverName, { accepted = false } = {}) {
  if (!raw || typeof raw !== 'object') return null;
  const nested = raw.served && typeof raw.served === 'object' ? raw.served : null;
  const familyValue = nested?.family ?? raw.model_family ?? null;
  const normalizedFamily = typeof familyValue === 'string'
    ? familyValue.trim().toLowerCase()
    : null;
  const familyAttested = (nested?.family_attested === true || raw.family_attested === true)
    && RECEIPT_FAMILIES.has(normalizedFamily);
  const modelValue = nested?.model ?? raw.model_served ?? null;
  const normalizedModel = typeof modelValue === 'string' && modelValue.trim()
    ? modelValue.trim().slice(0, 240)
    : null;
  const modelAttested = (nested?.model_attested === true || raw.model_attested === true)
    && normalizedModel !== null;
  if (!accepted && !familyAttested && !modelAttested) return null;
  return {
    driver: bounded(nested?.driver ?? driverName, 'unknown-driver'),
    family: familyAttested ? normalizedFamily : null,
    model: modelAttested ? normalizedModel : null,
    family_attested: familyAttested,
    model_attested: modelAttested,
  };
}

function normalizeTransportEntry(entry, ordinal, driverName, fallbackLabel) {
  const raw = entry?.receipt && typeof entry.receipt === 'object' ? entry.receipt : null;
  const kind = ordinal === 2 ? 'schema_reprompt' : 'initial';
  const label = bounded(entry?.label ?? raw?.label, fallbackLabel || '(unlabeled)');
  let status = entry?.outcome;
  if (!['accepted', 'schema_rejected', 'seat_unavailable', 'aborted'].includes(status)) {
    status = raw?.status === 'aborted' || raw?.aborted === true
      ? 'aborted'
      : raw?.ok === true
        ? 'accepted'
        : 'seat_unavailable';
  }
  if (!raw) status = 'seat_unavailable';
  if (raw && raw.ok !== true && (status === 'accepted' || status === 'schema_rejected')) {
    status = raw.status === 'aborted' || raw.aborted === true ? 'aborted' : 'seat_unavailable';
  }
  const acceptedProvider = raw?.ok === true;
  const served = servedFromRaw(raw, driverName, {
    accepted: acceptedProvider && (status === 'accepted' || status === 'schema_rejected'),
  });
  let error = null;
  if (status === 'schema_rejected') {
    error = errorInfo('schema_nonconforming', entry?.error || 'provider reply did not conform to the requested schema');
  } else if (status === 'aborted') {
    error = errorInfo('aborted', raw?.error || entry?.error || 'transport aborted');
  } else if (status === 'seat_unavailable') {
    const code = raw ? (raw.status || 'seat_unavailable') : 'missing_raw_receipt';
    error = errorInfo(code, raw?.error || entry?.error || (raw
      ? 'provider transport did not complete successfully'
      : 'driver returned or threw without a physical transport receipt'));
  }
  return {
    ordinal,
    kind,
    label,
    ok: status === 'accepted',
    status,
    provider_status: raw?.kill_status === 'kill_failed'
      ? 'kill_failed'
      : raw?.status != null
        ? bounded(raw.status, '', 240) || null
        : null,
    served,
    error,
  };
}

const PHYSICAL_OUTCOMES = new Set([
  'accepted', 'schema_rejected', 'seat_unavailable', 'aborted',
]);

function physicalSequenceError(entries, count) {
  if (count > 2) return `driver reported ${count} physical attempts; maximum is two`;
  for (const [index, entry] of entries.entries()) {
    if (!entry || typeof entry !== 'object' || !PHYSICAL_OUTCOMES.has(entry.outcome)) {
      return `physical attempt ${index + 1} has an invalid outcome`;
    }
  }
  if (entries[0]?.kind !== 'initial') return 'first physical attempt must be initial';
  if (entries.length === 2) {
    if (entries[0].outcome !== 'schema_rejected') {
      return 'a second physical attempt requires an initial schema_rejected outcome';
    }
    if (entries[1].kind !== 'schema_reprompt') {
      return 'second physical attempt must be schema_reprompt';
    }
  }
  return null;
}

async function runDispatcherAttempt(driver, opts, ordinal, kind) {
  const entries = [];
  let physicalCount = 0;
  let usedPhysicalHook = false;
  let value;
  let thrown = null;
  if (opts.signal?.aborted) {
    entries.push({
      outcome: 'aborted', label: opts.label,
      receipt: { ok: false, status: 'aborted', aborted: true, error: 'seat aborted before spawn' },
    });
    thrown = Object.assign(new Error('seat aborted before spawn'), { aborted: true });
  } else {
    try {
      value = await driver.runAgent({
        ...opts,
        onReceipt: undefined,
        [PHYSICAL_RECEIPT_HOOK]: (entry) => {
          usedPhysicalHook = true;
          physicalCount += 1;
          if (entries.length < 2) entries.push(entry);
          // Tee to a caller-supplied hook: the public trio.seat.v1 receipt keeps its
          // exact-key shape (strict consumers validate it), so measured usage on the
          // raw physical receipt is only reachable through this opt-in channel.
          const callerHook = opts[PHYSICAL_RECEIPT_HOOK];
          if (typeof callerHook === 'function') {
            try { callerHook(entry); } catch { /* observer must never break the seat */ }
          }
        },
      });
    } catch (error) {
      thrown = error;
      if (entries.length === 0 && error?.raw_receipt) {
        entries.push({ receipt: error.raw_receipt, label: opts.label });
      }
    }
  }
  const contractError = usedPhysicalHook
    ? physicalSequenceError(entries, physicalCount)
    : null;
  if (entries.length === 0) {
    entries.push({ receipt: null, label: opts.label, error: thrown?.message });
  }
  const requested = requestedFor(driver, opts, contractError ? [] : entries);
  const transportAttempts = contractError
    ? [{
      ordinal: 1,
      kind: 'initial',
      label: bounded(opts.label, '(unlabeled)'),
      ok: false,
      status: 'seat_unavailable',
      provider_status: null,
      served: null,
      error: errorInfo('invalid_physical_receipt_sequence', contractError),
    }]
    : entries.map((entry, index) => normalizeTransportEntry(
      entry,
      index + 1,
      driver.name,
      index === 0 ? opts.label : `${opts.label}#retry`,
    ));
  const last = transportAttempts.at(-1);
  const verification = isVerificationRole({ role: opts.role, label: opts.label });
  let status;
  let served = null;
  let error = null;
  if (contractError) {
    status = 'seat_unavailable';
    error = errorInfo('invalid_physical_receipt_sequence', contractError);
  } else if (thrown?.aborted || last.status === 'aborted') {
    status = 'aborted';
    error = errorInfo('aborted', thrown?.message || last.error?.message || 'transport aborted');
  } else if (thrown) {
    status = transportAttempts.length === 2
      && transportAttempts.every((attempt) => attempt.status === 'schema_rejected')
      ? 'schema_exhausted'
      : 'seat_unavailable';
    error = errorInfo(
      status === 'schema_exhausted' ? 'schema_nonconforming' : (thrown.seat_status || 'seat_unavailable'),
      thrown.message,
    );
  } else if (last.status !== 'accepted') {
    status = transportAttempts.length === 2
      && transportAttempts.every((attempt) => attempt.status === 'schema_rejected')
      ? 'schema_exhausted'
      : last.status === 'aborted'
        ? 'aborted'
        : 'seat_unavailable';
    error = errorInfo(last.error?.code || 'seat_unavailable', last.error?.message || 'transport failed');
  } else if (verification && !last.served?.family_attested) {
    status = 'seat_unavailable';
    error = errorInfo('served_unattested', 'verification requires an attested served family');
  } else {
    // (John, 2026-09-05) a verification seat whose FAMILY is attested but whose served MODEL
    // is not (the Codex CLI names no model; Grok plain output did not) is ACCEPTED with the
    // honest stamp `model_attested:false` on its receipt — family independence is what a
    // reviewer must prove; the model tier is stamped, never inferred. Said on the log so no
    // run is blind to it. A family that cannot be attested still fails closed above.
    if (verification && !last.served?.model_attested) {
      const say = typeof opts.log === 'function' ? opts.log : () => {};
      say(`⚠ ${opts.label ?? opts.role ?? 'seat'}: ${driver.name} verification seat served family "${last.served?.family ?? '?'}" with an UNATTESTED model — accepted, stamped model_attested:false`);
    }
    status = transportAttempts.length === 2 ? 'success_after_schema_reprompt' : 'success';
    served = last.served;
  }
  const ok = status === 'success' || status === 'success_after_schema_reprompt';
  return {
    value,
    attempt: {
      ordinal,
      kind,
      requested,
      ok,
      status,
      served: ok ? served : null,
      transport_attempts: transportAttempts,
      error: ok ? null : error,
    },
  };
}

export class ReceiptCallbackError extends Error {
  constructor(cause, receipt) {
    super(`Trio receipt callback failed: ${cause?.message ?? cause}`);
    this.name = 'ReceiptCallbackError';
    this.cause = cause;
    this.receipt = receipt;
  }
}

function failedSeatError(receipt) {
  const error = new HaltError(
    `trio seat ${receipt.status}: ${receipt.label}`,
    receipt.error?.message || 'inspect the attached trio.seat.v1 receipt',
  );
  error.receipt = receipt;
  error.aborted = receipt.status === 'aborted';
  if (!error.aborted) error.seat_unavailable = true;
  error.seat_status = receipt.status;
  error.requested_model = receipt.requested.model;
  error.served_model = null;
  return error;
}

function finalizeReceipt({ opts, role, verification, requested, attempts, status, served, error }) {
  return {
    schema: 'trio.seat.v1',
    ok: status === 'success' || status === 'success_after_failover',
    status,
    label: bounded(opts.label, role || requested.driver || '(unlabeled)'),
    role,
    verification,
    structured: !!opts.schema,
    requested,
    served,
    attempts,
    failover: {
      allowed: !verification,
      used: attempts.length === 2,
      blocked_reason: verification
        ? 'verification_seat'
        : status === 'seat_unavailable' && attempts.length === 1
          ? 'no_capable_fallback'
          : null,
    },
    error,
  };
}

/**
 * The single engine seam. Dispatches to the selected backend's `runAgent`.
 * @param {object}  opts
 * @param {string}  opts.prompt
 * @param {object}  [opts.schema]        JSON Schema; when present the reply is parsed/validated
 * @param {boolean} [opts.freshContext]  request an isolated context (native for sub-agent-capable backends)
 * @param {string}  [opts.driver]        explicit backend name (overrides TRIO_DRIVER)
 * @param {string}  [opts.role]          explicit seat role; wins over label derivation
 * @param {string}  [opts.label]         bounded diagnostic label and role fallback
 * @param {string}  [opts.model]         requested model identity (never a served assertion)
 * @param {AbortSignal} [opts.signal]    supervisor cancellation signal
 * @param {Function} [opts.onReceipt]    awaited once with the successful final trio.seat.v1 receipt
 * @returns {Promise<any>} model text, or the schema-validated object
 */
export async function runAgent(opts = {}) {
  // Driver selection order (2026-07-22 — Anchor prefs are universal source of truth):
  //   1. explicit opts.driver (per-call pin)
  //   2. Anchor settings.json / ~/.anchor/model_prefs.json by role
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
    else if (opts.runCodexCli) name = 'chatgpt-cli';
  }
  const activeEnv = opts.env ?? process.env;
  const role = normalizeRole({ role: opts.role, label: opts.label });
  if (!name) {
    name = resolveDriverFromFamilies({ role, label: opts.label }, activeEnv) || null;
  }
  if (!name && role) {
    const key = `TRIO_DRIVER_${role.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`;
    name = activeEnv[key] || null;
  }
  const driver = getDriver(name, activeEnv);
  return dispatchWithFailover(driver, { ...opts, role });
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
  const role = normalizeRole({ role: opts.role, label: opts.label });
  const verification = isVerificationRole({ role, label: opts.label });
  const primary = await runDispatcherAttempt(driver, { ...opts, role }, 1, 'primary');
  const attempts = [primary.attempt];
  let finalValue = primary.value;
  let status;
  let served = null;
  let topError = null;

  if (primary.attempt.ok) {
    status = 'success';
    served = primary.attempt.served;
  } else if (primary.attempt.status === 'aborted' || opts.signal?.aborted) {
    status = 'aborted';
    topError = errorInfo('aborted', primary.attempt.error?.message || 'logical dispatch aborted');
  } else if (verification) {
    status = 'verification_fail_closed';
    topError = errorInfo(
      primary.attempt.error?.code || 'seat_unavailable',
      primary.attempt.error?.message || 'verification seat failed closed',
    );
  } else if (driver.name === 'claude') {
    status = 'seat_unavailable';
    topError = errorInfo(
      primary.attempt.error?.code || 'seat_unavailable',
      primary.attempt.error?.message || 'no capable coding fallback is available',
    );
  } else {
    const fallbackDriver = getDriver('claude', opts.env ?? process.env);
    const failoverModel = belowFrontierClaudeModel();
    const log = typeof opts.log === 'function' ? opts.log : () => {};
    log(`⚠ ${opts.label ?? role ?? 'seat'}: ${driver.name} seat failed — FAILING OVER to Claude ${failoverModel} (cross_model:false).`);
    if (opts.signal?.aborted) {
      status = 'aborted';
      topError = errorInfo('aborted', 'logical dispatch aborted before fallback');
    } else {
      const fallback = await runDispatcherAttempt(fallbackDriver, {
        ...opts,
        role,
        driver: 'claude',
        model: failoverModel,
        cross_model: false,
        failed_over_from: {
          driver: driver.name,
          served: primary.attempt.transport_attempts.at(-1)?.served?.model ?? null,
        },
      }, 2, 'fallback');
      attempts.push(fallback.attempt);
      finalValue = fallback.value;
      if (fallback.attempt.ok) {
        status = 'success_after_failover';
        served = fallback.attempt.served;
      } else if (fallback.attempt.status === 'aborted') {
        status = 'aborted';
        topError = errorInfo('aborted', fallback.attempt.error?.message || 'fallback aborted');
      } else {
        status = 'seat_unavailable';
        topError = errorInfo(
          fallback.attempt.error?.code || 'seat_unavailable',
          fallback.attempt.error?.message || 'fallback seat unavailable',
        );
      }
    }
  }

  const receipt = finalizeReceipt({
    opts,
    role,
    verification,
    requested: primary.attempt.requested,
    attempts,
    status,
    served,
    error: topError,
  });
  if (!receipt.ok) throw failedSeatError(receipt);
  if (typeof opts.onReceipt === 'function') {
    try {
      await opts.onReceipt(receipt);
    } catch (error) {
      throw new ReceiptCallbackError(error, receipt);
    }
  }
  return finalValue;
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
    const role = normalizeRole({ role: o.role, label: o.label });
    const roleRoute = routes[role] || null;
    // A generic coding default may never capture a canonical verification seat.
    const route = roleRoute || (isVerificationRole({ role }) ? {} : (routes.default || {}));
    // Prefs-first: coding/review family (Anchor) wins unless the route table was
    // deliberately prefs-built (route.driver matches family) or caller pins model only.
    // Explicit empty routes {} → pure prefs. Explicit routes with drivers (tests / same-family
    // tables) still honor route.driver when present.
    const activeEnv = baseOpts.env ?? process.env;
    const fromFamily = resolveDriverFromFamilies({ role, label: o.label }, activeEnv);
    return runAgent({
      ...baseOpts,
      prompt,
      driver: roleRoute?.driver || (isVerificationRole({ role })
        ? fromFamily
        : (route.driver || fromFamily)) || null,
      schema: o.schema,
      label: o.label,
      role,
      model: o.model ?? route.model ?? null,
      freshContext: true,
      timeoutMs: o.timeoutMs ?? baseOpts.timeoutMs,
      sandbox: o.sandbox ?? baseOpts.sandbox,
      reasoningEffort: o.reasoningEffort ?? baseOpts.reasoningEffort,
      orchestrationMode: o.orchestrationMode ?? baseOpts.orchestrationMode,
      onReceipt: o.onReceipt ?? baseOpts.onReceipt,
      signal: o.signal ?? baseOpts.signal,
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
    seamAgent = (prompt, o = {}) => runAgent({
      ...opts,
      prompt,
      driver: backend.name,
      schema: o.schema,
      label: o.label,
      role: opts.role ?? o.role,
      model: opts.model ?? o.model,
      timeoutMs: o.timeoutMs ?? opts.timeoutMs,
      onReceipt: o.onReceipt ?? opts.onReceipt,
      signal: o.signal ?? opts.signal,
      freshContext: true,
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

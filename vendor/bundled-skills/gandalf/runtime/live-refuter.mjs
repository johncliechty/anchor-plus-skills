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
// NOTE (2026-08-31 Fable review): refuters are READ-ONLY verification seats (agy
// --readonly), so they CANNOT write the heartbeat file the swarm look-in supervisor
// reads — wired blind, superviseSeat killed healthy slow refuters at wall-clock and
// respawned a second paid call while the first still ran. The look-in (appendix +
// supervisor) is therefore unwired on this path; the driver's own timeout bounds a
// hung seat. Re-wire only with a heartbeat channel a read-only seat can actually use.

/** The drafter family (who authored the drafted claims) and the refuter family (who runs the
 *  independent refutation) for the reference W3 topology: Claude drafts, Gemini refutes. */
export const DRAFTER_FAMILY = 'claude';
export const REFUTER_FAMILY = 'gemini';
export const CANONICAL_CLAUDE_REFUTER_MODEL = 'claude-fable-5-2';
export const MAX_REFUTER_CONCURRENCY = 2;

export class RefuterConcurrencyBoundError extends RangeError {
  constructor(requested, bound = MAX_REFUTER_CONCURRENCY) {
    super(
      `BOUND_EXCEEDED_REFUSAL: GANDALF_REFUTER_CONCURRENCY=${JSON.stringify(requested)} is outside the allowed bound [1, ${bound}] (max_concurrency <= ${bound}).`
    );
    this.name = 'RefuterConcurrencyBoundError';
    this.code = 'BOUND_EXCEEDED_REFUSAL';
    this.requested = requested;
    this.bound = bound;
  }
}

export class ClaudeFableAttestationError extends Error {
  constructor(servedModel, requestedModel = CANONICAL_CLAUDE_REFUTER_MODEL, label = 'refuter') {
    super(
      `Claude refuter attestation mismatch (${label}): requested ${requestedModel} with positive attestation, served ${JSON.stringify(servedModel ?? 'unattested')}`
    );
    this.name = 'ClaudeFableAttestationError';
    this.code = 'ATTESTATION_MISMATCH';
    this.status = 'attestation_mismatch';
    this.requested_model = requestedModel;
    this.model_served = servedModel ?? null;
  }
}

export function resolveRefuterConcurrency({ maxConcurrency = undefined, env = process.env } = {}) {
  const raw = maxConcurrency !== undefined && maxConcurrency !== null
    ? maxConcurrency
    : env?.GANDALF_REFUTER_CONCURRENCY;
  if (raw === undefined || raw === null || String(raw).trim() === '') {
    return MAX_REFUTER_CONCURRENCY;
  }
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > MAX_REFUTER_CONCURRENCY) {
    throw new RefuterConcurrencyBoundError(raw, MAX_REFUTER_CONCURRENCY);
  }
  return parsed;
}

const DATED_CLAUDE_FABLE_RE = /^claude-fable-5-2(?:-\d{8}|-\d{4}-\d{2}-\d{2})?$/;

function normalizeClaudeFableId(modelId) {
  if (typeof modelId !== 'string') return modelId;
  const trimmed = modelId.trim();
  return DATED_CLAUDE_FABLE_RE.test(trimmed) ? 'claude-fable-5-2' : trimmed;
}

function normalizeFamilyToken(family) {
  const s = String(family || '').trim().toLowerCase();
  if (!s) return null;
  if (s === 'chatgpt' || s === 'codex') return 'openai';
  return s;
}

export function verifyClaudeFableAttestation(receiptOrReply, {
  requestedModel = CANONICAL_CLAUDE_REFUTER_MODEL,
  label = 'refuter',
} = {}) {
  const rec = receiptOrReply?.served
    ? {
      model_served: receiptOrReply.served.model ?? null,
      model_attested: receiptOrReply.served.model_attested === true,
      family_attested: receiptOrReply.served.family_attested === true,
    }
    : receiptOrReply;
  const rawServed = typeof rec?.model_served === 'string' && rec.model_served.trim()
    ? rec.model_served.trim()
    : null;
  const served = rawServed ? normalizeClaudeFableId(rawServed) : null;
  const normalizedRequested = normalizeClaudeFableId(requestedModel);
  const attested = rec?.model_attested === true;
  if (!attested || served !== normalizedRequested) {
    throw new ClaudeFableAttestationError(rawServed, normalizedRequested, label);
  }
  return {
    requested_model: normalizedRequested,
    model_served: served,
    model_attested: true,
    family_attested: rec?.family_attested !== false,
  };
}

/** Test/fixture only: historical Claude+Gemini table. Live production MUST omit routes
 *  (or call `buildDefaultRefuterRoutes`) so seats follow coding/review prefs — never pin Claude in launchers. */
export const DEFAULT_REFUTER_ROUTES = Object.freeze({
  refuter: { driver: 'gemini-cli', model: 'Gemini 3.1 Pro (High)' },
  default: { driver: 'claude' },
});

/**
 * Prefs-aware Gandalf/Jumper route table: refuter → REVIEW_FAMILY; default/drafter → CODING_FAMILY.
 * When review family resolves to Claude, explicitly pin `claude-fable-5-2` (never `--model best`).
 * @param {object} [env=process.env]
 */
export async function buildDefaultRefuterRoutes(env = process.env) {
  const { buildRoutesFromFamilies } = await import('../../drivers/index.mjs');
  const { isVariableStrengthActive, resolveSkillStrength } = await import('../../drivers/model-policy.mjs');
  const built = buildRoutesFromFamilies({
    env,
    codingRoles: [],
    reviewRoles: ['refuter'],
  });
  if (built.reviewDriver === 'claude') {
    const vsActive = isVariableStrengthActive({ settings: built.families, env });
    const effStrength = vsActive
      ? resolveSkillStrength({
          skill: 'gandalf',
          explicitStrength: env?.ANCHOR_STRENGTH ?? env?.TRIO_TIER,
          inheritedStrength: env?.ANCHOR_INHERITED_STRENGTH,
          cockpitStrength: env?.ANCHOR_COCKPIT_STRENGTH,
          defaultStrength: built.families?.model_policy?.default_strength || 'standard',
        })
      : 'heavy';
    const refuterClaudeModel = effStrength === 'heavy' ? CANONICAL_CLAUDE_REFUTER_MODEL : 'claude-opus-5-5';
    return {
      ...built,
      routes: Object.freeze({
        ...built.routes,
        refuter: { driver: 'claude', model: refuterClaudeModel },
      }),
    };
  }
  return built;
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
  const payload = isPlainObject(reply.value) ? reply.value : reply;
  return { defeater: payload.defeater, survived: payload.survived, verdict: payload.verdict };
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
  drafterFamily = undefined,
  refuterFamily = undefined,
  budget = REFUTER_BUDGET_R,
  maxConcurrency = undefined,
  env = process.env,
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
  const effectiveDrafterFamily = String(
    drafterFamily || agent._resolvedMeta?.drafterFamily || DRAFTER_FAMILY
  ).trim().toLowerCase();
  // INVARIANT 3 — routing guard: a refuter role must resolve to a NON-drafter family (never self-review).
  const routedFamily = routes
    ? assertCrossFamilyRouting({ routes, drafterFamily: effectiveDrafterFamily })
    : null;
  const effectiveRefuterFamily = String(
    refuterFamily || routedFamily || agent._resolvedMeta?.refuterFamily || REFUTER_FAMILY
  ).trim().toLowerCase();
  if (effectiveRefuterFamily === effectiveDrafterFamily) {
    throw new SelfRefutationHalt(effectiveRefuterFamily, effectiveDrafterFamily, routes?.refuter?.driver || null);
  }
  const cap = resolveRefuterConcurrency({ maxConcurrency, env });

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
  // encode the same host fact); GANDALF_REFUTER_CONCURRENCY overrides, ceiling 2.
  // Determinism: results are placed by INDEX, dispatch is sorted by index, and the
  // ledger mints in-process — output is order-independent of completion order.
  const seatReceipts = [];

  const refuteOne = async (i) => {
    const raw = rawElevations[i];
    // INVARIANT 2 — the object the GATE will read. We mint on THIS exact object and place it in the
    // returned draft, so elevationIdentity(bound) at mint === elevationIdentity(bound) at the gate.
    const bound = { ...raw };
    const label = `refuter:${raw.id ?? `e${i}`}`;
    const claudeTargetModel = routes?.refuter?.model || CANONICAL_CLAUDE_REFUTER_MODEL;
    const requestedModel = effectiveRefuterFamily === 'claude'
      ? claudeTargetModel
      : (routes?.refuter?.model ?? null);
    let capturedReceipt = null;
    try {
      const callOpts = {
        role,
        label,
        schema: REFUTER_REPLY_SCHEMA,
        ...(effectiveRefuterFamily === 'claude' ? { model: claudeTargetModel } : {}),
        onReceipt: (r) => { capturedReceipt = r; },
      };
      const reply = await agent(refutePrompt(raw), callOpts);
      const receiptSource = capturedReceipt
        ?? reply?.receipt
        ?? reply?._receipt
        ?? (isPlainObject(reply) && ('served' in reply || 'model_served' in reply || 'model_attested' in reply) ? reply : null);

      let servedModel = receiptSource?.served?.model ?? receiptSource?.model_served ?? null;
      let modelAttested = receiptSource?.served?.model_attested === true || receiptSource?.model_attested === true;
      let familyAttested = receiptSource?.served?.family_attested === true
        || receiptSource?.family_attested === true
        || modelAttested;

      if (effectiveRefuterFamily === 'claude') {
        const verified = verifyClaudeFableAttestation(receiptSource, {
          requestedModel: claudeTargetModel,
          label,
        });
        servedModel = verified.model_served;
        modelAttested = verified.model_attested;
        familyAttested = verified.family_attested;
      } else {
        const rawServedFamily = receiptSource?.served?.family ?? receiptSource?.model_family ?? null;
        const normServedFamily = normalizeFamilyToken(rawServedFamily);
        if (normServedFamily) {
          if (normServedFamily === normalizeFamilyToken(effectiveDrafterFamily)) {
            throw new SelfRefutationHalt(rawServedFamily, effectiveDrafterFamily, routes?.refuter?.driver || null);
          }
          if (normServedFamily !== normalizeFamilyToken(effectiveRefuterFamily)) {
            return {
              index: i,
              bound,
              entry: {
                index: i,
                id: raw.id ?? null,
                minted: false,
                requested_model: requestedModel,
                model_served: servedModel,
                model_attested: modelAttested,
                reason: `refuter family mismatch: expected ${effectiveRefuterFamily}, served ${rawServedFamily}`,
              },
            };
          }
        }
      }

      seatReceipts.push({
        label,
        family: effectiveRefuterFamily,
        requested_model: requestedModel,
        model_served: servedModel,
        model_attested: modelAttested,
        family_attested: familyAttested,
      });

      const { defeater, survived, verdict } = extractRefuterVerdict(reply);

      // INVARIANT 4 — survived must be an EXPLICIT boolean and defeater a NAMED concrete defeater;
      // anything else ⇒ NO provenance ⇒ the host floors the elevation to SPECULATIVE (honest floor).
      if (typeof survived !== 'boolean' || !isNamedDefeater(defeater)) {
        return {
          index: i,
          bound,
          entry: {
            index: i,
            id: raw.id ?? null,
            minted: false,
            requested_model: requestedModel,
            model_served: servedModel,
            model_attested: modelAttested,
            reason: 'refuter returned no explicit survived boolean and/or no named concrete defeater',
          },
        };
      }

      const v = (verdict === undefined || verdict === null || verdict === '') ? null : String(verdict);
      const result_digest = computeResultDigest({ elevation: bound, defeater, survived, verdict: v });
      const commission_id = ledger.mintCommission({
        drafter_family: effectiveDrafterFamily,
        refuter_family: effectiveRefuterFamily,
        result_digest,
      });
      const provenance = composeRefutationProvenance({
        elevation: bound,
        defeater,
        survived,
        verdict: v,
        drafter_family: effectiveDrafterFamily,
        refuter_family: effectiveRefuterFamily,
        commission_id,
      });
      bound.refutation_provenance = provenance;

      if (survived === false) {
        bound.rung = 'REFUTED';
      } else {
        bound.tier = 'GROUNDED';
      }
      return {
        index: i,
        bound,
        entry: {
          index: i,
          id: raw.id ?? null,
          minted: true,
          survived,
          commission_id,
          requested_model: requestedModel,
          model_served: servedModel,
          model_attested: modelAttested,
        },
      };
    } catch (err) {
      if (err instanceof SelfRefutationHalt || err instanceof ClaudeFableAttestationError) {
        throw err;
      }
      if (
        effectiveRefuterFamily === 'claude'
        && (
          err?.code === 'ATTESTATION_MISMATCH'
          || err?.provider_status === 'attestation_mismatch'
          || err?.seat_status === 'attestation_mismatch'
          || /attestation_mismatch|attestation mismatch/i.test(String(err?.message || ''))
        )
      ) {
        throw new ClaudeFableAttestationError(err?.served_model ?? null, claudeTargetModel, label);
      }
      log(`!! ${label}: refuter failed (${err?.message ?? err}) — elevation stays SPECULATIVE (no provenance minted)`);
      return {
        index: i,
        bound,
        entry: {
          index: i,
          id: raw.id ?? null,
          minted: false,
          requested_model: requestedModel,
          model_served: null,
          model_attested: false,
          reason: `refuter failed: ${err?.message ?? err}`,
        },
      };
    }
  };

  // Bounded pool: `cap` workers drain the firing queue; per-elevation transport errors
  // floor inside refuteOne, while fatal attestation / self-refutation errors halt all workers immediately.
  const queue = [...toRefute];
  const results = new Map(); // index -> { bound, entry }
  let aborted = false;
  await Promise.all(Array.from({ length: Math.min(cap, queue.length) }, async () => {
    while (!aborted && queue.length) {
      const i = queue.shift();
      try {
        const r = await refuteOne(i);
        results.set(r.index, r);
      } catch (err) {
        aborted = true;
        queue.length = 0;
        throw err;
      }
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

  const primaryServed = seatReceipts.find(s => s.model_served)?.model_served ?? null;
  const allAttested = seatReceipts.length > 0 && seatReceipts.every(s => s.model_attested === true);
  const receipt = {
    drafter_family: effectiveDrafterFamily,
    refuter_family: effectiveRefuterFamily,
    max_concurrency: cap,
    requested_model: effectiveRefuterFamily === 'claude' ? CANONICAL_CLAUDE_REFUTER_MODEL : (routes?.refuter?.model ?? null),
    model_served: primaryServed,
    model_attested: allAttested,
    seats: seatReceipts,
  };

  return { draft: { ...rawDraft, elevations: outElevations }, dispatch, receipt };
}

/**
 * Build the LIVE role-routed agent from coding/review family prefs
 * (refuter → REVIEW_FAMILY, drafter/default → CODING_FAMILY). Omit `routes` to honor prefs;
 * pass an explicit table to pin. Runs the routing guard FIRST so a self-review route can never
 * be built. ENV: forces CRUCIBLE_AGENT_LIVE=1. NOT called by the deterministic test.
 * @param {{routes?:object, drafterFamily?:string, env?:object}} [o]
 * @returns {Promise<Function>} the role-routed agent(prompt, opts)
 */
/**
 * The family that DRAFTED (2026-09-04, journal 0315): the session running this skill, not the
 * dashboard's coding family — a Claude Code session drafts as claude even when coding_family is
 * chatgpt. Explicit `drafterFamily` wins; then GANDALF_DRAFTER_FAMILY; then a Claude Code host
 * (CLAUDECODE set) is claude; else the coding family.
 */
export function resolveDrafterFamily({ drafterFamily, env = process.env, codingFamily } = {}) {
  const pick = (v) => (typeof v === 'string' && v.trim() ? v.trim().toLowerCase() : null);
  return pick(drafterFamily) || pick(env.GANDALF_DRAFTER_FAMILY) || (env.CLAUDECODE ? 'claude' : null) || pick(codingFamily) || DRAFTER_FAMILY;
}

/**
 * The refuter seat under the dashboard's rule (John, 2026-09-04): the configured family that is NOT
 * the drafter's — review_family first (the check seat), then coding_family; null when every
 * configured family is the drafter's (the caller HALTs honestly — never self-refutation, never a
 * family nobody selected).
 */
export function pickRefuterFamily({ families = {}, drafterFamily } = {}) {
  const d = String(drafterFamily || '').toLowerCase();
  for (const f of [families.review, families.coding]) {
    const fam = String(f || '').toLowerCase();
    if (fam && fam !== d) return fam;
  }
  return null;
}

export async function buildLiveRefuterAgent({ routes, drafterFamily, env = process.env } = {}) {
  const { makeRoleRoutedAgent, buildRoutesFromFamilies, familyToDriverName } = await import('../../drivers/index.mjs');
  const built = buildRoutesFromFamilies({
    env,
    codingRoles: [],
    reviewRoles: ['refuter'],
  });
  const resolvedDrafter = resolveDrafterFamily({ drafterFamily, env, codingFamily: built.families?.coding });
  let resolvedRoutes = routes;
  if (!resolvedRoutes) {
    // (2026-09-04) refuter = the configured non-drafter family; review_family first.
    const fam = pickRefuterFamily({ families: built.families || {}, drafterFamily: resolvedDrafter });
    const drv = fam ? familyToDriverName(fam) : null;
    resolvedRoutes = drv
      ? {
        ...built.routes,
        refuter: drv === 'claude'
          ? { driver: drv, model: CANONICAL_CLAUDE_REFUTER_MODEL }
          : { driver: drv },
      }
      : built.routes;
  } else if (
    resolvedRoutes.refuter?.driver === 'claude'
    && (!resolvedRoutes.refuter.model || resolvedRoutes.refuter.model === 'best')
  ) {
    resolvedRoutes = {
      ...resolvedRoutes,
      refuter: { ...resolvedRoutes.refuter, model: CANONICAL_CLAUDE_REFUTER_MODEL },
    };
  }
  // Fail-closed: a refuter that resolves to the drafter's family is a self-refutation HALT.
  const verifiedRefuter = assertCrossFamilyRouting({ routes: resolvedRoutes, drafterFamily: resolvedDrafter });
  const routedAgent = makeRoleRoutedAgent({ routes: resolvedRoutes, env: { ...env, CRUCIBLE_AGENT_LIVE: '1' } });
  routedAgent._resolvedMeta = Object.freeze({
    drafterFamily: resolvedDrafter,
    refuterFamily: verifiedRefuter,
    routes: resolvedRoutes,
  });
  return routedAgent;
}

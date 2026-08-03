// researchPrime intake-only triage wire (NS-01 / Wave 5).
//
// researchPrime receives two-dimension triage ONLY via the intake extension
// payload (bin/intake.mjs). Core Two-Gate governor module is intentionally
// untouched (byte-identity asserted by the Wave-5 suite).
//
// Contract:
//   · recommend + lock live in this module / shared core — never in the governor
//   · extension payload carries { tier, depth, rationale, knobs, stamp }
//   · unlocked headless → HALT; interactive confirm/edit or pre-lock required
//   · knobs come from mapping.mjs researchPrime table (named consumption site)
//
// Non-goals: Two-Gate schema changes; prose skill blocks (Wave 6).

import {
  DEPTH_BANDS,
  MODEL_TIERS,
  canonicalizeDepth,
  isModelTier,
  isProcessDepth,
  normalizeDepth,
  normalizeTier,
  recommend,
} from './core.mjs';
import {
  createLockRecord,
  getLockedBand,
  lockFromHeadless,
  lockFromInteractive,
} from './lock.mjs';
import {
  NS01_WAVE5_STAMP,
  researchPrimeKnobs,
} from './mapping.mjs';

export { NS01_WAVE5_STAMP };

/** Skill id stamped on every RP intake extension payload. */
export const RESEARCHPRIME_SKILL_ID = 'researchPrime';

/**
 * Build the advisory recommendation for RP intake signals.
 * Does NOT lock — callers must resolve a validating lock before work proceeds.
 *
 * @param {object} [inputs]  RP intake bag (intent/query + optional triage signals)
 * @returns {ReturnType<typeof recommend>}
 */
export function recommendResearchPrimeIntake(inputs = {}) {
  const i = inputs && typeof inputs === 'object' ? inputs : {};
  // Map common RP fields onto the shared recommend intake shape.
  const intake = {
    intent:
      typeof i.intent === 'string'
        ? i.intent
        : typeof i.query === 'string'
          ? i.query
          : typeof i.note === 'string'
            ? i.note
            : '',
    scope: i.scope,
    unknowns: i.unknowns,
    novel: i.novel,
    highStakes: i.highStakes,
    irreversible: i.irreversible,
    brownfield: i.brownfield,
    tier: i.tier,
    depth: i.depth,
    skill: RESEARCHPRIME_SKILL_ID,
  };
  return recommend(intake);
}

/**
 * Resolve a validating lock for researchPrime intake, or throw.
 *
 * Precedence:
 *   1. Explicit lock record / host.lock
 *   2. Headless: config-time lock and/or inherit
 *   3. Interactive: confirmed depth (+ optional tier) or confirm recommendation
 *
 * @param {object} [args]
 * @returns {{
 *   lock: Readonly<object>,
 *   recommendation: object,
 *   band: ReturnType<typeof getLockedBand>,
 *   knobs: Readonly<object>,
 * }}
 */
export function resolveResearchPrimeIntakeLock(args = {}) {
  const a = args && typeof args === 'object' ? args : {};
  const inputs = a.inputs && typeof a.inputs === 'object' ? a.inputs : {};
  const recommendation =
    a.recommendation && typeof a.recommendation === 'object'
      ? a.recommendation
      : recommendResearchPrimeIntake(inputs);

  const explicit = a.triageLock ?? a.lock ?? null;
  if (explicit != null) {
    const band = getLockedBand(explicit);
    const lock = createLockRecord({
      tier: band.tier,
      depth: band.depth,
      rationale: band.rationale,
      source: band.source,
      lockedAt: band.lockedAt,
    });
    const knobs = researchPrimeKnobs(lock.depth, lock.tier);
    return { lock, recommendation, band: getLockedBand(lock), knobs };
  }

  if (a.headless === true) {
    const lock = lockFromHeadless({
      config: a.triageConfig ?? a.config ?? null,
      inherit: a.triageInherit ?? a.inherit ?? null,
    });
    const knobs = researchPrimeKnobs(lock.depth, lock.tier);
    return { lock, recommendation, band: getLockedBand(lock), knobs };
  }

  const confirmedDepthRaw = a.confirmedDepth ?? a.depth ?? null;
  const confirmedDepth =
    canonicalizeDepth(confirmedDepthRaw) ??
    (isProcessDepth(confirmedDepthRaw)
      ? confirmedDepthRaw
      : normalizeDepth(confirmedDepthRaw));
  const confirmedTierRaw = a.confirmedTier ?? a.tier ?? null;
  const confirmedTier = isModelTier(confirmedTierRaw)
    ? confirmedTierRaw
    : normalizeTier(confirmedTierRaw);

  if (confirmedDepth && confirmedTier) {
    const lock = lockFromInteractive({
      decision: a.decision === 'confirm' ? 'confirm' : 'edit',
      recommendation:
        a.decision === 'confirm'
          ? {
              tier: confirmedTier,
              depth: confirmedDepth,
              rationale: a.rationale || recommendation.rationale,
            }
          : undefined,
      tier: confirmedTier,
      depth: confirmedDepth,
      rationale:
        a.rationale ||
        `researchPrime intake confirmed: tier=${confirmedTier} depth=${confirmedDepth}`,
    });
    const knobs = researchPrimeKnobs(lock.depth, lock.tier);
    return { lock, recommendation, band: getLockedBand(lock), knobs };
  }

  if (confirmedDepth) {
    const lock = lockFromInteractive({
      decision: 'confirm',
      recommendation: {
        tier: recommendation.tier,
        depth: confirmedDepth,
        rationale: recommendation.rationale,
      },
      rationale:
        a.rationale ||
        `researchPrime intake confirm depth=${confirmedDepth} tier=${recommendation.tier}`,
    });
    const knobs = researchPrimeKnobs(lock.depth, lock.tier);
    return { lock, recommendation, band: getLockedBand(lock), knobs };
  }

  // Gate-1 APPROVE path: treat human approval of the advisory recommendation as
  // interactive confirm (the RP human gate is Gate 1 on the intake artifact).
  if (a.gate1Decision === 'APPROVE' || a.decision === 'confirm') {
    const lock = lockFromInteractive({
      decision: 'confirm',
      recommendation: {
        tier: recommendation.tier,
        depth: recommendation.depth,
        rationale: recommendation.rationale,
      },
      rationale:
        a.rationale ||
        `researchPrime Gate-1 APPROVE: tier=${recommendation.tier} depth=${recommendation.depth}`,
    });
    const knobs = researchPrimeKnobs(lock.depth, lock.tier);
    return { lock, recommendation, band: getLockedBand(lock), knobs };
  }

  const err = new Error(
    'researchPrime intake: unlocked — confirm tier + depth (Gate-1 APPROVE, ' +
      'confirmedDepth/tier, triageLock, or headless config/inherit) before proceeding. ' +
      'Triage lives only in the intake extension payload; the governor module is not consulted.',
  );
  err.name = 'TriageUnlockedError';
  err.code = 'TRIAGE_UNLOCKED';
  err.halt_for_human = true;
  err.pending_action = 'confirm-researchprime-triage';
  throw err;
}

/**
 * Build the intake extension payload (the ONLY place RP triage is recorded).
 *
 * When a lock is available, knobs are locked-band knobs. When only a
 * recommendation is available (pre-prompt artifact write), knobs reflect the
 * advisory recommendation and `locked: false` so the human gate is visible.
 *
 * @param {object} [inputs]
 * @param {object} [opts]
 * @returns {Readonly<{
 *   skill: string,
 *   stamp: string,
 *   recommendation: { tier: string, depth: string, rationale: string, defaulted: boolean },
 *   triage: null | {
 *     locked: true,
 *     tier: string,
 *     depth: string,
 *     rationale: string,
 *     source: string,
 *     lockedAt: string,
 *   },
 *   knobs: Readonly<object>,
 *   locked: boolean,
 * }>}
 */
export function buildResearchPrimeIntakeExtension(inputs = {}, opts = {}) {
  const o = opts && typeof opts === 'object' ? opts : {};
  const recommendation =
    o.recommendation && typeof o.recommendation === 'object'
      ? o.recommendation
      : recommendResearchPrimeIntake(inputs);

  let triage = null;
  let knobs = null;
  let locked = false;

  if (o.lock != null || o.triageLock != null || o.headless === true || o.gate1Decision === 'APPROVE' ||
      o.confirmedDepth != null || o.depth != null || o.decision === 'confirm') {
    try {
      const resolved = resolveResearchPrimeIntakeLock({
        inputs,
        recommendation,
        ...o,
      });
      triage = Object.freeze({
        locked: true,
        tier: resolved.lock.tier,
        depth: resolved.lock.depth,
        rationale: resolved.lock.rationale,
        source: resolved.lock.source,
        lockedAt: resolved.lock.lockedAt,
      });
      knobs = resolved.knobs;
      locked = true;
    } catch (err) {
      // Pre-prompt artifact write may intentionally be unlocked; only rethrow
      // when the caller demanded a lock (headless / explicit).
      if (o.requireLock === true || o.headless === true) throw err;
    }
  }

  if (!knobs) {
    knobs = researchPrimeKnobs(recommendation.depth, recommendation.tier);
  }

  return Object.freeze({
    skill: RESEARCHPRIME_SKILL_ID,
    stamp: NS01_WAVE5_STAMP,
    recommendation: Object.freeze({
      tier: recommendation.tier,
      depth: recommendation.depth,
      rationale: recommendation.rationale,
      defaulted: !!recommendation.defaulted,
    }),
    triage,
    knobs,
    locked,
  });
}

/**
 * Apply a Gate-1 decision to a pre-written extension: APPROVE → lock + knobs;
 * EDIT leaves unlocked (caller must re-resolve); ABORT is not handled here.
 *
 * @param {object} extension  prior buildResearchPrimeIntakeExtension result
 * @param {'APPROVE'|'EDIT'|'ABORT'} decision
 * @param {object} [inputs]
 * @returns {Readonly<object>}
 */
export function finalizeIntakeExtensionOnGate1(extension, decision, inputs = {}) {
  const ext = extension && typeof extension === 'object' ? extension : {};
  const rec = ext.recommendation || recommendResearchPrimeIntake(inputs);
  if (decision === 'APPROVE') {
    return buildResearchPrimeIntakeExtension(inputs, {
      recommendation: {
        tier: rec.tier,
        depth: rec.depth,
        rationale: rec.rationale,
        defaulted: rec.defaulted,
      },
      gate1Decision: 'APPROVE',
      requireLock: true,
    });
  }
  // EDIT / other: keep advisory extension unlocked.
  return buildResearchPrimeIntakeExtension(inputs, {
    recommendation: {
      tier: rec.tier,
      depth: rec.depth,
      rationale: rec.rationale,
      defaulted: rec.defaulted,
    },
  });
}

export {
  DEPTH_BANDS,
  MODEL_TIERS,
  recommend,
  getLockedBand,
  researchPrimeKnobs,
};

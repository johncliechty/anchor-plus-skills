// Track B6 W2 — live reaper multi-pass path vs ceremony emitters.
//
// Production consumers of depth-variable knobs (reaperPasses, ceremonyLevel) and
// the depth-invariant safety floor (requireProofOfDeath, abstainByDefault).
//
// Rules (locked):
//   · reaperPasses comes ONLY from resolveZombieHunterBand / sole resolve at lock time
//   · ceremony emitters are gated by ceremonyLevel only (never thin the reaper path)
//   · requireProofOfDeath is ALWAYS read from ZOMBIE_HUNTER_SAFETY_FLOOR (or hard true)
//   · depth paths never assign requireProofOfDeath or abstainByDefault
//   · LITE may thin pass count / ceremony; never skips proof sequencing or freeze-kill gates

import {
  resolveZombieHunterBand,
  ZOMBIE_HUNTER_SAFETY_FLOOR,
  REAPER_PASSES_MIN,
} from './triage-band.mjs';
import {
  ceremonyLevelOrdinal,
  shouldEmitCeremony,
  emitCeremony,
  listCeremonyEmitters,
} from './ceremony-emit.mjs';

/**
 * Production-site inventory for B6 W2 (plan-named sites).
 * Tags: reaper-decision | ceremony-emitter | safety-floor | removed-shim
 * @type {ReadonlyArray<Readonly<{ site: string, tag: string, note: string }>>}
 */
export const PRODUCTION_SITE_INVENTORY = Object.freeze([
  Object.freeze({
    site: 'daemon.js',
    tag: 'reaper-decision',
    note: 'Telemetry / sweep cadence observer; does not thin proof-of-death',
  }),
  Object.freeze({
    site: 'classify.js',
    tag: 'reaper-decision',
    note: 'Joint-quad classify; abstain-by-default on uncertain legs',
  }),
  Object.freeze({
    site: 'server.js',
    tag: 'ceremony-emitter',
    note: 'Radar chrome / banners / Why panels (ceremonyLevel may thin)',
  }),
  Object.freeze({
    site: 'ownership.js',
    tag: 'reaper-decision',
    note: 'Ownership KEEP lookup; multi-pass confirmation consumer of reaperPasses',
  }),
  Object.freeze({
    site: 'freeze.js',
    tag: 'safety-floor',
    note: 'Sole freeze/kill boundary; requireProofOfDeath hard-true at gate',
  }),
  Object.freeze({
    site: 'soft-freeze.js',
    tag: 'removed-shim',
    note: 'SoftFreeze removed; hard-fail shim only',
  }),
  Object.freeze({
    site: 'ownership-ui.js',
    tag: 'ceremony-emitter',
    note: 'Ownership badge + extra UI chrome gated by ceremonyLevel',
  }),
  Object.freeze({
    site: 'session-start.js',
    tag: 'ceremony-emitter',
    note: 'Deep-brief / explain verbosity gated by ceremonyLevel',
  }),
  Object.freeze({
    site: 'sweep-worker.cjs',
    tag: 'reaper-decision',
    note: 'Isolated classify sweep worker; decision path not ceremony',
  }),
  Object.freeze({
    site: 'reaper-path.mjs',
    tag: 'reaper-decision',
    note: 'Live multi-pass ownership + proof-of-death gate (this module)',
  }),
  Object.freeze({
    site: 'ceremony-emit.mjs',
    tag: 'ceremony-emitter',
    note: 'Sole ceremony-level gate for non-decision emitters',
  }),
]);

/**
 * Lock-time knobs for the reaper path (sole resolve).
 * Depth-variable: reaperPasses, ceremonyLevel.
 * Safety: always floor (never depth-writable).
 *
 * @param {object} [opts] — same shape as resolveZombieHunterBand
 * @returns {Readonly<{
 *   depth: string,
 *   reaperPasses: number,
 *   ceremonyLevel: string,
 *   requireProofOfDeath: true,
 *   abstainByDefault: true,
 *   source: string,
 *   knobs: Readonly<object>,
 *   safety: Readonly<{ requireProofOfDeath: true, abstainByDefault: true }>,
 * }>}
 */
export function lockReaperKnobs(opts = {}) {
  const band = resolveZombieHunterBand(opts);
  // Safety always from floor — never from band.knobs (which exclude safety fields).
  const requireProofOfDeath = ZOMBIE_HUNTER_SAFETY_FLOOR.requireProofOfDeath === true;
  const abstainByDefault = ZOMBIE_HUNTER_SAFETY_FLOOR.abstainByDefault === true;
  return Object.freeze({
    depth: band.depth,
    reaperPasses: band.reaperPasses,
    ceremonyLevel: band.ceremonyLevel,
    requireProofOfDeath,
    abstainByDefault,
    source: band.source,
    knobs: band.knobs,
    safety: ZOMBIE_HUNTER_SAFETY_FLOOR,
    // Explicit: knobs must not carry mutable safety.
    knobsHasRequireProofOfDeath: Object.prototype.hasOwnProperty.call(band.knobs, 'requireProofOfDeath'),
    knobsHasAbstainByDefault: Object.prototype.hasOwnProperty.call(band.knobs, 'abstainByDefault'),
  });
}

/**
 * Live reaperPasses from sole resolve at lock time (no skill-local table).
 * @param {object} [opts]
 * @returns {number}
 */
export function resolveLiveReaperPasses(opts = {}) {
  const locked = lockReaperKnobs(opts);
  if (!Number.isInteger(locked.reaperPasses) || locked.reaperPasses < REAPER_PASSES_MIN) {
    const err = new Error(
      `live reaperPasses must be integer ≥ ${REAPER_PASSES_MIN} (got ${JSON.stringify(locked.reaperPasses)})`,
    );
    err.name = 'ZombieHunterLiveReaperPassesError';
    err.code = 'ZOMBIE_HUNTER_REAPER_PASSES';
    throw err;
  }
  return locked.reaperPasses;
}

/**
 * Proof-of-death gate — ALWAYS enforced from ZOMBIE_HUNTER_SAFETY_FLOOR (or hard true).
 * Never reads requireProofOfDeath from depth profile knobs.
 *
 * @param {{
 *   ownerConfirmedDead?: boolean,
 *   positiveProof?: boolean,
 *   uncertain?: boolean,
 *   liveRun?: boolean,
 *   missingProof?: boolean,
 * }} [evidence]
 * @param {object} [opts] — band lock opts (depth/env); safety still from floor
 * @returns {Readonly<{
 *   requireProofOfDeath: true,
 *   proofGateInvoked: true,
 *   allowDestructive: boolean,
 *   decision: 'PROCEED' | 'ABSTAIN' | 'KEEP',
 *   reason: string,
 *   safetySource: 'ZOMBIE_HUNTER_SAFETY_FLOOR',
 * }>}
 */
export function evaluateProofOfDeathGate(evidence = {}, opts = {}) {
  void opts; // depth may be present but MUST NOT change the floor
  // Hard true from floor — never depth profile.
  const requireProofOfDeath = ZOMBIE_HUNTER_SAFETY_FLOOR.requireProofOfDeath === true
    ? true
    : true; // belt-and-suspenders: always true even if floor were ever corrupted in test doubles

  // Live-run fixture always KEEP — never freeze/kill.
  if (evidence.liveRun === true) {
    return Object.freeze({
      requireProofOfDeath,
      proofGateInvoked: true,
      allowDestructive: false,
      decision: 'KEEP',
      reason: 'LIVE_RUN_KEEP',
      safetySource: 'ZOMBIE_HUNTER_SAFETY_FLOOR',
    });
  }

  // Missing / uncertain proof always abstains when requireProofOfDeath is true.
  if (
    evidence.missingProof === true
    || evidence.uncertain === true
    || evidence.positiveProof !== true
    || evidence.ownerConfirmedDead !== true
  ) {
    return Object.freeze({
      requireProofOfDeath,
      proofGateInvoked: true,
      allowDestructive: false,
      decision: 'ABSTAIN',
      reason: 'PROOF_OF_DEATH_REQUIRED',
      safetySource: 'ZOMBIE_HUNTER_SAFETY_FLOOR',
    });
  }

  return Object.freeze({
    requireProofOfDeath,
    proofGateInvoked: true,
    allowDestructive: true,
    decision: 'PROCEED',
    reason: 'PROOF_OF_DEATH_POSITIVE',
    safetySource: 'ZOMBIE_HUNTER_SAFETY_FLOOR',
  });
}

/**
 * One ownership-confirmation pass (pure; injectable lookup for hermetic tests).
 * @param {object} candidate
 * @param {object} [opts]
 * @param {number} passIndex — 0-based
 * @returns {Readonly<{ passIndex: number, owned: boolean, keep: boolean, failClosed: boolean, reason: string }>}
 */
export function runOwnershipConfirmationPass(candidate, opts = {}, passIndex = 0) {
  const lookupFn =
    typeof opts.lookupOwnership === 'function'
      ? opts.lookupOwnership
      : defaultOwnershipLookup;
  let lookup;
  try {
    lookup = lookupFn(candidate, { ...opts, passIndex }) || {};
  } catch {
    // Fail-closed: error → KEEP
    lookup = { owned: true, keep: true, failClosed: true, reason: 'OWNERSHIP_IPC_FAIL_CLOSED' };
  }
  const owned = !!lookup.owned;
  const failClosed = !!lookup.failClosed;
  const keep = !!(lookup.keep || owned || failClosed);
  return Object.freeze({
    passIndex,
    owned,
    keep,
    failClosed,
    reason: String(lookup.reason || (keep ? 'KEEP' : 'NOT_REGISTERED')),
  });
}

function defaultOwnershipLookup(candidate) {
  if (candidate && candidate.liveRun === true) {
    return { owned: true, keep: true, failClosed: false, reason: 'LIVE_RUN_KEEP' };
  }
  if (candidate && candidate.owned === true) {
    return { owned: true, keep: true, failClosed: false, reason: 'OWNERSHIP_REGISTERED_KEEP' };
  }
  if (candidate && candidate.ownershipUncertain === true) {
    return { owned: true, keep: true, failClosed: true, reason: 'OWNERSHIP_IPC_FAIL_CLOSED' };
  }
  return {
    owned: false,
    keep: false,
    failClosed: false,
    reason: 'OWNERSHIP_NOT_REGISTERED',
  };
}

/**
 * Live multi-pass ownership confirmation driven by knobs.reaperPasses at lock time.
 *
 * Ceremony thinning (lite) MUST NOT early-return past proof-of-death / freeze-kill gates.
 *
 * @param {object} [candidate]
 * @param {object} [opts] — depth/env lock opts + optional lookupOwnership / evidence
 * @returns {Readonly<{
 *   depth: string,
 *   reaperPasses: number,
 *   ceremonyLevel: string,
 *   observedPasses: number,
 *   ownershipPasses: ReadonlyArray<object>,
 *   anyKeep: boolean,
 *   proofGate: Readonly<object>,
 *   proofGateInvoked: true,
 *   requireProofOfDeath: true,
 *   decision: 'PROCEED' | 'ABSTAIN' | 'KEEP',
 *   allowDestructive: boolean,
 *   ceremonyEmissions: ReadonlyArray<object>,
 *   ceremonyEmittedCount: number,
 * }>}
 */
export function runReaperMultiPass(candidate = {}, opts = {}) {
  const locked = lockReaperKnobs(opts);
  const reaperPasses = locked.reaperPasses;
  const ownershipPasses = [];

  // Multi-pass ownership confirmation — count from sole resolve, not hardcoded table.
  for (let i = 0; i < reaperPasses; i += 1) {
    ownershipPasses.push(runOwnershipConfirmationPass(candidate, opts, i));
  }

  const anyKeep = ownershipPasses.some((p) => p.keep || p.owned || p.failClosed);

  // Ceremony emitters (optional side channel) — NEVER gate the reaper decision path.
  const ceremonyEmissions = [];
  for (const kind of listCeremonyEmitters()) {
    const emission = emitCeremony(kind, { candidate, depth: locked.depth }, {
      ceremonyLevel: locked.ceremonyLevel,
      env: opts.env,
      depth: locked.depth,
    });
    ceremonyEmissions.push(emission);
  }
  const ceremonyEmittedCount = ceremonyEmissions.filter((e) => e.emitted).length;

  // Proof-of-death ALWAYS runs when freeze/kill candidate reaches the gate —
  // even when ceremonyLevel is lite and even when reaperPasses === 1.
  const evidence = {
    liveRun: candidate.liveRun === true || anyKeep,
    missingProof: candidate.missingProof === true,
    uncertain:
      candidate.uncertain === true
      || candidate.ownershipUncertain === true
      || ownershipPasses.some((p) => p.failClosed),
    positiveProof: candidate.positiveProof === true && !anyKeep,
    ownerConfirmedDead:
      candidate.ownerConfirmedDead === true
      && candidate.positiveProof === true
      && !anyKeep,
    ...(opts.evidence && typeof opts.evidence === 'object' ? opts.evidence : {}),
  };

  // If ownership said KEEP on any pass, force live-run KEEP before proof (fail SAFE).
  if (anyKeep) {
    evidence.liveRun = true;
  }

  const proofGate = evaluateProofOfDeathGate(evidence, opts);

  // Decision: KEEP from ownership beats proceed; proof gate still invoked.
  let decision = proofGate.decision;
  let allowDestructive = proofGate.allowDestructive;
  if (anyKeep) {
    decision = 'KEEP';
    allowDestructive = false;
  }

  return Object.freeze({
    depth: locked.depth,
    reaperPasses,
    ceremonyLevel: locked.ceremonyLevel,
    observedPasses: ownershipPasses.length,
    ownershipPasses: Object.freeze(ownershipPasses.slice()),
    anyKeep,
    proofGate,
    proofGateInvoked: true,
    requireProofOfDeath: true,
    abstainByDefault: locked.abstainByDefault,
    decision,
    allowDestructive,
    ceremonyEmissions: Object.freeze(ceremonyEmissions.slice()),
    ceremonyEmittedCount,
    safety: ZOMBIE_HUNTER_SAFETY_FLOOR,
    knobs: locked.knobs,
    source: locked.source,
  });
}

/**
 * Freeze/kill decision path wrapper — proves LITE still invokes proof-of-death.
 * Does not perform OS kill; hermetic decision sequencing only.
 *
 * @param {object} [candidate]
 * @param {object} [opts]
 */
export function runFreezeKillDecisionPath(candidate = {}, opts = {}) {
  const result = runReaperMultiPass(candidate, opts);
  return Object.freeze({
    ...result,
    gate: 'freeze-kill',
    // Explicit stamps for hermetic cells.
    proofOfDeathRan: result.proofGateInvoked === true,
    requireProofOfDeathFromFloor:
      result.proofGate.safetySource === 'ZOMBIE_HUNTER_SAFETY_FLOOR'
      && result.requireProofOfDeath === true,
    ceremonyDidNotSkipProof: result.proofGateInvoked === true,
  });
}

export {
  resolveZombieHunterBand,
  ZOMBIE_HUNTER_SAFETY_FLOOR,
  REAPER_PASSES_MIN,
  ceremonyLevelOrdinal,
  shouldEmitCeremony,
  emitCeremony,
  listCeremonyEmitters,
};

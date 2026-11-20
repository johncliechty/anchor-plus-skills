// band-profile.mjs — Crucible/Foreman complexity bands (cf-slick 2026-07-22).
//
// Resolves a locked Stage-0 process depth into a concrete ceremony profile so
// LITE / SPIKE-FIRST / FULL are real paths (journal 0022: LITE must not only
// shrink Shark roundCap). Pure functions — unit-tested; no agent calls.
//
// North Star: does NOT auto-lock, does NOT remove user convergence authority,
// does NOT weaken ≥2-agree when multi-Shark runs. LITE may run 0–1 Shark rounds
// with honest stamp; FULL keeps concurrent multi-Shark.

/** @typedef {'LITE'|'MATRIX-FAST-TRACK'|'FULL'|'SPIKE-FIRST'} ProcessDepth */

/**
 * Normalize depth pin (aliases accepted on input).
 * @param {unknown} depth
 * @returns {ProcessDepth}
 */
export function normalizeBandDepth(depth) {
  const d = String(depth || '').trim().toUpperCase().replace(/_/g, '-');
  if (d === 'LITE' || d === 'LIGHT') return 'LITE';
  if (
    d === 'MATRIX-FAST-TRACK' ||
    d === 'MATRIX' ||
    d === 'FAST-TRACK' ||
    d === 'MATRIX-FAST' ||
    d === 'MFT'
  ) {
    return 'MATRIX-FAST-TRACK';
  }
  // MID / STANDARD → SPIKE-FIRST (mid-scale), NOT silent LITE collapse (Shark MAJOR)
  if (d === 'SPIKE-FIRST' || d === 'SPIKE' || d === 'SPIKEFIRST' || d === 'MID' || d === 'STANDARD') {
    return 'SPIKE-FIRST';
  }
  if (d === 'FULL' || d === 'HEAVY') return 'FULL';
  // Uncertain / missing → FULL (rigor default; Stage-0 should have locked already)
  return 'FULL';
}

/**
 * Ceremony profile for a process depth.
 *
 * @param {unknown} depth  locked Stage-0 depth
 * @param {object}  [overrides]
 * @returns {Readonly<{
 *   depth: ProcessDepth,
 *   label: string,
 *   roundCap: number,
 *   sharkRoles: number,
 *   skipFullOrangesBrainstorm: boolean,
 *   requireSpikeProbe: boolean,
 *   researchUpfront: boolean,
 *   maxModelCallsHint: number,
 *   maxModelCalls: number,
 *   minModelCallsHint?: number,
 *   fastPath?: string,
 *   matrixFastTrack?: boolean,
 *   matrixLayers?: readonly string[],
 *   deltaVerifyTimeoutMs?: number,
 *   skipStage2SharkLoop: boolean,
 *   skipStage2ElegancePass: boolean,
 *   enableSuperjumpOptions: boolean,
 *   foremanReviewersDefault: number,
 *   foremanLeanMidWave: boolean,
 *   notes: string,
 * }>}
 */
export function resolveBandProfile(depth, overrides = {}) {
  const d = normalizeBandDepth(depth);
  /** @type {any} */
  let profile;
  if (d === 'LITE') {
    profile = {
      depth: 'LITE',
      label: 'LITE — nimble small/clear work (<=4 model calls)',
      roundCap: 1,
      sharkRoles: 2, // concurrent pair; ≥2-agree still meaningful with 2
      skipFullOrangesBrainstorm: true, // single-pass constraints+approach (journal 0022/0026)
      requireSpikeProbe: false,
      researchUpfront: false,
      maxModelCallsHint: 4,
      maxModelCalls: 4,
      fastPath: 'slim',
      matrixFastTrack: false,
      skipStage2SharkLoop: true,
      skipStage2ElegancePass: true,
      enableSuperjumpOptions: false,
      foremanReviewersDefault: 1,
      foremanLeanMidWave: true,
      notes:
        'Enforced LITE fast path (<=4 model calls): Stage-0 intake + doctor preflight -> ' +
        'unified Plan+Waves draft -> 1 cross-family review -> <=1 delta patch -> locate-plan.mjs.',
    };
  } else if (d === 'MATRIX-FAST-TRACK') {
    profile = {
      depth: 'MATRIX-FAST-TRACK',
      label: 'MATRIX-FAST-TRACK — lean 2-stage L0-L5 adversarial matrix (6-9 model calls)',
      roundCap: 1,
      sharkRoles: 3,
      skipFullOrangesBrainstorm: true,
      requireSpikeProbe: false,
      researchUpfront: false,
      minModelCallsHint: 6,
      maxModelCallsHint: 9,
      maxModelCalls: 9,
      fastPath: 'matrix-fast-track',
      matrixFastTrack: true,
      matrixLayers: Object.freeze(['L0', 'L1', 'L2', 'L3', 'L4', 'L5']),
      deltaVerifyTimeoutMs: 120_000,
      skipStage2SharkLoop: true,
      skipStage2ElegancePass: true,
      enableSuperjumpOptions: false,
      foremanReviewersDefault: 2,
      foremanLeanMidWave: true,
      notes:
        'Anvil Stage-0 AST intake (0 LLM calls) -> Plan+Waves draft -> 1 cross-family L0-L5 ' +
        'adversarial matrix -> <=1 120s delta verification pass -> deterministic Stage-2 wave serialization.',
    };
  } else if (d === 'SPIKE-FIRST') {
    profile = {
      depth: 'SPIKE-FIRST',
      label: 'SPIKE-FIRST — mid-scale uncertain work',
      roundCap: 2,
      sharkRoles: 3,
      skipFullOrangesBrainstorm: false,
      requireSpikeProbe: true,
      researchUpfront: true,
      maxModelCallsHint: 18,
      maxModelCalls: 18,
      matrixFastTrack: false,
      skipStage2SharkLoop: false,
      skipStage2ElegancePass: false,
      enableSuperjumpOptions: true,
      foremanReviewersDefault: 2,
      foremanLeanMidWave: true,
      notes:
        'Bounded probe artifact + Superjump architectural option pass required before full plan ceremony.',
    };
  } else {
    profile = {
      depth: 'FULL',
      label: 'FULL — large / high-stakes',
      roundCap: 5,
      sharkRoles: 3,
      skipFullOrangesBrainstorm: false,
      requireSpikeProbe: false,
      researchUpfront: true,
      maxModelCallsHint: 40,
      maxModelCalls: 62,
      matrixFastTrack: false,
      skipStage2SharkLoop: false,
      skipStage2ElegancePass: false,
      enableSuperjumpOptions: false,
      foremanReviewersDefault: 2,
      foremanLeanMidWave: true, // mid-wave still lean; terminal/full-panel stays stakes-gated
      notes:
        'Full Oranges order + concurrent Sharks; effort-scoped caps + human-lockable dry exit.',
    };
  }

  // Explicit overrides (tests / operators) always win.
  const o = overrides && typeof overrides === 'object' ? overrides : {};
  const merged = { ...profile, ...o, depth: d };
  return Object.freeze(merged);
}

/**
 * Stamp fields for journal/runs and status tables.
 * @param {ReturnType<typeof resolveBandProfile>} profile
 */
export function bandProfileStamp(profile) {
  const p = profile || resolveBandProfile('FULL');
  return Object.freeze({
    depth: p.depth,
    band_profile: p.label,
    roundCap: p.roundCap,
    sharkRoles: p.sharkRoles,
    maxModelCalls: p.maxModelCalls,
    matrixFastTrack: !!p.matrixFastTrack,
    skipFullOrangesBrainstorm: p.skipFullOrangesBrainstorm,
    skipStage2SharkLoop: !!p.skipStage2SharkLoop,
    skipStage2ElegancePass: !!p.skipStage2ElegancePass,
    requireSpikeProbe: p.requireSpikeProbe,
  });
}

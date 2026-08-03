// band-profile.mjs — Crucible/Foreman complexity bands (cf-slick 2026-07-22).
//
// Resolves a locked Stage-0 process depth into a concrete ceremony profile so
// LITE / SPIKE-FIRST / FULL are real paths (journal 0022: LITE must not only
// shrink Shark roundCap). Pure functions — unit-tested; no agent calls.
//
// North Star: does NOT auto-lock, does NOT remove user convergence authority,
// does NOT weaken ≥2-agree when multi-Shark runs. LITE may run 0–1 Shark rounds
// with honest stamp; FULL keeps concurrent multi-Shark.

/** @typedef {'LITE'|'FULL'|'SPIKE-FIRST'} ProcessDepth */

/**
 * Normalize depth pin (aliases accepted on input).
 * @param {unknown} depth
 * @returns {ProcessDepth}
 */
export function normalizeBandDepth(depth) {
  const d = String(depth || '').trim().toUpperCase().replace(/_/g, '-');
  if (d === 'LITE' || d === 'LIGHT') return 'LITE';
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
 *   foremanReviewersDefault: number,
 *   foremanLeanMidWave: boolean,
 *   notes: string,
 * }>}
 */
export function resolveBandProfile(depth, overrides = {}) {
  const d = normalizeBandDepth(depth);
  /** @type {ReturnType<typeof resolveBandProfile>} */
  let profile;
  if (d === 'LITE') {
    profile = {
      depth: 'LITE',
      label: 'LITE — nimble small/clear work',
      roundCap: 1,
      sharkRoles: 2, // concurrent pair; ≥2-agree still meaningful with 2
      skipFullOrangesBrainstorm: true, // single-pass constraints+approach (journal 0022/0026)
      requireSpikeProbe: false,
      researchUpfront: false,
      maxModelCallsHint: 8,
      foremanReviewersDefault: 1,
      foremanLeanMidWave: true,
      notes:
        'Short frame → single-pass plan seed → ≤1 Shark round (2 concurrent) → approve. ' +
        'No full assumption-map→premortem→wide ideation by default.',
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
      foremanReviewersDefault: 2,
      foremanLeanMidWave: true,
      notes:
        'Bounded probe artifact required before full plan ceremony; then re-band LITE or FULL.',
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
    skipFullOrangesBrainstorm: p.skipFullOrangesBrainstorm,
    requireSpikeProbe: p.requireSpikeProbe,
  });
}

// Per-skill band → real-knob mapping tables (NS-01 / Waves 5–6).
//
// Locked process depth (and model tier where seats matter) must change real
// engine knobs — rounds / reviewers / seats / prose ceremony — not just labels.
// Inequality across FULL | LITE | SPIKE is tested for every mapped skill.
//
// B3: BAND_MAPPINGS.jumper is the sole numeric truth for jumper depth →
// {ideaRounds, killGates}. SPIKE is a first-class cell. killGates ≥ 3 is a
// load-or-init hard floor (never clamp) — see assertJumperKillGatesFloor.
//
// Wave 5: trio (crucible, foreman, researchPrime) + sample (gandalf).
// Wave 6: full 11 (adds jumper, ramanujan, tidy-idy, zombie-hunter,
//         literature-review, financial-analyst, legal-beagle).
//
// Named consumption sites:
//   · crucible-wire.mjs  → crucibleKnobs / assessComplexity.bandKnobs
//   · foreman-wire.mjs   → foremanKnobs → REVIEWERS_BY_DEPTH
//   · researchprime-wire → researchPrimeKnobs → intake extension payload
//   · entry-points.mjs   → knobsForSkill for every manifest skill
//
// Non-goals: DPAPI/sealer; researchPrime governor module (byte-unchanged).

import {
  ACCEPTED_DEPTH_SET,
  DEPTH_BANDS,
  DEPTH_BAND_VALUES,
  MODEL_TIERS,
  canonicalizeDepth,
  isModelTier,
  isProcessDepth,
  normalizeDepth,
  normalizeDepthStrict,
  normalizeTier,
} from './core.mjs';

/** Hard floor — jumper killGates never thinned below this at any depth. */
export const JUMPER_KILL_GATES_MIN = 3;

/**
 * Hard floor — zombie-hunter reaperPasses never collapses below this at any depth.
 * LITE may be 1 pass but never 0 (Track B6 / REAPER_PASSES_MIN).
 */
export const REAPER_PASSES_MIN = 1;

/**
 * Depth-invariant safety floor for zombie-hunter (Track B6).
 * NOT a function of depth; never merged into depth-variable knobs as overridable fields.
 * requireProofOfDeath and abstain-by-default stay true at every depth.
 */
export const ZOMBIE_HUNTER_SAFETY_FLOOR = Object.freeze({
  requireProofOfDeath: true,
  abstainByDefault: true,
});

/**
 * Depth-invariant safety floor for literature-review (Track B7).
 * NOT a function of depth; never merged into depth-variable knobs as overridable fields.
 * Quote-grounding / one-call-per-paper claim extraction floors stay full-strength at every band.
 */
export const LIT_REVIEW_SAFETY_FLOOR = Object.freeze({
  requireQuoteGrounding: true,
  oneCallPerPaperExtraction: true,
  minGroundedClaimsPerPaper: 1,
});

/** Named refuse: unknown process-depth token on literature-review resolve (refuse-closed). */
export const LIT_REVIEW_UNKNOWN_DEPTH = 'LIT_REVIEW_UNKNOWN_DEPTH';

/**
 * Named refuse: band locked (confirmedDepth / FOUNDRY_TRIAGE_DEPTH / lock) while caller
 * supplies snowballDepth or adversarialRounds that desync from live literatureReviewKnobs.
 */
export const LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED = 'LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED';

/** Floor field names that must never be thinned (false/0) on mapping rows. */
const LIT_REVIEW_FLOOR_FIELD_KEYS = Object.freeze([
  'requireQuoteGrounding',
  'oneCallPerPaperExtraction',
  'minGroundedClaimsPerPaper',
]);

/** Wave-5 surface stamp — asserted by the mapping / RP-intake suite. */
export const NS01_WAVE5_STAMP = 'ns01-w5-rp-intake-mapping';

/**
 * All skills with a band → knobs table (Wave 6 = full NS-01 manifest of 11).
 * Order is stable for greps / fingerprints; not load order.
 */
export const MAPPED_SKILLS = Object.freeze([
  'crucible',
  'foreman',
  'researchPrime',
  'gandalf',
  'jumper',
  'ramanujan',
  'tidy-idy',
  'zombie-hunter',
  'literature-review',
  'financial-analyst',
  'legal-beagle',
]);

/**
 * Per-skill, per-depth knob tables.
 * Values are intentional: LITE is strictly leaner than FULL on at least one
 * numeric knob; SPIKE keeps frontier seats (uncertain work) but may
 * differ on rounds/shards from FULL.
 *
 * @type {Readonly<Record<string, Readonly<Record<string, Readonly<object>>>>>}
 */
export const BAND_MAPPINGS = Object.freeze({
  crucible: Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      sharkRounds: 3,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      sharkRounds: 1,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      sharkRounds: 2,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  foreman: Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      reviewers: 2,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      reviewers: 1,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      reviewers: 2,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  researchPrime: Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      maxRounds: 8,
      includeAdjudication: true,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      maxRounds: 2,
      includeAdjudication: false,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      maxRounds: 4,
      includeAdjudication: true,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  gandalf: Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      shards: 8,
      fusionPasses: 2,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      shards: 2,
      fusionPasses: 1,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      shards: 4,
      fusionPasses: 2,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  // B3 sole numeric truth for jumper: LITE | SPIKE | FULL (SPIKE first-class).
  // ideaRounds: LITE < FULL on live read. killGates ≥ JUMPER_KILL_GATES_MIN every row.
  jumper: Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      ideaRounds: 5,
      killGates: 3,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      ideaRounds: 2,
      killGates: 3,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE]: Object.freeze({
      ideaRounds: 3,
      killGates: 3,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  // B4 sole numeric truth for ramanujan: LITE | SPIKE | FULL (canonical keys only).
  // verifyArms: LITE < FULL on live read. certifier: LITE false; FULL/SPIKE true.
  ramanujan: Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      verifyArms: 3,
      certifier: true,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      verifyArms: 1,
      certifier: false,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE]: Object.freeze({
      verifyArms: 2,
      certifier: true,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  'tidy-idy': Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      debatePasses: 2,
      maxRemovalsPerBatch: 25,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      debatePasses: 1,
      maxRemovalsPerBatch: 10,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      debatePasses: 1,
      maxRemovalsPerBatch: 15,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  'zombie-hunter': Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      reaperPasses: 3,
      requireProofOfDeath: true,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      reaperPasses: 1,
      requireProofOfDeath: true,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      reaperPasses: 2,
      requireProofOfDeath: true,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  'literature-review': Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      snowballDepth: 3,
      adversarialRounds: 2,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      snowballDepth: 1,
      adversarialRounds: 1,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      snowballDepth: 2,
      adversarialRounds: 1,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  'financial-analyst': Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      modelPasses: 3,
      tieOutRequired: true,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      modelPasses: 1,
      tieOutRequired: true,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      modelPasses: 2,
      tieOutRequired: true,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
  'legal-beagle': Object.freeze({
    [DEPTH_BANDS.FULL]: Object.freeze({
      reviewSeats: 3,
      citationLintRequired: true,
      seats: 'frontier',
      ceremony: 'full',
    }),
    [DEPTH_BANDS.LITE]: Object.freeze({
      reviewSeats: 1,
      citationLintRequired: true,
      seats: 'standard',
      ceremony: 'lite',
    }),
    [DEPTH_BANDS.SPIKE_FIRST]: Object.freeze({
      reviewSeats: 2,
      citationLintRequired: true,
      seats: 'frontier',
      ceremony: 'spike-first',
    }),
  }),
});

/**
 * Load-or-init hard floor for BAND_MAPPINGS.jumper killGates.
 * Every depth row must expose integer killGates ≥ min. Never clamps — throws.
 * Used at module init on the live table; tests inject synthetic rows (B3-SC3-LOAD-ASSERT).
 *
 * @param {Readonly<Record<string, Readonly<object>>> | Record<string, object>} jumperTable
 * @param {{ min?: number }} [opts]
 * @returns {true}
 */
export function assertJumperKillGatesFloor(jumperTable, opts = {}) {
  const min = Number.isInteger(opts.min) ? opts.min : JUMPER_KILL_GATES_MIN;
  if (!jumperTable || typeof jumperTable !== 'object') {
    const err = new Error('BAND_MAPPINGS.jumper missing or not an object');
    err.name = 'JumperKillGatesFloorError';
    err.code = 'JUMPER_KILLGATES_FLOOR';
    throw err;
  }
  const depths = Object.keys(jumperTable);
  if (depths.length === 0) {
    const err = new Error('BAND_MAPPINGS.jumper has no depth rows');
    err.name = 'JumperKillGatesFloorError';
    err.code = 'JUMPER_KILLGATES_FLOOR';
    throw err;
  }
  for (const depth of depths) {
    const row = jumperTable[depth];
    const kg = row && /** @type {{ killGates?: unknown }} */ (row).killGates;
    // Hard fail — never Math.max/clamp a thinned value up to the floor.
    if (!Number.isInteger(kg) || /** @type {number} */ (kg) < min) {
      const err = new Error(
        `BAND_MAPPINGS.jumper[${depth}].killGates must be integer ≥ ${min} ` +
          `(got ${JSON.stringify(kg)}); never clamp`,
      );
      err.name = 'JumperKillGatesFloorError';
      err.code = 'JUMPER_KILLGATES_FLOOR';
      /** @type {any} */ (err).depth = depth;
      /** @type {any} */ (err).killGates = kg;
      /** @type {any} */ (err).min = min;
      throw err;
    }
  }
  return true;
}

// Load-or-init: live jumper rows must satisfy the killGates floor (B3-SC3).
assertJumperKillGatesFloor(BAND_MAPPINGS.jumper);

/**
 * Load-or-init invariants for BAND_MAPPINGS.ramanujan (Track B4 SC1/SC2).
 * Canonical row keys FULL|LITE|SPIKE only; LITE.certifier===false;
 * LITE.verifyArms < FULL.verifyArms; every row integer verifyArms ≥ 1 + boolean certifier.
 * Never clamps — throws.
 *
 * @param {Readonly<Record<string, Readonly<object>>> | Record<string, object>} [table]
 * @returns {true}
 */
export function assertRamanujanBandInvariants(table = BAND_MAPPINGS.ramanujan) {
  if (!table || typeof table !== 'object') {
    const err = new Error('BAND_MAPPINGS.ramanujan missing or not an object');
    err.name = 'RamanujanBandInvariantError';
    err.code = 'RAMANUJAN_BAND_INVARIANT';
    throw err;
  }
  const keys = Object.keys(table);
  const allowed = new Set(['FULL', 'LITE', 'SPIKE']);
  if (keys.length !== 3 || keys.some((k) => !allowed.has(k))) {
    const err = new Error(
      `BAND_MAPPINGS.ramanujan keys must be exactly FULL|LITE|SPIKE (got ${JSON.stringify(keys)})`,
    );
    err.name = 'RamanujanBandInvariantError';
    err.code = 'RAMANUJAN_BAND_INVARIANT';
    /** @type {any} */ (err).keys = keys;
    throw err;
  }
  for (const depth of keys) {
    const row = table[depth];
    const verifyArms = row && /** @type {{ verifyArms?: unknown }} */ (row).verifyArms;
    const certifier = row && /** @type {{ certifier?: unknown }} */ (row).certifier;
    if (!Number.isInteger(verifyArms) || /** @type {number} */ (verifyArms) < 1) {
      const err = new Error(
        `BAND_MAPPINGS.ramanujan[${depth}].verifyArms must be integer ≥ 1 (got ${JSON.stringify(verifyArms)})`,
      );
      err.name = 'RamanujanBandInvariantError';
      err.code = 'RAMANUJAN_BAND_INVARIANT';
      /** @type {any} */ (err).depth = depth;
      throw err;
    }
    if (typeof certifier !== 'boolean') {
      const err = new Error(
        `BAND_MAPPINGS.ramanujan[${depth}].certifier must be boolean (got ${JSON.stringify(certifier)})`,
      );
      err.name = 'RamanujanBandInvariantError';
      err.code = 'RAMANUJAN_BAND_INVARIANT';
      /** @type {any} */ (err).depth = depth;
      throw err;
    }
  }
  const lite = /** @type {{ certifier?: unknown, verifyArms?: unknown }} */ (table.LITE);
  const full = /** @type {{ verifyArms?: unknown }} */ (table.FULL);
  if (lite.certifier !== false) {
    const err = new Error(
      `BAND_MAPPINGS.ramanujan.LITE.certifier must be false (got ${JSON.stringify(lite.certifier)})`,
    );
    err.name = 'RamanujanBandInvariantError';
    err.code = 'RAMANUJAN_BAND_INVARIANT';
    throw err;
  }
  if (
    !(
      Number.isInteger(lite.verifyArms) &&
      Number.isInteger(full.verifyArms) &&
      /** @type {number} */ (lite.verifyArms) < /** @type {number} */ (full.verifyArms)
    )
  ) {
    const err = new Error(
      `BAND_MAPPINGS.ramanujan LITE.verifyArms must be < FULL.verifyArms ` +
        `(got LITE=${JSON.stringify(lite.verifyArms)} FULL=${JSON.stringify(full.verifyArms)})`,
    );
    err.name = 'RamanujanBandInvariantError';
    err.code = 'RAMANUJAN_BAND_INVARIANT';
    throw err;
  }
  return true;
}

// Load-or-init: live ramanujan rows must satisfy B4 band invariants (SC1/SC2 floor).
assertRamanujanBandInvariants(BAND_MAPPINGS.ramanujan);

/**
 * Ceremony lean-ness ordinal for zombie-hunter load asserts / leanness checks.
 * Lower = leaner. Unknown tokens → null (caller hard-fails).
 *
 * @param {unknown} ceremonyOrLevel
 * @returns {number | null}
 */
export function ceremonyLevelOrdinal(ceremonyOrLevel) {
  if (ceremonyOrLevel == null) return null;
  const key = String(ceremonyOrLevel).trim().toLowerCase().replace(/_/g, '-');
  if (key === 'lite' || key === 'light') return 0;
  if (key === 'spike-first' || key === 'spike' || key === 'spikefirst') return 1;
  if (key === 'full') return 2;
  return null;
}

/**
 * Load-or-init invariants for BAND_MAPPINGS['zombie-hunter'] (Track B6 W1).
 * Every row: requireProofOfDeath===true; integer reaperPasses ≥ REAPER_PASSES_MIN.
 * LITE.reaperPasses < FULL.reaperPasses; LITE ceremony leaner than FULL.
 * Never clamps — throws (a zero table cell fails load, not green after Math.max).
 *
 * @param {Readonly<Record<string, Readonly<object>>> | Record<string, object>} [table]
 * @param {{ min?: number }} [opts]
 * @returns {true}
 */
export function assertZombieHunterBandInvariants(
  table = BAND_MAPPINGS['zombie-hunter'],
  opts = {},
) {
  const min = Number.isInteger(opts.min) ? opts.min : REAPER_PASSES_MIN;
  if (!table || typeof table !== 'object') {
    const err = new Error("BAND_MAPPINGS['zombie-hunter'] missing or not an object");
    err.name = 'ZombieHunterBandInvariantError';
    err.code = 'ZOMBIE_HUNTER_BAND_INVARIANT';
    throw err;
  }
  const depths = Object.keys(table);
  if (depths.length === 0) {
    const err = new Error("BAND_MAPPINGS['zombie-hunter'] has no depth rows");
    err.name = 'ZombieHunterBandInvariantError';
    err.code = 'ZOMBIE_HUNTER_BAND_INVARIANT';
    throw err;
  }
  for (const depth of depths) {
    const row = table[depth];
    const reaperPasses =
      row && /** @type {{ reaperPasses?: unknown }} */ (row).reaperPasses;
    const requireProofOfDeath =
      row && /** @type {{ requireProofOfDeath?: unknown }} */ (row).requireProofOfDeath;
    // Hard fail — never Math.max/clamp a thinned reaperPasses up to the floor.
    if (!Number.isInteger(reaperPasses) || /** @type {number} */ (reaperPasses) < min) {
      const err = new Error(
        `BAND_MAPPINGS['zombie-hunter'][${depth}].reaperPasses must be integer ≥ ${min} ` +
          `(got ${JSON.stringify(reaperPasses)}); never clamp`,
      );
      err.name = 'ZombieHunterBandInvariantError';
      err.code = 'ZOMBIE_HUNTER_BAND_INVARIANT';
      /** @type {any} */ (err).depth = depth;
      /** @type {any} */ (err).reaperPasses = reaperPasses;
      /** @type {any} */ (err).min = min;
      throw err;
    }
    if (requireProofOfDeath !== true) {
      const err = new Error(
        `BAND_MAPPINGS['zombie-hunter'][${depth}].requireProofOfDeath must be true ` +
          `(got ${JSON.stringify(requireProofOfDeath)}); never clamp green`,
      );
      err.name = 'ZombieHunterBandInvariantError';
      err.code = 'ZOMBIE_HUNTER_BAND_INVARIANT';
      /** @type {any} */ (err).depth = depth;
      throw err;
    }
  }
  const lite = /** @type {{ reaperPasses?: unknown, ceremony?: unknown }} */ (table.LITE);
  const full = /** @type {{ reaperPasses?: unknown, ceremony?: unknown }} */ (table.FULL);
  if (!lite || !full) {
    const err = new Error(
      "BAND_MAPPINGS['zombie-hunter'] must expose LITE and FULL rows for leanness asserts",
    );
    err.name = 'ZombieHunterBandInvariantError';
    err.code = 'ZOMBIE_HUNTER_BAND_INVARIANT';
    throw err;
  }
  if (
    !(
      Number.isInteger(lite.reaperPasses) &&
      Number.isInteger(full.reaperPasses) &&
      /** @type {number} */ (lite.reaperPasses) < /** @type {number} */ (full.reaperPasses)
    )
  ) {
    const err = new Error(
      `BAND_MAPPINGS['zombie-hunter'] LITE.reaperPasses must be < FULL.reaperPasses ` +
        `(got LITE=${JSON.stringify(lite.reaperPasses)} FULL=${JSON.stringify(full.reaperPasses)})`,
    );
    err.name = 'ZombieHunterBandInvariantError';
    err.code = 'ZOMBIE_HUNTER_BAND_INVARIANT';
    throw err;
  }
  const liteOrd = ceremonyLevelOrdinal(lite.ceremony);
  const fullOrd = ceremonyLevelOrdinal(full.ceremony);
  if (liteOrd == null || fullOrd == null || !(liteOrd < fullOrd)) {
    const err = new Error(
      `BAND_MAPPINGS['zombie-hunter'] LITE ceremony must be leaner than FULL ` +
        `(got LITE=${JSON.stringify(lite.ceremony)} FULL=${JSON.stringify(full.ceremony)})`,
    );
    err.name = 'ZombieHunterBandInvariantError';
    err.code = 'ZOMBIE_HUNTER_BAND_INVARIANT';
    throw err;
  }
  return true;
}

// Load-or-init: live zombie-hunter rows must satisfy B6 band invariants (W1 floor).
assertZombieHunterBandInvariants(BAND_MAPPINGS['zombie-hunter']);

/**
 * Load-or-init invariants for BAND_MAPPINGS['literature-review'] (Track B7 W1).
 * Every row: integer snowballDepth ≥ 1, integer adversarialRounds ≥ 0.
 * SC2 leaner soft-assert (no remap): LITE.snowballDepth < FULL.snowballDepth
 *   || LITE.adversarialRounds < FULL.adversarialRounds.
 * Hard-fail if a row embeds floor fields as false/0 (never Math.max/clamp-to-green).
 *
 * @param {Readonly<Record<string, Readonly<object>>> | Record<string, object>} [table]
 * @returns {true}
 */
export function assertLiteratureReviewBandInvariants(
  table = BAND_MAPPINGS['literature-review'],
) {
  if (!table || typeof table !== 'object') {
    const err = new Error("BAND_MAPPINGS['literature-review'] missing or not an object");
    err.name = 'LiteratureReviewBandInvariantError';
    err.code = 'LIT_REVIEW_BAND_INVARIANT';
    throw err;
  }
  const depths = Object.keys(table);
  if (depths.length === 0) {
    const err = new Error("BAND_MAPPINGS['literature-review'] has no depth rows");
    err.name = 'LiteratureReviewBandInvariantError';
    err.code = 'LIT_REVIEW_BAND_INVARIANT';
    throw err;
  }
  for (const depth of depths) {
    const row = table[depth];
    const snowballDepth =
      row && /** @type {{ snowballDepth?: unknown }} */ (row).snowballDepth;
    const adversarialRounds =
      row && /** @type {{ adversarialRounds?: unknown }} */ (row).adversarialRounds;
    // Hard fail — never Math.max/clamp a thinned snowballDepth up to 1.
    if (!Number.isInteger(snowballDepth) || /** @type {number} */ (snowballDepth) < 1) {
      const err = new Error(
        `BAND_MAPPINGS['literature-review'][${depth}].snowballDepth must be integer ≥ 1 ` +
          `(got ${JSON.stringify(snowballDepth)}); never clamp`,
      );
      err.name = 'LiteratureReviewBandInvariantError';
      err.code = 'LIT_REVIEW_BAND_INVARIANT';
      /** @type {any} */ (err).depth = depth;
      /** @type {any} */ (err).snowballDepth = snowballDepth;
      throw err;
    }
    if (!Number.isInteger(adversarialRounds) || /** @type {number} */ (adversarialRounds) < 0) {
      const err = new Error(
        `BAND_MAPPINGS['literature-review'][${depth}].adversarialRounds must be integer ≥ 0 ` +
          `(got ${JSON.stringify(adversarialRounds)}); never clamp`,
      );
      err.name = 'LiteratureReviewBandInvariantError';
      err.code = 'LIT_REVIEW_BAND_INVARIANT';
      /** @type {any} */ (err).depth = depth;
      /** @type {any} */ (err).adversarialRounds = adversarialRounds;
      throw err;
    }
    // Floor fields must never be thinned on mapping rows (false/0 → hard fail).
    const bag = /** @type {Record<string, unknown>} */ (row || {});
    for (const key of LIT_REVIEW_FLOOR_FIELD_KEYS) {
      if (!(key in bag)) continue;
      const v = bag[key];
      if (v === false || v === 0) {
        const err = new Error(
          `BAND_MAPPINGS['literature-review'][${depth}].${key} must not be false/0 ` +
            `(got ${JSON.stringify(v)}); floor lives on LIT_REVIEW_SAFETY_FLOOR only`,
        );
        err.name = 'LiteratureReviewBandInvariantError';
        err.code = 'LIT_REVIEW_BAND_INVARIANT';
        /** @type {any} */ (err).depth = depth;
        /** @type {any} */ (err).field = key;
        /** @type {any} */ (err).value = v;
        throw err;
      }
    }
  }
  const lite =
    /** @type {{ snowballDepth?: unknown, adversarialRounds?: unknown }} */ (table.LITE);
  const full =
    /** @type {{ snowballDepth?: unknown, adversarialRounds?: unknown }} */ (table.FULL);
  if (!lite || !full) {
    const err = new Error(
      "BAND_MAPPINGS['literature-review'] must expose LITE and FULL rows for leaner asserts",
    );
    err.name = 'LiteratureReviewBandInvariantError';
    err.code = 'LIT_REVIEW_BAND_INVARIANT';
    throw err;
  }
  // SC2 leaner soft-assert — never remap/rewrite cells to invent leanness.
  const leaner =
    (Number.isInteger(lite.snowballDepth) &&
      Number.isInteger(full.snowballDepth) &&
      /** @type {number} */ (lite.snowballDepth) < /** @type {number} */ (full.snowballDepth)) ||
    (Number.isInteger(lite.adversarialRounds) &&
      Number.isInteger(full.adversarialRounds) &&
      /** @type {number} */ (lite.adversarialRounds) <
        /** @type {number} */ (full.adversarialRounds));
  if (!leaner) {
    const err = new Error(
      `BAND_MAPPINGS['literature-review'] LITE must be leaner than FULL on snowballDepth ` +
        `or adversarialRounds (got LITE snowball=${JSON.stringify(lite.snowballDepth)} ` +
        `rounds=${JSON.stringify(lite.adversarialRounds)}; FULL snowball=${JSON.stringify(full.snowballDepth)} ` +
        `rounds=${JSON.stringify(full.adversarialRounds)}); never remap`,
    );
    err.name = 'LiteratureReviewBandInvariantError';
    err.code = 'LIT_REVIEW_BAND_INVARIANT';
    throw err;
  }
  return true;
}

// Load-or-init: live literature-review rows must satisfy B7 band invariants (W1 floor + leaner).
assertLiteratureReviewBandInvariants(BAND_MAPPINGS['literature-review']);

/**
 * Normalize skill id (case/alias tolerant for the full mapped set).
 * @param {unknown} skill
 * @returns {string | null}
 */
export function normalizeMappedSkill(skill) {
  if (typeof skill !== 'string' || !skill.trim()) return null;
  const key = skill.trim().toLowerCase().replace(/_/g, '-');
  if (key === 'crucible') return 'crucible';
  if (key === 'foreman') return 'foreman';
  if (key === 'researchprime' || key === 'research-prime') return 'researchPrime';
  if (key === 'gandalf') return 'gandalf';
  if (key === 'jumper') return 'jumper';
  if (key === 'ramanujan') return 'ramanujan';
  if (key === 'tidy-idy' || key === 'tidyidy' || key === 'tidy') return 'tidy-idy';
  if (key === 'zombie-hunter' || key === 'zombiehunter' || key === 'zombie') {
    return 'zombie-hunter';
  }
  if (key === 'literature-review' || key === 'literaturereview' || key === 'lit-review') {
    return 'literature-review';
  }
  if (key === 'financial-analyst' || key === 'financialanalyst' || key === 'fin-analyst') {
    return 'financial-analyst';
  }
  if (key === 'legal-beagle' || key === 'legalbeagle' || key === 'legal') return 'legal-beagle';
  return null;
}

/**
 * Resolve knobs for a skill + locked (or free-form) depth + optional tier.
 * Tier overlays `seats` when provided (Heavy → frontier, Standard → standard)
 * without erasing other depth knobs. Unknown skill/depth → null.
 *
 * @param {unknown} skill
 * @param {unknown} depth
 * @param {unknown} [tier]
 * @returns {Readonly<object> | null}
 */
export function knobsForSkill(skill, depth, tier) {
  const skillId = normalizeMappedSkill(skill);
  if (!skillId) return null;
  const table = BAND_MAPPINGS[skillId];
  if (!table) return null;
  // Canonicalize first so SPIKE-FIRST locks and SPIKE operator tokens hit the SPIKE row.
  const d =
    canonicalizeDepth(depth) ??
    (isProcessDepth(depth) ? /** @type {string} */ (depth) : normalizeDepth(depth));
  if (!d) return null;
  const row = table[d] ?? (d === DEPTH_BANDS.SPIKE ? table['SPIKE-FIRST'] : null);
  if (!row) return null;

  const base = { ...row, skill: skillId, depth: d === 'SPIKE-FIRST' ? DEPTH_BANDS.SPIKE : d };
  const t = isModelTier(tier) ? tier : normalizeTier(tier);
  if (t) {
    base.tier = t;
    // Visible tier overlay: Heavy keeps/raises frontier seats; Standard leans standard.
    // Does not silently invent a lock — caller must already hold a lock to apply knobs.
    if (t === MODEL_TIERS.STANDARD) base.seats = 'standard';
    else if (t === MODEL_TIERS.HEAVY) base.seats = 'frontier';
  }
  return Object.freeze(base);
}

/** Named site: Crucible Stage-0 / Shark fan-out. */
export function crucibleKnobs(depth, tier) {
  return knobsForSkill('crucible', depth, tier);
}

/** Named site: Foreman inherit reviewer fan-out. */
export function foremanKnobs(depth, tier) {
  return knobsForSkill('foreman', depth, tier);
}

/** Named site: researchPrime intake extension payload. */
export function researchPrimeKnobs(depth, tier) {
  return knobsForSkill('researchPrime', depth, tier);
}

/** Named site: Gandalf (engine + Wave-6 entry/prose). */
export function gandalfKnobs(depth, tier) {
  return knobsForSkill('gandalf', depth, tier);
}

/** Named site: Jumper. */
export function jumperKnobs(depth, tier) {
  return knobsForSkill('jumper', depth, tier);
}

/**
 * Sole resolve path for jumper depth → ideaRounds / killGates (B3 SC1).
 *
 * Pipeline (locked):
 *   1. normalizeDepth (strict) → canonical LITE | SPIKE | FULL (aliases → SPIKE)
 *   2. read **only** BAND_MAPPINGS.jumper via jumperKnobs (no path-local map)
 *   3. assert killGates ≥ JUMPER_KILL_GATES_MIN (never clamp)
 *   4. return { depth, ideaRounds, killGates }
 *
 * Tier is intentionally not accepted: ideaRounds/killGates are depth-only
 * (B3-SC1-TIER-INERT). Unknown depth hard-fails with accepted set named.
 *
 * @param {unknown} depth
 * @returns {Readonly<{ depth: string, ideaRounds: number, killGates: number }>}
 */
export function resolveJumperDepthKnobs(depth) {
  // Hard-fail unknown so production CLI can exit≠0 with accepted set on stderr.
  const d = normalizeDepthStrict(depth);
  // Sole table read — jumperKnobs → knobsForSkill('jumper') → BAND_MAPPINGS.jumper.
  const knobs = jumperKnobs(d);
  if (!knobs) {
    const err = new Error(
      `BAND_MAPPINGS.jumper has no row for depth ${JSON.stringify(d)}; ` +
        `accepted: ${ACCEPTED_DEPTH_SET.join(' | ')}`,
    );
    err.name = 'UnknownDepthError';
    err.code = 'TRIAGE_UNKNOWN_DEPTH';
    /** @type {any} */ (err).accepted = [...ACCEPTED_DEPTH_SET];
    throw err;
  }
  const ideaRounds = /** @type {{ ideaRounds?: unknown }} */ (knobs).ideaRounds;
  const killGates = /** @type {{ killGates?: unknown }} */ (knobs).killGates;
  // Per-resolve floor — never Math.max/clamp a thinned value.
  if (!Number.isInteger(killGates) || /** @type {number} */ (killGates) < JUMPER_KILL_GATES_MIN) {
    const err = new Error(
      `jumper killGates for ${d} must be integer ≥ ${JUMPER_KILL_GATES_MIN} ` +
        `(got ${JSON.stringify(killGates)}); never clamp`,
    );
    err.name = 'JumperKillGatesFloorError';
    err.code = 'JUMPER_KILLGATES_FLOOR';
    /** @type {any} */ (err).depth = d;
    /** @type {any} */ (err).killGates = killGates;
    throw err;
  }
  if (!Number.isInteger(ideaRounds) || /** @type {number} */ (ideaRounds) < 1) {
    const err = new Error(
      `jumper ideaRounds for ${d} must be a positive integer (got ${JSON.stringify(ideaRounds)})`,
    );
    err.name = 'JumperIdeaRoundsError';
    err.code = 'JUMPER_IDEA_ROUNDS';
    /** @type {any} */ (err).depth = d;
    throw err;
  }
  return Object.freeze({
    depth: d,
    ideaRounds: /** @type {number} */ (ideaRounds),
    killGates: /** @type {number} */ (killGates),
  });
}

/** Named site: Ramanujan. */
export function ramanujanKnobs(depth, tier) {
  return knobsForSkill('ramanujan', depth, tier);
}

/**
 * Sole resolve path for ramanujan depth → verifyArms / certifier (Track B4 SC1).
 *
 * Pipeline (locked):
 *   1. normalizeDepthStrict → canonical LITE | SPIKE | FULL (SPIKE aliases → SPIKE)
 *   2. read **only** BAND_MAPPINGS.ramanujan via ramanujanKnobs → knobsForSkill
 *      (no path-local map; no silent FULL fallback)
 *   3. assert integer verifyArms ≥ 1 and boolean certifier
 *   4. return Object.freeze({ depth, verifyArms, certifier })
 *
 * Tier is intentionally not accepted: verifyArms/certifier are depth-only
 * (tier env alone must never arm the certifier — B4 SC4).
 *
 * @param {unknown} depth
 * @returns {Readonly<{ depth: string, verifyArms: number, certifier: boolean }>}
 */
export function resolveRamanujanDepthKnobs(depth) {
  // Hard-fail unknown so production paths never invent FULL / silent fallback.
  const d = normalizeDepthStrict(depth);
  // Sole table read — ramanujanKnobs → knobsForSkill('ramanujan') → BAND_MAPPINGS.ramanujan.
  const knobs = ramanujanKnobs(d);
  if (!knobs) {
    const err = new Error(
      `BAND_MAPPINGS.ramanujan has no row for depth ${JSON.stringify(d)}; ` +
        `accepted: ${ACCEPTED_DEPTH_SET.join(' | ')}`,
    );
    err.name = 'UnknownDepthError';
    err.code = 'TRIAGE_UNKNOWN_DEPTH';
    /** @type {any} */ (err).accepted = [...ACCEPTED_DEPTH_SET];
    throw err;
  }
  const verifyArms = /** @type {{ verifyArms?: unknown }} */ (knobs).verifyArms;
  const certifier = /** @type {{ certifier?: unknown }} */ (knobs).certifier;
  if (!Number.isInteger(verifyArms) || /** @type {number} */ (verifyArms) < 1) {
    const err = new Error(
      `ramanujan verifyArms for ${d} must be integer ≥ 1 (got ${JSON.stringify(verifyArms)})`,
    );
    err.name = 'RamanujanVerifyArmsError';
    err.code = 'RAMANUJAN_VERIFY_ARMS';
    /** @type {any} */ (err).depth = d;
    /** @type {any} */ (err).verifyArms = verifyArms;
    throw err;
  }
  if (typeof certifier !== 'boolean') {
    const err = new Error(
      `ramanujan certifier for ${d} must be boolean (got ${JSON.stringify(certifier)})`,
    );
    err.name = 'RamanujanCertifierError';
    err.code = 'RAMANUJAN_CERTIFIER_TYPE';
    /** @type {any} */ (err).depth = d;
    /** @type {any} */ (err).certifier = certifier;
    throw err;
  }
  return Object.freeze({
    depth: d,
    verifyArms: /** @type {number} */ (verifyArms),
    certifier: /** @type {boolean} */ (certifier),
  });
}

/** Named site: Tidy-Idy. */
export function tidyIdyKnobs(depth, tier) {
  return knobsForSkill('tidy-idy', depth, tier);
}

/** Named site: Zombie-Hunter. */
export function zombieHunterKnobs(depth, tier) {
  return knobsForSkill('zombie-hunter', depth, tier);
}

/**
 * Sole resolve path for zombie-hunter depth → reaperPasses / ceremonyLevel (Track B6 W1).
 *
 * Pipeline (locked):
 *   1. normalizeDepthStrict → canonical LITE | SPIKE | FULL (SPIKE aliases → SPIKE)
 *   2. read **only** BAND_MAPPINGS['zombie-hunter'] via zombieHunterKnobs → knobsForSkill
 *      (no path-local map; no silent Math.max clamp)
 *   3. assert integer reaperPasses ≥ REAPER_PASSES_MIN; ceremony present
 *   4. return Object.freeze({ depth, reaperPasses, ceremonyLevel })
 *      — depth-variable knobs only; never includes writable requireProofOfDeath / abstainByDefault
 *
 * Safety fields live on ZOMBIE_HUNTER_SAFETY_FLOOR (depth-invariant), not this profile.
 * Tier is intentionally not accepted: reaperPasses/ceremonyLevel are depth-only.
 *
 * @param {unknown} depth
 * @returns {Readonly<{ depth: string, reaperPasses: number, ceremonyLevel: string }>}
 */
export function resolveZombieHunterDepthKnobs(depth) {
  // Hard-fail unknown so production paths never invent FULL / silent fallback here.
  const d = normalizeDepthStrict(depth);
  // Sole table read — zombieHunterKnobs → knobsForSkill('zombie-hunter') → BAND_MAPPINGS.
  const knobs = zombieHunterKnobs(d);
  if (!knobs) {
    const err = new Error(
      `BAND_MAPPINGS['zombie-hunter'] has no row for depth ${JSON.stringify(d)}; ` +
        `accepted: ${ACCEPTED_DEPTH_SET.join(' | ')}`,
    );
    err.name = 'UnknownDepthError';
    err.code = 'TRIAGE_UNKNOWN_DEPTH';
    /** @type {any} */ (err).accepted = [...ACCEPTED_DEPTH_SET];
    throw err;
  }
  const reaperPasses = /** @type {{ reaperPasses?: unknown }} */ (knobs).reaperPasses;
  const ceremony = /** @type {{ ceremony?: unknown }} */ (knobs).ceremony;
  // Per-resolve floor — never Math.max/clamp a thinned value up to REAPER_PASSES_MIN.
  if (!Number.isInteger(reaperPasses) || /** @type {number} */ (reaperPasses) < REAPER_PASSES_MIN) {
    const err = new Error(
      `zombie-hunter reaperPasses for ${d} must be integer ≥ ${REAPER_PASSES_MIN} ` +
        `(got ${JSON.stringify(reaperPasses)}); never clamp`,
    );
    err.name = 'ZombieHunterReaperPassesError';
    err.code = 'ZOMBIE_HUNTER_REAPER_PASSES';
    /** @type {any} */ (err).depth = d;
    /** @type {any} */ (err).reaperPasses = reaperPasses;
    throw err;
  }
  if (typeof ceremony !== 'string' || ceremonyLevelOrdinal(ceremony) == null) {
    const err = new Error(
      `zombie-hunter ceremony for ${d} must be a known ceremony token ` +
        `(got ${JSON.stringify(ceremony)})`,
    );
    err.name = 'ZombieHunterCeremonyError';
    err.code = 'ZOMBIE_HUNTER_CEREMONY';
    /** @type {any} */ (err).depth = d;
    throw err;
  }
  // Depth-variable knobs only — ceremony → ceremonyLevel normalize; no safety fields.
  return Object.freeze({
    depth: d,
    reaperPasses: /** @type {number} */ (reaperPasses),
    ceremonyLevel: ceremony,
  });
}

/**
 * Alias of resolveZombieHunterDepthKnobs — frozen depth-variable-only profile helper.
 * @param {unknown} depth
 * @returns {Readonly<{ depth: string, reaperPasses: number, ceremonyLevel: string }>}
 */
export function zombieHunterKnobProfile(depth) {
  return resolveZombieHunterDepthKnobs(depth);
}

/**
 * Sole production reader for literature-review depth-variable knobs (Track B7 W1).
 * Returns frozen knobs-only shape — never includes LIT_REVIEW_SAFETY_FLOOR keys.
 * Sole table path: knobsForSkill('literature-review') → BAND_MAPPINGS['literature-review'].
 *
 * @param {unknown} depth
 * @param {unknown} [tier] accepted for seat overlay consistency with knobsForSkill; seats only
 * @returns {Readonly<{
 *   depth: string,
 *   snowballDepth: number,
 *   adversarialRounds: number,
 *   ceremony: string,
 *   seats: string,
 *   skill: 'literature-review',
 * }> | null}
 */
export function literatureReviewKnobs(depth, tier) {
  const raw = knobsForSkill('literature-review', depth, tier);
  if (!raw) return null;
  const r = /** @type {Record<string, unknown>} */ (raw);
  // Knobs-only: depth-variable fields. Explicit pick omits any floor keys if a row ever embeds them.
  return Object.freeze({
    depth: /** @type {string} */ (r.depth),
    snowballDepth: /** @type {number} */ (r.snowballDepth),
    adversarialRounds: /** @type {number} */ (r.adversarialRounds),
    ceremony: /** @type {string} */ (r.ceremony),
    seats: /** @type {string} */ (r.seats),
    skill: /** @type {'literature-review'} */ ('literature-review'),
  });
}

/**
 * First non-empty string token (trim). Empty / whitespace → null.
 * @param {unknown} value
 * @returns {string | null}
 */
function litReviewNonEmptyToken(value) {
  if (value == null) return null;
  const s = typeof value === 'string' ? value.trim() : String(value).trim();
  return s ? s : null;
}

/**
 * Normalize literature-review depth or throw LIT_REVIEW_UNKNOWN_DEPTH (refuse-closed).
 * No silent FULL fallback that claims lock.
 *
 * @param {unknown} value
 * @returns {string}
 */
export function normalizeLiteratureReviewDepthStrict(value) {
  try {
    return normalizeDepthStrict(value);
  } catch (cause) {
    const err = new Error(
      `literature-review unknown process depth ${JSON.stringify(value)}; ` +
        `accepted: ${ACCEPTED_DEPTH_SET.join(' | ')}`,
    );
    err.name = 'LiteratureReviewUnknownDepthError';
    err.code = LIT_REVIEW_UNKNOWN_DEPTH;
    /** @type {any} */ (err).accepted = [...ACCEPTED_DEPTH_SET];
    /** @type {any} */ (err).value = value;
    /** @type {any} */ (err).cause = cause;
    throw err;
  }
}

/**
 * Build partial-override refuse error (band locked + desynced explicit knobs).
 * @param {string} field
 * @param {unknown} got
 * @param {unknown} expected
 * @param {string} band
 * @returns {Error}
 */
export function literatureReviewPartialOverrideError(field, got, expected, band) {
  const err = new Error(
    `literature-review partial override refused while triage lock is advertised: ` +
      `${field}=${JSON.stringify(got)} desyncs from literatureReviewKnobs(${JSON.stringify(band)}) ` +
      `expected ${JSON.stringify(expected)}; freestyle requires no FOUNDRY_TRIAGE_DEPTH / confirmedDepth lock`,
  );
  err.name = 'LiteratureReviewPartialOverrideError';
  err.code = LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED;
  /** @type {any} */ (err).field = field;
  /** @type {any} */ (err).got = got;
  /** @type {any} */ (err).expected = expected;
  /** @type {any} */ (err).band = band;
  return err;
}

/**
 * Resolve literature-review band + knobs + floor (Track B7 W1 control plane).
 *
 * Precedence (band only — first match wins after normalize):
 *   1. options.confirmedDepth / options.depth / intake lock depth
 *   2. process.env.FOUNDRY_TRIAGE_DEPTH (or opts.env)
 *   3. process.env.LITREVIEW_TRIAGE_DEPTH
 *   4. missing → mapped FULL with source 'default-full' (finite knobs, not a soft lock claim)
 *
 * Unknown token → LIT_REVIEW_UNKNOWN_DEPTH (refuse-closed).
 * When band is locked (rank 1–2 or lock stamp) and caller supplies snowballDepth /
 * adversarialRounds that differ from literatureReviewKnobs(band) →
 * LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED.
 *
 * @param {object} [opts]
 * @param {unknown} [opts.confirmedDepth]
 * @param {unknown} [opts.depth]
 * @param {unknown} [opts.snowballDepth] explicit freestyle / desync probe
 * @param {unknown} [opts.adversarialRounds] explicit freestyle / desync probe
 * @param {object} [opts.triageLock]
 * @param {object} [opts.lock]
 * @param {object} [opts.intake]
 * @param {NodeJS.ProcessEnv | Record<string, string | undefined>} [opts.env]
 * @returns {Readonly<{
 *   source: string,
 *   band: string,
 *   reason: string,
 *   knobs: Readonly<{
 *     depth: string,
 *     snowballDepth: number,
 *     adversarialRounds: number,
 *     ceremony: string,
 *     seats: string,
 *     skill: 'literature-review',
 *   }>,
 *   floor: typeof LIT_REVIEW_SAFETY_FLOOR,
 * }>}
 */
export function resolveLiteratureReviewBand({
  confirmedDepth = null,
  depth = null,
  snowballDepth = undefined,
  adversarialRounds = undefined,
  triageLock = null,
  lock = null,
  intake = null,
  env = process.env,
} = {}) {
  /** @type {string | null} */
  let picked = null;
  /** @type {string} */
  let source = 'default-full';
  /** @type {string} */
  let reason = 'no depth pin; mapped FULL default (finite knobs, not a lock claim)';
  /** @type {boolean} */
  let bandLocked = false;

  const confirmedPin = litReviewNonEmptyToken(confirmedDepth) || litReviewNonEmptyToken(depth);
  if (confirmedPin) {
    picked = confirmedPin;
    source = 'confirmed-depth';
    reason = `confirmedDepth/depth pin ${JSON.stringify(confirmedPin)}`;
    bandLocked = true;
  }

  if (picked == null) {
    const explicit = triageLock ?? lock ?? null;
    if (explicit != null && typeof explicit === 'object') {
      const bag = /** @type {Record<string, unknown>} */ (explicit);
      const lockDepth =
        litReviewNonEmptyToken(bag.depth) ||
        (bag.locked === true ? litReviewNonEmptyToken(bag.depth) : null);
      if (lockDepth) {
        picked = lockDepth;
        source = 'lock-record';
        reason = `lock/triageLock depth ${JSON.stringify(lockDepth)}`;
        bandLocked = true;
      }
    }
  }

  if (picked == null && intake != null && typeof intake === 'object') {
    const bag = /** @type {Record<string, unknown>} */ (intake);
    if (bag.lock != null && typeof bag.lock === 'object') {
      const lockBag = /** @type {Record<string, unknown>} */ (bag.lock);
      const lockDepth = litReviewNonEmptyToken(lockBag.depth);
      if (lockDepth) {
        picked = lockDepth;
        source = 'lock-record';
        reason = `intake.lock depth ${JSON.stringify(lockDepth)}`;
        bandLocked = true;
      }
    }
    if (picked == null) {
      const intakeDepth =
        litReviewNonEmptyToken(bag.confirmedDepth) || litReviewNonEmptyToken(bag.depth);
      if (intakeDepth) {
        picked = intakeDepth;
        source = 'confirmed-depth';
        reason = `intake confirmedDepth/depth ${JSON.stringify(intakeDepth)}`;
        bandLocked = true;
      }
    }
  }

  const e = env && typeof env === 'object' ? env : {};
  if (picked == null) {
    const foundry = litReviewNonEmptyToken(
      /** @type {Record<string, unknown>} */ (e).FOUNDRY_TRIAGE_DEPTH,
    );
    if (foundry) {
      picked = foundry;
      source = 'foundry-triage-depth';
      reason = `FOUNDRY_TRIAGE_DEPTH=${JSON.stringify(foundry)}`;
      // Rank-2 portfolio lock — partial override refused while advertised.
      bandLocked = true;
    }
  }
  if (picked == null) {
    const skillLocal = litReviewNonEmptyToken(
      /** @type {Record<string, unknown>} */ (e).LITREVIEW_TRIAGE_DEPTH,
    );
    if (skillLocal) {
      picked = skillLocal;
      source = 'litreview-triage-depth';
      reason = `LITREVIEW_TRIAGE_DEPTH=${JSON.stringify(skillLocal)}`;
      // Rank-3 skill pin — not FOUNDRY lock advertising; freestyle still allowed off-gate.
      bandLocked = false;
    }
  }

  const depthToken = picked || 'FULL';
  if (picked == null) {
    source = 'default-full';
    reason = 'no depth pin; mapped FULL default (finite knobs, not a lock claim)';
    bandLocked = false;
  }

  // Unknown → refuse-closed (LIT_REVIEW_UNKNOWN_DEPTH); never silent FULL that claims lock.
  const band = normalizeLiteratureReviewDepthStrict(depthToken);
  const knobs = literatureReviewKnobs(band);
  if (!knobs) {
    const err = new Error(
      `BAND_MAPPINGS['literature-review'] has no row for depth ${JSON.stringify(band)}; ` +
        `accepted: ${ACCEPTED_DEPTH_SET.join(' | ')}`,
    );
    err.name = 'LiteratureReviewUnknownDepthError';
    err.code = LIT_REVIEW_UNKNOWN_DEPTH;
    /** @type {any} */ (err).accepted = [...ACCEPTED_DEPTH_SET];
    /** @type {any} */ (err).band = band;
    throw err;
  }

  // Partial-override refuse while lock is advertised (rank 1–2 / lock stamp).
  if (bandLocked) {
    if (snowballDepth !== undefined && snowballDepth !== null) {
      const got = Number(snowballDepth);
      if (!(Number.isInteger(got) && got === knobs.snowballDepth)) {
        throw literatureReviewPartialOverrideError(
          'snowballDepth',
          snowballDepth,
          knobs.snowballDepth,
          band,
        );
      }
    }
    if (adversarialRounds !== undefined && adversarialRounds !== null) {
      const got = Number(adversarialRounds);
      if (!(Number.isInteger(got) && got === knobs.adversarialRounds)) {
        throw literatureReviewPartialOverrideError(
          'adversarialRounds',
          adversarialRounds,
          knobs.adversarialRounds,
          band,
        );
      }
    }
  }

  return Object.freeze({
    source,
    band,
    reason,
    knobs,
    floor: LIT_REVIEW_SAFETY_FLOOR,
  });
}

/** Named site: Financial-Analyst (prose host; knobs = ceremony only until NS-03). */
export function financialAnalystKnobs(depth, tier) {
  return knobsForSkill('financial-analyst', depth, tier);
}

/** Named site: Legal-Beagle (prose host; knobs = ceremony only until NS-02). */
export function legalBeagleKnobs(depth, tier) {
  return knobsForSkill('legal-beagle', depth, tier);
}

/**
 * JSON-stable fingerprint of knobs for inequality tests (order-independent enough).
 * @param {unknown} knobs
 * @returns {string}
 */
export function knobsFingerprint(knobs) {
  if (!knobs || typeof knobs !== 'object') return '';
  const o = /** @type {Record<string, unknown>} */ (knobs);
  const keys = Object.keys(o).sort();
  const sorted = {};
  for (const k of keys) sorted[k] = o[k];
  return JSON.stringify(sorted);
}

/**
 * True when two bands produce unequal knobs for a skill (NS criterion 6).
 * @param {string} skill
 * @param {string} depthA
 * @param {string} depthB
 * @returns {boolean}
 */
export function bandsInequal(skill, depthA, depthB) {
  const a = knobsForSkill(skill, depthA);
  const b = knobsForSkill(skill, depthB);
  if (!a || !b) return false;
  return knobsFingerprint(a) !== knobsFingerprint(b);
}

export { DEPTH_BANDS, DEPTH_BAND_VALUES, MODEL_TIERS };

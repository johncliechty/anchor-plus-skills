// Track B7 W2 — CLI/engine dual-knob apply for literature-review triage lock.
//
// Contract 1:
//   · band lives only as opts.triageBand / resolved.band (never overloaded onto snowball)
//   · snowball hops live only as opts.snowballDepth (integer ≥ 1)
//   · adversarialRounds lives only as opts.adversarialRounds (integer ≥ 0)
//   · locked path (confirmedDepth / --triage-depth / FOUNDRY_TRIAGE_DEPTH) applies BOTH
//     knobs from the same literatureReviewKnobs / resolveLiteratureReviewBand object
//   · partial freestyle override while lock advertised → LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED
//
// Pure helper (importable by hermetic tests). CLI calls applyLiteratureReviewTriageLock.

import {
  literatureReviewKnobs,
  resolveLiteratureReviewBand,
  LIT_REVIEW_SAFETY_FLOOR,
  LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED,
  LIT_REVIEW_UNKNOWN_DEPTH,
} from 'fil<path>';

export {
  literatureReviewKnobs,
  resolveLiteratureReviewBand,
  LIT_REVIEW_SAFETY_FLOOR,
  LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED,
  LIT_REVIEW_UNKNOWN_DEPTH,
};

function nonEmpty(value) {
  if (value == null) return null;
  const s = typeof value === 'string' ? value.trim() : String(value).trim();
  return s ? s : null;
}

/**
 * True when rank-1/2 band lock sources are present (Contract 1 partial-override refuse).
 * @param {object} opts
 * @param {NodeJS.ProcessEnv | Record<string, string | undefined>} env
 */
export function isLiteratureReviewBandLocked(opts = {}, env = process.env) {
  const e = env && typeof env === 'object' ? env : {};
  if (nonEmpty(opts.triageDepth)) return true;
  if (nonEmpty(opts.confirmedDepth)) return true;
  if (nonEmpty(/** @type {any} */ (e).FOUNDRY_TRIAGE_DEPTH)) return true;
  return false;
}

/**
 * True when any triage depth pin is present (rank 1–3), so knobs should be applied
 * from resolveLiteratureReviewBand rather than freestyle defaults.
 */
export function hasLiteratureReviewDepthPin(opts = {}, env = process.env) {
  const e = env && typeof env === 'object' ? env : {};
  if (isLiteratureReviewBandLocked(opts, e)) return true;
  if (nonEmpty(/** @type {any} */ (e).LITREVIEW_TRIAGE_DEPTH)) return true;
  return false;
}

/**
 * Apply triage lock knobs onto a CLI/engine opts bag without field collision.
 *
 * On depth-pin path (rank 1–3):
 *   - sets opts.snowballDepth + opts.adversarialRounds from the same knobs object
 *   - sets opts.triageBand = resolved.band (band only)
 *   - does NOT write integer snowball into a field named depth/band
 *   - rank 1–2: refuses desynced freestyle snowball/rounds while lock advertised
 *
 * Off pin path (freestyle):
 *   - preserves opts.snowballDepth (default 1) and opts.adversarialRounds (default 1
 *     to keep prior single-pass product behavior when unlocked)
 *   - does not stamp triageBand as a lock claim
 *
 * Mutates and returns opts; also returns structured resolve record when pinned.
 *
 * @param {object} opts  CLI/engine options bag (mutated)
 * @param {{ env?: NodeJS.ProcessEnv | Record<string, string | undefined> }} [args]
 * @returns {{
 *   opts: object,
 *   locked: boolean,
 *   resolved: null | ReturnType<typeof resolveLiteratureReviewBand>,
 *   floor: typeof LIT_REVIEW_SAFETY_FLOOR,
 * }}
 */
export function applyLiteratureReviewTriageLock(opts, { env = process.env } = {}) {
  if (!opts || typeof opts !== 'object') {
    throw new TypeError('applyLiteratureReviewTriageLock requires an opts object');
  }

  const e = env && typeof env === 'object' ? env : {};
  const locked = isLiteratureReviewBandLocked(opts, e);
  const pinned = hasLiteratureReviewDepthPin(opts, e);

  // Normalize freestyle snowball: migrate legacy opts.depth integer into snowballDepth.
  if (
    (opts.snowballDepth === undefined || opts.snowballDepth === null) &&
    typeof opts.depth === 'number' &&
    Number.isFinite(opts.depth)
  ) {
    opts.snowballDepth = opts.depth;
  }

  if (!pinned) {
    if (opts.snowballDepth === undefined || opts.snowballDepth === null) {
      opts.snowballDepth = 1;
    }
    if (opts.adversarialRounds === undefined || opts.adversarialRounds === null) {
      // Unlocked freestyle: preserve prior single governed-pass product default.
      opts.adversarialRounds = 1;
    }
    opts._triageResolved = null;
    return {
      opts,
      locked: false,
      resolved: null,
      floor: LIT_REVIEW_SAFETY_FLOOR,
    };
  }

  // Explicit freestyle probes only when caller marked them (or legacy depthExplicit).
  const snowballProbe =
    opts.snowballDepthExplicit === true || opts.depthExplicit === true
      ? opts.snowballDepth
      : undefined;
  const roundsProbe =
    opts.adversarialRoundsExplicit === true ? opts.adversarialRounds : undefined;

  const resolved = resolveLiteratureReviewBand({
    confirmedDepth: opts.triageDepth ?? opts.confirmedDepth ?? null,
    snowballDepth: snowballProbe,
    adversarialRounds: roundsProbe,
    env: e,
  });

  // Dual-knob apply from the SAME knobs object — no band/snowball collision.
  opts.snowballDepth = resolved.knobs.snowballDepth;
  opts.adversarialRounds = resolved.knobs.adversarialRounds;
  opts.triageBand = resolved.band;
  opts._triageKnobs = resolved.knobs;
  opts._triageResolved = resolved;
  opts._triageFloor = resolved.floor;

  // Forbidden: integer snowball stored in a field named as band/depth-as-band.
  // Never assign band string into snowball; never assign snowball into triageBand.
  if (opts.depth === resolved.band || opts.depth === resolved.knobs.depth) {
    delete opts.depth;
  }

  return {
    opts,
    locked: locked || resolved.source === 'foundry-triage-depth' || resolved.source === 'confirmed-depth' || resolved.source === 'lock-record',
    resolved,
    floor: resolved.floor,
  };
}

/**
 * Hermetic helper: build a clean opts bag under FOUNDRY_TRIAGE_DEPTH (or confirmedDepth)
 * and return the executed applied knobs (for SC2 leaner cells).
 *
 * @param {string} band
 * @param {{ env?: Record<string, string | undefined>, freestyle?: { snowballDepth?: number, adversarialRounds?: number } }} [args]
 */
export function applyBandUnderEnv(band, { env = {}, freestyle = null } = {}) {
  const mergedEnv = {
    ...env,
    FOUNDRY_TRIAGE_DEPTH: band,
  };
  const opts = {
    triageDepth: band,
    snowballDepth: freestyle?.snowballDepth,
    adversarialRounds: freestyle?.adversarialRounds,
    snowballDepthExplicit: freestyle?.snowballDepth !== undefined,
    adversarialRoundsExplicit: freestyle?.adversarialRounds !== undefined,
  };
  const out = applyLiteratureReviewTriageLock(opts, { env: mergedEnv });
  return {
    snowballDepth: out.opts.snowballDepth,
    adversarialRounds: out.opts.adversarialRounds,
    triageBand: out.opts.triageBand,
    locked: out.locked,
    resolved: out.resolved,
    floor: out.floor,
  };
}

// Dual-write dark surface matrix (G0 sole law for scare RED).
//
// Until classifierMode is armed with a version-matched canaryReceipt, EVERY
// actionable scare surface is non-actionable. Observe-only dual-run fields
// (wouldBeActionableRed, reason codes) remain visible so SC1/SC2 cannot green
// by blindness — dark ≠ silence.

const { isActionableRedAllowed, isFreezeKillAllowed } = require('./mode.js');

/** Named dual-write scare surfaces (legacy + new + Anchor chrome). */
const SURFACES = Object.freeze([
  'legacy_radar',
  'new_classifier',
  'dashboard_zombie_banner',
  'reaper_health_scare',
]);

/**
 * Count processes in a zombie group list (server bucket shape).
 * @param {Array<{count?: number}>} groups
 */
function countGroups(groups) {
  if (!Array.isArray(groups) || groups.length === 0) return 0;
  return groups.reduce((n, g) => n + (typeof g.count === 'number' ? g.count : 1), 0);
}

/**
 * Build observe-only dual-run fields from the would-be actionable zombie list
 * (legacy spending+unsupervised shape). Never invents RED under shadow.
 *
 * @param {object} opts
 * @param {string} opts.classifierMode
 * @param {Array} [opts.legacyWouldBeZombies] — grouped zombie tiles (pre-dark)
 * @param {Array} [opts.newWouldBeZombies] — optional new-classifier would-be list
 * @param {string[]} [opts.extraReasonCodes]
 */
function buildObserveDualRun(opts = {}) {
  const legacy = Array.isArray(opts.legacyWouldBeZombies) ? opts.legacyWouldBeZombies : [];
  const neu = Array.isArray(opts.newWouldBeZombies) ? opts.newWouldBeZombies : legacy;
  const legacyCount = countGroups(legacy);
  const newCount = countGroups(neu);
  const wouldBeActionableRed = legacyCount > 0 || newCount > 0;
  const reasonCodes = [];
  if (wouldBeActionableRed) {
    reasonCodes.push('WOULD_BE_ACTIONABLE_RED');
    if (legacyCount > 0) reasonCodes.push('LEGACY_SPEND_UNSUPERVISED_SHAPE');
    if (newCount > 0 && neu !== legacy) reasonCodes.push('NEW_CLASSIFIER_WOULD_BE_RED');
    reasonCodes.push('SHADOW_OBSERVE_ONLY');
  } else {
    reasonCodes.push('NO_WOULD_BE_RED');
  }
  if (Array.isArray(opts.extraReasonCodes)) {
    for (const c of opts.extraReasonCodes) {
      if (c && !reasonCodes.includes(c)) reasonCodes.push(c);
    }
  }
  return {
    wouldBeActionableRed,
    wouldBeCount: Math.max(legacyCount, newCount),
    legacyWouldBeCount: legacyCount,
    newWouldBeCount: newCount,
    reasonCodes,
    // Observe rows: strip reap affordance metadata for consumers.
    items: legacy.map((g) => ({
      id: g.id,
      name: g.name,
      path: g.path,
      count: g.count,
      providers: g.providers,
      root: g.root,
      supervised: g.supervised,
      observeOnly: true,
      actionable: false,
    })),
  };
}

/**
 * Per-surface dual-write evaluation. Under shadow (or any non-armed mode),
 * every surface has actionableRed=false; observe fields still populated.
 *
 * @param {object} opts
 * @param {string} opts.classifierMode
 * @param {object} [opts.observe] — from buildObserveDualRun
 * @param {Array} [opts.legacyWouldBeZombies]
 * @param {Array} [opts.newWouldBeZombies]
 */
function evaluateDualWriteSurfaces(opts = {}) {
  const mode = opts.classifierMode || 'shadow';
  const scare = isActionableRedAllowed(mode);
  const observe = opts.observe || buildObserveDualRun(opts);
  const wouldBe = observe.wouldBeActionableRed;
  const count = scare && wouldBe ? observe.wouldBeCount : 0;

  const surfaces = {};
  for (const name of SURFACES) {
    surfaces[name] = {
      surface: name,
      actionableRed: scare && wouldBe,
      actionableCount: scare && wouldBe ? observe.wouldBeCount : 0,
      observeOnly: !scare,
      scareLanguageAllowed: scare && wouldBe,
      reasonCodes: observe.reasonCodes.slice(),
    };
  }

  return {
    classifierMode: mode,
    actionableRedAllowed: scare,
    anySurfaceActionableRed: scare && wouldBe,
    actionableCount: count,
    freezeKillChrome: isFreezeKillAllowed(mode, opts.freezeCapability === true),
    observe,
    surfaces,
  };
}

/**
 * Apply dual-write dark to server bucket output.
 * Actionable `zombie` list is emptied under shadow; observe retains would-be.
 *
 * @param {{ zombie: Array, active: Array, idleCount: number }} raw
 * @param {string} classifierMode
 * @param {object} [extra]
 * @returns {object}
 */
function applyDualWriteToBuckets(raw, classifierMode, extra = {}) {
  const zombie = Array.isArray(raw.zombie) ? raw.zombie : [];
  const active = Array.isArray(raw.active) ? raw.active : [];
  const idleCount = typeof raw.idleCount === 'number' ? raw.idleCount : 0;
  const dual = evaluateDualWriteSurfaces({
    classifierMode,
    legacyWouldBeZombies: zombie,
    newWouldBeZombies: extra.newWouldBeZombies,
    freezeCapability: extra.freezeCapability,
  });
  const scare = dual.actionableRedAllowed;
  return {
    zombie: scare ? zombie : [],
    active,
    idleCount,
    observe: dual.observe,
    dualWrite: dual,
    classifierMode,
  };
}

/**
 * Assert helper used by G0 tests: no surface may show actionable RED under shadow.
 * @param {object} dual — evaluateDualWriteSurfaces result
 * @returns {boolean}
 */
function assertNoActionableRedUnderShadow(dual) {
  if (!dual || typeof dual !== 'object') return false;
  if (isActionableRedAllowed(dual.classifierMode)) return true; // not a shadow assert
  if (dual.anySurfaceActionableRed) return false;
  for (const name of SURFACES) {
    const s = dual.surfaces && dual.surfaces[name];
    if (!s) return false;
    if (s.actionableRed || s.actionableCount > 0 || s.scareLanguageAllowed) return false;
  }
  return true;
}

/**
 * Neutral (non-scare) copy for observe-only would-be rows under shadow.
 * Plan: zero zombie scare language on SUPERVISED/KEEP; observe census allowed.
 */
function observeOnlyBannerCopy(observe) {
  if (!observe || !observe.wouldBeActionableRed) {
    return 'No unsupervised paid-spend candidates in observe dual-run.';
  }
  const n = observe.wouldBeCount || 0;
  return `${n} observe-only candidate${n === 1 ? '' : 's'} (shadow mode — not actionable; investigate only).`;
}

/**
 * W10 / P7 — Cross-surface dual-write final asserts (release pack).
 *
 * Under shadow: every named surface non-actionable; observe dual-run may still
 * light wouldBeActionableRed (dark ≠ silence).
 * Under armed + joint would-be: all surfaces light together (joint light-up).
 * Under armed + no would-be: all surfaces stay dark.
 *
 * @param {object} [opts]
 * @param {string} [opts.classifierMode]
 * @param {Array} [opts.legacyWouldBeZombies]
 * @param {boolean} [opts.freezeCapability]
 * @returns {{ ok: boolean, failures: string[], dual: object, final: true }}
 */
function assertCrossSurfaceDualWriteFinal(opts = {}) {
  const mode = opts.classifierMode || 'shadow';
  const dual = evaluateDualWriteSurfaces({
    classifierMode: mode,
    legacyWouldBeZombies: opts.legacyWouldBeZombies,
    newWouldBeZombies: opts.newWouldBeZombies,
    freezeCapability: opts.freezeCapability,
    observe: opts.observe,
  });
  const failures = [];
  const scare = isActionableRedAllowed(mode);
  const wouldBe = !!(dual.observe && dual.observe.wouldBeActionableRed);

  for (const name of SURFACES) {
    const s = dual.surfaces && dual.surfaces[name];
    if (!s) {
      failures.push(`missing_surface:${name}`);
      continue;
    }
    if (!scare) {
      if (s.actionableRed || s.actionableCount > 0 || s.scareLanguageAllowed) {
        failures.push(`shadow_surface_actionable:${name}`);
      }
      if (!s.observeOnly) {
        failures.push(`shadow_surface_not_observe_only:${name}`);
      }
    } else if (wouldBe) {
      // Joint armed light-up: every scare surface must agree.
      if (!s.actionableRed) {
        failures.push(`armed_joint_surface_dark:${name}`);
      }
    } else if (s.actionableRed || s.actionableCount > 0) {
      failures.push(`armed_no_wouldbe_but_actionable:${name}`);
    }
  }

  if (!scare) {
    if (dual.anySurfaceActionableRed) {
      failures.push('shadow_anySurfaceActionableRed');
    }
    if (!assertNoActionableRedUnderShadow(dual)) {
      failures.push('assertNoActionableRedUnderShadow');
    }
  } else if (wouldBe) {
    if (!dual.anySurfaceActionableRed) {
      failures.push('armed_joint_anySurfaceActionableRed_false');
    }
  }

  return {
    ok: failures.length === 0,
    failures,
    dual,
    final: true,
    classifierMode: mode,
    jointWouldBe: wouldBe,
    surfaces: SURFACES.slice(),
  };
}

module.exports = {
  SURFACES,
  countGroups,
  buildObserveDualRun,
  evaluateDualWriteSurfaces,
  applyDualWriteToBuckets,
  assertNoActionableRedUnderShadow,
  observeOnlyBannerCopy,
  assertCrossSurfaceDualWriteFinal,
};

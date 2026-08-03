// W7 / SC4 — Cache-first radar paint, durable last-known, Why min payload.
//
// Cold/warm first paint must be ≤1000 ms from cache (never block on full sweep).
// Cached RED is never actionable (stale / shadow / sweepError ⇒ suppress).
// Freeze/Kill must not act on cache-only identity (require live identity fields).

const fs = require('node:fs');
const path = require('node:path');
const {
  applyDualWriteToBuckets,
  evaluateDualWriteSurfaces,
  buildObserveDualRun,
  assertNoActionableRedUnderShadow,
} = require('./dual-write.js');
const { isActionableRedAllowed, isFreezeKillAllowed } = require('./mode.js');
const { parseSweepJson, jsonSafeStringify, sanitizeProcessFields } = require('./json-safe.js');

/** First-paint budget (SC4). */
const PAINT_BUDGET_MS = 1000;

/** Schema version for durable last-known store. */
const LAST_KNOWN_SCHEMA = 'w7-last-known-v1';

/**
 * Closed treat enum for Why / Investigate deep-brief (mode + capability conditioned).
 * @type {readonly string[]}
 */
const RECOMMENDED_NEXT = Object.freeze([
  'KEEP',
  'INVESTIGATE',
  'OBSERVE_ONLY',
  'FREEZE_THEN_KILL',
  'ABSTAIN_WAIT',
  'OWNED_NO_KILL',
]);

const RECOMMENDED_NEXT_SET = new Set(RECOMMENDED_NEXT);

/** Default durable path under skill root (overridable). */
function defaultLastKnownPath(skillRoot) {
  const root = skillRoot || path.join(__dirname, '..');
  return path.join(root, '.zh-last-known.json');
}

/**
 * Compute cacheAge ms from lastSweepAt (Date|number|string|null).
 * @param {Date|number|string|null|undefined} lastSweepAt
 * @param {number} [now]
 * @returns {number|null}
 */
function computeCacheAgeMs(lastSweepAt, now = Date.now()) {
  if (lastSweepAt == null) return null;
  let t;
  if (lastSweepAt instanceof Date) t = lastSweepAt.getTime();
  else if (typeof lastSweepAt === 'number') t = lastSweepAt;
  else t = Date.parse(String(lastSweepAt));
  if (!Number.isFinite(t)) return null;
  return Math.max(0, now - t);
}

/**
 * Build a durable last-known snapshot (counts + non-actionable tile summaries).
 * On-disk store is always forced non-actionable (untrusted input on load).
 *
 * @param {object} state
 * @returns {object}
 */
function buildLastKnownSnapshot(state = {}) {
  const buckets = state.buckets || {
    zombie: state.zombie || [],
    active: state.active || [],
    idleCount: state.idleCount || 0,
    observe: state.observe || null,
  };
  const tiles = [];
  const pushTiles = (list, kind) => {
    for (const g of list || []) {
      tiles.push({
        id: g.id || g.pid || null,
        name: g.name || '?',
        path: g.path || '',
        count: g.count || 1,
        kind, // informational only — never actionable from cache
        actionable: false,
        reasonCodes: Array.isArray(g.reasonCodes) ? g.reasonCodes.slice(0, 16) : [],
        quadVerdict: g.quadVerdict || g.lastVerdict || null,
        ownershipBadge: g.ownershipBadge || null,
        providers: g.providers || [],
        pids: Array.isArray(g.pids) ? g.pids.slice(0, 40).map(String) : [],
      });
    }
  };
  // Never persist actionable scare tiles — store observe-only summaries.
  pushTiles(buckets.observe && buckets.observe.items ? buckets.observe.items : [], 'observe');
  pushTiles(buckets.active || [], 'active');
  // If zombie list present (armed path), still force non-actionable on disk.
  pushTiles((buckets.zombie || []).map((z) => ({ ...z, actionable: false })), 'would_be');

  return {
    schema: LAST_KNOWN_SCHEMA,
    writtenAt: state.writtenAt || Date.now(),
    lastSweepAt: state.lastSweepAt
      ? (state.lastSweepAt instanceof Date
        ? state.lastSweepAt.toISOString()
        : state.lastSweepAt)
      : null,
    lastSweepMs: state.lastSweepMs != null ? state.lastSweepMs : null,
    counts: {
      zombieActionable: 0, // durable store never claims actionable RED
      observeWouldBe: (buckets.observe && buckets.observe.wouldBeCount) || 0,
      active: (buckets.active || []).reduce((n, g) => n + (g.count || 1), 0),
      idle: buckets.idleCount || 0,
      hiddenNonEngine: state.hiddenNonEngine || 0,
    },
    tiles,
    observe: buckets.observe
      ? {
          wouldBeActionableRed: !!buckets.observe.wouldBeActionableRed,
          wouldBeCount: buckets.observe.wouldBeCount || 0,
          reasonCodes: (buckets.observe.reasonCodes || []).slice(),
        }
      : { wouldBeActionableRed: false, wouldBeCount: 0, reasonCodes: ['NO_WOULD_BE_RED'] },
    classifierMode: state.classifierMode || 'shadow',
    atlasHealth: state.atlasHealth || 'UNKNOWN',
    reasonCodes: Array.isArray(state.reasonCodes) ? state.reasonCodes.slice(0, 32) : [],
    // Force non-actionable chrome marker
    actionableRed: false,
    fromCache: true,
  };
}

/**
 * Write durable last-known JSON (atomic tmp + rename when possible).
 * @param {string} filePath
 * @param {object} snapshot
 * @returns {{ ok: boolean, path: string, error?: string }}
 */
function writeDurableLastKnown(filePath, snapshot) {
  const snap = buildLastKnownSnapshot(snapshot);
  // Always stamp non-actionable on write.
  snap.actionableRed = false;
  snap.counts = { ...snap.counts, zombieActionable: 0 };
  try {
    const dir = path.dirname(filePath);
    fs.mkdirSync(dir, { recursive: true });
    const tmp = filePath + '.tmp';
    fs.writeFileSync(tmp, jsonSafeStringify(snap), 'utf8');
    fs.renameSync(tmp, filePath);
    return { ok: true, path: filePath };
  } catch (e) {
    return { ok: false, path: filePath, error: String(e && e.message || e) };
  }
}

/**
 * Load durable last-known. Schema-validate; force non-actionable on any doubt.
 * @param {string} filePath
 * @returns {{ ok: boolean, snapshot: object|null, sweepError: string|null }}
 */
function loadDurableLastKnown(filePath) {
  try {
    if (!filePath || !fs.existsSync(filePath)) {
      return { ok: false, snapshot: null, sweepError: null };
    }
    const raw = fs.readFileSync(filePath, 'utf8');
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      return {
        ok: false,
        snapshot: null,
        sweepError: 'last-known parse failed: ' + (e && e.message),
      };
    }
    if (!parsed || typeof parsed !== 'object' || parsed.schema !== LAST_KNOWN_SCHEMA) {
      return { ok: false, snapshot: null, sweepError: 'last-known schema invalid' };
    }
    // Force non-actionable (disk is untrusted).
    const snap = sanitizeProcessFields({
      ...parsed,
      actionableRed: false,
      counts: {
        ...(parsed.counts || {}),
        zombieActionable: 0,
      },
      fromCache: true,
    });
    return { ok: true, snapshot: snap, sweepError: null };
  } catch (e) {
    return {
      ok: false,
      snapshot: null,
      sweepError: 'last-known read failed: ' + (e && e.message),
    };
  }
}

/**
 * Suppress actionable RED from any cache-shaped paint input.
 * Law: shadow OR sweepError OR stale/fromCache ⇒ no actionable RED.
 *
 * @param {object} raw — { zombie, active, idleCount } or dual-write buckets
 * @param {object} opts
 * @returns {object}
 */
function suppressActionableCachedRed(raw, opts = {}) {
  const mode = opts.classifierMode || 'shadow';
  const scare = isActionableRedAllowed(mode);
  const sweepError = opts.sweepError != null && opts.sweepError !== '';
  const fromCache = opts.fromCache !== false; // default true for cache path
  const forceSuppress = !scare || sweepError || fromCache || opts.forceNonActionable === true;

  const dual = applyDualWriteToBuckets(
    {
      zombie: Array.isArray(raw.zombie) ? raw.zombie : [],
      active: Array.isArray(raw.active) ? raw.active : [],
      idleCount: typeof raw.idleCount === 'number' ? raw.idleCount : 0,
    },
    mode,
    { freezeCapability: opts.freezeCapability === true },
  );

  if (forceSuppress) {
    return {
      ...dual,
      zombie: [], // never actionable from cache / error / shadow
      actionableRed: false,
      anySurfaceActionableRed: false,
      cacheSuppressed: true,
      suppressReason: sweepError
        ? 'sweep_error_abstain'
        : (!scare ? 'shadow_or_unarmed' : 'cache_stale_non_actionable'),
      dualWrite: {
        ...dual.dualWrite,
        anySurfaceActionableRed: false,
        actionableCount: 0,
        surfaces: Object.fromEntries(
          Object.entries((dual.dualWrite && dual.dualWrite.surfaces) || {}).map(([k, s]) => [
            k,
            {
              ...s,
              actionableRed: false,
              actionableCount: 0,
              scareLanguageAllowed: false,
              observeOnly: true,
            },
          ]),
        ),
      },
    };
  }
  return {
    ...dual,
    actionableRed: dual.dualWrite.anySurfaceActionableRed,
    anySurfaceActionableRed: dual.dualWrite.anySurfaceActionableRed,
    cacheSuppressed: false,
    suppressReason: null,
  };
}

/**
 * Mode- and capability-conditioned closed treat recommendation.
 * Shadow pre-arm never recommends FREEZE_THEN_KILL as scare path.
 *
 * @param {object} candidate
 * @param {object} opts — { classifierMode, freezeCapability, sweepError }
 * @returns {string}
 */
function recommendNext(candidate = {}, opts = {}) {
  const mode = String(opts.classifierMode || 'shadow').toLowerCase();
  const freezeCap = opts.freezeCapability === true;
  const scare = isActionableRedAllowed(mode);
  const owned = !!(candidate.ownership && (candidate.ownership.owned || candidate.ownership.keep
    || candidate.ownership.failClosed));
  const badgeOwned = !!(candidate.ownershipBadge && (candidate.ownershipBadge.owned
    || candidate.ownershipBadge.keep));
  if (owned || badgeOwned) return 'OWNED_NO_KILL';

  if (opts.sweepError) return 'ABSTAIN_WAIT';

  const verdict = String(candidate.quadVerdict || candidate.lastVerdict || candidate.verdict || '');
  if (verdict === 'ABSTAIN' || (candidate.quad && candidate.quad.abstain)) return 'ABSTAIN_WAIT';
  if (verdict === 'KEEP' || (candidate.quad && candidate.quad.keep)) return 'KEEP';
  if (candidate.supervisionStatus === 'SUPERVISED' || candidate.supervised === true) return 'KEEP';

  // Would-be joint positive under shadow → observe only / investigate, never reap scare.
  if (candidate.wouldBeActionableRed || verdict === 'WOULD_BE_RED') {
    if (!scare) return 'OBSERVE_ONLY';
    if (!freezeCap) return 'INVESTIGATE'; // armed scare but no freeze capability → no FREEZE_THEN_KILL sole path
    return 'FREEZE_THEN_KILL';
  }

  if (candidate.supervisionStatus === 'UNCERTAIN') return 'ABSTAIN_WAIT';
  return 'INVESTIGATE';
}

/**
 * Plain-language leg summary for Why min (no full resweep).
 * @param {object} candidate
 * @returns {object}
 */
function legSummary(candidate = {}) {
  const own = candidate.ownership || {};
  return {
    engine: candidate.engineClass || candidate.engineReason || (candidate.isEngine ? 'engine-positive' : 'unknown'),
    spend: candidate.spendStatus || candidate.spendReason
      || (candidate.spendingNow ? 'spending' : 'not-spending'),
    supervision: candidate.supervisionStatus
      || (candidate.supervised ? 'SUPERVISED' : 'unknown'),
    ownership: own.failClosed
      ? 'KEEP (IPC fail-closed)'
      : (own.owned || own.keep ? 'Anchor-owned KEEP' : 'not registered'),
  };
}

/**
 * Why min payload from cache — never blocks on full sweep.
 *
 * @param {object} candidate — row from cache / last-known
 * @param {object} opts
 * @returns {object}
 */
function buildWhyMinPayload(candidate = {}, opts = {}) {
  const cacheAge = opts.cacheAgeMs != null
    ? opts.cacheAgeMs
    : computeCacheAgeMs(opts.lastSweepAt, opts.now);
  const freezeCapability = opts.freezeCapability === true;
  const classifierMode = opts.classifierMode || 'shadow';
  const lastVerdict = candidate.quadVerdict
    || candidate.lastVerdict
    || candidate.verdict
    || (candidate.wouldBeActionableRed ? 'WOULD_BE_RED' : 'UNKNOWN');
  const reasonCodes = Array.isArray(candidate.reasonCodes)
    ? candidate.reasonCodes.slice()
    : (candidate.quad && Array.isArray(candidate.quad.reasonCodes)
      ? candidate.quad.reasonCodes.slice()
      : []);
  if (opts.sweepError && !reasonCodes.includes('SWEEP_ERROR')) {
    reasonCodes.push('SWEEP_ERROR');
  }
  if (classifierMode === 'shadow' && !reasonCodes.includes('SHADOW_OBSERVE_ONLY')
    && (candidate.wouldBeActionableRed || lastVerdict === 'WOULD_BE_RED')) {
    reasonCodes.push('SHADOW_OBSERVE_ONLY');
  }
  const recommended = recommendNext(candidate, {
    classifierMode,
    freezeCapability,
    sweepError: opts.sweepError,
  });
  return {
    fromCache: true,
    blocksFirstPaint: false,
    requiresFullSweep: false,
    reasonCodes,
    lastVerdict,
    cacheAgeMs: cacheAge,
    cacheAge: cacheAge,
    freezeCapability: opts.freezeCapability == null ? null : freezeCapability,
    classifierMode,
    ownershipBadge: candidate.ownershipBadge || (candidate.ownership
      ? {
          owned: !!candidate.ownership.owned,
          keep: !!candidate.ownership.keep,
          failClosed: !!candidate.ownership.failClosed,
          label: candidate.ownership.label || null,
        }
      : null),
    legSummary: legSummary(candidate),
    recommendedNext: recommended,
    treatEnum: RECOMMENDED_NEXT.slice(),
    uiCopy: {
      uncertainNotRed: 'Uncertain ≠ red — abstain, never scare',
      freezeBeforeKill: 'Freeze before Kill',
      shadowVsArmed: classifierMode === 'shadow'
        ? 'shadow (observe-only; Freeze/Kill disabled)'
        : `mode=${classifierMode}`,
      ownership: 'ownership badge on every candidate',
    },
  };
}

/**
 * Server radar state fields required by SC4 / W7.
 *
 * @param {object} opts
 * @returns {object}
 */
function buildRadarServerFields(opts = {}) {
  const cacheAgeMs = opts.cacheAgeMs != null
    ? opts.cacheAgeMs
    : computeCacheAgeMs(opts.lastSweepAt, opts.now);
  const mode = opts.classifierMode || 'shadow';
  const canary = opts.canaryReceipt || {
    present: false,
    valid: false,
  };
  return {
    sweepError: opts.sweepError != null ? opts.sweepError : null,
    cacheAge: cacheAgeMs,
    cacheAgeMs,
    freezeCapability: opts.freezeCapability === true,
    atlasHealth: opts.atlasHealth || 'UNKNOWN',
    reasonCodes: Array.isArray(opts.reasonCodes) ? opts.reasonCodes.slice() : [],
    classifierMode: mode,
    canaryReceipt: canary,
    canaryReceiptStatus: canary.valid
      ? 'valid'
      : (canary.present ? 'present_invalid' : 'none'),
    sweepInProgress: !!opts.sweepInProgress,
    lastSweepAt: opts.lastSweepAt || null,
    lastSweepMs: opts.lastSweepMs != null ? opts.lastSweepMs : null,
    fromCache: opts.fromCache !== false,
    paintPath: opts.paintPath || (opts.lastSweepAt ? 'warm' : 'cold'),
  };
}

/**
 * Cache-first radar paint (pure): shell + last-known or skeleton.
 * Never runs a full process sweep. Measures paintMs for SC4 gates.
 *
 * @param {object} opts
 * @returns {object}
 */
function paintRadarFromCache(opts = {}) {
  const t0 = typeof opts.now === 'number' ? opts.now : Date.now();
  const start = process.hrtime.bigint();

  let snapshot = opts.snapshot || null;
  let loadedError = null;
  if (!snapshot && opts.lastKnownPath) {
    const loaded = loadDurableLastKnown(opts.lastKnownPath);
    if (loaded.ok) snapshot = loaded.snapshot;
    else loadedError = loaded.sweepError;
  }

  const cold = !snapshot;
  const paintPath = cold ? 'cold' : 'warm';
  const classifierMode = opts.classifierMode
    || (snapshot && snapshot.classifierMode)
    || 'shadow';
  const sweepError = opts.sweepError != null
    ? opts.sweepError
    : loadedError;
  const freezeCapability = opts.freezeCapability === true;
  const lastSweepAt = opts.lastSweepAt
    || (snapshot && snapshot.lastSweepAt)
    || null;
  const cacheAgeMs = computeCacheAgeMs(lastSweepAt, typeof opts.now === 'number' ? opts.now : Date.now());

  // Build raw bucket shape from snapshot (or empty skeleton).
  const raw = cold
    ? { zombie: [], active: [], idleCount: 0 }
    : {
        zombie: [], // never paint actionable from cache
        active: (snapshot.tiles || []).filter((t) => t.kind === 'active'),
        idleCount: (snapshot.counts && snapshot.counts.idle) || 0,
      };

  // If snapshot has observe would-be, surface as observe dual-run (not actionable).
  if (!cold && snapshot.observe && snapshot.observe.wouldBeActionableRed) {
    raw._observeSeed = snapshot.observe;
  }

  const suppressed = suppressActionableCachedRed(raw, {
    classifierMode,
    freezeCapability,
    sweepError,
    fromCache: true,
    forceNonActionable: true,
  });

  // Restore observe from durable store if dual-write emptied it.
  if (raw._observeSeed && (!suppressed.observe || !suppressed.observe.wouldBeActionableRed)) {
    suppressed.observe = {
      wouldBeActionableRed: !!raw._observeSeed.wouldBeActionableRed,
      wouldBeCount: raw._observeSeed.wouldBeCount || 0,
      reasonCodes: (raw._observeSeed.reasonCodes || []).slice(),
      items: (snapshot.tiles || [])
        .filter((t) => t.kind === 'observe' || t.kind === 'would_be')
        .map((t) => ({
          id: t.id,
          name: t.name,
          path: t.path,
          count: t.count,
          observeOnly: true,
          actionable: false,
        })),
    };
  }

  const serverFields = buildRadarServerFields({
    sweepError,
    lastSweepAt,
    lastSweepMs: opts.lastSweepMs != null
      ? opts.lastSweepMs
      : (snapshot && snapshot.lastSweepMs),
    cacheAgeMs,
    freezeCapability,
    atlasHealth: opts.atlasHealth || (snapshot && snapshot.atlasHealth) || 'UNKNOWN',
    reasonCodes: opts.reasonCodes
      || (snapshot && snapshot.reasonCodes)
      || (suppressed.observe && suppressed.observe.reasonCodes)
      || [],
    classifierMode,
    canaryReceipt: opts.canaryReceipt || { present: false, valid: false },
    sweepInProgress: opts.sweepInProgress === true,
    fromCache: true,
    paintPath,
  });

  const shell = {
    kind: 'radar-shell',
    paintPath,
    skeleton: cold,
    hasLastKnown: !cold,
    counts: cold
      ? { actionableRed: 0, observeWouldBe: 0, active: 0, idle: 0 }
      : {
          actionableRed: 0,
          observeWouldBe: (suppressed.observe && suppressed.observe.wouldBeCount) || 0,
          active: (snapshot.counts && snapshot.counts.active) || 0,
          idle: (snapshot.counts && snapshot.counts.idle) || 0,
        },
    tiles: cold ? [] : (snapshot.tiles || []).map((t) => ({ ...t, actionable: false })),
    uiCopy: {
      uncertainNotRed: 'Uncertain ≠ red',
      freezeBeforeKill: 'Freeze before Kill',
      ownershipBadge: true,
      shadowVsArmed: classifierMode === 'shadow' ? 'shadow' : classifierMode,
    },
    actionableRed: false,
    anySurfaceActionableRed: false,
  };

  const end = process.hrtime.bigint();
  const paintMs = Number(end - start) / 1e6;

  return {
    ok: true,
    paintPath,
    paintMs,
    withinBudget: paintMs <= PAINT_BUDGET_MS,
    budgetMs: PAINT_BUDGET_MS,
    shell,
    buckets: suppressed,
    serverFields,
    dualWrite: suppressed.dualWrite,
    observe: suppressed.observe,
    fullSweepBackgroundOnly: true,
    blockedOnFullSweep: false,
    measuredAt: t0,
  };
}

/**
 * Identity is cache-only when createTime and/or imagePath are missing —
 * Freeze/Kill must refuse pid-only cache rows. A complete triple may proceed
 * into the sole boundary which always live-reprobes before suspend/kill.
 *
 * @param {{ pid?: unknown, createTime?: unknown, imagePath?: unknown, cacheOnly?: boolean }} identity
 * @returns {{ allow: boolean, cacheOnly: boolean, reason: string|null }}
 */
function identityActionGate(identity = {}) {
  const pid = identity.pid != null ? Number(identity.pid) : NaN;
  if (!Number.isFinite(pid) || pid <= 0) {
    return { allow: false, cacheOnly: true, reason: 'FREEZE_IDENTITY_REQUIRED' };
  }
  const hasCreate = identity.createTime != null && Number.isFinite(Number(identity.createTime));
  const hasImage = !!(identity.imagePath || identity.path || identity.image);
  // Explicit incomplete / cache-only pid row ⇒ refuse (never act on cache-only identity).
  if (identity.cacheOnly === true || !hasCreate || !hasImage) {
    return { allow: false, cacheOnly: true, reason: 'CACHE_ONLY_IDENTITY_REFUSED' };
  }
  return { allow: true, cacheOnly: false, reason: null };
}

/**
 * Cross-surface assert: abstain / sweepError / shadow ⇒ no actionable RED.
 * @param {object} dualOrPaint
 * @returns {boolean}
 */
function crossSurfaceNoRedOnAbstain(dualOrPaint) {
  const dual = dualOrPaint.dualWrite || dualOrPaint;
  if (!dual || typeof dual !== 'object') return false;
  if (dual.anySurfaceActionableRed) return false;
  if (dual.actionableRed) return false;
  if (dual.surfaces) {
    for (const s of Object.values(dual.surfaces)) {
      if (s && (s.actionableRed || s.actionableCount > 0 || s.scareLanguageAllowed)) return false;
    }
  }
  // Prefer shared shadow helper when classifierMode is shadow
  if (dual.classifierMode && !isActionableRedAllowed(dual.classifierMode)) {
    return assertNoActionableRedUnderShadow(dual);
  }
  return true;
}

module.exports = {
  PAINT_BUDGET_MS,
  LAST_KNOWN_SCHEMA,
  RECOMMENDED_NEXT,
  RECOMMENDED_NEXT_SET,
  defaultLastKnownPath,
  computeCacheAgeMs,
  buildLastKnownSnapshot,
  writeDurableLastKnown,
  loadDurableLastKnown,
  suppressActionableCachedRed,
  recommendNext,
  legSummary,
  buildWhyMinPayload,
  buildRadarServerFields,
  paintRadarFromCache,
  identityActionGate,
  crossSurfaceNoRedOnAbstain,
  // re-export for tests
  parseSweepJson,
  jsonSafeStringify,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  evaluateDualWriteSurfaces,
  buildObserveDualRun,
};

// Zombie Hunter — System-Wide Sentinel server (port 48484)
//
// TOKEN-SPEND-FIRST. The threat is a process spending paid AI tokens with
// nobody steering it. The page leads with: who is burning tokens unsupervised
// (reap), how much $/min is going out, and (folded away) everything that is NOT
// spending. Proxied by Anchor's Zombie Hunter button.
//
// classifyAll() runs in a forked worker (~10-20s: process tree + signature
// checks + network sample + token-log ledger) so the page never blocks. The
// server holds the last result + a short spend-recency memory (network
// connections are transient) and buckets engines: zombie (spending +
// unsupervised) / active (spending + supervised) / idle (hidden).
//
// Safety: OBSERVE-ONLY. Freeze (reversible) before Kill (confirm). Nothing auto.

const http = require('node:http');
const cp = require('node:child_process');
const path = require('node:path');
const { TelemetryDaemon } = require('./daemon.js');
const { ForensicsAnalyzer, buildIncidents } = require('./forensics.js');
const {
  resolveClassifierMode,
  getModePublicStatus,
  isActionableRedAllowed,
  isFreezeKillAllowed,
} = require('./mode.js');
const {
  applyDualWriteToBuckets,
  observeOnlyBannerCopy,
} = require('./dual-write.js');
const {
  getCatalogsPublicPayload,
  REASON_CATALOG_VERSION,
  DOCTOR_ISSUE_CATALOG_VERSION,
} = require('./reason-catalog.js');
const {
  ownershipStubContract,
  OWNERSHIP_STUB_VERSION,
} = require('./ownership.js');
const {
  resolveOwnershipBadge,
  shouldShowFreezeKill,
  renderOwnershipBadgeChipHtml,
  renderTileActsHtml,
  attachOwnershipToGroup,
  ownershipBadgeUiContract,
} = require('./ownership-ui.js');
const {
  computeClassifierHealthMetrics,
  getHealthMetricsPublicPayload,
} = require('./health-metrics.js');
const {
  freezeCandidate,
  unfreezeCandidate,
  killCandidate,
  issueKillConfirmToken,
  validateKillConfirm,
  probeFreezeCapability,
  soleFreezeKillServiceBoundary,
  FREEZE_METHOD,
  SPEND_POSTCONDITION,
  SOLE_BOUNDARY_ID,
} = require('./freeze.js');
const { parseSweepJson } = require('./json-safe.js');
const {
  PAINT_BUDGET_MS,
  defaultLastKnownPath,
  computeCacheAgeMs,
  buildLastKnownSnapshot,
  writeDurableLastKnown,
  loadDurableLastKnown,
  suppressActionableCachedRed,
  buildWhyMinPayload,
  buildRadarServerFields,
  paintRadarFromCache,
  identityActionGate,
  recommendNext,
  RECOMMENDED_NEXT,
} = require('./radar-cache.js');
const {
  ENGINE_IDS,
  ENGINE_TRANSPORT,
  SHELL_PAINT_BUDGET_MS,
  FIRST_PROMPT_BUDGET_MS,
  P5_START_PLUMBING,
  listEngineToggle,
  buildInvestigateSlimSeed,
  buildInvestigateDeepBrief,
  buildDoctorShortSeed,
  buildSessionStartPlan,
  doctorShellBeforeSessionContract,
  assertP5StartPlumbingGreen,
  formatInvestigateSlimSeedText,
  formatDoctorShortSeedText,
} = require('./session-start.js');
const {
  BANNER_DOCTOR_SEED_VERSION,
  normalizeBannerIssue,
  buildDashboardHealthBannerIssue,
  buildReaperHealthBannerIssue,
  buildDoctorNavigationFromBanner,
  buildBannerDiagnosePlan,
  attemptAsyncBannerDiagnoseStart,
  buildClickableBannerContract,
  extractBannerSeedFields,
  assertBannerDoctorFailSafeWithDualWrite,
} = require('./health-banner-doctor.js');

const PORT = parseInt(process.env.ZH_PORT || '48484', 10);
const SWEEP_INTERVAL_MS = 60_000;
/** Client GUI auto-refresh while tab is open (operator hunt watch). Default 90s. */
const UI_REFRESH_MS = Math.max(30_000, parseInt(process.env.ZH_UI_REFRESH_MS || '90000', 10) || 90_000);
const RECENT_SPEND_MS = 180_000;   // a process seen spending within 3 min still counts (covers between-calls gaps)
const WORKER = path.join(__dirname, 'sweep-worker.cjs');
const LAST_KNOWN_PATH = process.env.ZH_LAST_KNOWN_PATH || defaultLastKnownPath();

const daemon = new TelemetryDaemon();

/** Cached freezeCapability probe (non-elevated operator envelope).
 *  MUST NOT block HTTP paint: PowerShell NtSuspend probe can take 8–12s and
 *  Anchor's proxy timeout is ~5–15s. Cold path returns a fail-safe pending
 *  result and finishes the real probe on setImmediate / listen warm-up. */
let _capCache = null;
let _capCacheAt = 0;
let _capProbeInFlight = false;
const CAP_CACHE_MS = 60_000;

const CAP_PENDING = Object.freeze({
  freezeCapability: false,
  elevated: false,
  method: FREEZE_METHOD,
  envelope: 'non_elevated_operator',
  proven: false,
  reason: 'probe_pending',
});

function _capFromEnv() {
  if (process.env.ZH_FREEZE_CAPABILITY === '1' || process.env.ZH_FREEZE_CAPABILITY === 'true') {
    return {
      freezeCapability: true,
      elevated: false,
      method: FREEZE_METHOD,
      envelope: 'non_elevated_operator',
      proven: true,
      reason: 'env_override',
    };
  }
  if (process.env.ZH_FREEZE_CAPABILITY === '0' || process.env.ZH_FREEZE_CAPABILITY === 'false') {
    return {
      freezeCapability: false,
      elevated: false,
      method: FREEZE_METHOD,
      envelope: 'non_elevated_operator',
      proven: false,
      reason: 'env_override_false',
    };
  }
  return null;
}

function _scheduleFreezeProbe() {
  if (_capProbeInFlight) return;
  _capProbeInFlight = true;
  setImmediate(() => {
    try {
      const env = _capFromEnv();
      _capCache = env || probeFreezeCapability();
    } catch (err) {
      _capCache = {
        freezeCapability: false,
        elevated: false,
        method: FREEZE_METHOD,
        envelope: 'non_elevated_operator',
        proven: false,
        reason: 'probe_error',
        error: err && err.message ? err.message : 'probe_failed',
      };
    }
    _capCacheAt = Date.now();
    _capProbeInFlight = false;
  });
}

function currentFreezeCapability() {
  const now = Date.now();
  if (_capCache && now - _capCacheAt < CAP_CACHE_MS) return _capCache;

  const env = _capFromEnv();
  if (env) {
    _capCache = env;
    _capCacheAt = now;
    return _capCache;
  }

  // Warm but expired cache: serve stale while a background re-probe runs.
  if (_capCache) {
    _scheduleFreezeProbe();
    return _capCache;
  }

  // Cold start: never block the request on PowerShell (was ~12s vs Anchor 5s).
  _scheduleFreezeProbe();
  return CAP_PENDING;
}

/** Live mode resolution (forced shadow without version-matched canaryReceipt). */
function currentMode() {
  return resolveClassifierMode();
}
function modePublic() {
  const cap = currentFreezeCapability();
  return getModePublicStatus({ freezeCapability: cap.freezeCapability === true });
}

// ── cache (W7: in-memory last-known + durable cold store; full sweep background-only) ──
let engines = [];
let hiddenNonEngine = 0;
let hiddenSample = [];
let otherProcesses = [];
let ledger = { sessions: [], totals: { activeSessions: 0, usdRecent: 0, usdPerMin: 0, tokensRecent: 0 }, windowMin: 10 };
let incidents = [];
let lastSweepAt = null;
let lastSweepMs = null;
let sweepInProgress = false;
let sweepError = null;
let atlasHealth = 'UNKNOWN';
let lastObserve = null;
let lastReasonCodes = [];
let lastHealthMetrics = null; // W10 abstain-rate / unsupervised-spend TP
const recentSpend = new Map();     // pidKey -> lastSpendAtMs
const burnTrend = [];              // { t, usdPerMin } ring (since restart)
let frozenPids = new Set();

function pidKey(e) { return e.pid + '|' + e.name; }

/** Persist non-actionable last-known for cold restart paint (SC4). */
function persistLastKnown() {
  try {
    const b = buckets();
    writeDurableLastKnown(LAST_KNOWN_PATH, {
      buckets: b,
      lastSweepAt,
      lastSweepMs,
      hiddenNonEngine,
      classifierMode: currentMode().mode,
      atlasHealth,
      reasonCodes: lastReasonCodes,
    });
  } catch (_) { /* durable write is best-effort */ }
}

/** Cold start: load durable last-known summaries (never actionable). */
function hydrateFromDurableLastKnown() {
  const loaded = loadDurableLastKnown(LAST_KNOWN_PATH);
  if (!loaded.ok || !loaded.snapshot) return;
  const snap = loaded.snapshot;
  if (snap.lastSweepAt) {
    const t = Date.parse(String(snap.lastSweepAt));
    if (Number.isFinite(t)) lastSweepAt = new Date(t);
  }
  if (snap.lastSweepMs != null) lastSweepMs = snap.lastSweepMs;
  if (snap.atlasHealth) atlasHealth = snap.atlasHealth;
  if (snap.counts && typeof snap.counts.hiddenNonEngine === 'number') {
    hiddenNonEngine = snap.counts.hiddenNonEngine;
  }
  if (snap.observe) lastObserve = snap.observe;
  // engines stay empty until first live sweep — paint uses durable tiles via paintRadarFromCache
}

hydrateFromDurableLastKnown();

function runSweep() {
  if (sweepInProgress) return;
  sweepInProgress = true;
  let out = '';
  const child = cp.fork(WORKER, [], { stdio: ['ignore', 'pipe', 'inherit', 'ipc'] });
  child.stdout.on('data', (d) => { out += d.toString(); });
  child.on('close', () => {
    sweepInProgress = false;
    // W7: JSON-safe parse — fail ⇒ sweepError + abstain, never invent RED
    const r = parseSweepJson(out || '');
    if (!r.ok || r.parseFailed) {
      sweepError = r.sweepError || r.error || 'sweep failed';
      // Keep prior cache for paint but force non-actionable via buckets dual-write + suppress
      return;
    }
    sweepError = null;
    engines = r.engines || [];
    hiddenNonEngine = r.hiddenNonEngine || 0;
    hiddenSample = r.hiddenSample || [];
    otherProcesses = Array.isArray(r.otherProcesses) ? r.otherProcesses : [];
    ledger = r.ledger || ledger;
    atlasHealth = r.atlasHealth || (r.spendAtlas && r.spendAtlas.health) || atlasHealth || 'OK';
    if (r.observe) lastObserve = r.observe;
    if (r.observe && Array.isArray(r.observe.reasonCodes)) {
      lastReasonCodes = r.observe.reasonCodes.slice();
    }
    // W10 health fields: prefer classifyAll payload, else recompute
    lastHealthMetrics = r.healthMetrics
      || computeClassifierHealthMetrics(engines);
    const now = Date.now();
    for (const e of engines) {
      if (e.spendingNow || e.burnActivity || e.spendPositive) recentSpend.set(pidKey(e), now);
    }
    for (const [k, t] of recentSpend) if (now - t > 30 * 60 * 1000) recentSpend.delete(k);
    burnTrend.push({
      t: now,
      usdPerMin: Number(ledger.totals.usdPerMinAll != null
        ? ledger.totals.usdPerMinAll
        : ((ledger.totals.usdPerMin || 0) + (ledger.totals.usdPerMinEstimated || 0))) || 0,
    });
    while (burnTrend.length > 60) burnTrend.shift();
    for (const p of r.flaggedForLog || []) { try { daemon.logSuspicious(p); } catch (_) {} }
    try { daemon.cleanOldRecords(7); } catch (_) {}
    incidents = buildIncidents(new ForensicsAnalyzer(daemon).analyzeHistoricalData() || []);
    lastSweepAt = new Date();
    lastSweepMs = r.tookMs;
    persistLastKnown();
  });
  child.on('error', (e) => { sweepInProgress = false; sweepError = String(e.message || e); });
}

// Bucket engines using spend-recency + burn activity, then dual-write-dark under shadow.
// Actionable zombie list is empty when classifierMode is not armed.
// Active = spending/burning tokens AND supervised (or owned KEEP) — always shown.
// burnUncertain = burning but supervision UNCERTAIN (informational, never freeze/kill).
// RED would-be requires atlas spendPositive / wouldBeActionableRed (IP burn alone ≠ RED).
function buckets() {
  const now = Date.now();
  const zombie = [], active = [], burnUncertain = [];
  let idle = 0;
  for (const e of engines) {
    const key = pidKey(e);
    const lastSp = recentSpend.get(key);
    const burning = !!(e.spendingNow || e.burnActivity || e.spendPositive
      || (lastSp && now - lastSp < RECENT_SPEND_MS));
    if (!burning) { idle += 1; continue; }
    const agoMin = (e.spendingNow || e.burnActivity) ? 0
      : (lastSp ? Math.round((now - lastSp) / 60000) : 0);
    const rec = {
      ...e,
      spendAgoMin: agoMin,
      burnActivity: !!(e.burnActivity || e.spendingNow || e.spendPositive),
      providers: (e.providers && e.providers.length)
        ? e.providers
        : (e.activityProviders || []),
    };
    // W3 ownership KEEP: Anchor-owned or IPC fail-closed never zombie-shaped.
    const ownedKeep = !!(e.ownership && (e.ownership.owned || e.ownership.keep || e.ownership.failClosed));
    if (ownedKeep) {
      active.push(rec);
      continue;
    }
    // RED would-be (atlas joint positive) — zombie list (dark under shadow via dual-write)
    if (e.wouldBeActionableRed === true || e.quadVerdict === 'WOULD_BE_RED') {
      zombie.push(rec);
      continue;
    }
    // SUPERVISED (or legacy supervised) burn → active informational
    if (e.supervisionStatus === 'SUPERVISED' || e.supervised === true) {
      active.push(rec);
      continue;
    }
    // UNCERTAIN supervision + burn → show (not idle), no freeze/kill
    if (e.supervisionStatus === 'UNCERTAIN'
      || e.quadVerdict === 'ABSTAIN' || (e.quad && e.quad.abstain)) {
      burnUncertain.push({ ...rec, freezeKill: false, observeOnly: true });
      continue;
    }
    // UNSUPERVISED + burn but NOT atlas-joint-RED → informational, not reap
    if (e.supervisionStatus === 'UNSUPERVISED' || e.unsupervised === true) {
      if (e.spendPositive === true && e.wouldBeActionableRed !== false) {
        zombie.push(rec);
      } else {
        burnUncertain.push({ ...rec, freezeKill: false, observeOnly: true });
      }
      continue;
    }
    // Legacy boolean path
    (e.supervised ? active : zombie).push(rec);
  }
  const group = (list) => {
    const g = {};
    const members = {};
    for (const e of list) {
      const prov = (e.providers || []).join(',') || '—';
      const k = `${e.name}|${e.path}|${prov}|${e.root}`;
      (g[k] ??= { id: sanitizeId(k), name: e.name, path: e.path, providers: e.providers || [], root: e.root,
        parentAlive: e.parentAlive, parentName: e.parentName, supervised: e.supervised, sessionId: e.sessionId,
        pids: [], ages: [], conns: 0, spendAgo: [], sample: e.cmd,
        // W10: plumb ownership onto tiles for badge UI + Freeze/Kill hide
        ownership: e.ownership || null,
        ownershipBadge: e.ownershipBadge || null,
        quadVerdict: e.quadVerdict,
        wouldBeActionableRed: e.wouldBeActionableRed,
        reasonCodes: e.reasonCodes || [],
      });
      (members[k] ??= []).push(e);
      g[k].pids.push(e.pid); g[k].ages.push(e.ageMin); g[k].conns += e.conns || 0; g[k].spendAgo.push(e.spendAgoMin);
      // Prefer KEEP/owned badge if any member is owned
      if (e.ownershipBadge || e.ownership) {
        attachOwnershipToGroup(g[k], members[k]);
      }
    }
    return Object.values(g).map((x) => ({
      ...x, count: x.pids.length,
      minAge: Math.min(...x.ages.filter((a) => a >= 0), Infinity),
      maxAge: Math.max(...x.ages), spendAgoMin: Math.min(...x.spendAgo),
    })).sort((a, b) => b.count - a.count);
  };
  const raw = {
    zombie: group(zombie),
    active: group(active),
    burnUncertain: group(burnUncertain),
    idleCount: idle,
    otherProcesses: otherProcesses.slice(),
    otherCount: otherProcesses.length || hiddenNonEngine,
  };
  const mode = currentMode();
  const cap = currentFreezeCapability();
  // W7: dual-write dark + cache/error suppress (never actionable cached RED)
  const dual = applyDualWriteToBuckets(raw, mode.mode, {
    freezeCapability: cap.freezeCapability === true,
  });
  // Preserve informational buckets dual-write may not copy
  dual.burnUncertain = raw.burnUncertain;
  dual.otherProcesses = raw.otherProcesses;
  dual.otherCount = raw.otherCount;
  if (sweepError || !isActionableRedAllowed(mode.mode)) {
    const suppressed = suppressActionableCachedRed(raw, {
      classifierMode: mode.mode,
      freezeCapability: cap.freezeCapability === true,
      sweepError,
      fromCache: true,
      forceNonActionable: !!sweepError || !isActionableRedAllowed(mode.mode),
    });
    suppressed.burnUncertain = raw.burnUncertain;
    suppressed.active = raw.active; // never hide live burners under shadow
    suppressed.otherProcesses = raw.otherProcesses;
    suppressed.otherCount = raw.otherCount;
    return suppressed;
  }
  return dual;
}

/**
 * Resolve freeze/kill identity from request body and last sweep engines.
 * Prefer explicit {pid, createTime, imagePath}. Cache-only pid fallback is
 * marked so identityActionGate refuses action without live identity triple.
 */
function resolveTargets(body) {
  const out = [];
  if (Array.isArray(body && body.identities)) {
    for (const id of body.identities) {
      if (!id) continue;
      out.push({
        pid: id.pid,
        createTime: id.createTime != null ? id.createTime : id.CreateTimeMs,
        imagePath: id.imagePath || id.path || id.image || '',
        fromCache: id.fromCache === true,
        cacheOnly: id.cacheOnly === true,
      });
    }
  }
  if (out.length === 0 && Array.isArray(body && body.pids)) {
    for (const p of body.pids) {
      const eng = engines.find((e) => String(e.pid) === String(p) || Number(e.pid) === Number(p));
      const createTime = eng && eng.createTime != null ? eng.createTime : (eng && eng.CreateTimeMs);
      const imagePath = (eng && (eng.path || eng.imagePath || eng.name)) || '';
      // Incomplete identity triple from cache ⇒ cache-only refuse (never freeze/kill on pid alone)
      const incomplete = createTime == null || !imagePath;
      out.push({
        pid: p,
        createTime,
        imagePath,
        fromCache: true,
        cacheOnly: incomplete,
      });
    }
  }
  return out;
}

/**
 * Find a cached engine row for Why min payload (no resweep).
 */
function findCachedCandidate(query = {}) {
  const pid = query.pid != null ? String(query.pid) : null;
  const id = query.id != null ? String(query.id) : null;
  for (const e of engines) {
    if (pid && String(e.pid) === pid) return e;
    if (id && (String(e.pid) === id || e.name === id)) return e;
  }
  // Durable last-known tile fallback
  const loaded = loadDurableLastKnown(LAST_KNOWN_PATH);
  if (loaded.ok && loaded.snapshot && Array.isArray(loaded.snapshot.tiles)) {
    for (const t of loaded.snapshot.tiles) {
      if (pid && Array.isArray(t.pids) && t.pids.map(String).includes(pid)) return t;
      if (id && (String(t.id) === id || t.name === id)) return t;
    }
  }
  return null;
}

function sanitizeId(s) { return String(s).replace(/[^a-zA-Z0-9-]/g, '-'); }
function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function fmtTime(d) { return d ? d.toTimeString().slice(0, 8) : '—'; }
function fmtAge(m) {
  if (m == null || m < 0 || !isFinite(m)) return '?';
  if (m < 90) return m + 'm';
  const h = m / 60; return h < 48 ? h.toFixed(0) + 'h' : (h / 24).toFixed(0) + 'd';
}
function usd(n) { return '$' + (n || 0).toFixed(2); }

function tile(g, kind, opts = {}) {
  const ageStr = g.minAge === g.maxAge ? fmtAge(g.minAge) : fmtAge(g.minAge) + '–' + fmtAge(g.maxAge);
  const provStr = (g.providers || []).join(' + ') || 'a provider';
  const spendChip = g.spendAgoMin === 0
    ? `<span class="chip live">● calling ${esc(provStr)} now</span>`
    : `<span class="chip recent">called ${esc(provStr)} ${g.spendAgoMin}m ago</span>`;
  const frozenHere = g.pids.filter((p) => frozenPids.has(p)).length;
  const stateChip = frozenHere ? `<span class="chip frozen">${frozenHere}/${g.count} frozen</span>` : '';
  const observeOnly = kind === 'observe' || opts.observeOnly;
  // W10 ownership UI: Freeze/Kill hidden when owned / fail-closed KEEP
  const acts = renderTileActsHtml(g, {
    freezeKillEnabled: opts.freezeKillEnabled === true,
    observeOnly,
    kind,
  }, esc);
  const ownBadge = resolveOwnershipBadge(g) || g.ownershipBadge || g.ownership;
  const ownChip = renderOwnershipBadgeChipHtml(ownBadge, esc);
  const uiContract = ownershipBadgeUiContract(g, {
    freezeKillEnabled: opts.freezeKillEnabled === true,
    observeOnly,
    kind,
  });
  const whyBody = observeOnly
    ? `<b>Observe-only (shadow mode).</b> Dual-run would-be unsupervised spender shape for <b>${esc(provStr)}</b> — not actionable RED. Uncertain ≠ red. Freeze before Kill (disabled until armed + freezeCapability). Reason codes: SHADOW_OBSERVE_ONLY.`
    : (uiContract.ownedKeep
      ? `<b>Anchor-owned KEEP.</b> Ownership badge: ${esc(uiContract.label || 'Anchor-owned')}. Freeze/Kill hidden — use the Anchor reaper path for registered sessions, never Node kill.`
      : (kind === 'zombie'
        ? `<b>Token-spending zombie.</b> This is an AI engine actively calling <b>${esc(provStr)}</b> (a paid API) and it does <b>not</b> trace up to a live session — ${g.parentAlive ? 'no interactive shell above it' : 'its parent is dead'}. Freeze before Kill.`
        : `<b>Active &amp; supervised.</b> Calling ${esc(provStr)} but rooted in a live session (${esc(g.root)}) — this is your own running work, not a zombie. Uncertain ≠ red.`));
  const rowClass = observeOnly ? 'row observe' : `row ${kind}`;
  const freezeKillAttr = shouldShowFreezeKill(g, {
    freezeKillEnabled: opts.freezeKillEnabled === true,
    observeOnly,
    kind,
  }) ? '1' : '0';
  return `
  <div class="${rowClass}" id="row-${esc(g.id)}" data-freeze-kill-visible="${freezeKillAttr}" data-owned-keep="${uiContract.ownedKeep ? '1' : '0'}">
    <div class="rhead" onclick="tog(this)">
      <span class="caret">▶</span>
      <span class="rname"><span class="mono">${esc(g.name)}</span>${g.count > 1 ? ' ×' + g.count : ''}</span>
      <span class="rmeta">${spendChip}${stateChip}${ownChip}<span class="chip age">${esc(ageStr)}</span><span class="chip count">${g.count}</span></span>
    </div>
    <div class="rbody">
      <div class="kv">
        <span class="k">Spending</span><span class="v">${esc(provStr)} · ${g.conns} live connection${g.conns === 1 ? '' : 's'}${g.spendAgoMin ? ' · last seen ' + g.spendAgoMin + 'm ago' : ' · now'}</span>
        <span class="k">Supervision</span><span class="v">${g.supervised ? 'rooted in a live session (' + esc(g.root) + ')' : (g.parentAlive ? 'no interactive session (root ' + esc(g.root) + ')' : 'parent process is DEAD')}</span>
        <span class="k">Ownership</span><span class="v">${ownBadge ? esc(ownBadge.label || (ownBadge.owned || ownBadge.keep ? 'Anchor-owned KEEP' : 'not owned')) : '—'}</span>
        <span class="k">Session</span><span class="v">Windows session ${esc(g.sessionId)} · age ${esc(ageStr)}</span>
      </div>
      <div class="plist">${esc(g.pids.slice(0, 40).join(' · '))}</div>
      ${acts}
      <div class="why">${whyBody}
        <div class="cmd">${esc((g.sample || '').slice(0, 320))}</div>
      </div>
    </div>
  </div>`;
}

function renderLedger() {
  const t = ledger.totals || {};
  const byEng = t.byEngine || {};
  const engBits = ['claude', 'grok', 'gemini', 'openai']
    .map((e) => (byEng[e] ? `${byEng[e]} ${e}` : null))
    .filter(Boolean)
    .join(' · ');
  const rows = (ledger.sessions || []).slice(0, 16).map((s) => {
    const eng = esc(s.engine || '?');
    const cls = esc(s.evidenceClass || 'activity');
    const hasUsd = (s.evidenceClass === 'measured' || s.evidenceClass === 'estimated')
      && Number(s.usdPerMin) > 0;
    const rate = hasUsd
      ? `${usd(s.usdPerMin)}/min${s.evidenceClass === 'estimated' ? ' ~est' : ''}`
      : (s.tokensRecent ? `${((s.tokensRecent || 0) / 1000).toFixed(0)}k tok` : 'active');
    const tokBit = s.tokensRecent
      ? `${((s.tokensRecent || 0) / 1000).toFixed(0)}k tok`
      : (s.contextTokens ? `${((s.contextTokens || 0) / 1000).toFixed(0)}k ctx` : cls);
    const usdCol = hasUsd
      ? `${usd(s.usdRecent)}${s.evidenceClass === 'estimated' ? ' ~' : ''}`
      : tokBit;
    return `
    <div class="lrow">
      <span class="leng" title="evidence: ${cls}${s.estimateNote ? ' · ' + esc(s.estimateNote) : ''}">${eng}</span>
      <span class="lrate">${rate}</span>
      <span class="lmodel">${esc(s.model || '?')}</span>
      <span class="lcwd">${esc(s.cwd)}</span>
      <span class="lago">${s.lastActivityAgoMin}m ago</span>
      <span class="lusd" title="${esc(tokBit)}">${usdCol}</span>
    </div>`;
  }).join('');
  const measuredMin = t.measuredUsdPerMin != null ? t.measuredUsdPerMin : t.usdPerMin;
  const estMin = t.usdPerMinEstimated != null ? t.usdPerMinEstimated : 0;
  const allMin = t.usdPerMinAll != null ? t.usdPerMinAll : (measuredMin + estMin);
  return `
    <div class="ledger">
      <div class="lhead"><b>~${usd(allMin)}/min</b> burn view · ${usd(measuredMin)} measured + ${usd(estMin)} estimated · ${t.activeSessions || 0} session${t.activeSessions === 1 ? '' : 's'}${engBits ? ' (' + esc(engBits) + ')' : ''} · ${((t.tokensRecent || 0) / 1000).toFixed(0)}k tokens
        <span class="lnote">(Grok $ uses xAI API list rates · SuperGrok sub ≠ API bill · not measured)</span>
      </div>
      ${rows || '<div class="lrow"><span class="lcwd" style="color:var(--text-dim)">No engine sessions with recent activity.</span></div>'}
    </div>`;
}

function renderBurnTrend() {
  if (burnTrend.length < 2) return '';
  const max = Math.max(0.01, ...burnTrend.map((b) => b.usdPerMin));
  return `<div class="spark" title="$/min per sweep, since restart">` + burnTrend.map((b) => {
    const h = Math.max(3, Math.round((b.usdPerMin / max) * 100));
    const c = b.usdPerMin >= max * 0.66 ? 'var(--danger)' : b.usdPerMin >= max * 0.33 ? 'var(--warning)' : 'var(--text-dim)';
    return `<span style="height:${h}%;background:${c}"></span>`;
  }).join('') + `</div>`;
}

function generateDashboard() {
  // W7: cache-first paint — never await full sweep for shell
  const paint = paintRadarFromCache({
    lastKnownPath: LAST_KNOWN_PATH,
    classifierMode: modePublic().classifierMode,
    freezeCapability: modePublic().freezeCapability === true,
    sweepError,
    lastSweepAt,
    lastSweepMs,
    atlasHealth,
    sweepInProgress,
    canaryReceipt: modePublic().canaryReceipt,
    reasonCodes: lastReasonCodes,
  });
  const b = buckets();
  const mp = modePublic();
  const zProc = b.zombie.reduce((n, g) => n + g.count, 0);
  const aProc = b.active.reduce((n, g) => n + g.count, 0);
  const uProc = (b.burnUncertain || []).reduce((n, g) => n + g.count, 0);
  const oProc = typeof b.otherCount === 'number' ? b.otherCount
    : ((b.otherProcesses || []).length || hiddenNonEngine);
  const observe = b.observe || { wouldBeActionableRed: false, wouldBeCount: 0, items: [], reasonCodes: [] };
  const freezeKillEnabled = mp.freezeKillEnabled === true;
  const t = ledger.totals || {};
  const cacheAgeMs = computeCacheAgeMs(lastSweepAt);
  const ageStr = cacheAgeMs == null ? 'no cache' : (cacheAgeMs < 1000 ? '<1s' : Math.round(cacheAgeMs / 1000) + 's ago');
  const modeChip = `mode=${esc(mp.classifierMode)}${mp.modeForced ? ' (forced)' : ''} · freeze=${mp.freezeCapability ? 'MET' : 'off'} · atlas=${esc(atlasHealth)} · receipt=${mp.canaryReceipt && mp.canaryReceipt.valid ? 'valid' : 'none'} · cache=${esc(ageStr)}`;
  const cadence = sweepError
    ? `<span style="color:var(--danger)">sweep error: ${esc(sweepError)} · abstain (Uncertain ≠ red)</span>`
    : `Cache-first · full sweep background · every ${SWEEP_INTERVAL_MS / 1000}s · last look ${fmtTime(lastSweepAt)}${lastSweepMs ? ' (' + (lastSweepMs / 1000).toFixed(1) + 's)' : ''} · ${modeChip} · ${frozenPids.size ? frozenPids.size + ' frozen' : 'nothing paused'}`;
  // Cold shell: paint skeleton immediately; firstSweep no longer blocks full HTML shell
  const firstSweep = sweepInProgress && !lastSweepAt && engines.length === 0;

  // W7: when in-memory engines empty, surface durable last-known tiles (always non-actionable)
  const cacheTiles = (paint.shell && paint.shell.tiles) || [];
  const useCacheTiles = engines.length === 0 && cacheTiles.length > 0;
  const cacheObserveItems = useCacheTiles
    ? cacheTiles.filter((t) => t.kind === 'observe' || t.kind === 'would_be')
    : [];
  const cacheActiveItems = useCacheTiles
    ? cacheTiles.filter((t) => t.kind === 'active')
    : [];

  // Actionable RED tiles only when armed; under shadow / cache zombie list is empty.
  const zombieBody = b.zombie.length
    ? b.zombie.map((g) => tile(g, 'zombie', { freezeKillEnabled })).join('\n')
    : `<div class="allclear">✓ No actionable RED reap tiles (classifierMode=${esc(mp.classifierMode)}). Dual-write dark · Uncertain ≠ red · cache never actionable.</div>`;
  // Observe-only dual-run section (dark ≠ silence). Use observe.items or durable cache.
  const observeItems = (Array.isArray(observe.items) && observe.items.length)
    ? observe.items
    : cacheObserveItems;
  const observeLit = (observe.wouldBeActionableRed || cacheObserveItems.length > 0)
    && !isActionableRedAllowed(mp.classifierMode);
  const observeBody = observeLit
    ? `<div class="note" style="margin-bottom:8px">${esc(observeOnlyBannerCopy(observe.wouldBeActionableRed ? observe : {
        wouldBeActionableRed: true,
        wouldBeCount: cacheObserveItems.reduce((n, t) => n + (t.count || 1), 0),
      }))} · reasons: ${esc((observe.reasonCodes || lastReasonCodes || []).join(', ') || 'CACHED_NON_ACTIONABLE')} · last-known cache</div>`
      + observeItems.map((it) => {
            // Minimal observe row (no freeze/kill, no zombie scare language)
            return `<div class="row observe" id="row-obs-${esc(it.id || it.name)}">
              <div class="rhead" onclick="tog(this)">
                <span class="caret">▶</span>
                <span class="rname"><span class="mono">${esc(it.name)}</span>${it.count > 1 ? ' ×' + it.count : ''}</span>
                <span class="rmeta"><span class="chip age">observe-only · cache</span><span class="chip count">${it.count || 1}</span></span>
              </div>
              <div class="rbody">
                <div class="kv">
                  <span class="k">Status</span><span class="v">would-be dual-run candidate · not actionable under shadow · Uncertain ≠ red</span>
                  <span class="k">Path</span><span class="v">${esc(it.path || '—')}</span>
                  <span class="k">Reasons</span><span class="v">${esc((it.reasonCodes || observe.reasonCodes || lastReasonCodes || []).join(', '))}</span>
                </div>
                <div class="acts"><button class="btn" onclick="why(this)">Why?</button></div>
                <div class="why"><b>Observe-only (from cache).</b> Shadow dual-write keeps this non-actionable. Freeze before Kill. No zombie scare banner. Why min loads without full resweep.</div>
              </div>
            </div>`;
          }).join('\n')
    : '';
  const activeList = b.active.length ? b.active : cacheActiveItems;
  const activeBody = activeList.length
    ? activeList.map((g) => tile(g, 'active', { freezeKillEnabled: false })).join('\n')
    : `<div class="note">No supervised AI runs are actively calling a provider this moment (atlas host match or IP burn activity on an engine process).</div>`;
  const burnUncList = b.burnUncertain || [];
  const burnUncBody = burnUncList.length
    ? burnUncList.map((g) => tile(g, 'active', { freezeKillEnabled: false })).join('\n')
    : '';
  const otherList = b.otherProcesses || otherProcesses || [];
  const otherBody = otherList.length
    ? otherList.slice(0, 24).map((op) => `
      <div class="row other" id="row-oth-${esc(op.pid || op.name)}">
        <div class="rhead" onclick="tog(this)">
          <span class="caret">▶</span>
          <span class="rname"><span class="mono">${esc(op.name)}</span> <span class="chip age">pid ${esc(op.pid)}</span></span>
          <span class="rmeta"><span class="chip">${esc(op.reason || 'other')}</span></span>
        </div>
        <div class="rbody">
          <div class="kv">
            <span class="k">Path</span><span class="v">${esc(op.path || '—')}</span>
            <span class="k">Why listed</span><span class="v">${esc(op.reason || '—')} · freeze/kill disabled</span>
            <span class="k">Cmd</span><span class="v">${esc((op.cmd || '').slice(0, 280))}</span>
          </div>
        </div>
      </div>`).join('\n')
    : `<div class="note">No non-engine keyword matches this sweep.</div>`;

  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zombie Hunter — Token-Spend Sentinel</title>
<style>
  :root{--bg:#0f1117;--surface:#1a1d27;--surface2:#232733;--border:#2e3340;
    --text:#e2e4e9;--text-dim:#8b8f9a;--accent:#6c9cfc;--danger:#f87171;--warning:#fbbf24;--success:#4ade80;color-scheme:dark}
  *{box-sizing:border-box}
  body{font-family:system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--text);margin:0;padding:22px;line-height:1.5;font-size:14px}
  .dash{background:var(--surface);border:1px solid var(--border);border-radius:12px;max-width:980px;margin:0 auto;overflow:hidden}
  .dhead{display:flex;align-items:center;gap:13px;padding:15px 20px;border-bottom:1px solid var(--border);background:var(--surface2)}
  .radar{width:42px;height:42px;border-radius:8px;border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:22px;background:#0c0f15}
  .dhead h1{margin:0;font-size:17px} .dhead .cad{font-size:11px;color:var(--text-dim);margin-top:2px}
  .hbtn{margin-left:auto;font-size:12px;font-weight:600;padding:7px 13px;border-radius:8px;cursor:pointer;border:1px solid var(--accent);background:var(--surface);color:var(--text);white-space:nowrap}
  .hbtn:hover{background:#20242f} .hbtn:disabled{opacity:.6;cursor:default}
  .verdicts{display:flex;gap:10px;padding:14px 20px 0;flex-wrap:wrap}
  .vpill{flex:1;min-width:135px;border:1px solid var(--border);border-radius:10px;padding:10px 13px;background:var(--surface2)}
  .vpill .n{font-size:22px;font-weight:800;line-height:1} .vpill .l{font-size:10.5px;color:var(--text-dim);margin-top:3px;text-transform:uppercase;letter-spacing:.5px}
  .vpill.zombie{border-color:rgba(248,113,113,.5)} .vpill.zombie .n{color:var(--danger)}
  .vpill.burn{border-color:rgba(251,191,36,.45)} .vpill.burn .n{color:var(--warning)}
  .vpill.active{border-color:rgba(74,222,128,.4)} .vpill.active .n{color:var(--success)}
  .vpill.idle .n{color:var(--text-dim)}
  .row.other{border-left:3px solid var(--text-dim);opacity:.95}
  .row.observe{border-left:3px solid var(--accent)}
  .other-inventory{max-height:220px;overflow-y:auto;margin-top:8px;border:1px solid var(--border);border-radius:8px;padding:6px 8px;background:#0c0f15}
  .idle-line .idle-detail{display:none;margin-top:8px}
  .idle-line.open .idle-detail{display:block}
  .term-tile{margin:14px 20px 2px;border:1px solid var(--accent);border-radius:10px;background:var(--surface2);overflow:hidden}
  .term-head{display:flex;align-items:center;gap:10px;padding:10px 13px;cursor:pointer;user-select:none}
  .term-head:hover{background:#20242f} .term-tile.open .caret{transform:rotate(90deg)}
  .term-head .tt{font-weight:600;font-size:13px} .term-head .tsub{font-size:11px;color:var(--text-dim)}
  .engtoggle{margin-left:auto;display:flex;border:1px solid var(--border);border-radius:7px;overflow:hidden}
  .eng{font-size:11px;font-weight:600;padding:4px 12px;border:none;background:var(--surface);color:var(--text-dim);cursor:pointer}
  .eng.on{background:var(--accent);color:#0c0f15}
  .term-body{padding:2px 13px 13px}
  .btn-start{font-size:12px;font-weight:600;padding:7px 16px;border-radius:7px;border:1px solid var(--accent);background:var(--surface);color:var(--text);cursor:pointer}
  .btn-start:hover{background:#20242f} .btn-start:disabled{opacity:.6;cursor:default} .term-body .hint{font-size:11px;color:var(--text-dim);margin-left:10px}
  .body{padding:16px 20px}
  .sect{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--text-dim);font-weight:700;margin:18px 0 9px;display:flex;align-items:center;gap:8px}
  .sect:first-child{margin-top:2px}
  .badge{font-size:10px;padding:2px 7px;border-radius:10px;background:var(--surface2);color:var(--text-dim);text-transform:none;letter-spacing:0}
  .row{background:var(--surface2);border:1px solid var(--border);border-radius:9px;margin-bottom:7px;overflow:hidden}
  .row.zombie{border-left:3px solid var(--danger)} .row.active{border-left:3px solid var(--success)}
  .row.observe{border-left:3px solid var(--accent)}
  .rhead{display:flex;align-items:center;gap:10px;padding:9px 12px;cursor:pointer;user-select:none} .rhead:hover{background:#20242f}
  .caret{color:var(--text-dim);font-size:11px;transition:transform .15s;width:10px} .row.open .caret{transform:rotate(90deg)}
  .rname{font-weight:600;font-size:13px} .rname .mono{font-family:ui-monospace,Consolas,monospace;color:var(--accent);font-weight:500}
  .rmeta{margin-left:auto;display:flex;gap:7px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
  .chip{font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px}
  .chip.live{background:rgba(248,113,113,.18);color:var(--danger)} .chip.recent{background:rgba(251,191,36,.16);color:var(--warning)}
  .chip.count{background:rgba(108,156,252,.16);color:var(--accent)} .chip.age{background:rgba(108,156,252,.1);color:var(--accent)}
  .chip.frozen{background:rgba(251,191,36,.18);color:var(--warning)}
  .rbody{display:none;padding:0 12px 12px 32px;font-size:12.5px;color:var(--text-dim)} .row.open .rbody{display:block}
  .kv{display:grid;grid-template-columns:110px 1fr;gap:2px 10px;margin:8px 0}
  .kv .k{color:var(--text-dim)} .kv .v{color:var(--text);font-family:ui-monospace,Consolas,monospace;font-size:11.5px;word-break:break-all}
  .plist{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--text-dim);background:#0c0f15;border:1px solid var(--border);border-radius:7px;padding:8px 10px;margin:6px 0;word-break:break-all}
  .acts{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
  .btn{font-size:11px;padding:4px 11px;border-radius:6px;cursor:pointer;border:1px solid var(--border);background:var(--surface);color:var(--text)}
  .btn.reap{border-color:rgba(248,113,113,.5);color:var(--danger)} .btn.freeze{border-color:rgba(251,191,36,.45);color:var(--warning)} .btn:hover{border-color:var(--accent)}
  .why{display:none;margin-top:9px;font-size:12px;color:var(--text-dim);background:#0c0f15;border:1px solid var(--border);border-radius:7px;padding:9px 11px;border-left:3px solid var(--accent)}
  .why.open{display:block} .why .cmd{margin-top:8px;font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--accent);word-break:break-all}
  .allclear{border:1px dashed rgba(74,222,128,.35);border-radius:10px;padding:13px 15px;color:var(--success);font-size:12.5px;background:rgba(74,222,128,.05)}
  .note{font-size:11.5px;color:var(--text-dim)}
  .ledger{border:1px solid var(--border);border-radius:10px;background:var(--surface2);padding:12px 14px;margin-top:4px}
  .leng{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--accent);min-width:52px}
  .lhead{font-size:13px;margin-bottom:8px} .lhead b{color:var(--warning);font-size:15px} .lnote{color:var(--text-dim);font-size:10.5px;margin-left:6px}
  .lrow{display:flex;gap:12px;align-items:baseline;font-size:12px;padding:4px 0;border-top:1px solid var(--border)}
  .lrate{color:var(--warning);font-weight:700;width:78px;font-family:ui-monospace,Consolas,monospace}
  .lmodel{color:var(--accent);width:120px;font-size:11px} .lcwd{flex:1;font-family:ui-monospace,Consolas,monospace;font-size:11px;word-break:break-all}
  .lago{color:var(--text-dim);width:64px;text-align:right;font-size:11px} .lusd{color:var(--text);width:56px;text-align:right;font-family:ui-monospace,Consolas,monospace}
  .spark{display:flex;align-items:flex-end;gap:2px;height:34px;margin:8px 0 0}
  .spark span{flex:1;border-radius:2px 2px 0 0;min-height:3px}
  .idle-line{margin-top:16px;font-size:12px;color:var(--text-dim);border:1px dashed var(--border);border-radius:8px;padding:9px 12px;cursor:pointer}
  .idle-line:hover{border-color:var(--accent)} .idle-detail{display:none;margin-top:8px;font-size:11.5px;color:var(--text-dim)} .idle-line.open .idle-detail{display:block}
  .foot{max-width:980px;margin:12px auto 0;color:var(--text-dim);font-size:11px;text-align:center}
  .toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px 16px;font-size:13px;opacity:0;transition:.2s;pointer-events:none} .toast.show{opacity:1}
</style></head>
<body>
<div class="dash">
  <div class="dhead">
    <img class="radar" src="/vendor/brand/zombie-hunter-radar.jpg" alt="ZH" onerror="this.outerHTML='<div class=radar>🔥</div>'">
    <div><h1>Zombie Hunter — Token-Spend Sentinel</h1><div class="cad">${cadence}</div></div>
    <button class="hbtn" id="scanbtn" onclick="scanAgain(this)">↻ Run scan again</button>
  </div>
  <div class="verdicts">
    <div class="vpill zombie"><div class="n">${zProc}</div><div class="l">Actionable RED (armed only)</div></div>
    <div class="vpill burn"><div class="n">${usd(t.usdPerMinAll != null ? t.usdPerMinAll : ((t.usdPerMin || 0) + (t.usdPerMinEstimated || 0)))}</div><div class="l">Burn view $/min</div></div>
    <div class="vpill"><div class="n">${usd(t.usdPerMinEstimated || 0)}</div><div class="l">Grok est $/min</div></div>
    <div class="vpill"><div class="n">${t.activeSessions || 0}</div><div class="l">Ledger sessions</div></div>
    <div class="vpill active"><div class="n">${useCacheTiles ? (paint.shell.counts.active || 0) : aProc}</div><div class="l">Active burn · supervised</div></div>
    <div class="vpill idle"><div class="n">${uProc}</div><div class="l">Burn · uncertain / observe</div></div>
    <div class="vpill idle"><div class="n">${oProc}</div><div class="l">Other processes (no kill)</div></div>
  </div>
  <div class="note" style="padding:8px 20px 0;font-size:11.5px;color:var(--text-dim)">Classifier <b style="color:var(--accent)">${esc(mp.classifierMode)}</b>${mp.modeForced ? ' <span style="color:var(--warning)">(forced — no valid canaryReceipt)</span>' : ''} · dual-write dark · Uncertain ≠ red · Freeze before Kill · ownership badge · Freeze/Kill ${freezeKillEnabled ? 'enabled' : 'disabled'} · paint ${esc(paint.paintPath)}${paint.withinBudget ? ' ≤1s' : ''}</div>
  <div class="term-tile" id="termTile">
    <div class="term-head" onclick="toggleTerm()">
      <span class="caret">▶</span><span class="tt">🔎 Investigate with an agent</span>
      <span class="tsub">shell-first · slim seed · Claude / Gemini(agy) / Grok · async start</span>
      <span class="engtoggle" onclick="event.stopPropagation()">
        <button id="engC" class="eng on" onclick="setEng('claude',event)" title="Claude subscription CLI">Claude</button>
        <button id="engG" class="eng" onclick="setEng('gemini',event)" title="Gemini via agy">Gemini</button>
        <button id="engK" class="eng" onclick="setEng('grok',event)" title="Grok via grok.exe -p">Grok</button>
      </span>
    </div>
    <div class="term-body" id="termBody" style="display:none">
      <div class="note" id="termShellNote" style="margin:0 0 8px;font-size:11px">Shell ready (≤1s). Pick engine · slim seed (pid/class/reasons/freeze) · session starts async on demand — no multi-minute blank wait. Unhealthy engines disable with health.</div>
      <div id="termStart"><button class="btn-start" onclick="startTerm(this)">Start terminal (slim seed)</button><button class="btn" style="margin-left:8px" onclick="startTermDeep(this)">Deep brief</button><span class="hint" id="termHint"></span></div>
      <iframe id="termFrame" style="display:none;width:100%;height:460px;border:none;border-radius:8px;margin-top:2px"></iframe>
    </div>
  </div>
  <div class="body">
    ${firstSweep ? `<div class="allclear" style="color:var(--accent);border-color:rgba(108,156,252,.4)">◌ Shell painted from ${paint.paintPath === 'warm' ? 'last-known cache' : 'skeleton'} (≤1s). Full sweep runs in background (~10-20s). Uncertain ≠ red. This page refreshes automatically.</div>` : ''}
    <div class="sect">Actionable RED reap tiles — armed mode only</div>
    ${zombieBody}
    ${observeLit ? `
    <div class="sect">Observe-only dual-run (shadow — not actionable)</div>
    ${observeBody}
    ` : ''}
    <div class="sect">💸 Burn ledger — multi-engine (Claude measured $ · Grok/Gemini/OpenAI activity when present)</div>
    ${renderLedger()}
    ${renderBurnTrend()}
    <div class="sect">✓ Active burn · supervised — live sessions spending tokens (not zombies · no kill)</div>
    ${activeBody}
    ${burnUncList.length ? `
    <div class="sect">◐ Burn activity · uncertain supervision (informational · freeze/kill off)</div>
    ${burnUncBody}
    ` : ''}
    <div class="sect">Other processes on this computer (summary · no freeze/kill)</div>
    <div class="idle-line" onclick="this.classList.toggle('open')">
      📋 <b>${oProc}</b> inventory rows · idle engines + keyword matches · click to expand (not a reap list)
      <div class="idle-detail">
        <div class="other-inventory">${otherBody}</div>
        <div class="note" style="margin-top:8px">These are NOT reap targets. Sample names: ${esc((hiddenSample || []).slice(0, 12).join(', ')) || '—'}.</div>
      </div>
    </div>
  </div>
</div>
<div class="foot">Dual-write dark · classifierMode=${esc(mp.classifierMode)} · Uncertain ≠ red · Freeze before Kill · Active = supervised burn (atlas or IP activity) · RED needs atlas host match · Burn ledger = multi-engine · measured $ only where trail exists · GUI auto-refresh ~${UI_REFRESH_MS / 1000}s when tab visible.</div>
<div class="toast" id="toast"></div>
<script>
  // Local direct: http://127.0.0.1:PORT. When opened via Anchor reverse-proxy
  // (Tailscale/remote), Anchor rewrites API to /api/rnd/zombie_hunter_proxy and
  // injects ANCHOR_TOKEN so same-origin auth works without hitting the client's localhost.
  const API = 'http://127.0.0.1:${PORT}';
  var ANCHOR_TOKEN='__ANCHOR_TOKEN__';
  var ZH_ENG='claude', ZH_SID=null, ZH_ENG_HEALTH={claude:true,gemini:true,grok:true};
  function proxied(){return ANCHOR_TOKEN!==('__ANCHOR'+'_TOKEN__');}
  function hdr(){var h={'Content-Type':'application/json'};if(ANCHOR_TOKEN&&proxied())h['X-Anchor-Token']=ANCHOR_TOKEN;return h;}
  function withTok(o){if(ANCHOR_TOKEN&&proxied())o.token=ANCHOR_TOKEN;return o;}
  function apiUrl(p){
    var u=API+p;
    if(ANCHOR_TOKEN&&proxied()){
      u+=(u.indexOf('?')>=0?'&':'?')+'token='+encodeURIComponent(ANCHOR_TOKEN);
    }
    return u;
  }
  function tog(h){h.parentElement.classList.toggle('open');}
  function why(b){var w=b.parentElement.parentElement.querySelector('.why');if(w)w.classList.toggle('open');event.stopPropagation();}
  function paintEngButtons(){['claude','gemini','grok'].forEach(function(e){var id=e==='claude'?'engC':(e==='gemini'?'engG':'engK');var el=document.getElementById(id);if(!el)return;el.classList.toggle('on',ZH_ENG===e);var ok=ZH_ENG_HEALTH[e]!==false;el.disabled=!ok;el.title=ok?(e+' ready'):(e+' unavailable');el.style.opacity=ok?'1':'0.45';});}
  function toggleTerm(){var t=document.getElementById('termTile');t.classList.toggle('open');var open=t.classList.contains('open');document.getElementById('termBody').style.display=open?'block':'none';if(open){fetch(apiUrl('/api/engines')).then(function(r){return r.json();}).then(function(j){if(j&&j.engines){j.engines.forEach(function(row){ZH_ENG_HEALTH[row.id]=!!row.enabled;});if(j.defaultEngine)ZH_ENG=j.defaultEngine;paintEngButtons();}}).catch(function(){});if(!proxied()){document.getElementById('termHint').textContent='Open the Zombie Hunter button from the Anchor dashboard to use the live terminal.';var b=document.querySelector('.btn-start');if(b)b.disabled=true;}}}
  function setEng(e,ev){if(ev)ev.stopPropagation();if(ZH_ENG_HEALTH[e]===false){toast(e+' disabled (unhealthy)');return;}ZH_ENG=e;paintEngButtons();if(ZH_SID){toast('Switching to '+e+'…');fetch('/api/rnd/term_set_engine',{method:'POST',headers:hdr(),body:JSON.stringify(withTok({session:ZH_SID,engine:e}))}).then(function(){var f=document.getElementById('termFrame');f.src=f.src;}).catch(function(){});}}
  function _startInvestigate(btn, deep){if(!proxied())return;if(ZH_ENG_HEALTH[ZH_ENG]===false){toast(ZH_ENG+' disabled');return;}btn.disabled=true;var prev=btn.textContent;btn.textContent='Starting…';fetch('/api/rnd/zombie_terminal_start',{method:'POST',headers:hdr(),body:JSON.stringify(withTok({backend:ZH_ENG,slim:true,deepBrief:!!deep}))}).then(function(r){return r.json();}).then(function(d){if(d&&d.ok&&d.session_id){ZH_SID=d.session_id;var tq=(ANCHOR_TOKEN&&proxied())?('&token='+encodeURIComponent(ANCHOR_TOKEN)):'';var f=document.getElementById('termFrame');f.src='/zombie_terminal?session='+encodeURIComponent(d.session_id)+tq;document.getElementById('termStart').style.display='none';f.style.display='block';}else{btn.disabled=false;btn.textContent=prev;toast('Failed (non-blocking): '+((d&&d.error)||'unknown'));}}).catch(function(e){btn.disabled=false;btn.textContent=prev;toast('Error (non-blocking): '+e.message);});}
  function startTerm(btn){_startInvestigate(btn,false);}
  function startTermDeep(btn){_startInvestigate(btn,true);}
  function toast(m){var t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(function(){t.classList.remove('show')},2600);}
  async function post(p,b){const r=await fetch(apiUrl(p),{method:'POST',headers:hdr(),body:JSON.stringify(b)});return r.json();}
  async function doFreeze(id,pids){toast('Freezing '+pids.length+'… (NtSuspend · sole boundary)');try{const j=await post('/api/freeze',{pids});var sp=j.spendPostcondition&&j.spendPostcondition.class?(' · spend '+j.spendPostcondition.class):'';toast(j.ok?('Frozen '+j.frozen+sp):(j.reason||j.error||'Freeze failed'));setTimeout(reload,700);}catch(e){toast('Freeze error');}event.stopPropagation();}
  async function doKill(id,pids,name){if(!confirm('KILL '+pids.length+' process(es) of "'+name+'"?\\nTree-kills immediately, cannot be undone.\\nServer re-validates confirm + identity.'))return;var t=document.getElementById('row-'+id);if(t)t.style.opacity='.4';try{const tok=await post('/api/kill-confirm',{pids});if(!tok||!tok.ok||!tok.confirmToken){toast((tok&&(tok.reason||tok.error))||'Kill confirm refused');if(t)t.style.opacity='1';return;}const j=await post('/api/kill',{pids,confirm:true,confirmToken:tok.confirmToken,alreadyFrozen:false});toast(j.ok?('Killed '+j.killed+(j.rowRemoved?' · row removed':'')):(j.reason||j.error||'Kill failed'));if(!j.ok&&t)t.style.opacity='1';setTimeout(reload,700);}catch(e){toast('Kill error');if(t)t.style.opacity='1';}event.stopPropagation();}
  async function scanAgain(btn){btn.disabled=true;btn.textContent='↻ Scanning…';try{await post('/api/sweep',{});}catch(e){}var n=0;var iv=setInterval(async function(){n++;try{const s=await(await fetch(apiUrl('/api/state'))).json();if(!s.sweepInProgress){clearInterval(iv);reload();}}catch(e){}if(n>30){clearInterval(iv);reload();}},1500);}
  function reload(){location.reload();}
  ${firstSweep ? 'setTimeout(reload,4000);' : ''}
  // Auto-refresh while hunting (~UI_REFRESH_MS). Pause when tab hidden; wait out in-flight sweeps.
  (function(){
    var UI_REFRESH_MS=${UI_REFRESH_MS};
    var inflight=false;
    async function tick(){
      if(document.hidden||inflight)return;
      inflight=true;
      try{
        var s=await(await fetch(apiUrl('/api/state'),{cache:'no-store'})).json();
        if(s&&s.sweepInProgress){
          var n=0;
          var wait=setInterval(async function(){
            n++;
            try{
              var s2=await(await fetch(apiUrl('/api/state'),{cache:'no-store'})).json();
              if(!s2.sweepInProgress||n>40){clearInterval(wait);reload();}
            }catch(e){if(n>40){clearInterval(wait);inflight=false;}}
          },1500);
          return;
        }
        reload();
      }catch(e){inflight=false;}
    }
    setInterval(tick,UI_REFRESH_MS);
    document.addEventListener('visibilitychange',function(){
      if(!document.hidden)setTimeout(tick,1200);
    });
  })();
</script>
</body></html>`;
}

// ── HTTP ──
function sendJson(res, obj, code = 200) {
  res.writeHead(code, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' });
  res.end(JSON.stringify(obj));
}
function readBody(req) {
  return new Promise((resolve) => { let d = ''; req.on('data', (c) => { d += c; });
    req.on('end', () => { try { resolve(JSON.parse(d || '{}')); } catch (_) { resolve({}); } }); });
}
const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') { sendJson(res, {}, 204); return; }
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  if (req.method === 'GET' && url.pathname === '/') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(generateDashboard()); return;
  }
  if (req.method === 'GET' && url.pathname === '/api/state') {
    const b = buckets();
    const mp = modePublic();
    const catalogs = getCatalogsPublicPayload();
    const cacheAgeMs = computeCacheAgeMs(lastSweepAt);
    const radarFields = buildRadarServerFields({
      sweepError,
      lastSweepAt,
      lastSweepMs,
      cacheAgeMs,
      freezeCapability: mp.freezeCapability === true,
      atlasHealth,
      reasonCodes: (b.observe && b.observe.reasonCodes) || lastReasonCodes,
      classifierMode: mp.classifierMode,
      canaryReceipt: mp.canaryReceipt,
      sweepInProgress,
      fromCache: true,
      paintPath: lastSweepAt ? 'warm' : 'cold',
    });
    // Dual-write: actionable zombies empty under shadow → dashboard banner stays dark
    // (Anchor handle_zombie_spenders sums st.zombies). Observe + dualWrite for all surfaces.
    sendJson(res, {
      zombies: b.zombie,
      active: b.active,
      idleCount: b.idleCount,
      hiddenNonEngine,
      observe: b.observe,
      dualWrite: b.dualWrite,
      classifierMode: mp.classifierMode,
      modeForced: mp.modeForced,
      modeReason: mp.modeReason,
      canaryReceipt: mp.canaryReceipt,
      freezeCapability: mp.freezeCapability,
      freezeKillEnabled: mp.freezeKillEnabled,
      actionableRedAllowed: mp.actionableRedAllowed,
      // W7 / SC4 server fields
      sweepError: radarFields.sweepError,
      cacheAge: radarFields.cacheAge,
      cacheAgeMs: radarFields.cacheAgeMs,
      atlasHealth: radarFields.atlasHealth,
      reasonCodes: radarFields.reasonCodes,
      canaryReceiptStatus: radarFields.canaryReceiptStatus,
      paintPath: radarFields.paintPath,
      paintBudgetMs: PAINT_BUDGET_MS,
      // Explicit reaper-health / dashboard scare fields (dual-write matrix)
      // W9/SC7: scare banners stay dual-write dark under shadow; clickable health
      // banners seed Doctor 1:1 (not a markdown path) via /api/doctor/banner-seed.
      dashboardZombieBanner: {
        actionableRed: !!(b.dualWrite && b.dualWrite.surfaces && b.dualWrite.surfaces.dashboard_zombie_banner && b.dualWrite.surfaces.dashboard_zombie_banner.actionableRed),
        count: b.zombie.reduce((n, g) => n + (g.count || 0), 0),
        observeOnly: !mp.actionableRedAllowed,
        clickableToDoctor: false, // zombie scare → Zombie Hunter radar, not Doctor
      },
      reaperHealthScare: {
        actionableRed: !!(b.dualWrite && b.dualWrite.surfaces && b.dualWrite.surfaces.reaper_health_scare && b.dualWrite.surfaces.reaper_health_scare.actionableRed),
        observeOnly: !mp.actionableRedAllowed,
        reasonCodes: (b.observe && b.observe.reasonCodes) || [],
        // W9: reaper-health banner opens Doctor with closed issue seed (not markdown)
        clickableToDoctor: true,
        bannerDoctorVersion: BANNER_DOCTOR_SEED_VERSION,
      },
      // W3: versioned closed reason + Doctor issue catalogs in server payloads
      reasonCatalogVersion: REASON_CATALOG_VERSION,
      doctorIssueCatalogVersion: DOCTOR_ISSUE_CATALOG_VERSION,
      reasonCatalog: catalogs,
      ownershipStub: ownershipStubContract(),
      ownershipStubVersion: OWNERSHIP_STUB_VERSION,
      sc1Claimed: !!mp.sc1Claimed,
      freezeKillForbidden: !mp.freezeKillEnabled,
      freezeMethod: FREEZE_METHOD,
      soleFreezeKillBoundary: soleFreezeKillServiceBoundary(),
      spendPostconditionClasses: Object.values(SPEND_POSTCONDITION),
      recommendedNextEnum: RECOMMENDED_NEXT.slice(),
      // W10 / P7: abstain-rate + unsupervised-spend TP health fields
      healthMetrics: lastHealthMetrics
        || getHealthMetricsPublicPayload(engines, {
          classifierMode: mp.classifierMode,
          atlasHealth: radarFields.atlasHealth,
          sweepError: radarFields.sweepError,
        }),
      abstainRate: (lastHealthMetrics && lastHealthMetrics.abstainRate) != null
        ? lastHealthMetrics.abstainRate
        : computeClassifierHealthMetrics(engines).abstainRate,
      unsupervisedSpendTruePositiveCount: (lastHealthMetrics
        && lastHealthMetrics.unsupervisedSpendTruePositiveCount) != null
        ? lastHealthMetrics.unsupervisedSpendTruePositiveCount
        : computeClassifierHealthMetrics(engines).unsupervisedSpendTruePositiveCount,
      ledger, incidents, lastSweepAt, lastSweepMs, sweepInProgress, frozen: [...frozenPids],
    });
    return;
  }
  // W8 / SC5+SC6: engine toggle health + shared session-start plumbing
  if (req.method === 'GET' && url.pathname === '/api/engines') {
    const envProfile = {
      claude: process.env.ZH_ENGINE_CLAUDE !== '0',
      gemini: process.env.ZH_ENGINE_GEMINI !== '0',
      grok: process.env.ZH_ENGINE_GROK !== '0',
    };
    // Default assume available unless explicitly disabled (Anchor probes real CLIs).
    const toggle = listEngineToggle(envProfile, {
      prefs: {
        default_cli: process.env.ZH_DEFAULT_CLI || process.env.ANCHOR_DEFAULT_CLI,
        coding_family: process.env.ZH_CODING_FAMILY || process.env.CODING_FAMILY,
        review_family: process.env.ZH_REVIEW_FAMILY || process.env.REVIEW_FAMILY,
      },
      lastUsed: process.env.ZH_LAST_ENGINE,
    });
    const p5 = assertP5StartPlumbingGreen();
    sendJson(res, {
      ok: true,
      ...toggle,
      transports: ENGINE_TRANSPORT,
      engineIds: ENGINE_IDS.slice(),
      shellPaintBudgetMs: SHELL_PAINT_BUDGET_MS,
      firstPromptBudgetMs: FIRST_PROMPT_BUDGET_MS,
      p5Plumbing: p5.plumbing,
      p5Green: p5.ok,
      doctorShell: doctorShellBeforeSessionContract(toggle),
    });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/session-start/plan') {
    const mp = modePublic();
    const surface = url.searchParams.get('surface') || 'investigate';
    const engine = url.searchParams.get('engine');
    const pid = url.searchParams.get('pid');
    const deepBrief = url.searchParams.get('deepBrief') === '1';
    const profile = {
      claude: process.env.ZH_ENGINE_CLAUDE !== '0',
      gemini: process.env.ZH_ENGINE_GEMINI !== '0',
      grok: process.env.ZH_ENGINE_GROK !== '0',
    };
    let candidate = findCachedCandidate({ pid, id: url.searchParams.get('id') }) || {
      pid: pid ? Number(pid) : null,
      reasonCodes: lastReasonCodes,
    };
    const plan = buildSessionStartPlan({
      surface,
      engine,
      candidate,
      deepBrief,
      profile,
      classifierMode: mp.classifierMode,
      freezeCapability: mp.freezeCapability === true,
      freezeKillEnabled: mp.freezeKillEnabled,
      prefs: {
        default_cli: process.env.ZH_DEFAULT_CLI || process.env.ANCHOR_DEFAULT_CLI,
        coding_family: process.env.ZH_CODING_FAMILY || process.env.CODING_FAMILY,
        review_family: process.env.ZH_REVIEW_FAMILY || process.env.REVIEW_FAMILY,
      },
    });
    sendJson(res, { ok: true, plan });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/investigate/slim-seed') {
    const mp = modePublic();
    const pid = url.searchParams.get('pid');
    const candidate = findCachedCandidate({ pid, id: url.searchParams.get('id') }) || {
      pid: pid ? Number(pid) : null,
      reasonCodes: lastReasonCodes,
      engineClass: url.searchParams.get('class') || 'unknown',
    };
    const slim = buildInvestigateSlimSeed(candidate, {
      classifierMode: mp.classifierMode,
      freezeCapability: mp.freezeCapability === true,
      freezeKillEnabled: mp.freezeKillEnabled,
    });
    sendJson(res, {
      ok: true,
      slim,
      seedText: formatInvestigateSlimSeedText(slim),
      firstPromptBudgetMs: FIRST_PROMPT_BUDGET_MS,
    });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/investigate/deep-brief') {
    const mp = modePublic();
    const pid = url.searchParams.get('pid');
    const candidate = findCachedCandidate({ pid, id: url.searchParams.get('id') }) || {
      pid: pid ? Number(pid) : null,
      reasonCodes: lastReasonCodes,
      wouldBeActionableRed: false,
    };
    const deep = buildInvestigateDeepBrief(candidate, {
      classifierMode: mp.classifierMode,
      freezeCapability: mp.freezeCapability === true,
      freezeKillEnabled: mp.freezeKillEnabled,
      lastSweepAt,
      sweepError,
      cacheAgeMs: computeCacheAgeMs(lastSweepAt),
    });
    sendJson(res, { ok: true, deep, treatEnum: RECOMMENDED_NEXT.slice() });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/doctor/shell') {
    const toggle = listEngineToggle({
      claude: process.env.ZH_ENGINE_CLAUDE !== '0',
      gemini: process.env.ZH_ENGINE_GEMINI !== '0',
      grok: process.env.ZH_ENGINE_GROK !== '0',
    });
    sendJson(res, {
      ok: true,
      ...doctorShellBeforeSessionContract(toggle),
      p5Green: assertP5StartPlumbingGreen().ok,
    });
    return;
  }
  // W9 / SC7: health + reaper-health banner → Doctor 1:1 seed + async diagnose attempt
  if (req.method === 'GET' && url.pathname === '/api/doctor/banner-seed') {
    const mp = modePublic();
    const surface = (url.searchParams.get('surface') || 'dashboard_health').toLowerCase();
    let issue;
    if (surface === 'reaper_health' || surface === 'reaper') {
      issue = buildReaperHealthBannerIssue({
        kind: url.searchParams.get('kind') || 'abstain-streak',
        message: url.searchParams.get('message') || undefined,
        lastError: url.searchParams.get('lastError') || undefined,
        streak: url.searchParams.get('streak'),
        threshold: url.searchParams.get('threshold'),
        issueId: url.searchParams.get('issueId') || undefined,
      });
    } else if (url.searchParams.get('issueId') || url.searchParams.get('message')) {
      issue = extractBannerSeedFields({
        issueId: url.searchParams.get('issueId'),
        message: url.searchParams.get('message'),
        component: url.searchParams.get('component'),
        lastError: url.searchParams.get('lastError'),
        suggestedChecks: (url.searchParams.get('suggestedChecks') || '')
          .split('|').filter(Boolean),
        bannerSurface: surface,
      });
      // Re-normalize through catalog when only issueId given
      if (surface === 'dashboard_health' || surface === 'health') {
        issue = buildDashboardHealthBannerIssue({
          ...issue,
          reportDate: url.searchParams.get('reportDate') || '',
          status: url.searchParams.get('status') || issue.lastError || 'ISSUES FOUND',
        });
      } else {
        issue = normalizeBannerIssue({ ...issue, bannerSurface: surface });
      }
    } else {
      issue = buildDashboardHealthBannerIssue({
        reportDate: url.searchParams.get('reportDate') || '',
        status: url.searchParams.get('status') || 'ISSUES FOUND',
        lastError: url.searchParams.get('lastError') || undefined,
      });
    }
    const profile = {
      claude: process.env.ZH_ENGINE_CLAUDE !== '0',
      gemini: process.env.ZH_ENGINE_GEMINI !== '0',
      grok: process.env.ZH_ENGINE_GROK !== '0',
    };
    const engine = url.searchParams.get('engine');
    const autoDiagnose = url.searchParams.get('diagnose') !== '0';
    const plan = buildBannerDiagnosePlan(issue, {
      profile,
      engine,
      classifierMode: mp.classifierMode,
      autoDiagnose,
      prefs: {
        default_cli: process.env.ZH_DEFAULT_CLI || process.env.ANCHOR_DEFAULT_CLI,
        coding_family: process.env.ZH_CODING_FAMILY || process.env.CODING_FAMILY,
        review_family: process.env.ZH_REVIEW_FAMILY || process.env.REVIEW_FAMILY,
      },
    });
    const click = buildClickableBannerContract(issue, { autoDiagnose });
    const attempt = autoDiagnose
      ? attemptAsyncBannerDiagnoseStart(issue, {
        profile,
        engine,
        classifierMode: mp.classifierMode,
        forceFail: url.searchParams.get('forceFail') === '1',
      })
      : null;
    const failSafe = assertBannerDoctorFailSafeWithDualWrite({
      classifierMode: mp.classifierMode,
      issue,
      profile,
    });
    sendJson(res, {
      ok: true,
      surface,
      issue: extractBannerSeedFields(issue),
      seed: plan.seed,
      seedText: plan.seedText,
      oneToOne: plan.bannerOneToOne,
      navigation: plan.navigation,
      clickable: click,
      diagnosePlan: plan,
      asyncDiagnoseAttempt: attempt,
      failSafe,
      bannerDoctorVersion: BANNER_DOCTOR_SEED_VERSION,
      p5Green: assertP5StartPlumbingGreen().ok,
      // Explicit contract markers for SC7
      notMarkdownPath: true,
      markdownPath: null,
    });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/doctor/banner-diagnose') {
    const mp = modePublic();
    const body = await readBody(req);
    const profile = {
      claude: process.env.ZH_ENGINE_CLAUDE !== '0',
      gemini: process.env.ZH_ENGINE_GEMINI !== '0',
      grok: process.env.ZH_ENGINE_GROK !== '0',
    };
    let issue = body.issue || null;
    if (!issue && body.surface === 'reaper_health') {
      issue = buildReaperHealthBannerIssue(body);
    } else if (!issue) {
      issue = buildDashboardHealthBannerIssue(body);
    }
    const result = attemptAsyncBannerDiagnoseStart(issue, {
      profile,
      engine: body.engine || body.backend,
      classifierMode: mp.classifierMode || body.classifierMode,
      forceFail: body.forceFail === true,
      failReason: body.failReason,
      prefs: {
        default_cli: process.env.ZH_DEFAULT_CLI || process.env.ANCHOR_DEFAULT_CLI,
        coding_family: process.env.ZH_CODING_FAMILY || process.env.CODING_FAMILY,
        review_family: process.env.ZH_REVIEW_FAMILY || process.env.REVIEW_FAMILY,
      },
    });
    sendJson(res, {
      ok: result.ok,
      ...result,
      navigation: buildDoctorNavigationFromBanner(issue, { autoDiagnose: true }),
      bannerDoctorVersion: BANNER_DOCTOR_SEED_VERSION,
      notMarkdownPath: true,
    }, result.ok ? 200 : 200); // failure is non-blocking — always 200 with ok:false
    return;
  }
  // W7: Why min payload from cache (no full resweep)
  if (req.method === 'GET' && url.pathname === '/api/why') {
    const mp = modePublic();
    const pid = url.searchParams.get('pid');
    const id = url.searchParams.get('id');
    const candidate = findCachedCandidate({ pid, id }) || {
      reasonCodes: lastReasonCodes,
      quadVerdict: sweepError ? 'ABSTAIN' : 'UNKNOWN',
      wouldBeActionableRed: false,
    };
    const why = buildWhyMinPayload(candidate, {
      classifierMode: mp.classifierMode,
      freezeCapability: mp.freezeCapability === true,
      lastSweepAt,
      sweepError,
      cacheAgeMs: computeCacheAgeMs(lastSweepAt),
    });
    sendJson(res, { ok: true, why, treatEnum: RECOMMENDED_NEXT.slice() });
    return;
  }
  // W7: pure cache paint probe (for tests / health)
  if (req.method === 'GET' && url.pathname === '/api/radar-paint') {
    const mp = modePublic();
    const paint = paintRadarFromCache({
      lastKnownPath: LAST_KNOWN_PATH,
      classifierMode: mp.classifierMode,
      freezeCapability: mp.freezeCapability === true,
      sweepError,
      lastSweepAt,
      lastSweepMs,
      atlasHealth,
      canaryReceipt: mp.canaryReceipt,
      reasonCodes: lastReasonCodes,
      sweepInProgress,
    });
    sendJson(res, { ok: true, ...paint });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/mode') {
    sendJson(res, {
      ok: true,
      ...modePublic(),
      resolved: currentMode(),
      reasonCatalogVersion: REASON_CATALOG_VERSION,
      doctorIssueCatalogVersion: DOCTOR_ISSUE_CATALOG_VERSION,
      reasonCatalog: getCatalogsPublicPayload(),
      ownershipStub: ownershipStubContract(),
    });
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/catalogs') {
    // W3 seed endpoint: closed classifier reason codes + Doctor issue IDs
    sendJson(res, {
      ok: true,
      ...getCatalogsPublicPayload(),
      ownershipStub: ownershipStubContract(),
    });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/sweep') { runSweep(); sendJson(res, { ok: true, sweepInProgress }); return; }
  if (req.method === 'GET' && url.pathname === '/api/freeze-capability') {
    const cap = currentFreezeCapability();
    sendJson(res, { ok: true, ...cap, boundary: SOLE_BOUNDARY_ID });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/kill-confirm') {
    // Server-issued one-shot confirm token (GUI must present after browser confirm).
    const mp = modePublic();
    if (!mp.freezeKillEnabled || !isFreezeKillAllowed(mp.classifierMode, mp.freezeCapability)) {
      sendJson(res, {
        ok: false,
        error: 'KILL_DISABLED',
        reason: mp.actionableRedAllowed ? 'freeze_capability_false' : 'shadow_mode_kill_disabled',
        classifierMode: mp.classifierMode,
      }, 403);
      return;
    }
    const body = await readBody(req);
    const targets = resolveTargets(body);
    const issued = issueKillConfirmToken({ pids: targets.map((t) => t.pid) });
    sendJson(res, {
      ok: true,
      confirmToken: issued.confirmToken,
      expiresAt: issued.expiresAt,
      pids: issued.pids,
      serverValidated: true,
      boundary: SOLE_BOUNDARY_ID,
    });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/freeze') {
    // W6 sole boundary: identity re-probe + NtSuspendProcess (never SoftFreeze).
    const mp = modePublic();
    const body = await readBody(req);
    if (!mp.freezeKillEnabled || !isFreezeKillAllowed(mp.classifierMode, mp.freezeCapability)) {
      sendJson(res, {
        ok: false,
        frozen: 0,
        error: 'FREEZE_UNAVAILABLE',
        reason: mp.actionableRedAllowed ? 'freeze_capability_false' : 'shadow_mode_freeze_disabled',
        classifierMode: mp.classifierMode,
        freezeCapability: mp.freezeCapability,
        boundary: SOLE_BOUNDARY_ID,
        method: FREEZE_METHOD,
      }, 403);
      return;
    }
    const targets = resolveTargets(body);
    const results = [];
    let n = 0;
    let lastSpend = null;
    for (const t of targets) {
      // W7: never freeze from cache-only identity
      const gate = identityActionGate(t);
      if (!gate.allow) {
        results.push({
          ok: false,
          frozen: false,
          error: gate.reason,
          reason: gate.reason,
          cacheOnly: true,
          method: FREEZE_METHOD,
          boundary: SOLE_BOUNDARY_ID,
        });
        continue;
      }
      const r = freezeCandidate(t, {
        mode: mp.classifierMode,
        freezeCapability: mp.freezeCapability === true,
      });
      results.push(r);
      if (r.ok && r.frozen) {
        n += 1;
        frozenPids.add(String(t.pid));
        lastSpend = r.spendPostcondition;
      }
    }
    sendJson(res, {
      ok: n > 0 && results.every((r) => r.ok),
      frozen: n,
      results,
      spendPostcondition: lastSpend,
      method: FREEZE_METHOD,
      boundary: SOLE_BOUNDARY_ID,
      honest: true,
    });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/unfreeze') {
    const mp = modePublic();
    if (!mp.freezeKillEnabled) {
      sendJson(res, {
        ok: false,
        error: 'FREEZE_UNAVAILABLE',
        reason: 'shadow_mode_freeze_disabled',
        boundary: SOLE_BOUNDARY_ID,
      }, 403);
      return;
    }
    const body = await readBody(req);
    const targets = resolveTargets(body);
    const results = [];
    for (const t of targets) {
      const r = unfreezeCandidate(t);
      results.push(r);
      if (r.ok) frozenPids.delete(String(t.pid));
    }
    sendJson(res, { ok: results.every((r) => r.ok), results, boundary: SOLE_BOUNDARY_ID });
    return;
  }
  if (req.method === 'POST' && url.pathname === '/api/kill') {
    // W6 sole boundary: authz + server-validated confirm + tree-kill + death verify.
    // No inline taskkill — GUI must call this boundary only.
    const mp = modePublic();
    const body = await readBody(req);
    if (!mp.freezeKillEnabled || !isFreezeKillAllowed(mp.classifierMode, mp.freezeCapability)) {
      sendJson(res, {
        ok: false,
        killed: 0,
        rowRemoved: 0,
        error: 'KILL_DISABLED',
        reason: mp.actionableRedAllowed ? 'freeze_capability_false' : 'shadow_mode_kill_disabled',
        classifierMode: mp.classifierMode,
        boundary: SOLE_BOUNDARY_ID,
      }, 403);
      return;
    }
    const targets = resolveTargets(body);
    const alreadyFrozen = body.alreadyFrozen === true
      || (targets.length > 0 && targets.every((t) => frozenPids.has(String(t.pid))));
    const results = [];
    let killed = 0;
    let rowRemoved = 0;
    // Validate confirm once for the batch, then mark confirmValidated for each target.
    const confirmPids = targets.map((t) => t.pid);
    const confirm = validateKillConfirm({
      confirm: body.confirm,
      confirmToken: body.confirmToken,
      pids: confirmPids,
    });
    if (!confirm.ok) {
      sendJson(res, {
        ok: false,
        killed: 0,
        rowRemoved: 0,
        error: confirm.reason,
        reason: confirm.reason,
        boundary: SOLE_BOUNDARY_ID,
      }, 403);
      return;
    }
    for (const t of targets) {
      // W7: never kill from cache-only identity
      const gate = identityActionGate(t);
      if (!gate.allow) {
        results.push({
          ok: false,
          killed: false,
          rowRemoved: false,
          error: gate.reason,
          reason: gate.reason,
          cacheOnly: true,
          boundary: SOLE_BOUNDARY_ID,
        });
        continue;
      }
      const r = killCandidate(t, {
        mode: mp.classifierMode,
        freezeCapability: mp.freezeCapability === true,
        alreadyFrozen,
        confirmValidated: true,
      });
      results.push(r);
      if (r.ok && r.killed) {
        killed += 1;
        frozenPids.delete(String(t.pid));
      }
      if (r.rowRemoved) rowRemoved += 1;
    }
    sendJson(res, {
      ok: targets.length > 0 && results.every((r) => r.ok),
      killed,
      rowRemoved,
      results,
      boundary: SOLE_BOUNDARY_ID,
      honest: true,
    });
    return;
  }
  sendJson(res, { ok: false, error: 'not found' }, 404);
});

// Export pure helpers for unit tests without starting the listener when required as a library.
// When run as main (node server.js / sweep path), listen as before.
const isMain = require.main === module
  || (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename));

if (isMain) {
  server.listen(PORT, '127.0.0.1', () => {
    const m = currentMode();
    console.log(`Token-Spend Sentinel running on http://127.0.0.1:${PORT} · classifierMode=${m.mode}${m.forced ? ' (forced)' : ''}`);
    // Warm freezeCapability off the request path so first dashboard paint is instant.
    _scheduleFreezeProbe();
    runSweep();
    const iv = setInterval(runSweep, SWEEP_INTERVAL_MS);
    if (iv.unref) iv.unref();
  });
}

module.exports = {
  buckets,
  currentMode,
  modePublic,
  currentFreezeCapability,
  resolveTargets,
  findCachedCandidate,
  server,
  runSweep,
  applyDualWriteToBuckets,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  getCatalogsPublicPayload,
  ownershipStubContract,
  soleFreezeKillServiceBoundary,
  FREEZE_METHOD,
  SOLE_BOUNDARY_ID,
  // W7 / SC4 exports for unit tests
  paintRadarFromCache,
  buildWhyMinPayload,
  buildRadarServerFields,
  suppressActionableCachedRed,
  identityActionGate,
  recommendNext,
  computeCacheAgeMs,
  writeDurableLastKnown,
  loadDurableLastKnown,
  buildLastKnownSnapshot,
  parseSweepJson,
  PAINT_BUDGET_MS,
  RECOMMENDED_NEXT,
  LAST_KNOWN_PATH,
  UI_REFRESH_MS,
  SWEEP_INTERVAL_MS,
  // W10 / P7 ownership UI + health
  tile,
  shouldShowFreezeKill,
  ownershipBadgeUiContract,
  resolveOwnershipBadge,
  computeClassifierHealthMetrics,
  getHealthMetricsPublicPayload,
};


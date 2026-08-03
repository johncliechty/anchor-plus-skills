// Token-spend-first classifier.
//
// The threat that matters is a process SPENDING PAID AI TOKENS with nobody
// steering it. So the primary signal is spend (network connections to a paid
// provider + the token-log ledger), and supervision is the guard that keeps us
// from reaping your own live session.
//
// Per AI-engine process we emit the raw signals; the SERVER applies recency
// (connections are transient) and buckets them:
//   zombie  = spending (now or recently) AND unsupervised   -> reap target
//   active  = spending AND supervised (your live session)   -> informational
//   idle    = an AI engine not spending                     -> hidden
// Non-engine keyword matches (tail -f on a log, shells) are NOT a threat and
// are only counted, never shown.
//
// Supervised = ancestry hits an *active* interactive host session (active VS Code /
// Anchor / terminal/shell/Grok/…), not a stale host image. Inactive shells
// (session 0 / job-orphaned) do not KEEP spenders (John 2026-07-23).
//
// W2 (C1+C3, G1): normative host-walk (D=32, set R, UNCERTAIN stop rules) and
// closed E1/E2 engine legs. Uncertain never becomes unsupervised. No SC1 claim.
// W3 (P1): ownership KEEP stub + reason catalog + four-leg quad skeleton.
// W4 (G2+G3): spend atlas fail-closed + joint quad gate under dual-run shadow.
// W5 (G4–G6): SC1 canary pack + residual attestation + version-matched receipt;
// sc1Claimed when receipt carries sc1CanaryGreen. Freeze/Kill still forbidden.
// Zombie ⇔ engine ∧ paid-spend ∧ unsupervised ∧ not Anchor-owned; any
// uncertain leg ⇒ abstain.

const cp = require('node:child_process');
const { ProcessDiscovery } = require('./discovery.js');
const {
  collectSpend,
  evaluateSpendLeg,
  spendLegForPid,
  SPEND_ATLAS_VERSION,
  SPEND_ATLAS_HASH,
  SPEND_ATLAS_POSITIVE,
  matchSpendAtlasHost,
  positiveAtlasHosts,
} = require('./spend.js');
const { resolveClassifierMode, isActionableRedAllowed, currentHashes } = require('./mode.js');
const { buildObserveDualRun, evaluateDualWriteSurfaces } = require('./dual-write.js');
const { sanitizeControlChars } = require('./json-safe.js');
const {
  walkHostSupervision,
  indexProcessesByPid,
  matchHostAllowlist,
  HOST_WALK_MAX_DEPTH,
  HOST_ALLOWLIST_VERSION,
  HOST_ALLOWLIST_H,
  SYSTEM_ROOT_SET_R,
  toWalkNode,
} = require('./host-walk.js');
const {
  evaluateEngineLeg,
  hasEngineKeywordHint,
  ENGINE_ATLAS_VERSION,
  ENGINE_ALLOWLIST_E1,
  SUPPORT_ALLOWLIST_E2,
  SUPPORT_HOP_CAP_K,
} = require('./engine-leg.js');
const { normalizeImageBasename, matchNormalizedExact } = require('./normalize.js');
const {
  productionOwnershipLeg,
  lookupOwnership,
  ownershipStubContract,
  OWNERSHIP_IPC_STUB,
  OWNERSHIP_IPC_FAIL_CLOSED,
  OWNERSHIP_REGISTERED_KEEP,
  OWNERSHIP_NOT_REGISTERED,
  OWNERSHIP_STUB_MAX_WAVE,
  OWNERSHIP_STUB_VERSION,
} = require('./ownership.js');
const {
  evaluateQuad,
  failSafeMatrixEntry,
} = require('./quad.js');
const {
  getCatalogsPublicPayload,
  REASON_CATALOG_VERSION,
  DOCTOR_ISSUE_CATALOG_VERSION,
  CLASSIFIER_REASON_CODES,
  filterKnownReasonCodes,
} = require('./reason-catalog.js');
const {
  computeClassifierHealthMetrics,
} = require('./health-metrics.js');

function sanitizeId(s) { return String(s).replace(/[^a-zA-Z0-9-]/g, '-'); }

function enumerateAll() {
  // Include CreateTimeMs for host-walk createTime inversion checks (C1).
  const script = "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,SessionId,ExecutablePath,CommandLine,@{n='AgeMin';e={if($_.CreationDate){[int]((Get-Date)-$_.CreationDate).TotalMinutes}else{-1}}},@{n='CreateTimeMs';e={if($_.CreationDate){[int64]($_.CreationDate.ToUniversalTime()-[datetime]'1970-01-01').TotalMilliseconds}else{$null}}} | ConvertTo-Json -Compress -Depth 3";
  const out = cp.execSync(`powershell -NoProfile -Command "${script}"`, {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
    stdio: 'pipe',
  });
  let arr = JSON.parse(out || '[]');
  if (!Array.isArray(arr)) arr = [arr];
  return arr;
}

/**
 * Production host-walk entry — same path unit tests exercise with fixtures.
 * @param {object} candidate — {pid,ppid,imagePath,createTime} or Win32 row
 * @param {Map|object} byPid
 */
function productionHostWalk(candidate, byPid) {
  return walkHostSupervision(candidate, byPid, { maxDepth: HOST_WALK_MAX_DEPTH });
}

/**
 * Production engine-leg entry.
 * @param {object} proc
 * @param {Map|object} byPid
 */
function productionEngineLeg(proc, byPid) {
  return evaluateEngineLeg(proc, byPid);
}

/**
 * Production ownership leg (W3 stub — fail-closed on error/timeout).
 * @param {object} proc
 * @param {object} [opts]
 */
function productionOwnership(proc, opts) {
  return productionOwnershipLeg(proc, opts || {});
}

/**
 * Production joint-quad skeleton (engine ∧ spend ∧ unsupervised ∧ not-owned).
 * @param {object} legs — { engine, spend, supervision, ownership }
 */
function productionQuad(legs) {
  return evaluateQuad(legs);
}

/**
 * Production spend leg (W4) — process-owned atlas match only; never port-443 alone.
 * @param {object} input — evaluateSpendLeg options (pid, connections, forceStale, …)
 */
function productionSpendLeg(input) {
  return evaluateSpendLeg(input || {});
}

/**
 * Collect descendant PIDs (bounded) for subtree spend attribution.
 * @param {number} pid
 * @param {Map} childrenOf
 * @param {number} [cap]
 */
function collectSubtreePids(pid, childrenOf, cap = 500) {
  const out = [];
  const seen = new Set();
  const stack = [Number(pid)];
  while (stack.length) {
    const cur = stack.pop();
    if (seen.has(cur)) continue;
    seen.add(cur);
    if (cur !== Number(pid)) out.push(cur);
    for (const ch of (childrenOf.get(cur) || [])) stack.push(ch);
    if (seen.size > cap) break;
  }
  return out;
}

/**
 * Classify a single candidate from fixture-shaped inputs (joint gate / OL1 TP).
 * Same production walk + engine + spend + ownership + quad path as classifyAll.
 *
 * @param {object} candidate — { pid, ppid, imagePath, createTime, commandLine?, name? }
 * @param {Array|Map} processTree — nodes for walk index
 * @param {object} [opts]
 * @param {object} [opts.spend] — evaluateSpendLeg input (connections, forceStale, …)
 * @param {object} [opts.ownership] — ownership inject
 * @param {string} [opts.classifierMode]
 */
function classifyCandidate(candidate, processTree, opts = {}) {
  const nodes = Array.isArray(processTree)
    ? processTree
    : (processTree instanceof Map ? [...processTree.values()] : []);
  const walkIndex = indexProcessesByPid(nodes);
  const childrenOf = new Map();
  for (const n of nodes) {
    const pid = Number(n.pid != null ? n.pid : n.ProcessId);
    const pp = Number(n.ppid != null ? n.ppid : n.ParentProcessId);
    if (!childrenOf.has(pp)) childrenOf.set(pp, []);
    childrenOf.get(pp).push(pid);
  }

  const walkNode = {
    pid: Number(candidate.pid != null ? candidate.pid : candidate.ProcessId),
    ppid: Number(candidate.ppid != null ? candidate.ppid : candidate.ParentProcessId),
    imagePath: candidate.imagePath || candidate.ExecutablePath || candidate.name || candidate.Name || '',
    name: candidate.name || candidate.Name || '',
    createTime: candidate.createTime != null ? Number(candidate.createTime) : (
      candidate.CreateTimeMs != null ? Number(candidate.CreateTimeMs) : null
    ),
    commandLine: candidate.commandLine || candidate.CommandLine || '',
  };

  const eng = productionEngineLeg(walkNode, walkIndex);
  const sup = productionHostWalk(walkNode, walkIndex);
  const subtree = collectSubtreePids(walkNode.pid, childrenOf);
  const spendInput = {
    pid: walkNode.pid,
    subtreePids: subtree,
    ...(opts.spend || {}),
  };
  const sp = productionSpendLeg(spendInput);
  const own = productionOwnership({
    pid: walkNode.pid,
    createTime: walkNode.createTime,
    imagePath: walkNode.imagePath,
  }, opts.ownership || {});

  const quad = productionQuad({
    engine: eng,
    spend: sp,
    supervision: sup,
    ownership: own,
  });

  const modeResolved = resolveClassifierMode({
    requestedMode: opts.classifierMode || 'shadow',
    receipt: opts.receipt != null ? opts.receipt : null,
  });
  const scareOk = isActionableRedAllowed(modeResolved.mode);
  const wouldBeActionableRed = !!quad.wouldBeActionableRed;

  const row = {
    pid: String(walkNode.pid),
    name: walkNode.name || String(walkNode.imagePath).split(/[/\\]/).pop(),
    path: walkNode.imagePath || '(path unavailable)',
    isEngine: eng.isE1,
    isE2Support: eng.isE2Support,
    engineClass: eng.engineClass,
    engineReason: eng.reason,
    supervisionStatus: sup.status,
    supervisionReason: sup.reason,
    supervised: sup.supervised,
    unsupervised: sup.unsupervised,
    parentAlive: sup.parentAlive,
    parentName: sup.parentName,
    root: sup.root,
    hostId: sup.hostId,
    hostFixtureId: sup.fixtureId,
    spendingNow: !!sp.spendingNow,
    spendPositive: !!sp.spendPositive,
    burnActivity: !!(sp.burnActivity || sp.spendPositive || sp.spendingNow),
    activityProviders: (sp.activityProviders || sp.providers || []).slice(),
    activityReason: sp.activityReason || null,
    spendStatus: sp.status,
    spendReason: sp.reason,
    spendHosts: (sp.hosts || []).slice(),
    providers: (sp.providers || []).slice(),
    conns: sp.conns || 0,
    atlasStale: !!sp.atlasStale,
    ownership: {
      owned: !!own.owned,
      keep: !!own.keep,
      failClosed: !!own.failClosed,
      status: own.status,
      reason: own.reason,
      reasonCodes: (own.reasonCodes || []).slice(),
      stub: true,
      stubVersion: own.stubVersion,
      stubMaxWave: own.stubMaxWave,
    },
    ownershipBadge: own.badge || null,
    quadVerdict: quad.verdict,
    quad: {
      verdict: quad.verdict,
      jointPositive: quad.jointPositive,
      wouldBeActionableRed: quad.wouldBeActionableRed,
      abstain: quad.abstain,
      keep: quad.keep,
      reasonCodes: (quad.reasonCodes || []).slice(),
      uncertainLegs: (quad.uncertainLegs || []).slice(),
      legs: quad.legs,
    },
    reasonCodes: filterKnownReasonCodes(quad.reasonCodes || []),
    wouldBeActionableRed,
    actionable: scareOk && wouldBeActionableRed,
    classifierMode: modeResolved.mode,
  };

  const observe = buildObserveDualRun({
    legacyWouldBeZombies: wouldBeActionableRed
      ? [{
        id: row.pid,
        name: row.name,
        path: row.path,
        count: 1,
        providers: row.providers,
        root: row.root,
        supervised: row.supervised,
      }]
      : [],
    newWouldBeZombies: wouldBeActionableRed
      ? [{ id: row.pid, name: row.name, count: 1, providers: row.providers }]
      : [],
    extraReasonCodes: row.reasonCodes,
  });
  const dualWrite = evaluateDualWriteSurfaces({
    classifierMode: modeResolved.mode,
    observe,
  });

  return {
    ok: true,
    row,
    engine: eng,
    spend: sp,
    supervision: sup,
    ownership: own,
    quad,
    observe,
    dualWrite,
    classifierMode: modeResolved.mode,
    actionableRedAllowed: scareOk,
    wouldBeActionableRed,
    // dual-run shadow fields (G3)
    dualRunShadow: {
      wouldBeActionableRed,
      observeOnly: !scareOk,
      actionableRed: scareOk && wouldBeActionableRed,
      reasonCodes: row.reasonCodes.slice(),
      spendAtlasVersion: SPEND_ATLAS_VERSION,
      spendAtlasHash: SPEND_ATLAS_HASH,
      hashes: currentHashes(),
    },
  };
}

function classifyAll(opts = {}) {
  // opts.ownership — inject registry / forceError for tests; production omits.
  // opts.spend — inject connections / forceStale / attribution for tests.
  const t0 = Date.now();
  const all = enumerateAll();
  const byId = new Map();
  const childrenOf = new Map();
  // Index for host-walk / engine-leg (normalized walk fields)
  const walkIndex = indexProcessesByPid(all.map((p) => ({
    pid: Number(p.ProcessId),
    ppid: Number(p.ParentProcessId),
    imagePath: p.ExecutablePath || p.Name || '',
    name: p.Name || '',
    createTime: p.CreateTimeMs != null ? Number(p.CreateTimeMs) : null,
    commandLine: p.CommandLine || '',
    ProcessId: p.ProcessId,
    ParentProcessId: p.ParentProcessId,
    Name: p.Name,
    ExecutablePath: p.ExecutablePath,
    CommandLine: p.CommandLine,
    SessionId: p.SessionId,
    AgeMin: p.AgeMin,
  })));

  for (const p of all) {
    byId.set(Number(p.ProcessId), p);
    const pp = Number(p.ParentProcessId);
    if (!childrenOf.has(pp)) childrenOf.set(pp, []);
    childrenOf.get(pp).push(Number(p.ProcessId));
  }

  const spend = collectSpend(10, t0, opts.spend || {});
  const net = spend.net || {};

  const disc = new ProcessDiscovery();
  const sigCache = new Map();
  const isSigned = (path) => {
    if (!path) return false;
    if (!sigCache.has(path)) sigCache.set(path, disc.checkMicrosoftSignature(path));
    return sigCache.get(path);
  };

  // W4 spend leg for a process = evaluateSpendLeg on own + descendant ownership set.
  // Live net only contains atlas-matched hosts; inject opts.spend for fixtures.
  const spendFor = (pid) => {
    const subtree = collectSubtreePids(pid, childrenOf);
    if (opts.spend && (opts.spend.connections || opts.spend.forceStale
      || opts.spend.attributionUnreadable || opts.spend.atlasEntries)) {
      return spendLegForPid(pid, spend, subtree, opts.spend);
    }
    return spendLegForPid(pid, spend, subtree, {});
  };

  const engines = [];
  let hiddenNonEngine = 0;
  const hiddenSample = [];
  /** Non-reap inventory: keyword matches + idle engines (no freeze/kill). */
  const otherProcesses = [];

  const pushOther = (p, reason) => {
    hiddenNonEngine += 1;
    if (hiddenSample.length < 24) hiddenSample.push(p.Name);
    if (otherProcesses.length < 80) {
      otherProcesses.push({
        pid: String(p.ProcessId),
        name: sanitizeControlChars(p.Name || ''),
        path: sanitizeControlChars(p.ExecutablePath || ''),
        cmd: sanitizeControlChars(String(p.CommandLine || '').slice(0, 240)),
        ageMin: typeof p.AgeMin === 'number' ? p.AgeMin : -1,
        reason,
        freezeKill: false,
      });
    }
  };

  for (const p of all) {
    const pid = Number(p.ProcessId);
    const walkNode = {
      pid,
      ppid: Number(p.ParentProcessId),
      imagePath: p.ExecutablePath || p.Name || '',
      name: p.Name || '',
      createTime: p.CreateTimeMs != null ? Number(p.CreateTimeMs) : null,
      commandLine: p.CommandLine || '',
    };

    // Closed E1/E2 engine leg — cmdline/keyword alone never engine-positive.
    const eng = productionEngineLeg(walkNode, walkIndex);
    if (!eng.isEnginePositive) {
      // Idle / keyword-only — inventory only, never freeze/kill.
      if (hasEngineKeywordHint(p.CommandLine, p.Name) || disc.isSuspicious(p.CommandLine, p.Name)) {
        pushOther(p, 'keyword-match-not-engine');
      }
      continue;
    }

    // Signed system images still skipped for support noise (legacy behavior).
    if (isSigned(p.ExecutablePath) && eng.isE2Support) {
      pushOther(p, 'signed-support-noise');
      continue;
    }

    // Normative host-walk (C1) — ancestry-only SUPERVISED/UNSUPERVISED/UNCERTAIN.
    const sup = productionHostWalk(walkNode, walkIndex);
    const sp = spendFor(pid);

    // W3 ownership KEEP stub (fail-closed on IPC error/timeout).
    const own = productionOwnership({
      pid,
      createTime: walkNode.createTime,
      imagePath: walkNode.imagePath,
    }, opts.ownership || {});

    // Four-leg joint quad: engine ∧ paid-spend ∧ unsupervised ∧ not owned.
    // Any UNCERTAIN leg ⇒ ABSTAIN; owned/fail-closed ⇒ KEEP.
    const quad = productionQuad({
      engine: eng,
      spend: sp,
      supervision: sup,
      ownership: own,
    });

    const wouldBeActionableRed = !!quad.wouldBeActionableRed;

    engines.push({
      pid: String(pid),
      name: sanitizeControlChars(p.Name),
      path: sanitizeControlChars(p.ExecutablePath || '(path unavailable)'),
      // W7: identity triple fields for freeze re-probe (never act on pid alone)
      createTime: walkNode.createTime != null ? walkNode.createTime : (
        p.CreateTimeMs != null ? Number(p.CreateTimeMs) : null
      ),
      imagePath: sanitizeControlChars(p.ExecutablePath || walkNode.imagePath || ''),
      sessionId: p.SessionId,
      ageMin: typeof p.AgeMin === 'number' ? p.AgeMin : -1,
      cmd: sanitizeControlChars(p.CommandLine || ''),
      isEngine: eng.isE1,
      isE2Support: eng.isE2Support,
      engineClass: eng.engineClass,
      engineReason: eng.reason,
      // Three-state supervision (W2); boolean supervised kept for legacy buckets.
      supervisionStatus: sup.status,
      supervisionReason: sup.reason,
      supervised: sup.supervised,
      unsupervised: sup.unsupervised,
      parentAlive: sup.parentAlive,
      parentName: sup.parentName,
      root: sup.root,
      hostId: sup.hostId,
      hostFixtureId: sup.fixtureId,
      spendingNow: !!sp.spendingNow,
      spendPositive: !!sp.spendPositive,
      // Informational burn (IP activity or atlas) — never alone for RED/quad positive
      burnActivity: !!(sp.burnActivity || sp.spendPositive || sp.spendingNow),
      activityProviders: (sp.activityProviders || sp.providers || []).slice(),
      activityReason: sp.activityReason || null,
      spendStatus: sp.status,
      spendReason: sp.reason,
      spendHosts: (sp.hosts || []).slice(),
      providers: (sp.providers || []).slice(),
      conns: sp.conns || 0,
      atlasStale: !!sp.atlasStale,
      // W3 ownership badge + quad
      ownership: {
        owned: !!own.owned,
        keep: !!own.keep,
        failClosed: !!own.failClosed,
        status: own.status,
        reason: own.reason,
        reasonCodes: (own.reasonCodes || []).slice(),
        stub: true,
        stubVersion: own.stubVersion,
        stubMaxWave: own.stubMaxWave,
      },
      ownershipBadge: own.badge || null,
      quadVerdict: quad.verdict,
      quad: {
        verdict: quad.verdict,
        jointPositive: quad.jointPositive,
        wouldBeActionableRed: quad.wouldBeActionableRed,
        abstain: quad.abstain,
        keep: quad.keep,
        reasonCodes: (quad.reasonCodes || []).slice(),
        uncertainLegs: (quad.uncertainLegs || []).slice(),
      },
      reasonCodes: filterKnownReasonCodes(quad.reasonCodes || []),
      wouldBeActionableRed,
      actionable: false, // filled below from mode; default fail-SAFE
    });
  }

  // Idle engines (not burning) also land in otherProcesses for inventory.
  for (const e of engines) {
    if (e.burnActivity || e.spendingNow || e.spendPositive) continue;
    if (otherProcesses.length >= 80) break;
    otherProcesses.push({
      pid: e.pid,
      name: e.name,
      path: e.path,
      cmd: (e.cmd || '').slice(0, 240),
      ageMin: e.ageMin,
      reason: 'idle-engine-not-spending',
      freezeKill: false,
      supervisionStatus: e.supervisionStatus,
    });
  }

  // Flat list for telemetry history (keeps the historical incident view alive).
  const flaggedForLog = engines.map((e) => ({
    processId: e.pid, name: e.name, executablePath: e.path, commandLine: e.cmd,
  }));

  // G0: force shadow unless a version-matched canaryReceipt allows armed.
  const modeResolved = resolveClassifierMode();
  const scareOk = isActionableRedAllowed(modeResolved.mode);
  for (const e of engines) {
    e.actionable = scareOk && e.wouldBeActionableRed;
  }

  const wouldBeList = engines
    .filter((e) => e.wouldBeActionableRed)
    .map((e) => ({
      id: e.pid,
      name: e.name,
      path: e.path,
      count: 1,
      providers: e.providers,
      root: e.root,
      supervised: e.supervised,
      supervisionStatus: e.supervisionStatus,
      ownership: e.ownership,
      ownershipBadge: e.ownershipBadge,
      quadVerdict: e.quadVerdict,
      reasonCodes: e.reasonCodes,
      pids: [e.pid],
    }));

  // Aggregate observe reason codes from joint-positive rows + mode.
  const extraObserveCodes = [];
  for (const e of engines) {
    if (e.wouldBeActionableRed) {
      for (const c of e.reasonCodes || []) {
        if (!extraObserveCodes.includes(c)) extraObserveCodes.push(c);
      }
    }
  }
  const observe = buildObserveDualRun({
    legacyWouldBeZombies: wouldBeList,
    newWouldBeZombies: wouldBeList,
    extraReasonCodes: extraObserveCodes,
  });
  const dualWrite = evaluateDualWriteSurfaces({
    classifierMode: modeResolved.mode,
    observe,
  });

  // Fail-SAFE matrix samples (uncertain / owned / joint) for residual dual-write asserts.
  const failSafeSamples = engines.slice(0, 32).map((e) => failSafeMatrixEntry(
    e.quad || {
      verdict: e.quadVerdict,
      jointPositive: !!e.wouldBeActionableRed,
      wouldBeActionableRed: !!e.wouldBeActionableRed,
      reasonCodes: e.reasonCodes || [],
      uncertainLegs: (e.quad && e.quad.uncertainLegs) || [],
    },
    modeResolved.mode,
    scareOk,
  ));

  const catalogs = getCatalogsPublicPayload();

  return {
    ok: true,
    tookMs: Date.now() - t0,
    engines,
    hiddenNonEngine,
    hiddenSample,
    otherProcesses,
    ledger: { sessions: spend.sessions, totals: spend.totals, windowMin: spend.windowMin },
    flaggedForLog,
    // G0 dual-write / shadow force fields (production path, not test-only)
    classifierMode: modeResolved.mode,
    modeForced: modeResolved.forced,
    modeReason: modeResolved.reason,
    canaryReceiptValid: modeResolved.receiptValid,
    observe,
    dualWrite,
    actionableRedAllowed: scareOk,
    // dual-run shadow fields (W4 / G3)
    dualRunShadow: {
      wouldBeActionableRed: observe.wouldBeActionableRed,
      wouldBeCount: observe.wouldBeCount,
      observeOnly: !scareOk,
      actionableRed: scareOk && observe.wouldBeActionableRed,
      reasonCodes: (observe.reasonCodes || []).slice(),
      spendAtlasVersion: SPEND_ATLAS_VERSION,
      spendAtlasHash: SPEND_ATLAS_HASH,
      hashes: currentHashes(),
    },
    // W2 geometry metadata (hashes / versions; no SC1 claim)
    hostAllowlistVersion: HOST_ALLOWLIST_VERSION,
    engineAtlasVersion: ENGINE_ATLAS_VERSION,
    hostWalkMaxDepth: HOST_WALK_MAX_DEPTH,
    // W4 spend atlas
    spendAtlasVersion: SPEND_ATLAS_VERSION,
    spendAtlasHash: SPEND_ATLAS_HASH,
    atlasHealth: (spend.atlas && spend.atlas.health) || (spend.atlas && spend.atlas.stale ? 'STALE' : 'OK'),
    spendAtlas: spend.atlas || null,
    // W3 ownership + reason catalog + quad skeleton
    ownershipStub: ownershipStubContract(),
    reasonCatalogVersion: REASON_CATALOG_VERSION,
    doctorIssueCatalogVersion: DOCTOR_ISSUE_CATALOG_VERSION,
    reasonCatalog: catalogs,
    failSafeSamples,
    // W5/W6: SC1 claimed only with version-matched SC1 canary receipt.
    // Freeze/Kill require separate freezeCapability on the sole boundary (default off here).
    sc1Claimed: !!modeResolved.sc1Claimed,
    freezeKillForbidden: true,
    // W10 / P7: abstain-rate + unsupervised-spend true-positive health fields
    healthMetrics: computeClassifierHealthMetrics(engines),
  };
}

module.exports = {
  classifyAll,
  classifyCandidate,
  // Production seams used by W2/W3/W4 unit packs (same path as classifyAll)
  productionHostWalk,
  productionEngineLeg,
  productionOwnership,
  productionQuad,
  productionSpendLeg,
  evaluateSpendLeg,
  walkHostSupervision,
  evaluateEngineLeg,
  evaluateQuad,
  lookupOwnership,
  matchHostAllowlist,
  matchSpendAtlasHost,
  normalizeImageBasename,
  matchNormalizedExact,
  indexProcessesByPid,
  toWalkNode,
  ownershipStubContract,
  getCatalogsPublicPayload,
  collectSubtreePids,
  HOST_WALK_MAX_DEPTH,
  HOST_ALLOWLIST_VERSION,
  HOST_ALLOWLIST_H,
  SYSTEM_ROOT_SET_R,
  ENGINE_ATLAS_VERSION,
  ENGINE_ALLOWLIST_E1,
  SUPPORT_ALLOWLIST_E2,
  SUPPORT_HOP_CAP_K,
  SPEND_ATLAS_VERSION,
  SPEND_ATLAS_HASH,
  SPEND_ATLAS_POSITIVE,
  positiveAtlasHosts,
  hasEngineKeywordHint,
  OWNERSHIP_IPC_STUB,
  OWNERSHIP_IPC_FAIL_CLOSED,
  OWNERSHIP_REGISTERED_KEEP,
  OWNERSHIP_NOT_REGISTERED,
  OWNERSHIP_STUB_MAX_WAVE,
  OWNERSHIP_STUB_VERSION,
  REASON_CATALOG_VERSION,
  DOCTOR_ISSUE_CATALOG_VERSION,
  CLASSIFIER_REASON_CODES,
  computeClassifierHealthMetrics,
};

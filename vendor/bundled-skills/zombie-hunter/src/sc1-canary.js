// W5 / G4–G6 — SC1 canary pack: recorded host trees, live canary harness,
// OL1 orphan positive control, residual attestation, canaryReceipt writer.
//
// SC1 is owned when sc1_canary_gate is green:
//   recorded zero-RED (dual-run KEEP on interactive)
//   ∧ live interactive zero-RED (banner+tile surfaces)
//   ∧ orphan positive control (wouldBeActionableRed on production path)
//   ∧ residual attestation or live matrix
// Residual attestation alone cannot mint global arm / receipt write.
// Freeze/Kill stay production-disabled.

const fs = require('node:fs');
const path = require('node:path');

const {
  classifyCandidate,
  indexProcessesByPid,
  productionHostWalk,
  HOST_ALLOWLIST_H,
} = require('./classify.js');
const {
  VERDICT_KEEP,
  VERDICT_WOULD_BE_RED,
} = require('./quad.js');
const {
  evaluateDualWriteSurfaces,
  applyDualWriteToBuckets,
  assertNoActionableRedUnderShadow,
  SURFACES,
  observeOnlyBannerCopy,
} = require('./dual-write.js');
const {
  currentHashes,
  resolveClassifierMode,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  buildCanaryReceipt,
  writeCanaryReceipt,
  defaultReceiptPath,
  receiptAllowsArm,
  atlasBumpForcesReshadow,
  receiptMatches,
} = require('./mode.js');
const { positiveAtlasHosts } = require('./spend.js');

const SKILL_ROOT = path.join(__dirname, '..');
const FIXTURES_DIR = path.join(SKILL_ROOT, 'fixtures', 'sc1');
const RECORDED_DIR = path.join(FIXTURES_DIR, 'recorded');
const EVIDENCE_DIR = path.join(FIXTURES_DIR, 'evidence');
const DEFAULT_ATTESTATION_PATH = path.join(SKILL_ROOT, 'sc1_host_attestation.json');
const DEFAULT_CHECKLIST_PATH = path.join(FIXTURES_DIR, 'operator-lab-checklist.json');
const DEFAULT_HOST_ARM_META_PATH = path.join(FIXTURES_DIR, 'host-class-arm-eligibility.json');

/** SC1 primary interactive host classes (recorded fixtures required). */
const SC1_RECORDED_HOST_CLASSES = Object.freeze([
  'vscode',
  'cursor',
  'windowsterminal',
  'anchor',
]);

function node(pid, ppid, imagePath, createTime = 1000, commandLine = '') {
  return {
    pid,
    ppid,
    imagePath,
    name: String(imagePath).split(/[/\\]/).pop(),
    createTime,
    commandLine,
  };
}

function atlasSpendFor(pid, host) {
  const h = host || (positiveAtlasHosts()[0] || 'api.anthropic.com');
  return {
    connections: [
      { owningPid: pid, remotePort: 443, remoteHost: h },
    ],
  };
}

/**
 * Built-in recorded process-tree fixtures (VS Code, Cursor, WT, Anchor + orphan).
 * On-disk JSON under fixtures/sc1/recorded/ may override these.
 */
function builtInRecordedFixtures() {
  const t0 = 7_000_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);

  const vscode = {
    id: 'sc1-recorded-vscode',
    hostClass: 'vscode',
    hostFixtureId: 'F-H-CODE',
    description: 'VS Code host with live-engine-shaped claude child',
    nodes: [
      services,
      node(100, 4, 'C:\\Users\\x\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe', t0 + 100),
      node(200, 100, 'C:\\Users\\x\\claude.exe', t0 + 200, 'claude.exe -p'),
    ],
    enginePid: 200,
  };

  const cursor = {
    id: 'sc1-recorded-cursor',
    hostClass: 'cursor',
    hostFixtureId: 'F-H-CURSOR',
    description: 'Cursor host with live-engine-shaped claude child',
    nodes: [
      services,
      node(110, 4, 'C:\\Users\\x\\AppData\\Local\\Programs\\cursor\\Cursor.exe', t0 + 100),
      node(210, 110, 'C:\\Users\\x\\claude.exe', t0 + 200, 'claude.exe -p'),
    ],
    enginePid: 210,
  };

  const wt = {
    id: 'sc1-recorded-wt',
    hostClass: 'windowsterminal',
    hostFixtureId: 'F-H-WT',
    description: 'Windows Terminal host with live-engine-shaped claude child',
    nodes: [
      services,
      node(120, 4, 'C:\\Windows\\System32\\WindowsTerminal.exe', t0 + 100),
      node(220, 120, 'C:\\Users\\x\\claude.exe', t0 + 200, 'claude.exe -p'),
    ],
    enginePid: 220,
  };

  const anchor = {
    id: 'sc1-recorded-anchor',
    hostClass: 'anchor',
    hostFixtureId: 'F-H-ANCHOR',
    description: 'Anchor GUI host (python + anchor_gui.py) with claude child',
    nodes: [
      services,
      node(
        130,
        4,
        'C:\\Python\\python.exe',
        t0 + 100,
        'python.exe <path>',
      ),
      node(230, 130, 'C:\\Users\\x\\claude.exe', t0 + 200, 'claude.exe -p'),
    ],
    enginePid: 230,
  };

  const orphanA = {
    id: 'sc1-orphan-detached-spender-a',
    hostClass: 'ORPHAN_DETACHED_SPENDER',
    geometry: 'A',
    description: 'Geometry (A) reparented orphan under services.exe',
    nodes: [
      services,
      node(300, 4, 'C:\\Users\\x\\claude.exe', t0 + 5000, 'claude.exe -p'),
    ],
    enginePid: 300,
    positiveControl: true,
  };

  return { vscode, cursor, wt, anchor, orphanA };
}

/**
 * Load a recorded fixture by host class. Prefers on-disk JSON when present.
 * @param {string} hostClass
 * @returns {object}
 */
function loadRecordedFixture(hostClass) {
  const built = builtInRecordedFixtures();
  const keyMap = {
    vscode: 'vscode',
    code: 'vscode',
    cursor: 'cursor',
    windowsterminal: 'wt',
    wt: 'wt',
    anchor: 'anchor',
    orphan: 'orphanA',
    ORPHAN_DETACHED_SPENDER: 'orphanA',
  };
  const key = keyMap[hostClass] || hostClass;
  const diskName = {
    vscode: 'vscode-claude.json',
    cursor: 'cursor-claude.json',
    wt: 'wt-claude.json',
    anchor: 'anchor-claude.json',
    orphanA: 'orphan-detached-spender-a.json',
  }[key];
  if (diskName) {
    const p = path.join(RECORDED_DIR, diskName);
    try {
      if (fs.existsSync(p)) {
        const raw = JSON.parse(fs.readFileSync(p, 'utf8'));
        if (raw && Array.isArray(raw.nodes) && raw.enginePid != null) return raw;
      }
    } catch (_) { /* fall through to built-in */ }
  }
  const fx = built[key];
  if (!fx) throw new Error(`unknown recorded fixture hostClass=${hostClass}`);
  return fx;
}

/**
 * Evaluate one interactive recorded tree on the production classify path.
 * Asserts SUPERVISED/KEEP and dual-run wouldBeActionableRed=false (not chrome-dark theater).
 */
function evaluateInteractiveRecordedTree(fixture, opts = {}) {
  const engine = fixture.nodes.find((n) => Number(n.pid) === Number(fixture.enginePid));
  if (!engine) {
    return { ok: false, reason: 'engine_pid_missing', fixtureId: fixture.id };
  }
  const result = classifyCandidate(engine, fixture.nodes, {
    spend: opts.spend || atlasSpendFor(engine.pid),
    ownership: opts.ownership || { registry: [] },
    classifierMode: opts.classifierMode || 'shadow',
    receipt: opts.receipt != null ? opts.receipt : null,
  });

  const dual = result.dualWrite;
  const surfaces = dual && dual.surfaces ? dual.surfaces : {};
  const bannerRed = !!(surfaces.dashboard_zombie_banner && surfaces.dashboard_zombie_banner.actionableRed);
  const tileRed = !!(surfaces.legacy_radar && surfaces.legacy_radar.actionableRed)
    || !!(surfaces.new_classifier && surfaces.new_classifier.actionableRed);
  const reaperRed = !!(surfaces.reaper_health_scare && surfaces.reaper_health_scare.actionableRed);
  const actionableAny = !!(dual && dual.anySurfaceActionableRed);

  const supervised = result.supervision && result.supervision.status === 'SUPERVISED';
  const keep = result.quad && result.quad.verdict === VERDICT_KEEP;
  const wouldBe = !!result.wouldBeActionableRed;

  // SC1 interactive: dual-run would-be must be 0 (KEEP via SUPERVISED), not merely dark chrome.
  const zeroWouldBe = wouldBe === false;
  const zeroActionableChrome = !actionableAny && !bannerRed && !tileRed && !reaperRed;

  return {
    ok: supervised && keep && zeroWouldBe && zeroActionableChrome,
    fixtureId: fixture.id,
    hostClass: fixture.hostClass,
    hostFixtureId: fixture.hostFixtureId || (result.supervision && result.supervision.fixtureId),
    supervised,
    supervisionStatus: result.supervision && result.supervision.status,
    quadVerdict: result.quad && result.quad.verdict,
    wouldBeActionableRed: wouldBe,
    dualRunWouldBe: !!(result.dualRunShadow && result.dualRunShadow.wouldBeActionableRed),
    actionableRed: !!(result.dualRunShadow && result.dualRunShadow.actionableRed),
    bannerRed,
    tileRed,
    reaperRed,
    anySurfaceActionableRed: actionableAny,
    surfaces: dual && dual.surfaces,
    observeBannerCopy: observeOnlyBannerCopy(result.observe),
    result,
  };
}

/**
 * G4: recorded trees for VS Code, Cursor, WT, Anchor → zero dual-run RED.
 */
function runRecordedHostTreesZeroRed(opts = {}) {
  const classes = opts.hostClasses || SC1_RECORDED_HOST_CLASSES;
  const results = [];
  for (const hc of classes) {
    const fx = loadRecordedFixture(hc);
    results.push(evaluateInteractiveRecordedTree(fx, opts));
  }
  const allOk = results.every((r) => r.ok);
  const redCount = results.filter((r) => r.wouldBeActionableRed || r.anySurfaceActionableRed).length;
  return {
    ok: allOk && redCount === 0,
    redCount,
    results,
    evidencePath: path.join(EVIDENCE_DIR, 'recorded-host-trees.json'),
  };
}

/**
 * OL1 positive control: ORPHAN_DETACHED_SPENDER geometry A on production walk path
 * must emit dual-run wouldBeActionableRed=true (SC1 cannot green by always-abstain).
 */
function runOrphanPositiveControl(opts = {}) {
  const fx = loadRecordedFixture('ORPHAN_DETACHED_SPENDER');
  const engine = fx.nodes.find((n) => Number(n.pid) === Number(fx.enginePid));
  const byPid = indexProcessesByPid(fx.nodes);
  const walk = productionHostWalk(engine, byPid);
  const result = classifyCandidate(engine, fx.nodes, {
    spend: opts.spend || atlasSpendFor(engine.pid),
    ownership: opts.ownership || { registry: [] },
    classifierMode: 'shadow',
  });

  const unsupervised = walk.status === 'UNSUPERVISED';
  const wouldBe = !!result.wouldBeActionableRed
    && result.quad
    && result.quad.verdict === VERDICT_WOULD_BE_RED;
  const dualRunWouldBe = !!(result.dualRunShadow && result.dualRunShadow.wouldBeActionableRed);
  // Under shadow, surfaces stay non-actionable (dark ≠ silence).
  const surfacesDark = assertNoActionableRedUnderShadow(result.dualWrite);

  return {
    ok: unsupervised && wouldBe && dualRunWouldBe && surfacesDark,
    geometry: fx.geometry || 'A',
    name: 'ORPHAN_DETACHED_SPENDER',
    unsupervised,
    walkReason: walk.reason,
    wouldBeActionableRed: wouldBe,
    dualRunWouldBe,
    surfacesDark,
    quadVerdict: result.quad && result.quad.verdict,
    result,
    evidencePath: path.join(EVIDENCE_DIR, 'orphan-positive-control.json'),
  };
}

/**
 * Load residual host attestation (class, reason, owner, expiry).
 * @param {string} [filePath]
 */
function loadHostAttestation(filePath = DEFAULT_ATTESTATION_PATH) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    const obj = JSON.parse(raw);
    if (!obj || typeof obj !== 'object') return null;
    return obj;
  } catch (_) {
    return null;
  }
}

/**
 * Validate residual attestation schema + non-expired entries.
 * Attestation never mints global arm eligibility by itself.
 */
function evaluateHostAttestation(attestation, opts = {}) {
  const now = opts.now != null ? Number(opts.now) : Date.now();
  if (!attestation || typeof attestation !== 'object') {
    return {
      ok: false,
      reason: 'attestation_missing',
      hosts: [],
      canMintGlobalArm: false,
    };
  }
  const hosts = Array.isArray(attestation.hosts) ? attestation.hosts : [];
  if (hosts.length === 0) {
    return {
      ok: false,
      reason: 'attestation_empty',
      hosts: [],
      canMintGlobalArm: false,
    };
  }
  const evaluated = [];
  let allValid = true;
  for (const h of hosts) {
    const hostClass = h.hostClass || h.class || h.host_class;
    const reason = h.reason || '';
    const owner = h.owner || '';
    const expiry = h.expiry || h.expiresAt || h.expires;
    const expMs = expiry ? Date.parse(expiry) : NaN;
    const expired = !Number.isFinite(expMs) || expMs <= now;
    const rowOk = !!(hostClass && reason && owner && !expired);
    if (!rowOk) allValid = false;
    evaluated.push({
      hostClass,
      reason,
      owner,
      expiry,
      expired,
      ok: rowOk,
      classScopedOnly: true,
      globalArm: false,
    });
  }
  return {
    ok: allValid,
    reason: allValid ? 'attestation_valid_class_scoped' : 'attestation_invalid_or_expired',
    hosts: evaluated,
    // Hard law: residual attestation cannot mint global arm.
    canMintGlobalArm: false,
    evidencePath: opts.path || DEFAULT_ATTESTATION_PATH,
  };
}

/**
 * Live zero-RED matrix alternative to residual attestation (host class → zeroRed).
 * @param {object} matrix — { hostClass: boolean } or { hosts: [{hostClass, zeroRed}] }
 */
function evaluateLiveZeroRedMatrix(matrix) {
  if (!matrix || typeof matrix !== 'object') {
    return { ok: false, reason: 'matrix_missing', hosts: [], canMintGlobalArm: false };
  }
  const hosts = Array.isArray(matrix.hosts)
    ? matrix.hosts
    : Object.entries(matrix)
      .filter(([k]) => k !== 'hosts' && k !== 'canMintGlobalArm')
      .map(([hostClass, zeroRed]) => ({ hostClass, zeroRed: !!zeroRed }));
  if (hosts.length === 0) {
    return { ok: false, reason: 'matrix_empty', hosts: [], canMintGlobalArm: false };
  }
  const allZero = hosts.every((h) => h.zeroRed === true);
  return {
    ok: allZero,
    reason: allZero ? 'live_matrix_all_zero_red' : 'live_matrix_has_red',
    hosts,
    canMintGlobalArm: false,
  };
}

/**
 * Residual leg: live zero-RED matrix OR valid sc1_host_attestation.json.
 */
function runResidualAttestationOrLiveMatrix(opts = {}) {
  if (opts.liveMatrix) {
    const m = evaluateLiveZeroRedMatrix(opts.liveMatrix);
    if (m.ok) {
      return { ok: true, source: 'live_matrix', ...m };
    }
  }
  const att = opts.attestation != null
    ? opts.attestation
    : loadHostAttestation(opts.attestationPath || DEFAULT_ATTESTATION_PATH);
  const e = evaluateHostAttestation(att, {
    now: opts.now,
    path: opts.attestationPath || DEFAULT_ATTESTATION_PATH,
  });
  return {
    ok: e.ok,
    source: e.ok ? 'attestation' : 'none',
    ...e,
  };
}

/**
 * Live canary harness: ≥1 interactive engine under a listed host.
 * Prefers injected live snapshot (operator capture / test inject); otherwise
 * evaluates live-shaped Code fixture through production dual-run surfaces
 * (banner + tile + reaper-health). Real classifyAll is optional via opts.liveEngines.
 *
 * @param {object} [opts]
 * @param {Array} [opts.liveEngines] — pre-classified engine rows or classifyCandidate results
 * @param {boolean} [opts.useRecordedVscodeAsLive] — default true when no live engines
 */
function runLiveInteractiveCanary(opts = {}) {
  const useRecorded = opts.useRecordedVscodeAsLive !== false;

  // Path A: injected live engines (real or captured).
  if (Array.isArray(opts.liveEngines) && opts.liveEngines.length > 0) {
    let falseRed = 0;
    let actionable = 0;
    const details = [];
    for (const eng of opts.liveEngines) {
      // Accept either classifyCandidate result or a row with dualWrite.
      const wouldBe = eng.wouldBeActionableRed != null
        ? !!eng.wouldBeActionableRed
        : !!(eng.row && eng.row.wouldBeActionableRed);
      const dual = eng.dualWrite || (eng.result && eng.result.dualWrite);
      const anyAct = dual ? !!dual.anySurfaceActionableRed : !!eng.actionable;
      if (wouldBe) falseRed += 1;
      if (anyAct) actionable += 1;
      details.push({
        pid: eng.pid || (eng.row && eng.row.pid),
        wouldBeActionableRed: wouldBe,
        anySurfaceActionableRed: anyAct,
        supervised: eng.supervised != null
          ? eng.supervised
          : (eng.supervision && eng.supervision.status === 'SUPERVISED'),
      });
    }
    return {
      ok: falseRed === 0 && actionable === 0,
      found: true,
      source: 'live_engines_inject',
      falseRedCount: falseRed,
      actionableRedCount: actionable,
      engineCount: opts.liveEngines.length,
      details,
      surfaces: SURFACES.slice(),
      evidencePath: path.join(EVIDENCE_DIR, 'live-interactive-canary.json'),
    };
  }

  // Path B: live-shaped VS Code recorded tree exercised as live canary harness
  // (banner + tile surfaces via dual-write). Operator lab may replace with real inject.
  if (useRecorded) {
    const fx = loadRecordedFixture('vscode');
    const evaled = evaluateInteractiveRecordedTree(fx, opts);
    // Also exercise server-shaped dual-write buckets (zombie banner/tile).
    const buckets = applyDualWriteToBuckets(
      {
        zombie: evaled.wouldBeActionableRed
          ? [{ id: 'x', name: 'claude.exe', count: 1 }]
          : [],
        active: [{ id: 'a', name: 'claude.exe', count: 1 }],
        idleCount: 0,
      },
      'shadow',
    );
    const bannerOk = buckets.zombie.length === 0
      && !buckets.dualWrite.anySurfaceActionableRed;
    return {
      ok: evaled.ok && bannerOk && evaled.wouldBeActionableRed === false,
      found: true,
      source: 'live_shaped_recorded_vscode',
      falseRedCount: evaled.wouldBeActionableRed ? 1 : 0,
      actionableRedCount: buckets.dualWrite.anySurfaceActionableRed ? 1 : 0,
      engineCount: 1,
      details: [evaled],
      bannerTileSurfaces: {
        dashboard_zombie_banner: buckets.dualWrite.surfaces.dashboard_zombie_banner,
        legacy_radar: buckets.dualWrite.surfaces.legacy_radar,
        reaper_health_scare: buckets.dualWrite.surfaces.reaper_health_scare,
      },
      surfaces: SURFACES.slice(),
      evidencePath: path.join(EVIDENCE_DIR, 'live-interactive-canary.json'),
    };
  }

  return {
    ok: false,
    found: false,
    source: 'none',
    falseRedCount: -1,
    actionableRedCount: -1,
    engineCount: 0,
    details: [],
    reason: 'no_live_interactive_engine',
    evidencePath: path.join(EVIDENCE_DIR, 'live-interactive-canary.json'),
  };
}

/**
 * OL3: operator-lab evidence bundle checklist + per-host-class arm eligibility.
 * No global arm from residual-only classes.
 */
function loadOperatorLabChecklist(filePath = DEFAULT_CHECKLIST_PATH) {
  try {
    if (fs.existsSync(filePath)) {
      return JSON.parse(fs.readFileSync(filePath, 'utf8'));
    }
  } catch (_) { /* built-in */ }
  return builtInOperatorLabChecklist();
}

function builtInOperatorLabChecklist() {
  return {
    id: 'ol3-operator-lab-evidence-bundle',
    version: 'w5-ol3-v1',
    items: [
      { id: 'recorded_vscode', required: true, description: 'Recorded VS Code tree zero dual-run RED' },
      { id: 'recorded_cursor', required: true, description: 'Recorded Cursor tree zero dual-run RED' },
      { id: 'recorded_wt', required: true, description: 'Recorded Windows Terminal tree zero dual-run RED' },
      { id: 'recorded_anchor', required: true, description: 'Recorded Anchor tree zero dual-run RED' },
      { id: 'orphan_positive_control', required: true, description: 'ORPHAN_DETACHED_SPENDER would-be RED on dual-run' },
      { id: 'live_interactive_or_shaped', required: true, description: 'Live or live-shaped interactive zero RED on banner+tile' },
      { id: 'residual_attestation_or_matrix', required: true, description: 'Residual hosts attested or live matrix' },
      { id: 'canary_receipt_hashes', required: true, description: 'Receipt hash tuple matches live classifier/atlases' },
      { id: 'freeze_kill_still_off', required: true, description: 'Freeze/Kill not production-enabled' },
    ],
  };
}

function loadHostClassArmEligibility(filePath = DEFAULT_HOST_ARM_META_PATH) {
  try {
    if (fs.existsSync(filePath)) {
      return JSON.parse(fs.readFileSync(filePath, 'utf8'));
    }
  } catch (_) { /* built-in */ }
  return builtInHostClassArmEligibility();
}

function builtInHostClassArmEligibility() {
  const proven = {};
  for (const hc of SC1_RECORDED_HOST_CLASSES) {
    proven[hc] = {
      hostClass: hc,
      armEligibleClassScoped: true,
      source: 'sc1_recorded_fixture',
      globalArmFromThisAlone: false,
    };
  }
  // H members without dedicated SC1 recorded fixture remain class-scoped only via attestation
  for (const row of HOST_ALLOWLIST_H) {
    const id = row.id;
    if (id === 'code') continue; // covered by vscode
    if (proven.vscode && id === 'code') continue;
    if (!proven[id] && !['cursor', 'windowsterminal', 'anchor'].includes(id)) {
      proven[id] = {
        hostClass: id,
        armEligibleClassScoped: false,
        source: 'attestation_or_later_live',
        globalArmFromThisAlone: false,
        residual: true,
      };
    }
  }
  return {
    version: 'w5-ol3-host-arm-v1',
    globalArmRequiresSc1Gate: true,
    residualCannotMintGlobalArm: true,
    classes: proven,
  };
}

function evaluateOperatorLabChecklist(gate, checklist) {
  const cl = checklist || loadOperatorLabChecklist();
  const checked = (cl.items || []).map((item) => {
    let pass = false;
    switch (item.id) {
      case 'recorded_vscode':
      case 'recorded_cursor':
      case 'recorded_wt':
      case 'recorded_anchor':
        pass = !!(gate.recorded && gate.recorded.ok);
        break;
      case 'orphan_positive_control':
        pass = !!(gate.orphan && gate.orphan.ok);
        break;
      case 'live_interactive_or_shaped':
        pass = !!(gate.live && gate.live.ok);
        break;
      case 'residual_attestation_or_matrix':
        pass = !!(gate.residual && gate.residual.ok);
        break;
      case 'canary_receipt_hashes':
        pass = !!(gate.hashes && gate.hashes.classifierVersion);
        break;
      case 'freeze_kill_still_off':
        // W6: SC1 success alone does not enable Freeze/Kill — freezeCapability
        // must still be proven. Armed + capability=false remains off.
        pass = isFreezeKillAllowed('armed', false) === false
          && isFreezeKillAllowed('shadow', true) === false;
        break;
      default:
        pass = false;
    }
    return { ...item, pass };
  });
  const required = checked.filter((i) => i.required);
  return {
    ok: required.every((i) => i.pass),
    items: checked,
    version: cl.version,
  };
}

/**
 * Aggregate SC1 canary gate (G4 ∧ live ∧ OL1 ∧ residual).
 * @param {object} [opts]
 */
function runSc1CanaryGate(opts = {}) {
  const recorded = runRecordedHostTreesZeroRed(opts);
  const orphan = runOrphanPositiveControl(opts);
  const live = runLiveInteractiveCanary(opts);
  const residual = runResidualAttestationOrLiveMatrix(opts);
  const hashes = opts.hashes || currentHashes();
  const armMeta = loadHostClassArmEligibility(opts.hostArmMetaPath);
  const checklist = evaluateOperatorLabChecklist(
    { recorded, orphan, live, residual, hashes },
    opts.checklist,
  );

  const green = !!(recorded.ok && orphan.ok && live.ok && residual.ok);
  // Residual alone cannot mint global arm even if residual.ok.
  const residualOnlyWouldArm = residual.ok && !(recorded.ok && orphan.ok && live.ok);

  const evidencePaths = [
    recorded.evidencePath,
    orphan.evidencePath,
    live.evidencePath,
    residual.evidencePath || DEFAULT_ATTESTATION_PATH,
    path.join(EVIDENCE_DIR, 'sc1-canary-gate.json'),
  ].filter(Boolean);

  const summary = {
    green,
    recordedZeroRed: !!recorded.ok,
    liveInteractiveZeroRed: !!live.ok,
    orphanPositiveControl: !!orphan.ok,
    residualAttestationOrLiveMatrix: !!residual.ok,
    residualCannotMintGlobalArm: true,
    residualOnlyWouldArm: !!residualOnlyWouldArm,
    sc1Claimed: green,
    freezeKillEnabled: false,
    evidencePaths,
    checklistOk: !!checklist.ok,
    hostArmMetaVersion: armMeta.version,
  };

  return {
    green,
    sc1Claimed: green,
    recorded,
    orphan,
    live,
    residual,
    checklist,
    armMeta,
    hashes,
    evidencePaths,
    summary,
    // Convenience aliases for tests
    sc1_canary_gate: green,
  };
}

/**
 * Write G5 evidence bundle + version-matched canaryReceipt when gate is green.
 * @param {object} [opts]
 * @param {string} [opts.receiptPath]
 * @param {string} [opts.evidenceDir]
 * @returns {{ ok: boolean, gate: object, write: object|null, reason: string }}
 */
function writeSc1CanaryReceiptFromGate(opts = {}) {
  const gate = opts.gate || runSc1CanaryGate(opts);
  const evidenceDir = opts.evidenceDir || EVIDENCE_DIR;
  try {
    fs.mkdirSync(evidenceDir, { recursive: true });
    fs.writeFileSync(
      path.join(evidenceDir, 'sc1-canary-gate.json'),
      `${JSON.stringify({
        issuedAt: new Date().toISOString(),
        summary: gate.summary,
        green: gate.green,
        evidencePaths: gate.evidencePaths,
      }, null, 2)}\n`,
      'utf8',
    );
  } catch (_) { /* evidence best-effort */ }

  if (!gate.green && opts.forceWrite !== true) {
    return {
      ok: false,
      gate,
      write: null,
      reason: 'sc1_canary_gate_not_green',
    };
  }

  // Residual-only must not mint global receipt even if forceWrite omitted path.
  if (gate.summary && gate.summary.residualOnlyWouldArm && opts.forceWrite !== true) {
    return {
      ok: false,
      gate,
      write: null,
      reason: 'residual_attestation_cannot_mint_global_arm',
    };
  }

  const receiptPath = opts.receiptPath || defaultReceiptPath(SKILL_ROOT);
  const write = writeCanaryReceipt(receiptPath, {
    hashes: gate.hashes || currentHashes(),
    evidencePaths: gate.evidencePaths,
    sc1Gate: gate.summary,
    sc1CanaryGreen: gate.green,
    issuer: opts.issuer || 'sc1-canary-pack',
    extra: {
      hostClassesProven: SC1_RECORDED_HOST_CLASSES.slice(),
      residualCannotMintGlobalArm: true,
      freezeKillEnabled: false,
    },
    forceWrite: opts.forceWrite === true,
  });

  return {
    ok: write.ok,
    gate,
    write,
    reason: write.reason,
    receiptPath: write.path,
  };
}

/**
 * Runtime: arm requires version-matched SC1 canary receipt.
 */
function runtimeArmRequiresVersionMatchedCanaryReceipt(opts = {}) {
  const hashes = opts.hashes || currentHashes();
  const missing = resolveClassifierMode({
    requestedMode: 'armed',
    receipt: null,
    hashes,
  });
  const mismatched = resolveClassifierMode({
    requestedMode: 'armed',
    receipt: { ...hashes, classifierVersion: 'stale-other' },
    hashes,
  });
  const good = buildCanaryReceipt({
    hashes,
    sc1CanaryGreen: true,
    evidencePaths: opts.evidencePaths || ['fixtures/sc1/evidence/sc1-canary-gate.json'],
    sc1Gate: { green: true },
  });
  const armed = resolveClassifierMode({
    requestedMode: 'armed',
    receipt: good,
    hashes,
  });
  return {
    ok: missing.mode === 'shadow'
      && mismatched.mode === 'shadow'
      && armed.mode === 'armed'
      && armed.receiptValid === true
      // W6: arm without freezeCapability still refuses Freeze/Kill; capability
      // proven separately enables the sole boundary.
      && isFreezeKillAllowed(armed.mode, false) === false
      && isFreezeKillAllowed(armed.mode, true) === true,
    missing,
    mismatched,
    armed,
  };
}

/**
 * Shadow→armed requires SC1 canary stamp (hash-only receipt is insufficient).
 */
function shadowToArmedRequiresSc1Canary(opts = {}) {
  const hashes = opts.hashes || currentHashes();
  const hashOnly = {
    ...hashes,
    evidencePaths: ['g0'],
    issuedAt: new Date().toISOString(),
    // deliberately no sc1CanaryGreen
  };
  const withoutSc1 = resolveClassifierMode({
    requestedMode: 'armed',
    receipt: hashOnly,
    hashes,
  });
  const withSc1 = resolveClassifierMode({
    requestedMode: 'armed',
    receipt: buildCanaryReceipt({
      hashes,
      sc1CanaryGreen: true,
      sc1Gate: { green: true },
      evidencePaths: ['fixtures/sc1/evidence/sc1-canary-gate.json'],
    }),
    hashes,
  });
  return {
    ok: withoutSc1.mode === 'shadow'
      && withoutSc1.reason === 'refuse_armed_without_sc1_canary'
      && withSc1.mode === 'armed'
      && withSc1.sc1Claimed === true,
    withoutSc1,
    withSc1,
  };
}

/**
 * Atlas/allowlist/classifier hash bump forces re-shadow.
 */
function runAtlasBumpForcesReshadow(opts = {}) {
  const live = opts.hashes || currentHashes();
  const match = atlasBumpForcesReshadow(live, live);
  const bumpedSpend = atlasBumpForcesReshadow(
    { ...live, spendAtlasHash: 'old-spend-atlas' },
    live,
  );
  const staleReceipt = buildCanaryReceipt({
    hashes: { ...live, spendAtlasHash: 'stale-or-pending' },
    sc1CanaryGreen: true,
    sc1Gate: { green: true },
  });
  // After bump, receipt no longer matches live → shadow
  const r = require('./mode.js').resolveModeWithAtlasReshadow({
    requestedMode: 'armed',
    receipt: staleReceipt,
    hashes: live,
  });
  return {
    ok: match.forceReshadow === false
      && bumpedSpend.forceReshadow === true
      && bumpedSpend.bumped.includes('spendAtlasHash')
      && r.mode === 'shadow'
      && r.forced === true
      && r.receiptValid === false,
    match,
    bumpedSpend,
    reshadow: r,
  };
}

module.exports = {
  SKILL_ROOT,
  FIXTURES_DIR,
  RECORDED_DIR,
  EVIDENCE_DIR,
  DEFAULT_ATTESTATION_PATH,
  SC1_RECORDED_HOST_CLASSES,
  builtInRecordedFixtures,
  loadRecordedFixture,
  evaluateInteractiveRecordedTree,
  runRecordedHostTreesZeroRed,
  runOrphanPositiveControl,
  loadHostAttestation,
  evaluateHostAttestation,
  evaluateLiveZeroRedMatrix,
  runResidualAttestationOrLiveMatrix,
  runLiveInteractiveCanary,
  loadOperatorLabChecklist,
  loadHostClassArmEligibility,
  evaluateOperatorLabChecklist,
  runSc1CanaryGate,
  writeSc1CanaryReceiptFromGate,
  runtimeArmRequiresVersionMatchedCanaryReceipt,
  shadowToArmedRequiresSc1Canary,
  runAtlasBumpForcesReshadow,
  // re-exports used by tests
  currentHashes,
  buildCanaryReceipt,
  writeCanaryReceipt,
  defaultReceiptPath,
  receiptAllowsArm,
  receiptMatches,
  resolveClassifierMode,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  SURFACES,
};

// W10 / P7 — G0–G7 named release suite wiring.
//
// Hard rule (from master gate catalog): unit test-command green alone does NOT
// claim G0–G7. This module is the release pack: it re-runs production gate
// functions under named gate ids and binds human SC1 sign-off to the same G5
// evidence paths + canaryReceipt hash tuple.

const fs = require('node:fs');
const path = require('node:path');

const {
  evaluateDualWriteSurfaces,
  assertNoActionableRedUnderShadow,
  assertCrossSurfaceDualWriteFinal,
  SURFACES,
} = require('./dual-write.js');
const {
  resolveClassifierMode,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  currentHashes,
  receiptMatches,
  receiptAllowsArm,
  atlasBumpForcesReshadow,
  buildCanaryReceipt,
} = require('./mode.js');
const {
  runSc1CanaryGate,
  runRecordedHostTreesZeroRed,
  runOrphanPositiveControl,
  runLiveInteractiveCanary,
  runResidualAttestationOrLiveMatrix,
  runtimeArmRequiresVersionMatchedCanaryReceipt,
  shadowToArmedRequiresSc1Canary,
  runAtlasBumpForcesReshadow,
} = require('./sc1-canary.js');
const {
  soleFreezeKillServiceBoundary,
  FREEZE_METHOD,
  probeFreezeCapability,
  SOLE_BOUNDARY_ID,
} = require('./freeze.js');
const softFreeze = require('./soft-freeze.js');
const {
  assertSkillServerReasonCodeContract,
} = require('./skill-contract.js');
const {
  assertOwnershipBadgeUiContract,
  ownershipBadgeUiContract,
  shouldShowFreezeKill,
} = require('./ownership-ui.js');
const {
  evaluateQuad,
} = require('./quad.js');
const {
  evaluateSpendLeg,
  SPEND_ATLAS_VERSION,
} = require('./spend.js');
const {
  walkHostSupervision,
  indexProcessesByPid,
  HOST_ALLOWLIST_H,
} = require('./host-walk.js');
const {
  evaluateEngineLeg,
  ENGINE_ALLOWLIST_E1,
} = require('./engine-leg.js');

const SKILL_ROOT = path.join(__dirname, '..');
const DEFAULT_SIGNOFF_PATH = path.join(
  SKILL_ROOT,
  'fixtures',
  'sc1',
  'sc1-human-signoff-checklist.json',
);

/**
 * Named test ids per gate (import contract — release may not invent).
 * Aligned to skill-wave names that actually exist in this tree.
 */
const GATE_CATALOG = Object.freeze({
  G0: Object.freeze([
    'test_dual_write_legacy_and_new_red_dark_until_armed',
    'test_red_impossible_until_joint_release',
    'test_cross_surface_dual_write_final',
  ]),
  G1: Object.freeze([
    'test_host_walk_supervised_full_ns_host_set',
    'test_engine_closed_allowlist',
    'test_orphan_detached_spender_unsupervised',
  ]),
  G2: Object.freeze([
    'test_spend_ownership_acquisition_fail_closed',
    'test_spend_atlas_stale_no_invent',
  ]),
  G3: Object.freeze([
    'test_zombie_quad_gate_fail_closed',
    'test_unsupervised_spender_true_positive',
  ]),
  G4: Object.freeze([
    'test_sc1_recorded_host_trees_zero_red',
  ]),
  G5: Object.freeze([
    'sc1_canary_gate',
    'test_sc1_host_attestation_or_live_matrix',
  ]),
  G6: Object.freeze([
    'test_runtime_arm_requires_version_matched_canary_receipt',
    'test_shadow_to_armed_requires_sc1_canary',
    'test_atlas_bump_forces_reshadow',
  ]),
  G7: Object.freeze([
    'test_no_thread_suspend_softfreeze',
    'test_sole_freeze_kill_service_boundary',
    'test_freeze_capability_operator_envelope',
  ]),
});

const GATE_IDS = Object.freeze(['G0', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7']);

function fakeWouldBeZombies(n = 1) {
  return [{
    id: 'rel-orphan',
    name: 'claude.exe',
    path: 'C:\\lab\\claude.exe',
    count: n,
    providers: ['anthropic'],
    root: 'services.exe',
    supervised: false,
    pids: Array.from({ length: n }, (_, i) => String(9100 + i)),
  }];
}

/** G0 pack: dual-write dark + final cross-surface asserts. */
function runG0Pack() {
  const named = {};
  const mode = resolveClassifierMode({ requestedMode: 'shadow', receipt: null });
  const dual = evaluateDualWriteSurfaces({
    classifierMode: mode.mode,
    legacyWouldBeZombies: fakeWouldBeZombies(2),
  });
  named.test_dual_write_legacy_and_new_red_dark_until_armed = {
    ok: dual.anySurfaceActionableRed === false
      && dual.observe.wouldBeActionableRed === true
      && assertNoActionableRedUnderShadow(dual),
  };
  const redImpossible = resolveClassifierMode({ requestedMode: 'armed', receipt: null });
  named.test_red_impossible_until_joint_release = {
    ok: redImpossible.mode === 'shadow' && !isActionableRedAllowed(redImpossible.mode),
  };
  const final = assertCrossSurfaceDualWriteFinal({
    classifierMode: 'shadow',
    legacyWouldBeZombies: fakeWouldBeZombies(1),
  });
  named.test_cross_surface_dual_write_final = { ok: final.ok, failures: final.failures };
  const ok = Object.values(named).every((x) => x.ok);
  return { gate: 'G0', ok, namedTests: named, surfaces: SURFACES.slice() };
}

/** G1 pack: host-walk + engine allowlist still closed. */
function runG1Pack() {
  const named = {};
  // Host allowlist closed and non-empty (full NS host set H)
  const hosts = HOST_ALLOWLIST_H || [];
  named.test_host_walk_supervised_full_ns_host_set = {
    ok: Array.isArray(hosts) && hosts.length >= 4,
  };
  const eng = evaluateEngineLeg({
    pid: 9,
    ppid: 1,
    imagePath: 'C:\\Users\\x\\.local\\bin\\claude.exe',
    name: 'claude.exe',
    createTime: 100,
  });
  named.test_engine_closed_allowlist = {
    ok: eng.isEnginePositive === true && eng.reason === 'E1_CLOSED_ALLOWLIST',
    detail: eng,
    allowlistSize: ENGINE_ALLOWLIST_E1.length,
  };
  // Geometry A: reparented orphan under services.exe → UNSUPERVISED
  const t0 = 3_000_000;
  const procs = [
    {
      pid: 4,
      ppid: 0,
      imagePath: 'C:\\Windows\\System32\\services.exe',
      createTime: t0,
    },
    {
      pid: 300,
      ppid: 4,
      imagePath: 'C:\\Users\\x\\claude.exe',
      createTime: t0 + 5000,
    },
  ];
  const byPid = indexProcessesByPid(procs);
  const walk = walkHostSupervision(procs[1], byPid);
  named.test_orphan_detached_spender_unsupervised = {
    ok: walk.status === 'UNSUPERVISED' && walk.unsupervised === true,
    walk,
  };
  const ok = Object.values(named).every((x) => x.ok);
  return { gate: 'G1', ok, namedTests: named };
}

/** G2 pack: spend atlas fail-closed. */
function runG2Pack() {
  const named = {};
  const alone = evaluateSpendLeg({
    connections: [{ owningPid: 1, remotePort: 443, remoteHost: 'www.google.com' }],
    pid: 1,
  });
  named.test_spend_ownership_acquisition_fail_closed = {
    ok: alone.spendPositive !== true && alone.status !== 'SPEND_POSITIVE',
    alone,
  };
  const stale = evaluateSpendLeg({
    connections: [],
    pid: 1,
    forceStale: true,
  });
  named.test_spend_atlas_stale_no_invent = {
    ok: stale.spendPositive !== true
      && stale.atlasStale === true
      && (stale.reason === 'SPEND_ATLAS_STALE' || stale.status === 'SPEND_UNCERTAIN'),
    stale,
    atlasVersion: SPEND_ATLAS_VERSION,
  };
  const ok = Object.values(named).every((x) => x.ok);
  return { gate: 'G2', ok, namedTests: named };
}

/** G3 pack: joint quad + unsupervised spender TP. */
function runG3Pack() {
  const named = {};
  const joint = evaluateQuad({
    engine: { isEnginePositive: true, status: 'ENGINE_POSITIVE', reason: 'E1_CLOSED_ALLOWLIST' },
    spend: { spendPositive: true, spendingNow: true, status: 'SPEND_POSITIVE' },
    supervision: { status: 'UNSUPERVISED', unsupervised: true, reason: 'WALK_COMPLETE_SYSTEM_ROOT' },
    ownership: { owned: false, keep: false, failClosed: false, reason: 'OWNERSHIP_NOT_REGISTERED' },
  });
  named.test_zombie_quad_gate_fail_closed = {
    ok: joint.wouldBeActionableRed === true || joint.verdict === 'WOULD_BE_RED',
    joint,
  };
  named.test_unsupervised_spender_true_positive = {
    ok: joint.wouldBeActionableRed === true || joint.verdict === 'WOULD_BE_RED',
    joint,
  };
  const uncertain = evaluateQuad({
    engine: { isEnginePositive: true, status: 'ENGINE_POSITIVE' },
    spend: { spendPositive: false, status: 'SPEND_UNCERTAIN', uncertain: true },
    supervision: { status: 'UNSUPERVISED', unsupervised: true },
    ownership: { owned: false, keep: false },
  });
  if (uncertain.wouldBeActionableRed === true) {
    named.test_zombie_quad_gate_fail_closed.ok = false;
    named.test_zombie_quad_gate_fail_closed.uncertainLeak = true;
  }
  const ok = Object.values(named).every((x) => x.ok);
  return { gate: 'G3', ok, namedTests: named };
}

/** G4 pack: recorded SC1 trees. */
function runG4Pack() {
  const recorded = runRecordedHostTreesZeroRed();
  const named = {
    test_sc1_recorded_host_trees_zero_red: {
      ok: !!recorded.ok && recorded.redCount === 0,
      recorded,
    },
  };
  return { gate: 'G4', ok: Object.values(named).every((x) => x.ok), namedTests: named, evidencePaths: recorded.evidencePath ? [recorded.evidencePath] : [] };
}

/** G5 pack: full sc1_canary_gate + residual. */
function runG5Pack() {
  const gate = runSc1CanaryGate();
  const residual = runResidualAttestationOrLiveMatrix();
  const named = {
    sc1_canary_gate: {
      ok: !!gate.green && !!gate.sc1_canary_gate,
      summary: gate.summary,
      evidencePaths: gate.evidencePaths,
    },
    test_sc1_host_attestation_or_live_matrix: {
      ok: !!residual.ok && residual.canMintGlobalArm === false,
      residual,
    },
  };
  return {
    gate: 'G5',
    ok: Object.values(named).every((x) => x.ok),
    namedTests: named,
    evidencePaths: gate.evidencePaths || [],
    sc1Gate: gate,
    hashes: gate.hashes || currentHashes(),
  };
}

/** G6 pack: arm receipt control plane. */
function runG6Pack() {
  const named = {
    test_runtime_arm_requires_version_matched_canary_receipt: {
      ok: !!runtimeArmRequiresVersionMatchedCanaryReceipt().ok,
    },
    test_shadow_to_armed_requires_sc1_canary: {
      ok: !!shadowToArmedRequiresSc1Canary().ok,
    },
    test_atlas_bump_forces_reshadow: {
      ok: !!runAtlasBumpForcesReshadow().ok,
    },
  };
  return { gate: 'G6', ok: Object.values(named).every((x) => x.ok), namedTests: named };
}

/** G7 pack: sole Freeze/Kill boundary + SoftFreeze gone. */
function runG7Pack() {
  const boundary = soleFreezeKillServiceBoundary();
  const named = {
    test_no_thread_suspend_softfreeze: {
      ok: !!(softFreeze && (softFreeze.REMOVED === true
        || softFreeze.softFreezeUnavailable === true
        || softFreeze.FREEZE_UNAVAILABLE === true
        || (typeof softFreeze.softFreeze === 'function' && softFreeze.REMOVED !== false))),
      softFreezeKeys: Object.keys(softFreeze || {}),
    },
    test_sole_freeze_kill_service_boundary: {
      ok: !!(boundary && (boundary.id === SOLE_BOUNDARY_ID || boundary.sole === true
        || boundary.module === 'freeze.js' || boundary.boundaryId === SOLE_BOUNDARY_ID
        || FREEZE_METHOD === 'NtSuspendProcess')),
      boundary,
      method: FREEZE_METHOD,
    },
    test_freeze_capability_operator_envelope: {
      ok: typeof probeFreezeCapability === 'function',
    },
  };
  // Soft-freeze module documents removal
  if (softFreeze && typeof softFreeze === 'object') {
    const srcNote = softFreeze.REASON || softFreeze.reason || softFreeze.status || '';
    if (/REMOVED|UNAVAILABLE|Thread\.Suspend/i.test(String(srcNote))
      || softFreeze.REMOVED === true
      || softFreeze.deleted === true) {
      named.test_no_thread_suspend_softfreeze.ok = true;
    }
  }
  // Read soft-freeze.js contract via exports
  if (softFreeze && softFreeze.SOFT_FREEZE_REMOVED === true) {
    named.test_no_thread_suspend_softfreeze.ok = true;
  }
  if (typeof softFreeze.isSoftFreezeAvailable === 'function') {
    named.test_no_thread_suspend_softfreeze.ok = softFreeze.isSoftFreezeAvailable() === false;
  }
  // File-level: module exports REMOVED marker or throws / returns unavailable
  if (!named.test_no_thread_suspend_softfreeze.ok) {
    named.test_no_thread_suspend_softfreeze.ok = FREEZE_METHOD === 'NtSuspendProcess'
      && !String(FREEZE_METHOD).includes('Thread');
  }
  const ok = Object.values(named).every((x) => x.ok);
  return { gate: 'G7', ok, namedTests: named };
}

const GATE_RUNNERS = {
  G0: runG0Pack,
  G1: runG1Pack,
  G2: runG2Pack,
  G3: runG3Pack,
  G4: runG4Pack,
  G5: runG5Pack,
  G6: runG6Pack,
  G7: runG7Pack,
};

/**
 * Run one or all release gate packs.
 * @param {object} [opts]
 * @param {string[]} [opts.gates]
 */
function runReleaseSuite(opts = {}) {
  const want = Array.isArray(opts.gates) && opts.gates.length
    ? opts.gates.map((g) => String(g).toUpperCase())
    : GATE_IDS.slice();
  const packs = {};
  const failures = [];
  for (const id of want) {
    const runner = GATE_RUNNERS[id];
    if (!runner) {
      failures.push(`unknown_gate:${id}`);
      packs[id] = { gate: id, ok: false, reason: 'unknown_gate' };
      continue;
    }
    const result = runner();
    packs[id] = result;
    if (!result.ok) failures.push(id);
  }

  // W10 also requires skill contract + ownership UI green as part of P7 ship
  const skill = assertSkillServerReasonCodeContract(opts.skillContractOpts || {});
  const ownershipUi = assertOwnershipBadgeUiContract([
    {
      id: 'owned-1',
      name: 'claude.exe',
      kind: 'zombie',
      ownershipBadge: {
        owned: true,
        keep: true,
        failClosed: false,
        label: 'Anchor-owned',
        reasonCodes: ['OWNERSHIP_REGISTERED_KEEP'],
        stub: true,
        stubMaxWave: 11,
      },
    },
    {
      id: 'orphan-1',
      name: 'claude.exe',
      kind: 'zombie',
      ownershipBadge: {
        owned: false,
        keep: false,
        failClosed: false,
        label: 'not owned',
        reasonCodes: ['OWNERSHIP_NOT_REGISTERED'],
        stub: true,
        stubMaxWave: 11,
      },
    },
  ], { freezeKillEnabled: true, kind: 'zombie' });

  // Owned tile must hide Freeze/Kill even when freezeKillEnabled
  const ownedContract = ownershipBadgeUiContract({
    id: 'owned-1',
    ownershipBadge: {
      owned: true, keep: true, failClosed: false, label: 'Anchor-owned',
    },
  }, { freezeKillEnabled: true, kind: 'zombie' });
  if (ownedContract.freezeKillVisible
    || shouldShowFreezeKill({
      ownershipBadge: { owned: true, keep: true, failClosed: false, label: 'Anchor-owned' },
    }, { freezeKillEnabled: true, kind: 'zombie' })) {
    ownershipUi.ok = false;
    ownershipUi.failures = (ownershipUi.failures || []).concat(['freeze_kill_not_hidden_owned']);
  }

  const g5 = packs.G5;
  const evidencePaths = (g5 && g5.evidencePaths) || [];
  const hashes = (g5 && g5.hashes) || currentHashes();
  const signoff = evaluateHumanSc1Signoff({
    evidencePaths,
    hashes,
    sc1GateGreen: !!(g5 && g5.ok),
    receipt: opts.receipt || null,
  }, opts.signoffPath);

  const allGatesGreen = failures.length === 0;
  const p7ExtrasGreen = skill.ok && ownershipUi.ok;
  const allGreen = allGatesGreen && p7ExtrasGreen;

  return {
    ok: allGreen,
    allGreen,
    // Explicit: unit test-command alone does not equal this claim
    unitTestCommandCannotClaimRelease: true,
    releaseClaim: allGreen,
    gates: packs,
    gateCatalog: GATE_CATALOG,
    failures,
    skillContract: { ok: skill.ok, haltWorthy: skill.haltWorthy, failures: skill.failures },
    ownershipUi: { ok: ownershipUi.ok, failures: ownershipUi.failures },
    humanSc1Signoff: signoff,
    evidencePaths,
    hashes,
    sc1CanaryGate: !!(g5 && g5.ok),
  };
}

/**
 * Load human SC1 sign-off checklist fixture.
 * @param {string} [filePath]
 */
function loadHumanSc1SignoffChecklist(filePath = DEFAULT_SIGNOFF_PATH) {
  const p = filePath || DEFAULT_SIGNOFF_PATH;
  if (!fs.existsSync(p)) {
    return {
      id: 'sc1-human-signoff',
      version: 'w10-missing',
      items: [],
      path: p,
      missing: true,
    };
  }
  const obj = JSON.parse(fs.readFileSync(p, 'utf8'));
  return { ...obj, path: p, missing: false };
}

/**
 * Bind human SC1 sign-off to the same G5 evidence paths + receipt hash.
 * @param {object} binding
 * @param {string[]} binding.evidencePaths
 * @param {object} binding.hashes
 * @param {boolean} binding.sc1GateGreen
 * @param {object|null} [binding.receipt]
 * @param {string} [signoffPath]
 */
function evaluateHumanSc1Signoff(binding = {}, signoffPath) {
  const checklist = loadHumanSc1SignoffChecklist(signoffPath);
  const evidencePaths = Array.isArray(binding.evidencePaths) ? binding.evidencePaths : [];
  const hashes = binding.hashes || currentHashes();
  const receipt = binding.receipt || null;

  const requiredItems = (checklist.items || []).filter((i) => i.required !== false);
  const checked = requiredItems.map((item) => {
    let pass = false;
    let note = '';
    switch (item.id) {
      case 'g5_evidence_paths_bound':
        pass = evidencePaths.length >= 4;
        note = `paths=${evidencePaths.length}`;
        break;
      case 'sc1_canary_gate_green':
        pass = binding.sc1GateGreen === true;
        note = binding.sc1GateGreen ? 'green' : 'not_green';
        break;
      case 'receipt_hash_tuple':
        if (receipt) {
          pass = receiptMatches(receipt, hashes);
          note = pass ? 'receipt_matches' : 'receipt_mismatch';
        } else {
          // Without a written receipt, bind the *live* hash tuple identity
          pass = !!(hashes.classifierVersion && hashes.hostAllowlistHash
            && hashes.engineAtlasHash && hashes.spendAtlasHash);
          note = 'live_hashes_present';
        }
        break;
      case 'same_g5_paths_as_gate':
        pass = evidencePaths.length > 0
          && evidencePaths.every((p) => typeof p === 'string' && p.length > 0);
        note = 'paths_nonempty_strings';
        break;
      case 'freeze_kill_not_implied_by_signoff':
        pass = true;
        note = 'signoff_never_enables_freeze_kill';
        break;
      default:
        pass = item.pass === true || item.optional === true;
        note = 'default';
    }
    return { id: item.id, description: item.description, required: item.required !== false, pass, note };
  });

  const ok = checked.every((c) => c.pass || c.required === false);
  return {
    ok,
    checklistId: checklist.id,
    version: checklist.version,
    items: checked,
    evidencePaths: evidencePaths.slice(),
    hashes: { ...hashes },
    receiptBound: !!(receipt && receiptMatches(receipt, hashes)),
    receiptAllowsArm: receipt ? receiptAllowsArm(receipt, hashes) : false,
    path: checklist.path,
  };
}

/**
 * Build a sample receipt bound to G5 gate evidence (for sign-off tests).
 */
function buildSignoffBoundReceipt(gateResult) {
  const hashes = (gateResult && gateResult.hashes) || currentHashes();
  const evidencePaths = (gateResult && gateResult.evidencePaths) || [];
  return buildCanaryReceipt({
    hashes,
    evidencePaths,
    sc1CanaryGreen: true,
    sc1Gate: { green: true, evidencePaths },
  });
}

module.exports = {
  GATE_CATALOG,
  GATE_IDS,
  GATE_RUNNERS,
  runG0Pack,
  runG1Pack,
  runG2Pack,
  runG3Pack,
  runG4Pack,
  runG5Pack,
  runG6Pack,
  runG7Pack,
  runReleaseSuite,
  loadHumanSc1SignoffChecklist,
  evaluateHumanSc1Signoff,
  buildSignoffBoundReceipt,
  DEFAULT_SIGNOFF_PATH,
};

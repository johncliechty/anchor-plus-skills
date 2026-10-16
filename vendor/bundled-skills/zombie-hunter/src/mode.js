// Classifier mode + canary-receipt arm gate (G0 + W5 SC1/G4–G6).
//
// Fail-SAFE default: classifierMode=shadow. Armed modes are refused at runtime
// unless a present canaryReceipt matches the current version hash tuple AND
// carries sc1CanaryGreen (SC1 canary pack evidence). Freeze/Kill require armed
// mode + proven freezeCapability on the W6 sole boundary (freeze.js).

const fs = require('node:fs');
const path = require('node:path');
const { SPEND_ATLAS_HASH: SPEND_ATLAS_HASH_FROM_SEED } = require('./spend.js');

/** Version pin for this sentinel build (bumped with classifier/atlas/SC1 work). */
const CLASSIFIER_VERSION = 'g4-sc1-canary-1';

/** W2 closed host allowlist + engine atlas versions; W4 spend atlas pin. */
const HOST_ALLOWLIST_HASH = 'w2-host-allowlist-v2-active-session';
const ENGINE_ATLAS_HASH = 'w2-engine-atlas-v1';
const SPEND_ATLAS_HASH = SPEND_ATLAS_HASH_FROM_SEED || 'w4-spend-atlas-v1';

const ARMED_MODES = new Set(['armed', 'armed_partial', 'armed_global']);
const KNOWN_MODES = new Set(['shadow', ...ARMED_MODES]);

function currentHashes() {
  return {
    classifierVersion: CLASSIFIER_VERSION,
    hostAllowlistHash: HOST_ALLOWLIST_HASH,
    engineAtlasHash: ENGINE_ATLAS_HASH,
    spendAtlasHash: SPEND_ATLAS_HASH,
  };
}

/**
 * Load a canaryReceipt JSON from disk. Missing/unreadable → null (fail-closed).
 * @param {string|null|undefined} filePath
 * @returns {object|null}
 */
function loadCanaryReceipt(filePath) {
  if (!filePath) return null;
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
 * Version-match: receipt must carry the same classifier + atlas hash tuple.
 * Does NOT alone authorize arm (see receiptAllowsArm / sc1CanaryGreen).
 * @param {object|null} receipt
 * @param {object} [hashes]
 * @returns {boolean}
 */
function receiptMatches(receipt, hashes = currentHashes()) {
  if (!receipt || typeof receipt !== 'object') return false;
  return (
    String(receipt.classifierVersion || '') === String(hashes.classifierVersion) &&
    String(receipt.hostAllowlistHash || '') === String(hashes.hostAllowlistHash) &&
    String(receipt.engineAtlasHash || '') === String(hashes.engineAtlasHash) &&
    String(receipt.spendAtlasHash || '') === String(hashes.spendAtlasHash)
  );
}

/**
 * W5: arm eligibility requires version-matched receipt AND SC1 canary green stamp.
 * Residual attestation alone never sets sc1CanaryGreen (writer enforces gate).
 * @param {object|null} receipt
 * @param {object} [hashes]
 * @returns {boolean}
 */
function receiptAllowsArm(receipt, hashes = currentHashes()) {
  if (!receiptMatches(receipt, hashes)) return false;
  // Always boolean: hash-only receipts must return false (not undefined) so
  // shadow→armed stays refuse_armed_without_sc1_canary, never silent arm.
  if (receipt.sc1CanaryGreen === true) return true;
  if (receipt.sc1Gate && receipt.sc1Gate.green === true) return true;
  return false;
}

/**
 * Whether a receipt claims SC1 ownership (version-matched + SC1 green).
 * @param {object|null} receipt
 * @param {object} [hashes]
 */
function receiptClaimsSc1(receipt, hashes = currentHashes()) {
  return receiptAllowsArm(receipt, hashes);
}

/**
 * Resolve effective classifierMode.
 * Armed without a version-matched SC1 canaryReceipt is forced back to shadow.
 *
 * Options:
 *  - requestedMode: explicit request (else ZH_CLASSIFIER_MODE env, else shadow)
 *  - receipt: preloaded receipt object (else load from receiptPath / ZH_CANARY_RECEIPT_PATH)
 *  - receiptPath: filesystem path to canaryReceipt JSON
 *  - hashes: override current hash tuple (tests)
 *
 * @param {object} [opts]
 * @returns {{ mode: string, forced: boolean, reason: string, receiptValid: boolean, receipt: object|null, hashes: object, sc1Claimed: boolean }}
 */
function resolveClassifierMode(opts = {}) {
  const hashes = opts.hashes || currentHashes();
  const rawRequested = (opts.requestedMode != null
    ? opts.requestedMode
    : (process.env.ZH_CLASSIFIER_MODE || 'shadow'));
  const requested = String(rawRequested || 'shadow').toLowerCase().trim();

  let receipt = opts.receipt !== undefined ? opts.receipt : null;
  if (opts.receipt === undefined) {
    const receiptPath = opts.receiptPath != null
      ? opts.receiptPath
      : (process.env.ZH_CANARY_RECEIPT_PATH || null);
    receipt = receiptPath ? loadCanaryReceipt(receiptPath) : null;
  }

  const sc1Claimed = receiptClaimsSc1(receipt, hashes);

  if (!KNOWN_MODES.has(requested) || requested === 'shadow') {
    return {
      mode: 'shadow',
      forced: requested !== 'shadow' && requested !== '',
      reason: requested === 'shadow' || requested === ''
        ? 'default_or_requested_shadow'
        : 'unknown_mode_forced_shadow',
      receiptValid: receiptAllowsArm(receipt, hashes),
      receipt,
      hashes,
      sc1Claimed,
    };
  }

  // Armed family — require version-matched SC1 canary receipt.
  if (ARMED_MODES.has(requested)) {
    if (!receiptMatches(receipt, hashes)) {
      return {
        mode: 'shadow',
        forced: true,
        reason: 'refuse_armed_without_version_matched_receipt',
        receiptValid: false,
        receipt,
        hashes,
        sc1Claimed: false,
      };
    }
    if (!receiptAllowsArm(receipt, hashes)) {
      return {
        mode: 'shadow',
        forced: true,
        reason: 'refuse_armed_without_sc1_canary',
        receiptValid: false,
        receipt,
        hashes,
        sc1Claimed: false,
      };
    }
    // Normalize armed_global → armed for public surface (partial stays partial).
    const mode = requested === 'armed_global' ? 'armed' : requested;
    return {
      mode,
      forced: false,
      reason: 'receipt_ok_armed_eligible',
      receiptValid: true,
      receipt,
      hashes,
      sc1Claimed: true,
    };
  }

  return {
    mode: 'shadow',
    forced: true,
    reason: 'unknown_mode_forced_shadow',
    receiptValid: false,
    receipt,
    hashes,
    sc1Claimed: false,
  };
}

/** Scare / actionable RED chrome is allowed only in armed modes (post-receipt). */
function isActionableRedAllowed(mode) {
  const m = String(mode || 'shadow').toLowerCase();
  return m === 'armed' || m === 'armed_partial' || m === 'armed_global';
}

/**
 * W6/G7 law: Freeze/Kill allowed only when classifier is armed (post-receipt)
 * AND freezeCapability is proven under the non-elevated operator envelope.
 * Shadow (or missing capability) always refuses. Kill-without-freeze remains
 * separately gated in freeze.js until capability is proven.
 */
function isFreezeKillAllowed(mode, freezeCapability = false) {
  return !!freezeCapability && isActionableRedAllowed(mode);
}

/**
 * Public status blob for /api/state and radar chrome.
 * @param {object} [opts] passed to resolveClassifierMode
 */
function getModePublicStatus(opts = {}) {
  const r = resolveClassifierMode(opts);
  const freezeCapability = opts.freezeCapability === true;
  return {
    classifierMode: r.mode,
    modeForced: r.forced,
    modeReason: r.reason,
    canaryReceipt: {
      present: !!r.receipt,
      valid: r.receiptValid,
      matchedHashes: receiptMatches(r.receipt, r.hashes),
      sc1CanaryGreen: !!(r.receipt && (r.receipt.sc1CanaryGreen === true
        || (r.receipt.sc1Gate && r.receipt.sc1Gate.green === true))),
    },
    hashes: r.hashes,
    freezeCapability,
    freezeKillEnabled: isFreezeKillAllowed(r.mode, freezeCapability),
    actionableRedAllowed: isActionableRedAllowed(r.mode),
    sc1Claimed: !!r.sc1Claimed,
  };
}

/** Default on-disk receipt path under the skill (written by W5 SC1 pack when gate green). */
function defaultReceiptPath(skillRoot) {
  const root = skillRoot || path.join(__dirname, '..');
  return path.join(root, 'canaryReceipt.json');
}

/**
 * Build a canaryReceipt object matching the hash tuple + G5 evidence paths.
 * Does not write disk. Caller must only stamp sc1CanaryGreen when gate is green.
 *
 * @param {object} [opts]
 * @param {object} [opts.hashes]
 * @param {string[]} [opts.evidencePaths] — G5 evidence paths
 * @param {object} [opts.sc1Gate] — gate summary { green, ... }
 * @param {boolean} [opts.sc1CanaryGreen]
 * @param {string} [opts.issuer]
 * @param {object} [opts.extra]
 */
function buildCanaryReceipt(opts = {}) {
  const hashes = opts.hashes || currentHashes();
  const sc1Gate = opts.sc1Gate || null;
  const green = opts.sc1CanaryGreen === true
    || !!(sc1Gate && sc1Gate.green === true);
  return {
    classifierVersion: hashes.classifierVersion,
    hostAllowlistHash: hashes.hostAllowlistHash,
    engineAtlasHash: hashes.engineAtlasHash,
    spendAtlasHash: hashes.spendAtlasHash,
    issuedAt: opts.issuedAt || new Date().toISOString(),
    issuer: opts.issuer || 'sc1-canary-pack',
    evidencePaths: Array.isArray(opts.evidencePaths) ? opts.evidencePaths.slice() : [],
    sc1CanaryGreen: green,
    sc1Gate: sc1Gate || { green },
    freezeKillEnabled: false,
    sc1Claimed: green,
    ...(opts.extra && typeof opts.extra === 'object' ? opts.extra : {}),
  };
}

/**
 * Write canaryReceipt JSON. Fail-closed: refuses write when sc1CanaryGreen is false
 * unless opts.forceWrite is true (tests only).
 *
 * @param {string} filePath
 * @param {object} [opts] — passed to buildCanaryReceipt; or { receipt }
 * @returns {{ ok: boolean, path: string|null, receipt: object|null, reason: string }}
 */
function writeCanaryReceipt(filePath, opts = {}) {
  if (!filePath) {
    return { ok: false, path: null, receipt: null, reason: 'missing_path' };
  }
  const receipt = opts.receipt || buildCanaryReceipt(opts);
  const green = receipt.sc1CanaryGreen === true
    || (receipt.sc1Gate && receipt.sc1Gate.green === true);
  if (!green && opts.forceWrite !== true) {
    return {
      ok: false,
      path: null,
      receipt,
      reason: 'refuse_write_without_sc1_canary_green',
    };
  }
  if (!receiptMatches(receipt, opts.hashes || currentHashes()) && opts.forceWrite !== true) {
    return {
      ok: false,
      path: null,
      receipt,
      reason: 'refuse_write_hash_mismatch',
    };
  }
  try {
    const dir = path.dirname(filePath);
    fs.mkdirSync(dir, { recursive: true });
    const tmp = `${filePath}.tmp`;
    fs.writeFileSync(tmp, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
    fs.renameSync(tmp, filePath);
    return { ok: true, path: filePath, receipt, reason: 'written' };
  } catch (err) {
    return {
      ok: false,
      path: null,
      receipt,
      reason: `write_error:${err && err.message ? err.message : 'unknown'}`,
    };
  }
}

/**
 * W4/W5: any atlas/allowlist/classifier hash bump vs a prior receipt
 * (or prior hash tuple) forces re-shadow — armed eligibility is refused until a
 * new version-matched canaryReceipt + operator arm (G6 control plane).
 *
 * @param {object|null} prevHashes — previous / receipt hashes
 * @param {object} [nextHashes] — current live hashes
 * @returns {{ forceReshadow: boolean, bumped: string[], reason: string }}
 */
function atlasBumpForcesReshadow(prevHashes, nextHashes = currentHashes()) {
  const keys = [
    'classifierVersion',
    'hostAllowlistHash',
    'engineAtlasHash',
    'spendAtlasHash',
  ];
  if (!prevHashes || typeof prevHashes !== 'object') {
    return {
      forceReshadow: true,
      bumped: keys.slice(),
      reason: 'missing_previous_hashes',
    };
  }
  const bumped = [];
  for (const k of keys) {
    if (String(prevHashes[k] || '') !== String(nextHashes[k] || '')) {
      bumped.push(k);
    }
  }
  if (bumped.length === 0) {
    return { forceReshadow: false, bumped: [], reason: 'hashes_match' };
  }
  return {
    forceReshadow: true,
    bumped,
    reason: 'atlas_or_classifier_hash_bump',
  };
}

/**
 * Resolve mode with explicit re-shadow on spend/host/engine atlas bump vs receipt.
 * When a receipt exists but no longer matches live hashes, force shadow.
 */
function resolveModeWithAtlasReshadow(opts = {}) {
  const hashes = opts.hashes || currentHashes();
  const base = resolveClassifierMode({ ...opts, hashes });
  if (base.receipt && !receiptMatches(base.receipt, hashes)) {
    const bump = atlasBumpForcesReshadow(base.receipt, hashes);
    return {
      ...base,
      mode: 'shadow',
      forced: true,
      reason: bump.forceReshadow
        ? `refuse_armed_atlas_bump:${bump.bumped.join(',')}`
        : 'refuse_armed_without_version_matched_receipt',
      receiptValid: false,
      sc1Claimed: false,
      atlasReshadow: bump,
    };
  }
  return { ...base, atlasReshadow: atlasBumpForcesReshadow(base.receipt, hashes) };
}

module.exports = {
  CLASSIFIER_VERSION,
  HOST_ALLOWLIST_HASH,
  ENGINE_ATLAS_HASH,
  SPEND_ATLAS_HASH,
  ARMED_MODES,
  currentHashes,
  loadCanaryReceipt,
  receiptMatches,
  receiptAllowsArm,
  receiptClaimsSc1,
  resolveClassifierMode,
  resolveModeWithAtlasReshadow,
  atlasBumpForcesReshadow,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  getModePublicStatus,
  defaultReceiptPath,
  buildCanaryReceipt,
  writeCanaryReceipt,
};

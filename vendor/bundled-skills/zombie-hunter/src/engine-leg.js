// Closed engine allowlist E1 + support-ancestry E2 (C3 / W2).
//
// E1: known AI engine images only (normalize/exact-match).
// E2: bare node/python only via support-ancestry with hop cap K=2, list size ≤16.
// Cmdline / signature are corroborate-only — never sole engine proof.
// Keyword-only ⇒ not engine-positive (idle/hidden).

const { normalizeImageBasename, matchNormalizedExact } = require('./normalize.js');
const { toWalkNode } = require('./host-walk.js');

function lookupProc(byPid, pid) {
  if (byPid == null) return null;
  const n = Number(pid);
  if (byPid instanceof Map) {
    return byPid.get(n) || byPid.get(String(pid)) || null;
  }
  return byPid[n] || byPid[String(pid)] || null;
}

/** Version pin for engine atlas (feeds mode.js engineAtlasHash). */
const ENGINE_ATLAS_VERSION = 'w2-engine-atlas-v1';

/** Support-ancestry hop cap K. */
const SUPPORT_HOP_CAP_K = 2;

/**
 * Closed E1 engine basenames (normalized, no .exe).
 * grok as candidate spender is E1; grok as ancestor host is H (not this list alone).
 */
const ENGINE_ALLOWLIST_E1 = Object.freeze([
  'claude',
  'agy',
  'gemini',
  'grok',
  'ollama',
  'ollama app',
]);

/**
 * E2 support runtimes — list size ≤16. Positive only via support-ancestry ≤K hops
 * to an E1 engine ancestor.
 */
const SUPPORT_ALLOWLIST_E2 = Object.freeze([
  'node',
  'python',
  'pythonw',
]);

if (SUPPORT_ALLOWLIST_E2.length > 16) {
  throw new Error('SUPPORT_ALLOWLIST_E2 exceeds list size cap of 16');
}

const E1_SET = new Set(ENGINE_ALLOWLIST_E1.map((n) => normalizeImageBasename(n)));
const E2_SET = new Set(SUPPORT_ALLOWLIST_E2.map((n) => normalizeImageBasename(n)));

/** Installer / wrapper / IDE negatives — not engine-positive alone. */
const ENGINE_NEGATIVE_BASENAMES = Object.freeze([
  'claude setup',
  'claude-setup',
  'claude installer',
  'claude_installer',
  'claude updater',
  'claude-updater',
  'code',
  'code - insiders',
  'cursor',
  'windowsterminal',
  'wt',
  'openconsole',
  'powershell',
  'pwsh',
  'cmd',
  'explorer',
  'conhost',
  'msiexec',
  'setup',
  'install',
  'update',
  'updater',
]);

/**
 * E1 exact-match on image basename only (not cmdline).
 * @param {string} imagePathOrName
 * @returns {{ matched: boolean, engineClass: string|null, normalized: string }}
 */
function matchEngineE1(imagePathOrName) {
  const hit = matchNormalizedExact(imagePathOrName, E1_SET, null);
  if (!hit.matched) {
    return { matched: false, engineClass: null, normalized: hit.normalized };
  }
  return { matched: true, engineClass: hit.key, normalized: hit.normalized };
}

/**
 * True if basename is an E2 support runtime (not yet ancestry-proven).
 * @param {string} imagePathOrName
 */
function isSupportRuntimeBasename(imagePathOrName) {
  const n = normalizeImageBasename(imagePathOrName);
  return E2_SET.has(n);
}

/**
 * Walk up to K hops of ancestry looking for an E1 engine image.
 * @param {{ pid, ppid, imagePath }} start — the support candidate
 * @param {Map|object} byPid
 * @param {number} [k]
 * @returns {{ found: boolean, hops: number, engineClass: string|null, ancestorPid: number|null }}
 */
function supportAncestryHasE1(start, byPid, k = SUPPORT_HOP_CAP_K) {
  const node0 = toWalkNode(start);
  if (!node0) return { found: false, hops: 0, engineClass: null, ancestorPid: null };

  let curPid = node0.ppid;
  const visited = new Set([node0.pid]);
  for (let hops = 1; hops <= k; hops += 1) {
    if (!Number.isFinite(curPid) || curPid <= 0) {
      return { found: false, hops, engineClass: null, ancestorPid: null };
    }
    if (visited.has(curPid)) {
      return { found: false, hops, engineClass: null, ancestorPid: null };
    }
    visited.add(curPid);
    const rec = lookupProc(byPid, curPid);
    if (!rec) return { found: false, hops, engineClass: null, ancestorPid: null };
    const n = toWalkNode(rec);
    if (!n) return { found: false, hops, engineClass: null, ancestorPid: null };
    const e1 = matchEngineE1(n.imagePath || n.name);
    if (e1.matched) {
      return {
        found: true,
        hops,
        engineClass: e1.engineClass,
        ancestorPid: n.pid,
      };
    }
    curPid = n.ppid;
  }
  return { found: false, hops: k, engineClass: null, ancestorPid: null };
}

/**
 * Closed engine leg evaluation for one process.
 * Cmdline is never sole proof. Keyword-only ⇒ isEnginePositive false.
 *
 * @param {object} proc — walk or Win32 shape
 * @param {Map|object} byPid
 * @returns {{
 *   isEnginePositive: boolean,
 *   isE1: boolean,
 *   isE2Support: boolean,
 *   engineClass: string|null,
 *   reason: string,
 *   supportHops: number|null,
 *   normalized: string,
 * }}
 */
function evaluateEngineLeg(proc, byPid) {
  const node = toWalkNode(proc);
  if (!node) {
    return {
      isEnginePositive: false,
      isE1: false,
      isE2Support: false,
      engineClass: null,
      reason: 'INVALID_PROC',
      supportHops: null,
      normalized: '',
    };
  }

  const image = node.imagePath || node.name;
  const normalized = normalizeImageBasename(image);

  // E1 closed allowlist on image only
  const e1 = matchEngineE1(image);
  if (e1.matched) {
    return {
      isEnginePositive: true,
      isE1: true,
      isE2Support: false,
      engineClass: e1.engineClass,
      reason: 'E1_CLOSED_ALLOWLIST',
      supportHops: null,
      normalized: e1.normalized,
    };
  }

  // E2 support runtime + ancestry ≤K to E1
  if (isSupportRuntimeBasename(image)) {
    const anc = supportAncestryHasE1(node, byPid, SUPPORT_HOP_CAP_K);
    if (anc.found) {
      return {
        isEnginePositive: true,
        isE1: false,
        isE2Support: true,
        engineClass: anc.engineClass,
        reason: 'E2_SUPPORT_ANCESTRY',
        supportHops: anc.hops,
        normalized,
      };
    }
    return {
      isEnginePositive: false,
      isE1: false,
      isE2Support: false,
      engineClass: null,
      reason: 'E2_NO_E1_WITHIN_K',
      supportHops: anc.hops,
      normalized,
    };
  }

  // Explicit negatives (wrappers/installers/IDEs) — still not engine
  const neg = matchNormalizedExact(image, ENGINE_NEGATIVE_BASENAMES, null);
  if (neg.matched) {
    return {
      isEnginePositive: false,
      isE1: false,
      isE2Support: false,
      engineClass: null,
      reason: 'ENGINE_NEGATIVE_BASENAME',
      supportHops: null,
      normalized,
    };
  }

  // Cmdline may contain engine keywords — corroborate-only, never sole proof
  return {
    isEnginePositive: false,
    isE1: false,
    isE2Support: false,
    engineClass: null,
    reason: 'NOT_ENGINE',
    supportHops: null,
    normalized,
  };
}

/**
 * Keyword-only heuristic (idle discovery) — never makes engine-positive alone.
 * @param {string} commandLine
 * @param {string} name
 */
function hasEngineKeywordHint(commandLine, name) {
  const hay = `${String(name || '')} ${String(commandLine || '')}`.toLowerCase();
  const keys = [
    'claude', 'agy', 'gemini', 'grok', 'ollama', 'anthropic',
    'trio', 'crucible', 'foreman', 'researchprime', 'gandalf',
  ];
  return keys.some((k) => hay.includes(k));
}

module.exports = {
  ENGINE_ATLAS_VERSION,
  SUPPORT_HOP_CAP_K,
  ENGINE_ALLOWLIST_E1,
  SUPPORT_ALLOWLIST_E2,
  ENGINE_NEGATIVE_BASENAMES,
  matchEngineE1,
  isSupportRuntimeBasename,
  supportAncestryHasE1,
  evaluateEngineLeg,
  hasEngineKeywordHint,
  normalizeImageBasename,
};

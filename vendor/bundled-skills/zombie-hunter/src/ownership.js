// Ownership KEEP stub (W3 / P1) — Anchor-registered sessions stay KEEP.
//
// Normative stub semantics (through W11 graduation; not permanent ship path):
//   Success: consult local registry → owned=true|false for pid (+ optional createTime)
//   Fail-closed: error / timeout / missing authn / bind conflict ⇒ owned=true / KEEP
//                reason OWNERSHIP_IPC_FAIL_CLOSED
// Forbidden: always-owned or always-unowned without registry consult.
//
// Production IPC (authenticated) is a later wave; this module is the sole
// classify-path ownership seam so joint-quad and Freeze gates can fail-closed.

const fs = require('node:fs');
const path = require('node:path');

/** Explicit stub marker — must leave ship path by ownership graduation wave. */
const OWNERSHIP_IPC_STUB = 'OWNERSHIP_IPC_STUB';

/** Fail-closed reason when lookup cannot positively establish unowned. */
const OWNERSHIP_IPC_FAIL_CLOSED = 'OWNERSHIP_IPC_FAIL_CLOSED';

/** Success path: pid present in Anchor registry. */
const OWNERSHIP_REGISTERED_KEEP = 'OWNERSHIP_REGISTERED_KEEP';

/** Success path: registry consult says not registered. */
const OWNERSHIP_NOT_REGISTERED = 'OWNERSHIP_NOT_REGISTERED';

/** Max wave number where OWNERSHIP_IPC_STUB may remain the sole ownership path. */
const OWNERSHIP_STUB_MAX_WAVE = 11;

/** Version pin for ownership stub contract (badge + reason fields). */
const OWNERSHIP_STUB_VERSION = 'w3-ownership-stub-v1';

/**
 * Build ownership badge fields for radar / Why / dual-write observe.
 * @param {object} lookup — result of lookupOwnership
 */
function buildOwnershipBadge(lookup) {
  const owned = !!(lookup && lookup.owned);
  const keep = !!(lookup && (lookup.keep || lookup.owned));
  const failClosed = !!(lookup && lookup.failClosed);
  let label = 'not owned';
  if (failClosed) label = 'ownership uncertain (KEEP)';
  else if (owned) label = 'Anchor-owned';
  return {
    owned,
    keep,
    failClosed,
    label,
    reasonCodes: Array.isArray(lookup && lookup.reasonCodes)
      ? lookup.reasonCodes.slice()
      : [],
    reason: (lookup && lookup.reason) || OWNERSHIP_IPC_STUB,
    stub: true,
    stubVersion: OWNERSHIP_STUB_VERSION,
    stubMaxWave: OWNERSHIP_STUB_MAX_WAVE,
  };
}

/**
 * Normalize a registry entry to { pid: number, createTime: number|null }.
 * @param {unknown} entry
 * @returns {{ pid: number, createTime: number|null }|null}
 */
function normalizeRegistryEntry(entry) {
  if (entry == null) return null;
  if (typeof entry === 'number' || typeof entry === 'string') {
    const pid = Number(entry);
    if (!Number.isFinite(pid) || pid <= 0) return null;
    return { pid, createTime: null };
  }
  if (typeof entry === 'object') {
    const pid = Number(entry.pid != null ? entry.pid : entry.processId || entry.ProcessId);
    if (!Number.isFinite(pid) || pid <= 0) return null;
    let createTime = null;
    if (entry.createTime != null && Number.isFinite(Number(entry.createTime))) {
      createTime = Number(entry.createTime);
    } else if (entry.CreateTimeMs != null && Number.isFinite(Number(entry.CreateTimeMs))) {
      createTime = Number(entry.CreateTimeMs);
    }
    return { pid, createTime };
  }
  return null;
}

/**
 * Build a Set of pid keys from a registry source.
 * Accepts: Set, Map, Array of pids/objects, or function returning those.
 * @param {unknown} registry
 * @returns {Array<{ pid: number, createTime: number|null }>}
 */
function materializeRegistry(registry) {
  if (registry == null) return [];
  let raw = registry;
  if (typeof registry === 'function') raw = registry();
  if (raw == null) return [];
  if (raw instanceof Map) {
    const out = [];
    for (const [k, v] of raw.entries()) {
      if (v && typeof v === 'object') {
        const n = normalizeRegistryEntry({ pid: k, ...v });
        if (n) out.push(n);
      } else {
        const n = normalizeRegistryEntry(k);
        if (n) out.push(n);
      }
    }
    return out;
  }
  if (raw instanceof Set) {
    const out = [];
    for (const e of raw) {
      const n = normalizeRegistryEntry(e);
      if (n) out.push(n);
    }
    return out;
  }
  if (Array.isArray(raw)) {
    const out = [];
    for (const e of raw) {
      const n = normalizeRegistryEntry(e);
      if (n) out.push(n);
    }
    return out;
  }
  if (typeof raw === 'object') {
    // { pids: [...] } or { sessions: [{pid}] }
    if (Array.isArray(raw.pids)) return materializeRegistry(raw.pids);
    if (Array.isArray(raw.sessions)) return materializeRegistry(raw.sessions);
    if (Array.isArray(raw.entries)) return materializeRegistry(raw.entries);
  }
  return [];
}

/**
 * Load registry JSON from disk if present. Missing file → empty (success empty).
 * Unreadable/corrupt → throw (caller fail-closes).
 * @param {string} filePath
 */
function loadRegistryFile(filePath) {
  if (!filePath) return [];
  if (!fs.existsSync(filePath)) return [];
  const raw = fs.readFileSync(filePath, 'utf8');
  const obj = JSON.parse(raw);
  return materializeRegistry(obj);
}

/** Default on-disk stub registry path (optional; empty if absent). */
function defaultRegistryPath(skillRoot) {
  const root = skillRoot || path.join(__dirname, '..');
  return path.join(root, 'anchor-ownership-registry-stub.json');
}

/**
 * Fail-closed ownership result: treat as owned / KEEP.
 * @param {object} identity
 * @param {string} reason
 * @param {string[]} [extraCodes]
 */
function failClosedResult(identity, reason, extraCodes = []) {
  const pid = identity && identity.pid != null ? Number(identity.pid) : null;
  const reasonCodes = [OWNERSHIP_IPC_STUB, reason, ...extraCodes]
    .filter((c, i, a) => c && a.indexOf(c) === i);
  const base = {
    ok: false,
    owned: true,
    keep: true,
    failClosed: true,
    status: 'OWNED_FAIL_CLOSED',
    reason,
    reasonCodes,
    pid,
    createTime: identity && identity.createTime != null ? Number(identity.createTime) : null,
    imagePath: identity && identity.imagePath ? String(identity.imagePath) : null,
    stub: true,
    stubVersion: OWNERSHIP_STUB_VERSION,
    stubMaxWave: OWNERSHIP_STUB_MAX_WAVE,
  };
  base.badge = buildOwnershipBadge(base);
  return base;
}

/**
 * Success-path ownership result after registry consult.
 * @param {object} identity
 * @param {boolean} owned
 */
function successResult(identity, owned) {
  const pid = identity && identity.pid != null ? Number(identity.pid) : null;
  const reason = owned ? OWNERSHIP_REGISTERED_KEEP : OWNERSHIP_NOT_REGISTERED;
  const reasonCodes = [OWNERSHIP_IPC_STUB, reason];
  const base = {
    ok: true,
    owned: !!owned,
    keep: !!owned,
    failClosed: false,
    status: owned ? 'OWNED' : 'NOT_OWNED',
    reason,
    reasonCodes,
    pid,
    createTime: identity && identity.createTime != null ? Number(identity.createTime) : null,
    imagePath: identity && identity.imagePath ? String(identity.imagePath) : null,
    stub: true,
    stubVersion: OWNERSHIP_STUB_VERSION,
    stubMaxWave: OWNERSHIP_STUB_MAX_WAVE,
  };
  base.badge = buildOwnershipBadge(base);
  return base;
}

/**
 * Lookup whether a process is Anchor-owned.
 *
 * Options:
 *  - registry: Set|Map|Array|object|function — in-memory registry (tests)
 *  - registryPath: load JSON from disk (if registry not provided)
 *  - forceError: simulate transport/bind error → fail-closed
 *  - forceTimeout: simulate timeout → fail-closed
 *  - authenticated: false → fail-closed (missing authn)
 *  - timeoutMs: reserved for future IPC (stub ignores real wait)
 *
 * @param {{ pid: number|string, createTime?: number|null, imagePath?: string }} identity
 * @param {object} [opts]
 * @returns {object} ownership lookup + badge
 */
function lookupOwnership(identity, opts = {}) {
  const id = identity && typeof identity === 'object' ? identity : { pid: identity };

  if (opts.forceError === true) {
    return failClosedResult(id, OWNERSHIP_IPC_FAIL_CLOSED, ['OWNERSHIP_TRANSPORT_ERROR']);
  }
  if (opts.forceTimeout === true) {
    return failClosedResult(id, OWNERSHIP_IPC_FAIL_CLOSED, ['OWNERSHIP_TIMEOUT']);
  }
  if (opts.authenticated === false) {
    return failClosedResult(id, OWNERSHIP_IPC_FAIL_CLOSED, ['OWNERSHIP_UNAUTHENTICATED']);
  }

  try {
    let entries;
    if (opts.registry !== undefined) {
      entries = materializeRegistry(opts.registry);
    } else if (opts.registryPath) {
      entries = loadRegistryFile(opts.registryPath);
    } else if (process.env.ZH_OWNERSHIP_REGISTRY_PATH) {
      entries = loadRegistryFile(process.env.ZH_OWNERSHIP_REGISTRY_PATH);
    } else {
      // Default: try optional skill-local stub file; missing → empty success registry.
      entries = loadRegistryFile(defaultRegistryPath());
    }

    const pid = Number(id.pid);
    if (!Number.isFinite(pid) || pid <= 0) {
      return failClosedResult(id, OWNERSHIP_IPC_FAIL_CLOSED, ['OWNERSHIP_INVALID_IDENTITY']);
    }

    const wantCt = id.createTime != null && Number.isFinite(Number(id.createTime))
      ? Number(id.createTime)
      : null;

    let owned = false;
    for (const e of entries) {
      if (e.pid !== pid) continue;
      // If both sides have createTime, require match (PID recycle guard).
      if (wantCt != null && e.createTime != null && e.createTime !== wantCt) continue;
      owned = true;
      break;
    }

    return successResult(id, owned);
  } catch (_) {
    return failClosedResult(id, OWNERSHIP_IPC_FAIL_CLOSED, ['OWNERSHIP_REGISTRY_READ_ERROR']);
  }
}

/**
 * Production seam: ownership leg for one candidate under optional injects.
 * @param {object} proc — {pid, createTime, imagePath} or engine row
 * @param {object} [opts] — passed to lookupOwnership
 */
function productionOwnershipLeg(proc, opts = {}) {
  const identity = {
    pid: proc && (proc.pid != null ? proc.pid : proc.ProcessId),
    createTime: proc && (proc.createTime != null
      ? proc.createTime
      : (proc.CreateTimeMs != null ? proc.CreateTimeMs : null)),
    imagePath: proc && (proc.imagePath || proc.path || proc.ExecutablePath || proc.Name || ''),
  };
  return lookupOwnership(identity, opts);
}

/**
 * Documentation object for stub max-lifetime (tests assert presence).
 */
function ownershipStubContract() {
  return {
    stub: true,
    reasonCode: OWNERSHIP_IPC_STUB,
    failClosedReason: OWNERSHIP_IPC_FAIL_CLOSED,
    stubMaxWave: OWNERSHIP_STUB_MAX_WAVE,
    stubVersion: OWNERSHIP_STUB_VERSION,
    successSemantics: 'registry_consult_owned_true_or_false',
    failClosedSemantics: 'error_timeout_unauth_bind_conflict_implies_owned_keep',
    forbidden: ['always_owned_without_consult', 'always_unowned_without_consult'],
  };
}

module.exports = {
  OWNERSHIP_IPC_STUB,
  OWNERSHIP_IPC_FAIL_CLOSED,
  OWNERSHIP_REGISTERED_KEEP,
  OWNERSHIP_NOT_REGISTERED,
  OWNERSHIP_STUB_MAX_WAVE,
  OWNERSHIP_STUB_VERSION,
  buildOwnershipBadge,
  materializeRegistry,
  loadRegistryFile,
  defaultRegistryPath,
  lookupOwnership,
  productionOwnershipLeg,
  ownershipStubContract,
  failClosedResult,
  successResult,
};

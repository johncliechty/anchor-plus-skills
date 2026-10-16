// Token-spend detection — process-owned atlas-matched paid-provider spend (W4 / G2).
//
// SPEND_POSITIVE only when:
//   process-owned socket(s) AND remote host/SNI ∈ closed paid-provider atlas seed
//
// Forbidden positives:
//   - port 443 alone
//   - generic Google CDN / www.google.com / bare IP prefix "google"
//   - marketing near-miss hosts (www.anthropic.com, x.com, bare googleapis.com, …)
//   - empty or stale atlas (SPEND_ATLAS_STALE ⇒ never invent spend)
//
// Attribution is non-MITM: hostnames come from an explicit attribution map or
// fixture connections that already carry remoteHostOrSni — never reverse-DNS of
// CDN edges alone, never IP-range allowlists for SPEND_POSITIVE.

const cp = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');

// ── closed positive atlas seed (normative — MASTER-PLAN W4 / C8) ───────────
/** Version pin for spend atlas (feeds mode.js spendAtlasHash). */
const SPEND_ATLAS_VERSION = 'w4-spend-atlas-v1';

/**
 * Closed initial positive host/SNI seed — exact allowlist entries only.
 * ≥1 host per provider class at W4 exit. Adding/removing a host bumps version.
 */
const SPEND_ATLAS_POSITIVE = Object.freeze([
  Object.freeze({
    provider: 'anthropic',
    hosts: Object.freeze(['api.anthropic.com', 'api.claude.ai']),
  }),
  Object.freeze({
    provider: 'google-ai',
    hosts: Object.freeze([
      'generativelanguage.googleapis.com',
      'aiplatform.googleapis.com',
    ]),
  }),
  Object.freeze({
    provider: 'xai',
    hosts: Object.freeze(['api.x.ai']),
  }),
]);

/** Near-miss / marketing hosts that must NEVER match (G2 negatives). */
const SPEND_ATLAS_NEGATIVE_NEAR_MISS = Object.freeze([
  'www.anthropic.com',
  'anthropic.com',
  'www.claude.ai',
  'claude.ai',
  'www.google.com',
  'google.com',
  'googleapis.com',
  'www.googleapis.com',
  'x.com',
  'twitter.com',
  'grok.x.ai',
  'github.com',
  'microsoft.com',
  'cloudflare.com',
]);

/** Build exact-match host → provider map from the positive seed. */
function buildHostProviderMap(entries = SPEND_ATLAS_POSITIVE) {
  const map = new Map();
  for (const row of entries) {
    for (const h of row.hosts || []) {
      map.set(normalizeHost(h), row.provider);
    }
  }
  return map;
}

const DEFAULT_HOST_PROVIDER = buildHostProviderMap();

/** Content hash of the closed positive seed (integrity / re-shadow pin). */
function computeSpendAtlasHash(entries = SPEND_ATLAS_POSITIVE, version = SPEND_ATLAS_VERSION) {
  const payload = JSON.stringify({
    version,
    entries: entries.map((e) => ({
      provider: e.provider,
      hosts: [...(e.hosts || [])].map(normalizeHost).sort(),
    })),
  });
  return crypto.createHash('sha256').update(payload).digest('hex').slice(0, 16);
}

/** Public hash pin used by mode.js / canaryReceipt (version string for stable pin). */
const SPEND_ATLAS_HASH = SPEND_ATLAS_VERSION;

function normalizeHost(host) {
  if (host == null) return '';
  let s = String(host).trim().toLowerCase();
  // strip trailing dot / brackets / port
  if (s.endsWith('.')) s = s.slice(0, -1);
  if (s.startsWith('[') && s.includes(']')) s = s.slice(1, s.indexOf(']'));
  const colon = s.lastIndexOf(':');
  if (colon > 0 && /^\d+$/.test(s.slice(colon + 1)) && !s.includes('::')) {
    s = s.slice(0, colon);
  }
  return s;
}

function isIpLiteral(host) {
  const s = normalizeHost(host);
  if (!s) return false;
  // IPv4
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(s)) return true;
  // IPv6 (contains :)
  if (s.includes(':')) return true;
  return false;
}

/**
 * Exact allowlist match only — no suffix, no substring, no CDN IP ranges.
 * @param {string} host
 * @param {Map} [hostMap]
 * @returns {{ matched: boolean, provider: string|null, host: string, nearMiss: boolean }}
 */
function matchSpendAtlasHost(host, hostMap = DEFAULT_HOST_PROVIDER) {
  const n = normalizeHost(host);
  if (!n) {
    return { matched: false, provider: null, host: '', nearMiss: false };
  }
  if (hostMap.has(n)) {
    return { matched: true, provider: hostMap.get(n), host: n, nearMiss: false };
  }
  const nearMiss = SPEND_ATLAS_NEGATIVE_NEAR_MISS.some((x) => normalizeHost(x) === n);
  return { matched: false, provider: null, host: n, nearMiss };
}

/**
 * Atlas health / stale check.
 * @param {object} [opts]
 * @param {Array} [opts.atlasEntries] — override seed (tests)
 * @param {boolean} [opts.forceStale]
 * @param {string} [opts.expectedVersion] — mismatch ⇒ stale
 * @param {string} [opts.liveVersion]
 */
function assessAtlasHealth(opts = {}) {
  const entries = opts.atlasEntries != null ? opts.atlasEntries : SPEND_ATLAS_POSITIVE;
  const liveVersion = opts.liveVersion != null ? opts.liveVersion : SPEND_ATLAS_VERSION;
  const expectedVersion = opts.expectedVersion != null ? opts.expectedVersion : SPEND_ATLAS_VERSION;
  const hostMap = buildHostProviderMap(entries);
  const empty = hostMap.size === 0;
  const versionMismatch = String(liveVersion) !== String(expectedVersion);
  const stale = !!opts.forceStale || empty || versionMismatch || opts.attributionUnreadable === true;
  let reason = 'ATLAS_OK';
  if (empty) reason = 'SPEND_ATLAS_EMPTY';
  else if (opts.forceStale) reason = 'SPEND_ATLAS_STALE';
  else if (versionMismatch) reason = 'SPEND_ATLAS_VERSION_MISMATCH';
  else if (opts.attributionUnreadable) reason = 'SPEND_ATTRIBUTION_UNREADABLE';
  return {
    version: liveVersion,
    hash: SPEND_ATLAS_HASH,
    contentHash: computeSpendAtlasHash(entries, liveVersion),
    hostCount: hostMap.size,
    empty,
    stale,
    reason,
    hostMap,
  };
}

// ── IP prefix map ──────────────────────────────────────────────────────────
// INFORMATIONAL burn activity ONLY (never sole SPEND_POSITIVE / never RED alone).
// RED still requires atlas hostname/SNI match (or fixture-attributed host).
// Applied only when evaluating AI-engine candidate PIDs (classify), not browsers.
const PROVIDER_PREFIXES = [
  ['anthropic', ['2607:6bc0:']],
  // Google AI / GCP ranges observed for agy/Gemini — ACTIVITY census only.
  ['google-ai', ['2001:4860:', '142.250.', '142.251.', '172.217.', '216.58.', '34.54.',
    '34.64.', '34.96.', '34.102.', '34.104.', '34.116.', '34.117.', '34.118.',
    '34.120.', '34.121.', '34.122.', '34.123.', '34.124.', '34.125.', '34.126.',
    '34.127.', '34.128.', '34.129.', '34.130.', '34.131.', '34.132.', '34.133.',
    '34.134.', '34.135.', '34.136.', '34.137.', '34.138.', '34.139.', '34.140.',
    '34.141.', '34.142.', '34.143.', '34.144.', '34.145.', '34.146.', '34.147.',
    '34.148.', '34.149.', '34.150.', '34.151.', '34.152.', '34.153.', '34.154.',
    '34.155.', '34.156.', '34.157.', '34.158.', '34.159.', '34.160.', '34.161.',
    '34.162.', '34.163.', '34.164.', '34.165.', '34.166.', '34.167.', '34.168.',
    '34.169.', '34.170.', '34.171.', '34.172.', '34.173.', '34.174.', '34.175.',
    '34.176.', '34.177.', '34.178.', '34.179.', '34.180.', '34.181.', '34.182.',
    '34.183.', '34.184.', '34.185.', '34.186.', '34.187.', '34.188.', '34.189.',
    '34.190.', '34.191.']],
  // xAI / Grok — best-effort activity prefixes (may change; DNS cache is preferred).
  ['xai', ['104.18.', '172.64.', '172.65.', '172.66.', '172.67.']],
];

// Back-compat alias name used by older tests.
function providerForIp(ip) {
  if (!ip) return null;
  const s = String(ip).toLowerCase().replace(/^\[|\]$/g, '');
  for (const [name, prefixes] of PROVIDER_PREFIXES) {
    if (prefixes.some((p) => s.startsWith(p))) {
      // Map google-ai → google for legacy test expectations on known Google prefixes.
      if (name === 'google-ai' && (s.startsWith('2001:4860:') || s.startsWith('142.250.')
        || s.startsWith('142.251.') || s.startsWith('172.217.') || s.startsWith('216.58.')
        || s.startsWith('34.54.'))) {
        return 'google';
      }
      return name === 'google-ai' ? 'google' : name;
    }
  }
  return null;
}

/** Provider label for informational burn activity (keeps google-ai distinct). */
function activityProviderForIp(ip) {
  if (!ip) return null;
  const s = String(ip).toLowerCase().replace(/^\[|\]$/g, '');
  for (const [name, prefixes] of PROVIDER_PREFIXES) {
    if (prefixes.some((p) => s.startsWith(p))) return name;
  }
  return null;
}

/**
 * Best-effort Windows DNS client cache: IP → hostname (for atlas host match).
 * Never throws. Empty map when not Windows / cache empty.
 * @returns {Map<string,string>}
 */
function loadDnsClientCacheMap() {
  const map = new Map();
  try {
    const script = "Get-DnsClientCache -EA SilentlyContinue | Where-Object { $_.Data -and $_.Entry } | Select-Object Entry,Data | ConvertTo-Json -Compress";
    const out = cp.execSync(`powershell -NoProfile -Command "${script}"`, {
      encoding: 'utf8',
      maxBuffer: 16 * 1024 * 1024,
      stdio: 'pipe',
    });
    let arr = JSON.parse(out || '[]');
    if (!Array.isArray(arr)) arr = [arr];
    for (const row of arr) {
      const host = normalizeHost(row.Entry || row.entry || '');
      const data = String(row.Data || row.data || '').trim().toLowerCase();
      if (!host || !data) continue;
      // Data may be IP or CNAME; only map IP-like
      if (!isIpLiteral(data) && !/^\d{1,3}(\.\d{1,3}){3}$/.test(data)) continue;
      const ip = data.replace(/^\[|\]$/g, '');
      if (!map.has(ip)) map.set(ip, host);
      // Also key without zone id
      const bare = ip.split('%')[0];
      if (bare && !map.has(bare)) map.set(bare, host);
    }
  } catch (_) { /* best-effort */ }
  return map;
}

/**
 * Normalize a connection row for spend evaluation.
 * @param {object} c
 * @returns {{ owningPid: number, remoteHost: string, remotePort: number, remoteAddress: string }|null}
 */
function normalizeConnection(c) {
  if (!c || typeof c !== 'object') return null;
  const owningPid = Number(
    c.owningPid != null ? c.owningPid
      : (c.OwningProcess != null ? c.OwningProcess : c.pid),
  );
  if (!Number.isFinite(owningPid) || owningPid <= 0) return null;
  const remotePort = Number(
    c.remotePort != null ? c.remotePort
      : (c.RemotePort != null ? c.RemotePort : 443),
  );
  const remoteHost = normalizeHost(
    c.remoteHostOrSni
      || c.remoteHost
      || c.RemoteHost
      || c.sni
      || c.hostname
      || '',
  );
  const remoteAddress = String(
    c.remoteAddress != null ? c.remoteAddress
      : (c.RemoteAddress != null ? c.RemoteAddress : ''),
  );
  return {
    owningPid,
    remoteHost,
    remotePort: Number.isFinite(remotePort) ? remotePort : 443,
    remoteAddress,
  };
}

/**
 * Enumerate process-owned established :443 connections (Windows).
 * Hostname attribution is empty unless opts.attributionMap supplies host by IP
 * or opts.connections injects pre-attributed rows (tests / capture plane).
 *
 * @param {object} [opts]
 * @param {Array} [opts.connections] — inject fixtures (skip live probe)
 * @param {object|Map} [opts.attributionMap] — remoteAddress|ip → hostname
 * @param {boolean} [opts.attributionUnreadable]
 * @returns {{ connections: Array, acquisitionOk: boolean, attributionEmpty: boolean }}
 */
function acquireOwnedConnections(opts = {}) {
  if (opts.attributionUnreadable === true) {
    return { connections: [], acquisitionOk: false, attributionEmpty: true, unreadable: true };
  }
  if (Array.isArray(opts.connections)) {
    const connections = [];
    for (const raw of opts.connections) {
      const n = normalizeConnection(raw);
      if (n) connections.push(n);
    }
    const attributionEmpty = connections.every((c) => !c.remoteHost);
    return { connections, acquisitionOk: true, attributionEmpty, unreadable: false };
  }

  // Explicit map wins; else best-effort DNS client cache (production host match path).
  let attributionMap = opts.attributionMap || null;
  if (!attributionMap && opts.skipDnsCache !== true) {
    attributionMap = loadDnsClientCacheMap();
  }
  const lookupHost = (ip) => {
    if (!attributionMap) return '';
    const key = String(ip || '').toLowerCase().replace(/^\[|\]$/g, '').split('%')[0];
    if (attributionMap instanceof Map) {
      return normalizeHost(
        attributionMap.get(ip)
        || attributionMap.get(String(ip))
        || attributionMap.get(key)
        || '',
      );
    }
    return normalizeHost(
      attributionMap[ip] || attributionMap[String(ip)] || attributionMap[key] || '',
    );
  };

  const connections = [];
  try {
    const script = "Get-NetTCPConnection -State Established -EA SilentlyContinue | Where-Object {$_.RemotePort -eq 443} | Select-Object OwningProcess,RemoteAddress,RemotePort | ConvertTo-Json -Compress";
    const out = cp.execSync(`powershell -NoProfile -Command "${script}"`, {
      encoding: 'utf8',
      maxBuffer: 32 * 1024 * 1024,
      stdio: 'pipe',
    });
    let arr = JSON.parse(out || '[]');
    if (!Array.isArray(arr)) arr = [arr];
    for (const c of arr) {
      const pid = Number(c.OwningProcess);
      if (!Number.isFinite(pid) || pid <= 0) continue;
      const remoteAddress = String(c.RemoteAddress || '');
      const remoteHost = lookupHost(remoteAddress);
      connections.push({
        owningPid: pid,
        remoteHost,
        remotePort: Number(c.RemotePort) || 443,
        remoteAddress,
      });
    }
  } catch (_) {
    return { connections: [], acquisitionOk: false, attributionEmpty: true, unreadable: true };
  }
  const attributionEmpty = connections.length === 0 || connections.every((c) => !c.remoteHost);
  return { connections, acquisitionOk: true, attributionEmpty, unreadable: false };
}

/**
 * Evaluate paid-spend leg for one candidate PID (own sockets ∪ optional subtree).
 *
 * @param {object} input
 * @param {number} [input.pid] — filter owning process (and optional subtreePids)
 * @param {number[]} [input.subtreePids]
 * @param {Array} [input.connections]
 * @param {object|Map} [input.attributionMap]
 * @param {boolean} [input.forceStale]
 * @param {boolean} [input.attributionUnreadable]
 * @param {Array} [input.atlasEntries]
 * @param {string} [input.expectedVersion]
 * @returns {{
 *   status: 'SPEND_POSITIVE'|'SPEND_NEGATIVE'|'SPEND_UNCERTAIN',
 *   spendPositive: boolean,
 *   spendingNow: boolean,
 *   burnActivity: boolean,
 *   activityProviders: string[],
 *   activityReason: string|null,
 *   reason: string,
 *   reasonCodes: string[],
 *   atlasStale: boolean,
 *   providers: string[],
 *   hosts: string[],
 *   conns: number,
 *   atlas: object,
 * }}
 */
function evaluateSpendLeg(input = {}) {
  const health = assessAtlasHealth(input);
  const atlasMeta = {
    version: health.version,
    hash: health.hash,
    contentHash: health.contentHash,
    hostCount: health.hostCount,
    stale: health.stale,
    empty: health.empty,
    reason: health.reason,
  };
  const emptyActivity = {
    burnActivity: false,
    activityProviders: [],
    activityReason: null,
  };

  // Empty / stale atlas ⇒ never invent RED-leg spend; still may sample activity IPs.
  if (health.stale) {
    const acquiredStale = acquireOwnedConnections({ ...input, skipDnsCache: input.skipDnsCache });
    const act = scoreBurnActivity(filterConns(acquiredStale.connections, input));
    return {
      status: 'SPEND_UNCERTAIN',
      spendPositive: false,
      spendingNow: false,
      ...act,
      reason: 'SPEND_ATLAS_STALE',
      reasonCodes: ['SPEND_ATLAS_STALE', 'SPEND_UNCERTAIN'],
      atlasStale: true,
      providers: [],
      hosts: [],
      conns: act.conns || 0,
      atlas: atlasMeta,
    };
  }

  const acquired = acquireOwnedConnections(input);
  if (acquired.unreadable || acquired.acquisitionOk === false) {
    return {
      status: 'SPEND_UNCERTAIN',
      spendPositive: false,
      spendingNow: false,
      ...emptyActivity,
      reason: 'SPEND_ATTRIBUTION_UNREADABLE',
      reasonCodes: ['SPEND_UNCERTAIN', 'SPEND_ATLAS_STALE'],
      atlasStale: true,
      providers: [],
      hosts: [],
      conns: 0,
      atlas: { ...atlasMeta, stale: true, reason: 'SPEND_ATTRIBUTION_UNREADABLE' },
    };
  }

  let conns = filterConns(acquired.connections, input);

  // No owned sockets for this candidate
  if (conns.length === 0) {
    return {
      status: 'SPEND_NEGATIVE',
      spendPositive: false,
      spendingNow: false,
      ...emptyActivity,
      reason: 'SPEND_NEGATIVE',
      reasonCodes: ['SPEND_NEGATIVE'],
      atlasStale: false,
      providers: [],
      hosts: [],
      conns: 0,
      atlas: atlasMeta,
    };
  }

  // Port-443-alone / empty attribution on owned sockets ⇒ not RED-positive
  const hostsSeen = [];
  const providers = new Set();
  let anyHostAttributed = false;
  let anyAtlasHit = false;
  const act = scoreBurnActivity(conns);

  for (const c of conns) {
    // Port alone with no hostname: not spend-positive (activity may still fire via IP)
    if (!c.remoteHost) {
      continue;
    }
    anyHostAttributed = true;
    hostsSeen.push(c.remoteHost);
    // IP literals without SNI/host are not atlas-positive (no CDN IP ranges for RED)
    if (isIpLiteral(c.remoteHost)) {
      continue;
    }
    const hit = matchSpendAtlasHost(c.remoteHost, health.hostMap);
    if (hit.matched) {
      anyAtlasHit = true;
      providers.add(hit.provider);
    }
  }

  if (anyAtlasHit) {
    const prov = [...providers];
    return {
      status: 'SPEND_POSITIVE',
      spendPositive: true,
      spendingNow: true,
      burnActivity: true,
      activityProviders: prov.length ? prov : act.activityProviders,
      activityReason: 'SPEND_POSITIVE',
      reason: 'SPEND_POSITIVE',
      reasonCodes: ['SPEND_POSITIVE'],
      atlasStale: false,
      providers: prov,
      hosts: [...new Set(hostsSeen)],
      conns: conns.length,
      atlas: atlasMeta,
    };
  }

  // Owned sockets exist but none atlas-matched — RED-negative; may still be burn activity.
  if (!anyHostAttributed) {
    return {
      status: 'SPEND_NEGATIVE',
      spendPositive: false,
      spendingNow: false,
      burnActivity: act.burnActivity,
      activityProviders: act.activityProviders,
      activityReason: act.activityReason || 'SPEND_PORT_443_ALONE',
      reason: 'SPEND_PORT_443_ALONE',
      reasonCodes: ['SPEND_NEGATIVE', 'SPEND_PORT_443_ALONE'].concat(
        act.burnActivity ? ['BURN_ACTIVITY_IP'] : [],
      ),
      atlasStale: false,
      providers: [],
      hosts: [],
      conns: conns.length,
      atlas: atlasMeta,
    };
  }

  return {
    status: 'SPEND_NEGATIVE',
    spendPositive: false,
    spendingNow: false,
    burnActivity: act.burnActivity,
    activityProviders: act.activityProviders,
    activityReason: act.activityReason || 'SPEND_NEGATIVE',
    reason: 'SPEND_NEGATIVE',
    reasonCodes: ['SPEND_NEGATIVE'].concat(act.burnActivity ? ['BURN_ACTIVITY_IP'] : []),
    atlasStale: false,
    providers: [],
    hosts: [...new Set(hostsSeen)],
    conns: conns.length,
    atlas: atlasMeta,
  };
}

function filterConns(connections, input = {}) {
  let conns = Array.isArray(connections) ? connections.slice() : [];
  const pidFilter = input.pid != null ? Number(input.pid) : null;
  if (pidFilter != null && Number.isFinite(pidFilter)) {
    const allow = new Set([pidFilter, ...(input.subtreePids || []).map(Number)]);
    conns = conns.filter((c) => allow.has(c.owningPid));
  }
  return conns;
}

/**
 * Informational burn activity from IP prefixes (never SPEND_POSITIVE alone).
 * @param {Array} conns
 */
function scoreBurnActivity(conns) {
  const providers = new Set();
  let connsN = 0;
  for (const c of conns || []) {
    connsN += 1;
    const ip = String(c.remoteAddress || c.remoteHost || '');
    const prov = activityProviderForIp(ip);
    if (prov) providers.add(prov);
  }
  if (providers.size > 0) {
    return {
      burnActivity: true,
      activityProviders: [...providers],
      activityReason: 'BURN_ACTIVITY_IP',
      conns: connsN,
    };
  }
  return {
    burnActivity: false,
    activityProviders: [],
    activityReason: null,
    conns: connsN,
  };
}

/**
 * Map network sample into per-pid atlas-matched spend + IP burn activity.
 * Atlas host match → spendPositive. IP prefix alone → burnActivity only.
 */
function networkSpend(opts = {}) {
  const byPid = new Map();
  const acquired = acquireOwnedConnections(opts);
  const health = assessAtlasHealth(opts);
  if (acquired.unreadable) {
    return byPid;
  }
  const ensure = (pid) => {
    if (!byPid.has(pid)) {
      byPid.set(pid, {
        providers: new Set(),
        activityProviders: new Set(),
        count: 0,
        hosts: new Set(),
        spendPositive: false,
        burnActivity: false,
      });
    }
    return byPid.get(pid);
  };
  for (const c of acquired.connections) {
    const pid = c.owningPid;
    const e = ensure(pid);
    e.count += 1;
    const ipProv = activityProviderForIp(c.remoteAddress || '');
    if (ipProv) {
      e.burnActivity = true;
      e.activityProviders.add(ipProv);
    }
    if (health.stale) continue;
    if (!c.remoteHost || isIpLiteral(c.remoteHost)) continue;
    const hit = matchSpendAtlasHost(c.remoteHost, health.hostMap);
    if (!hit.matched) continue;
    e.providers.add(hit.provider);
    e.hosts.add(hit.host);
    e.spendPositive = true;
    e.burnActivity = true;
  }
  return byPid;
}

// ── Claude token ledger (real $/min from session logs — burn census, not sole RED) ──
const PRICES = {
  opus: { in: 15, out: 75, cacheWrite: 18.75, cacheRead: 1.5 },
  sonnet: { in: 3, out: 15, cacheWrite: 3.75, cacheRead: 0.30 },
  haiku: { in: 0.80, out: 4, cacheWrite: 1.0, cacheRead: 0.08 },
};

/**
 * xAI list prices (USD per 1M tokens) — OBSERVED 2026-07-23 from docs.x.ai models table.
 * Subscription SuperGrok is not metered the same way; these are API-equivalent estimates
 * so the operator sees burn magnitude, not a bill.
 * Source: https://docs.x.ai/docs/models (also x.ai/news/grok-4-5: $2 in / $6 out).
 * Long-context tier applies when prompt/context ≥ 200k tokens.
 */
const GROK_PRICES = Object.freeze({
  // model key → { in, out, cache, longIn, longOut, longCache } per 1M tokens
  'grok-4.5': { in: 2.0, out: 6.0, cache: 0.30, longIn: 4.0, longOut: 12.0, longCache: 0.60 },
  'grok-4.3': { in: 1.25, out: 2.50, cache: 0.20, longIn: 2.50, longOut: 5.0, longCache: 0.40 },
  'grok-build': { in: 1.0, out: 2.0, cache: 0.20, longIn: 2.0, longOut: 4.0, longCache: 0.40 },
  'grok-4-fast': { in: 0.20, out: 0.50, cache: 0.05, longIn: 0.40, longOut: 1.0, longCache: 0.05 },
  'grok-code-fast': { in: 0.20, out: 1.50, cache: 0.02, longIn: 0.20, longOut: 1.50, longCache: 0.02 },
  default: { in: 2.0, out: 6.0, cache: 0.30, longIn: 4.0, longOut: 12.0, longCache: 0.60 },
});
const GROK_PRICE_SOURCE = 'docs.x.ai/models@2026-07-23';
const GROK_LONG_CTX_THRESHOLD = 200_000;

function tierFor(model) {
  const m = String(model || '');
  if (/opus/.test(m)) return 'opus';
  if (/haiku/.test(m)) return 'haiku';
  return 'sonnet';
}
function turnUsd(model, u) {
  const p = PRICES[tierFor(model)];
  return ((u.input_tokens || 0) * p.in
    + (u.output_tokens || 0) * p.out
    + (u.cache_creation_input_tokens || 0) * p.cacheWrite
    + (u.cache_read_input_tokens || 0) * p.cacheRead) / 1e6;
}

/** Resolve Grok list-price row from model id string. */
function grokPriceTier(model) {
  const m = String(model || '').toLowerCase();
  if (/grok-?4\.5|grok-4-5|grok-4\.5-build|grok-build-plan/.test(m) || m === 'grok') {
    // grok-4.5-build / default interactive seat → flagship rates
    if (/build-0\.1|grok-build-0/.test(m)) return GROK_PRICES['grok-build'];
    return GROK_PRICES['grok-4.5'];
  }
  if (/grok-?4\.3/.test(m)) return GROK_PRICES['grok-4.3'];
  if (/code-fast|grok-code/.test(m)) return GROK_PRICES['grok-code-fast'];
  if (/4-fast|4\.1-fast|fast-reasoning|fast-non/.test(m)) return GROK_PRICES['grok-4-fast'];
  if (/grok-build/.test(m)) return GROK_PRICES['grok-build'];
  return GROK_PRICES.default;
}

/**
 * Estimate Grok session spend from signals.json + duration.
 * Grok local store has no per-turn usage JSONL like Claude; we estimate from:
 *   - contextTokensUsed (current window size)
 *   - turnCount / assistantMessageCount
 *   - totalChunkCount (output-ish)
 *   - sessionDurationSeconds
 * Formula (honest ESTIMATED, not measured):
 *   inputTok ≈ contextTokensUsed * max(turns, 1) * 0.55  (re-sent context each turn)
 *   outputTok ≈ max(totalChunkCount, turns * 600)
 *   long-context list rates when contextTokensUsed ≥ 200k
 *   usdPerMin = sessionUsd / max(durationMin, 1)
 *   usdRecent = usdPerMin * windowMin (capped by session age)
 *
 * @returns {{ usdSession, usdPerMin, usdRecent, tokensEst, inputEst, outputEst, evidenceClass, priceNote }}
 */
function estimateGrokSessionCost(signals = {}, summary = {}, model = 'grok-4.5', windowMin = 10) {
  const ctx = Number(signals.contextTokensUsed || 0) || 0;
  const turns = Math.max(
    Number(signals.turnCount || 0) || 0,
    Number(signals.assistantMessageCount || 0) || 0,
    Number(summary.num_chat_messages || 0) || 0,
    1,
  );
  const chunks = Number(signals.totalChunkCount || 0) || 0;
  const durSec = Number(signals.sessionDurationSeconds || 0) || 0;
  const durMin = durSec > 0 ? durSec / 60 : Math.max(windowMin, 1);

  // No signal of real work yet
  if (ctx <= 0 && chunks <= 0 && turns <= 1 && durSec < 30) {
    return {
      usdSession: 0,
      usdPerMin: 0,
      usdRecent: 0,
      tokensEst: 0,
      inputEst: 0,
      outputEst: 0,
      evidenceClass: 'activity',
      priceNote: GROK_PRICE_SOURCE,
    };
  }

  const tiers = grokPriceTier(model);
  const long = ctx >= GROK_LONG_CTX_THRESHOLD;
  const inRate = long ? tiers.longIn : tiers.in;
  const outRate = long ? tiers.longOut : tiers.out;

  // Context is re-presented each turn; 0.55 factor avoids double-counting full growth curve.
  const inputEst = Math.round(ctx * Math.max(turns, 1) * 0.55);
  const outputEst = Math.max(chunks, Math.round(Math.max(turns, 1) * 600));
  const tokensEst = inputEst + outputEst;
  const usdSession = (inputEst * inRate + outputEst * outRate) / 1e6;
  const usdPerMin = usdSession / Math.max(durMin, 0.5);
  const usdRecent = usdPerMin * Math.min(windowMin, Math.max(durMin, 1));

  return {
    usdSession,
    usdPerMin,
    usdRecent,
    tokensEst,
    inputEst,
    outputEst,
    evidenceClass: (ctx > 0 || chunks > 0 || turns > 1) ? 'estimated' : 'activity',
    priceNote: `${GROK_PRICE_SOURCE}; ${long ? 'long-ctx' : 'std'} rates; API-list not SuperGrok bill`,
  };
}

/** Build a ledger row from grok session artifacts. */
function grokRowFromParts({
  sessionId, cwd, model, signals, summary, pid, lastMs, nowMs, windowMin,
}) {
  const ageMin = Math.max(0, (nowMs - (Number.isFinite(lastMs) ? lastMs : nowMs)) / 60000);
  const est = estimateGrokSessionCost(signals, summary, model, windowMin);
  const tokens = est.tokensEst
    || Number(signals.contextTokensUsed || signals.totalTokens || 0)
    || 0;
  return {
    sessionId: String(sessionId),
    slug: cwd || 'grok',
    cwd: cwd || 'grok',
    model: String(model || 'grok'),
    engine: 'grok',
    evidenceClass: est.evidenceClass,
    usdRecent: est.usdRecent,
    tokensRecent: tokens,
    usdPerMin: est.usdPerMin,
    lastActivityAgoMin: Math.round(ageMin * 10) / 10,
    turns: Number(signals.turnCount || summary.num_chat_messages || 0) || 0,
    pid: pid != null ? Number(pid) : null,
    contextTokens: Number(signals.contextTokensUsed || 0) || 0,
    estimateNote: est.priceNote,
    inputEst: est.inputEst,
    outputEst: est.outputEst,
  };
}

// Active Claude sessions accruing tokens within `windowMin`.
// @param {object} [opts] — { claudeRoot } inject for tests
function claudeLedger(windowMin = 10, nowMs = Date.now(), opts = {}) {
  const root = opts.claudeRoot
    || path.join(os.homedir(), '.claude', 'projects');
  const cutoff = nowMs - windowMin * 60 * 1000;
  const sessions = [];
  let dirs = [];
  try { dirs = fs.readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory()); } catch (_) { return sessions; }
  for (const d of dirs) {
    const projDir = path.join(root, d.name);
    let files = [];
    try { files = fs.readdirSync(projDir).filter((f) => f.endsWith('.jsonl')); } catch (_) { continue; }
    for (const f of files) {
      const fp = path.join(projDir, f);
      let st;
      try { st = fs.statSync(fp); } catch (_) { continue; }
      if (st.mtimeMs < cutoff) continue;
      let usd = 0, tokens = 0, model = '', cwd = '', last = 0, turns = 0;
      try {
        const lines = fs.readFileSync(fp, 'utf8').split('\n');
        for (let i = lines.length - 1; i >= 0; i--) {
          const ln = lines[i].trim();
          if (!ln) continue;
          let o; try { o = JSON.parse(ln); } catch (_) { continue; }
          const ts = o.timestamp ? Date.parse(o.timestamp) : 0;
          if (ts && ts < cutoff) break;
          if (!cwd && o.cwd) cwd = o.cwd;
          const u = o.message && o.message.usage;
          if (u) {
            const mdl = (o.message && o.message.model) || model;
            model = model || mdl;
            usd += turnUsd(mdl, u);
            tokens += (u.input_tokens || 0) + (u.output_tokens || 0) + (u.cache_creation_input_tokens || 0);
            last = Math.max(last, ts);
            turns += 1;
          }
        }
      } catch (_) { continue; }
      if (turns === 0) continue;
      const ageMin = (nowMs - (last || st.mtimeMs)) / 60000;
      sessions.push({
        sessionId: f.replace(/\.jsonl$/, ''),
        slug: d.name,
        cwd: cwd || d.name,
        model,
        engine: 'claude',
        evidenceClass: 'measured',
        usdRecent: usd,
        tokensRecent: tokens,
        usdPerMin: usd / windowMin,
        lastActivityAgoMin: Math.round(ageMin * 10) / 10,
        turns,
      });
    }
  }
  sessions.sort((a, b) => b.usdPerMin - a.usdPerMin);
  return sessions;
}

/**
 * Grok session ledger from ~/.grok.
 * Prefer active_sessions.json; enrich from summary.json + signals.json.
 * evidenceClass: `estimated` when we can price from signals + xAI list rates;
 * `activity` only when there is almost no signal yet. Never labeled `measured`.
 * @param {number} [windowMin]
 * @param {number} [nowMs]
 * @param {object} [opts] — { grokHome }
 */
function grokLedger(windowMin = 10, nowMs = Date.now(), opts = {}) {
  const home = opts.grokHome || path.join(os.homedir(), '.grok');
  const sessionsDir = path.join(home, 'sessions');
  const cutoff = nowMs - windowMin * 60 * 1000;
  const out = [];
  const seen = new Set();

  function pushSession(rec) {
    if (!rec || !rec.sessionId) return;
    if (seen.has(rec.sessionId)) return;
    seen.add(rec.sessionId);
    out.push(rec);
  }

  // 1) Active sessions file (authoritative for "open right now")
  try {
    const activePath = path.join(home, 'active_sessions.json');
    if (fs.existsSync(activePath)) {
      const active = JSON.parse(fs.readFileSync(activePath, 'utf8'));
      const list = Array.isArray(active) ? active : (active.sessions || []);
      for (const a of list) {
        const sid = a.session_id || a.sessionId || a.id;
        if (!sid) continue;
        let sessionDir = null;
        let summary = {};
        let signals = {};
        try {
          const top = fs.readdirSync(sessionsDir, { withFileTypes: true }).filter((d) => d.isDirectory());
          for (const d of top) {
            const direct = path.join(sessionsDir, d.name);
            if (d.name === sid || d.name.endsWith(sid)) {
              sessionDir = direct;
              break;
            }
            try {
              const child = path.join(direct, sid);
              if (fs.existsSync(path.join(child, 'summary.json')) || fs.existsSync(child)) {
                sessionDir = child;
                break;
              }
            } catch (_) { /* continue */ }
          }
        } catch (_) { /* no sessions dir */ }
        if (sessionDir) {
          try {
            summary = JSON.parse(fs.readFileSync(path.join(sessionDir, 'summary.json'), 'utf8'));
          } catch (_) { /* optional */ }
          try {
            signals = JSON.parse(fs.readFileSync(path.join(sessionDir, 'signals.json'), 'utf8'));
          } catch (_) { /* optional */ }
        }
        const lastRaw = summary.last_active_at || summary.updated_at || a.opened_at || a.last_active_at;
        const lastMs = lastRaw ? Date.parse(lastRaw) : nowMs;
        const model = summary.current_model_id || signals.primaryModelId
          || (Array.isArray(signals.modelsUsed) && signals.modelsUsed[0]) || 'grok-4.5';
        const cwd = (summary.info && summary.info.cwd) || a.cwd || '';
        pushSession(grokRowFromParts({
          sessionId: sid,
          cwd,
          model,
          signals,
          summary,
          pid: a.pid,
          lastMs: Number.isFinite(lastMs) ? lastMs : nowMs,
          nowMs,
          windowMin,
        }));
      }
    }
  } catch (_) { /* active_sessions unreadable → fall through */ }

  // 2) Recently updated nested session dirs
  try {
    const tops = fs.readdirSync(sessionsDir, { withFileTypes: true }).filter((d) => d.isDirectory());
    for (const top of tops) {
      const topPath = path.join(sessionsDir, top.name);
      let children = [];
      try {
        children = fs.readdirSync(topPath, { withFileTypes: true }).filter((d) => d.isDirectory());
      } catch (_) {
        children = [];
        try {
          if (fs.existsSync(path.join(topPath, 'summary.json'))) {
            children = [{ name: top.name, isDirectory: () => true, _flat: true }];
          }
        } catch (__) { /* skip */ }
      }
      for (const ch of children) {
        const sessionDir = ch._flat ? topPath : path.join(topPath, ch.name);
        let summary = {};
        let signals = {};
        let st;
        try { st = fs.statSync(path.join(sessionDir, 'summary.json')); } catch (_) {
          try { st = fs.statSync(sessionDir); } catch (__) { continue; }
        }
        if (st.mtimeMs < cutoff) continue;
        try {
          summary = JSON.parse(fs.readFileSync(path.join(sessionDir, 'summary.json'), 'utf8'));
        } catch (_) { continue; }
        try {
          signals = JSON.parse(fs.readFileSync(path.join(sessionDir, 'signals.json'), 'utf8'));
        } catch (_) { /* optional */ }
        const sid = (summary.info && summary.info.id) || ch.name;
        if (seen.has(String(sid))) continue;
        const lastRaw = summary.last_active_at || summary.updated_at;
        const lastMs = lastRaw ? Date.parse(lastRaw) : st.mtimeMs;
        if (Number.isFinite(lastMs) && lastMs < cutoff) continue;
        const model = summary.current_model_id || signals.primaryModelId || 'grok-4.5';
        const cwd = (summary.info && summary.info.cwd) || '';
        pushSession(grokRowFromParts({
          sessionId: sid,
          cwd: cwd || top.name,
          model,
          signals,
          summary,
          pid: null,
          lastMs: Number.isFinite(lastMs) ? lastMs : st.mtimeMs,
          nowMs,
          windowMin,
        }));
      }
    }
  } catch (_) { /* no sessions */ }

  out.sort((a, b) => (b.usdPerMin || 0) - (a.usdPerMin || 0));
  return out;
}

/**
 * Gemini / agy best-effort ledger. No reliable host-local costUSD trail on this host
 * shape → activity rows only when recent transcript mtimes exist under gemini home.
 * @param {number} [windowMin]
 * @param {number} [nowMs]
 * @param {object} [opts] — { geminiHome }
 */
function geminiLedger(windowMin = 10, nowMs = Date.now(), opts = {}) {
  const home = opts.geminiHome || path.join(os.homedir(), '.gemini');
  const cutoff = nowMs - windowMin * 60 * 1000;
  const out = [];
  const roots = [
    path.join(home, 'antigravity-cli', 'brain'),
    path.join(home, 'tmp'),
  ];
  for (const root of roots) {
    let dirs = [];
    try { dirs = fs.readdirSync(root, { withFileTypes: true }).filter((d) => d.isDirectory()); } catch (_) { continue; }
    for (const d of dirs) {
      // Look for transcript.jsonl under common layout
      const candidates = [
        path.join(root, d.name, '.system_generated', 'logs', 'transcript.jsonl'),
        path.join(root, d.name, 'transcript.jsonl'),
        path.join(root, d.name, 'logs', 'transcript.jsonl'),
      ];
      for (const fp of candidates) {
        let st;
        try { st = fs.statSync(fp); } catch (_) { continue; }
        if (st.mtimeMs < cutoff) continue;
        const ageMin = (nowMs - st.mtimeMs) / 60000;
        out.push({
          sessionId: d.name,
          slug: d.name,
          cwd: root,
          model: 'gemini',
          engine: 'gemini',
          evidenceClass: 'activity',
          usdRecent: 0,
          tokensRecent: 0,
          usdPerMin: 0,
          lastActivityAgoMin: Math.round(ageMin * 10) / 10,
          turns: 0,
        });
        break;
      }
    }
  }
  out.sort((a, b) => a.lastActivityAgoMin - b.lastActivityAgoMin);
  return out;
}

/**
 * OpenAI stub — populate when a host-local trail is provided via opts.openaiSessions
 * or a future ~/.openai layout. Never invent $ or fake zeros as measured.
 * @param {number} [windowMin]
 * @param {number} [nowMs]
 * @param {object} [opts]
 */
function openaiLedger(windowMin = 10, nowMs = Date.now(), opts = {}) {
  if (Array.isArray(opts.openaiSessions)) {
    return opts.openaiSessions.map((s) => ({
      sessionId: s.sessionId || s.id || 'openai',
      slug: s.slug || s.cwd || 'openai',
      cwd: s.cwd || 'openai',
      model: s.model || 'openai',
      engine: 'openai',
      evidenceClass: s.evidenceClass || 'activity',
      usdRecent: Number(s.usdRecent) || 0,
      tokensRecent: Number(s.tokensRecent) || 0,
      usdPerMin: Number(s.usdPerMin) || 0,
      lastActivityAgoMin: Number(s.lastActivityAgoMin) || 0,
      turns: Number(s.turns) || 0,
    }));
  }
  // Default: no local OpenAI trail on this host → empty (not measured $0)
  return [];
}

/**
 * Merge multi-engine sessions with honest totals.
 * usdPerMin / usdRecent = MEASURED only (evidenceClass === 'measured').
 * usdPerMinEstimated / usdRecentEstimated = ESTIMATED (Grok list-price heuristics).
 * usdPerMinAll = measured + estimated (operator burn view; never labeled measured).
 * activeSessions = all engines with recent activity.
 */
function mergeLedgerSessions(sessionLists) {
  const sessions = [];
  for (const list of sessionLists) {
    if (Array.isArray(list)) sessions.push(...list);
  }
  const measured = sessions.filter((s) => s.evidenceClass === 'measured');
  const estimated = sessions.filter((s) => s.evidenceClass === 'estimated');
  const activityOnly = sessions.filter((s) => s.evidenceClass === 'activity');
  const byEngine = {};
  for (const s of sessions) {
    const e = s.engine || 'unknown';
    byEngine[e] = (byEngine[e] || 0) + 1;
  }
  const measuredUsdPerMin = measured.reduce((s, x) => s + (Number(x.usdPerMin) || 0), 0);
  const estimatedUsdPerMin = estimated.reduce((s, x) => s + (Number(x.usdPerMin) || 0), 0);
  const measuredUsdRecent = measured.reduce((s, x) => s + (Number(x.usdRecent) || 0), 0);
  const estimatedUsdRecent = estimated.reduce((s, x) => s + (Number(x.usdRecent) || 0), 0);
  const totals = {
    activeSessions: sessions.length,
    activitySessions: activityOnly.length,
    measuredSessions: measured.length,
    estimatedSessions: estimated.length,
    // Back-compat: usdPerMin stays MEASURED-only so callers do not treat estimates as bills
    usdRecent: measuredUsdRecent,
    usdPerMin: measuredUsdPerMin,
    measuredUsdPerMin,
    measuredUsdRecent,
    usdPerMinEstimated: estimatedUsdPerMin,
    usdRecentEstimated: estimatedUsdRecent,
    // Operator-facing combined burn (measured + estimated)
    usdPerMinAll: measuredUsdPerMin + estimatedUsdPerMin,
    usdRecentAll: measuredUsdRecent + estimatedUsdRecent,
    tokensRecent: sessions.reduce((s, x) => s + (Number(x.tokensRecent) || 0), 0),
    byEngine,
    grokPriceSource: GROK_PRICE_SOURCE,
  };
  // Sort: measured $, then estimated $, then activity; within band by usdPerMin
  const rank = (c) => (c === 'measured' ? 2 : c === 'estimated' ? 1 : 0);
  sessions.sort((a, b) => {
    const dr = rank(b.evidenceClass) - rank(a.evidenceClass);
    if (dr) return dr;
    return (b.usdPerMin || 0) - (a.usdPerMin || 0);
  });
  return { sessions, totals };
}

/**
 * Collect ledger + optional network atlas spend snapshot.
 * @param {number} [windowMin]
 * @param {number} [nowMs]
 * @param {object} [spendOpts] — connections / attribution / forceStale inject for tests
 *                               + claudeRoot / grokHome / geminiHome / openaiSessions
 */
function collectSpend(windowMin = 10, nowMs = Date.now(), spendOpts = {}) {
  const health = assessAtlasHealth(spendOpts);
  const byPid = networkSpend(spendOpts);
  const ledgerOpts = {
    claudeRoot: spendOpts.claudeRoot,
    grokHome: spendOpts.grokHome,
    geminiHome: spendOpts.geminiHome,
    openaiSessions: spendOpts.openaiSessions,
  };
  const claude = claudeLedger(windowMin, nowMs, ledgerOpts);
  const grok = grokLedger(windowMin, nowMs, ledgerOpts);
  const gemini = geminiLedger(windowMin, nowMs, ledgerOpts);
  const openai = openaiLedger(windowMin, nowMs, ledgerOpts);
  const merged = mergeLedgerSessions([claude, grok, gemini, openai]);
  const net = {};
  for (const [pid, v] of byPid) {
    net[pid] = {
      providers: [...(v.providers || [])],
      activityProviders: [...(v.activityProviders || [])],
      count: v.count,
      hosts: v.hosts ? [...v.hosts] : [],
      spendPositive: !!v.spendPositive,
      burnActivity: !!(v.burnActivity || v.spendPositive),
    };
  }
  return {
    net,
    sessions: merged.sessions,
    totals: merged.totals,
    windowMin,
    atlas: {
      version: health.version,
      hash: health.hash,
      contentHash: health.contentHash,
      hostCount: health.hostCount,
      stale: health.stale,
      empty: health.empty,
      reason: health.reason,
      health: health.stale ? 'STALE' : 'OK',
    },
    spendOptsApplied: !!spendOpts && Object.keys(spendOpts).length > 0,
  };
}

/**
 * Spend leg for a pid using collectSpend net + evaluateSpendLeg (production seam).
 * Prefer evaluateSpendLeg with explicit connections for joint-quad tests.
 */
function spendLegForPid(pid, collectResult, subtreePids = [], inject = {}) {
  const net = (collectResult && collectResult.net) || {};
  // If inject provides connections, use evaluateSpendLeg as source of truth
  if (inject.connections || inject.forceStale || inject.attributionUnreadable || inject.atlasEntries) {
    return evaluateSpendLeg({
      pid,
      subtreePids,
      ...inject,
    });
  }
  // From live collectSpend net (atlas-matched + IP activity)
  const providers = new Set();
  const activityProviders = new Set();
  let conns = 0;
  let burnActivity = false;
  const hosts = new Set();
  const allow = new Set([Number(pid), ...subtreePids.map(Number)]);
  for (const p of allow) {
    const e = net[p];
    if (!e) continue;
    conns += e.count || 0;
    for (const pr of e.providers || []) providers.add(pr);
    for (const pr of e.activityProviders || []) activityProviders.add(pr);
    for (const h of e.hosts || []) hosts.add(h);
    if (e.burnActivity || e.spendPositive) burnActivity = true;
  }
  const atlas = (collectResult && collectResult.atlas) || assessAtlasHealth();
  if (atlas.stale) {
    return {
      status: 'SPEND_UNCERTAIN',
      spendPositive: false,
      spendingNow: false,
      burnActivity,
      activityProviders: [...activityProviders],
      activityReason: burnActivity ? 'BURN_ACTIVITY_IP' : null,
      reason: 'SPEND_ATLAS_STALE',
      reasonCodes: ['SPEND_ATLAS_STALE', 'SPEND_UNCERTAIN'].concat(
        burnActivity ? ['BURN_ACTIVITY_IP'] : [],
      ),
      atlasStale: true,
      providers: [],
      hosts: [],
      conns,
      atlas,
    };
  }
  if (providers.size > 0) {
    return {
      status: 'SPEND_POSITIVE',
      spendPositive: true,
      spendingNow: true,
      burnActivity: true,
      activityProviders: [...providers],
      activityReason: 'SPEND_POSITIVE',
      reason: 'SPEND_POSITIVE',
      reasonCodes: ['SPEND_POSITIVE'],
      atlasStale: false,
      providers: [...providers],
      hosts: [...hosts],
      conns,
      atlas,
    };
  }
  return {
    status: 'SPEND_NEGATIVE',
    spendPositive: false,
    spendingNow: false,
    burnActivity,
    activityProviders: [...activityProviders],
    activityReason: burnActivity ? 'BURN_ACTIVITY_IP' : null,
    reason: burnActivity ? 'SPEND_PORT_443_ALONE' : 'SPEND_NEGATIVE',
    reasonCodes: ['SPEND_NEGATIVE'].concat(burnActivity ? ['BURN_ACTIVITY_IP', 'SPEND_PORT_443_ALONE'] : []),
    atlasStale: false,
    providers: [],
    hosts: [...hosts],
    conns,
    atlas,
  };
}

/** Closed seed host list (flat) for fixtures / tests. */
function positiveAtlasHosts() {
  const out = [];
  for (const row of SPEND_ATLAS_POSITIVE) {
    for (const h of row.hosts) out.push(h);
  }
  return out;
}

module.exports = {
  SPEND_ATLAS_VERSION,
  SPEND_ATLAS_HASH,
  SPEND_ATLAS_POSITIVE,
  SPEND_ATLAS_NEGATIVE_NEAR_MISS,
  PROVIDER_PREFIXES,
  normalizeHost,
  isIpLiteral,
  matchSpendAtlasHost,
  assessAtlasHealth,
  computeSpendAtlasHash,
  buildHostProviderMap,
  acquireOwnedConnections,
  evaluateSpendLeg,
  networkSpend,
  providerForIp,
  activityProviderForIp,
  loadDnsClientCacheMap,
  scoreBurnActivity,
  claudeLedger,
  grokLedger,
  geminiLedger,
  openaiLedger,
  mergeLedgerSessions,
  estimateGrokSessionCost,
  grokPriceTier,
  GROK_PRICES,
  GROK_PRICE_SOURCE,
  collectSpend,
  spendLegForPid,
  turnUsd,
  tierFor,
  positiveAtlasHosts,
};

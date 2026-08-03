// Normative interactive-host supervision walk (C1 / W2 + active-session hardening).
//
// Inputs: { pid, ppid, imagePath, createTime, sessionId? } (+ commandLine for Anchor gate).
// Ancestry-only: SUPERVISED | UNSUPERVISED | UNCERTAIN.
// D=32; system-root set R; uncertain never becomes unsupervised.
// Weak-root supervision symbols are banned (must not exist as a live export).
//
// Active-session rule (John 2026-07-23): SUPERVISED only when an allowlisted host
// ancestor is an *active* work session — active VS Code/Cursor, active Anchor,
// active terminal/shell — not a stale/orphaned host image. Inactive shells
// (session 0, job/service parent) do NOT protect token spenders.

const { normalizeImageBasename, matchNormalizedExact } = require('./normalize.js');

/** Max parent hops (inclusive depth cap). Past this → UNCERTAIN. */
const HOST_WALK_MAX_DEPTH = 32;

/** Version pin for host allowlist H (feeds mode.js hostAllowlistHash). */
const HOST_ALLOWLIST_VERSION = 'w2-host-allowlist-v2-active-session';

/**
 * System-root set R — walk complete to R with zero H hits ⇒ UNSUPERVISED.
 * Normalized basenames (no .exe).
 */
const SYSTEM_ROOT_SET_R = Object.freeze(new Set([
  'services',
  'smss',
  'wininit',
  'winlogon',
  'csrss',
  'system',
  'registry',
  'idle',
  'system idle process',
  'secure system',
  'memory compression',
]));

/**
 * Closed host allowlist H (1:1 with North Star interactive hosts).
 * names: normalized exact-match targets; aliases folded via HOST_ALIAS_TABLE.
 */
const HOST_ALLOWLIST_H = Object.freeze([
  Object.freeze({ id: 'code', names: Object.freeze(['code']), fixtureId: 'F-H-CODE' }),
  Object.freeze({
    id: 'code-insiders',
    names: Object.freeze(['code - insiders']),
    fixtureId: 'F-H-CODE-INSIDERS',
  }),
  Object.freeze({ id: 'cursor', names: Object.freeze(['cursor']), fixtureId: 'F-H-CURSOR' }),
  Object.freeze({
    id: 'windowsterminal',
    names: Object.freeze(['windowsterminal', 'wt']),
    fixtureId: 'F-H-WT',
  }),
  Object.freeze({
    id: 'openconsole',
    names: Object.freeze(['openconsole']),
    fixtureId: 'F-H-OPENCONSOLE',
  }),
  Object.freeze({ id: 'conhost', names: Object.freeze(['conhost']), fixtureId: 'F-H-CONHOST-ANC' }),
  Object.freeze({ id: 'grok', names: Object.freeze(['grok']), fixtureId: 'F-H-GROK' }),
  Object.freeze({
    id: 'anchor',
    names: Object.freeze(['anchor', 'anchor_gui']),
    fixtureId: 'F-H-ANCHOR',
    // python/pythonw only when cmdline contains anchor_gui.py
    cmdlineGate: Object.freeze({
      basenames: Object.freeze(['python', 'pythonw']),
      includes: 'anchor_gui.py',
    }),
  }),
  Object.freeze({
    id: 'shell',
    names: Object.freeze(['powershell', 'pwsh', 'cmd']),
    fixtureId: 'F-H-SHELL',
  }),
  Object.freeze({ id: 'explorer', names: Object.freeze(['explorer']), fixtureId: 'F-H-EXPLORER' }),
]);

/**
 * Versioned alias table: normalized alias → canonical allowlist name.
 * Multi-word Insiders and WT launcher residuals only — never substring.
 */
const HOST_ALIAS_TABLE = Object.freeze({
  // VS Code Insiders image strings → canonical multi-word form
  'code - insiders': 'code - insiders',
  // Windows Terminal launcher residual
  wt: 'windowsterminal',
});

/** Near-miss negatives that must NOT match (documentation + tests). */
const HOST_NEAR_MISS_NEGATIVES = Object.freeze([
  'codehelper',
  'code-tunnel',
  'vscodium',
  'cursor-updater',
  'windows terminal', // space variant not in alias table
  'explorer++',
  'pwsh-preview',
  'openconsolehelper',
  'python', // bare python without anchor_gui.py gate
  'pythonw',
]);

/** Flat set of all normalized H names (excluding cmdline-gated-only basenames). */
function buildHostNameSet() {
  const s = new Set();
  for (const row of HOST_ALLOWLIST_H) {
    for (const n of row.names) s.add(normalizeImageBasename(n));
  }
  return s;
}

const HOST_NAME_SET = buildHostNameSet();

/**
 * Match an image (+ optional cmdline) against closed host allowlist H.
 * @param {string} imagePathOrName
 * @param {string} [commandLine]
 * @returns {{ matched: boolean, hostId: string|null, fixtureId: string|null, normalized: string, via: string|null }}
 */
function matchHostAllowlist(imagePathOrName, commandLine = '') {
  const normalized = normalizeImageBasename(imagePathOrName);
  if (!normalized) {
    return { matched: false, hostId: null, fixtureId: null, normalized: '', via: null };
  }

  // Cmdline-gated Anchor: python/pythonw + anchor_gui.py
  const cmd = String(commandLine || '').toLowerCase();
  for (const row of HOST_ALLOWLIST_H) {
    if (!row.cmdlineGate) continue;
    const gateNames = row.cmdlineGate.basenames.map((b) => normalizeImageBasename(b));
    if (gateNames.includes(normalized) && cmd.includes(row.cmdlineGate.includes.toLowerCase())) {
      return {
        matched: true,
        hostId: row.id,
        fixtureId: row.fixtureId,
        normalized,
        via: 'cmdline_gate',
      };
    }
  }

  // Exact name / alias against each row
  for (const row of HOST_ALLOWLIST_H) {
    const rowSet = new Set(row.names.map((n) => normalizeImageBasename(n)));
    const hit = matchNormalizedExact(imagePathOrName, rowSet, HOST_ALIAS_TABLE);
    if (hit.matched) {
      return {
        matched: true,
        hostId: row.id,
        fixtureId: row.fixtureId,
        normalized: hit.normalized,
        via: 'exact',
      };
    }
  }

  // Alias that expands to another row's canonical (e.g. wt → windowsterminal)
  const aliasCanon = HOST_ALIAS_TABLE[normalized];
  if (aliasCanon) {
    const canon = normalizeImageBasename(aliasCanon);
    for (const row of HOST_ALLOWLIST_H) {
      const rowSet = new Set(row.names.map((n) => normalizeImageBasename(n)));
      if (rowSet.has(canon) || rowSet.has(normalized)) {
        return {
          matched: true,
          hostId: row.id,
          fixtureId: row.fixtureId,
          normalized,
          via: 'alias',
        };
      }
    }
  }

  return { matched: false, hostId: null, fixtureId: null, normalized, via: null };
}

function isSystemRoot(imagePathOrName) {
  const n = normalizeImageBasename(imagePathOrName);
  return SYSTEM_ROOT_SET_R.has(n);
}

/**
 * Resolve a process record from a Map/object index by pid.
 * Index values may be probe shape or Win32 enumerate shape.
 * @param {Map|object} byPid
 * @param {number|string} pid
 */
function lookupProc(byPid, pid) {
  if (byPid == null) return null;
  const n = Number(pid);
  if (byPid instanceof Map) {
    return byPid.get(n) || byPid.get(String(pid)) || null;
  }
  return byPid[n] || byPid[String(pid)] || null;
}

/**
 * Normalize a process record to walk fields.
 * Accepts {pid,ppid,imagePath,createTime,commandLine} or Win32-ish fields.
 */
/** Basenames that mark non-interactive job/service parents (shell under these ≠ active terminal). */
const NON_INTERACTIVE_JOB_PARENTS = Object.freeze(new Set([
  'services',
  'svchost',
  'taskeng',
  'taskhostw',
  'taskhost',
  'smss',
  'wininit',
  'system',
  'registry',
  'idle',
  'system idle process',
]));

function toWalkNode(rec) {
  if (!rec || typeof rec !== 'object') return null;
  const pid = Number(rec.pid != null ? rec.pid : rec.ProcessId);
  const ppid = Number(rec.ppid != null ? rec.ppid : rec.ParentProcessId);
  const imagePath = rec.imagePath != null
    ? rec.imagePath
    : (rec.ExecutablePath || rec.path || rec.Name || rec.name || '');
  const name = rec.name != null ? rec.name : (rec.Name || imagePath);
  const createTime = rec.createTime != null
    ? Number(rec.createTime)
    : (rec.CreateTimeMs != null ? Number(rec.CreateTimeMs) : null);
  const commandLine = rec.commandLine != null
    ? rec.commandLine
    : (rec.CommandLine || rec.cmd || '');
  // Win32 SessionId: 0 = services/non-interactive; >0 = user interactive session.
  const rawSid = rec.sessionId != null ? rec.sessionId
    : (rec.SessionId != null ? rec.SessionId : null);
  const sessionId = rawSid == null || rawSid === ''
    ? null
    : Number(rawSid);
  if (!Number.isFinite(pid)) return null;
  return {
    pid,
    ppid: Number.isFinite(ppid) ? ppid : -1,
    imagePath: String(imagePath || name || ''),
    name: String(name || imagePath || ''),
    createTime: createTime != null && Number.isFinite(createTime) ? createTime : null,
    commandLine: String(commandLine || ''),
    sessionId: sessionId != null && Number.isFinite(sessionId) ? sessionId : null,
  };
}

/**
 * Whether a shell host sits only under non-interactive job/service parents
 * (orphaned/scheduled shell — not an active human terminal session).
 * @param {ReturnType<typeof toWalkNode>} hostNode
 * @param {Map|object} byPid
 * @param {number} [maxHops=8]
 */
function isUnderNonInteractiveJobHost(hostNode, byPid, maxHops = 8) {
  if (!hostNode) return false;
  let cur = lookupProc(byPid, hostNode.ppid);
  let hops = 0;
  let sawOnlyJob = true;
  let sawAny = false;
  while (cur && hops < maxHops) {
    const n = toWalkNode(cur);
    if (!n) break;
    sawAny = true;
    const base = normalizeImageBasename(n.imagePath || n.name);
    if (isSystemRoot(n.imagePath || n.name)) break;
    // Interactive co-host on the way up → not a pure job orphan
    const hit = matchHostAllowlist(n.imagePath || n.name, n.commandLine);
    if (hit.matched && hit.hostId !== 'shell') {
      return false;
    }
    if (!NON_INTERACTIVE_JOB_PARENTS.has(base) && hit.hostId !== 'shell') {
      sawOnlyJob = false;
    }
    cur = lookupProc(byPid, n.ppid);
    hops += 1;
  }
  return sawAny && sawOnlyJob;
}

/**
 * Active-session gate for an allowlisted host ancestor.
 * SUPERVISED only when the host represents an *active* work session
 * (active VS Code / Anchor / terminal), not a stale host image.
 *
 * @param {ReturnType<typeof toWalkNode>} hostNode
 * @param {string|null} hostId — from matchHostAllowlist
 * @param {Map|object} byPid
 * @returns {{ active: boolean, reason: string }}
 */
function isHostSessionActive(hostNode, hostId, byPid) {
  if (!hostNode) return { active: false, reason: 'HOST_MISSING' };
  const sid = hostNode.sessionId;

  // Session 0 is the Windows services/non-interactive space.
  if (sid === 0) {
    if (hostId === 'shell') {
      return { active: false, reason: 'HOST_SHELL_SESSION0' };
    }
    // IDE/terminal/Grok/Anchor in session 0 is not an interactive user session.
    return { active: false, reason: 'HOST_SESSION0_NONINTERACTIVE' };
  }

  // Shells: active only if interactive user session OR not a job-orphaned shell.
  if (hostId === 'shell') {
    if (sid != null && sid > 0) {
      return { active: true, reason: 'HOST_SHELL_INTERACTIVE_SESSION' };
    }
    // sessionId missing (fixtures / degraded probe): refuse if under job parents only.
    if (isUnderNonInteractiveJobHost(hostNode, byPid)) {
      return { active: false, reason: 'HOST_SHELL_ORPHAN_JOB' };
    }
    return { active: true, reason: 'HOST_SHELL_DEFAULT_ACTIVE' };
  }

  // VS Code / Cursor / WT / OpenConsole / conhost / explorer / grok / Anchor
  if (sid != null && sid > 0) {
    return { active: true, reason: 'HOST_INTERACTIVE_SESSION' };
  }
  // Missing SessionId: process exists on chain (fixture / older probe) → active default.
  // Production classify.js supplies SessionId from Win32.
  if (sid == null) {
    return { active: true, reason: 'HOST_DEFAULT_ACTIVE' };
  }
  return { active: false, reason: 'HOST_INACTIVE' };
}

/**
 * Sole normative supervision host-walk (ancestry-only).
 *
 * @param {{ pid, ppid, imagePath, createTime, commandLine? }} candidate
 * @param {Map|object} byPid — full tree index
 * @param {{ maxDepth?: number }} [opts]
 * @returns {{
 *   status: 'SUPERVISED'|'UNSUPERVISED'|'UNCERTAIN',
 *   reason: string,
 *   root: string,
 *   hostId: string|null,
 *   fixtureId: string|null,
 *   hops: number,
 *   parentAlive: boolean,
 *   parentName: string,
 *   supervised: boolean,
 *   unsupervised: boolean,
 * }}
 */
function walkHostSupervision(candidate, byPid, opts = {}) {
  const maxDepth = opts.maxDepth != null ? Number(opts.maxDepth) : HOST_WALK_MAX_DEPTH;
  const start = toWalkNode(candidate);
  if (!start) {
    return packResult('UNCERTAIN', 'INVALID_CANDIDATE', '(none)', null, null, 0, false, '<none>');
  }

  const parentRec = lookupProc(byPid, start.ppid);
  if (!parentRec) {
    // Missing parent → fail-closed UNCERTAIN (never unsupervised).
    return packResult(
      'UNCERTAIN',
      'MISSING_PARENT',
      '(none)',
      null,
      null,
      0,
      false,
      '<dead>',
    );
  }

  const parentNode = toWalkNode(parentRec);
  const parentName = parentNode ? parentNode.name : '<dead>';

  let cur = parentNode;
  let prevCreateTime = start.createTime;
  const visited = new Set([start.pid]);
  let hops = 0;

  while (cur && hops < maxDepth) {
    if (visited.has(cur.pid)) {
      return packResult(
        'UNCERTAIN',
        'PPID_CYCLE',
        cur.name || cur.imagePath,
        null,
        null,
        hops,
        true,
        parentName,
      );
    }
    visited.add(cur.pid);

    // createTime inversion: ancestor createTime strictly after descendant → UNCERTAIN
    // (normal Windows trees have parent older than child: ancestor.createTime <= descendant).
    if (
      prevCreateTime != null
      && cur.createTime != null
      && Number.isFinite(prevCreateTime)
      && Number.isFinite(cur.createTime)
      && cur.createTime > prevCreateTime
    ) {
      return packResult(
        'UNCERTAIN',
        'CREATETIME_INVERSION',
        cur.name || cur.imagePath,
        null,
        null,
        hops,
        true,
        parentName,
      );
    }

    const hostHit = matchHostAllowlist(cur.imagePath || cur.name, cur.commandLine);
    if (hostHit.matched) {
      // Active-session hardening: allowlisted image alone is not enough — host must
      // be an *active* VS Code / Anchor / terminal (etc.) session. Inactive shells
      // (session 0, job-orphaned) are skipped so walk can reach true unsupervised.
      const activity = isHostSessionActive(cur, hostHit.hostId, byPid);
      if (activity.active) {
        return packResult(
          'SUPERVISED',
          'HOST_ALLOWLIST_ANCESTOR',
          cur.name || cur.imagePath,
          hostHit.hostId,
          hostHit.fixtureId,
          hops + 1,
          true,
          parentName,
          { hostActive: true, hostActiveReason: activity.reason },
        );
      }
      // Inactive host: do not SUPERVISE; keep walking (stale shell must not KEEP spenders).
      // Fall through to system-root / next parent.
    }

    if (isSystemRoot(cur.imagePath || cur.name)) {
      return packResult(
        'UNSUPERVISED',
        'WALK_COMPLETE_SYSTEM_ROOT',
        cur.name || cur.imagePath,
        null,
        null,
        hops + 1,
        true,
        parentName,
      );
    }

    prevCreateTime = cur.createTime != null ? cur.createTime : prevCreateTime;
    const nextRec = lookupProc(byPid, cur.ppid);
    if (!nextRec) {
      // Chain broke before R and before H → UNCERTAIN
      return packResult(
        'UNCERTAIN',
        'MISSING_ANCESTOR',
        cur.name || cur.imagePath,
        null,
        null,
        hops + 1,
        true,
        parentName,
      );
    }

    const nextNode = toWalkNode(nextRec);
    // Self-ppid / trivial cycle
    if (nextNode && nextNode.pid === cur.pid) {
      return packResult(
        'UNCERTAIN',
        'PPID_CYCLE',
        cur.name || cur.imagePath,
        null,
        null,
        hops + 1,
        true,
        parentName,
      );
    }
    cur = nextNode;
    hops += 1;
  }

  // Depth truncation past D without H or R
  return packResult(
    'UNCERTAIN',
    'DEPTH_TRUNCATION',
    cur ? (cur.name || cur.imagePath) : '(truncated)',
    null,
    null,
    hops,
    true,
    parentName,
  );
}

function packResult(status, reason, root, hostId, fixtureId, hops, parentAlive, parentName, extra = {}) {
  return {
    status,
    reason,
    root: String(root || '(none)'),
    hostId: hostId || null,
    fixtureId: fixtureId || null,
    hops,
    parentAlive: !!parentAlive,
    parentName: String(parentName || '<none>'),
    supervised: status === 'SUPERVISED',
    unsupervised: status === 'UNSUPERVISED',
    hostActive: extra.hostActive != null ? !!extra.hostActive : (status === 'SUPERVISED'),
    hostActiveReason: extra.hostActiveReason || null,
  };
}

/**
 * Build a pid→record Map from an array of walk nodes / Win32 rows.
 * @param {Array<object>} processes
 * @returns {Map<number, object>}
 */
function indexProcessesByPid(processes) {
  const m = new Map();
  for (const p of processes || []) {
    const n = toWalkNode(p);
    if (n) {
      // Preserve original fields + normalized walk fields
      m.set(n.pid, {
        ...p,
        pid: n.pid,
        ppid: n.ppid,
        imagePath: n.imagePath,
        name: n.name,
        createTime: n.createTime,
        commandLine: n.commandLine,
        sessionId: n.sessionId,
        ProcessId: n.pid,
        ParentProcessId: n.ppid,
        Name: n.name,
        ExecutablePath: n.imagePath,
        CommandLine: n.commandLine,
        CreateTimeMs: n.createTime,
        SessionId: n.sessionId,
      });
    }
  }
  return m;
}

module.exports = {
  HOST_WALK_MAX_DEPTH,
  HOST_ALLOWLIST_VERSION,
  SYSTEM_ROOT_SET_R,
  HOST_ALLOWLIST_H,
  HOST_ALIAS_TABLE,
  HOST_NEAR_MISS_NEGATIVES,
  HOST_NAME_SET,
  NON_INTERACTIVE_JOB_PARENTS,
  matchHostAllowlist,
  isSystemRoot,
  isHostSessionActive,
  isUnderNonInteractiveJobHost,
  walkHostSupervision,
  indexProcessesByPid,
  toWalkNode,
  normalizeImageBasename,
  matchNormalizedExact,
};

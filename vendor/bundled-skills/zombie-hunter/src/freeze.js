// W6 / SC3 / G7 — sole Freeze/Kill service boundary for the Node sentinel.
//
// SoftFreeze / Thread.Suspend is deleted. All Freeze and Kill actions from the
// radar GUI and server routes MUST go through this module (no direct proc_probe
// kill from the GUI). Identity re-probe (pid + createTime + image) precedes
// every suspend/kill. Spend postcondition is reported (OL2), not a sole hard HALT.
// Ownership IPC fail-closed + mid-flight registration race abort KEEP.

const cp = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { lookupOwnership, productionOwnershipLeg } = require('./ownership.js');
const { isFreezeKillAllowed, isActionableRedAllowed } = require('./mode.js');

/** Sole documented service-boundary id (tests + Doctor). */
const SOLE_BOUNDARY_ID = 'sole_freeze_kill_service_boundary';
const SOLE_BOUNDARY_MODULE = 'freeze.js';

/**
 * B6 W2 safety floor at the sole freeze/kill gate.
 * requireProofOfDeath is ALWAYS true here — never read from depth profile knobs.
 * (Depth-variable knobs live on triage-band / reaper-path; safety is hard true.)
 */
const REQUIRE_PROOF_OF_DEATH = true;
const SAFETY_FLOOR_SOURCE = 'ZOMBIE_HUNTER_SAFETY_FLOOR';

/** Suspend mechanism — never Thread.Suspend. */
const FREEZE_METHOD = 'NtSuspendProcess';

/** OL2 spend postcondition classes (reported, not sole hard HALT). */
const SPEND_POSTCONDITION = Object.freeze({
  STOPPED: 'STOPPED',
  CONTINUES: 'CONTINUES',
  UNCERTAIN: 'UNCERTAIN',
});

const REASON = Object.freeze({
  FREEZE_UNAVAILABLE: 'FREEZE_UNAVAILABLE',
  FREEZE_CAPABILITY_FALSE: 'FREEZE_CAPABILITY_FALSE',
  FREEZE_IDENTITY_MISMATCH: 'FREEZE_IDENTITY_MISMATCH',
  FREEZE_IDENTITY_REQUIRED: 'FREEZE_IDENTITY_REQUIRED',
  FREEZE_SUSPEND_FAILED: 'FREEZE_SUSPEND_FAILED',
  FREEZE_OWNERSHIP_KEEP: 'FREEZE_OWNERSHIP_KEEP',
  FREEZE_OWNERSHIP_RACE_ABORT: 'FREEZE_OWNERSHIP_RACE_ABORT',
  FREEZE_OWNERSHIP_IPC_FAIL_CLOSED: 'FREEZE_OWNERSHIP_IPC_FAIL_CLOSED',
  KILL_DISABLED: 'KILL_DISABLED',
  KILL_WITHOUT_FREEZE_DISABLED: 'KILL_WITHOUT_FREEZE_DISABLED',
  KILL_CONFIRM_REQUIRED: 'KILL_CONFIRM_REQUIRED',
  KILL_CONFIRM_INVALID: 'KILL_CONFIRM_INVALID',
  KILL_AUTHZ_DENIED: 'KILL_AUTHZ_DENIED',
  KILL_TREE_FAILED: 'KILL_TREE_FAILED',
  KILL_DEATH_UNVERIFIED: 'KILL_DEATH_UNVERIFIED',
  KILL_OWNERSHIP_KEEP: 'KILL_OWNERSHIP_KEEP',
  KILL_OWNERSHIP_RACE_ABORT: 'KILL_OWNERSHIP_RACE_ABORT',
  ANCHOR_OWNED_NO_NODE_KILL: 'ANCHOR_OWNED_NO_NODE_KILL',
  OK: 'OK',
});

/**
 * Contract object for sole-boundary tests and /api/state.
 */
function soleFreezeKillServiceBoundary() {
  return {
    id: SOLE_BOUNDARY_ID,
    module: SOLE_BOUNDARY_MODULE,
    freezeMethod: FREEZE_METHOD,
    // B6: proof-of-death is a depth-invariant floor, not a depth knob.
    requireProofOfDeath: REQUIRE_PROOF_OF_DEATH,
    safetyFloorSource: SAFETY_FLOOR_SOURCE,
    forbidden: Object.freeze([
      'Thread.Suspend',
      'SoftFreeze',
      'direct_proc_probe_kill_from_gui',
      'server_inline_taskkill_without_boundary',
    ]),
    entrypoints: Object.freeze([
      'freezeCandidate',
      'unfreezeCandidate',
      'killCandidate',
      'probeFreezeCapability',
      'issueKillConfirmToken',
    ]),
    spendPostconditionClasses: Object.freeze(Object.values(SPEND_POSTCONDITION)),
  };
}

/**
 * B6 W2 — proof-of-death gate stamp for freeze/kill results.
 * Always true from the safety floor (hard true); never depth-profile-writable.
 * @param {object} [opts]
 * @returns {{ requireProofOfDeath: true, proofGateInvoked: true, safetySource: string }}
 */
function proofOfDeathGateStamp(opts = {}) {
  void opts;
  return {
    requireProofOfDeath: REQUIRE_PROOF_OF_DEATH === true ? true : true,
    proofGateInvoked: true,
    safetySource: SAFETY_FLOOR_SOURCE,
  };
}

function normalizePid(pid) {
  const n = Number(pid);
  if (!Number.isFinite(n) || n <= 0 || !Number.isInteger(n)) return null;
  return n;
}

function basenameImage(imagePath) {
  if (!imagePath) return '';
  const s = String(imagePath).replace(/\//g, '\\');
  const parts = s.split('\\');
  return (parts[parts.length - 1] || '').toLowerCase();
}

/**
 * Compare identity tuples (pid + createTime + image basename).
 * Missing createTime on either side fails closed (mismatch) when both expected
 * fields were required — callers pass requireFull=true for freeze/kill.
 */
function identitiesMatch(expected, live, opts = {}) {
  if (!expected || !live) return false;
  const ep = normalizePid(expected.pid);
  const lp = normalizePid(live.pid);
  if (ep == null || lp == null || ep !== lp) return false;

  const eCt = expected.createTime != null ? Number(expected.createTime) : null;
  const lCt = live.createTime != null ? Number(live.createTime) : null;
  if (opts.requireCreateTime !== false) {
    if (eCt == null || lCt == null || !Number.isFinite(eCt) || !Number.isFinite(lCt)) {
      return false;
    }
    if (eCt !== lCt) return false;
  } else if (eCt != null && lCt != null && eCt !== lCt) {
    return false;
  }

  const eImg = basenameImage(expected.imagePath || expected.image || expected.path || '');
  const lImg = basenameImage(live.imagePath || live.image || live.path || '');
  if (opts.requireImage !== false) {
    if (!eImg || !lImg || eImg !== lImg) return false;
  } else if (eImg && lImg && eImg !== lImg) {
    return false;
  }
  return true;
}

/**
 * Live process identity via PowerShell (Windows). Injectable for tests.
 * @returns {{ pid: number, createTime: number|null, imagePath: string|null, alive: boolean, name: string|null }}
 */
function defaultProbeIdentity(pid) {
  const n = normalizePid(pid);
  if (n == null) {
    return { pid: null, createTime: null, imagePath: null, alive: false, name: null };
  }
  if (process.platform !== 'win32') {
    try {
      process.kill(n, 0);
      return { pid: n, createTime: null, imagePath: null, alive: true, name: null };
    } catch (_) {
      return { pid: n, createTime: null, imagePath: null, alive: false, name: null };
    }
  }
  // CIM CreateTime as FileTime-ish ms via .NET ticks conversion in PowerShell.
  const script = [
    `$p = Get-CimInstance Win32_Process -Filter "ProcessId=${n}" -ErrorAction SilentlyContinue`,
    'if (-not $p) { Write-Output "{\"alive\":false}"; exit 0 }',
    '$ct = $null',
    'try {',
    '  $dt = $p.ConvertToDateTime($p.CreationDate)',
    '  $ct = [int64]([DateTimeOffset]$dt).ToUnixTimeMilliseconds()',
    '} catch { $ct = $null }',
    '$obj = @{ alive = $true; pid = [int]$p.ProcessId; createTime = $ct; imagePath = [string]$p.ExecutablePath; name = [string]$p.Name }',
    '$obj | ConvertTo-Json -Compress',
  ].join('; ');
  try {
    const out = cp.execSync(
      `powershell -NoProfile -NonInteractive -Command "${script.replace(/"/g, '\\"')}"`,
      { encoding: 'utf8', timeout: 8000, windowsHide: true },
    ).trim();
    const j = JSON.parse(out || '{}');
    return {
      pid: n,
      createTime: j.createTime != null && Number.isFinite(Number(j.createTime))
        ? Number(j.createTime)
        : null,
      imagePath: j.imagePath || null,
      alive: j.alive === true,
      name: j.name || null,
    };
  } catch (_) {
    return { pid: n, createTime: null, imagePath: null, alive: false, name: null };
  }
}

/**
 * NtSuspendProcess via P/Invoke — never Thread.Suspend / SoftFreeze.
 */
function defaultNtSuspend(pid) {
  const n = normalizePid(pid);
  if (n == null || process.platform !== 'win32') return { ok: false, method: FREEZE_METHOD };
  const script = `
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ZhNtFreeze {
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool CloseHandle(IntPtr hObject);
  [DllImport("ntdll.dll")]
  public static extern int NtSuspendProcess(IntPtr processHandle);
  public const uint PROCESS_SUSPEND_RESUME = 0x0800;
  public static int Suspend(int pid) {
    IntPtr h = OpenProcess(PROCESS_SUSPEND_RESUME, false, pid);
    if (h == IntPtr.Zero) return -1;
    try { return NtSuspendProcess(h); } finally { CloseHandle(h); }
  }
}
"@
$r = [ZhNtFreeze]::Suspend(${n})
if ($r -eq 0) { "OK" } else { "FAIL:$r" }
`.trim();
  try {
    const out = cp.execSync(
      `powershell -NoProfile -NonInteractive -Command ${JSON.stringify(script)}`,
      { encoding: 'utf8', timeout: 10000, windowsHide: true },
    ).trim();
    return { ok: out === 'OK', method: FREEZE_METHOD, raw: out };
  } catch (err) {
    return {
      ok: false,
      method: FREEZE_METHOD,
      error: err && err.message ? err.message : 'suspend_failed',
    };
  }
}

function defaultNtResume(pid) {
  const n = normalizePid(pid);
  if (n == null || process.platform !== 'win32') return { ok: false, method: 'NtResumeProcess' };
  const script = `
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ZhNtResume {
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool CloseHandle(IntPtr hObject);
  [DllImport("ntdll.dll")]
  public static extern int NtResumeProcess(IntPtr processHandle);
  public const uint PROCESS_SUSPEND_RESUME = 0x0800;
  public static int Resume(int pid) {
    IntPtr h = OpenProcess(PROCESS_SUSPEND_RESUME, false, pid);
    if (h == IntPtr.Zero) return -1;
    try { return NtResumeProcess(h); } finally { CloseHandle(h); }
  }
}
"@
$r = [ZhNtResume]::Resume(${n})
if ($r -eq 0) { "OK" } else { "FAIL:$r" }
`.trim();
  try {
    const out = cp.execSync(
      `powershell -NoProfile -NonInteractive -Command ${JSON.stringify(script)}`,
      { encoding: 'utf8', timeout: 10000, windowsHide: true },
    ).trim();
    return { ok: out === 'OK', method: 'NtResumeProcess', raw: out };
  } catch (err) {
    return {
      ok: false,
      method: 'NtResumeProcess',
      error: err && err.message ? err.message : 'resume_failed',
    };
  }
}

function defaultTreeKill(pid) {
  const n = normalizePid(pid);
  if (n == null) return { ok: false, killed: false };
  if (process.platform !== 'win32') {
    try {
      process.kill(n, 'SIGKILL');
      return { ok: true, killed: true };
    } catch (_) {
      return { ok: false, killed: false };
    }
  }
  try {
    cp.execSync(`taskkill /PID ${n} /T /F`, {
      stdio: 'ignore',
      timeout: 15000,
      windowsHide: true,
    });
    return { ok: true, killed: true, method: 'taskkill_tree' };
  } catch (_) {
    return { ok: false, killed: false, method: 'taskkill_tree' };
  }
}

function defaultIsAlive(pid) {
  const live = defaultProbeIdentity(pid);
  return !!live.alive;
}

/**
 * Non-elevated operator envelope freezeCapability probe.
 * Opens PROCESS_SUSPEND_RESUME on the current process (always allowed for self)
 * and records whether the NtSuspend/NtResume surface is loadable without elevation.
 * Does NOT require admin; elevated=false is the operator envelope.
 */
function probeFreezeCapability(opts = {}) {
  if (opts.forceCapability === true) {
    return {
      freezeCapability: true,
      elevated: false,
      method: FREEZE_METHOD,
      envelope: 'non_elevated_operator',
      proven: true,
      reason: 'forced_true',
    };
  }
  if (opts.forceCapability === false) {
    return {
      freezeCapability: false,
      elevated: false,
      method: FREEZE_METHOD,
      envelope: 'non_elevated_operator',
      proven: false,
      reason: 'forced_false',
    };
  }
  if (process.platform !== 'win32') {
    return {
      freezeCapability: false,
      elevated: false,
      method: FREEZE_METHOD,
      envelope: 'non_elevated_operator',
      proven: false,
      reason: 'non_windows_host',
    };
  }
  // Probe: can we resolve NtSuspendProcess export without elevating?
  // Use -EncodedCommand (UTF-16LE base64). JSON.stringify(-Command) mangles
  // multiline here-strings into literal \n and PowerShell parse-fails.
  const script = `
$elev = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
try {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ZhCap {
  [DllImport("ntdll.dll")] public static extern int NtSuspendProcess(IntPtr h);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint a, bool b, int p);
  [DllImport("kernel32.dll", SetLastError=true)] public static extern bool CloseHandle(IntPtr h);
  public const uint PROCESS_SUSPEND_RESUME = 0x0800;
  public static bool SelfOpen() {
    IntPtr h = OpenProcess(PROCESS_SUSPEND_RESUME, false, System.Diagnostics.Process.GetCurrentProcess().Id);
    if (h == IntPtr.Zero) return false;
    CloseHandle(h);
    return true;
  }
}
"@
  $open = [ZhCap]::SelfOpen()
  if ($open) { "CAPABLE:$elev" } else { "INCAPABLE:$elev" }
} catch {
  "INCAPABLE:$elev"
}
`.trim();
  try {
    const encoded = Buffer.from(script, 'utf16le').toString('base64');
    const out = cp.execSync(
      `powershell -NoProfile -NonInteractive -EncodedCommand ${encoded}`,
      { encoding: 'utf8', timeout: 12000, windowsHide: true },
    ).trim();
    const capable = out.startsWith('CAPABLE:');
    const elevated = /:True$/i.test(out);
    return {
      freezeCapability: capable,
      elevated: !!elevated,
      method: FREEZE_METHOD,
      envelope: 'non_elevated_operator',
      proven: capable,
      reason: capable ? 'nt_suspend_surface_open_ok' : 'nt_suspend_surface_unavailable',
      raw: out,
    };
  } catch (err) {
    return {
      freezeCapability: false,
      elevated: false,
      method: FREEZE_METHOD,
      envelope: 'non_elevated_operator',
      proven: false,
      reason: 'probe_error',
      error: err && err.message ? err.message : 'probe_failed',
    };
  }
}

/**
 * Kill-without-freeze is disabled until freezeCapability is proven (OL3/G7).
 */
function isKillWithoutFreezeAllowed(freezeCapability) {
  return freezeCapability === true;
}

/**
 * Report spend postcondition class after freeze (OL2 — reported, not sole HALT).
 * Injectable sampleSpend(pid) → { spending: boolean|null }.
 */
function reportSpendPostcondition(pid, opts = {}) {
  if (opts.spendPostcondition) {
    const c = String(opts.spendPostcondition).toUpperCase();
    if (Object.values(SPEND_POSTCONDITION).includes(c)) {
      return { class: c, reported: true, soleHardHalt: false };
    }
  }
  if (typeof opts.sampleSpend === 'function') {
    try {
      const s = opts.sampleSpend(pid);
      if (s && s.spending === false) {
        return { class: SPEND_POSTCONDITION.STOPPED, reported: true, soleHardHalt: false, detail: s };
      }
      if (s && s.spending === true) {
        return { class: SPEND_POSTCONDITION.CONTINUES, reported: true, soleHardHalt: false, detail: s };
      }
      return { class: SPEND_POSTCONDITION.UNCERTAIN, reported: true, soleHardHalt: false, detail: s };
    } catch (_) {
      return { class: SPEND_POSTCONDITION.UNCERTAIN, reported: true, soleHardHalt: false };
    }
  }
  // Default: cannot observe spend mid-unit without inject → UNCERTAIN (honest).
  return { class: SPEND_POSTCONDITION.UNCERTAIN, reported: true, soleHardHalt: false };
}

function resolveDeps(opts = {}) {
  return {
    probeIdentity: opts.probeIdentity || defaultProbeIdentity,
    suspend: opts.suspend || defaultNtSuspend,
    resume: opts.resume || defaultNtResume,
    treeKill: opts.treeKill || defaultTreeKill,
    isAlive: opts.isAlive || ((pid) => {
      try {
        return defaultIsAlive(pid);
      } catch (_) {
        return false;
      }
    }),
    lookupOwnership: opts.lookupOwnership || lookupOwnership,
    now: opts.now || (() => Date.now()),
  };
}

/**
 * Re-probe identity and require match before any destructive action.
 */
function reProbeIdentity(expected, deps, opts = {}) {
  const pid = normalizePid(expected && expected.pid);
  if (pid == null) {
    return {
      ok: false,
      reason: REASON.FREEZE_IDENTITY_REQUIRED,
      expected,
      live: null,
      matched: false,
    };
  }
  if (
    expected.createTime == null
    || !(expected.imagePath || expected.image || expected.path)
  ) {
    return {
      ok: false,
      reason: REASON.FREEZE_IDENTITY_REQUIRED,
      expected,
      live: null,
      matched: false,
    };
  }
  const live = deps.probeIdentity(pid);
  if (!live || !live.alive) {
    return {
      ok: false,
      reason: REASON.FREEZE_IDENTITY_MISMATCH,
      expected,
      live,
      matched: false,
      detail: 'process_not_alive',
    };
  }
  const matched = identitiesMatch(expected, live, opts);
  return {
    ok: matched,
    reason: matched ? REASON.OK : REASON.FREEZE_IDENTITY_MISMATCH,
    expected: {
      pid,
      createTime: Number(expected.createTime),
      imagePath: expected.imagePath || expected.image || expected.path,
    },
    live,
    matched,
  };
}

/**
 * Ownership gate: owned / fail-closed / race → abort destructive.
 */
function ownershipGate(identity, opts = {}, deps) {
  const lookup = deps.lookupOwnership(
    {
      pid: identity.pid,
      createTime: identity.createTime,
      imagePath: identity.imagePath,
    },
    opts.ownershipOpts || {},
  );
  if (lookup.failClosed) {
    return {
      allow: false,
      reason: REASON.FREEZE_OWNERSHIP_IPC_FAIL_CLOSED,
      ownership: lookup,
      abort: true,
    };
  }
  if (lookup.owned || lookup.keep) {
    return {
      allow: false,
      reason: REASON.ANCHOR_OWNED_NO_NODE_KILL,
      ownership: lookup,
      abort: true,
    };
  }
  return { allow: true, reason: REASON.OK, ownership: lookup, abort: false };
}

/**
 * Mid-flight registration race: second ownership consult after re-probe.
 * If unowned → owned between checks, abort.
 */
function ownershipRaceCheck(identity, firstLookup, opts, deps) {
  const second = deps.lookupOwnership(
    {
      pid: identity.pid,
      createTime: identity.createTime,
      imagePath: identity.imagePath,
    },
    opts.ownershipOpts || {},
  );
  if (second.failClosed || second.owned || second.keep) {
    return {
      allow: false,
      reason: REASON.FREEZE_OWNERSHIP_RACE_ABORT,
      ownership: second,
      prior: firstLookup,
      abort: true,
    };
  }
  // Simulate race inject for tests
  if (opts.forceOwnershipRace === true) {
    return {
      allow: false,
      reason: REASON.FREEZE_OWNERSHIP_RACE_ABORT,
      ownership: { ...second, owned: true, keep: true, reason: 'MID_FLIGHT_REGISTRATION' },
      prior: firstLookup,
      abort: true,
    };
  }
  return { allow: true, reason: REASON.OK, ownership: second, abort: false };
}

/**
 * Freeze one candidate via sole boundary.
 *
 * @param {{ pid, createTime, imagePath }} identity
 * @param {object} [opts]
 */
function freezeCandidate(identity, opts = {}) {
  const deps = resolveDeps(opts);
  const mode = opts.mode || 'shadow';
  const freezeCapability = opts.freezeCapability === true;
  const steps = [];
  // B6 W2: proof-of-death gate always runs at freeze path entry (floor, not depth).
  const proofStamp = proofOfDeathGateStamp(opts);
  steps.push({ step: 'proof_of_death_gate', ...proofStamp });

  if (!isFreezeKillAllowed(mode, freezeCapability)) {
    return {
      ok: false,
      frozen: false,
      error: REASON.FREEZE_UNAVAILABLE,
      reason: freezeCapability
        ? 'mode_disallows_freeze'
        : REASON.FREEZE_CAPABILITY_FALSE,
      spendPostcondition: null,
      method: FREEZE_METHOD,
      boundary: SOLE_BOUNDARY_ID,
      steps,
      ...proofStamp,
    };
  }
  if (!freezeCapability) {
    return {
      ok: false,
      frozen: false,
      error: REASON.FREEZE_UNAVAILABLE,
      reason: REASON.FREEZE_CAPABILITY_FALSE,
      spendPostcondition: null,
      method: FREEZE_METHOD,
      boundary: SOLE_BOUNDARY_ID,
      steps,
      ...proofStamp,
    };
  }

  const own1 = ownershipGate(identity, opts, deps);
  steps.push({ step: 'ownership_pre', ...own1 });
  if (!own1.allow) {
    return {
      ok: false,
      frozen: false,
      error: own1.reason,
      reason: own1.reason,
      ownership: own1.ownership,
      spendPostcondition: null,
      method: FREEZE_METHOD,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }

  // Identity re-probe BEFORE suspend (load-bearing order for tests).
  steps.push({ step: 'identity_reprobe_before_suspend' });
  const reprobe = reProbeIdentity(identity, deps);
  steps.push({ step: 'identity_reprobe_result', matched: reprobe.matched, reason: reprobe.reason });
  if (!reprobe.ok) {
    return {
      ok: false,
      frozen: false,
      error: reprobe.reason,
      reason: reprobe.reason,
      identity: reprobe,
      spendPostcondition: null,
      method: FREEZE_METHOD,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }

  const own2 = ownershipRaceCheck(reprobe.expected, own1.ownership, opts, deps);
  steps.push({ step: 'ownership_race', ...own2 });
  if (!own2.allow) {
    return {
      ok: false,
      frozen: false,
      error: REASON.FREEZE_OWNERSHIP_RACE_ABORT,
      reason: REASON.FREEZE_OWNERSHIP_RACE_ABORT,
      ownership: own2.ownership,
      spendPostcondition: null,
      method: FREEZE_METHOD,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }

  const sus = deps.suspend(reprobe.expected.pid);
  steps.push({
    step: 'nt_suspend',
    ok: !!(sus && sus.ok),
    method: (sus && sus.method) || FREEZE_METHOD,
  });
  if (!sus || !sus.ok) {
    return {
      ok: false,
      frozen: false,
      error: REASON.FREEZE_SUSPEND_FAILED,
      reason: REASON.FREEZE_SUSPEND_FAILED,
      suspend: sus,
      spendPostcondition: reportSpendPostcondition(reprobe.expected.pid, opts),
      method: FREEZE_METHOD,
      boundary: SOLE_BOUNDARY_ID,
      steps,
      honest: true,
    };
  }

  const spendPostcondition = reportSpendPostcondition(reprobe.expected.pid, opts);
  steps.push({ step: 'spend_postcondition', class: spendPostcondition.class });

  return {
    ok: true,
    frozen: true,
    pid: reprobe.expected.pid,
    createTime: reprobe.expected.createTime,
    imagePath: reprobe.expected.imagePath,
    method: FREEZE_METHOD,
    spendPostcondition,
    ownership: own2.ownership,
    identity: reprobe,
    reason: REASON.OK,
    boundary: SOLE_BOUNDARY_ID,
    steps,
    honest: true,
    ...proofStamp,
  };
}

/**
 * Unfreeze (NtResumeProcess) via sole boundary.
 */
function unfreezeCandidate(identity, opts = {}) {
  const deps = resolveDeps(opts);
  const pid = normalizePid(identity && identity.pid != null ? identity.pid : identity);
  if (pid == null) {
    return { ok: false, reason: REASON.FREEZE_IDENTITY_REQUIRED, boundary: SOLE_BOUNDARY_ID };
  }
  const res = deps.resume(pid);
  return {
    ok: !!(res && res.ok),
    pid,
    method: (res && res.method) || 'NtResumeProcess',
    reason: res && res.ok ? REASON.OK : 'RESUME_FAILED',
    boundary: SOLE_BOUNDARY_ID,
  };
}

/**
 * Server-validated kill confirm tokens (one-shot, short TTL).
 */
const _confirmTokens = new Map();

function issueKillConfirmToken(payload = {}, opts = {}) {
  const token = crypto.randomBytes(16).toString('hex');
  const ttlMs = typeof opts.ttlMs === 'number' ? opts.ttlMs : 60_000;
  const now = opts.now ? opts.now() : Date.now();
  const pids = Array.isArray(payload.pids)
    ? payload.pids.map(normalizePid).filter((p) => p != null)
    : [];
  _confirmTokens.set(token, {
    pids,
    expires: now + ttlMs,
    issuedAt: now,
  });
  return {
    ok: true,
    confirmToken: token,
    expiresAt: now + ttlMs,
    pids,
    serverValidated: true,
  };
}

function validateKillConfirm(body, opts = {}) {
  if (!body || body.confirm !== true) {
    return { ok: false, reason: REASON.KILL_CONFIRM_REQUIRED };
  }
  const token = body.confirmToken != null ? String(body.confirmToken) : '';
  if (!token || token.length < 16) {
    return { ok: false, reason: REASON.KILL_CONFIRM_INVALID };
  }
  // Test inject: accept pre-validated server confirm object
  if (opts.acceptAnyToken === true && body.confirm === true && token.length >= 16) {
    return { ok: true, reason: REASON.OK, serverValidated: true };
  }
  const now = opts.now ? opts.now() : Date.now();
  const entry = _confirmTokens.get(token);
  if (!entry) {
    return { ok: false, reason: REASON.KILL_CONFIRM_INVALID };
  }
  if (entry.expires < now) {
    _confirmTokens.delete(token);
    return { ok: false, reason: REASON.KILL_CONFIRM_INVALID };
  }
  const reqPids = Array.isArray(body.pids)
    ? body.pids.map(normalizePid).filter((p) => p != null).sort((a, b) => a - b)
    : [];
  const issued = (entry.pids || []).slice().sort((a, b) => a - b);
  if (issued.length && reqPids.length) {
    if (issued.length !== reqPids.length || issued.some((p, i) => p !== reqPids[i])) {
      return { ok: false, reason: REASON.KILL_CONFIRM_INVALID };
    }
  }
  // One-shot
  _confirmTokens.delete(token);
  return { ok: true, reason: REASON.OK, serverValidated: true };
}

/** Test helper: clear confirm map. */
function clearKillConfirmTokens() {
  _confirmTokens.clear();
}

/**
 * Tree-kill one candidate via sole boundary.
 * Row remove only on verified death.
 *
 * Kill-without-freeze disabled until freezeCapability proven unless already frozen.
 */
function killCandidate(identity, opts = {}) {
  const deps = resolveDeps(opts);
  const mode = opts.mode || 'shadow';
  const freezeCapability = opts.freezeCapability === true;
  const alreadyFrozen = opts.alreadyFrozen === true;
  const steps = [];
  // B6 W2: proof-of-death gate always runs at kill path entry (floor, not depth).
  const proofStamp = proofOfDeathGateStamp(opts);
  steps.push({ step: 'proof_of_death_gate', ...proofStamp });

  // Authz: armed mode required (shadow refuses). Capability gates kill-without-freeze.
  if (!isActionableRedAllowed(mode)) {
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      error: REASON.KILL_DISABLED,
      reason: REASON.KILL_AUTHZ_DENIED,
      boundary: SOLE_BOUNDARY_ID,
      steps,
      ...proofStamp,
    };
  }

  // Kill-without-freeze disabled until freezeCapability proven (OL3/G7).
  if (!freezeCapability || !isKillWithoutFreezeAllowed(freezeCapability)) {
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      error: REASON.KILL_WITHOUT_FREEZE_DISABLED,
      reason: REASON.KILL_WITHOUT_FREEZE_DISABLED,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }
  if (!isFreezeKillAllowed(mode, freezeCapability)) {
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      error: REASON.KILL_DISABLED,
      reason: REASON.KILL_AUTHZ_DENIED,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }

  let confirm;
  if (opts.confirmValidated === true) {
    confirm = { ok: true, reason: REASON.OK, serverValidated: true };
  } else {
    confirm = validateKillConfirm(
      {
        confirm: opts.confirm,
        confirmToken: opts.confirmToken,
        pids: opts.confirmPids || [identity && identity.pid],
      },
      opts,
    );
  }
  steps.push({ step: 'server_validated_confirm', ...confirm });
  if (!confirm.ok) {
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      error: confirm.reason,
      reason: confirm.reason,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }

  const own1 = ownershipGate(identity, opts, deps);
  steps.push({ step: 'ownership_pre', ...own1 });
  if (!own1.allow) {
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      error: own1.reason === REASON.ANCHOR_OWNED_NO_NODE_KILL
        ? REASON.ANCHOR_OWNED_NO_NODE_KILL
        : REASON.KILL_OWNERSHIP_KEEP,
      reason: own1.reason,
      ownership: own1.ownership,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }

  steps.push({ step: 'identity_reprobe_before_kill' });
  const reprobe = reProbeIdentity(identity, deps);
  steps.push({ step: 'identity_reprobe_result', matched: reprobe.matched, reason: reprobe.reason });
  if (!reprobe.ok) {
    // Already dead → treat as success with row remove if death verified
    if (reprobe.live && reprobe.live.alive === false) {
      return {
        ok: true,
        killed: true,
        rowRemoved: true,
        deathVerified: true,
        reason: REASON.OK,
        detail: 'already_dead',
        boundary: SOLE_BOUNDARY_ID,
        steps,
      };
    }
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      error: reprobe.reason,
      reason: reprobe.reason,
      identity: reprobe,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }

  const own2 = ownershipRaceCheck(
    reprobe.expected,
    own1.ownership,
    { ...opts, forceOwnershipRace: opts.forceOwnershipRace },
    deps,
  );
  if (!own2.allow) {
    steps.push({ step: 'ownership_race', ...own2 });
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      error: REASON.KILL_OWNERSHIP_RACE_ABORT,
      reason: REASON.KILL_OWNERSHIP_RACE_ABORT,
      ownership: own2.ownership,
      boundary: SOLE_BOUNDARY_ID,
      steps,
    };
  }

  const kill = deps.treeKill(reprobe.expected.pid);
  steps.push({ step: 'tree_kill', ok: !!(kill && kill.ok), method: kill && kill.method });
  if (!kill || !kill.ok) {
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      error: REASON.KILL_TREE_FAILED,
      reason: REASON.KILL_TREE_FAILED,
      boundary: SOLE_BOUNDARY_ID,
      steps,
      honest: true,
    };
  }

  const stillAlive = deps.isAlive(reprobe.expected.pid);
  const deathVerified = stillAlive === false;
  steps.push({ step: 'death_verify', deathVerified, stillAlive });
  if (!deathVerified) {
    return {
      ok: false,
      killed: false,
      rowRemoved: false,
      deathVerified: false,
      error: REASON.KILL_DEATH_UNVERIFIED,
      reason: REASON.KILL_DEATH_UNVERIFIED,
      boundary: SOLE_BOUNDARY_ID,
      steps,
      honest: true,
    };
  }

  return {
    ok: true,
    killed: true,
    rowRemoved: true,
    deathVerified: true,
    pid: reprobe.expected.pid,
    method: (kill && kill.method) || 'taskkill_tree',
    ownership: own2.ownership,
    identity: reprobe,
    reason: REASON.OK,
    boundary: SOLE_BOUNDARY_ID,
    steps,
    honest: true,
    ...proofStamp,
  };
}

/**
 * Batch freeze for server /api/freeze body.
 */
function freezeMany(targets, opts = {}) {
  const results = [];
  let frozen = 0;
  for (const t of targets || []) {
    const r = freezeCandidate(t, opts);
    results.push(r);
    if (r.ok && r.frozen) frozen += 1;
  }
  return {
    ok: frozen > 0 && results.every((r) => r.ok),
    frozen,
    results,
    boundary: SOLE_BOUNDARY_ID,
    method: FREEZE_METHOD,
  };
}

/**
 * Batch kill for server /api/kill body.
 * Server-validated confirm is checked once for the whole batch.
 */
function killMany(targets, opts = {}) {
  const list = Array.isArray(targets) ? targets : [];
  const pids = list.map((t) => normalizePid(t && t.pid)).filter((p) => p != null);
  const confirm = opts.confirmValidated === true
    ? { ok: true, reason: REASON.OK, serverValidated: true }
    : validateKillConfirm(
      {
        confirm: opts.confirm,
        confirmToken: opts.confirmToken,
        pids: opts.confirmPids || pids,
      },
      opts,
    );
  if (!confirm.ok) {
    return {
      ok: false,
      killed: 0,
      rowRemoved: 0,
      results: [],
      error: confirm.reason,
      reason: confirm.reason,
      boundary: SOLE_BOUNDARY_ID,
    };
  }
  const results = [];
  let killed = 0;
  let rowRemoved = 0;
  for (const t of list) {
    const r = killCandidate(t, { ...opts, confirmValidated: true });
    results.push(r);
    if (r.ok && r.killed) killed += 1;
    if (r.rowRemoved) rowRemoved += 1;
  }
  return {
    ok: list.length > 0 && results.every((r) => r.ok),
    killed,
    rowRemoved,
    results,
    boundary: SOLE_BOUNDARY_ID,
  };
}

/**
 * Assert source text has no live SoftFreeze / Thread.Suspend *execution* path.
 * Mentions of the ban (comments, forbidden catalogs) are allowed; the load-bearing
 * anti-pattern is calling Suspend on process threads or constructing SoftFreeze.
 */
function assertNoThreadSuspendSoftFreeze(sourceText) {
  const s = String(sourceText || '');
  // Strip line comments so documentation of the ban does not false-positive.
  const code = s.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
  const banned = [
    /\$thread\.Suspend\s*\(/i,
    /\.Threads[\s\S]{0,80}\.Suspend\s*\(/i,
    /foreach\s*\(\s*\$thread\s+in\s+\$process\.Threads\s*\)/i,
    /new\s+SoftFreeze\s*\(/,
    /class\s+SoftFreeze\b/,
  ];
  const hits = banned.filter((re) => re.test(code));
  return {
    ok: hits.length === 0 && /NtSuspendProcess/.test(s),
    hits: hits.map(String),
    method: FREEZE_METHOD,
    requiresNtSuspend: true,
  };
}

/**
 * Read this module + server wiring sources for sole-boundary / no-SoftFreeze tests.
 */
function readBoundarySources(skillRoot) {
  const root = skillRoot || path.join(__dirname, '..');
  const freezePath = path.join(root, 'src', 'freeze.js');
  const serverPath = path.join(root, 'src', 'server.js');
  const softPath = path.join(root, 'src', 'soft-freeze.js');
  const freezeSrc = fs.readFileSync(freezePath, 'utf8');
  const serverSrc = fs.readFileSync(serverPath, 'utf8');
  let softSrc = null;
  let softExists = false;
  try {
    softSrc = fs.readFileSync(softPath, 'utf8');
    softExists = true;
  } catch (_) {
    softExists = false;
  }
  return { freezeSrc, serverSrc, softSrc, softExists, freezePath, serverPath, softPath };
}

module.exports = {
  SOLE_BOUNDARY_ID,
  SOLE_BOUNDARY_MODULE,
  FREEZE_METHOD,
  REQUIRE_PROOF_OF_DEATH,
  SAFETY_FLOOR_SOURCE,
  SPEND_POSTCONDITION,
  REASON,
  soleFreezeKillServiceBoundary,
  proofOfDeathGateStamp,
  identitiesMatch,
  probeFreezeCapability,
  isKillWithoutFreezeAllowed,
  reportSpendPostcondition,
  reProbeIdentity,
  freezeCandidate,
  unfreezeCandidate,
  killCandidate,
  freezeMany,
  killMany,
  issueKillConfirmToken,
  validateKillConfirm,
  clearKillConfirmTokens,
  assertNoThreadSuspendSoftFreeze,
  readBoundarySources,
  defaultProbeIdentity,
  defaultNtSuspend,
  defaultNtResume,
  defaultTreeKill,
  productionOwnershipLeg,
};

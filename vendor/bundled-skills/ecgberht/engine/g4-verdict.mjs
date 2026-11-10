/**
 * Anti-stub G4 gate (Wave 4).
 *
 * PASS requires ALL of:
 *   (a) captured child cmdline naming a trio CLI entry
 *   (b) handback file at the contract path passes receipt-validate
 *   (c) (pid, proc_create_time) process identity observed live then terminal
 *
 * A launcher spawning `node -e` with a canned JSON satisfies NONE of these.
 * G4 FAIL is an explicit HALT for Waves 11–22 (precondition import).
 *
 * artifacts/g4-evidence.json is written from OBSERVED evidence only (S8) —
 * the executor writes evidence, never `commissionable`.
 *
 * Path policy: shipped artifact fields never embed host-absolute user homes
 * (`<path> `<path> Prefer skill-root-relative paths or env-neutral
 * tokens; temp worktrees are redacted to `<worktree>`.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import {
  writeFileAtomicSync,
  withFileLock,
  writeJsonIdempotentSync,
} from './durable-write.mjs';
import {
  isIngestable,
  readIngestableHandback,
  handbackJsonPath,
  CONTRACT_VERSION,
} from './handback-contract.mjs';
import { validateReceipt } from './receipt-validate.mjs';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(ENGINE_DIR, '..');

/**
 * Redact host-absolute paths for shipped artifact fields.
 * @param {unknown} value
 * @param {string} [root]
 * @returns {unknown}
 */
export function sanitizeArtifactPath(value, root = DEFAULT_ROOT) {
  if (value == null) return value;
  if (typeof value !== 'string') return value;
  const s = value;
  // Already a relative contract-ish path
  if (!path.isAbsolute(s) && !/^[A-Za-z]:[\\/]/.test(s) && !s.startsWith('/Users/')) {
    return s.split(path.sep).join('/');
  }
  const rootAbs = path.resolve(root);
  const resolved = path.resolve(s);
  if (resolved === rootAbs || resolved.startsWith(rootAbs + path.sep)) {
    return path.relative(rootAbs, resolved).split(path.sep).join('/') || '.';
  }
  // Temp / user-home / other host paths → opaque tokens (never ship home dirs)
  const tmp = os.tmpdir();
  if (resolved.startsWith(path.resolve(tmp) + path.sep) || resolved === path.resolve(tmp)) {
    // Preserve trailing contract relative segment when present
    const norm = resolved.split(path.sep).join('/');
    const marker = '/.ecgberht/handback/';
    const idx = norm.indexOf(marker);
    if (idx >= 0) return `<worktree>${norm.slice(idx)}`;
    return '<worktree>';
  }
  if (/([/\\])Users\1/i.test(resolved) || /([/\\])home\1/i.test(resolved)) {
    return '<redacted-host-path>';
  }
  // Other absolute path whose segments name a trio CLI entry (a REGISTERED
  // SKILL ROOT entry, e.g. <path>
  // keep the path RELATIVE FROM the trio-naming segment
  // (→ researchPrime/bin/run-rounds.mjs). This ships no host prefix while
  // preserving the segment evidence the anti-stub token check re-derives
  // from disk — basename-only collapse silently destroyed live-skill
  // evidence (journal 0074, FIX 3).
  const segs = resolved.split(/[\\/]+/).filter(Boolean);
  for (let i = 0; i < segs.length; i += 1) {
    if (pathSegmentNamesTrioEntry(segs[i])) {
      return segs.slice(i).join('/');
    }
  }
  // Other absolute (e.g. Program Files node.exe) → basename only for cmdline parts
  return path.basename(resolved);
}

/**
 * Deep-sanitize evidence/verdict objects before disk write.
 * @param {object} obj
 * @param {string} [root]
 * @returns {object}
 */
export function sanitizeEvidenceForShip(obj, root = DEFAULT_ROOT) {
  if (!obj || typeof obj !== 'object') return obj;
  const out = Array.isArray(obj) ? [] : {};
  for (const [k, v] of Object.entries(obj)) {
    if (v == null) {
      out[k] = v;
      continue;
    }
    if (k === 'skills' && Array.isArray(v)) {
      // Multi-skill SC6 evidence: sanitize each observed skill blob
      out[k] = v.map((item) =>
        item && typeof item === 'object'
          ? sanitizeEvidenceForShip(item, root)
          : item,
      );
      continue;
    }
    if (
      k === 'cmdline' ||
      k === 'evidence_paths' ||
      (Array.isArray(v) && (k.endsWith('_paths') || k === 'argv'))
    ) {
      out[k] = Array.isArray(v)
        ? v.map((p) =>
            typeof p === 'string' ? sanitizeArtifactPath(p, root) : p,
          )
        : v;
      continue;
    }
    if (
      typeof v === 'string' &&
      (k === 'path' ||
        k.endsWith('_path') ||
        k === 'worktree' ||
        k === 'handback_path' ||
        k.endsWith('Path'))
    ) {
      out[k] = sanitizeArtifactPath(v, root);
      continue;
    }
    if (typeof v === 'object' && !Array.isArray(v)) {
      out[k] = sanitizeEvidenceForShip(v, root);
      continue;
    }
    out[k] = v;
  }
  return out;
}

/**
 * Observe process create-time (seconds since epoch). OS-level, not caller fiction.
 *
 * Engine law (w5x git-free / process-free): nothing under engine/ may import
 * child_process or spawn. Create-time that needs a host tool (Windows WMI /
 * PowerShell) is observed by the host gate or standing-suite recorder, then
 * passed in as evidence. Here we only read what pure Node + the filesystem
 * can see — typically /proc/<pid> birthtime/ctime on Linux.
 *
 * @param {number} pid
 * @returns {number|null}
 */
export function observeProcCreateTime(pid) {
  const n = Number(pid);
  if (!Number.isFinite(n) || n <= 0) return null;
  // Pure filesystem observation only — no process spawn (engine law).
  try {
    const stat = fs.statSync(`/proc/${n}`);
    const ms = stat.birthtimeMs || stat.ctimeMs;
    return Number.isFinite(ms) ? ms / 1000 : null;
  } catch {
    // Windows and other hosts without /proc: create-time is unreadable here.
    // observeProcessIdentity then reports create_time_unreadable when live.
    return null;
  }
}

/**
 * Observe whether (pid, proc_create_time) is live NOW.
 * Never trusts a caller-asserted boolean alone for the live half.
 *
 * @param {number|null|undefined} pid
 * @param {number|null|undefined} procCreateTime
 * @returns {{ status: 'alive'|'dead'|'unknown', pid: number|null, proc_create_time: number|null, observed_at: string }}
 */
export function observeProcessIdentity(pid, procCreateTime) {
  const observed_at = new Date().toISOString();
  const p = pid == null ? null : Number(pid);
  if (p == null || !Number.isFinite(p) || p <= 0) {
    return { status: 'dead', pid: null, proc_create_time: null, observed_at };
  }
  let live = false;
  try {
    // signal 0 — throws if no process / no permission
    process.kill(p, 0);
    live = true;
  } catch (e) {
    const code = e && (e.code || e.errno);
    if (code === 'EPERM') {
      // Exists but we cannot signal — treat as live-unknown create_time check
      live = true;
    } else {
      return {
        status: 'dead',
        pid: p,
        proc_create_time: procCreateTime == null ? null : Number(procCreateTime),
        observed_at,
      };
    }
  }
  const want =
    procCreateTime == null || procCreateTime === ''
      ? null
      : Number(procCreateTime);
  if (want == null || !Number.isFinite(want)) {
    return {
      status: live ? 'unknown' : 'dead',
      pid: p,
      proc_create_time: null,
      observed_at,
      reason: 'missing_proc_create_time',
    };
  }
  const nowCt = observeProcCreateTime(p);
  if (nowCt == null) {
    // Live pid but create_time unreadable → unknown (PID-reuse hazard)
    return {
      status: live ? 'unknown' : 'dead',
      pid: p,
      proc_create_time: want,
      observed_at,
      reason: 'create_time_unreadable',
    };
  }
  if (Math.abs(nowCt - want) > 1.5) {
    return {
      status: 'dead',
      pid: p,
      proc_create_time: want,
      observed_at,
      reason: 'pid_reuse_detected',
      observed_create_time: nowCt,
    };
  }
  return {
    status: live ? 'alive' : 'dead',
    pid: p,
    proc_create_time: want,
    observed_at,
    observed_create_time: nowCt,
  };
}

/**
 * Path-segment tokens that count as naming a trio CLI entry.
 * Match is by path SEGMENT identity (directory name or exact file basename
 * like `researchPrime.mjs`) — NOT by free substring, so a file named
 * `researchPrime-lite-standin.mjs` alone does not satisfy anti-stub.
 */
export const TRIO_CLI_ENTRY_TOKENS = Object.freeze([
  'researchPrime',
  'research-prime',
  'research_prime',
  'crucible',
  'foreman',
  'gandalf',
  'jumper',
  // common trio driver entry spellings (exact segment / basename)
  'trio',
  'run-live',
  'agy-dispatch',
]);

/** Allowed extensions when the token is the file basename stem. */
const TRIO_BASENAME_EXTS = Object.freeze(['.mjs', '.js', '.cjs', '.py', '.cmd', '.exe', '.ps1']);

export const G4_VERDICT_REL = path.join('artifacts', 'g4-verdict.json');
export const G4_EVIDENCE_REL = path.join('artifacts', 'g4-evidence.json');

export const G4_HALT_NAME = 'G4_HALT';
export const G4_HALT_MESSAGE =
  'G4 HALT — artifacts/g4-verdict.json is not PASS and no qualifying Anchor-owned fallback executor is recorded. Waves 11–22 are blocked.';

/**
 * True when a single path segment names a trio CLI entry.
 * Accepts exact token directories (`…/researchPrime/cli.mjs`) and exact
 * basenames (`researchPrime.mjs`, `run-live.mjs`). Rejects substring
 * filename hacks (`researchPrime-lite-standin.mjs`).
 *
 * @param {string} segment
 * @returns {boolean}
 */
export function pathSegmentNamesTrioEntry(segment) {
  if (!segment || typeof segment !== 'string') return false;
  const seg = segment.trim();
  if (!seg) return false;
  const lower = seg.toLowerCase();
  for (const tok of TRIO_CLI_ENTRY_TOKENS) {
    const t = String(tok).toLowerCase();
    if (lower === t) return true;
    for (const ext of TRIO_BASENAME_EXTS) {
      if (lower === t + ext) return true;
    }
  }
  return false;
}

/* ────────────────────────────────────────────────────────────────────────────
 * EVIDENCE CLASS (SC6 corrective, journal 0074).
 *
 * The token check above matches by PATH SEGMENT, so a directory literally
 * named `jumper` under gate/ satisfies "trio CLI cmdline evidence" — the
 * anti-stub hole that let two STAND-INS report SC6 FEASIBLE with zero real
 * skills ever commissioned. The token check stays NECESSARY (a canned
 * `node -e` still fails) but is no longer SUFFICIENT for commissionability:
 * every evidence entry now carries an `evidence_class` derived from the
 * RESOLVED REAL PATH (realpath, junctions/symlinks followed) of the observed
 * process entry:
 *
 *   harness    — entry resolves under <repo>/gate/ (the repeatable stand-ins;
 *                they still prove the HANDBACK CONTRACT, keeping Wave 4 green)
 *   live-skill — entry resolves under a REGISTERED SKILL ROOT
 *                (~/.claude/skills/<name> — junction target followed, which is
 *                the skill's own repo root — or <path> Foundry\skills\<name>,
 *                or ECGBERHT_SKILL_ROOTS entries)
 *   unknown    — neither (never counts as live-skill)
 *
 * deriveCommissionableSkills counts a skill commissionable ONLY on live-skill
 * evidence; harness-only skills are excluded with `harness_evidence_only`.
 * ──────────────────────────────────────────────────────────────────────────── */

export const EVIDENCE_CLASS = Object.freeze({
  HARNESS: 'harness',
  LIVE_SKILL: 'live-skill',
  UNKNOWN: 'unknown',
});

/** Default foundry skills dir named by the corrective instruction. */
export const DEFAULT_FOUNDRY_SKILLS_DIR = '<path> Foundry\\skills';

/** Case-fold a path for comparison (Windows realpaths are case-insensitive). */
function canonForCompare(p) {
  const abs = path.resolve(String(p));
  let real = abs;
  try {
    real = fs.realpathSync(abs);
  } catch {
    /* keep abs — nonexistent paths compare on their resolved form */
  }
  return process.platform === 'win32' ? real.toLowerCase() : real;
}

/** True when `child` is `parent` or lives under it (after canonicalization). */
function isUnder(childCanon, parentCanon) {
  return (
    childCanon === parentCanon || childCanon.startsWith(parentCanon + path.sep)
  );
}

/**
 * Resolve the REGISTERED SKILL ROOTS for a skill name (realpaths, junctions
 * followed). Sources, in order:
 *   1. injected opts.skillRoots (tests / gates)
 *   2. env ECGBERHT_SKILL_ROOTS (path-delimiter-separated list)
 *   3. ~/.claude/skills/<name> — the junction AND its realpath target
 *      (the target IS the skill's own repo root)
 *   4. <foundry>/skills/<name> (DEFAULT_FOUNDRY_SKILLS_DIR)
 * Only roots that exist on disk are returned. Never invents paths.
 *
 * @param {string} skill
 * @param {{ home?: string, env?: NodeJS.ProcessEnv, skillRoots?: string[], foundryDir?: string }} [opts]
 * @returns {string[]} canonical (realpath, case-folded on win32) roots
 */
export function resolveRegisteredSkillRoots(skill, opts = {}) {
  const out = new Set();
  const env = opts.env ?? process.env;
  const name = String(skill ?? '').trim();
  if (!name) return [];
  const lower = name.toLowerCase();

  const candidates = [];
  for (const r of opts.skillRoots ?? []) candidates.push(r);
  const envRoots = String(env.ECGBERHT_SKILL_ROOTS ?? '')
    .split(path.delimiter)
    .map((s) => s.trim())
    .filter(Boolean);
  for (const r of envRoots) candidates.push(r);

  const home = opts.home ?? os.homedir();
  for (const n of new Set([name, lower])) {
    candidates.push(path.join(home, '.claude', 'skills', n));
    candidates.push(path.join(opts.foundryDir ?? DEFAULT_FOUNDRY_SKILLS_DIR, n));
  }

  for (const c of candidates) {
    try {
      if (!fs.existsSync(c)) continue;
      out.add(canonForCompare(c));
    } catch {
      /* skip unreadable candidates */
    }
  }
  return [...out];
}

/**
 * Classify one observed entry path against the repo gate dir and the
 * registered skill roots. Pure aside from realpath resolution — no spawn.
 *
 * @param {string} entryPath
 * @param {{ root?: string, skillRootsCanon?: string[] }} [opts]
 * @returns {'harness'|'live-skill'|'unknown'}
 */
export function classifyEvidenceEntryPath(entryPath, opts = {}) {
  if (!entryPath || typeof entryPath !== 'string') return EVIDENCE_CLASS.UNKNOWN;
  const root = opts.root ?? DEFAULT_ROOT;
  let candidate = entryPath;
  if (!path.isAbsolute(candidate)) {
    candidate = path.join(root, candidate);
  }
  const canon = canonForCompare(candidate);
  const gateCanon = canonForCompare(path.join(root, 'gate'));
  if (isUnder(canon, gateCanon)) return EVIDENCE_CLASS.HARNESS;
  for (const skillRoot of opts.skillRootsCanon ?? []) {
    if (isUnder(canon, skillRoot)) return EVIDENCE_CLASS.LIVE_SKILL;
  }
  return EVIDENCE_CLASS.UNKNOWN;
}

/**
 * Derive the evidence_class for an observed cmdline: find the path-like argv
 * entries whose segments name a trio CLI entry, resolve their REAL paths, and
 * classify. `live-skill` wins over `harness` only when a trio-naming entry
 * genuinely resolves under a registered skill root — a directory merely NAMED
 * `jumper` under gate/ stays `harness`.
 *
 * @param {string[]|string|null|undefined} cmdline
 * @param {{ root?: string, skill?: string|null, skillRoots?: string[], home?: string, env?: NodeJS.ProcessEnv, foundryDir?: string }} [opts]
 * @returns {{ evidence_class: 'harness'|'live-skill'|'unknown', basis: { entry_path: string|null, matched: string|null } }}
 */
export function deriveEvidenceClass(cmdline, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const parts = Array.isArray(cmdline)
    ? cmdline.map(String)
    : cmdline == null
      ? []
      : [String(cmdline)];

  const skillRootsCanon = opts.skillRootsCanon
    ? opts.skillRootsCanon
    : resolveRegisteredSkillRoots(opts.skill ?? '', opts);

  let best = null; // { cls, part }
  for (const part of parts) {
    if (!/[\\/]/.test(part)) continue;
    const segments = part.split(/[\\/]+/).filter(Boolean);
    const namesTrio = segments.some((seg) => pathSegmentNamesTrioEntry(seg));
    if (!namesTrio) continue;
    const cls = classifyEvidenceEntryPath(part, { root, skillRootsCanon });
    if (cls === EVIDENCE_CLASS.LIVE_SKILL) {
      best = { cls, part };
      break; // strongest class — done
    }
    if (!best || (best.cls === EVIDENCE_CLASS.UNKNOWN && cls === EVIDENCE_CLASS.HARNESS)) {
      best = { cls, part };
    }
  }

  if (!best) {
    return {
      evidence_class: EVIDENCE_CLASS.UNKNOWN,
      basis: { entry_path: null, matched: null },
    };
  }
  return {
    evidence_class: best.cls,
    basis: {
      entry_path: best.part,
      matched:
        best.cls === EVIDENCE_CLASS.HARNESS
          ? 'repo-gate-dir'
          : best.cls === EVIDENCE_CLASS.LIVE_SKILL
            ? 'registered-skill-root'
            : null,
    },
  };
}

/**
 * @param {string[]|string|null|undefined} cmdline
 * @returns {boolean}
 */
export function cmdlineNamesTrioEntry(cmdline) {
  const parts = Array.isArray(cmdline)
    ? cmdline.map(String)
    : cmdline == null
      ? []
      : [String(cmdline)];
  const joined = parts.join(' ');
  if (!joined.trim()) return false;
  // Explicit refuse of the classic stub: node -e with inline canned JSON
  if (/\bnode(\.exe)?\b/i.test(joined) && /\s-e\b/i.test(joined)) {
    return false;
  }
  for (const part of parts) {
    // Split on path separators and whitespace-adjacent tokens already split
    const segments = String(part).split(/[\\/]+/).filter(Boolean);
    for (const seg of segments) {
      if (pathSegmentNamesTrioEntry(seg)) return true;
    }
  }
  return false;
}

/**
 * Evaluate observed evidence into a G4 verdict object (pure; no IO).
 *
 * @param {{
 *   cmdline?: string[]|string,
 *   pid?: number|null,
 *   proc_create_time?: number|null,
 *   observed_live?: boolean,
 *   observed_terminal?: boolean,
 *   handback_path?: string|null,
 *   handback_id?: string|null,
 *   receipt_validate_ok?: boolean,
 *   path?: string|null,
 *   worktree?: string|null,
 *   evidence_paths?: string[],
 *   recorded_at?: string,
 *   skill?: string|null,
 * }} evidence
 * @returns {{
 *   verdict: 'PASS'|'FAIL',
 *   path: string|null,
 *   pid: number|null,
 *   proc_create_time: number|null,
 *   handback_id: string|null,
 *   evidence_paths: string[],
 *   recorded_at: string,
 *   fail_reasons: string[],
 *   checks: object,
 *   contract_version: string,
 * }}
 */
export function evaluateG4Evidence(evidence = {}) {
  const fail_reasons = [];
  const cmdline = evidence.cmdline;
  const trioOk = cmdlineNamesTrioEntry(cmdline);
  if (!trioOk) {
    fail_reasons.push('cmdline_missing_trio_entry');
  }

  const receiptOk = evidence.receipt_validate_ok === true;
  if (!receiptOk) {
    fail_reasons.push('receipt_validate_not_ok');
  }

  const pid = evidence.pid == null ? null : Number(evidence.pid);
  const pct =
    evidence.proc_create_time == null || evidence.proc_create_time === ''
      ? null
      : Number(evidence.proc_create_time);

  // Live-then-terminal requires an observation record, not a free boolean.
  // Accept either:
  //   - identity_observation: { live: {...}, terminal: {...} } from observeProcessIdentity
  //   - observed_live + observed_terminal AND observation_method in allowed set
  //     with live_observed_at / terminal_observed_at timestamps
  const obs = evidence.identity_observation;
  let live = false;
  let terminal = false;
  let observationProven = false;

  if (obs && typeof obs === 'object') {
    const liveRec = obs.live || obs.observed_live_record;
    const termRec = obs.terminal || obs.observed_terminal_record;
    if (liveRec && termRec) {
      live = liveRec.status === 'alive' || liveRec.observed_live === true;
      terminal =
        termRec.status === 'dead' ||
        termRec.status === 'terminal' ||
        termRec.observed_terminal === true;
      // Terminal after a supervised wait: explicit terminal flag on record
      if (termRec.observed_terminal === true) terminal = true;
      observationProven =
        live &&
        terminal &&
        typeof (liveRec.observed_at || liveRec.at) === 'string' &&
        typeof (termRec.observed_at || termRec.at) === 'string';
    }
  }

  if (!observationProven) {
    const method = String(evidence.observation_method || '');
    const allowed = new Set([
      'observeProcessIdentity',
      'spawn-wait-exit',
      'spawnSync-exit',
      'job_runner-supervised',
    ]);
    const methodLive = evidence.observed_live === true;
    const methodTerminal = evidence.observed_terminal === true;
    if (
      allowed.has(method) &&
      typeof evidence.live_observed_at === 'string' &&
      typeof evidence.terminal_observed_at === 'string' &&
      methodLive &&
      methodTerminal
    ) {
      live = methodLive;
      terminal = methodTerminal;
      observationProven = true;
    } else if (!live && !terminal) {
      // Preserve free-boolean claims only so the failure reason can name them
      live = methodLive;
      terminal = methodTerminal;
    }
  }

  const identityOk =
    pid != null &&
    Number.isFinite(pid) &&
    pid > 0 &&
    pct != null &&
    Number.isFinite(pct) &&
    live &&
    terminal &&
    observationProven;
  if (!identityOk) {
    fail_reasons.push('process_identity_not_live_then_terminal');
    if (!observationProven && (evidence.observed_live || evidence.observed_terminal)) {
      fail_reasons.push('process_identity_caller_asserted_without_observation_record');
    }
  }

  const verdict = fail_reasons.length === 0 ? 'PASS' : 'FAIL';
  const pathOut =
    evidence.path ??
    evidence.handback_path ??
    evidence.worktree ??
    null;

  return {
    verdict,
    path: pathOut == null ? null : String(pathOut),
    pid: identityOk ? pid : pid != null && Number.isFinite(pid) ? pid : null,
    proc_create_time:
      identityOk ? pct : pct != null && Number.isFinite(pct) ? pct : null,
    handback_id: evidence.handback_id == null ? null : String(evidence.handback_id),
    evidence_paths: Array.isArray(evidence.evidence_paths)
      ? evidence.evidence_paths.map(String)
      : [],
    recorded_at: evidence.recorded_at ?? new Date().toISOString(),
    fail_reasons,
    checks: {
      cmdline_names_trio_entry: trioOk,
      receipt_validate_ok: receiptOk,
      pid_and_create_time_live_then_terminal: identityOk,
      observation_proven: observationProven,
    },
    contract_version: CONTRACT_VERSION,
    skill: evidence.skill ?? null,
  };
}

/**
 * Build evidence from a completed contract-conformant worktree + process facts.
 *
 * @param {{
 *   worktree: string,
 *   cmdline: string[]|string,
 *   pid: number,
 *   proc_create_time: number,
 *   observed_live: boolean,
 *   observed_terminal: boolean,
 *   evidence_paths?: string[],
 *   skill?: string|null,
 * }} args
 * @returns {object} evidence object (observed fields only — no commissionable)
 */
export function collectEvidenceFromWorktree(args) {
  const worktree = args.worktree;
  const classDerived = deriveEvidenceClass(args.cmdline, {
    root: args.root,
    skill: args.skill ?? null,
    skillRoots: args.skillRoots,
    home: args.home,
    env: args.env,
  });
  const evidence = {
    cmdline: args.cmdline,
    pid: args.pid,
    proc_create_time: args.proc_create_time,
    observed_live: args.observed_live === true,
    observed_terminal: args.observed_terminal === true,
    worktree,
    handback_path: handbackJsonPath(worktree),
    evidence_paths: args.evidence_paths ?? [],
    skill: args.skill ?? null,
    evidence_class: classDerived.evidence_class,
    evidence_class_basis: classDerived.basis,
    recorded_at: new Date().toISOString(),
    // S8: never stamp commissionable from the executor
  };

  if (isIngestable(worktree)) {
    const read = readIngestableHandback(worktree);
    if (read.ok) {
      const v = validateReceipt(read.handback);
      evidence.receipt_validate_ok = v.ok === true;
      evidence.handback_id =
        read.handback_id ??
        read.handback?.handback_id ??
        read.client_event_id ??
        null;
      evidence.client_event_id = read.client_event_id;
      if (v.ok) evidence.path = handbackJsonPath(worktree);
    } else {
      evidence.receipt_validate_ok = false;
      evidence.handback_read_error = read.error;
    }
  } else {
    evidence.receipt_validate_ok = false;
    evidence.handback_read_error = 'pair_not_ingestable';
  }

  return evidence;
}

/**
 * @param {string} [root] skill / project root containing artifacts/
 * @returns {string}
 */
export function g4VerdictPath(root = DEFAULT_ROOT) {
  return path.join(root, G4_VERDICT_REL);
}

/**
 * @param {string} [root]
 * @returns {string}
 */
export function g4EvidencePath(root = DEFAULT_ROOT) {
  return path.join(root, G4_EVIDENCE_REL);
}

/**
 * Write g4-evidence.json from observed evidence only (S8). Never sets commissionable.
 *
 * @param {object} evidence
 * @param {{ root?: string }} [opts]
 * @returns {string} path written
 */
export function writeG4Evidence(evidence, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const outPath = g4EvidencePath(root);
  const dir = path.dirname(outPath);
  fs.mkdirSync(dir, { recursive: true });

  // Strip any accidental commissionable stamp (S8: executor never writes it)
  const clean = { ...evidence };
  delete clean.commissionable;

  const payload = sanitizeEvidenceForShip(
    {
      ...clean,
      written_by: 'g4-verdict.mjs',
      recorded_at: clean.recorded_at ?? new Date().toISOString(),
      contract_version: CONTRACT_VERSION,
    },
    root,
  );

  // Idempotent (journal 0070/0074): a re-observation whose SEMANTIC content
  // (skills, entries, checks — pids/timestamps aside) is unchanged leaves the
  // file byte-identical and produces no git delta.
  writeJsonIdempotentSync(outPath, payload);
  return outPath;
}

/**
 * Write g4-verdict.json from an evaluateG4Evidence result.
 *
 * @param {object} verdict evaluateG4Evidence result
 * @param {{ root?: string }} [opts]
 * @returns {string}
 */
export function writeG4Verdict(verdict, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const outPath = g4VerdictPath(root);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });

  const payload = sanitizeEvidenceForShip(
    {
      verdict: verdict.verdict,
      path: verdict.path,
      pid: verdict.pid,
      proc_create_time: verdict.proc_create_time,
      handback_id: verdict.handback_id,
      evidence_paths: verdict.evidence_paths ?? [],
      recorded_at: verdict.recorded_at ?? new Date().toISOString(),
      fail_reasons: verdict.fail_reasons ?? [],
      checks: verdict.checks ?? {},
      contract_version: CONTRACT_VERSION,
      written_by: 'g4-verdict.mjs',
    },
    root,
  );

  // Idempotent: unchanged verdict leaves the file byte-identical (0070 fix).
  writeJsonIdempotentSync(outPath, payload);
  return outPath;
}

/**
 * Evaluate evidence, write both artifacts, return verdict.
 *
 * @param {object} evidence
 * @param {{ root?: string }} [opts]
 */
export function recordG4FromEvidence(evidence, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const evidencePath = writeG4Evidence(evidence, { root });
  const verdict = evaluateG4Evidence({
    ...evidence,
    evidence_paths: [
      ...(Array.isArray(evidence.evidence_paths) ? evidence.evidence_paths : []),
      evidencePath,
    ],
  });
  const verdictPath = writeG4Verdict(
    {
      ...verdict,
      evidence_paths: [
        ...verdict.evidence_paths,
        evidencePath,
        g4VerdictPath(root),
      ],
    },
    { root },
  );
  return { verdict, evidencePath, verdictPath };
}

/**
 * Read current g4-verdict.json (or null if missing/torn).
 * @param {string} [root]
 */
export function readG4Verdict(root = DEFAULT_ROOT) {
  const p = g4VerdictPath(root);
  try {
    const raw = fs.readFileSync(p, 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Read current g4-evidence.json (or null if missing/torn).
 * @param {string} [root]
 */
export function readG4EvidenceDoc(root = DEFAULT_ROOT) {
  const p = g4EvidencePath(root);
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Semantic identity of one evidence entry — the fields that matter for
 * merge retention. Run identity (pid, create-time, handback ids, timestamps)
 * is volatile by construction; what makes two observations "the same claim"
 * is: which skill, through which entry class/path, with the receipt valid and
 * the anti-stub evaluation passing.
 *
 * @param {object|null|undefined} entry
 * @returns {string}
 */
export function semanticEvidenceKey(entry) {
  if (!entry || typeof entry !== 'object') return 'null';
  const rel = Array.isArray(entry.evidence_paths)
    ? (entry.evidence_paths[0] ?? null)
    : null;
  return JSON.stringify({
    skill: entry.skill ?? null,
    evidence_class: entry.evidence_class ?? null,
    entry_rel: rel,
    receipt_validate_ok: entry.receipt_validate_ok === true,
    verdict: evaluateG4Evidence(entry).verdict,
  });
}

/** Rank an evidence entry for per-skill preference. */
function evidenceRank(entry) {
  const pass = evaluateG4Evidence(entry ?? {}).verdict === 'PASS' ? 2 : 0;
  const live = entry?.evidence_class === EVIDENCE_CLASS.LIVE_SKILL ? 1 : 0;
  return pass * 2 + live; // live-skill PASS(5) > harness PASS(4) > live FAIL(1) > rest(0)
}

/**
 * Merge fresh per-skill evidence entries into an existing g4-evidence doc.
 *
 * Rules (pure — no IO):
 *   - one entry per skill (case-insensitive key);
 *   - a retained LIVE-SKILL entry is never displaced by a fresh HARNESS entry
 *     (the standing suite's repeatable stand-ins must not clobber real-run
 *     evidence recorded by gate/w5-real-run.mjs);
 *   - a fresh entry of the SAME class replaces the old one ONLY when its
 *     semantic key differs — identical claims keep the OLD bytes so the
 *     artifact stays git-stable (journal 0070);
 *   - order: existing skills first (stable), new skills appended.
 *
 * @param {object|null} existingDoc parsed artifacts/g4-evidence.json (or null)
 * @param {object[]} freshEntries per-skill observed evidence entries
 * @returns {{ skills: object[], root: object|null }}
 */
export function mergeG4SkillEvidence(existingDoc, freshEntries) {
  const existing = Array.isArray(existingDoc?.skills)
    ? existingDoc.skills.filter(Boolean)
    : existingDoc && (existingDoc.skill || existingDoc.cmdline)
      ? [existingDoc]
      : [];
  const fresh = (freshEntries ?? []).filter(Boolean);

  const keyOf = (e) => String(e?.skill ?? '').toLowerCase();
  const order = [];
  const chosen = new Map();

  for (const e of existing) {
    const k = keyOf(e);
    if (!k) continue;
    if (!chosen.has(k)) order.push(k);
    chosen.set(k, e);
  }

  for (const f of fresh) {
    const k = keyOf(f);
    if (!k) continue;
    const prev = chosen.get(k);
    if (!prev) {
      order.push(k);
      chosen.set(k, f);
      continue;
    }
    const prevRank = evidenceRank(prev);
    const freshRank = evidenceRank(f);
    if (freshRank > prevRank) {
      chosen.set(k, f); // e.g. live-skill PASS displaces harness PASS
      continue;
    }
    if (freshRank < prevRank) {
      continue; // never displace live-skill with harness (or PASS with FAIL)
    }
    // Same rank: replace only on a genuine semantic change (git stability).
    if (semanticEvidenceKey(prev) !== semanticEvidenceKey(f)) {
      chosen.set(k, f);
    }
  }

  const skills = order.map((k) => chosen.get(k));
  const rootEntry =
    skills.find((e) => String(e?.skill ?? '').toLowerCase() === 'researchprime') ??
    skills[0] ??
    null;
  return { skills, root: rootEntry };
}

/**
 * Merge fresh entries with the on-disk evidence and record evidence + verdict.
 * The recorder path for BOTH the standing suite (harness observations) and
 * the w5 real-run gate (live-skill observations): neither clobbers the other,
 * and an unchanged merge leaves both artifacts byte-identical.
 *
 * @param {object[]} freshEntries
 * @param {{ root?: string }} [opts]
 */
export function recordG4MergedEvidence(freshEntries, opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const existing = readG4EvidenceDoc(root);
  const merged = mergeG4SkillEvidence(existing, freshEntries);
  if (!merged.root) {
    return {
      ok: false,
      error: 'no_evidence_entries',
      message: 'nothing to record — no existing or fresh evidence entries',
    };
  }
  const multi = {
    ...merged.root,
    skills: merged.skills,
  };
  const { verdict, evidencePath, verdictPath } = recordG4FromEvidence(multi, {
    root,
  });
  return { ok: true, verdict, evidencePath, verdictPath, skills: merged.skills };
}

/**
 * Qualifying Anchor-owned fallback: must discharge IDENTICAL obligations.
 * Self-declared boolean bags do NOT qualify — requires on-disk evidence that
 * itself evaluates to anti-stub PASS (or a verified evidence file path).
 *
 * @param {object|null} fallback
 * @param {{ root?: string }} [opts]
 * @returns {boolean}
 */
export function isQualifyingFallback(fallback, opts = {}) {
  if (!fallback || typeof fallback !== 'object') return false;
  const flagsOk =
    fallback.owner === 'anchor' &&
    fallback.auth_on === true &&
    fallback.refuses_unconfirmed === true &&
    fallback.anti_stub_evidence === true &&
    fallback.durable_handback_file === true &&
    fallback.full_failure_state_table === true &&
    fallback.discharges_identical_obligations === true;
  if (!flagsOk) return false;

  // Anti self-declared bypass: require evidence that re-evaluates to PASS,
  // or a durable evidence file under the project that does.
  const root = opts.root ?? DEFAULT_ROOT;
  if (fallback.evidence && typeof fallback.evidence === 'object') {
    const v = evaluateG4Evidence(fallback.evidence);
    return v.verdict === 'PASS';
  }
  const evPath = fallback.evidence_path || fallback.g4_evidence_path;
  if (typeof evPath === 'string' && evPath.trim()) {
    let abs = evPath;
    if (!path.isAbsolute(evPath)) {
      abs = path.join(root, evPath);
    }
    try {
      const raw = fs.readFileSync(abs, 'utf8');
      const evidence = JSON.parse(raw);
      const v = evaluateG4Evidence(evidence);
      return v.verdict === 'PASS';
    } catch {
      return false;
    }
  }
  // Flags alone never lift the HALT
  return false;
}

/**
 * Wave-11+ precondition: FAIL the build unless verdict PASS or qualifying fallback.
 *
 * @param {{ root?: string, fallback?: object|null }} [opts]
 * @returns {{ ok: true, verdict: object } | { ok: false, halt: string, message: string, verdict: object|null }}
 */
export function assertG4Precondition(opts = {}) {
  const root = opts.root ?? DEFAULT_ROOT;
  const verdict = readG4Verdict(root);

  if (verdict && verdict.verdict === 'PASS') {
    // Anti-stub: a PASS record must still carry the three checks when present
    const checks = verdict.checks || {};
    if (
      checks.cmdline_names_trio_entry === false ||
      checks.receipt_validate_ok === false ||
      checks.pid_and_create_time_live_then_terminal === false
    ) {
      return {
        ok: false,
        halt: G4_HALT_NAME,
        message: `${G4_HALT_MESSAGE} (PASS record fails anti-stub checks)`,
        verdict,
      };
    }
    return { ok: true, verdict };
  }

  if (isQualifyingFallback(opts.fallback ?? null, { root })) {
    return {
      ok: true,
      verdict,
      via_fallback: true,
      fallback: opts.fallback,
    };
  }

  return {
    ok: false,
    halt: G4_HALT_NAME,
    message: G4_HALT_MESSAGE,
    verdict,
  };
}

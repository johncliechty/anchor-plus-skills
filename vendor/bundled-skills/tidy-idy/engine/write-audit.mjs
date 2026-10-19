// engine/write-audit.mjs — Wave 1 tripwire, TIER 1 (engine self-writes).
//
// The analysis pass performs ZERO writes under the project root. That is not a
// convention here, it is enforced: every stage does its filesystem access
// through this facade, and any write under `rootPath` that is not inside
// `reportDir` is BLOCKED AT THE CALL SITE (the underlying fs call never runs)
// and fails the run with the offending stage and path named.
//
// Blocking at the call site — rather than detecting the damage afterwards — is
// the whole point: an after-the-fact sweep can only tell you that the tool
// already corrupted the tree it promised not to touch.
//
// Child-process spawns are LOGGED (not blocked — git is a native tool the
// engine legitimately shells out to) so that if a native tool writes under the
// root, the drift sweep's delta is attributable to a specific command from a
// specific stage instead of being an unexplained mystery.
//
// Tier 2 (external drift vs snapshot S) lives in engine/snapshot.mjs; the two
// tiers have deliberately different semantics — see that file's header.

import fsp from 'node:fs/promises';
import { constants as FS } from 'node:fs';
import path from 'node:path';
import { execFile as execFileCb } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

const execFileAsync = promisify(execFileCb);

/** Thrown at the call site of a blocked write. */
export class WriteAuditViolation extends Error {
  constructor({ op, target, stage, rootPath, reportDir }) {
    super(
      `ZERO-WRITE INVARIANT VIOLATED: stage '${stage || 'unknown'}' attempted ${op}() on '${target}', ` +
      `which is under the project root '${rootPath}' and outside the run's reportDir '${reportDir}'. ` +
      'The analysis pass performs no writes under the root; the call was BLOCKED and the run fails here.');
    this.name = 'WriteAuditViolation';
    this.op = op;
    this.target = target;
    this.stage = stage || null;
    this.rootPath = rootPath;
    this.reportDir = reportDir;
  }
}

/** fs/promises members that mutate the filesystem. */
const WRITE_OPS = [
  'writeFile', 'appendFile', 'mkdir', 'mkdtemp', 'rm', 'rmdir', 'unlink',
  'rename', 'copyFile', 'cp', 'truncate', 'symlink', 'link', 'chmod', 'chown',
  'lchmod', 'lchown', 'utimes', 'lutimes',
];

/** fs/promises members that only read — passed through untouched. */
const READ_OPS = [
  'readFile', 'readdir', 'stat', 'lstat', 'access', 'realpath', 'readlink', 'statfs',
];

/** Which argument of each op is a path that must be checked. */
const EXTRA_PATH_ARG = { rename: [0, 1], copyFile: [0, 1], cp: [0, 1], link: [0, 1], symlink: [1] };

function isInside(parent, child) {
  const rel = path.relative(parent, child);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/** Any bit that makes an open() capable of modifying the file it opens. */
const WRITE_FLAG_MASK = FS.O_WRONLY | FS.O_RDWR | FS.O_CREAT | FS.O_TRUNC | FS.O_APPEND;

/**
 * Does this `open()` flags argument request write access?
 *
 * fs.open accepts flags as a STRING ('w') or as a NUMERIC bitmask
 * (fs.constants.O_WRONLY | O_CREAT). A tripwire that only pattern-matched the
 * string form had a hole exactly the size of the numeric API: `String(577)` has
 * no 'w', 'a', 'x' or '+' in it, so a numeric write-open was waved straight
 * through the guard. Both forms are decided here, once.
 */
export function opensForWrite(flags) {
  if (typeof flags === 'number') return (flags & WRITE_FLAG_MASK) !== 0;
  const f = String(flags);
  // 'r' and 'rs' are the only read-only string modes; everything else that
  // carries w/a/x/+ mutates.
  if (f === 'r' || f === 'rs') return false;
  return /[wax+]/.test(f);
}

/**
 * Create the audit facade for one run.
 *
 * @param {{rootPath: string, reportDir: string, baseFs?: object, baseExecFile?: Function}} opts
 */
export function createWriteAudit({ rootPath, reportDir, baseFs = fsp, baseExecFile = execFileAsync }) {
  const root = path.resolve(rootPath);
  const report = path.resolve(reportDir);
  const violations = [];
  const spawns = [];
  let currentStage = null;

  function enterStage(name) { currentStage = name; return name; }
  function currentStageName() { return currentStage; }

  /**
   * The predicate. `true` means "allowed". Writes OUTSIDE the root are not this
   * tripwire's business (temp dirs, the user's home) — the invariant being
   * enforced is specifically "the tool does not modify the project it is
   * analysing".
   */
  function isAllowedWrite(target) {
    const abs = path.resolve(target);
    if (!isInside(root, abs)) return true;
    return isInside(report, abs);
  }

  function guard(op, target) {
    if (target === undefined || target === null) return;
    let asPath = null;
    if (typeof target === 'string') asPath = target;
    else if (target instanceof URL) asPath = fileURLToPath(target);
    else if (Buffer.isBuffer(target)) asPath = target.toString();
    if (asPath === null) return; // fd-style handle: not a path write we can attribute
    const abs = path.resolve(asPath);
    if (isAllowedWrite(abs)) return;
    const violation = {
      op, target: abs, stage: currentStage, at: new Date().toISOString(),
    };
    violations.push(violation);
    throw new WriteAuditViolation({ op, target: abs, stage: currentStage, rootPath: root, reportDir: report });
  }

  const fs = {};
  for (const op of READ_OPS) {
    if (typeof baseFs[op] === 'function') fs[op] = (...args) => baseFs[op](...args);
  }
  for (const op of WRITE_OPS) {
    if (typeof baseFs[op] !== 'function') continue;
    // `async` is load-bearing, not cosmetic: fs/promises members are awaited by
    // their callers, so a BLOCKED call must surface as a REJECTED PROMISE. A
    // synchronous throw from a promise-shaped API escapes `await`-less call
    // sites and .catch() handlers alike — the violation would bypass the very
    // stage error-handling that turns it into a failed run.
    fs[op] = async (...args) => {
      const idxs = EXTRA_PATH_ARG[op] || [0];
      for (const i of idxs) guard(op, args[i]);
      return baseFs[op](...args);
    };
  }
  // `open` is special: read modes are fine, write modes are a write. Both the
  // string and the numeric flag forms are decided by opensForWrite().
  if (typeof baseFs.open === 'function') {
    fs.open = async (file, flags = 'r', ...rest) => {
      if (opensForWrite(flags)) guard('open', file);
      return baseFs.open(file, flags, ...rest);
    };
  }

  /**
   * Attributable child-process execution. Logged, never blocked — a git read is
   * a legitimate native call; the log is what makes a native WRITE traceable.
   */
  async function execFile(cmd, args = [], opts = {}) {
    const record = {
      cmd, args: [...args], cwd: opts.cwd || process.cwd(),
      stage: currentStage, at: new Date().toISOString(), ok: null,
    };
    spawns.push(record);
    try {
      const out = await baseExecFile(cmd, args, opts);
      record.ok = true;
      return out;
    } catch (err) {
      record.ok = false;
      record.error = err && err.message;
      throw err;
    }
  }

  /** Throw if anything was blocked — used by the pipeline to fail the run. */
  function assertNoViolations() {
    if (violations.length) {
      const v = violations[0];
      throw new WriteAuditViolation({ op: v.op, target: v.target, stage: v.stage, rootPath: root, reportDir: report });
    }
  }

  return {
    rootPath: root,
    reportDir: report,
    fs,
    execFile,
    enterStage,
    currentStage: currentStageName,
    isAllowedWrite,
    violations,
    spawns,
    assertNoViolations,
  };
}

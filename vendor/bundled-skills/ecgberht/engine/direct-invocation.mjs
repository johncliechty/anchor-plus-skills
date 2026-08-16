/**
 * "Was this module run directly?" — junction/symlink-safe.
 *
 * WHY THIS EXISTS (sleep cycle 2026-08-04, promoted from gandalf journal 0275).
 *
 * The usual guard compares `path.resolve(process.argv[1])` against the module's own
 * `import.meta.url`. Through a junction or symlink those are DIFFERENT STRINGS for the
 * SAME FILE, so the comparison fails, `main()` never runs, and the process exits 0
 * having written nothing. Silent success is the worst possible failure here: the caller
 * sees exit 0 and an empty stdout and concludes the command did nothing wrong.
 *
 * Gandalf hit this exact bug (`node <junction>/runtime/gandalf-run.mjs` exited 0 and
 * wrote no report) and journal 0275 named the fix: realpath BOTH sides. This module is
 * that fix, made shared and tested, because Ecgberht is itself registered as a junction
 * — `~/.claude/skills/ecgberht -> <path> — so the REGISTERED skill path is
 * precisely the path that triggers it. Both `bin/ecgberht.mjs` and `bin/steward.mjs`
 * were silently dead when invoked that way.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Resolve a path through junctions/symlinks, falling back to a plain resolve when the
 * file does not exist (a not-yet-created path is not an error for this predicate).
 *
 * @param {string} p
 * @returns {string}
 */
export function realOrResolve(p) {
  const abs = path.resolve(String(p));
  try {
    // realpathSync.native follows Windows junctions AND normalises 8.3 / case.
    return fs.realpathSync.native ? fs.realpathSync.native(abs) : fs.realpathSync(abs);
  } catch {
    return abs;
  }
}

/**
 * True when `argv1` refers to the same FILE as `moduleUrl`, however it was spelled.
 *
 * Windows paths are compared case-insensitively: the same file reached as
 * `<path> and `<path> must not read as two files.
 *
 * @param {string|undefined} argv1 typically process.argv[1]
 * @param {string} moduleUrl typically import.meta.url
 * @returns {boolean}
 */
export function isDirectInvocation(argv1, moduleUrl) {
  if (!argv1) return false;
  let self;
  try {
    self = realOrResolve(fileURLToPath(moduleUrl));
  } catch {
    return false;
  }
  const invoked = realOrResolve(argv1);
  if (process.platform === 'win32') {
    return invoked.toLowerCase() === self.toLowerCase();
  }
  return invoked === self;
}

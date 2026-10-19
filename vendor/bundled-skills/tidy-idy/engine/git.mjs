// engine/git.mjs — Wave 1: the git handle, or null.
//
// `ctx.git` is a HANDLE or NULL — never a boolean flag, never a thrown refusal
// at open time. A folder without a repo is a first-class case (Wave 2 ships
// ordinary-folder modes; Wave 4 ships Trash removals for it), so this module's
// only job is to answer "is there a repo here, and what is it" honestly.
//
// Every command is pinned with `-C <root>` and the handle asserts that the
// discovered toplevel IS the root, so no run can ever operate on an enclosing
// repository it merely happens to sit inside.

import path from 'node:path';
import { execFile as execFileCb } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFileCb);

/** Minimum git supporting `checkout --no-overlay` (Wave-0 verdict, Wave-3 executor). */
export const MIN_GIT_VERSION = '2.22';

function cmpVersion(a, b) {
  const pa = String(a).split('.').map((n) => parseInt(n, 10) || 0);
  const pb = String(b).split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d < 0 ? -1 : 1;
  }
  return 0;
}

/**
 * Open a git handle for `rootPath`, or return null when there is no repository
 * whose toplevel is exactly that path.
 *
 * @param {string} rootPath
 * @param {{execFile?: Function}} [opts]
 * @returns {Promise<null|object>}
 */
export async function openGit(rootPath, { execFile = execFileAsync } = {}) {
  const root = path.resolve(rootPath);

  const run = async (args, opts = {}) => {
    const { stdout, stderr } = await execFile('git', ['-C', root, ...args], { maxBuffer: 32 * 1024 * 1024, ...opts });
    return { stdout: String(stdout), stderr: String(stderr) };
  };

  let toplevel;
  try {
    const { stdout } = await run(['rev-parse', '--show-toplevel']);
    toplevel = path.resolve(stdout.trim());
  } catch {
    return null; // not a repository — a legitimate, declared state
  }

  // An ENCLOSING repository is not this run's repository. `rev-parse` walks
  // upwards, so a plain folder that merely happens to sit under someone else's
  // work tree (a checkout above it, a home directory under version control, an
  // OS temp dir inside a repo) would otherwise hand us a handle onto a tree we
  // were never pointed at — and every git-held operation would then act on it.
  // The header contract of this module is that the handle's toplevel IS the
  // root; anything else is the no-repository case, which Wave 2 and Wave 4 both
  // ship as a first-class mode (ordinary-folder modes, Trash removals).
  if (toplevel !== root) return null;

  let version = null;
  try {
    const { stdout } = await execFile('git', ['--version'], {});
    const m = /(\d+\.\d+(?:\.\d+)?)/.exec(String(stdout));
    version = m ? m[1] : null;
  } catch { /* version is advisory here; Wave 3 asserts it before --no-overlay */ }

  let head = null;
  try {
    const { stdout } = await run(['rev-parse', 'HEAD']);
    head = stdout.trim() || null;
  } catch {
    head = null; // a repo with no commits yet: real, and not an error
  }

  let branch = null;
  try {
    const { stdout } = await run(['rev-parse', '--abbrev-ref', 'HEAD']);
    branch = stdout.trim() || null;
  } catch { /* detached or unborn */ }

  return {
    root,
    toplevel,
    /** The root IS the repo toplevel — false means we are inside an enclosing repo. */
    rootIsToplevel: toplevel === root,
    version,
    head,
    branch,
    run,
    supportsNoOverlay() { return version ? cmpVersion(version, MIN_GIT_VERSION) >= 0 : false; },
    async porcelain() {
      const { stdout } = await run(['status', '--porcelain=v2', '--branch', '--untracked-files=all']);
      return stdout;
    },
    async isDirty() {
      const { stdout } = await run(['status', '--porcelain']);
      return stdout.trim().length > 0;
    },
    async summary() {
      const dirtyOut = await run(['status', '--porcelain']).then((r) => r.stdout).catch(() => '');
      const dirtyCount = dirtyOut.split('\n').filter((l) => l.trim()).length;
      return { branch, head, shortHead: head ? head.slice(0, 7) : null, dirtyCount, dirty: dirtyCount > 0 };
    },
  };
}

export { cmpVersion };

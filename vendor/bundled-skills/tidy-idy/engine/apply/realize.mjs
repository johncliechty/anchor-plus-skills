// engine/apply/realize.mjs — Wave 3, canonical pipeline step 5.
//
// The commit and the ref are ALREADY DURABLE when this runs. That ordering is
// the whole safety argument: from here on, every possible failure leaves the
// content held by git, so the worst outcome is a working tree that needs the
// sync retried — never content that is gone.
//
// MECHANISM. The Wave-0 spike measured `git checkout --no-overlay <C> -- <paths>`
// and stamped it CONFIRMED (spike/no-overlay-verdict.json): it updates matched
// files AND deletes matched files absent from <C>, in both the index and the
// working tree, scoped strictly to the pathspec. Deletion propagation is the
// load-bearing behaviour — without it a REMOVE would commit but leave the file
// on disk. The verdict is re-measured on the gate runner's real git on every
// suite run, so it cannot rot silently.
//
// The verdict also carries a mitigation this module implements: `--no-overlay`
// exists only from git 2.22, and only the runner's own version is OBSERVED. So
// the version is asserted at runtime BEFORE the flag is used, and the spike's
// pre-specified per-path fallback (checkout-for-content + delete-for-deletion,
// same journal, same idempotency) is available as a strategy — DORMANT, per the
// frozen plan, because the verdict is CONFIRMED, but present so that a REFUTED
// re-measurement has a landing site instead of a redesign.
//
// PROBED BEHAVIOURS, each with a fixture test:
//   • locked file (Windows) — checkout exits nonzero; the op is journaled and
//     retried, and because it is a pure idempotent function of (C, pathspecs) a
//     retry is always safe.
//   • dirty index — unrelated staged entries are outside the pathspec, and an
//     approved path with newly-staged changes was already dropped as stale in
//     step 2, so this step never overwrites staged work.
//   • case-insensitive filesystem — refused earlier, at compile time.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { cmpVersion, MIN_GIT_VERSION } from '../git.mjs';
import { lit, revBlob, revBytes } from './git-plumbing.mjs';

export const REALIZE_STRATEGY = Object.freeze({
  NO_OVERLAY: 'no-overlay',
  PER_PATH: 'per-path',
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Make the working tree and the user's index match <commit> for exactly the
 * approved paths.
 *
 * @param {{run: Function, rootPath: string, commit: string, paths: string[],
 *   gitVersion?: string|null, strategy?: string, maxAttempts?: number,
 *   journal?: object|null, fs?: object, delayMs?: number}} opts
 */
export async function realizeWorkingTree({
  run,
  rootPath,
  commit,
  paths = [],
  gitVersion = null,
  strategy = REALIZE_STRATEGY.NO_OVERLAY,
  maxAttempts = 3,
  journal = null,
  fs = fsp,
  delayMs = 25,
} = {}) {
  const pathspecs = [...new Set(paths)].sort();
  if (!pathspecs.length) {
    return { strategy, complete: true, attempts: 0, pending: [], pathspecs, note: 'nothing to realize' };
  }

  if (strategy === REALIZE_STRATEGY.NO_OVERLAY && gitVersion && cmpVersion(gitVersion, MIN_GIT_VERSION) < 0) {
    // Not a silent downgrade: the fallback is named in the result so a run on an
    // old git is visibly a different code path, not a mystery.
    strategy = REALIZE_STRATEGY.PER_PATH;
  }

  if (journal) await journal.append('realize-start', { commit, strategy, pathspecs });

  let attempts = 0;
  let lastError = null;

  while (attempts < maxAttempts) {
    attempts++;
    try {
      if (strategy === REALIZE_STRATEGY.NO_OVERLAY) {
        const r = await run(['checkout', '--no-overlay', commit, '--', ...pathspecs.map(lit)], { allowFailure: true });
        if (r.code !== 0) throw new Error(`git checkout --no-overlay exited ${r.code}: ${r.stderr.trim()}`);
      } else {
        await realizePerPath({ run, rootPath, commit, pathspecs, journal, fs });
      }
    } catch (err) {
      lastError = err;
      if (journal) await journal.append('realize-attempt-failed', { attempt: attempts, error: err.message });
      if (attempts < maxAttempts) { await sleep(delayMs); continue; }
    }

    // Converged? Ask the tree, not the exit code — a locked file that another
    // process released between the failure and this check is genuinely done, and
    // a zero exit that somehow left a path unrealized must not read as success.
    const pending = await pendingPaths({ run, rootPath, commit, pathspecs, fs });
    if (!pending.length) {
      if (journal) await journal.append('realize-done', { commit, strategy, attempts });
      return { strategy, complete: true, attempts, pending: [], pathspecs, note: `working tree and index match ${commit.slice(0, 7)} for all ${pathspecs.length} approved path(s)` };
    }
    if (attempts >= maxAttempts) {
      if (journal) await journal.append('realize-incomplete', { commit, strategy, attempts, pending });
      return {
        strategy,
        complete: false,
        attempts,
        pending,
        pathspecs,
        error: lastError ? lastError.message : null,
        note: `INCOMPLETE working-tree sync: ${pending.length} approved path(s) could not be realized (${pending.map((p) => p.path).join(', ')}). The commit and the branch are already durable, so NOTHING IS LOST — re-run the sync: git -C <root> checkout --no-overlay ${commit} -- ${pending.map((p) => p.path).join(' ')}`,
      };
    }
    await sleep(delayMs);
  }

  /* c8 ignore next */
  return { strategy, complete: false, attempts, pending: [], pathspecs, error: lastError ? lastError.message : null };
}

/**
 * The spike's pre-specified REFUTED fallback, kept dormant but real: per-path
 * checkout-for-content, delete-for-deletion, journaled per path, idempotent.
 */
async function realizePerPath({ run, rootPath, commit, pathspecs, journal, fs }) {
  for (const rel of pathspecs) {
    const blob = await revBlob(run, commit, rel);
    if (journal) await journal.append('realize-path', { path: rel, op: blob ? 'checkout-for-content' : 'delete-for-deletion', state: 'started' });
    if (blob) {
      await run(['checkout', commit, '--', lit(rel)]);
    } else {
      await fs.rm(path.join(rootPath, rel), { force: true });
      // An index entry that is already gone is not an error — that is what makes
      // the retry converge instead of failing on the second pass.
      await run(['update-index', '--force-remove', '--', rel], { allowFailure: true });
    }
    if (journal) await journal.append('realize-path', { path: rel, op: blob ? 'checkout-for-content' : 'delete-for-deletion', state: 'done' });
  }
}

/** Which approved paths still do not match <commit>? */
export async function pendingPaths({ run, rootPath, commit, pathspecs, fs = fsp }) {
  const pending = [];
  for (const rel of pathspecs) {
    const expected = await revBytes(run, commit, rel);
    const abs = path.join(rootPath, rel);
    let actual = null;
    let exists = true;
    try {
      actual = await fs.readFile(abs);
    } catch (err) {
      if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) exists = false;
      else { pending.push({ path: rel, state: 'unreadable', error: err.message }); continue; }
    }
    if (expected === null) {
      if (exists) pending.push({ path: rel, state: 'should-be-deleted-but-present' });
      continue;
    }
    if (!exists) { pending.push({ path: rel, state: 'should-exist-but-missing' }); continue; }
    if (!expected.equals(actual)) pending.push({ path: rel, state: 'content-differs' });
  }
  return pending;
}

export default { realizeWorkingTree, pendingPaths, REALIZE_STRATEGY };

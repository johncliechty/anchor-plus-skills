// engine/apply/git-plumbing.mjs — Wave 3: the one place Apply talks to git.
//
// The analysis half of the engine reaches git through `ctx.git.run()`, which is
// built on execFile and cannot feed a process STDIN. Apply needs exactly that:
// Amendment C.iv requires tool-generated blobs to be hashed from IN-MEMORY
// content (`git hash-object -w --stdin`) rather than re-read from the working
// tree, because a re-read is a second chance for the bytes a human approved to
// differ from the bytes that get committed.
//
// So this module is a spawn-based runner with three properties Apply depends on:
//   • STDIN — content goes in as bytes, never through a temp file on disk.
//   • BUFFER STDOUT — `git cat-file blob` must round-trip binary byte-for-byte.
//   • GIT_INDEX_FILE per call — the compiled plan lives in a temp index so the
//     user's own index is never touched (canonical table, step 3).
//
// Every invocation is pinned with `-C <root>`; there is no CWD-relative call.

import { spawn as defaultSpawn } from 'node:child_process';
import path from 'node:path';

/** A git command that exited nonzero. Carries enough to journal it honestly. */
export class GitCommandError extends Error {
  constructor(args, exitCode, stderr) {
    super(`git ${args.join(' ')} exited ${exitCode}: ${String(stderr).trim()}`);
    this.name = 'GitCommandError';
    this.gitArgs = args;
    this.exitCode = exitCode;
    this.stderr = String(stderr);
  }
}

/**
 * Pathspec magic that turns a repo-relative path into a LITERAL match.
 *
 * Without it a path containing `*`, `?` or a leading `:` would be interpreted as
 * a glob or as pathspec magic — i.e. an approved operation on one file could
 * silently widen to match others. Consent-scope forbids that, so every pathspec
 * Apply hands to git is wrapped.
 */
export function lit(rel) {
  return `:(literal)${rel}`;
}

/**
 * Build a runner pinned to one repository root.
 *
 * @param {{root: string, env?: object, spawn?: Function}} opts
 * @returns {(args: string[], opts?: object) => Promise<{code: number, stdout: Buffer, stderr: string, text: string}>}
 */
export function makeGitRunner({ root, env = process.env, spawn = defaultSpawn } = {}) {
  const cwdRoot = path.resolve(root);

  return function run(args, { input = null, indexFile = null, allowFailure = false, env: overrideEnv = null } = {}) {
    return new Promise((resolve, reject) => {
      // Per-call env overrides exist for exactly one caller: Bootstrap's
      // commit-tree, which supplies GIT_AUTHOR_*/GIT_COMMITTER_* when the
      // machine has no git identity configured — otherwise a background
      // Bootstrap on a fresh machine dies at the last step of the only Apply a
      // non-git folder can receive.
      const childEnv = { ...env, ...(overrideEnv || {}) };
      if (indexFile) childEnv.GIT_INDEX_FILE = indexFile;
      // A commit compiled by Apply must not inherit an interactive editor or a
      // pager: both would hang a background job forever.
      childEnv.GIT_TERMINAL_PROMPT = '0';
      childEnv.GIT_PAGER = 'cat';

      const child = spawn('git', ['-C', cwdRoot, ...args], { env: childEnv, windowsHide: true });
      const out = [];
      const err = [];
      child.stdout.on('data', (d) => out.push(d));
      child.stderr.on('data', (d) => err.push(d));
      child.on('error', reject);
      child.on('close', (code) => {
        const stdout = Buffer.concat(out);
        const stderr = Buffer.concat(err).toString('utf8');
        if (code !== 0 && !allowFailure) {
          reject(new GitCommandError(args, code, stderr));
          return;
        }
        resolve({ code, stdout, stderr, text: stdout.toString('utf8') });
      });

      if (input !== null && input !== undefined) child.stdin.end(input);
      else child.stdin.end();
    });
  };
}

/** `<rev>:<path>` exists? Returns its blob sha, or null. */
export async function revBlob(run, rev, rel) {
  const r = await run(['rev-parse', '--verify', '--quiet', `${rev}:${rel}`], { allowFailure: true });
  const sha = r.text.trim();
  return r.code === 0 && sha ? sha : null;
}

/** The bytes of `<rev>:<path>`, or null when the path is absent from that tree. */
export async function revBytes(run, rev, rel) {
  const r = await run(['cat-file', 'blob', `${rev}:${rel}`], { allowFailure: true });
  if (r.code !== 0) return null;
  return r.stdout;
}

/** The byte size of `<rev>:<path>`, or null. Cheaper than reading the blob. */
export async function revSize(run, rev, rel) {
  const r = await run(['cat-file', '-s', `${rev}:${rel}`], { allowFailure: true });
  if (r.code !== 0) return null;
  const n = Number(r.text.trim());
  return Number.isFinite(n) ? n : null;
}

/** Every path a single commit changed, as {status, path, origPath?}. */
export async function commitPaths(run, commit) {
  const r = await run(['diff-tree', '-r', '-z', '--no-commit-id', '--name-status', '--no-renames', commit]);
  const fields = r.text.split('\0').filter((s) => s.length > 0);
  const out = [];
  for (let i = 0; i < fields.length; i += 2) {
    const status = fields[i];
    const rel = fields[i + 1];
    if (rel === undefined) break;
    out.push({ status, path: rel });
  }
  return out;
}

export default { makeGitRunner, GitCommandError, lit, revBlob, revBytes, revSize, commitPaths };

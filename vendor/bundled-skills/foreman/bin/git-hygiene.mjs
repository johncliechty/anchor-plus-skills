// git-hygiene.mjs — Foreman Phase 3c: git hygiene + git-resume reconciliation.
//
// Scope (Phase 3c per Foreman-Implementation-Plan-FINAL.md §9 + §8 + §6.3):
//   ALL git operations are confined to the TARGET PROJECT repo (the projectDir
//   passed by the orchestrator). This module never runs git against the Foreman
//   source tree or C:\dev — a containment guard (assertContainment) hard-refuses
//   any repo whose toplevel contains the Foreman source.
//
// What the plan specifies (and this module implements):
//   - §9 commit hygiene: explicit PER-FILE staging (NEVER `git add .`/`-A`);
//     repo-boundary resolution (`git rev-parse --show-toplevel` per changed file,
//     refuse a wave spanning >1 toplevel, HALT on a nested `.git` in the staging
//     set); meaningful messages (NOT "Wave X complete"); NEVER auto-push; "no
//     remote" is flagged. No force, no history rewrite (the plan never authorizes
//     either; the conservative damage-prevention reading is to do neither).
//   - §6.3 non-convergence: `git stash` the failed attempt and record the ref so
//     the tree is left clean + recoverable.
//   - §8 resume reconciliation: compare `git rev-parse HEAD` to the checkpoint's
//     `last_commit`; if HEAD is AHEAD (commit landed before the checkpoint
//     updated) adopt HEAD and skip the re-commit (prevents double-apply); HALT on
//     genuine divergence (rewritten history / wrong branch / unexpected dirty).
//
// Where the plan is SILENT, this module follows the build prompt's explicit
// CONSERVATIVE directive (documented, configurable, not invented contrary to the
// plan):
//   - Dedicated work branch (default `foreman/run`); commits NEVER land on the
//     default/main branch. (§9 names a branch only for the §6.3 failed attempt.)
//   - Dirty-tree policy: refuse to START on an unexpectedly dirty tree rather than
//     clobbering user changes (nearest plan anchor: §6.5 "repo in bad state").
//   - Commit message template (the plan gives only the negative constraint).
//
// Commit <-> checkpoint ORDER (defined here, proven in test/git-hygiene.test.mjs):
//   COMMIT first, THEN the orchestrator writes the checkpoint recording last_commit.
//   So a commit-then-crash leaves HEAD ahead of checkpoint.last_commit (reconcile
//   adopts HEAD; commitWave is idempotent so the re-run makes no duplicate commit),
//   and a crash-before-commit leaves HEAD == last_commit with the wave's work
//   uncommitted on disk (reconcile treats that as the expected in-progress state
//   when the checkpoint shows a resumable wave, else HALTs).

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { HaltError } from './foreman-lib.mjs';

// Resolve the Foreman source root from this module's own location so the
// containment guard cannot be fooled by a relative cwd. .../foreman/bin/<this>.
const FOREMAN_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const DEFAULT_WORK_BRANCH = 'foreman/run';
const FORBIDDEN_BRANCHES = new Set(['main', 'master', 'HEAD']);
// Foreman's own state artifacts: never staged, and ignored when assessing whether
// the working tree is "dirty" (they are Foreman output, not user/wave changes).
const FOREMAN_EXCLUDES = [
  '.foreman/',
  'foreman-checkpoint.json',
  'foreman-checkpoint.json.tmp',
];

/** True if `child` is the same path as, or nested inside, `parent`. */
function within(child, parent) {
  const c = path.resolve(child);
  const p = path.resolve(parent);
  return c === p || c.startsWith(p + path.sep);
}

// Hardening (P2): hang-proof every git call. Under load (multiple agents + a
// large test gate) a git op can stall on lock contention, a hanging pre-commit
// hook, or a credential/network prompt. spawnSync with no timeout would freeze
// the whole orchestrator. Kill any git that exceeds this and surface a clear,
// actionable HALT instead of an indefinite hang.
const GIT_TIMEOUT_MS = 120000;

/** Run git in `repoDir`. shell:false (no injection); never auto-network.
 * `raw:true` returns stdout UNTRIMMED — required for `--porcelain` parsing, whose
 * first line's leading status space (" M path") is significant; trimming it shifts
 * the columns and mangles the first path (the map.json-not-committed bug 2026-06-04). */
function git(repoDir, args, { allowFail = false, raw = false } = {}) {
  const res = spawnSync('git', args, {
    cwd: repoDir, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024,
    timeout: GIT_TIMEOUT_MS, killSignal: 'SIGKILL', windowsHide: true,
  });
  if (res.error) {
    const timedOut = res.error.code === 'ETIMEDOUT' || res.signal === 'SIGKILL';
    const msg = timedOut
      ? `git ${args.join(' ')} exceeded ${Math.round(GIT_TIMEOUT_MS / 1000)}s and was killed ` +
        `(possible lock contention, a hanging hook, or a credential/network prompt) — resolve the cause and retry`
      : `git ${args.join(' ')}: ${res.error.message}`;
    if (allowFail) return { ok: false, status: null, stdout: '', stderr: msg, timedOut };
    throw new HaltError(timedOut ? 'git invocation timed out' : 'git invocation failed', msg);
  }
  const out = { ok: res.status === 0, status: res.status,
    stdout: raw ? (res.stdout || '') : (res.stdout || '').trim(), stderr: (res.stderr || '').trim() };
  return out;
}

/**
 * Hardening (P1): clear a STALE `.git/index.lock` left by a prior crashed run.
 *
 * Foreman runs every git op serially via spawnSync (each completes before the
 * next begins), so it NEVER holds index.lock across calls. A lock present at
 * context-creation time is therefore necessarily stale — left when a previous
 * run crashed or the machine froze mid-`git commit`. Such a lock makes every
 * subsequent git write fail ("Unable to create '.../index.lock': File exists"),
 * which would block --resume after exactly the kind of crash this hardening
 * targets. Removing it deletes only the mutex file, never any tracked work.
 */
function clearStaleIndexLock(repoDir, log) {
  const r = git(repoDir, ['rev-parse', '--git-dir'], { allowFail: true });
  if (!r.ok) return;
  const gitDir = path.isAbsolute(r.stdout) ? r.stdout : path.resolve(repoDir, r.stdout);
  const lock = path.join(gitDir, 'index.lock');
  if (!fs.existsSync(lock)) return;
  try {
    fs.rmSync(lock, { force: true });
    if (log) log('git hygiene: removed a stale .git/index.lock (left by a prior interrupted run; ' +
      'Foreman runs git serially so a lock at startup is never a live operation)');
  } catch (e) {
    throw new HaltError('could not remove a stale git index.lock',
      `${lock}: ${e.message} — no git process should be running against this repo; remove it manually and retry`);
  }
}

/** Is `dir` inside a git work tree? */
export function isGitRepo(dir) {
  const r = git(dir, ['rev-parse', '--is-inside-work-tree'], { allowFail: true });
  return r.ok && r.stdout === 'true';
}

function toplevel(dir) {
  const r = git(dir, ['rev-parse', '--show-toplevel'], { allowFail: true });
  if (!r.ok) throw new HaltError('not a git repository', `${dir}: ${r.stderr || 'git rev-parse --show-toplevel failed'}`);
  // git prints forward slashes even on Windows; normalize to an OS path.
  return path.resolve(r.stdout);
}

/**
 * Containment guard (CRITICAL SAFETY): refuse to operate on any repo that overlaps
 * the Foreman source tree in EITHER direction — a repo whose toplevel CONTAINS the
 * Foreman source, or a repo nested INSIDE the Foreman source. Neither C:\dev nor
 * C:\dev\foreman is a repo today, so this never fires in practice — it is a hard
 * belt-and-suspenders stop so a future mis-invocation can never commit/stash the
 * Foreman source.
 */
export function assertContainment(repoTop) {
  if (within(FOREMAN_ROOT, repoTop)) {
    throw new HaltError(
      'refusing to run git against a repo that contains the Foreman source',
      `repo toplevel ${repoTop} contains ${FOREMAN_ROOT} — Foreman never commits its own source (CRITICAL SAFETY)`,
    );
  }
  if (within(repoTop, FOREMAN_ROOT)) {
    throw new HaltError(
      'refusing to run git against a repo nested inside the Foreman source',
      `repo toplevel ${repoTop} is inside ${FOREMAN_ROOT} — Foreman never commits its own source (CRITICAL SAFETY)`,
    );
  }
}

function headSha(repoDir) {
  const r = git(repoDir, ['rev-parse', '--verify', 'HEAD'], { allowFail: true });
  return r.ok ? r.stdout : null; // null = unborn HEAD (no commits yet)
}

function currentBranch(repoDir) {
  const r = git(repoDir, ['rev-parse', '--abbrev-ref', 'HEAD'], { allowFail: true });
  return r.ok ? r.stdout : ''; // 'HEAD' if detached; '' if unborn/failed
}

function hasRemote(repoDir) {
  const r = git(repoDir, ['remote'], { allowFail: true });
  return r.ok && r.stdout.length > 0;
}

/** porcelain status lines, EXCLUDING Foreman's own state artifacts. */
function dirtyEntries(repoDir) {
  const r = git(repoDir, ['status', '--porcelain'], { allowFail: true, raw: true });
  if (!r.ok) throw new HaltError('git status failed', r.stderr);
  const out = [];
  for (const line of r.stdout.split(/\r?\n/)) {
    if (!line.trim()) continue;
    // porcelain v1: cols 0-1 = XY status, col 2 = space, path from col 3 ("XY orig
    // -> path" for renames). The leading status space is significant — parse from
    // FIXED columns; never l.trim() before extracting (that mangled the first path).
    let p = line.slice(3);
    if (p.includes(' -> ')) p = p.split(' -> ').pop();
    p = p.replace(/^"|"$/g, '').trim();
    if (FOREMAN_EXCLUDES.some((ex) => (ex.endsWith('/') ? p.startsWith(ex) : p === ex))) continue;
    out.push(p);
  }
  return out;
}

function isDirty(repoDir) {
  return dirtyEntries(repoDir).length > 0;
}

/** a is an ancestor of b (b is a descendant of a). */
function isAncestor(repoDir, a, b) {
  const r = git(repoDir, ['merge-base', '--is-ancestor', a, b], { allowFail: true });
  return r.status === 0;
}

/**
 * Install Foreman's state-dir excludes into the repo-local `.git/info/exclude`
 * (NEVER the user's tracked `.gitignore`), idempotently. This keeps
 * `.foreman/` + the checkpoint untracked so they neither get staged nor make the
 * tree read as "dirty". Best-effort: a failure to write the exclude file is
 * tolerated (the per-file staging below never stages them regardless).
 */
function installForemanExcludes(repoTop) {
  try {
    const ex = path.join(repoTop, '.git', 'info', 'exclude');
    let cur = '';
    try { cur = fs.readFileSync(ex, 'utf8'); } catch { /* may not exist */ }
    const want = FOREMAN_EXCLUDES.filter((p) => !cur.split(/\r?\n/).includes(p));
    if (want.length) {
      const sep = cur.length && !cur.endsWith('\n') ? '\n' : '';
      fs.appendFileSync(ex, sep + '# Foreman state (added by git-hygiene; not user-tracked)\n' + want.join('\n') + '\n');
    }
  } catch { /* tolerate: staging is explicit per-file and never stages these */ }
}

/**
 * Resolve the toplevel of each changed file and enforce §9 repo-boundary safety:
 *   - every changed file must resolve to the SAME toplevel == the project repo
 *     (a file under a nested repo resolves to the nested toplevel -> >1 toplevel),
 *   - no path in the staging set may sit inside a nested `.git` repo.
 * Throws HaltError on a breach. `files` are project-relative (deletion markers
 * stripped by the caller).
 */
function assertRepoBoundary(repoTop, files) {
  const tops = new Set();
  for (const rel of files) {
    const abs = path.resolve(repoTop, rel);
    const dir = fs.existsSync(abs) ? (fs.statSync(abs).isDirectory() ? abs : path.dirname(abs)) : path.dirname(abs);
    const t = fs.existsSync(dir) ? git(dir, ['rev-parse', '--show-toplevel'], { allowFail: true }) : { ok: false, stderr: 'directory does not exist' };
    if (t.ok) {
      tops.add(path.resolve(t.stdout));
    } else if (within(abs, repoTop)) {
      // The file's directory could not be resolved directly — a TRANSIENT path
      // (created then removed during the wave, e.g. a script's scratch output) or a
      // git-quoted special-char path can linger in the gate-time changed set. It
      // came from `git status` run inside repoTop, so it is BY CONSTRUCTION inside
      // this repo: treat its toplevel as repoTop rather than HALTing. A path
      // genuinely OUTSIDE repoTop still falls through to the cross-repo HALT below.
      tops.add(path.resolve(repoTop));
    } else {
      throw new HaltError('repo-boundary check failed',
        `cannot resolve toplevel for ${rel} and it is not within ${repoTop} — refusing to commit across repo boundaries (§9)`);
    }
    // Nested-repo detection: a `.git` directory anywhere between repoTop and the
    // file's directory (exclusive of repoTop itself) means a nested repo.
    let walk = path.dirname(abs);
    while (within(walk, repoTop) && path.resolve(walk) !== path.resolve(repoTop)) {
      if (fs.existsSync(path.join(walk, '.git'))) {
        throw new HaltError(
          'nested .git inside the staging set',
          `${rel} sits under a nested git repo at ${walk} — refusing to stage across repo boundaries (§9)`,
        );
      }
      walk = path.dirname(walk);
    }
  }
  if (tops.size > 1) {
    throw new HaltError(
      'wave changes span more than one git toplevel',
      `changed files resolve to ${tops.size} repos: ${[...tops].join(', ')} — refusing to commit across repo boundaries (§9)`,
    );
  }
  if (tops.size === 1 && path.resolve([...tops][0]) !== path.resolve(repoTop)) {
    throw new HaltError(
      'wave changes are outside the project repo',
      `changed files resolve to ${[...tops][0]} but the project repo is ${repoTop} (§9)`,
    );
  }
}

/** Meaningful commit message (§9: NOT "Wave X complete"). */
export function commitMessage(wave, gate) {
  const t = gate?.tap || {};
  const title = wave.title ? ` "${wave.title}"` : '';
  const subject = `foreman: wave ${wave.n}${title} GREEN (gate ${t.pass ?? '?'}/${t.tests ?? '?'})`;
  const body =
    `Orchestrator-run gate proved real passing tests for this wave.\n` +
    `gate: ${gate?.command ?? '?'} -> exit ${gate?.exit_code ?? '?'}, ` +
    `tap tests=${t.tests ?? '?'} pass=${t.pass ?? '?'} fail=${t.fail ?? '?'}.\n` +
    `[foreman: no push, no force; committed on a dedicated work branch]`;
  return `${subject}\n\n${body}`;
}

/**
 * Build a git-hygiene context bound to ONE target repo + work branch. Validates
 * the dir is a repo and the containment guard, installs the state excludes.
 */
export function makeGitContext({ repoDir, workBranch = DEFAULT_WORK_BRANCH, log = null }) {
  if (FORBIDDEN_BRANCHES.has(workBranch)) {
    throw new HaltError('refusing to use a default/main branch as the work branch',
      `work branch "${workBranch}" is a default branch — pick a dedicated branch (e.g. ${DEFAULT_WORK_BRANCH})`);
  }
  if (!isGitRepo(repoDir)) {
    throw new HaltError('git hygiene requested but the project is not a git repository',
      `${repoDir} is not inside a git work tree — init the repo or run without --git`);
  }
  const repoTop = toplevel(repoDir);
  assertContainment(repoTop);
  clearStaleIndexLock(repoDir, log); // P1: a lock at startup is stale (serial git) — clear it so resume isn't blocked
  installForemanExcludes(repoTop);

  const ctx = {
    repoDir, repoTop, workBranch,
    headSha: () => headSha(repoDir),
    currentBranch: () => currentBranch(repoDir),
    hasRemote: () => hasRemote(repoDir),
    isDirty: () => isDirty(repoDir),
    dirtyEntries: () => dirtyEntries(repoDir),

    /**
     * The wave's changed files = the working tree's changes vs HEAD (tracked
     * modifications/adds/deletes + untracked), as project-relative paths
     * ('<p>' or '<p> (deleted)'), EXCLUDING Foreman state. This is the §8
     * "idempotent-from-last-commit" view: on a fresh wave it equals the new edits;
     * on a crash-before-commit RESUME it still surfaces the prior run's uncommitted
     * deliverable (which an in-process per-invocation snapshot would miss). Used by
     * runWave both for the §5 vacuous-GREEN guard and for explicit commit staging.
     */
    changedVsHead() {
      const r = git(repoDir, ['status', '--porcelain', '--untracked-files=all'], { allowFail: true, raw: true });
      if (!r.ok) throw new HaltError('git status failed', r.stderr);
      const out = [];
      for (const line of r.stdout.split(/\r?\n/)) {
        if (!line.trim()) continue;
        const code = line.slice(0, 2);
        let p = line.slice(3).trim();
        if (p.includes(' -> ')) p = p.split(' -> ').pop().trim(); // rename: take the new path
        p = p.replace(/^"|"$/g, '');
        if (FOREMAN_EXCLUDES.some((ex) => (ex.endsWith('/') ? p.startsWith(ex) : p === ex))) continue;
        out.push(code.includes('D') ? `${p} (deleted)` : p);
      }
      return out;
    },

    /**
     * Fresh-start preflight (§9 dirty-tree + dedicated branch). Refuses on an
     * unexpectedly dirty tree (no clobber), then switches to the dedicated work
     * branch (creating it from the current HEAD if needed). Returns the base
     * branch we started from (so the caller can prove it stays untouched).
     */
    prepareFreshStart() {
      if (headSha(repoDir) === null) {
        throw new HaltError('repo has no baseline commit',
          `${repoTop} has an unborn HEAD — make an initial commit before running Foreman so reconciliation has a baseline (§8)`);
      }
      const dirty = dirtyEntries(repoDir);
      if (dirty.length) {
        throw new HaltError('refusing to start on an unexpectedly dirty working tree',
          `${dirty.length} uncommitted change(s) in ${repoTop} (e.g. "${dirty[0]}") — commit/stash them first; ` +
          `Foreman will not clobber user changes (conservative dirty-tree policy)`);
      }
      const base = currentBranch(repoDir);
      if (base === workBranch) return { baseBranch: base, created: false };
      // create-or-switch (NEVER -B, which would reset an existing branch).
      const exists = git(repoDir, ['rev-parse', '--verify', '--quiet', `refs/heads/${workBranch}`], { allowFail: true }).status === 0;
      const co = exists
        ? git(repoDir, ['checkout', workBranch], { allowFail: true })
        : git(repoDir, ['checkout', '-b', workBranch], { allowFail: true });
      if (!co.ok) {
        throw new HaltError('could not switch to the dedicated work branch', `${workBranch}: ${co.stderr}`);
      }
      return { baseBranch: base, created: !exists };
    },

    /**
     * Commit ONE wave's changed files (§9). Explicit per-file staging (NEVER
     * `git add .`/`-A`), repo-boundary enforced, NO push/force. IDEMPOTENT: if
     * nothing is staged (e.g. a commit-then-crash re-run where the work is already
     * committed), it makes NO empty commit and returns the current HEAD sha.
     *
     * @returns {{ sha:string, committed:boolean, files:string[], branch:string }}
     */
    commitWave({ files, wave, gate }) {
      // Never commit on a default/main branch (defence in depth: prepareFreshStart
      // already switched, but verify before every commit).
      const br = currentBranch(repoDir);
      if (FORBIDDEN_BRANCHES.has(br) || br !== workBranch) {
        throw new HaltError('refusing to commit off the dedicated work branch',
          `HEAD is on "${br}" but the work branch is "${workBranch}" — Foreman never commits on the default branch (§9)`);
      }
      const rels = (files || [])
        .map((f) => f.replace(/ \(deleted\)$/, ''))
        .filter((f) => !FOREMAN_EXCLUDES.some((ex) => (ex.endsWith('/') ? f.startsWith(ex) : f === ex)));
      if (rels.length === 0) {
        // No deliverable file changed — caller's vacuous-green guard already
        // covers "proved nothing"; here just don't fabricate a commit.
        return { sha: headSha(repoDir), committed: false, files: [], branch: br };
      }
      assertRepoBoundary(repoTop, rels);
      // Explicit per-file staging (handles add/modify/delete for tracked paths).
      for (const rel of rels) {
        const a = git(repoDir, ['add', '--', path.resolve(repoTop, rel)], { allowFail: true });
        if (!a.ok) {
          // A transient path (created then removed mid-wave) can linger in the
          // gate-time changed set; `git add` then fails with "pathspec did not
          // match". If it no longer exists on disk it is not a deliverable — skip
          // it. (A real deletion stages fine via `git add`, so a failing add for a
          // file that STILL exists is a genuine error and still HALTs.)
          if (!fs.existsSync(path.resolve(repoTop, rel))) continue;
          throw new HaltError('git add failed', `${rel}: ${a.stderr}`);
        }
      }
      // Nothing actually staged (idempotent re-run after commit-then-crash).
      if (git(repoDir, ['diff', '--cached', '--quiet'], { allowFail: true }).status === 0) {
        return { sha: headSha(repoDir), committed: false, files: rels, branch: br };
      }
      const msg = commitMessage(wave, gate);
      const c = git(repoDir, ['commit', '-m', msg], { allowFail: true });
      if (!c.ok) {
        throw new HaltError('git commit failed',
          `${c.stderr || 'commit returned non-zero'} — (a missing user.name/user.email, or a failing pre-commit hook, will land here; resolve it, do not bypass)`);
      }
      const sha = headSha(repoDir);
      return { sha, committed: true, files: rels, branch: br };
    },

    /**
     * §6.3 non-convergence: stash the failed attempt (including untracked) so the
     * tree is left clean + recoverable, and return the stash commit ref. No-op
     * (null) if there is nothing to stash.
     */
    stashFailedAttempt(label) {
      if (!isDirty(repoDir)) return null;
      const s = git(repoDir, ['stash', 'push', '--include-untracked', '-m', label], { allowFail: true });
      if (!s.ok) {
        throw new HaltError('git stash failed', s.stderr);
      }
      const ref = git(repoDir, ['rev-parse', 'stash@{0}'], { allowFail: true });
      return ref.ok ? ref.stdout : 'stash@{0}';
    },

    /**
     * §8 resume reconciliation. Compares HEAD to the checkpoint's last_commit and
     * the working-tree state to what the checkpoint implies, and either returns a
     * safe continuation directive or HALTs on divergence.
     *
     * @param {object} cp   the validated checkpoint
     * @returns {{ action:'in-sync'|'adopt-head', headBefore:?string, adoptedHead:?string, detail:string }}
     */
    reconcile(cp) {
      const br = currentBranch(repoDir);
      if (br !== workBranch) {
        throw new HaltError('resume on the wrong git branch',
          `checkpoint expects the dedicated work branch "${workBranch}" but HEAD is on "${br}" — ` +
          `check out ${workBranch} (or clear the checkpoint); refusing to commit on the wrong branch (§8/§9)`);
      }
      const head = headSha(repoDir);
      const last = cp.last_commit || null;
      const resumableInProgress =
        cp.status === 'budget_stopped' || (cp.status === 'running' && cp.last_verdict !== 'GO');
      const dirty = dirtyEntries(repoDir);

      // No commit recorded yet (pre-first-wave checkpoint): only an in-progress
      // wave may legitimately leave a dirty tree.
      if (last === null) {
        if (dirty.length && !resumableInProgress) {
          throw new HaltError('resume: unexpected uncommitted changes (no wave committed yet)',
            `${dirty.length} change(s) but the checkpoint records no committed wave and none in progress (e.g. "${dirty[0]}")`);
        }
        return { action: 'in-sync', headBefore: head, adoptedHead: null, detail: 'no commit recorded yet; continuing' };
      }

      if (head === last) {
        // crash-before-commit (or clean stop). Dirty is OK only if a wave is in
        // progress; otherwise the tree should be clean.
        if (dirty.length && !resumableInProgress) {
          throw new HaltError('resume: unexpected uncommitted changes diverge from the checkpoint',
            `HEAD == last_commit (${last.slice(0, 7)}) but ${dirty.length} uncommitted change(s) exist and no wave is in progress ` +
            `(e.g. "${dirty[0]}") — refusing to blind-proceed (§8)`);
        }
        return { action: 'in-sync', headBefore: head, adoptedHead: null,
          detail: `HEAD == last_commit (${last.slice(0, 7)})${dirty.length ? '; in-progress wave changes present (expected)' : ''}` };
      }

      // HEAD != last_commit. Determine the relationship.
      if (head && isAncestor(repoDir, last, head)) {
        // HEAD is a descendant of last_commit: commit-then-crash. Adopt HEAD and
        // skip the re-commit (do NOT redo the wave — §8).
        if (dirty.length) {
          throw new HaltError('resume: HEAD advanced past the checkpoint AND the tree is dirty',
            `HEAD (${head.slice(0, 7)}) is ahead of last_commit (${last.slice(0, 7)}) but ${dirty.length} uncommitted change(s) ` +
            `also exist — ambiguous; refusing to blind-proceed (§8)`);
        }
        // The realistic commit-then-crash window is EXACTLY one wave commit (commit
        // landed, checkpoint write didn't). More than one commit ahead means
        // multiple waves committed with no checkpoint update — we cannot safely map
        // commits→waves, so HALT rather than guess.
        const aheadR = git(repoDir, ['rev-list', '--count', `${last}..${head}`], { allowFail: true });
        const ahead = Number(aheadR.stdout);
        if (!aheadR.ok || !Number.isInteger(ahead) || ahead < 1) {
          throw new HaltError('resume: could not measure how far HEAD is ahead of the checkpoint', aheadR.stderr || aheadR.stdout);
        }
        if (ahead > 1) {
          throw new HaltError('resume: HEAD is multiple commits ahead of the checkpoint',
            `HEAD is ${ahead} commits ahead of last_commit (${last.slice(0, 7)}) — cannot map commits to waves unambiguously; resolve manually (§8)`);
        }
        return { action: 'adopt-head', headBefore: last, adoptedHead: head, aheadCount: ahead,
          detail: `commit-then-crash recovery: HEAD (${head.slice(0, 7)}) is exactly 1 commit ahead of checkpoint last_commit (${last.slice(0, 7)}); adopting HEAD, skipping re-commit (§8)` };
      }

      // Either HEAD is an ancestor of last_commit (a recorded commit is MISSING
      // from git — lost/reset), or the two have diverged (rebase/rewrite/foreign
      // commit). Both are unsafe to auto-continue.
      throw new HaltError('resume: git HEAD has diverged from the checkpoint',
        `checkpoint last_commit=${last.slice(0, 7)} but git HEAD=${head ? head.slice(0, 7) : '(unborn)'} is neither equal nor a descendant — ` +
        `history was rewritten/reset or a foreign commit intervened; resolve manually, do not blind-proceed (§8/§6.5)`);
    },
  };
  return ctx;
}

export const _internals = { within, assertRepoBoundary, dirtyEntries, isAncestor, clearStaleIndexLock, FOREMAN_ROOT, FOREMAN_EXCLUDES };

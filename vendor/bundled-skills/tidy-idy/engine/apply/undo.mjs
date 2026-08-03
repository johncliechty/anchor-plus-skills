// engine/apply/undo.mjs — Wave 3: revert-or-refuse undo.
//
// Owned decision #2, in code: UNDO NEVER FORCE-OVERWRITES THE WORKING TREE OR
// LATER COMMITS. It either applies cleanly or it refuses and tells the user
// exactly what is in the way. The per-file `git checkout <tidy-commit>^ -- <p>`
// degrade is BANNED as an automatic behaviour — it appears in this file only as
// a copyable string a human may choose to run in their own terminal, clearly
// marked destructive. That distinction is the entire point: the tool never
// silently destroys, and the user is never blocked from deciding otherwise.
//
// THE FOUR ENUMERATED BRANCHES:
//   (a) dirty working tree overlapping the revert paths → refuse, list them
//   (b) later commits conflict with the revert          → refuse, list commits+paths
//   (c) the tidy commit is already reverted             → no-op with an explanation
//   (d) HEAD moved but the revert merges cleanly        → allowed
//
// Plus two rules that span every undo path in the system:
//
//   NO-CLOBBER (engine/apply/no-clobber.mjs). Before writing ANY destination, the
//     path's current content is compared against what the Apply left there. A
//     mismatch refuses THAT path — with a diff and a copyable command — while
//     the others proceed. Working-tree dirtiness on an affected path counts as
//     unclean, not only commit-level conflicts.
//
//   DECISION #8 COMPENSATION. A tidy commit containing SAVE operations does not
//     undo to "the file is gone/old" — it undoes to the exact pre-Apply state,
//     which was DIRTY: the content existed in the working tree, unstaged. So
//     after the clean revert, each SAVE'd path is re-materialised from
//     `<C>:<path>` into the working tree UNSTAGED, inside the same lock window.
//     Only git-held content is ever written, so the compensation itself cannot
//     lose anything.
//
// THE TRASH HALF (Amendment A, Wave 4). An Apply may have had two halves — one
// commit plus one journaled Trash move-set — so its undo has two as well: the
// revert above, then restore-from-Trash for the same run, inside the SAME lock
// window and under the same no-clobber rule. A folder with no repository has
// only the second half, and undoApply routes straight to it (branch
// 'restore-from-trash') instead of refusing for want of a commit.
//
// PARTIAL UNDO. When no-clobber or a later commit refuses SOME paths but not
// others, a whole-commit `git revert` is not available (it is all-or-nothing).
// The remaining paths still proceed — through the SAME compiled-plan machinery
// Apply uses: one temp index, one commit, one compare-and-swap, one journaled
// realization restricted to the surviving pathspecs. The refused paths are not
// touched by any step.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { reportDirFor } from '../report-dir.mjs';
import { makeGitRunner, revBytes, revBlob, commitPaths } from './git-plumbing.mjs';
import { acquireLock } from './lock.mjs';
import { openJournal, readJournal, findJournalForCommit } from './journal.mjs';
import { checkNoClobber, expectationsFromJournal } from './no-clobber.mjs';
import { parsePlanTrailer, OP_KIND } from './plan.mjs';
import { withTempIndex } from './temp-index.mjs';
import { realizeWorkingTree, REALIZE_STRATEGY } from './realize.mjs';
import { restoreFromTrash, readTrashLedger, TRASH_STATUS } from './trash.mjs';

export const UNDO_STATUS = Object.freeze({
  REVERTED: 'reverted',
  PARTIAL: 'partial',
  NO_OP: 'no-op',
  REFUSED: 'refused',
  /** Amendment A: the Apply had no git half, so its undo has none either. */
  RESTORED: 'restored-from-trash',
});

export const UNDO_BRANCH = Object.freeze({
  CLEAN_REVERT: 'clean-revert',
  HEAD_MOVED_CLEAN: 'head-moved-but-merges-cleanly',
  ALREADY_REVERTED: 'already-reverted',
  DIRTY_OVERLAP: 'dirty-overlap',
  LATER_COMMIT_CONFLICT: 'later-commit-conflict',
  PARTIAL: 'partial-some-paths-refused',
  TRASH_RESTORE: 'restore-from-trash',
});

export const UNDO_REFUSAL = Object.freeze({
  NO_GIT: 'ADVISORY_MODE_NO_GIT',
  LOCK_HELD: 'LOCK_HELD',
  UNKNOWN_COMMIT: 'UNKNOWN_COMMIT',
  MERGE_COMMIT: 'MERGE_COMMIT_UNSUPPORTED',
  NOT_A_TIDY_COMMIT: 'NOT_A_TIDY_COMMIT',
  DIRTY_OVERLAP: 'DIRTY_OVERLAP',
  LATER_COMMIT_CONFLICT: 'LATER_COMMIT_CONFLICT',
  DETACHED_HEAD: 'DETACHED_HEAD',
  REF_RACE: 'REF_COMPARE_AND_SWAP_FAILED',
});

/**
 * Undo one tidy commit.
 *
 * @param {{rootPath: string, git: object|null, commit: string, reportDir?: string,
 *   runId?: string|null, requireTidyCommit?: boolean, fs?: object, env?: object,
 *   run?: Function, now?: Function, jobId?: string|null,
 *   maxRealizeAttempts?: number, realizeStrategy?: string}} opts
 */
export async function undoApply(opts = {}) {
  const {
    git,
    commit: commitish,
    runId = null,
    requireTidyCommit = false,
    fs = fsp,
    env = process.env,
    now = () => new Date(),
    jobId = null,
    maxRealizeAttempts = 3,
    realizeStrategy = REALIZE_STRATEGY.NO_OVERLAY,
  } = opts;

  const root = path.resolve(opts.rootPath);
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : reportDirFor(root);

  // ---- Amendment A: the repo-less undo is restore-from-Trash -------------
  // An Apply on a folder with no repository moved files into the Trash; its
  // undo moves them back. That is the whole undo — there is no commit to revert
  // because there was nothing for a commit to hold.
  if (!git) {
    if (runId) {
      const { journal: ledger } = await readTrashLedger({ reportDir, runId, fs });
      if (ledger) return undoTrashOnly({ root, reportDir, runId, fs, now, jobId });
    }
    return {
      status: UNDO_STATUS.REFUSED,
      code: UNDO_REFUSAL.NO_GIT,
      message: `Undo refuses: there is no git repository at this root, and no Trash ledger${runId ? ` for run ${runId}` : ' (no run id was given)'} — so there is neither a commit to revert nor a move-set to reverse. Removals made without git are undone by restoring from the Trash (Amendment A); pass the run id of the Apply you want undone.`,
    };
  }

  const run = opts.run || makeGitRunner({ root, env });

  const lock = await acquireLock({ reportDir, jobId, purpose: 'undo', fs, now });
  if (!lock.ok) {
    return { status: UNDO_STATUS.REFUSED, code: UNDO_REFUSAL.LOCK_HELD, message: lock.message, holder: lock.holder };
  }

  let journal = null;
  try {
    // ---- identify the commit --------------------------------------------
    const resolved = await run(['rev-parse', '--verify', '--quiet', `${commitish}^{commit}`], { allowFailure: true });
    if (resolved.code !== 0) {
      return { status: UNDO_STATUS.REFUSED, code: UNDO_REFUSAL.UNKNOWN_COMMIT, message: `no such commit: ${commitish}` };
    }
    const commit = resolved.text.trim();

    const parentsLine = (await run(['rev-list', '--parents', '-n', '1', commit])).text.trim().split(/\s+/);
    const parents = parentsLine.slice(1);
    if (parents.length !== 1) {
      return {
        status: UNDO_STATUS.REFUSED,
        code: UNDO_REFUSAL.MERGE_COMMIT,
        message: `${commit.slice(0, 7)} has ${parents.length} parent(s). Every tidy commit has exactly one; reverting a merge needs a mainline choice this tool will not make on your behalf.`,
      };
    }
    const parent = parents[0];

    const message = (await run(['log', '-1', '--format=%B', commit])).text;
    const plan = parsePlanTrailer(message);
    if (requireTidyCommit && !plan) {
      return { status: UNDO_STATUS.REFUSED, code: UNDO_REFUSAL.NOT_A_TIDY_COMMIT, message: `${commit.slice(0, 7)} carries no tidy-idy plan trailer — it was not produced by this tool` };
    }

    const head = (await run(['rev-parse', 'HEAD'])).text.trim();
    const symRes = await run(['symbolic-ref', '--quiet', 'HEAD'], { allowFailure: true });
    const ref = symRes.code === 0 ? symRes.text.trim() : null;
    if (!ref) {
      return { status: UNDO_STATUS.REFUSED, code: UNDO_REFUSAL.DETACHED_HEAD, message: 'HEAD is detached — undo would leave the revert unreachable from any branch' };
    }

    const affected = (await commitPaths(run, commit)).map((c) => c.path);
    const applyJournal = await loadApplyJournal({ reportDir, runId, commit, fs });
    const savePaths = savePathsOf(plan, applyJournal);
    // The Apply may have had a Trash half, whose undo is its own move-back. It
    // is keyed by RUN, not by commit, so the run id is resolved once here —
    // from the caller when given, otherwise from whichever journal named this
    // commit.
    const effectiveRunId = runId || (applyJournal && applyJournal.runId) || null;

    journal = await openJournal({ reportDir, runId: runId || commit, kind: 'undo', fs, now });
    await journal.append('undo-start', { commit, parent, head, affected, savePaths });

    // ---- branch (c): already reverted ------------------------------------
    if (await isAlreadyReverted({ run, head, parent, paths: affected })) {
      const result = {
        status: UNDO_STATUS.NO_OP,
        branch: UNDO_BRANCH.ALREADY_REVERTED,
        commit,
        affected,
        message: `nothing to undo: every path touched by ${commit.slice(0, 7)} already matches its pre-Apply state at HEAD — this commit has been reverted already (or its effect was otherwise undone). No commit was created and nothing was written.`,
      };
      await journal.append('undo-no-op', result);
      return result;
    }

    // The two refusal checks run in THIS order on purpose. A later commit moves
    // the working tree too, so running no-clobber first would classify every
    // later-commit conflict as "you edited this file" — true in a trivial sense
    // and useless to the person reading the panel. Committed divergence is
    // branch (b); only what is left — divergence that exists solely in the
    // working tree — is branch (a)/no-clobber.

    // ---- branch (b): did a commit made after the tidy commit change it? ---
    const laterCommitRefusals = [];
    const stillAtCommit = [];
    for (const rel of affected) {
      const atHead = await revBlob(run, head, rel);
      const atCommit = await revBlob(run, commit, rel);
      if (atHead === atCommit) { stillAtCommit.push(rel); continue; }
      laterCommitRefusals.push({
        path: rel,
        reason: 'later-commit-conflict',
        message: `'${rel}' has been changed by a commit made after the tidy commit — undoing it would discard that later work, which this tool never does`,
        commits: await commitsTouching({ run, from: commit, to: head, rel }),
      });
    }

    // ---- branch (a) / NO-CLOBBER: uncommitted divergence, before ANY write -
    const expectations = expectationsFromJournal(applyJournal);
    const { ok: restorable, refused: clobberRefused } = await checkNoClobber({ run, rootPath: root, commit, paths: stillAtCommit, expected: expectations, fs });

    const refused = [...clobberRefused, ...laterCommitRefusals];
    const revertCommand = {
      command: `git -C ${root} revert -n ${commit}`,
      destructive: false,
      note: 'run this yourself to attempt the revert manually and resolve whatever is in the way, in your own terminal',
    };

    // ---- nothing can proceed: refuse, touching nothing -------------------
    if (!restorable.length) {
      const onlyLater = laterCommitRefusals.length > 0 && clobberRefused.length === 0;
      const result = {
        status: UNDO_STATUS.REFUSED,
        code: onlyLater ? UNDO_REFUSAL.LATER_COMMIT_CONFLICT : UNDO_REFUSAL.DIRTY_OVERLAP,
        branch: onlyLater ? UNDO_BRANCH.LATER_COMMIT_CONFLICT : UNDO_BRANCH.DIRTY_OVERLAP,
        commit,
        refused,
        overlapping: clobberRefused.map((r) => r.path),
        conflictingCommits: [...new Set(laterCommitRefusals.flatMap((r) => r.commits.map((c) => c.sha)))],
        revertCommand,
        panel: 'Undo blocked — resolve manually',
        message: `Undo refused: every path this commit touched is in the way (${refused.map((r) => r.path).join(', ')}). NOTHING was written — your working tree and history are exactly as they were. Resolve the listed paths, or run the revert yourself with the command below.`,
      };
      await journal.append('undo-refused', result);
      return result;
    }

    const partial = refused.length > 0;

    // ---- whole-commit cleanliness, tested WITHOUT mutating the checkout ---
    if (!partial) {
      const cleanliness = await testRevertCleanliness({ run, root, commit, parent, head, fs });
      if (!cleanliness.clean) {
        const conflictPaths = cleanliness.conflicts.length ? cleanliness.conflicts : affected;
        const result = {
          status: UNDO_STATUS.REFUSED,
          code: UNDO_REFUSAL.LATER_COMMIT_CONFLICT,
          branch: UNDO_BRANCH.LATER_COMMIT_CONFLICT,
          commit,
          cleanliness,
          conflictingPaths: conflictPaths,
          conflictingCommits: await commitsBetween({ run, from: commit, to: head, paths: conflictPaths }),
          revertCommand,
          panel: 'Undo blocked — resolve manually',
          message: `Undo refused: reverting ${commit.slice(0, 7)} does not apply cleanly on top of the current history (tested with ${cleanliness.method}, without touching your working tree). Nothing was written.`,
        };
        await journal.append('undo-refused', result);
        return result;
      }
    }

    // ---- execute ---------------------------------------------------------
    let revertCommit;
    let realization = null;
    if (!partial) {
      await journal.append('revert', { commit, method: 'git revert --no-edit', state: 'started' });
      const rev = await run(['revert', '--no-edit', commit], { allowFailure: true });
      if (rev.code !== 0) {
        // The cleanliness test said this would apply; it did not. Abort the
        // sequencer so the repository is left exactly as it was found.
        await run(['revert', '--abort'], { allowFailure: true });
        const result = {
          status: UNDO_STATUS.REFUSED,
          code: UNDO_REFUSAL.LATER_COMMIT_CONFLICT,
          branch: UNDO_BRANCH.LATER_COMMIT_CONFLICT,
          commit,
          revertCommand,
          panel: 'Undo blocked — resolve manually',
          stderr: rev.stderr,
          message: `Undo refused: git could not apply the revert (${rev.stderr.trim()}). The revert was aborted, so nothing was written.`,
        };
        await journal.append('undo-refused', result);
        return result;
      }
      revertCommit = (await run(['rev-parse', 'HEAD'])).text.trim();
      await journal.append('revert', { commit, revertCommit, state: 'done' });
    } else {
      const compiled = await compilePartialRevert({ run, root, head, ref, commit, parent, paths: restorable, refused, fs, journal });
      if (compiled.refusal) {
        await journal.append('undo-refused', compiled.refusal);
        return compiled.refusal;
      }
      revertCommit = compiled.revertCommit;
      realization = await realizeWorkingTree({
        run, rootPath: root, commit: revertCommit, paths: restorable,
        gitVersion: git.version || null, strategy: realizeStrategy,
        maxAttempts: maxRealizeAttempts, journal, fs,
      });
    }

    // ---- decision-#8 SAVE compensation, inside the same lock window ------
    const compensated = [];
    for (const rel of savePaths) {
      if (!restorable.includes(rel)) continue;
      const bytes = await revBytes(run, commit, rel);
      if (bytes === null) continue;
      const abs = path.join(root, rel);
      await journal.append('compensate', { path: rel, source: `${commit}:${rel}`, bytes: bytes.length, state: 'started' });
      await fs.mkdir(path.dirname(abs), { recursive: true });
      // Written to the WORKING TREE ONLY — the index keeps the reverted state,
      // so the path comes back exactly as it was pre-Apply: unstaged.
      await fs.writeFile(abs, bytes);
      await journal.append('compensate', { path: rel, state: 'done' });
      compensated.push({ path: rel, bytes: bytes.length, staged: false, note: 'restored to the working tree UNSTAGED — the exact pre-Apply state' });
    }

    // ---- the Trash half of the same Apply, moved back --------------------
    // Same lock window, same journal discipline, same no-clobber rule: a path
    // the user has since recreated is refused rather than overwritten, and the
    // rest still come back.
    let trashRestore = null;
    if (effectiveRunId) {
      const { journal: ledger } = await readTrashLedger({ reportDir, runId: effectiveRunId, fs });
      if (ledger) {
        await journal.append('trash-restore', { runId: effectiveRunId, state: 'started' });
        trashRestore = await restoreFromTrash({ rootPath: root, reportDir, runId: effectiveRunId, fs, now });
        await journal.append('trash-restore', {
          runId: effectiveRunId, state: 'done', status: trashRestore.status,
          restored: trashRestore.restored.map((r) => r.path),
          refused: trashRestore.refused,
        });
      }
    }
    const trashRefused = trashRestore ? trashRestore.refused : [];

    const branch = partial
      ? UNDO_BRANCH.PARTIAL
      : (head === commit ? UNDO_BRANCH.CLEAN_REVERT : UNDO_BRANCH.HEAD_MOVED_CLEAN);

    const result = {
      status: (partial || trashRefused.length) ? UNDO_STATUS.PARTIAL : UNDO_STATUS.REVERTED,
      branch,
      commit,
      revertCommit,
      restored: restorable,
      refused,
      compensated,
      trash: trashRestore
        ? { status: trashRestore.status, restored: trashRestore.restored, refused: trashRestore.refused, dir: trashRestore.dir }
        : null,
      realization,
      ...(refused.length ? { revertCommand, panel: 'Undo blocked — resolve manually (for the refused paths)' } : {}),
      journal: { dir: journal.dir, file: journal.file },
      message: [
        partial
          ? `partially undone: ${restorable.length} path(s) restored in one commit ${String(revertCommit).slice(0, 7)}; ${refused.length} path(s) REFUSED and left exactly as they are (${refused.map((r) => r.path).join(', ')}) — nothing you created or edited after the Apply was overwritten`
          : `undone: ${commit.slice(0, 7)} reverted as ${String(revertCommit).slice(0, 7)}${compensated.length ? `, and ${compensated.length} SAVE'd path(s) re-materialised into the working tree unstaged (decision #8)` : ''}`,
        trashRestore
          ? (trashRefused.length
            ? `${trashRestore.restored.length} file(s) restored from the Trash, ${trashRefused.length} REFUSED and left in it (${trashRefused.map((r) => r.path).join(', ')})`
            : `${trashRestore.restored.length} file(s) restored from the Trash to their original paths`)
          : null,
      ].filter(Boolean).join('; '),
    };
    await journal.append('undo-done', result);
    await journal.writeSummary({ ...result, at: now().toISOString() });
    return result;
  } finally {
    await lock.release().catch(() => {});
  }
}

/**
 * Undo an Apply that had no git half: restore its Trash move-set.
 *
 * Under the same project lock as every other mutating operation, so a restore
 * and a scan (or a second restore) cannot interleave on one root.
 */
async function undoTrashOnly({ root, reportDir, runId, fs, now, jobId }) {
  const lock = await acquireLock({ reportDir, jobId, purpose: 'undo', fs, now });
  if (!lock.ok) {
    return { status: UNDO_STATUS.REFUSED, code: UNDO_REFUSAL.LOCK_HELD, message: lock.message, holder: lock.holder };
  }
  const journal = await openJournal({ reportDir, runId, kind: 'undo', fs, now });
  try {
    await journal.append('undo-start', { runId, branch: UNDO_BRANCH.TRASH_RESTORE, git: null });
    const restore = await restoreFromTrash({ rootPath: root, reportDir, runId, fs, now });
    const result = {
      status: restore.status === TRASH_STATUS.REFUSED
        ? UNDO_STATUS.REFUSED
        : (restore.refused.length ? UNDO_STATUS.PARTIAL : UNDO_STATUS.RESTORED),
      branch: UNDO_BRANCH.TRASH_RESTORE,
      commit: null,
      runId,
      restored: restore.restored.map((r) => r.path),
      refused: restore.refused,
      trash: { status: restore.status, restored: restore.restored, refused: restore.refused, dir: restore.dir },
      journal: { dir: journal.dir, file: journal.file },
      message: restore.message,
    };
    await journal.append('undo-done', result);
    await journal.writeSummary({ ...result, at: now().toISOString() });
    return result;
  } finally {
    await lock.release().catch(() => {});
  }
}

/** Every affected path already matches its pre-Apply blob at HEAD. */
async function isAlreadyReverted({ run, head, parent, paths }) {
  if (!paths.length) return true;
  for (const rel of paths) {
    const atHead = await revBlob(run, head, rel);
    const atParent = await revBlob(run, parent, rel);
    if (atHead !== atParent) return false;
  }
  return true;
}

/**
 * Is a whole-commit revert clean? Tested WITHOUT touching the user's checkout:
 * `git merge-tree --write-tree` where available, otherwise a disposable temp
 * worktree. Never `revert --no-commit` on the live tree.
 */
export async function testRevertCleanliness({ run, root, commit, parent, head, fs = fsp }) {
  const mt = await run(['merge-tree', '--write-tree', `--merge-base=${commit}`, head, parent], { allowFailure: true });
  if (mt.code === 0) return { clean: true, method: 'git merge-tree --write-tree', conflicts: [] };
  if (mt.code === 1) {
    return { clean: false, method: 'git merge-tree --write-tree', conflicts: parseMergeTreeConflicts(mt.text), detail: mt.text };
  }

  // git < 2.38 (or an unsupported invocation): a DISPOSABLE temp worktree. The
  // dry-run happens there and only there; the user's checkout is never the
  // experiment. `-C <dir>` after the runner's own `-C <root>` is cumulative, and
  // dir is absolute, so this runs inside the probe worktree.
  const dir = path.join(root, '.git', 'tidy-idy-undo-probe');
  await fs.rm(dir, { recursive: true, force: true }).catch(() => {});
  const add = await run(['worktree', 'add', '--detach', '--force', dir, head], { allowFailure: true });
  if (add.code !== 0) {
    // Cannot PROVE cleanliness ⇒ must not claim it.
    return { clean: false, method: 'temp-worktree (unavailable)', conflicts: [], detail: add.stderr };
  }
  try {
    const probe = await run(['-C', dir, 'revert', '--no-commit', commit], { allowFailure: true });
    await run(['-C', dir, 'revert', '--abort'], { allowFailure: true });
    if (probe.code === 0) return { clean: true, method: 'disposable temp worktree dry-run', conflicts: [] };
    return { clean: false, method: 'disposable temp worktree dry-run', conflicts: parseMergeTreeConflicts(probe.stderr), detail: probe.stderr };
  } finally {
    await run(['worktree', 'remove', '--force', dir], { allowFailure: true });
    await fs.rm(dir, { recursive: true, force: true }).catch(() => {});
    await run(['worktree', 'prune'], { allowFailure: true });
  }
}

function parseMergeTreeConflicts(text) {
  const paths = new Set();
  for (const line of String(text).split('\n')) {
    const m = /^CONFLICT \([^)]*\): (?:Merge conflict in )?(.+)$/.exec(line.trim());
    if (m && m[1]) paths.add(m[1].trim());
  }
  return [...paths];
}

async function commitsTouching({ run, from, to, rel }) {
  const r = await run(['log', '--format=%H%x09%s', `${from}..${to}`, '--', rel], { allowFailure: true });
  if (r.code !== 0) return [];
  return r.text.split('\n').filter(Boolean).map((line) => {
    const tab = line.indexOf('\t');
    return tab === -1
      ? { sha: line.trim(), subject: null }
      : { sha: line.slice(0, tab), subject: line.slice(tab + 1) };
  });
}

async function commitsBetween({ run, from, to, paths }) {
  const seen = new Map();
  for (const rel of paths) {
    for (const c of await commitsTouching({ run, from, to, rel })) {
      if (!seen.has(c.sha)) seen.set(c.sha, { ...c, paths: [] });
      seen.get(c.sha).paths.push(rel);
    }
  }
  return [...seen.values()];
}

/** `<rev>:<path>` as {mode, type, sha}, or null. */
async function treeEntry(run, rev, rel) {
  const r = await run(['ls-tree', '-z', rev, '--', rel], { allowFailure: true });
  if (r.code !== 0) return null;
  const line = r.text.split('\0').find((s) => s.length > 0);
  if (!line) return null;
  const tab = line.indexOf('\t');
  const meta = line.slice(0, tab).split(/\s+/);
  return { mode: meta[0], type: meta[1], sha: meta[2] };
}

/**
 * A path-restricted revert, compiled exactly the way Apply compiles a plan: one
 * temp index seeded from HEAD, one commit, one compare-and-swap. Refused paths
 * appear in no step, so they cannot be touched even by accident.
 */
async function compilePartialRevert({ run, root, head, ref, commit, parent, paths, refused, fs, journal }) {
  await journal.append('partial-revert-plan', { commit, parent, restoring: paths, refusing: refused.map((r) => r.path) });

  const tree = await withTempIndex({ run, head, fs }, async (idx) => {
    for (const rel of paths) {
      const entry = await treeEntry(run, parent, rel);
      if (entry && entry.type === 'blob') await idx.setEntry(rel, entry.mode, entry.sha);
      else await idx.removeEntry(rel);
    }
    return idx.writeTree();
  });

  const message = [
    `Revert "tidy-idy ${commit.slice(0, 7)}" (PARTIAL)`,
    '',
    `This reverts ${paths.length} path(s) of tidy-idy commit ${commit}.`,
    `${refused.length} path(s) were REFUSED and left untouched by the no-clobber invariant:`,
    ...refused.map((r) => `  - ${r.path}: ${r.reason}`),
    '',
    'A whole-commit `git revert` was not used because it is all-or-nothing and would have overwritten the refused paths.',
  ].join('\n');

  const revertCommit = (await run(['commit-tree', tree, '-p', head, '-m', message])).text.trim();
  const cas = await run(['update-ref', ref, revertCommit, head], { allowFailure: true });
  if (cas.code !== 0) {
    return {
      refusal: {
        status: UNDO_STATUS.REFUSED,
        code: UNDO_REFUSAL.REF_RACE,
        commit,
        message: 'Undo refused: the branch moved while the partial revert was being compiled, so the compare-and-swap failed. Nothing was applied.',
      },
    };
  }
  await journal.append('partial-revert-commit', { revertCommit, tree, parent: head });
  return { revertCommit };
}

/** SAVE paths of the tidy commit, from its plan trailer or from the journal. */
function savePathsOf(plan, applyJournal) {
  const fromTrailer = plan && Array.isArray(plan.ops)
    ? plan.ops.filter((o) => o.kind === OP_KIND.SAVE).map((o) => o.path)
    : [];
  if (fromTrailer.length) return fromTrailer;
  if (!applyJournal) return [];
  return applyJournal.records.filter((r) => r.type === 'op-result' && r.kind === OP_KIND.SAVE).map((r) => r.path);
}

async function loadApplyJournal({ reportDir, runId, commit, fs }) {
  if (runId) {
    const j = await readJournal({ reportDir, runId, kind: 'apply', fs });
    if (j) return j;
  }
  return findJournalForCommit({ reportDir, commit, kind: 'apply', fs });
}

export default { undoApply, testRevertCleanliness, UNDO_STATUS, UNDO_BRANCH, UNDO_REFUSAL };

// engine/apply/executor.mjs — Wave 3: the only code that mutates content.
//
// WAVE 4 (Amendment A) WIDENED WHAT "ONE APPLY" MEANS, without adding a second
// pipeline: an Apply is ONE git commit for the content git holds PLUS ONE atomic
// journaled Trash move-set for the content it does not — approved together,
// revalidated together, and each reversible on its own terms (`git revert` /
// restore-from-Trash). A folder with no repository is therefore no longer
// refused outright: it simply has no git half.
//
// The canonical Apply pipeline (MASTER-PLAN, normative state-transition table),
// implemented verbatim and in order:
//
//   1. Acquire the project-root lock; assert HEAD == S.head.
//   2. Revalidate every approved finding against S; mismatches drop as stale.
//   3. Compile all survivors into ONE temporary index seeded from H's tree —
//      zero working-tree writes. Any failure aborts ALL.
//   4. Write exactly ONE commit C via commit-tree; advance the branch with a
//      compare-and-swap update-ref.
//   5. Realize the working tree and reconcile the user's index with the single
//      native mechanism, journaled and retried.
//
// Everything before step 4 is reversible by doing nothing (a scratch index file
// is deleted). Everything after it is reversible by `git revert` (plus the
// decision-#8 SAVE compensation), because git holds the content. There is no
// window in which content exists only in the working tree and only in this
// process's memory — which is the property the whole design is arranged around.
//
// A refusal is ALWAYS machine-readable and always names what it refused. "It
// didn't work" is the one failure mode a tool with delete permissions may never
// have.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { DEFAULT_PROTECTION, ACTIONABLE_ACTIONS } from '../protection.mjs';
import { loadPorcelain } from '../porcelain.mjs';
import { reportDirFor } from '../report-dir.mjs';
import { toPosixRel } from '../glob.mjs';

import { makeGitRunner, revBytes } from './git-plumbing.mjs';
import { resolveApprovals, stampFindingIds } from './identity.mjs';
import { openJournal } from './journal.mjs';
import { revalidateFindings, assertHeadMatchesSnapshot } from './revalidate.mjs';
import { planFromFindings, opPaths, declaredTransitions, findCaseCollisions, buildCommitMessage, OP_KIND } from './plan.mjs';
import { withTempIndex, modeForPath } from './temp-index.mjs';
import { realizeWorkingTree, REALIZE_STRATEGY } from './realize.mjs';
import { capturePorcelainClasses, diffPorcelainClasses } from './consent-scope.mjs';
import { preflightTrashMoveSet, executeTrashMoveSet, TRASH_STATUS } from './trash.mjs';
// B5 P4: single entry-lock preflight (consult + acquire) — panel/library cannot bypass.
import { ensureApplyEntryLock, ENTRY_LOCK_CODE } from '../launch/lock-authority.mjs';

export const APPLY_REFUSAL = Object.freeze({
  NO_GIT: 'ADVISORY_MODE_NO_GIT',
  NO_HEAD: 'NO_HEAD_COMMIT',
  DETACHED_HEAD: 'DETACHED_HEAD',
  HEAD_MOVED: 'HEAD_MOVED_SINCE_SNAPSHOT',
  REF_RACE: 'REF_COMPARE_AND_SWAP_FAILED',
  PROTECTED_PATH: 'PROTECTED_PATH_IN_REQUEST',
  UNMATCHED_ID: 'UNMATCHED_FINDING_ID',
  LOCK_HELD: 'LOCK_HELD',
  /** Missing/unlocked entry lock when acquire is not allowed (B5 P4 / SC4). */
  ENTRY_LOCK_REQUIRED: ENTRY_LOCK_CODE.ENTRY_LOCK_REQUIRED,
  ALREADY_APPLIED: 'RUN_ALREADY_APPLIED',
  UNSUPPORTED_OP: 'UNSUPPORTED_OP',
  TRASH_PREFLIGHT: 'TRASH_PREFLIGHT_FAILED',
  CASE_COLLISION: 'CASE_COLLISION_REFUSED',
  COMPILE_FAILED: 'COMPILE_FAILED_ABORT_ALL',
});

export const APPLY_STATUS = Object.freeze({
  APPLIED: 'applied',
  /** Both halves ran but the Trash move-set did not complete. Loud, per-path. */
  PARTIAL: 'partial',
  NO_OP: 'no-op',
  REFUSED: 'refused',
});

function refuse(code, message, extra = {}) {
  return { status: APPLY_STATUS.REFUSED, code, message, commit: null, ops: [], stale: [], ...extra };
}

/**
 * Apply an approved subset of a run's findings as exactly ONE commit — or as
 * nothing at all.
 *
 * @param {{rootPath: string, git: object|null, runId: string, snapshot: object,
 *   findings: object[], approvals: any[], protection?: object, reportDir?: string,
 *   ruleset?: object|null, jobId?: string|null, trashExecutor?: Function|null,
 *   realizeStrategy?: string, maxRealizeAttempts?: number, fs?: object,
 *   env?: object, run?: Function, now?: Function, requireFullIdentity?: boolean,
 *   isAlive?: Function, allowAcquire?: boolean, lock?: object|null}} opts
 */
export async function applyApproved(opts = {}) {
  const {
    rootPath,
    git,
    runId,
    snapshot = null,
    findings = [],
    approvals = [],
    protection = DEFAULT_PROTECTION,
    ruleset = null,
    jobId = null,
    trashExecutor = null,
    realizeStrategy = REALIZE_STRATEGY.NO_OVERLAY,
    maxRealizeAttempts = 3,
    fs = fsp,
    env = process.env,
    now = () => new Date(),
    requireFullIdentity = true,
    isAlive = undefined,
    /**
     * When false, Apply will not call acquireLock — missing borrow →
     * ENTRY_LOCK_REQUIRED. Default true (library path may acquire).
     */
    allowAcquire = true,
    /**
     * A lock this caller ALREADY holds over the same project root, borrowed for
     * the duration of this Apply.
     *
     * The Wave-6 panel is the caller that needs it: the launcher takes the
     * project lock before the scan and holds it for the panel's whole lifetime
     * (that is what makes "Apply later, from the panel" safe), so a panel-driven
     * Apply that acquired the lock again would contend with its own launcher and
     * refuse itself with LOCK_HELD forever. A borrowed lock is never released
     * here — the owner that took it is the owner that drops it.
     */
    lock: borrowedLock = null,
  } = opts;

  const root = path.resolve(rootPath);
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : reportDirFor(root);

  // ---- git:null contract, as Amendment A left it -------------------------
  // Wave 1 declared "no repo ⇒ Apply refuses", because without git there is no
  // `git revert` and therefore no undo. Amendment A supplied the missing undo:
  // content git does not hold is REMOVED BY MOVING IT INTO THE REVERSIBLE TRASH,
  // whose undo is a journaled move-back. So a repo-less Apply is no longer
  // refused wholesale — it is refused only for the operations that genuinely
  // need git (below, once the plan is compiled and we know which those are).
  // Bootstrap remains an optional upgrade, never a gate.
  const run = opts.run || makeGitRunner({ root, env });

  // ---- identity: approvals must round-trip in full -----------------------
  stampFindingIds(findings, runId);
  const { approved, refusals } = resolveApprovals({ runId, findings, approvals, requireFullIdentity });
  if (refusals.length) {
    return refuse(APPLY_REFUSAL.UNMATCHED_ID,
      `Apply refuses ${refusals.length} approval(s) it cannot match exactly to a finding of run ${runId} — and refuses the whole request rather than applying the rest: an unmatched ID is a stale tab, a bug or an attack, and none of those is a reason to proceed.`,
      { refusals });
  }
  if (!approved.length) {
    return { status: APPLY_STATUS.NO_OP, code: null, message: 'no findings were approved — nothing to apply', commit: null, ops: [], stale: [] };
  }

  // ---- protection, re-run inside Apply as defence in depth ---------------
  // Same module as Wave 1, second call site. The scan already filtered these
  // out; this catches a request that never came from a scan.
  const protectedHits = approved
    .filter((f) => ACTIONABLE_ACTIONS.has(f.action))
    .map((f) => ({ finding: f, verdict: protection.classify(f.path) }))
    .filter((h) => h.verdict.protected);
  if (protectedHits.length) {
    return refuse(APPLY_REFUSAL.PROTECTED_PATH,
      `Apply refuses: ${protectedHits.length} approved operation(s) target PROTECTED path(s). Protection is deny-by-default and is enforced twice — once before a finding is ever emitted, and again here — so a request that reached Apply with a protected path in it never came from a rendered tile.`,
      { protectedPaths: protectedHits.map((h) => ({ path: h.finding.path, action: h.finding.action, pattern: h.verdict.pattern, class: h.verdict.class, why: h.verdict.why })) });
  }

  // ---- git:null contract, checked as REQUEST COHERENCE -------------------
  // Whether an operation needs git is a property of the REQUEST, not of whether
  // this run was applied before — so an operation that genuinely needs git in a
  // folder with no repository is refused HERE, alongside the other pre-lock
  // request-validation refusals (UNMATCHED_ID, PROTECTED_PATH), rather than
  // being masked by the one-Apply idempotency guard below. Removals of content
  // git does not hold are unaffected: they compile to Trash ops, which need no
  // repository. (The post-compile check below is the second layer for survivors.)
  if (!git) {
    const { ops: plannedOps } = planFromFindings({ findings: approved, runId });
    const needGit = plannedOps.filter((op) => op.kind !== OP_KIND.TRASH);
    if (needGit.length) {
      return refuse(APPLY_REFUSAL.NO_GIT,
        `Apply refuses ${needGit.length} approved operation(s) that require a repository (${needGit.map((op) => `${op.kind} ${op.path}`).join(', ')}): without git there is no commit to hold the content and no \`git revert\` to take it back, and this tool does not make changes it cannot undo. Removals of content git does not hold are unaffected — they move into the reversible Trash — and \`git init\` (Bootstrap) is an optional upgrade the preflight proposes, never a gate.`,
        { advisory: true, gitOps: needGit.map((op) => ({ id: op.id, kind: op.kind, path: op.path })) });
    }
  }

  // ---- step 1: entry/apply lock preflight (B5 P4) ------------------------
  // Sole gate: ensureApplyEntryLock (consultTidyLock + borrow/acquireLock).
  // Unlocked / missing / foreign → structured refuse, ops empty, no trash/
  // commit/fs mutation of the fixture content. Panel + library share this path.
  const entryOpts = {
    rootPath: root,
    reportDir,
    lock: borrowedLock,
    jobId,
    purpose: 'apply',
    fs,
    now,
    allowAcquire,
  };
  if (typeof isAlive === 'function') entryOpts.isAlive = isAlive;
  const entry = await ensureApplyEntryLock(entryOpts);
  if (!entry.ok) {
    const code = entry.code === ENTRY_LOCK_CODE.ENTRY_LOCK_REQUIRED
      ? APPLY_REFUSAL.ENTRY_LOCK_REQUIRED
      : APPLY_REFUSAL.LOCK_HELD;
    return refuse(code, entry.message, {
      holder: entry.holder || null,
      consult: entry.consult || null,
    });
  }
  const lock = entry.lock;
  const borrowed = entry.borrowed === true;

  let journal = null;
  try {
    // ONE Apply per run. The panel's state machine (Wave 6) enforces this over
    // HTTP; the journal enforces it here, so a library caller cannot double-apply
    // by retrying. A PARTIAL Apply is deliberately NOT sealed: an interrupted
    // Trash move-set is meant to be retried, and the trash journal makes that
    // retry idempotent rather than duplicative.
    const priorSummary = await readJsonOrNull(fs, path.join(reportDir, 'apply', String(runId), 'summary.json'));
    if (priorSummary && priorSummary.status === APPLY_STATUS.APPLIED) {
      return refuse(APPLY_REFUSAL.ALREADY_APPLIED,
        `run ${runId} has already been applied (commit ${priorSummary.commit}) — one Apply per run; re-scan to pick up whatever is left`,
        { commit: priorSummary.commit, priorSummary });
    }

    journal = await openJournal({ reportDir, runId, fs, now });
    if (lock.stolenFrom) await journal.append('lock-stolen', { stolenFrom: lock.stolenFrom });

    // ---- step 1 (cont.): HEAD == S.head, asserted UNDER the lock ---------
    // Skipped entirely without a repository: there is no HEAD to move, and S
    // records none. The Trash half's equivalent guarantee is per-path content
    // revalidation below, which runs on both paths.
    let head = null;
    let ref = null;
    if (git) {
      const headRes = await run(['rev-parse', 'HEAD'], { allowFailure: true });
      head = headRes.code === 0 ? headRes.text.trim() : null;
      if (!head) {
        return refuse(APPLY_REFUSAL.NO_HEAD, 'this repository has no commits yet, so there is no tree for a compiled plan to be a delta on — commit something (or run Bootstrap) and re-scan');
      }

      const symRes = await run(['symbolic-ref', '--quiet', 'HEAD'], { allowFailure: true });
      ref = symRes.code === 0 ? symRes.text.trim() : null;
      if (!ref) {
        return refuse(APPLY_REFUSAL.DETACHED_HEAD, 'HEAD is detached. A tidy commit here would not be reachable from any branch, and the undo story ("git revert the tidy commit on the branch you were on") would be a lie — v1 refuses instead of guessing which branch you meant.');
      }

      const headCheck = assertHeadMatchesSnapshot(head, snapshot);
      if (!headCheck.ok) {
        return refuse(APPLY_REFUSAL.HEAD_MOVED, headCheck.message, { snapshotHead: headCheck.snapshotHead || null, currentHead: head });
      }
    }

    // ---- step 2: revalidate against S ------------------------------------
    const porcelain = git ? await loadPorcelain({ git, state: {} }) : null;
    const { survivors, stale } = await revalidateFindings({ findings: approved, snapshot, porcelain, rootPath: root, fs });
    await journal.append('revalidated', { approved: approved.length, survivors: survivors.length, stale });

    if (!survivors.length) {
      const result = {
        status: APPLY_STATUS.NO_OP,
        code: null,
        commit: null,
        ops: [],
        stale,
        message: `every approved finding was dropped as 'stale — re-run': the tree changed after the scan, so nothing was committed`,
        journal: { dir: journal.dir, file: journal.file },
      };
      await journal.writeSummary({ ...result, runId, at: now().toISOString() });
      return result;
    }

    // ---- plan compilation, before anything is touched --------------------
    const { ops, unsupported } = planFromFindings({ findings: survivors, runId });
    if (unsupported.length) {
      return refuse(APPLY_REFUSAL.UNSUPPORTED_OP,
        `Apply refuses: ${unsupported.length} approved operation(s) have no compiled form in this executor. An approved tile that silently does nothing is worse than a refusal, so the whole Apply aborts.`,
        { unsupported });
    }

    // ---- the two halves of one Apply -------------------------------------
    // Amendment A: "one Apply" is ONE git commit for content git holds PLUS ONE
    // atomic journaled Trash move-set for content it does not. Both halves are
    // compiled and revalidated together (above), and both are reversible.
    const trashOps = ops.filter((op) => op.kind === OP_KIND.TRASH);
    const gitOps = ops.filter((op) => op.kind !== OP_KIND.TRASH);

    if (!git && gitOps.length) {
      return refuse(APPLY_REFUSAL.NO_GIT,
        `Apply refuses ${gitOps.length} approved operation(s) that require a repository (${gitOps.map((op) => `${op.kind} ${op.path}`).join(', ')}): without git there is no commit to hold the content and no \`git revert\` to take it back, and this tool does not make changes it cannot undo. Removals of content git does not hold are unaffected — they move into the reversible Trash — and \`git init\` (Bootstrap) is an optional upgrade the preflight proposes, never a gate.`,
        { advisory: true, gitOps: gitOps.map((op) => ({ id: op.id, kind: op.kind, path: op.path })) });
    }

    const ignorecase = await probeIgnorecase(run, git);
    const collisions = findCaseCollisions({ ops, existingPaths: Object.keys((snapshot && snapshot.paths) || {}), ignorecase });
    if (collisions.length) {
      return refuse(APPLY_REFUSAL.CASE_COLLISION,
        `Apply refuses: this filesystem is case-insensitive (core.ignorecase=true) and the plan contains path(s) that differ only in case. git and the filesystem would disagree about what exists, and the loser would be whichever content was written second.`,
        { collisions });
    }

    // ---- the Trash half's pre-flight, BEFORE anything is mutated ---------
    // Everything about a Trash move that is knowable in advance is decided here,
    // next to the temp-index compile and with the same consequence: a failure
    // aborts the WHOLE Apply with nothing moved and nothing committed.
    let trashPlan = null;
    if (trashOps.length && !trashExecutor) {
      trashPlan = await preflightTrashMoveSet({ rootPath: root, reportDir, runId, ops: trashOps, fs });
      if (!trashPlan.ok) {
        await journal.append('aborted', { stage: 'trash-preflight', problems: trashPlan.problems });
        const result = refuse(APPLY_REFUSAL.TRASH_PREFLIGHT,
          `Apply aborted before touching anything: ${trashPlan.problems.length} approved Trash removal(s) cannot be performed (${trashPlan.problems.map((p) => `${p.path}: ${p.code}`).join('; ')}). One Apply is all-or-nothing, so NOTHING was committed and NOTHING was moved.`,
          { trashProblems: trashPlan.problems, stale, journal: { dir: journal.dir, file: journal.file } });
        await journal.writeSummary({ ...result, runId, at: now().toISOString() });
        return result;
      }
    }

    const classesBefore = await capturePorcelainClasses({ git });
    await journal.append('plan', {
      head,
      ref,
      ignorecase,
      gitOps: gitOps.length,
      trashOps: trashOps.length,
      ops: ops.map((op) => ({ id: op.id, kind: op.kind, path: op.path, from: op.from || null, to: op.to || null, summary: op.summary })),
    });

    // ---- steps 3 & 4: compile in a temp index, then ONE commit -----------
    let compiled = { tree: null, results: [] };
    if (gitOps.length) {
      try {
        compiled = await withTempIndex({ run, head, fs }, async (idx) => {
          const results = [];
          for (const op of gitOps) {
            results.push(await compileOp({ idx, op, run, rootPath: root, head, fs }));
          }
          const tree = await idx.writeTree();
          return { tree, results };
        });
      } catch (err) {
        // ABORT ALL. The temp index is already gone (withTempIndex's finally), no
        // commit exists, nothing has been moved to the Trash, and neither the
        // working tree nor the user's index has been touched at any point.
        await journal.append('aborted', { error: err.message, stage: 'compile' });
        const result = refuse(APPLY_REFUSAL.COMPILE_FAILED,
          `Apply aborted during plan compilation: ${err.message}. NOTHING was committed and NOTHING was written — the temp index was discarded, no file was moved to the Trash, and your working tree and index are bit-identical to what they were before you pressed Apply. Re-scan and try again.`,
          { stale, journal: { dir: journal.dir, file: journal.file } });
        await journal.writeSummary({ ...result, runId, at: now().toISOString() });
        return result;
      }
    }

    // ---- the git half: exactly one commit, or none -----------------------
    let commit = null;
    let realization = null;
    const headTree = git ? (await run(['rev-parse', `${head}^{tree}`])).text.trim() : null;
    const treeChanged = Boolean(gitOps.length && compiled.tree && compiled.tree !== headTree);

    if (gitOps.length && !treeChanged && !trashOps.length) {
      const result = {
        status: APPLY_STATUS.NO_OP,
        code: null,
        commit: null,
        ops: compiled.results,
        stale,
        message: 'the compiled plan produces a tree identical to HEAD — there is nothing to commit, so no empty commit was created',
        journal: { dir: journal.dir, file: journal.file },
      };
      await journal.writeSummary({ ...result, runId, at: now().toISOString() });
      return result;
    }

    if (treeChanged) {
      const message = buildCommitMessage({ runId, ops: gitOps, rulesetVersion: ruleset ? ruleset.version : null });
      commit = (await run(['commit-tree', compiled.tree, '-p', head, '-m', message])).text.trim();
      await journal.append('commit', { commit, tree: compiled.tree, parent: head, ref });

      // Compare-and-swap: the ONLY way the branch moves. If HEAD advanced between
      // the assertion above and this line, the update fails and we have written an
      // unreferenced commit object — harmless, collectable, and NOT a mutation of
      // anything the user can see. Nothing has been moved to the Trash yet either,
      // which is exactly why the commit goes first.
      const cas = await run(['update-ref', ref, commit, head], { allowFailure: true });
      if (cas.code !== 0) {
        await journal.append('ref-race', { commit, expected: head, stderr: cas.stderr });
        const result = refuse(APPLY_REFUSAL.REF_RACE,
          `Apply refuses: the branch moved between revalidation and the ref update, so the compare-and-swap failed. Nothing was applied — the commit object that was written is unreferenced, no file was moved to the Trash, and nothing changed. Re-scan and approve again.`,
          { attemptedCommit: commit, expectedHead: head, stale, journal: { dir: journal.dir, file: journal.file } });
        await journal.writeSummary({ ...result, runId, at: now().toISOString() });
        return result;
      }

      // ---- step 5: realize the working tree + user index -----------------
      const pathspecs = [...new Set(gitOps.flatMap(opPaths))];
      realization = await realizeWorkingTree({
        run, rootPath: root, commit, paths: pathspecs,
        gitVersion: git.version || null,
        strategy: realizeStrategy,
        maxAttempts: maxRealizeAttempts,
        journal, fs,
      });
    }

    // ---- the Trash half: one atomic journaled move-set -------------------
    // After the commit, deliberately. The commit is durable and revertible the
    // instant update-ref returns; the move-set is journaled and restorable the
    // instant it starts. Ordering them this way means the only window that can
    // ever exist is "committed, moves outstanding" — which the trash journal
    // describes per path and a retry resumes — rather than "files moved, commit
    // lost", which nothing could describe.
    let trash = null;
    if (trashOps.length) {
      trash = trashExecutor
        ? await trashExecutor({ rootPath: root, reportDir, runId, ops: trashOps, fs, now, applyJournal: journal })
        : await executeTrashMoveSet({ rootPath: root, reportDir, runId, ops: trashOps, fs, now, applyJournal: journal });

      for (const m of trash.moved || []) {
        compiled.results.push({
          id: (trashOps.find((op) => op.path === m.path) || {}).id || null,
          kind: OP_KIND.TRASH, path: m.path, result: 'ok',
          trashPath: m.trashPath || null, hash: m.hash || null,
          expectedAfter: { path: m.path, exists: false },
        });
      }
      for (const f of trash.failed || []) {
        compiled.results.push({
          id: (trashOps.find((op) => op.path === f.path) || {}).id || null,
          kind: OP_KIND.TRASH, path: f.path, result: 'failed', code: f.code, message: f.message,
          expectedAfter: { path: f.path, exists: true },
        });
      }
    }

    for (const opResult of compiled.results) {
      await journal.append('op-result', { ...opResult, commit, expectedAfter: opResult.expectedAfter });
    }

    // ---- the consent-scope invariant, asserted on the real repository ----
    // Captured after BOTH halves: a Trash removal takes an untracked path to
    // absent, which its tile declared, and the diff must see that as declared
    // rather than as an undeclared class change.
    const classesAfter = await capturePorcelainClasses({ git });
    const consentScope = diffPorcelainClasses({ before: classesBefore, after: classesAfter, declared: declaredTransitions(ops) });
    await journal.append('consent-scope', consentScope);

    const trashIncomplete = Boolean(trash && trash.status !== TRASH_STATUS.OK && trash.status !== TRASH_STATUS.NO_OP);
    const realizeIncomplete = Boolean(realization && !realization.complete);

    const result = {
      status: trashIncomplete ? APPLY_STATUS.PARTIAL : APPLY_STATUS.APPLIED,
      code: null,
      runId,
      commit,
      parent: commit ? head : null,
      ref: commit ? ref : null,
      branch: commit ? ref.replace(/^refs\/heads\//, '') : null,
      ops: compiled.results,
      stale,
      realization,
      consentScope,
      trash: trash
        ? { status: trash.status, dir: trash.dir, moved: trash.moved, failed: trash.failed, resumed: trash.resumed || 0, journal: trash.journal || null }
        : null,
      journal: { dir: journal.dir, file: journal.file },
      undo: {
        available: true,
        how: [
          commit ? 'git revert of this single commit, plus re-materialisation of any SAVE path into the working tree unstaged (decision #8)' : null,
          trash && (trash.moved || []).length ? 'restore-from-Trash — a journaled move-back of every file this Apply moved (Amendment A)' : null,
        ].filter(Boolean).join('; '),
        command: commit ? `git -C ${root} revert -n ${commit}` : null,
        trashRunId: trash && (trash.moved || []).length ? runId : null,
      },
      message: buildResultMessage({ commit, compiled, stale, trash, trashIncomplete, realization, realizeIncomplete }),
    };
    await journal.writeSummary({ ...result, at: now().toISOString() });
    return result;
  } finally {
    // A borrowed lock outlives this Apply by design: releasing it here would
    // drop the panel's hold on the project the moment the first Apply returned.
    if (!borrowed) await lock.release().catch(() => {});
  }
}

/** Compile ONE operation into the temp index. Throwing here aborts everything. */
async function compileOp({ idx, op, run, rootPath, head, fs }) {
  switch (op.kind) {
    case OP_KIND.REMOVE: {
      const entry = await idx.entry(op.path);
      if (!entry) throw new Error(`cannot remove '${op.path}': git does not track it at HEAD, so a removal here would not be undoable by reverting the tidy commit`);
      await idx.removeEntry(op.path);
      return { id: op.id, kind: op.kind, path: op.path, result: 'ok', blobAtHead: entry.sha, expectedAfter: { path: op.path, exists: false } };
    }

    case OP_KIND.SAVE: {
      // Read at compile time, under the lock, AFTER revalidation proved the
      // bytes still hash to what the tile showed.
      const content = await fs.readFile(path.join(rootPath, op.path));
      const sha = await idx.hashObject(content);
      const mode = await modeForPath({ idx, rootPath, rel: op.path, fs });
      await idx.setEntry(op.path, mode, sha);
      return { id: op.id, kind: op.kind, path: op.path, result: 'ok', blob: sha, bytes: content.length, expectedAfter: { path: op.path, exists: true, blob: sha } };
    }

    case OP_KIND.WRITE: {
      // Amendment C.iv: the approved bytes, hashed FROM MEMORY. A re-read of the
      // working tree here would be a second chance for what gets committed to
      // differ from what a human read on the tile.
      const sha = await idx.hashObject(op.content);
      const mode = await modeForPath({ idx, rootPath, rel: op.path, fs });
      await idx.setEntry(op.path, mode, sha);
      return { id: op.id, kind: op.kind, path: op.path, result: 'ok', blob: sha, bytes: op.content.length, source: 'in-memory approved content', expectedAfter: { path: op.path, exists: true, blob: sha } };
    }

    case OP_KIND.GITIGNORE: {
      const before = await readGitignore({ run, rootPath, head, fs });
      const alreadyPresent = before.split('\n').some((l) => l.trim() === op.gitignoreLine);
      const separator = before === '' || before.endsWith('\n') ? '' : '\n';
      const after = alreadyPresent ? before : `${before}${separator}${op.gitignoreLine}\n`;
      const sha = await idx.hashObject(Buffer.from(after, 'utf8'));
      const mode = await modeForPath({ idx, rootPath, rel: '.gitignore', fs });
      await idx.setEntry('.gitignore', mode, sha);
      return { id: op.id, kind: op.kind, path: '.gitignore', subject: op.path, result: 'ok', blob: sha, expectedAfter: { path: '.gitignore', exists: true, blob: sha } };
    }

    case OP_KIND.MOVE: {
      const single = await idx.entry(op.from);
      const entries = single ? [single] : await idx.entriesUnder(op.from);
      if (!entries.length) throw new Error(`cannot move '${op.from}': git tracks nothing there at HEAD`);
      const moved = [];
      for (const e of entries) {
        const suffix = e.path === op.from ? '' : e.path.slice(op.from.replace(/\/$/, '').length + 1);
        const dest = suffix ? `${op.to.replace(/\/$/, '')}/${suffix}` : op.to;
        // Add at the destination BEFORE dropping the source: at no point in the
        // compiled tree does the content exist nowhere.
        await idx.setEntry(dest, e.mode, e.sha);
        await idx.removeEntry(e.path);
        moved.push({ from: e.path, to: dest, blob: e.sha });
      }
      return { id: op.id, kind: op.kind, path: op.from, to: op.to, result: 'ok', moved, expectedAfter: { path: op.to, exists: true } };
    }

    /* c8 ignore next 2 */
    default:
      throw new Error(`unsupported operation kind '${op.kind}'`);
  }
}

/** Current .gitignore: working tree first, then HEAD, then empty. */
async function readGitignore({ run, rootPath, head, fs }) {
  try {
    return String(await fs.readFile(path.join(rootPath, '.gitignore'), 'utf8'));
  } catch { /* not on disk */ }
  const blob = await revBytes(run, head, '.gitignore');
  return blob ? blob.toString('utf8') : '';
}

async function probeIgnorecase(run, git) {
  // Without a repository there is no core.ignorecase to read, and the collision
  // still matters: two paths differing only in case would land on one another
  // inside the Trash. So the platform default stands in, rather than the check
  // quietly not happening.
  if (!git) return process.platform === 'win32' || process.platform === 'darwin';
  const r = await run(['config', '--type=bool', '--get', 'core.ignorecase'], { allowFailure: true });
  if (r.code === 0) return r.text.trim() === 'true';
  return process.platform === 'win32' || process.platform === 'darwin';
}

/** One sentence that never overstates what happened. */
function buildResultMessage({ commit, compiled, stale, trash, trashIncomplete, realization, realizeIncomplete }) {
  const parts = [];
  const gitCount = compiled.results.filter((r) => r.kind !== OP_KIND.TRASH).length;
  if (commit) {
    parts.push(realizeIncomplete
      ? `committed ${gitCount} operation(s) as ${commit.slice(0, 7)}, but the working-tree sync is INCOMPLETE — ${realization.note}`
      : `applied ${gitCount} operation(s) as ONE commit ${commit.slice(0, 7)}`);
  }
  if (trash) {
    parts.push(trashIncomplete
      ? `TRASH MOVE-SET INCOMPLETE: ${(trash.moved || []).length} file(s) moved, ${(trash.failed || []).length} refused or failed (${(trash.failed || []).map((f) => `${f.path}: ${f.code}`).join('; ')}) — per-path state is journaled and a retry resumes it`
      : `moved ${(trash.moved || []).length} file(s) into the reversible Trash (undo = restore-from-Trash)`);
  }
  if (stale.length) parts.push(`${stale.length} finding(s) dropped as stale`);
  return parts.join('; ');
}

async function readJsonOrNull(fs, file) {
  try { return JSON.parse(String(await fs.readFile(file, 'utf8'))); } catch { return null; }
}

/** Convenience: the pathspec set an Apply result touched. */
export function appliedPaths(result) {
  return [...new Set((result.ops || []).flatMap((o) => (o.moved ? o.moved.flatMap((m) => [m.from, m.to]) : [toPosixRel(o.path)])))];
}

export default { applyApproved, APPLY_REFUSAL, APPLY_STATUS };

// engine/apply/reorg.mjs — Wave 8: reorg moves, class-partitioned and two-phase.
//
// Reorg is the third and most dangerous finding class: moving a leaf/asset
// directory can break a reference. v1 ships it gated (leaf-only AND zero-hit for
// the normal path; non-zero-hit only through the explicit per-proposal override)
// and, crucially, EXECUTES it through a per-path CONTENT-CLASS PARTITION so that
// each path is moved by the mechanism whose undo actually holds its content:
//
//   tracked (git holds it, clean)      → Wave-3 compiled single-commit plan:
//       temp-index re-pathing (add blob at new path, drop the old entry), the
//       same content revalidation as any Apply. UNDO = `git revert` of the tidy
//       commit.
//   untracked-in-git-repo / non-git    → Wave-4 journaled move-set, except the
//       destination is the NEW PATH instead of the Trash. UNDO = journaled
//       move-back. NO `git add`, NO index write, NO .gitignore write — approving
//       a Move never changes any path's tracking class (asserted by the
//       consent-scope porcelain-class diff).
//
// A MIXED directory (some tracked members, some not) is the hard case, and it is
// run as an EXPLICIT, code-enforced two-phase state machine, journaled
// fsync-before-act, so that a crash at ANY point resolves to exactly one of two
// states — never a third:
//
//   apply:  PLANNED → PREFLIGHTED → FS_MOVING(k/n) → FS_DONE → COMMITTED
//           → REF_ADVANCED → DONE
//   undo:   UNDO_PLANNED → REVERT_COMMITTED → MOVING_BACK(k/n) → UNDO_DONE
//
// Both halves are COMPILED and REVALIDATED before either executes (the git tree
// is written into a temp index and the fs move-set is preflighted for
// source-present / destination-free / ignorecase). Then the fs half moves, then
// the commit lands. Recovery derives roll-forward vs roll-back from the last
// durable journal state PLUS one observable git fact — is the journaled commit
// sha at the journaled ref? — and nothing else:
//
//   • no COMMITTED record, or the journaled commit is NOT at the ref → the commit
//     never landed → ROLL BACK the completed fs moves; the tree is bit-identical
//     and nothing is committed (an unreferenced commit object is harmless).
//   • the journaled commit IS at the ref → the commit landed → ROLL FORWARD:
//     complete any outstanding fs move and the working-tree realization; the move
//     is fully applied.
//
// The crash-at-every-step table (docs/reorg-two-phase-crash-table.md) enumerates
// one row per (state, crash point) and names the test that proves it; the
// integration matrix instantiates every row.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { toPosixRel } from '../glob.mjs';
import { TRACKING } from '../porcelain.mjs';
import { hashFile } from '../snapshot.mjs';

import { makeGitRunner } from './git-plumbing.mjs';
import { withTempIndex } from './temp-index.mjs';
import { openJournal, readJournal } from './journal.mjs';
import { realizeWorkingTree, REALIZE_STRATEGY } from './realize.mjs';
import { capturePorcelainClasses, diffPorcelainClasses } from './consent-scope.mjs';
import { checkPathAgainstExpectation } from './no-clobber.mjs';
import { acquireLock } from './lock.mjs';

export const REORG_KIND = 'reorg';

/** How git relates to one path inside a proposed move — decides its executor. */
export const REORG_CONTENT_CLASS = Object.freeze({
  /** git holds it, clean: temp-index re-pathing, undo = git revert. */
  TRACKED: 'tracked',
  /** untracked inside a repo: journaled move-set, undo = journaled move-back. */
  UNTRACKED: 'untracked-in-git-repo',
  /** no repository: the same journaled move-set / move-back. */
  NON_GIT: 'non-git',
});

/** The named executor each content class is moved by. */
export const REORG_EXECUTOR = Object.freeze({
  [REORG_CONTENT_CLASS.TRACKED]: 'wave3-single-commit-plan',
  [REORG_CONTENT_CLASS.UNTRACKED]: 'wave4-journaled-move-set',
  [REORG_CONTENT_CLASS.NON_GIT]: 'wave4-journaled-move-set',
});

/** The named undo each content class is reversed by. */
export const REORG_UNDO = Object.freeze({
  [REORG_CONTENT_CLASS.TRACKED]: 'git-revert',
  [REORG_CONTENT_CLASS.UNTRACKED]: 'journaled-move-back',
  [REORG_CONTENT_CLASS.NON_GIT]: 'journaled-move-back',
});

/** The apply state machine — every transition is appended fsync-before-act. */
export const REORG_APPLY_STATE = Object.freeze({
  PLANNED: 'PLANNED',
  PREFLIGHTED: 'PREFLIGHTED',
  FS_MOVING: 'FS_MOVING',
  FS_DONE: 'FS_DONE',
  COMMITTED: 'COMMITTED',
  REF_ADVANCED: 'REF_ADVANCED',
  DONE: 'DONE',
});

/** The undo state machine — git revert then journaled move-back, as one unit. */
export const REORG_UNDO_STATE = Object.freeze({
  UNDO_PLANNED: 'UNDO_PLANNED',
  REVERT_COMMITTED: 'REVERT_COMMITTED',
  MOVING_BACK: 'MOVING_BACK',
  UNDO_DONE: 'UNDO_DONE',
});

export const REORG_STATUS = Object.freeze({
  APPLIED: 'applied',
  ROLLED_BACK: 'rolled-back',
  PARTIAL: 'partial',
  REFUSED: 'refused',
  NO_OP: 'no-op',
});

/** What a crash-recovery pass decided to do. */
export const REORG_RECOVERY = Object.freeze({
  ROLL_FORWARD: 'roll-forward',
  ROLL_BACK: 'roll-back',
  NONE: 'none',
});

export const REORG_REFUSAL = Object.freeze({
  NO_DESTINATION: 'REORG_NO_DESTINATION',
  NOT_ELIGIBLE: 'REORG_NOT_ELIGIBLE_NO_OVERRIDE',
  SOURCE_MISSING: 'REORG_SOURCE_MISSING',
  DEST_OCCUPIED: 'REORG_DESTINATION_OCCUPIED',
  CASE_COLLISION: 'REORG_CASE_COLLISION',
  DIRTY_MEMBER: 'REORG_DIRTY_MEMBER',
  STALE: 'REORG_STALE',
  NO_HEAD: 'REORG_NO_HEAD_COMMIT',
  DETACHED_HEAD: 'REORG_DETACHED_HEAD',
  HEAD_MOVED: 'REORG_HEAD_MOVED_SINCE_SNAPSHOT',
  REF_RACE: 'REORG_REF_COMPARE_AND_SWAP_FAILED',
  OUTSIDE_ROOT: 'REORG_PATH_ESCAPES_ROOT',
  EMPTY: 'REORG_EMPTY_MOVE',
});

/** Tracking classes git holds a clean copy of — the only ones the git half moves. */
const CLEAN_TRACKED = new Set([TRACKING.TRACKED_CLEAN]);
/** Tracking classes git holds an OLDER version of — a move would risk the newer work. */
const DIRTY_TRACKED = new Set([TRACKING.TRACKED_MODIFIED, TRACKING.STAGED, TRACKING.UNMERGED]);

function refuse(code, message, extra = {}) {
  return { status: REORG_STATUS.REFUSED, code, message, commit: null, ...extra };
}

// ─── content-class partition ────────────────────────────────────────────────

/**
 * Classify ONE path inside a proposed move. This is the per-path content-class
 * partition, computed at compile time.
 *
 * @returns {{rel: string, contentClass: string|null, trackingClass: string, eligible: boolean, reason: string|null}}
 */
export function classifyReorgMember({ rel, porcelain = null, git = null }) {
  const p = toPosixRel(rel);
  if (!git || !porcelain) {
    return { rel: p, contentClass: REORG_CONTENT_CLASS.NON_GIT, trackingClass: TRACKING.NON_GIT, eligible: true, reason: null };
  }
  const cls = porcelain.classify(p);
  if (CLEAN_TRACKED.has(cls)) {
    return { rel: p, contentClass: REORG_CONTENT_CLASS.TRACKED, trackingClass: cls, eligible: true, reason: null };
  }
  if (DIRTY_TRACKED.has(cls) || cls === 'unknown') {
    return {
      rel: p, contentClass: null, trackingClass: cls, eligible: false,
      reason: `git holds only an older version of '${p}' (${cls}) — moving it would risk working-tree content git has never seen; excluded until it is clean`,
    };
  }
  // Untracked or ignored inside a repo: git does not hold it, so the move-set is
  // the reversible mechanism. IGNORED is treated as untracked-in-repo for moving.
  return { rel: p, contentClass: REORG_CONTENT_CLASS.UNTRACKED, trackingClass: cls, eligible: true, reason: null };
}

/**
 * Partition a whole proposed move into its content classes and per-member
 * moves, naming the executor and undo each member is bound to.
 *
 * @param {{move: {from: string, to: string}, members: string[], porcelain?: object|null, git?: object|null}} opts
 */
export function partitionReorgMove({ move, members = [], porcelain = null, git = null }) {
  const from = toPosixRel(move && move.from);
  const to = toPosixRel(move && move.to);
  const classes = { [REORG_CONTENT_CLASS.TRACKED]: [], [REORG_CONTENT_CLASS.UNTRACKED]: [], [REORG_CONTENT_CLASS.NON_GIT]: [] };
  const memberMoves = [];
  const ineligible = [];

  for (const raw of members) {
    const rel = toPosixRel(raw);
    const suffix = rel === from ? '' : rel.slice(from.replace(/\/$/, '').length + 1);
    const dest = suffix ? `${to.replace(/\/$/, '')}/${suffix}` : to;
    const c = classifyReorgMember({ rel, porcelain, git });
    if (!c.eligible) { ineligible.push({ ...c, dest }); continue; }
    const mm = { from: rel, to: dest, contentClass: c.contentClass, trackingClass: c.trackingClass, executor: REORG_EXECUTOR[c.contentClass], undo: REORG_UNDO[c.contentClass] };
    memberMoves.push(mm);
    classes[c.contentClass].push(mm);
  }

  const usedClasses = Object.entries(classes).filter(([, v]) => v.length).map(([k]) => k);
  const hasGit = classes[REORG_CONTENT_CLASS.TRACKED].length > 0;
  const hasFs = classes[REORG_CONTENT_CLASS.UNTRACKED].length > 0 || classes[REORG_CONTENT_CLASS.NON_GIT].length > 0;

  return {
    from, to, memberMoves, classes, ineligible,
    usedClasses,
    hasGit, hasFs,
    mixed: hasGit && hasFs,
    fsMoves: [...classes[REORG_CONTENT_CLASS.UNTRACKED], ...classes[REORG_CONTENT_CLASS.NON_GIT]],
    gitMoves: classes[REORG_CONTENT_CLASS.TRACKED],
  };
}

// ─── small fs primitives (shared with the Trash move-set discipline) ─────────

async function statOrNull(fs, abs) {
  try { return await fs.stat(abs); } catch { return null; }
}

async function hashOrNull(fs, abs) {
  try { return await hashFile(abs, { fs }); } catch { return null; }
}

/** rename, falling back to copy+unlink across devices; returns the method used. */
async function moveFile(fs, from, to) {
  await fs.mkdir(path.dirname(to), { recursive: true });
  try {
    await fs.rename(from, to);
    return 'rename';
  } catch (err) {
    if (err && (err.code === 'EXDEV' || err.code === 'EPERM' || err.code === 'EACCES')) {
      await fs.copyFile(from, to);
      await fs.rm(from, { force: true });
      return 'copy+unlink';
    }
    throw err;
  }
}

function insideRoot(root, abs) {
  const rel = path.relative(root, abs);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

// ─── preflight: everything knowable before anything moves ────────────────────

/**
 * Preflight the fs half: every source present, every destination free, no
 * case-collision on a case-insensitive filesystem. Mirrors the Trash preflight,
 * but the destination is the NEW PATH, not a Trash slot.
 */
export function preflightReorgFs({ rootPath, fsMoves = [], ignorecase = false }) {
  const root = path.resolve(rootPath);
  const problems = [];
  const planned = [];
  const lowerDest = new Map();

  for (const mv of fsMoves) {
    const srcAbs = path.join(root, mv.from);
    const destAbs = path.join(root, mv.to);
    if (!insideRoot(root, srcAbs) || !insideRoot(root, destAbs)) {
      problems.push({ path: mv.from, to: mv.to, code: REORG_REFUSAL.OUTSIDE_ROOT, message: `'${mv.from}' → '${mv.to}' escapes the run root` });
      continue;
    }
    if (ignorecase) {
      const key = mv.to.toLowerCase();
      if (lowerDest.has(key)) {
        problems.push({ path: mv.from, to: mv.to, code: REORG_REFUSAL.CASE_COLLISION, message: `destination '${mv.to}' collides on a case-insensitive filesystem with '${lowerDest.get(key)}'` });
        continue;
      }
      lowerDest.set(key, mv.to);
    }
    planned.push(mv);
  }
  return { ok: problems.length === 0, problems, planned };
}

// ─── the git half: the Wave-3 compiled single-commit plan (re-pathing) ───────

/**
 * Build the tree that re-paths every tracked member, in a temp index seeded from
 * HEAD — zero working-tree writes. Returns the tree sha (or null if unchanged).
 */
async function compileGitTree({ run, head, gitMoves, fs }) {
  return withTempIndex({ run, head, fs }, async (idx) => {
    const moved = [];
    for (const mv of gitMoves) {
      const e = await idx.entry(mv.from);
      if (!e) throw new Error(`cannot move '${mv.from}': git tracks nothing there at HEAD`);
      await idx.setEntry(mv.to, e.mode, e.sha); // add at destination BEFORE dropping source
      await idx.removeEntry(mv.from);
      moved.push({ from: mv.from, to: mv.to, blob: e.sha, mode: e.mode });
    }
    const tree = await idx.writeTree();
    return { tree, moved };
  });
}

/**
 * Realize a reorg's tracked half into the working tree after the commit has
 * landed.
 *
 * IMPORTANT: only DESTINATION paths are handed to `git checkout --no-overlay`.
 * Source pathspecs are ABSENT from the tidy commit (they were re-pathed out of
 * the tree). On some git/rename shapes — notably a commit produced by `git mv`
 * and recovered mid-realization — including those source pathspecs makes the
 * entire checkout fail with "pathspec did not match", leaving destinations that
 * were deleted mid-realize unrestored. Destinations are checked out from <C>;
 * sources still present on disk are then force-removed (and dropped from the
 * index) as a separate, idempotent step.
 */
async function realizeReorgGitMoves({
  run, rootPath, commit, gitMoves = [], gitVersion = null,
  strategy = REALIZE_STRATEGY.NO_OVERLAY, journal = null, fs = fsp,
}) {
  const toPaths = [...new Set(gitMoves.map((m) => m.to).filter(Boolean))];
  const fromPaths = [...new Set(gitMoves.map((m) => m.from).filter(Boolean))]
    .filter((from) => !toPaths.includes(from));

  const realization = await realizeWorkingTree({
    run,
    rootPath,
    commit,
    paths: toPaths,
    gitVersion,
    strategy,
    journal,
    fs,
  });

  for (const from of fromPaths) {
    const abs = path.join(rootPath, from);
    try {
      await fs.rm(abs, { force: true, recursive: true });
    } catch { /* already gone — idempotent */ }
    await run(['update-index', '--force-remove', '--', from], { allowFailure: true });
    // Prune empty parent directories left behind by the rename (best-effort).
    let dir = path.dirname(abs);
    const rootAbs = path.resolve(rootPath);
    while (dir && dir !== rootAbs && dir.startsWith(rootAbs)) {
      try {
        await fs.rmdir(dir);
      } catch {
        break; // not empty or not a dir — stop climbing
      }
      dir = path.dirname(dir);
    }
  }

  return realization;
}

function reorgCommitMessage({ runId, from, to, gitMoves }) {
  const lines = [
    `tidy-idy reorg: move ${from} → ${to}`,
    '',
    `run: ${runId}`,
    'reorganisations:',
    ...gitMoves.map((m) => `  ${m.from} → ${m.to}`),
  ];
  return lines.join('\n') + '\n';
}

// ─── revalidation: the tree is the tree the tile described ───────────────────

/**
 * Revalidate every member against snapshot S. A directory move is atomic, so a
 * single edited-since-scan member drops the WHOLE move as stale — the fail-safe
 * direction is always "do less", never "move some of the directory".
 */
async function revalidateMembers({ rootPath, memberMoves, snapshot, porcelain, fs }) {
  const root = path.resolve(rootPath);
  for (const mv of memberMoves) {
    const abs = path.join(root, mv.from);
    const st = await statOrNull(fs, abs);
    if (!st) return { ok: false, code: REORG_REFUSAL.SOURCE_MISSING, member: mv.from, message: `'${mv.from}' no longer exists — it was removed or renamed after the scan; re-scan` };
    const expected = snapshot && snapshot.hashes ? snapshot.hashes[mv.from] : null;
    if (expected) {
      const nowHash = await hashOrNull(fs, abs);
      if (nowHash !== expected) {
        return { ok: false, code: REORG_REFUSAL.STALE, member: mv.from, message: `'${mv.from}' changed on disk after the run snapshot — the bytes on the tile are not the bytes on disk; re-scan and approve again` };
      }
    }
    // A member that became dirty (staged/modified) since the scan is a class the
    // move was not reasoned about against; refuse the whole move.
    if (porcelain && mv.contentClass === REORG_CONTENT_CLASS.TRACKED) {
      const cls = porcelain.classify(mv.from);
      if (!CLEAN_TRACKED.has(cls)) {
        return { ok: false, code: REORG_REFUSAL.DIRTY_MEMBER, member: mv.from, message: `'${mv.from}' is no longer tracked-and-clean (${cls}) — a move would risk work git has not seen; re-scan` };
      }
    }
  }
  return { ok: true };
}

// ─── the apply entry point ───────────────────────────────────────────────────

/**
 * Apply one approved reorg move through its content-class partition and the
 * two-phase state machine.
 *
 * @param {{rootPath: string, git: object|null, runId: string, reportDir: string,
 *   finding: object, snapshot?: object|null, porcelain?: object|null,
 *   override?: boolean, fs?: object, now?: Function, run?: Function,
 *   lock?: object|null, env?: object, realizeStrategy?: string}} opts
 */
export async function applyReorgMove(opts = {}) {
  const {
    rootPath,
    git,
    runId,
    finding,
    snapshot = null,
    porcelain = null,
    override = false,
    fs = fsp,
    now = () => new Date(),
    env = process.env,
    realizeStrategy = REALIZE_STRATEGY.NO_OVERLAY,
    lock: borrowedLock = null,
  } = opts;

  const root = path.resolve(rootPath);
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : path.join(root, '.tidy-idy');
  const run = opts.run || makeGitRunner({ root, env });

  const move = finding && (finding.move || (finding.from && finding.to ? { from: finding.from, to: finding.to } : null));
  if (!move || !move.from || !move.to) {
    return refuse(REORG_REFUSAL.NO_DESTINATION, 'a reorg move must name both a source and a destination');
  }
  // Eligibility gate: a non-zero-hit (advisory) proposal may be applied ONLY with
  // the explicit per-proposal override — never in bulk (Amendment C.i).
  const eligible = finding.eligible !== false;
  if (!eligible && !override) {
    return refuse(REORG_REFUSAL.NOT_ELIGIBLE,
      `this reorg proposal is advisory: its reference scan found ${finding.referenceScan ? finding.referenceScan.hitCount : 'some'} hit(s), so it is excluded from bulk-approve and can be applied only through its own explicit 'Apply anyway — I'll fix the references' override`,
      { advisory: true, referenceScan: finding.referenceScan || null });
  }

  const members = Array.isArray(finding.members) && finding.members.length ? finding.members : [move.from];
  const part = partitionReorgMove({ move, members, porcelain, git });
  if (!part.memberMoves.length) {
    return { status: REORG_STATUS.NO_OP, code: null, commit: null, message: `nothing to move: every member of '${part.from}' was ineligible`, ineligible: part.ineligible };
  }

  // Revalidate BEFORE either half executes.
  const reval = await revalidateMembers({ rootPath: root, memberMoves: part.memberMoves, snapshot, porcelain, fs });
  if (!reval.ok) return refuse(reval.code, reval.message, { member: reval.member });

  // The lock: borrow the caller's if it holds one, else take it for this move.
  const borrowed = Boolean(borrowedLock && borrowedLock.ok);
  const lock = borrowed ? borrowedLock : await acquireLock({ reportDir, purpose: 'reorg-apply', fs, now });
  if (!lock.ok) return refuse('LOCK_HELD', lock.message, { holder: lock.holder });

  const journal = await openJournal({ reportDir, runId, kind: REORG_KIND, fs, now });
  const classesBefore = await capturePorcelainClasses({ git });

  try {
    // ---- git preflight, under the lock -----------------------------------
    let head = null;
    let ref = null;
    if (part.hasGit) {
      if (!git) return refuse(REORG_REFUSAL.NO_HEAD, 'tracked members require a repository to commit into');
      const headRes = await run(['rev-parse', 'HEAD'], { allowFailure: true });
      head = headRes.code === 0 ? headRes.text.trim() : null;
      if (!head) return refuse(REORG_REFUSAL.NO_HEAD, 'this repository has no commits yet, so there is no tree for the tracked half to be a delta on');
      const symRes = await run(['symbolic-ref', '--quiet', 'HEAD'], { allowFailure: true });
      ref = symRes.code === 0 ? symRes.text.trim() : null;
      if (!ref) return refuse(REORG_REFUSAL.DETACHED_HEAD, 'HEAD is detached — the "git revert the tidy commit" undo story would be a lie, so v1 refuses');
      if (snapshot && snapshot.head && snapshot.head !== head) {
        return refuse(REORG_REFUSAL.HEAD_MOVED, `HEAD moved since the scan (snapshot recorded ${snapshot.head}, HEAD is now ${head}) — re-scan and approve again`, { snapshotHead: snapshot.head, currentHead: head });
      }
    }

    const ignorecase = await probeIgnorecase(run, git);
    await journal.append('state', {
      state: REORG_APPLY_STATE.PLANNED,
      move: { from: part.from, to: part.to }, mixed: part.mixed,
      classes: part.usedClasses, head, ref,
      fsMoves: part.fsMoves.map((m) => ({ from: m.from, to: m.to })),
      gitMoves: part.gitMoves.map((m) => ({ from: m.from, to: m.to })),
      override: Boolean(override && !eligible),
    });

    const fsPre = preflightReorgFs({ rootPath: root, fsMoves: part.fsMoves, ignorecase });
    if (!fsPre.ok) {
      await journal.append('aborted', { stage: 'fs-preflight', problems: fsPre.problems });
      const first = fsPre.problems[0];
      return refuse(first.code, `Apply aborted before touching anything: ${fsPre.problems.map((p) => `${p.path}: ${p.code}`).join('; ')}. NOTHING was moved.`, { problems: fsPre.problems });
    }

    // ---- compile the git tree (no writes) --------------------------------
    let gitTree = null;
    let gitMovedResults = [];
    if (part.hasGit) {
      try {
        const compiled = await compileGitTree({ run, head, gitMoves: part.gitMoves, fs });
        gitTree = compiled.tree;
        gitMovedResults = compiled.moved;
      } catch (err) {
        await journal.append('aborted', { stage: 'git-compile', error: err.message });
        return refuse(REORG_REFUSAL.STALE, `Apply aborted during compilation: ${err.message}. NOTHING was committed and NOTHING was moved.`, { error: err.message });
      }
      const headTree = (await run(['rev-parse', `${head}^{tree}`])).text.trim();
      if (gitTree === headTree) gitTree = null; // re-pathing produced no change (paths already there)
    }

    await journal.append('state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree, head, ref });

    // ---- PHASE 1: the journaled fs move-set ------------------------------
    const movedFs = [];
    if (part.fsMoves.length) {
      await journal.append('state', { state: REORG_APPLY_STATE.FS_MOVING, total: part.fsMoves.length });
      let k = 0;
      for (const mv of part.fsMoves) {
        const srcAbs = path.join(root, mv.from);
        const destAbs = path.join(root, mv.to);
        // no-clobber: the destination must be free before we move onto it.
        const guard = await checkPathAgainstExpectation({ rootPath: root, path: mv.to, expected: { exists: false }, fs });
        if (!guard.ok) {
          await journal.append('fs-move', { from: mv.from, to: mv.to, state: 'failed', code: REORG_REFUSAL.DEST_OCCUPIED, reason: guard.reason });
          // Roll back the fs moves already completed; nothing was committed.
          await rollbackFsMoves({ root, journal, moved: movedFs, fs });
          await journal.append('state', { state: REORG_APPLY_STATE.PLANNED, note: 'rolled back after destination-occupied' });
          return { status: REORG_STATUS.ROLLED_BACK, code: REORG_REFUSAL.DEST_OCCUPIED, commit: null, message: `destination '${mv.to}' is occupied (${guard.reason}) — the completed fs moves were rolled back and nothing was committed`, rolledBack: movedFs.length };
        }
        const hash = await hashOrNull(fs, srcAbs);
        const size = (await statOrNull(fs, srcAbs) || {}).size ?? null;
        await journal.append('fs-move', { from: mv.from, to: mv.to, state: 'started', hash, size });
        let method;
        try {
          method = await moveFile(fs, srcAbs, destAbs);
        } catch (err) {
          await journal.append('fs-move', { from: mv.from, to: mv.to, state: 'failed', code: 'IO_ERROR', error: err.message });
          await rollbackFsMoves({ root, journal, moved: movedFs, fs });
          await journal.append('state', { state: REORG_APPLY_STATE.PLANNED, note: 'rolled back after fs io error' });
          return { status: REORG_STATUS.ROLLED_BACK, code: 'IO_ERROR', commit: null, message: `fs move '${mv.from}' → '${mv.to}' failed (${err.message}); the completed fs moves were rolled back and nothing was committed`, rolledBack: movedFs.length };
        }
        await journal.append('fs-move', { from: mv.from, to: mv.to, state: 'done', hash, size, method, k: ++k, n: part.fsMoves.length });
        movedFs.push({ from: mv.from, to: mv.to, hash, size, method, contentClass: mv.contentClass });
      }
      await journal.append('state', { state: REORG_APPLY_STATE.FS_DONE, moved: movedFs.length });
    }

    // ---- PHASE 2: commit the tracked half, then advance the ref ----------
    let commit = null;
    let realization = null;
    if (gitTree) {
      const message = reorgCommitMessage({ runId, from: part.from, to: part.to, gitMoves: part.gitMoves });
      commit = (await run(['commit-tree', gitTree, '-p', head, '-m', message])).text.trim();
      await journal.append('state', { state: REORG_APPLY_STATE.COMMITTED, commit, tree: gitTree, parent: head, ref });

      const cas = await run(['update-ref', ref, commit, head], { allowFailure: true });
      if (cas.code !== 0) {
        await journal.append('ref-race', { commit, expected: head, stderr: cas.stderr });
        // The commit is written but unreferenced (never landed). Roll the fs half
        // back to bit-identical; the commit object is harmless and collectable.
        await rollbackFsMoves({ root, journal, moved: movedFs, fs });
        await journal.append('state', { state: REORG_APPLY_STATE.PLANNED, note: 'rolled back after ref race' });
        return { status: REORG_STATUS.ROLLED_BACK, code: REORG_REFUSAL.REF_RACE, commit: null, attemptedCommit: commit, message: 'the branch moved between preflight and the ref update — the compare-and-swap failed, the fs half was rolled back, and nothing landed', rolledBack: movedFs.length };
      }
      await journal.append('state', { state: REORG_APPLY_STATE.REF_ADVANCED, commit, ref });

      realization = await realizeReorgGitMoves({
        run, rootPath: root, commit, gitMoves: part.gitMoves,
        gitVersion: git.version || null, strategy: realizeStrategy, journal, fs,
      });
    }

    // ---- consent-scope: no undeclared tracking-class change --------------
    const classesAfter = await capturePorcelainClasses({ git });
    const consentScope = diffPorcelainClasses({ before: classesBefore, after: classesAfter, declared: declaredReorgTransitions(part) });
    await journal.append('consent-scope', consentScope);

    await journal.append('state', { state: REORG_APPLY_STATE.DONE, commit });

    const result = {
      status: REORG_STATUS.APPLIED,
      code: null,
      runId,
      from: part.from,
      to: part.to,
      mixed: part.mixed,
      classes: part.usedClasses,
      commit,
      parent: commit ? head : null,
      ref: commit ? ref : null,
      branch: commit ? ref.replace(/^refs\/heads\//, '') : null,
      gitMoved: gitMovedResults,
      fsMoved: movedFs,
      ineligible: part.ineligible,
      realization,
      consentScope,
      journal: { dir: journal.dir, file: journal.file },
      undo: {
        available: true,
        how: [
          commit ? `git revert of the tidy commit ${commit.slice(0, 7)}` : null,
          movedFs.length ? 'journaled move-back of every fs-moved file' : null,
        ].filter(Boolean).join(' + '),
        command: commit ? `git -C ${root} revert -n ${commit}` : null,
        moveBackRunId: movedFs.length ? runId : null,
      },
      message: buildReorgMessage({ part, commit, movedFs }),
    };
    await journal.writeSummary({ ...result, at: now().toISOString() });
    return result;
  } finally {
    if (!borrowed) await lock.release().catch(() => {});
  }
}

/** Declared class transitions for the consent-scope diff. */
function declaredReorgTransitions(part) {
  const t = [];
  for (const mv of part.gitMoves) {
    t.push({ path: mv.from, from: TRACKING.TRACKED_CLEAN, to: 'absent' });
    t.push({ path: mv.to, from: 'absent', to: TRACKING.TRACKED_CLEAN });
  }
  // The fs half moves untracked/non-git content: git's tracking class is
  // untracked (or absent) both before and after — the path changes, the CLASS
  // does not. So the fs source goes untracked→absent and the fs destination goes
  // absent→untracked, both declared, so no `git add` / index write is implied.
  for (const mv of part.fsMoves) {
    const cls = mv.trackingClass === TRACKING.IGNORED ? TRACKING.IGNORED : TRACKING.UNTRACKED;
    t.push({ path: mv.from, from: cls, to: 'absent' });
    t.push({ path: mv.to, from: 'absent', to: cls });
  }
  return t;
}

function buildReorgMessage({ part, commit, movedFs }) {
  const parts = [];
  if (commit) parts.push(`re-pathed ${part.gitMoves.length} tracked file(s) in ONE commit ${commit.slice(0, 7)} (undo = git revert)`);
  if (movedFs.length) parts.push(`moved ${movedFs.length} untracked/non-git file(s) via journaled move-set (undo = journaled move-back)`);
  if (part.ineligible.length) parts.push(`${part.ineligible.length} member(s) excluded as not clean`);
  return `reorg ${part.from} → ${part.to}: ${parts.join('; ')}`;
}

async function probeIgnorecase(run, git) {
  if (!git) return process.platform === 'win32' || process.platform === 'darwin';
  const r = await run(['config', '--type=bool', '--get', 'core.ignorecase'], { allowFailure: true });
  if (r.code === 0) return r.text.trim() === 'true';
  return process.platform === 'win32' || process.platform === 'darwin';
}

// ─── rollback of the fs half (phase-1 undo, used on failure and roll-back) ────

/**
 * Move every completed fs move back to its source, in reverse order, each
 * destination guarded by the no-clobber invariant. Used both when a phase fails
 * mid-apply and when crash-recovery decides the commit never landed.
 */
async function rollbackFsMoves({ root, journal, moved, fs }) {
  for (let i = moved.length - 1; i >= 0; i--) {
    const mv = moved[i];
    const destAbs = path.join(root, mv.to);
    const srcAbs = path.join(root, mv.from);
    const backHere = await statOrNull(fs, srcAbs);
    if (backHere) continue; // already back (idempotent resume)
    const there = await statOrNull(fs, destAbs);
    if (!there) continue; // nothing to move back
    await journal.append('fs-move-back', { from: mv.to, to: mv.from, state: 'started' });
    await moveFile(fs, destAbs, srcAbs);
    await journal.append('fs-move-back', { from: mv.to, to: mv.from, state: 'done' });
  }
}

// ─── crash recovery: last durable journal state + one git fact ───────────────

/**
 * Resume a reorg apply that was interrupted. Reads the journal, derives the last
 * durable state, then decides — from that state plus the single observable git
 * fact "is the journaled commit sha at the journaled ref?" — whether to roll
 * FORWARD to fully-applied or ROLL BACK to bit-identical. There is no third state.
 *
 * @param {{rootPath: string, git: object|null, runId: string, reportDir: string,
 *   fs?: object, now?: Function, run?: Function, env?: object, realizeStrategy?: string}} opts
 */
export async function recoverReorgApply(opts = {}) {
  const { rootPath, git, runId, fs = fsp, now = () => new Date(), env = process.env, realizeStrategy = REALIZE_STRATEGY.NO_OVERLAY } = opts;
  const root = path.resolve(rootPath);
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : path.join(root, '.tidy-idy');
  const run = opts.run || makeGitRunner({ root, env });

  const j = await readJournal({ reportDir, runId, kind: REORG_KIND, fs });
  if (!j || !j.records.length) {
    return { status: REORG_STATUS.NO_OP, recovery: REORG_RECOVERY.NONE, message: `no reorg journal for run ${runId} — nothing to recover` };
  }

  const states = j.records.filter((r) => r.type === 'state');
  const last = states.length ? states[states.length - 1] : null;
  const committedRec = states.find((r) => r.state === REORG_APPLY_STATE.COMMITTED) || null;
  const plan = states.find((r) => r.state === REORG_APPLY_STATE.PLANNED) || {};

  if (last && last.state === REORG_APPLY_STATE.DONE) {
    return { status: REORG_STATUS.APPLIED, recovery: REORG_RECOVERY.NONE, message: 'reorg already fully applied', commit: committedRec ? committedRec.commit : null };
  }

  // The one observable git fact: is the journaled commit at the journaled ref?
  const journaledCommit = committedRec ? committedRec.commit : null;
  const ref = (committedRec && committedRec.ref) || plan.ref || null;
  let commitLanded = false;
  if (journaledCommit && ref && git) {
    const refRes = await run(['rev-parse', '--verify', '--quiet', ref], { allowFailure: true });
    const refSha = refRes.code === 0 ? refRes.text.trim() : null;
    if (refSha === journaledCommit) commitLanded = true;
    else {
      // The commit may have landed and then a later commit stacked on top; ask git
      // whether the branch tip is a descendant of the journaled commit.
      const anc = await run(['merge-base', '--is-ancestor', journaledCommit, ref], { allowFailure: true });
      if (anc.code === 0 && refSha) commitLanded = true;
    }
  }

  const journal = await openJournal({ reportDir, runId, kind: REORG_KIND, fs, now });

  // Reconstruct what the fs half was supposed to do, and what it recorded doing.
  const plannedFs = Array.isArray(plan.fsMoves) ? plan.fsMoves : [];
  const fsDone = j.records.filter((r) => r.type === 'fs-move' && r.state === 'done').map((r) => ({ from: r.from, to: r.to, hash: r.hash, size: r.size }));
  const fsStartedNotDone = j.records
    .filter((r) => r.type === 'fs-move' && r.state === 'started')
    .filter((r) => !fsDone.some((d) => d.from === r.from && d.to === r.to));

  if (commitLanded) {
    // ROLL FORWARD to fully-applied: complete any outstanding fs move, then the
    // working-tree realization, then seal DONE.
    await journal.append('recovery', { decision: REORG_RECOVERY.ROLL_FORWARD, commit: journaledCommit, ref });
    const completed = [...fsDone];
    for (const mv of plannedFs) {
      const srcAbs = path.join(root, mv.from);
      const destAbs = path.join(root, mv.to);
      const already = completed.some((d) => d.from === mv.from && d.to === mv.to);
      if (already) continue;
      const atDest = await statOrNull(fs, destAbs);
      const atSrc = await statOrNull(fs, srcAbs);
      if (atDest && !atSrc) { // the rename had completed before the crash
        await journal.append('fs-move', { from: mv.from, to: mv.to, state: 'done', reconciled: 'the rename had completed before the crash' });
        completed.push({ from: mv.from, to: mv.to });
        continue;
      }
      if (atSrc && !atDest) { // finish it forward
        await journal.append('fs-move', { from: mv.from, to: mv.to, state: 'started', recovered: true });
        await moveFile(fs, srcAbs, destAbs);
        await journal.append('fs-move', { from: mv.from, to: mv.to, state: 'done', recovered: true });
        completed.push({ from: mv.from, to: mv.to });
      }
    }
    let realization = null;
    const gitMoves = Array.isArray(plan.gitMoves) ? plan.gitMoves : [];
    if (journaledCommit && gitMoves.length && git) {
      // Destinations only — see realizeReorgGitMoves. Recovering a REF_ADVANCED
      // crash where a destination was deleted mid-realize MUST restore it from C.
      realization = await realizeReorgGitMoves({
        run, rootPath: root, commit: journaledCommit, gitMoves,
        gitVersion: git.version || null, strategy: realizeStrategy, journal, fs,
      });
    }
    await journal.append('state', { state: REORG_APPLY_STATE.DONE, commit: journaledCommit, recovered: true });
    const result = { status: REORG_STATUS.APPLIED, recovery: REORG_RECOVERY.ROLL_FORWARD, commit: journaledCommit, ref, fsMoved: completed, realization, message: `recovered: the commit landed, so the reorg was rolled FORWARD to fully-applied (${completed.length} fs move(s) reconciled)`, journal: { dir: journal.dir, file: journal.file } };
    await journal.writeSummary({ ...result, at: now().toISOString() });
    return result;
  }

  // ROLL BACK to bit-identical: the commit did not land. Move every completed fs
  // move back to its source; the tree becomes bit-identical and nothing is
  // committed (an unreferenced commit object, if any, is harmless).
  await journal.append('recovery', { decision: REORG_RECOVERY.ROLL_BACK, journaledCommit, ref, reason: journaledCommit ? 'the journaled commit is not at the ref' : 'no commit was ever written' });
  // Reconcile a rename that completed but whose 'done' record was lost.
  const toRollBack = [...fsDone];
  for (const r of fsStartedNotDone) {
    const srcAbs = path.join(root, r.from);
    const destAbs = path.join(root, r.to);
    const atDest = await statOrNull(fs, destAbs);
    const atSrc = await statOrNull(fs, srcAbs);
    if (atDest && !atSrc) toRollBack.push({ from: r.from, to: r.to });
  }
  await rollbackFsMoves({ root, journal, moved: toRollBack, fs });
  await journal.append('state', { state: REORG_APPLY_STATE.PLANNED, recovered: true, note: 'rolled back to bit-identical' });
  const result = { status: REORG_STATUS.ROLLED_BACK, recovery: REORG_RECOVERY.ROLL_BACK, commit: null, rolledBack: toRollBack.length, message: `recovered: the commit did not land, so the reorg was rolled BACK to bit-identical (${toRollBack.length} fs move(s) reversed); nothing was committed`, journal: { dir: journal.dir, file: journal.file } };
  await journal.writeSummary({ ...result, at: now().toISOString() });
  return result;
}

// ─── the named undo: git revert + journaled move-back as one journaled unit ──

/**
 * Undo a completed reorg apply. For the tracked half this is `git revert` of the
 * tidy commit; for the fs half it is a journaled move-back of every moved file,
 * each destination guarded by the no-clobber invariant. Both run as ONE journaled
 * undo unit with the same crash-resume semantics.
 *
 * @param {{rootPath: string, git: object|null, runId: string, reportDir: string,
 *   commit?: string|null, fs?: object, now?: Function, run?: Function,
 *   env?: object, lock?: object|null}} opts
 */
export async function undoReorgMove(opts = {}) {
  const { rootPath, git, runId, commit = null, fs = fsp, now = () => new Date(), env = process.env, lock: borrowedLock = null } = opts;
  const root = path.resolve(rootPath);
  const reportDir = opts.reportDir ? path.resolve(opts.reportDir) : path.join(root, '.tidy-idy');
  const run = opts.run || makeGitRunner({ root, env });

  const applyJournal = await readJournal({ reportDir, runId, kind: REORG_KIND, fs });
  if (!applyJournal) {
    return { status: REORG_STATUS.NO_OP, message: `no reorg apply journal for run ${runId} — nothing to undo` };
  }
  const fsDone = applyJournal.records
    .filter((r) => r.type === 'fs-move' && r.state === 'done')
    .map((r) => ({ from: r.from, to: r.to, hash: r.hash }));
  const committedRec = applyJournal.records.find((r) => r.type === 'state' && r.state === REORG_APPLY_STATE.COMMITTED) || null;
  const effectiveCommit = commit || (committedRec ? committedRec.commit : null);

  const borrowed = Boolean(borrowedLock && borrowedLock.ok);
  const lock = borrowed ? borrowedLock : await acquireLock({ reportDir, purpose: 'reorg-undo', fs, now });
  if (!lock.ok) return refuse('LOCK_HELD', lock.message, { holder: lock.holder });

  const journal = await openJournal({ reportDir, runId, kind: 'reorg-undo', fs, now });
  try {
    await journal.append('state', { state: REORG_UNDO_STATE.UNDO_PLANNED, commit: effectiveCommit, fsBack: fsDone.length });

    // ---- the git half: git revert of the tidy commit ---------------------
    let revert = null;
    if (effectiveCommit && git) {
      const head = (await run(['rev-parse', 'HEAD'], { allowFailure: true })).text.trim();
      const rev = await run(['revert', '--no-edit', effectiveCommit], { allowFailure: true });
      if (rev.code !== 0) {
        // A dirty tree or later-commit conflict: refuse rather than force. Nothing
        // has been moved back yet, so the tree is untouched by this undo.
        await run(['revert', '--abort'], { allowFailure: true });
        await journal.append('revert-refused', { commit: effectiveCommit, stderr: rev.stderr });
        return { status: REORG_STATUS.REFUSED, code: 'REVERT_REFUSED', message: `git revert of ${effectiveCommit.slice(0, 7)} did not apply cleanly (${rev.stderr.trim()}) — the tree was left untouched; resolve manually`, commit: null };
      }
      const revertCommit = (await run(['rev-parse', 'HEAD'], { allowFailure: true })).text.trim();
      revert = { from: head, commit: revertCommit };
      await journal.append('state', { state: REORG_UNDO_STATE.REVERT_COMMITTED, revertCommit, reverted: effectiveCommit });
    }

    // ---- the fs half: journaled move-back, no-clobber guarded -------------
    const restored = [];
    const refused = [];
    if (fsDone.length) {
      await journal.append('state', { state: REORG_UNDO_STATE.MOVING_BACK, total: fsDone.length });
      let k = 0;
      for (const mv of fsDone) {
        const destAbs = path.join(root, mv.to);   // where the apply moved it to
        const srcAbs = path.join(root, mv.from);   // its original path
        const atOriginal = await statOrNull(fs, srcAbs);
        const atMoved = await statOrNull(fs, destAbs);
        if (!atMoved && atOriginal) { // already back (idempotent resume)
          await journal.append('fs-move-back', { from: mv.to, to: mv.from, state: 'done', reconciled: 'already back' });
          restored.push({ path: mv.from, alreadyRestored: true });
          continue;
        }
        if (!atMoved && !atOriginal) {
          await journal.append('fs-move-back', { from: mv.to, to: mv.from, state: 'failed', code: 'NOT_FOUND' });
          refused.push({ path: mv.from, code: 'NOT_FOUND', message: `neither '${mv.to}' nor '${mv.from}' exists — the file was moved or deleted after the reorg` });
          continue;
        }
        // no-clobber: the original path must be free before we move back onto it.
        const guard = await checkPathAgainstExpectation({ rootPath: root, path: mv.from, expected: { exists: false }, fs });
        if (!guard.ok) {
          await journal.append('fs-move-back', { from: mv.to, to: mv.from, state: 'refused', code: REORG_REFUSAL.DEST_OCCUPIED, reason: guard.reason });
          refused.push({ path: mv.from, code: REORG_REFUSAL.DEST_OCCUPIED, reason: guard.reason, message: `'${mv.from}' is occupied (${guard.reason}) — the move-back is refused rather than overwrite it; the moved copy stays at '${mv.to}'` });
          continue;
        }
        await journal.append('fs-move-back', { from: mv.to, to: mv.from, state: 'started' });
        await moveFile(fs, destAbs, srcAbs);
        const afterHash = await hashOrNull(fs, srcAbs);
        await journal.append('fs-move-back', { from: mv.to, to: mv.from, state: 'done', hash: afterHash, k: ++k, n: fsDone.length });
        restored.push({ path: mv.from, hash: afterHash, bitIdentical: mv.hash ? afterHash === mv.hash : null });
      }
    }

    await journal.append('state', { state: REORG_UNDO_STATE.UNDO_DONE, restored: restored.length, refused: refused.length });

    const status = refused.length ? (restored.length || revert ? REORG_STATUS.PARTIAL : REORG_STATUS.REFUSED) : REORG_STATUS.ROLLED_BACK;
    const result = {
      status,
      revert,
      restored,
      refused,
      commit: revert ? revert.commit : null,
      message: [
        revert ? `git revert committed as ${revert.commit.slice(0, 7)}` : null,
        fsDone.length ? `${restored.length} file(s) moved back, ${refused.length} refused` : null,
      ].filter(Boolean).join('; '),
      journal: { dir: journal.dir, file: journal.file },
    };
    await journal.writeSummary({ ...result, at: now().toISOString() });
    return result;
  } finally {
    if (!borrowed) await lock.release().catch(() => {});
  }
}

export default {
  REORG_KIND,
  REORG_CONTENT_CLASS,
  REORG_EXECUTOR,
  REORG_UNDO,
  REORG_APPLY_STATE,
  REORG_UNDO_STATE,
  REORG_STATUS,
  REORG_RECOVERY,
  REORG_REFUSAL,
  classifyReorgMember,
  partitionReorgMove,
  preflightReorgFs,
  applyReorgMove,
  recoverReorgApply,
  undoReorgMove,
};

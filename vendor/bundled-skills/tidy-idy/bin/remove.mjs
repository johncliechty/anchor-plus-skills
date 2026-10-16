#!/usr/bin/env node
// remove.mjs — GIT IS THE ARCHIVE (C9, 2026-07-11; replaces the deleted archive.mjs).
//
// The old subsystem moved REMOVE verdicts to .archive/ with a manifest, then
// HARD-DELETED them after a 30-day TTL — ~250 lines whose permanent-deletion paths
// were the tool's whole risk surface (≤10 files deleted per run with NO
// confirmation; a timestamp "Safety Interlock" that defended against conditions
// that cannot occur). The hygiene gate already guarantees everything is committed
// and pushed before tidy-idy touches anything, so git IS the archive:
//
//   REMOVE verdict → fs.rm (path-contained, protected-set enforced)
//                  → ONE commit: "tidy-idy: remove <n> dead file(s) ..."
//   Recovery       → `git revert <commit>` (or checkout any file from HEAD~1).
//
// NOTHING in this module can lose work that git holds, and it refuses to run
// where git does not hold it (hygiene.mjs enforces that upstream).

import fs from 'node:fs/promises';
import path from 'node:path';
import { exec } from 'node:child_process';
import { promisify } from 'node:util';
import { promptUser } from './hygiene.mjs';
import { resolveTidyIdyKnobs } from '../engine/triage-knobs.mjs';

const execAsync = promisify(exec);

/**
 * Files tidy-idy must NEVER remove, regardless of any judgment: governance and
 * capture surfaces, tests, and executable entry points. (A judge verdict against
 * these is reported as PROTECTED, never acted on.)
 */
export const PROTECTED_PATTERNS = [
  /^SKILL\.md$/i,
  /^NORTH-STAR\.md$/i,
  /^INTENT\.md$/i,
  /^LESSONS\.md$/i,
  /^CHANGELOG\.md$/i,
  /^README\.md$/i,
  /(^|\/)journal(\/|$)/i,
  /(^|\/)tests?(\/|$)/i,
  /\.(test|spec)\.(m?js|cjs|ts|py)$/i,
  /(^|\/)bin(\/|$)/i,
];

export function isProtected(relPath) {
  const rel = String(relPath).replace(/\\/g, '/');
  return PROTECTED_PATTERNS.some((re) => re.test(rel));
}

/** How many removals in one project require an explicit human confirmation. */
export const REMOVAL_CONFIRM_THRESHOLD = 10;

/**
 * Resolve max removals per batch from @foundry/triage when depth resolves.
 * Sole numeric path: resolveTidyIdyKnobs → tidyIdyKnobs → BAND_MAPPINGS['tidy-idy'].
 * Never thins PROTECTED_PATTERNS. Explicit options.maxRemovalsPerBatch wins.
 * No depth → null (uncapped legacy).
 */
export function resolveMaxRemovalsPerBatch(options = {}) {
  if (options.maxRemovalsPerBatch != null && Number.isFinite(Number(options.maxRemovalsPerBatch))) {
    return Math.max(1, Math.floor(Number(options.maxRemovalsPerBatch)));
  }
  const knobs = resolveTidyIdyKnobs(options);
  if (!knobs) return null;
  const n = /** @type {{ maxRemovalsPerBatch?: unknown }} */ (knobs).maxRemovalsPerBatch;
  if (n == null || !Number.isFinite(Number(n))) return null;
  return Math.max(1, Math.floor(Number(n)));
}

export { resolveTidyIdyKnobs };

/**
 * Execute REMOVE judgments for one project: delete the files, then commit the
 * deletions so git carries the undo. Returns { removed, protectedSkips, skipped,
 * commit } — no TTLs, no manifests, no hard-delete queue.
 *
 * @param {string} projectPath
 * @param {Array<{filepath:string, verdict:string, reasoning?:string}>} judgments
 * @param {object} options { exec, interactive, stdout, stdin, log, maxRemovalsPerBatch, triageDepth }
 */
export async function runRemoval(projectPath, judgments, options = {}) {
  const log = options.log || (() => {});
  const outputStream = options.stdout || process.stdout;
  const execFn = options.exec || execAsync;
  const resolvedProject = path.resolve(projectPath);
  const maxBatch = resolveMaxRemovalsPerBatch(options);

  const removed = [];
  const protectedSkips = [];
  const skipped = [];

  // 1. Collect the actionable REMOVE set: exact existing files, inside the project,
  //    not protected. Protect / RETAIN filter ALWAYS runs first at every depth
  //    (LITE thins ceremony batch size only — never PROTECTED_PATTERNS or RETAIN).
  //    Everything else is reported, never guessed at.
  const toRemove = [];
  for (const j of judgments || []) {
    // The debate engine emits `decision`; accept `verdict` too (same meaning) —
    // the field mismatch was caught by the test-adaptation pass before it could
    // ship a tool that never removed anything end-to-end.
    const verdict = String(j?.verdict ?? j?.decision ?? '').toUpperCase();
    if (verdict !== 'REMOVE') { skipped.push({ ...j, why: 'verdict not REMOVE' }); continue; }
    const abs = path.resolve(resolvedProject, j.filepath);
    const rel = path.relative(resolvedProject, abs);
    if (rel.startsWith('..') || path.isAbsolute(rel)) { skipped.push({ ...j, why: 'outside the project (path containment)' }); continue; }
    // Protect before any band-thin cap — never drop protect hits to meet maxRemovalsPerBatch.
    if (isProtected(rel)) { protectedSkips.push({ ...j, rel, why: 'PROTECTED file class — never removed' }); continue; }
    try {
      const st = await fs.stat(abs);
      if (!st.isFile()) { skipped.push({ ...j, why: 'not a regular file' }); continue; }
    } catch { skipped.push({ ...j, why: 'file does not exist' }); continue; }
    toRemove.push({ ...j, abs, rel });
  }

  if (!toRemove.length) {
    return { removed, protectedSkips, skipped, commit: null };
  }

  // 1b. Band-thin AFTER protect filter (B5 P2): cap from live mapping
  // maxRemovalsPerBatch only. Overflow → skipped with deferred why; protected
  // hits already in protectedSkips and are never used to "make room" for the cap.
  if (maxBatch != null && toRemove.length > maxBatch) {
    log(`band-thin: capping removals ${toRemove.length} → ${maxBatch} (maxRemovalsPerBatch)`);
    const deferred = toRemove.splice(maxBatch);
    deferred.forEach((t) => skipped.push({ ...t, why: `deferred: triage maxRemovalsPerBatch=${maxBatch}` }));
  }

  // 2. Human gate on LARGE removal sets (git makes every removal recoverable, but
  //    a big sweep still deserves a look before it lands as a commit).
  if (toRemove.length > REMOVAL_CONFIRM_THRESHOLD) {
    const isInteractive = options.interactive !== undefined ? options.interactive : process.stdin.isTTY;
    if (!isInteractive) {
      outputStream.write(`REMOVAL DEFERRED: ${toRemove.length} files exceed the ${REMOVAL_CONFIRM_THRESHOLD}-file gate and no human is attached — nothing removed this run.\n`);
      toRemove.forEach((t) => skipped.push({ ...t, why: `deferred: >${REMOVAL_CONFIRM_THRESHOLD} removals need interactive confirmation` }));
      return { removed, protectedSkips, skipped, commit: null };
    }
    const answer = await promptUser({
      question: `Remove ${toRemove.length} files from '${projectPath}' (git-recoverable via revert)?`,
      context: toRemove.map((t) => `- ${t.rel}: ${String(t.reasoning || '').slice(0, 120)}`).join('\n'),
      explanation: 'Every removal is committed in one tidy-idy commit; recovery is `git revert <commit>`. The set is large, so confirm before it lands.',
      options: ['Proceed with the removal + commit.', 'Skip removals this run (report only).'],
      recommendation: 'Review the list; choose 1 if it reads as dead weight, 2 if anything looks load-bearing.',
    }, options);
    if (answer !== '1') {
      toRemove.forEach((t) => skipped.push({ ...t, why: 'human declined the removal set' }));
      return { removed, protectedSkips, skipped, commit: null };
    }
  }

  // 3. Remove + commit (git carries the undo).
  for (const t of toRemove) {
    await fs.rm(t.abs);
    removed.push({ filepath: t.rel, reasoning: t.reasoning || null });
    log(`removed: ${t.rel}`);
  }
  let commit = null;
  try {
    await execFn('git add -A', { cwd: resolvedProject });
    const msg = `tidy-idy: remove ${removed.length} dead file(s) (recovery: git revert this commit)`;
    await execFn(`git commit -m "${msg}"`, { cwd: resolvedProject });
    const { stdout } = await execFn('git rev-parse --short HEAD', { cwd: resolvedProject });
    commit = String(stdout).trim();
    outputStream.write(`Committed ${removed.length} removal(s) as ${commit} — recovery: git revert ${commit}\n`);
  } catch (err) {
    // A failed commit after deletion would leave the tree dirty with no undo
    // handle — that is a HARD error, not a warning (never leave removals uncommitted).
    throw new Error(`removal commit FAILED after deleting ${removed.length} file(s) in ${projectPath}: ${err.message} — restore with 'git checkout -- .' and investigate`);
  }
  return { removed, protectedSkips, skipped, commit };
}

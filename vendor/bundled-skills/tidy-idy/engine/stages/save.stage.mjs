// engine/stages/save.stage.mjs — Wave 2: the SAVE finding class.
//
// The second finding class, built on git's own porcelain and on nothing else.
// Untracked files and modified-tracked files become SAVE findings carrying the
// VERBATIM porcelain record, a content hash recorded into snapshot S, and the
// exact diff of what a commit WOULD contain.
//
// "BLIND `git add` IS STRUCTURALLY IMPOSSIBLE" is the load-bearing property, and
// it is a property of the DATA, not of the executor's good intentions: a SAVE
// finding never carries a path-and-please-add-it instruction. It carries a
// content hash taken at snapshot time plus the rendered diff, and Wave 3's Apply
// hashes THAT recorded content into its temp index. If the file changed after
// the scan, the hash no longer matches and the finding drops as stale — so
// there is no code path through which "save this file" can mean "commit whatever
// happens to be on disk at Apply time".
//
// Two exclusions are absolute:
//   • .gitignore'd files are never offered. git deliberately does not report
//     them as untracked, so they never enter the candidate set at all.
//   • Secret-flagged paths are never offered. The Wave-2 gate ran upstream of
//     this stage; a flagged path is skipped here and surfaces only as the
//     triage stage's non-approvable BLOCKED tile.

import path from 'node:path';
import { makeStageResult, STATUS } from '../envelope.mjs';
import { loadPorcelain, TRACKING } from '../porcelain.mjs';
import { ensureHash } from '../snapshot.mjs';
import { renderUnifiedDiff, diffStats } from '../diff.mjs';
import { LLM_READ_CAP_BYTES } from '../secret-triage.mjs';

/** The only op kind a SAVE finding may carry. Never `git add <path>`. */
export const SAVE_OP_KIND = 'save-blob';

export const saveStage = {
  name: 'save',
  requiresGit: true,
  gitNull: {
    status: STATUS.OK,
    // Exact cap, and it is zero: without a repository there is nothing to commit
    // TO, so a SAVE finding would be an offer the tool cannot honour.
    findings: 0,
    note: 'no repo — SAVE requires somewhere to commit to; zero findings, and the preflight proposes the optional Bootstrap instead',
  },

  async run(ctx) {
    if (!ctx.git) {
      return makeStageResult({
        stage: saveStage.name,
        status: STATUS.OK,
        coverage: { scanned: 0, skipped: 0, errored: 0, note: saveStage.gitNull.note },
        findings: [],
        notes: [
          'no git repository at the run root — SAVE is not offered because there is no history to save into; this is a declared, supported state',
          'the preflight stage proposes Bootstrap (optional, never a gate); removals here flow through the reversible Trash (Amendment A)',
        ],
      });
    }

    let porcelain;
    try {
      porcelain = await loadPorcelain(ctx);
    } catch (err) {
      return makeStageResult({
        stage: saveStage.name,
        status: STATUS.FAILED,
        coverage: { scanned: 0, skipped: 0, errored: 1, note: 'git status could not be read — SAVE candidates are UNKNOWN for this run, not empty' },
        errors: [{ name: err.name || 'Error', message: `git status --porcelain=v2 failed: ${err.message}` }],
        findings: [],
      });
    }

    const inScope = new Set((ctx.state.inScope || []).map(String));
    const triage = ctx.state.triage || new Map();
    const blocked = ctx.state.llmBlocked || new Set();
    const snapshot = ctx.state.snapshot;

    const findings = [];
    const errors = [];
    let secretBlockedCount = 0;
    let outOfScope = 0;

    for (const rec of porcelain.records) {
      // .gitignore'd content is not a candidate: git does not report it as
      // untracked, and the ignored records we do see exist only to classify.
      if (rec.trackingClass === TRACKING.IGNORED) continue;
      if (rec.trackingClass === TRACKING.TRACKED_CLEAN) continue;
      // Topology decides the tree; a path git reports but the run excluded
      // (nested repo, excluded subtree, link object) is not ours to offer.
      if (!inScope.has(rec.path)) { outOfScope++; continue; }
      if (ctx.protection.isExcluded(rec.path)) { outOfScope++; continue; }

      if (blocked.has(rec.path)) {
        // Hard-blocked upstream. No SAVE finding, therefore no approval control.
        secretBlockedCount++;
        continue;
      }

      const abs = path.join(ctx.rootPath, rec.path);
      const verdict = triage.get(rec.path) || null;

      let contentHash = null;
      if (snapshot) {
        try { contentHash = await ensureHash(snapshot, rec.path, { fs: ctx.fs }); } catch { contentHash = null; }
      }

      let overlap;
      try {
        overlap = await computeDirtyOverlap(ctx, rec, verdict);
      } catch (err) {
        errors.push({ message: `could not compute the would-be-committed diff for '${rec.path}': ${err.message}` });
        overlap = { available: false, reason: err.message };
      }

      findings.push({
        stage: saveStage.name,
        kind: 'save-candidate',
        action: 'save',
        path: rec.path,
        absolutePath: abs,
        trackingClass: rec.trackingClass,
        // git's own line, verbatim — the panel quotes this, never a paraphrase.
        porcelain: rec.raw,
        porcelainRecord: { kind: rec.kind, xy: rec.xy, staged: rec.staged, unstaged: rec.unstaged, ...(rec.origPath ? { origPath: rec.origPath } : {}) },
        contentHash,
        /**
         * The ONLY op a SAVE finding carries. It names the exact bytes (by hash,
         * taken at snapshot time) rather than the path — which is what makes a
         * blind `git add` structurally impossible rather than merely discouraged.
         */
        op: {
          kind: SAVE_OP_KIND,
          path: rec.path,
          contentHash,
          source: 'working tree as at snapshot S',
          note: 'Apply hashes exactly this content into its temp index; a post-scan change makes the hash mismatch and the finding drops as stale',
        },
        dirtyOverlap: overlap,
        // A staged path is flagged, never silently folded in: approving this
        // tile would commit the STAGED content too, and the user must see that.
        hasStagedChanges: rec.staged,
        ...(rec.staged ? {
          stagedWarning: 'this path has STAGED changes — approving the SAVE commits the staged content shown in the diff below, not just the unstaged edit',
        } : {}),
        quarantine: verdict ? verdict.quarantine : null,
        bulkApprovable: !(verdict && verdict.quarantine),
        defaultChecked: false,
        why: rec.trackingClass === TRACKING.UNTRACKED
          ? 'git does not hold this file at all — a SAVE commit is what makes it recoverable'
          : 'git holds an older version of this file — the working-tree edit is not yet recoverable from history',
      });
    }

    const notes = [
      `${findings.length} SAVE candidate(s) from \`git status --porcelain=v2\` (untracked + modified-tracked)`,
      ".gitignore'd paths are never offered — git does not report them as untracked, so they never enter the candidate set",
      'no SAVE finding carries a `git add <path>` instruction; each names the exact content hash Apply must realise',
    ];
    if (secretBlockedCount) notes.push(`${secretBlockedCount} candidate(s) hard-blocked by the pre-LLM secret gate and NOT offered for SAVE — they appear as non-approvable BLOCKED tiles`);
    if (outOfScope) notes.push(`${outOfScope} path(s) git reported but the run's topology/exclusion policy places outside scope`);
    if (porcelain.indexError) notes.push(`git ls-files failed (${porcelain.indexError}) — tracking classes degrade to 'unknown' and removal eligibility fails safe`);

    return makeStageResult({
      stage: saveStage.name,
      status: errors.length ? STATUS.PARTIAL : STATUS.OK,
      coverage: {
        scanned: porcelain.records.length,
        skipped: 0,
        errored: errors.length,
        note: `${porcelain.records.length} porcelain record(s) considered; ${secretBlockedCount} withheld by the secret gate`,
      },
      errors,
      findings,
      notes,
      data: { branch: porcelain.branch, dirtyCount: porcelain.dirtyCount() },
    });
  },
};

/**
 * The exact diff a SAVE would commit, plus whether the file moved since the
 * scan. "Flagged with the exact would-be-committed diff" is the plan's wording
 * and it is meant literally: for a tracked file that is `git diff HEAD -- path`,
 * git's own rendering, not ours.
 */
async function computeDirtyOverlap(ctx, rec, verdict) {
  const snapshot = ctx.state.snapshot;
  const rel = rec.path;
  const abs = path.join(ctx.rootPath, rel);

  const meta = snapshot && snapshot.paths ? snapshot.paths[rel] : null;
  let changedSinceScan = false;
  let current = null;
  try {
    const st = await ctx.fs.stat(abs);
    current = { size: st.size, mtimeMs: Math.round(st.mtimeMs) };
    if (meta && (current.size !== meta.size || current.mtimeMs !== meta.mtimeMs)) changedSinceScan = true;
  } catch {
    changedSinceScan = true;
  }

  // Oversize/binary content is described, never rendered — a diff of a 40MB
  // binary is not evidence, it is a denial of service on the panel.
  if (verdict && verdict.quarantine) {
    return {
      available: false,
      reason: `quarantined (${verdict.quarantine}) — the would-be-committed content is ${verdict.quarantine === 'binary' ? 'binary' : `${verdict.size} bytes, past the ${LLM_READ_CAP_BYTES}-byte render cap`}; approve individually after inspecting the file yourself`,
      changedSinceScan,
      staged: rec.staged,
    };
  }

  if (rec.trackingClass === TRACKING.UNTRACKED) {
    let content = '';
    try {
      content = await ctx.fs.readFile(abs, 'utf8');
    } catch (err) {
      return { available: false, reason: `unreadable: ${err.message}`, changedSinceScan, staged: false };
    }
    return {
      available: true,
      source: 'whole-file (untracked: every line is an addition)',
      diff: renderUnifiedDiff('', content, { fromLabel: '/dev/null', toLabel: `b/${rel}` }),
      stats: diffStats('', content),
      changedSinceScan,
      staged: false,
    };
  }

  // Tracked-with-changes: git renders it. `git diff HEAD` covers staged AND
  // unstaged together, which is exactly what the commit would contain.
  const { stdout } = await ctx.git.run(['diff', 'HEAD', '--', rel]);
  return {
    available: true,
    source: 'git diff HEAD -- <path> (staged and unstaged together — exactly what the commit would contain)',
    diff: String(stdout),
    changedSinceScan,
    staged: rec.staged,
    ...(changedSinceScan ? {
      changedWarning: 'this file changed on disk AFTER the run snapshot S — the diff above is git\'s current view; Apply-time revalidation drops the finding unless it is re-validated',
    } : {}),
  };
}

export default saveStage;

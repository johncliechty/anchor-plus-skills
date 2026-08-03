// engine/stages/reorg.stage.mjs — Wave 8: leaf/asset-directory move proposals.
//
// Reorg is the third finding class and the most dangerous: a move can break a
// reference. v1 proposes moves ONLY for leaf/asset directories, and every
// proposal carries a WHOLE-TREE textual reference scan (grep for the directory
// and its members across every in-scope text file INCLUDING tsconfig / Dockerfile
// / CI workflows / configs), with the hit list stored on the finding.
//
// The Apply gate is owned here, in the shape the finding takes:
//
//   eligible = leaf/asset directory move AND zero-hit reference scan.
//     Rendered as a normal approvable tile; may ride bulk-approve.
//
//   non-zero-hit  → the tile is ADVISORY: excluded from bulk-approve, applyable
//     ONLY through its own explicit 'Apply anyway — I'll fix the references'
//     click-through override, never in bulk (Amendment C.i).
//
// v1 never edits file contents to fix references (that automation is deferred);
// it only proposes the move and shows the evidence, so approval is a judgment
// about visible structure. The move is EXECUTED by engine/apply/reorg.mjs through
// the per-path content-class partition (tracked / untracked-in-git / non-git).
//
// This stage is filesystem-and-textual only, so it runs identically with or
// without a repository — git absence changes only the executor/undo the move
// lands through (journaled move-set instead of a git commit), never whether a
// proposal is produced.

import path from 'node:path';
import { makeStageResult, STATUS } from '../envelope.mjs';
import { loadPorcelain } from '../porcelain.mjs';
import { classifyReorgMember } from '../apply/reorg.mjs';

/** Extensions that make a directory an "asset directory" rather than source. */
const ASSET_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.avif',
  '.mp3', '.wav', '.ogg', '.flac', '.mp4', '.webm', '.mov', '.woff', '.woff2',
  '.ttf', '.otf', '.eot', '.pdf', '.csv', '.tsv', '.dat', '.bin',
]);

/** Directory roots that already ARE a conventional home for assets. */
const CONVENTIONAL_ASSET_ROOTS = ['assets', 'static', 'public', 'media', 'images', 'img', 'fonts'];

/** The conventional destination a stray asset directory is proposed to move to. */
const ASSET_HOME = 'assets';

/** Reference-scan a file only if it is small enough to be cheap and textual. */
const REFERENCE_SCAN_CAP_BYTES = 512 * 1024;

function ext(rel) {
  const base = rel.split('/').pop() || '';
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot).toLowerCase() : '';
}

function dirOf(rel) {
  const i = rel.lastIndexOf('/');
  return i === -1 ? '' : rel.slice(0, i);
}

function firstSegment(rel) {
  const i = rel.indexOf('/');
  return i === -1 ? rel : rel.slice(0, i);
}

export const reorgStage = {
  name: 'reorg',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    // The reference scan and the leaf/asset detection are filesystem-and-textual;
    // git absence removes no behaviour, it only changes the executor the move
    // would land through (journaled move-set instead of a git commit).
    findings: Number.POSITIVE_INFINITY,
    note: 'no repo — leaf/asset-directory reorg proposals and the whole-tree textual reference scan run unchanged; git absence only changes the apply/undo path (journaled move-set instead of git commit + revert)',
  },

  async run(ctx) {
    const inScope = (ctx.state.inScope || []).filter((rel) => !ctx.protection.isProtected(rel));
    const snapshot = ctx.state.snapshot;
    const blocked = ctx.state.llmBlocked || new Set();
    const porcelain = await loadPorcelain(ctx).catch(() => null);

    // --- group in-scope files by their directory ---------------------------
    const filesByDir = new Map();
    const dirsWithSubdirFiles = new Set();
    for (const rel of inScope) {
      const d = dirOf(rel);
      if (!filesByDir.has(d)) filesByDir.set(d, []);
      filesByDir.get(d).push(rel);
      // Mark every ancestor of a deeper file so we can tell a leaf from a branch.
      let a = d;
      while (a) {
        const parent = dirOf(a);
        if (parent !== a) dirsWithSubdirFiles.add(parent);
        if (!parent) break;
        a = parent;
      }
    }

    // --- select candidate leaf/asset directories ---------------------------
    const candidates = [];
    for (const [dir, files] of filesByDir) {
      if (!dir) continue;                                   // the root itself is never a move
      if (dirsWithSubdirFiles.has(dir)) continue;           // not a leaf — it has subdirectories with files
      if (files.length === 0) continue;
      // Already living in a conventional asset home? Leave it be.
      if (CONVENTIONAL_ASSET_ROOTS.includes(firstSegment(dir))) continue;
      // Asset directory: every direct file is a non-source asset by extension.
      const assetish = files.every((f) => ASSET_EXTENSIONS.has(ext(f)));
      if (!assetish) continue;
      candidates.push({ dir, files });
    }

    // --- for each candidate, run the whole-tree reference scan --------------
    const findings = [];
    const errors = [];
    let scannedForRefs = 0;

    for (const cand of candidates) {
      const { dir, files } = cand;
      const to = `${ASSET_HOME}/${dir.split('/').pop()}`;
      if (to === dir) continue; // already at its conventional destination

      // The needles: the directory path, every member path, and every member
      // basename. A reference to any of these breaks if the directory moves.
      const needles = new Set([dir]);
      for (const f of files) {
        needles.add(f);
        needles.add(f.split('/').pop());
      }

      const hits = [];
      let refError = false;
      for (const rel of inScope) {
        // References from INSIDE the moved directory travel with it — only
        // external files can be broken by the move.
        if (rel === dir || rel.startsWith(`${dir}/`)) continue;
        if (blocked.has(rel)) continue; // never read blocked content for any purpose
        const meta = snapshot && snapshot.paths ? snapshot.paths[rel] : null;
        if (meta && meta.size > REFERENCE_SCAN_CAP_BYTES) continue;
        let text;
        try {
          text = await ctx.fs.readFile(path.join(ctx.rootPath, rel), 'utf8');
        } catch { refError = true; continue; }
        if (text.includes(String.fromCharCode(0))) continue; // binary: not a reference source
        scannedForRefs++;
        const lines = text.split('\n');
        for (let i = 0; i < lines.length; i++) {
          for (const needle of needles) {
            if (needle && lines[i].includes(needle)) {
              hits.push({ path: rel, line: i + 1, needle, text: lines[i].trim().slice(0, 200) });
              break; // one hit per line is enough evidence
            }
          }
        }
      }
      if (refError) errors.push({ path: dir, message: 'one or more files could not be read during the reference scan' });

      const hitCount = hits.length;
      const eligible = hitCount === 0;

      // The content-class preview each member falls into (authoritative partition
      // is recomputed at apply time; this is for the tile).
      const memberClasses = files.map((f) => {
        const c = classifyReorgMember({ rel: f, porcelain, git: ctx.git });
        return { path: f, contentClass: c.contentClass, trackingClass: c.trackingClass, eligible: c.eligible };
      });

      findings.push({
        stage: reorgStage.name,
        kind: 'reorg-proposal',
        action: 'reorg',
        path: dir,
        absolutePath: path.join(ctx.rootPath, dir),
        move: { from: dir, to },
        members: files,
        memberClasses,
        referenceScan: {
          hitCount,
          hits: hits.slice(0, 50), // cap the stored evidence; hitCount is exact
          truncated: hits.length > 50,
          scannedFiles: scannedForRefs,
          scope: 'whole-tree textual scan of every in-scope file including config/CI/build files',
        },
        before: renderTree(dir, files),
        after: renderTree(to, files.map((f) => `${to}/${f.slice(dir.length + 1)}`)),
        eligible,
        // Non-zero-hit proposals require the per-proposal override: excluded from
        // bulk-approve and applyable ONLY through the explicit click-through
        // (Amendment C.i). Kept in its OWN field — never `advisory`, which the
        // pipeline reserves for the run-level no-repository marker.
        overrideRequired: !eligible,
        referenceUnsafe: eligible ? null : {
          hitCount,
          reason: `the whole-tree reference scan found ${hitCount} hit(s) — moving this directory would break ${hitCount} reference(s) unless you fix them yourself`,
          overrideLabel: "Apply anyway — I'll fix the references",
        },
        bulkApprovable: eligible,
        defaultChecked: false,
        why: eligible
          ? `leaf/asset directory with ZERO references anywhere in the tree — moving it to '${to}' cannot break a reference`
          : `leaf/asset directory referenced ${hitCount} time(s) — advisory only; applyable via the explicit per-proposal override`,
      });
    }

    return makeStageResult({
      stage: reorgStage.name,
      status: errors.length ? STATUS.PARTIAL : STATUS.OK,
      coverage: {
        scanned: filesByDir.size,
        skipped: 0,
        errored: errors.length,
        note: `${candidates.length} leaf/asset directory candidate(s) evaluated; each reference-scanned across the whole in-scope tree`,
      },
      errors,
      findings,
      notes: [
        `${findings.length} reorg proposal(s): ${findings.filter((f) => f.eligible).length} zero-hit (approvable), ${findings.filter((f) => !f.eligible).length} advisory (override-only)`,
        'v1 proposes moves only for leaf/asset directories and never edits file contents to fix references',
      ],
      data: { candidates: candidates.length },
    });
  },
};

/** A tiny before/after tree rendering for the tile (one path per line, sorted). */
function renderTree(root, paths) {
  return { root, entries: [...paths].sort() };
}

export default reorgStage;

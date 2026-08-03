// engine/apply/revalidate.mjs — Wave 3: Apply-time revalidation against S.
//
// Step 2 of the canonical Apply pipeline. Snapshot S (Wave 1) is the single time
// authority; this module is the place where "the world as the human read it"
// meets "the world as it is now", and every disagreement resolves the same way:
// THE FINDING DROPS. It is never coerced, never re-derived, never applied
// against content nobody looked at.
//
// Three checks, each closing a distinct way to lose work:
//
//   CONTENT HASH — the bytes are the bytes the tile described. Without this,
//     "remove foo.md" approved at 09:00 would delete whatever foo.md contains at
//     09:40, including forty minutes of work git has never seen.
//
//   EXISTENCE — the path is still there (or, for a proposal that creates a file,
//     still absent). Applying to a vanished path is at best a no-op and at worst
//     a resurrection of something the user just deleted.
//
//   PORCELAIN CLASS, INCLUDING NEWLY-STAGED — a path that became STAGED after
//     the scan is carrying an intention the tool knows nothing about. Committing
//     it would fold the user's staged work into a tidy commit they did not
//     approve, and step 5's working-tree realization would then overwrite it.
//
// A finding with no recorded content hash cannot be checked at all, so it is
// dropped too. The fail-safe direction is always "do less".

import fsp from 'node:fs/promises';
import path from 'node:path';
import { hashFile } from '../snapshot.mjs';
import { TRACKING } from '../porcelain.mjs';
import { toPosixRel } from '../glob.mjs';

export const STALE_REASON = Object.freeze({
  MISSING: 'missing',
  UNEXPECTEDLY_PRESENT: 'unexpectedly-present',
  CONTENT_CHANGED: 'content-changed',
  CLASS_CHANGED: 'class-changed',
  NEWLY_STAGED: 'newly-staged',
  NO_BASELINE: 'no-baseline-hash',
  UNREADABLE: 'unreadable',
});

const STALE_MESSAGE = {
  [STALE_REASON.MISSING]: 'the path no longer exists — it was removed or renamed after the scan',
  [STALE_REASON.UNEXPECTEDLY_PRESENT]: 'the path now exists although the approved proposal was to create it — applying would overwrite content nobody has seen',
  [STALE_REASON.CONTENT_CHANGED]: 'the file changed on disk after the run snapshot S — the bytes on the tile are not the bytes on disk',
  [STALE_REASON.CLASS_CHANGED]: "the path's git status class changed after the scan — the operation was reasoned about against a different relationship to git",
  [STALE_REASON.NEWLY_STAGED]: 'the path has been STAGED since the scan — a tidy commit would fold in staged work the user never offered to this tool',
  [STALE_REASON.NO_BASELINE]: 'no content hash was recorded for this finding, so it cannot be revalidated — the fail-safe is to drop it, never to apply it unchecked',
  [STALE_REASON.UNREADABLE]: 'the path could not be read at Apply time',
};

/** Actions whose subject file must exist and match its recorded bytes. */
const NEEDS_EXISTING_FILE = new Set(['remove', 'save', 'trash', 'move', 'reorg']);

/**
 * Revalidate approved findings against S and against git's CURRENT porcelain.
 *
 * @param {{findings: object[], snapshot: object, porcelain: object|null,
 *   rootPath: string, fs?: object}} opts
 * @returns {Promise<{survivors: object[], stale: object[]}>}
 */
export async function revalidateFindings({ findings = [], snapshot = null, porcelain = null, rootPath, fs = fsp } = {}) {
  const survivors = [];
  const stale = [];

  const drop = (f, reason, detail = {}) => {
    stale.push({
      id: f.id || null,
      path: f.path,
      action: f.action,
      reason,
      message: `stale — re-run: ${STALE_MESSAGE[reason]}`,
      ...detail,
    });
  };

  for (const f of findings) {
    const rel = toPosixRel(f.path);
    const abs = path.join(rootPath, rel);
    const createsFile = Boolean(f.proposal && f.proposal.createsFile);

    // ---- existence -------------------------------------------------------
    let exists = true;
    let currentHash = null;
    try {
      currentHash = await hashFile(abs, { fs });
    } catch (err) {
      if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) exists = false;
      else { drop(f, STALE_REASON.UNREADABLE, { error: err && err.message }); continue; }
    }

    if (createsFile) {
      if (exists) { drop(f, STALE_REASON.UNEXPECTEDLY_PRESENT, { now: currentHash }); continue; }
    } else if (!exists) {
      drop(f, STALE_REASON.MISSING);
      continue;
    }

    // ---- content hash vs S ----------------------------------------------
    if (!createsFile) {
      const expected = f.contentHash ?? (snapshot && snapshot.hashes ? snapshot.hashes[rel] : null) ?? null;
      if (!expected) {
        if (NEEDS_EXISTING_FILE.has(f.action) || f.action === 'propose-content') { drop(f, STALE_REASON.NO_BASELINE); continue; }
      } else if (expected !== currentHash) {
        drop(f, STALE_REASON.CONTENT_CHANGED, { expected, now: currentHash });
        continue;
      }
    }

    // ---- porcelain class, including "no newly-staged changes" ------------
    if (porcelain) {
      const currentClass = porcelain.classify(rel);
      const expectedClass = f.trackingClass || null;

      const wasStaged = expectedClass === TRACKING.STAGED;
      if (!wasStaged && currentClass === TRACKING.STAGED) {
        drop(f, STALE_REASON.NEWLY_STAGED, { was: expectedClass, now: currentClass });
        continue;
      }
      if (expectedClass && currentClass !== expectedClass) {
        drop(f, STALE_REASON.CLASS_CHANGED, { was: expectedClass, now: currentClass });
        continue;
      }
    }

    survivors.push(f);
  }

  return { survivors, stale };
}

/**
 * HEAD == S.head, asserted under the lock immediately before anything is
 * compiled. A moved HEAD means every hash in S describes a tree that is no
 * longer the parent of the commit we are about to write.
 */
export function assertHeadMatchesSnapshot(head, snapshot) {
  const expected = snapshot ? snapshot.head : null;
  if (!expected) {
    return { ok: false, message: 'the run snapshot S records no HEAD — Apply has no baseline to revalidate against and refuses' };
  }
  if (head !== expected) {
    return {
      ok: false,
      message: `HEAD moved since the scan (snapshot S recorded ${expected}, HEAD is now ${head}) — every finding was reasoned about against the old tree; re-scan and approve again`,
      snapshotHead: expected,
      currentHead: head,
    };
  }
  return { ok: true, head };
}

export default { revalidateFindings, assertHeadMatchesSnapshot, STALE_REASON };

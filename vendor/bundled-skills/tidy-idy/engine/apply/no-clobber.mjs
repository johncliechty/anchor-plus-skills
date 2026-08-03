// engine/apply/no-clobber.mjs — Wave 3: the NO-CLOBBER UNDO INVARIANT.
//
//   Before writing ANY destination path, a restorer compares that path's current
//   content against the journaled expected post-Apply state. A mismatch — the
//   user edited or recreated the path after the Apply — REFUSES that path's
//   restore, with a diff and a copyable manual command, while the remaining
//   paths proceed.
//
// This is a SYSTEM-WIDE rule, deliberately built as its own module rather than
// inside the git-undo path: Wave 4's Trash restore, Wave 8's reorg move-back and
// Bootstrap's undo all import this and get the same refusal semantics. An undo
// that silently overwrites work created after the Apply is the same data-loss
// failure the whole tool exists to prevent, just wearing a helpful mask.
//
// EXPECTED STATE. A correct Apply leaves the working tree matching commit C for
// every path C touched: SAVE paths hold C's content, REMOVE paths are absent,
// MOVE destinations hold C's content and MOVE sources are absent. So C ITSELF is
// a complete, authoritative expectation — the journal is consulted when present
// (it is more explicit), but the check still works after `.tidy-idy/` has been
// deleted, which is a directory people delete.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { revBytes, revSize } from './git-plumbing.mjs';
import { renderUnifiedDiff } from '../diff.mjs';
import { hashFile } from '../snapshot.mjs';

export const CLOBBER_REASON = Object.freeze({
  EDITED: 'edited-after-apply',
  RECREATED: 'recreated-after-apply',
  DELETED: 'deleted-after-apply',
  UNREADABLE: 'unreadable',
});

function looksBinary(buf) {
  if (!buf) return false;
  return buf.slice(0, 8000).includes(0);
}

function renderRefusalDiff(expected, actual, rel) {
  if (looksBinary(expected) || looksBinary(actual)) {
    return { available: false, reason: 'binary content — a rendered diff would not be evidence' };
  }
  return {
    available: true,
    diff: renderUnifiedDiff(
      expected ? expected.toString('utf8') : '',
      actual ? actual.toString('utf8') : '',
      { fromLabel: `expected (what the Apply left at ${rel})`, toLabel: `actual (${rel} on disk now)` },
    ),
  };
}

/**
 * Check every destination path an undo is about to write.
 *
 * @param {{run: Function, rootPath: string, commit: string, paths: string[],
 *   expected?: Map<string, {exists: boolean}>|null, fs?: object}} opts
 * @returns {Promise<{ok: string[], refused: object[]}>}
 */
export async function checkNoClobber({ run, rootPath, commit, paths = [], expected = null, fs = fsp } = {}) {
  const ok = [];
  const refused = [];

  for (const rel of paths) {
    const abs = path.join(rootPath, rel);

    // What the Apply left here.
    const declared = expected && expected.get ? expected.get(rel) : null;
    const expectedSize = await revSize(run, commit, rel);
    const expectedExists = declared ? Boolean(declared.exists) : expectedSize !== null;

    // What is here now.
    let actualExists = true;
    let actualSize = null;
    try {
      const st = await fs.stat(abs);
      actualSize = st.size;
    } catch (err) {
      if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) actualExists = false;
      else {
        refused.push({
          path: rel,
          reason: CLOBBER_REASON.UNREADABLE,
          message: `NO-CLOBBER: '${rel}' could not be read (${err.message}), so the undo cannot prove it is safe to write and refuses this path`,
          manualCommand: manualRestoreCommand(rootPath, commit, rel, expectedExists),
        });
        continue;
      }
    }

    if (!expectedExists && !actualExists) { ok.push(rel); continue; }

    if (!expectedExists && actualExists) {
      // The classic case: the Apply removed q, the user made a new q.
      const actual = await readOrNull(fs, abs);
      refused.push({
        path: rel,
        reason: CLOBBER_REASON.RECREATED,
        message: `NO-CLOBBER: the Apply removed '${rel}', but a file now exists there — restoring would overwrite content created after the Apply, which this tool never does`,
        expected: { exists: false },
        actual: { exists: true, size: actualSize },
        ...renderRefusalDiff(Buffer.alloc(0), actual, rel),
        manualCommand: manualRestoreCommand(rootPath, commit, rel, expectedExists),
      });
      continue;
    }

    if (expectedExists && !actualExists) {
      // Deleted after the Apply. Recreating it would resurrect a file the user
      // deliberately removed, so it is refused rather than silently restored.
      refused.push({
        path: rel,
        reason: CLOBBER_REASON.DELETED,
        message: `NO-CLOBBER: '${rel}' was deleted after the Apply — the undo will not resurrect a path the user removed; approve it manually if that is what you want`,
        expected: { exists: true, size: expectedSize },
        actual: { exists: false },
        manualCommand: manualRestoreCommand(rootPath, commit, rel, expectedExists),
      });
      continue;
    }

    if (actualSize !== expectedSize) {
      const [expectedBytes, actualBytes] = [await revBytes(run, commit, rel), await readOrNull(fs, abs)];
      refused.push(editedRefusal(rootPath, commit, rel, expectedBytes, actualBytes, expectedSize, actualSize));
      continue;
    }

    const expectedBytes = await revBytes(run, commit, rel);
    const actualBytes = await readOrNull(fs, abs);
    if (!expectedBytes || !actualBytes || !expectedBytes.equals(actualBytes)) {
      refused.push(editedRefusal(rootPath, commit, rel, expectedBytes, actualBytes, expectedSize, actualSize));
      continue;
    }

    ok.push(rel);
  }

  return { ok, refused };
}

/**
 * The same rule, for restorers that have NO COMMIT to compare against.
 *
 * Wave 4's Trash restore and Bootstrap undo both write to paths whose expected
 * post-Apply state was journaled as plain filesystem facts — "this path should
 * be absent (we moved it to the Trash)", "this path should hold exactly these
 * bytes (we created it)". Rather than each inventing its own idea of what
 * counts as safe, they share this predicate, so the no-clobber invariant means
 * the same thing on every undo path in the system.
 *
 * @param {{rootPath: string, path: string, expected: {exists: boolean, hash?: string|null, size?: number|null}, fs?: object}} opts
 * @returns {Promise<{ok: boolean, reason?: string, actual: object, expected: object, message?: string}>}
 */
export async function checkPathAgainstExpectation({ rootPath, path: rel, expected = {}, fs = fsp } = {}) {
  const abs = path.join(rootPath, rel);
  const expectExists = Boolean(expected.exists);

  let st = null;
  try {
    st = await fs.stat(abs);
  } catch (err) {
    if (!err || (err.code !== 'ENOENT' && err.code !== 'ENOTDIR')) {
      return {
        ok: false,
        reason: CLOBBER_REASON.UNREADABLE,
        expected,
        actual: { readable: false, error: err && err.message },
        message: `NO-CLOBBER: '${rel}' could not be read (${err && err.message}), so the restore cannot prove it is safe to write and refuses this path`,
      };
    }
  }

  const actualExists = st !== null;

  if (!expectExists && !actualExists) return { ok: true, expected, actual: { exists: false } };

  if (!expectExists && actualExists) {
    return {
      ok: false,
      reason: CLOBBER_REASON.RECREATED,
      expected,
      actual: { exists: true, size: st.size },
      message: `NO-CLOBBER: this operation removed '${rel}', but a file exists there again — restoring would overwrite content created afterwards, which this tool never does`,
    };
  }

  if (expectExists && !actualExists) {
    return {
      ok: false,
      reason: CLOBBER_REASON.DELETED,
      expected,
      actual: { exists: false },
      message: `NO-CLOBBER: '${rel}' was deleted after the operation — the undo will not resurrect a path the user removed; do it by hand if that is what you want`,
    };
  }

  if (expected.hash) {
    const actualHash = await hashOrNull(fs, abs);
    if (actualHash !== expected.hash) {
      return {
        ok: false,
        reason: CLOBBER_REASON.EDITED,
        expected,
        actual: { exists: true, size: st.size, hash: actualHash },
        message: `NO-CLOBBER: '${rel}' has been edited since the operation — the undo refuses this path rather than overwrite work no commit holds`,
      };
    }
  }

  return { ok: true, expected, actual: { exists: true, size: st.size } };
}

async function hashOrNull(fs, abs) {
  try { return await hashFile(abs, { fs }); } catch { return null; }
}

function editedRefusal(rootPath, commit, rel, expectedBytes, actualBytes, expectedSize, actualSize) {
  return {
    path: rel,
    reason: CLOBBER_REASON.EDITED,
    message: `NO-CLOBBER: '${rel}' has been edited since the Apply — the undo refuses this path rather than overwrite work that is not in any commit`,
    expected: { exists: true, size: expectedSize },
    actual: { exists: true, size: actualSize },
    ...renderRefusalDiff(expectedBytes, actualBytes, rel),
    manualCommand: manualRestoreCommand(rootPath, commit, rel, true),
  };
}

async function readOrNull(fs, abs) {
  try { return await fs.readFile(abs); } catch { return null; }
}

/**
 * The command the panel offers for copying. It is EXPLICITLY marked destructive:
 * the tool will not run it, and the human running it in their own terminal is a
 * different act from the tool doing it silently.
 */
export function manualRestoreCommand(rootPath, commit, rel, expectedExists) {
  return {
    command: `git -C ${quote(rootPath)} checkout ${commit}^ -- ${quote(rel)}`,
    destructive: true,
    note: expectedExists
      ? 'run this yourself ONLY if you are willing to lose the current content of this path'
      : 'this restores the pre-Apply version of a path you have since recreated — it overwrites your new file',
  };
}

function quote(s) {
  return /[\s"']/.test(s) ? `"${String(s).replace(/"/g, '\\"')}"` : String(s);
}

/**
 * Journal-derived expectations, when a journal is available. Falls back to
 * `null` (commit-derived) so callers never branch on its presence.
 */
export function expectationsFromJournal(journal) {
  if (!journal || !journal.records) return null;
  const map = new Map();
  for (const r of journal.records) {
    if (r.type !== 'op-result' || !r.expectedAfter) continue;
    map.set(r.expectedAfter.path || r.path, r.expectedAfter);
  }
  return map.size ? map : null;
}

export default { checkNoClobber, checkPathAgainstExpectation, expectationsFromJournal, manualRestoreCommand, CLOBBER_REASON };

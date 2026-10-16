// engine/apply/trash.mjs — Wave 4: the reversible Trash (Amendment A).
//
// git holds the content it holds. For everything else — an UNTRACKED file in a
// repo, ANY file in a folder with no repo — there is no `git revert` to undo a
// removal with, and the whole tool rests on never making a change it cannot take
// back. So a removal of non-git-held content is not a delete. It is a MOVE into
// a per-project Trash, journaled, and its undo is the move back:
//
//   .tidy-idy/trash/<run-id>/
//     journal.jsonl          every move and every restore, flushed BEFORE the act
//     manifest.json          the human/panel summary, rewritten as state changes
//     files/<original/rel>   the file itself, under its original relative path
//
// Storing each file under its ORIGINAL relative path inside `files/` is what
// makes two junk files named `notes.txt` in different directories survivable,
// and makes a restore's destination readable by eye from the trash tree alone.
//
// WHAT "ATOMIC MOVE-SET" MEANS HERE, precisely — because a filesystem gives no
// multi-file transaction and claiming one would be a lie:
//
//   1. PRE-FLIGHT BEFORE ANY MUTATION. Every source is proven present and every
//      trash slot proven free before the first rename. The failures that are
//      knowable in advance (a vanished file, an occupied slot, an unwritable
//      trash dir) therefore abort the set with NOTHING moved — which is where
//      Apply calls it, ahead of the commit, so a bad plan costs nothing.
//   2. JOURNAL-BEFORE-ACT, FLUSHED. Each move appends `started` (and fsyncs)
//      before the rename and `done` after it. A crash leaves a record of an act
//      that may or may not have happened — never an act with no record.
//   3. IDEMPOTENT RESUME. A retry re-reads the journal, reconciles each pending
//      record against the filesystem, and completes only what is genuinely
//      outstanding. No file is moved twice and none is skipped, so the set
//      always converges to fully-applied.
//
// Restore has the same three properties, plus the system-wide NO-CLOBBER rule:
// if something now occupies a file's original path, the restore REFUSES that
// path with an explanation and a copyable command, and the other paths still go
// back. An undo that overwrites whatever the user put there afterwards is the
// same data loss the tool exists to prevent, wearing a helpful mask.
//
// Emptying the Trash is the ONE destructive operation in this file, it is never
// automatic, and it is the only place `rm` appears.

import fsp from 'node:fs/promises';
import path from 'node:path';

import { hashFile } from '../snapshot.mjs';
import { toPosixRel } from '../glob.mjs';
import { openJournal, readJournal, journalDirFor } from './journal.mjs';
import { checkPathAgainstExpectation } from './no-clobber.mjs';

export const TRASH_KIND = 'trash';

/** Default retention. Nothing is ever purged without an explicit call. */
export const DEFAULT_TTL_DAYS = 30;
export const DEFAULT_TTL_MS = DEFAULT_TTL_DAYS * 24 * 60 * 60 * 1000;

export const TRASH_REFUSAL = Object.freeze({
  SOURCE_MISSING: 'SOURCE_MISSING',
  SLOT_OCCUPIED: 'TRASH_SLOT_OCCUPIED',
  DEST_OCCUPIED: 'ORIGINAL_PATH_REOCCUPIED',
  OUTSIDE_ROOT: 'PATH_ESCAPES_ROOT',
  NOT_IN_TRASH: 'NOT_IN_TRASH',
  IO: 'IO_ERROR',
});

export const TRASH_STATUS = Object.freeze({
  OK: 'ok',
  PARTIAL: 'partial',
  REFUSED: 'refused',
  NO_OP: 'no-op',
});

/** `<reportDir>/trash/<run-id>/` — one directory per run. */
export function trashDirFor(reportDir, runId) {
  return journalDirFor(reportDir, runId, TRASH_KIND);
}

/** Where the bytes live inside a run's trash directory. */
export function trashFilesDirFor(reportDir, runId) {
  return path.join(trashDirFor(reportDir, runId), 'files');
}

/**
 * Make the tool's own state directory invisible to git, WITHOUT touching the
 * project's .gitignore.
 *
 * `.tidy-idy/.gitignore` containing `*` ignores the directory from the inside.
 * That matters twice over: the trash must not show up as a mountain of
 * untracked files in the user's next `git status`, and the consent-scope
 * invariant forbids an Apply from writing an ignore rule no tile declared — a
 * file written INSIDE reportDir (the tripwire's sole exception) is the tool's
 * own state, not a change to the user's repository configuration.
 */
export async function ensureReportDirIgnored({ reportDir, fs = fsp } = {}) {
  const file = path.join(reportDir, '.gitignore');
  try {
    await fs.stat(file);
    return { written: false, path: file };
  } catch { /* absent — write it */ }
  await fs.mkdir(reportDir, { recursive: true });
  await fs.writeFile(file,
    '# tidy-idy\'s own run state, including the reversible Trash.\n'
    + '# Self-ignoring so the tool never has to edit YOUR .gitignore to stay out of git.\n'
    + '*\n', 'utf8');
  return { written: true, path: file };
}

function resolveInside(root, rel) {
  const p = toPosixRel(rel);
  const abs = path.resolve(root, p);
  const inside = abs === path.resolve(root)
    ? false
    : abs.startsWith(path.resolve(root) + path.sep);
  return { rel: p, abs, inside };
}

async function statOrNull(fs, abs) {
  try { return await fs.stat(abs); } catch { return null; }
}

async function hashOrNull(fs, abs) {
  try { return await hashFile(abs, { fs }); } catch { return null; }
}

/** rename, falling back to copy+unlink across devices. */
async function moveFile(fs, from, to) {
  await fs.mkdir(path.dirname(to), { recursive: true });
  try {
    await fs.rename(from, to);
    return 'rename';
  } catch (err) {
    if (!err || (err.code !== 'EXDEV' && err.code !== 'EPERM' && err.code !== 'EACCES')) throw err;
    await fs.copyFile(from, to);
    await fs.rm(from, { force: true });
    return 'copy+unlink';
  }
}

/**
 * Read a run's trash ledger back into per-path state.
 *
 * The ledger — not the directory listing — is the authority: a file sitting in
 * `files/` with no `done` record is an interrupted move whose reconciliation is
 * decided against the filesystem below, and a `done` record whose file is gone
 * is a restore that already happened.
 */
export async function readTrashLedger({ reportDir, runId, fs = fsp } = {}) {
  const journal = await readJournal({ reportDir, runId, kind: TRASH_KIND, fs });
  const entries = new Map();

  for (const r of (journal ? journal.records : [])) {
    if (r.type !== 'move' && r.type !== 'restore') continue;
    const rel = toPosixRel(r.path);
    const prior = entries.get(rel) || { path: rel, trashRel: r.trashRel || null, moveState: null, restoreState: null };
    if (r.trashRel) prior.trashRel = r.trashRel;
    if (r.hash) prior.hash = r.hash;
    if (r.size !== undefined && r.size !== null) prior.size = r.size;
    if (r.type === 'move') prior.moveState = r.state;
    else prior.restoreState = r.state;
    entries.set(rel, prior);
  }

  return { journal, entries };
}

/**
 * Everything knowable BEFORE the first rename.
 *
 * Apply calls this while the plan is still compiling, so a trash removal that
 * cannot succeed aborts the whole Apply with nothing moved and nothing
 * committed — the same all-or-nothing the temp index gives the git half.
 *
 * @param {{rootPath: string, reportDir: string, runId: string, ops: object[], fs?: object}} opts
 * @returns {Promise<{ok: boolean, problems: object[], planned: object[]}>}
 */
export async function preflightTrashMoveSet({ rootPath, reportDir, runId, ops = [], fs = fsp } = {}) {
  const root = path.resolve(rootPath);
  const filesDir = trashFilesDirFor(reportDir, runId);
  const { entries } = await readTrashLedger({ reportDir, runId, fs });

  const problems = [];
  const planned = [];

  for (const op of ops) {
    const { rel, abs, inside } = resolveInside(root, op.path);
    const prior = entries.get(rel) || null;

    if (!inside) {
      problems.push({
        path: rel,
        code: TRASH_REFUSAL.OUTSIDE_ROOT,
        message: `'${rel}' resolves outside the run root — the Trash only ever accepts content from inside the project it belongs to`,
      });
      continue;
    }

    // Already trashed by an earlier, interrupted attempt at THIS run: not a
    // problem, an outstanding item that resume will reconcile.
    if (prior && prior.moveState === 'done' && prior.restoreState !== 'done') {
      planned.push({ ...op, rel, abs, trashRel: prior.trashRel, resumed: true });
      continue;
    }

    const src = await statOrNull(fs, abs);
    if (!src) {
      problems.push({
        path: rel,
        code: TRASH_REFUSAL.SOURCE_MISSING,
        message: `'${rel}' is no longer on disk — it was removed or renamed after the scan, so there is nothing to move to the Trash`,
      });
      continue;
    }

    const trashRel = rel;
    const dest = path.join(filesDir, trashRel);
    const occupied = await statOrNull(fs, dest);
    if (occupied && !(prior && prior.moveState)) {
      problems.push({
        path: rel,
        code: TRASH_REFUSAL.SLOT_OCCUPIED,
        message: `the Trash slot for '${rel}' in run ${runId} is already occupied — refusing rather than overwriting something already in the Trash`,
        trashPath: dest,
      });
      continue;
    }

    planned.push({ ...op, rel, abs, trashRel, dest, size: src.size, resumed: false });
  }

  return { ok: problems.length === 0, problems, planned };
}

/**
 * Execute the move-set. Journaled, resumable, and safe to call again after a
 * crash: the second call completes exactly what the first did not.
 *
 * @param {{rootPath: string, reportDir: string, runId: string, ops: object[],
 *   fs?: object, now?: Function, applyJournal?: object|null}} opts
 */
export async function executeTrashMoveSet({
  rootPath, reportDir, runId, ops = [], fs = fsp, now = () => new Date(), applyJournal = null,
} = {}) {
  const root = path.resolve(rootPath);
  const dir = trashDirFor(reportDir, runId);
  const filesDir = trashFilesDirFor(reportDir, runId);

  if (!ops.length) {
    return { status: TRASH_STATUS.NO_OP, moved: [], failed: [], dir, files: filesDir, resumed: 0 };
  }

  await fs.mkdir(filesDir, { recursive: true });
  await ensureReportDirIgnored({ reportDir, fs });

  const { entries } = await readTrashLedger({ reportDir, runId, fs });
  const ledger = await openJournal({ reportDir, runId, kind: TRASH_KIND, fs, now });

  const moved = [];
  const failed = [];
  let resumed = 0;

  // Deterministic order, so a resumed run walks the set exactly as the first
  // attempt did and a journal diffs cleanly between attempts.
  const ordered = [...ops].sort((a, b) => toPosixRel(a.path).localeCompare(toPosixRel(b.path)));

  for (const op of ordered) {
    const { rel, abs, inside } = resolveInside(root, op.path);
    const trashRel = rel;
    const dest = path.join(filesDir, trashRel);
    const prior = entries.get(rel) || null;

    if (!inside) {
      failed.push({ path: rel, code: TRASH_REFUSAL.OUTSIDE_ROOT, message: `'${rel}' resolves outside the run root` });
      await ledger.append('move', { path: rel, state: 'failed', code: TRASH_REFUSAL.OUTSIDE_ROOT });
      continue;
    }

    // ---- resume reconciliation ------------------------------------------
    if (prior && prior.moveState === 'done' && prior.restoreState !== 'done') {
      moved.push({ path: rel, trashRel: prior.trashRel || trashRel, trashPath: dest, hash: prior.hash || null, size: prior.size ?? null, alreadyDone: true });
      resumed++;
      continue;
    }

    const srcStat = await statOrNull(fs, abs);
    const destStat = await statOrNull(fs, dest);

    if (prior && prior.moveState === 'started' && !srcStat && destStat) {
      // The rename completed; the crash landed between the act and its record.
      const hash = prior.hash || await hashOrNull(fs, dest);
      await ledger.append('move', { path: rel, trashRel, state: 'done', hash, size: destStat.size, reconciled: 'the rename had completed before the interruption — recording it rather than repeating it' });
      moved.push({ path: rel, trashRel, trashPath: dest, hash, size: destStat.size, resumed: true });
      resumed++;
      continue;
    }

    if (!srcStat) {
      failed.push({
        path: rel,
        code: TRASH_REFUSAL.SOURCE_MISSING,
        message: `'${rel}' is not on disk — nothing was moved for this path`,
      });
      await ledger.append('move', { path: rel, state: 'failed', code: TRASH_REFUSAL.SOURCE_MISSING });
      continue;
    }

    if (destStat && !(prior && prior.moveState === 'started')) {
      failed.push({
        path: rel,
        code: TRASH_REFUSAL.SLOT_OCCUPIED,
        message: `the Trash slot for '${rel}' is already occupied — refusing to overwrite content already in the Trash`,
        trashPath: dest,
      });
      await ledger.append('move', { path: rel, state: 'failed', code: TRASH_REFUSAL.SLOT_OCCUPIED });
      continue;
    }

    // ---- journal-before-act ----------------------------------------------
    const hash = await hashOrNull(fs, abs);
    await ledger.append('move', {
      path: rel, trashRel, state: 'started', hash, size: srcStat.size,
      note: 'the file is MOVED, never deleted — undo is restore-from-Trash',
    });

    try {
      const method = await moveFile(fs, abs, dest);
      await ledger.append('move', { path: rel, trashRel, state: 'done', hash, size: srcStat.size, method });
      moved.push({ path: rel, trashRel, trashPath: dest, hash, size: srcStat.size, method });
    } catch (err) {
      await ledger.append('move', { path: rel, trashRel, state: 'failed', code: TRASH_REFUSAL.IO, error: err && err.message });
      failed.push({
        path: rel,
        code: TRASH_REFUSAL.IO,
        message: `'${rel}' could not be moved into the Trash (${err && err.message}) — it is still exactly where it was`,
      });
    }
  }

  const status = failed.length === 0
    ? TRASH_STATUS.OK
    : (moved.length ? TRASH_STATUS.PARTIAL : TRASH_STATUS.REFUSED);

  const manifest = await writeManifest({ reportDir, runId, fs, now });

  if (applyJournal) {
    await applyJournal.append('trash-move-set', {
      status, dir, moved: moved.map((m) => m.path), failed, resumed,
    });
  }

  return {
    status,
    moved,
    failed,
    resumed,
    dir,
    files: filesDir,
    manifest: manifest.path,
    journal: { dir: ledger.dir, file: ledger.file },
    reversible: true,
    undo: {
      how: 'restore-from-Trash — a pure journaled move-back of each file to its original path',
      note: 'nothing was deleted; every moved file is byte-identical inside the Trash',
    },
    message: status === TRASH_STATUS.OK
      ? `moved ${moved.length} file(s) into the reversible Trash at ${dir}${resumed ? ` (${resumed} already moved by an interrupted earlier attempt)` : ''}`
      : `TRASH MOVE-SET INCOMPLETE: ${moved.length} file(s) moved, ${failed.length} REFUSED or failed (${failed.map((f) => `${f.path}: ${f.code}`).join('; ')}) — every per-path outcome is recorded in ${path.join(dir, 'journal.jsonl')}, and nothing that failed was touched`,
  };
}

/**
 * Restore a run's trashed files to their original paths.
 *
 * @param {{rootPath: string, reportDir: string, runId: string, paths?: string[]|null,
 *   fs?: object, now?: Function}} opts
 */
export async function restoreFromTrash({
  rootPath, reportDir, runId, paths = null, fs = fsp, now = () => new Date(),
} = {}) {
  const root = path.resolve(rootPath);
  const dir = trashDirFor(reportDir, runId);
  const filesDir = trashFilesDirFor(reportDir, runId);

  const { journal: existing, entries } = await readTrashLedger({ reportDir, runId, fs });
  if (!existing) {
    return {
      status: TRASH_STATUS.REFUSED,
      code: TRASH_REFUSAL.NOT_IN_TRASH,
      restored: [],
      refused: [],
      message: `there is no Trash ledger for run ${runId} at ${dir} — nothing to restore`,
    };
  }

  const wanted = paths ? new Set(paths.map(toPosixRel)) : null;
  const candidates = [...entries.values()]
    .filter((e) => e.moveState === 'done')
    .filter((e) => !wanted || wanted.has(e.path))
    .sort((a, b) => a.path.localeCompare(b.path));

  const ledger = await openJournal({ reportDir, runId, kind: TRASH_KIND, fs, now });

  const restored = [];
  const refused = [];
  let resumed = 0;

  for (const entry of candidates) {
    const rel = entry.path;
    const abs = path.join(root, rel);
    const src = path.join(filesDir, entry.trashRel || rel);

    const inTrash = await statOrNull(fs, src);
    const atOriginal = await statOrNull(fs, abs);

    // ---- resume reconciliation ------------------------------------------
    if (!inTrash && atOriginal) {
      // The move-back completed; only its `done` record is missing.
      if (entry.restoreState !== 'done') {
        await ledger.append('restore', { path: rel, trashRel: entry.trashRel || rel, state: 'done', hash: entry.hash || null, reconciled: 'the file was already back at its original path — recording the restore rather than repeating it' });
        resumed++;
      }
      restored.push({ path: rel, alreadyRestored: true, hash: entry.hash || null });
      continue;
    }

    if (!inTrash && !atOriginal) {
      refused.push({
        path: rel,
        code: TRASH_REFUSAL.NOT_IN_TRASH,
        message: `'${rel}' is neither in the Trash nor at its original path — the Trash cannot restore what it does not hold, and it will not invent content`,
      });
      await ledger.append('restore', { path: rel, state: 'failed', code: TRASH_REFUSAL.NOT_IN_TRASH });
      continue;
    }

    // ---- NO-CLOBBER ------------------------------------------------------
    // The removal left this path ABSENT; that is the expectation the restore is
    // checked against, through the same system-wide predicate the git undo and
    // Bootstrap undo use. Anything else there means the user recreated it, so
    // THIS path is refused and the others still go back — the trashed copy stays
    // safe exactly where it is.
    const guard = await checkPathAgainstExpectation({ rootPath: root, path: rel, expected: { exists: false }, fs });
    if (!guard.ok) {
      refused.push({
        path: rel,
        code: TRASH_REFUSAL.DEST_OCCUPIED,
        reason: guard.reason,
        message: `${guard.message}. The trashed copy is untouched and still in the Trash.`,
        expected: guard.expected,
        actual: guard.actual,
        trashPath: src,
        manualCommand: manualMoveCommand(src, abs),
      });
      await ledger.append('restore', { path: rel, state: 'refused', code: TRASH_REFUSAL.DEST_OCCUPIED, reason: guard.reason, actual: guard.actual });
      continue;
    }

    await ledger.append('restore', { path: rel, trashRel: entry.trashRel || rel, state: 'started', hash: entry.hash || null });
    try {
      const method = await moveFile(fs, src, abs);
      const afterHash = await hashOrNull(fs, abs);
      await ledger.append('restore', { path: rel, trashRel: entry.trashRel || rel, state: 'done', hash: afterHash, method });
      restored.push({ path: rel, hash: afterHash, bitIdentical: entry.hash ? afterHash === entry.hash : null, method });
    } catch (err) {
      await ledger.append('restore', { path: rel, state: 'failed', code: TRASH_REFUSAL.IO, error: err && err.message });
      refused.push({
        path: rel,
        code: TRASH_REFUSAL.IO,
        message: `'${rel}' could not be moved back (${err && err.message}) — it is still in the Trash and can be restored by hand`,
        trashPath: src,
        manualCommand: manualMoveCommand(src, abs),
      });
    }
  }

  await writeManifest({ reportDir, runId, fs, now });

  const status = refused.length === 0
    ? (restored.length ? TRASH_STATUS.OK : TRASH_STATUS.NO_OP)
    : (restored.length ? TRASH_STATUS.PARTIAL : TRASH_STATUS.REFUSED);

  return {
    status,
    restored,
    refused,
    resumed,
    dir,
    journal: { dir: ledger.dir, file: ledger.file },
    message: refused.length === 0
      ? `restored ${restored.length} file(s) from the Trash to their original paths${resumed ? ` (${resumed} were already back after an interrupted earlier restore)` : ''}`
      : `restored ${restored.length} file(s); ${refused.length} REFUSED and left in the Trash (${refused.map((r) => `${r.path}: ${r.code}`).join('; ')}) — nothing at those paths was overwritten`,
  };
}

/** The copyable command for a refusal. Explicitly marked destructive. */
export function manualMoveCommand(from, to) {
  return {
    command: process.platform === 'win32'
      ? `Move-Item -Force ${quote(from)} ${quote(to)}`
      : `mv -f ${quote(from)} ${quote(to)}`,
    destructive: true,
    note: 'run this yourself ONLY if you are willing to lose whatever currently sits at the destination',
  };
}

function quote(s) {
  return /[\s"']/.test(String(s)) ? `"${String(s).replace(/"/g, '\\"')}"` : String(s);
}

/** The panel-readable summary of one run's Trash, derived from its ledger. */
export async function writeManifest({ reportDir, runId, fs = fsp, now = () => new Date() } = {}) {
  const dir = trashDirFor(reportDir, runId);
  const { entries } = await readTrashLedger({ reportDir, runId, fs });
  const items = [...entries.values()]
    .filter((e) => e.moveState === 'done')
    .map((e) => ({
      path: e.path,
      trashRel: e.trashRel || e.path,
      hash: e.hash || null,
      size: e.size ?? null,
      restored: e.restoreState === 'done',
    }))
    .sort((a, b) => a.path.localeCompare(b.path));

  const manifest = {
    version: 1,
    runId,
    updatedAt: now().toISOString(),
    items,
    held: items.filter((i) => !i.restored).length,
    restored: items.filter((i) => i.restored).length,
    note: 'these files were MOVED here, not deleted; restore-from-Trash puts each one back at `path` bit-identically',
  };
  const file = path.join(dir, 'manifest.json');
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(file, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  return { path: file, manifest };
}

/**
 * Every run's Trash under a project, with TTL state computed but NOT acted on.
 * Expiry is a label here; only emptyTrash() deletes, and only when called.
 */
export async function listTrash({ reportDir, fs = fsp, now = () => new Date(), ttlMs = DEFAULT_TTL_MS } = {}) {
  const base = path.join(reportDir, TRASH_KIND);
  let runIds;
  try {
    runIds = await fs.readdir(base);
  } catch {
    return { runs: [], base };
  }

  const runs = [];
  for (const runId of runIds.sort()) {
    const { journal, entries } = await readTrashLedger({ reportDir, runId, fs });
    if (!journal) continue;
    const items = [...entries.values()].filter((e) => e.moveState === 'done');
    const held = items.filter((e) => e.restoreState !== 'done');
    const firstAt = journal.records.length ? journal.records[0].at : null;
    const ageMs = firstAt ? now().getTime() - new Date(firstAt).getTime() : 0;
    runs.push({
      runId,
      dir: trashDirFor(reportDir, runId),
      movedAt: firstAt,
      ageMs,
      items: items.length,
      held: held.length,
      restored: items.length - held.length,
      bytes: held.reduce((n, e) => n + (e.size || 0), 0),
      /** Past its TTL and therefore OFFERED for emptying — never auto-purged. */
      expired: ageMs > ttlMs,
      /** An emptied/fully-restored run holds nothing; keeping it is free. */
      empty: held.length === 0,
    });
  }
  return { runs, base, ttlMs };
}

/**
 * Permanently delete trashed content. THE ONLY DESTRUCTIVE OPERATION IN THIS
 * FILE, and it never runs on its own: a caller must ask, either for one run or
 * for everything past the TTL.
 *
 * @param {{reportDir: string, runId?: string|null, expiredOnly?: boolean,
 *   ttlMs?: number, fs?: object, now?: Function}} opts
 */
export async function emptyTrash({
  reportDir, runId = null, expiredOnly = false, ttlMs = DEFAULT_TTL_MS, fs = fsp, now = () => new Date(),
} = {}) {
  const { runs } = await listTrash({ reportDir, fs, now, ttlMs });
  const targets = runs
    .filter((r) => (runId ? r.runId === String(runId) : true))
    .filter((r) => (expiredOnly ? r.expired : true));

  const purged = [];
  for (const r of targets) {
    await fs.rm(r.dir, { recursive: true, force: true });
    purged.push({ runId: r.runId, items: r.held, bytes: r.bytes, dir: r.dir });
  }

  return {
    purged,
    kept: runs.filter((r) => !targets.includes(r)).map((r) => r.runId),
    ttlMs,
    message: purged.length
      ? `permanently deleted ${purged.reduce((n, p) => n + p.items, 0)} file(s) from ${purged.length} Trash run(s) — this is the one step that is NOT reversible, and it happened because it was asked for`
      : 'nothing was emptied',
  };
}

export default {
  trashDirFor, trashFilesDirFor, ensureReportDirIgnored, preflightTrashMoveSet,
  executeTrashMoveSet, restoreFromTrash, readTrashLedger, listTrash, emptyTrash,
  writeManifest, manualMoveCommand, TRASH_REFUSAL, TRASH_STATUS, TRASH_KIND, DEFAULT_TTL_MS,
};

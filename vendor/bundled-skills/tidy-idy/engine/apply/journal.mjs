// engine/apply/journal.mjs — Wave 3: the forensic run journal.
//
// Every Apply and every Undo writes an append-only JSONL record of the compiled
// plan, each operation's result, and the resulting commit sha. It exists for two
// different readers:
//
//   THE HUMAN, afterwards: "what did this tool do to my repository at 02:14?" is
//     a question the answer to which must not be "read the diff and guess".
//
//   THE RECOVERY PATH, next time: working-tree realization is journaled so an
//     interruption can be retried from the record instead of re-derived. Wave 4's
//     Trash and Wave 8's mixed reorg apply use this same append-fsync-before-act
//     discipline, which is why the flush is not optional.
//
// The journal lives under reportDir — the ONE location the zero-write tripwire
// exempts — so writing it can never be mistaken for the engine mutating a
// project. Apply's other writes are the commit (in the object store) and the
// realization (in the working tree), and both are named on an approved tile.

import fsp from 'node:fs/promises';
import path from 'node:path';

export const JOURNAL_FILE = 'journal.jsonl';

/** `<reportDir>/apply/<runId>/` — one directory per run, per kind. */
export function journalDirFor(reportDir, runId, kind = 'apply') {
  return path.join(reportDir, kind, String(runId));
}

/**
 * Open (creating) a run journal.
 *
 * @param {{reportDir: string, runId: string, kind?: string, fs?: object, now?: Function}} opts
 */
export async function openJournal({ reportDir, runId, kind = 'apply', fs = fsp, now = () => new Date() } = {}) {
  const dir = journalDirFor(reportDir, runId, kind);
  await fs.mkdir(dir, { recursive: true });
  const file = path.join(dir, JOURNAL_FILE);
  const records = [];
  let seq = 0;

  return {
    dir,
    file,
    records,

    /**
     * Append one record and FLUSH IT BEFORE THE ACT IT DESCRIBES RETURNS.
     * A journal written lazily records intentions that may never have happened
     * and misses acts that did — which is worse than no journal at all.
     */
    async append(type, data = {}) {
      const record = { seq: seq++, at: now().toISOString(), runId, kind, type, ...data };
      records.push(record);
      let handle = null;
      try {
        handle = await fs.open(file, 'a');
        await handle.writeFile(`${JSON.stringify(record)}\n`, 'utf8');
        // Best-effort durability: a filesystem that cannot fsync (or an injected
        // test double that has no sync) must not take the Apply down with it.
        if (typeof handle.sync === 'function') await handle.sync().catch(() => {});
      } finally {
        if (handle) await handle.close().catch(() => {});
      }
      return record;
    },

    /** The human-readable summary a panel or a later reader opens first. */
    async writeSummary(summary) {
      await fs.writeFile(path.join(dir, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
    },
  };
}

/** Read a journal back — used by Undo to recover the exact per-op expectations. */
export async function readJournal({ reportDir, runId, kind = 'apply', fs = fsp } = {}) {
  const file = path.join(journalDirFor(reportDir, runId, kind), JOURNAL_FILE);
  let text;
  try {
    text = String(await fs.readFile(file, 'utf8'));
  } catch {
    return null;
  }
  const records = [];
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try { records.push(JSON.parse(line)); } catch { /* a torn final line is expected after a crash */ }
  }
  return { file, records };
}

/**
 * Find the journal for a given commit sha without knowing its run id — the
 * situation Undo is in when it is handed only a sha.
 */
export async function findJournalForCommit({ reportDir, commit, kind = 'apply', fs = fsp } = {}) {
  let runIds;
  try {
    runIds = await fs.readdir(path.join(reportDir, kind));
  } catch {
    return null;
  }
  for (const runId of runIds) {
    const j = await readJournal({ reportDir, runId, kind, fs });
    if (!j) continue;
    if (j.records.some((r) => r.commit === commit)) return { runId, ...j };
  }
  return null;
}

export default { openJournal, readJournal, findJournalForCommit, journalDirFor, JOURNAL_FILE };

// engine/apply/temp-index.mjs — Wave 3: the compiled plan's workspace.
//
// The whole plan is compiled into a TEMPORARY index (GIT_INDEX_FILE) seeded from
// HEAD's tree. Two invariants come free from that choice and from nothing else:
//
//   THE USER'S INDEX IS NEVER TOUCHED. Someone with a half-staged commit in
//     progress can run Apply and lose nothing; git's own `add`/`rm` would have
//     written straight into it.
//
//   ABORT-ALL IS TRIVIAL. "Discard the plan" is `unlink(tempIndexFile)`. There
//     is no partial state to unwind, because until `commit-tree` runs, nothing
//     outside a scratch file in the OS temp directory has changed at all.
//
// The temp index lives OUTSIDE the project root (os.tmpdir()), not under
// reportDir: a git index file sitting inside the tree being analysed is exactly
// the kind of artefact a hygiene tool should not be creating, and the tripwire
// would be right to be suspicious of it.

import crypto from 'node:crypto';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { lit } from './git-plumbing.mjs';

/** Parse one `git ls-files -s -z` record: `<mode> <sha> <stage>\t<path>`. */
function parseStageLine(line) {
  const tab = line.indexOf('\t');
  if (tab === -1) return null;
  const meta = line.slice(0, tab).split(' ');
  return { mode: meta[0], sha: meta[1], stage: Number(meta[2]), path: line.slice(tab + 1) };
}

/**
 * Create a temp index seeded from `head`, hand it to `fn`, and remove it on
 * EVERY exit path — including the abort-all throw.
 *
 * @param {{run: Function, head: string, fs?: object, tmpDir?: string}} opts
 * @param {(idx: object) => Promise<any>} fn
 */
export async function withTempIndex({ run, head, fs = fsp, tmpDir = os.tmpdir() }, fn) {
  const indexFile = path.join(tmpDir, `tidy-idy-index-${crypto.randomBytes(8).toString('hex')}`);
  const idx = makeTempIndex({ run, indexFile });
  try {
    await idx.seed(head);
    return await fn(idx);
  } finally {
    await fs.rm(indexFile, { force: true }).catch(() => {});
    await fs.rm(`${indexFile}.lock`, { force: true }).catch(() => {});
  }
}

export function makeTempIndex({ run, indexFile }) {
  const g = (args, opts = {}) => run(args, { ...opts, indexFile });

  return {
    indexFile,

    /** Seed from a tree-ish. This is what makes the plan a delta on HEAD. */
    async seed(head) {
      await g(['read-tree', head]);
    },

    /** The single index entry for a path, or null. */
    async entry(rel) {
      const r = await g(['ls-files', '-s', '-z', '--', lit(rel)]);
      const first = r.text.split('\0').find((s) => s.length > 0);
      return first ? parseStageLine(first) : null;
    },

    /** Every entry under a directory prefix (a reorg MOVE's source subtree). */
    async entriesUnder(relDir) {
      const spec = relDir.endsWith('/') ? relDir : `${relDir}/`;
      const r = await g(['ls-files', '-s', '-z', '--', `:(literal)${spec}`]);
      return r.text.split('\0').filter((s) => s.length > 0).map(parseStageLine).filter(Boolean);
    },

    /**
     * Hash IN-MEMORY content into the object store (Amendment C.iv).
     *
     * `--stdin` without `--path` deliberately stores the RAW BYTES: a filtered
     * hash would mean `git cat-file blob C:p` no longer returns what the human
     * approved, and every bit-for-bit undo guarantee in this wave is stated
     * against those exact bytes.
     */
    async hashObject(content) {
      const r = await g(['hash-object', '-w', '--stdin'], { input: content });
      return r.text.trim();
    },

    async setEntry(rel, mode, sha) {
      await g(['update-index', '--add', '--cacheinfo', `${mode},${sha},${rel}`]);
    },

    async removeEntry(rel) {
      await g(['update-index', '--force-remove', '--', rel]);
    },

    async writeTree() {
      const r = await g(['write-tree']);
      return r.text.trim();
    },
  };
}

/** The mode a new entry should carry: preserve the tracked mode when there is one. */
export async function modeForPath({ idx, rootPath, rel, fs = fsp }) {
  const existing = await idx.entry(rel);
  if (existing && existing.mode) return existing.mode;
  if (process.platform !== 'win32') {
    try {
      const st = await fs.stat(path.join(rootPath, rel));
      if (st.mode & 0o111) return '100755';
    } catch { /* absent: a created file is a plain file */ }
  }
  return '100644';
}

export default { withTempIndex, makeTempIndex, modeForPath };

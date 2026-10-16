// engine/snapshot.mjs — Wave 1: run snapshot S, the single time authority.
//
// S is captured ONCE, before analysis, and is the only "what the tree looked
// like" record in the system. SAVE identity (Wave 2) and Apply-time
// revalidation (Wave 3) compare against this same object, so no stage ever
// carries its own ad-hoc snapshot that could disagree with another's.
//
//   S = { head, root, capturedAt, paths: {rel -> {size, mtimeMs}}, hashes: {rel -> sha256},
//         excluded: [...], truncated: bool }
//
// Content hashes are LAZY: computed only for paths that become findings or
// Apply candidates, which keeps a 300k-file tree cheap to snapshot.
//
// TIER 2 OF THE TRIPWIRE lives here, and its semantics are deliberately
// DIFFERENT from Tier 1 (engine/write-audit.mjs):
//
//   production background run — external drift NEVER aborts. The user editing
//     their own files while a background pass runs is expected behaviour, not
//     an error. A delta on a FINDING's path marks exactly that finding STALE
//     (Apply-time revalidation drops it unless re-validated); a delta on a
//     non-finding path is recorded in the drift log and nothing else.
//
//   hermetic CI fixture — ANY delta fails the build. No external editor exists
//     in a fixture, so a delta there can only have come from the engine itself.
//     That is the assertion which actually verifies the zero-write invariant;
//     Tier 1 blocks the writes it can see, Tier 2 catches anything it could not.

import crypto from 'node:crypto';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { toPosixRel } from './glob.mjs';

/**
 * Capture S over an already-computed in-scope path list (the scan stage owns
 * enumeration; the snapshot owns metadata + time authority).
 *
 * @param {{rootPath: string, head?: string|null, paths: string[], excluded?: object[], fs?: object, now?: Function}} opts
 */
export async function captureSnapshot({ rootPath, head = null, paths = [], excluded = [], fs = fsp, now = () => new Date() }) {
  const root = path.resolve(rootPath);
  const S = {
    version: 1,
    root,
    head: head || null,
    capturedAt: now().toISOString(),
    paths: {},
    hashes: {},
    excluded: excluded.map((e) => (typeof e === 'string' ? { path: e, reason: 'excluded' } : e)),
    errors: [],
  };

  for (const p of paths) {
    const rel = toPosixRel(path.isAbsolute(p) ? path.relative(root, p) : p);
    const abs = path.join(root, rel);
    try {
      const st = await fs.stat(abs);
      S.paths[rel] = { size: st.size, mtimeMs: Math.round(st.mtimeMs) };
    } catch (err) {
      S.errors.push({ path: rel, error: err && err.message });
    }
  }
  return S;
}

/** sha256 of a file's bytes. */
export async function hashFile(absPath, { fs = fsp } = {}) {
  const buf = await fs.readFile(absPath);
  return 'sha256:' + crypto.createHash('sha256').update(buf).digest('hex');
}

/**
 * Lazily record (and return) the content hash for one in-scope path. Called at
 * finding-emission time — the ONLY place hashes enter S.
 */
export async function ensureHash(S, rel, { fs = fsp } = {}) {
  const key = toPosixRel(rel);
  if (S.hashes[key]) return S.hashes[key];
  const abs = path.join(S.root, key);
  try {
    const h = await hashFile(abs, { fs });
    S.hashes[key] = h;
    return h;
  } catch (err) {
    S.errors.push({ path: key, error: `hash failed: ${err && err.message}` });
    return null;
  }
}

/**
 * The post-analysis metadata sweep. Compares the tree against S and classifies
 * every delta per the two-tier semantics described in the file header.
 *
 * @param {object} S
 * @param {{findingPaths?: string[], hermetic?: boolean, fs?: object}} opts
 * @returns {Promise<{deltas: object[], stale: string[], drift: object[], hermeticFailure: boolean, status: 'ok'|'partial'|'failed'}>}
 */
export async function sweepSnapshot(S, { findingPaths = [], hermetic = false, fs = fsp } = {}) {
  const findings = new Set(findingPaths.map(toPosixRel));
  const deltas = [];

  for (const [rel, meta] of Object.entries(S.paths)) {
    const abs = path.join(S.root, rel);
    let st = null;
    try {
      st = await fs.stat(abs);
    } catch {
      deltas.push({ path: rel, kind: 'deleted', was: meta, now: null });
      continue;
    }
    const nowMeta = { size: st.size, mtimeMs: Math.round(st.mtimeMs) };
    if (nowMeta.size !== meta.size || nowMeta.mtimeMs !== meta.mtimeMs) {
      deltas.push({ path: rel, kind: 'modified', was: meta, now: nowMeta });
    }
  }

  const stale = [];
  const drift = [];
  for (const d of deltas) {
    if (findings.has(d.path)) stale.push(d.path);
    else drift.push(d);
  }

  const hermeticFailure = Boolean(hermetic && deltas.length > 0);
  return {
    deltas,
    stale,
    drift,
    hermeticFailure,
    // A production run with drift is STILL a completed run — 'partial' at worst,
    // never 'failed'. Only the hermetic fixture turns a delta into a failure.
    status: hermeticFailure ? 'failed' : (deltas.length ? 'partial' : 'ok'),
    note: hermeticFailure
      ? `HERMETIC FIXTURE: ${deltas.length} metadata delta(s) vs snapshot S with no external editor present — the engine wrote under the root. Zero-write invariant broken.`
      : (deltas.length
        ? `${stale.length} finding path(s) marked STALE, ${drift.length} non-finding path(s) recorded in the drift log — external edits during a background pass are expected and do not abort the run.`
        : 'no metadata drift vs snapshot S'),
  };
}

/** Mark findings whose path drifted; the panel renders these as STALE. */
export function applyStaleness(findings, stalePaths) {
  const stale = new Set(stalePaths.map(toPosixRel));
  let marked = 0;
  for (const f of findings || []) {
    const rel = f && (f.path || f.rel || f.filepath);
    if (rel && stale.has(toPosixRel(rel))) {
      f.stale = true;
      f.staleReason = 'file changed on disk after the run snapshot S was taken — Apply-time revalidation will drop it unless re-validated';
      marked++;
    }
  }
  return marked;
}

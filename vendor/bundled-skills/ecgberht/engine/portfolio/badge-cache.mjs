/**
 * Wave 17 — ambient ⚑ badge cache under the portfolio index home.
 *
 * The ingest path (attention push) updates this cell; the badge poll path
 * reads it behind the index-only trap so each poll opens a bounded number of
 * files and never walks project roots (discoverStrips unreachable).
 *
 * Leaf-ish module: durable write + fs only for the cache file itself. Raise
 * scoring is inlined for needs_you / deliverable_ready so this file does not
 * import high-seat.mjs (avoids load cycles with glance).
 *
 * Stdlib only. No host-absolute paths.
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  writeFileAtomicSync,
  withFileLock,
  LOCK_TIMEOUT_MS,
} from '../durable-write.mjs';

export const BADGE_CACHE_REL = 'badge-cache.json';
export const BADGE_CACHE_SCHEMA = 'ecgberht-badge-cache-v0';
export const ATTENTION_INDEX_REL = 'attention';

/** Raise-relevant published attention states (criterion 12). */
const RAISE_STATES = new Set(['needs_you', 'deliverable_ready', 'blocked']);

/**
 * @param {string} home
 * @returns {string}
 */
export function badgeCachePath(home) {
  return path.join(String(home), BADGE_CACHE_REL);
}

/**
 * @param {{ count?: number, queue_length?: number, at?: string, updated_via?: string, projects?: string[] }} cell
 */
export function badgeCachePayload(cell = {}) {
  const count = Number(cell.count ?? cell.queue_length ?? 0) || 0;
  return {
    schema: BADGE_CACHE_SCHEMA,
    glyph: '⚑',
    count,
    queue_length: count,
    only_ambient_signal: true,
    at: cell.at ?? new Date().toISOString(),
    updated_via: cell.updated_via ?? 'recompute',
    projects: Array.isArray(cell.projects) ? cell.projects : [],
    ambient_beyond_badge: 0,
  };
}

/**
 * Write the badge cache cell (ingest path — has write authority on index home).
 * @param {{ home: string, count?: number, queue_length?: number, projects?: string[], updated_via?: string }} req
 */
export function writeBadgeCache(req = {}) {
  const home = req.home;
  if (!home || typeof home !== 'string') {
    return Object.freeze({ ok: false, reason: 'home_required', path: null });
  }
  const payload = badgeCachePayload(req);
  const cellPath = badgeCachePath(home);
  const bytes = `${JSON.stringify(payload, null, 2)}\n`;
  try {
    withFileLock(
      cellPath,
      () => {
        fs.mkdirSync(path.dirname(cellPath), { recursive: true });
        writeFileAtomicSync(cellPath, bytes);
      },
      { timeoutMs: LOCK_TIMEOUT_MS },
    );
  } catch {
    try {
      fs.mkdirSync(path.dirname(cellPath), { recursive: true });
      writeFileAtomicSync(cellPath, bytes);
    } catch (e2) {
      return Object.freeze({
        ok: false,
        reason: String(e2?.message ?? e2),
        path: cellPath,
      });
    }
  }
  return Object.freeze({
    ok: true,
    path: cellPath,
    cell: payload,
    count: payload.count,
  });
}

/**
 * Read badge cache (caller supplies fs facade for index-only trap).
 * @param {{ home: string, fsx?: object }} req
 */
export function readBadgeCacheFile(req = {}) {
  const home = req.home;
  if (!home) {
    return Object.freeze({ ok: false, exists: false, cell: null, reason: 'home_required' });
  }
  const fsx = req.fsx ?? fs;
  const cellPath = badgeCachePath(home);
  try {
    if (!fsx.existsSync(cellPath)) {
      return Object.freeze({ ok: true, exists: false, cell: null, path: cellPath });
    }
    const cell = JSON.parse(fsx.readFileSync(cellPath, 'utf8'));
    if (!cell || cell.schema !== BADGE_CACHE_SCHEMA) {
      return Object.freeze({
        ok: false,
        exists: true,
        cell: null,
        path: cellPath,
        reason: 'schema_mismatch',
      });
    }
    return Object.freeze({ ok: true, exists: true, cell, path: cellPath });
  } catch (e) {
    return Object.freeze({
      ok: false,
      exists: false,
      cell: null,
      path: cellPath,
      reason: String(e?.message ?? e),
    });
  }
}

/**
 * List attention cells under index home.
 * @param {{ home: string, fsx?: object }} req
 * @returns {object[]}
 */
export function listAttentionCells(req = {}) {
  const home = req.home;
  if (!home) return [];
  const fsx = req.fsx ?? fs;
  const dir = path.join(home, ATTENTION_INDEX_REL);
  let names = [];
  try {
    if (!fsx.existsSync(dir)) return [];
    names = fsx.readdirSync(dir);
  } catch {
    return [];
  }
  const cells = [];
  for (const name of names) {
    if (!String(name).endsWith('.json')) continue;
    try {
      const cell = JSON.parse(fsx.readFileSync(path.join(dir, name), 'utf8'));
      if (cell && typeof cell === 'object') cells.push(cell);
    } catch {
      // skip unreadable cell file
    }
  }
  return cells;
}

/**
 * Count raise-queue length from attention cells (needs_you / deliverable_ready / blocked).
 * @param {object[]} cells
 */
export function countRaiseFromAttentionCells(cells = []) {
  const projects = [];
  let count = 0;
  for (const c of cells) {
    if (c && RAISE_STATES.has(c.state)) {
      count += 1;
      if (c.project_id) projects.push(c.project_id);
    }
  }
  return { count, projects };
}

/**
 * Recompute badge cache from attention cells under home (ingest path).
 * @param {{ home: string }} req
 */
export function recomputeBadgeCacheFromHome(req = {}) {
  const home = req.home;
  if (!home) return Object.freeze({ ok: false, reason: 'home_required' });
  const cells = listAttentionCells({ home, fsx: fs });
  const { count, projects } = countRaiseFromAttentionCells(cells);
  const written = writeBadgeCache({
    home,
    count,
    projects,
    updated_via: req.updated_via ?? 'recomputeBadgeCacheFromHome',
  });
  return Object.freeze({
    ok: written.ok === true,
    count,
    projects,
    cache: written,
    cells_read: cells.length,
  });
}

/**
 * Called after a successful attention push (Wave 17 ingest → badge cache).
 * @param {{ home: string, justPushed?: object }} req
 */
export function refreshBadgeCacheAfterAttentionPush(req = {}) {
  return recomputeBadgeCacheFromHome({
    home: req.home,
    updated_via: 'pushAttentionProjection',
  });
}

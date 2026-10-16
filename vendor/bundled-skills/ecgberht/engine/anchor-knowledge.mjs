/**
 * TW2 — Anchor knowledge adapter (READ-ONLY).
 *
 * Q7 evidence source: `.anchor/projects/<p>/{planning,research}/summaries`
 * + `deliverables`, read as evidence only.
 *
 * Direction law (W7-BRIEF-SPEC §3.3): Ecgberht reads Anchor's store as
 * evidence; it NEVER writes campaign truth into it. Strip+Face remain the
 * sole ledger. Missing/empty store → `unknown`, no crash, nothing invented.
 */

import fs from 'node:fs';
import path from 'node:path';

/** This adapter has zero write authority over the Anchor store. */
export const ANCHOR_KNOWLEDGE_READ_ONLY = true;

/** Store layout relative names (never host-absolute). */
export const ANCHOR_STORE_DIR_NAME = '.anchor';
export const ANCHOR_PROJECTS_DIR_NAME = 'projects';
export const ANCHOR_LANES = Object.freeze(['planning', 'research']);
export const ANCHOR_SUMMARY_FILE_NAME = 'summary.json';
export const ANCHOR_PROJECT_SUMMARY_FILE_NAME = 'project-summary.json';

/** Env override for the anchor store root (dir containing `projects/`). */
export const ENV_ANCHOR_ROOT = 'ECGBERHT_ANCHOR_ROOT';

/** Direction law, exported for docs/tests. */
export const ANCHOR_DIRECTION_LAW = Object.freeze({
  reads: 'anchor_store_as_evidence',
  writes: 'never',
  sole_ledger: 'strip_and_face',
  missing_store: 'unknown_no_crash',
});

function isDir(p) {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

function isFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

/**
 * Resolve the anchor store root (the `.anchor` directory).
 * Order: explicit opts.anchor_root → env ECGBERHT_ANCHOR_ROOT → walk up from
 * project_path looking for `.anchor/projects`. Nothing found → null (unknown).
 * @param {{ project_path?: string|null, anchor_root?: string|null, env?: object }} [opts]
 * @returns {{ root: string|null, source: string }}
 */
export function resolveAnchorRoot(opts = {}) {
  if (typeof opts.anchor_root === 'string' && opts.anchor_root.trim()) {
    return { root: path.resolve(opts.anchor_root.trim()), source: 'explicit' };
  }
  const env = opts.env ?? process.env;
  const fromEnv = env?.[ENV_ANCHOR_ROOT];
  if (typeof fromEnv === 'string' && fromEnv.trim()) {
    return { root: path.resolve(fromEnv.trim()), source: 'env' };
  }
  if (typeof opts.project_path === 'string' && opts.project_path.trim()) {
    let dir = path.resolve(opts.project_path.trim());
    for (let hop = 0; hop < 8; hop++) {
      const candidate = path.join(dir, ANCHOR_STORE_DIR_NAME);
      if (isDir(path.join(candidate, ANCHOR_PROJECTS_DIR_NAME))) {
        return { root: candidate, source: 'walk_up' };
      }
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  return { root: null, source: 'none' };
}

function readJsonSafe(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Recursively collect summary.json files under a lane's summaries dir.
 * @param {string} dir
 * @param {number} [depth]
 * @returns {string[]}
 */
function collectSummaryFiles(dir, depth = 0) {
  if (depth > 4 || !isDir(dir)) return [];
  const out = [];
  let entries = [];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const ent of entries) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      out.push(...collectSummaryFiles(p, depth + 1));
    } else if (ent.isFile() && ent.name === ANCHOR_SUMMARY_FILE_NAME) {
      out.push(p);
    }
  }
  return out;
}

/**
 * A summary is grounded when it carries claims or a non-empty summary text
 * and does not self-declare `no_grounded_claims: true`.
 * @param {object} summary
 */
export function isGroundedSummary(summary) {
  if (!summary || typeof summary !== 'object') return false;
  if (summary.no_grounded_claims === true) return false;
  const claims = Array.isArray(summary.claims) ? summary.claims : [];
  const text =
    typeof summary.summary_text === 'string' ? summary.summary_text.trim() : '';
  return claims.length > 0 || text !== '';
}

/**
 * Read-only projection of one project's Anchor knowledge store.
 * Missing/empty store is an honest `present: false` — never a crash.
 * @param {{
 *   project_path?: string|null,
 *   project_key?: string|null,
 *   anchor_root?: string|null,
 *   env?: object,
 * }} [opts]
 * @returns {object}
 */
export function readAnchorProjectKnowledge(opts = {}) {
  const resolved = resolveAnchorRoot(opts);
  const project_key =
    typeof opts.project_key === 'string' && opts.project_key.trim()
      ? opts.project_key.trim()
      : opts.project_path
        ? path.basename(path.resolve(opts.project_path))
        : null;

  const base = {
    ok: true,
    read_only: ANCHOR_KNOWLEDGE_READ_ONLY,
    direction_law: ANCHOR_DIRECTION_LAW,
    write_authority: 'none',
    anchor_root_source: resolved.source,
    project_key,
    present: false,
    summaries: [],
    deliverables: [],
    grounded_count: 0,
    lanes_scanned: [],
  };

  if (!resolved.root || !project_key) {
    return { ...base, reason: !resolved.root ? 'no_anchor_root' : 'no_project_key' };
  }

  const projectDir = path.join(
    resolved.root,
    ANCHOR_PROJECTS_DIR_NAME,
    project_key,
  );
  if (!isDir(projectDir)) {
    return { ...base, reason: 'project_store_missing' };
  }

  const summaries = [];
  const lanes_scanned = [];
  for (const lane of ANCHOR_LANES) {
    const lanesDir = path.join(projectDir, lane, 'summaries');
    lanes_scanned.push(lane);
    for (const file of collectSummaryFiles(lanesDir)) {
      const summary = readJsonSafe(file);
      if (!summary) continue;
      const rel = path
        .relative(resolved.root, file)
        .split(path.sep)
        .join('/');
      summaries.push({
        lane,
        path: rel,
        title: typeof summary.title === 'string' ? summary.title : null,
        no_grounded_claims: summary.no_grounded_claims === true,
        claims_count: Array.isArray(summary.claims) ? summary.claims.length : 0,
        claims: Array.isArray(summary.claims) ? summary.claims.slice(0, 12) : [],
        summary_text:
          typeof summary.summary_text === 'string' ? summary.summary_text : '',
        grounded: isGroundedSummary(summary),
        generated_at: summary.generated_at ?? null,
      });
    }
  }

  // Project-level summary (if present) counts as an evidence surface too.
  const projectSummaryPath = path.join(projectDir, ANCHOR_PROJECT_SUMMARY_FILE_NAME);
  if (isFile(projectSummaryPath)) {
    const summary = readJsonSafe(projectSummaryPath);
    if (summary) {
      summaries.push({
        lane: 'project',
        path: path
          .relative(resolved.root, projectSummaryPath)
          .split(path.sep)
          .join('/'),
        title: typeof summary.title === 'string' ? summary.title : null,
        no_grounded_claims: summary.no_grounded_claims === true,
        claims_count: Array.isArray(summary.claims) ? summary.claims.length : 0,
        claims: Array.isArray(summary.claims) ? summary.claims.slice(0, 12) : [],
        summary_text:
          typeof summary.summary_text === 'string' ? summary.summary_text : '',
        grounded: isGroundedSummary(summary),
        generated_at: summary.generated_at ?? null,
      });
    }
  }

  // Deliverables: names only (evidence pointers, no content parse required).
  const deliverables = [];
  const deliverablesDir = path.join(projectDir, 'deliverables');
  if (isDir(deliverablesDir)) {
    try {
      for (const ent of fs.readdirSync(deliverablesDir, { withFileTypes: true })) {
        deliverables.push({
          name: ent.name,
          kind: ent.isDirectory() ? 'dir' : 'file',
          path: path
            .relative(resolved.root, path.join(deliverablesDir, ent.name))
            .split(path.sep)
            .join('/'),
        });
      }
    } catch {
      // unreadable deliverables dir → honest empty list
    }
  }

  return {
    ...base,
    present: true,
    project_store_present: true,
    summaries,
    deliverables,
    grounded_count: summaries.filter((s) => s.grounded).length,
    lanes_scanned,
  };
}

/**
 * Q7 conclusions from the read-only knowledge projection.
 * No grounded evidence → empty list (caller renders honest unknown).
 * @param {object} knowledge result of readAnchorProjectKnowledge
 * @returns {{ conclusions: object[], grounded: boolean }}
 */
export function anchorConclusions(knowledge) {
  if (!knowledge || knowledge.present !== true) {
    return { conclusions: [], grounded: false };
  }
  const conclusions = [];
  for (const s of knowledge.summaries) {
    if (!s.grounded) continue;
    const text =
      (s.claims && s.claims.length
        ? s.claims
            .map((c) => (typeof c === 'string' ? c : (c?.text ?? c?.claim ?? null)))
            .filter(Boolean)
            .join('; ')
        : '') ||
      s.summary_text.trim() ||
      s.title ||
      null;
    if (!text) continue;
    conclusions.push({
      lane: s.lane,
      text,
      provenance: { source: s.path, store: 'anchor_read_only' },
    });
  }
  return { conclusions, grounded: conclusions.length > 0 };
}

/**
 * Any attempt to write campaign truth into the Anchor store is ALWAYS refused.
 * Mirrors mutateStripInPlace / mutateRoadmapProjectionInPlace refusal style.
 * @param {object} [attempt]
 */
export function refuseAnchorStoreWrite(attempt = {}) {
  return {
    ok: false,
    error: 'anchor_store_write_refused',
    read_only: ANCHOR_KNOWLEDGE_READ_ONLY,
    direction_law: ANCHOR_DIRECTION_LAW,
    message:
      'Ecgberht reads the Anchor store as evidence only; it never writes campaign truth into it. Strip+Face remain the sole ledger.',
    attempted: Object.keys(attempt || {}),
    store_unchanged: true,
  };
}

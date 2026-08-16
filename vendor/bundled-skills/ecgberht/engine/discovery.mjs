/**
 * A1 discovery — CLI/env roots, no registry.
 * First match wins: strip.json or ECGBERHT.md Strip fence.
 * Scan listed roots + one level of subdirs; ignore junk; empty → structured empty.
 */

import fs from 'node:fs';
import path from 'node:path';
import {
  FACE_FILE_NAME,
  STRIP_FILE_NAME,
  extractStripFence,
  hasStripFenceMarker,
  parseStrip,
  toStripProjection,
} from './face-strip.mjs';

/** Env var: OS path separator (path.delimiter) separated list of roots. */
export const ENV_STRIP_ROOTS = 'ECGBERHT_STRIP_ROOTS';

/** Directory basenames skipped during scan (junk). */
export const JUNK_DIR_NAMES = Object.freeze([
  'node_modules',
  '.git',
  'vendor',
  '.hg',
  '.svn',
  '.trash',
  'dist',
  'build',
  'coverage',
  '__pycache__',
  '.cache',
  'tmp',
  'temp',
]);

const JUNK_SET = new Set(JUNK_DIR_NAMES.map((n) => n.toLowerCase()));

/**
 * Parse ECGBERHT_STRIP_ROOTS (or any delimiter-separated string).
 * @param {string|undefined|null} envValue
 * @param {string} [delimiter] defaults to path.delimiter
 * @returns {string[]}
 */
export function parseRootsFromEnv(envValue, delimiter = path.delimiter) {
  if (envValue == null || envValue === '') return [];
  if (typeof envValue !== 'string') return [];
  return envValue
    .split(delimiter)
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * Parse CLI argv for --roots and --project.
 * Forms: --roots a;b  OR  --roots a --roots b  OR  --roots=a;b
 * On Windows path.delimiter is `;`; also accept `,` as soft separator inside one token.
 * @param {string[]} argv
 * @returns {{ roots: string[], project: string|null, rest: string[] }}
 */
export function parseRootsFromCliArgs(argv = []) {
  const roots = [];
  let project = null;
  const rest = [];
  const tokens = Array.isArray(argv) ? [...argv] : [];

  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (t === '--roots' || t === '-R') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        roots.push(...splitRootToken(next));
        i++;
      }
      continue;
    }
    if (t.startsWith('--roots=')) {
      roots.push(...splitRootToken(t.slice('--roots='.length)));
      continue;
    }
    if (t === '--project' || t === '-p') {
      const next = tokens[i + 1];
      if (next && !next.startsWith('-')) {
        project = next;
        i++;
      }
      continue;
    }
    if (t.startsWith('--project=')) {
      project = t.slice('--project='.length);
      continue;
    }
    rest.push(t);
  }

  return { roots, project, rest };
}

/**
 * @param {string} token
 */
function splitRootToken(token) {
  // Prefer OS delimiter; also split on comma for ergonomics when not Windows-drive-ambiguous
  const delim = path.delimiter;
  let parts = token.split(delim).map((s) => s.trim()).filter(Boolean);
  if (parts.length === 1 && delim !== ',' && token.includes(',')) {
    // Only split commas when not looking like a single path with no delimiter use
    parts = token.split(',').map((s) => s.trim()).filter(Boolean);
  }
  return parts;
}

/**
 * Resolve discovery roots: CLI --roots first, else env, else empty.
 * A1 live path: when opts.env is omitted, read process.env.ECGBERHT_STRIP_ROOTS
 * (no registry). opts.env / opts.envValue override for tests and injectors.
 * @param {{ roots?: string[], env?: NodeJS.ProcessEnv|object, envValue?: string|null }} [opts]
 * @returns {string[]}
 */
export function resolveDiscoveryRoots(opts = {}) {
  const fromCli = Array.isArray(opts.roots) ? opts.roots.filter(Boolean) : [];
  if (fromCli.length) return fromCli.map((r) => path.resolve(r));

  let envValue = opts.envValue;
  if (envValue === undefined) {
    // Live A1: process.env is the default host surface when env bag not injected
    const env = opts.env !== undefined ? opts.env : process.env;
    envValue = env?.[ENV_STRIP_ROOTS];
  }
  return parseRootsFromEnv(envValue).map((r) => path.resolve(r));
}

/**
 * @param {string} name basename
 */
export function isJunkDirName(name) {
  if (!name || typeof name !== 'string') return true;
  if (name === '.' || name === '..') return true;
  return JUNK_SET.has(name.toLowerCase());
}

/**
 * Does this directory contain strip.json?
 * @param {string} dir
 */
export function findStripJson(dir) {
  const p = path.join(dir, STRIP_FILE_NAME);
  try {
    if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
  } catch {
    return null;
  }
  return null;
}

/**
 * Does this directory contain ECGBERHT.md with a Strip fence?
 * Reads Face only to extract fence JSON — not a full narrative rank path.
 * @param {string} dir
 * @returns {{ path: string|null, strip: object|null, has_fence: boolean }}
 */
export function findStripFenceInFace(dir) {
  const p = path.join(dir, FACE_FILE_NAME);
  try {
    if (!fs.existsSync(p) || !fs.statSync(p).isFile()) {
      return { path: null, strip: null, has_fence: false };
    }
    const raw = fs.readFileSync(p, 'utf8');
    if (!hasStripFenceMarker(raw)) {
      return { path: p, strip: null, has_fence: false };
    }
    const fence = extractStripFence(raw);
    if (!fence.found) {
      return { path: p, strip: null, has_fence: false };
    }
    const parsed = parseStrip(fence.strip);
    return {
      path: p,
      strip: parsed.ok ? parsed.strip : fence.strip,
      has_fence: true,
    };
  } catch {
    return { path: null, strip: null, has_fence: false };
  }
}

/**
 * First match wins for a single directory: strip.json, else Face fence.
 * @param {string} dir
 * @returns {object|null} discovery hit or null
 */
export function discoverInDirectory(dir) {
  const resolved = path.resolve(dir);
  let stat;
  try {
    stat = fs.statSync(resolved);
  } catch {
    return null;
  }
  if (!stat.isDirectory()) return null;

  const base = path.basename(resolved);
  if (isJunkDirName(base)) return null;

  const stripJson = findStripJson(resolved);
  if (stripJson) {
    try {
      const raw = fs.readFileSync(stripJson, 'utf8');
      const parsed = parseStrip(raw);
      if (parsed.ok) {
        return {
          project_path: resolved,
          strip_path: stripJson,
          face_path: fs.existsSync(path.join(resolved, FACE_FILE_NAME))
            ? path.join(resolved, FACE_FILE_NAME)
            : null,
          strip_source: 'strip.json',
          strip: parsed.strip,
          face_fully_loaded: false,
          projection: toStripProjection(parsed.strip, {
            project_path: resolved,
            strip_source: 'strip.json',
          }),
        };
      }
    } catch {
      // fall through to fence
    }
  }

  const fence = findStripFenceInFace(resolved);
  if (fence.has_fence && fence.strip) {
    return {
      project_path: resolved,
      strip_path: null,
      face_path: fence.path,
      strip_source: 'face_fence',
      strip: fence.strip,
      // Fence parse reads the Face file for the JSON block only — not rank-time full Face narrative use
      face_fully_loaded: false,
      projection: toStripProjection(fence.strip, {
        project_path: resolved,
        strip_source: 'face_fence',
      }),
    };
  }

  return null;
}

/**
 * A1 discovery under locked MVP scan depth: each listed root + one level of subdirs.
 * Junk dirs skipped. Empty roots → structured empty (ok:true, strips:[]).
 * No registry. First match wins per directory (strip.json over fence).
 *
 * Anti-N-full-read metric: face_full_reads stays 0 on this path (fence parse is
 * projection-only; full Face narrative load is reserved for top-k drill-in / heal).
 *
 * @param {{ roots?: string[], env?: object, envValue?: string|null }} [opts]
 * @returns {{ ok: true, strips: object[], roots: string[], empty: boolean, scanned: string[], skipped_junk: string[], face_full_reads: number, fence_partial_reads: number }}
 */
export function discoverStrips(opts = {}) {
  const roots = resolveDiscoveryRoots(opts);
  const strips = [];
  const scanned = [];
  const skipped_junk = [];
  const seen = new Set();
  // Honest anti-N-full-read counters: discovery never full-loads Face narrative
  let face_full_reads = 0;
  let fence_partial_reads = 0;
  let strip_json_reads = 0;

  if (roots.length === 0) {
    return {
      ok: true,
      empty: true,
      strips: [],
      roots: [],
      scanned: [],
      skipped_junk: [],
      face_full_reads: 0,
      fence_partial_reads: 0,
      strip_json_reads: 0,
      message: 'No discovery roots (CLI --roots / ECGBERHT_STRIP_ROOTS empty)',
      registry: false,
    };
  }

  for (const root of roots) {
    collectHit(root, strips, scanned, seen, {
      onFence: () => {
        fence_partial_reads += 1;
      },
      onStripJson: () => {
        strip_json_reads += 1;
      },
    });

    let entries = [];
    try {
      entries = fs.readdirSync(root, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const ent of entries) {
      if (!ent.isDirectory()) continue;
      if (isJunkDirName(ent.name)) {
        skipped_junk.push(path.join(root, ent.name));
        continue;
      }
      const child = path.join(root, ent.name);
      collectHit(child, strips, scanned, seen, {
        onFence: () => {
          fence_partial_reads += 1;
        },
        onStripJson: () => {
          strip_json_reads += 1;
        },
      });
    }
  }

  // face_full_reads intentionally remains 0: discover never calls full Face narrative load
  return {
    ok: true,
    empty: strips.length === 0,
    strips,
    roots,
    scanned,
    skipped_junk,
    face_full_reads,
    fence_partial_reads,
    strip_json_reads,
    registry: false,
    scan_depth: 1,
    message:
      strips.length === 0
        ? 'Structured empty: no strip.json or Face Strip fence under roots'
        : `Discovered ${strips.length} strip projection(s)`,
  };
}

/**
 * @param {string} dir
 * @param {object[]} strips
 * @param {string[]} scanned
 * @param {Set<string>} seen
 * @param {{ onFence?: () => void, onStripJson?: () => void }} [hooks]
 */
function collectHit(dir, strips, scanned, seen, hooks = {}) {
  const key = path.resolve(dir);
  if (seen.has(key)) return;
  scanned.push(key);
  const hit = discoverInDirectory(dir);
  if (hit) {
    seen.add(key);
    if (hit.strip_source === 'face_fence' && typeof hooks.onFence === 'function') {
      hooks.onFence();
    }
    if (hit.strip_source === 'strip.json' && typeof hooks.onStripJson === 'function') {
      hooks.onStripJson();
    }
    strips.push(hit);
  }
}

/**
 * Per-wave repo manifests + lane file selection (Wave 1 BUILD CONTRACT).
 *
 * Primary repo by wave (from IMPLEMENTATION-PLAN v3 BUILD CONTRACT + W13 pin):
 *   Ecgberht — 1, 2, 3, 6, 7, 8, 9, 10, 12, 14, 15, 16, 20, 21, 22
 *   Anchor   — 13 (Python outbox host contract only), 17, 18
 *   both     — 4, 5, 11, 19
 *
 * AUTH-ON lane files live under test/auth-on/ (or *.auth-on.test.mjs).
 * Everything else under test/*.test.mjs is the SKILL lane (host-less).
 */

import fs from 'node:fs';
import path from 'node:path';

/** @type {Record<number, Array<'ecgberht'|'anchor'>>} */
export const WAVE_REPOS = Object.freeze({
  1: ['ecgberht'],
  2: ['ecgberht'],
  3: ['ecgberht'],
  4: ['ecgberht', 'anchor'],
  5: ['ecgberht', 'anchor'],
  6: ['ecgberht'],
  7: ['ecgberht'],
  8: ['ecgberht'],
  9: ['ecgberht'],
  10: ['ecgberht'],
  11: ['ecgberht', 'anchor'],
  12: ['ecgberht'],
  // Wave 13: primary repo is Anchor (S12 Python outbox host contract only).
  13: ['anchor'],
  14: ['ecgberht'],
  15: ['ecgberht'],
  16: ['ecgberht'],
  17: ['anchor'],
  18: ['anchor'],
  19: ['ecgberht', 'anchor'],
  20: ['ecgberht'],
  21: ['ecgberht'],
  22: ['ecgberht'],
});

/**
 * @param {number} wave
 * @returns {Array<'ecgberht'|'anchor'>}
 */
export function reposForWave(wave) {
  const n = Number(wave);
  return WAVE_REPOS[n] ? [...WAVE_REPOS[n]] : ['ecgberht'];
}

/**
 * Optional per-wave pytest paths (relative to Anchor root). Empty until Anchor
 * waves land tests; Wave 1 wires the bridge so later waves can declare paths.
 * @type {Record<number, string[]>}
 */
export const WAVE_PYTEST_PATHS = Object.freeze({
  // Wave 1 has no Anchor pytest yet; bridge still exercises empty-list success.
  1: [],
  // Wave 4 — Anchor reference commission executor (host contract only).
  4: ['tests/test_commission_executor_w4.py'],
  // Wave 13 — S12 status outbox + lease emission (host contract only).
  13: ['tests/test_status_outbox_w13.py'],
});

/**
 * Union of all declared pytest paths (for full-suite auth-on bridge when
 * ECGBERHT_WAVE is unset). Deduped, stable order by wave number then path.
 * @returns {string[]}
 */
export function allPytestPaths() {
  const seen = new Set();
  const out = [];
  for (const n of Object.keys(WAVE_PYTEST_PATHS)
    .map(Number)
    .sort((a, b) => a - b)) {
    for (const p of WAVE_PYTEST_PATHS[n] || []) {
      if (!seen.has(p)) {
        seen.add(p);
        out.push(p);
      }
    }
  }
  return out;
}

/**
 * @param {number} wave
 * @returns {string[]}
 */
export function pytestPathsForWave(wave) {
  const n = Number(wave);
  return WAVE_PYTEST_PATHS[n] ? [...WAVE_PYTEST_PATHS[n]] : [];
}

/**
 * Wave-1 AUTH-ON lane files (done-when: hammer, durability, auth negatives,
 * A3, T-DUR-S11, pytest bridge, T-EQUIV-01, CI diff guard). Host-less skill
 * proofs (lane scrub unit tests, skill pack, reachability) stay in skill.
 * Match on basename so both `test/w1-…` and nested paths classify correctly.
 */
const AUTH_ON_BASENAME_RE =
  /^(w1-auth-|w1-storage-hammer|w1-a3-|w1-t-dur-s11|w1-equiv-check|w1-diff-guard|w1-pytest-bridge)/i;

/**
 * Classify a test file path as skill vs auth-on.
 * @param {string} relPath posix or platform path relative to repo root
 * @returns {'skill'|'auth-on'}
 */
export function classifyTestFile(relPath) {
  const norm = String(relPath).replace(/\\/g, '/');
  const base = norm.includes('/') ? norm.slice(norm.lastIndexOf('/') + 1) : norm;
  if (
    norm.includes('/auth-on/') ||
    norm.startsWith('auth-on/') ||
    norm.endsWith('.auth-on.test.mjs') ||
    norm.endsWith('.auth-on.test.js') ||
    AUTH_ON_BASENAME_RE.test(base)
  ) {
    return 'auth-on';
  }
  return 'skill';
}

/**
 * List test files under testDir, partitioned by lane.
 * @param {string} testDir absolute path to test/
 * @returns {{ skill: string[], authOn: string[], all: string[] }}
 *   paths relative to repo root as `test/...`
 */
export function listLaneTestFiles(testDir) {
  const skill = [];
  const authOn = [];

  function walk(dir, relBase) {
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of entries) {
      const abs = path.join(dir, ent.name);
      const rel = path.join(relBase, ent.name);
      if (ent.isDirectory()) {
        // helpers/ is not a test suite
        if (ent.name === 'helpers' || ent.name === 'fixtures') continue;
        walk(abs, rel);
        continue;
      }
      if (!ent.isFile()) continue;
      if (!ent.name.endsWith('.test.mjs') && !ent.name.endsWith('.test.js')) {
        continue;
      }
      const posix = rel.split(path.sep).join('/');
      const lane = classifyTestFile(posix);
      if (lane === 'auth-on') authOn.push(posix);
      else skill.push(posix);
    }
  }

  walk(testDir, 'test');
  skill.sort();
  authOn.sort();
  return { skill, authOn, all: [...skill, ...authOn].sort() };
}

/**
 * Resolve Anchor repo root for the pytest bridge.
 * Prefer ANCHOR_REPO / ECGBERHT_ANCHOR_ROOT env; else sibling ../Anchor.
 * @param {string} ecgberhtRoot
 * @param {NodeJS.ProcessEnv} [env]
 * @returns {string|null} absolute path or null if missing
 */
export function resolveAnchorRoot(ecgberhtRoot, env = process.env) {
  const fromEnv = env.ANCHOR_REPO || env.ECGBERHT_ANCHOR_ROOT || env.ANCHOR_ROOT;
  if (fromEnv && String(fromEnv).trim()) {
    const p = path.resolve(String(fromEnv).trim());
    return fs.existsSync(p) ? p : null;
  }
  const sibling = path.resolve(ecgberhtRoot, '..', 'Anchor');
  return fs.existsSync(sibling) ? sibling : null;
}

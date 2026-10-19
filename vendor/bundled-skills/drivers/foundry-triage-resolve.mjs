// foundry-triage-resolve.mjs — resolve @foundry/triage wire modules without
// hardcoding host paths (ship-safe for collaborators; 2026-07-24).
//
// Search order:
//   1. FOUNDRY_TRIAGE_DIR / <file>
//   2. ANCHOR_FOUNDRY_DIR / foundry/triage / <file>
//   3. SKILL_FOUNDRY_DIR / foundry/triage / <file>
//   4. sibling of trio: ../Skill Foundry/foundry/triage/<file>
//   5. env FOUNDRY_HOME / foundry/triage / <file>
//
// Returns a file:// URL for dynamic import().

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TRIO_ROOT = path.resolve(HERE, '..');

/**
 * @param {string} file  e.g. 'crucible-wire.mjs' | 'foreman-wire.mjs'
 * @returns {string} absolute filesystem path
 */
export function resolveFoundryTriagePath(file) {
  const name = String(file || '').replace(/^[/\\]+/, '');
  if (!name || name.includes('..')) {
    throw new Error(`invalid foundry triage file: ${file}`);
  }
  const candidates = [];
  const push = (p) => { if (p) candidates.push(path.resolve(p)); };

  if (process.env.FOUNDRY_TRIAGE_DIR) {
    push(path.join(process.env.FOUNDRY_TRIAGE_DIR, name));
  }
  for (const rootEnv of ['ANCHOR_FOUNDRY_DIR', 'SKILL_FOUNDRY_DIR', 'FOUNDRY_HOME']) {
    const root = process.env[rootEnv];
    if (root) push(path.join(root, 'foundry', 'triage', name));
  }
  // Sibling monorepo layouts (author machine common)
  push(path.join(TRIO_ROOT, '..', 'Skill Foundry', 'foundry', 'triage', name));
  push(path.join(TRIO_ROOT, '..', 'Skill-Foundry', 'foundry', 'triage', name));
  push(path.join(TRIO_ROOT, 'vendor', 'foundry-triage', name));
  // Skills-only / clean-ship package: drivers live next to skills; triage under
  // bundled-skills/foundry/triage (vendored by vendor_skills.vendor_trio_runtime_support).
  // When this file is at <bundle>/drivers/foundry-triage-resolve.mjs:
  push(path.join(HERE, '..', 'foundry', 'triage', name));
  push(path.join(TRIO_ROOT, 'foundry', 'triage', name));
  // When engines run from skills/foreman/bin with cwd package root:
  push(path.join(process.cwd(), 'vendor', 'bundled-skills', 'foundry', 'triage', name));
  push(path.join(process.cwd(), 'skills', 'foundry', 'triage', name));
  push(path.join(process.cwd(), 'foundry', 'triage', name));

  for (const c of candidates) {
    try {
      if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
    } catch { /* */ }
  }
  throw new Error(
    `@foundry/triage/${name} not found. Set ANCHOR_FOUNDRY_DIR or FOUNDRY_TRIAGE_DIR ` +
    `to the Skill Foundry root (or foundry/triage directory). Searched ${candidates.length} candidates.`,
  );
}

/** @param {string} file @returns {string} file:// URL for import() */
export function resolveFoundryTriageHref(file) {
  return pathToFileURL(resolveFoundryTriagePath(file)).href;
}

/**
 * Dynamic-import a triage wire module.
 * @param {string} file
 * @returns {Promise<Record<string, unknown>>}
 */
export async function importFoundryTriage(file) {
  const href = resolveFoundryTriageHref(file);
  return import(href);
}

export default {
  resolveFoundryTriagePath,
  resolveFoundryTriageHref,
  importFoundryTriage,
};

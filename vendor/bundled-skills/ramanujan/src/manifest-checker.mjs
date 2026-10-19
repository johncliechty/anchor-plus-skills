// Wave 1 — SKILL.md manifest checker.
//
// The skill manifest (SKILL.md) is the human/agent-facing contract for Ramanujan.
// This checker is the machine gate the Wave-1 done-when names: it confirms SKILL.md
// exists and names all six pillars + THE HONESTY LAW. It is intentionally small and
// dependency-free so it can run on a fresh checkout (`node --test test/`) and as a CLI.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** The six pillars of Ramanujan, in North-Star order. */
export const PILLARS = Object.freeze([
  'Understand',
  'Solve',
  'Verify',
  'Dialogue',
  'Formalize',
  'Contextualize',
]);

/** The governing invariant the manifest must name. */
export const HONESTY_LAW = 'Honesty Law';

/** Default location of the skill manifest (repo root, one level up from src/). */
export const DEFAULT_SKILL_PATH = path.join(__dirname, '..', 'SKILL.md');

/**
 * Check raw manifest CONTENT (no filesystem). Returns { ok, missing } where `missing`
 * is the list of required tokens (pillar names and/or the Honesty Law) not found.
 * Matching is case-insensitive and word-boundary anchored so a substring (e.g. a
 * pillar name buried inside another word) does not produce a false positive.
 */
export function checkManifestContent(content) {
  if (typeof content !== 'string') {
    throw new TypeError('checkManifestContent expects a string');
  }
  const missing = [];
  for (const pillar of PILLARS) {
    if (!new RegExp(`\\b${pillar}\\b`, 'i').test(content)) missing.push(pillar);
  }
  if (!new RegExp(`\\b${HONESTY_LAW}\\b`, 'i').test(content)) missing.push(HONESTY_LAW);
  return { ok: missing.length === 0, missing };
}

/**
 * Check the SKILL.md file at `skillPath` (defaults to the repo-root SKILL.md).
 * Returns { ok, missing, path }. A missing file is itself a failure (ok=false).
 */
export function checkManifest(skillPath = DEFAULT_SKILL_PATH) {
  if (!fs.existsSync(skillPath)) {
    return { ok: false, missing: [`SKILL.md (file not found at ${skillPath})`], path: skillPath };
  }
  const content = fs.readFileSync(skillPath, 'utf8');
  return { ...checkManifestContent(content), path: skillPath };
}

// CLI entry point: exit 0 when the manifest passes, non-zero (naming the gaps) otherwise.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = checkManifest(process.argv[2]);
  if (result.ok) {
    console.log(`OK: ${result.path} names all six pillars + THE HONESTY LAW.`);
    process.exit(0);
  } else {
    console.error(`FAIL: ${result.path} is missing: ${result.missing.join(', ')}`);
    process.exit(1);
  }
}

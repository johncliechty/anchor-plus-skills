/**
 * Privacy scaffold — W1.
 *
 * Packs are SHAREABLE; calibration passages (John's own prose used to
 * calibrate the voice guard) are PRIVATE and live in the project roots or
 * profiles/, never in a pack. Any file carrying the CALIBRATION-PASSAGE
 * marker inside a pack folder fails the marker-scan test, which names it.
 * profiles/ and calibration/ are .gitignored in this skill folder.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const LIB_DIR = path.dirname(fileURLToPath(import.meta.url));
export const DEFAULT_PACKS_DIR = path.join(LIB_DIR, '..', 'packs');

export const CALIBRATION_MARKER = 'CALIBRATION-PASSAGE';

/** Scan every file under a packs dir for the marker → findings [{file}]. */
export function scanPacksForMarker(packsDir = DEFAULT_PACKS_DIR) {
  const findings = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const abs = path.join(dir, e.name);
      if (e.isDirectory()) walk(abs);
      else if (e.isFile()) {
        let text;
        try {
          text = fs.readFileSync(abs, 'utf8');
        } catch {
          continue;
        }
        if (text.includes(CALIBRATION_MARKER)) {
          findings.push({ file: path.relative(packsDir, abs).replace(/\\/g, '/') });
        }
      }
    }
  };
  walk(packsDir);
  return findings;
}

/**
 * List non-sample files under a repo's .git/hooks — the no-git-hooks gate
 * asserts this is EMPTY for every repository the build touched.
 */
export function listGitHooks(repoRoot) {
  const hooksDir = path.join(repoRoot, '.git', 'hooks');
  let entries = [];
  try {
    entries = fs.readdirSync(hooksDir);
  } catch {
    return [];
  }
  return entries.filter((f) => !f.endsWith('.sample'));
}

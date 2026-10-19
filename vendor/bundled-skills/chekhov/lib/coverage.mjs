/**
 * lib/coverage.mjs — the T0 coverage section of the lint report (W2).
 *
 * Every unmigrated docx is named by the REPORT, never by a debt file: this
 * section lists every docx in a root with no *_source.md beside it, and lists
 * the JS bible generators as FROZEN (kept, not run). It REPLACES the cut
 * MIGRATION-DEBT.md — there is no hand-kept copy to rot.
 *
 * Coverage is INFORMATIONAL: it never fails the lint (exit stays 0).
 *
 * A docx whose canonical markdown carries a DIFFERENT name (the plan keeps
 * Series_Bible_v4.2_source.md as canonical for Series_Bible_v4.2_Extended.docx)
 * is covered through the root's chekhov/manifest.json: any docx recorded there
 * as a canonical entry's source_docx is migrated, whatever its sibling names.
 */
import fs from 'node:fs';
import path from 'node:path';
import { sourcePathFor } from './migrate.mjs';

const SKIP_DIRS = new Set(['.git', 'node_modules', 'chekhov', '.claude', '.snapshots', '.anchor', '.foreman']);

/** Basenames like bible_v04_generator.js — the frozen Word-bible generators. */
const GENERATOR_RE = /generator[^/\\]*\.js$/i;

function coveredDocxRels(root) {
  const covered = new Set();
  try {
    const doc = JSON.parse(fs.readFileSync(path.join(root, 'chekhov', 'manifest.json'), 'utf8'));
    for (const entry of doc.canonical || []) {
      if (entry.source_docx) covered.add(String(entry.source_docx).replace(/\\/g, '/'));
    }
  } catch {
    /* no manifest yet: only the beside-the-docx rule applies */
  }
  return covered;
}

/**
 * Walk one root → { unmigrated_docx: [rel...], generators_frozen: [{rel,
 * status, note}...] }, both sorted. Reads only; runs nothing.
 */
export function coverageForRoot(root) {
  const covered = coveredDocxRels(root);
  const unmigrated = [];
  const generators = [];
  const walk = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const abs = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (!SKIP_DIRS.has(e.name)) walk(abs);
        continue;
      }
      if (!e.isFile()) continue;
      const rel = path.relative(root, abs).replace(/\\/g, '/');
      if (/\.docx$/i.test(e.name)) {
        if (!fs.existsSync(sourcePathFor(abs)) && !covered.has(rel)) unmigrated.push(rel);
      } else if (GENERATOR_RE.test(e.name)) {
        generators.push({ rel, status: 'FROZEN', note: 'kept, not run' });
      }
    }
  };
  walk(root);
  unmigrated.sort();
  generators.sort((a, b) => (a.rel < b.rel ? -1 : 1));
  return { unmigrated_docx: unmigrated, generators_frozen: generators };
}

// drivers/canonical-scan.mjs — SR-2 canonical-tree guard (Phase 1.1 done-when a+b).
//
// Statically proves that NO production import specifier escapes the canonical trio tree
// (no `fil<path> archive import, no absolute drive/POSIX path). ESM
// specifiers are static, so a whole-tree specifier scan IS the runtime resolution
// property: with the archive dirs renamed/removed, zero imports could resolve outside
// `<path> This is the assertion registered in the Phase-0.4 gate-inventory
// manifest so the run-live.mjs:129 regression window stays closed across Phases 3-5.

import fs from 'node:fs';
import path from 'node:path';

// `test` is skipped: engine entrypoints never import from test/ , and test-fixture
// strings (the RED-probe samples) must not trip the whole-tree scan.
const SKIP_DIRS = new Set(['node_modules', '.git', '.foreman', 'test']);
const CODE_EXT = new Set(['.mjs', '.js']);

/**
 * True iff `spec` is an ABSOLUTE / archive specifier that would resolve outside the
 * canonical tree. Relative (`./`, `../`) and bare (`node:fs`, package) specifiers stay
 * in-tree and return false.
 * @param {*} spec
 * @returns {boolean}
 */
export function isEscapingSpecifier(spec) {
  if (typeof spec !== 'string' || !spec) return false;
  if (/^file:\/\//i.test(spec)) return true;     // file:// URL (the archive-import form)
  if (/^[A-Za-z]:[\\/]/.test(spec)) return true;  // Windows absolute (C:\ or C:/)
  if (spec.startsWith('/') || spec.startsWith('\\')) return true; // POSIX / UNC absolute
  return false;
}

const IMPORT_RES = [
  /\bfrom\s*['"]([^'"]+)['"]/g,           // import ... from '...'
  /\bimport\s*['"]([^'"]+)['"]/g,          // side-effect import '...'
  /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g,    // dynamic import('...')
  /\brequire\(\s*['"]([^'"]+)['"]\s*\)/g,   // require('...')
];

/** Extract every string-literal import/require specifier from JS source. */
export function extractSpecifiers(src) {
  const found = [];
  for (const re of IMPORT_RES) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(src))) found.push(m[1]);
  }
  return found;
}

/**
 * Walk `rootDir` and return every escaping import found in production code.
 * @param {string} rootDir
 * @returns {{file:string, spec:string}[]}  empty array === GREEN (no escapes)
 */
export function scanTreeForEscapes(rootDir) {
  const escapes = [];
  const walk = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      if (ent.isDirectory()) {
        if (!SKIP_DIRS.has(ent.name)) walk(path.join(dir, ent.name));
      } else if (CODE_EXT.has(path.extname(ent.name))) {
        const file = path.join(dir, ent.name);
        for (const spec of extractSpecifiers(fs.readFileSync(file, 'utf8'))) {
          if (isEscapingSpecifier(spec)) escapes.push({ file, spec });
        }
      }
    }
  };
  walk(rootDir);
  return escapes;
}
